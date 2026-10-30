#!/usr/bin/env python3
"""查询计划探针（B11，跨门：es／fr／it）。2026-10-27。**只读。**

照 `vi/probes/query_plans.py` 的三条判据，但不为每门各写一份：
  · SQL 从服务层源码**原文抠**（`this.xxx = this.db.prepare(\\`…\\`)`），抠到的条数与 `EXPECT` 不符 ⇒ 红
    （少一条＝正则漂了，那条查询这里完全看不见）。
  · `EXPLAIN QUERY PLAN` 里对**大表**（行数 ≥ ROW_FLOOR）的 `SCAN` ⇒ 红。
    ⚠️ 认的是 `SCAN` 这个词：`SCAN dict USING COVERING INDEX x` 有索引名，干的却是把索引从头扫到尾。
  · `USE TEMP B-TREE` ⇒ 报出来（不判红：小结果集上排序无所谓）。
页面级耗时另由 `scripts/page_timing.tsx` 量（读者口径：服务层真取一整页）。

用法：
    python3 scripts/query_plans_probe.py --lang es
    python3 scripts/query_plans_probe.py --lang es --mutate   # 变异：在内存里改 SQL／去掉统计信息
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TS = {"es": "spanish.ts", "fr": "french.ts", "it": "italian.ts"}
EXPECT = {"es": 20, "fr": 26, "it": 26}      # 2026-10-27 逐条数过（`this.x = this.db.prepare` 的条数）；改了服务层要跟着改
ROW_FLOOR = 20000
# 有意不判红的全表扫：**必须写理由**。
EXEMPT = {"statsQuery": "`/stats` 接口的全库计数，扫全表就是它的工作本身；词条页与搜索都不走它（vi 同一结论）"}
Q = re.compile(r"this\.(\w+)\s*=\s*this\.db\.prepare\(\s*`([\s\S]*?)`\s*\)")


def queries(lang):
    src = (ROOT / "packages/dict-core/src" / TS[lang]).read_text(encoding="utf-8")
    # `${NAME}` 插值（fr 的 `ENTRY_COLS`）按源码里同名常量的值展开；展开不了就原样留着 ⇒ 当场报错
    consts = dict(re.findall(r"const (\w+)\s*=\s*[`'\"]([^`'\"]*)[`'\"]", src))
    return [(n, re.sub(r"\$\{(\w+)\}", lambda m: consts.get(m.group(1), m.group(0)), q))
            for n, q in Q.findall(src)]


def nparams(con, sql):
    try:
        con.execute("EXPLAIN QUERY PLAN " + sql, ())
        return 0
    except sqlite3.ProgrammingError as e:
        m = re.search(r"uses (\d+)", str(e))
        if not m:
            raise
        return int(m.group(1))


def check(lang, con, rows, qs, stat, say=print):
    """→ 红的处数。参数都由调用方给，方便变异在内存里改。"""
    red = 0 if len(qs) == EXPECT[lang] else 1
    if red:
        say("  🔴 抠到 %d 条，期望 %d —— 正则漂了或服务层改了查询写法" % (len(qs), EXPECT[lang]))
    # 🔴 没有统计信息 ⇒ 红（B11）。2026-10-27 实测这三门补上之后**没有可测变化**（热查询本来就选对了索引，
    #    与 vi 同、与 ko 相反）—— 留着它是因为数据长大／查询改了之后，没有它计划器才会选反驱动表。
    #    重建库之后忘了跑，这里会说话。
    if not stat:
        red += 1
        say("  🔴 没有 sqlite_stat1 —— 跑 `python3 scripts/analyze_db.py --lang %s --apply`" % lang)
    for name, sql in qs:
        n = nparams(con, sql)
        # 🔴 参数绑**真实形状的字符串**，不绑 NULL：`LIKE ?` 只有右边是确定的字符串时，
        #    计划器才把前缀匹配改写成索引范围查询。第一版绑 NULL ⇒ es/it 的 `prefixQuery`
        #    报 `SCAN dict`（114 万／150 万行），而实测 4 字符以上前缀热态 0.1–5.7 ms ——
        #    **报的是我绑的参数，不是真实调用**。数字类参数（LIMIT/id）绑字符串不影响计划形状。
        plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, ("a%",) * n)]
        scans = []
        for p in plan:
            m = re.match(r"SCAN (\w+)", p)
            if m and rows.get(m.group(1), 0) >= ROW_FLOOR:
                scans.append("%s（%s 行）" % (p, format(rows[m.group(1)], ",")))
        temp = [p for p in plan if "TEMP B-TREE" in p]
        if scans and name in EXEMPT:
            say("  ⚪ %-24s 有意豁免：%s" % (name, EXEMPT[name]))
            continue
        red += bool(scans)
        mark = "🔴" if scans else ("⚠️ " if temp else "✅")
        say("  %s %-24s %s" % (mark, name, "；".join(scans + temp) or ""))
    return red


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=sorted(TS))
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    db = ROOT / "data/db" / ("synapse-dict-%s.sqlite" % a.lang)
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    stat = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'").fetchone()[0]
    rows = {}
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        rows[t] = con.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
    qs = queries(a.lang)
    print("■ %s：抠到 %d 条查询／统计信息 %s" % (a.lang, len(qs), "有" if stat else "🔴 没有"))
    red = check(a.lang, con, rows, qs, stat)
    print(("🔴 %d 处" % red) if red else "✅ 计划全绿")
    if not a.mutate:
        sys.exit(1 if red else 0)
    print("\n■ 变异（内存里的查询表／统计信息）")
    quiet = lambda *_: None
    cases = [
        ("少抠到一条查询", qs[:-1], stat, True),
        ("新查询在 dict 上套函数过滤（用不上索引）",
         qs + [("zzMutant", "SELECT id FROM dict WHERE length(word) = ?")], stat, True),
        ("统计信息没了", qs, 0, True),
        ("（反控）原样", qs, stat, False),
    ]
    dead = 0
    for name, q2, st2, want in cases:
        got = check(a.lang, con, rows, q2, st2, say=quiet) > 0
        dead += got != want
        print("  %s %s" % ("✅" if got == want else "🔴 没逮到", name))
    print("  变异 %d/%d" % (len(cases) - dead, len(cases)))
    sys.exit(1 if dead or red else 0)


if __name__ == "__main__":
    main()
