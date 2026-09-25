#!/usr/bin/env python3
"""给阶段 8 补收的那批新词**定向补写**关系边。2026-09-24。

═══ 为什么不能 `build_relation_layer.py --replace` ═══
`sense_relation` 现在有**三个写入方**：
    建库那一支（`build_relation_layer.py`）                192,530
    `fix_meta_gloss.py` 的 `hanja_spelling`                51,254  🔴 **不可重跑**
    `harvest_relations_from_examples.py`                  10,417
整表重建会把后两批**静默抹掉**，而 `build_relation_layer` 的 `expect` 只按自己的行数算
⇒ **闸不会响**。`fix_meta_gloss` 那批尤其回不来：它消费的 `sense_gloss` 元描述行
已经删掉了（`[[replay-scripts-undo-fixes]]`：A 层搬到 B 层前先问 B 被修过吗）。
⇒ 已在 `build_relation_layer.py` 里加了拦截，本脚本是它指向的那条路。

═══ 判据一个字不重抄 ═══
本脚本 **import `build_relation_layer.scan`** —— 抽取逻辑、kind 映射、去重键
全部是它那一份。本脚本只做两件它不做的事：
  ① 把结果**过滤到这批新词**；② `INSERT OR IGNORE`（库里已有的边不动）。

═══ 这批新词是谁 ═══
判据按**含义**取，不按 id 区间（`dict.id` 是 AUTOINCREMENT，行数 ≠ 最大 id，
我用行数当边界当场误报过 13 条）：
    只有 `ko-edition` 的词条，且证据层一条都没有 ⇒ 正是 K13 收的那 13,062 个。

跑（在仓库根）：
    python3 -u ko/pipeline/topup_relations_new_words.py
    python3 -u ko/pipeline/topup_relations_new_words.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import sqlite3

import dbtool
import paths
from build_relation_layer import scan

f = lambda n: format(n, ",")

NEW_WORDS_SQL = """
    SELECT e.word_id FROM entry e
     WHERE e.src = 'ko-edition'
       AND NOT EXISTS (SELECT 1 FROM entry e2
                        WHERE e2.word_id = e.word_id AND e2.src <> 'ko-edition')
       AND NOT EXISTS (SELECT 1 FROM sense_src x WHERE x.word_id = e.word_id)
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
    inentry = {r[1]: r[0] for r in con.execute("SELECT id, src_ref FROM entry")}
    sense_of = {}
    for wid, eid, rank, sid in con.execute(
            "SELECT word_id, entry_id, rank, id FROM sense"):
        sense_of[(wid, eid, rank - 1)] = sid
    new = {r[0] for r in con.execute(NEW_WORDS_SQL)}
    have = {(w, k, t) for w, k, t in con.execute(
        "SELECT word_id, kind, target FROM sense_relation")}
    before = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    con.close()
    print("■ 本步新收的词形 %s 个" % f(len(new)))

    rows, stat = scan(indict, inentry, sense_of)
    print("■ 建库那份抽取器扫出 %s 条边（全库口径）" % f(len(rows)))
    mine = [r for r in rows if r[0] in new]
    print("   ├ 落在新词上的        %s" % f(len(mine)))
    fresh = [r for r in mine if (r[0], r[2], r[3]) not in have]
    print("   └ **库里还没有的**     %s" % f(len(fresh)))
    kinds = collections.Counter(r[2] for r in fresh)
    for k, v in kinds.most_common(10):
        print("        %-18s %6s" % (k, f(v)))
    if not a.apply:
        print("\n（这是 dry 跑。加 --apply 才写库）")
        return

    with dbtool.session(
            "ko-topup-relations-new-words",
            expect={"#sense_relation": len(fresh),
                    "sense_relation.target": len(fresh)},
            invalidates=[
                "空白页判据：这批新词此前靠「有读音」一条撑着，现在有 %s 条带关系了 —— "
                "空白页数**不会变**（读音那一条已经让它们不空白），但**原因变了**，"
                "验收时别把它算成新修好的" % f(len(fresh)),
            ]) as s:
        for i in range(0, len(fresh), 20000):
            s.executemany(
                "INSERT OR IGNORE INTO sense_relation "
                "(word_id, sense_id, kind, target, tags, src, src_ref)"
                " VALUES (?,?,?,?,?,?,?)", fresh[i:i + 20000])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n■ 写后回核（从库里重算）")
    red = 0
    for name, got, want in [
            ("sense_relation 行数", q("SELECT COUNT(*) FROM sense_relation"),
             before + len(fresh)),
            ("🔴 `hanja_spelling` 还在（不可重跑的那批）",
             q("SELECT COUNT(*) FROM sense_relation WHERE kind='hanja_spelling'"),
             51_254),
            ("🔴 起点不在 dict 的边",
             q("SELECT COUNT(*) FROM sense_relation r WHERE NOT EXISTS"
               "(SELECT 1 FROM dict d WHERE d.id=r.word_id)"), 0),
            ("新词里有关系边的词形", q(
                "SELECT COUNT(DISTINCT word_id) FROM sense_relation "
                "WHERE word_id IN (%s)" % NEW_WORDS_SQL),
             len({r[0] for r in mine}))]:
        mark = "✅" if got == want else "🔴"
        red += got != want
        print("   %s %-40s %9s  期望 %9s" % (mark, name, f(got), f(want)))
    con.close()
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


if __name__ == "__main__":
    main()
