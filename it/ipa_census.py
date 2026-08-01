#!/usr/bin/env python3
"""it 音标**来源普查** —— 库里每条 IPA 到底是谁给的：kaikki 人工源 / G2P 规则 / 豆包填空。
零成本，read-only，不调模型。2026-08-01。

⭐ 为什么这是第一步（es 上的教训）：
   es 花了一整天在「62 万条 G2P 音标可能有系统性缺陷」这个假设上，最后 1500 条盲测
   量出那层标出率只有 2.3%（比 kaikki 原生的 6.2% 还低）—— **风险面判断整个反了**，
   真正的问题集中在「既无 kaikki 背书、规则也算不出」的那 2.4 万条。
   → 动手之前先知道**哪些行有权威源背书**，是唯一能防止把力气花错地方的办法。

判定（对每个词形）：
   kaikki 有值且与库内逐字相同  → kaikki原生      （权威源背书，最可信）
   规则算得出且与库内逐字相同    → 规则生成        （G2P 产物，可用 kaikki 覆盖的部分外推质量）
   kaikki 有值但与库内不同      → kaikki被改写     （要查：谁改的、为什么）
   规则算得出但与库内不同       → 规则算得出但不同   （多为豆包填的；es 上这层标出率最高）
   两者都给不出                → 豆包/未知        （无任何背书，风险最高）

用法（在 it/ 目录）：
  python3 ipa_census.py                 # 全量普查
  python3 ipa_census.py --dump 无背书.tsv  # 导出无人工源背书的行
"""
import argparse, sqlite3, time
from collections import Counter, defaultdict
from pathlib import Path

import kaikki_util
from b_ipa import word_to_ipa

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
ORDER = ["kaikki原生", "规则生成", "kaikki有但被改写", "规则算得出但不同", "豆包/未知"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", help="把无人工源背书的行导出到该 tsv")
    ap.add_argument("--ex", type=int, default=4, help="每类打印几条例词")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT id, word, ipa, is_lemma FROM dict "
                        "WHERE TRIM(COALESCE(ipa,''))<>''").fetchall()
    conn.close()
    print(f"有音标 {len(rows):,} 行,判定来源中…", flush=True)

    t0 = time.time()
    # 🔴 一趟同时取「音位式」与「重音形映射」。后者必须有 —— 见 kaikki_util 里的注释:
    #    b_ipa_fill 是喂**带重音形**给 G2P 的,拿光杆词形复算会走倒二默认、结果对不上,
    #    第一版普查因此把 11.2 万行(19.2%)误判成「规则算得出但不同」。
    # words=None:必须扫**全部条目**。重音形挂在它所属 lemma 名下(`dìgito` 属 `digitare`),
    # 按库内词表过滤会漏掉一大批映射 —— 与 b_ipa_fill.build_accent_map 保持同口径。
    kk, amap = kaikki_util.sounds_and_accent_map(None)
    print(f"  kaikki 音位式 {len(kk):,} 词 / 重音形映射 {len(amap):,} 条 "
          f"({time.time()-t0:.0f}s)", flush=True)

    def rule_of(w):
        """复现 b_ipa_fill 的生成路径:先查带重音形,查不到才喂光杆词形。"""
        src = amap.get(kaikki_util.unaccent(w), w)
        rv = word_to_ipa(src)
        return rv.strip("/") if rv else None

    tally = Counter()
    ex = defaultdict(list)
    unsourced = []
    for rid, w, p, isl in rows:
        kv = kk.get(w)
        rv = rule_of(w)
        if kv is not None and kv == p:
            src = "kaikki原生"
        elif rv is not None and rv == p:
            src = "规则生成"
        elif kv is not None:
            src = "kaikki有但被改写"
        elif rv is not None:
            src = "规则算得出但不同"
        else:
            src = "豆包/未知"
        lay = "lemma" if isl else "变形层"
        tally[(src, lay)] += 1
        if len(ex[(src, lay)]) < a.ex:
            ex[(src, lay)].append((w, p, kv, rv))
        if src in ("规则算得出但不同", "豆包/未知"):
            unsourced.append((rid, w, p, lay, src, kv or "", rv or ""))
    print(f"  判定完毕 ({time.time()-t0:.0f}s)\n", flush=True)

    if a.dump:
        with open(a.dump, "w", encoding="utf-8") as f:
            f.write("id\tword\tipa\tlayer\tsrc\tkaikki\trule\n")
            for r in unsourced:
                f.write("\t".join(map(str, r)) + "\n")
        print(f"→ 无人工源背书的 {len(unsourced):,} 行已导出 {a.dump}\n")

    W = 78
    print("=" * W)
    print(f"{'来源':22}{'lemma':>12}{'变形层':>12}{'合计':>12}{'占比':>9}")
    print("=" * W)
    tot = sum(tally.values())
    for s in ORDER:
        l, i = tally[(s, "lemma")], tally[(s, "变形层")]
        if l + i == 0:
            continue
        print(f"{s:22}{l:>12,}{i:>12,}{l+i:>12,}{100*(l+i)/tot:>8.2f}%")
    print("-" * W)
    print(f"{'合计':22}{sum(v for (s,x),v in tally.items() if x=='lemma'):>12,}"
          f"{sum(v for (s,x),v in tally.items() if x=='变形层'):>12,}{tot:>12,}")

    for s in ORDER:
        for lay in ("lemma", "变形层"):
            if not ex[(s, lay)]:
                continue
            print(f"\n■ {lay} / {s}  ({tally[(s,lay)]:,} 条)")
            for w, p, kv, rv in ex[(s, lay)]:
                print(f"    {w[:26]:28} 库 {p[:24]:26} kaikki {str(kv)[:22]:24} 规则 {str(rv)[:22]}")


if __name__ == "__main__":
    main()
