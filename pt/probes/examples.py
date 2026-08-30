#!/usr/bin/env python3
"""阶段 5c 探针：各版有多少例句、自带哪些译文、**要翻译的真分母是多少**。2026-08-30。
只读，不写库。

🔴 **翻译成本的分母不是"例句条数"是"不同句子数"** ——
   同一句可以给好几个词当例句（fr 实测省 16.9%）。报价前必须量这个数。

⚠️ 只认 kaikki（用户 2026-08-03 方针 A3：Tatoeba / OPUS 一律排除）。
"""
import gzip
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import paths   # noqa: E402
from intake_edition_words import EDITIONS   # noqa: E402

# 源头给译文的字段名各版不同，全都收集起来看
TR_KEYS = ("english", "translation", "trans", "zh", "chinese")


def main():
    all_text, samples = set(), []
    grand = Counter()
    for ed in ("pt", "en", "fr", "zh", "es", "it", "de"):
        path, filt = EDITIONS[ed]
        if not path.exists():
            continue
        c, seen = Counter(), set()
        keys = Counter()
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
                for si, sn in enumerate(e.get("senses") or []):
                    for ex in (sn.get("examples") or []):
                        t = (ex.get("text") or "").strip()
                        if not t:
                            c["无 text（跳过）"] += 1
                            continue
                        c["例句"] += 1
                        seen.add(t)
                        all_text.add(t)
                        for k in ex:
                            keys[k] += 1
                        for k in TR_KEYS:
                            if (ex.get(k) or "").strip():
                                c["自带 " + k] += 1
                        if len(samples) < 400 and random.random() < 0.002:
                            samples.append((ed, e.get("word"), t[:110],
                                            (ex.get("english") or "")[:60]))
        c["不同句子"] = len(seen)
        grand[ed] = c["例句"]
        print("\n══ %s 版 ══" % ed)
        for k, v in c.most_common():
            print("   %-24s %10s" % (k, f"{v:,}"))
        print("   字段出现次数：%s" % ", ".join(
            "%s=%s" % (k, f"{v:,}") for k, v in keys.most_common(10)))

    print("\n══ 合计 ══")
    print("   各版例句合计       %10s" % f"{sum(grand.values()):,}")
    print("   🔴 **全局不同句子** %10s   ← 翻译成本的真分母" % f"{len(all_text):,}")
    lens = [len(t) for t in all_text]
    lens.sort()
    print("   句长 中位 %d ／ 均 %.0f ／ P90 %d"
          % (lens[len(lens) // 2], sum(lens) / len(lens), lens[int(len(lens) * .9)]))
    print("\n── 抽样 15 条 ──")
    random.seed(0)
    for ed, w, t, en in random.sample(samples, min(15, len(samples))):
        print("   [%s] %-16s %s" % (ed, (w or "")[:16], t))
        if en:
            print("        EN: %s" % en)


if __name__ == "__main__":
    sys.exit(main())
