#!/usr/bin/env python3
"""热点查询的执行计划闸：**跑之前**就断言走了索引。2026-08-16。

═══ 为什么要有 ═══
2026-08-16 收词把 `dict` 从 767,289 涨到 1,307,170（+70%），紧接着几个 `--verify`
就跑超时。我是**等它超时了才去 EXPLAIN**，顺序反了 —— 用户当场点破：
「你跑之前先试一下有没有走索引不更好？」

查出来的原因正是我自己记过的坑（`query-perf-collation-traps`）：

    idx_word ON dict(word COLLATE NOCASE)      索引是 NOCASE
    SELECT id FROM dict WHERE word = ?          查询是默认 BINARY
    ⇒ EXPLAIN: **SCAN** dict USING COVERING INDEX idx_word   ← 全表扫 130 万行

`SCAN ... USING COVERING INDEX` 这行字最阴险：它**长得像走了索引**，
实际是把整个索引从头扫到尾。判据必须认 `SEARCH`，不能只看有没有 `INDEX` 字样。

═══ 🔴 为什么必须是闸而不是"下次注意" ═══
性能问题**要等数据长大才咬人**。今早 76 万行时这条查询感觉不出来，
灌到 130 万就卡死。⇒ 每次大批量写入之后跑一遍，比事后 debug 便宜得多。

用法（在 it/ 目录下）：
    python3 probes/query_plans.py
    python3 probes/query_plans.py --mutate    # 变异验证：判据必须能识破假索引
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths   # noqa: E402

# (说明, SQL, 参数)。都是划词/查词路径上真正会跑的形状。
HOT = [
    ("按词形精确查（划词命中的主路径）",
     "SELECT id FROM dict WHERE word = ?", ("casa",)),
    ("按词形不分大小写查（exactQuery 的第二排序键）",
     "SELECT id FROM dict WHERE word = ? COLLATE NOCASE", ("casa",)),
    # 2026-08-17 加：`getEntry` 精确匹配落空时的回落路径（撇号/重音写法不同）。
    ("按归一词形查（去重音+撇号回落）",
     "SELECT id FROM dict WHERE word_norm = ? "
     "ORDER BY is_lemma DESC, LENGTH(word) ASC, word ASC LIMIT 1", ("all'alba",)),
    ("取一个词形的变形关系",
     "SELECT base, label_zh FROM inflection WHERE word_id = ?", (1,)),
    ("取一个原形的全部变形",
     "SELECT word_id FROM inflection WHERE base_id = ?", (1,)),
    ("取一个词的义项",
     "SELECT id FROM sense WHERE word_id = ?", (1,)),
    ("取一条义项的释义",
     "SELECT text FROM sense_gloss WHERE sense_id = ? AND lang = 'zh' AND seq = 0", (1,)),
    ("取一条义项的证据",
     "SELECT text FROM sense_src WHERE sense_id = ?", (1,)),
    ("取一个词条下的义项",
     "SELECT id FROM sense WHERE entry_id = ?", (1,)),
    ("取一个词形的搭配",
     "SELECT text FROM collocation WHERE word_id = ?", (1,)),
]


def plan_ok(con, sql, args):
    """→ (是否走了索引查找, 计划文字)

    🔴 判据认 `SEARCH`，**不认 `SCAN ... USING COVERING INDEX`** ——
       后者长得像走了索引，实际是把索引整个扫一遍。
    """
    rows = con.execute("EXPLAIN QUERY PLAN " + sql, args).fetchall()
    txt = " / ".join(r[3] for r in rows)
    return ("SEARCH" in txt), txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)

    if a.mutate:
        print("═══ 变异验证：判据必须识破「像走了索引其实是全表扫」═══")
        cases = [
            ("SEARCH ⇒ 认为走了索引", "SEARCH dict USING INDEX idx_x (word=?)", True),
            ("🔴 SCAN + COVERING INDEX ⇒ 必须判为没走",
             "SCAN dict USING COVERING INDEX idx_word", False),
            ("🔴 裸 SCAN ⇒ 没走", "SCAN dict", False),
            ("SEARCH + AUTOMATIC INDEX ⇒ 认（sqlite 临时建的也算走了）",
             "SEARCH t USING AUTOMATIC COVERING INDEX (x=?)", True),
        ]
        ok = True
        for name, txt, want in cases:
            got = "SEARCH" in txt
            ok &= got == want
            print("   %s %-40s %s" % ("✅" if got == want else "🔴", name, txt[:44]))
        print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
        return 0 if ok else 1

    n = con.execute("SELECT count(*) FROM dict").fetchone()[0]
    print("═══ 热点查询执行计划（dict %s 行）═══" % f"{n:,}")
    bad = 0
    for name, sql, args in HOT:
        good, txt = plan_ok(con, sql, args)
        t = time.time()
        for _ in range(200):
            con.execute(sql, args).fetchone()
        ms = (time.time() - t) * 5      # → 每次微秒
        bad += 0 if good else 1
        print("   %s %-34s %7.1f µs  %s" % ("✅" if good else "🔴", name, ms * 1000, txt[:52]))
    print("\n   %s" % ("✅ 全部走索引" if not bad else "🔴 %d 条在全表扫 —— 数据一涨就会卡死" % bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
