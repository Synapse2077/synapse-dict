#!/usr/bin/env python3
"""把两家外审提的每一条规则**单独**放到标尺上量：修好几个、弄坏几个。2026-09-21。

═══ 为什么要有这个脚本 ═══
2026-09-21 就 G2P 规则问了豆包 pro 与 deepseek v4-pro，两家在 Q3（-다 能不能当용언判据）、
Q5（要不要出版）、Q6（져/쳐 的施行条件）上给了**相反**的答案，且各自都说自己"零误伤"。

🔴 规矩是「两家不一致时回源核对，**不取多数**」。而这件事上权威源就在手上：
   韩文版的 65,926 条发音形。⇒ 每一条建议都能当场变成两个数。
⭐ 没有这两个数，采纳与否就退化成"听谁说得笃定"——
   而上一轮两家在 `pronunciation_entry` 上同时错了一到两个数量级。

═══ 判据：只看「净修好」不够，必须**两个数都看** ═══
一条规则修好 40 个、弄坏 3 个，和修好 40 个、弄坏 0 个，是两回事：
前者意味着**规则的条件写宽了**，宽的那部分会在标尺外的 23 万词上放大。
⇒ 采纳线定在「弄坏 ≤ 修好的 5%」，**弄坏的那几个必须逐条看过**。

跑（在仓库根）：
    python3 -u ko/pipeline/ablate_g2p.py
    python3 -u ko/pipeline/ablate_g2p.py --half hold     # 最后确认才用留出半
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sqlite3

import paths
from pipeline import g2p


def load(half):
    """→ [(word, gold发音形, sino)]，只取纯谚文且发音形唯一的词形。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # 🔴 `sino` 只认库里真有汉字表记的，**不按"长得像汉字词"猜**
    sino = {r[0] for r in con.execute(
        "SELECT DISTINCT d.word FROM entry e JOIN dict d ON d.id = e.word_id "
        "WHERE e.hanja IS NOT NULL")}
    t = {}
    for w, ph in con.execute(
            "SELECT d.word, p.hangeul_phonetic FROM pronunciation p "
            "JOIN dict d ON d.id = p.word_id WHERE p.hangeul_phonetic IS NOT NULL"):
        t.setdefault(w, set()).add(g2p.strip_len(ph))
    con.close()
    return [(w, next(iter(s)), w in sino) for w, s in t.items()
            if len(s) == 1 and all(g2p.is_syl(c) for c in w)
            and g2p.half_of(w) == half]


def run(rows, rules):
    """→ {word: 算出来的发音形}"""
    return {w: g2p.strip_len(g2p.to_phonetic(w, sino=si, rules=rules))
            for w, g, si in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", default="dev", choices=["dev", "hold"])
    ap.add_argument("--base", default="", help="逗号分隔的基线规则集")
    ap.add_argument("--show", type=int, default=6, help="每条列几个被弄坏的")
    a = ap.parse_args()

    rows = load(a.half)
    gold = {w: g for w, g, _ in rows}
    base = frozenset(x for x in a.base.split(",") if x)
    b = run(rows, base)
    nb = sum(1 for w in gold if b[w] == gold[w])
    print("■ 半：%s   词形 %s   基线规则集：%s"
          % (a.half, format(len(rows), ","), sorted(base) or "（空）"))
    print("   基线 A 级 %s / %s = %.2f%%\n"
          % (format(nb, ","), format(len(rows), ","), 100 * nb / len(rows)))

    print("   %-14s %7s %7s %8s   %s" % ("候选规则", "修好", "🔴弄坏", "净", "被弄坏的样本"))
    for r in g2p.ALL_RULES:
        if r in base:
            continue
        c = run(rows, base | {r})
        fix = [w for w in gold if b[w] != gold[w] and c[w] == gold[w]]
        brk = [w for w in gold if b[w] == gold[w] and c[w] != gold[w]]
        samp = "  ".join("%s→%s(应%s)" % (w, c[w], gold[w]) for w in brk[:a.show])
        print("   %-14s %7s %7s %+8d   %s"
              % (r, format(len(fix), ","), format(len(brk), ","),
                 len(fix) - len(brk), samp[:110]))


if __name__ == "__main__":
    main()
