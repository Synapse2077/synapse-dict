#!/usr/bin/env python3
"""阶段 6 探针：七版里有多少葡语词的真人录音 URL。2026-08-30。只读，不写库。

🔴 **复核一条旧结论**：`[[cross-edition-harvest]]` 记着「pt 为 0」——
   那是 2026-08-01 只看**英文版**得出的。本探针逐版量，看这条还成不成立。

⚠️ 只落 URL 不下载字节（`[[audio-from-commons-not-tts]]`：
   `upload.wikimedia.org` 是读者 CDN、**有意限流**，es 全量 276MB 要 6–9 小时）。
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

KEYS = ("mp3_url", "ogg_url", "wav_url", "oga_url", "flac_url", "opus_url")


def main():
    tot = Counter()
    samples = []
    for ed in ("pt", "en", "fr", "zh", "es", "it", "de"):
        path, filt = EDITIONS[ed]
        if not path.exists():
            continue
        c, words = Counter(), set()
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
                w = (e.get("word") or "").strip()
                for sd in (e.get("sounds") or []):
                    hit = [k for k in KEYS if sd.get(k)]
                    if not hit:
                        continue
                    c["录音条目"] += 1
                    words.add(w)
                    for k in hit:
                        c["  " + k] += 1
                    tg = "/".join(sd.get("tags") or []) or "(无 tags)"
                    c["tag·" + tg[:24]] += 1
                    if len(samples) < 300:
                        samples.append((ed, w, sd.get(hit[0])[:96], tg[:24]))
        c["不同词形"] = len(words)
        tot[ed] = c["录音条目"]
        print("\n══ %s 版 ══" % ed)
        for k, v in c.most_common(12):
            print("   %-30s %8s" % (k, f"{v:,}"))
    print("\n══ 合计 %s 条录音条目 ══" % f"{sum(tot.values()):,}")
    print("\n── 抽样 10 ──")
    import random
    random.seed(0)
    for ed, w, u, tg in random.sample(samples, min(10, len(samples))):
        print("   [%s] %-20s %-20s %s" % (ed, w[:20], tg, u))


if __name__ == "__main__":
    sys.exit(main())
