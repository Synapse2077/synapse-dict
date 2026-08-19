#!/usr/bin/env python3
"""把词头的假「阴阳性」按义项级真值收回来。2026-08-17。

═══ 用户会看到什么 ═══
    abate   词头徽标【名词 · 阴阳性】
            义项 1~5 全是「il 阳」
⇒ **同一屏自相矛盾**。`abbondanza` 同病（词头阴阳性 / 5 条义项全「la 阴」）。

═══ 根因 ═══
与 `drop_folded_pos.py` 同一个：`build.py:330` 的 `key = word.lower()` 折叠大小写，
`Abate`（姓氏）的性别并进了 `abate`（修道院院长，阳）⇒ 并集 `mf`。
折叠来源占 1,122 / 2,045；另 923 行折叠源已不在库里，但症状与修法相同。

═══ 判据 ═══
`dict.gender = 'mf'` 且**本行**可见义项的性别**全体一致**为单一值 g ⇒ 改成 g。

    🔴 义项跨性别的 133 行**不动** —— 词头粗分 `mf`、义项细分，是 2026-08-12 定的
       展示约定（`il fine` 目的 / `la fine` 结尾），那不是缺陷。
    ⚠️ 本行没有义项级性别的 13,605 行**不动**：无从判定 ≠ 该改。
    ⚠️ 只处理 `mf → 单一值`。另有 133 行是别的形状（`dict.gender='m'` 而义项说 `f` 之类），
       判据不同、风险不同，记账不动。

用法（在 it/ 目录下）：
    python3 fixes/fix_folded_gender.py            # 干跑
    python3 fixes/fix_folded_gender.py --apply
    python3 fixes/fix_folded_gender.py --verify
    python3 fixes/fix_folded_gender.py --mutate
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402


def sense_gender(con):
    """→ {word_id: 可见义项上出现过的性别集合}"""
    g = defaultdict(set)
    for wid, x in con.execute(
            "SELECT word_id, gender FROM sense "
            "WHERE gender IS NOT NULL AND gender <> '' AND COALESCE(hidden,0)=0"):
        g[wid].add(x)
    return g


def decide(head, senses):
    """判据本体。→ 应有的性别，或 None 表示不动。闸与写入共用这一个函数。"""
    if head != "mf" or not senses:
        return None
    if len(senses) != 1:
        return None                     # 义项跨性别：词头粗分 mf 是对的
    only = next(iter(senses))
    return None if only == "mf" else only


def scan(con):
    sg = sense_gender(con)
    out = []
    for wid, w, g in con.execute("SELECT id, word, gender FROM dict WHERE gender IS NOT NULL"):
        new = decide(g, sg.get(wid))
        if new:
            out.append((wid, w, g, new))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    sg = sense_gender(con)
    left = scan(con)
    keep_mf = sum(1 for wid, g in con.execute("SELECT id, gender FROM dict WHERE gender='mf'")
                  if sg.get(wid) and len(sg[wid]) > 1)
    other = sum(1 for wid, g in con.execute(
        "SELECT id, gender FROM dict WHERE gender IS NOT NULL AND gender <> 'mf'")
        if sg.get(wid) and g not in sg[wid])
    empty = con.execute("SELECT count(*) FROM dict WHERE gender = ''").fetchone()[0]
    checks = [
        ("🔴 义项一致却标 mf 的已清零", len(left), 0),
        ("🔴 没有把 gender 写成空串", empty, 0),
        # 🔴 这条防的是判据写反：跨性别的词头必须仍是 mf
        ("🔴 义项跨性别的仍保持 mf（2026-08-12 展示约定）", keep_mf, 133),
        ("（记账）非 mf 形状的对不上，判据不同，不动", other, other),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-44s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def mutate():
    print("\n═══ 变异验证 ═══")
    cases = [
        ("义项全阳 ⇒ 词头改阳", decide("mf", {"m"}), "m"),
        ("义项全阴 ⇒ 词头改阴", decide("mf", {"f"}), "f"),
        ("🔴 义项跨性别 ⇒ 不动（il fine / la fine）", decide("mf", {"m", "f"}), None),
        ("🔴 本行没有义项级性别 ⇒ 不动", decide("mf", set()), None),
        ("🔴 词头本来就是单一性别 ⇒ 不归本步", decide("m", {"f"}), None),
        ("🔴 义项自己就是 mf ⇒ 不动", decide("mf", {"mf"}), None),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-46s → %r" % ("✅" if good else "🔴", name, got))
        if not good:
            print("        期望 %r" % (want,))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = scan(ro)
    f = lambda x: format(x, ",")
    print("■ 要改的 %s 行" % f(len(rows)))
    for k, v in Counter(r[3] for r in rows).most_common():
        print("   mf → %-4s %s" % (k, f(v)))
    for wid, w, o, n in rows[:8]:
        print("   %-22s %s → %s" % (w[:22], o, n))
    if not a.apply or not rows:
        ro.close()
        if not a.apply:
            print("\n(未加 --apply，不写库)")
        return 0
    ro.close()
    with dbtool.session("fix-folded-gender", expect={"__rows__": 0}) as s:
        s.executemany("UPDATE dict SET gender=? WHERE id=?", [(n, wid) for wid, _, _, n in rows])
    print("\n■ 已改 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
