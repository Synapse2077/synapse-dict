#!/usr/bin/env python3
"""阶段 9：预计算短前缀的搜索结果 —— 干掉搜索下拉的尖峰。2026-09-08。零成本。

═══ en 的实测（阶段 8 接上服务后，进程内非 HTTP）═══
    修之前（无统计信息）        **均 12,076 ms**   🔴🔴
    ① `ANALYZE`                均 16.3 ms（快 740 倍）
    ② `inflection.base_id` 索引 `getEntry` 88.5 → 2.8 ms
    ③ 本步（预计算短前缀）      目标：`a`/`th`/`un` 那一档也进 1 ms

🔴🔴 **① 是真缺陷，`[[query-perf-collation-traps]]` 的原样复发（de 已记过一次）**：
   摘要查询 `... JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' WHERE s.word_id=?`
   的计划是 **`SEARCH g USING INDEX idx_glosslang (lang=?)`** —— 规划器从选择性最差
   那头进（`lang='zh'` 有 177 万行），因为**库里没有统计信息**。
   搜索一次要查 20 条摘要 ⇒ **20 次 = 11,227 ms**，那 12 秒的 93% 是它。
   一条 `ANALYZE`（7.2 秒）之后计划翻转，同一段 **11,227 ms → 0.41 ms（快 27,000 倍）**。
   ⚠️ de 那轮记的是「快 4,800 倍」，en 更极端 —— **库越大这个洞越深**。

═══ 瓶颈是排序不是过滤（es/it 实测，de 复现，en 再复现）═══
    只过滤 + LIMIT，不排序     0.0 ms
    过滤 + 排序 + LIMIT 20     2.5 ms   ← 为取 20 条把候选整个排一遍
短前缀（`a` 有 30 万候选）时这个差距放大到 105 ms。

═══ 判据：只有短前缀是问题，而短前缀的答案完全由前缀决定 ═══
`ORDER BY` 每一项都只依赖词形本身和这个前缀 ⇒ **可确定性预计算**。

🔴🔴 **`LIVE` 与 `packages/dict-core/src/english.ts` 的 `prefix` 逐字相同，
     一行都不从 de/pt/fr 抄。**en 的排序有别人没有的一级：**ECDICT `freq_rank`**
     （五门都没有这把尺子）。照抄 de 的「按长度排」会静默改掉顺序，而两边都不报错。

⚠️ **大小写不归一**：键就是调用方传进来的原字符串。`Lead` 与 `lead` 是两个词条
   （阶段 1a 实测 NOCASE 会多挂 12,834 条污染）⇒ 归一会把它们混为一谈。
   缓存未命中 = 正确回退到实时查询，不是错误。

═══ 闸 ═══
① **可逆性回核（100%，非抽样）**：每个预计算前缀重跑 `LIVE`，id 序列**逐位**比。
② **指纹**：只哈排序依赖的那几列（`word`/`freq_rank`），不用 `COUNT:MAX(id)` ——
   那种指纹看得见增删、**看不见 UPDATE**，而 UPDATE 这些列会让下拉静默排错。

    cd en && python3 -u pipeline/build_search_prefix.py
    cd en && python3 -u pipeline/build_search_prefix.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import hashlib
import sqlite3
import string
import time

import dbtool
import paths

LIMIT = 20
MAXLEN = 3          # 预计算 1–3 字符前缀；4 字符起实时查询已在 1 ms 内
ALPHA = string.ascii_lowercase + string.ascii_uppercase + string.digits + "'- "

# 🔴 与 english.ts 的 `prefix` **逐字相同**。改一边必须改另一边（闸①会当场发现）
LIVE = """SELECT id FROM dict WHERE word LIKE ? ESCAPE '\\'
 ORDER BY (word = ?) DESC,
          CASE WHEN freq_rank IS NULL THEN 1 ELSE 0 END,
          freq_rank ASC, length(word) ASC, word ASC
 LIMIT ?"""


def fingerprint(con):
    """只哈**排序依赖的列**。看得见 UPDATE，不只是增删。"""
    h = hashlib.sha256()
    for w, f in con.execute("SELECT word, freq_rank FROM dict ORDER BY id"):
        h.update(("%s\t%s\n" % (w, f)).encode())
    return h.hexdigest()[:16]


def prefixes(con):
    """只对**库里真有词以此开头**的前缀预计算 —— 组合爆炸没有意义。"""
    out = set()
    for (w,) in con.execute("SELECT word FROM dict"):
        for n in range(1, min(MAXLEN, len(w)) + 1):
            p = w[:n]
            if all(ch in ALPHA for ch in p):
                out.add(p)
    return sorted(out)


def main(apply_=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ps = prefixes(con)
    print("═══ 阶段 9 计划 ═══")
    print("   预计算前缀（1–%d 字符，库里真有词以此开头）%s 个" % (MAXLEN, format(len(ps), ",")))
    t0 = time.time()
    rows = []
    for p in ps:
        esc = p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        ids = [r[0] for r in con.execute(LIVE, ("%s%%" % esc, p, LIMIT))]
        rows.extend((p, i, wid) for i, wid in enumerate(ids))
    print("   预计算 %s 行，用时 %.1f 秒" % (format(len(rows), ","), time.time() - t0))
    fp = fingerprint(con)
    print("   指纹（word+freq_rank）%s" % fp)
    con.close()
    if not apply_:
        print("\n(干跑。加 --apply 才写库)")
        return 0

    # 🔴 `expect` 要**声明所有被动的表**，而且值是**增量**不是总数。
    #    第一版写 `expect={}`，闸当场报「未声明的表 search_prefix 行数变了 +523,252」——
    #    它正是为这件事存在的。⚠️ 表可能还不存在，所以现取要容错。
    con0 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    def _now(t):
        try:
            return con0.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        except sqlite3.Error:
            return 0
    d_rows, d_meta = len(rows) - _now("search_prefix"), 1 - _now("search_prefix_meta")
    con0.close()
    print("   本次净增量 search_prefix %+d ／ meta %+d" % (d_rows, d_meta))
    with dbtool.session("keep-v3-9-search-prefix",
                        expect={"#search_prefix": d_rows,
                                "#search_prefix_meta": d_meta}) as s:
        s.execute("""CREATE TABLE IF NOT EXISTS search_prefix (
                       prefix  TEXT NOT NULL,
                       rank    INTEGER NOT NULL,
                       word_id INTEGER NOT NULL,
                       PRIMARY KEY (prefix, rank)
                     ) WITHOUT ROWID""")
        s.execute("""CREATE TABLE IF NOT EXISTS search_prefix_meta (
                       k TEXT PRIMARY KEY, v TEXT NOT NULL)""")
        s.execute("DELETE FROM search_prefix")
        s.executemany("INSERT INTO search_prefix (prefix,rank,word_id) VALUES (?,?,?)", rows)
        s.execute("INSERT OR REPLACE INTO search_prefix_meta (k,v) VALUES ('fingerprint',?)", (fp,))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸②：可逆性回核（100%%，非抽样）═══")
    bad = 0
    t0 = time.time()
    for p in ps:
        esc = p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        live = [r[0] for r in con.execute(LIVE, ("%s%%" % esc, p, LIMIT))]
        cached = [r[0] for r in con.execute(
            "SELECT word_id FROM search_prefix WHERE prefix=? ORDER BY rank", (p,))]
        if live != cached:
            bad += 1
            if bad <= 3:
                print("   🔴 %r  实时 %s ／ 缓存 %s" % (p, live[:5], cached[:5]))
    print("   %s 逐位比对 %s 个前缀，不一致 %s（用时 %.1f 秒）"
          % ("✅" if bad == 0 else "🔴", format(len(ps), ","), bad, time.time() - t0))
    n, = con.execute("SELECT COUNT(*) FROM search_prefix").fetchone()
    f2, = con.execute("SELECT v FROM search_prefix_meta WHERE k='fingerprint'").fetchone()
    print("   %s 指纹与库一致：%s" % ("✅" if f2 == fingerprint(con) else "🔴", f2))
    print("   search_prefix %s 行" % format(n, ","))
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(apply_="--apply" in _sys.argv))
