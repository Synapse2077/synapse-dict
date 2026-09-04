#!/usr/bin/env python3
"""**外锚闸**：库 vs 各版 dump，**义项级**逐条比对。de 版，2026-09-04（阶段 7）。

═══ 为什么必须有这一道，且它与回归闸不可互相替代 ═══
`[[external-anchor-gates]]`：闸分两类 ——
**锚自己上一版的必然过期，锚外部 dump 的永不过期**。
回归闸问的是「**过去的修复还在不在**」，它只看库里已有的东西；
本闸问的是「**源头有而我们没有的，还剩多少**」—— 这两个问题没有交集。

es 那轮正是这道闸逮到 `derived` **义项级漏收 20,193 条**，
而所有内部闸（行数、不变量、可逆性）永远发现不了它：
**词形在库、义项没收进来**，按词形量覆盖率是满分。

⚠️ pt 和 de 原本都没有这道闸（es/it/fr 有）。de 这一份补在阶段 7。

═══ 🔴 为什么必须是义项级，不能是词形级 ═══
按词形级量，「词形在库、这条义项没收」永远是绿的。
⇒ 一律按 **(词形, 义项文本)** 二元组比对。

═══ 🔴 判据一个字都不重抄 ═══
本文件 import 收词器/收义项器里那一份：
    `ingest_de_senses.is_real_sense`   ← 什么算「真释义」（排除指针义项）
    `intake_edition_words.norm_word`   ← 词形归一（撇号、空白）
    `intake_edition_words.EDITIONS`    ← 各版 dump 路径与要不要按 lang_code 筛
**闸与收词器判据漂开 = 闸在报自己的 bug** —— fr 那轮从 it 抄了一条「词缀豁免」，
当场报 42 条假缺口，逐条读下来 40 条是纯指针、收词器跳过是对的
（`[[fix-regression-and-gate]]` 第三种机制）。
⚠️ 而 2026-09-03 建回归闸那天，**33 条断言里 9 条是同一个形状的错**，
   其中两条还是「判据 import 对了、喂错了对象」。所以本文件的每一条比对，
   下面都写清楚**它拿库里的哪一列去对源头的哪一个字段**。

═══ 四类缺口 ═══
    ① 词形根本不在 `dict`                     → 阶段 3 收词的账
    ② 词形在库、**这条义项**没有              → 阶段 1.5 收义项的账
    ③ 指针义项（`form_of`/`alt_of`/`form-of`）→ **归变形层，不算缺口**
    ④ 证据层 `sense_src` 有、出版层 `sense` 没有 → de 实测 1,524（0.6%），
      与 fr 的 61,364（7.3%）不是一个量级：**德语版与英文版的词形重叠只有 3 个**，
      不存在「同一个词两套义项要裁决」的问题。

用法（在 de/ 目录下）：
    python3 -u pipeline/verify_vs_dump.py              # 全部源
    python3 -u pipeline/verify_vs_dump.py --src de     # 只看一个
    python3 -u pipeline/verify_vs_dump.py --gaps /tmp/gaps.json
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths                                                   # noqa: E402
from ingest_de_senses import is_real_sense                     # noqa: E402
from intake_edition_words import EDITIONS, norm_word           # noqa: E402

f = lambda n: format(n, ",")


def norm_gloss(s):
    return re.sub(r"\s+", " ", s or "").strip()


# (键, 说明, 比对模式, 收录范围)
#
# 🔴 `scope` 决定这一源的缺口**判不判红**。没有它，闸永远红 ⇒ 没人看 ⇒ 等于没有闸
#    （`[[fix-regression-and-gate]]` 第四种机制：闸没坏，是没人再看它了）。
# ⭐ de 的范围是 `[[gloss-three-languages]]` 定的：**释义只保留三语**
#    （中文 + 英文 + 本语言）。所以 fr/zh/it/es/pt 五版**只取词形，不取释义** ——
#    实测每个维基版只给「自己语言的词」写定义，对外语词只写翻译。
#    这不是"没收"，是**有意不收**，所以它们的义项缺口不判红。
SOURCES = [
    ("en", "英文版德语切片：词形 + 英文义项（建库主源）", "gloss", "collect"),
    ("de", "德语版：词形 + 德语义项（进证据层）", "gloss", "collect"),
    ("fr", "法语版（残差收词，只取词形）", "words-only", "ledger"),
    ("zh", "中文版（残差收词 + 白送中文，只取词形）", "words-only", "ledger"),
    ("it", "意语版（残差收词，只取词形）", "words-only", "ledger"),
    ("es", "西语版（残差收词，只取词形）", "words-only", "ledger"),
    ("pt", "葡语版（残差收词，只取词形）", "words-only", "ledger"),
]
SCOPE_NOTE = {"collect": "要收", "ledger": "📋 按三语方针有意不收释义"}


def op(p):
    p = Path(p)
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def audit(name, desc, mode, scope, words, have, verbose=True):
    """→ (计数, 缺词形, 缺义项)。

    `words` = 库内全部词形（归一后）；
    `have`  = {词形: {该词在库里的全部义项文本}} —— **证据层 `sense_src.text`**，
              因为源头给的就是原文，拿出版层去对会把「收进来了但没出版」误报成「没收」。
    """
    path, need_filter = EDITIONS[name]
    c = Counter()
    miss_words, miss_senses = set(), defaultdict(list)
    with op(path) as fh:
        for line in fh:
            if need_filter and '"lang_code"' in line and '"de"' not in line:
                continue                        # 便宜的预筛，与收词器同一招
            try:
                e = json.loads(line)
            except Exception:
                c["坏行"] += 1
                continue
            if need_filter and e.get("lang_code") != "de":
                continue
            w0 = (e.get("word") or "").strip()
            if not w0:
                continue
            # 🔴 归一必须与收词器同一份 `norm_word`（折叠空白 + 撇号）。
            #    不归一会把 `Kup'jans'k` 与 `Kup’jans’k` 当两个词形，报出成千条假缺口。
            w = norm_word(w0)
            senses = e.get("senses") or []
            if not senses:
                c["无 senses 的条目"] += 1
            for s in senses:
                # ③ 指针义项 ⇒ 归变形层。判据**直接用收义项器那一份** `is_real_sense`。
                if not is_real_sense(s):
                    c["③ 指针义项 / 空 gloss（归变形层，不算缺口）"] += 1
                    continue
                g = norm_gloss((s.get("glosses") or [""])[0])
                c["源头真义项"] += 1
                if w not in words:
                    c["🔴 ① 词形不在库里"] += 1
                    miss_words.add(w0)
                    continue
                if mode == "words-only":
                    c["② 该版按三语方针只取词形"] += 1
                    continue
                if g not in have.get(w, ()):
                    c["🔴 ② 词形在库、这条义项没有"] += 1
                    if len(miss_senses[w0]) < 2:
                        miss_senses[w0].append(g[:64])
    if verbose:
        print("\n■ %s —— %s   [%s]" % (name, desc, SCOPE_NOTE[scope]))
        for k, v in c.most_common():
            print("   %-44s %11s" % (k, f(v)))
        print("   缺口词形 %s 个 ／ 缺口义项涉及 %s 个词形"
              % (f(len(miss_words)), f(len(miss_senses))))
        for x in sorted(miss_words)[:4]:
            print("      缺词形 %s" % x)
        for x, gs in list(miss_senses.items())[:4]:
            print("      缺义项 %-20s %s" % (x[:20], gs[0]))
    return c, miss_words, miss_senses


def unpublished(con):
    """④ 证据层有、出版层没有。→ (条数, 涉及词形数, 样本)。

    ⚠️ 这一类**词形级和证据级两道闸都看不见**：词形在库、证据也收进来了，
       只是没有一条出版义项承接它。fr 那轮 61,364 条（7.3%）就藏在这里。
    """
    n = con.execute("SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL").fetchone()[0]
    nw = con.execute("SELECT COUNT(DISTINCT word_id) FROM sense_src "
                     "WHERE sense_id IS NULL").fetchone()[0]
    # 其中**整个词形一条出版义项都没有**的 —— 这才是读者真会撞上的
    hard = con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT s.word_id FROM sense_src s "
        " WHERE s.sense_id IS NULL"
        "   AND NOT EXISTS(SELECT 1 FROM sense x WHERE x.word_id=s.word_id))").fetchone()[0]
    ex = con.execute(
        "SELECT d.word, s.text FROM sense_src s JOIN dict d ON d.id=s.word_id "
        " WHERE s.sense_id IS NULL"
        "   AND NOT EXISTS(SELECT 1 FROM sense x WHERE x.word_id=s.word_id) LIMIT 8").fetchall()
    return n, nw, hard, ex


# 已接受基线：`源键 → (① 上限, ② 上限, 理由)`。**超了红。**
# 🔴 与回归闸同一条规矩：ACCEPT 锁的是**数字**不是名字。
ACCEPT = {
    "en": (0, 1_600,
           "② 上限 1,600：英文版同一个 gloss 在库里可能已按上游改写后的措辞落库"
           "（收尾单 C6：上游改写 143 个词条的释义）。①（词形不在库）必须是 0。"),
    "de": (14, 67_037,
           "🔴🔴 **这道闸建成当天逮到的东西，收尾单 C29。** 我第一版把基线写成 (0,0)"
           "「德语版是收录源，两类都必须归零」—— **那是没查收录范围就写的**。\n"
           "      查了 `ingest_de_senses.main()`：1.5a 的 `targets` 是 "
           "`zero = 一条义项都没有的词形`，**只收英文版没覆盖的词**。\n"
           "      ⇒ 源头 238,364 条真释义，1.5a 只收 135,179 ⇒ 当时差 **103,171 条**；"
           "**阶段 1.5c 用唯一映射确定性补掉 36,134 之后，基线收紧到 67,037**。"
           "（62,577 个词形，`Dezember` 的 „der zwölfte und somit letzte Monat eines Jahres" "\"" " 就在里面）。\n"
           "      ⚠️ **这个范围不是随手定的，它换掉了一整笔钱**：es/fr 对所有词都收本语言版 "
           "⇒ 与英文版词形重叠 15–28% ⇒ 同一个词两套义项必须逐条裁决；\n"
           "        pt/de 把范围切成「只补零义项的词」⇒ 重叠 0.0% ⇒ 裁决这一笔从没发生。\n"
           "        **重叠 0.0% 不是数据的性质，是这个范围决定的结果。**\n"
           "      ⇒ 基线锁在实测值，等 C29 决定补到哪一档再往下调。**别把它调回 0 来让闸好看。**\n"
           "      ①=14：德语版有、`dict` 里没有的词形（阶段 3 的残差，量级可忽略但如实锁住）。"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="只审一个源")
    ap.add_argument("--gaps", help="把缺口写成 JSON 供下一步消费")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {norm_word(w) for (w,) in con.execute("SELECT word FROM dict")}
    have = defaultdict(set)
    for w, t in con.execute("SELECT d.word, s.text FROM sense_src s "
                            "JOIN dict d ON d.id=s.word_id"):
        have[norm_word(w)].add(norm_gloss(t))
    print("■ 库内词形 %s ／ 有证据义项的词形 %s" % (f(len(words)), f(len(have))))

    red, out, loose = 0, {}, []
    for name, desc, mode, scope in SOURCES:
        if a.src and name != a.src:
            continue
        if not Path(EDITIONS[name][0]).exists():
            print("\n■ %s —— dump 不在盘上，跳过" % name)
            continue
        c, mw, ms = audit(name, desc, mode, scope, words, have)
        out[name] = {"miss_words": sorted(mw)[:5000],
                     "miss_senses": {k: v for k, v in list(ms.items())[:5000]}}
        if scope != "collect":
            continue
        e1, e2 = c["🔴 ① 词形不在库里"], c["🔴 ② 词形在库、这条义项没有"]
        a1, a2, why = ACCEPT.get(name, (0, 0, ""))
        for tag, got, exp in (("①", e1, a1), ("②", e2, a2)):
            if got > exp:
                red += 1
                print("   🔴 %s 超出已接受基线：%s > %s" % (tag, f(got), f(exp)))
                if why:
                    print("      当初的理由：%s" % why)
            elif got < exp:
                # 🔴🔴 **基线松了没人管，正是闸烂掉的方式**（`[[fix-regression-and-gate]]`
                #    第四种机制：pt 那轮 F3 从 539 涨到 643 一声没吭，因为 ACCEPT 按名字豁免）。
                #    回归闸有这一段，本闸第一版**漏写了** —— 1.5c 把 ② 从 103,171 降到 67,037，
                #    而闸只会说「通过」。⇒ 降下来必须大声要求收紧，**连理由文案一起改**。
                loose.append((name, tag, exp, got))

    n4, nw4, hard4, ex4 = unpublished(con)
    con.close()
    print("\n■ ④ 证据层有、出版层没有：%s 条 ／ 涉及 %s 个词形" % (f(n4), f(nw4)))
    print("   其中**整个词形一条出版义项都没有** %s 个 —— 读者真会撞上的就是这批" % f(hard4))
    for w, t in ex4:
        print("      %-22s %s" % (w[:22], (t or "")[:56]))

    if a.gaps:
        Path(a.gaps).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        print("\n■ 缺口已写入 %s" % a.gaps)

    # ⬇ 不算红（数据变好了），但**必须打印**：基线降下来而理由文案没跟着改，
    #   就是 pt 那次「理由写 2,888、实际 610」的成因。
    for nm, tag, exp, got in loose:
        print("⬇  基线该收紧：%s %s  期望 %s → 实际 %s（改数字的同时改理由文案）"
              % (nm, tag, f(exp), f(got)))
    print("\n%s" % ("✅ 外锚闸通过" if not red else "🔴 %d 条超出基线" % red))
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
