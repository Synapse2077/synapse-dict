#!/usr/bin/env python3
"""阶段 -1 词汇残差 —— 各版还能给多少**我们没有的**德语词形。2026-08-31。

═══ 判据（照 pt/fr 那两份，逐条有来历；**德语上有两条必须反过来写**）═══

**① 顺序无关的差集。** 不问"按某个顺序依次收，每版边际新增多少"——那个数依赖顺序。
   只问 `residual_x = V_x \\ 现有库`，各版独立可比。

**② 🔴🔴 「只差大小写」「只差变音符」在德语上不是假新词，是真词。**
   pt/fr 那两份把它们当"落库归一后会塌掉的假新词"单列扣掉 —— **照抄到德语上就是错的**：

       Sie(您) / sie(她)          德语名词首字母大写是正字法硬规则
       Band(卷·乐队) / band(绑)   库里实测 7,946 组共享同一小写形，两边各占一行
       schön(美丽) / schon(已经)  ä/ö/ü 是**字母**不是变音记号
       Bär(熊) / Bar(酒吧)

   ⇒ 这两列照报，但标题写「对照」不写「假」，**并且不从残差里扣**。
     `[[criteria-narrower-than-you-think]]` 的反面：判据从另一门语言抄过来时，
     "该扣掉的噪声"可能正是这门语言的信息。

**③ 残差是上界不是真值。** dump 里的**原始字符串集**，落库还要过解析/归一/去重
   （fr 那轮上界 36,007 → 落点 35,336 = 98.1%）。报的时候必须说它是上界。

**④ 变形词形与真词头分开数。** 变形不送模型翻译（`infl` 确定性生成），
   花钱的只有真词头 —— 判据用 kaikki 的结构化字段 `form_of`/`alt_of`，不猜前缀。

**⑤ 🔴 `forms` 数组要单独数，而且它的**原始数字不能当收词量**。**
   pt 那轮的教训是"只数顶层 `word` 会漏掉整个变位层"（葡语维基不给变位形建页）。
   德语版**两头都有**：963,570 个顶层词形 + 6,305,204 条 forms。
   但 pt 那轮在 `forms` 上还栽了第二次：**法语版把主语代词写进了变位表单元格**，
   照收就是 283,136 条 `eu solidificarei` 这种假词形，靠抽样反验才拦下。
   **德语变位表必然有同一形状**（`ich mache` / `du machst` / `der Mann` / `Singular`…）。
   ⇒ 第一版跑完**抽样反验当场坐实**（`data/work/de/probe/residual_20260831.txt`）：
     德语变位表**确实**把主语代词写进单元格，而且比葡语那次更彻底 ——
     `ich abstottre` / `sie werden beteiligt haben` / `du wirst geladen haben`，
     **德语的复合时态本来就是分析式的**（werden/haben/sein + 分词），
     整格就是一个小句子，不是词形。而且第一版判据还**漏了 `er/sie/es` 这种斜杠代词串**
     （按空格切，首词是 `er/sie/es` 整体，不在代词表里）。
   ⇒ 第二版加一列 **`单词形`**：不含空格、不含 `/`、剥掉命令式的 `!`。
     **这一列才是能拿去排阶段 3 工期的数**；原始残差列保留，作为"上界的上界"如实报。
   ⚠️ 判据仍**只用于计数**，落库的清洗判据是阶段 3 的活、要配抽样反验才能定
     （pt 那轮 283,136 条假词形就是抽样反验拦下的）。

**⑥ 🔴 wordfreq 当尺子的判据只能是 `tokenize(w)==[w.lower()]`**
   （`[[wordfreq-ruler-traps]]` 四个陷阱：多词是拼的 / **词缀被静默剥掉再查** /
   大小写折叠 / 词形非词元）。

⚠️ 本脚本只读，不写库、不下载。

跑：  python3 probes/residual.py           （在 de/ 目录下，约 25–40 分钟）
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

# `forms` 单元格里明显不是词形的：占位符与表格结构标签。**只挡这两类**，
# 别的一律照收并如实报 —— 判据宽窄的裁决要等阶段 3 配抽样反验。
_JUNK_TAGS = {"table-tags", "inflection-template", "class"}
_PLACEHOLDER = {"-", "—", "–", "−", "?", "", "…", "/"}

# ⚠️ 下面这张表**不用于过滤**，只用于「风险有多大」那一行的计数。
#    德语变位/变格表的单元格常带人称代词与冠词；法语版给葡语灌过 28 万条同形状的假词形。
_DE_LEAD = {"ich", "du", "er", "sie", "es", "wir", "ihr", "Sie",
            "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
            "eines", "einer", "dass", "wenn", "Singular", "Plural", "Person"}


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def strip_accents(w):
    """只用于「对照」那一列 —— **不是**主判据（见文件头 ②）。"""
    nfd = unicodedata.normalize("NFD", w)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def is_single_form(w):
    """→ 这个字符串是不是一个**词形**（而不是一格小句子）。

    🔴 判据三条，每条都有实测来历（见文件头 ⑤）：
      · 不含空格 —— 德语复合时态是分析式的，`ich werde kooperieren` 是小句不是词形
      · 不含 `/`  —— `er/sie/es wurde transzendiert` 这类代词串，第一版按空格切漏掉了
      · 剥掉命令式的 `!`（`belle!` → `belle`）后仍非空

    ⚠️ 代价说清楚：德语确实有**可分动词分离式**（`ich komme an`）这种多词真形式，
       这条判据把它们一起排除了。理由是**查词典的单位是 `ankommen` 不是 `komme an`**，
       而且那批本来就以词元形式在库里。**不是"它们不是德语"，是"它们不是词头"。**
    """
    w = w.strip().rstrip("!").strip()
    return bool(w) and " " not in w and "/" not in w


def scan(p, need_filter, limit=None):
    """→ ({词形: 是不是纯变形}, 代词/冠词打头的单元格数, {单词形: 是不是纯变形})"""
    out, risky, single = {}, 0, {}
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
            w = e.get("word")
            if not w:
                continue
            senses = e.get("senses") or []
            # 同一词形的每个 pos 块是独立一行（`PITFALLS` B1）：
            # 只要有**一块**是真义项，这个词形就不是纯变形
            is_infl = bool(senses) and all(
                (s.get("form_of") or s.get("alt_of")) for s in senses)
            out[w] = out.get(w, True) and is_infl
            for fm in (e.get("forms") or []):
                raw = (fm.get("form") or "").strip()
                if not raw or raw in _PLACEHOLDER:
                    continue
                if _JUNK_TAGS & set(fm.get("tags") or []):
                    continue
                if raw.split()[0] in _DE_LEAD or "/" in raw.split()[0]:
                    risky += 1
                # 变位表里的形式**按定义就是变形**；但它在别处可能是词头，
                # 那行的 False 不能被覆盖 ⇒ setdefault 而不是赋值。
                out.setdefault(raw, True)
                if is_single_form(raw):
                    single.setdefault(raw.strip().rstrip("!").strip(), True)
    # 顶层词头一律算「单词形」侧的一员（它们是真词条，不是表格单元格）
    for w, isinf in out.items():
        if is_single_form(w):
            single[w] = single.get(w, True) and isinf
    return out, risky, single


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
    print("现有库词形 %s" % f"{len(base):,}")
    print("⚠️ 「对照」两列**不从残差里扣**：德语大小写与 ä/ö/ü 都是区别性的（文件头 ②）")

    print("\n%-4s %11s %11s %11s %11s %12s %11s %11s %13s" %
          ("源", "词形", "🔴残差", "其中真词头", "其中变形",
           "⭐单词形残差", "对照·大小写", "对照·变音符", "⚠️代词/冠词格"))
    print("-" * 112)

    allw, per, alls = {}, {}, {}
    for key, p, filt in SOURCES:
        if not p.exists():
            print("%-4s 🔴 文件不存在" % key)
            continue
        got, risky, single = scan(p, filt, limit)
        for w, isinf in got.items():
            allw[w] = allw.get(w, True) and isinf
        for w, isinf in single.items():
            alls[w] = alls.get(w, True) and isinf
        res = {w: i for w, i in got.items() if w not in base}
        sres = {w: i for w, i in single.items() if w not in base}
        heads = [w for w, i in res.items() if not i]
        infl = [w for w, i in res.items() if i]
        same_c = sum(1 for w in res if w.casefold() in base_fold)
        same_a = sum(1 for w in res if strip_accents(w) in base_acc)
        per[key] = set(res)
        print("%-4s %11s %11s %11s %11s %12s %11s %11s %13s" % (
            key, f"{len(got):,}", f"{len(res):,}", f"{len(heads):,}", f"{len(infl):,}",
            f"{len(sres):,}", f"{same_c:,}", f"{same_a:,}", f"{risky:,}"))
        sys.stdout.flush()

    union = {w: i for w, i in allw.items() if w not in base}
    u_heads = [w for w, i in union.items() if not i]
    u_infl = [w for w, i in union.items() if i]
    su = {w: i for w, i in alls.items() if w not in base}
    su_heads = [w for w, i in su.items() if not i]
    print("-" * 112)
    print("%-4s %11s %11s %11s %11s %12s" % ("并集", f"{len(allw):,}", f"{len(union):,}",
                                             f"{len(u_heads):,}", f"{len(u_infl):,}",
                                             f"{len(su):,}"))
    print("\n⇒ 现有 %s 词形，跨版并集**新增上界 %s**（真词头 %s ／ 变形 %s），收完约 %s 行。"
          % (f"{len(base):,}", f"{len(union):,}", f"{len(u_heads):,}", f"{len(u_infl):,}",
             f"{len(base) + len(union):,}"))
    print("   🔴 **这一行是上界的上界，不许拿去排工期** —— forms 侧混着整格小句子。")
    print("⭐ 按单词形判据（无空格/无 `/`/剥 `!`）：**新增 %s（真词头 %s ／ 变形 %s）**，"
          "收完约 %s 行 —— **这才是阶段 3 的数**。"
          % (f"{len(su):,}", f"{len(su_heads):,}", f"{len(su) - len(su_heads):,}",
             f"{len(base) + len(su):,}"))

    print("\n── 各版独有贡献（去掉别版已给的）──")
    for key in per:
        others = set().union(*[v for k, v in per.items() if k != key]) if len(per) > 1 else set()
        print("   %-4s 独有 %s" % (key, f"{len(per[key] - others):,}"))

    # ⑥ 成本侧：新词头里有多少查得到频次（只有真词头要送模型翻译）
    try:
        from wordfreq import zipf_frequency, tokenize
    except ImportError:
        print("\n⚠️ 没装 wordfreq，跳过频次分层")
        return
    buckets = {"zipf≥3（常用）": 0, "2≤zipf<3": 0, "1≤zipf<2": 0, "0<zipf<1": 0, "查不到": 0}
    for w in su_heads:
        try:
            if tokenize(w, "de") != [w.lower()]:     # 🔴 判据只能是这个（文件头 ⑥）
                buckets["查不到"] += 1
                continue
            z = zipf_frequency(w, "de")
        except Exception:
            buckets["查不到"] += 1
            continue
        k = ("zipf≥3（常用）" if z >= 3 else "2≤zipf<3" if z >= 2
             else "1≤zipf<2" if z >= 1 else "0<zipf<1" if z > 0 else "查不到")
        buckets[k] += 1
    print("\n── 新真词头（单词形判据）的频次分层（决定阶段 1.5 送不送模型）──")
    for k, v in buckets.items():
        print("   %-14s %s" % (k, f"{v:,}"))


if __name__ == "__main__":
    main()
