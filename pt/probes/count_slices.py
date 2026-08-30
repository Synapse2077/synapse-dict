#!/usr/bin/env python3
"""阶段 -1 取数核对 —— 每个源实测：条目数 / 葡语条目 / 义项数 / 各字段贡献。2026-08-29。

═══ 为什么必须实测，不能抄索引页、更不能凭印象 ═══
`PT_PLAN` 阶段 -1 的判据是「每个源负责哪些字段，由**数出来的数**支撑」。
fr 那轮这一步逮到三处自伤，**一个都不是读代码看出来的**：
  · 法语原文释义 210 万 → 真值 **697,814**（73.7% 是变形指针）
  · 中文版可用中文 151,537 → **27,440**（78.8% 是指针）
  · tr/el/ru 三版的"真释义"数全是假象 —— 那三版根本不标变形
⇒ 判据必须是 kaikki 的**结构化字段** `form_of` / `alt_of`，不是按释义文本猜前缀。
  （it 上同一个坑：意语原文释义真值 105,474 而非 714,223，**阶段 1.5 的 3–4 天工期
   就是按那个虚数排的**。）

⚠️ `form_of` 与 `alt_of` 这里都算"非真释义"，但**建库时绝不能混为一谈** ——
   es 把两者当同一回事，造出「Méjico 的 阳性」这类编造标签 3,890 个（`PITFALLS` B 组）。
   本脚本只计数，混着数无害；`build.py` 里必须分开。

═══ 🔴 pt 特有的两列：`forms 带 ipa` 与 `巴葡/欧葡` ═══
pt 这一门唯一确定的难点是**变形层 32.7 万词形没有音标**（`PT_PLAN` §三）。
`FRAMEWORK.md:446` 实测过"pt 的 forms 不带 ipa"，但**那只量了英文版**——
葡语版 / 法语版 / 西语版**从来没有人查过这一项**。如果其中任何一版的 forms 带 ipa，
fr 那招（从 lemma 的 forms 收割变位形音标，一次补 387,826 条）在 pt 上就重新成立，
G2P 那个决策也就不用做了。⇒ **这是本次扫描最值钱的一列。**

同理 `ipa_br` / `ipa_pt` 的分布：跨版收割已知只能补欧葡（`[[cross-edition-harvest]]`），
但那也是**印象不是实测**。这里按 `sounds[].tags` 里的地区标记分开数。

⚠️ 本脚本**不下载任何东西**，只扫本地已有的 7 个源。
   需要下载的 per-language 切片留给第二步，由本次结果决定值不值得下。

跑：  python3 probes/count_slices.py            （在 pt/ 目录下，约 15–25 分钟，1.87 GB）
      python3 probes/count_slices.py --quick     （每源只扫前 20 万行，看形状用，约 1 分钟）
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
#  ⚠️ 没有"索引页声称义项数"这一列 —— fr 那轮的数字是从 kaikki 索引页抄的，
#     需要联网。pt 这一步先不联网，**差多少就报多少**的交叉核对留给第二步。
SOURCES = [
    ("en", D / "kaikki.org-dictionary-Portuguese.jsonl", False, "结构基准（现建库主源）"),
    ("pt", D / "ptwiktionary.jsonl.gz",                  True,  "🔴 葡语原文释义的唯一来源 + 音标"),
    ("fr", D / "frwiktionary.jsonl.gz",                  True,  "跨版收割（已知能补约 18.0 万欧葡音标）"),
    ("es", D / "eswiktionary.jsonl.gz",                  True,  "🔴 西伊比利亚近亲，从没量过"),
    ("de", D / "dewiktionary.jsonl.gz",                  True,  "跨版收割（录音）"),
    ("zh", D / "zhwiktionary.jsonl.gz",                  True,  "人工中文 / 盲测真值"),
    ("it", D / "itwiktionary.jsonl.gz",                  True,  "跨版收割"),
]

# 地区标记：哪些串算巴葡 / 欧葡。
# 🔴 判据写死在这里，不在读数时临时想 —— 而且**只认标记，不猜**：
#    两边都不匹配的记 `未标地区`，如实报，不硬塞进任何一边。
#
# 🔴 2026-08-29 **第一版这个判据窄了两层，当场被数据打回**（`[[ledger-numbers-lie]]` 同形状）：
#    ① 只查 `sounds[].tags` —— 而法语版/葡语版把地区写在 **`raw_tags`** 里，`tags` 恒空；
#    ② 只认英文串 —— 法语版写 `Brésil`/`Portugal`，葡语版写**巴西方言名**
#       `Carioca`/`Paulistana`/`Caipira`/`Gaúcha`/`Paranaense`，一个英文串都没有。
#    第一版据此报「法语版一条都没标地区」，真值是 8,133 条（1.0%）。
#    ⚠️ 结论方向没变（99% 确实没标），但**那是碰巧对，不是判据对**。
#
# ⚠️ 葡语版的方言名是**巴西内部方言**，不是 br/pt 二分 —— 归进 BR 是有损的，
#    真正怎么落表由 `PT_PLAN` §四.3 决定，这里只负责如实计数。
BR = {"Brazil", "Brazilian", "Brazilian Portuguese", "brasileiro", "Brasil", "Brésil",
      "Carioca", "Paulistana", "Paulista", "Caipira", "Gaúcha", "Paranaense",
      "São Paulo", "Rio de Janeiro", "Região Sul", "Sul"}
PT = {"Portugal", "European Portuguese", "European", "Europe", "português europeu",
      "Porto", "Coimbra", "Braga", "Lisbonne", "Lisboa", "Alentejo"}


def _region(s):
    """→ 'br' / 'pt' / None。**同时看 `tags` 和 `raw_tags`**，并对
    `Porto (Portugal)` 这种复合串做子串包含判断（判据只在这一个函数里）。"""
    marks = list(s.get("tags") or []) + list(s.get("raw_tags") or [])
    if not marks:
        return None
    blob = " | ".join(marks)
    hit_pt = any(k in blob for k in PT)
    hit_br = any(k in blob for k in BR)
    if hit_br and not hit_pt:
        return "br"
    if hit_pt and not hit_br:
        return "pt"
    return None                      # 两边都命中 or 都没命中 —— 如实记「未标」，不猜


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
            if need_filter and e.get("lang_code") != "pt":
                continue
            c["葡语条目"] += 1
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
            # 🔴 pt 特有：按地区标记分开数（判据写死在 BR/PT 两个集合里）
            for s in sounds:
                if not s.get("ipa"):
                    continue
                r = _region(s)
                c["音标_巴葡" if r == "br" else "音标_欧葡" if r == "pt" else "音标_未标地区"] += 1
                # 🔴 X-SAMPA 冒充 IPA：葡语版实测 132 条标着 `SAMPA`（fr 那轮同形状 150 条）。
                #    灌库前必须排除，这里先数出来。
                if any("SAMPA" in m for m in
                       list(s.get("tags") or []) + list(s.get("raw_tags") or [])):
                    c["🔴标着SAMPA的"] += 1

            if any(s.get(k) for s in sounds for k in ("mp3_url", "ogg_url", "wav_url")):
                c["带录音条目"] += 1
                c["录音条数"] += sum(1 for s in sounds
                                     for k in ("mp3_url", "ogg_url", "wav_url") if s.get(k))
            if any(s.get("examples") for s in senses):
                c["带例句条目"] += 1

            # 🔴🔴 本次扫描最值钱的一列：forms 数组里带不带 ipa。
            #     带 ⇒ fr 那招（从 lemma 收割变位形音标）在 pt 上重新成立。
            forms = e.get("forms") or []
            if forms:
                c["带 forms 条目"] += 1
                c["forms 条数"] += len(forms)
                n = sum(1 for fm in forms if fm.get("ipa"))
                if n:
                    c["🔴forms带ipa的条目"] += 1
                    c["🔴forms带ipa条数"] += n
    c["不同词形"] = len(words)
    c["非指针词形"] = len(lemmas)
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    limit = 200000 if a.quick else None

    print("%-4s %11s %11s %11s %10s %10s %9s %9s %9s" %
          ("源", "行", "葡语条目", "义项", "其中指针", "真释义", "带音标", "带录音", "带例句"))
    print("-" * 96)
    for key, p, filt, why in SOURCES:
        if not p.exists():
            print("%-4s 🔴 文件不存在：%s" % (key, p))
            continue
        c = scan(p, filt, limit)
        print("%-4s %11s %11s %11s %10s %10s %9s %9s %9s%s" % (
            key, f'{c["行"]:,}', f'{c["葡语条目"]:,}', f'{c["义项"]:,}',
            f'{c["义项_指针"]:,}', f'{c["义项_有释义"]:,}',
            f'{c["带音标条目"]:,}', f'{c["带录音条目"]:,}', f'{c["带例句条目"]:,}',
            "  (截断)" if c.get("截断") else ""))
        print("     用途：%s" % why)
        print("     词形 %s（非指针 %s）| 音标 %s 条 = 巴葡 %s / 欧葡 %s / 未标 %s | 录音 %s 条" % (
            f'{c["不同词形"]:,}', f'{c["非指针词形"]:,}', f'{c["音标条数"]:,}',
            f'{c["音标_巴葡"]:,}', f'{c["音标_欧葡"]:,}', f'{c["音标_未标地区"]:,}',
            f'{c["录音条数"]:,}'))
        print("     🔴 forms：%s 个条目带 forms（共 %s 条）；**其中带 ipa 的条目 %s 个 / %s 条**" % (
            f'{c["带 forms 条目"]:,}', f'{c["forms 条数"]:,}',
            f'{c["🔴forms带ipa的条目"]:,}', f'{c["🔴forms带ipa条数"]:,}'))
        if c.get("坏行"):
            print("     ⚠️ 坏行 %s" % f'{c["坏行"]:,}')
        sys.stdout.flush()


if __name__ == "__main__":
    main()
