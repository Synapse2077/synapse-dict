#!/usr/bin/env python3
"""预计算短前缀的搜索结果 —— 干掉搜索下拉的 354ms 尖峰。2026-08-20。

═══ 缺陷（每次按键都撞到）═══
    search 前缀   P50 1.9ms   P95 26ms   P99 210ms   max 295ms

`search()` 是搜索下拉与划词的路径，**用户每敲一个字符就跑一次**。350ms 是看得见的卡。

═══ 瓶颈是排序，不是过滤（实测，不是猜）═══
    只过滤不排序不 LIMIT      7–16 ms   （候选 2–3 万条）
    过滤 + LIMIT 20，不排序      0 ms
    过滤 + 排序 + LIMIT 20     35–59 ms  ← 差额全在排序

为了取 20 条，把 2–3 万条候选整个排了一遍。`ORDER BY` 里有
`LENGTH(word)` 和 `CASE WHEN lower(word)=lower(?)`，都不可索引；
而 `word LIKE ? OR word_norm LIKE ?` 的 **OR 又强制走 MULTI-INDEX OR**，
规划器不会为它采用排序索引 —— 实测建 `(is_lemma, LENGTH(word), word)` 索引后
`EXPLAIN QUERY PLAN` 里 `USE TEMP B-TREE FOR ORDER BY` 原样还在，耗时几乎没变。

═══ 判据：问题**只在短前缀**，而短前缀的答案完全由前缀决定 ═══
    1 字符：中位 57ms  最慢 354ms
    2 字符：中位 14ms  最慢  40ms
    3 字符：中位  1ms  最慢 114ms   ← `"des"` 这类高频前缀，取样不同就看不见
    4 字符：中位  0ms  最慢  12ms   ← 不预计算

而全库 1 字符前缀只有 **65** 种、2 字符 **977** 种。
top-50 与查询上下文无关（`ORDER BY` 的每一项都只依赖词形本身和这个前缀），
⇒ **可以完全确定性地预计算**，表只有两万来行。

═══ 缓存未命中 = 正确回退，不是错误 ═══
键就是调用方传进来的原字符串。查不到就走实时查询 —— 结果一样，只是慢一点。
🔴 这条性质是有意设计的：SQLite 的 `lower()` **不认非 ASCII**（`lower('Á')`='Á'），
   所以 `Á` 和 `á` 走 `CASE WHEN lower(word)=lower(?)` 会得到**不同**的排序。
   与其去猜大小写归一规则，不如让键严格等于原串、猜不中就回退。

═══ 闸 ═══
① **可逆性回核**（100%，非抽样）：每一个预计算的前缀，重跑实时查询，
   id 序列必须**逐个相同**。一个不同就中止。
② 陈旧性：记下建表时 `dict` 的行数与 max(id)。`dict` 一变，闸就红 ——
   预计算表的头号风险不是算错，是**算对了然后数据变了没人重算**。
③ 变异验证

用法（在 es/ 目录下）：
    python3 pipeline/build_search_prefix.py            # 试算 + 闸，不写库
    python3 pipeline/build_search_prefix.py --apply
    python3 pipeline/build_search_prefix.py --mutate
"""
import argparse
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 🔴 先做到 2 就够不够？**不够。** 实测 1–2 字符降到 1ms 之后，最慢的变成
#    3 字符的 `"des"`（114ms）—— `desde/después/desarrollo/describir…`，
#    西语最常见的前缀之一，候选集依然上万。⇒ 扩到 3。
#    4 字符实测 max 12ms，不值得再扩（表会翻好几倍）。
MAXLEN = 3
TOPN = 50           # `apps/api` 的 parseLimit 上限是 50（默认 20）

DDL = """CREATE TABLE search_prefix (
  prefix  TEXT NOT NULL,      -- 调用方传进来的原字符串（不做大小写归一，见文件头）
  rank    INTEGER NOT NULL,   -- 0 起，与实时查询的输出顺序逐位一致
  word_id INTEGER NOT NULL,
  PRIMARY KEY (prefix, rank)
) WITHOUT ROWID"""
DDL_META = """CREATE TABLE search_prefix_meta (
  k TEXT PRIMARY KEY, v TEXT NOT NULL
)"""

# 与 `spanish.ts:prefixQuery` 的内层**逐字相同**。判据与实现共用一份（A93）——
# 这里若与那边差一个字，预计算出来的顺序就和页面上的不一样，而两边都不会报错。
LIVE = """
SELECT id FROM dict
WHERE word LIKE ? COLLATE NOCASE OR word_norm LIKE ? COLLATE NOCASE
ORDER BY
  CASE WHEN lower(word) = lower(?) THEN 0 ELSE 1 END,
  is_lemma DESC,
  LENGTH(word) ASC,
  word ASC
LIMIT ?
"""


def keys(con):
    """要预计算哪些前缀。取 `dict.word` 真实出现的 1–2 字符前缀，**连同大小写变体**。

    再加上 SQLite `lower()` 之后的形式 —— 用户多半小写输入，而库里可能只有大写词形。
    """
    s = set()
    for (w,) in con.execute("SELECT word FROM dict"):
        w = w.strip()          # ⚠️ `search()` 先 trim，不 trim 会造出永远命中不到的键
        for L in range(1, MAXLEN + 1):
            if len(w) >= L:
                s.add(w[:L])
    # SQLite 的 lower（ASCII-only），与查询里那个 lower(?) 保持同一套
    extra = set()
    for k in s:
        lo = "".join(c.lower() if "A" <= c <= "Z" else c for c in k)
        extra.add(lo)
    return sorted(s | extra)


def build(con, ks, verbose=True):
    rows, c = [], Counter()
    t0 = time.time()
    for i, k in enumerate(ks):
        ids = [r[0] for r in con.execute(LIVE, (k + "%", k + "%", k, TOPN))]
        for r, wid in enumerate(ids):
            rows.append((k, r, wid))
        c["前缀"] += 1
        c["命中 0 条的前缀"] += (not ids)
        if verbose and i and i % 500 == 0:
            print("     … %d/%d  %.0fs" % (i, len(ks), time.time() - t0))
    if verbose:
        print("■ 预计算 %s 个前缀 / %s 行，用时 %.0fs" % (
            format(c["前缀"], ","), format(len(rows), ","), time.time() - t0))
        if c["命中 0 条的前缀"]:
            print("     （其中 %d 个前缀查不到任何词，存空）" % c["命中 0 条的前缀"])
    return rows


def fingerprint(con):
    n, mx = con.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM dict").fetchone()
    return "%d:%d" % (n, mx)


def apply(con, rows):
    con.execute("DROP TABLE IF EXISTS search_prefix")
    con.execute("DROP TABLE IF EXISTS search_prefix_meta")
    con.execute(DDL)
    con.execute(DDL_META)
    con.executemany(
        "INSERT INTO search_prefix (prefix, rank, word_id) VALUES (?,?,?)", rows)
    con.execute("INSERT INTO search_prefix_meta (k, v) VALUES ('dict_fingerprint', ?)",
                (fingerprint(con),))
    con.execute("INSERT INTO search_prefix_meta (k, v) VALUES ('topn', ?)", (str(TOPN),))
    return len(rows)


def gate(con, verbose=True):
    """闸①：每个前缀重跑实时查询，id 序列逐位比。100%，非抽样。"""
    bad, n_pref, mism = [], 0, 0
    stored = {}
    for k, r, wid in con.execute(
            "SELECT prefix, rank, word_id FROM search_prefix ORDER BY prefix, rank"):
        stored.setdefault(k, []).append(wid)
    for k, ids in stored.items():
        n_pref += 1
        live = [r[0] for r in con.execute(LIVE, (k + "%", k + "%", k, TOPN))]
        if live != ids:
            mism += 1
            if len(bad) < 3:
                bad.append("     🔴 前缀 %r 与实时查询不一致（存 %d / 实时 %d）"
                           % (k, len(ids), len(live)))
    out = []
    if mism:
        out.append("🔴 %s 个前缀的预计算结果与实时查询不一致" % format(mism, ","))
        out += bad
    fp = con.execute(
        "SELECT v FROM search_prefix_meta WHERE k='dict_fingerprint'").fetchone()
    if not fp or fp[0] != fingerprint(con):
        out.append("🔴 `dict` 已变（指纹 %s → %s），预计算表已陈旧，必须重建"
                   % (fp[0] if fp else "?", fingerprint(con)))
    if verbose:
        print("■ 闸：核对 %s 个前缀，不一致 %s；指纹 %s" % (
            format(n_pref, ","), mism, "✓" if not out or "陈旧" not in out[-1] else "🔴"))
        for b in out:
            print("     " + b if not b.startswith("     ") else b)
        if not out:
            print("     ✅ 全部通过")
    return out


def mutate(rows):
    import shutil
    import tempfile
    # 🔴 **变异必须打在一个真有 >=2 条结果的前缀上。**
    #    第一版盲取 `rows[0]`（字母序第一个前缀）—— 意语那个前缀只有 1 行，
    #    「少存一行」和「前两条对调」双双变成空操作、构造上不可能红（4/5 变 3/5）。
    #    西语侧碰巧有 2 行以上才过的，等于白给。变异没触发先查变异对不对。
    cnt = Counter(k for k, _i, _w in rows)
    pick = next(k for k, n in cnt.items() if n >= 3)
    idx = [j for j, (k, _i, _w) in enumerate(rows) if k == pick]

    def drop_one(r):
        return [x for j, x in enumerate(r) if j != idx[0]]

    def swap_two(r):
        r = list(r)
        a, b = idx[0], idx[1]
        r[a] = (r[a][0], r[b][1], r[a][2])
        r[b] = (r[b][0], r[a][1] if False else rows[idx[0]][1], r[b][2])
        return r

    def bad_id(r):
        r = list(r)
        k, i, w = r[idx[0]]
        r[idx[0]] = (k, i, w + 7)
        return r

    MUT = [
        ("① 改掉一个前缀里的一个 id", bad_id, True),
        ("② 少存一行（顺序错位）", drop_one, True),
        ("③ 把某前缀的前两条对调", swap_two, True),
        ("④【负控】原样写入", lambda r: r, False),
    ]

    ok, cases = 0, []
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.sqlite"
        shutil.copy2(paths.DB, p)
        c = sqlite3.connect(p)
        for name, mut, want_red in MUT:
            c.execute("SAVEPOINT m")
            try:
                apply(c, mut(list(rows)))
                bad = gate(c, verbose=False)
            finally:
                c.execute("ROLLBACK TO m")
                c.execute("RELEASE m")
            good = bool(bad) == want_red
            ok += good
            cases.append((name, ("✅ 报红" if bad else "✅ 照常绿") if good
                          else ("🔴 该红没红" if want_red else "🔴 不该红却红了")))
        # ⑤ 陈旧性：动了 dict 之后闸必须红
        c2 = sqlite3.connect(p)
        c2.execute("SAVEPOINT m")
        apply(c2, list(rows))
        c2.execute("INSERT INTO dict (word, word_norm, is_lemma) VALUES ('__x__','__x__',1)")
        bad = gate(c2, verbose=False)
        c2.execute("ROLLBACK TO m")
        c2.close()
        ok += bool(bad)
        cases.append(("⑤ dict 变了（陈旧性）", "✅ 报红" if bad else "🔴 该红没红"))
        c.close()
    print("\n■ 变异验证")
    for n, s in cases:
        print("     %-30s %s" % (n, s))
    print("     %d/%d" % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ks = keys(con)
    print("■ 待预计算前缀 %s 个（1–%d 字符，含大小写变体）" % (format(len(ks), ","), MAXLEN))
    rows = build(con, ks)
    con.close()
    if a.mutate:
        return mutate(rows)
    if not a.apply:
        print("\n(未加 --apply，没有写库)")
        return 0
    with dbtool.session("search-prefix", expect={}) as s:
        s.written = apply(s.conn, rows)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = gate(con)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
