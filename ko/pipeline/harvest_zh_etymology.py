#!/usr/bin/env python3
"""K36①：收中文版两片（繁／简）的词源正文进 `etymology`。2026-10-27。**免费，不调模型。**

═══ 盘子（2026-10-27 干跑实测）═══
    中文繁 6,260 ／ 中文简 682 条有 `etymology_texts`（**复数** —— K36 本身就是读单数读出的 0）。
    落点：认得到同源 entry 1,405 ／ 词在 dict 但没有中文版 entry 5,536 ／ 词不在库 1。
    形状：正文 5,241 ／汉字占比低（引中世韩语文献 `＜ 놓다《龍飛御天歌》(1447)`）1,647 ／
          指针 15 ／只有标点 1。

═══ 🔴 落进 `etymology`，不是 `etymology_gloss` ═══
计划表 K36 原话是「收进 `etymology_gloss`」—— **那是错的落点**：`etymology_gloss` 的键是
`etymology_id`，意思是「**那一条英文词源**的中文译文」；而中文版这批是**中文版自己写的词源**，
不是英文那条的翻译，说的未必是同一件事（同一个词英文版可能有好几支）。塞进去＝主键认得上、配对是错的
（`[[primary-key-is-not-enough]]`）。⇒ 照 vi（3,461 条）／ru（15,302 条）的先例：
**一份来源一行，`edition`／`src` 写明是中文版**。

═══ 挂在哪 ═══
    · 同源 entry 认得到（键用 `intake_editions.iter_entries()` —— 建 entry 时的**同一套推导**，import 不重写）
      ⇒ `entry_id` 照填，页面上那一组的词源标题下直接印。
    · 认不到（这个词英文版也有，所以当初没建中文版 entry）⇒ `entry_id` 留空、挂在词上。
      展示层把「这一页有、而没有任何一组印出来」的词源汇总到页尾单独成区（照 vi 的 B18 解法）。

═══ 不收的两类（逐条读过，16 条，没有误伤）═══
    · 指针 15 条：`參見主條目。`（没说是哪一条）／`參見가엾다 (gayeopda)。` —— 照 vi/ru「指针段不出版」。
    · 只有标点 1 条：`라장조` 的 `。`。判据交给 Unicode（一个字母或数字都没有），不手抄字符范围。

═══ 正文一个字节不改 ═══
繁体原样存、原样印 —— 与 ko 已收的中文版释义一致；也避开 B25（整段 `t2s` 会把本来就是简体的改错）。

跑（在仓库根）：
    python3 -u ko/pipeline/harvest_zh_etymology.py            # 干跑
    python3 -u ko/pipeline/harvest_zh_etymology.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import re
import sqlite3
import unicodedata

import dbtool
import paths
from intake_editions import iter_entries

f = lambda n: format(n, ",")
POINTER = re.compile(r"^(參見|参见|參看|参看|見主條目|见主条目)")
SRC_FILE = {"zh-edition-simp": paths.ZH_SIMP.name, "zh-edition-trad": paths.ZH_TRAD.name}


def has_alnum(t):
    return any(unicodedata.category(c)[0] in "LN" for c in t)


def harvest(con):
    """→ (rows, stat)。rows = (word_id, entry_id|None, edition, etym_no, text, src, src_ref)"""
    eref = {r[0]: r[1] for r in con.execute("SELECT src_ref, id FROM entry")}
    wid = {r[0]: r[1] for r in con.execute("SELECT word, id FROM dict")}
    rows, stat = [], collections.Counter()
    for src, _glang, w, praw, etym, seq, d in iter_entries():
        if not src.startswith("zh-"):
            continue
        ts = d.get("etymology_texts") or []
        if isinstance(ts, str):
            ts = [ts]
        text = "\n".join(x.strip() for x in ts if x and x.strip())
        if not text:
            continue
        stat[src + " · 有词源正文"] += 1
        if not has_alnum(text):
            stat["不收 · 只有标点"] += 1
            continue
        if POINTER.match(text):
            stat["不收 · 指针段"] += 1
            continue
        ref = "%s:%s:%s:%s:%d" % (src, w, praw, etym, seq)
        if w not in wid:
            stat["不收 · 词不在 dict"] += 1
            continue
        eid = eref.get(ref)
        stat["收 · 挂 entry" if eid else "收 · 挂在词上（无中文版 entry）"] += 1
        rows.append((wid[w], eid, src, etym, text, SRC_FILE[src], ref))
    return rows, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = con.execute("SELECT COUNT(*) FROM etymology WHERE edition LIKE 'zh-%'").fetchone()[0]
    if have:
        raise SystemExit("🔴 已有 %s 行中文版词源 —— 本脚本只做首次收录" % f(have))
    rows, stat = harvest(con)
    con.close()
    print("■ K36① 中文版词源")
    for k, v in sorted(stat.items()):
        print("   %-34s %7s" % (k, f(v)))
    print("   %-34s %7s" % ("── 要写的", f(len(rows))))
    if not a.apply:
        print("\n（干跑。加 --apply 才写库）")
        return

    with dbtool.session(
            "ko-k36-harvest-zh-etymology",
            expect={"#etymology": len(rows)},
            invalidates=[
                "展示层：`entry_id` 为空的那批只能在页尾「其余词源」区印 —— "
                "`KoreanEntryView` 必须同步加上，否则 %s 条一个读者都看不到（K26 的形状）"
                % f(sum(1 for r in rows if r[1] is None)),
                "`etymologyEditions` 会多出 zh-edition-* ⇒ 中文版组没有词源时开始如实印「源头未给出」",
            ]) as s:
        s.executemany(
            "INSERT INTO etymology (word_id, entry_id, edition, etym_no, text, src, src_ref)"
            " VALUES (?,?,?,?,?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    want_e = sum(1 for r in rows if r[1] is not None)
    checks = [
        ("中文版词源行数", q("SELECT COUNT(*) FROM etymology WHERE edition LIKE 'zh-%'"), len(rows)),
        ("其中挂 entry", q("SELECT COUNT(*) FROM etymology WHERE edition LIKE 'zh-%' AND entry_id IS NOT NULL"), want_e),
        ("🔴 挂的 entry 来源与 edition 不一致",
         q("SELECT COUNT(*) FROM etymology t JOIN entry e ON e.id=t.entry_id WHERE t.edition<>e.src"), 0),
        ("🔴 挂的 entry 词源号不一致",
         q("SELECT COUNT(*) FROM etymology t JOIN entry e ON e.id=t.entry_id WHERE t.etym_no<>e.etym_no"), 0),
        ("🔴 挂的 entry 不属于这个词",
         q("SELECT COUNT(*) FROM etymology t JOIN entry e ON e.id=t.entry_id WHERE t.word_id<>e.word_id"), 0),
        ("🔴 英文版行数变了", q("SELECT COUNT(*) FROM etymology WHERE edition='en-edition'"), 38796),
    ]
    red = 0
    print("\n■ 写后回核（从库里重算）")
    for name, got, want in checks:
        red += got != want
        print("   %s %-30s %8s  期望 %8s" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    print("\n■ 抽样（人眼看）")
    for w, ed, t in con.execute("SELECT d.word, t.edition, t.text FROM etymology t JOIN dict d ON d.id=t.word_id "
                                "WHERE t.edition LIKE 'zh-%' ORDER BY RANDOM() LIMIT 8"):
        print("   %-10s %-16s %s" % (w, ed, t.replace("\n", " ⏎ ")[:80]))
    con.close()
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


if __name__ == "__main__":
    main()
