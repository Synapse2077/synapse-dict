#!/usr/bin/env python3
"""B31（pt）— 例句标签：判据唯一的家 ＋ 回填 `example.tags`。2026-11-07。

═══ 是什么 ═══
源头在 `senses[].examples[]` 上标了 `tags`／`raw_tags`。ru（R25）、fr、en、de、es、vi、ko、it、ja 已做；
**按语种解耦**，pt 的值域、白名单写在这里，不 import 别门。B31 的第十门、最后一门。

pt 的例句来自十五份 dump（`ingest_examples.EDITIONS`）。全量值域（2026-11-07 只读扫）：
  · en 版 11,727 条里带 144：`collocation` 127；地区 `Brazil` 7／`Portugal` 6 不收；`raw_tags` 6 种全是
    自由文本（`idiomatic, Brazil`、`usually said to a child`）。
  · fr 版 13,744 条里带 6：`raw_tags: Proverbial` 1 收；学科名 4、`physical` 1 不收。
  · de 版 739 条里带 84：**全是国名**（`Brasilien` 34／`Portugal` 23／`Angola` 12…）不收。
  · 其余十二版：0。

═══ 判据（照前几门用户定的同一套口径）═══
· 逐字白名单；收类型（搭配／谚语）；**不收**地区、学科、自由文本。
· 同一（词，句子）多版／多义项都有时入库只留先到的一行，**标签取所有出现处的并集**。

═══ 键怎么对上库 ═══
直接调 `ingest_examples.scan()`（同一份 EDITIONS、同一个键（`norm_apos(词)`，`text.strip()`））。
桥（义项挂载）只影响 `sense_id`、不影响键 ⇒ 回填传空桥。

用法（在仓库根）：
    python3 -u pt/pipeline/example_tags.py              # 干跑
    python3 -u pt/pipeline/example_tags.py --apply
    python3 -u pt/pipeline/example_tags.py --verify
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 印出来的顺序 ＝ 受控值域。库里出现这之外的值＝回归闸红、页面查不到中文名。
EXAMPLE_TAG_ORDER = ("collocation", "proverb")

_TAGS = {"collocation": "collocation"}
# `raw_tags` 源头原文 → 我们的键。逐字。
_RAW = {"Proverbial": "proverb"}     # fr 版 1
# ⚠️ 有意不收：`idiomatic, Brazil`（复合自由文本，带地区）、地区、学科名、`physical`。


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
EXPECT_TAGGED = 128   # 2026-11-07 首次回填：scan() 给的 128 行（其中 3 行经族K 近似重复合并落到留下的那一行）


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
    ids = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    rows, _g, _st = IE.scan(ids, {}, {}, list(IE.EDITIONS))
    rows = list(rows.values())
    want = {(r["word"], r["text"]): r["tags"] for r in rows if r["tags"]}
    have = {(w, t): i for i, w, t in con.execute("SELECT id, word, text FROM example")}
    has_col = any(r[1] == "tags" for r in con.execute("PRAGMA table_info(example)"))
    cur = dict(con.execute("SELECT id, tags FROM example WHERE tags IS NOT NULL")) if has_col else {}
    con.close()

    print("■ scan() 例句 %s 行 ／ 库里 %s 行" % (format(len(rows), ","), format(len(have), ",")))
    # 🔴 scan() 比库多出来的那批，是 `fixes/fix_example_near_dup.py`（族K，2026-08-30）**合并掉**的
    #    「同一句话的两个抄本」（`palma da mão` vs `palma da mão.`，留有中文译文的那条）。
    #    标签属于「这句话」，不属于哪个抄本 ⇒ 精确键找不到时，按**同一个判据**
    #    （import `same_sentence`，不另写）找留下来的那一行；多个抄本的标签取并集。
    #    只在可见行里找（族K 只合并可见行），且归一键必须恰好命中一行，否则照旧报「找不到」。
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))
    from fix_example_near_dup import same_sentence
    con = _con_ro()
    ns = {}
    for i, w, t in con.execute("SELECT id, word, text FROM example WHERE COALESCE(hidden,0)=0"):
        ns.setdefault((w, same_sentence(t)), []).append(i)
    con.close()
    target = {}                       # example.id → 键集合
    miss, merged = [], 0
    for k, v in want.items():
        i = have.get(k)
        if i is None:
            hit = ns.get((k[0], same_sentence(k[1])), [])
            if len(hit) != 1:
                miss.append(k)
                continue
            i, merged = hit[0], merged + 1
        target.setdefault(i, set()).update(v.split("|"))
    final = {i: join_tags(ks) for i, ks in target.items()}
    upd = [(v, i) for i, v in final.items() if cur.get(i) != v]
    print("■ 其中经族K 合并后落到留下来那一行的：%s" % format(merged, ","))
    by = Counter(k for v in final.values() for k in v.split("|"))
    want = final                      # 下面的写后核对按「落到库里的行」算
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
