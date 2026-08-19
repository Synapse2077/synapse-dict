#!/usr/bin/env python3
"""意语版的**词组子条目**：一半归还给那个词条，一半进搭配表。2026-08-16。

═══ 是什么 ═══
意语版把词组写成母词条下的子条目，形如 `词组: 定义`：

    informatica  →  `ingegneria informatica: ramo dell'ingegneria che progetta…`
    leone        →  `leone marino: nome comune di alcune specie di mammiferi…`
    tempo        →  `tempo di reazione: lasso temporale che trascorre…`

这条定义讲的是**词组**，不是词头。2026-08-16 建 `finish_it_defs.subentry()` 时
把它们从义项层拦下了（393 条），拦下之后要给它们找个正确的家 ——
`ship-dont-measure-in-circles`：**要么修要么记账，不许只是量清楚**。

═══ 两半，去处不同 ═══
    A  88 条：**词组本身就是我们库里的词形** —— `ingegneria informatica`、
       `persona giuridica`、`anno bisestile` 都是独立词条。
       ⇒ 把证据行的 `word_id` 改指到那个词条，`finish_it_defs` 下一轮就会正常裁决它。
       这不是搬运，是**归还**：定义本来就是那个词的。
    B 305 条：词组不在库里（`leone d'America`、`curva del cane`）。
       ⇒ 进 `collocation`（`move_pseudo_senses_to_colloc` 给已发布的那 377 条选的同一个家）。

⚠️ A 里有 2 条目标词条已经有同一条释义/证据了，跳过（源头两处重复收录）。

═══ 与 `move_pseudo_senses_to_colloc` 的分工 ═══
那个脚本处理**已经发布成义项**的伪义项（377 条，隐藏 + 搬走）。
本脚本处理**从没发布过**的证据行（`sense_src.sense_id IS NULL`）——
它扫的是 `sense_gloss`，永远看不到这批。两者判据不同但归宿相同。

用法（在 it/ 目录下）：
    python3 fixes/reroute_subentry_defs.py                  # 两半都看
    python3 fixes/reroute_subentry_defs.py --apply          # 只做 A（确定性、不花钱）
    python3 fixes/reroute_subentry_defs.py --run            # 给 B 翻中文
    python3 fixes/reroute_subentry_defs.py --apply-colloc   # 落 B
    python3 fixes/reroute_subentry_defs.py --verify
    python3 fixes/reroute_subentry_defs.py --mutate
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool   # noqa: E402
import paths    # noqa: E402
import translate_it_defs as T   # noqa: E402  复用可续传跑批器
from finish_it_defs import subentry   # noqa: E402  判据唯一的家，10/10 变异验过
from promote_it_gloss import PTR      # noqa: E402
from strip_it_placeholder import clean, not_a_definition   # noqa: E402

OUT = paths.WORK / "subentry_colloc_zh.jsonl"
SRC_TAG = "it-edition:subentry"

SYS = """你是意大利语—中文词典编纂员。输入是意大利语**词组**及其意语释义。
给出这个词组的中文说法。

规则：
1. 写这个词组**指的那个东西**在中文里的说法，读者拿它替换句子里的这个词组，意思应当成立。
   `leone marino: nome comune di alcune specie di mammiferi…` → `海狮`
2. 有通行中文名的用通行名（生物、化学、法律、地理术语尤其要用）
3. 不要写"关于这个词组"的话（"指…""表示…""该词组…"）
4. 释义里有区分信息、不写就会跟别的词混时，写在括号里，括号内不限长度
5. 句末不加任何标点
6. 你读不懂或无法确定时，`zh` 给空字符串 ""，**不要猜**

输入是 JSON 数组，每项有 `id`、`word`（词组）、`it`（意语释义）。
输出**只有** JSON 数组，每项 {"id": 原样, "zh": "中文"}。不要围栏、不要解释。"""


def split(con):
    """→ (A 归还的 [(xid, 目标wid, 词组, 定义)], B 进搭配的 [(xid, 母wid, 母词, 词组, 定义)], 统计)"""
    wid_of = {}
    for i, w in con.execute("SELECT id, word FROM dict ORDER BY id"):
        wid_of.setdefault(w, i)
    back, colloc, st = [], [], Counter()
    for xid, wid, w, t in con.execute(
            "SELECT x.id, x.word_id, d.word, x.text FROM sense_src x "
            "JOIN dict d ON d.id=x.word_id "
            "WHERE x.src='it-edition' AND x.sense_id IS NULL ORDER BY x.id"):
        if not_a_definition(t) or PTR.match(t):
            continue
        sub = subentry(t, w)
        if not sub:
            continue
        phrase, body = sub
        tgt = wid_of.get(phrase)
        if tgt is None:
            colloc.append((xid, wid, w, phrase, clean(body)))
            st["B 词组不在库里 ⇒ 进 collocation"] += 1
            continue
        # 目标词条已经有同一条释义或同一条证据 ⇒ 源头重复收录，跳过
        if con.execute(
                "SELECT 1 FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
                "WHERE s.word_id=? AND g.lang='it' AND g.kind='definition' AND g.text=?",
                (tgt, clean(body))).fetchone() or con.execute(
                "SELECT 1 FROM sense_src WHERE word_id=? AND text=?", (tgt, body)).fetchone():
            st["⚠️ 目标词条已有同一条，跳过（源头重复收录）"] += 1
            continue
        back.append((xid, tgt, phrase, clean(body)))
        st["A 词组本身是词条 ⇒ 归还给它"] += 1
    return back, colloc, st


def load_zh():
    got = {}
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                x = json.loads(line)
                zh = (x.get("zh") or "").strip().rstrip("。.")
                if zh:
                    got[int(x["id"])] = zh
            except Exception:
                continue
    return got


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    back, colloc, _ = split(con)
    # ⚠️ 证据行**不标记已搬走**（`move_pseudo_senses_to_colloc` 同样如此：搭配表里
    #    没有指回 sense_src 的字段）。所以 B 半的判据不能是「split 后为空」——
    #    那永远做不到。正确判据是「每条 B 都已经在 collocation 里有对应行」。
    done = {(w, t) for w, t in con.execute(
        "SELECT k.word_id, k.text FROM collocation k JOIN collocation_gloss g "
        "ON g.collocation_id=k.id AND g.src=?", (SRC_TAG,))}
    left_b = [x for x in colloc if (x[1], x[3]) not in done]
    # 归还过的：凡是文本形如 `X: …` 且 X 是库里词形的证据，其 word_id 必须就是 X
    wid_of = {}
    for i, w in con.execute("SELECT id, word FROM dict ORDER BY id"):
        wid_of.setdefault(w, i)
    misplaced = 0
    for wid, t in con.execute(
            "SELECT word_id, text FROM sense_src WHERE src='it-edition' AND sense_id IS NULL"):
        # ⚠️ 必须先确认**真的有冒号**：`split(":")` 在没有冒号时返回整串，
        #    `elefante`（单词释义）就会被当成"冒号前是 elefante"而误报（165 条假阳性）。
        if ":" not in (t or ""):
            continue
        head = t.split(":", 1)[0].strip()
        if head and head in wid_of and wid_of[head] != wid:
            misplaced += 1
    checks = [
        ("🔴 没有还能归还却没归还的（A）", len(back), 0),
        # 🔴 已接受基线 1 + 理由：`homo` 那条是**源头散文**（用法说明里恰好有冒号），
        #    `subentry()` 把它误当成词组子条目，模型按 prompt 规则 6 正确地返回了空串。
        #    判据已经收窄过两轮（A4：三轮停手），这一条按上界记账。
        ("每条 B 都已在 collocation 里落地（基线 1，源头散文）", len(left_b), 1),
        # 🔴 已接受基线 2 + 理由：`sicurezza informatica` / `motore termico` ——
        #    目标词条已有逐字相同的释义，`split()` 故意跳过（源头两处重复收录）。
        ("`X: …` 的证据挂在 X 自己词形下（基线 2，源头重复）", misplaced, 2),
        ("🔴 本步搬进搭配的都带中文",
         q("SELECT count(*) FROM collocation k WHERE EXISTS("
           "SELECT 1 FROM collocation_gloss g WHERE g.collocation_id=k.id AND g.src=?) "
           "AND NOT EXISTS(SELECT 1 FROM collocation_gloss g WHERE g.collocation_id=k.id "
           "AND g.lang='zh')", SRC_TAG), 0),
        ("🔴 本步搬进搭配的都带意语原文",
         q("SELECT count(*) FROM collocation k WHERE EXISTS("
           "SELECT 1 FROM collocation_gloss g WHERE g.collocation_id=k.id AND g.src=?) "
           "AND NOT EXISTS(SELECT 1 FROM collocation_gloss g WHERE g.collocation_id=k.id "
           "AND g.lang='it')", SRC_TAG), 0),
        ("搭配表 rank 在每个词内不重复",
         q("SELECT count(*) FROM (SELECT word_id, rank FROM collocation "
           "GROUP BY 1,2 HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-42s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def mutate():
    """判据的家在 `finish_it_defs.subentry`，那边已 10/10 验过；这里验本步的分流。"""
    print("\n═══ 变异验证：分流判据 ═══")
    cases = [
        ("词组含词头且不等于词头 ⇒ 是子条目",
         subentry("leone marino: nome comune di mammiferi", "leone") is not None, True),
        ("词头 + 同位语 ⇒ 不是子条目",
         subentry("verde oliva, colore RAL – codice RAL: RAL 6003", "verde oliva") is None, True),
        ("普通释义 ⇒ 不是子条目",
         subentry("persona scontrosa e poco socievole", "misantropo") is None, True),
        ("撇号是词边界（sott'olio 里的 olio 算）",
         subentry("sott'olio e sott'aceto: prodotti conservati", "olio") is not None, True),
        ("🔴 子串不算（ora 不在 temporale 里）",
         subentry("con senso temporale: in questo momento", "ora") is None, True),
    ]
    ok = True
    for name, got, want in cases:
        ok &= got == want
        print("   %s %s" % ("✅" if got == want else "🔴", name))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "run", "apply-colloc", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true", dest=f.replace("-", "_"))
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    back, colloc, st = split(ro)
    for k, v in st.most_common():
        print("   %-42s %7s" % (k, f"{v:,}"))

    if a.run:
        items = [{"id": xid, "word": ph, "it": body} for xid, _w, _mw, ph, body in colloc]
        print("\n■ 给 %s 个词组翻中文" % f"{len(items):,}")
        T.SYS, T.CHUNK = SYS, 20
        OUT.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(T.run_batches(items, OUT))
        return 0

    if a.apply_colloc:
        zh = load_zh()
        mx = dict(ro.execute("SELECT word_id, max(rank) FROM collocation GROUP BY word_id"))
        seen = set()
        krows, grows, skip = [], [], 0
        for xid, wid, _mw, ph, body in colloc:
            if xid not in zh or (wid, ph) in seen:
                skip += 1
                continue
            seen.add((wid, ph))
            mx[wid] = mx.get(wid, 0) + 1
            krows.append((wid, ph, mx[wid], xid, body, zh[xid]))
        print("\n■ 将新增搭配 %s 条（没拿到中文/本轮重复 跳过 %s）"
              % (f"{len(krows):,}", f"{skip:,}"))
        for wid, ph, rk, _x, body, z in krows[:10]:
            print("   %-26s %-16s ← %s" % (ph[:26], z[:16], body[:40]))
        ro.close()
        if not krows:
            return 0
        with dbtool.session("subentry-to-colloc",
                            expect={"#collocation": len(krows),
                                    "#collocation_gloss": 2 * len(krows)}) as s:
            for wid, ph, rk, _x, body, z in krows:
                cur = s.execute("INSERT INTO collocation (word_id, sense_id, text, rank) "
                                "VALUES (?, NULL, ?, ?)", (wid, ph, rk))
                cid = cur.lastrowid
                grows += [(cid, "zh", z, SRC_TAG), (cid, "it", body, SRC_TAG)]
            s.executemany("INSERT INTO collocation_gloss (collocation_id, lang, text, src) "
                          "VALUES (?,?,?,?)", grows)
        print("\n■ 已新增搭配 %s 条" % f"{len(krows):,}")
        return 0

    print("\n■ A 归还给词组自己的词条 %s 条" % f"{len(back):,}")
    for _x, _t, ph, body in back[:10]:
        print("   %-26s %s" % (ph[:26], body[:52]))
    print("\n■ B 进 collocation %s 条（需先 --run 翻中文）" % f"{len(colloc):,}")
    for _x, _w, mw, ph, body in colloc[:6]:
        print("   %-26s（%s 的搭配） %s" % (ph[:26], mw[:12], body[:36]))
    ro.close()
    if not a.apply or not back:
        print("\n(未加 --apply，不写库)" if not a.apply else "")
        return 0
    with dbtool.session("reroute-subentry", expect={"#sense_src": 0}) as s:
        s.executemany("UPDATE sense_src SET word_id=? WHERE id=?",
                      [(tgt, xid) for xid, tgt, _p, _b in back])
    print("\n■ 已归还 %s 条（下一轮 finish_it_defs 会正常裁决它们）" % f"{len(back):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
