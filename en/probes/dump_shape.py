#!/usr/bin/env python3
"""阶段 -1 探针 A：**新包的形状**（`EN_PLAN` §一 全部数字重测）。2026-09-07。

═══ 为什么必须重测 ═══
`EN_PLAN` 头部写死：所有 kaikki 侧的数字都来自 2025-04-24 的老包，**阶段 -1 必须用新包重测**。
更要紧的是 §1.4 那条自伤：我拿「kaikki 只比库里多 93 个词」下过
「换基底收词收益为零」的结论 —— 而那 93 是**同源自比**
（`probes/import-wiktionary-newwords.py` 读的就是老包，逻辑是"库里没有的全插进去"）。
⇒ **拿新包重算，那个差值才第一次有意义。**

输出（全部落 `data/work/en/probe/`，不打屏刷屏）：
  dump_shape.json          总体形状
  words_new.tsv            新包每个词头一行：词头 / 有无IPA / 义项数 / 非元描述义项数 / 例句数
  pos_hist.tsv             词性分布

零 API 成本、只读。
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import time

import paths

OUT = paths.WORK / "probe"

# 元描述首义的措辞。**只用于分层统计，不用于任何写库判据。**
# 🔴 判据故意收窄：只认「首义以它开头」，不扫全文 ——
#    `[[criteria-narrower-than-you-think]]`，宽判据会把带例句说明的真义项吃进去。
META = ("plural of", "past tense of", "past participle of", "alternative form of",
        "alternative spelling of", "present participle of", "comparative of",
        "superlative of", "synonym of", "obsolete form of", "misspelling of",
        "inflection of", "abbreviation of", "initialism of", "acronym of",
        "pronunciation spelling of", "archaic form of", "obsolete spelling of",
        "eye dialect of", "clipping of", "ellipsis of", "attributive form of")


def is_meta(gloss):
    g = (gloss or "").strip().lower()
    return any(g.startswith(m) for m in META)


def main(src, tag):
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    n_line = n_bad = 0
    words, words_ipa = set(), set()
    pos_c = collections.Counter()
    n_entry_ipa = n_sense = n_meta = n_ex = n_forms = n_multiword = 0
    n_rel = n_etym = 0
    fw = open(OUT / ("words_%s.tsv" % tag), "w", encoding="utf-8")
    for line in open(src, encoding="utf-8"):
        n_line += 1
        try:
            d = json.loads(line)
        except Exception:
            n_bad += 1
            continue
        w = (d.get("word") or "").strip()
        if not w:
            continue
        words.add(w)
        if " " in w:
            n_multiword += 1
        pos_c[d.get("pos", "?")] += 1

        ipa = [s for s in (d.get("sounds") or []) if s.get("ipa")]
        if ipa:
            n_entry_ipa += 1
            words_ipa.add(w)
        if d.get("forms"):
            n_forms += 1
        if d.get("etymology_text"):
            n_etym += 1

        ns = nm = ne = 0
        for s in (d.get("senses") or []):
            gl = s.get("glosses") or []
            if not gl:
                continue
            ns += 1
            if not is_meta(gl[0]):
                nm += 1
            ne += len(s.get("examples") or [])
            for k in ("synonyms", "antonyms", "hypernyms", "hyponyms", "derived", "related"):
                n_rel += len(s.get(k) or [])
        n_sense += ns
        n_meta += (ns - nm)
        n_ex += ne
        fw.write("%s\t%d\t%d\t%d\t%d\n" % (w.replace("\t", " "), 1 if ipa else 0, ns, nm, ne))
    fw.close()

    shape = {
        "src": str(src), "tag": tag, "seconds": round(time.time() - t0, 1),
        "lines": n_line, "unparsable": n_bad,
        "distinct_words": len(words), "multiword_entries": n_multiword,
        "entries_with_ipa": n_entry_ipa, "distinct_words_with_ipa": len(words_ipa),
        "senses": n_sense, "senses_meta": n_meta, "senses_real": n_sense - n_meta,
        "examples": n_ex, "entries_with_forms": n_forms,
        "entries_with_etymology": n_etym, "sense_relations": n_rel,
    }
    (OUT / ("dump_shape_%s.json" % tag)).write_text(
        json.dumps(shape, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(OUT / ("pos_hist_%s.tsv" % tag), "w", encoding="utf-8") as f:
        for p, n in pos_c.most_common():
            f.write("%s\t%d\n" % (p, n))
    for k, v in shape.items():
        print("  %-26s %s" % (k, f"{v:,}" if isinstance(v, int) else v))


if __name__ == "__main__":
    which = _sys.argv[1] if len(_sys.argv) > 1 else "new"
    main(paths.KK if which == "new" else paths.KK_2025, which)
