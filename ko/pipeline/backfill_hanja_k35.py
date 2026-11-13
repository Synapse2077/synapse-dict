#!/usr/bin/env python3
"""K35：构词表里的汉字形，补进**还没有任何汉字形**的谚文词的 `hanja_spelling`。2026-11-07。

═══ 来源 ═══
K33（2026-09-27）把汉字词条页「例句」区里的构词表迁成了关系边：`珠` 页的 `珠算/주산` ⇒
`sense_relation(kind='derived', writer='reclass_nonexamples', target='珠算/주산')`。
每条给出一对 (汉字形 H, 谚文词 K)。「零信息损失」那一步只保证了**链接**不丢，
没有把 H 记到 K 自己身上 —— 读者点进 `구비` 看不到 `口碑`。

═══ 四类（2026-11-07 实测，与 09-27 账上的数不同，见 KO_PLAN K35）═══
边 2,305 条 ⇒ 去重对子 2,203：
    一致 1,972   K 已有汉字形且含 H（已记值里的 `交付/交附` 按斜杠拆开再比）
    碰撞   150   K 已有汉字形但不含 H —— 绝大多数是**同形异义**（`대위` 大尉 vs 代位、`고사` 故事/告辭…），
                 少数是源头写错（`수검`←`收斂`，斂 读 렴）⇒ **一条都不收**，理由见下
    空白    76   K 在 dict、一个汉字形都没有        ⇒ **本脚本收的就是这一批**
    无词     5   K 不在 dict
⭐ 源头可信度下界 一致/(一致＋碰撞) = 92.93%（碰撞里大半是真同形异义，所以是下界）。

═══ 收之前的两道筛 ═══
① **逐字读音核对**（`reading_check`）：H 与 K 等长，且 H 的每个字在 `hanja_reading` 里的读音
   （含头音法则变体）等于 K 对应位置的音节。在「一致」那批上验：1,737 通过／8 读音对不上（全是不规则读法
   `契丹 거란`／`松茸 송이`／`盟誓 맹세` —— 检查器偏严，宁可错拦不错放）／227 有字不在读音表。
   碰撞里它逮到 `收斂/수검`、`辦出/변출` 两条源头错字。空白 76 条：66 通过、0 对不上、10 有字不在读音表。
② **人工读**：读音表查不到字的 10 条逐条读过，全对 ⇒ 登记在 `READ_BY_HUMAN`；
   同音错字读音核对抓不到 ⇒ 76 条逐条读过，判掉 1 条 ⇒ `ADJUDICATED_REJECT`。

═══ 为什么碰撞的 150 条不收（什么会推翻）═══
`hanja_spelling` 是**词级**的（`sense_id` 全为 NULL）。`부정` 已记着 不定/不正/不貞/否定，源头这里给 `不精`
—— 那是**又一个**同音词，挂在词上读者分不出它对应哪条义项。正确的家是**义项级**的汉字表记，
而那是 K20（谚文页是词形不是词）要先回答的结构问题。⇒ 推翻条件：K20 定下义项级汉字表记的结构。

用法（在仓库根）：
    python3 -u ko/pipeline/backfill_hanja_k35.py            # 干跑（四类计数＋读音核对＋要收的清单）
    python3 -u ko/pipeline/backfill_hanja_k35.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import re
import sqlite3

import dbtool
import paths
import relation_writers
import resolve_relation_targets as R   # 落点解析判据：import，不重写

WRITER = relation_writers.name(__file__)
f = lambda n: format(n, ",")

HAN = re.compile(r"^[㐀-䶿一-鿿豈-﫿]+$")
HANGUL = re.compile(r"^[가-힣]+$")
YI = {2, 3, 6, 7, 12, 17, 20}          # ㅑㅒㅕㅖㅛㅠㅣ

# 读音表里查不到字、人工逐条读过确认无误的（2026-11-07）
READ_BY_HUMAN = {
    ("徵稅", "징세"), ("懷孕", "회잉"), ("懷爐", "회로"), ("排布", "배포"), ("甘言利說", "감언이설"),
    ("矜持", "긍지"), ("虛實", "허실"), ("虛張聲勢", "허장성세"), ("虛無", "허무"), ("麻布", "마포"),
}
# 人工判掉的（读音核对抓不到的同音错字）
ADJUDICATED_REJECT = {
    ("一日虐", "일일학"): "源头错字：正字 一日瘧（间日疟），虐／瘧 同读 학，逐字读音核对抓不到",
}


def pairs_and_edges(con):
    """→ ({(H,K): (src, src_ref) 取 id 最小的那条边}, 形状不对的条数, 边数)"""
    out, odd, n = {}, 0, 0
    for i, t, src, ref in con.execute(
            "SELECT id, target, src, src_ref FROM sense_relation "
            "WHERE writer='reclass_nonexamples' AND kind='derived' ORDER BY id"):
        if "/" not in t:
            continue
        h, k = [x.strip() for x in t.split("/", 1)]
        if HAN.match(h) and HANGUL.match(k):
            n += 1
            out.setdefault((h, k), (src, ref))
        else:
            odd += 1
    return out, odd, n


def existing_hanja(con):
    """→ {谚文词: 已记的汉字形集合}（`entry.hanja` ∪ 可见的 hanja_spelling/alt_hanja/hanja_form_of；斜杠并列拆开）"""
    have = collections.defaultdict(set)
    for w, h in con.execute("SELECT d.word, e.hanja FROM entry e JOIN dict d ON d.id=e.word_id "
                            "WHERE e.hanja IS NOT NULL AND e.hanja<>''"):
        have[w].update(x.strip() for x in h.split("/") if x.strip())
    for w, t in con.execute("SELECT d.word, r.target FROM sense_relation r JOIN dict d ON d.id=r.word_id "
                            "WHERE r.kind IN ('hanja_spelling','alt_hanja','hanja_form_of') "
                            "AND COALESCE(r.hidden,0)=0"):
        have[w].update(x.strip() for x in t.split("/") if x.strip())
    return have


def classify(con):
    pairs, odd, n = pairs_and_edges(con)
    wid = {}
    for i, w in con.execute("SELECT id, word FROM dict ORDER BY id"):
        wid.setdefault(w, i)
    have = existing_hanja(con)
    cat = collections.defaultdict(list)
    for (h, k) in sorted(pairs):
        if k not in wid:
            cat["无词"].append((h, k))
        elif not have.get(k):
            cat["空白"].append((h, k))
        elif h in have[k]:
            cat["一致"].append((h, k))
        else:
            cat["碰撞"].append((h, k))
    return cat, pairs, wid, odd, n


def _dueum(syl):
    """头音法则变体（宽口径：任意位置都放过 —— 宁可漏报读音错，不误拦真词）。"""
    c = ord(syl) - 0xAC00
    if not 0 <= c < 11172:
        return {syl}
    ini, med, fin = c // 588, (c % 588) // 28, c % 28
    out = {syl}
    mk = lambda i: chr(0xAC00 + (i * 21 + med) * 28 + fin)
    if ini == 5:                        # ㄹ → ㅇ（yi 前）／ㄴ
        out.add(mk(11 if med in YI else 2))
    if ini == 2 and med in YI:          # ㄴ → ㅇ（yi 前）
        out.add(mk(11))
    return out


def reading_check(con):
    rd = collections.defaultdict(set)
    for h, w in con.execute("SELECT r.hanja, d.word FROM hanja_reading r JOIN dict d ON d.id=r.word_id"):
        rd[h] |= _dueum(w)

    def judge(h, k):
        if len(h) != len(k):
            return "长度不等"
        for a, b in zip(h, k):
            if a not in rd:
                return "有字查不到读音"
            if b not in rd[a]:
                return "读音对不上"
        return "通过"
    return judge


def plan(con):
    """→ (要收的 [(word_id, H, src, src_ref)], 报告)。判据只在这里。"""
    cat, pairs, wid, odd, n = classify(con)
    judge = reading_check(con)
    take, why_not = [], collections.Counter()
    for h, k in cat["空白"]:
        if (h, k) in ADJUDICATED_REJECT:
            why_not["人工判掉（同音错字）"] += 1
            continue
        v = judge(h, k)
        if v == "通过" or (v == "有字查不到读音" and (h, k) in READ_BY_HUMAN):
            src, ref = pairs[(h, k)]
            take.append((wid[k], h, src, ref + "#k35"))
        else:
            why_not["读音核对：" + v] += 1
    return take, cat, judge, why_not, odd, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    take, cat, judge, why_not, odd, n = plan(con)
    print("■ 构词表边 %s 条 ⇒ 去重对子 %s（形状不对跳过 %s）"
          % (f(n), f(sum(len(v) for v in cat.values())), f(odd)))
    for c in ("一致", "碰撞", "空白", "无词"):
        rc = collections.Counter(judge(h, k) for h, k in cat[c]) if c != "无词" else {}
        print("   %-4s %5s   逐字读音：%s" % (c, f(len(cat[c])), dict(rc)))
    a1, b1 = len(cat["一致"]), len(cat["碰撞"])
    print("■ 源头可信度下界 %.2f%%" % (100.0 * a1 / max(a1 + b1, 1)))
    print("■ 碰撞里读音对不上的（源头写错字）：%s"
          % [x for x in cat["碰撞"] if judge(*x) == "读音对不上"])
    print("■ 要收 %s 条 ／ 不收 %s" % (f(len(take)), dict(why_not)))
    have_norm = {w for w, in con.execute("SELECT word_norm FROM dict")}
    rows = []
    for wid_, h, src, ref in take:
        tn, _how = R.resolve(h, have_norm)
        rows.append((wid_, h, src, ref, tn))
    dup = con.execute("SELECT COUNT(*) FROM sense_relation WHERE src_ref IN (%s)"
                      % ",".join("?" * len(rows)), [r[3] for r in rows]).fetchone()[0] if rows else 0
    n_before = con.execute("SELECT COUNT(*) FROM sense_relation WHERE kind='hanja_spelling'").fetchone()[0]
    con.close()
    if dup:
        raise SystemExit("🔴 src_ref 已存在 %d 条 —— 已经跑过？" % dup)
    if not a.apply:
        print("（干跑。加 --apply 才写库）")
        return 0
    n_tn = sum(1 for r in rows if r[4])
    with dbtool.session("ko-k35-hanja-spelling",
                        expect={"#sense_relation": len(rows),
                                "sense_relation.target": len(rows),
                                "sense_relation.writer": len(rows),
                                "sense_relation.target_norm": n_tn},
                        invalidates=[]) as s:
        s.executemany(
            "INSERT INTO sense_relation"
            " (word_id, sense_id, kind, target, tags, hidden, src, src_ref, target_norm, writer)"
            " VALUES (?, NULL, 'hanja_spelling', ?, NULL, 0, ?, ?, ?, '%s')" % WRITER, rows)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n_after = con.execute("SELECT COUNT(*) FROM sense_relation WHERE kind='hanja_spelling'").fetchone()[0]
    left = len(classify(con)[0]["空白"])
    con.close()
    print("■ 写后：hanja_spelling %s → %s（应 +%s）；空白剩 %s（应 = 不收的 %s）"
          % (f(n_before), f(n_after), f(len(rows)), f(left), sum(why_not.values())))
    return 0 if (n_after - n_before == len(rows) and left == sum(why_not.values())) else 1


if __name__ == "__main__":
    _sys.exit(main())
