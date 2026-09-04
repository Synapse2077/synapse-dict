#!/usr/bin/env python3
"""预计算短前缀的搜索结果（德语）—— 干掉搜索下拉的尖峰。2026-09-04（阶段 9）。

═══ de 的实测（阶段 9 开工时，进程内非 HTTP）═══
`search()` 是搜索下拉与划词的路径，**用户每敲一个字符就跑一次**。

    修之前                      **1,678 – 1,798 ms**
    ① `ANALYZE`（见下）          **0.9 – 110 ms**
    ② 本步（预计算短前缀）        目标：短前缀也进 1 ms

🔴🔴 **① 是个真缺陷，不是"顺手优化"，而且它是 `[[query-perf-collation-traps]]` 的原样复发**：
   中文摘要 `SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh'
   WHERE s.word_id=?` 的计划是 **`SEARCH g USING INDEX idx_glosslang (lang=?)`** ——
   规划器**从选择性最差那头入手**（`lang='zh'` 有 22 万行），而不是从高选择性的 `word_id` 进。
   `sense_gloss` 的主键 `(sense_id, lang, kind, seq)` 本来就能服务这个查询，
   **规划器不用它是因为库里没有统计信息**。
   一条 `ANALYZE` 之后计划翻转，同一段 200 次调用 **16,382 ms → 3.5 ms（快 4,800 倍）**。
   ⚠️ 搜索一次要查 20 条摘要 ⇒ 81.91 ms × 20 = 1,638 ms，**那 1,700 ms 的 96% 是它**。

═══ 瓶颈是排序不是过滤（es/it 2026-08-20 实测，de 复现）═══
    只过滤，不排序不 LIMIT      31.4 ms
    过滤 + LIMIT 20，不排序      **0.1 ms**   ← 过滤本身几乎免费
    过滤 + 排序 + LIMIT 20      36.0 ms      ← 为取 20 条把 36,574 个候选整个排一遍

`ORDER BY` 里的 `LENGTH(word)` 不可索引，而 `word LIKE ? OR word_norm LIKE ?` 的
**OR 强制走 MULTI-INDEX OR** ⇒ 规划器不会为它采用排序索引，**建索引没用**。

═══ 判据：问题只在短前缀，而短前缀的答案完全由前缀决定 ═══
`ORDER BY` 的每一项都只依赖词形本身和这个前缀，与查询上下文无关 ⇒ **可确定性预计算**。

🔴🔴 **`LIVE` 与 `packages/dict-core/src/german.ts` 的 `prefix` 逐字相同，
     一行都不从 pt/fr/it 抄。** pt 的排序是**两级**精确匹配
     （`word = ?` 之后还有 `lower(word) = lower(?)`），照抄过来会**静默改掉排序**，
     而两边都不会报错。
     ⚠️ 而且 de **必须只有一级**：SQLite 的 `lower()` 只处理 ASCII
     （收尾单 C25：`upper('KöR')` 原样返回），德语词头大量带 ä/ö/ü ——
     第二级在 de 上是**坏的**，不是"少一个优化"。

═══ 缓存未命中 = 正确回退，不是错误 ═══
键就是调用方传进来的原字符串（不做大小写归一，理由同上）。查不到就走实时查询 ——
结果一样，只是慢一点。`german.ts` 里连"表存不存在"都按未命中处理。

═══ 闸 ═══
① **可逆性回核**（100%，非抽样）：每个预计算前缀重跑实时查询，id 序列**逐位**比。
② **指纹**：`dict` 的排序依赖列（`word`/`word_norm`/`is_lemma`）一变，预计算表即陈旧。
   🔴 指纹**只哈排序依赖的那三列**，不用 `COUNT:MAX(id)` —— 那种指纹看得见增删、
      **看不见 UPDATE**，而 UPDATE 这三列会让下拉静默排错（pt 2026-08-31 改过这一版）。

用法（在 de/ 目录下）：
    python3 -u pipeline/build_search_prefix.py            # 干跑
    python3 -u pipeline/build_search_prefix.py --apply
    python3 -u pipeline/build_search_prefix.py --verify   # 只跑闸
"""
import argparse
import hashlib
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")
MAXLEN = 3
TOPN = 50           # 服务层 limit 默认 20；留到 50 以容纳更大的取数

DDL = """CREATE TABLE search_prefix (
  prefix  TEXT NOT NULL,      -- 调用方传进来的原字符串（不做大小写归一，见文件头）
  rank    INTEGER NOT NULL,   -- 0 起，与实时查询的输出顺序逐位一致
  word_id INTEGER NOT NULL,
  PRIMARY KEY (prefix, rank)
) WITHOUT ROWID"""
DDL_META = """CREATE TABLE search_prefix_meta (
  k TEXT PRIMARY KEY, v TEXT NOT NULL
)"""

# 🔴 与 `packages/dict-core/src/german.ts` 的 `prefix` **逐字相同**。改一边必须改另一边。
LIVE = """
SELECT id FROM dict
WHERE word LIKE ? COLLATE NOCASE OR word_norm LIKE ? COLLATE NOCASE
ORDER BY CASE WHEN word = ? THEN 0 ELSE 1 END,
         is_lemma DESC,
         LENGTH(word) ASC,
         word ASC
LIMIT ?
"""


def keys(con):
    """要预计算哪些前缀：`dict.word` 真实出现的 1–3 字符前缀。

    ⚠️ 必须先 `strip()` —— `search()` 是先 trim 再查的，不 trim 会造出永远命中不到的键。
    ⚠️ 顺带补一份 ASCII 小写形（`Ge` → `ge`）：德语名词首字母大写，
       而用户打字常全小写。**只折叠 A–Z**，不碰 ä/ö/ü（SQLite 那边也不认，C25）。
    """
    s = set()
    for (w,) in con.execute("SELECT word FROM dict"):
        w = w.strip()
        for L in range(1, MAXLEN + 1):
            if len(w) >= L:
                s.add(w[:L])
    extra = {"".join(c.lower() if "A" <= c <= "Z" else c for c in k) for k in s}
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
        if verbose and i and i % 2000 == 0:
            print("     … %d/%d  %.0fs" % (i, len(ks), time.time() - t0), flush=True)
    if verbose:
        print("■ 预计算 %s 个前缀 / %s 行，用时 %.0fs"
              % (f(c["前缀"]), f(len(rows)), time.time() - t0))
        if c["命中 0 条的前缀"]:
            print("     （其中 %d 个前缀查不到任何词，存空）" % c["命中 0 条的前缀"])
    return rows


def fingerprint(con):
    """「上游变没变」的指纹。**LIVE 的 ORDER BY 用到什么，就哈什么。**

    🔴 不用 `COUNT(*):MAX(id)` —— 那种指纹只看得见**增删**，
       而排序依赖的 `word`/`word_norm`/`is_lemma` 被 **UPDATE** 时行数与最大 id 一个字不变，
       **指纹静默不动、下拉排序已经错了**。pt 2026-08-31 就是改的这一处。
    """
    h = hashlib.blake2b(digest_size=12)
    n = 0
    for w, wn, il in con.execute("SELECT word, word_norm, is_lemma FROM dict ORDER BY id"):
        n += 1
        h.update(("%s\x00%s\x00%s\x00" % (w, wn, il)).encode("utf-8"))
    return "%d:%s" % (n, h.hexdigest())


def gate(con, verbose=True):
    """闸①：每个前缀重跑实时查询，id 序列**逐位**比。100%，非抽样。"""
    stored, bad, mism = {}, [], 0
    for k, r, wid in con.execute(
            "SELECT prefix, rank, word_id FROM search_prefix ORDER BY prefix, rank"):
        stored.setdefault(k, []).append(wid)
    for k, ids in stored.items():
        live = [r[0] for r in con.execute(LIVE, (k + "%", k + "%", k, TOPN))]
        if live != ids:
            mism += 1
            if len(bad) < 3:
                bad.append("🔴 前缀 %r 与实时查询不一致（存 %d / 实时 %d）"
                           % (k, len(ids), len(live)))
    out = []
    if mism:
        out.append("🔴 %s 个前缀的预计算结果与实时查询不一致" % f(mism))
        out += bad
    row = con.execute("SELECT v FROM search_prefix_meta WHERE k='dict_fingerprint'").fetchone()
    now = fingerprint(con)
    if not row or row[0] != now:
        out.append("🔴 `dict` 已变（指纹 %s → %s），预计算表陈旧，必须重建"
                   % (row[0] if row else "?", now))
    if verbose:
        print("■ 闸①：核对 %s 个前缀，不一致 %s" % (f(len(stored)), mism))
        for b in out:
            print("     " + b)
        if not out:
            print("     ✅ 全部通过（逐位比对，非抽样）")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        bad = gate(con)
        con.close()
        return 1 if bad else 0
    ks = keys(con)
    print("■ 待预计算前缀 %s 个（1–%d 字符，含 ASCII 小写形）" % (f(len(ks)), MAXLEN))
    rows = build(con, ks)
    con.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("keep-v3-9-search-prefix", expect={}) as s:
        s.execute("DROP TABLE IF EXISTS search_prefix")
        s.execute("DROP TABLE IF EXISTS search_prefix_meta")
        s.execute(DDL)
        s.execute(DDL_META)
        s.executemany("INSERT INTO search_prefix (prefix, rank, word_id) VALUES (?,?,?)", rows)
        s.execute("INSERT INTO search_prefix_meta (k, v) VALUES ('dict_fingerprint', ?)",
                  (fingerprint(s.conn),))
        s.execute("INSERT INTO search_prefix_meta (k, v) VALUES ('topn', ?)", (str(TOPN),))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = gate(con)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
