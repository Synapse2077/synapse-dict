#!/usr/bin/env python3
"""阶段 -1 取数核对 —— 每个源实测：条目数 / 德语条目 / 义项数 / 各字段贡献。2026-08-31。

═══ 为什么必须实测，不能抄索引页、更不能凭印象 ═══
`PT_PLAN` / `FR_PLAN` 阶段 -1 各逮到三处自伤，一个都不是读代码看出来的
（法语原文释义 210 万 → 真值 697,814；中文版可用中文 151,537 → 27,440）。
⇒ 判据必须是 kaikki 的**结构化字段** `form_of` / `alt_of`，不是按释义文本猜前缀。

⚠️ `form_of` 与 `alt_of` 这里都算"非真释义"，但**建库时绝不能混为一谈** ——
   es 把两者当同一回事，造出「Méjico 的 阳性」这类编造标签 3,890 个（`PITFALLS` B 组）。

═══ 🔴 de 特有的三列（别的语种没量过，或量了但结论不能照搬）═══
① **`forms` 数组带不带 ipa**：de 的变形层 260,066 行里只有 20,553 行有音标（7.9%），
   与 pt 开工时同一个形状。`docs/lang/de-DESIGN.md` 写着「变位形 IPA 无法从 forms 收割
   （含 ipa=0%）」——**但那只量了英文版**，德语版从来没有人查过这一项。
   带 ⇒ fr 那招（从 lemma 的 forms 收割变位形音标，一次补 387,826 条）在 de 上成立。
② **德语版的录音**：`[[audio-from-commons-not-tts]]` 记着 de 覆盖 76%，那是**英文版**的数。
   德语维基的 Aussprache 段几乎条条带 Lautsprecher，规模要实测。
③ **三性 + 属格/复数的著录**：德语名词的两大著录形（`des Hauses` / `die Häuser`）
   在 dump 里是 `forms` 还是 `head_templates`，决定阶段 2 变形层怎么建。

⚠️ 本脚本**不下载任何东西**，只扫本地已有的源。
🔴 建库主源 `kaikki.org-dictionary-German.jsonl`（英文版德语切片）**当前不在盘上**
   （见 data/MANIFEST.md）—— 脚本会如实报「文件不存在」，要不要重下由 DE_PLAN 决定。

跑：  cd de && python3 probes/count_slices.py            （全量，约 20–40 分钟）
      cd de && python3 probes/count_slices.py --quick     （每源前 20 万行，看形状，约 1 分钟）
"""
import argparse
import gzip
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import paths                                     # noqa: E402

D = paths.DUMPS

# (键, 文件, 是否需要按 lang_code 过滤, 用途)
#  🔴 "需要过滤" = 该文件是**多语种整包**；per-language 切片已经切好，不用再过滤。
SOURCES = [
    ("en", D / "kaikki.org-dictionary-German.jsonl", False, "结构基准（建库主源）"),
    ("de", D / "dewiktionary.jsonl.gz",             True,  "🔴 德语原文释义/音标/例句/录音的唯一来源"),
    ("fr", D / "frwiktionary.jsonl.gz",             True,  "跨版收割（fr 版对外语词最慷慨）"),
    ("es", D / "eswiktionary.jsonl.gz",             True,  "跨版收割"),
    ("it", D / "itwiktionary.jsonl.gz",             True,  "跨版收割"),
    ("pt", D / "ptwiktionary.jsonl.gz",             True,  "跨版收割"),
    ("zh", D / "zhwiktionary.jsonl.gz",             True,  "人工中文 / 盲测真值"),
]

# 德语的地区变体标记（德/奥/瑞）—— 只认标记，不猜；两边都不匹配的记「未标」。
AT = {"Austria", "Austrian", "Österreich", "österreichisch", "Wien", "autrichien"}
CH = {"Switzerland", "Swiss", "Schweiz", "schweizerisch", "Zürich", "suisse"}


def _region(s):
    marks = list(s.get("tags") or []) + list(s.get("raw_tags") or [])
    if not marks:
        return None
    blob = " | ".join(marks)
    hit_at = any(k in blob for k in AT)
    hit_ch = any(k in blob for k in CH)
    if hit_at and not hit_ch:
        return "at"
    if hit_ch and not hit_at:
        return "ch"
    return None


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
            if need_filter and e.get("lang_code") != "de":
                continue
            c["德语条目"] += 1
            w = e.get("word")
            if w:
                words.add(w)
            senses = e.get("senses") or []
            c["义项"] += len(senses)
            for s in senses:
                if s.get("form_of") or s.get("alt_of"):
                    c["义项_指针"] += 1
                elif s.get("glosses"):
                    c["义项_有释义"] += 1
                c["例句条数"] += len(s.get("examples") or [])
            if not any((s.get("form_of") or s.get("alt_of")) for s in senses) and w:
                lemmas.add(w)

            sounds = e.get("sounds") or []
            if any(s.get("ipa") for s in sounds):
                c["带音标条目"] += 1
                c["音标条数"] += sum(1 for s in sounds if s.get("ipa"))
            for s in sounds:
                if not s.get("ipa"):
                    continue
                r = _region(s)
                c["音标_奥" if r == "at" else "音标_瑞" if r == "ch" else "音标_未标地区"] += 1
                # X-SAMPA 冒充 IPA：fr 150 条 / pt 132 条，灌库前必须排除，这里先数
                if any("SAMPA" in m for m in
                       list(s.get("tags") or []) + list(s.get("raw_tags") or [])):
                    c["🔴标着SAMPA的"] += 1

            if any(s.get(k) for s in sounds for k in ("mp3_url", "ogg_url", "wav_url")):
                c["带录音条目"] += 1
                c["录音条数"] += sum(1 for s in sounds
                                     for k in ("mp3_url", "ogg_url", "wav_url") if s.get(k))
            if any(s.get("examples") for s in senses):
                c["带例句条目"] += 1

            # 🔴🔴 de 特有①：forms 数组里带不带 ipa
            forms = e.get("forms") or []
            if forms:
                c["带 forms 条目"] += 1
                c["forms 条数"] += len(forms)
                n = sum(1 for fm in forms if fm.get("ipa"))
                if n:
                    c["🔴forms带ipa的条目"] += 1
                    c["🔴forms带ipa条数"] += n
                # de 特有③：属格/复数著录形在不在 forms 里（决定阶段 2 怎么建变形层）
                for fm in forms:
                    t = " ".join(fm.get("tags") or []) + " " + " ".join(fm.get("raw_tags") or [])
                    if "genitive" in t or "Genitiv" in t:
                        c["forms_属格"] += 1
                    if "plural" in t or "Plural" in t:
                        c["forms_复数"] += 1
            # 关系（阶段 6）：词级与义项级两处都要数（es 只取词级漏了 20,193 条）
            for k in ("synonyms", "antonyms", "derived", "related", "hypernyms", "hyponyms"):
                c["关系_词级"] += len(e.get(k) or [])
                for s in senses:
                    c["关系_义项级"] += len(s.get(k) or [])
    c["不同词形"] = len(words)
    c["非指针词形"] = len(lemmas)
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only", help="只扫这一个源的键（en/de/fr/es/it/pt/zh）")
    a = ap.parse_args()
    limit = 200000 if a.quick else None

    print("%-4s %11s %11s %11s %10s %10s %9s %9s %9s" %
          ("源", "行", "德语条目", "义项", "其中指针", "真释义", "带音标", "带录音", "带例句"))
    print("-" * 96)
    for key, p, filt, why in SOURCES:
        if a.only and key != a.only:
            continue
        if not p.exists():
            print("%-4s 🔴 文件不存在：%s" % (key, p))
            print("     用途：%s" % why)
            sys.stdout.flush()
            continue
        c = scan(p, filt, limit)
        print("%-4s %11s %11s %11s %10s %10s %9s %9s %9s%s" % (
            key, f'{c["行"]:,}', f'{c["德语条目"]:,}', f'{c["义项"]:,}',
            f'{c["义项_指针"]:,}', f'{c["义项_有释义"]:,}',
            f'{c["带音标条目"]:,}', f'{c["带录音条目"]:,}', f'{c["带例句条目"]:,}',
            "  (截断)" if c.get("截断") else ""))
        print("     用途：%s" % why)
        print("     词形 %s（非指针 %s）| 音标 %s 条 = 奥 %s / 瑞 %s / 未标 %s | 录音 %s 条 | 例句 %s 条" % (
            f'{c["不同词形"]:,}', f'{c["非指针词形"]:,}', f'{c["音标条数"]:,}',
            f'{c["音标_奥"]:,}', f'{c["音标_瑞"]:,}', f'{c["音标_未标地区"]:,}',
            f'{c["录音条数"]:,}', f'{c["例句条数"]:,}'))
        print("     🔴 forms：%s 个条目带 forms（共 %s 条）；**其中带 ipa 的条目 %s 个 / %s 条**；属格 %s / 复数 %s" % (
            f'{c["带 forms 条目"]:,}', f'{c["forms 条数"]:,}',
            f'{c["🔴forms带ipa的条目"]:,}', f'{c["🔴forms带ipa条数"]:,}',
            f'{c["forms_属格"]:,}', f'{c["forms_复数"]:,}'))
        print("     关系：词级 %s / 义项级 %s | SAMPA 冒充 %s | 坏行 %s" % (
            f'{c["关系_词级"]:,}', f'{c["关系_义项级"]:,}',
            f'{c["🔴标着SAMPA的"]:,}', f'{c.get("坏行", 0):,}'))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
