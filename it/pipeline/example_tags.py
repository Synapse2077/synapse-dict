#!/usr/bin/env python3
"""B31（it）— 例句标签：判据唯一的家 ＋ 回填 `example.tags`。2026-11-07。

═══ 是什么 ═══
源头在 `senses[].examples[]` 上标了 `tags`／`raw_tags`。ru（R25）、fr、en、de、es、vi、ko 已做；
**按语种解耦**，it 的值域、白名单写在这里，不 import 别门。

it 的例句来自三份 dump（`ingest_examples.SOURCES`）。全量值域（2026-11-07 只读扫）：
  · en 版 10,939 条里带 273：`collocation` 210、`vulgar`／`archaic`／`informal`／`slang`／`polite` 各 1、
    语法（`relational`／`adjective`／`impersonal`）、地区 `Tuscany`；`raw_tags` 48 种只有 `proverb` 4／
    `figurative` 3 可归类，其余是自由文本（`yelled by pirates`、整句意语）。
  · fr 版 10,768 条里带 133：`figuratively` 5、`dated` 1、`slang` 1、`raw_tags: Proverbial` 2；
    其余是学科名（`Informatique` 11…）、`physical` 8（具体义，引申方式的反面，不是语体）、`Ancient` 3（年代）。
  · it 版：0。

═══ 判据（照前几门用户定的同一套口径）═══
· 逐字白名单；收类型（搭配／谚语）与语体；**不收**地区、学科、语法、自由文本。
· `polite`（en 1 条）不收：意语里指敬称形式（Lei），是语法人称，不是语体。
· 同一（词，句子）多版都有时入库只留优先级高的那版（`PRIO`），**标签取所有出现处的并集**。

═══ 键怎么对上库 ═══
直接调 `ingest_examples.collect()`（同一份 SOURCES、同一套过滤、同一个键（词，`text.strip()`））。

用法（在 it/ 目录下）：
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
    "informal", "slang", "dated", "archaic", "vulgar",
    "figurative",
)

_TAGS = {
    "collocation": "collocation",
    "informal": "informal", "slang": "slang", "dated": "dated", "archaic": "archaic",
    "vulgar": "vulgar", "figuratively": "figurative",
}
# `raw_tags` 源头原文 → 我们的键。逐字。
_RAW = {"proverb": "proverb", "Proverbial": "proverb", "figurative": "figurative"}
# ⚠️ 有意不收：`figurative, pejorative`（复合自由文本）、`chiefly jocular expression`、学科名、地区、语法。


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
EXPECT_TAGGED = 230   # 2026-11-07 首次回填：collect() 给的（词,句）230 个，库里全部找到


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

    con = _con_ro()
    rows, _c = IE.collect(con, verbose=False)
    want = {(r["word"], r["text"]): r["tags"] for r in rows if r["tags"]}
    have = {(w, t): i for i, w, t in con.execute("SELECT id, word, text FROM example")}
    has_col = any(r[1] == "tags" for r in con.execute("PRAGMA table_info(example)"))
    cur = dict(con.execute("SELECT id, tags FROM example WHERE tags IS NOT NULL")) if has_col else {}
    con.close()

    print("■ collect() 例句 %s 行 ／ 库里 %s 行" % (format(len(rows), ","), format(len(have), ",")))
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
