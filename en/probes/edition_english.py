#!/usr/bin/env python3
"""阶段 -1 探针 B：**六个非英文版里的英语条目**。2026-09-07。

═══ 为什么 en 到今天才做这件事 ═══
`[[multi-edition-methodology]]` 的版本榜：**英语是唯一 en 版排第 1 的**
（en 版 1,772,999 义项 vs 第 2 名 fr 版 224,320，差 8 倍）；其余五门的 en 版都排第 2/第 3。
所以跨版收割对它们是刚需，对英语边际收益结构上就小 —— 于是**一次都没做过**
（盘上 fr 5 份 / it 5 份 / pt 8 份切片，en **0 份**）。

🔴 **但"边际收益小"是就释义说的，音标不是同一回事。**
   老包实测：en 版 145 万条 entry 里只有 13.4 万条有 IPA（词头 9.6 万，7%）——
   `EN_PLAN` §3.1「六门里唯一主源给不出音标」。de 那轮靠跨版补了 82.0%。
   ⇒ **这一层必须量，不许沿用"英语不需要跨版"这个印象。**

🔴 第二个问题（`EN_PLAN` §3.3，直接决定 1.5 要花多少钱）：
   **中文版里的英语条目带不带人工中文释义、有多少。**
   `[[prove-free-path-before-quoting]]`：报价必须先证明免费路径走不通。

⚠️ 整版包是**多语种**的（zh 版覆盖 2,598 种语言、中文条目只占 9.9%），
   必须按 `lang_code == "en"` 自筛，不能整包当英语用。

输出 `data/work/en/probe/`：
  edition_english.json     每版：英语条目数 / 词头数 / 带 IPA / 带中文 / 义项数
  edition_words.tsv        逐词逐版一行，供与库做落点对账（**量落点不量源头**）

零 API 成本、只读、不下载。
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import gzip
import json
import time

import paths
from dbtool import has_han          # 判据只许一份：含中文的字符集（含扩展区）

OUT = paths.WORK / "probe"

EDITIONS = ["zh", "fr", "de", "es", "it", "pt"]

# 🔴🔴 **源头会把「这里没有音标」写成一个占位符**，`ipa` 字段非空但内容是空的。
#    de 阶段 4 实测丢弃过 21,149 条（`Subfamilia → […]`），`de/probes/entry_level_ipa.py`
#    里就有这张表 —— **而我移植本探针时恰恰漏了它**，第一版把 de 版报成
#    「净增 39,960 个带 IPA 的英语词头」，抽样一看**全是 `[…]`**。
#    （`[[measure-landing-not-source]]`：新数字先假设我的度量错了。）
#    ⇒ 判据：剥掉定界符和空白之后什么都不剩，就不是音标。
PLACEHOLDER = {"[…]", "…", "[...]", "...", "[ ]", "[]", "//", "/ /", ""}


def real_ipas(entry):
    """这条 entry 真正给出的音标（已剔占位符）。→ set"""
    out = set()
    for s in (entry.get("sounds") or []):
        v = (s.get("ipa") or "").strip()
        if not v or v in PLACEHOLDER:
            continue
        if not v.strip("/[]\\ …·.") :          # 只剩定界符和省略号 ⇒ 占位符的变体
            continue
        out.add(v)
    return out


def rows(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                yield json.loads(line)
            except Exception:
                continue


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fw = open(OUT / "edition_words.tsv", "w", encoding="utf-8")
    fw.write("edition\tword\thas_ipa\thas_zh\tn_sense\n")
    report = {}
    for ed in EDITIONS:
        p = paths.DUMPS / ("%swiktionary.jsonl.gz" % ed)
        if not p.exists():
            report[ed] = {"error": "包不在盘上：%s" % p.name}
            print("  %-4s ⚠️ 包不在盘上" % ed)
            continue
        t0 = time.time()
        n_line = n_en = n_sense = 0
        words, w_ipa, w_zh, w_ph = set(), set(), set(), set()
        n_ipa_entry = n_zh_sense = n_ph = 0
        for d in rows(p):
            n_line += 1
            if d.get("lang_code") != "en":
                continue
            w = (d.get("word") or "").strip()
            if not w:
                continue
            n_en += 1
            words.add(w)
            ipa = real_ipas(d)
            # 占位符单独数 —— 它是「源头声称有、实际没有」的量，必须看得见
            if not ipa and (d.get("sounds") or []):
                if any((s.get("ipa") or "").strip() for s in d["sounds"]):
                    n_ph += 1
                    w_ph.add(w)
            if ipa:
                n_ipa_entry += 1
                w_ipa.add(w)
            ns = nz = 0
            for s in (d.get("senses") or []):
                for g in (s.get("glosses") or []):
                    ns += 1
                    # 🔴 判据是「这条释义里有没有汉字」，不是「这是不是中文版」——
                    #    中文版里也有大量用英文写的释义，反过来别的版也可能夹中文。
                    #    量落点不量源头（`[[measure-landing-not-source]]`）。
                    if has_han(g):
                        nz += 1
            n_sense += ns
            n_zh_sense += nz
            if nz:
                w_zh.add(w)
            fw.write("%s\t%s\t%d\t%d\t%d\n"
                     % (ed, w.replace("\t", " "), 1 if ipa else 0, 1 if nz else 0, ns))
        report[ed] = {
            "package": p.name, "seconds": round(time.time() - t0, 1),
            "lines_total": n_line, "english_entries": n_en,
            "english_share_pct": round(100 * n_en / max(n_line, 1), 2),
            "distinct_words": len(words),
            "entries_with_ipa": n_ipa_entry, "words_with_ipa": len(w_ipa),
            "entries_placeholder_only": n_ph, "words_placeholder_only": len(w_ph),
            "senses": n_sense, "senses_with_han": n_zh_sense, "words_with_han": len(w_zh),
        }
        print("  %-4s 英语条目 %8s / 词头 %8s | **真** IPA 词头 %7s (占位符 %7s) | "
              "带汉字释义 %7s 条 / %7s 词  (%.0fs)"
              % (ed, f"{n_en:,}", f"{len(words):,}", f"{len(w_ipa):,}", f"{len(w_ph):,}",
                 f"{n_zh_sense:,}", f"{len(w_zh):,}", report[ed]["seconds"]))
    fw.close()
    (OUT / "edition_english.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
