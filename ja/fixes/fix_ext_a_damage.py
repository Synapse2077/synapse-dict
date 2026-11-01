#!/usr/bin/env python3
"""B29 顺带：09-16 整段 OpenCC 把**日文汉字**转成了扩展 A 区字形。ja，2026-10-30。

═══ 缺陷 ═══
B25 的安全判据只拦「目标字不在 BMP」，而扩展 A（U+3400–4DBF）在 BMP 里 ⇒ 漏网：
    八重樫（姓氏）→ 八重㭴     樫本 → 㭴本     樫羽 → 㭴羽     例句「八重樫先生」×2、「樫手」（朝鲜陶钵名）
    象棋的「車、俥」→「车、伡」（红方的车，简体棋书也写「俥」）
⚠️ **不能写成通用判据**：扩展 A 的目标字里有一批正是规范简体（`鸊鷉→䴙䴘`、`鴷→䴕`），B29 有意转过去的。
⇒ 逐条裁决的清单，每条带证据。

═══ 证据 ═══
三条义项：模型答案 `data/work/ja/translate/defs.jsonl` 写的就是 `八重樫`／`樫本`／`樫羽`（库里的「（姓氏）」是后面加的）。
两条例句：日语原文 `八重樫先生`（英译 Yaegashi Sensei）。一条例句：原文 `樫手`。象棋那条：词头 `騎兵`，川中岛将棋。
只换那一个字，整行其余一个字不动。

跑（在仓库根）：
    python3 -u ja/fixes/fix_ext_a_damage.py            # 干跑
    python3 -u ja/fixes/fix_ext_a_damage.py --apply
"""
import sys as _sys
import pathlib as _pl
_HERE = _pl.Path(__file__).resolve().parent
_sys.path.insert(0, str(_HERE.parent))

import argparse
import sqlite3

import dbtool
import paths

# (表, rowid, 错字, 正字)
FIX = [("sense_gloss", 223006, "㭴", "樫"), ("sense_gloss", 238221, "㭴", "樫"),
       ("sense_gloss", 267508, "㭴", "樫"),
       ("example_gloss", 32638, "㭴", "樫"), ("example_gloss", 32691, "㭴", "樫"),
       ("example_gloss", 63345, "㭴", "樫"),
       ("sense_gloss", 85047, "伡", "俥")]
BAD = "㭴伡"


def plan(con):
    out = []
    for t, rid, bad, good in FIX:
        r = con.execute("SELECT text FROM %s WHERE rowid=? AND lang='zh'" % t, (rid,)).fetchone()
        if r and bad in r[0]:
            out.append((t, rid, r[0], r[0].replace(bad, good)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = plan(con)
    con.close()
    for t, rid, old, new in todo:
        print("   %-13s %6d  %s\n                       → %s" % (t, rid, old[:50], new[:50]))
    print("■ 要改 %d 行（清单 %d 条）" % (len(todo), len(FIX)))
    if not a.apply or not todo:
        return
    with dbtool.session("ja-fix-ext-a-damage") as s:
        for t in ("sense_gloss", "example_gloss"):
            s.executemany("UPDATE %s SET text=? WHERE rowid=?" % t,
                          [(new, rid) for tt, rid, _o, new in todo if tt == t])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = sum(1 for t in ("sense_gloss", "example_gloss") for (x,) in
               con.execute("SELECT text FROM %s WHERE lang='zh'" % t) if any(c in x for c in BAD))
    print("■ 写后回核：库里仍有 `㭴`／`伡` %d（期望 0）" % left)
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
