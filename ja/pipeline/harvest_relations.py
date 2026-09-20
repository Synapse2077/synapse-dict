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
from pipeline.harvest_examples import simplified_only

f = lambda n: format(n, ",")
KIND = {"synonyms": "synonym", "antonyms": "antonym", "hypernyms": "hypernym",
        "hyponyms": "hyponym", "holonyms": "holonym", "meronyms": "meronym",
        "derived": "derived", "related": "related",
        "coordinate_terms": "coordinate", "proverbs": "proverb",
        "abbreviations": "abbreviation"}
JA = re.compile(r"[ぁ-ゖァ-ヺ一-鿿々〆ヶ]")


def is_chinese_target(it, src, simp):
    """这个关系目标是**中文**不是日语吗？→ True 就挂 `hidden=1`（不删，可逆）。

    🔴🔴 **三个版本三种机制，判据不能合并成一条。**（2026-09-19，欠账 15）

    ① **中文版**：`derived`/`related` 数组把**日语词与它的中文释义交替排列**，
       而中文那一半**只有 `word` 一个键、没有 `roman`/`ruby`**：

           {'word': '少女歌劇', 'roman': 'shōjo kageki', 'ruby': [...]}   ← 真词
           {'word': '年轻'}  {'word': '兴趣'}  {'word': '爱好'}            ← 中文释义碎片

       ⇒ 判据＝`裸（无 roman 无 ruby）` ∧ `含简体专用字`。实测**精确命中 81 条**，
       而 `唖呕`/`柜霜`/`蔂`（真日语拡張新字体）带 roman/ruby，正确避开。
       ⚠️ 「裸」单用太宽（6,744 条，含 `五月`/`早苗月` 这种真日语词），必须取交集。

    ② **日语版**：把日语写法与中文简体写法**成对列出**
       （`漢語`/`汉语`、`洗手間`/`卫生间`、`漢奸`/`汉奸`）⇒ 含简体专用字的那一半就是中文。

    ③ 🔴 **英文版一条都不许碰。** 那 40 条（`呕唖`/`丰容`/`柜霜`）**不是中文，是拡張新字体** ——
       源头把 `呕唖` 与 `嘔啞` 成对列在 `character` 条目下、tag 写着 `extended shinjitai`。
       我第一版把三版合成一条判据、差点把它们当中文删掉
       （`[[criteria-narrower-than-you-think]]` 的反面：**判据比它要描述的东西宽**）。
       `侭田`（姓氏，唯一已知的假阳性）也来自英文版 ⇒ 排除英文版自动躲开它。
    """
    w = (it.get("word") or "").strip()
    if not any(ch in simp for ch in w):
        return False
    if src == "zh-edition":
        return not it.get("roman") and not it.get("ruby")
    return src == "ja-edition"
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


# ── 2026-09-19（欠账 16）：目标里**含空格**的 2,029 条，一条判据管不了 ──
# 逐条看过之后是四种形状，每种的处置不同。判据写成「认得出哪一种」而不是「长得像不像词」。
# ① 并列表：`縞馬, 斑馬`。🔴 **只认半角逗号+空格，不认顿号。**
#    顿号在日语里是**句内标点**：`井の中の蛙、大海を知らず`／`一日の計は朝にあり、一年の計は元旦にあり`
#    是一条谚语不是两个目标。实测已落库的 297 条拆分**全部**来自半角逗号、顿号零条 ⇒
#    顿号分支在真列表上没用过，却会拆坏 50 多条谚语。**可逆性回核逮到的，不是闸。**
LIST_SEP = re.compile(r",\s+")
ROMAJI_PAREN = re.compile(r"^(.+?)\s*\(([A-Za-zāīūēōâîûêô'’\- ]+)\)$")   # ② `女郎 (jorō)`
ARROW = re.compile(r"\s*[→⇒]\s*")                     # ③ `兄様 → 兄さん` / `→ 襲`


LATIN = re.compile(r"[A-Za-z]")


def _one(w):
    """一个候选串 → 干净目标或 None。

    要求：有日文字符、不含空格、**且不混拉丁字母**。
    🔴 最后一条是抽样反验逼出来的：`ja-cardinals?action=edite Japanese numbers…` 这种
       模板残渣的末段是 `numbersNumberKanjiKanaRomaji0零れい` —— 有日文、无空格，
       前两条判据放它过去了。**日语词条不会把拉丁字母混在词里**（`GNP`/`AA` 是纯拉丁，
       走 `clean_target` 那条路，不经过这里）。
    """
    w = (w or "").strip(" 　\"”'’[]")
    if not w or " " in w or not JA.search(w) or LATIN.search(w):
        return None
    return w


def clean_targets(w):
    """→ **目标列表**（0…N 个）。`clean_target` 只能返回一个，装不下并列表。

    🔴 四种形状，顺序不能改（`[[regex-alternation-order]]`：顺序本身就是判据）：
      ① **并列表** `縞馬, 斑馬` ⇒ 拆成 2 个。⚠️ 拆出来**每一片都要过 `_one`**，
         否则 `割符(historically read as かちふ, today read as…)` 这种带逗号的散文
         会被拆成两段垃圾（实测 5 条，正好落到 ④）。
      ② **罗马字回显** `女郎 (jorō)` ⇒ 剥掉括号。欠账 13 清过**串尾**回显，
         带括号这个变体活了下来 —— **同一个病的第二种写法**。
      ③ **箭头** `兄様 → 兄さん`（两边都是词）/ `→ 襲`（左边空）/
         `胸を貸す → a more powerful person…`（右边是英文）⇒ 沿箭头切，留过得了 `_one` 的。
      ④ **前半是词、其后全无日文** `ごみ箱 rubbish bin`、`あたし 30%`（问卷百分比）
         ⇒ 取前半。
      ⑤ 剩下的是**活用构成公式**（`stem + い`、`mizenkei + ない`）与整句散文 ⇒ 返回空列表，
         调用方挂 `hidden=1` 而不是删（`[[prefer-reversible-designs]]`）。
    """
    w = clean_target(w)
    if not w:
        return []
    if " " not in w and "," not in w:
        return [w]
    # 🔴 **活用构成公式一律不是词**：`stem + い`、`mizenkei + ない`、`ren'yōkei + ましょう`。
    #    这条必须在 ④⑤ **之前**：镜像规则⑤会把 `ren'yōkei + ましょう` 的尾巴 `ましょう`
    #    当成词收下来 —— 那是活用后缀不是相关词。
    #    ⚠️⚠️ **必须在「无空格就原样返回」之后**：我验「含 `+` 的 40 个串全是公式」时
    #    只在**含空格的那批**上验过，却把它用到了全部目标上 ⇒ `C++`／`LGBT+`／`+α`
    #    这些真词条被误杀。**判据只在它被验过的域里成立**
    #    （`[[criteria-narrower-than-you-think]]`，同一天第三次）。
    if "+" in w:
        return []
    if LIST_SEP.search(w):
        parts = [_one(p) for p in LIST_SEP.split(w)]
        return [p for p in parts if p] if all(parts) else []
    m = ROMAJI_PAREN.match(w)
    if m and _one(m.group(1)):
        return [_one(m.group(1))]
    if ARROW.search(w):
        return [p for p in (_one(x) for x in ARROW.split(w)) if p]
    # ④ 前半是词、其后全无日文：`ごみ箱 rubbish bin`、`あたし 30%`
    first = w.split(" ")[0]
    head = _one(first)
    if head and not JA.search(w[len(first):]):
        return [head]
    # ⑤ **④ 的镜像**：后半是词、其前全无日文 —— `(2ch slang) セクースする`、
    #    `Ibaraki) しぐ`、`and see ちんぽこ`。日语在末尾时 ④ 认不出来，
    #    而这一族是**标签前缀/引导语**，丢掉就等于丢掉一个真词。
    last = w.split(" ")[-1]
    tail = _one(last)
    pre = w[:len(w) - len(last)]
    # ⚠️ 前缀必须**像标签**（以 `)`/`]` 收尾）或**很短**，否则就是在从整句英文里抠尾巴：
    #    `that consists of suffixing verbs with the auxiliary… 遊ばせ` 不该变成 `遊ばせ`。
    if tail and not JA.search(pre) and (pre.rstrip().endswith((")", "]")) or len(pre) <= 12):
        return [tail]
    return []


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

    # 简体专用字表 —— **import 例句层那一份，不新写**（`[[refactor-mindset-code-quality]]`）
    con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    SIMP = simplified_only(con2)
    con2.close()

    st = collections.Counter()
    rows = {}                      # (word_id, sense_id, kind, target) -> 行

    def add(w, sid, kind, tgt, tags, src, ref, hidden=0):
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
        rows[k] = (i, sid, kind, tgt, tags, hidden, src, ref)
        st[src + ("/⚪ 中文目标⇒hidden " if hidden else "/收下 ") + kind] += 1

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
                        ts = clean_targets(it.get("word"))
                        if not ts:
                            st[src + "/🔴 丢：不是词（英文释义/模板报错）"] += 1
                            continue
                        cn = int(is_chinese_target(it, src, SIMP))
                        for t in ts:
                            add(w, None, kind, t, None, src,
                                "%s:top:%s:%s:%s" % (src, w, kind, t), hidden=cn)
                    for s in o.get("senses") or []:
                        gl = ((s.get("glosses") or [""])[0] or "").strip()
                        sid = br.get((w, gl))
                        for it in (s.get(key) or []):
                            ts = clean_targets(it.get("word"))
                            if not ts:
                                st[src + "/🔴 丢：不是词（英文释义/模板报错）"] += 1
                                continue
                            cn = int(is_chinese_target(it, src, SIMP))
                            for t in ts:
                                add(w, sid, kind, t, None, src,
                                    "%s:sense:%s:%s:%s:%s" % (src, w, sid, kind, t), hidden=cn)

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
