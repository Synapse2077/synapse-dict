#!/usr/bin/env python3
"""B31（ko）— 回填 `example.tags`。2026-11-07。

判据住 `criteria.py`（`example_tag_set`／`join_example_tags`），取值与去重**全部**来自
`harvest_examples.harvest()`（同一个键（词，正文）、同一套前缀剥离）——本脚本一行判据都不写，
只把 harvest() 产出的标签按（词，正文）原地写进已有行。`[[enrich-not-rebuild]]`。

跑（在仓库根）：
    python3 -u ko/pipeline/fill_example_tags.py           # 干跑
    python3 -u ko/pipeline/fill_example_tags.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import sqlite3

import dbtool
import paths
import harvest_examples as HE

f = lambda n: format(n, ",")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    rows, _lab, _resid, _st = HE.harvest()
    want = {(r["word"], r["text"]): r["tags"] for r in rows if r["tags"]}
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {(w, t): i for i, w, t in con.execute("SELECT id, word, text FROM example")}
    has_col = any(r[1] == "tags" for r in con.execute("PRAGMA table_info(example)"))
    cur = dict(con.execute("SELECT id, tags FROM example WHERE tags IS NOT NULL")) if has_col else {}
    indict = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()
    # 词形不在 dict ⇒ 这句例句本来就没入库（收词缺口，不是标签缺口），与外锚闸同一条规矩
    nodict = [k for k in want if k not in have and k[0] not in indict]
    miss = [k for k in want if k not in have and k[0] in indict]
    upd = [(v, have[k]) for k, v in want.items() if k in have and cur.get(have[k]) != v]
    by = collections.Counter(k for k, v in want.items() if k in have for k in v.split("|"))
    print("■ harvest() 带标签的（词，正文）%s ／ 词形不在 dict %s ／ 库里找不到 %s"
          % (f(len(want)), f(len(nodict)), f(len(miss))))
    print("   " + "  ".join("%s %s" % (k, f(by[k])) for k in HE.CR.EXAMPLE_TAG_ORDER if by[k]))
    for k in miss[:5]:
        print("   🔴 找不到：%s ｜ %s" % (k[0], k[1][:60]))
    print("■ 要写 %s 行" % f(len(upd)))
    if miss:
        print("🔴 词形在 dict 而句子不在库里 —— 外锚闸该先红，先查清再写")
        return 1
    if not a.apply:
        print("（干跑。加 --apply 才写库）")
        return 0
    with dbtool.session("ko-b31-example-tags",
                        # 非空计数的变化 ＝ 写后应有（want 里落在库中的）− 写前已有
                        expect={"example.tags": sum(1 for k in want if k in have) - len(cur)},
                        invalidates=["例句标签列新增：展示层 korean.ts／App 要读它；契约闸要查值域"]) as s:
        if not has_col:
            s.execute("ALTER TABLE example ADD COLUMN tags TEXT")
        s.executemany("UPDATE example SET tags=? WHERE id=?", upd)
    return 0


if __name__ == "__main__":
    _sys.exit(main())
