#!/usr/bin/env python3
"""阶段 -1 取数核对 —— 每个切片实测：条目数 / 意语条目 / 义项数 / 各字段贡献。

═══ 为什么必须实测，不能抄索引页 ═══
`IT_PLAN` 阶段 -1 判据 2：「每个下载的切片：行数 + 意语条目数实测，与索引页声称的数字比对」。
判据 3：「明确写下每个版本**负责哪些字段**」—— 这句话必须由**数出来的数**支撑，
不能凭"法语版音标多"这种印象（那正是 es 上反复自伤的"量源头不量落点"）。

⚠️ 索引页的 senses 数与这里数出来的可能对不上，正常来源有二：
   ① 索引页统计的时间点与切片生成时间不同；② 它可能把 redirect / 无义项条目算法不同。
   **差多少就报多少，不修饰。**

跑：  python3 probes/count_slices.py            （在 it/ 目录下，约 3–6 分钟）
      python3 probes/count_slices.py --quick     （每个源只扫前 20 万行，看形状用）
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

# (键, 文件, 是否需要按 lang_code 过滤, 索引页声称的意语义项数, 用途)
SOURCES = [
    ("en",      D / "kaikki.org-dictionary-Italian.jsonl",          False, 719428,  "结构基准（现建库主源）"),
    ("fr",      D / "kaikki.org-frwiktionary-Italian.jsonl.gz",     False, 1309451, "存量最大"),
    ("it",      D / "itwiktionary.jsonl.gz",                         True,  715056,  "意语原文释义唯一来源"),
    ("zh-trad", D / "kaikki.org-zhwiktionary-Italian-trad.jsonl.gz", False, 194842,  "中文释义/盲测真值"),
    ("zh-simp", D / "kaikki.org-zhwiktionary-Italian-simp.jsonl.gz", False, 3515,    "同上（第二个本地名）"),
    ("el",      D / "kaikki.org-elwiktionary-Italian.jsonl.gz",      False, 175183,  "录音/词形并集"),
    ("tr",      D / "kaikki.org-trwiktionary-Italian.jsonl.gz",      False, 154681,  "录音/词形并集"),
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
            if need_filter and e.get("lang_code") != "it":
                continue
            c["意语条目"] += 1
            w = e.get("word")
            if w:
                words.add(w)
            senses = e.get("senses") or []
            c["义项"] += len(senses)
            # 变形指针义项（`plurale di X`）：kaikki 用 form_of 标注，别数进"真释义"
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

    print("%-9s %10s %10s %10s %9s %9s %10s %10s %9s" %
          ("源", "行", "意语条目", "义项", "其中指针", "有释义", "带音标", "带录音", "声称义项"))
    print("-" * 96)
    for key, p, filt, claim, why in SOURCES:
        if not p.exists():
            print("%-9s 🔴 文件不存在：%s" % (key, p))
            continue
        c = scan(p, filt, limit)
        print("%-9s %10s %10s %10s %9s %9s %10s %10s %9s%s" % (
            key, f'{c["行"]:,}', f'{c["意语条目"]:,}', f'{c["义项"]:,}',
            f'{c["义项_指针"]:,}', f'{c["义项_有释义"]:,}',
            f'{c["带音标条目"]:,}', f'{c["带录音条目"]:,}', f'{claim:,}',
            "  (截断)" if c.get("截断") else ""))
        print("          用途：%s | 不同词形 %s（非指针 %s）| 音标 %s 条 | 录音 %s 条 | 与声称差 %+.1f%%" % (
            why, f'{c["不同词形"]:,}', f'{c["非指针词形"]:,}',
            f'{c["音标条数"]:,}', f'{c["录音条数"]:,}',
            100.0 * (c["义项"] - claim) / claim if claim else 0))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
