#!/usr/bin/env python3
"""阶段 -1 取数核对 —— 每个源实测：条目数 / 法语条目 / 义项数 / 各字段贡献。2026-08-21。

═══ 为什么必须实测，不能抄索引页 ═══
`FR_PLAN` 阶段 -1 判据：「每个源：行数 + 法语条目数实测，与索引页声称的数字比对」；
「明确写下每个版本**负责哪些字段**」—— 这句话必须由**数出来的数**支撑，
不能凭"法语版音标多"这种印象（那正是 es 上反复自伤的"量源头不量落点"）。

🔴 **本脚本存在的直接理由**：我 2026-08-21 第一版扫描报「法文版 2,106,669 条目带法语原文释义
（99.98%）」，那个数把**变形指针**（`Masculin pluriel de X`）算进了"释义"。
it 上同一个坑的代价写在 `it-CONVENTIONS.md`：意语原文释义的真实规模是 105,474 条、
不是 714,223 —— **后者 85% 是变形指针**，而阶段 1.5 的 3–4 天工期就是按那个虚数排的。
⇒ 判据必须是 kaikki 的**结构化字段** `form_of` / `alt_of`，不是我猜的法语前缀词表。

⚠️ `form_of` 与 `alt_of` 在这里都算"非真释义"，但**建库时绝不能混为一谈** ——
   `alt_of` 是异体拼写、`form_of` 是屈折变形，es 把两者当同一回事造出了
   「Méjico 的 阳性」这类编造标签，3,890 个（`PITFALLS` B 组）。
   这里只是计数，混着数无害；`build.py` 里必须分开。

⚠️ 索引页的 senses 数与这里数出来的可能对不上，正常来源有二：
   ① 索引页统计时间点与切片生成时间不同；② redirect / 无义项条目的算法不同。
   **差多少就报多少，不修饰。**

跑：  python3 probes/count_slices.py           （在 fr/ 目录下，约 8–15 分钟）
      python3 probes/count_slices.py --quick    （每个源只扫前 20 万行，看形状用）
"""
import sys
import pathlib
import argparse
import gzip
import json
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import paths

D = paths.DUMPS

# (键, 文件, 是否需要按 lang_code 过滤, 索引页声称的法语义项数, 用途)
#  🔴 "需要过滤" = 该文件是**多语种整包**；per-language 切片已经切好，不用再过滤。
SOURCES = [
    ("en",  D / "kaikki.org-dictionary-French.jsonl",        False, 458908,  "结构基准（现建库主源）"),
    ("fr",  D / "frwiktionary.jsonl.gz",                      True,  2653194, "存量最大 + 法语原文释义唯一来源"),
    ("tr",  D / "kaikki.org-trwiktionary-French.jsonl.gz",    False, 215326,  "词形并集（实测几乎无音标）"),
    ("zh",  D / "zhwiktionary.jsonl.gz",                      True,  183447,  "人工中文 / 盲测真值（两个本地名合计）"),
    ("el",  D / "kaikki.org-elwiktionary-French.jsonl.gz",    False, 83892,   "词形并集 + 例句"),
    ("nl",  D / "kaikki.org-nlwiktionary-French.jsonl.gz",    False, 54434,   "录音密度最高"),
    ("ru",  D / "kaikki.org-ruwiktionary-French.jsonl.gz",    False, 43224,   "词形 + 例句"),
    ("ja",  D / "kaikki.org-jawiktionary-French.jsonl.gz",    False, 36727,   "音标"),
    ("it",  D / "itwiktionary.jsonl.gz",                      True,  34788,   "跨版收割"),
    ("de",  D / "dewiktionary.jsonl.gz",                      True,  16913,   "跨版收割（录音）"),
    ("es",  D / "eswiktionary.jsonl.gz",                      True,  0,       "跨版收割（索引页未识别本地名）"),
    ("pt",  D / "ptwiktionary.jsonl.gz",                      True,  7839,    "跨版收割"),
    # ⏸ pl（41,437 义项 / 4.6 MB）：本地名 `język francuski` 的三种写法全部 404，
    #    按「判据改到第三轮就停手」记账不追。要用时先查它的真实切片 URL。
]


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def scan(p, need_filter, limit=None):
    c = Counter()
    words, lemmas = set(), set()
    with opener(p) as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                c["截断"] = 1
                break
            c["行"] += 1
            try:
                e = json.loads(line)
            except Exception:
                c["坏行"] += 1
                continue
            if need_filter and e.get("lang_code") != "fr":
                continue
            c["法语条目"] += 1
            w = e.get("word")
            if w:
                words.add(w)
            senses = e.get("senses") or []
            c["义项"] += len(senses)
            # 🔴 变形指针义项：judged by kaikki 的结构化字段，**不是**按释义文本猜前缀
            for s in senses:
                if s.get("form_of") or s.get("alt_of"):
                    c["义项_指针"] += 1
                elif s.get("glosses"):
                    c["义项_有释义"] += 1
            if not any((s.get("form_of") or s.get("alt_of")) for s in senses) and w:
                lemmas.add(w)
            sounds = e.get("sounds") or []
            if any(s.get("ipa") for s in sounds):
                c["带音标条目"] += 1
                c["音标条数"] += sum(1 for s in sounds if s.get("ipa"))
            if any(s.get(k) for s in sounds for k in ("mp3_url", "ogg_url", "wav_url")):
                c["带录音条目"] += 1
                c["录音条数"] += sum(1 for s in sounds
                                     for k in ("mp3_url", "ogg_url", "wav_url") if s.get(k))
            if any(s.get("examples") for s in senses):
                c["带例句条目"] += 1
            if e.get("forms"):
                c["带 forms 条目"] += 1
    c["不同词形"] = len(words)
    c["非指针词形"] = len(lemmas)
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    limit = 200000 if a.quick else None

    print("%-5s %11s %11s %11s %10s %10s %9s %9s %9s %10s" %
          ("源", "行", "法语条目", "义项", "其中指针", "真释义", "带音标", "带录音", "带例句", "声称义项"))
    print("-" * 108)
    for key, p, filt, claim, why in SOURCES:
        if not p.exists():
            print("%-5s 🔴 文件不存在：%s" % (key, p))
            continue
        c = scan(p, filt, limit)
        print("%-5s %11s %11s %11s %10s %10s %9s %9s %9s %10s%s" % (
            key, f'{c["行"]:,}', f'{c["法语条目"]:,}', f'{c["义项"]:,}',
            f'{c["义项_指针"]:,}', f'{c["义项_有释义"]:,}',
            f'{c["带音标条目"]:,}', f'{c["带录音条目"]:,}', f'{c["带例句条目"]:,}',
            f'{claim:,}', "  (截断)" if c.get("截断") else ""))
        print("      用途：%s | 不同词形 %s（非指针 %s）| 音标 %s 条 | 录音 %s 条 | 与声称差 %s" % (
            why, f'{c["不同词形"]:,}', f'{c["非指针词形"]:,}',
            f'{c["音标条数"]:,}', f'{c["录音条数"]:,}',
            ("%+.1f%%" % (100.0 * (c["义项"] - claim) / claim)) if claim else "（索引页未给）"))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
