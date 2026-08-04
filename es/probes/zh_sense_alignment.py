#!/usr/bin/env python3
"""译文核对的**义项级**比对：中文版有、而我们一个义项都没对上的义项。2026-08-03。只读，不调模型。

═══ 为什么词级不够 ═══
`zh_translation_divergence.py` 是**词级**的：只要任一义项搭得上就算"一致"，
于是 `coche` 有五个义项、缺了最常用的那个也照样计入 95% 那一档。
它回答的是"我们和中文版有没有在讲同一个词"，不是"我们缺不缺义项"。

2026-08-02 试过用**义项数**当筛子（`sense_gap_candidates.py`：中文版和西语版都比我们多），
只筛出 8 条 —— 因为**我们的义项集合通常比两个源都大**（英文版切得极细）。
结论当时就写下了：**缺口不在数量在结构**。本脚本换成按**内容**逐义项配对，
直接回答"中文版的这一条，我们有没有对应的"。

═══ 判据（沿用词级那套的两层，不另发明）═══
中文版某义项算"我们有" = 它与**我们任一义项**在 L1（词级/子串）或 L2（共享实词字）上搭得上。
两层的理由见 `zh_translation_divergence.py`：中文近义大量共字不共词（碎屑/碎片）。
元描述义项（"XX的复数"）在加载时已剔除。

⚠️ **本脚本产出的是候选，不是判决。** 中文版给的义项也可能是冷僻义、方言义、
   或它自己切得比我们粗。真要补，还得过第二个独立源（西语版）——见 2026-08-02 那轮。

用法（在 es/ 目录）：
    python3 probes/zh_sense_alignment.py
    python3 probes/zh_sense_alignment.py --dump
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import random
import sqlite3

import paths
from probes.zh_translation_divergence import META_GLOSS, agrees, shares_char, toks

ZH = paths.WORK / "zh_es.jsonl"
OUT = paths.WORK / "runs" / "zh_sense_gaps.jsonl"


def load_zh_senses():
    """→ {word: [(原文, token集), …]}，逐义项保留（词级那份是合并成一袋的）。"""
    d = collections.defaultdict(list)
    for ln in open(ZH, encoding="utf-8"):
        e = json.loads(ln)
        for s in e["senses"]:
            for g in s["g"]:
                if META_GLOSS.search(g):
                    continue
                tk = toks(g)
                if tk:
                    d[e["word"]].append((g, tk))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    a = ap.parse_args()

    zh = load_zh_senses()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = conn.execute(
        "SELECT word, pos, translation, level, definition FROM dict WHERE is_lemma=1 "
        "AND TRIM(COALESCE(translation,''))<>''").fetchall()
    conn.close()

    stat = collections.Counter()
    by_lv = collections.Counter()
    recs = []
    for w, pos, tr, lv, dfn in rows:
        zs = zh.get(w)
        if not zs:
            continue
        ours = [(ln, toks(ln)) for ln in (tr or "").split("\n") if toks(ln)]
        if not ours:
            continue
        stat["可比词"] += 1
        stat["我们的义项"] += len(ours)
        stat["中文版义项"] += len(zs)
        miss = [g for g, tk in zs
                if not any(agrees(tk, o) or shares_char(tk, o) for _, o in ours)]
        stat["中文版义项·我们没有"] += len(miss)
        if not miss:
            continue
        stat["有缺口的词"] += 1
        # 词级比对是否已经把这个词标成"分歧"？没标 = 词级漏掉的
        word_level_ok = any(agrees(tk, o) or shares_char(tk, o)
                            for _, tk in zs for _, o in ours)
        if word_level_ok:
            stat["🔴 词级看不见的（我们对上了别的义项）"] += 1
            by_lv[lv or "—"] += 1
        recs.append({"word": w, "pos": pos, "level": lv, "hidden": word_level_ok,
                     "ours": tr, "miss": miss,
                     "def": (dfn or "").split("\n")[0][:90]})

    print("■ 义项级比对（可比词 = 双方都有释义的 lemma）")
    for k in ("可比词", "我们的义项", "中文版义项", "中文版义项·我们没有",
              "有缺口的词", "🔴 词级看不见的（我们对上了别的义项）"):
        print("   %-32s %8s" % (k, "{:,}".format(stat[k])))
    print("   %-32s %7.1f%%" % ("中文版义项的未覆盖率",
                                100 * stat["中文版义项·我们没有"] / max(stat["中文版义项"], 1)))
    print("\n   词级看不见的那批按 CEFR：", dict(sorted(by_lv.items())))

    core = [r for r in recs if r["hidden"] and (r["level"] or "") in ("A1", "A2", "B1")]
    print("\n" + "=" * 78)
    print("■ 核心层（A1/A2/B1）且词级看不见的：%d 条，全列如下\n" % len(core))
    for r in sorted(core, key=lambda x: (x["level"], x["word"]))[:40]:
        print("  %-16s [%s·%s]" % (r["word"], r["pos"], r["level"]))
        print("     我们  : %s" % (r["ours"] or "").replace("\n", " / ")[:88])
        print("     中文版缺: %s" % " / ".join(r["miss"])[:88])
    if len(core) > 40:
        print("   …… 还有 %d 条" % (len(core) - 40))

    rest = [r for r in recs if r["hidden"] and r not in core]
    if rest:
        random.seed(11)
        print("\n" + "=" * 78 + "\n■ 尾巴层样本 8 条\n")
        for r in random.sample(rest, min(8, len(rest))):
            print("  %-16s [%s·%s]" % (r["word"], r["pos"], r["level"]))
            print("     我们  : %s" % (r["ours"] or "").replace("\n", " / ")[:88])
            print("     中文版缺: %s" % " / ".join(r["miss"])[:88])

    if a.dump:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("\n→ %s（%d 条）" % (OUT, len(recs)))


if __name__ == "__main__":
    main()
