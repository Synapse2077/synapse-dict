#!/usr/bin/env python3
"""同一词形下中文逐字相同的义项 —— 按源头的区分信息补出括注。2026-08-19。

═══ 规则怎么定的（两家顾问 + 我回数据裁决）═══
2026-08-19 就这批同时问了 v4-pro 与豆包 pro（各一次，开思考）。**核心模板两家一致**：

    主名（能区分的最小信息）      括号外是对应词、括号内是区分信息

三处分歧我自己裁的，理由都不是"谁更权威"：

① **法国省名带不带「省」字** —— v4-pro 说带、豆包说不带。**回我们自己的库验**：
   `Mayenne` 在库里是「马耶讷（法国省份及河流）」、`Aisne` 同样 ——
   **裸名本身有歧义**（同一个名字既是省又是河）。⇒ 带「省」。v4-pro 对。
② **v4-pro 夸「圣莱杰（艾马维尔的村庄）」结构好**，可它同一份答案里又写着
   「不要出现『……的村庄』这种带『的』的区分结构」—— **自相矛盾**。
   ⇒ 按已有约定（地名音译里不出现「的」）去掉。
③ **豆包说「极度生僻、用户查询概率低于 1% 的地名不该动」** —— **驳回**：
   那是 A45 明令禁止的形式代理，而且不可验证。判据只能是
   **「源头有没有可译的区分信息」**：有就补，没有就合并。

═══ 分工：模型只做一件事 ═══
🔴 模型**只回答「这条义项的区分信息是什么」**，源头没给就回 `null`。
   「要不要合并」由**我按返回结果确定性地决定**（一组里全是 null ⇒ 合并）。
   把两件事塞进一次调用，控制组就得同时验两个字段（A47 的代价记着呢）。

═══ 输入只喂被判断的那个字段 ═══
⚠️ `context-you-give-leaks-into-output`：给模型的"仅供参考"会直接漏进输出。
   这里只喂 词形 + 每条义项的**源头原文** + 当前中文（当前中文是**主名的来源**，
   必须给，否则模型会重新音译，十条各译一个样）。**不喂任何母地名/上下文**。

用法（在 it/ 目录下）：
    python3 fixes/distinguish_duplicate_zh.py                 # 干跑，出数
    python3 fixes/distinguish_duplicate_zh.py --pilot 20      # 🔴 先跑切片自己读（A47）
    python3 fixes/distinguish_duplicate_zh.py --run           # 跑全量（只写产物文件）
    python3 fixes/distinguish_duplicate_zh.py --apply         # 落库
    python3 fixes/distinguish_duplicate_zh.py --verify
"""
import argparse
import asyncio
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool     # noqa: E402
import ds_batch   # noqa: E402
import paths      # noqa: E402
# 🔴 判据与回归闸 B2 **共用一份**：那条闸查的就是"释义尾部的词性标签与本义项词性相同"。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strip_pos_label_in_gloss import LAB, TAIL   # noqa: E402

f = lambda n: format(n, ",")
OUT = paths.WORK / "dup_zh_out.jsonl"
SRC_TAG = "deepseek-v4-flash:distinguish"

SYS = """你在给一部意大利语→中文词典补「区分信息」。

同一个词形下有几条义项，它们的中文**现在完全一样**，用户看到同一句话重复显示。
你的任务：对每一条义项，只回答**它与同组其他义项的区分信息**。

输出 JSON 对象，键是义项标识号（原样回传，不是序号），值是：
  {"zh": "主名（区分信息）"}      源头给了可区分的信息
  {"zh": null}                    源头没有给任何可区分的信息

规则：
1. **主名照抄当前中文**，不要重新音译。只在后面加中文圆括号写区分信息。
2. 括号里只放**能区分**的最小内容。同组全是同一类型（比如都是市镇）就不要写类别词；
   类型不同（市镇 / 男名 / 河流）才写最低限度的类别词。
3. 法国省、意大利大区这类行政区，**要带「省」「大区」字样**：
   同名的既可能是省也可能是河，不带就还是有歧义。
4. 🔴 括号里**不许出现「的」字结构**。写「（夏朗德省）」不写「（夏朗德省的市镇）」。
5. 🔴 **不许编造源头没有的信息**。源头只说 `(Belgique)` 就只写「（比利时）」，
   不要补造具体省份。
6. 🔴 两条源头如果说的是同一件事（一条英文一条意大利文、或一详一略），
   **两条都回 null** —— 那是重复收录，不是两个义项，不要硬造区别。
   也包括**中文里本来就分不开**的近义：
     `being` / `existence` 中文都是「存在」 ⇒ 两条都回 null。
     **不要**写成「存在（存在物）」「存在（存在状态）」——
     那是为了消除重复而制造的伪差异，比重复更糟：用户会以为真有这个区别。
   判据：**你补的那个括注，中文母语者查词时用得上吗？**用不上就回 null。
7. 整条中文越短越好，但必须与同组其他条互不相同。

只输出 JSON，不要解释。"""


def load_groups(con):
    """→ [{word, zh, items:[{id, src_text}]}]，同一词形下中文逐字相同的组。"""
    out = []
    for w, zh, ids in con.execute(
            "SELECT d.word, g.text, group_concat(s.id) FROM sense s "
            "JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' "
            "AND g.kind='equivalent' AND g.seq=0 "
            "WHERE COALESCE(s.hidden,0)=0 GROUP BY s.word_id, g.text HAVING count(*)>1"):
        items = []
        for sid, in con.execute("SELECT id FROM sense WHERE id IN (%s) ORDER BY rank" % ids):
            en = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='en' "
                             "AND seq=0", (sid,)).fetchone()
            it = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='it' "
                             "AND kind='definition' AND seq=0", (sid,)).fetchone()
            sx = con.execute("SELECT text FROM sense_src WHERE sense_id=? LIMIT 1",
                             (sid,)).fetchone()
            txt = (en or [None])[0] or (it or [None])[0] or (sx or [None])[0] or ""
            pos = con.execute("SELECT pos FROM sense WHERE id=?", (sid,)).fetchone()
            items.append({"id": sid, "src": txt.strip(), "pos": (pos or [None])[0]})
        out.append({"word": w, "zh": zh, "items": items})
    return out


def payload_of(g):
    """一组 → 一条 payload。**只带词形、当前中文、每条的源头原文**。"""
    return {"w": g["word"], "now": g["zh"],
            "senses": [{"n": i["id"], "src": i["src"]} for i in g["items"]]}


# ── 接收端的闸：模型回来的东西要先过这几条，再谈落库 ──────────────────────
BAD_DE = re.compile(r"（[^）]*的[^）]*）")          # 括号里带「的」（规则 4）
HAS_PAREN = re.compile(r"（[^）]+）$")


def check(word, now, zh, pos=None):
    """→ 不合格的理由；合格返回 None。**判据与 prompt 的规则一一对应**。"""
    if zh is None:
        return None
    # 🔴 括注不许就是词性本身。页面**已经按词性分组、组头写着「形容词」**，
    #    再写「米色（形容词）」等于说两遍 —— 而且这正是 `strip_pos_label_in_gloss`
    #    当初修掉的形状，回归闸 B2 会当场报红（2026-08-19 实测逮到我自己写的 6 条）。
    #    ⇒ 组内只靠词性区分的那几组，**本来就不该改**：页面上它们不重复。
    m = TAIL.search(zh or "")
    if m and pos and LAB.get(m.group(1)) == pos:
        return "括注就是词性本身（页面已按词性分组）"
    zh = zh.strip()
    if not zh:
        return "空串"
    if not zh.startswith(now):
        return "主名被改写了（应照抄「%s」）" % now
    if zh == now:
        return "没加任何区分信息"
    if not HAS_PAREN.search(zh):
        return "区分信息没放在末尾的中文括号里"
    if BAD_DE.search(zh):
        return "括号里出现「的」字结构"
    if len(zh) > len(now) + 24:
        return "括号太长（>24 字）"
    return None


def collect():
    """读产物 → {sense_id: zh or None}"""
    got = {}
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if "id" in r:
                got[int(r["id"])] = (r.get("zh") or None)
    return got


def decide(groups, got):
    """→ (要改写的 [(sense_id, zh)], 要合并的 [(留下的 id, [藏的 id])], 统计)

    🔴 「合并」是**我确定性决定的**，不是模型说的：一组里所有义项都回 null
       ⇒ 源头没有任何可区分信息 ⇒ 除第一条外全藏。
    """
    upd, merge, c = [], [], Counter()
    for g in groups:
        ids = [i["id"] for i in g["items"]]
        vals = [got.get(i) for i in ids]
        if all(i in got for i in ids) is False:
            c["模型没答全，跳过"] += 1
            continue
        good, bad = [], []
        pos_of = {i["id"]: i.get("pos") for i in g["items"]}
        for sid, v in zip(ids, vals):
            why = check(g["word"], g["zh"], v, pos_of.get(sid))
            (bad if why else good).append((sid, v, why))
        if bad:
            c["有不合格回答，整组跳过：" + bad[0][2]] += 1
            continue
        vals2 = [v for _s, v, _w in good]
        if all(v is None for v in vals2):
            merge.append((ids[0], ids[1:]))
            c["✅ 合并（源头无区分信息）"] += 1
            continue
        # 🔴 判据是**最终结果互不相同**，不是"每条都得有括注"。
        #    第一版写成「有 null 就整组跳过」，白扔了 27 组：三条里两条补了括注、
        #    一条保持原样，结果照样三条各不相同 —— 那就是达标的。
        #    ⇒ null 的那条按**原中文**参与判重；全部互不相同才落库。
        final = [(sid, v if v is not None else g["zh"]) for sid, v, _w in good]
        texts = [t for _s, t in final]
        if len(set(texts)) != len(texts):
            c["🔴 最终中文仍有重复 ⇒ 跳过"] += 1
            continue
        # 只写**真的改了**的那些（null 那条不用动）
        upd.extend((sid, t) for (sid, t), (_s2, v, _w) in zip(final, good) if v is not None)
        c["✅ 补区分信息"] += 1
    return upd, merge, c


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    left = q("SELECT count(*) FROM (SELECT s.word_id, g.text FROM sense s "
             "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' AND g.kind='equivalent' "
             "AND g.seq=0 WHERE COALESCE(s.hidden,0)=0 GROUP BY s.word_id, g.text "
             "HAVING count(*)>1)")
    checks = [
        # ⚠️ 基线 28（起点 470 → 藏真重复 362 → 补区分/合并后 28）。三个来源：
        #    ① 模型没答全 / 组内口径不一致 / 回答被接收端闸拦下 —— **这一轮没修**，
        #       不是修不了，数字变大就要查（说明又有新的重复冒出来）
        #    ② 3 组是**故意退回**的：`beige`/`fashion`/`nostri` 组内只靠词性区分，
        #       而页面本来就按词性分组、组头写着「形容词」「名词」⇒ 那里不重复，
        #       补括注反而说了两遍（回归闸 B2 当场逮到）
        ("同词形下中文仍然逐字相同的组（基线 28）", left, 28),
        # 🔴 接收端闸：落库的中文一条都不许违反规则 4（括号里带「的」）
        ("🔴 本轮写入的中文里括号带「的」",
         sum(1 for (t,) in con.execute(
             "SELECT text FROM sense_gloss WHERE src=? AND lang='zh'", (SRC_TAG,))
             if BAD_DE.search(t)), 0),
        # 🔴 藏过头的真判据：**既没有可见义项、也没有变形关系**（页面真的一片空白）。
        #    ⚠️ 第一版没有「也没有变形关系」这一条，报 934 —— 其中 909 个页面上有
        #    「变位形式」区块，根本不空白。**尺子错，不是数据错**（A33）。
        #    ⚠️ 基线 25：拿写库前的备份逐个比过，**这一轮一个都没新增**（25 → 25）。
        #    那 25 个词形的义项**中英文全空**（收词收进来了、内容被占位符清理拿光），
        #    放出来只会显示一个空条目，比空白更糟 ⇒ 保持隐藏，记账。
        ("一条可见义项都不剩、也没有变形关系的词形（基线 25）",
         q("SELECT count(*) FROM (SELECT s.word_id FROM sense s GROUP BY s.word_id "
           "HAVING sum(CASE WHEN COALESCE(s.hidden,0)=0 THEN 1 ELSE 0 END)=0 "
           "AND sum(COALESCE(s.hidden,0))>0) t WHERE NOT EXISTS("
           "SELECT 1 FROM inflection i WHERE i.word_id=t.word_id)"), 25),
    ]
    ok = True
    for name, got_, want in checks:
        ok &= got_ == want
        print("   %s %-40s %s (期望 %s)" % ("✅" if got_ == want else "🔴", name, f(got_), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("run", "apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    ap.add_argument("--pilot", type=int, default=0, help="只跑前 N 组（切片自读，A47）")
    ap.add_argument("--retry", action="store_true",
                    help="只补跑「没答全」的组，批调到 2（A66）")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    groups = load_groups(ro)
    ro.close()
    print("■ 待处理 %s 组 / %s 条义项" % (f(len(groups)), f(sum(len(g["items"]) for g in groups))))

    if a.run or a.pilot or a.retry:
        # 🔴 切片要**分层**：第一版直接取前 N 组，20 组里一条地名都没有 ——
        #    而地名正是这批最扎眼的一族。按「源头形状」分三层各取 1/3。
        if a.retry:
            # A66：flash 会**静默丢掉批里的一部分**（不报错、失败 0）。
            # 收敛靠多轮补跑 + 把批调小，判据是**库里还缺多少**，不是日志说跑完了。
            done = set(collect())
            todo = [g for g in groups if not all(i["id"] in done for i in g["items"])]
            print("■ 补跑没答全的 %s 组（批 2）" % f(len(todo)))
        elif a.pilot:
            geo = [g for g in groups if any(re.search(r"\([^)]+\)\.?$", i["src"] or "")
                                            for i in g["items"])]
            ptr = [g for g in groups if g not in geo and ("形式" in g["zh"] or "变体" in g["zh"])]
            rest = [g for g in groups if g not in geo and g not in ptr]
            k = max(1, a.pilot // 3)
            todo = geo[:k] + ptr[:k] + rest[:a.pilot - 2 * k]
        else:
            todo = groups
        # 🔴 `--retry` 用 **B=1**（一次一组）。实测：批 2 时有 12 组连跑 4 轮每次都被丢，
        #    而把同一组**单独送一次就成功**（`mercantile` 正确回 null×2）——
        #    **不是模型拒答，是批量路径丢的**。消融（单条送）是定位这类问题的手法。
        B = 1 if a.retry else 8
        batches, meta = [], []
        for i in range(0, len(todo), B):
            chunk = todo[i:i + B]
            batches.append([payload_of(g) for g in chunk])
            meta.append([(str(x["id"]), x["id"]) for g in chunk for x in g["items"]])
        tok = asyncio.run(ds_batch.run(SYS, batches, meta, OUT, mode="flash", conc=4,
                                       every=1, thinking="disabled"))
        print("■ token %s" % f(tok))

    got = collect()
    print("■ 已拿到答案 %s 条" % f(len(got)))
    upd, merge, c = decide(groups, got)
    for k, v in c.most_common():
        print("   %-40s %s" % (k, f(v)))
    print("■ 要改写 %s 条、合并 %s 组" % (f(len(upd)), f(len(merge))))
    byid = {i["id"]: (g["word"], g["zh"]) for g in groups for i in g["items"]}
    for sid, zh in upd[:20]:
        print("     %-18s 「%s」→「%s」" % (byid[sid][0][:18], byid[sid][1][:14], zh[:34]))
    if not a.apply or not (upd or merge):
        print("\n(未加 --apply，不写库)")
        return 0
    hide = [i for _k, ids in merge for i in ids]
    with dbtool.session("distinguish-duplicate-zh", expect={"__rows__": 0}) as s:
        s.executemany("UPDATE sense_gloss SET text=?, src=? WHERE sense_id=? AND lang='zh' "
                      "AND kind='equivalent' AND seq=0",
                      [(zh, SRC_TAG, sid) for sid, zh in upd])
        if hide:
            s.execute("UPDATE sense SET hidden=1 WHERE id IN (%s)"
                      % ",".join(str(i) for i in hide))
        s.written = len(upd) + len(hide)
    print("\n■ 已改写 %s 条、藏 %s 条" % (f(len(upd)), f(len(hide))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
