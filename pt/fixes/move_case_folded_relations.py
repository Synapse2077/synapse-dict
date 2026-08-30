#!/usr/bin/env python3
"""阶段 7 逮到：大小写折叠残留 —— `alt_of` 关系留在小写词形上。2026-08-30。

═══ 怎么发现的 ═══
**阶段 7 的回归闸 B2 报的**。B2 断言「带 `alt_of` 的词形必须有可见义项」
（那正是阶段 2a 修的东西），红了 16 条。逐条读完不是 2a 的修复丢了，是另一族：

    leia   → Lia             而 `leia` 是 `ler` 的虚拟式
    cansas → Kansas          而 `cansas` 是 `cansar` 的第二人称单数
    minas  → Minas Gerais    而 `minas` 是 `mina` 的复数
    doe    → Diário Oficial…  而 `doe` 是 `doar` 的虚拟式（关系属于缩写 `DOE`）

⇒ `[[case-folding-contaminates-columns]]` 那一族：建库时 `word.lower()` 把大写专名
  的属性并进了小写词形；阶段 3a 把行拆开了，**但属性没跟着搬**。
  （那条记忆记的是 `pos` 3,558 行 + `gender` 2,045 行，`sense_relation` 是新的一处。）

═══ 判据（确定性，非启发式）═══
一条 `alt_of` 要搬，当且仅当同时满足：
  ① 它挂的词形**没有任何可见义项**（说明这条关系不属于它）
  ② 库里存在**恰好一个**大小写不同的同形词（`lower(word)` 相同）
  ③ 那个大写行上**还没有**同样的关系
⚠️ ② 要求「恰好一个」：多于一个就分不清该搬给谁 ⇒ **不搬，报出来**。

用法（在 pt/ 目录下）：
    python3 fixes/move_case_folded_relations.py
    python3 fixes/move_case_folded_relations.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402


def plan(con):
    todo, skip = [], []
    rows = con.execute(
        "SELECT r.id, r.word_id, d.word, r.kind, r.target FROM sense_relation r "
        "JOIN dict d ON d.id=r.word_id "
        "WHERE r.kind='alt_of' AND NOT EXISTS("
        "  SELECT 1 FROM entry e JOIN sense s ON s.entry_id=e.id "
        "  WHERE e.word_id=r.word_id)").fetchall()
    for rid, wid, w, kind, tgt in rows:
        cand = con.execute(
            "SELECT id, word FROM dict WHERE lower(word)=lower(?) AND word<>?",
            (w, w)).fetchall()
        if len(cand) != 1:
            skip.append((w, tgt, "同形词 %d 个，分不清搬给谁" % len(cand)))
            continue
        nid, nw = cand[0]
        if con.execute("SELECT 1 FROM sense_relation WHERE word_id=? AND kind=? "
                       "AND target=?", (nid, kind, tgt)).fetchone():
            skip.append((w, tgt, "%s 上已有同样的关系" % nw))
            continue
        todo.append((rid, wid, w, nid, nw, tgt))
    return todo, skip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo, skip = plan(con)
    con.close()
    print("■ 要搬的 alt_of 关系：%d 条" % len(todo))
    for _rid, _wid, w, _nid, nw, tgt in todo:
        print("   %-14s → %-24s  搬到  %s" % (w, tgt[:24], nw))
    if skip:
        print("\n■ 不搬（报出来，不猜）：%d 条" % len(skip))
        for w, tgt, why in skip:
            print("   %-14s → %-24s  %s" % (w, tgt[:24], why))
    if not todo or not a.apply:
        print("\n(未加 --apply，不写库)" if todo else "\n✓ 没有要改的")
        return 0
    with dbtool.session("fix-pt-case-folded-relations",
                        expect={"#sense_relation": 0}) as s:
        for rid, _wid, _w, nid, _nw, _t in todo:
            s.execute("UPDATE sense_relation SET word_id=? WHERE id=?", (nid, rid))
    print("\n✓ 已搬 %d 条" % len(todo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
