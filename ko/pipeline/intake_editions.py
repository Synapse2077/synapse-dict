#!/usr/bin/env python3
"""阶段 4a：从韩文版＋中文版两片收词 —— 词形 ＋ 它们的义项。2026-09-21。
**七门里最大的一次收词。**

═══ 落点 ═══
    源                  净增词形   其中有释义   其中有 IPA
    韩文版 한국어         77,149     46,993     48,120
    中文简体 朝鲜语      180,226    180,224        344   ← **白送的中文释义**
    中文繁体 朝鮮語       30,037     30,005      1,020
    ────────────────────────────────────────────
                    并集 ~266,580 ⇒ `dict` 378,811 → ~645,391

🔴 **日文版不在本步**：它的释义是日语，按「释义只保留三语」不进库；
   它的词形若只有日语释义，收进来就是空白页。它的 IPA 已在阶段 3 用掉了。

═══ 🔴 `KO_PLAN` §四.1 的四条必办，本步兑现前两条 ═══
  **a** 收词落库后**立刻**查空白页 —— 写在本脚本的回核里，不等阶段 5
  **b** `invalidates` 名单**一定非空** —— 这次动了分母、读音层、变形层三处
  （c 读音靠 G2P 补、d 词性宁缺不猜 —— c 在 4b，d 见下）

═══ 🔴 判据 d：词性宁缺不猜 ═══
中文版 pos **99.5% 是 `unknown`**，韩文版 15,268 条 unknown。
我查过 `pos_title` 能不能救 —— **不能**：
    韩文版 unknown 里 **98.8%（15,092 条）根本没有 pos_title**
    中文版 unknown 里 **99.98%（194,343 条）没有**
    有的那几个，值是「품사」(词性)「釋義」(释义) —— **那是章节标题不是词性**
⇒ `entry.pos` / `pos_raw` **存源头原值 `unknown`**，不猜、不留空、不映射成别的。
🔴 什么会推翻：找到能给这批词定词性的源（韩国国立国语院的开放词表之类），
  或源头某天把 pos 补上。**不许用"看词尾像动词"这种形式代理**（`-다` 结尾的
  既有动词也有形容词还有名词，猜错就是错，而错比缺更伤权威）。

═══ 义项：按**来源语言**入库，不做跨版对齐 ═══
    韩文版的释义 → `sense_gloss(lang='ko')`
    中文版的释义 → `sense_gloss(lang='zh')`   ← **白送，不用翻译**
🔴 **不把中文版的义项当成英文版义项的「译文」** —— 它们是各版独立编纂的义项，
   `[[flash-translation-validated]]`：别拿另一版义项当翻译真值。
   本步收的是**新词形**的义项（这些词英文版根本没有，不存在对齐问题）；
   **已有词形**的中文释义怎么挂，是阶段 5 的事，那里要做真正的裁决。

跑（在仓库根）：
    python3 -u ko/pipeline/intake_editions.py
    python3 -u ko/pipeline/intake_editions.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import gzip
import json
import sqlite3
import unicodedata

# 🔴 判据**只写一份**，住在 `criteria.py` —— 建外锚闸时发现它在三个文件里
#    各有一份（当时三份一样，但三份一定会漂，而闸正要靠它）。
#    `[[refactor-mindset-code-quality]]`／外锚闸必须 import 收词器用的那一份。
from criteria import norm_ko, is_pointer_sense  # noqa: F401

import dbtool
import paths
from build_entry_layer import POS_MAP
from build_inflection_layer import is_korean_form
from coverage import blank_pages, blank_sample

# (来源名, 路径, 释义语言)
SOURCES = [
    ("ko-edition", paths.EDITION, "ko"),
    ("zh-edition-simp", paths.ZH_SIMP, "zh"),
    ("zh-edition-trad", paths.ZH_TRAD, "zh"),
]
BATCH = 40000


def op(p):
    p = str(p)
    return gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") \
        else open(p, encoding="utf-8")




def iter_entries():
    """吐出 (src, gloss_lang, word, pos_raw, etym_no, seq, senses)。
    两遍扫描共用，保证「收哪些词」和「收哪些义项」出自同一条判据。"""
    for src, path, glang in SOURCES:
        seen = collections.Counter()
        for line in op(path):
            try:
                d = json.loads(line)
            except Exception:
                continue
            w = d.get("word")
            if not w or not w.strip():
                continue
            praw = d.get("pos") or "unknown"
            en_ = d.get("etymology_number")
            etym = str(en_) if en_ is not None else "0"
            k = (src, w, praw, etym)
            seq = seen[k]
            seen[k] += 1
            yield src, glang, w, praw, etym, seq, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
    before_dict = len(indict)
    before_lemma = con.execute(
        "SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    before_sense = con.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
    max_id_before = con.execute("SELECT MAX(id) FROM dict").fetchone()[0]
    before_max_sense = con.execute("SELECT COALESCE(MAX(id),0) FROM sense").fetchone()[0]
    max_rank = {r[0]: r[1] for r in con.execute(
        "SELECT word_id, MAX(rank) FROM sense GROUP BY word_id")}
    con.close()

    # ── 第一遍：要收哪些词形 ──
    newwords = {}                      # word → {pos:Counter, lemma:bool}
    stat = collections.Counter()
    for src, glang, w, praw, etym, seq, d in iter_entries():
        if w in indict:
            stat["已在 dict（本步不动它，中文释义留给阶段 5）·" + src] += 1
            continue
        # 🔴 **词形必须是韩语** —— 这条判据阶段 2c 就建好了（`is_korean_form`），
        #    而我收词时**忘了用**，结果 12 个非韩语词头落了库：
        #      罗马字转写  gibun / musan / saja / sanso / yeot / reru
        #      英语词      pedestal / phylactic / vermiform appendix / oganeson
        #    前者违反判据 1（罗马字不许进词形），后者根本不是韩语。
        #    ⚠️ 这是「同一条判据没在所有层上一致」的**第二次**
        #      （第一次是冗余去重只在变形层做了、`hanja_reading` 漏了）。
        if not is_korean_form(w):
            stat["跳过·不是韩语词形·" + src] += 1
            continue
        real = [s for s in (d.get("senses") or []) if s.get("glosses")]
        if not real:
            stat["跳过·无释义·" + src] += 1
            continue
        e = newwords.setdefault(w, {"pos": collections.Counter(), "lemma": False})
        e["pos"][praw] += 1
        if any(not is_pointer_sense(s) for s in real):
            e["lemma"] = True
        stat["→ 新词形·" + src] += 1

    print("■ 扫三份源")
    for k, v in sorted(stat.items()):
        print("   %-52s %9s" % (k, format(v, ",")))
    print("   %-52s %9s" % ("🔴 净增词形（并集）", format(len(newwords), ",")))
    unknown_pos = sum(1 for e in newwords.values()
                      if set(e["pos"]) == {"unknown"})
    print("   %-52s %9s (%.1f%%)" % ("  └ 词性只有 unknown 的（判据 d：不猜）",
                                     format(unknown_pos, ","),
                                     100 * unknown_pos / max(len(newwords), 1)))
    print("\n■ 分母会怎么变（当场说清，否则下次看见会当成回归）：")
    after = before_dict + len(newwords)
    print("   dict           %s → %s" % (format(before_dict, ","), format(after, ",")))
    print("   词元           %s → %s" % (format(before_lemma, ","),
                                        format(before_lemma + sum(
                                            1 for e in newwords.values() if e["lemma"]), ",")))

    # ── 第二遍：这批词的 entry 与义项（**dry 跑也要算**，否则 expect 只能写 None，
    #    而 `None` 等于"允许变但不校验"—— 那道闸就白设了）──
    rows = [(w, norm_ko(w), 1 if e["lemma"] else 0,
             "/".join(p for p, _ in e["pos"].most_common() if p) or None)
            for w, e in sorted(newwords.items())]
    erows, srows, glossrows, senserows = [], [], [], []
    rank_of = collections.Counter()
    for src, glang, w, praw, etym, seq, d in iter_entries():
        if w not in newwords:
            continue
        real = [x for x in (d.get("senses") or []) if x.get("glosses")]
        if not real:
            continue
        eref = "%s:%s:%s:%s:%d" % (src, w, praw, etym, seq)
        erows.append((w, POS_MAP.get(praw, praw), praw, etym, seq, src, eref))
        for i, se in enumerate(real):
            g = se.get("glosses") or []
            ptr = is_pointer_sense(se)
            sidx = None
            if not ptr:
                rank_of[w] += 1
                sidx = len(senserows)
                senserows.append((w, eref, rank_of[w], POS_MAP.get(praw, praw)))
                for j, gg in enumerate(g):
                    glossrows.append((sidx, glang, "definition", j, gg, src))
            srows.append((w, sidx, src, "%s#%d" % (eref, i), glang, g[-1],
                          json.dumps(se.get("tags") or [], ensure_ascii=False)
                          if se.get("tags") else None))
    print("\n■ 这批词带来的层：")
    print("   %-22s %9s" % ("entry", format(len(erows), ",")))
    print("   %-22s %9s" % ("sense（出版层）", format(len(senserows), ",")))
    print("   %-22s %9s" % ("sense_gloss", format(len(glossrows), ",")))
    print("   %-22s %9s" % ("sense_src（证据层）", format(len(srows), ",")))
    byl = collections.Counter(g[1] for g in glossrows)
    print("   释义语言分布: %s   ⭐ zh 那部分是**白送的中文释义**" % dict(byl))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    rows = [(w, norm_ko(w), 1 if e["lemma"] else 0,
             "/".join(p for p, _ in e["pos"].most_common() if p) or None)
            for w, e in sorted(newwords.items())]

    # 🔴🔴 **词形和义项必须在同一个事务里** —— 这是阶段 2c 刚学到的那条：
    #    分成两步的中间状态就是 26 万个空白页，而 pt 正是这么留下
    #    355,605 个「搜得到、点进去空白」的词形，且「没有人会回头重跑」。
    #    ⇒ 下面一个 `session` 里依次插 dict → entry → sense_src/sense/sense_gloss，
    #      要么全有，要么全没有。
    with dbtool.session(
            "intake-ko-editions",
            expect={"__rows__": len(rows), "pos": len(rows),
                    "#entry": len(erows), "#sense": len(senserows),
                    "#sense_gloss": len(glossrows), "#sense_src": len(srows),
                    "sense_src.sense_id": sum(1 for r in srows if r[1] is not None)},
            invalidates=[
                "**分母**：dict %s → %s，词元数同步变 —— 所有按词形/词元算的覆盖率都要重算"
                % (format(before_dict, ","), format(after, ",")),
                "**读音层**：新收的 %s 个词形里 4.9 万有 IPA，阶段 4b 必须重跑 "
                "`build_pronunciation.py --replace`（ja 栽过：收词后没重跑，覆盖率 99.90%%→39.8%%）"
                % format(len(rows), ","),
                "**变形层**：韩文版给新词形带来 3 万个变形 form，阶段 4b 要增量补",
                # 🔴 第一版**漏了这一条**，后果当场显形：29,297 个新词形的义项全是指针
                #    （`一世` → "X 的汉字表记"），指针的内容在**关系层**，
                #    而关系层只建过英文版那批 ⇒ 它们成了空白页。
                "**关系层**：新词形的指针义项（`form_of`/`alt_of`）与关系字段要收，"
                "否则「义项全是指针」的那批（实测 29,297 个）就是空白页",
                "**空白页基线**：回归闸 R1 的 6 会变，本步回核当场量新值并写进 R1",
                "**搜索层**：`search_prefix` 要在这批之后重建（阶段 9）",
            ]) as s:
        for i in range(0, len(rows), BATCH):
            s.executemany(
                "INSERT INTO dict (word, word_norm, is_lemma, pos) VALUES (?,?,?,?)",
                rows[i:i + BATCH])
        print("   ✓ dict +%s" % format(len(rows), ","))

        # ── 拿新 id（按本次写库的边界取，不靠"最大的 N 个"）──
        for r in s.execute("SELECT id, word FROM dict WHERE id > ?", (max_id_before,)):
            indict[r[1]] = r[0]

        efull = [(indict[w], w, pos, praw, etym, seq, src, eref)
                 for w, pos, praw, etym, seq, src, eref in erows]
        for i in range(0, len(efull), BATCH):
            s.executemany(
                "INSERT INTO entry (word_id, word_src, pos, pos_raw, etym_no, seq, "
                "src, src_ref) VALUES (?,?,?,?,?,?,?,?)", efull[i:i + BATCH])
        eid_of = {r[1]: r[0] for r in s.execute(
            "SELECT id, src_ref FROM entry WHERE src <> 'en-edition'")}

        sfull = [(indict[w], eid_of.get(eref), rank, pos)
                 for w, eref, rank, pos in senserows]
        for i in range(0, len(sfull), BATCH):
            s.executemany(
                "INSERT INTO sense (word_id, entry_id, rank, pos) VALUES (?,?,?,?)",
                sfull[i:i + BATCH])
        # 🔴 **按内容键 (word_id, rank) 回查，不靠插入顺序** ——
        #    "新插的正好按我给的顺序排列"是个关于实现的假设，
        #    与我在 2a 批评过的"取最大的 N 个 id"同类。
        idmap = {}
        for sid, wid, rank in s.execute(
                "SELECT id, word_id, rank FROM sense WHERE id > ?", (before_max_sense,)):
            idmap[(wid, rank)] = sid
        real_sid = [idmap[(r[0], r[2])] for r in sfull]

        for i in range(0, len(glossrows), BATCH):
            s.executemany(
                "INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src) "
                "VALUES (?,?,?,?,?,?)",
                [(real_sid[g[0]], g[1], g[2], g[3], g[4], g[5])
                 for g in glossrows[i:i + BATCH]])
        for i in range(0, len(srows), BATCH):
            s.executemany(
                "INSERT INTO sense_src (word_id, sense_id, src, src_ref, lang, "
                "text, raw_tags) VALUES (?,?,?,?,?,?,?)",
                [(indict[r[0]], real_sid[r[1]] if r[1] is not None else None,
                  r[2], r[3], r[4], r[5], r[6]) for r in srows[i:i + BATCH]])
        print("   ✓ 义项三层写完")

    print("\n═══ 写后回核（必办 a：**当场**查空白页，不等阶段 5）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    blank = blank_pages(con)
    checks = [
        ("dict 行数", q("SELECT COUNT(*) FROM dict"), after),
        ("word 仍唯一", q("SELECT COUNT(*) FROM (SELECT word FROM dict "
                          "GROUP BY word HAVING COUNT(*)>1)"), 0),
        ("word_norm == word（NFC 自证）",
         q("SELECT COUNT(*) FROM dict WHERE word_norm<>word"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-30s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    print("\n   🔴🔴 **空白页 = %s**（收词前是 6）" % format(blank, ","))
    print("      —— 这批词的义项要在**下一步**（4a-senses）立刻收，"
          "否则它们就是 pt 那 355,605 个空白页")
    print("      样本：%s" % blank_sample(con, 8))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
