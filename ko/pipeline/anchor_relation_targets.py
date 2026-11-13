#!/usr/bin/env python3
"""K20：关系边落到具体词条 —— 派生列 `sense_relation.target_entry_id`。ko，2026-11-11。**不花钱。**

判据全在 `criteria.relation_target_entry`，本文件一条都不写。**这一列只由本脚本写**：
任何往 `sense_relation` 写行、或改了 `entry.hanja`／`sense.hidden` 的脚本跑完都要再跑一次本脚本；回归闸 R35 是它的不动点
（库里的值 ≠ 判据重算 ⇒ 红），所以忘了跑会在写库后当场被点名。

    python3 -u ko/pipeline/anchor_relation_targets.py            # 干跑：分布 ＋ 样本
    python3 -u ko/pipeline/anchor_relation_targets.py --apply
"""
import argparse
import collections
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
import criteria                                                 # noqa: E402

F = lambda n: format(n, ",")                                    # noqa: E731


def plan(con):
    """→ (updates [(新值, id)], 统计, 样本)。回归闸 R35 import 它数「还剩几条没同步」（应为 0）。"""
    by_word = collections.defaultdict(list)
    by_hanja = collections.defaultdict(list)
    for eid, wn, h in con.execute("SELECT e.id, d.word_norm, e.hanja FROM entry e JOIN dict d ON d.id = e.word_id"):
        by_word[wn].append((eid, h))
        if h:
            by_hanja[h].append(eid)
    vis = {r[0] for r in con.execute("SELECT DISTINCT entry_id FROM sense WHERE hidden = 0")}
    has_col = "target_entry_id" in {c[1] for c in con.execute("PRAGMA table_info(sense_relation)")}
    up, st, eg = [], collections.Counter(), collections.defaultdict(list)
    for rid, t, tn, kind, cur, sw in con.execute(
            "SELECT r.id, r.target, r.target_norm, r.kind, %s, d.word FROM sense_relation r "
            "JOIN dict d ON d.id = r.word_id" % ("r.target_entry_id" if has_col else "NULL")):
        new, rule = criteria.relation_target_entry(t, tn, kind, lambda w: by_word.get(w, ()),
                                                   lambda h: by_hanja.get(h, ()), vis.__contains__, sw)
        if new is not None:
            st["锚定·" + rule] += 1
            if len(eg[rule]) < 6:
                eg[rule].append((t, tn, new))
        if new != cur:
            up.append((new, rid))
    st["要改"] = len(up)
    return up, st, eg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    up, st, eg = plan(con)
    print("■ K20 关系边落到具体词条")
    for k in sorted(st):
        print("   %-20s %8s" % (k, F(st[k])))
    for rule, xs in eg.items():
        for t, tn, e in xs:
            w, h = con.execute("SELECT d.word, e.hanja FROM entry e JOIN dict d ON d.id=e.word_id WHERE e.id=?",
                               (e,)).fetchone()
            print("   [%s] %-14s 词形落点 %-8s → 词条 %s %s(%s)" % (rule, t, tn, e, w, h))
    has_col = "target_entry_id" in {c[1] for c in con.execute("PRAGMA table_info(sense_relation)")}
    have = con.execute("SELECT COUNT(*) FROM sense_relation WHERE target_entry_id IS NOT NULL").fetchone()[0] \
        if has_col else 0
    con.close()
    if not a.apply:
        print("\n(干跑。)")
        return
    import dbtool
    want = sum(v for k, v in st.items() if k.startswith("锚定·"))
    with dbtool.session("k20-anchor-relation-targets",
                        expect={"sense_relation.target_entry_id": want - have}) as s:
        if not has_col:
            s.execute("ALTER TABLE sense_relation ADD COLUMN target_entry_id INTEGER")
        s.executemany("UPDATE sense_relation SET target_entry_id = ? WHERE id = ?", up)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = plan(con)[0]
    con.close()
    if left:
        raise SystemExit("🔴 写后重算还剩 %d 条不一致" % len(left))
    print("✓ 写完，重算一致")


if __name__ == "__main__":
    main()
