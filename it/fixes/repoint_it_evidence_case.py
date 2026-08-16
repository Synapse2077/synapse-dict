#!/usr/bin/env python3
"""把未裁决的意语证据重新指到**精确大小写**的 dict 行。2026-08-13，阶段 3 收尾。

═══ 缺陷怎么来的 ═══
阶段 1.5 灌意语证据时，库里还没拆大小写，`word_id` 是按 `w.lower()` 查的
⇒ dump 里的 `Angola` 挂到了 `angola` 那行。
阶段 3a 拆行后，`split_case_forms.py` 把 **已裁决**（`sense_id` 非空）的证据
跟着义项搬到了新行 `Angola`，但 **未裁决**（`sense_id IS NULL`）的没搬 ——
于是同一批证据里两种状态并存，外锚闸报出 184 条（改用精确大小写复刻后暴涨到 1,430，
正说明**不一致的是数据不是尺子**）。

⇒ 本脚本把未裁决的那些也指到精确大小写的行。`src_ref` 里带着 dump 的真实大小写，
   是确定性的凭据，不用猜。

用法（在 it/ 目录下）：
    python3 fixes/repoint_it_evidence_case.py            # 干跑
    python3 fixes/repoint_it_evidence_case.py --apply
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402


def plan(con):
    words = {}
    for wid, w in con.execute("SELECT id, word FROM dict"):
        words[w] = wid
    moves, stat = [], Counter()
    for xid, wid, ref, sid in con.execute(
            "SELECT id, word_id, src_ref, sense_id FROM sense_src WHERE src='it-edition'"):
        w0 = ref[len("kk-it:"):].rsplit("#", 1)[0].rsplit(":", 1)[0]
        exact = words.get(w0)
        if exact is None or exact == wid:
            stat["已经指对了 / 没有精确大小写行"] += 1
            continue
        if sid is not None:
            stat["🔴 已裁决的却指错了（不该发生）"] += 1
            continue
        stat["✅ 未裁决、要改指到精确大小写行"] += 1
        moves.append((exact, xid))
    return moves, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    moves, stat = plan(ro)
    for k, v in stat.most_common():
        print("   %-38s %9s" % (k, f"{v:,}"))
    ro.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("repoint-it-evidence", expect={}) as s:
        s.executemany("UPDATE sense_src SET word_id=? WHERE id=?", moves)
    print("\n■ 已改指 %s 条" % f"{len(moves):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
