#!/usr/bin/env python3
"""义项补全的候选集：给每条分歧找**第二个独立证据**。只读，不写库，不调模型。2026-08-02。

═══ 为什么还要一步 ═══
`zh_translation_divergence.py` 给出 1,275 条"我们和中文版一个实词字都不共享"。
双家评审逐样本裁决后，两家**同时**判 import 的只有 3/18（17%）—— 也就是说
这 1,275 条里**大部分不该补**（近义改述、生僻义、方言义、专名描述…）。

判"该不该补"是语义题，确定性做不了。但**"我们的义项集合是不是偏薄"是可以确定性测的**：
    我们的义项数（来自英文版）  vs  中文版义项数  vs  西语版义项数
中文版和西语版是**两个互相独立的源**。两个都比我们多，比只有一个多可信得多。
→ 本脚本产出带证据分层的候选集，**把送模型裁决的量压下来**，而不是把 1,275 条全送。

⚠️ 这里量的仍然是"义项数"这个**代理指标**，不是"缺了哪个义项"。它只用来排序和分层，
   不用来做最终裁决 —— 别把代理指标当结论（今天已经在这上面栽了十几次）。

用法（在 es/ 目录）：
    python3 probes/sense_gap_candidates.py
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import gzip
import json
import sqlite3

import paths

DIV = paths.WORK / "runs" / "zh_translation_divergence.jsonl"
OUT = paths.WORK / "runs" / "sense_gap_candidates.jsonl"

# 中文版里这些"义项"是元描述，不算义项数
from probes.zh_translation_divergence import META_GLOSS


def es_edition_senses():
    """西语版每个西语词的**真义项数**（剔掉变位/元描述指针）。"""
    n = collections.Counter()
    for ln in gzip.open(paths.EDITION, "rt", encoding="utf-8", errors="replace"):
        e = json.loads(ln)
        if e.get("lang_code") != "es":
            continue
        c = 0
        for s in e.get("senses") or []:
            g = (s.get("glosses") or [""])[0]
            if not g or s.get("form_of") or s.get("alt_of"):
                continue
            c += 1
        n[e["word"]] += c
    return n


def zh_senses():
    n = collections.Counter()
    for ln in open(paths.WORK / "zh_es.jsonl", encoding="utf-8"):
        e = json.loads(ln)
        c = sum(1 for s in e["senses"] for g in s["g"] if not META_GLOSS.search(g))
        n[e["word"]] += c
    return n


def main():
    div = [json.loads(l) for l in open(DIV, encoding="utf-8")]
    zh, es = zh_senses(), es_edition_senses()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ours = {w: (d or "").count("\n") + 1
            for w, d in conn.execute(
                "SELECT word, definition FROM dict WHERE is_lemma=1 "
                "AND TRIM(COALESCE(definition,''))<>''")}
    conn.close()

    tier = collections.Counter()
    recs = []
    for r in div:
        w = r["word"]
        o, z, e = ours.get(w, 0), zh.get(w, 0), es.get(w, 0)
        if not o:
            continue
        both = z > o and e > o
        one = (z > o) != (e > o)
        t = ("① 两个独立源都比我们多义项" if both
             else "② 只有一个源比我们多" if one
             else "③ 义项数不比我们多（多半是改述/生僻义）")
        tier[t] += 1
        r.update({"ours_n": o, "zh_n": z, "es_n": e, "tier": t})
        recs.append(r)

    print("■ 1,275 条分歧按「第二个独立证据」分层")
    for t, n in sorted(tier.items()):
        print("    %-34s %5d  (%.1f%%)" % (t, n, n * 100 / max(len(recs), 1)))

    core = [r for r in recs if r["tier"].startswith("①")]
    lv = collections.Counter(r["level"] or "—" for r in core)
    print("\n■ ① 层按 CEFR：%s" % dict(sorted(lv.items())))
    print("\n■ ① 层样本（我们的义项数 / 中文版 / 西语版）")
    for r in sorted(core, key=lambda x: (x["level"] or "z"))[:14]:
        print("   %-16s [%s]  我们%d 中文版%d 西语版%d" % (
            r["word"], r["level"], r["ours_n"], r["zh_n"], r["es_n"]))
        print("      我们  : %s" % (r["ours"] or "").replace("\n", " / ")[:74])
        print("      中文版: %s" % " / ".join(r["zh"])[:74])

    with open(OUT, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\n→ %s" % OUT)


if __name__ == "__main__":
    main()
