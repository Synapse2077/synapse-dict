#!/usr/bin/env python3
"""规则 G2P 生成的音标里，字母 x 被写成 `ɡs`。es，2026-10-29（BACKLOG B28）。

═══ 缺陷 ═══
`fix_x_gs.py`（08-02）定了约定：x 写 /ks/、词首 x 写 /s/（西语版写 ks 7,311、ɡs 0），修了源头来的音标。
**但没修规则 G2P `b_ipa.py`**：它的韵尾浊化（kaikki 约定 p/t/k 在辅音前 → b/d/ɡ）把 x 拆出来的 `k`
也浊化了 ⇒ `taxi → ˈtaɡsi`。08-20 `ingest_missing_bases.py` 用它给补收的词头算音标，`ɡs` 又回来了
（`anfioxo → anˈfjoɡso`、`asfíxico → asˈfiɡsiko`）。这些词没有读音行，页面退回印 `dict.phonetic`。
回归闸 A1 一直判绿 —— 它只在 `pronunciation` 上判红（B28 本体）。

═══ 判据：两个独立信号一致才写 ═══
① 修好的 G2P（`b_ipa.word_to_ipa`，x 的 `k` 不再浊化）重新生成；
② `fix_x_gs.convert` 对旧值做的修正（数 x 段与 ɡs+ks 对齐，幂等）。
两边相同 ⇒ 写；不同或有一边给不出 ⇒ 不动，列出来。

跑（在仓库根）：
    python3 -u es/fixes/fix_rule_ipa_x.py            # 干跑
    python3 -u es/fixes/fix_rule_ipa_x.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import sqlite3

import dbtool
import paths
from b_ipa import word_to_ipa
from fix_x_gs import convert


def plan(con):
    ok, skip = [], []
    for wid, word, ph in con.execute(
            "SELECT id, word, phonetic FROM dict WHERE phonetic_src='rule' AND phonetic LIKE '%ɡs%'"):
        if "x" not in word.lower():
            continue                         # `párkings`/`gangsterismos`：ɡ 是字母 g 的真音
        a = convert(word, ph)
        g = word_to_ipa(word)
        b = g.strip("/") if g else None
        if a is None and (b is None or b == ph):
            continue                         # x 那处已是 ks，剩下的 ɡs 是 ng+s（`unboxings`）
        (ok if a and a == b else skip).append((wid, word, ph, a, b))
    return ok, skip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok, skip = plan(con)
    con.close()
    print("■ 规则音标里 x 写成 ɡs：两个信号一致 %d 条，不一致/给不出 %d 条" % (len(ok), len(skip)))
    for wid, w, ph, x, y in ok[:10]:
        print("   %-22s %-26s → %s" % (w, ph, x))
    for wid, w, ph, x, y in skip:
        print("   不动 %-18s %-26s convert=%s  g2p=%s" % (w, ph, x, y))
    if not a.apply or not ok:
        print("\n（干跑。加 --apply 才写库）" if ok else "\n（无事可做）")
        return
    with dbtool.session("rule-ipa-x", expect={"phonetic": 0}) as s:
        for wid, _w, _ph, new, _b in ok:
            s.execute("UPDATE dict SET phonetic=? WHERE id=?", (new, wid))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left, _ = plan(con)
    con.close()
    print("\n■ 写后回核：仍待修 %d 条（期望 0）" % len(left))
    if left:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
