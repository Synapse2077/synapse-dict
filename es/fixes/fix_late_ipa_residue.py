#!/usr/bin/env python3
"""`fix_ipa_residue` 的 trill／initr 两族，在**它之后才进库的行**上再跑一遍。es，2026-10-29（BACKLOG B28）。

═══ 缺陷 ═══
07-31 的 `fix_ipa_residue.py` 修的是当时的 `dict.phonetic`。之后西语版收词（08 月）与豆包补音标又带进来：
    `diarrhea djaˈrɾea`、`R.I.P. ˈeɾre ˈi ˈpe`（rɾ/ɾr 双颤音符）
    `Rhodesia del Norte ɾoˈdesja …`、`rhinoceronte ɾinoθeˈɾonte`（词首 ɾ 应为颤音 r）
这些词没有读音行，页面退回印 `dict.phonetic`；回归闸 A5/A6 只在 `pronunciation` 上判红，一直是绿的。

═══ 判据 ═══
一个字都不在这里写 —— import `fix_ipa_residue.FAMS`（找行）与 `propose`（给新值）。
`propose` 给不出的（词数与音标段数不符、单字母 `r`/`R` 是字母名）**不动**，列出来交回归闸的已接受基线。
原脚本写库不走 `dbtool`（建在闸门之前），所以不重跑它，只借判据。

跑（在仓库根）：
    python3 -u es/fixes/fix_late_ipa_residue.py            # 干跑
    python3 -u es/fixes/fix_late_ipa_residue.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import sqlite3

import dbtool
import paths
from fix_ipa_residue import FAMS, propose

FAMILIES = ("trill", "initr")


def plan(con):
    ok, skip = [], []
    for fam in FAMILIES:
        for wid, word, cur in con.execute(
                "SELECT id, word, phonetic FROM dict WHERE " + FAMS[fam][1]):
            new, why = propose(fam, word, cur)
            (ok if new and new != cur else skip).append((fam, wid, word, cur, new, why))
    return ok, skip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok, skip = plan(con)
    con.close()
    print("■ 迟到的 trill／initr 残留：修 %d 条，不动 %d 条" % (len(ok), len(skip)))
    for fam, _wid, w, cur, new, why in ok:
        print("   %-6s %-22s %-32s → %s" % (fam, w, cur, new))
    for fam, _wid, w, cur, _new, why in skip:
        print("   不动 %-6s %-18s %-30s %s" % (fam, w, cur, why))
    if not a.apply or not ok:
        print("\n（干跑。加 --apply 才写库）" if ok else "\n（无事可做）")
        return
    with dbtool.session("late-ipa-residue", expect={"phonetic": 0}) as s:
        for _f, wid, _w, _c, new, _y in ok:
            s.execute("UPDATE dict SET phonetic=? WHERE id=?", (new, wid))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left, _ = plan(con)
    con.close()
    print("\n■ 写后回核：仍待修 %d 条（期望 0）" % len(left))
    if left:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
