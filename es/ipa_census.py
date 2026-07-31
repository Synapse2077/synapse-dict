#!/usr/bin/env python3
"""es 音标**来源普查** —— 每一条音标到底是谁写的?确定性判定,不调模型。见对话 2026-07-31。

⭐ 为什么必须先分来源再谈质量:三个来源的缺陷机理完全不同,混在一起算平均数没有可操作性。
   - kaikki 原生:人工源,权威。它的"怪写法"(coda 浊化 ˈaɡto、短语次重音 ˌ、近音 β/ð/ɣ)
     **是约定不是缺陷** —— 2026-07-31 我把它当缺陷报过两次,都是错的。这一层基本不该动。
   - b_ipa.py 规则生成:确定性可重算、可回归。错了是**规则错**,改规则重跑即可,一次修一片。
   - 豆包填空:无人工源背书、无规则可回溯。**今天修掉的 1,134 条残留全部出自这一层**。
     它才是缺陷的主要产地,也是唯一值得逐条查的一层。

判定口径(优先级从上到下,先命中先归属):
  kaikki     该词在 kaikki 有音位式 /.../ 且与库内值**逐字相同**
  规则       `b_ipa.word_to_ipa(word)` 输出与库内值逐字相同
  kaikki改   kaikki 有此词但值不同(被后续流程改写过 —— 需要解释)
  规则可达但不同  规则算得出但与库内不同(多为 kaikki 原生,规则只是碰巧也能算)
  豆包/未知   以上都不是:kaikki 无此词、规则也算不出 → 只能是豆包填的

read-only。用法(在 es/ 目录):
  python3 ipa_census.py
  python3 ipa_census.py --sample 20     # 每类打印若干样例
"""
import argparse, sqlite3, time
from collections import Counter, defaultdict
from pathlib import Path

import kaikki_util
from b_ipa import word_to_ipa

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-es.sqlite"
KK = HERE / "kaikki.org-dictionary-Spanish.jsonl"


def load_kaikki(words):
    t0 = time.time()
    kk = kaikki_util.phonemic_ipa(words)   # 🔴 必须走 kaikki_util,别自己写正则,见该文件头
    print(f"  kaikki 音位式命中 {len(kk):,} 词 ({time.time()-t0:.0f}s)", flush=True)
    return kk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=6)
    ap.add_argument("--dump", metavar="TSV",
                    help="把**非 kaikki 原生、非规则生成**的行(即无人工源背书那两类)"
                         "导成 TSV: id/layer/src/word/库值/kaikki/规则。后续逐族排查的输入。")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT id, word, phonetic, is_lemma FROM dict WHERE TRIM(COALESCE(phonetic,''))<>''"
    ).fetchall()
    conn.close()
    print(f"有音标 {len(rows):,} 行,判定来源中…", flush=True)

    kk = load_kaikki({r[1] for r in rows})

    t0 = time.time()
    tally = Counter()
    ex = defaultdict(list)
    dump = []
    for rid, w, p, isl in rows:
        layer = "lemma" if isl else "变形层"
        kv = kk.get(w)
        rv = word_to_ipa(w)
        rv = rv.strip("/") if rv else None
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
        tally[(layer, src)] += 1
        if len(ex[(layer, src)]) < a.sample:
            ex[(layer, src)].append((w, p, kv, rv))
        if a.dump and src in ("规则算得出但不同", "豆包/未知", "kaikki有但被改写"):
            dump.append((rid, layer, src, w, p, kv or "", rv or ""))
    print(f"  判定完毕 ({time.time()-t0:.0f}s)\n", flush=True)

    if a.dump:
        with open(a.dump, "w", encoding="utf-8") as f:
            f.write("id\tlayer\tsrc\tword\tdb\tkaikki\trule\n")
            for r in dump:
                f.write("\t".join(str(x) for x in r) + "\n")
        print(f"→ 无人工源背书的 {len(dump):,} 行已导出 {a.dump}\n", flush=True)

    ORDER = ["kaikki原生", "规则生成", "kaikki有但被改写", "规则算得出但不同", "豆包/未知"]
    print("=" * 78)
    print(f"{'来源':20}{'lemma':>12}{'变形层':>14}{'合计':>12}{'占比':>9}")
    print("=" * 78)
    tot = sum(tally.values())
    for src in ORDER:
        l, i = tally[("lemma", src)], tally[("变形层", src)]
        print(f"{src:20}{l:>12,}{i:>14,}{l+i:>12,}{100*(l+i)/tot:>8.2f}%")
    print("-" * 78)
    tl = sum(tally[("lemma", s)] for s in ORDER)
    ti = sum(tally[("变形层", s)] for s in ORDER)
    print(f"{'合计':20}{tl:>12,}{ti:>14,}{tot:>12,}")

    for src in ORDER:
        for layer in ("lemma", "变形层"):
            if not ex[(layer, src)]:
                continue
            print(f"\n■ {layer} / {src}  ({tally[(layer,src)]:,} 条)")
            for w, p, kv, rv in ex[(layer, src)]:
                print(f"    {w[:24]:26} 库 {p[:24]:26} kaikki {str(kv)[:18]:20} 规则 {str(rv)[:18]}")


if __name__ == "__main__":
    main()
