#!/usr/bin/env python3
"""阶段 3b：收 ECDICT 补充词 + 建 `legacy_gloss` 词条级释义层。2026-09-07。

用户 2026-09-07 定的**方案 D**：全收 + 分层出版。零 API 成本、纯确定性。

═══ 为什么必须收（不收是倒退）═══
这批词在 kaikki 里**一个词条都没有** —— `microcellular rubber [化] 微孔橡胶`、
`bath carburizing [机] 炉浴增炭`、`Vitis wuhanensis n. 武汉葡萄`。
用户定的分工里，「ECDICT 多了很多专业词汇」指的就是它们。
现有产品划词能查到，v3 之后查不到 ＝ **倒退**。
🔴 `FRAMEWORK` 说「错比缺更伤权威」；而**倒退比缺更伤信任**。

═══ 🔴 但它们没有义项 ⇒ 中文必须有地方落 ═══
收进 `dict` 而中文无处安放 ＝ 262 万个**完全空白页**，比不收更糟。
⇒ 建 `legacy_gloss`（**词条级**，不是义项级）：

  · 与 `EN_PLAN` §〇 不冲突 —— 那条定的是「ECDICT 中文**不进 `sense_gloss`**」（不进义项层）；
    词条级另建一张表，展示层能清楚标注「本条来自 ECDICT，非本版义项」。
  · 对**有 kaikki 义项**的词，这张表同时是 §〇 说的**验收负控**（五门都没有的东西）。

`published` 一列把「显不显示」变成可逆开关（`[[prefer-reversible-designs]]`）：
    qual='low'（20.8 万，抽样 bad≈39%）          → 0
    该词形已有 v3 义项（ECDICT 中文降级为负控）    → 0
    其余                                        → 1

═══ 🔴 纯变形空壳不收（35,941 条）═══
它们唯一的内容是 `(genus chlorophyllum 的复数)` —— 而这个信息**变形层已经有了**。
收进来就是重新制造项目花了几个月清掉的那种空壳。

判据被数据打回**四次**，每次都是漏了一族，逐条验过两个方向才定：
  ① 只看 `"的复数" in t and len<40`     → 把 `<方> v. 发生（'appen 即 happen 的过去式…）` 判成空壳（**丢好数据**）
  ② 加词性前缀剥离 + 首尾锚            → 漏 `(chumbawamba 的复数)` 带括号一族
  ③ 加括号剥离                        → 漏 `(ni-hard iron 的复数)` **多词原形**一族
  ④ 放开空格 + 要求原形**不含汉字**      → 定稿（否则 `很大的变形` 这种真中文会被误判）
⚠️ 两个方向的代价不对称：**漏判只是多收噪声**（`qual` 分层兜得住），
   **误判是丢好词条**。所以判据宁可窄。

跑：
    cd en && python3 pipeline/intake_legacy.py
    cd en && python3 pipeline/intake_legacy.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import re
import sqlite3

import dbtool
import paths
from word_norm import norm_en

SRC = "ecdict"

# ── 空壳判据（判据只许这一份）──
POSPFX = re.compile(r"^\s*(?:<[^>]{1,6}>\s*)?(?:[a-z]{1,5}\.\s*)*")
PARENS = re.compile(r"^[（(]\s*(.*?)\s*[）)]$")
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
META = re.compile(r"^(.{1,60}?)\s*的\s*(?:复数|单数|过去式|过去分词|现在分词|"
                  r"第三人称单数|现在时第三人称单数|最高级|比较级|变形|变化形式)(?:形式)?\s*$")


def is_shell_line(l):
    l = POSPFX.sub("", l.strip())
    m = PARENS.match(l)
    if m:
        l = m.group(1)
    m = META.match(l)
    # 原形必须是拉丁词形（可含空格/连字符），**不含汉字** —— 否则真中文会被误判
    return bool(m) and not HAN.search(m.group(1))


def is_shell(t):
    if not t or not t.strip():
        return True
    return all(is_shell_line(l) for l in t.split("\n") if l.strip())


# ECDICT 的 pos 是 `j:100` / `j:94/n:6`，取权重最高的那个
EPOS = {"n": "n", "v": "v", "j": "adj", "r": "adv", "p": "pron", "i": "prep",
        "u": "intj", "m": "num", "c": "conj", "d": "det", "x": None}


def parse_pos(s):
    if not s:
        return None
    best, bw = None, -1
    for part in s.split("/"):
        k, _, w = part.partition(":")
        try:
            w = int(w)
        except ValueError:
            w = 0
        if w > bw and EPOS.get(k.strip()):
            best, bw = EPOS[k.strip()], w
    return best


DDL = """CREATE TABLE legacy_gloss (
    word_id   INTEGER PRIMARY KEY,   -- → dict.id（ECDICT 本来就一词一行）
    text      TEXT NOT NULL,         -- ECDICT 译文原文，**一个字节不改**
    qual      TEXT NOT NULL,         -- core/judged/fixed/good/fair/low（老库的质量分层）
    published INTEGER NOT NULL,      -- 0 = 默认不出版（low ／ 已有 v3 义项）
    src       TEXT NOT NULL
)"""
IDX = ["CREATE INDEX idx_lg_qual ON legacy_gloss(qual)",
       "CREATE INDEX idx_lg_pub ON legacy_gloss(published)"]


def collect():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    has_sense = {i for (i,) in con.execute("SELECT DISTINCT word_id FROM sense")}
    legacy = list(con.execute(
        "SELECT word, qual, translation, pos, exchange FROM legacy_dict"))
    con.close()

    new_rows, stat = [], collections.Counter()
    for w, qual, tr, pos, ex in legacy:
        if w in wid:
            stat["already"] += 1
            continue
        if is_shell(tr):
            stat["shell_skipped"] += 1
            continue
        infl = bool(ex) and any(p.startswith("0:") for p in ex.split("/"))
        new_rows.append((w, norm_en(w), 0 if infl else 1, parse_pos(pos)))
        stat["intake"] += 1
    stat["new_pos"] = sum(1 for r in new_rows if r[3])
    stat["new_lemma"] = sum(1 for r in new_rows if r[2])
    return new_rows, legacy, wid, has_sense, stat


def plan_gloss(legacy, wid, has_sense):
    """→ [(word_id, text, qual, published, src)]；覆盖**所有**映射得上的 legacy 行"""
    out = []
    for w, qual, tr, _pos, _ex in legacy:
        i = wid.get(w)
        if i is None or not (tr or "").strip():
            continue
        pub = 0 if (qual == "low" or i in has_sense) else 1
        out.append((i, tr, qual or "unknown", pub, SRC))
    return out


def report(checks):
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-40s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    n0 = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    # 🔴 收词前的最大 id：闸要用它把「本步新收的」与老行分开。
    #    **不许写死行数** —— 字面量闸 2026-09-07 当场逮到我把 589 写进期望位
    #    （而且那 589 是收词**之前**的空白页数，收完自然会变，属"非单调判据"，
    #      与账的闸那次「dict 必须为空」是同一个病）。
    maxid0 = con.execute("SELECT COALESCE(MAX(id),0) FROM dict").fetchone()[0]
    pos0 = con.execute("SELECT COUNT(*) FROM dict WHERE pos IS NOT NULL").fetchone()[0]
    nl = con.execute("SELECT COUNT(*) FROM legacy_dict").fetchone()[0]
    nsense0 = con.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
    blank0 = con.execute(
        "SELECT COUNT(*) FROM dict d WHERE"
        " NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
        " AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)").fetchone()[0]
    con.close()
    new_rows, legacy, wid, has_sense, stat = collect()

    print("═══ 阶段 3b 计划（方案 D：全收 + 分层出版）═══")
    print("   legacy 总行            %10s" % format(len(legacy), ","))
    print("   已在 dict（kaikki 有）   %10s" % format(stat["already"], ","))
    print("   🔴 纯变形空壳，不收       %10s" % format(stat["shell_skipped"], ","))
    print("   ⇒ 本步收词              %10s   dict %s → %s"
          % (format(stat["intake"], ","), format(n0, ","), format(n0 + stat["intake"], ",")))
    print("      其中 is_lemma=1      %10s   有 pos %s"
          % (format(stat["new_lemma"], ","), format(stat["new_pos"], ",")))
    if not run:
        print("\n   （legacy_gloss 的行数要等收词落库、word_id 齐了才算得准）")
        print("\n(干跑。加 --run 才写库)")
        return 0

    # ── 第一刀：收词
    with dbtool.session("keep-v3-3b-intake",
                        expect={"__rows__": stat["intake"], "pos": stat["new_pos"]}) as s:
        s.executemany("INSERT INTO dict (word, word_norm, is_lemma, pos) VALUES (?,?,?,?)",
                      new_rows)

    # ── 第二刀：legacy_gloss（word_id 现在才齐）
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    has_sense = {i for (i,) in con.execute("SELECT DISTINCT word_id FROM sense")}
    con.close()
    gl = plan_gloss(legacy, wid, has_sense)
    npub = sum(1 for r in gl if r[3])
    print("\n   legacy_gloss 将写 %s 行（出版 %s ／ 不出版 %s）"
          % (format(len(gl), ","), format(npub, ","), format(len(gl) - npub, ",")))
    with dbtool.session("keep-v3-3b-legacygloss", expect={"#legacy_gloss": len(gl)}) as s:
        if "legacy_gloss" not in have:
            s.execute(DDL)
            for i in IDX:
                s.execute(i)
        s.executemany("INSERT INTO legacy_gloss (word_id, text, qual, published, src) "
                      "VALUES (?,?,?,?,?)", gl)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n═══ 闸② ═══")
    bad = report([
        ("dict 行数", q("SELECT COUNT(*) FROM dict"), n0 + stat["intake"]),
        ("词形仍唯一", q("SELECT COUNT(DISTINCT word) FROM dict"), n0 + stat["intake"]),
        ("legacy_gloss 行数", q("SELECT COUNT(*) FROM legacy_gloss"), len(gl)),
        ("legacy_gloss.word_id 全落在 dict 上",
         q("SELECT COUNT(*) FROM legacy_gloss g LEFT JOIN dict d ON d.id=g.word_id "
           "WHERE d.id IS NULL"), 0),
        ("low 全部不出版",
         q("SELECT COUNT(*) FROM legacy_gloss WHERE qual='low' AND published=1"), 0),
        ("已有 v3 义项的全部不出版（降级为负控）",
         q("SELECT COUNT(*) FROM legacy_gloss g WHERE g.published=1 AND EXISTS"
           "(SELECT 1 FROM sense s WHERE s.word_id=g.word_id)"), 0),
        # 🔴 本步新收的词**一个都不许是空白页** —— 这是方案 D 成立的前提：
        #    收进来而中文无处安放 ＝ 262 万个空白页，比不收更糟。
        ("🔴 本步新收的词零空白页",
         q("SELECT COUNT(*) FROM dict d WHERE d.id>%d"
           " AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
           " AND NOT EXISTS(SELECT 1 FROM legacy_gloss g WHERE g.word_id=d.id)"
           " AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)" % maxid0), 0),
        ("⚠️ 全库残余空白页（收词前 %d，只许降不许升）" % blank0,
         min(q("SELECT COUNT(*) FROM dict d WHERE"
               " NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
               " AND NOT EXISTS(SELECT 1 FROM legacy_gloss g WHERE g.word_id=d.id)"
               " AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)"), blank0), 
         q("SELECT COUNT(*) FROM dict d WHERE"
           " NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
           " AND NOT EXISTS(SELECT 1 FROM legacy_gloss g WHERE g.word_id=d.id)"
           " AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)")),
        ("译文一个字节不改（抽 legacy 对比）",
         q("SELECT COUNT(*) FROM legacy_gloss g JOIN dict d ON d.id=g.word_id "
           "JOIN legacy_dict l ON l.word=d.word WHERE l.translation<>g.text"), 0),
        ("legacy_dict 未被触碰", q("SELECT COUNT(*) FROM legacy_dict"), nl),
        ("sense 未被触碰", q("SELECT COUNT(*) FROM sense"), nsense0),
    ])
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
