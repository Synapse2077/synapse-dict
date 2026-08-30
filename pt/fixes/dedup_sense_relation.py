#!/usr/bin/env python3
"""🔴 `sense_relation` 的 UNIQUE 对 NULL 行不生效 ⇒ 重跑一次就整批复制。2026-08-30。

═══ 缺陷本体 ═══
    CREATE TABLE sense_relation (... UNIQUE(word_id, sense_id, kind, target))
                                             ↑ 可空

**SQL 里 `NULL != NULL`** —— 只要 `sense_id IS NULL`，这条 UNIQUE **根本不约束**。
而词条级关系（各版的 `synonyms`/`antonyms` 长在词条上，不在义项上）**正好全是 NULL**，
占全表大头。⇒ `INSERT OR IGNORE` 一条都 IGNORE 不掉，每重跑一次复制一整份。

    实测：重跑收割器后 231,330 行里 **155,734 行是重复**
          `livre → antonym → dependente`  存了两条，`sense_id` 都是 NULL、`src` 都是 pt-edition

⚠️ **收割器内存里的 `seen` 集合防不住这个** —— 它只保证单次运行内不重复，
   跨运行要靠数据库约束，而那个约束是坏的。**「我这边去过重了」不等于「库里不会重」。**

═══ 为什么其余四张表没事（逐表查过，不是假设）═══
    sense_src / entry / inflection   UNIQUE(src_ref)        NOT NULL ✅
    example                          UNIQUE(word, text)     NOT NULL ✅
    audio                            UNIQUE(word, file)     NOT NULL ✅
    pronunciation                    UNIQUE(word_id,ipa,notation) NOT NULL ✅
    实测重复行数全是 0。

═══ 处置 ═══
① 删重复，**每组留 `MIN(id)`**（最早写入的那条，它的 `src` 是第一个给出这条关系的版本）。
② 建**表达式唯一索引** `(word_id, COALESCE(sense_id,-1), kind, target)` ——
   表内联的 UNIQUE 改不了（要重建表），但加一个索引效果一样且是**增量**的，
   而且 `-1` 不可能是真的 `sense.id`（AUTOINCREMENT 从 1 开始）。
③ 回归闸加一条，防止再犯。

用法（在 pt/ 目录下）：
    python3 fixes/dedup_sense_relation.py
    python3 fixes/dedup_sense_relation.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

KEY = "word_id, COALESCE(sense_id,-1), kind, target"
IDX = "idx_rel_unique"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    tot = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    keep = con.execute(
        "SELECT COUNT(*) FROM (SELECT 1 FROM sense_relation GROUP BY %s)" % KEY).fetchone()[0]
    print("■ sense_relation %s 行 ／ 去重后 %s 行 ／ **要删 %s 行**"
          % (format(tot, ","), format(keep, ","), format(tot - keep, ",")))
    print("\n── 抽样：重复组长什么样 ──")
    for w, k, t, ids, srcs in con.execute(
            "SELECT d.word, r.kind, r.target, GROUP_CONCAT(r.id), GROUP_CONCAT(r.src) "
            "FROM sense_relation r JOIN dict d ON d.id=r.word_id "
            "GROUP BY %s HAVING COUNT(*)>1 LIMIT 6" % KEY):
        print("   %-18s %-9s %-20s id=%s  src=%s" % (w[:18], k, t[:20], ids[:26], srcs[:34]))
    con.close()
    if tot == keep:
        print("\n✓ 没有重复")
        return 0
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("fix-pt-dedup-relations",
                        expect={"#sense_relation": -(tot - keep)}) as s:
        s.execute("DELETE FROM sense_relation WHERE id NOT IN "
                  "(SELECT MIN(id) FROM sense_relation GROUP BY %s)" % KEY)
        # ② 让它不能再犯。表内联的 UNIQUE 改不了，加表达式唯一索引效果一样。
        s.execute("CREATE UNIQUE INDEX IF NOT EXISTS %s ON sense_relation(%s)" % (IDX, KEY))
    print("\n✓ 已删 %s 行，并建了唯一索引 %s（再重跑也不会重复）"
          % (format(tot - keep, ","), IDX))
    return 0


if __name__ == "__main__":
    sys.exit(main())
