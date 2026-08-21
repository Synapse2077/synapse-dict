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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths   # noqa: E402
# 🔴 与收词器**共用同一份**「法语版缺定义占位符」判据。抄一份就是两边漂开的起点。
from intake_fr_words import PLACE as FR_PLACE   # noqa: E402

AFFIX_POS = {"prefix", "suffix", "infix", "interfix", "circumfix", "combining_form"}
norm = lambda s: re.sub(r"\s+", " ", s or "").strip()

# 🔴 每个版本必须声明**它的义项算不算缺口**，否则度量口径必错：
#    · fr 版的义项是**法语释义**，按 A3 明确不收 ⇒ 只看词形缺口
#    · it 版的义项已灌进 `sense_src(src='it-edition')` ⇒ 要跟那里比，不是跟英文 gloss 比
#    第一版没分这个口径，报出 fr 缺义项 77,372 / it 缺义项 92,117 —— **全是假的**。
# 🔴 2026-08-17 加第 6 列 `scope`：这一源的缺口**要不要收**。
#
# 起因：脚本原来把每一源的缺口都报成红色 🔴，包括**已决定不收**的那几源
# ⇒ 这条闸永远红。而「闸必须带已接受基线 + 理由，否则永远红、没人看」是我自己
#   记过的教训（`fix-regression-and-gate`）。红灯没有信息量，等于没有闸。
#
# 收录范围是用户 2026-08-17 定的：看词汇来源排名，**法语版之后断档**（10.3×），
# 断档线以下的几源边际贡献合计仅 1.87 万，一律只记账不收：
#
#     英文版义项级 form_of  436,700 (33.4%)   ┐
#     法语版变位表          417,647 (32.0%)   │ 收
#     法语版词条            166,630 (12.7%)   │
#     英文版词条            151,400 (11.6%)   │
#     英文版变位表          122,234 ( 9.4%)   ┘
#     ──────────────────── 断档 ────────────────────
#     意语版词条             11,889 ( 0.9%)   ← 释义要（阶段 1.5），词形也收
#     希腊语版/土耳其版/中文版  合计 1.87 万     ← 只记账
#
# ⚠️ `scope="ledger"` 的源仍然**每次都扫**：数字要在明处，只是不判红。
#    哪天决定要收，改一个字段即可，不用重写脚本。
SOURCES = [
    ("en", paths.KK, None, "结构基准：词条/义项/英文释义", "en-gloss", "collect"),
    ("it", paths.EDITION, "it", "意语原文释义", "it-evidence", "collect"),
    ("fr", paths.KK_FR, None, "词形并集（释义按 A3 不收）", "words-only", "collect"),
    ("zh-t", paths.KK_ZH_T, None, "中文版·繁（断档线下）", "words-only", "ledger"),
    ("zh-s", paths.KK_ZH_S, None, "中文版·简（断档线下）", "words-only", "ledger"),
    ("el", paths.KK_EL, None, "希腊语版（断档线下）", "words-only", "ledger"),
    ("tr", paths.KK_TR, None, "土耳其语版（断档线下）", "words-only", "ledger"),
]
SCOPE_NOTE = {"collect": "要收", "ledger": "📋 有意不收（2026-08-17：法语版之后断档）"}


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
                # 🔴 2026-08-19：判据必须与**那一版自己的收词器**逐字一致，
                #    否则闸永远红而数据没问题。这道闸原来只看 `form_of`、且只认意语版的
                #    占位符，于是把法语版 30 个词形报成「要收」——回源逐条看，
                #    全是 `intake_fr_words.py:77-82` 按两条成文规则有意不收的：
                #      · `alt_of` 指针（`kilohenry` = kH 的拼写变体）→ 归变形层
                #      · 法语版自己的占位符 `Définition manquante ou à compléter. (Ajouter)`
                #        （`laserfoto` / `black noise` / `diventabile`）→ 没东西可翻
                #
                # ⚠️ 🔴 这两条**只对法语版成立，不能一刀切到所有源**。
                #    我第一版就是一刀切的，英文版的「变形指针」当场从 43.7 万涨到 51.8 万 ——
                #    那 8 万条是 `alt_of`，而英文版的 alt_of **是要收的**
                #    （`build.py:147` 当年正是"把 alt_of 当 form_of"才造出 3,890 条编造标签）。
                #    一刀切等于把英文版的一整族真缺口从闸的视野里抹掉。
                #    ⇒ 豁免按源声明，判据跟着那一版自己的收词器走。
                if s.get("form_of") and not affix:
                    c["③ 变形指针（记账，不算缺口）"] += 1
                    continue
                if name == "fr":
                    if s.get("alt_of") and not affix:
                        c["③ alt_of 指针（fr 收词器不收，记账）"] += 1
                        continue
                    if FR_PLACE.search(g):
                        c["📋 法语版自己的「缺定义」占位符（没东西可翻，不算缺口）"] += 1
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
                    # 🔴 意语版的「缺定义」占位符按既定规则删除（fixes/strip_it_placeholder.py），
                    #    它**不是**缺口。不单列出来这条闸就永远红。
                    if "definizione mancante" in g or "aggiungila tu" in g:
                        c["📋 占位符（已按规则删除，不算缺口）"] += 1
                        continue
                    c["🔴 ② 词形在库、这条义项没有"] += 1
                    if len(miss_senses[w0]) < 2:
                        miss_senses[w0].append(g[:56])
    if verbose:
        meta = {x[0]: x for x in SOURCES}[name]
        print("\n■ %s —— %s   [%s]" % (name, meta[3], SCOPE_NOTE[meta[5]]))
        led = meta[5] == "ledger"
        for k, v in c.most_common():
            print("   %-34s %9s" % (k.replace("🔴", "📋") if led else k, f"{v:,}"))
        print("   缺口词形 %s 个" % f"{len(miss_words):,}")
        for w in sorted(miss_words)[:4]:
            print("      缺词形 %s" % w)
        for w, gs in list(miss_senses.items())[:4]:
            print("      缺义项 %-16s %s" % (w, gs[0]))
    return c, miss_words, miss_senses


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    # 🔴 缺口清单**由审计脚本本身导出**，不要在别处重新量一遍。
    #    我 2026-08-17 写临时脚本重算，fr 报 3,483 / it 报 600,781 —— 全是假的，
    #    因为漏了这里的「③ 变形指针」分类那一层（`measure-landing-not-source`：
    #    量自己的转换器不量数据）。要清单就从这里拿。
    ap.add_argument("--dump-gaps", metavar="PATH",
                    help="把 scope=collect 各源的缺口清单写成 JSON")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {w.lower() for (w,) in con.execute("SELECT word FROM dict")}
    have = defaultdict(set)
    for w, g in con.execute(
            "SELECT d.word, gl.text FROM sense s JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss gl ON gl.sense_id=s.id AND gl.lang='en'"):
        have[w.lower()].add(g)
    # 🔴 2026-08-17：it 版的证据**不能按 `sense_src.word_id` 归组**。
    #    `fixes/reroute_subentry_defs.py` 有意把子条目改挂到**短语自己的词条**上：
    #        库里 word='ingegneria informatica'  ← src_ref='kk-it:informatica:noun#0.1'
    #    按 word_id 归组就会问「informatica 有没有这条 gloss」，答案是没有 ⇒ 报假缺口。
    #    实测 124 条缺义项里 **84 条是这个假阳性**。
    #    ⇒ 判据改成按 `src_ref` 里的**源头词形**归组 —— 那一列写的是 dump 坐标，
    #      重路由不会改它，所以它才是"这条 gloss 收没收"的正确锚点。
    #      （`measure-landing-not-source` 的变体：**判据没跟上数据结构的变更**。）
    have_it = defaultdict(set)
    for ref, t in con.execute(
            "SELECT x.src_ref, x.text FROM sense_src x WHERE x.src='it-edition'"):
        # src_ref 形如 kk-it:<源头词形>:<词性>#<etym>.<idx>
        body = ref[len("kk-it:"):] if ref.startswith("kk-it:") else ref
        w0 = body.rsplit(":", 1)[0] if ":" in body else body
        have_it[w0.lower()].add(t)
    print("■ 库：词形 %s / 有英文义项的词形 %s" % (f"{len(words):,}", f"{len(have):,}"))

    total = Counter()
    gaps = {}
    for name, path, lc, _desc, mode, scope in SOURCES:
        if a.src and a.src != name:
            continue
        if not Path(path).exists():
            print("\n■ %s —— 文件不存在，跳过" % name)
            continue
        c, mw, ms = audit(name, path, lc, words,
                          have_it if mode == "it-evidence" else have, mode)
        if a.dump_gaps and scope == "collect":
            gaps[name] = {"miss_words": sorted(mw),
                          "miss_senses": {w: gs for w, gs in ms.items()}}
        tag = "要收" if scope == "collect" else "记账"
        total[("%s·缺词形" % name, tag)] = len(mw)
        total[("%s·缺义项" % name, tag)] = c["🔴 ② 词形在库、这条义项没有"]
    print("\n■ 汇总")
    todo = sum(v for (k, t), v in total.items() if t == "要收" and v)
    for tag in ("要收", "记账"):
        rows = [(k, v) for (k, t), v in total.items() if t == tag and v]
        if not rows:
            continue
        print("   —— %s ——" % ("🔴 要收" if tag == "要收" and todo else "✅ 要收" if tag == "要收"
                              else "📋 有意不收（2026-08-17：法语版之后断档）"))
        for k, v in rows:
            print("      %-20s %9s" % (k, f"{v:,}"))
    print("\n   %s 在收录范围内的缺口合计 %s（期望 0）"
          % ("✅" if todo == 0 else "🔴", f"{todo:,}"))
    if a.dump_gaps:
        Path(a.dump_gaps).write_text(json.dumps(gaps, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
        print("   缺口清单 → %s" % a.dump_gaps)
    return 0 if todo == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
