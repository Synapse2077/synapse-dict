#!/usr/bin/env python3
"""**外锚闸**：库 vs 各版 dump，义项级逐条比对。2026-08-25，补阶段 3 的收官条件。

═══ 为什么补这个 ═══
阶段 3 的「完成的定义」写了两条：① 收词后库行数 == 预期值 ✅；
② **外锚闸重扫 dump 逐条 diff 通过** —— **这条一直没做**。
`es/` 和 `it/` 都有 `verify_vs_dump.py`，`fr/` 没有。

`[[external-anchor-gates]]`：闸分两类 ——
**锚自己上一版的必然过期，锚外部 dump 的永不过期**。
es 那轮正是这道闸逮到 `derived` 义项级漏收 20,193 条，
所有内部闸（行数、不变量、可逆性）永远发现不了它：词形在库、义项没收进来。

═══ 为什么必须是义项级 ═══
按**词形级**量覆盖率，「词形在库、这条义项没收」永远是绿的。
⇒ 一律按 (词形, 义项文本) 二元组比对。

═══ fr 特有的第四类缺口 ═══
it/es 的闸查三类；fr 多一类，因为 fr 的法语释义走了**两层**：
    dump → `sense_src`（证据层，710,567）→ `sense_gloss`（出版层，523,723）
🔴 **中间差 18.6 万条**（阶段 1.5 第一段的裁决桶 ①/①'/③：结构对得上但语义没验，
   有意没挂）。这批**收进来了但没出版**，词形级和证据级两道闸都看不见它 ——
   所以本闸单列一类「④ 证据层有、出版层没有」。

⚠️ 判据必须与**那一版自己的收词器逐字一致**，否则闸永远红而数据没问题。
   本文件一律 `import` 收词器里的常量与函数（`norm_apos` / `SOURCES` / `POS_MAP`），
   **一个字都不重抄** —— it 那轮抄一份的代价是两边判据漂开、报了一堆假缺口。

用法（在 fr/ 目录下）：
    python3 -u pipeline/verify_vs_dump.py            # 全部源
    python3 -u pipeline/verify_vs_dump.py --src fr   # 只看一个
    python3 -u pipeline/verify_vs_dump.py --dump-gaps /tmp/gaps.json
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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths                                                    # noqa: E402
from ingest_fr_edition import is_pointer                        # noqa: E402
from intake_fr_words import norm_apos                           # noqa: E402
from intake_other_editions import SOURCES as OTHER_SOURCES      # noqa: E402

def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


# 法文版自己的「缺定义」占位符 —— 没东西可翻，**不是缺口**。
# 与 `fixes/strip_editorial_residue.py` 同一族判据（那里是清理，这里是豁免）。
FR_PLACE = re.compile(r"D[ée]finition manquante ou [àa] compl[ée]ter|"
                      r"[ÉE]tymologie manquante ou incompl[èe]te")

# (键, 路径, lang_code 过滤, 说明, 比对模式, 收录范围)
#
# 🔴 `scope` 决定这一源的缺口**判不判红**。没有它，闸永远红 ⇒ 没人看 ⇒ 等于没有闸
#    （`[[fix-regression-and-gate]]`：闸必须带已接受基线 + 理由）。
# ⭐ fr 全部十二源用户 2026-08-22 定的是**全收**，所以这里没有 `ledger` 的源；
#    留着这个字段是为了以后要缩范围时改一个字就行，不用重写脚本。
SOURCES = [
    ("en", paths.KK, None, "英文版：词形 + 英文义项", "en-gloss", "collect"),
    ("fr", paths.EDITION, "fr", "法文版：词形 + 法语义项（进证据层）", "fr-evidence", "collect"),
] + [(k, paths.DUMPS / fn, "fr" if flt else None,
      "%s 版（残差收词，只取词形）" % k, "words-only", "collect")
     for k, fn, flt in OTHER_SOURCES]

SCOPE_NOTE = {"collect": "要收", "ledger": "📋 有意不收"}


def op(p):
    return gzip.open(p, "rt", encoding="utf-8") if str(p).endswith(".gz") \
        else open(p, encoding="utf-8")


def audit(name, path, lang_code, words, have, mode, verbose=True):
    c = Counter()
    miss_words, miss_senses = set(), defaultdict(list)
    with op(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                c["坏行"] += 1
                continue
            if lang_code and e.get("lang_code") != lang_code:
                continue
            w0 = (e.get("word") or "").strip()
            if not w0:
                continue
            # 🔴 撇号归一必须与收词器同一份：`norm_apos`。不归一会把 `l’eau` 与 `l'eau`
            #    当成两个词形，闸当场报出几万条假缺口。
            w = norm_apos(w0).lower()
            senses = e.get("senses") or []
            if not senses:
                c["无 senses 的条目"] += 1
            for s in senses:
                g = norm((s.get("glosses") or [""])[0])
                if not g:
                    c["空 gloss"] += 1
                    continue
                # ③ 指针 ⇒ 归变形层，不算义项缺口。
                # 🔴 判据**直接用收词器那一份** `is_pointer`，不在这里另写。
                #    第一版我从 it 抄了一条「词缀豁免」（`and not affix`），当场报 42 条
                #    假缺口 —— 逐条读下来 40 条是纯指针（`Pluriel de -ande.`），
                #    收词器跳过是对的。**闸与收词器判据不一致 = 闸在报自己的 bug。**
                if is_pointer(s):
                    c["③ 指针义项（归变形层，不算缺口）"] += 1
                    continue
                if name == "fr":
                    if FR_PLACE.search(g):
                        c["📋 法文版自己的占位符（没东西可翻，不算缺口）"] += 1
                        continue
                c["源头真义项"] += 1
                if w not in words:
                    c["🔴 ① 词形不在库里"] += 1
                    miss_words.add(w0)
                    continue
                if mode == "words-only":
                    c["② 该版只取词形（释义按既定范围不收）"] += 1
                    continue
                if g not in have.get(w, ()):
                    c["🔴 ② 词形在库、这条义项没有"] += 1
                    if len(miss_senses[w0]) < 2:
                        miss_senses[w0].append(g[:60])
    if verbose:
        meta = {x[0]: x for x in SOURCES}[name]
        print("\n■ %s —— %s   [%s]" % (name, meta[3], SCOPE_NOTE[meta[5]]))
        for k, v in c.most_common():
            print("   %-40s %11s" % (k, format(v, ",")))
        print("   缺口词形 %s 个" % format(len(miss_words), ","))
        for x in sorted(miss_words)[:4]:
            print("      缺词形 %s" % x)
        for x, gs in list(miss_senses.items())[:4]:
            print("      缺义项 %-18s %s" % (x[:18], gs[0]))
    return c, miss_words, miss_senses


def unpublished(con):
    """④ fr 特有：**证据层有、出版层没有**的法语释义。

    这批不是"漏收"，是阶段 1.5 第一段有意留下的裁决桶（结构对得上但语义没验）。
    单列出来是因为**前三类闸都看不见它** —— 词形在库、证据也在库，只是没上架。
    """
    n_src = con.execute(
        "SELECT count(*) FROM sense_src WHERE src='fr-edition'").fetchone()[0]
    n_pub = con.execute(
        "SELECT count(*) FROM sense_gloss WHERE lang='fr' AND src='fr-edition'").fetchone()[0]
    return n_src, n_pub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--dump-gaps", metavar="PATH", help="缺口清单写成 JSON")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {norm_apos(w).lower() for (w,) in con.execute("SELECT word FROM dict")}
    have_en = defaultdict(set)
    for w, g in con.execute(
            "SELECT d.word, gl.text FROM sense s JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss gl ON gl.sense_id=s.id AND gl.lang='en'"):
        have_en[norm_apos(w).lower()].add(g)
    # 🔴 法文版的落点是**证据层** `sense_src`，不是 `sense_gloss` ——
    #    拿出版层去比会把那 18.6 万裁决桶全报成"漏收"（它们没漏，是有意没上架）。
    #    ⇒ ② 类缺口对着证据层比，"有没有上架"由 ④ 单独报。
    have_fr = defaultdict(set)
    for w, t in con.execute(
            "SELECT d.word, x.text FROM sense_src x JOIN dict d ON d.id=x.word_id "
            "WHERE x.src='fr-edition'"):
        have_fr[norm_apos(w).lower()].add(norm(t))
    print("■ 库：词形 %s ｜ 有英文义项的词形 %s ｜ 有法语证据的词形 %s"
          % (format(len(words), ","), format(len(have_en), ","), format(len(have_fr), ",")))

    total, gaps = Counter(), {}
    for name, path, lc, _d, mode, scope in SOURCES:
        if a.src and a.src != name:
            continue
        if not Path(path).exists():
            print("\n■ %s —— 文件不存在，跳过" % name)
            continue
        c, mw, ms = audit(name, path, lc, words,
                          have_fr if mode == "fr-evidence" else have_en, mode)
        if a.dump_gaps and scope == "collect":
            gaps[name] = {"miss_words": sorted(mw), "miss_senses": dict(ms)}
        tag = SCOPE_NOTE[scope]
        total[("%s·缺词形" % name, tag)] = len(mw)
        total[("%s·缺义项" % name, tag)] = c["🔴 ② 词形在库、这条义项没有"]

    n_src, n_pub = unpublished(con)
    print("\n■ ④ 法语释义：证据层 %s → 出版层 %s，**差 %s**"
          % (format(n_src, ","), format(n_pub, ","), format(n_src - n_pub, ",")))
    print("   这是阶段 1.5 第一段的裁决桶（①/①'/③：结构对得上但语义没验，有意没挂），")
    print("   **不是漏收**。前三类闸看不见它，所以单列在这里盯着。")

    print("\n■ 汇总")
    todo = sum(v for (k, t), v in total.items() if t == "要收" and v)
    for tag in ("要收", "📋 有意不收"):
        rows = [(k, v) for (k, t), v in total.items() if t == tag and v]
        if not rows:
            continue
        print("   —— %s ——" % (("🔴 " if todo else "✅ ") + tag if tag == "要收" else tag))
        for k, v in sorted(rows, key=lambda x: -x[1]):
            print("      %-22s %11s" % (k, format(v, ",")))
    print("\n   %s 收录范围内的缺口合计 %s（期望 0）"
          % ("✅" if todo == 0 else "🔴", format(todo, ",")))
    if a.dump_gaps:
        Path(a.dump_gaps).write_text(json.dumps(gaps, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
        print("   缺口清单 → %s" % a.dump_gaps)
    return 0 if todo == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
