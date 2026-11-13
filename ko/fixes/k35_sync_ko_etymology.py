#!/usr/bin/env python3
"""K35 的下游同步：补了 `hanja_spelling` 之后，韩文版词源里「한자 X.」那批变成重复 ⇒ 按收割器自己的规则删掉。2026-11-07。

═══ 为什么 ═══
`harvest_ko_etymology.py`（K36②）的判据 `criteria.ko_etymology`：词源正文只有「한자 X」、而这一页已经印着 X
（`entry.hanja`／`hanja_spelling`／`alt_hanja`）⇒ **不收**（同一个汉字形一页印两遍）。
K35 给 75 个词补了 `hanja_spelling`，其中 41 个词的韩文版词源正文**恰好就是那一句** ⇒ 现在收割器不要它们了，
库里还留着 ⇒ 外锚闸「库里有·追不回源头 41」当场判红（它是对的）。
⚠️ 收割器只做首次收录（已有行就停机），所以这里只做**差集同步**：库里有而收割器不产出的那批。

═══ 删之前逐条断言（任一不满足就停机）═══
① 差集只出现在「库里有」这一侧：收割器产出而库里没有的 = 0
② 每一行的正文按 `criteria.ko_etymology` 判，结果是「不收·汉字写法已在页面上」
③ 每一行身上没有 `etymology_gloss`（有的话那是花过钱的译文，要另议）
⇒ 信息零损失：被删的那个汉字形就印在同一页的汉字表记里。

跑（在仓库根）：
    python3 -u ko/fixes/k35_sync_ko_etymology.py            # 干跑
    python3 -u ko/fixes/k35_sync_ko_etymology.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import sqlite3

import dbtool
import paths
import harvest_ko_etymology as HKE
from criteria import ko_etymology


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, _st, _s = HKE.harvest(con)
    want = {r[6] for r in rows}
    have = {ref: (i, w, t) for i, ref, w, t in con.execute(
        "SELECT e.id, e.src_ref, d.word, e.text FROM etymology e JOIN dict d ON d.id=e.word_id "
        "WHERE e.edition=?", (HKE.EDITION,))}
    miss = [r for r in want if r not in have]
    extra = [have[r] for r in sorted(have) if r not in want]
    known = HKE.known_hanja(con)
    print("■ 收割器产出 %d ／ 库里 %d ⇒ 库里多 %d、库里缺 %d" % (len(want), len(have), len(extra), len(miss)))
    if miss:
        raise SystemExit("🔴 ① 收割器产出而库里没有 %d 行 —— 这不是本脚本的场景" % len(miss))
    bad = []
    for i, w, t in extra:
        _txt, why = ko_etymology([t], known.get(w, set()))
        if why != "不收·汉字写法已在页面上":
            bad.append((i, w, t, why))
    if bad:
        raise SystemExit("🔴 ② 有 %d 行不是「汉字写法已在页面上」：%r" % (len(bad), bad[:5]))
    ids = [x[0] for x in extra]
    ng = con.execute("SELECT COUNT(*) FROM etymology_gloss WHERE etymology_id IN (%s)"
                     % ",".join("?" * len(ids)), ids).fetchone()[0] if ids else 0
    con.close()
    if ng:
        raise SystemExit("🔴 ③ 这批行身上挂着 %d 条译文 —— 先另议" % ng)
    for i, w, t in extra[:8]:
        print("   %-8s %s" % (w, t))
    if not extra:
        print("■ 库已与收割器一致，什么都不做")
        return 0
    if not a.apply:
        print("（干跑。加 --apply 才写库）")
        return 0
    with dbtool.session("ko-k35-sync-ko-etymology", expect={"#etymology": -len(ids)},
                        invalidates=[]) as s:
        s.executemany("DELETE FROM etymology WHERE id=?", [(i,) for i in ids])
    return 0


if __name__ == "__main__":
    _sys.exit(main())
