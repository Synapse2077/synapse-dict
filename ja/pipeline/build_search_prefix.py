#!/usr/bin/env python3
"""阶段 9 —— 预计算慢前缀的搜索结果。零模型调用。2026-09-16。

═══ 实测：瓶颈是排序不是过滤（ja 自己量的，不是照抄）═══
搜索下拉**用户每敲一个字符跑一次**。拿 `あ`（11,764 个候选）分解：

    ① 只过滤，不排序不 LIMIT       约 2 ms
    ② 过滤 + LIMIT 30，**不排序**   **1 ms**   ← 过滤几乎免费
    ③ 过滤 + 排序 + LIMIT 30        **9 ms**   ← 为取 30 条把 11,764 个候选整个排一遍
    ④ 全套（含两个子查询）           9 ms      ← 子查询已不要钱（见下）

`ORDER BY` 里的 `length(word)` 和 `freq_zipf IS NULL` 都不可索引 ⇒ **建索引没用**。
而 `ORDER BY` 的每一项只依赖词形本身和这个前缀，与上下文无关 ⇒ **可确定性预计算**。

═══ 🔴 到这一步之前，先修掉两个真缺陷（它们比预计算重要得多）═══
**① `ANALYZE` 从来没跑过。** 库里没有统计信息，规划器**从选择性最差那头入手**：
   中文摘要子查询的计划是 `SEARCH g USING INDEX idx_glosslang (lang=?)` ——
   `lang='zh'` 有 **29 万行**，每个候选词扫一遍。搜索最慢 **40.9 ms → 7.1 ms**。
   ⚠️ 与 de 阶段 9 记的是**同一个**形状（`[[query-perf-collation-traps]]`）。
**② `inflection.base_id` 上没有索引。** 展示层查「这个词的活用形」正是按它查，
   ⇒ 每开一个词条页**全扫 567,717 行**。词条页 **71 ms → 0.4 ms**。
   🔴 建库时建了 `idx_infl_base`（按**文本** `base`），那是给「回填 base_id」用的 ——
   **写入路径的索引不等于读取路径的索引**。

⇒ 两个修完之后，剩下的才是真·排序开销，也才轮到本步。

═══ 🔴 判据按「候选数」定，不按「前缀长度」定 ═══
de/pt 那边预计算的是**短前缀**（1–2 字符）。照搬到日语上是个形式代理：
日语的首字是几千个汉字，**1 字前缀就有 15,102 种**，而其中绝大多数只有几个候选、
本来就 0.1 ms。慢的不是「短」，是「候选多」。

实测各档（随机抽 8 个前缀 × 8 次）：

    候选 100–300     0.11 ms        候选 1,500–4,000    0.87 ms
    候选 300–700     0.17 ms        候选 4,000–12,000   **1.70 ms**
    候选 700–1,500   0.36 ms

⇒ 阈值定 **1,500**（超过它才开始超 1 ms），一共 **63 个前缀** —— 预计算表小得可笑，
   而它盖住的正是全部的尖峰。`[[criteria-from-meaning-not-form]]`。

═══ 🔴🔴 `LIVE` 必须与 `packages/dict-core/src/japanese.ts` 的 `search` **逐字相同** ═══
排序但凡差一个键，缓存命中与未命中会给出**不同的顺序**，而两边都不会报错。
⇒ 本文件末尾的闸做**可逆性回核（100%，非抽样）**：每个预计算前缀重跑实时查询，
   id 序列**逐位**比。

═══ 缓存未命中 ＝ 正确回退，不是错误 ═══
查不到就走实时查询，结果一样只是慢一点。表不存在也按未命中处理。

用法（在仓库根）：
    python3 -u ja/pipeline/build_search_prefix.py
    python3 -u ja/pipeline/build_search_prefix.py --apply
    python3 -u ja/pipeline/build_search_prefix.py --verify
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import hashlib
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")
TOPN = 30            # 与 `japanese.ts` 的 search 默认 limit 一致
MIN_CAND = 1500      # 见文件头：实测超过它才开始超 1 ms
MAXLEN = 3           # 候选数 ≥1500 的前缀最长就是 3 字符

DDL = """CREATE TABLE IF NOT EXISTS search_prefix (
           prefix  TEXT    NOT NULL,
           rank    INTEGER NOT NULL,
           word_id INTEGER NOT NULL,
           PRIMARY KEY (prefix, rank)
         ) WITHOUT ROWID"""
DDL_META = """CREATE TABLE IF NOT EXISTS search_prefix_meta (
                k TEXT PRIMARY KEY, v TEXT NOT NULL)"""

# 🔴 与 `japanese.ts` 的 `search` 逐字相同。改一边就必须改另一边，闸会逐位比。
LIVE = """
  SELECT d.id FROM dict d
  WHERE d.word_norm >= ? AND d.word_norm < ?
  ORDER BY d.is_lemma DESC, d.freq_zipf IS NULL, d.freq_zipf DESC,
           length(d.word), d.word
  LIMIT ?
"""


def hot_prefixes(con):
    """→ [(前缀, 候选数)]，候选数 ≥ MIN_CAND 的那些。"""
    parts = " UNION ALL ".join(
        "SELECT substr(word_norm,1,%d) k, COUNT(*) n FROM dict"
        " WHERE length(word_norm)>=%d GROUP BY 1" % (i, i)
        for i in range(1, MAXLEN + 1))
    return [(r[0], r[1]) for r in con.execute(
        "WITH p AS (%s) SELECT k, n FROM p WHERE n >= ? ORDER BY n DESC"
        % parts, (MIN_CAND,)) if r[0]]


def fingerprint(con):
    """「上游变没变」的指纹。🔴 **`LIVE` 的 ORDER BY 用到什么，就哈什么。**
    少哈一列，那一列改了之后预计算表就静默陈旧（而查询照样返回旧顺序）。"""
    h = hashlib.sha256()
    for row in con.execute(
            "SELECT id, word, word_norm, is_lemma, freq_zipf FROM dict ORDER BY id"):
        h.update(repr(row).encode())
    return h.hexdigest()


def verify(con, verbose=True):
    """闸①：**可逆性回核，100% 非抽样。**每个预计算前缀重跑实时查询，id 序列逐位比。"""
    rows = {}
    for pre, rank, wid in con.execute(
            "SELECT prefix, rank, word_id FROM search_prefix ORDER BY prefix, rank"):
        rows.setdefault(pre, []).append(wid)
    bad = []
    for pre, ids in rows.items():
        live = [r[0] for r in con.execute(LIVE, (pre, pre + "￿", TOPN))]
        if live != ids:
            bad.append(pre)
    fp = fingerprint(con)
    saved = con.execute(
        "SELECT v FROM search_prefix_meta WHERE k='dict_fingerprint'").fetchone()
    stale = (saved is None) or (saved[0] != fp)
    if verbose:
        print("   %s 可逆性回核：%s 个前缀逐位一致%s"
              % ("🔴" if bad else "✅", f(len(rows)),
                 ("，**%d 个对不上**：%s" % (len(bad), "、".join(bad[:5]))) if bad else ""))
        print("   %s 指纹：%s" % ("🔴" if stale else "✅",
                                "上游已变，预计算表**陈旧**，重跑本步" if stale else "与 dict 一致"))
    return bad, stale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    if a.verify:
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        bad, stale = verify(con)
        con.close()
        _sys.exit(1 if (bad or stale) else 0)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    hot = hot_prefixes(con)
    print("■ 候选数 ≥ %s 的前缀：%s 个（候选合计 %s）"
          % (f(MIN_CAND), f(len(hot)), f(sum(n for _k, n in hot))))
    for k, n in hot[:8]:
        print("   %-6s %s" % (k, f(n)))
    rows = []
    for pre, _n in hot:
        for rank, r in enumerate(con.execute(LIVE, (pre, pre + "￿", TOPN))):
            rows.append((pre, rank, r[0]))
    fp = fingerprint(con)
    con.close()
    print("■ 预计算行数 %s" % f(len(rows)))
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        return

    with dbtool.session("ja-build-search-prefix", expect={
            "__rows__": 0, "#entry": 0, "#sense": 0, "#example": 0,
            "#sense_relation": 0}) as con:
        con.execute(DDL)
        con.execute(DDL_META)
        con.execute("DELETE FROM search_prefix")
        con.executemany(
            "INSERT INTO search_prefix(prefix, rank, word_id) VALUES(?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO search_prefix_meta(k, v) VALUES"
                    "('dict_fingerprint', ?)", (fp,))
        con.execute("INSERT OR REPLACE INTO search_prefix_meta(k, v) VALUES"
                    "('min_candidates', ?)", (str(MIN_CAND),))
        con.execute("INSERT OR REPLACE INTO search_prefix_meta(k, v) VALUES"
                    "('topn', ?)", (str(TOPN),))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print()
    bad, stale = verify(con)
    con.close()
    if bad or stale:
        _sys.exit(1)


if __name__ == "__main__":
    main()
