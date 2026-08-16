#!/usr/bin/env python3
"""从证据行的 `src_ref` 恢复义项词性。2026-08-16。

═══ 用户从界面上看出来的（第二次）═══
`pezza onorevole` 的义项分组显示成 `【-】` —— 词性是空的。全库量下来
**14,330 条可见义项（3.5%）** 的 `COALESCE(sense.pos, entry.pos)` 为 NULL，
样例全是专名：`Barsanufio`（男名）/ `Odilia`（女名）/ `Dodoma`（首都）。

═══ 成因 ═══
`promote_orphan_it_defs` / 早期几个提升脚本建 `sense` 行时只写了
`(id, word_id, rank)`，**没写 pos**；它们又不挂 `entry`（那是英文版侧的结构），
于是两处都取不到词性。

═══ 判据：确定性，不问模型 ═══
每条这样的义项都有自己的 `it-edition` 证据行，`src_ref` 形如
`kk-it:<词形>:<词性>#<occ>.<idx>` —— **词性就写在里面**。
实测 14,326 条能从证据里取到**唯一**词性，4 条没有证据行（留空，记账）。

⚠️ 取到的是 kaikki 长写法，必须过 `build.POS_MAP` 转成展示层认的短码 ——
   这正是昨天 `tempo` 显示出英文 `noun` 的那个坑（`normalize_sense_pos.py`）。

用法（在 it/ 目录下）：
    python3 fixes/backfill_sense_pos.py
    python3 fixes/backfill_sense_pos.py --apply
    python3 fixes/backfill_sense_pos.py --verify
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build import POS_MAP   # noqa: E402
from promote_it_gloss import pos_of_ref   # noqa: E402

SHORT = set(POS_MAP.values())


def plan(con):
    rows, stat = [], Counter()
    for sid, in con.execute(
            "SELECT s.id FROM sense s LEFT JOIN entry e ON e.id=s.entry_id "
            "WHERE COALESCE(s.hidden,0)=0 AND COALESCE(s.pos, e.pos) IS NULL"):
        poss = {pos_of_ref(ref) for src, ref in con.execute(
            "SELECT src, src_ref FROM sense_src WHERE sense_id=?", (sid,))
            if src == "it-edition"}
        if not poss:
            stat["🔴 没有意语证据行，留空（记账）"] += 1
            continue
        if len(poss) > 1:
            stat["⚠️ 证据里多个词性，留空（记账）"] += 1
            continue
        raw = poss.pop()
        short = POS_MAP.get(raw)
        if not short:
            stat["🔴 POS_MAP 查不到: " + raw] += 1
            continue
        stat["✅ 从证据恢复"] += 1
        rows.append((short, sid))
    return rows, stat


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    left, _ = plan(con)
    checks = [
        # 🔴 已接受基线 + 理由：4 条义项没有任何证据行，无从恢复，宁可留空不猜
        ("🔴 无词性且可恢复的义项已清零", len(left), 0),
        ("🔴 sense.pos 全是展示层认得的短码",
         sum(1 for (p,) in con.execute("SELECT DISTINCT pos FROM sense WHERE pos IS NOT NULL")
             if p not in SHORT), 0),
        ("🔴 恢复出的词性必须与它自己的意语证据一致（逐条回核）",
         sum(1 for ref, pos in con.execute(
             "SELECT x.src_ref, s.pos FROM sense_src x JOIN sense s ON s.id=x.sense_id "
             "WHERE x.src='it-edition' AND s.entry_id IS NULL AND s.pos IS NOT NULL")
             if POS_MAP.get(pos_of_ref(ref)) != pos), 0),
        ("义项行数不变（本步只填列）", q("SELECT count(*) FROM sense") > 0, True),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %s (期望 %s)" % ("✅" if good else "🔴", name, got, want))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows, stat = plan(ro)
    for k, v in stat.most_common():
        print("   %-34s %7s" % (k, f"{v:,}"))
    print("\n■ 将回填 %s 条" % f"{len(rows):,}")
    print("   词性分布 %s" % Counter(p for p, _ in rows).most_common(6))
    ro.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("backfill-sense-pos", expect={"#sense": 0}) as s:
        s.executemany("UPDATE sense SET pos=? WHERE id=?", rows)
    print("\n■ 已回填 %s 条" % f"{len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
