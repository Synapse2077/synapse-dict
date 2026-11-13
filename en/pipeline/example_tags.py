#!/usr/bin/env python3
"""B31（en）— 例句标签：判据唯一的家 ＋ 回填 `example.tags`。2026-11-07。

═══ 是什么 ═══
源头在 `senses[].examples[]` 上标了 `tags`／`raw_tags`。ru（R25）、fr 已做；**按语种解耦**，
en 的值域、白名单写在这里，不 import 别门。

en 版 dump 全量值域（2026-11-07 只读扫，带标签的例句 7,499 条）：
  · `tags` 22 种：`collocation` **7,343**（这条「例句」其实是固定搭配，如 `make a decision`）；
    其余全是个位数 —— 语体 `informal`／`dated`／`archaic`／`humorous`／`sarcastic`／
    `nonstandard`／`proscribed`，地区 `UK` 7／`US` 4，语法 `transitive`／`countable`…，
    书写系统 `Traditional-Chinese`／`Simplified-Chinese`（别的语言的例句串进来）。
  · `raw_tags` 119 种，**全是自由文本**（`double possessive`、`This usage is likely ironic.`、
    整句释义）⇒ 一个都不收（B31 用户 2026-11-05 定：自由文本不许当标签印）。

═══ 判据（照 fr 用户 11-06 定的同一套口径）═══
· **逐字白名单**；收「类型（搭配）」与「语体」，不收地区（地区是另一个维度，义项层已有）、
  不收语法、不收书写系统。
· `sarcastic` 并进 `ironic`（ru／fr 同款：值域里只留一个「讽刺」）。
· 同一（词，句子）在多个义项下出现时，入库只留一行（`UNIQUE(word,text)`），
  **标签取并集**（fr 同款，否则后出现那处的标签被静默吞掉）。

═══ 键怎么对上库 ═══
不另写一套读 dump 的代码：`harvest_ex_rel.py` 把标签写进中间件 `ex_rel.jsonl`（`tg`），
`build_ex_rel.collect()` 用它自己的去重键（词，`text.strip()`）合并 —— 本脚本**直接调 collect()**，
与落库那一步同一个键、同一个去重，回填不可能和重建对不上。
⚠️ 所以回填前必须先重跑 `harvest_ex_rel.py`（只重写中间件，不碰库）；
   中间件是旧的（没有 `tg`）＝ 本脚本拒绝写（`--apply` 前检查）。

用法（在 en/ 目录下）：
    python3 -u pipeline/harvest_ex_rel.py           # 先重生中间件（带 tg）
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
    "collocation",
    "informal", "nonstandard", "proscribed",
    "dated", "archaic",
    "humorous", "ironic",
)

_TAGS = {
    "collocation": "collocation",
    "informal": "informal", "nonstandard": "nonstandard", "proscribed": "proscribed",
    "dated": "dated", "archaic": "archaic",
    "humorous": "humorous", "sarcastic": "ironic", "ironic": "ironic",
}
# `raw_tags` 一个都不收（全是自由文本，见文件头）。写空表而不是删掉这一段：
# 下一个人看到「raw 没处理」会以为是漏了。
_RAW = {}


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
EXPECT_TAGGED = 7339   # 2026-11-07 首次回填：collect() 给的（词,句）7,339 个，库里全部找到


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
    import build_ex_rel as BX
    import dbtool

    con = _con_ro()
    ex, _rel, st = BX.collect(con)
    if not st["ex 带 tg 字段"]:
        print("🔴 中间件里没有 `tg` 字段 —— 先跑 pipeline/harvest_ex_rel.py 重生中间件")
        return 1
    want = {(r[0], r[2]): r[10] for r in ex if r[10]}
    have = {(w, t): i for i, w, t in con.execute("SELECT id, word, text FROM example")}
    has_col = any(r[1] == "tags" for r in con.execute("PRAGMA table_info(example)"))
    cur = dict(con.execute("SELECT id, tags FROM example WHERE tags IS NOT NULL")) if has_col else {}
    con.close()

    # 🔴 中间件与库必须是同一批：collect() 出来的行数 ≠ 库里行数 ⇒ 中间件或库被单独动过
    print("■ collect() 例句 %s 行 ／ 库里 %s 行" % (format(len(ex), ","), format(len(have), ",")))
    if len(ex) != len(have):
        print("🔴 行数对不上 —— 中间件与库不是同一批，先查清再写")
        return 1
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
