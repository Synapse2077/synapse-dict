#!/usr/bin/env python3
"""阶段 -1 落点实测 —— 各版的葡语音标，**落到我们库里**能补多少。2026-08-29。

═══ 为什么必须单独有这一步 ═══
`count_slices.py` 报的是**源头数**：法语版有 296,658 个葡语词形、811,074 条音标。
那个数回答不了唯一要紧的问题：**其中有多少个正好是我们缺音标的那 326,511 个词形。**

🔴 `[[measure-landing-not-source]]` 是本项目最高频的自伤错误（两天十次）：
   「kaikki 有 97.5% tags」≠「我们丢了语域」；译文分歧 26.1%→5.5%→4.9% 三个数全是假的。
   ⇒ 新数字先假设我的度量错了。

本脚本回答四个问题，每个都分 lemma / 变形两层（pt 的缺口全在变形层）：
  ① 这一版的词形，有多少**在我们 dict 里**
  ② 其中有多少**我们现在缺音标**   ← 这就是"能补多少"的落点数
  ③ 有多少**根本不在我们库里**     ← 阶段 3 收词的残差
  ④ 各版之间重叠多少，**并集**能补多少 ← 决定 G2P 造不造的那个数

═══ 判据写死在这里，不在读数时临时想 ═══
🔴 **词形匹配只认逐字节相等**。大小写折叠会把专名的属性并进小写词形
   （`[[case-folding-contaminates-columns]]`：`usa` 被显示成【专名】），这里**不折叠**，
   但**单独报**折叠后能多匹配多少 —— 差多少就报多少，由后面的阶段决定要不要收。
⚠️ 撇号/重音符约定各版不同（fr 那轮阶段 3b-0 实测我们库直撇 2,429 : 弯撇 3，
   法文版 23 : 20,198）。这里同样**只报不改**，把差额单列一行。

⚠️ 本脚本**只读**，不写库、不下载。

跑：  python3 probes/ipa_landing.py          （在 pt/ 目录下，约 15–25 分钟）
      python3 probes/ipa_landing.py --quick   （每源前 20 万行）
"""
import argparse
import gzip
import json
import pathlib
import sqlite3
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import paths                                     # noqa: E402

D = paths.DUMPS
SOURCES = [
    ("en", D / "kaikki.org-dictionary-Portuguese.jsonl", False),
    ("pt", D / "ptwiktionary.jsonl.gz",                  True),
    ("fr", D / "frwiktionary.jsonl.gz",                  True),
    ("es", D / "eswiktionary.jsonl.gz",                  True),
    ("de", D / "dewiktionary.jsonl.gz",                  True),
    ("zh", D / "zhwiktionary.jsonl.gz",                  True),
    ("it", D / "itwiktionary.jsonl.gz",                  True),
]


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def load_db():
    """→ (有音标的词形, 缺音标的词形, 缺音标且是变形的, 折叠索引)

    🔴 「缺音标」＝ `ipa_br` 和 `ipa_pt` **都**空。补上任何一种都算补上了一半，
       但两种都没有的才是真缺口 —— 判据取 OR 而不是 AND，会把
       「只有欧葡、缺巴葡」的 8 万多行算成"已有"，那是另一个问题（收尾单 C3）。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have, miss, miss_infl = set(), set(), set()
    q = ("SELECT word, is_lemma,"
         " (TRIM(COALESCE(ipa_br,''))<>'' OR TRIM(COALESCE(ipa_pt,''))<>'') AS has"
         " FROM dict")
    for w, is_lemma, has in con.execute(q):
        if has:
            have.add(w)
        else:
            miss.add(w)
            if not is_lemma:
                miss_infl.add(w)
    con.close()
    return have, miss, miss_infl


def fold(w):
    """折叠键：NFC + casefold。**只用于"多匹配多少"这一行的对照**，不用于主判据。"""
    return unicodedata.normalize("NFC", w).casefold()


def scan(p, need_filter, limit=None):
    """→ {词形: 是不是变形}（只收**带 ipa** 的条目）"""
    out = {}
    with opener(p) as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            try:
                e = json.loads(line)
            except Exception:
                continue
            if need_filter and e.get("lang_code") != "pt":
                continue
            if not any(s.get("ipa") for s in (e.get("sounds") or [])):
                continue
            w = e.get("word")
            if not w:
                continue
            senses = e.get("senses") or []
            is_infl = bool(senses) and all(
                (s.get("form_of") or s.get("alt_of")) for s in senses)
            # 同一词形多个 pos 块（`PITFALLS` B1）：只要有一块是真义项就不算纯变形
            out[w] = out.get(w, True) and is_infl
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    limit = 200000 if a.quick else None

    have, miss, miss_infl = load_db()
    fold_miss = {fold(w): w for w in miss}
    print("库现状：有音标词形 %s ／ 缺音标 %s（其中变形 %s）"
          % (f"{len(have):,}", f"{len(miss):,}", f"{len(miss_infl):,}"))
    print("\n%-4s %11s %11s %11s %11s %11s %11s" %
          ("源", "带ipa词形", "①在库里", "②补缺口", "其中变形", "③库里没有", "折叠多匹配"))
    print("-" * 84)

    union = set()
    per = {}
    for key, p, filt in SOURCES:
        if not p.exists():
            print("%-4s 🔴 文件不存在" % key)
            continue
        got = scan(p, filt, limit)
        words = set(got)
        in_db = words & (have | miss)
        fills = words & miss
        fills_infl = words & miss_infl
        newly = words - have - miss
        extra = len({fold(w) for w in newly} & set(fold_miss)) # 折叠后才对上的
        union |= fills
        per[key] = fills
        print("%-4s %11s %11s %11s %11s %11s %11s" % (
            key, f"{len(words):,}", f"{len(in_db):,}", f"{len(fills):,}",
            f"{len(fills_infl):,}", f"{len(newly):,}", f"{extra:,}"))
        sys.stdout.flush()

    print("-" * 84)
    print("%-4s %11s %11s %11s %11s" %
          ("并集", "", "", f"{len(union):,}", f"{len(union & miss_infl):,}"))
    print("\n⇒ 缺音标 %s 个词形，跨版并集能补 **%s 个（%.1f%%）**，剩 %s 个只能靠 G2P 或留空。"
          % (f"{len(miss):,}", f"{len(union):,}", 100.0 * len(union) / max(len(miss), 1),
             f"{len(miss) - len(union):,}"))

    print("\n── 各版的独有贡献（去掉别版已给的，看谁不可替代）──")
    for key in per:
        others = set().union(*[v for k, v in per.items() if k != key]) if len(per) > 1 else set()
        print("   %-4s 独有 %s" % (key, f"{len(per[key] - others):,}"))


if __name__ == "__main__":
    main()
