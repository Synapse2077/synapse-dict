#!/usr/bin/env python3
"""阶段 5b —— 三版收割语义关系 + `soft-redirect` 异表记 → `sense_relation`。2026-09-15。

═══ 两批东西，判据完全不同 ═══
**① 语义关系**（同义/反义/上位/下位/派生/相关…）
    英文版  义项级 109,657 ＋ 顶层 59,686   ← **唯一有义项级的一版**
    日语版  顶层 130,992
    中文版  顶层  42,302

**② `soft-redirect` 异表记**（`暗い` → `くらい`）
    目标=1   38,738 条 ⇒ 收，`kind='alt_of'`
    目标≥2    7,288 条 ⇒ **不收**

🔴🔴 ②的第二档是 `JA_PLAN` §二.5 定死的：`いぬ → 犬 狗 戌 率寝 寝ぬ 去ぬ` 是**同音索引页**，
   六个毫不相干的词。把 n≥2 当异体写进关系层，等于断言 `犬` 和 `去ぬ` 是异体字 ——
   **7,288 条规模的错**。一刀切（"都是 soft-redirect，都当异体"）看着省事，
   而省下的那一步正是唯一要紧的那一步。

═══ 🔴 顶层关系一律 `sense_id=NULL`，不靠 `_dis1` 往义项上挂 ═══
kaikki 的顶层关系带 `_dis1`（`'2 96 2'` ＝ 96% 概率属于第 2 条义项）。
拿它挂义项能多挂 6 万条，但那是**概率**不是事实 ——
`[[verification-gates-not-sampling]]`：**义项错配比缺一条严重得多**，
es 那轮自动判重 186 条里 12.4% 是错配。⇒ 顶层的就老实待在词条级。

═══ 🔴 `word` 字段里粘着释义，而且有两种形状 ═══
    `手痛い: severe`                          ← 词 + 粘着的英文释义（5,074 条）
    `蟻の物参り: → a metaphor likening ants…`   ← 同上，更长
    `a metaphor for a large group of people`  ← **整条就是英文释义，没有词**
    `[noun] Lua execution error in Module:…`  ← 维基模板报错泄漏进数据

前两种切 `: ` 就好；后两种必须丢。**判据按含义不按长度**：
`len(word) > 40` 是形状代理，会连 `蟻の穴より堤の崩れ` 这种真谚语一起砍
（`[[criteria-from-meaning-not-form]]`）。
⇒ 判据是「**切完之后，整串是由空格分开的多个拉丁词**」—— 那是英文句子，不是日语词条。
⚠️ 不能简单写「没有日文字符就丢」：`GNP`／`AA`／`OA`／`new` 都是**库里真实存在的日语词条**
   （`new` 甚至是个 soft-redirect 词头）。区别在**有没有空格**：日语词条不是英文句子。

用法（在仓库根）：
    python3 -u ja/pipeline/harvest_relations.py
    python3 -u ja/pipeline/harvest_relations.py --apply
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

f = lambda n: format(n, ",")
KIND = {"synonyms": "synonym", "antonyms": "antonym", "hypernyms": "hypernym",
        "hyponyms": "hyponym", "holonyms": "holonym", "meronyms": "meronym",
        "derived": "derived", "related": "related",
        "coordinate_terms": "coordinate", "proverbs": "proverb",
        "abbreviations": "abbreviation"}
JA = re.compile(r"[ぁ-ゖァ-ヺ一-鿿々〆ヶ]")
LATIN_PHRASE = re.compile(r"^[^぀-ヿ一-鿿]*\s[^぀-ヿ一-鿿]*$")


def clean_target(w):
    """→ 干净的目标词，或 None（这条不是词）。

    🔴 顺序要紧：**先切粘着的释义，再判是不是英文句子**。
       反过来的话 `蟻の物参り: → a metaphor likening ants in single file…` 整条带空格，
       会被当英文句子丢掉 —— 而它切完是个正经的日语谚语。
    """
    w = (w or "").strip()
    if not w:
        return None
    for sep in (": ", "：", ":　"):
        if sep in w:
            w = w.split(sep, 1)[0].strip()
            break
    if not w or "\n" in w:
        return None
    # 整串没有日文字符、且**带空格** ⇒ 英文释义/模板报错，不是词条。
    # （`GNP`/`AA`/`new` 没有空格，留下 —— 它们是库里真实存在的日语词条）
    if not JA.search(w) and " " in w:
        return None
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    bridge = collections.defaultdict(dict)
    for src, word, text, sid in con.execute(
            "SELECT g.src, d.word, g.text, g.sense_id FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "WHERE g.src NOT LIKE 'model:%'"):
        bridge[src].setdefault((word, text), sid)
    con.close()

    st = collections.Counter()
    rows = {}                      # (word_id, sense_id, kind, target) -> 行

    def add(w, sid, kind, tgt, tags, src, ref):
        i = wid.get(w)
        if i is None:
            st[src + "/词形不在库里"] += 1
            return
        k = (i, sid, kind, tgt)
        if k in rows:
            st[src + "/重复"] += 1
            return
        if tgt == w:
            st[src + "/🔴 丢：指向自己"] += 1
            return
        rows[k] = (i, sid, kind, tgt, tags, 0, src, ref)
        st[src + "/收下 " + kind] += 1

    ED = [("en-edition", lambda: open(paths.KK, encoding="utf-8"), None),
          ("ja-edition", lambda: open(paths.EDITION, encoding="utf-8"), None),
          ("zh-edition", lambda: gzip.open(paths.ZH_EDITION, "rt", encoding="utf-8"), "ja")]
    for src, op, lc in ED:
        br = bridge.get(src, {})
        with op() as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if lc and o.get("lang_code") != lc:
                    continue
                w = o.get("word") or ""
                # ── ② soft-redirect ──
                if o.get("pos") == "soft-redirect":
                    r = o.get("redirects") or []
                    if len(r) == 1:
                        t = clean_target(r[0])
                        if t:
                            add(w, None, "alt_of", t, None, src,
                                "%s:redirect:%s" % (src, w))
                    elif len(r) >= 2:
                        # 🔴 同音索引页：**不当异表记收，但要当「参见」收**。
                        #    §二.5 禁止的是「断言 `犬` 和 `去ぬ` 是异体字」，
                        #    不是"这一页不许存在"。整条丢掉的代价我实测过：
                        #    157 个词形变成搜得到、点进去**真空白**，而它们是
                        #    `関わる`／`我儘`／`スルメ`／`船唄` 这种正经词。
                        #    ⇒ `kind='see_also'`：不断言同一性，只说"这几个词都念这个音"——
                        #      那正是源头说它是的东西，也正是读者需要的那一页。
                        for x in r:
                            t = clean_target(x)
                            if t:
                                add(w, None, "see_also", t, None, src,
                                    "%s:index:%s:%s" % (src, w, t))
                        st[src + "/⚪ 同音索引页 ⇒ see_also（不断言异体）"] += 1
                    continue
                # ── ① 语义关系 ──
                for key, kind in KIND.items():
                    for it in (o.get(key) or []):
                        t = clean_target(it.get("word"))
                        if not t:
                            st[src + "/🔴 丢：不是词（英文释义/模板报错）"] += 1
                            continue
                        add(w, None, kind, t, None, src,
                            "%s:top:%s:%s:%s" % (src, w, kind, t))
                    for s in o.get("senses") or []:
                        gl = ((s.get("glosses") or [""])[0] or "").strip()
                        sid = br.get((w, gl))
                        for it in (s.get(key) or []):
                            t = clean_target(it.get("word"))
                            if not t:
                                st[src + "/🔴 丢：不是词（英文释义/模板报错）"] += 1
                                continue
                            add(w, sid, kind, t, None, src,
                                "%s:sense:%s:%s:%s:%s" % (src, w, sid, kind, t))

    # 🔴🔴 **同音索引页的判据必须在聚合之后再判一次。**
    #    §二.5 的规矩是「一个词形指向 ≥2 个目标 ⇒ 同音索引页，不是异表记」。
    #    我把它实现成「**一条 kaikki 词条**的 `redirects` 有几个目标」——
    #    那是英文版的序列化方式。**中文版把同一张索引页拆成了多条词条、每条一个目标**，
    #    于是 `いる → 入る / 射る / 煎る / 要る / 鋳る` 五条各自 `len(r)==1`，
    #    全部通过了逐条判据，聚合起来正是判据要挡的那个东西（287 个词形）。
    #    ⇒ 同一条规矩、两种序列化，判据只认得其中一种
    #      （`[[decision-not-propagated-across-editions]]`）。判据要打在**含义**上：
    #      「这个词形最终指向几个目标」，而不是「源头某一行里写了几个目标」。
    by_word = collections.defaultdict(set)
    for (i, sid, kind, tgt) in rows:
        if kind == "alt_of":
            by_word[i].add(tgt)
    multi = {i for i, t in by_word.items() if len(t) > 1}
    if multi:
        # 聚合后才现形的那批，同样**降级成 see_also，不是删掉**（理由同上）。
        for k in [k for k in rows if k[2] == "alt_of" and k[0] in multi]:
            i, sid, kind, tgt = k
            row = rows.pop(k)
            k2 = (i, sid, "see_also", tgt)
            rows.setdefault(k2, (i, sid, "see_also", tgt, *row[4:]))
        st["⚪ 同音索引页（聚合后 ≥2 目标）⇒ see_also"] += len(multi)

    out = list(rows.values())
    for k in sorted(st):
        print("   %-48s %s" % (k, f(st[k])))
    onsense = sum(1 for r in out if r[1])
    resolved = sum(1 for r in out if r[3] in wid)
    print("\n■ 关系 %s 条｜挂到义项 %s (%.1f%%)｜目标在库里 %s (%.1f%%)"
          % (f(len(out)), f(onsense), 100 * onsense / max(len(out), 1),
             f(resolved), 100 * resolved / max(len(out), 1)))
    alt = sum(1 for r in out if r[2] == "alt_of")
    print("■ 其中异表记 alt_of %s 条" % f(alt))
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        return

    old = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True).execute(
        "SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    with dbtool.session("ja-harvest-relations", expect={
            "#sense_relation": len(out) - old, "#dict": 0, "#entry": 0,
            "#sense": 0, "#example": 0}) as con:
        con.execute("DELETE FROM sense_relation")
        con.executemany(
            "INSERT OR IGNORE INTO sense_relation"
            "(word_id,sense_id,kind,target,tags,hidden,src,src_ref) "
            "VALUES(?,?,?,?,?,?,?,?)", out)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("word_id 都指向存在的词形", q(
            "SELECT COUNT(*) FROM sense_relation r LEFT JOIN dict d ON d.id=r.word_id "
            "WHERE d.id IS NULL") == 0),
        ("sense_id 非空时都指向存在的义项", q(
            "SELECT COUNT(*) FROM sense_relation r LEFT JOIN sense s ON s.id=r.sense_id "
            "WHERE r.sense_id IS NOT NULL AND s.id IS NULL") == 0),
        ("挂上的义项与关系是同一个词", q(
            "SELECT COUNT(*) FROM sense_relation r JOIN sense s ON s.id=r.sense_id "
            "WHERE s.word_id<>r.word_id") == 0),
        ("没有指向自己的关系", q(
            "SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id "
            "WHERE d.word=r.target") == 0),
        # 🔴 这条直接断言 §二.5 那个决定，而不是断言"alt_of 有多少条"。
        #    判据要写**目的**不是目的的代理（`[[proxy-metric-gets-optimized]]`）。
        # 断言的是**目的**：没有任何词形被断言成 ≥2 个不同词的异体。
        ("同音索引页一条都没混进异表记（它们在 see_also 里）", q(
            "SELECT COUNT(*) FROM (SELECT word_id FROM sense_relation "
            "WHERE kind='alt_of' GROUP BY word_id HAVING COUNT(*)>1)") == 0),
        ("目标不是英文句子（没有含空格的纯拉丁目标）", sum(
            1 for (t,) in con.execute("SELECT DISTINCT target FROM sense_relation")
            if not JA.search(t) and " " in t) == 0),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    for kind, n in con.execute(
            "SELECT kind, COUNT(*) FROM sense_relation GROUP BY 1 ORDER BY 2 DESC"):
        print("   %-14s %s" % (kind, f(n)))
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
