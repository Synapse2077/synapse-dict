#!/usr/bin/env python3
"""B25：09-16 **整段** OpenCC 繁→简改错的中文释义与例句译文，按安全判据从原文重算。ja，2026-10-29。

═══ 缺陷 ═══
`fix_traditional_to_simplified.py`（09-16）给 `convert` 传的是整段 opencc t2s，在本来就是简体的文本上会改错：
扩展平面字形（`鮟鱇→𩽾𩾌`、`鰤鱼→𫚕鱼`，多数字体是豆腐块）、歧义字（卦名 `乾下艮上→干下艮上`、
人名 `市乾鹿文`、`覆上了雪→复上`、`糙叶薹草→苔草`、`甯子→宁子`）。

═══ 判据 ═══
一条不在这里写 —— `fix_traditional_to_simplified.safe_t2s`（安全版）／`opencc_t2s`（复现历史用）、
`convert`（日文引文保护）、`fix_tw_vocab.apply_row`（台湾用词，09-16 之后那一轮）。
每行找原文：模型答案（按主键）、证据层 `sense_src`、`example.src_translation`。
    现值 == 原文                                    ⇒ 没被转过
    现值 == 用词(convert(原文, opencc)) ≠ 用词(convert(原文, 安全)) ⇒ **被整段转错了**，改成后者
    对不上                                          ⇒ 不动，单独计数

跑（在仓库根）：
    python3 -u ja/fixes/fix_t2s_damage.py            # 干跑
    python3 -u ja/fixes/fix_t2s_damage.py --apply
"""
import sys as _sys
import pathlib as _pl
_HERE = _pl.Path(__file__).resolve().parent
_sys.path.insert(0, str(_HERE.parent))
_sys.path.insert(0, str(_HERE))

import argparse
import collections
import json
import sqlite3

import dbtool
import paths
from fix_traditional_to_simplified import convert, opencc_t2s, safe_t2s
from fix_tw_vocab import apply_row as tw_apply

W = paths.ROOT / "data" / "work" / "ja"
ANSWERS = {"sense_gloss": [W / "translate" / "defs.jsonl", W / "translate" / "defs_ja.jsonl",
                           W / "hier_gloss_zh.jsonl"],
           "example_gloss": [W / "runs" / "examples_zh.jsonl"]}
TABLES = (("sense_gloss", "sense_id"), ("example_gloss", "example_id"))


def old_fn(s):
    return tw_apply(convert(s, opencc_t2s)[0])


def new_fn(s):
    return tw_apply(convert(s, safe_t2s)[0])


def originals(con, tbl):
    orig = collections.defaultdict(set)
    for f in ANSWERS[tbl]:
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            i = str(d["id"])                      # `hier_gloss_zh` 里 `s123` 是义项、`u…` 不是
            if d.get("zh") and (i.isdigit() or (i[:1] == "s" and i[1:].isdigit())):
                orig[int(i.lstrip("s"))].add(d["zh"])
    sql = ("SELECT sense_id, text FROM sense_src WHERE lang='zh' AND sense_id IS NOT NULL" if tbl == "sense_gloss"
           else "SELECT id, src_translation FROM example WHERE src_translation IS NOT NULL")
    for k, t in con.execute(sql):
        if t:
            orig[k].add(t)
    return orig


def plan(con):
    todo, st = [], collections.Counter()
    for tbl, key in TABLES:
        orig = originals(con, tbl)
        for rid, k, text, src in con.execute("SELECT rowid, %s, text, src FROM %s WHERE lang='zh'" % (key, tbl)):
            cands = orig.get(k, ())
            if text in cands:
                st[(tbl, "没被转过")] += 1
                continue
            hit = sorted(o for o in cands if old_fn(o) == text)
            if not hit:
                st[(tbl, "对不上原文（证明不了）")] += 1
                continue
            new = new_fn(hit[0])
            if new == text:
                st[(tbl, "被转过·转对了")] += 1
            else:
                st[(tbl, "被转过·🔴转错了")] += 1
                todo.append((tbl, rid, text, new, src))
    return todo, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    assert paths.DB.name == "synapse-dict-ja.sqlite", paths.DB
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo, st = plan(con)
    con.close()
    print("■ B25 整段繁→简改错（ja）")
    for (tbl, k), v in sorted(st.items()):
        print("   %-14s %-22s %9s" % (tbl, k, format(v, ",")))
    for tbl, _rid, old, new, src in todo[::max(1, len(todo) // 25)]:
        print("   %-13s %-28s → %s" % (tbl, old.replace("\n", " ")[:28], new.replace("\n", " ")[:36]))
    if not a.apply or not todo:
        print("\n（干跑。加 --apply 才写库）" if todo else "\n（无事可做）")
        return
    with dbtool.session("ja-fix-t2s-damage", expect={
            "__rows__": 0, "#sense_gloss": 0, "#example_gloss": 0}) as s:
        for tbl in ("sense_gloss", "example_gloss"):
            s.executemany("UPDATE %s SET text=? WHERE rowid=?" % tbl,
                          [(n, r) for t, r, _o, n, _s in todo if t == tbl])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left, _ = plan(con)
    con.close()
    print("\n■ 写后回核：仍转错 %d 条（期望 0）" % len(left))
    if left:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
