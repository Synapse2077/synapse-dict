#!/usr/bin/env python3
"""B31（ja）— 例句标签：判据唯一的家 ＋ 回填 `example.tags`。2026-11-07。

═══ 是什么 ═══
源头在 `senses[].examples[]` 上标了 `tags`／`raw_tags`。ru（R25）、fr、en、de、es、vi、ko、it 已做；
**按语种解耦**，ja 的值域、白名单写在这里，不 import 别门。

ja 的例句来自三份 dump（`harvest_examples.editions()`）。全量值域（2026-11-07 只读扫）：
  · en 版 22,228 条里带 193：`collocation` 26、`Internet` 3、`polite` 1、`humorous` 1、`proscribed` 1；
    地区（`Kansai` 6）、书写系统（`Traditional-Chinese`）、`Sino-Korean` 不收；`raw_tags` 124 种只收
    `proverb` 1／`Internet slang` 4，其余是学科（`computing` 6）、方言地名（`Tsugaru`）、复合自由文本
    （`modern language, literary` 7 —— 「现代语，书面」两层意思粘在一起，不拆）。
  · ja 版／zh 版：0。
  ⚠️ ja 的搭配只有 26 条（B31 立账时就记了「ja 只有 26 条」），是十门里最少的。

═══ 判据（照前几门用户定的同一套口径）═══
· 逐字白名单；收类型（搭配／谚语）与语体；**不收**地区、学科、书写系统、自由文本。
· `polite` 在日语里是丁宁语（です・ます），义项层 `JA_REGISTER_LABELS` 已有这个键 ⇒ 收，同名。
· 同一（词，句子）多版都有时入库只留信息最多的那条，**标签取所有出现处的并集**。

═══ 键怎么对上库 ═══
直接调 `harvest_examples.harvest()`（同一份 editions、同一套过滤与拆分、同一个键（词，`text.strip()`））。

用法（在仓库根）：
    python3 -u ja/pipeline/example_tags.py              # 干跑
    python3 -u ja/pipeline/example_tags.py --apply
    python3 -u ja/pipeline/example_tags.py --verify
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
    "polite", "internet", "humorous", "proscribed",
)

_TAGS = {
    "collocation": "collocation", "polite": "polite", "Internet": "internet",
    "humorous": "humorous", "proscribed": "proscribed",
}
# `raw_tags` 源头原文 → 我们的键。逐字。
_RAW = {"proverb": "proverb", "Internet slang": "internet"}
# ⚠️ 有意不收：`Internet meme`（指模因出处，不是语体）、`modern language, literary` 等复合自由文本、学科、地区。


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
EXPECT_TAGGED = 37   # 2026-11-07 首次回填：harvest() 给的（词,句）37 个，库里全部找到


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
    import harvest_examples as HX

    con = _con_ro()
    HX._simp = HX.simplified_only(con)
    rows, _g, _st = HX.harvest(con)
    want = {(r[0], r[2]): r[12] for r in rows if r[12]}
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
