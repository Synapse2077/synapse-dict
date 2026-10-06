#!/usr/bin/env python3
"""W17：把**被当例句收进来的关系数据**收进关系层。vi，2026-10-05。

═══ 🔴🔴 这笔账的前提**大半不成立**，是量出来的 ═══
账上写的是「103 条关系元数据，我们没有收进关系层」。2026-10-05 一量：

    103 条
      ▸ **声调范式表** 18 条     `level tone: y` / `high rising: ý`
                                 ——字母条目列它那个元音的六声，属**音标层**不是关系层
      ▸ 其余 85 条解出的目标里：
          ✅ 关系层**早就有了**     83   源头给了两遍（规范的 `coordinate_terms`
                                       字段 ＋ 又挤进 `examples`），我们从规范字段收过了
          🔴 真缺                  19   全是**对称并列词**
          ⚠️ 不是词形              13   ← **我第一版逗号切法的残渣**，不是源头的账

⭐ 两条教训：
  ① 「我们没收」这句话**没量就写进了账本**。源头把同一份数据给了两遍，
     而我只看见挤进 examples 的那一遍。`[[measure-landing-not-source]]`。
  ② 那 13 条残渣是**我的判据**造出来的（`body.split(",")` 把
     `tàu hoả (“train”), tàu điện (“tram”)` 的括号限定语切断，
     造出 `in general` / `loosely or tightly)` 这种假目标）
     —— `[[residual-bucket-is-not-evidence]]`：别拿自己制造的残差当证据。
     ⇒ 本脚本的解析器**括号/引号内的逗号不算分隔符**。

═══ 为什么只能解析文本（而别处的规矩是「靠源头结构字段」）═══
⚠️ 这一批的特点正是**源头没给结构字段** —— 它把关系数据塞进了 `examples[].text`。
   所以这里没有「结构字段 vs 正则」的选择，只有「解析文本 or 不收」。
   ⇒ 两条纪律代替它：**① 目标必须在 `dict` 里**（解析错的词形自然落不上）
                     **② 19 条全部打印出来逐条读**，不抽样。

═══ kind 映射 ═══
`coordinate term(s)` → `coordinate` ／ `meronym(s)` → `meronym` ／ `cf` → `related`
🔴 `near-synonym(s)` **不收**：`stage6_sources.KINDS` 里没有这个 kind，而
   「近义」与 `synonym` 的差别是源头自己的分级，硬塞进 `synonym` 就是**改写源头的口径**。
   实测它那 52 条的目标**全部已在关系层**（以源头规范字段给的 kind 收的），
   所以不收它一条也不丢。⚠️ 什么会推翻：源头开始只在 examples 里给 near-synonym。

用法：
    python3 -u vi/fixes/collect_w17_relations.py            # 只报，逐条打印
    python3 -u vi/fixes/collect_w17_relations.py --apply
"""
import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import dbtool                                             # noqa: E402
import paths                                              # noqa: E402
import stage6_sources as S6                               # noqa: E402
from criteria import norm_vi                              # noqa: E402

F = lambda n: format(n, ",")                              # noqa: E731

# 🔴 `src` 列的值。关系闸的 `NON_EDITION_SRC` 登记的就是它，外锚闸按它取这一批
#    ——**三处共用这一个常量**，字面量抄三遍迟早漂开。
SRC = "w17-from-examples"

# 行首标签 → `KINDS` 的值域。**只列要收的那几种**，别的有意留空。
LABEL_KIND = {
    "coordinate term": "coordinate", "coordinate terms": "coordinate",
    "comeronym": "meronym", "comeronyms": "meronym",
    "meronym": "meronym", "meronyms": "meronym",
    "holonym": "holonym", "holonyms": "holonym",
    "cf": "related",
}
# 🔴 有意不收的标签，**写出来**而不是让它们落进 else ——
#    `[[record-the-negative-decision]]`：否定结论要能被闸看见。
LABEL_SKIP = {
    "near-synonym": "KINDS 里没有这个 kind，塞进 synonym 等于改写源头分级",
    "near-synonyms": "同上",
    "near-antonym": "同上", "near-antonyms": "同上",
    "synonym": "源头规范字段已收", "synonyms": "源头规范字段已收",
    "antonym": "源头规范字段已收", "antonyms": "源头规范字段已收",
    "hypernym": "源头规范字段已收", "hypernyms": "源头规范字段已收",
    "hyponym": "源头规范字段已收", "hyponyms": "源头规范字段已收",
    "see also": "指向整篇文章不是词形", "derived term": "源头规范字段已收",
    "derived terms": "源头规范字段已收", "related term": "源头规范字段已收",
    "related terms": "源头规范字段已收", "troponym": "源头规范字段已收",
    "troponyms": "源头规范字段已收",
}
# 越南语六声的英文名 —— 字母条目的声调范式表，**属音标层**。记 W23。
TONE_LABELS = {"level tone", "high rising", "high rising glottalized",
               "low", "low falling", "low glottalized",
               "dipping-rising", "falling"}

_OPEN = "（(「『【《〈[“‘"
_CLOSE = "）)」』】》〉]”’"


def split_targets(body):
    """按逗号切目标，**括号/引号内的逗号不算分隔符**。→ [目标…]

    🔴 第一版 `body.split(",")` 造出 13 条假目标（`in general` /
       `loosely or tightly)`），因为源头的形状是
       `tàu hoả (“train”), tàu điện (“tram”)` —— 限定语自己带逗号。
    """
    out, buf, depth = [], [], 0
    for ch in body:
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))
    # 目标 ＝ 第一个括号之前那一段（括号里是源头给的释义，不是词形的一部分）
    res = []
    for x in out:
        x = re.split(r"[（(“「]", x, 1)[0].strip().strip("“”\"'.;")
        if x:
            res.append(x)
    return res


def parse(con):
    """**只解析，不看库里已经有什么。** → (全部解出的行, 统计, 逐条清单)

    🔴🔴 **这个函数是为外锚闸拆出来的，而拆它的理由本身是一条教训。**
       第一版只有 `plan()`，它在解析的同时就把「关系层已经有了」的跳掉 ——
       于是插库之后再调一次，它返回 **0 行**。
       ⇒ 外锚闸拿不到一份「这 30 行应该是什么」的独立真值，
         只能在三向恒等里把它们报成「追不回源头」（它确实这么报了，**而它是对的**）。
    ⚠️ 两条路里选的是**给它一个锚**，不是把它从闸里排除：
       排除等于造一个洞 —— `[[gate-registers-status-quo-as-spec]]`。
       这 30 行解析自 `example.text`，而 `example` 本身被外锚闸锚到 dump
       ⇒ **它们是传递地锚住的**，闸只要确认「库里这 30 行 ≡ 重算一遍的结果」。
    """
    indict = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        indict[w] = i
    stat = collections.Counter()
    ins, listed = [], []
    seen = set()
    for wid, w, text in con.execute(
            "SELECT e.word_id, d.word, e.text FROM example e JOIN dict d ON d.id = e.word_id "
            " WHERE e.hidden = 1 AND e.hidden_why = ? ORDER BY e.id",
            (S6.HIDDEN_META_NOT_EXAMPLE,)):
        if ":" not in text:
            stat["没有冒号 ⇒ 解不出标签"] += 1
            continue
        lab, body = text.split(":", 1)
        lab = lab.strip().lower()
        if lab in TONE_LABELS:
            stat["声调范式表（属音标层，记 W23）"] += 1
            continue
        if lab in LABEL_SKIP:
            stat["有意不收：%s" % lab] += 1
            continue
        kind = LABEL_KIND.get(lab)
        if not kind:
            # 🔴 **未登记的标签必须大声报出来**，不许静默跳过 ——
            #    源头新增一种关系字段名时，这就是唯一的信号。
            stat["🔴 标签没登记：%r" % lab] += 1
            continue
        for tgt in split_targets(body):
            if tgt not in indict:
                stat["目标不在 dict（汉字/外语/解析不出）"] += 1
                continue
            if (wid, kind, tgt) in seen:
                stat["本批重复"] += 1
                continue
            seen.add((wid, kind, tgt))
            ins.append((wid, kind, tgt, indict[tgt], norm_vi(tgt)))
            listed.append((w, lab, kind, tgt))
            stat["✅ 解出来的"] += 1
    return ins, stat, listed


def plan(con):
    """`parse()` 减掉**关系层已经有的** ⇒ 真正要插的。→ (要插的行, 统计, 逐条清单)

    ⚠️ 「已经有了」占 83 条 —— 源头把同一份数据给了两遍（规范的 `coordinate_terms`
       字段 ＋ 又挤进 `examples`），我们早就从规范字段收过了。
    """
    allrows, stat, listed = parse(con)
    have = {(wid, kind, tgt) for wid, kind, tgt
            in con.execute("SELECT word_id, kind, target FROM sense_relation "
                           "WHERE src <> ?", (SRC,))}
    out, out_listed = [], []
    for r, l in zip(allrows, listed):
        if (r[0], r[1], r[2]) in have:
            stat["关系层已经有了"] += 1
            continue
        out.append(r)
        out_listed.append(l)
    return out, stat, out_listed


def src_ref(wid, kind, tgt):
    """这一批的 `src_ref` 公式。**只有一个家** —— 闸和写入方调同一个。

    ⚠️ 不许反向 `split(':')` 解析（词形本身可能含冒号；ja 那边栽过，
       1,866 条只对上 1,091 而**对不上的静默漏修**）。
    """
    return "relw17:%s:%s:%s" % (wid, kind, tgt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    cols = [r[1] for r in con.execute("PRAGMA table_info(sense_relation)")]
    ins, stat, listed = plan(con)
    con.close()
    print("■ `sense_relation` 的列：%s" % ", ".join(cols))
    for k, v in stat.most_common():
        print("   %-44s %5s" % (k, F(v)))
    print("\n■ 要收的 %s 条（全部打印，不抽样）" % F(len(ins)))
    for w, lab, kind, tgt in listed:
        print("   %-16s %-18s → %-10s  %s" % (w, lab, kind, tgt))
    if not a.apply:
        print("\n(只报不写。加 --apply。)")
        return
    if not ins:
        return
    # ⚠️ `src` 要能把这一批与两个既有写入方分开（ko 的 K14 正是栽在这里：
    #    两个写入方在 `src` 列分不开）⇒ 单独一个值。
    # ⚠️ `src_ref` 是 NOT NULL UNIQUE ⇒ 必须自己构造，而且**前缀要与既有写入方分开**
    #    （既有的是 `rel:<版>:…`）。公式在 `src_ref()` 里，外锚闸调同一个。
    rows = [(wid, None, kind, tgt, tid, SRC, src_ref(wid, kind, tgt))
            for wid, kind, tgt, tid, _ in ins]
    with dbtool.session(
            "vi-w17-collect-relations",
            expect={"__rows__": 0, "#sense_relation": len(rows),
                    "sense_relation.word_id": len(rows),
                    "sense_relation.kind": len(rows),
                    "sense_relation.target": len(rows),
                    "sense_relation.target_id": len(rows),
                    "sense_relation.hidden": len(rows),
                    "sense_relation.src": len(rows),
                    "sense_relation.src_ref": len(rows)},
            invalidates=[]) as s:
        s.executemany(
            "INSERT INTO sense_relation (word_id, sense_id, kind, target, target_id, src, "
            "src_ref) VALUES (?,?,?,?,?,?,?)", rows)


if __name__ == "__main__":
    main()
