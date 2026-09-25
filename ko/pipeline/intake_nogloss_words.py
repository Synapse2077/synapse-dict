#!/usr/bin/env python3
"""阶段 8 途中补收：韩文版 13,095 个**没有任何带 gloss 义项**的词头。2026-09-24。

═══ 它是外锚闸逮到的 ═══
`ko/pipeline/verify_vs_dump.py` 第一次跑，查 IPA 缺口时发现
`발가벗기다`（脱光）/`안내되다`（被引导）/`덜그렁하다`（哐啷响）**根本不在 `dict` 里**。
回源查：收词器 `intake_editions.py` 要求「至少一条带 gloss 的义项」——

    real = [s for s in (d.get("senses") or []) if s.get("glosses")]
    if not real:
        stat["跳过·无释义·" + src] += 1
        continue

而韩文版对这些词给的义项是 `tags:["no-gloss"]`。
🔴 **`를`（宾格助词，韩语最基本的词之一）就这么不在词典里**，而 `을`（同一个助词的
辅音后变体）在 —— 因为 `을` 在别的版里有 gloss。

🔴 **这与 K1 同形**：阶段 1 也推迟过 6,089 个无 gloss 的汉字词形，阶段 2a 收了 5,955 个
（134 个 forms/sounds/etym/关系四样全空的不收）。**同一条判据没在韩文版上复用** ——
这是 ko 第三次「已有判据漏用」（前两次：`is_korean_form` 没用在收词上、
`invalidates` 漏了关系层）。

═══ 收什么、不收什么（判据照抄阶段 2a，那次是对的）═══
收：`is_korean_form` 通过 **且** 至少有一样内容（IPA / 发音形 / 罗马字 / forms / 关系）。
不收：五样全空的（实测 **33 个**）—— 收进来就是纯空白页，落账不收。

    带 IPA        13,050 (99.7%)      带发音形谚文  13,047
    带罗马字       13,047              带关系         1,681 (12.8%)
    🔴 五样全空        33

═══ 🔴 它们没有任何语言的释义 ═══
用户 2026-09-24 拍板「先收录再说」。⚠️ 这会让「词元里有释义的占比」这个数**掉下去**——
分母涨 1.3 万而分子不动。那不是回归，是分母变了，**必须在 `invalidates` 里声明**
（ko 阶段 4b 的 93.5%→27.7% 就是这么处理的，所以没变成惊吓）。

═══ 建 `dict` ＋ `entry`，**不建 `sense`/`sense_src`** ═══
没有 gloss ⇒ 证据层没有东西可存，建空行就是假装有内容。
建 `entry` 的理由是**四套罗马字要有地方住**（`fill_romanization.py` 写在 `entry` 上）。

跑（在仓库根）：
    python3 -u ko/pipeline/intake_nogloss_words.py
    python3 -u ko/pipeline/intake_nogloss_words.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import json
import sqlite3

import dbtool
import paths
from criteria import NOT_A_WORD, norm_ko
from build_entry_layer import POS_MAP
from build_inflection_layer import is_korean_form

f = lambda n: format(n, ",")
SRC = "ko-edition"
REL_FIELDS = ("synonyms", "antonyms", "derived", "related", "hypernyms",
              "hyponyms", "coordinate_terms", "proverbs")


def scan(indict):
    """→ (words, skipped)。words[w] = {pos:Counter, recs:[(praw, etym, seq)], 有什么}"""
    words, skipped = {}, []
    seen = collections.Counter()
    for line in open(paths.EDITION, encoding="utf-8"):
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("pos") in NOT_A_WORD:
            continue
        w = (o.get("word") or "").strip()
        if not w or norm_ko(w) in indict:
            continue
        if [s for s in (o.get("senses") or []) if s.get("glosses")]:
            continue                      # 有 gloss 的走正常收词器，不归本步
        praw = o.get("pos")
        en_ = o.get("etymology_number")
        etym = str(en_) if en_ is not None else "0"
        k = (w, praw, etym)
        seq = seen[k]
        seen[k] += 1
        d = words.setdefault(w, {"pos": collections.Counter(), "recs": [],
                                 "ipa": 0, "hp": 0, "roman": 0,
                                 "forms": 0, "rel": 0})
        d["pos"][praw] += 1
        d["recs"].append((praw, etym, seq))
        for s in o.get("sounds") or []:
            d["ipa"] += bool(s.get("ipa"))
            d["hp"] += bool(s.get("hangeul"))
            d["roman"] += bool(s.get("roman"))
        d["forms"] += len(o.get("forms") or [])
        for kk in REL_FIELDS:
            d["rel"] += len(o.get(kk) or [])
    # ── 判据照抄阶段 2a：不是韩语词形不收；五样全空不收 ──
    keep = {}
    for w, d in words.items():
        if not is_korean_form(w):
            skipped.append((w, "不是韩语词形"))
            continue
        if not any(d[k] for k in ("ipa", "hp", "roman", "forms", "rel")):
            skipped.append((w, "IPA/发音形/罗马字/forms/关系 五样全空"))
            continue
        keep[w] = d
    return keep, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {norm_ko(r[0]) for r in con.execute("SELECT word FROM dict")}
    before = {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
              for t in ("dict", "entry")}
    before_lemma = con.execute(
        "SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    con.close()

    words, skipped = scan(indict)
    print("■ 韩文版里没有任何带 gloss 义项、且不在 `dict` 的词头")
    print("   %-34s %8s" % ("✅ 要收", f(len(words))))
    c = collections.Counter(why for _w, why in skipped)
    for k, v in c.most_common():
        print("   %-34s %8s" % ("不收·" + k, f(v)))
    for k in ("ipa", "hp", "roman", "rel"):
        n = sum(1 for d in words.values() if d[k])
        print("      带 %-6s %7s (%.1f%%)"
              % (k, f(n), 100.0 * n / max(len(words), 1)))

    # 落账：不收的那批
    p = paths.WORK / "nogloss_words_skipped.tsv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("# 韩文版无 gloss 词头里**有意不收**的。2026-09-24。\n")
        fh.write("# 什么会推翻：这些词在别的源里拿到了内容，或者判据本身被翻案。\n")
        for w, why in skipped:
            fh.write("%s\t%s\n" % (w, why))
    print("   落账 %s（%d 行）" % (p.relative_to(paths.ROOT), len(skipped)))

    drows = [(w, norm_ko(w), 1, "/".join(x for x, _ in d["pos"].most_common() if x)
              or None) for w, d in sorted(words.items())]
    print("\n■ `dict` %s → %s（词元 %s → %s）"
          % (f(before["dict"]), f(before["dict"] + len(drows)),
             f(before_lemma), f(before_lemma + len(drows))))
    nentry = sum(len(d["recs"]) for d in words.values())
    print("■ `entry` %s → %s（+%s）"
          % (f(before["entry"]), f(before["entry"] + nentry), f(nentry)))
    print("■ **不建** `sense` / `sense_src` —— 没有 gloss，证据层没有东西可存")

    if not a.apply:
        print("\n（这是 dry 跑。加 --apply 才写库）")
        return

    with dbtool.session(
            "ko-intake-nogloss-words",
            expect={"__rows__": len(drows), "#entry": nentry,
                    "pos": None},
            invalidates=[
                "🔴 **词元分母涨 %s** ⇒ 所有「每词元」的覆盖率都会掉一截。"
                "**那不是回归，是分母变了** —— 对外报数必须说明。"
                "账的闸 P6 的两条读音覆盖率、一条「词元里有释义的占比」都要重新量落点"
                % f(len(drows)),
                "🔴 **读音层必须重跑**：这批词 99.7% 带人工 IPA、发音形谚文与四套罗马字，"
                "而它们此前一行都没进 `pronunciation`。"
                "次序：`build_pronunciation.py --replace --apply` "
                "→ `fill_g2p_pronunciation.py --rebuild --apply`（前者会连 g2p 行一起删）",
                "🔴 **罗马字层要重跑**：`fill_romanization.py` 写在 `entry` 上，"
                "新建的 entry 行现在四列全空",
                "关系层：这批里 1,681 个词形带关系字段，**要定向补写** —— "
                "`build_relation_layer.py --replace` 已被拦住"
                "（那会抹掉 `hanja_spelling` 那 5.1 万条不可重跑的行）",
                "外锚闸 `verify_vs_dump.py` 的 `BUDGET`：ko-edition 那一档会变 —— "
                "**先量落点再改，别提前调**",
            ]) as s:
        for i in range(0, len(drows), 20000):
            s.executemany(
                "INSERT INTO dict (word, word_norm, is_lemma, pos) VALUES (?,?,?,?)",
                drows[i:i + 20000])
        wid = {r[1]: r[0] for r in s.execute("SELECT id, word FROM dict")}
        erows = []
        for w, d in sorted(words.items()):
            for praw, etym, seq in d["recs"]:
                erows.append((wid[w], w, POS_MAP.get(praw, praw), praw, etym, seq,
                              SRC, "%s:%s:%s:%s:%d" % (SRC, w, praw, etym, seq)))
        for i in range(0, len(erows), 20000):
            s.executemany(
                "INSERT INTO entry (word_id, word_src, pos, pos_raw, etym_no, seq,"
                " src, src_ref) VALUES (?,?,?,?,?,?,?,?)", erows[i:i + 20000])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n■ 写后回核（从库里重算）")
    red = 0
    for name, got, want in [
            ("dict 行数", q("SELECT COUNT(*) FROM dict"), before["dict"] + len(drows)),
            ("entry 行数", q("SELECT COUNT(*) FROM entry"), before["entry"] + nentry),
            # 🔴 这一条验的是「本步**有意不建** sense」真的没建 ——
            #    否则"不建"就只是一句写在文件头的话（`[[lesson-must-become-mechanism]]`）。
            # 🔴🔴 第一版写的是 `word_id > before["dict"]` —— 拿**行数**当 id 边界。
            #    `dict.id` 是 AUTOINCREMENT，实测行数 640,463 而 max(id) 640,482
            #    （19 个空洞）⇒ 那条检查当场误报 13 条，而那 13 条是**旧词**
            #    （`힘의평형` `𪝤` …），它们本来就该有义项。
            #    **红的是检查不是数据。** ⇒ 判据改成按**含义**取这批词：
            #      「只有 ko-edition 的词条，且证据层一条都没有」——
            #      这正是本步收的那批的定义，与 id 无关。
            ("🔴 本步新收的词形里有 sense 行的",
             q("SELECT COUNT(*) FROM sense s WHERE s.word_id IN ("
               " SELECT e.word_id FROM entry e WHERE e.src='%s'"
               "  AND NOT EXISTS (SELECT 1 FROM entry e2 WHERE e2.word_id=e.word_id"
               "                   AND e2.src<>'%s')"
               "  AND NOT EXISTS (SELECT 1 FROM sense_src x WHERE x.word_id=e.word_id))"
               % (SRC, SRC)), 0),
            ("🔴 新 entry 认不到 dict 的",
             q("SELECT COUNT(*) FROM entry e WHERE NOT EXISTS"
               "(SELECT 1 FROM dict d WHERE d.id=e.word_id)"), 0),
            ("`를` 现在在库里", q("SELECT COUNT(*) FROM dict WHERE word='를'"), 1)]:
        mark = "✅" if got == want else "🔴"
        red += got != want
        print("   %s %-30s %9s  期望 %9s" % (mark, name, f(got), f(want)))
    con.close()
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


if __name__ == "__main__":
    main()
