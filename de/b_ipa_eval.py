#!/usr/bin/env python3
"""德语 G2P 自证：对 DB 里有 kaikki IPA 的 lemma，跑 word_to_ipa 与之比对。
三档：strict(归一后全等) / no-stress(忽略重音+音节点) / segment(再忽略长音ː，看音段骨架)。
在 de/ 目录跑：python3 b_ipa_eval.py [样本数]
"""
import re
import sqlite3
import sys
from pathlib import Path

from b_ipa import word_to_ipa

DB = Path(__file__).resolve().parent / "synapse-dict-de.sqlite"


def norm(s, stress=True, length=True):
    s = s.strip().strip("/").strip("[]").strip()
    # 去记号差异：连结弧、非成节符 ̯、成节符 ̩、次重音
    for ch in ("͡", "̯", "̩", "ˌ"):
        s = s.replace(ch, "")
    # 统一双元音/音节化写法（kaikki ↔ 本引擎约定差异，非真错）
    s = s.replace("ɔʏ", "ɔɪ").replace("aʊ", "aʊ")
    s = s.replace("ən", "n").replace("əl", "l").replace("əʁ", "ɐ").replace("əm", "m")
    s = s.replace("ɐ", "ɐ")
    if not stress:
        s = s.replace("ˈ", "").replace(".", "").replace(" ", "")
    if not length:
        s = s.replace("ː", "")
    return s


def main(limit=400):
    conn = sqlite3.connect(str(DB))
    # 只评**简单短词**（≤8 字母、无空格）以隔离 G2P 核心正确率，排除复合词/外来长词噪声
    rows = conn.execute(
        "SELECT word, ipa FROM dict WHERE is_lemma=1 AND ipa IS NOT NULL AND ipa!='' "
        "AND word NOT LIKE '% %' AND LENGTH(word) BETWEEN 3 AND 8 "
        "ORDER BY RANDOM() LIMIT ?", (limit,)).fetchall()
    n = strict = nostress = seg = none = 0
    misses = []
    for w, kaikki in rows:
        got = word_to_ipa(w)
        if not got:
            none += 1
            continue
        n += 1
        k1 = norm(kaikki.split(",")[0])          # kaikki 可能多变体，取第一个
        g1 = norm(got)
        if g1 == k1:
            strict += 1; nostress += 1; seg += 1
        elif norm(got, stress=False) == norm(kaikki.split(",")[0], stress=False):
            nostress += 1; seg += 1
        elif norm(got, stress=False, length=False) == norm(kaikki.split(",")[0], stress=False, length=False):
            seg += 1
        else:
            if len(misses) < 30:
                misses.append((w, kaikki.split(",")[0].strip(), got))
    print(f"评测 {n} 词（G2P 放弃 {none}）")
    print(f"  strict   {strict} ({100*strict//max(n,1)}%)")
    print(f"  no-stress {nostress} ({100*nostress//max(n,1)}%)")
    print(f"  segment  {seg} ({100*seg//max(n,1)}%)")
    print("失配样例（word / kaikki / G2P）:")
    for w, k, g in misses:
        print(f"   {w:18} {k:22} {g}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 400)
