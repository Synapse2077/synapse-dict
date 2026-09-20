#!/usr/bin/env python3
"""词头里的**转义泄漏**：`` `tilde` `` / `` `lowbar` `` / `` `period` ``。2026-09-19。零模型调用。

═══ 是什么 ═══
阶段 0 建库时，维基源码里的实体转义（`&tilde;` 这一族）被 kaikki 渲染成
`` `名字` `` 的形式原样收了进来，于是 16 个颜文字词条的**词头是坏的**：

    (^.^)/`tilde``tilde``tilde`      真形 → (^.^)/~~~
    m(`lowbar` `lowbar`)m            真形 → m(_ _)m
    `period``period`                 真形 → ..

**读者搜得到、点进去看见一串反引号**，属于 `错比缺更伤权威` 的那一侧。
JA_PLAN 工程欠账 5 记的是 755 条，实测到 2026-09-19 只剩 **18 条含反引号**、
其中 16 条需要修 —— 其余是先前几轮清洗顺带带走的。

═══ 🔴 判据只认**成对的** `` `名字` ``，不认裸反引号 ═══
`(´・ω・\`)` 与 `(´･ω･\`)` 这两个颜文字里的反引号**是字形本身**，不是转义。
判据写成「凡是反引号就处理」会把它们改坏 ——
两个真词条换十六个坏词条，那是拿一个错换另一个错。
⇒ 正则 `` `([a-z]+)` ``，且只替换**认识的**转义名；出现没见过的名字**整条不动并报出来**
（`[[criteria-narrower-than-you-think]]`）。

跑（在仓库根）：
    python3 -u ja/fixes/fix_escape_leak.py
    python3 -u ja/fixes/fix_escape_leak.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import re
import sqlite3

import dbtool
import paths
from pipeline.build import norm_ja

# 只认这三个 —— 全量扫过 dict/sense_relation/example/sense_gloss，出现的就这三种。
ESCAPE = {"tilde": "~", "lowbar": "_", "period": "."}
PAT = re.compile(r"`([a-z]+)`")


def unescape(s):
    """→ (新串, 未知转义名列表)。有未知名字时**不替换任何东西**，交给调用方记账。"""
    unknown = [m for m in PAT.findall(s) if m not in ESCAPE]
    if unknown:
        return s, unknown
    return PAT.sub(lambda m: ESCAPE[m.group(1)], s), []


def main():
    assert paths.DB.name == "synapse-dict-ja.sqlite", "🔴 paths 不是 ja 的"
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    w2i = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    # 🔴 **四个桶必须装得下每一条**：第一版漏了「裸反引号」那一桶，
    #    `(´・ω・`)` 这类既不在「要修」也不在「不动」，被静默排除 ⇒ 总数印成 16 而实际 18。
    #    残差是残差不是度量（`[[residual-bucket-is-not-evidence]]`），漏一个桶它就虚瘦。
    fixes, unknown_esc, literal, clash = [], [], [], []
    total = 0
    for i, w in con.execute("SELECT id, word FROM dict WHERE word LIKE '%`%'"):
        total += 1
        new, unknown = unescape(w)
        if unknown:
            unknown_esc.append((w, unknown))
        elif new == w:
            literal.append(w)          # 反引号是**字形本身**，不是转义
        elif new in w2i and w2i[new] != i:
            clash.append((i, w, new))  # 洗完撞上已有词形 ⇒ 本轮不动（合并要另起一轮）
        else:
            fixes.append((i, w, new))
    con.close()
    assert total == len(fixes) + len(unknown_esc) + len(literal) + len(clash), "🔴 桶没装全"

    print("   含反引号的词头 %d ＝ 要修 %d ＋ 字形本身带反引号 %d ＋ 未知转义 %d ＋ 撞词形 %d"
          % (total, len(fixes), len(literal), len(unknown_esc), len(clash)))
    for w in literal:
        print("      有意不动（反引号是字形的一部分）：%r" % w)
    for w, u in unknown_esc:
        print("      🔴 有意不动（出现没见过的转义名 %s）：%r" % (u, w))
    dbtool.sample_check([(w, n) for _i, w, n in fixes], 12, ("改前", "改后"))
    if clash:
        print("   🔴 撞词形，本轮不动：%s" % clash[:5])

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("ja-escape-leak", expect={}, invalidates=[]) as s:
        s.executemany("UPDATE dict SET word=?, word_norm=? WHERE id=?",
                      [(n, norm_ja(n), i) for i, _w, n in fixes])


if __name__ == "__main__":
    main()
