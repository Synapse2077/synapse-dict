#!/usr/bin/env python3
"""§四.1-c 的「先验」那一半：拿韩文版的发音形谚文当标尺，实测 G2P 准确率。2026-09-21。

**这个脚本不写库。** 它回答的是一个先决问题：
「韩语的 G2P 够不够格给那 23 万个没有读音的词形补音？」

═══ 标尺为什么能用（这一条要先答，否则后面的数没有意义）═══
标尺集 = `pronunciation.hangeul_phonetic` 非空的 65,926 行 / 53,311 个词形。
🔴 最容易犯的错是**默认标尺集有代表性**。要问的是：
   「韩文版是不是只在『读音≠拼写』的时候才标发音形？」
   —— 如果是，标尺集就是被挑难的，量出来的准确率会**低估**真实值。
   实测：**发音形 == 拼写形的占 54.8%** ⇒ 源头是无条件标注的，没有难度偏置。
⚠️ 另一半偏置仍在：标尺集是**韩文版收的词**（多为词元），而应用对象含大量
   中文版独有词。这一条**不能靠标尺内部证伪**，只能在报告里写明。

═══ 开发半 / 留出半 ═══
规则只看开发半的错误；报出去的数是**留出半**的（`[[proxy-metric-gets-optimized]]`）。
切分按词形的 md5 —— 稳定、与行序无关、同词形不跨半。

跑（在仓库根）：
    python3 -u ko/pipeline/validate_g2p.py
    python3 -u ko/pipeline/validate_g2p.py --show dev --errors 40
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import sqlite3

import paths
from pipeline import g2p


def load(con):
    """→ {词形: {'phon': {发音形…}, 'ipa': {IPA…}, 'has_len': bool}}"""
    d = {}
    for w, ph, ipa in con.execute(
            "SELECT d.word, p.hangeul_phonetic, p.ipa FROM pronunciation p "
            "JOIN dict d ON d.id = p.word_id "
            "WHERE p.hangeul_phonetic IS NOT NULL"):
        e = d.setdefault(w, {"phon": set(), "ipa": set(), "has_len": False,
                             "pairs": []})
        if "ː" in (ph or "") or "ː" in (ipa or ""):
            e["has_len"] = True
        e["phon"].add(g2p.strip_len(ph))
        e["ipa"].add(g2p.strip_stress(g2p.strip_len(ipa)))
        e["pairs"].append((g2p.strip_len(ph),
                           g2p.strip_stress(g2p.strip_len(ipa))))
    return d


PURE = lambda w: bool(w) and all(g2p.is_syl(c) for c in w)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", choices=["dev", "hold", "both"], default="both")
    ap.add_argument("--errors", type=int, default=0,
                    help="列出多少条错误样本（只列开发半 —— 留出半不许看）")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    truth = load(con)

    print("═══ 标尺集 ═══")
    print("   词形 %s ／ 其中纯谚文无空格 %s"
          % (format(len(truth), ","),
             format(sum(1 for w in truth if PURE(w)), ",")))
    nlen = sum(1 for w, e in truth.items() if e["has_len"])
    print("   带长音标记的词形 %s（%.1f%%）—— **规则上算不出来，两边都剥掉再比**"
          % (format(nlen, ","), 100 * nlen / len(truth)))
    multi = sum(1 for w, e in truth.items() if len(e["phon"]) > 1)
    print("   有 ≥2 个不同发音形的词形 %s（%.1f%%）—— 这些**单列**，不混进主指标"
          % (format(multi, ","), 100 * multi / len(truth)))

    # ── 主指标只在「纯谚文 ＋ 发音形唯一」的子集上算 ────────────────
    bucket = {"dev": [], "hold": []}
    for w, e in truth.items():
        if not PURE(w) or len(e["phon"]) != 1:
            continue
        bucket[g2p.half_of(w)].append((w, next(iter(e["phon"])), e))

    for half in ("dev", "hold"):
        rows = bucket[half]
        okA = okB = okE2E = 0
        errA = []
        errB = []
        for w, gold_ph, e in rows:
            my_ph = g2p.strip_len(g2p.to_phonetic(w))
            a_ok = my_ph == gold_ph
            okA += a_ok
            if not a_ok and len(errA) < 4000:
                errA.append((w, gold_ph, my_ph))
            # B 级**用金标准的发音形**当输入 —— 这样量的才是 B 级自己
            gold_ipas = {i for p, i in e["pairs"] if p == gold_ph}
            my_ipa_from_gold = g2p.to_ipa(gold_ph)
            b_ok = my_ipa_from_gold in gold_ipas
            okB += b_ok
            if not b_ok and len(errB) < 4000:
                errB.append((gold_ph, sorted(gold_ipas)[0], my_ipa_from_gold))
            okE2E += g2p.to_ipa(my_ph) in gold_ipas

        n = max(len(rows), 1)
        tag = "开发半" if half == "dev" else "🔴 留出半（报这个）"
        print("\n═══ %s：%s 个词形 ═══" % (tag, format(len(rows), ",")))
        print("   A 级 표기형→발음형   %7s / %7s = %6.2f%%"
              % (format(okA, ","), format(len(rows), ","), 100 * okA / n))
        print("   B 级 발음형→IPA      %7s / %7s = %6.2f%%   （输入用金标准发音形）"
              % (format(okB, ","), format(len(rows), ","), 100 * okB / n))
        print("   端到端 표기형→IPA    %7s / %7s = %6.2f%%"
              % (format(okE2E, ","), format(len(rows), ","), 100 * okE2E / n))

        if half == "dev":
            dev_errA, dev_errB = errA, errB

    # ── 错误分类：只看开发半 ────────────────────────────────────
    print("\n═══ 开发半 A 级错误归类（%s 条）═══" % format(len(dev_errA), ","))
    cat = collections.Counter()
    for w, gold, mine in dev_errA:
        if len(gold) != len(mine):
            cat["长度不等（ㄴ첨가/音节增减）"] += 1
            continue
        diff = [(a, b) for a, b in zip(gold, mine) if a != b]
        if len(diff) == 1:
            g_, m_ = diff[0]
            gd, md = g2p.decompose(g_), g2p.decompose(m_)
            if gd[0] != md[0] and gd[1] == md[1] and gd[2] == md[2]:
                cat["只差초성（多半是경음화/비음화判错）"] += 1
            elif gd[2] != md[2] and gd[0] == md[0] and gd[1] == md[1]:
                cat["只差종성"] += 1
            elif gd[1] != md[1]:
                cat["差중성（元音）"] += 1
            else:
                cat["单音节多处不同"] += 1
        else:
            cat["多处不同"] += 1
    for k, v in cat.most_common():
        print("   %-34s %7s（%.1f%%）"
              % (k, format(v, ","), 100 * v / max(len(dev_errA), 1)))

    print("\n═══ 开发半 B 级错误归类（%s 条）═══" % format(len(dev_errB), ","))
    cb = collections.Counter()
    for ph, gold, mine in dev_errB:
        cb[("长度 %+d" % (len(mine) - len(gold))) if len(mine) != len(gold)
           else "等长不同"] += 1
    for k, v in cb.most_common(8):
        print("   %-34s %7s" % (k, format(v, ",")))

    if a.errors:
        print("\n■ 开发半 A 级错误样本（金标准 ／ 我算的）")
        for w, gold, mine in dev_errA[:a.errors]:
            print("   %-14s %-16s %s" % (w, gold, mine))
        print("\n■ 开发半 B 级错误样本（发音形 ／ 金标准 IPA ／ 我算的）")
        for ph, gold, mine in dev_errB[:a.errors]:
            print("   %-14s %-26s %s" % (ph, gold, mine))
    con.close()


if __name__ == "__main__":
    main()
