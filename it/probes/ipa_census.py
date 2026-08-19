#!/usr/bin/env python3
"""阶段 4 第一步：**回源数音标条数**。不写库，只出数。2026-08-17。

═══ 为什么第一步是数数 ═══
现在音标是 `dict` 上的一个列 —— 一个词形只放得下一个值。源头给的远不止一个：
同形异读（`ancora` 锚 ˈankora / 仍然 anˈkora）、地区差（`casa` 北部 ˈkaza / 标准 ˈkasa）、
宽式与严式。**被列结构挤掉了多少，只有回源数才知道。**

⚠️ 判据必须按**条**数，不能按词形数 —— es 的 `derived` 就是漏了这层，
   按词形看覆盖率 100%、按条看少收 20,193 条（`external-anchor-gates`）。

本脚本产出三组数，写进 `data/work/it/ipa_census/`：
  ① 每个版本：带音标的条目数 / 音标行数 / 词形数 / 去重后的 (词形,音标,记法) 组合数
  ② **归一效果对照**：en 与 fr 都给了音标的词形里，归一前后一致率各是多少
     （A13 说「没归一会误报 92% 冲突」，这里把那个数真的量出来）
  ③ 与库对比：应落表条数 vs 现在列里的 588,280；库里有而源头查不到的那批有多少
     （那批的 `ipa_src` 只能写 `unknown`，**不猜**）

用法（在 it/ 目录下）：
    python3 probes/ipa_census.py            # 全量三版
    python3 probes/ipa_census.py --quick    # 只跑两个 gz 切片（跳过 761 MB 的英文版）
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths          # noqa: E402
from ipa_variants import cmp_key, iter_source, norm_ipa, variants_of   # noqa: E402

OUT = paths.WORK / "ipa_census"
SOURCES = [
    ("en-edition", paths.KK, None, "英文版切片（建库主源）"),
    ("it-edition", paths.EDITION, "it", "意语版整包（按 lang_code 过滤）"),
    ("fr-edition", paths.KK_FR, None, "法语版切片（A13：音标主源，6.3 倍）"),
]
f = lambda n: format(n, ",")


def scan(src, path, lang_code):
    """→ (word → {(ipa, notation)}), 计数器。同时把明细写成 TSV 备查。"""
    per_word = defaultdict(set)
    c = Counter()
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / ("%s.tsv" % src)).open("w", encoding="utf-8") as fh:
        fh.write("word\tpos\tetym\tipa\tnotation\traw\ttags\tsrc_ref\n")
        for w, d in iter_source(path, src, lang_code):
            c["条目"] += 1
            vs = variants_of(d, src)
            if not vs:
                continue
            c["带音标的条目"] += 1
            for v in vs:
                c["音标行"] += 1
                c["记法·" + v.notation] += 1
                per_word[v.word].add((v.ipa, v.notation))
                fh.write("\t".join([v.word, v.pos, str(v.etym_no), v.ipa, v.notation,
                                    v.raw.replace("\t", " "), "|".join(v.tags),
                                    v.src_ref]) + "\n")
    c["词形"] = len(per_word)
    c["去重组合"] = sum(len(s) for s in per_word.values())
    return per_word, c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()

    tables = {}
    for src, path, lc, desc in SOURCES:
        if a.quick and src == "en-edition":
            print("■ 跳过 %s（--quick）" % src)
            continue
        print("■ 扫 %-12s %s" % (src, desc), flush=True)
        pw, c = scan(src, path, lc)
        tables[src] = pw
        for k in ("条目", "带音标的条目", "音标行", "词形", "去重组合",
                  "记法·phonemic", "记法·narrow"):
            print("     %-14s %s" % (k, f(c[k])))
        print("     一词多读（去重后 >1 条）%s" % f(sum(1 for s in pw.values() if len(s) > 1)),
              flush=True)

    # ═══ ② 归一效果对照 ═══
    if "en-edition" in tables and "fr-edition" in tables:
        en, fr = tables["en-edition"], tables["fr-edition"]
        both = set(en) & set(fr)
        agree_norm = sum(1 for w in both
                         if {i for i, n in en[w] if n == "phonemic"} &
                            {i for i, n in fr[w] if n == "phonemic"})
        # 归一前：把 fr 侧的 `.ˈ` 还原回去，再比
        def unnorm(s):
            return s.replace("ˈ", ".ˈ").replace("ˌ", ".ˌ").lstrip(".")
        agree_raw = sum(1 for w in both
                        if {i for i, n in en[w] if n == "phonemic"} &
                           {unnorm(i) for i, n in fr[w] if n == "phonemic"})
        print("\n═══ 归一效果（en ∩ fr 都有音标的词形 %s 个）═══" % f(len(both)))
        print("   归一后至少有一条音位式一致   %s (%.1f%%)"
              % (f(agree_norm), 100.0 * agree_norm / max(1, len(both))))
        print("   🔴 归一前（fr 的 `.ˈ` 不折） %s (%.1f%%)   ← A13 那个「误报 92%%」的本体"
              % (f(agree_raw), 100.0 * agree_raw / max(1, len(both))))

    # ═══ ③ 与库对比 ═══
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    dict_ipa = {w: i for w, i in con.execute(
        "SELECT word, ipa FROM dict WHERE trim(COALESCE(ipa,''))<>''")}
    all_words = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()

    # 并集要按**两把尺子**各算一遍：存什么（norm）与算不算同一个读音（cmp）
    union, union_cmp = defaultdict(set), defaultdict(set)
    for src in tables:
        for w, s in tables[src].items():
            union[w] |= s
            union_cmp[w] |= {(cmp_key(i), n) for i, n in s}
    in_dict = {w: s for w, s in union_cmp.items() if w in all_words}
    rows = sum(len(s) for s in in_dict.values())
    raw_rows = sum(len(s) for s in union.values())
    print("\n═══ 与库对比 ═══")
    print("   源头并集（%d 版，按 norm）  %s 个词形 / %s 条"
          % (len(tables), f(len(union)), f(raw_rows)))
    print("   同上，折掉音节点后         %s 条  ← 差额 %s 条是各版排版习惯，不是变体"
          % (f(sum(len(s) for s in union_cmp.values())),
             f(raw_rows - sum(len(s) for s in union_cmp.values()))))
    print("   其中库里有这个词形的       %s 个词形 / %s 条  ← 阶段 4 应落表的量"
          % (f(len(in_dict)), f(rows)))
    print("   现在 dict.ipa 列里          %s 条（一词形一条，上限就是词形数）" % f(len(dict_ipa)))
    print("   ⇒ 被列结构挤掉的            %s 条" % f(rows - len(dict_ipa)))
    multi = sum(1 for s in in_dict.values() if len(s) > 1)
    print("   其中真·一词多读的词形       %s 个" % f(multi))

    # 库里有、源头查不到的：那批只能写 unknown
    miss = [w for w, i in dict_ipa.items()
            if (cmp_key(i), "phonemic") not in union_cmp.get(w, ())
            and (cmp_key(i), "narrow") not in union_cmp.get(w, ())]
    print("\n   🔴 库里有音标、但三版都查不到这一条的  %s 个词形" % f(len(miss)))
    print("      （这批的 `ipa_src` 只能写 unknown —— 证明不了来源不许猜）")
    nosrc = [w for w in miss if w not in union]
    print("      其中源头**这个词形一条音标都没给**的 %s 个（剩下 %s 个是源头给了别的读音）"
          % (f(len(nosrc)), f(len(miss) - len(nosrc))))
    for w in miss[:10]:
        print("        %-24s 库=%s   源头=%s"
              % (w[:24], dict_ipa[w][:28],
                 " / ".join(sorted(x for x, n in union.get(w, ()))[:2]) or "（无）"))
    (OUT / "miss_in_dumps.txt").write_text("\n".join(miss), encoding="utf-8")
    print("\n   明细写在 %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
