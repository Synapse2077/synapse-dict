#!/usr/bin/env python3
"""阶段 5a/5b 取数：例句 + 语义关系，**一次扫 dump 同时收**。2026-09-08。零 API。

═══ ⭐ en 独有的便宜：例句/关系能**确定性**挂到义项 ═══
`sense_src.src_ref` = `en-edition:<词>:<pos_raw>:<etym>:<seq>#<义项序号>`，全表唯一。
扫 dump 时按同样的规则重建这个键 ⇒ **挂载率应是 100%**。
🔴 de 那轮只能拿「(词形, 德语释义原文) 逐字节匹配」，挂上 **51.3%**；
   pt 靠 `src_gloss` 消歧。en 不需要那些近似手段 —— 但**挂载率要实测，不是假设**。

═══ 为什么中间件不够用 ═══
`entries.jsonl` 的 sense 里 `ex` 只是**条数**（int），不是正文；关系压根没收。
⇒ 本步必须回 dump。**只扫这一次**，例句与关系一起收，产出中间件供 5a/5b 落库。

═══ 收哪些关系（先量再定，不照抄 de）═══
de 有意**不收** derived / related / proverbs 共 87,001 条 ——「构词族与联想词不是语义关系」。
本步先把各族的量打出来（`--scan` 只统计不落盘），再决定 en 收哪些。
`[[es-v3-structure-backfill]]`：照搬别的语言结构前，先量这门语言有没有那个病。

    cd en && python3 -u pipeline/harvest_ex_rel.py          # 扫 + 出中间件 + 统计
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json

import paths

OUT = paths.WORK / "ingest" / "ex_rel.jsonl"
REL_KINDS = ("synonyms", "antonyms", "hypernyms", "hyponyms", "holonyms",
             "meronyms", "coordinate_terms", "troponyms", "derived", "related",
             "proverbs", "abbreviations", "anagrams")


def main():
    seen = collections.Counter()
    stat = collections.Counter()
    rel_c = collections.Counter()
    ex_type = collections.Counter()
    n_line = 0
    with OUT.open("w", encoding="utf-8") as w:
        for line in paths.KK.open(encoding="utf-8"):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("source") == "thesaurus":
                continue
            n_line += 1
            word = o.get("word")
            praw = o.get("pos") or "unknown"
            etym = str(o.get("etymology_number") or "0")
            k = (word, praw, etym)
            seq = seen[k]
            seen[k] += 1
            base = "en-edition:%s:%s:%s:%d" % (word, praw, etym, seq)

            rec = {"w": word, "b": base, "ex": [], "rel": []}
            # 条目级关系：挂到词、不挂义项
            for kind in REL_KINDS:
                for r in o.get(kind) or []:
                    t = (r.get("word") or "").strip()
                    if t:
                        rel_c["entry:" + kind] += 1
                        rec["rel"].append({"k": kind, "t": t, "i": None,
                                           "g": r.get("tags") or []})
            for idx, s in enumerate(o.get("senses") or []):
                for e in s.get("examples") or []:
                    t = (e.get("text") or "").strip()
                    if not t:
                        continue
                    ty = "quote" if (e.get("type") == "quote" or e.get("ref")) else \
                         "example" if e.get("type") == "example" else "other"
                    ex_type[ty] += 1
                    stat["ex"] += 1
                    rec["ex"].append({"i": idx, "t": t, "ty": ty,
                                      "r": e.get("ref"), "en": e.get("english"),
                                      "b": e.get("bold_text_offsets")})
                for kind in REL_KINDS:
                    for r in s.get(kind) or []:
                        t = (r.get("word") or "").strip()
                        if t:
                            rel_c["sense:" + kind] += 1
                            rec["rel"].append({"k": kind, "t": t, "i": idx,
                                               "g": r.get("tags") or []})
            if rec["ex"] or rec["rel"]:
                w.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stat["lines"] += 1
            if n_line % 300000 == 0:
                print("   … %s 行 ｜ 例句 %s ｜ 关系 %s"
                      % (format(n_line, ","), format(stat["ex"], ","),
                         format(sum(rel_c.values()), ",")), flush=True)

    print("\n═══ 扫完 %s 行 ═══" % format(n_line, ","))
    print("   例句 %s ｜ %s" % (format(stat["ex"], ","),
                              "  ".join("%s %s" % (k, format(v, ","))
                                        for k, v in ex_type.most_common())))
    print("\n   关系（义项级 / 条目级）—— **先量再决定收哪些**：")
    kinds = sorted({k.split(":", 1)[1] for k in rel_c})
    print("      %-18s %11s %11s" % ("kind", "义项级", "条目级"))
    for k in sorted(kinds, key=lambda x: -(rel_c["sense:" + x] + rel_c["entry:" + x])):
        print("      %-18s %11s %11s" % (k, format(rel_c["sense:" + k], ","),
                                         format(rel_c["entry:" + k], ",")))
    print("\n   合计关系 %s ｜ 中间件 %s 行 → %s"
          % (format(sum(rel_c.values()), ","), format(stat["lines"], ","), OUT))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
