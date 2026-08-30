#!/usr/bin/env python3
"""阶段 1.5 探针：那 48,810 个零义项词头，各版能给什么。2026-08-30。只读，不写库。

🔴 **报价之前必须把免费路径挖干净**（`[[prove-free-path-before-quoting]]`）。
   最值得试的一条：**中文版直接给中文释义** ——
   `[[gloss-three-languages]]` 记着 es 那轮「zh 版 27,475 个人工中文**只用了 37 条**」。
"""
import gzip
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import paths   # noqa: E402
from intake_edition_words import EDITIONS, norm_apos   # noqa: E402

HAN = set(range(0x4E00, 0xA000))


def has_han(s):
    return any(ord(c) in HAN for c in s or "")


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    need = {w for (w,) in con.execute(
        "SELECT d.word FROM dict d WHERE d.is_lemma=1 AND NOT EXISTS("
        "  SELECT 1 FROM entry e JOIN sense s ON s.entry_id=e.id WHERE e.word_id=d.id)")}
    con.close()
    print("■ 零义项词头 %s" % f"{len(need):,}")

    got = defaultdict(dict)      # word -> {ed: [gloss…]}
    stat = Counter()
    samples = defaultdict(list)
    for ed in ("pt", "zh", "fr", "en", "ru", "pl", "es", "de", "it"):
        path, filt = EDITIONS[ed]
        if not path.exists():
            continue
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
                w = norm_apos((e.get("word") or "").strip())
                if w not in need:
                    continue
                gs = [(sn.get("glosses") or [""])[0].strip()
                      for sn in (e.get("senses") or [])
                      if (sn.get("glosses") or [""])[0].strip()
                      and not (sn.get("form_of") or sn.get("alt_of"))]
                if not gs:
                    continue
                got[w].setdefault(ed, []).extend(gs)
                stat["%s·有真释义的词" % ed] += 1
                stat["%s·义项条数" % ed] += len(gs)
                if ed == "zh":
                    n = sum(1 for g in gs if has_han(g))
                    stat["zh·其中带汉字的义项"] += n
                if len(samples[ed]) < 6:
                    samples[ed].append((w, gs[0][:70]))
        stat["扫完 " + ed] += 1

    print()
    for k, v in sorted(stat.items()):
        if not k.startswith("扫完"):
            print("   %-24s %8s" % (k, f"{v:,}"))

    print("\n═══ 免费路径盘点 ═══")
    zh_free = {w for w, d in got.items()
               if any(has_han(g) for g in d.get("zh", []))}
    print("  🔴 中文版直接给中文释义的词    %s   ← **免费**" % f"{len(zh_free):,}")
    cover = set(got)
    print("  至少有一版给出真释义的词      %s / %s (%.1f%%)"
          % (f"{len(cover):,}", f"{len(need):,}", 100 * len(cover) / len(need)))
    print("  一版都没有（源头就没有释义）  %s" % f"{len(need) - len(cover):,}")
    todo = cover - zh_free
    print("  🔴 要送翻译的词                %s" % f"{len(todo):,}")
    n_sense = sum(len(v) for w in todo for v in got[w].values())
    chars = sum(len(g) for w in todo for v in got[w].values() for g in v)
    print("     其中义项条数 %s ／ 原文字符 %s（均 %.0f）"
          % (f"{n_sense:,}", f"{chars:,}", chars / max(n_sense, 1)))

    for ed in ("zh", "pt", "fr", "ru"):
        if samples[ed]:
            print("\n── %s 版样例 ──" % ed)
            for w, g in samples[ed]:
                print("   %-24s %s" % (w[:24], g))


if __name__ == "__main__":
    sys.exit(main())
