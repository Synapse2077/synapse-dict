#!/usr/bin/env python3
"""阶段 1.5 取数：意语版自己写的释义，到底有多少、能落到哪里。2026-08-13。

阶段 -1 量到「真释义 105,474 条」，那是**按义项**数的。真正决定工作量和钱的是三个数：
    ① 有多少条真释义（不是 `plurale di X` 这类变形指针）
    ② 这些释义落在多少个**我们库里已有**的词形上（落不上的是阶段 3 的收词工作，不是 1.5 的）
    ③ 这些词形里有多少**已经有中文**了 —— 这一条直接决定「全量重译 vs 只补缺口」的钱

⚠️ 意语版没有 `etymology_number` 字段（用的是 `etymology_texts` 复数），
   所以这一版的词条键里 etym 恒为 0，与英文版不同 —— 别拿英文版的键去套。

用法（在 it/ 目录下）：
    python3 probes/edition_gloss_census.py
"""
import gzip
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths   # noqa: E402

AFFIX_POS = {"prefix", "suffix", "infix", "interfix", "circumfix", "combining_form"}
# 变形指针的意语模板文本：`plurale di X` / `participio passato di X` / `femminile di X` …
PTR = re.compile(
    r"^(prima |seconda |terza )?(persona )?"
    r"(singolare|plurale|maschile|femminile|participio|gerundio|infinito|imperativo|"
    r"indicativo|congiuntivo|condizionale|superlativo|diminutivo|accrescitivo|"
    r"vezzeggiativo|peggiorativo|dispregiativo|forma|voce)\b.{0,80}?\bdi\s+\S+\s*$",
    re.IGNORECASE)


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {}
    for wid, w in con.execute("SELECT id, word FROM dict"):
        words.setdefault(w.lower(), wid)
    zh_words = {w.lower() for (w,) in con.execute(
        "SELECT DISTINCT d.word FROM dict d JOIN sense s ON s.word_id = d.id "
        "JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='zh'")}

    stat = Counter()
    per_word = defaultdict(int)     # 库里已有的词形 → 该词形的真释义条数
    miss_word = defaultdict(int)    # 库里没有的词形
    lens = []
    for line in gzip.open(paths.EDITION, "rt", encoding="utf-8"):
        e = json.loads(line)
        if e.get("lang_code") != "it":
            continue
        stat["意语词条"] += 1
        w = (e.get("word") or "").strip()
        pos = e.get("pos") or ""
        affix = pos in AFFIX_POS
        for s in (e.get("senses") or []):
            g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
            stat["义项"] += 1
            if not g:
                stat["空 gloss"] += 1
                continue
            if (s.get("form_of") or s.get("alt_of")) and not affix:
                stat["变形指针（结构字段判定）"] += 1
                continue
            if PTR.match(g):
                stat["变形指针（释义文本判定）"] += 1
                continue
            stat["✅ 真释义"] += 1
            lens.append(len(g))
            if w.lower() in words:
                per_word[w.lower()] += 1
            else:
                miss_word[w.lower()] += 1

    print("■ 意语版（itwiktionary，lang_code=it）")
    for k, v in stat.most_common():
        print("   %-28s %9s" % (k, f"{v:,}"))

    have = sum(per_word.values())
    miss = sum(miss_word.values())
    print("\n■ 真释义的落点")
    print("   落在库里已有的词形上        %9s 条 / %s 个词形"
          % (f"{have:,}", f"{len(per_word):,}"))
    print("   词形库里没有（→ 阶段 3 收词）  %9s 条 / %s 个词形"
          % (f"{miss:,}", f"{len(miss_word):,}"))

    with_zh = sum(v for w, v in per_word.items() if w in zh_words)
    no_zh = have - with_zh
    print("\n■ 🔴 决定钱的那个数（在已有词形里）")
    print("   词形**已经有中文**          %9s 条 / %s 个词形"
          % (f"{with_zh:,}", f"{len([w for w in per_word if w in zh_words]):,}"))
    print("   词形**一条中文都没有**       %9s 条 / %s 个词形"
          % (f"{no_zh:,}", f"{len([w for w in per_word if w not in zh_words]):,}"))

    lens.sort()
    print("\n■ 释义长度（字符）：中位 %d / 均值 %d / P90 %d / 最长 %d"
          % (lens[len(lens) // 2], sum(lens) / len(lens), lens[int(len(lens) * .9)], lens[-1]))
    print("   ⇒ 比英文版 gloss 长得多（英文版多是 'to do / to make' 这种），"
          "翻译成本按字符算不能照搬 es 的单价")
    return 0


if __name__ == "__main__":
    sys.exit(main())
