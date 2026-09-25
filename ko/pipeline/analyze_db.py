#!/usr/bin/env python3
"""跑 `ANALYZE`：给查询计划器统计信息。ko，2026-09-25（阶段 9d）。

═══ 怎么发现的 ═══
阶段 9c 的展示层契约闸**跑了两分钟还没跑完**（40 个关系最多的词，各渲染一遍）。
量下去，慢的是 `korean.ts` 里给每个关系目标取中文释义的那条子查询：

    ... FROM sense s2 JOIN sense_gloss g ON g.sense_id = s2.id
        JOIN dict d2 ON d2.id = s2.word_id
        WHERE d2.word_norm = ? AND g.lang='zh' AND s2.hidden = 0

**一次 61 毫秒。** `물` 有 263 条关系 ⇒ 一个页面 16 秒。

═══ 根子：**没有统计信息，计划器把驱动表选反了** ═══
    没 ANALYZE：SEARCH g USING INDEX idx_glosslang (lang=?)      ← 从 zh 释义扫起
                                                                   （77,946 行！）
    有 ANALYZE：SEARCH d2 USING COVERING INDEX idx_dict_norm (word_norm=?)
                SEARCH s2 USING INDEX idx_sense_word (word_id=?)
                SEARCH g  USING INDEX sqlite_autoindex_sense_gloss_1 (sense_id=?, lang=?)

**61 ms → 0.1 ms，600 倍**，而且**一个索引都不用加** ——
`sense_gloss` 的 UNIQUE(sense_id, lang, …) 自动索引本来就够用，
计划器只是不知道 `lang='zh'` 有多不挑剔（占 51.8%）。

⭐ `[[query-perf-collation-traps]]` 记着的那句：**性能要等数据长大才咬人**。
   这条子查询在阶段 5 刚写出来时库里只有几千条中文释义，怎么走都快。
🔴 我第一反应是加一个复合索引 `sense_gloss(sense_id, lang)` —— 加了之后
   61 ms 只降到 48 ms，**因为计划器仍然不肯用它**。
   ⇒ **先确认「慢在哪一步」再动手**（`[[enrich-perf-discipline]]`：
     优化前先确认量的工具真的在量）。这里的工具是 `EXPLAIN QUERY PLAN`。

═══ 🔴 这是一笔跨语种的账 ═══
实测八门库：**de / en / ja / pt 有 `sqlite_stat1`，es / fr / it / ko 没有。**
同一件事做对了四门、漏了四门，而每门自己的闸全绿
（`[[decision-not-propagated-across-editions]]`）。⇒ 落账 `BACKLOG` **B11**。

⚠️ **统计信息会过期**：往后每次大批量写库（收词、生成活用表）之后都要重跑。
   跑它是幂等的，代价几秒。

跑（在仓库根）：
    python3 -u ko/pipeline/analyze_db.py
    python3 -u ko/pipeline/analyze_db.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sqlite3
import time

import dbtool
import paths

f = lambda n: format(n, ",")

# 展示层真正走的那几条热查询。**判据是"页面上跑的那条"，不是我随手编一条**。
PROBES = [
    ("关系目标的中文释义（`korean.ts` relations 子查询）",
     "SELECT g.text FROM sense s2 JOIN sense_gloss g ON g.sense_id = s2.id"
     " JOIN dict d2 ON d2.id = s2.word_id"
     " WHERE d2.word_norm = ? AND g.lang='zh' AND s2.hidden = 0"
     " ORDER BY s2.rank LIMIT 1"),
    ("前缀搜索（`korean.ts` search）",
     "SELECT d.id, d.word FROM dict d WHERE d.word_norm >= ? AND d.word_norm < ?"
     " ORDER BY d.is_lemma DESC, LENGTH(d.word), d.word LIMIT 20"),
    ("词条的活用表（`korean.ts` inflections）",
     "SELECT i.word_id, i.label_zh FROM inflection i"
     " JOIN dict d ON d.id = i.base_id WHERE d.word_norm = ? LIMIT 400"),
]
WORDS = ["물", "꽃", "한국", "사랑", "바다", "하다", "가다", "사람", "책", "집"]


def bench(db, label):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    out = []
    for name, sql in PROBES:
        n = sql.count("?")
        args = [(w,) if n == 1 else (w, w + "￿") for w in WORDS]
        plan = [r[-1] for r in con.execute("EXPLAIN QUERY PLAN " + sql, args[0])]
        t = time.time()
        for a in args:
            con.execute(sql, a).fetchall()
        ms = (time.time() - t) * 1000 / len(args)
        out.append((name, ms, plan))
    con.close()
    print("\n■ %s" % label)
    for name, ms, plan in out:
        print("   %-44s %8.2f ms/次" % (name, ms))
        print("      %s" % plan[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    has = con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'").fetchone()[0]
    con.close()
    print("■ 库里有没有统计信息（`sqlite_stat1`）：%s" % ("有" if has else "🔴 没有"))

    before = bench(paths.DB, "现状")

    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-analyze",
            # 🔴 `ANALYZE` 建 `sqlite_stat1`/`sqlite_stat4`，**一行业务数据都不动**。
            expect={},
            invalidates=[]) as s:
        s.execute("ANALYZE")

    after = bench(paths.DB, "ANALYZE 之后")

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    ok = True
    checks = [
        ("`sqlite_stat1` 建出来了",
         q("SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'"), 1),
        # 🔴 反向：统计信息不该改变**任何查询的结果**，只改它的走法。
        #    这里拿一条有确定答案的查询钉住（`한국` 的中文释义条数）。
        ("`한국` 的中文释义条数没变",
         q("SELECT COUNT(*) FROM sense s JOIN sense_gloss g ON g.sense_id=s.id"
           " JOIN dict d ON d.id=s.word_id"
           " WHERE d.word='한국' AND g.lang='zh' AND s.hidden=0"),
         2),
    ]
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-30s %6s（期望 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))
    con.close()

    # 🔴 **提速要真的发生**：热查询至少快一个数量级，否则这一步白做
    worst = max(a2[1] / max(b[1], 1e-9) for b, a2 in zip(before, after))
    for (name, b_ms, _), (_, a_ms, _) in zip(before, after):
        tag = "✅" if a_ms <= b_ms / 2 or a_ms < 1.0 else "⚠️"
        print("   %s %-44s %8.2f → %.2f ms" % (tag, name, b_ms, a_ms))
    if before[0][1] / max(after[0][1], 1e-9) < 5:
        ok = False
        print("   🔴 最热的那条没有明显提速 —— 计划器可能还是选反了驱动表")
    if not ok:
        raise SystemExit("🔴 回核对不上")
    print("\n⚠️ 统计信息会过期：往后每次大批量写库之后重跑一次（幂等，几秒）")


if __name__ == "__main__":
    main()
