#!/usr/bin/env python3
"""补上缺失的 BINARY 配套索引。2026-09-12。

═══ 这是本项目第五次撞同一个坑，而这次是**上一次做成的闸**逮住的 ═══
`de/tests/test_no_regression.py` 的 A6「有 NOCASE 索引却没有配套 BINARY 索引」
把我当天新建的两条 `collocation` 索引打红了。那条闸正是第四次撞完之后做成的机制
（`[[lesson-must-become-mechanism]]`：做成机制的全守住了、写成文字的一条没守住）。

修完 `collocation` 顺手把**同一条判据横着量了六门**，发现三处早就存在的缺口，
而且全在**查词主路径**上：

    es  dict.word            1,148,071 行     75.0 ms/次   🔴 SCAN dict USING COVERING INDEX idx_word
    fr  dict.word            2,086,292 行    171.7 ms/次   🔴 SCAN
    en  legacy_dict.word     3,929,564 行    277.4 ms/次   🔴 SCAN legacy_dict USING ... idx_stardict_word_nocase
    ── 对照：it / pt / de 都有 `idx_word_bin` ──  0.014 ms/次   ✅ SEARCH

**5,000～20,000 倍。** 原因与前四次一字不差：索引建成 `COLLATE NOCASE`，
而 `WHERE word = ?` 是默认 BINARY 比较，SQLite **静默**退化成全索引扫。

🔴 **A6 那条闸只有 de 有，其余五门是瞎的。** 这正是
「上一次记的教训要 grep 同一个写法的**所有实例**，不能只修当时那一处」
（`docs/PITFALLS.md` 54）—— de 修完就停了，没人回头看另外五门。
⇒ 本脚本补索引；把 A6 推广到六门是另一件事，单独做。

═══ 只加索引，一个字节数据都不动 ═══
完全可逆（`DROP INDEX`）。闸②直接看**执行计划与耗时**，不看"索引建出来没有"
—— 后者是形式判据，`SCAN ... USING COVERING INDEX` 会照样让它绿
（同一天在 `build_collocation_search.py` 上刚栽过一次）。

用法（仓库根目录）：
    python3 scripts/fix_collation_gap.py            # 干跑：只量，不建
    python3 scripts/fix_collation_gap.py --apply
    python3 scripts/fix_collation_gap.py --check    # 🔴 六门一起查，有缺口就非 0 退出
"""
import argparse
import importlib
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
f = lambda n: format(n, ",")

# 语种 → (表, 列, 新索引名, 计时用的词)
PLAN = {
    "es": ("dict", "word", "idx_word_bin", "casa"),
    "fr": ("dict", "word", "idx_word_bin", "maison"),
    "en": ("legacy_dict", "word", "idx_stardict_word_bin", "house"),
}
SLOW_MS = 1.0


def load(lang):
    for m in ("paths", "dbtool"):
        sys.modules.pop(m, None)
    sys.path.insert(0, str(ROOT / lang))
    try:
        paths = importlib.import_module("paths")
        dbtool = importlib.import_module("dbtool")
    finally:
        sys.path.pop(0)
    assert lang in str(paths.DB), paths.DB
    return paths, dbtool


def probe(con, tbl, col, word):
    """→ (走了索引查找吗, 热态每次毫秒, 计划文字)。**热身之后再计时**
    —— 冷启的那一下量的是磁盘，不是每次查询的代价。"""
    sql = "SELECT id FROM %s WHERE %s = ?" % (tbl, col)
    plan = " | ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, (word,)))
    for _ in range(3):
        con.execute(sql, (word,)).fetchall()
    t0 = time.perf_counter()
    for _ in range(200):
        con.execute(sql, (word,)).fetchall()
    return ("SEARCH" in plan), (time.perf_counter() - t0) / 200 * 1000, plan


def run(lang, apply_):
    tbl, col, idx, word = PLAN[lang]
    paths, dbtool = load(lang)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n = con.execute("SELECT COUNT(*) FROM %s" % tbl).fetchone()[0]
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (tbl,))}
    ok0, ms0, plan0 = probe(con, tbl, col, word)
    print("\n" + "═" * 62)
    print("══ %s  %s %s 行  （%s %s）" % (lang, tbl, f(n), idx, "已存在" if idx in have else "待建"))
    print("   修前：%s  %.3f ms/次" % ("✅ SEARCH" if ok0 else "🔴 全表扫", ms0))
    print("        %s" % plan0)
    con.close()

    if not apply_:
        print("\n(干跑。--apply 才建索引)")
        return 0
    if idx in have and ok0:
        print("\n✅ 已经是对的，不动。")
        return 0

    # ⚠️ 建索引是 schema 改动，不是数据改动，但仍然走写库闸门 ——
    #    `[[dbtool-and-golden-tests]]`：动库之前必过备份 + 不变量 + 回归。
    with dbtool.session("collation-twin", expect={}) as s:
        s.execute("DROP INDEX IF EXISTS %s" % idx)
        s.execute("CREATE INDEX %s ON %s(%s)" % (idx, tbl, col))

    # 🔴 **新建索引对已预编译的语句无效**（本文件族的老坑），所以这里必须
    #    新开一个连接量 —— 沿用上面那个会量出"索引没用"的假象。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok1, ms1, plan1 = probe(con, tbl, col, word)
    con.close()
    checks = [("🔴 还是没走 SEARCH", int(not ok1), 0),
              ("🔴 热态每次仍超过 %.1f ms（实测 %.3f）" % (SLOW_MS, ms1), int(ms1 > SLOW_MS), 0),
              ("⭐ 确实变快了（负控：别把没变化当成功）", int(ms1 < ms0 / 2), 1)]
    print("\n═══ 闸：建完之后 ═══")
    print("   修后：%s  %.3f ms/次（%.0f× 快）" % (
        "✅ SEARCH" if ok1 else "🔴 全表扫", ms1, ms0 / max(ms1, 1e-9)))
    print("        %s" % plan1)
    bad = 0
    for name, got, want in checks:
        okk = got == want
        bad += not okk
        print("   %s %-46s %s / %s" % ("✅" if okk else "🔴", name, got, want))
    return 1 if bad else 0


ALL_LANGS = ["es", "it", "fr", "pt", "de", "en"]


def check_all():
    """🔴 **六门一起查 A6 判据。**

    `de/tests/test_no_regression.py` 的 A6 只守 de 一门，**其余五门是瞎的** ——
    而今天横量一遍就发现 es / fr / en 三处早就存在的缺口，全在查词主路径上。
    这正是 `docs/PITFALLS.md` 54：**上一次记的教训要 grep 同一个写法的所有实例。**

    ⚠️ 做成**一条跨六门的闸**而不是往五个 `test_no_regression.py` 各抄一份：
       五份拷贝会各自漂移（`[[refactor-mindset-code-quality]]`），
       而这条判据本身与语种无关 —— 它问的是 schema 的形状。
    """
    bad = 0
    print("═══ A6 跨六门：有 NOCASE 索引却没有配套 BINARY 索引 ═══\n")
    for lang in ALL_LANGS:
        paths, _ = load(lang)
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        nocase, binary = set(), set()
        for tbl, sql in con.execute("SELECT tbl_name, sql FROM sqlite_master "
                                    "WHERE type='index' AND sql IS NOT NULL"):
            # ⚠️ 复合索引也要逐列拆 —— 只匹配"整个括号里就一列"会漏掉
            #    `(word, pos)` 这类里的第一列。
            inner = sql[sql.rindex("(") + 1:sql.rindex(")")]
            for part in inner.split(","):
                t = part.strip()
                if not t:
                    continue
                name = t.split()[0].strip('"[]`')
                (nocase if "COLLATE NOCASE" in t.upper() else binary).add((tbl, name))
        gap = sorted(nocase - binary)
        con.close()
        bad += len(gap)
        print("   %s %-3s NOCASE %d 列 ｜ 缺配套 BINARY %d 列 %s"
              % ("✅" if not gap else "🔴", lang, len(nocase), len(gap),
                 "  ".join("%s.%s" % g for g in gap)))
    print("\n%s" % ("🔴 %d 处缺口" % bad if bad else "✅ 六门都没有缺口"))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="六门一起查 A6 判据（不建索引），有缺口就非 0 退出")
    a = ap.parse_args()
    if a.check:
        return check_all()
    bad = sum(run(l, a.apply) for l in PLAN)
    print("\n%s" % ("🔴 有语种未通过" if bad else "✅ 全部通过"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
