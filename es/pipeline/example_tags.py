#!/usr/bin/env python3
"""B31（es）— 例句标签：判据唯一的家 ＋ 回填 `example.tags`。2026-11-07。

═══ 是什么 ═══
源头在 `senses[].examples[]` 上标了 `tags`／`raw_tags`。ru（R25）、fr、en、de 已做；**按语种解耦**，
es 的值域、白名单写在这里，不 import 别门。

es 的例句来自七份 dump（`ingest_examples.SOURCES`）。全量值域（2026-11-07 只读扫 41 秒）：
  · en 版 20,690 条里带 626：`collocation` 618、`informal`／`formal`／`US`／`Mexico` 各 1；
    `raw_tags` 10 种全是自由文本（`"no" is optional`、`restaurant name`）。
  · fr 版 8,031 条里带 23：`figuratively` 6、`proverb` 1 ＋ `raw_tags: Proverbial` 4、`vulgar` 1；
    其余是地区（`Cuba`／`Chili`）、学科（`Commerce`）、语法。
  · zh 版 1,553 条里带 1：`colloquial`。
  · de 版 882 条里带 49：**全是国名**（`Kolumbien` 8／`Mexiko` 7…）。
  · es／it／pt 版：0。

═══ 判据（照 fr／en／de 用户定的同一套口径）═══
· 逐字白名单；收类型（搭配／谚语）与语体；**不收地区**、学科、语法、自由文本。
· 同一（词，句子）多份来源／多处出现时入库只留先到的一行（`UNIQUE(word,text)`），**标签取并集**。

═══ 键怎么对上库 ═══
不另写读 dump 的代码：直接调 `ingest_examples.harvest()`（同一份 SOURCES、同一个键（词，`text.strip()`））。

用法（在 es/ 目录下）：
    python3 -u pipeline/example_tags.py              # 干跑
    python3 -u pipeline/example_tags.py --apply
    python3 -u pipeline/example_tags.py --verify
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 印出来的顺序 ＝ 受控值域。库里出现这之外的值＝回归闸红、页面查不到中文名。
EXAMPLE_TAG_ORDER = (
    "collocation", "proverb",
    "colloquial", "informal", "formal", "vulgar",
    "figurative",
)

_TAGS = {
    "collocation": "collocation", "proverb": "proverb",
    "colloquial": "colloquial", "informal": "informal", "formal": "formal", "vulgar": "vulgar",
    "figuratively": "figurative",
}
# `raw_tags` 源头原文 → 我们的键。逐字。
_RAW = {"Proverbial": "proverb"}     # fr 版 4
# ⚠️ 有意不收：地区（`Mexico`／`US`／de 版国名／fr 版 `Cuba`…）、`Expression`（fr 1，含义不明）、
#    `formal singular`／`informal singular`（en，说的是代词的人称形式，不是语体）、其余自由文本。


def example_tags(x):
    """源头一条例句（dict）→ 我们的键集合（可能为空）。"""
    out = set()
    for t in x.get("tags") or ():
        k = _TAGS.get(t)
        if k:
            out.add(k)
    for t in x.get("raw_tags") or ():
        k = _RAW.get(t)
        if k:
            out.add(k)
    return out


def join_tags(keys):
    """键集合 → 入库字符串（`|` 分隔、按 EXAMPLE_TAG_ORDER 排）；空 → None。"""
    ks = [k for k in EXAMPLE_TAG_ORDER if k in keys]
    return "|".join(ks) if ks else None


def bad_tag_value(v):
    """回归闸的判据：值域外的键、重复、或没按 EXAMPLE_TAG_ORDER 排。"""
    if v is None:
        return False
    ks = v.split("|")
    if any(k not in EXAMPLE_TAG_ORDER for k in ks):
        return True
    return ks != [k for k in EXAMPLE_TAG_ORDER if k in ks]


# 回填后带标签的行数 —— **独立声明**（`[[expectation-must-be-declared]]`），改它必须写理由。
EXPECT_TAGGED = 632   # 2026-11-07 首次回填：harvest() 给的（词,句）632 个，库里全部找到


def _con_ro():
    import paths
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.verify:
        return verify()
    import dbtool
    import ingest_examples as IE

    rows, _st = IE.harvest()
    want = {k: r[12] for k, r in rows.items() if r[12]}
    con = _con_ro()
    have = {(w, t): i for i, w, t in con.execute("SELECT id, word, text FROM example")}
    has_col = any(r[1] == "tags" for r in con.execute("PRAGMA table_info(example)"))
    cur = dict(con.execute("SELECT id, tags FROM example WHERE tags IS NOT NULL")) if has_col else {}
    con.close()

    print("■ harvest() 例句 %s 行 ／ 库里 %s 行" % (format(len(rows), ","), format(len(have), ",")))
    miss = [k for k in want if k not in have]
    upd = [(v, have[k]) for k, v in want.items() if k in have and cur.get(have[k]) != v]
    by = Counter(k for v in want.values() for k in v.split("|"))
    print("■ 带标签的（词，句子）%s 个；库里找不到 %s"
          % (format(len(want), ","), format(len(miss), ",")))
    for k in EXAMPLE_TAG_ORDER:
        print("   %-12s %6s" % (k, format(by[k], ",")))
    for k in miss[:5]:
        print("   找不到：%s ｜ %s" % (k[0], k[1][:70]))
    print("■ 要写 %s 行" % format(len(upd), ","))
    if miss:
        print("🔴 有标签的句子在库里找不到 —— 先查清再写")
        return 1
    if not a.apply:
        print("(未加 --apply，未写库)")
        return 0
    with dbtool.session("b31-example-tags", expect={}) as s:
        if not has_col:
            s.execute("ALTER TABLE example ADD COLUMN tags TEXT")
        s.executemany("UPDATE example SET tags=? WHERE id=?", upd)
    con = _con_ro()
    after = con.execute("SELECT count(*) FROM example WHERE tags IS NOT NULL").fetchone()[0]
    con.close()
    if after != len(want):
        print("🔴 写后带标签 %s 行 ≠ 应有 %s" % (after, len(want)))
        return 1
    return verify()


def verify():
    con = _con_ro()
    n = con.execute("SELECT count(*) FROM example WHERE tags IS NOT NULL").fetchone()[0]
    bad = sum(1 for (v,) in con.execute("SELECT tags FROM example WHERE tags IS NOT NULL")
              if bad_tag_value(v))
    print("■ example.tags 非空 %s 行（期望 %s）｜ 值域外／乱序 %d"
          % (format(n, ","), EXPECT_TAGGED, bad))
    ok = bad == 0 and (EXPECT_TAGGED is None or n == EXPECT_TAGGED)
    print("✓ 通过" if ok else "🔴 未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
