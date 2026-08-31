#!/usr/bin/env python3
"""接义项级关系时顺出来的一族：**同一条关系在词条级和义项级各存了一份**。2026-08-31。

═══ 怎么发现的 ═══
不是闸发现的，是**接展示层**发现的（`[[it-display-layer-stage8]]` 第三次兑现）：
库里 153,452 条关系有 71,017 条带 `sense_id`，而展示层查的是 `WHERE word_id = ?`
—— 义项归属整个丢掉。把它接上（`pinta` 8 个义项的近义词不再拍平成一列）之后，
新加的契约闸断言当场红了：

    bater：词条级重复了义项级的 1 条（synonym:colidir）
    por  ：词条级重复了义项级的 9 条（synonym:a favor de）

⇒ 读者会在同一页上看到同一个近义词两遍：一遍在义项下面，一遍在页尾。

🔴 **回归闸 H2 的名字正是「只差 sense_id 的 NULL 的内容重复」，而它报 0** ——
   它的 SQL 按 `GROUP BY word_id, COALESCE(sense_id,-1), kind, target` 分组，
   **把 NULL 当成了区分键**，于是 NULL 行与义项行永远落在不同组里。
   闸在报自己的 bug（`[[fix-regression-and-gate]]` 第三种机制）。已一并修正。

═══ 判据（按含义）═══
「这条词条级关系**说的话，已经有一条更具体的说过了**」：
同 `(word_id, kind, target)` 已经挂在**某个义项**上 ⇒ 词条级那条不带新信息。

⚠️ **不删行、加 `hidden` 列**（照 `example.hidden` / `sense.hidden` 的先例，
   `[[prefer-reversible-designs]]`）：`UPDATE … SET hidden=0` 一条 SQL 全撤。
⚠️ 反方向的 69,527 条**一个字不动** —— 它们没有义项归属，是页尾那一块唯一的内容。

用法（在 pt/ 目录下）：
    python3 fixes/hide_dup_word_level_relations.py
    python3 fixes/hide_dup_word_level_relations.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

DUP = """
SELECT r.id, d.word, r.kind, r.target FROM sense_relation r JOIN dict d ON d.id=r.word_id
 WHERE r.sense_id IS NULL AND COALESCE(r.hidden,0)=0 AND EXISTS(
   SELECT 1 FROM sense_relation q WHERE q.word_id=r.word_id AND q.kind=r.kind
     AND q.target=r.target AND q.sense_id IS NOT NULL)
"""


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    has = con.execute(
        "SELECT COUNT(*) FROM pragma_table_info('sense_relation') WHERE name='hidden'"
    ).fetchone()[0]
    if not has and not a.apply:
        print("⚠️ `sense_relation` 还没有 `hidden` 列，--apply 时会先加列")
    rows = con.execute(DUP.replace("COALESCE(r.hidden,0)=0 AND ", "") if not has
                       else DUP).fetchall()
    f = lambda n: format(n, ",")
    left = con.execute(
        "SELECT COUNT(*) FROM sense_relation r WHERE r.sense_id IS NULL AND NOT EXISTS("
        "  SELECT 1 FROM sense_relation q WHERE q.word_id=r.word_id AND q.kind=r.kind"
        "    AND q.target=r.target AND q.sense_id IS NOT NULL)").fetchone()[0]
    print("■ 词条级冗余（同词同类同目标已挂在某义项上）%s 条" % f(len(rows)))
    print("■ 词条级保留（没有义项归属，页尾那块唯一的内容）%s 条" % f(left))
    print("\n■ 抽 10 条看：")
    for _i, w, k, t in rows[:10]:
        print("   %-20s %-10s %s" % (w[:20], k, t[:34]))
    con.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    # ⚠️ 不传 `expect`：本步**只 UPDATE 不增删行**，`dbtool` 的 expect 说的是
    #    「dict 某列的增量」或「某表的行数增量」，这里两样都是 0 —— 传个假键
    #    会让闸看起来在守而其实没守（`SELECT 1` 那个毛病）。真正守它的是
    #    契约闸新加的那条「同一条关系印了两遍」。
    with dbtool.session("hide-pt-dup-word-relations") as s:
        if not has:
            s.execute("ALTER TABLE sense_relation ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
        s.executemany("UPDATE sense_relation SET hidden=1 WHERE id=?",
                      [(i,) for i, _w, _k, _t in rows])
    print("\n✓ 隐 %s 条（`UPDATE sense_relation SET hidden=0` 可全撤）" % f(len(rows)))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
