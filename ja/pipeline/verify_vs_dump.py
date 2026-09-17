#!/usr/bin/env python3
"""**外锚闸**：库 vs 三版 dump，**义项级**逐条比对。ja 版，2026-09-16（阶段 7）。

═══ 为什么必须有这一道，且它与回归闸不可互相替代 ═══
`[[external-anchor-gates]]`：**锚自己上一版的必然过期，锚外部 dump 的永不过期**。

    回归闸  问「**过去的修复还在不在**」 —— 只看库里已有的东西
    外锚闸  问「**源头有而我们没有的，还剩多少**」

两个问题没有交集。es 那轮正是这道闸逮到 `derived` **义项级漏收 20,193 条**，
而所有内部闸（行数、不变量、可逆性）永远发现不了它：
**词形在库、义项没收进来**，按词形量覆盖率是满分。

═══ 🔴 必须义项级，不能词形级 ═══
按词形级量，「词形在库、这条义项没收」永远是绿的。
⇒ 一律按 **(词形, 义项文本)** 二元组比对。

═══ 🔴 判据一个字都不重抄 ═══
本文件 import 收词器那一份：
    `intake_edition_words.real_senses`   ← 什么算「真释义」（排除指针义项）
    `intake_edition_words.clean_gloss`   ← 中文版 gloss 的清洗
    `intake_edition_words.POINTER`
    `build.norm_ja`                       ← 词形归一
**闸与收词器判据漂开 ＝ 闸在报自己的 bug。** fr 那轮从 it 抄了一条「词缀豁免」，
当场报 42 条假缺口，逐条读下来 40 条是纯指针、收词器跳过是对的。
ja 这一轮也演过：阶段 1 的罗马字断言自己重写了一条规则，报 6 条假红。

═══ ⚠️ 这门语言上「缺」的三个正当来源，不是缺陷 ═══
① **中文版同词两版都有时取日语版**（阶段 3a 的决定，不做跨版义项配对）——
   中文版那条义项因此不在库里，**是有意的**。
② **`soft-redirect` 不产生义项**，它进关系层（阶段 5b/5d）。
③ **kaikki 的同一条义项在两版里文本不同**（翻译腔、断句不同）——
   二元组对不上，但内容在。本闸按**文本**比，所以这类会计入"缺"。
⇒ 因此本闸的判据是**趋势和上限**，不是"必须为 0"。基线写在 `BUDGET` 里，各带理由。

用法（在仓库根）：
    python3 -u ja/pipeline/verify_vs_dump.py
    python3 -u ja/pipeline/verify_vs_dump.py --show 20     # 逐条看缺的长什么样
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import gzip
import json
import sqlite3

import paths
from build import norm_ja
from intake_edition_words import real_senses, clean_gloss

f = lambda n: format(n, ",")

# 各版允许的缺口上限：`版 → (条数上限, 理由)`。**锁数字，不锁名字。**
BUDGET = {
    "en-edition": (0, "英文版是建库主源，义项**全收** ⇒ 一条都不许缺。"),
    "ja-edition": (
        58_364,
        "🔴🔴 **我第一版给这条写的理由是错的**（写的是「文本比对的局限，不是漏收」）。"
        "闸报 36% 超上限，逐条读之后发现**是真的缺内容**：`男児`／`表現`／`灌漑`／`流入` "
        "这些常用词在库里**一条日语释义都没有**，而日语版 dump 里有。"
        "⇒ 闸逮到的第一件事，是我为它写的解释在说谎。<br>"
        "**真正的原因**：日语版的释义要挂到义项上，就得知道它对应哪一条义项。"
        "实测 23,692 个词形有未收的日语释义，其中**配对唯一（库里 1 义项、源头 1 释义）"
        "的只有 9 个**，其余 23,683 个两边条数对不上 ⇒ 挂上去就是猜。<br>"
        "⇒ 与 `JA_PLAN` §四.1 **同一条决定**（那条说的是中文版释义，这里是日语版释义，"
        "同一个问题）：**不做跨版义项配对**。es 那轮自动判重 186 条里 12.4% 是错配"
        "（`peón` 的「棋子」并进了「行人」）。多一条义项是「缺」，义项错配是「错」，"
        "**错比缺更伤权威**。<br>"
        "⚠️ 已有 83,861 个词形的日语释义是齐的，缺的是配不上对的那批。"
        "那 9 个唯一配对的没单独去补 —— 写个脚本收 9 行不划算，记在这儿。<br>"
        "🔴 **推翻它需要**：出现一种能**证明**对齐正确性的手段（判官不算，"
        "`[[llm-as-evaluator-discipline]]`⑬：判官错误率 ≥ 缺陷率就别造），"
        "或者 schema 改成能挂「词条级释义」而不必绑到某条义项上。"),
    "zh-edition": (
        55_363,   # 实测值。原来写 70,000 是拍的 —— 拍一个宽上限等于给自己留静默余量
        "🔴 **这是有意的缺，阶段 3a 定的**：同词两版都有时**取日语版、不做跨版义项配对**。"
        "理由见 `JA_PLAN` §四.1 —— 做更好的对齐最多省 4.1 元，而代价是**义项错配**"
        "（es 那轮自动判重 186 条里 12.4% 错配）。多一条义项是「缺」，错配是「错」，"
        "**错比缺更伤权威**。<br>"
        "🔴 **推翻它需要**：出现一种能证明对齐正确性的手段（不是模型判重），"
        "或者中文版独有义项的规模涨到让 4 元变成 40 元。"),
}


def dump_senses():
    """→ {版: {(归一词形, 义项文本)}}。判据全部来自收词器。"""
    out = {}
    for name, op, lc in [
            ("en-edition", lambda: open(paths.KK, encoding="utf-8"), None),
            ("ja-edition", lambda: open(paths.EDITION, encoding="utf-8"), None),
            ("zh-edition", lambda: gzip.open(paths.ZH_EDITION, "rt",
                                             encoding="utf-8"), "ja")]:
        s = set()
        with op() as fh:
            for line in fh:
                o = json.loads(line)
                if lc and o.get("lang_code") != lc:
                    continue
                if o.get("pos") == "soft-redirect":
                    continue          # 它进关系层，本来就不产生义项
                w = o.get("word") or ""
                if not w:
                    continue
                nw = norm_ja(w)
                for g, _tg in real_senses(o):
                    if name == "zh-edition":
                        # 🔴 中文版要过清洗器 —— 否则拿**未清洗**的原文去比
                        #    库里**已清洗**的文本，会把 100% 都报成"缺"。
                        for c in clean_gloss(g, w):
                            s.add((nw, c))
                    else:
                        s.add((nw, g))
        out[name] = s
        print("   %-12s 源头义项二元组 %s" % (name, f(len(s))), flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=0)
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = set()
    for w, t in con.execute(
            "SELECT d.word, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
            "JOIN dict d ON d.id=s.word_id WHERE g.src NOT LIKE 'model:%'"):
        have.add((norm_ja(w), t))
    # 证据层也算「我们有」—— 出版层没出的，证据层留着就不算丢
    for w, t in con.execute(
            "SELECT d.word, x.text FROM sense_src x JOIN dict d ON d.id=x.word_id"):
        have.add((norm_ja(w), t))
    con.close()
    print("■ 库里（出版层 ∪ 证据层）义项二元组 %s\n" % f(len(have)))

    src = dump_senses()
    print()
    red = 0
    for name, s in src.items():
        miss = s - have
        cap, why = BUDGET[name]
        over = len(miss) > cap
        red += over
        print("%s %-12s 缺 %9s / %9s = %5.2f%%   （上限 %s）"
              % ("🔴" if over else "✅", name, f(len(miss)), f(len(s)),
                 100 * len(miss) / max(len(s), 1), f(cap)))
        if over:
            print("   %s" % why[:220])
        if a.show and miss:
            for w, t in list(miss)[:a.show]:
                print("      %-14s %s" % (w[:14], t[:60]))
    if red:
        print("\n🔴 %d 版超出上限 —— 逐条读（`--show 20`）再决定是补收还是改上限。" % red)
        print("   ⚠️ **别直接调高上限**，那是把闸关掉。")
    else:
        print("\n✅ 三版都在上限内")
    _sys.exit(1 if red else 0)


if __name__ == "__main__":
    main()
