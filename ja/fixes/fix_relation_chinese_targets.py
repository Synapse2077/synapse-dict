#!/usr/bin/env python3
"""关系目标里混着的**中文词**挂 `hidden=1`。2026-09-19。零模型调用。（JA_PLAN 欠账 15）

═══ 为什么是 hidden 不是 delete ═══
`sense_relation.hidden` 是这个库里既有的机制（`example.hidden` 已有 438 行在用），
展示层查的是 `WHERE r.hidden = 0`。**挂起来是可逆的，删掉不是**
（`[[prefer-reversible-designs]]`）—— 而这批判据虽然验过，残留假阳性仍是可能的。

═══ 判据与三种机制 ═══
见 `pipeline/harvest_relations.is_chinese_target()` 的文档串。**本脚本 import 它，不重写。**
一句话：中文版是「日语词与中文释义交替排列」，日语版是「日中写法成对列出」，
而**英文版那批根本不是中文，是拡張新字体，一条都不许碰**。

🔴 生成侧已同步改掉（`harvest_relations` 收行时直接写 `hidden`），
   不改的话下次重跑原样长回来（`[[replay-scripts-undo-fixes]]`）。

跑（在仓库根）：
    python3 -u ja/fixes/fix_relation_chinese_targets.py
    python3 -u ja/fixes/fix_relation_chinese_targets.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import gzip
import json
import sqlite3

import dbtool
import paths
from pipeline.harvest_examples import simplified_only
from pipeline.harvest_relations import KIND, clean_target, is_chinese_target


def scan(simp):
    """→ `{(词形, kind, 目标)}`，判为中文的那些。"""
    doomed = set()
    stat = collections.Counter()
    for src, op, lc in (("ja-edition", lambda: open(paths.EDITION, encoding="utf-8"), None),
                        ("zh-edition",
                         lambda: gzip.open(paths.ZH_EDITION, "rt", encoding="utf-8"), "ja")):
        with op() as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if lc and o.get("lang_code") != lc:
                    continue
                w = o.get("word") or ""
                for key, kind in KIND.items():
                    items = list(o.get(key) or [])
                    for s in o.get("senses") or []:
                        items += list(s.get(key) or [])
                    for it in items:
                        t = clean_target(it.get("word"))
                        if t and is_chinese_target(it, src, simp):
                            doomed.add((w, kind, t))
                            stat[src] += 1
    return doomed, stat


def main():
    assert paths.DB.name == "synapse-dict-ja.sqlite", "🔴 paths 不是 ja 的"
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    simp = simplified_only(con)
    doomed, stat = scan(simp)
    hit = [(i, w, k, t) for i, w, k, t in con.execute(
        "SELECT r.id, d.word, r.kind, r.target FROM sense_relation r"
        " JOIN dict d ON d.id=r.word_id WHERE r.hidden=0")
        if (w, k, t) in doomed]
    by_src = collections.Counter(
        s for (s,) in con.execute(
            "SELECT src FROM sense_relation WHERE id IN (%s)"
            % ",".join(str(i) for i, *_ in hit)) ) if hit else collections.Counter()
    con.close()

    print("   源头判为中文的 (词形,kind,目标) 组合：%s" % dict(stat))
    print("   库里要挂起的行：%s ｜按来源 %s" % (format(len(hit), ","), dict(by_src)))
    # 🔴 英文版一条都不该在里面 —— 那批是拡張新字体
    assert "en-edition" not in by_src, "🔴 判据碰到了英文版：那批是拡張新字体不是中文"
    dbtool.sample_check([(w, k, t) for _i, w, k, t in hit[::max(1, len(hit) // 16)]],
                        14, ("词条", "关系", "被挂起的目标"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return
    with dbtool.session("ja-relation-chinese-targets", expect={}, invalidates=[]) as s:
        s.executemany("UPDATE sense_relation SET hidden=1 WHERE id=?",
                      [(i,) for i, *_ in hit])


if __name__ == "__main__":
    main()
