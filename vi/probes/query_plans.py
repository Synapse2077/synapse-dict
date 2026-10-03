#!/usr/bin/env python3
"""查询计划闸：展示层真正跑的每一条查询，**走的是索引还是全表扫**。vi，2026-10-03（阶段 9c）。

═══ 为什么要这道闸 ═══
`[[query-perf-collation-traps]]` 记着同一个病在本仓库栽过**五次**，每次都是
「等到超时了才去 EXPLAIN」。用户点破的是**顺序**：「你跑之前先试一下有没有走索引不更好？」
🔴 vi 这一轮它当场兑现：**W15 的指针查询在每开一个词条页都跑，而 `sense_src` 上
   一个索引都没有** ⇒ `SCAN sense_src`（136,034 行），实测 **14.40 ms**，
   是同一页其余五条（0.07–1.15 ms）的 **100 倍**。加索引之后 **0.018 ms（快 800 倍）**。
⚠️ 这条热路径是**阶段 9 才出现的** —— 建表时 `sense_src` 只是证据层，没人按 `word_id` 查它。
   「性能要等数据长大、或等读取路径出现才咬人」。

═══ 🔴🔴 vi 的结论与 ko **相反**，照搬会留着那 14 ms ═══
ko 那轮的结论是「`ANALYZE` 一条把 51.45ms → 0.04ms，**一个索引都没加**；
第一反应加复合索引只降到 48ms —— 计划器不肯用它」。
vi 实测反过来：**索引是全部功劳，`ANALYZE` 之后没有可测的进一步变化**
（0.018 → 0.025 ms，在噪声里）。
⇒ `[[decision-not-propagated-across-editions]]` 的反向用法：**别把别门的结论当结论**，
  每门自己量。`ANALYZE` 仍然跑了（B11 要求八门都跑），但对 vi 它不是那个起作用的东西。

═══ 🔴 判据从 `vietnamese.ts` **原文抠出来**，不在这儿抄一份 ═══
一条查询在这儿抄一遍，它和展示层迟早漂开 —— 那时这道闸量的是**一条没人跑的 SQL**。
⇒ 本文件从 `packages/dict-core/src/vietnamese.ts` 里正则抠 `名字: this.db.prepare(…)`，
  **抠不到或抠少了就直接红**（闸自己的闸，见 `EXPECT_QUERIES`）。

═══ 三条判据，缺一条都放得过真问题 ═══
① **`SCAN <表>` ⇒ 红。**
   ⚠️ `SCAN dict USING COVERING INDEX idx_x` **这行字最阴险** —— 索引名在，
     干的却是把整个索引从头扫到尾。判据认的是 `SEARCH` 这个词，不是「有没有 INDEX 字样」。
   ⚠️ 小表上的 SCAN 无所谓 ⇒ 按**表的行数**设门槛（`ROW_FLOOR`）。
② **`USE TEMP B-TREE FOR ORDER BY` ⇒ 报出来**（计划对了也可能全花在临时排序上）。
③ **热态耗时上限。** 计划对了也可能慢（相关子查询 × 未截断行数 = O(n²)）。

═══ ⚠️ 量性能先分冷热 ═══
同一条查询新开连接第一遍与热态差一个数量级，差额全是把索引页读进 page cache。
**每键代价看热态**（API 进程长驻），冷启的数照打但不做闸。

跑：
    python3 vi/probes/query_plans.py
    python3 vi/probes/query_plans.py --mutate
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

TS = paths.ROOT / "packages" / "dict-core" / "src" / "vietnamese.ts"
F = lambda n: format(n, ",")                                       # noqa: E731

# 🔴 **闸自己的闸**：`vietnamese.ts` 里这些查询必须都抠到。
#    少一条就说明正则漂了（或者有人把查询改成了别的写法），而**抠不到的查询
#    这道闸完全看不见** —— 那正是 ko 的账的闸栽过的「结构性失明」形状。
EXPECT_QUERIES = {
    "stats", "search", "exactWord", "exactNorm", "homographs", "entries",
    "pronunciations", "spellings", "senses", "relations", "classifiers",
    "examples", "etymologies", "audios", "pointers",
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

# 允许 TEMP B-TREE 的查询 ＋ 理由。**空着不行，必须逐条说明**。
ALLOW_TEMP_BTREE = {
    # `search` 的 ORDER BY 是 `is_lemma DESC, syllables, LENGTH(word), word`，
    # 四个键里有表达式（`LENGTH`）⇒ 任何索引都产不出这个顺序。
    # ⭐ 它**已经被 LIMIT 挡住**：范围查询先拿到前缀命中的那一小批，再排序。
    #   实测最狠的前缀热态在 10 ms 以内（见报告），而 es/it 当年 295/490 ms 才值得做
    #   `search_prefix` 预计算 ⇒ 这里**有意不优化**。
    "search": "ORDER BY 里有 LENGTH() 表达式，索引产不出这个顺序；LIMIT 已挡住代价",
    # 🔴 **有意不加索引，而这个决定是量出来的**（`[[record-the-negative-decision]]`）：
    #    `ORDER BY r.kind, r.id`，而 `idx_rel_word` 只有 `word_id`。
    #    实测最狠的词 `bánh` 有 **411 条**可出版关系，热态 **1.972 ms**（上限 5 ms）。
    #    临时建了 `(word_id, kind)` 复合索引量过：**1.751 ms，而临时 B 树照样在**
    #    —— 省 0.2 ms，换 145,085 行上的一个索引，不值。
    #    ⭐ 这正是 ko 记过的那条原样重演：「第一反应加复合索引只降到 48ms，
    #      **计划器不肯用它**」—— 那门是不肯用，这门是用了但照样排序。
    # 🔴 **什么会推翻**：某个词形的可出版关系涨到 2,000 行以上（届时这条会撞 5 ms 上限
    #    而当场红），或 `ORDER BY` 改成能被索引覆盖的形式。
    "relations": "排序键 (kind, id) 无索引；实测最坏 411 行 1.97 ms，"
                 "复合索引实测只省 0.2 ms 且临时 B 树仍在 ⇒ 有意不加",
}

# 热态耗时上限（ms，每次调用）。🔴 **按用途分档**：
#   词条页的每条查询都在一次页面请求里跑一遍 ⇒ 卡严；
#   `stats` 只在首页跑一次 ⇒ 松。
MS_CAP = {"stats": 60.0, "search": 15.0}
MS_CAP_DEFAULT = 5.0

# 拿来当样本的「重词」—— 挑的是各层行数最多的，不是随机词。
HEAVY_WORDS = ["nhà", "con", "ăn", "đi", "mai", "UBND"]
PARAMS = {
    "stats": [()],
    "search": [("ng", "ng￿", 30), ("c", "c￿", 30), ("a", "a￿", 30)],
    "exactWord": [(w,) for w in HEAVY_WORDS],
    "exactNorm": [(w,) for w in HEAVY_WORDS],
}


def extract_queries(src):
    """从 `vietnamese.ts` 抠出 `名字: this.db.prepare(…)` 的 SQL。"""
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
        r = con.execute("SELECT id FROM dict WHERE word_norm=?", (w,)).fetchone()
        if r:
            ids[w] = r[0]
    if n == 0:
        return [()]
    # `spellings` 那条是 UNION ALL、两个 `?` 都是同一个 word_id
    return [tuple([ids[w]] * n) for w in HEAVY_WORDS if w in ids]


def check(db=None):
    """→ (红的列表, 报告行)。"""
    db = db or paths.DB
    red, report = [], []
    if not TS.exists():
        return [("闸自己", "`vietnamese.ts` 不在 —— 抠不到任何查询")], report
    qs = extract_queries(TS.read_text(encoding="utf-8"))
    miss = sorted(EXPECT_QUERIES - set(qs))
    extra = sorted(set(qs) - EXPECT_QUERIES)
    if miss:
        red.append(("闸自己", "从 `vietnamese.ts` **抠不到** %s —— 正则漂了，"
                              "而抠不到的查询这道闸完全看不见" % "、".join(miss)))
    if extra:
        red.append(("闸自己", "`vietnamese.ts` 里多了 %s 条没登记的查询：%s —— "
                              "登记进 `EXPECT_QUERIES`，不然它跑成全表扫也没人说话"
                    % (len(extra), "、".join(extra))))
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    nocase = nocase_audit(con)
    if nocase:
        red.append(("NOCASE", "全库出现 NOCASE：%s —— vi 的归一在 `word_norm` 里，"
                              "NOCASE 只折 ASCII，在越南语上必然错" % nocase))
    rows = table_rows(con)
    big = {t for t, n in rows.items() if n >= ROW_FLOOR}
    report.append("■ 查询计划闸（vi）：从 `vietnamese.ts` 抠到 %d 条查询，大表门槛 %s 行"
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

    🔴 判据的素材是 `vietnamese.ts` 和库的索引 ⇒ 变异动这两样，**跑完原样还原**。
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
    expect("pointers", "🔴 去掉 `pointers` 的 `word_id = ?` 条件 ⇒ 大表全表扫",
           orig.replace("WHERE word_id = ? AND sense_id IS NULL",
                        "WHERE sense_id IS NULL AND ? IS NOT NULL", 1))
    # ④ 索引侧的变异：删掉 `idx_sense_src_word` ⇒ pointers 变 SCAN
    con = sqlite3.connect(paths.DB)
    con.execute("DROP INDEX IF EXISTS idx_sense_src_word")
    con.commit()
    con.close()
    hit4 = any(c == "pointers" for c, _ in check()[0])
    con = sqlite3.connect(paths.DB)
    con.execute("CREATE INDEX IF NOT EXISTS idx_sense_src_word ON sense_src(word_id)")
    con.commit()
    con.close()
    ok &= hit4
    print("   %s %-10s 🔴 删掉 `idx_sense_src_word`（它是本轮逮到的那个缺陷）"
          % ("✅" if hit4 else "🔴 没逮到", "pointers"))
    # ⑤ NOCASE 审计：真建一张带 NOCASE 的表
    con = sqlite3.connect(paths.DB)
    con.execute("CREATE TABLE IF NOT EXISTS _mut_nocase (w TEXT COLLATE NOCASE)")
    con.commit()
    con.close()
    hit5 = any(c == "NOCASE" for c, _ in check()[0])
    con = sqlite3.connect(paths.DB)
    con.execute("DROP TABLE _mut_nocase")
    con.commit()
    con.close()
    ok &= hit5
    print("   %s %-10s 🔴 建一张带 COLLATE NOCASE 的表" % ("✅" if hit5 else "🔴 没逮到", "NOCASE"))
    # 还原回核
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    idx = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='idx_sense_src_word'").fetchone()[0]
    tbl = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='_mut_nocase'").fetchone()[0]
    con.close()
    good = idx == 1 and tbl == 0 and TS.read_text(encoding="utf-8") == orig
    ok &= good
    print("   %s 还原回核：索引在=%d、变异表已删=%s、`vietnamese.ts` 一字未改=%s"
          % ("✅" if good else "🔴🔴", idx, tbl == 0,
             TS.read_text(encoding="utf-8") == orig))
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
