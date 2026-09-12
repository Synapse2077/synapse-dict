#!/usr/bin/env python3
"""让搭配短语**能被搜到**：建归一形 + 索引。2026-09-12。

═══ 起因 ═══
用户在 es 的 `quiteño` 页上看到「搭配 / 固定短语 · habitante quiteño 基多居民」，
回到搜索框输入 `habitante quiteño` —— **什么都没有**。
因为六门的 `search()` 只查 `dict.word` / `dict.word_norm`，
`collocation` / `example` 两张表**根本不在检索范围里**。

页面上印出来的字符串，读者搜一下总该有反应。这跟前几天那条
「下位词点不动」是同一族问题：**展示了读者没法据以行动的东西**。

═══ 做什么 ═══
`collocation` 加一列 `text_norm`，口径与 `dict.word_norm` **逐字一致**
（各门自己的 `pipeline/build.unaccent`：es 去重音、de 还要 ä→ae、
 fr 还要 œ→oe、pt 还要 ç→c）。然后建前缀索引。

🔴 **必须复用各门自己的 `unaccent`，不许在这里重写一个。**
   重写出来的哪怕只差一个 ß→ss，就会变成「搜 `strasse` 搜不到 `Straße` 的搭配，
   而搜同一个词头却搜得到」—— 同一个库里两套归一规则，
   这类不一致是 `[[query-perf-collation-traps]]` 的近亲：**不报错，只是静默查不到**。

═══ 🔴 索引不是可选项 ═══
`search()` 是**每敲一个字符跑一次**的路径。不建索引就是每次全表扫 ——
`collocation` 只有 1.4～2.9 万行，今天扫得动，但
`[[query-perf-collation-traps]]`：**性能要等数据长大才咬人**。
本脚本建完索引后当场计时，慢于 5 ms 就红。

═══ 为什么只做「整条短语前缀」，不做「短语里的词」 ═══
`habitante quiteño` 里的 `quiteño` **本身就是词头**，搜它已经能搜到词条页，
再让它同时命中一堆包含它的短语只会把下拉框挤满。
⇒ 只解决"把页面上那一整条抄下来搜"这个真实场景。
   `[[criteria-narrower-than-you-think]]`：先做窄的那个。

用法（仓库根目录）：
    python3 scripts/build_collocation_search.py --all           # 干跑
    python3 scripts/build_collocation_search.py --all --apply
"""
import argparse
import importlib
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ["es", "it", "fr", "pt", "de"]
SLOW_MS = 5.0

# 🔴🔴 **两条索引都必须是 `COLLATE NOCASE`。**
#    SQLite 默认的 `LIKE` 是大小写不敏感的，而**这种 LIKE 只认 NOCASE 索引** ——
#    建在 BINARY 上的索引它一眼都不看。
#    第一版只建了 `idx_col_norm ON collocation(text_norm)`（BINARY），结果是
#        SCAN collocation USING COVERING INDEX idx_col_norm
#    —— **索引名在计划里，干的却是全表扫**（es 9.6ms / it 234.7ms / de 13.3ms）。
#    `dict` 表早就踩过并解决了：它有 `idx_word (word COLLATE NOCASE)` +
#    `idx_norm_nocase (word_norm COLLATE NOCASE)` 两条，我没照抄。
#
# 🔴 连带的教训：**闸问错了问题。**「计划里有没有 idx_col_norm」是个形式判据，
#    我想问的是「它有没有做范围查找」。SCAN 也带着索引名，照样绿。
#    ⇒ 判据改成必须出现 `SEARCH ... USING INDEX <名字>`，且 EXPLAIN 的是
#      **服务层真正要跑的那条 SQL**，不是我另写的简化版
#      （`[[criteria-from-meaning-not-form]]`、`[[correct-steps-can-compose-a-hole]]`）。
INDEXES = [
    ("idx_col_text_nocase", "CREATE INDEX idx_col_text_nocase "
                            "ON collocation(text COLLATE NOCASE)"),
    ("idx_col_norm_nocase", "CREATE INDEX idx_col_norm_nocase "
                            "ON collocation(text_norm COLLATE NOCASE)"),
]
# 🔴🔴 **配套的 BINARY 索引 —— 不是可选项。**
#    只建 NOCASE 的话，`WHERE text = ?`（默认 BINARY 比较）用不上它，
#    SQLite **静默**退化成全索引扫。本项目这已经是第五次撞同一个坑，
#    而这次是 **de 的回归闸 A6「有 NOCASE 索引却没有配套 BINARY 索引」当场逮住的**
#    —— 那条闸正是 2026-09-04 第四次撞完之后做成的机制。
#    `[[lesson-must-become-mechanism]]`：**做成机制的全守住了，写成文字的一条没守住。**
#    ⚠️ 别去论证"我这两条查询只用 NOCASE，所以不需要" ——
#      第四次的现场就是"当时确实只有 NOCASE 查询"，后来加的 `WHERE text=?` 没人回头看。
#      规则是结构性的：**NOCASE 索引一律配一条 BINARY 的。**
BINARY_TWINS = [
    ("idx_col_text_bin", "CREATE INDEX idx_col_text_bin ON collocation(text)"),
    ("idx_col_norm_bin", "CREATE INDEX idx_col_norm_bin ON collocation(text_norm)"),
]
# 服务层真正要跑的那两条（见 packages/dict-core/src/<lang>.ts 的 collocSearchByText/ByNorm）。
#
# 🔴🔴 **不能写成 `WHERE text LIKE ? OR text_norm LIKE ?`。**
#    那样两条索引确实都走 SEARCH（`MULTI-INDEX OR`），但 `MULTI-INDEX OR`
#    **产不出有序结果** ⇒ 计划末尾挂着 `USE TEMP B-TREE FOR ORDER BY`，
#    也就是把命中的全部行排一遍才取前 20。实测最坏情形：
#        it `c%` **923.8 ms** ／ fr `p%` 285.9 ms ／ pt `c%` 277.3 ms
#    而这是**每敲一个字符跑一次**的路径。
#    ⇒ 拆成两条单列查询，各自沿自己的索引顺序扫、取够 20 条就停，服务层再合并。
#        同样的最坏情形降到 **0.73 ms**（it）。
#    ⚠️ 代价：排序从"短的在前"变成按字母序。读者抄一整条短语来搜时命中唯一，
#       这个代价看不见；而 923 ms 是看得见的。
#
# ⚠️ 两列都要查：从页面抄下来的带重音（命中 `text`），自己敲的多半不带（命中 `text_norm`）。
def service_sql(col, extra=""):
    return """
  SELECT c.text AS phrase, c.src AS colSrc, c.word_id AS wordId, d.word AS owner,
         (SELECT text FROM collocation_gloss
           WHERE collocation_id = c.id AND lang = 'zh') AS zh
    FROM collocation c JOIN dict d ON d.id = c.word_id
   WHERE c.{col} LIKE ? COLLATE NOCASE{extra}
   ORDER BY c.{col} COLLATE NOCASE
   LIMIT ?
""".format(col=col, extra=extra)


SERVICE_QUERIES = [("idx_col_text_nocase", service_sql("text")),
                   ("idx_col_norm_nocase", service_sql("text_norm"))]

f = lambda n: format(n, ",")


def load(lang):
    """加载某门语言的 `paths` / `dbtool` / `pipeline.build.unaccent`。
    **每次都先清模块**：五门同名，不清会拿到上一门的 DB 路径（静默写错库）。"""
    for m in ("paths", "dbtool", "build", "pipeline", "pipeline.build"):
        sys.modules.pop(m, None)
    sys.path.insert(0, str(ROOT / lang))
    sys.path.insert(0, str(ROOT / lang / "pipeline"))
    try:
        paths = importlib.import_module("paths")
        dbtool = importlib.import_module("dbtool")
        build = importlib.import_module("build")
    finally:
        sys.path.pop(0)
        sys.path.pop(0)
    assert lang in str(paths.DB), "%s 的 DB 路径里没有语种名：%s" % (lang, paths.DB)
    # ⚠️ 函数名各门不一样（de 叫 `norm_de`，其余叫 `unaccent`）。
    #    第一版写死 `build.unaccent` ⇒ 跑到 de 直接 AttributeError。
    #    **这声当场的报错比什么都值** —— 要是我图省事在这里自己写一个归一函数，
    #    de 的 ä→ae 就会静默丢掉，变成「搜 Straße 的搭配搜不到、搜词头却搜得到」。
    for name in ("unaccent", "norm_%s" % lang):
        fn = getattr(build, name, None)
        if fn:
            return paths, dbtool, fn
    raise SystemExit("🔴 %s/pipeline/build.py 里找不到归一函数" % lang)


def check_same_ruler(con, unaccent, lang):
    """🔴 闸：拿来的 `unaccent` 必须**真的就是建 `dict.word_norm` 用的那一个**。
    判据不是"函数名对不对"，是**拿现成的 word/word_norm 对逐条重算**。
    抽 3,000 个含非 ASCII 的词头 —— 只抽纯 ASCII 的话任何实现都能过（判据比对象宽）。"""
    rows = con.execute(
        "SELECT word, word_norm FROM dict WHERE word <> word_norm LIMIT 3000").fetchall()
    bad = [(w, n, unaccent(w)) for w, n in rows if unaccent(w) != n]
    return len(rows), bad


def plan(con, unaccent):
    rows = [(unaccent(t), cid) for cid, t in con.execute("SELECT id, text FROM collocation")]
    empty = sum(1 for n, _ in rows if not n.strip())
    return rows, empty


def timing(con, lang):
    """当场计时。**分冷热两个数，闸看热的。**

    🔴 第一版只量了冷的（新连接上跑第一遍），得到 14～26 ms，
       而同样的查询手工循环量出来是 0.5～0.9 ms —— 差了 20 倍。
       差额是**首次查询把索引页从磁盘读进 page cache** 的一次性代价，
       跟"每敲一个字符要多久"是两件事：API 进程是长驻的，热了之后就一直是热的。
       `[[enrich-perf-discipline]]`：**优化前先确认「量的工具真的在量」** ——
       差点因为这 26 ms 去改一个本来已经对了的查询。
    ⚠️ 冷的那个数照样打出来：它是**首个用户第一次敲键**的真实体验，只是不做闸。

    探针取该语种**最常见的 1～3 字符前缀**（不是我随手挑的字母）——
    挑到冷门前缀会量出一个漂亮但没意义的数字。
    """
    probes = [p for (p,) in con.execute(
        "SELECT SUBSTR(text_norm, 1, ?) p FROM collocation GROUP BY p "
        "ORDER BY COUNT(*) DESC LIMIT 2", (1,)).fetchall()]
    probes += [p for n in (2, 3) for (p,) in con.execute(
        "SELECT SUBSTR(text_norm, 1, ?) p FROM collocation GROUP BY p "
        "ORDER BY COUNT(*) DESC LIMIT 1", (n,)).fetchall()]

    def once(p):
        t0 = time.perf_counter()
        for _, sql in SERVICE_QUERIES:
            con.execute(sql, (p + "%", 20)).fetchall()
        return (time.perf_counter() - t0) * 1000

    cold = max(once(p) for p in probes)          # 第一遍：含磁盘读
    worst, worst_q = 0.0, ""
    for p in probes:                              # 第二遍：热的，这才是每键的代价
        ms = once(p)
        if ms > worst:
            worst, worst_q = ms, p
    return worst, worst_q, cold


def run(lang, apply_, verify_only=False):
    paths, dbtool, unaccent = load(lang)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n_total = con.execute("SELECT COUNT(*) FROM collocation").fetchone()[0]
    has_col = any(r[1] == "text_norm" for r in con.execute("PRAGMA table_info(collocation)"))
    print("\n" + "═" * 62)
    print("══ %s  搭配 %s 条  （text_norm 列%s）" % (lang, f(n_total), "已存在" if has_col else "待加"))

    n_ruler, ruler_bad = check_same_ruler(con, unaccent, lang)
    rows, empty = plan(con, unaccent)

    print("\n═══ 闸①：写库之前 ═══")
    checks = [
        ("🔴 归一尺子与 dict.word_norm 不一致（抽 %s 个）" % f(n_ruler), len(ruler_bad), 0),
        ("尺子抽样量 > 0（负控：别拿空样本当绿灯）", int(n_ruler > 0), 1),
        ("要算的条数", len(rows), n_total),
        ("🔴 归一后是空串", empty, 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-48s %s / %s" % ("✅" if ok else "🔴", name, f(got), f(want)))
    for w, n, mine in ruler_bad[:5]:
        print("      🔴 %-22s 库里 %-22s 我算的 %s" % (w, n, mine))
    ex = con.execute("SELECT text FROM collocation LIMIT 3").fetchall()
    print("   样例：" + " ／ ".join("%s → %s" % (t, unaccent(t)) for (t,) in ex))
    con.close()
    if bad:
        print("\n🔴 闸红，不写。")
        return 1
    if not apply_ and not verify_only:
        print("\n(干跑。--apply 才写库)")
        return 0

    # `--verify`：库已经是对的，只想把**闸②**再跑一遍（比如闸的判据改了）。
    # ⚠️ 单独留这个口子是有原因的：`dbtool.session()` 每次都全库备份，
    #    五门一轮 ≈ 9.9 GB。为了重跑一次判据而写 9.9 GB，代价和收益完全不成比例
    #    （`[[backup-retention]]`：备份是字节封顶的预算，不是免费的）。
    if not verify_only:
        with dbtool.session("colloc-search", expect={}) as s:
            if not has_col:
                s.execute("ALTER TABLE collocation ADD COLUMN text_norm TEXT")
            s.executemany("UPDATE collocation SET text_norm=? WHERE id=?", rows)
            # 第一版建的 BINARY 索引留着没用还占空间，一并删掉。
            s.execute("DROP INDEX IF EXISTS idx_col_norm")
            for name, ddl in INDEXES + BINARY_TWINS:
                s.execute("DROP INDEX IF EXISTS %s" % name)
                s.execute(ddl)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = con.execute
    nnull = q("SELECT COUNT(*) FROM collocation WHERE text_norm IS NULL OR text_norm=''").fetchone()[0]
    now = q("SELECT COUNT(*) FROM collocation").fetchone()[0]
    # 🔴 索引到底用上没有 —— 看执行计划，不看快不快；
    #    而且 EXPLAIN 的必须是**服务层真要跑的那条 SQL**。
    #    「快」在 2 万行上永远成立（`[[query-perf-collation-traps]]`：性能要等数据长大才咬人）。
    # 判据有三条，缺一条都会放过一种真实发生过的退化：
    #   ① 该走的索引必须做 **SEARCH** —— 只查索引名的话
    #      `SCAN ... USING COVERING INDEX <名字>` 会照样绿（第一版就是这么绿的）
    #   ② 计划里不许出现对 collocation 的 SCAN（别名是 `c`，两种写法都得认）
    #   ③ 不许出现 `TEMP B-TREE FOR ORDER BY` —— 第二版栽在这条上：
    #      索引全走 SEARCH、闸全绿，it 却要 923.8 ms
    missing, scanned, sorted_ = [], 0, 0
    plan_parts = []
    for idx_name, sql in SERVICE_QUERIES:
        rows_ = q("EXPLAIN QUERY PLAN " + sql, ("a%", 20)).fetchall()
        plan_parts.append("%s: %s" % (idx_name, " | ".join(r[3] for r in rows_)))
        if not any("SEARCH" in r[3] and idx_name in r[3] for r in rows_):
            missing.append(idx_name)
        scanned += any(r[3].startswith(("SCAN c ", "SCAN c\t", "SCAN collocation"))
                       or r[3].strip() == "SCAN c" for r in rows_)
        sorted_ += any("TEMP B-TREE" in r[3] for r in rows_)
    plan_txt = "\n              ".join(plan_parts)
    have_idx = {r[0] for r in q(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='collocation'")}
    no_twin = [n for n, _ in BINARY_TWINS if n not in have_idx]
    ms, wq, cold = timing(con, lang)
    checks = [("🔴 还有没算归一形的行", nnull, 0),
              ("总行数没变", now, n_total),
              ("🔴 有索引没被用来做 SEARCH：%s" % ("／".join(missing) or "—"), len(missing), 0),
              ("🔴 计划里出现了 SCAN collocation（全表扫）", scanned, 0),
              ("🔴 计划里出现了 TEMP B-TREE（为排序把命中行全排一遍）", sorted_, 0),
              ("🔴 NOCASE 索引没有配套 BINARY 索引：%s" % ("／".join(no_twin) or "—"),
               len(no_twin), 0),
              ("🔴 热态最慢前缀 `%s` 超过 %.0f ms（实测 %.2f；冷启首查 %.1f）"
               % (wq, SLOW_MS, ms, cold), int(ms > SLOW_MS), 0)]
    print("\n═══ 闸②：写库之后 ═══")
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-48s %s / %s" % ("✅" if ok else "🔴", name, f(got), f(want)))
    print("   执行计划：%s" % plan_txt)
    con.close()
    print("\n%s %s：%s 条可检索" % ("🔴 写库后闸红" if bad else "✅", lang, f(len(rows))))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=LANGS)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true",
                    help="不写库，只把闸②对现有的库再跑一遍")
    a = ap.parse_args()
    if not a.lang and not a.all:
        ap.error("要么 --lang <xx>，要么 --all")
    bad = sum(run(l, a.apply, a.verify) for l in (LANGS if a.all else [a.lang]))
    print("\n%s" % ("🔴 有语种未通过" if bad else "✅ 全部通过"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
