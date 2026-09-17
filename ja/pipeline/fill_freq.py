#!/usr/bin/env python3
"""阶段 5c —— 频次层 `dict.freq_zipf`。零模型调用。2026-09-15。

═══ 🔴🔴 这门语言上，**天真地用 wordfreq 会造出一把说谎的尺子** ═══
`wordfreq` 的日语通路要 MeCab 分词（`pip install mecab-python3 ipadic`）。
装好之后 `zipf_frequency(w,'ja')` 对任何词形都给得出一个数 —— 问题正在这儿：

    词形被切成多个 token 时，wordfreq 返回的是**由各部件组合估算**出来的数。
    对短语这是合理的估计，对**词典词条**是错的，而且错的方向固定：**偏高**。

实测（4,000 个词元抽样）：

    单 token   1,735 (43.4%)      ← 这批的数可信
    多 token   2,265 (56.6%)      ← 这批的数是拼出来的
      其中报出 zipf > 4 的：`分親` 4.90 ／ `情報管理システム` 4.81 ／ `カバー曲` 4.57
      对照：`愛する` 4.26、`痛い` 4.74

⇒ **`分親` 会排在 `愛する` 前面。** 这把尺子不是不准，是**系统性地把生僻复合词
   顶到常用词上面**。而频次的下游用途恰恰是排序和挑核心词
   （`[[es-audio-and-examples-wip]]`：挑词判据是 `freq_zipf` 不是 `level`）——
   一把在这个方向上说谎的尺子，比没有尺子更坏。

═══ 决定：**只给单 token 的词形落 `freq_zipf`，其余留 NULL** ═══
留 NULL 是诚实的「我们没有这个词的频次」；填一个组合估算值是**假装我们有**。
`[[dont-gate-facts-on-my-uncertainty]]` 的反面用法：这一行要写的不是源头给的，
是我推出来的 —— 那就别写。

⚠️ 代价说清楚：56.6% 的词元没有频次，**核心词挑选只能在单 token 那批里做**。
   `JA_PLAN` §四.2「声调 15.1% 够不够上页面」要的核心词覆盖率，
   分母得按这个口径重新说，不能假装覆盖全库。

⚠️ `[[wordfreq-ruler-traps]]` 记的四个坑（词缀被静默剥掉再查）在日语上表现不同：
   日语不剥词缀，它**分词**。症状从"查了别的词"变成"拼了个不存在的词"。

用法（在仓库根）：
    python3 -u ja/pipeline/fill_freq.py
    python3 -u ja/pipeline/fill_freq.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import sqlite3
import unicodedata

import dbtool
import paths

f = lambda n: format(n, ",")


def _same(a, b):
    """两串是不是同一个词 —— 只容忍 NFKC 全角/半角归一和大小写，不容忍**掉字符**。"""
    n = lambda x: unicodedata.normalize("NFKC", x).casefold()
    return n(a) == n(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    from wordfreq import zipf_frequency, tokenize

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = [(i, w) for i, w in con.execute(
        "SELECT id, word FROM dict WHERE is_lemma=1")]
    con.close()
    print("■ 词元 %s" % f(len(words)), flush=True)

    rows, st = [], collections.Counter()
    for i, w in words:
        try:
            tk = tokenize(w, "ja")
        except Exception:
            st["🔴 分词失败"] += 1
            continue
        if len(tk) != 1:
            st["⚪ 多 token，有意留 NULL" if tk else "🔴 切不出 token"] += 1
            continue
        # 🔴 **单 token 还不够，token 必须就是这个词。**
        #    `は〜` 被切成 `['は']` —— 一个 token，于是通过了上面那条判据，
        #    然后领到了助词 `は` 的频次 **7.46**，和 `は` 并列全库第一。
        #    `お〜`→`お` 同样。这正是 `[[wordfreq-ruler-traps]]` 记的头号坑
        #    「词缀被静默剥掉再查」，日语版本是**符号被剥掉再查**。
        #    ⚠️ 但 `ＡＢ`→`ab`、`ｱｲ`→`アイ` 是 wordfreq **正当的归一**（全角/半角），
        #       不能一并否掉 ⇒ 两边都做 NFKC + casefold 之后再比。
        if _same(w, tk[0]):
            pass
        else:
            st["🔴 分词改了词（领到的是别的词的频次）⇒ 留 NULL"] += 1
            continue
        z = zipf_frequency(w, "ja")
        st["单 token"] += 1
        if z <= 0:
            st["  但语料里没有（zipf=0）⇒ 留 NULL"] += 1
            continue
        rows.append((z, i))
        st["  ⭐ 落库"] += 1
    for k in sorted(st):
        print("   %-40s %s" % (k, f(st[k])))
    print("\n■ 要落 %s 条（覆盖词元 %.1f%%）"
          % (f(len(rows)), 100 * len(rows) / max(len(words), 1)))
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        for z, i in sorted(rows, key=lambda x: -x[0])[:10]:
            print("   %.2f  %s" % (z, dict(words)[i]))
        return

    with dbtool.session("ja-fill-freq", expect={
            "freq_zipf": len(rows), "__rows__": 0, "#entry": 0, "#sense": 0,
            "#example": 0, "#sense_relation": 0}) as con:
        con.executemany("UPDATE dict SET freq_zipf=? WHERE id=?", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda s: con.execute(s).fetchone()[0]
    # 🔴 断言要打在**判据本身**上：有 freq 的行必须都是单 token。
    #    写成「freq 的最大值 <= 7」那种范围检查是形式代理 —— `分親` 4.90 完全在范围内。
    bad = sum(1 for (w,) in con.execute(
        "SELECT word FROM dict WHERE freq_zipf IS NOT NULL")
        if len(tokenize(w, "ja")) != 1 or not _same(w, tokenize(w, "ja")[0]))
    checks = [
        ("有频次的词形，分词后就是它自己（组合估算和掉字符都没混进来）", bad == 0),
        ("没有 0 或负的频次", q(
            "SELECT COUNT(*) FROM dict WHERE freq_zipf IS NOT NULL "
            "AND freq_zipf<=0") == 0),
        ("变形词形没有被写上频次", q(
            "SELECT COUNT(*) FROM dict WHERE is_lemma=0 AND freq_zipf IS NOT NULL") == 0),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    print("\n■ 频次最高的 12 个词元（肉眼可判：必须都是真常用词）：")
    for w, z in con.execute(
            "SELECT word, freq_zipf FROM dict WHERE freq_zipf IS NOT NULL "
            "ORDER BY freq_zipf DESC LIMIT 12"):
        print("   %5.2f  %s" % (z, w))
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
