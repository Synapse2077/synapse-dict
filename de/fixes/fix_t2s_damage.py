#!/usr/bin/env python3
"""B25：09-18 两次**整段** OpenCC 繁→简改错的中文释义，按安全判据从原文重算。de，2026-10-29。

═══ 缺陷 ═══
`fix_traditional_to_simplified.py` 与 `backfill_blank_from_zh.py`（09-18）都对中文整段 t2s。
OpenCC 在**本来就是简体**的文本上会改错：生僻字转成扩展平面字形（`宽翅鵟→宽翅𫛭`、`二噁英→二𫫇英`，
多数字体是豆腐块）、歧义字（`覆上→复上`、`乾卦→干卦`）。证据层原样留着原文，所以能精确找回。

═══ 判据 ═══
一条不在这里写 —— `fix_traditional_to_simplified.t2s`（安全版）与 `t2s_opencc`（复现历史用）。
每行中文找原文：模型答案 `data/work/de/defs/def_zh.jsonl`（按 sense_id）、证据层 `sense_src`（中文版，
连同回填脚本的 `clean_gloss` 重算出的那一段）。
    现值 == 原文                         ⇒ 没被转过，不动
    现值 == t2s_opencc(原文) ≠ t2s(原文) ⇒ **被整段转错了**，改成 t2s(原文)
    哪个原文都对不上                     ⇒ 不动（1.5a 那 10,122 条没进证据层，证明不了，单独计数）

跑（在仓库根）：
    python3 -u de/fixes/fix_t2s_damage.py            # 干跑
    python3 -u de/fixes/fix_t2s_damage.py --apply
"""
import sys as _sys
import pathlib as _pl
_HERE = _pl.Path(__file__).resolve().parent
_sys.path.insert(0, str(_HERE.parent))
_sys.path.insert(0, str(_HERE.parent / "pipeline"))
_sys.path.insert(0, str(_HERE))

import argparse
import collections
import json
import sqlite3

import dbtool
import paths
from fix_traditional_to_simplified import t2s, t2s_opencc
from backfill_blank_from_zh import clean_gloss

ANSWERS = [paths.ROOT / "data" / "work" / "de" / "defs" / "def_zh.jsonl"]


def originals(con):
    orig = collections.defaultdict(set)
    for f in ANSWERS:
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if d.get("zh"):
                orig[int(d["id"])].add(d["zh"])
    for sid, t, w in con.execute("SELECT x.sense_id, x.text, d.word FROM sense_src x JOIN dict d ON d.id=x.word_id "
                                 "WHERE x.lang='zh' AND x.sense_id IS NOT NULL"):
        if t:
            orig[sid].add(t)
            for part in [x for x in t.split("\n") if x.strip()] or [t]:
                z = clean_gloss(part, w)[0]
                if z:
                    orig[sid].add(z)
    return orig


def plan(con):
    orig = originals(con)
    todo, st = [], collections.Counter()
    for rid, sid, text, src in con.execute("SELECT rowid, sense_id, text, src FROM sense_gloss WHERE lang='zh'"):
        cands = orig.get(sid, ())
        if text in cands:
            st["没被转过"] += 1
            continue
        hit = sorted(o for o in cands if t2s_opencc(o) == text)
        if not hit:
            st["对不上原文（证明不了）"] += 1
            continue
        new = t2s(hit[0])
        if new == text:
            st["被转过·转对了"] += 1
        else:
            st["被转过·🔴转错了"] += 1
            todo.append((rid, text, new, src))
    return todo, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    assert paths.DB.name == "synapse-dict-de.sqlite", paths.DB
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo, st = plan(con)
    con.close()
    print("■ B25 整段繁→简改错（de sense_gloss）")
    for k, v in st.most_common():
        print("   %-22s %9s" % (k, format(v, ",")))
    for rid, old, new, src in todo:
        print("   %-12s %-28s → %s" % (src[:12], old[:28], new[:40]))
    if not a.apply or not todo:
        print("\n（干跑。加 --apply 才写库）" if todo else "\n（无事可做）")
        return
    with dbtool.session("de-fix-t2s-damage", expect={}) as s:
        s.executemany("UPDATE sense_gloss SET text=? WHERE rowid=?", [(n, r) for r, _o, n, _s in todo])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left, _ = plan(con)
    con.close()
    print("\n■ 写后回核：仍转错 %d 条（期望 0）" % len(left))
    if left:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
