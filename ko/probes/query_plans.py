#!/usr/bin/env python3
"""查询计划闸：展示层真正跑的每一条查询，**走的是索引还是全表扫**。ko，2026-09-25（阶段 9d）。

═══ 为什么要这道闸 ═══
`[[query-perf-collation-traps]]` 记着同一个病在本仓库栽过**五次**，
每次都是「等到超时了才去 EXPLAIN」。用户点破的是**顺序**：
「你跑之前先试一下有没有走索引不更好？」⇒ it 那轮做成了 `it/probes/query_plans.py`。
ko 这一轮它又兑现了一次：阶段 9c 的契约闸跑两分钟跑不完，
根子是**没有 `ANALYZE`，计划器把驱动表选反了**（`ko/pipeline/analyze_db.py`，51ms → 0.04ms）。

═══ 🔴 判据从 `korean.ts` **原文抠出来**，不在这儿抄一份 ═══
一条查询在这儿抄一遍，它和展示层迟早漂开 —— 那时这道闸量的是**一条没人跑的 SQL**
（`[[refactor-mindset-code-quality]]`／`[[fix-regression-and-gate]]` 第三种机制）。
⇒ 本文件从 `packages/dict-core/src/korean.ts` 里正则抠 `名字: this.db.prepare(…)`，
  **抠不到就直接红**（闸自己的闸，见 `EXPECT_QUERIES`）。

═══ 三条判据，缺一条都放得过真问题 ═══
① **`SCAN <表>` ⇒ 红。**
   ⚠️ `SCAN dict USING COVERING INDEX idx_word` **这行字最阴险** —— 索引名在，
     干的却是把整个索引从头扫到尾。判据认的是 `SEARCH` 这个词，不是「有没有 INDEX 字样」。
   ⚠️ 小表（`hanja_reading` 8,432 行）上的 SCAN 无所谓 ⇒ 按**表的行数**设门槛。
② **`USE TEMP B-TREE FOR ORDER BY` ⇒ 报出来。**
   it 那轮：两条索引都 SEARCH 了，查询照样 923 ms，慢的全在临时 B 树排序
   （`MULTI-INDEX OR` 产不出有序结果）。⇒「有没有 SEARCH」一条判据是不够的。
   🔴 ko 的 `search` **有意留着它**：见下面 `ALLOW_TEMP_BTREE` 的理由与实测数。
③ **热态耗时上限。** 计划对了也可能慢（相关子查询 × 未截断行数 = O(n²)）。

═══ ⚠️ 量性能先分冷热 ═══
同一条查询新开连接第一遍与热态差 20 倍，差额全是把索引页读进 page cache。
**每键代价看热态**（API 进程长驻），冷启的数照打但不做闸。

═══ ⭐ NOCASE 那一族的坑，ko 结构上碰不到 —— 但要**断言**它 ═══
`[[query-perf-collation-traps]]`：「NOCASE 列上做 BINARY 比较 ＝ 静默全表扫」，
de 为此有回归闸 A6「有 NOCASE 索引却没有配套 BINARY 索引」。
ko 全库 **0 个 NOCASE 索引、0 个 COLLATE 列声明** —— 因为 SQLite 的 NOCASE
只折 ASCII，对谚文完全无效，ko 一律走 `word_norm`（NFC）。
🔴 **「碰不到」不等于「不用查」**：下一个人加一条 NOCASE 索引，这条前提就没了。
  ⇒ 做成断言（`nocase_audit`），不是做成注释。

跑（在仓库根）：
    python3 -u ko/probes/query_plans.py
    python3 -u ko/probes/query_plans.py --mutate    # 变异验证：这道闸拦得住什么
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import re
import sqlite3
import time

import paths

TS = _pl.Path(__file__).resolve().parent.parent.parent / "packages" / "dict-core" \
    / "src" / "korean.ts"

# 🔴 **独立声明**：`korean.ts` 里应该有这几条查询。少一条就是要么被删了、
#    要么正则抠不到 —— 两种都必须红，不能静默少量一条
#    （`[[expectation-must-be-declared]]`）。
EXPECT_QUERIES = {
    "stats", "search", "exact", "entries", "pronunciations", "senses",
    "relations", "examples", "inflections", "baseOf", "hanjaReadings",
    "etymology", "audio",
}

# 每条查询用什么参数量。**挑最狠的那个词，不挑好看的**：
#   `가`  1 字符前缀，候选 19,700 —— 全库最多
#   `물`  263 条关系 —— 全库关系最多的那一档
#   `걷다` 169 个活用形
# 🔴🔴 **参数也必须与调用方一致，不能自己编。** 第一版我给 `search` 传的是
#    `("가", "나", 20)` —— 那覆盖**整个 가 行**（가…깋，十几万条），
#    而 `korean.ts:322` 真正传的是 `(p, p + "\uffff")`，**只覆盖前缀 `가`**。
#    结果闸量到 45 ms 报红，而页面上那条查询的真实代价是 5.2 ms。
#    ⇒ 闸量了一条**没人跑的查询**，红得有理由但理由是假的
#    （`[[criteria-from-meaning-not-form]]`：判据要照真实形态写）。
#    ⚠️ 修法是**让参数对齐调用方**，不是把上限调高去迁就我编的那条。
SEARCH_HI = "\uffff"                      # 与 `korean.ts` 的 `${p}￿` 同一个字符
PARAMS = {
    "stats": [()],
    # 全库 11,944 个 1 字符前缀里候选最多的几个（`가` 19,700 条，最狠）
    "search": [(p, p + SEARCH_HI, 20) for p in ("가", "우", "사", "한국")],
    "exact": [("물",)],
}
HEAVY_WORDS = ["물", "걷다", "하다", "한국", "꽃"]

# 热态上限（毫秒）。🔴 不是拍的：取实测值的 3–5 倍留余量。
# ⚠️ **别因为跑慢了就调高它** —— 调高＝把闸关掉（`[[proxy-metric-gets-optimized]]`）。
LIMIT_MS = {
    "search": 12.0,       # 实测最慢 `가` 5.20 ms
    # 🔴 `stats` 单独给一档，**理由要写清楚**：它是六个全表 COUNT
    #    （`dict` 123 万 ＋ `inflection` 115 万），SQLite 没有缓存行数，
    #    数一张表就是扫一张表 —— **这不是缺陷，是这件事本身的代价**。
    #    横量八门：数一次 `dict` 热态 3.5–22.8 ms，ko 14.8 ms，处在中间。
    #    ⚠️ 它只在 `/stats` 端点上跑（`apps/api/src/index.ts:178`），
    #      **一次页面加载一次，不在每敲一键的路径上**。
    #    🔴 什么会让它变成问题：它被挪进搜索/词条路径。那时这条上限要跟着改小，
    #      并且真正的修法是**把这六个数落成一张小表**，不是调高上限。
    "stats": 250.0,
    "relations": 8.0,     # 实测 `물`（263 条边）ANALYZE 后 1 ms 级
    "inflections": 8.0,   # 实测 `걷다`（169 形）
    "senses": 8.0,        # 实测 `하다`（38 义项）
    "_default": 5.0,
}

# 🔴 允许出现临时 B 树排序的查询。**值是理由，不是 `True`** ——
#    写不出理由就加不进来（闸会检查理由长度）。
#
# ═══ 这条规则真正想抓的是什么 ═══
# it 那轮 923 ms 的现场是**排一个会随语料增长的候选集**（`LIKE` 命中上千行，
# `LIMIT 20` 最后才截）。而下面这些查询排的是**一个词自己的那几十行** ——
# 上界由源头给这个词写了多少内容决定，**不随库变大**。
# ⇒ 判据按**候选集会不会随语料增长**分，不按"有没有 TEMP B-TREE"一刀切。
#   一刀切的后果是这条规则天天红、天天被无视，等于没有（`[[fix-regression-and-gate]]`）。
# ⚠️ 每条仍然带实测热态数，**下次谁改了 ORDER BY，时间上限是兜底**。
ALLOW_TEMP_BTREE = {
    # 唯一一条候选集**随语料增长**的，所以理由写得最长。
    "search":
        "`ORDER BY d.is_lemma DESC, LENGTH(d.word), d.word`：`LENGTH()` 不可索引，"
        "而这个排序是**产品决定**（词元排在变形形前面 —— 库里 96% 是活用形，"
        "不排序搜 `가` 出来的全是活用形）。"
        "⭐ 实测代价可接受所以**有意不上预计算表**：全库 11,944 个 1 字符前缀里"
        "最狠的 `가`（候选 19,700）热态 5.20 ms，2 字符最狠 0.58 ms。"
        "es/it 当年是 295/490 ms 才值得做 `search_prefix`（`[[search-prefix-precompute]]`）"
        "—— 韩语把 123 万词形摊在 11,944 个**首音节**上，拉丁语只有 26 个首字母，"
        "这是**字符系统本身**的差别，不是我们优化得好。"
        "🔴 什么会推翻它：① `LIMIT_MS['search']` 红了；② `ORDER BY` 改了或 SELECT 里"
        "加了按行计算的列；③ `dict` 再涨一个数量级。",

    # ↓ 以下候选集都是「一个词自己的行」，上界由源头决定，不随语料增长。
    "entries":  "排一个词的词条（`ORDER BY etym_no, seq`）。最多的 `하다` 也只有几条，热 0.02 ms",
    "senses":   "排一个词的义项（`ORDER BY e.etym_no, s.rank, s.id`，跨 LEFT JOIN 无法走单索引）。"
                "全库最多的 `하다` 38 条，热 0.32 ms",
    "relations": "排一个词的关系边（`ORDER BY r.kind, r.id`）。全库最多的 `물` 263 条，热 2.02 ms",
    "examples": "排一个词的例句（`ORDER BY x.sense_id IS NULL, x.id` —— 表达式不可索引）。"
                "全库最多的 `하다` 71 条，热 0.32 ms",
    "pronunciations":
        "排一个词的读音（`ORDER BY (src='g2p'), is_primary DESC, id` —— 表达式不可索引；"
        "这个顺序是**内容决定**：源头给的排在我们算的前面）。最多 5 条，热 0.03 ms",
    "baseOf":   "排这个词形指回的原形（`ORDER BY i.base, i.id`）。热 0.02 ms",
    "etymology": "排一个词的词源段（`ORDER BY etym_no`）。热 0.03 ms",
    "audio":    "排一个词的录音（`ORDER BY (kind<>'human'), id` —— 表达式不可索引；"
                "真人录音排在合成音前面）。并完转码重复之后最多 3 条，热 0.06 ms",
}
# 🔴 闸自己的闸：理由太短 ＝ 没写理由，等于偷偷把规则关掉
_thin = sorted(k for k, v in ALLOW_TEMP_BTREE.items() if len(v) < 30)
assert not _thin, "这些登记项没写清理由：%s" % _thin

# SCAN 门槛：表行数 ≤ 这个数时，全表扫无所谓（`hanja_reading` 8,432 行）
SCAN_OK_ROWS = 20000

# 🔴 允许全表扫的查询 —— **每条都要写明为什么**。
#    `stats` 是六个 `COUNT(*)`：**数一张表在 SQLite 里就是扫一张表**，
#    没有别的走法。把它算成缺陷会逼着我去"优化"一件本来就该这么贵的事。
#    ⚠️ 真要让它变快只有一条路：把这六个数**落成一张小表**、写库时维护。
#      现在不做，因为它一次页面加载才跑一次（见 `LIMIT_MS["stats"]` 的注释）。
ALLOW_SCAN = {"stats"}

f = lambda n: format(n, ",")


def extract_queries(src):
    """从 `korean.ts` 抠出 `名字: this.db.prepare(…)` 的 SQL。"""
    out = {}
    for m in re.finditer(r"(\w+):\s*this\.db\.prepare\(", src):
        name, i = m.group(1), m.end()
        depth, j = 1, m.end()
        while depth and j < len(src):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
            j += 1
        body = src[i:j - 1]
        # 模板串 / 拼接串 / 单引号串都剥成纯 SQL
        sql = "".join(re.findall(r"`([^`]*)`|'((?:[^'\\]|\\.)*)'", body)
                      and [a or b for a, b in
                           re.findall(r"`([^`]*)`|'((?:[^'\\]|\\.)*)'", body)])
        sql = sql.replace("\\'", "'")
        if sql.strip():
            out[name] = sql
    return out


def table_rows(con):
    rows = {}
    for (t,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'"):
        try:
            rows[t] = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        except sqlite3.Error:
            pass
    return rows


def nocase_audit(con):
    """🔴 ko 的前提：全库没有 NOCASE。它没了，`word_norm` 那套判据就不成立。"""
    bad = []
    for n, t, sql in con.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master"
            " WHERE sql IS NOT NULL"):
        if "NOCASE" in sql.upper():
            bad.append((t, n))
    return bad


def args_for(name, sql, con):
    if name in PARAMS:
        return PARAMS[name]
    n = sql.count("?")
    if n == 0:
        return [()]
    # 一参数的：按词形或词 id 传
    ids = {}
    for w in HEAVY_WORDS:
        r = con.execute("SELECT id FROM dict WHERE word_norm=?", (w,)).fetchone()
        if r:
            ids[w] = r[0]
    # `examples` / `audio` 用词形，其余用 word_id —— 判据来自 SQL 本身
    by_word = re.search(r"\b(word|x\.word)\s*=\s*\?", sql) is not None
    return [((w if by_word else ids[w]),) for w in HEAVY_WORDS if w in ids]


def check(db=None):
    """→ (红的列表, 报告行)。"""
    db = db or paths.DB
    red, report = [], []
    if not TS.exists():
        return [("闸自己", "`korean.ts` 不在 —— 抠不到任何查询")], report
    qs = extract_queries(TS.read_text(encoding="utf-8"))

    # ── 闸自己的闸 ──
    missing = sorted(EXPECT_QUERIES - set(qs))
    extra = sorted(set(qs) - EXPECT_QUERIES)
    if missing:
        red.append(("闸自己", "这几条查询抠不到：%s —— **要么被删了，要么正则失效**，"
                              "两种都不能当成「全绿」" % missing))
    if extra:
        report.append(("ℹ️", "`korean.ts` 里多出的查询（本闸没量过）：%s" % extra))

    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    rows = table_rows(con)

    nc = nocase_audit(con)
    if nc:
        red.append(("NOCASE 审计",
                    "库里出现了 NOCASE：%s —— ko 的前提是**全库没有 NOCASE**"
                    "（它只折 ASCII，对谚文无效）。出现了就要像 de 的 A6 那样"
                    "配一条 BINARY 双胞胎，否则是静默全表扫" % nc))
    else:
        report.append(("✅", "NOCASE 审计：全库 0 个 NOCASE 索引/列声明（ko 的前提成立）"))

    # 🔴🔴 统计信息是**前提，不是并列的一条检查**：没有它，下面量到的计划与耗时
    #    全部是另一个世界的数，报出来只会误导。⇒ 当场返回，不往下量。
    #    ⚠️ 这不是"少查几条"——是**不假装那些数还有意义**。
    #    ⭐ 顺带治好了一个真问题：变异验证里「把 `sqlite_stat1` 删掉」那条，
    #      闸老老实实拿坏计划把每条查询跑了 40 遍，**自己跑成了超时** ——
    #      与上面「计划红了跳过计时」同一个毛病：**闸被它正在诊断的病拖垮**。
    if not con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'").fetchone()[0]:
        red.append(("统计信息", "库里没有 `sqlite_stat1` —— 计划器会把驱动表选反"
                                "（实测热查询 0.04 ms → 51 ms）。"
                                "先跑 `python3 ko/pipeline/analyze_db.py --apply`，"
                                "**在那之前下面的计划与耗时都不作数**"))
        con.close()
        return red, report

    for name in sorted(qs):
        if name not in EXPECT_QUERIES:
            continue
        sql = qs[name]
        argv = args_for(name, sql, con)
        if not argv:
            red.append((name, "没有可用的参数 —— 量不了"))
            continue
        # ── 先只取计划，不计时 ──
        # 🔴 顺序是有意的：**计划已经判定是全表扫时，再去计时毫无意义，
        #    而且会让闸自己卡死** —— 变异验证第一版把 `search` 改成不可索引的
        #    表达式，闸老老实实把 123 万行扫了 8 遍，两分钟没跑完。
        #    ⇒ 计划红了就跳过计时。**闸不该被它正在诊断的病拖垮。**
        plans = []
        for a in argv:
            try:
                plans.append([r[-1] for r in
                              con.execute("EXPLAIN QUERY PLAN " + sql, a)])
            except sqlite3.Error as e:
                red.append((name, "跑不起来：%s" % e))
                break
        if not plans:
            continue
        flat = [ln for p_ in plans for ln in p_]
        plan_red = len(red)

        # ① SCAN 大表
        for ln in flat:
            m = re.match(r"\s*SCAN (\w+)", ln)
            if not m:
                continue
            tbl = m.group(1)
            # 计划里写的可能是别名；用别名找不到就按 SQL 里的 `FROM <表> <别名>` 还原
            real = tbl if tbl in rows else None
            if real is None:
                mm = re.search(r"\b(?:FROM|JOIN)\s+(\w+)\s+(?:AS\s+)?%s\b"
                               % re.escape(tbl), sql)
                real = mm.group(1) if mm else tbl
            n = rows.get(real, 0)
            if n > SCAN_OK_ROWS and name not in ALLOW_SCAN:
                red.append((name, "🔴 `%s`（%s 行）是 **SCAN** 不是 SEARCH：%s"
                            % (real, f(n), ln.strip())))

        # ② 临时 B 树排序
        tb = [ln for ln in flat if "TEMP B-TREE" in ln]
        if tb and name not in ALLOW_TEMP_BTREE:
            red.append((name, "🔴 %s —— 排序走临时 B 树。"
                              "it 那轮两条索引都 SEARCH 了、查询仍 923 ms，慢的全在这儿。"
                              "确认代价可接受就写进 `ALLOW_TEMP_BTREE` **并写明理由**"
                        % tb[0].strip()))

        if len(red) > plan_red:
            report.append(("🔴", "%-15s 计划已判红，跳过计时" % name))
            continue

        worst_ms, worst_arg = 0.0, None
        for a in argv:
            for _ in range(3):                       # 预热（量热态）
                con.execute(sql, a).fetchall()
            t = time.time()
            for _ in range(5):
                con.execute(sql, a).fetchall()
            ms = (time.time() - t) * 1000 / 5
            if ms > worst_ms:
                worst_ms, worst_arg = ms, a

        # ③ 热态耗时
        cap = LIMIT_MS.get(name, LIMIT_MS["_default"])
        if worst_ms > cap:
            red.append((name, "🔴 热态 %.2f ms（上限 %.1f，参数 %s）"
                        % (worst_ms, cap, worst_arg)))
        report.append(("✅" if worst_ms <= cap else "🔴",
                       "%-15s 热 %6.2f ms / 上限 %4.1f   %s%s"
                       % (name, worst_ms, cap,
                          "SEARCH" if any("SEARCH" in x for x in flat) else "全表扫(已登记)",
                          "  ⚠️TEMP B-TREE(已登记)" if tb and name in ALLOW_TEMP_BTREE
                          else ("  🔴TEMP B-TREE" if tb else ""))))
    con.close()
    return red, report


# ══════════════════════════════════════════════════════════════════
# 🔴 变异验证：**一条永远通过的检查等于没检查。**
#    每条都注入一个真会发生的坏改动，闸必须当场红。
# ══════════════════════════════════════════════════════════════════
def mutate():
    import shutil
    import tempfile
    src = TS.read_text(encoding="utf-8")
    assert "exact" not in ALLOW_TEMP_BTREE, \
        "`exact` 被登记进 ALLOW_TEMP_BTREE 了 —— 第三条变异失效，换一个锚点"
    ok = True

    def run_with_ts(newsrc):
        TS.write_text(newsrc, encoding="utf-8")
        try:
            return check()[0]
        finally:
            TS.write_text(src, encoding="utf-8")

    cases = [
        ("删掉一条查询（`hanjaReadings`）",
         lambda: run_with_ts(re.sub(
             r"\n\s*hanjaReadings: this\.db\.prepare\([^;]*?\),", "", src, count=1))),
        ("把 `search` 的索引列换成不可索引的表达式",
         lambda: run_with_ts(src.replace(
             "WHERE d.word_norm >= ? AND d.word_norm < ?",
             "WHERE LENGTH(d.word_norm) >= LENGTH(?) AND d.word || '' <> ?", 1))),
        # 🔴 这条变异**换过一次**：原来是「给 `relations` 加个不可索引的排序」——
        #    而 `relations` 后来登记进了 `ALLOW_TEMP_BTREE`，那条变异**静默失效**
        #    （`[[ko-dict-pipeline]]`：一天内四条变异静默失效，锚在会变的东西上）。
        #    ⇒ 改成锚在**没有登记**的那条（`exact`）上，并断言它确实没登记。
        ("给没登记过的 `exact` 加一条走临时 B 树的排序",
         lambda: run_with_ts(src.replace(
             "'SELECT id, word, is_lemma FROM dict WHERE word_norm = ?'",
             "'SELECT id, word, is_lemma FROM dict WHERE word_norm = ?"
             " ORDER BY LENGTH(word), id'", 1))),
    ]
    for name, fn in cases:
        red = fn()
        good = bool(red)
        ok &= good
        print("   %s %-40s %s" % ("✅" if good else "🔴", name,
                                  red[0][1][:64] if red else "闸没红 —— 这条是假闸"))

    # 第四条动的是**库**不是源码：把统计信息删掉
    with tempfile.TemporaryDirectory() as d:
        cp = _pl.Path(d) / "x.sqlite"
        shutil.copy(paths.DB, cp)
        c = sqlite3.connect(cp)
        # 🔴 **不在这儿跑 `ANALYZE`**：它在 230 万行上要跑近一分钟，
        #    而第一版就是这么写的 —— **变异验证自己跑成了超时**。
        #    前提改成断言：真库必须已经有 `sqlite_stat1`（基线那条闸已经保证了）。
        assert c.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'"
        ).fetchone()[0], "真库里没有 sqlite_stat1 —— 这条变异无从做起"
        c.execute("DROP TABLE sqlite_stat1")
        c.commit()
        c.close()
        red = check(cp)[0]
        good = any("统计信息" in r[0] for r in red)
        ok &= good
        print("   %s %-40s %s" % ("✅" if good else "🔴", "把 `sqlite_stat1` 删掉",
                                  "闸红了（对）" if good else "闸没红 —— 这条是假闸"))
    print("\n   变异验证 %s" % ("全部逮到 ✓" if ok else "🔴 有假闸"))
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    if a.mutate:
        print("\n═══ ko 查询计划闸 · 变异验证 ═══")
        _sys.exit(0 if mutate() else 1)

    red, report = check()
    print("\n═══ ko 查询计划闸（展示层真正跑的 %d 条查询）═══" % len(EXPECT_QUERIES))
    for tag, ln in report:
        print("   %s %s" % (tag, ln))
    if not red:
        print("\n■ ko 查询计划闸全绿 ✓")
        _sys.exit(0)
    print("\n🔴 ko 查询计划闸：%d 条红" % len(red))
    for name, why in red:
        print("   %-16s %s" % (name, why))
    _sys.exit(1)
