#!/usr/bin/env python3
"""阶段 -1 探针 C：**新包相对现库多出来的那批词，成色如何**。2026-09-07。

═══ 为什么要单独量 ═══
新包 vs 现库的差值是 **22,572 个词（1.63%）** —— 这是 `EN_PLAN` §1.4 那个
「只差 93 个」被推翻之后的真数。但**数量不是判据，成色才是**。

肉眼看头 20 个样本，压倒性地是**乌克兰地名**（Rokytne / Zabolottia / Monastyrets /
Voroshylove / Piskivka…）—— 像是 Wiktionary 的一次机器批量导入。
🔴 **但「看着像」不是结论**（`[[verify-before-claiming-confirmed]]`）：
   `[[dict-scope-four-rules]]` 的收录方针是按词性和用途定的，不是按我对样本的印象。
   ⇒ 本探针如实统计 pos 分布、IPA、例句、义项，让阶段 3 的收词判据有数可依。

⚠️ 它回答的是「**这 2.2 万值不值得单独做一轮收词**」，
   不回答「阶段 3 要不要收」—— 阶段 3 收的是整个新包，不是这个差集。

跑：  cd en && python3 probes/newword_shape.py
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import sqlite3

import paths

OUT = paths.WORK / "probe"


def main():
    # 现库词表
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = set()
    for (w,) in con.execute("SELECT word FROM stardict"):
        have.add(w)
        have.add(w.lower())
    con.close()

    # 新包里库中没有的词
    miss = set()
    for line in open(OUT / "words_new.tsv", encoding="utf-8"):
        w = line.split("\t", 1)[0]
        if w not in have and w.lower() not in have:
            miss.add(w)

    pos_c = collections.Counter()
    pos_words = collections.defaultdict(set)
    n_ipa = n_ex = n_sense = 0
    samples = collections.defaultdict(list)
    for line in open(paths.KK, encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        w = (d.get("word") or "").strip()
        if w not in miss:
            continue
        pos = d.get("pos") or "?"
        pos_c[pos] += 1
        pos_words[pos].add(w)
        if any(s.get("ipa") for s in (d.get("sounds") or [])):
            n_ipa += 1
        for s in (d.get("senses") or []):
            if s.get("glosses"):
                n_sense += 1
            n_ex += len(s.get("examples") or [])
        if len(samples[pos]) < 8:
            g = ((d.get("senses") or [{}])[0].get("glosses") or [""])[0]
            samples[pos].append((w, g[:64]))

    print("═══ 新包多出来的 %s 个词，按词性 ═══" % f"{len(miss):,}")
    tot_w = sum(len(v) for v in pos_words.values())
    for pos, n in pos_c.most_common():
        print("  %-12s 条目 %6s  词形 %6s  (%.1f%%)"
              % (pos, f"{n:,}", f"{len(pos_words[pos]):,}",
                 100 * len(pos_words[pos]) / max(tot_w, 1)))
    print("\n  带 IPA 的条目 %s ｜ 义项 %s ｜ 例句 %s"
          % (f"{n_ipa:,}", f"{n_sense:,}", f"{n_ex:,}"))
    print("\n═══ 各词性样本 ═══")
    for pos, _ in pos_c.most_common(6):
        print("  ── %s" % pos)
        for w, g in samples[pos]:
            print("     %-26s %s" % (w[:26], g))

    (OUT / "newwords.json").write_text(json.dumps({
        "missing_words": len(miss),
        "by_pos_entries": dict(pos_c),
        "by_pos_words": {k: len(v) for k, v in pos_words.items()},
        "entries_with_ipa": n_ipa, "senses": n_sense, "examples": n_ex,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(OUT / "newwords.tsv", "w", encoding="utf-8") as f:
        for w in sorted(miss):
            f.write(w + "\n")


if __name__ == "__main__":
    main()
