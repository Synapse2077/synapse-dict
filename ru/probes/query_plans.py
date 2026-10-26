"""查询计划闸：展示层真正跑的每一条查询，**走的是索引还是全表扫**。ru，2026-10-25（阶段 9c）。

照 vi 的 `vi/probes/query_plans.py`（判据与 `[[query-perf-collation-traps]]` 的来历见那份文件头）。ru 的不同：
· 判据从 `packages/dict-core/src/russian.ts` **原文抠**，抠不到或多出没登记的都红（闸自己的闸）。
· 「重词」挑的是 ru 各层行数最多的：`полвека`（1,108 条关系）／`вода`（242 KB 的页）／`замок`（13 个 entry）……
· 🔴 索引侧的变异**跑在库的副本上**（vi 那份直接 DROP/CREATE 真库的索引 —— 写真库要过 dbtool，副本不用）。
· ⚠️ 别把别门的结论当结论（vi：索引是全部功劳、ANALYZE 无可测变化；ko：相反）—— 本门自己量。

跑：
    python3 ru/probes/query_plans.py
    python3 ru/probes/query_plans.py --mutate
"""
import re
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                                       # noqa: E402

TS = paths.ROOT / "packages" / "dict-core" / "src" / "russian.ts"
F = lambda n: format(n, ",")                                       # noqa: E731

# 🔴 **闸自己的闸**：`russian.ts` 里这些查询必须都抠到。
#    少一条就说明正则漂了（或者有人把查询改成了别的写法），而**抠不到的查询
#    这道闸完全看不见** —— 那正是 ko 的账的闸栽过的「结构性失明」形状。
EXPECT_QUERIES = {
    "stats", "search", "exactWord", "exactNorm", "homographs", "entries", "stress",
    "senses", "glosses", "tags", "pronunciations", "inflections", "examples",
    "relations", "etymologies", "audios", "pointers",
    "exactFold", "yoVariants",          # R30（2026-10-25）：ё 召回键
}

# 行数低于这个的表，SCAN 不算问题（整表就在一两页里）
ROW_FLOOR = 5000

# 🔴 **聚合型查询免 SCAN 判据，但必须逐条写明理由**（不是白名单，是「这条查询的
#    工作本身就是扫全表」）。`stats` 是 `SELECT COUNT(*) FROM <七张表>` ——
#    数全表的行**不可能不扫全表**，它的真判据是热态上限（60 ms，实测 20.5 ms）。
#    ⚠️ 第一版没有这个豁免，于是它报「stats 大表全表扫 ×6」—— 判据说的是
#      「本该用索引却扫了全表」，而 COUNT(*) 不是那种情形。
AGGREGATE_FULL_SCAN = {
    "stats": "SELECT COUNT(*) 数全表的行，扫全表是它的工作本身；真判据是热态上限",
}

# 🔴🔴 **临时 B 树的代价取决于排序的行数，不取决于它存不存在。**
#    第一版把任何 `USE TEMP B-TREE` 都判红 ⇒ 15 条查询里 9 条红，
#    而它们排的是 10–200 行（热态 0.015–0.8 ms）—— 排 18 行用临时 B 树是**免费的**。
#    ⚠️ 要是改成「登记 9 条白名单」，那就是 `[[gate-registers-status-quo-as-spec]]`：
#      如实登记现状，然后再也不问现状对不对。
#    ⇒ 判据按**含义**写：排序的行数超过这个数才要求登记理由。
#      it 那轮的教训（两条索引都 SEARCH 了而查询 923 ms，慢的全在临时排序）
#      发生在**大集合**上，这个门槛正是为那种情形留的。
TEMP_BTREE_ROW_FLOOR = 200

# 允许 TEMP B-TREE 的查询 ＋ 理由（**逐条量过才登记**，见首跑报告）
ALLOW_TEMP_BTREE = {
    "search": "ORDER BY 里有 LENGTH() 表达式，索引产不出这个顺序；LIMIT 已挡住代价",
}

# 🔴 `search` 的上限 50 ms 是**量过之后有意放宽**的（`[[record-the-negative-decision]]`）：
#    最狠的单字母前缀 `п`（15.5 万个词形）热态 37.5 ms、`с` 22.7、`к` 19.7；两字母最狠 `по` 15.3。
#    代价全在排序（`ORDER BY is_lemma DESC, LENGTH(word), word` 要排整个前缀范围）。
#    参照：ko 最狠 5.2 ms 有意不做、es/it 当年 295/490 ms 才做了 `search_prefix` 预计算 ——
#    ru 在两者之间，**低于人眼可感的 ~100 ms**；预计算表还会带来新的失效方式（dict 一动就过期）。
#    🔴 **什么会推翻**：任一前缀热态 > 50 ms（本闸当场红），或用户反馈下拉卡顿。
#    ⚠️ ANALYZE 之后没有可测变化（16.1 → 21.8 ms，噪声）—— 与 vi 同、与 ko 反；别门的结论不当结论。
MS_CAP = {"stats": 400.0, "search": 50.0}
MS_CAP_DEFAULT = 5.0

# 「重词」：各层行数最多的。`ебать` 是全库关系最多的页（5,640 条）
HEAVY_WORDS = ["вода", "замок", "полвека", "все", "Москва", "быть", "идти", "дом", "показать", "ебать"]
PARAMS = {
    "stats": [()],
    # 最狠的三个前缀（量过）：п（15.5 万）／с／по
    # R30 起区间走 `word_fold`（召回键）、逐字对上 `word_norm` 的排前 ⇒ 5 个参数。
    #   `е` 是新加的最狠前缀：折叠后它把 е- 与 ё- 开头的两批词并在一个区间里
    "search": [(f, f + "\uffff", n, n + "\uffff", 30) for n, f in
               (("п", "п"), ("с", "с"), ("по", "по"), ("е", "е"), ("ё", "е"), ("всё", "все"))],
    "exactWord": [(w,) for w in HEAVY_WORDS],
    "exactNorm": [(w.lower(),) for w in HEAVY_WORDS],
    "homographs": [(w.lower(), 0) for w in HEAVY_WORDS],
    "exactFold": [(w.lower().replace("ё", "е"),) for w in HEAVY_WORDS + ["чёс", "ёлка"]],
    "yoVariants": [(w.lower().replace("ё", "е"), w.lower()) for w in HEAVY_WORDS + ["всё", "ёлка"]],
}


def extract_queries(src):
    """从 `russian.ts` 抠出 `名字: this.db.prepare(…)` 的 SQL。"""
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
        parts = re.findall(r"`([^`]*)`|'((?:[^'\\]|\\.)*)'", body)
        sql = "".join(a or b for a, b in parts).replace("\\'", "'")
        if sql.strip():
            out[name] = sql
    return out


def table_rows(con):
    rows = {}
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"
                            " AND name NOT LIKE 'sqlite_%'"):
        try:
            rows[t] = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        except sqlite3.Error:
            pass
    return rows


def nocase_audit(con):
    """🔴 vi 的前提：全库没有 NOCASE。

    `[[query-perf-collation-traps]]`：**NOCASE 列上做 BINARY 比较＝静默全表扫**。
    vi 的归一在 `word_norm` 里（`criteria.norm_vi` 小写 ＋ NFC），
    所以**一个 NOCASE 都不该有** —— 有了就说明有人想用排序规则代替归一列，
    而那条路在越南语上必然错（NOCASE 只折 ASCII，`Ắ`/`ắ` 折不了）。

    🔴🔴 **判据收窄过一次，而逮到它的是一条正确的决定。** 第一版在 DDL 文本里找
       `NOCASE` 字样 —— 当场报红 `dict`，而那个 `NOCASE` 在**注释里**，
       写的正是「这一列**有意不带** `COLLATE NOCASE`（NOCASE 只折 ASCII，
       `'VIỆT' = 'việt' COLLATE NOCASE → 0`）」。
       **判据把一条正确决定的说明文字判成了违规**，而且方向最坏：它逼人去删那段注释。
    ⇒ 先剥掉 SQL 注释（`--` 到行尾、`/* */`）再找。
      `[[criteria-narrower-than-you-think]]`：判据说的是「有列用了 NOCASE 排序规则」，
      不是「DDL 文本里出现过这个词」。
    """
    def strip_comments(sql):
        sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
        return "\n".join(re.sub(r"--.*$", "", ln) for ln in sql.split("\n"))

    return [(t, n) for n, t, sql in con.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL")
        if "NOCASE" in strip_comments(sql).upper()]


def args_for(name, sql, con):
    if name in PARAMS:
        return PARAMS[name]
    n = sql.count("?")
    ids = {}
    for w in HEAVY_WORDS:
        r = con.execute("SELECT id FROM dict WHERE word=?", (w,)).fetchone()
        if r:
            ids[w] = r[0]
    if n == 0:
        return [()]
    return [tuple([ids[w]] * n) for w in HEAVY_WORDS if w in ids]


def check(db=None):
    """→ (红的列表, 报告行)。"""
    db = db or paths.DB
    red, report = [], []
    if not TS.exists():
        return [("闸自己", "`russian.ts` 不在 —— 抠不到任何查询")], report
    qs = extract_queries(TS.read_text(encoding="utf-8"))
    miss = sorted(EXPECT_QUERIES - set(qs))
    extra = sorted(set(qs) - EXPECT_QUERIES)
    if miss:
        red.append(("闸自己", "从 `russian.ts` **抠不到** %s —— 正则漂了，"
                              "而抠不到的查询这道闸完全看不见" % "、".join(miss)))
    if extra:
        red.append(("闸自己", "`russian.ts` 里多了 %s 条没登记的查询：%s —— "
                              "登记进 `EXPECT_QUERIES`，不然它跑成全表扫也没人说话"
                    % (len(extra), "、".join(extra))))
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    nocase = nocase_audit(con)
    if nocase:
        red.append(("NOCASE", "全库出现 NOCASE：%s —— ru 的归一在 `word_norm` 里，"
                              "NOCASE 只折 ASCII，西里尔大小写折不了（`'МОСКВА' = 'москва' COLLATE NOCASE → 0`）" % nocase))
    rows = table_rows(con)
    big = {t for t, n in rows.items() if n >= ROW_FLOOR}
    report.append("■ 查询计划闸（ru）：从 `russian.ts` 抠到 %d 条查询，大表门槛 %s 行"
                  % (len(qs), F(ROW_FLOOR)))
    report.append("   `sqlite_stat1`：%s"
                  % ("在（ANALYZE 跑过）" if con.execute(
                      "SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'"
                  ).fetchone()[0] else "🔴 不在 —— B11 没跑"))
    for name in sorted(qs):
        sql = qs[name]
        args = args_for(name, sql, con)
        if not args:
            red.append((name, "取不到参数样本 —— 这条查询没被量过"))
            continue
        plan = [r[-1] for r in con.execute("EXPLAIN QUERY PLAN " + sql, args[0])]
        scans = [p for p in plan if p.strip().startswith("SCAN")
                 and any(" %s" % t in p for t in big)]
        temp = [p for p in plan if "TEMP B-TREE" in p]
        for _ in range(2):                                   # 预热
            for a in args:
                con.execute(sql, a).fetchall()
        t0 = time.perf_counter()
        for a in args:
            con.execute(sql, a).fetchall()
        ms = (time.perf_counter() - t0) * 1000 / len(args)
        cap = MS_CAP.get(name, MS_CAP_DEFAULT)
        marks = []
        n_rows = max(len(con.execute(sql, a).fetchall()) for a in args)
        if scans and name not in AGGREGATE_FULL_SCAN:
            red.append((name, "**大表全表扫**：%s" % " ／ ".join(scans)))
            marks.append("🔴SCAN")
        elif scans:
            marks.append("⚠️SCAN(聚合型，已登记)")
        if temp and n_rows > TEMP_BTREE_ROW_FLOOR and name not in ALLOW_TEMP_BTREE:
            red.append((name, "排 %s 行用临时 B 树（超过 %d 行的门槛），"
                              "而 `ALLOW_TEMP_BTREE` 里没登记理由"
                        % (F(n_rows), TEMP_BTREE_ROW_FLOOR)))
            marks.append("🔴TEMP")
        elif temp:
            marks.append("⚠️TEMP(%s 行%s)" % (F(n_rows),
                                             "，已登记" if name in ALLOW_TEMP_BTREE else ""))
        if ms > cap:
            red.append((name, "热态 %.2f ms 超过上限 %.1f ms" % (ms, cap)))
            marks.append("🔴慢")
        report.append("   %-14s %7.3f ms（上限 %4.1f）%s %s"
                      % (name, ms, cap, "✅" if not marks else " ".join(marks),
                         plan[0][:62] if plan else ""))
    con.close()
    return red, report


def mutate():
    """变异验证：三条判据**真的逮得到东西**。

    🔴 判据的素材是 `russian.ts` 和库的索引 ⇒ 变异动这两样，**跑完原样还原**。
    """
    base, _ = check()
    if base:
        print("🔴 基线就不绿，变异验证没有意义：")
        for c, w in base:
            print("   %-14s %s" % (c, w))
        return False
    ok = True
    orig = TS.read_text(encoding="utf-8")

    def expect(cid, name, mutated):
        nonlocal ok
        if mutated is None or mutated == orig:
            print("   🔴🔴 %-10s %s —— **锚失效，什么都没注入**" % (cid, name))
            ok = False
            return
        TS.write_text(mutated, encoding="utf-8")
        try:
            hit = any(c == cid for c, _ in check()[0])
        finally:
            TS.write_text(orig, encoding="utf-8")
        ok &= hit
        print("   %s %-10s %s" % ("✅" if hit else "🔴 没逮到", cid, name))

    print("═══ 变异验证 ═══")
    # ① 抠不到查询 ⇒ 闸自己红（把 `pointers:` 改名，它就从 EXPECT 里消失）
    expect("闸自己", "把 `pointers` 查询改名（闸就抠不到它了）",
           orig.replace("      pointers: this.db.prepare(", "      pointersX: this.db.prepare(", 1))
    # ② 加一条没登记的查询 ⇒ 闸自己红
    expect("闸自己", "加一条没登记进 `EXPECT_QUERIES` 的查询",
           orig.replace("      pointers: this.db.prepare(",
                        "      mutantQ: this.db.prepare('SELECT 1'),\n      pointers: this.db.prepare(", 1))
    # ③ **大表全表扫**：把 `pointers` 的 WHERE 去掉 word_id ⇒ SCAN sense_src
    # 🔴🔴 **2026-10-06：这条变异从 10-05 起一直是空操作，而它看起来是绿的。**
    #    原来的锚是字面量 `"WHERE word_id = ? AND sense_id IS NULL"`，
    #    而 W15 结清那天这条查询加了表别名和一个条件，变成
    #        `WHERE s.word_id = ? AND s.sense_id IS NULL AND s.ptr_class = 'pointer'`
    #    ⇒ `str.replace` **什么都没替换**，`expect()` 照样跑、照样报结果。
    # ⭐ 逮到它的是 W19 新建的那档「变异台账」**第一次强制跑**（`run_gates.py --mutate`）——
    #   `expect()` 本来就会把 `None` 印成「🔴🔴 锚失效，什么都没注入」，
    #   **而在那之前没有任何东西逼人跑这条路**。这正是 W19 那笔账的全部内容。
    # ⇒ 锚从**字面量**改成**结构**：在 `pointers` 那一块里找「`…word_id = ? AND`」
    #   并整段去掉（别名有没有都认），替换后与原文相同就返回 None ⇒ 大声报锚失效。
    _ptr = re.sub(r"(pointers: this\.db\.prepare\(`[\s\S]{0,400}?WHERE\s+)"
                  r"[A-Za-z_]*\.?word_id\s*=\s*\?\s+AND\s+",
                  r"\1", orig, count=1)
    expect("pointers", "🔴 去掉 `pointers` 的 `word_id = ?` 条件 ⇒ 大表全表扫",
           _ptr if _ptr != orig else None)
    # ④⑤ 索引侧／库侧的变异：**跑在副本上**（不碰真库）
    import shutil, tempfile
    with tempfile.TemporaryDirectory() as td:
        cp = Path(td) / paths.DB.name
        shutil.copy2(paths.DB, cp)
        con = sqlite3.connect(cp)
        con.execute("DROP INDEX IF EXISTS idx_sense_src_word")
        con.commit()
        con.close()
        hit4 = any(c == "pointers" for c, _ in check(cp)[0])
        ok &= hit4
        print("   %s %-10s 🔴 删掉 `idx_sense_src_word` ⇒ 指针查询变全表扫" % ("✅" if hit4 else "🔴 没逮到", "pointers"))
        con = sqlite3.connect(cp)
        con.execute("CREATE INDEX IF NOT EXISTS idx_sense_src_word ON sense_src(word_id)")
        con.execute("DROP INDEX IF EXISTS idx_infl_entry")
        con.commit()
        con.close()
        hit6 = any(c == "inflections" for c, _ in check(cp)[0])
        ok &= hit6
        print("   %s %-10s 🔴 删掉 `idx_infl_entry` ⇒ 变位表（638 万行）全表扫" % ("✅" if hit6 else "🔴 没逮到", "inflections"))
        con = sqlite3.connect(cp)
        con.execute("CREATE TABLE IF NOT EXISTS _mut_nocase (w TEXT COLLATE NOCASE)")
        con.commit()
        con.close()
        hit5 = any(c == "NOCASE" for c, _ in check(cp)[0])
        ok &= hit5
        print("   %s %-10s 🔴 建一张带 COLLATE NOCASE 的表" % ("✅" if hit5 else "🔴 没逮到", "NOCASE"))
    good = TS.read_text(encoding="utf-8") == orig
    ok &= good
    print("   %s 还原回核：`russian.ts` 一字未改=%s（真库从没被写过）" % ("✅" if good else "🔴🔴", good))
    return ok


def main():
    if "--mutate" in sys.argv:
        raise SystemExit(0 if mutate() else 1)
    red, report = check()
    for line in report:
        print(line)
    print()
    for cid, why in red:
        print("   🔴 %-14s %s" % (cid, why))
    if not red:
        print("   ✅ 全绿（每条查询都走索引、热态都在上限内）")
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
