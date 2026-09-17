#!/usr/bin/env python3
"""阶段 3a：跨版收词。零模型调用。2026-09-15。

═══ 收什么 ═══
日语版与中文版有真义项、而我们没有的词形 —— 实测 **127,211 个**
（日语版独有 58,849 ／中文版独有 60,413 ／两版都有 7,949）。
对照库内词元 86,902，是 146% 的增量。

⚠️ 另有 **4,523 个**词形我们当**变形**收着（`is_lemma=0`），而日语版说它有真义项
   —— 那批要**升格**不是新插（照 es 的做法：不许把词元和变形混为一行）。

═══ 🔴🔴 收完必须回头重连 `inflection.base_id` ═══
阶段 2 建变形层时，221,135 行的原形不在库里（指向 14,658 个词元），`base_id` 留空。
收词把它们补进来了 ⇒ **本步最后一件事是重连**。
`base` 是原样存的文本，一条 UPDATE 就够，不用重跑整层。
⚠️ **pt 正是栽在这个顺序上**：变形层建在收词之前，收进来的 30 万变形从此没人连线，
   355,605 个词形（46.2%）既无义项也无变形链＝搜得到、点进去空白页。

═══ 释义只留三语，且**不跨版合并义项** ═══
日语版给日语原文定义、中文版给中文释义。**同一个词两版都有时取日语版**，
不做跨版义项配对 —— 那是 `[[verification-gates-not-sampling]]` 说的那类灾难
（义项错配比缺一条严重得多），而 1.5a 已经量过：做更好的对齐最多省 4 块钱。

═══ 中文版的 gloss 带结构残渣，要洗 ═══
    作用空間 → 「作用空間【さようくうかん】\\n作用空间。」   词头+读音混进释义
    外寸   → 「外寸【がいすん】\\n外径尺寸。==日语==…」    还带维基章节标记
实测已落库的 13,250 条里有 23 条带换行、10 条带【】、9 条带 ==（0.2%）—— 本步一并洗掉。

跑（在仓库根）：
    python3 -u ja/pipeline/intake_edition_words.py
    python3 -u ja/pipeline/intake_edition_words.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import gzip
import json
import re
import sqlite3

import dbtool
import paths
from pipeline.build import norm_ja
# 🔴 词性映射**只许一份** —— 2026-09-16 之前这个文件里另有一张更短的表，
#    于是 3a 收的词落了原始码（`proverb`/`adnominal`/`symbol`/`syllable`/`abbrev`…），
#    与阶段 1 落的 `prov`/`adnom`/`sym`/`kana` 在库里并存：
#    **同一个概念两个码**，展示层分成两组、其中一组印英文。
from pipeline.build_entry_layer import POS_MAP

POINTER = ("form-of", "alt-of", "romanization")
# ══════ 中文版 gloss 的结构残渣 —— 五种形状，量过才写判据 ══════
# 147,338 条 gloss 里：干净 71.84%／`词头【读音】`+换行 27.40%／汉字等级 309 条／
# `==章节==` 434 条／**一格塞 ≥2 条编号义项 4,576 条（3.1%）**。
#
# 🔴 **【】不一定是读音。** 80 条里的【】是**学科标签或用法注**：
#       `【數學】【化學】 公式`        `忽略，放松【多用「お～になる」的形式】`
#    ⇒ 只在「整行恰好是 `词头【假名】`」时才剥，且**括号内必须含假名**。
#    第一版写的是 `startswith(word)` 就剥 —— 把 `基本システム【きほん system】`
#    啃成了 `きほん system】`。抽样当场逮到（`[[criteria-narrower-than-you-think]]`）。
HEAD_READING = re.compile(r"^\S*【[^】]*[ぁ-ゖァ-ヺー][^】]*】$")
# 🔴 `===A======B===` 里中间那串 `=` 被**两个章节共享**，`==+[^=\n]*==+` 贪婪地
#    吃掉前一个章节和共享的 `======`，剩下 `B===` 原地留着。
#    2026-09-16 阶段 7 的回归闸报出来的（`===Etymology 4======Etymology 5===`）。
#    ⚠️ **同一个模式 `ja/fixes/fix_gloss_residue.py` 也要用 ⇒ 那边 import 这一份，
#       不许再写一遍**（`[[etymology-layer-acceptance]]`：同一个假设写在两处、
#       只改一处，三层全绿而端到端才逮到）。
SECTION = re.compile(r"(?:={2,}[^=\n]*)+={2,}")
GRADE_ONLY = re.compile(r"^（[^）]*漢字[^）]*）$")
NUMBERED = re.compile(r"^\s*\d+[.．、]\s*")
POS_LINE = re.compile(r"^[名動形副助接感代連他自サ変五一下上·・]{1,8}$")


def clean_gloss(g, word):
    """→ [释义, …]（可能多条：一格塞了多条编号义项时拆开）。空列表＝这条不是释义。

    🔴 **只删结构，不改内容一个字。**拆出来的每条是独立义项，不是把它们拼成一串。
    """
    lines = [x.strip() for x in SECTION.sub("", g or "").split("\n") if x.strip()]
    out, dropped = [], False
    for i, ln in enumerate(lines):
        if i == 0 and HEAD_READING.match(ln):
            dropped = True
            continue                       # `大臣【だいじん】` 抬头
        if GRADE_ONLY.match(ln):
            dropped = True
            continue                       # `（常用漢字）` 是字种等级不是释义
        if POS_LINE.match(ln):
            dropped = True
            continue                       # `名·他サ` 是词性行
        out.append(ln)
    # 🔴 洗掉结构行之后**只剩词头本身** ⇒ 那是条目存根不是释义（`鈹\n（表外漢字）`）。
    #    ⚠️ 但**单行、整条就等于词头**的要留：那是同形汉语词（`英語` → `英語`），
    #       日语汉字词与汉语大量同形同义 —— 判据的差别在于「有没有别的结构行被删掉」。
    if dropped and out == [word]:
        return []
    if not out:
        return []
    # 一格塞了 ≥2 条编号义项 ⇒ 拆成多条；例句行（不带编号、跟在编号行后面）丢掉
    nums = [x for x in out if NUMBERED.match(x)]
    if len(nums) >= 2:
        # 🔴 去掉编号之后可能什么都不剩（`1.` 单独成行）—— 那种不是义项。
        #    第一版没滤，5 条空释义落了库，写后回核当场报红。
        return [x for x in (NUMBERED.sub("", y).strip() for y in nums) if x]
    return [out[0]]


def _assert_ja():
    assert paths.DB.name == "synapse-dict-ja.sqlite", "🔴 paths 不是 ja 的：%s" % paths.DB
    assert not hasattr(dbtool, "has_han"), "🔴 dbtool 不是 ja 的"


def real_senses(o):
    out = []
    for s in (o.get("senses") or []):
        tg = s.get("tags") or []
        if s.get("form_of") or s.get("alt_of") or any(t in POINTER for t in tg):
            continue
        g = [x for x in (s.get("glosses") or []) if x and x.strip()]
        if g:
            out.append((g[0].strip(), tg))
    return out


def scan(have):
    """→ {word: (src, pos, [(gloss, tags), …])}。同词两版都有时**取日语版**。"""
    got = {}
    for line in open(paths.EDITION, encoding="utf-8"):
        o = json.loads(line)
        w = (o.get("word") or "").strip()
        if not w or w in got:
            continue
        ss = real_senses(o)
        if ss:
            got[w] = ("ja-edition", o.get("pos"), ss)
    for line in gzip.open(paths.ZH_EDITION, "rt", encoding="utf-8"):
        if '"lang_code": "ja"' not in line:
            continue
        o = json.loads(line)
        if o.get("lang_code") != "ja":
            continue
        w = (o.get("word") or "").strip()
        if not w or w in got:
            continue
        ss = [(x, tg) for g, tg in real_senses(o) for x in clean_gloss(g, w)]
        if ss:
            got[w] = ("zh-edition", o.get("pos"), ss)
    return got


def main():
    _assert_ja()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {w: (i, l) for w, i, l in con.execute("SELECT word, id, is_lemma FROM dict")}
    dangling = con.execute(
        "SELECT COUNT(*) FROM inflection WHERE base_id IS NULL").fetchone()[0]
    dirty = con.execute(
        "SELECT COUNT(*) FROM sense_gloss WHERE src='zh-edition' AND ("
        "instr(text, char(10))>0 OR text LIKE '%【%' OR text LIKE '%==%')").fetchone()[0]
    con.close()

    got = scan(have)
    new = {w: v for w, v in got.items() if w not in have}
    upgrade = {w: v for w, v in got.items() if w in have and have[w][1] == 0}
    stat = collections.Counter()
    for w, (src, pos, ss) in new.items():
        stat["新词·" + src] += 1
        stat["新义项·" + src] += len(ss)
    print("■ 两版有真义项的词形 %s" % f"{len(got):,}")
    print("   🔴 我们没有的（新插）  %s" % f"{len(new):,}")
    print("   ⚠️ 当变形收着的（升格）  %s" % f"{len(upgrade):,}")
    for k, v in sorted(stat.items()):
        print("   %-22s %9s" % (k, format(v, ",")))
    print("   ⇒ dict %s → %s ｜词元 %s → %s"
          % (f"{len(have):,}", f"{len(have) + len(new):,}",
             f"{sum(1 for v in have.values() if v[1]):,}",
             f"{sum(1 for v in have.values() if v[1]) + len(new) + len(upgrade):,}"))
    print("   ⇒ 待重连的 `base_id` 悬空行 %s ｜待洗的中文版残渣 %s"
          % (f"{dangling:,}", f"{dirty:,}"))

    dbtool.sample_check(
        [(w, v[0], v[1] or "?", v[2][0][0][:40]) for w, v in list(new.items())[::max(1, len(new) // 16)]],
        12, ("词形", "来源", "词性", "首条释义"))
    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    # ── 先把已落库的中文版残渣洗掉（42 条），再插新词 ──
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    fix, drop = [], []
    for gid, sid, txt, w in con.execute(
            "SELECT g.rowid, g.sense_id, g.text, d.word FROM sense_gloss g"
            " JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id"
            " WHERE g.src='zh-edition' AND (instr(g.text, char(10))>0"
            " OR g.text LIKE '%【%' OR g.text LIKE '%==%')"):
        c = clean_gloss(txt, w)
        if not c:
            drop.append((gid,))
        elif c[0] != txt:
            fix.append((c[0], gid))
    con.close()
    print("\n■ 已落库残渣：洗好 %d 条 ｜整条丢弃 %d 条" % (len(fix), len(drop)))

    words = sorted(new)
    n_sense = sum(len(v[2]) for v in new.values())
    # 🔴 收词闸（2026-09-16 加）：插新词形必须声明让哪些层过期了。
    #    这一步当年**正是**让中文覆盖 98.66% → 70.77%、读音覆盖 99.90% → 39.8% 的那一步。
    with dbtool.session("ja-intake-edition-words", invalidates=[
            "义项的中文覆盖率", "词元的假名读音覆盖率", "**不是**空白页的词形占比",
            "变形层 inflection.base_id（收词补进来的原形要重连）"], expect={
            "__rows__": len(words), "pos": len(words),
            "#entry": len(words), "#sense_src": n_sense, "#sense": n_sense,
            "#sense_gloss": n_sense - len(drop)}) as s:
        s.executemany("UPDATE sense_gloss SET text=? WHERE rowid=?", fix)
        s.executemany("DELETE FROM sense_gloss WHERE rowid=?", drop)
        # ① 升格：当变形收着、别的版说它有真义项 ⇒ is_lemma 0→1（**不新建行**）
        s.executemany("UPDATE dict SET is_lemma=1 WHERE word=?", [(w,) for w in upgrade])
        # ② 新词进 dict
        s.executemany("INSERT INTO dict (word, word_norm, is_lemma, pos) VALUES (?,?,1,?)",
                      [(w, norm_ja(w), POS_MAP.get(new[w][1], new[w][1] or "unknown"))
                       for w in words])
        wid = {w: i for i, w in s.execute("SELECT id, word FROM dict")}
        # ③ entry：一词一条（这两版不给词源号，etym_no 记 "0"）
        s.executemany(
            "INSERT INTO entry (word_id, word_src, pos, pos_raw, etym_no, seq, src, src_ref)"
            " VALUES (?,?,?,?,'0',0,?,?)",
            [(wid[w], w, POS_MAP.get(new[w][1], new[w][1] or "unknown"),
              new[w][1] or "unknown", new[w][0], "%s:%s:%s:0:0" % (new[w][0], w, new[w][1]))
             for w in words])
        eid = {r: i for i, r in s.execute("SELECT id, src_ref FROM entry")}
        srcs, senses, glosses = [], [], []
        for w in words:
            src, pos, ss = new[w]
            e = eid["%s:%s:%s:0:0" % (src, w, pos)]
            for k, (g, tg) in enumerate(ss):
                lang = "ja" if src == "ja-edition" else "zh"
                srcs.append((wid[w], src, "%s:%s:%s:0:0#%d" % (src, w, pos, k), lang, g,
                             json.dumps(tg, ensure_ascii=False) or None))
                senses.append((wid[w], e, k + 1,
                               POS_MAP.get(pos, pos or "unknown")))
                glosses.append((wid[w], k + 1, lang, "definition", 0, g, src))
        s.executemany("INSERT INTO sense_src (word_id, sense_id, src, src_ref, lang, text,"
                      " raw_tags) VALUES (?,NULL,?,?,?,?,?)", srcs)
        s.executemany("INSERT INTO sense (word_id, entry_id, rank, pos) VALUES (?,?,?,?)", senses)
        s.execute("CREATE TEMP TABLE _g(word_id INT, rank INT, lang TEXT, kind TEXT,"
                  " seq INT, text TEXT, src TEXT)")
        s.executemany("INSERT INTO _g VALUES (?,?,?,?,?,?,?)", glosses)
        s.execute("INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src)"
                  " SELECT s.id, g.lang, g.kind, g.seq, g.text, g.src FROM _g g"
                  " JOIN sense s ON s.word_id=g.word_id AND s.rank=g.rank")
        # ④ 🔴🔴 重连 `inflection.base_id` —— **pt 栽过的那个顺序错**
        s.execute("CREATE TEMP TABLE _b(base TEXT PRIMARY KEY, id INT)")
        s.execute("INSERT INTO _b SELECT word, id FROM dict")
        s.execute("UPDATE inflection SET base_id="
                  "(SELECT b.id FROM _b b WHERE b.base=inflection.base)"
                  " WHERE base_id IS NULL")

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    left = q("SELECT COUNT(*) FROM inflection WHERE base_id IS NULL")
    blank = q("SELECT COUNT(*) FROM dict d WHERE NOT EXISTS(SELECT 1 FROM sense s"
              " WHERE s.word_id=d.id) AND NOT EXISTS(SELECT 1 FROM inflection i"
              " WHERE i.word_id=d.id)")
    tot = q("SELECT COUNT(*) FROM dict")
    print("\n═══ 写后回核 ═══")
    print("   ⭐ `base_id` 悬空 %s → %s（重连了 %s 行）"
          % (f"{dangling:,}", f"{left:,}", f"{dangling - left:,}"))
    print("   ⭐ 点进去空白页的词形 %s / %s = %.2f%%" % (f"{blank:,}", f"{tot:,}", 100 * blank / tot))
    for name, got, want in [
        ("孤儿 entry", q("SELECT COUNT(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id"
                        " WHERE d.id IS NULL"), 0),
        ("孤儿 sense", q("SELECT COUNT(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id"
                        " WHERE d.id IS NULL"), 0),
        ("每条 sense 都有 gloss", q("SELECT COUNT(*) FROM sense s WHERE NOT EXISTS("
                                 "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id)"), 0),
        ("中文版残渣（换行/【】/==）", q("SELECT COUNT(*) FROM sense_gloss WHERE src='zh-edition'"
                               " AND (instr(text,char(10))>0 OR text LIKE '%==%')"), 0)]:
        print("   %s %-30s %10s（期望 %s）" % ("✅" if got == want else "🔴", name,
                                             format(got, ","), format(want, ",")))
    con.close()


if __name__ == "__main__":
    main()
