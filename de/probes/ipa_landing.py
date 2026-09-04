#!/usr/bin/env python3
"""阶段 -1 落点实测 —— 各版的德语音标，**落到我们库里**能补多少。2026-08-31（拷自 pt）。

═══ 为什么必须单独有这一步 ═══
`count_slices.py` 报的是**源头数**：德语版有 963,570 个德语词形、1,058,543 条音标。
那个数回答不了唯一要紧的问题：**其中有多少个正好是我们缺音标的那 239,513 个词形。**
（de 的缺口 100% 在变形层：lemma 层开工当天就 99.8% 有音标。）

🔴 `[[measure-landing-not-source]]` 是本项目最高频的自伤错误（两天十次）：
   「kaikki 有 97.5% tags」≠「我们丢了语域」；译文分歧 26.1%→5.5%→4.9% 三个数全是假的。
   ⇒ 新数字先假设我的度量错了。

本脚本回答四个问题，每个都分 lemma / 变形两层（de 的缺口同样全在变形层）：
  ① 这一版的词形，有多少**在我们 dict 里**
  ② 其中有多少**我们现在缺音标**   ← 这就是"能补多少"的落点数
  ③ 有多少**根本不在我们库里**     ← 阶段 3 收词的残差
  ④ 各版之间重叠多少，**并集**能补多少 ← 决定 G2P 造不造的那个数

═══ 判据写死在这里，不在读数时临时想 ═══
🔴 **词形匹配只认逐字节相等**。这一条在德语上比在别的语种更硬：
   **德语名词首字母大写是正字法硬规则**，`Sie`(您) / `sie`(她)、`Band`(卷/乐队) / `band`(绑)
   是**不同的词**，折叠掉就是把两个词的音标混成一个。库里实测有 7,946 组词形共享同一个
   小写形，两边各占一行 —— 那不是重复，是德语。
   ⇒ 「折叠多匹配」那一列在 pt 上是"顺手能多补的"，**在 de 上是警戒线**：
     它要是很大，说明我在拿一门语言的直觉套另一门（`[[criteria-narrower-than-you-think]]`）。
⚠️ 德语的 ä/ö/ü/ß 是**字母不是变音记号**：`schon`(已经) / `schön`(美丽) 是两个词。
   `word_norm` 那一列做 ä→ae 的归一是**为了检索**，不能拿来当匹配键。这里只用原字符串。

⚠️ 本脚本**只读**，不写库、不下载。

跑：  python3 probes/ipa_landing.py          （在 de/ 目录下，约 20–35 分钟）
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
    ("en", D / "kaikki.org-dictionary-German.jsonl", False),
    ("de", D / "dewiktionary.jsonl.gz",              True),
    ("fr", D / "frwiktionary.jsonl.gz",              True),
    ("zh", D / "zhwiktionary.jsonl.gz",              True),
    ("it", D / "itwiktionary.jsonl.gz",              True),
    ("es", D / "eswiktionary.jsonl.gz",              True),
    ("pt", D / "ptwiktionary.jsonl.gz",              True),
]


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def load_db():
    """→ (有音标的词形, 缺音标的词形, 缺音标且**页面上只是变形**的, 缺音标且是空白页的)

    ⚠️ de 是**单读音**语言，只有 `ipa` 一列 —— pt 那版要判两列都空才算缺口，
       这里不需要（实测德语版带奥/瑞地区标记的音标只占 0.13%，不设分区列）。

    🔴 **2026-09-03 换判据：分层不许再用 `dict.is_lemma`。**
       `is_lemma` 是**七月建库那版**的列，此后再没被写过 —— 它恒等于 89,709，
       而阶段 1.5a/2a 之后有 **124,291 个词形有真义项却标着 `is_lemma=0`**。
       照旧判据跑，探针会把「读者点进去有释义、却没有音标」的那 12 万条
       整个算进"变形层噪声"，而那正是唯一该先补的一批。
       ⇒ 判据换成 v3 的事实：**页面上是什么**（有真义项／只是变形／空白页），
         那也正是"补了之后读者看不看得见"的判据。
    ⚠️ **空白页单独一层、有意不补**：页面上除了一个音标什么都没有，
       补了反而更像缺陷（`PITFALLS` D1 同理）。它要单独报数，不能混进缺口总数里
       让人以为"还差这么多"。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have, miss, miss_infl, miss_blank = set(), set(), set(), set()
    q = ("SELECT d.word, TRIM(COALESCE(d.ipa,''))<>'' AS has,"
         "       EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id) AS has_sense,"
         "       EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id) AS has_infl"
         "  FROM dict d")
    for w, has, has_sense, has_infl in con.execute(q):
        if has:
            have.add(w)
            continue
        miss.add(w)
        if has_sense:
            pass                        # 有真义项 —— 这就是该先补的那层
        elif has_infl:
            miss_infl.add(w)
        else:
            miss_blank.add(w)
    con.close()
    return have, miss, miss_infl, miss_blank


def fold(w):
    """折叠键：NFC + casefold。**只用于"多匹配多少"这一行的对照**，不用于主判据。

    🔴 de 上这一列是**警戒线不是机会**（见文件头）：德语大小写是区别性的。
    """
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
            if need_filter and e.get("lang_code") != "de":
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

    have, miss, miss_infl, miss_blank = load_db()
    fold_miss = {fold(w): w for w in miss}
    # 🔴 **该先补的那一层**：缺音标、且页面上有真义项。读者查词唯一看得见的就是它。
    miss_sense = miss - miss_infl - miss_blank
    print("库现状：有音标 %s ／ 缺音标 %s"
          % (f"{len(have):,}", f"{len(miss):,}"))
    print("   缺口按**页面上是什么**分三层（判据是有没有真义项，不是 is_lemma）：")
    print("     ⭐ 有真义项（读者看得见）  %s   ← 这一层是目标"
          % f"{len(miss_sense):,}")
    print("        只是变形               %s" % f"{len(miss_infl):,}")
    print("        空白页（有意不补）      %s" % f"{len(miss_blank):,}")
    print("\n%-4s %11s %11s %11s %11s %11s %11s" %
          ("源", "带ipa词形", "①在库里", "②补缺口", "⭐补有义项", "③库里没有", "折叠多匹配"))
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
        fills_sense = words & miss_sense
        newly = words - have - miss
        extra = len({fold(w) for w in newly} & set(fold_miss)) # 折叠后才对上的
        union |= fills
        per[key] = fills
        print("%-4s %11s %11s %11s %11s %11s %11s" % (
            key, f"{len(words):,}", f"{len(in_db):,}", f"{len(fills):,}",
            f"{len(fills_sense):,}", f"{len(newly):,}", f"{extra:,}"))
        sys.stdout.flush()

    print("-" * 84)
    print("%-4s %11s %11s %11s %11s" %
          ("并集", "", "", f"{len(union):,}", f"{len(union & miss_sense):,}"))
    us, um = len(union & miss_sense), max(len(miss_sense), 1)
    print("\n⇒ **⭐ 有真义项那一层**：缺 %s，跨版并集补 **%s（%.1f%%）**，剩 %s。"
          % (f"{len(miss_sense):,}", f"{us:,}", 100.0 * us / um, f"{len(miss_sense)-us:,}"))
    print("   全部缺口（含变形层与空白页）：缺 %s，补 %s（%.1f%%）—— **这个数不该拿去排工期**，"
          % (f"{len(miss):,}", f"{len(union):,}", 100.0 * len(union) / max(len(miss), 1)))
    print("   它把读者看不见的两层也算了进来。")

    print("\n── 各版的独有贡献（去掉别版已给的，看谁不可替代）──")
    for key in per:
        others = set().union(*[v for k, v in per.items() if k != key]) if len(per) > 1 else set()
        print("   %-4s 独有 %s" % (key, f"{len(per[key] - others):,}"))


if __name__ == "__main__":
    main()
