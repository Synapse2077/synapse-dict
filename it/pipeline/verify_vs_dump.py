#!/usr/bin/env python3
"""缺口审计：库 vs 各版 dump，**义项级**逐条比对。2026-08-13，阶段 3。

═══ 为什么是义项级 ═══
es 上按**词形级**量覆盖率，结果 `derived` 那一层义项级漏收 20,193 条完全看不见 ——
词形在库里、义项没收进来，词形级口径永远是绿的。
⇒ 本脚本一律按 (词形, 义项文本) 二元组比对。

═══ 三类缺口 ═══
① 词形不在库里            → 收词（本阶段）
② 词形在库、这条义项没有   → 补义项（本阶段，仅英文版；其它版释义按 A3 不收）
③ 是变形指针 / 已判为不收 → 记账

⚠️ 外部锚：比对对象是**冻结的 dump 文件**，不是我们自己的上一版 ⇒ 这条闸永不过期。
⚠️ 堵自我背书：缺口按**源头**分类，绝不用"我们收了所以它对"当判据。

用法（在 it/ 目录下）：
    python3 pipeline/verify_vs_dump.py            # 全部版本
    python3 pipeline/verify_vs_dump.py --src en   # 只看一个
"""
import argparse
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
norm = lambda s: re.sub(r"\s+", " ", s or "").strip()

# 🔴 每个版本必须声明**它的义项算不算缺口**，否则度量口径必错：
#    · fr 版的义项是**法语释义**，按 A3 明确不收 ⇒ 只看词形缺口
#    · it 版的义项已灌进 `sense_src(src='it-edition')` ⇒ 要跟那里比，不是跟英文 gloss 比
#    第一版没分这个口径，报出 fr 缺义项 77,372 / it 缺义项 92,117 —— **全是假的**。
SOURCES = [
    ("en", paths.KK, None, "结构基准：词条/义项/英文释义", "en-gloss"),
    ("it", paths.EDITION, "it", "意语原文释义", "it-evidence"),
    ("fr", paths.KK_FR, None, "词形并集（释义按 A3 不收）", "words-only"),
    ("zh-t", paths.KK_ZH_T, None, "词形并集 + 中文盲测真值", "words-only"),
    ("zh-s", paths.KK_ZH_S, None, "同上", "words-only"),
]


def op(p):
    return gzip.open(p, "rt", encoding="utf-8") if str(p).endswith(".gz") \
        else open(p, encoding="utf-8")


def audit(name, path, lang_code, words, have_glosses, mode, verbose=True):
    """→ 该版的缺口统计"""
    c = Counter()
    miss_words = set()
    miss_senses = defaultdict(list)
    with op(path) as f:
        for line in f:
            e = json.loads(line)
            if lang_code and e.get("lang_code") != lang_code:
                continue
            w0 = (e.get("word") or "").strip()
            w = w0.lower()
            pos = e.get("pos") or ""
            affix = pos in AFFIX_POS
            for s in (e.get("senses") or []):
                g = norm((s.get("glosses") or [""])[0])
                if not g:
                    c["空 gloss"] += 1
                    continue
                if s.get("form_of") and not affix:
                    c["③ 变形指针（记账，不算缺口）"] += 1
                    continue
                c["源头真义项"] += 1
                if w not in words:
                    c["🔴 ① 词形不在库里"] += 1
                    miss_words.add(w0)
                    continue
                if mode == "words-only":
                    c["② 该版释义按 A3 不收（只取词形）"] += 1
                    continue
                if g not in have_glosses.get(w, ()):
                    c["🔴 ② 词形在库、这条义项没有"] += 1
                    if len(miss_senses[w0]) < 2:
                        miss_senses[w0].append(g[:56])
    if verbose:
        print("\n■ %s —— %s" % (name, {x[0]: x[3] for x in SOURCES}[name]))
        for k, v in c.most_common():
            print("   %-34s %9s" % (k, f"{v:,}"))
        print("   缺口词形 %s 个" % f"{len(miss_words):,}")
        for w in sorted(miss_words)[:4]:
            print("      缺词形 %s" % w)
        for w, gs in list(miss_senses.items())[:4]:
            print("      缺义项 %-16s %s" % (w, gs[0]))
    return c, miss_words, miss_senses


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {w.lower() for (w,) in con.execute("SELECT word FROM dict")}
    have = defaultdict(set)
    for w, g in con.execute(
            "SELECT d.word, gl.text FROM sense s JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss gl ON gl.sense_id=s.id AND gl.lang='en'"):
        have[w.lower()].add(g)
    have_it = defaultdict(set)
    for w, t in con.execute(
            "SELECT d.word, x.text FROM sense_src x JOIN dict d ON d.id=x.word_id "
            "WHERE x.src='it-edition'"):
        have_it[w.lower()].add(t)
    print("■ 库：词形 %s / 有英文义项的词形 %s" % (f"{len(words):,}", f"{len(have):,}"))

    total = Counter()
    for name, path, lc, _desc, mode in SOURCES:
        if a.src and a.src != name:
            continue
        if not Path(path).exists():
            print("\n■ %s —— 文件不存在，跳过" % name)
            continue
        c, mw, ms = audit(name, path, lc, words,
                          have_it if mode == "it-evidence" else have, mode)
        total["缺口词形·并集"] += 0
        total["%s·缺词形" % name] = len(mw)
        total["%s·缺义项" % name] = c["🔴 ② 词形在库、这条义项没有"]
    print("\n■ 汇总")
    for k, v in total.items():
        if v:
            print("   %-22s %9s" % (k, f"{v:,}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
