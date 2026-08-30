#!/usr/bin/env python3
"""阶段 5b 探针：各版的语义关系在哪一层、有多少。2026-08-30。只读，不写库。

判据同 it/fr，不重新设计：
  ✅ 语义关系  synonyms/antonyms/hypernyms/hyponyms/coordinate_terms/meronyms/holonyms
  ❌ derived/related/proverbs —— 构词族与联想词，不是语义关系（单独计数，供决策）
"""
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import paths   # noqa: E402
from intake_edition_words import EDITIONS   # noqa: E402

SEM = ("synonyms", "antonyms", "hypernyms", "hyponyms",
       "coordinate_terms", "meronyms", "holonyms")
SKIP = ("derived", "related", "proverbs")


def main():
    for ed in ("pt", "en", "fr", "zh"):
        path, filt = EDITIONS[ed]
        if not path.exists():
            print("缺 %s" % ed)
            continue
        c = Counter()
        op = gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" \
            else open(path, encoding="utf-8")
        with op as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if filt and e.get("lang_code") != "pt":
                    continue
                c["条目"] += 1
                for k in SEM + SKIP:
                    n = len(e.get(k) or [])
                    if n:
                        c["词条级·" + k] += n
                for sn in (e.get("senses") or []):
                    for k in SEM + SKIP:
                        n = len(sn.get(k) or [])
                        if n:
                            c["义项级·" + k] += n
        print("\n══ %s 版 ══  条目 %s" % (ed, f"{c['条目']:,}"))
        sem_e = sum(v for k, v in c.items() if k.startswith("词条级·")
                    and k.split("·")[1] in SEM)
        sem_s = sum(v for k, v in c.items() if k.startswith("义项级·")
                    and k.split("·")[1] in SEM)
        print("   语义关系：词条级 %s ／ 义项级 %s" % (f"{sem_e:,}", f"{sem_s:,}"))
        for k, v in sorted(c.items()):
            if k != "条目":
                mark = "  " if k.split("·")[1] in SEM else "✗ "
                print("   %s%-30s %10s" % (mark, k, f"{v:,}"))


if __name__ == "__main__":
    sys.exit(main())
