#!/usr/bin/env python3
"""阶段 -1 词汇残差 —— 各版还能给多少**我们没有的**葡语词形，以及收词要花多少钱。2026-08-29。

═══ 判据（照 fr 那份，逐条有来历）═══

**① 顺序无关的差集。** 不问"按某个顺序依次收，每版边际新增多少"——那个数依赖顺序，
   换个顺序两版的数字会互换。只问 `residual_x = V_x \\ 现有库`，各版独立可比。

**② 🔴 三类「假新词」必须单独量**：只差大小写 / 只差重音符 / 只差撇号。
   这三类在落库归一后会塌掉，raw 差集会把它们当新词
   （`[[measure-landing-not-source]]`；fr 阶段 3b-0 实测撇号约定完全相反：
   我们库直撇 2,429 : 弯撇 3，法文版 23 : 20,198）。

**③ 残差是上界不是真值。** 这是 dump 里的**原始字符串集**，落库还要过解析/归一/去重。
   fr 那轮预测上界 36,007、实测落点 35,336（98.1%）—— 上界是可信的，但**报的时候要说它是上界**。

**④ 变形词形与真词头分开数。** 变形不送模型翻译（`infl` 确定性生成），
   花钱的只有真词头 —— 判据用 kaikki 的结构化字段 `form_of`/`alt_of`，不猜前缀。

**⑤ 🔴🔴 本脚本第一版只数顶层 `word`，漏掉了 `forms` 数组里的词形 —— 2026-08-29 被用户问倒。**
   用户问「pt 词汇量没过百万，比 fr/es/it 少很多，正常吗，还是漏了重要来源」。
   查下来是**判据比它要描述的东西窄**（`[[criteria-narrower-than-you-think]]` 第 N 次）：
   · **法语维基给每个屈折形式单独建页** ⇒ 顶层 `word` 就抓得到 `mangeraient`；
   · **葡语维基不建那些页** ⇒ 变位形只活在词条内部的 `forms` 变位表里。
   实测每条目的 forms 条数：葡语版 **51.9**（＝完整动词变位表，葡语还多出
   **人称不定式**和**将来虚拟式**两个西/法都没有的时态）、英文版 9.1。
   ⇒ 第一版据此报「英文版实际能补 0 个新词形、已经榨干」——
   **真值是它的 forms 里藏着 94,000 个我们没有的词形。**
   ⚠️ 教训不是"记得数 forms"，是：**同一个判据在 A 语言上成立不等于在 B 语言上成立**，
      而我是从 fr 抄的这个脚本。

**⑥ 🔴 wordfreq 当尺子的判据只能是 `tokenize(w)==[w.lower()]`**
   （`[[wordfreq-ruler-traps]]`：多词是拼的 / **词缀被静默剥掉再查**（`a-`→7.36）/
   大小写折叠 / 词形非词元 —— 四个陷阱）。

⚠️ 本脚本只读，不写库、不下载。

跑：  python3 probes/residual.py           （在 pt/ 目录下，约 20–30 分钟）
      python3 probes/residual.py --quick    （每源前 20 万行）
"""
import argparse
import gzip
import json
import pathlib
import sqlite3
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "pipeline"))
import paths                                     # noqa: E402

D = paths.DUMPS
SOURCES = [
    ("en", D / "kaikki.org-dictionary-Portuguese.jsonl", False),
    ("pt", D / "ptwiktionary.jsonl.gz",                  True),
    ("fr", D / "frwiktionary.jsonl.gz",                  True),
    ("zh", D / "zhwiktionary.jsonl.gz",                  True),
    ("de", D / "dewiktionary.jsonl.gz",                  True),
    ("es", D / "eswiktionary.jsonl.gz",                  True),
    ("it", D / "itwiktionary.jsonl.gz",                  True),
]


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def strip_accents(w):
    return "".join(c for c in unicodedata.normalize("NFD", w)
                   if unicodedata.category(c) != "Mn")


def strip_apos(w):
    return w.replace("’", "'").replace("ʼ", "'")


# 🔴 2026-08-29 **判据只许一份：直接 import 收词脚本那一份，不在这里手抄。**
#
#    起因：本文件第一版自己写了一套宽的 `forms` 过滤（只挡三个 tag），
#    据此报「跨版并集上界 643,117、收完约 1,054,919」。而 3b 真正收词时，
#    抽样反验逼出了收窄的判据（法语版代词单元格 238,556 + 法语时态名表头 511,000+
#    + 音节划分 2,041 全是垃圾）⇒ **实际落点 769,012，比"上界"少 28.7 万。**
#
#    那个差不是"上界本来就偏高"（fr 那轮上界 36,007 → 落点 35,336 = 98.1%，很准），
#    是**两把尺子不一样**：探针宽、收词窄，所以"上界"里混着 `eu solidificarei` 和 `Indicatif`。
#    ⇒ `[[regex-alternation-order]]` 那条：抽了常量却在另一文件又手抄一份窄的，坏了 43 条。
#      这次是反过来 —— 手抄了一份**宽**的，于是预测多报了 40%。
from intake_edition_words import _real_forms   # noqa: E402


def scan(p, need_filter, limit=None, edition=None):
    """→ {词形: 是不是纯变形}

    🔴 **同时收顶层 `word` 和 `forms` 数组**（见文件头 ⑤）。
       只收顶层在 fr 上够用（法语维基给每个屈折形式建页），在 pt 上**漏掉整个变位层**
       —— 葡语维基不建那些页，变位形只活在词条内部的变位表里。
    """
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
            w = e.get("word")
            if not w:
                continue
            senses = e.get("senses") or []
            # 同一词形的每个 pos 块是独立一行（`PITFALLS` B1）：
            # 只要有**一块**是真义项，这个词形就不是纯变形
            is_infl = bool(senses) and all(
                (s.get("form_of") or s.get("alt_of")) for s in senses)
            out[w] = out.get(w, True) and is_infl
            # 变位表里的形式**按定义就是变形**；但如果它在别处是词头，
            # 上面那行的 False 不能被这里覆盖掉 ⇒ 用 setdefault 而不是赋值。
            for fm in (e.get("forms") or []):
                for x in _real_forms(fm, edition):
                    out.setdefault(x, True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    limit = 200000 if a.quick else None

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    base = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()
    base_fold = {w.casefold() for w in base}
    base_acc = {strip_accents(w) for w in base}
    base_apo = {strip_apos(w) for w in base}
    print("现有库词形 %s" % f"{len(base):,}")

    print("\n%-4s %11s %11s %11s %11s %10s %10s %10s" %
          ("源", "词形", "🔴残差", "其中真词头", "其中变形", "假·大小写", "假·重音符", "假·撇号"))
    print("-" * 84)

    allw = {}
    per = {}
    for key, p, filt in SOURCES:
        if not p.exists():
            print("%-4s 🔴 文件不存在" % key)
            continue
        got = scan(p, filt, limit, key)
        for w, isinf in got.items():
            allw[w] = allw.get(w, True) and isinf
        res = {w: i for w, i in got.items() if w not in base}
        heads = [w for w, i in res.items() if not i]
        infl = [w for w, i in res.items() if i]
        fake_c = sum(1 for w in res if w.casefold() in base_fold)
        fake_a = sum(1 for w in res if strip_accents(w) in base_acc)
        fake_p = sum(1 for w in res if strip_apos(w) in base_apo)
        per[key] = set(res)
        print("%-4s %11s %11s %11s %11s %10s %10s %10s" % (
            key, f"{len(got):,}", f"{len(res):,}", f"{len(heads):,}", f"{len(infl):,}",
            f"{fake_c:,}", f"{fake_a:,}", f"{fake_p:,}"))
        sys.stdout.flush()

    union = {w: i for w, i in allw.items() if w not in base}
    u_heads = [w for w, i in union.items() if not i]
    u_infl = [w for w, i in union.items() if i]
    print("-" * 84)
    print("%-4s %11s %11s %11s %11s" % ("并集", f"{len(allw):,}", f"{len(union):,}",
                                        f"{len(u_heads):,}", f"{len(u_infl):,}"))
    print("\n⇒ 现有 %s 词形，跨版并集**新增上界 %s**（真词头 %s ／ 变形 %s），"
          "收完约 %s 行。" % (
              f"{len(base):,}", f"{len(union):,}", f"{len(u_heads):,}", f"{len(u_infl):,}",
              f"{len(base) + len(union):,}"))
    print("   ⚠️ 这是**上界** —— dump 原始字符串集，落库还要过解析/归一/去重"
          "（fr 那轮上界 36,007 → 落点 35,336 = 98.1%）")

    print("\n── 各版独有贡献（去掉别版已给的）──")
    for key in per:
        others = set().union(*[v for k, v in per.items() if k != key]) if len(per) > 1 else set()
        print("   %-4s 独有 %s" % (key, f"{len(per[key] - others):,}"))

    # ⑤ 成本侧：新词头里有多少查得到频次（只有真词头要送模型翻译）
    try:
        from wordfreq import zipf_frequency, tokenize
    except ImportError:
        print("\n⚠️ 没装 wordfreq，跳过频次分层")
        return
    have = 0
    for w in u_heads:
        try:
            if tokenize(w, "pt") != [w.lower()]:     # 🔴 判据只能是这个（四个陷阱见文件头）
                continue
        except Exception:
            continue
        if zipf_frequency(w, "pt") > 0:
            have += 1
    print("\n── 成本侧：%s 个新词头里，wordfreq 查得到频次的 %s（%.1f%%）──"
          % (f"{len(u_heads):,}", f"{have:,}", 100.0 * have / max(len(u_heads), 1)))
    print("   ⚠️ 对照 fr：87%% 的新词头查不到频次 ⇒ 全收 vs 只收有频次的差 6.7 倍成本")


if __name__ == "__main__":
    main()
