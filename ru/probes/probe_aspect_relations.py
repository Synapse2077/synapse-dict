#!/usr/bin/env python3
"""阶段 -1 探测④：**体（aspect）对住在哪** ／ 428 万条 `related` 的 `raw_tags` 分堆
／ 重音的形状（多重音、ё、屈折中移动）。2026-10-07。只读可重跑。

为什么要这一份：用户 2026-10-07 定了「屈折形**先收**」，于是
`RU_PLAN` §三 的决定②（重音层做到哪一级）和决定④（体对 ／ 构词词族）**要去问外审**，
而 `[[consult-two-models-on-rules]]` 的纪律是 **材料里必须带权威源的真值** ——
不带真值的咨询，两家会一致地编出具体数字（已栽四次）。

⇒ 本脚本只产出**问外审要用的真实样本与分堆**，不下结论。

用法：
    python3 ru/probes/probe_aspect_relations.py [--limit N] [--archive]
"""
import argparse
import collections
import gzip
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402

STRESS = "́"
SRC = [("en", paths.KK), ("ru", paths.EDITION), ("zh-t", paths.ZH_TRAD)]

# 🔴🔴🔴 **这张候选词表害过一次，代价是两家外审一起答错。2026-10-07 当天修。**
#
# 第一版写的是 `("perfective", "imperfective", "aspect", "вид", "сов", "несов")`，
# 注释里还写着「把源头出现的全列出来，不只找自己猜的那两个」—— **而它正是一张猜的表**。
# 结果：ru 版的完成体在 wiktextract 里标的是 **`perfect`**（不是 `perfective`），
# 于是我量到「imperfective 24,049 ／ perfective 个位数」，并把这个「不对称」写进了
# 外审材料。两家外审对一个**根本不存在的现象**各给了一套有说服力的归因
# （一家说"编辑惯例"、一家说"wiktextract 抽取遗漏"），**两个都错**。
#
#     真值（判据改成词干 perf/imperf 之后）：
#         imperfective 24,049 ／ **perfect 23,534** ／ biaspectual 1,386   ← 几乎对称
#
# ⭐ 三条教训叠在这一行上：
#   · `[[dont-say-source-lacks-what-we-skipped]]` ＝ ko 的 **K36** 第四次：
#     「某版没有 X」是从**错的值名**上读到的一个 0；
#   · `[[criterion-true-half-vouches-for-false-half]]`：我的数字字面上是真的
#     （`perfective` 确实几乎没有），它给**后半句那个错结论**背了书，还一路背到外审那里；
#   · `[[consult-two-models-on-rules]]`：**问外审之前，材料里每一句「源头没有/几乎没有 X」
#     都必须是「值域全打出来」之后得到的**，不是「我猜的候选词的命中率」。
#
# ⇒ 判据改成**两条一起跑**：① 按词干匹配（宽，认得出 perfect/perfective 两种写法）；
#   ② **无条件打印 tags 的完整值域**（§D），让下一个漏掉的值名自己显形。
ASPECT_STEMS = ("perf", "imperf", "aspect", "biaspect", "вид", "сов", "несов")


def rd(p, limit=None):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                return
            yield json.loads(line)


def pct(a, b):
    return "%6.2f%%" % (100.0 * a / b) if b else "     —"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--archive", action="store_true")
    a = ap.parse_args()
    limit = a.limit or None

    acc = {}
    for name, p in SRC:
        d = {
            "lines": 0,
            # ── 体 ──
            "aspect_where": collections.Counter(),   # 体信息出现在哪个字段
            "aspect_tagvals": collections.Counter(),
            "aspect_sample": [],
            # 🔴 完整值域（§D）—— 不过滤，这是 §A 候选词表的闸
            "all_word_tags": collections.Counter(),
            "all_forms_tags": collections.Counter(),
            "all_sense_tags": collections.Counter(),
            # ── related 的 raw_tags 分堆（428 万条到底是什么）──
            "rel_rawtags": collections.Counter(),
            "rel_tags": collections.Counter(),
            "rel_pairs": set(),                      # (源词, 目标词) 去重后还剩多少
            "rel_rows": 0,
            "rel_sample_by_tag": {},
            # ── 重音的形状 ──
            "multi_stress": 0, "stress_sample": [],
            "yo_no_stress": 0, "yo_total": 0,
            "canon_variants": collections.Counter(), # 一个词有几个 canonical
            "shift_sample": [],
        }
        for e in rd(p, limit):
            d["lines"] += 1
            w = e.get("word") or ""

            # ── 体：逐个字段找，不预设它在哪 ──
            for tag in e.get("tags") or []:
                d["all_word_tags"][tag] += 1
                if any(x in tag.lower() for x in ASPECT_STEMS):
                    d["aspect_where"]["word.tags"] += 1
                    d["aspect_tagvals"]["word.tags=" + tag] += 1
            for s in e.get("senses") or []:
                for tag in s.get("tags") or []:
                    d["all_sense_tags"][tag] += 1
                    if any(x in tag.lower() for x in ASPECT_STEMS):
                        d["aspect_where"]["sense.tags"] += 1
                        d["aspect_tagvals"]["sense.tags=" + tag] += 1
            for f in e.get("forms") or []:
                tags = f.get("tags") or []
                for _t in tags:
                    d["all_forms_tags"][_t] += 1
                if any(any(x in t.lower() for x in ASPECT_STEMS) for t in tags):
                    d["aspect_where"]["forms.tags"] += 1
                    for t in tags:
                        if any(x in t.lower() for x in ASPECT_STEMS):
                            d["aspect_tagvals"]["forms.tags=" + t] += 1
                    if len(d["aspect_sample"]) < 10:
                        d["aspect_sample"].append(
                            "%s → %s  tags=%s" % (w, f.get("form"), tags))
            for k in ("synonyms", "antonyms", "related", "derived", "coordinate_terms"):
                for it in e.get(k) or []:
                    if not isinstance(it, dict):
                        continue
                    allt = (it.get("tags") or []) + (it.get("raw_tags") or [])
                    if any(any(x in str(t).lower() for x in ASPECT_STEMS) for t in allt):
                        d["aspect_where"]["%s[].tags" % k] += 1
                        for t in allt:
                            if any(x in str(t).lower() for x in ASPECT_STEMS):
                                d["aspect_tagvals"]["%s[]=%s" % (k, t)] += 1
                        if len(d["aspect_sample"]) < 20:
                            d["aspect_sample"].append(
                                "%s --%s--> %s  tags=%s" % (w, k, it.get("word"), allt))

            # ── related 分堆 ──
            for it in e.get("related") or []:
                if not isinstance(it, dict):
                    continue
                d["rel_rows"] += 1
                tgt = it.get("word") or ""
                d["rel_pairs"].add((w, tgt))
                rt = tuple(it.get("raw_tags") or [])
                key = " / ".join(rt) if rt else "（无 raw_tags）"
                d["rel_rawtags"][key] += 1
                for t in it.get("tags") or []:
                    d["rel_tags"][t] += 1
                if key not in d["rel_sample_by_tag"]:
                    d["rel_sample_by_tag"][key] = "%s → %s" % (w, tgt)

            # ── 重音形状 ──
            if "ё" in w.lower():
                d["yo_total"] += 1
            canon = [f.get("form") or "" for f in e.get("forms") or []
                     if "canonical" in (f.get("tags") or [])]
            if canon:
                d["canon_variants"][len(canon)] += 1
                for c in canon:
                    if c.count(STRESS) >= 2:
                        d["multi_stress"] += 1
                        if len(d["stress_sample"]) < 10:
                            d["stress_sample"].append("%s → %s" % (w, c))
                    if "ё" in c.lower() and STRESS not in c:
                        d["yo_no_stress"] += 1
            # 屈折中重音移动：同一条目里取两个带重音的 form 比位置
            forms = [f.get("form") or "" for f in e.get("forms") or []]
            pos = {criteria.stress_position(f) for f in forms if STRESS in f}
            if len(pos) >= 2 and len(d["shift_sample"]) < 8:
                shown = [f for f in forms if STRESS in f][:6]
                d["shift_sample"].append("%s：%s" % (w, " ".join(shown)))
        acc[name] = d
        print("  · %-5s %9s 行" % (name, "{:,}".format(d["lines"])), file=sys.stderr)

    buf = io.StringIO()
    with redirect_stdout(buf):
        print("■ 俄语阶段 -1 探测④：体 / 构词词族 / 重音形状  2026-10-07"
              + ("（--limit %d）" % a.limit if a.limit else "（全量）"))

        print("\n" + "═" * 78)
        print("§ A 体（aspect）信息**住在哪个字段** —— 逐个字段找，不预设")
        print("═" * 78)
        for name, _ in SRC:
            d = acc[name]
            print("\n  ── %s" % name)
            if not d["aspect_where"]:
                print("     （一个字段都没命中 —— 候选词：%s）" % ", ".join(ASPECT_STEMS))
            for k, c in d["aspect_where"].most_common():
                print("     %-22s %10s" % (k, "{:,}".format(c)))
            print("     值域：")
            for k, c in d["aspect_tagvals"].most_common(14):
                print("        %-40s %10s" % (k[:38], "{:,}".format(c)))
            for s in d["aspect_sample"][:10]:
                print("     · " + s)

        print("\n" + "═" * 78)
        print("§ B ru 版 `related` 的 `raw_tags` 分堆 —— 428 万条到底是什么")
        print("═" * 78)
        d = acc["ru"]
        print("  条数 %s ／ **(源词, 目标词) 去重后 %s** ⇒ 重复率 %s"
              % ("{:,}".format(d["rel_rows"]), "{:,}".format(len(d["rel_pairs"])),
                 pct(d["rel_rows"] - len(d["rel_pairs"]), max(d["rel_rows"], 1))))
        print("\n  %-46s%12s  样例" % ("raw_tags 组合", "条数"))
        print("  " + "-" * 76)
        for k, c in d["rel_rawtags"].most_common(26):
            print("  %-46s%12s  %s" % (k[:44], "{:,}".format(c),
                                       d["rel_sample_by_tag"].get(k, "")[:26]))
        print("\n  共 %d 种 raw_tags 组合。`tags`（结构化那一列）的值域：" % len(d["rel_rawtags"]))
        for k, c in d["rel_tags"].most_common(12):
            print("     %-24s %10s" % (k, "{:,}".format(c)))

        print("\n" + "═" * 78)
        print("§ C 重音的形状：多重音 / ё / 屈折中移动")
        print("═" * 78)
        for name, _ in SRC:
            d = acc[name]
            print("\n  ── %s" % name)
            print("     canonical 个数分布：%s"
                  % "  ".join("%d个×%s" % (k, "{:,}".format(v))
                              for k, v in sorted(d["canon_variants"].items())))
            print("     canonical 里带 ≥2 个重音符：%s" % "{:,}".format(d["multi_stress"]))
            print("     词头含 ё 的条目：%s ／ canonical 含 ё 但不带重音符：%s"
                  % ("{:,}".format(d["yo_total"]), "{:,}".format(d["yo_no_stress"])))
            for s in d["stress_sample"][:6]:
                print("     · 多重音  " + s)
            for s in d["shift_sample"][:6]:
                print("     · 重音移动 " + s)
        print("\n" + "═" * 78)
        print("§ D 🔴 `tags` 的**完整值域**（无条件全打，不过滤）")
        print("═" * 78)
        print("  这一节是 §A 那张候选词表的**闸**：§A 按词干匹配，而词干也是猜的；")
        print("  本节把源头出现过的每一个 tag 值原样印出来，**下一个漏掉的值名会自己显形**。")
        print("  （2026-10-07 代价已付：候选表漏了 `perfect`，两家外审一起答错。）")
        for name, _ in SRC:
            d = acc[name]
            print("\n  ── %s：word.tags %d 种 ／ forms.tags %d 种 ／ sense.tags %d 种"
                  % (name, len(d["all_word_tags"]), len(d["all_forms_tags"]),
                     len(d["all_sense_tags"])))
            for label, ctr in (("word.tags", d["all_word_tags"]),
                               ("forms.tags", d["all_forms_tags"]),
                               ("sense.tags", d["all_sense_tags"])):
                vals = "  ".join("%s=%s" % (k, format(v, ",")) for k, v in ctr.most_common(40))
                print("     %-11s %s" % (label, vals[:1400] or "（空）"))
                if len(ctr) > 40:
                    print("                 …… 另有 %d 种" % (len(ctr) - 40))
    txt = buf.getvalue()
    print(txt)
    if a.archive:
        paths.PROBE.mkdir(parents=True, exist_ok=True)
        out = paths.PROBE / "probe_aspect_relations.txt"
        out.write_text(txt, "utf-8")
        print("■ 已存档 → %s" % out, file=sys.stderr)


if __name__ == "__main__":
    main()
