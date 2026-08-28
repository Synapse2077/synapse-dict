#!/usr/bin/env python3
"""同一条义项上重复的法语原文，3 条。2026-08-27。

`pipeline/adjudicate_fr_defs.py --verify` 的闸 ④ 报出来的。

═══ 怎么来的 ═══
裁决那一步靠「(词形, clean(证据)) 在不在出版层」判重。这三条的证据里带着
**句中的** wiki 链接残渣，而出版层那一侧早被行级脚本修干净了：

    证据 clean → 'Classe dans laquelle on range plusieurs chose]]s qui…'
    出版层     → 'Classe dans laquelle on range plusieurs choses qui…'

两侧对不上 ⇒ 判重永远不命中 ⇒ 同一句法语被当成"还没出版"再挂一遍。
🔴 与 `fixes/reclean_published_fr_defs.py` 同一个根因的两个方向：
   那个是出版层带残渣、证据层干净；这个是证据层带残渣、出版层干净。
   两边都已由 `gloss_clean` 的 wiki 规则补齐（2026-08-27），**不会再产生**。
   这个脚本只清已经躺在库里的三条。

⚠️ 只删**逐字完全相同**的那一份，`seq` 大的走。近似的一个字不碰 ——
   同一条义项挂两句不同的法语是合法的（法文版的第二种说法）。

用法（在 fr/ 目录下）：
    python3 -u fixes/drop_duplicate_glosses.py
    python3 -u fixes/drop_duplicate_glosses.py --apply
"""
import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402

f = lambda n: format(n, ",")


def plan(con):
    """→ [(sense_id, lang, kind, seq)]，每组只留 seq 最小的那份。"""
    grp = defaultdict(list)
    for sid, lang, kind, seq, txt in con.execute(
            "SELECT sense_id, lang, kind, seq, text FROM sense_gloss"):
        grp[(sid, lang, kind)].append((seq, txt))
    drop = []
    for (sid, lang, kind), rows in grp.items():
        seen = {}
        for seq, txt in sorted(rows):
            if txt in seen:
                drop.append((sid, lang, kind, seq, txt))
            else:
                seen[txt] = seq
    return drop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    drop = plan(con)
    print("■ 逐字重复、要删的 gloss 行：%s" % f(len(drop)))
    for sid, lang, kind, seq, txt in drop:
        w = con.execute("SELECT d.word FROM sense s JOIN dict d ON d.id=s.word_id "
                        "WHERE s.id=?", (sid,)).fetchone()[0]
        keep = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE sense_id=? "
                           "AND lang=? AND kind=?", (sid, lang, kind)).fetchone()[0]
        print("   %-16s sense=%-8d %s/%s seq=%d（该组共 %d 行，删后 %d）\n      %r"
              % (w, sid, lang, kind, seq, keep, keep - 1, txt[:90]))

    # 闸：删完每组必须还剩至少一行（不许把一条义项的释义删空）
    left = defaultdict(int)
    for sid, lang, kind, seq, txt in drop:
        left[(sid, lang, kind)] += 1
    bad = 0
    for (sid, lang, kind), n in left.items():
        tot = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE sense_id=? "
                          "AND lang=? AND kind=?", (sid, lang, kind)).fetchone()[0]
        if tot - n < 1:
            bad += 1
    print("\n  %s 闸：删完每组至少剩 1 行 —— 违反 %s / %s 组"
          % ("✅" if not bad else "🔴", f(bad), f(len(left))))
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if bad:
        return 1
    with dbtool.session("keep-v3-dedup-gloss",
                        expect={"#sense_gloss": -len(drop)}) as s:
        s.executemany("DELETE FROM sense_gloss WHERE sense_id=? AND lang=? "
                      "AND kind=? AND seq=?",
                      [(sid, lang, kind, seq) for sid, lang, kind, seq, _t in drop])
    print("✓ 删 %s 行" % f(len(drop)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
