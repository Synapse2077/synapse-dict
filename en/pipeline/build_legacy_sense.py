#!/usr/bin/env python3
"""把**词条级**的老词典释义拆成**义项级**，进 v3 的义项层。2026-09-09。

═══ 起因 ═══
用户 2026-09-09：「能按照其他语言一样处理吗，我们只要知道来源就行，
具体怎么拆分是我们自己的事」。

en 有 **2,421,239** 个词形（60.3%）只有词条级释义，展示成一整块文本：

    n. 传真
    vt. 发传真
    [计] 传真系统; 传真

而其余五门（和 en 的 v3 那 34.5%）是「词性 + 逐条义项」。**这是数据问题不是排版问题** ——
文本从来没被拆开过，展示层只能原样打印。

═══ 🔴 与阶段 0 那条禁令不冲突（`EN_PLAN` §〇）═══
§〇 写的是「ECDICT 中文**不进 `sense_gloss`**」，理由是
**「把词形级整块拆开贴到 kaikki 的义项上就是义项错配」**。
⇒ 禁的是**对齐**。本步只处理**根本没有 kaikki 义项**的那 242 万词：
  它们没有可错配的对象，`n. 传真` / `vt. 发传真` 是**源头自己的切分**，不是我猜的。
⚠️ 有 v3 义项的词，一行都不碰（闸里有负控守着）。

⭐ `sense_src.src` 的建表注释里本来就写着 `en-edition / zh-edition / **ecdict**`，
   这条路是阶段 0 预留好的 —— **结构里不出现来源的名字，来源列里必须出现**。

═══ 判据（每一条都回源验过，见 `probes/ecdict_shape.py`）═══
    <块>  := <行>（换行分隔，96.07% 单行）
    <行>  := [<词性>] <义项>；<义项>；…
    <义项> := [<类别>]* <中文>

  · **词性是封闭集**。判不准的**不硬塞**（照阶段 1d「宁可缺，不可错」）：
    `un.`(49,638) 实测全是名词性复合词但拿不准、`na.`(8,707) 名动混杂、
    `st.`(346) 是成句不全是谚语 ⇒ **pos 留空，原码存进 `raw_tags` 不丢**。
  · **切分必须括号感知**：`wilkins → n. 威尔金斯（姓氏，英国生物物理学家；美国民权
    领袖；澳大利亚北极探险家）` —— 朴素按「；」切会把一个人名撕成三块。实测 2,968 条。
  · **释义里嵌着别的词条**（`outerer → outer ⏎ ['autə] ⏎ adj. ⏎ 在外面…`）：2026-10-29 起先按结构剪掉
    （`prune_embedded`，见那一节）。原来写的「混着音标的跳过 3,900 条」判据字符集窄了，实际有 3,333 个词
    照样逐行进了义项层（`G.O.S.` 752 条＝`go` 全文）。剪完仍混着音标的（509 条）照旧跳过、走原样兜底。

    cd en && python3 -u pipeline/build_legacy_sense.py
    cd en && python3 -u pipeline/build_legacy_sense.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "probes"))

import collections
import json
import re
import sqlite3

import dbtool
import paths

SRC = "ecdict"

# ── 词性映射：只映**判得准**的（`probes/ecdict_shape.py` 逐个读过样本）
POS_MAP = {
    "n.": "n", "v.": "v", "vt.": "v", "vi.": "v",
    "a.": "adj", "adj.": "adj", "ad.": "adv", "adv.": "adv",
    "pron.": "pron", "prep.": "prep", "conj.": "conj", "num.": "num",
    "int.": "intj", "interj.": "intj", "art.": "art", "det.": "det",
    "pref.": "pref", "prefix.": "pref", "suf.": "suf", "suff.": "suf",
    "phr.": "phr", "ph.": "phr", "phrase.": "phr", "idiom.": "phr",
    "pr.": "prov",
}
# 🔴 判不准的：不映射、不丢弃 —— 原码进 `raw_tags`，需要时还能回来
POS_KEEP_RAW = {"un.", "na.", "st.", "abbr.", "comb.", "short.", "aux.", "modal."}
# `abbr.` 照 v3 自己的做法：不当词性，当语法标签
POS_AS_TAG = {"abbr.": ("grammar", "abbreviation")}

# ── 类别标记分桶。**只列验过的**，其余一律 topic 并落 ledger
MARK_REGION = {"美国", "英国", "英", "美", "加拿大", "澳", "澳大利亚", "苏格兰",
               "爱尔兰", "新西兰", "印度", "南非", "英格兰", "威尔士", "主美国英语",
               "主英国英语"}
MARK_REGISTER = {"俚", "口语", "网络", "古", "废", "方", "谑", "贬", "褒", "讳",
                 "书", "俗", "粗", "婉"}
MARK_NAME = {"人名", "地名", "姓氏", "女名", "男名", "英格兰人姓氏", "苏格兰人姓氏",
             "威尔士人姓氏", "爱尔兰人姓氏", "法国人姓氏", "德国人姓氏"}

POS_RE = re.compile(r"^\s*([a-zA-Z]{1,7}\.)\s+")
MARK_RE = re.compile(r"^\s*\[([^\]=]{1,6})\]\s*")
# 🔴 释义里混进音标 ⇒ 别的词典条目被粘进来了，不结构化
IPA_RE = re.compile(r"\[[ˈˌa-zA-Zɑɒəɜɪʊʌθðŋʃʒæːˑ'.:]{2,}\]")
OPEN, CLOSE = "（〔([【<《", "）〕)]】>》"


def split_top(s):
    """按「；/;」切，**括号内不切**。

    🔴 朴素切法实测切坏 2,968 条：`威尔金斯（姓氏，英国生物物理学家；美国民权领袖）`
       会被撕成三块 —— 那不是三个义项，是一个人名的注释。
    """
    out, buf, depth = [], [], 0
    for ch in s:
        if ch in OPEN:
            depth += 1
        elif ch in CLOSE:
            depth = max(0, depth - 1)
        if ch in "；;" and depth == 0:
            out.append("".join(buf)); buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


# ══════════════════════════════════════════════════════════════════════════
#  多行原文里嵌着的「词条」（2026-10-29，EN_PLAN §16.7④）
# ══════════════════════════════════════════════════════════════════════════
# 🔴 ECDICT 有一批释义字段是**整段词条原文**：变形词 = 一句指针 ＋ 把原形的整条粘在后面
#      `kamakuras → kamakura的复数 ⏎ Kamakura ⏎ [,kɑ:mə'kurə] ⏎ adj. ⏎ 镰仓时期艺术…`
#    原形是大词就粘几百行（`G.O.S.` 752 条义项＝ `go` 的全文，`vi.`／`前进`／`每小时走90英里` 各成一条）。
#    上面的 `IPA_RE` 本来要拦它们，但字符集写窄了（缺 `ɡ` `ɔ` `ɛ` 和逗号）⇒ 3,333 个词照样逐行进了义项层；
#    拦住的那批走「整块原文兜底」，页面上同样是整段别的词条。
# ⇒ 按**结构**认：一行拉丁字母词头，紧跟一行音标或单独的词性标记 ＝ 一个嵌入词条的开头。
#    每个嵌入词条：是本词自己（同词异写 `A.B.F.M.`／`ABFM`）⇒ 留；是别的词而它**没有自己的页** ⇒ 留
#    （唯一的释义来源，28 个）；是别的词、**有自己的页** ⇒ 删（读者点过去看全文）。
#    本词在它前面一行自己的内容都没有（`G.O.S.`、`Woop Woop`）⇒ 留**第一个**，不让页面变空。
#    留下的部分再清掉格式行：音标行、与词头相同的行、`变形：` 及其后的变形列表；
#    单独一行的词性标记**不当义项**，当作后面几行的词性（`parse` 只认同一行的 `n. 传真`）。
#    🔴 所有留下的字都原样取自源头，这里只删不写。
# 音标行，两档：
#   `PHON_LINE`  方括号里含 IPA 符号（`[ɡəu]`、`[ju:; 弱ju; jə]`）—— 单看这一行就能定，删行、闸 A9 都用它
#   `PHON_ANY`   方括号里没有中文就行（`[pit]`）—— **只在紧跟拉丁词头时**才是音标：
#                单看一行会误伤缩写全称 `[European Atomic Energy Community]`、`[E(scherichia)coli]`
# 🔴 第一版只有前一档 ⇒ `[pit]`／`[spin]`／`[red]` 认不出，`p.i.t` 留下 80 条 `pit` 的释义；
#    放宽成后一档单用 ⇒ 又会删掉缩写全称。⇒ 宽的那档靠上下文（前一行是词头）定。只放行弱读/强读标记「弱」「强」。
PHON_LINE = re.compile(r"^\s*\[(?:[^\]㐀-鿿]|[弱强])*[ɑæəɛɪʊʌɔθðʃʒŋːɡ'ˈ,:;](?:[^\]㐀-鿿]|[弱强])*\]\s*$")
PHON_ANY = re.compile(r"^\s*\[(?:[^\]㐀-鿿]|[弱强])+\]\s*$")
POS_LINE = re.compile(r"^\s*((n|v|vt|vi|adj|adv|prep|conj|pron|int|interj|abbr|art|num|aux|a|ad|pl|det|suf|pref|comb)"
                      r"\.?\s*(&|,|/|和)?\s*)+$", re.I)
HEAD_LINE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9.\-' ]{0,40}$")
SECTION_LINE = re.compile(r"^\s*(变形|短语|派生词|习语|同义词|反义词|参考|词组)\s*[:：]\s*$")
CJK_RE = re.compile(r"[㐀-鿿]")


def word_key(w):
    """同词异写的比较键：小写、只留字母数字、去掉同形词编号（`go1`→`go`、`A.B.F.M.`→`abfm`）。"""
    return re.sub(r"\d+$", "", re.sub(r"[^0-9a-z]", "", (w or "").lower()))


def is_head(line):
    """拉丁字母词头。🔴 词性标记（`abbr.`、`n.`）也长这个形状 —— 不排除的话 `abbr.` 下一行的
    `[European Atomic Energy Community]` 会被当成「词头 + 音标」，整段缩写全称被当成别的词条删掉。"""
    return bool(HEAD_LINE.match(line)) and not POS_LINE.match(line) and not line.strip().startswith("=")


def embedded_starts(lines):
    return [i for i in range(len(lines) - 1)
            if is_head(lines[i])
            and (PHON_ANY.match(lines[i + 1]) or POS_LINE.match(lines[i + 1]))]


def prune_embedded(word, text, has_page):
    """→ 清过的原文（只删行、合并单独成行的词性，一个字不写）。没有可动的就原样返回。

    `has_page(headword)`：那个词在本库里有没有自己的页（不算本词自己）。"""
    lines = [l for l in (text or "").split("\n")]
    if len(lines) < 2:
        return text
    starts = embedded_starts(lines)
    me = word_key(word)
    heads = set()
    if starts:
        keep = lines[:starts[0]]
        own = any(CJK_RE.search(l) for l in keep)
        for n, a in enumerate(starts):
            b = starts[n + 1] if n + 1 < len(starts) else len(lines)
            h = lines[a].strip()
            heads.add(word_key(h))
            # 🔴 同词异写只认「缩写的不同写法」（`A.B.F.M.`↔`ABFM`，361 处）。带同形词编号的词头（`go1`、`cab1`）
            #    是正式词条，**不会**是缩写的另一种写法 —— 第一版只比 `word_key`，`g.o` 与 `go1` 都成了 `go`，
            #    整条 `go` 被当成 `g.o` 自己的内容留下（568 条义项）。实测这个形状 51 处，全是误判。
            # 本词带点时，只有词头也是缩写（全大写 `ABFM`，或本身带点 `aft.`）才算同一个词；
            # 词头是普通词（`hand`、`you`、`go1`）⇒ 是 ECDICT 把普通词拆成字母串再粘全文（`H.and.` 845 条）。
            same = word_key(h) == me and ("." not in (word or "") or "." in h
                                          or (h == h.upper() and not re.search(r"\d$", h)))
            if same or not has_page(h):
                keep.extend(lines[a + 1:b])
            elif n == 0 and not own:
                # 本词一行自己的内容都没有、开头就是别的词的整条（`piger → pig1 …`、`carrys → carry …`，2,096 个，
                # 几乎全是 ECDICT 自造的假变形）⇒ 印一行**交叉引用**，读者点过去看全文。
                # 🔴 第一版是「留第一个嵌入词条，免得页面变空」—— 于是 `H.and.` 留下 `hand` 的 845 条、`carrys` 217 条，
                #    读者会以为假词 `carrys` 有这么多义项。`= X` 是源头自己的记号（`= general obligation bond`），
                #    这里只复述「这一格放的是 X 的词条」，不写任何释义。
                keep.append("= " + re.sub(r"\d+$", "", h))
    else:
        keep = lines
    out, pos, skip_forms, prev = [], None, False, ""
    for l in keep:
        s = l.strip()
        after_head, prev = is_head(prev), s
        if not s or PHON_LINE.match(s) or (after_head and PHON_ANY.match(s)):
            continue
        if SECTION_LINE.match(s):
            skip_forms = s.startswith("变形")
            continue
        if skip_forms:
            if CJK_RE.search(s):
                skip_forms = False
            else:
                continue                      # `变形：` 下面的 `vt.`／`talent-spotted`／`. talent-spotting`
        if POS_LINE.match(s):
            pos = s
            continue
        if not CJK_RE.search(s) and not s.startswith("=") and word_key(s) in heads | {me}:
            continue                          # 与词头相同的行（`Go`、`ABFM`）
        if pos and not POS_RE.match(s):
            tok = re.match(r"[A-Za-z]+", pos.strip()).group(0) + "."     # `vt.,`／`abbr` → `vt.`／`abbr.`
            s = "%s %s" % (tok, s)
        out.append(s)
    return "\n".join(out)


def parse(text):
    """→ ([(pos_raw, marks, gloss)], 残渣[])，按展示顺序"""
    items, resid = [], []
    for ln in (text or "").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        pos_raw = None
        m = POS_RE.match(ln)
        if m and (m.group(1).lower() in POS_MAP or m.group(1).lower() in POS_KEEP_RAW):
            pos_raw = m.group(1).lower()
            ln = ln[m.end():]
        got = False
        # 🔴 **行首标记覆盖整行**（回源验的）：
        #      `[网络] 我不感兴趣；我没兴趣；我没有兴趣` —— 三条是同一句的不同说法，
        #      `[化] 酮葡糖酸; 葡糖酮酸` 同理。实测 27,329 行是这个形状。
        #    而 `费用变动; [会计] 成本变动` 证明标记也可以是**逐条**的（5,939 行）。
        #    ⇒ 行首标记当**该行的默认值**，条目自带标记时用它自己的。
        #    ⚠️ 第一版只挂给第一条，`FAX` 的「传真系统」有 `[计]`、「传真」没有 ——
        #      那是**欠账**（缺不是错），但既然量得出来就该补上。
        line_default = []
        for k, seg in enumerate(split_top(ln)):
            # 🔴 分号之间夹着单独的词性（`六道木； n.；六道木`、`…；comb`）⇒ 是后面几段的词性，不是义项
            #    （2026-10-29，A9 在重建后报的 104 条）。判不准的词性照旧不硬塞。
            if POS_LINE.match(seg):
                tok = re.match(r"[A-Za-z]+", seg.strip()).group(0).lower() + "."
                if tok in POS_MAP or tok in POS_KEEP_RAW:
                    pos_raw = tok
                continue
            marks = []
            while True:
                mm = MARK_RE.match(seg)
                if not mm:
                    break
                marks.append(mm.group(1))
                seg = seg[mm.end():].strip()
            if k == 0 and marks:
                # 🔴 **专名标记不传播。**学科/语域标记说的是「整行都在这个领域」，
                #    而 `[人名]`/`[地名]` 说的是「**这一条**是专名」，下一条可能不是：
                #      `n. [地名][菲律宾] 马拉维利亚；（沙漠）粉花夜开野花`
                #                                    ↑ 这是植物，不是菲律宾的地名
                #      `[人名] 吉芬; 低质商品`  ↑ 那是经济学的吉芬商品
                #    实测只有 **9 行**受影响，但**印错一个词性/类别就是错**，
                #    而传播对的有 27,320 行 —— 两边都要照顾到，不能一刀切。
                if not any(x in MARK_NAME for x in marks):
                    line_default = list(marks)
            elif not marks:
                marks = list(line_default)
            if seg:
                items.append((pos_raw, marks, seg))
                got = True
        if not got and ln:
            resid.append(ln)
    return items, resid


def bucket(mark):
    """方括号标记归桶。查不到的落 `topic`（学科标记是开放集，枚举不完）。

    🔴 2026-09-15 补的守卫：**ECDICT 的标记全是中文短码**（`计` `医` `化` `军`…），
       3,239 种 65.3 万条无一例外。所以凡是拉丁字母的，都是 `MARK_RE`
       从释义正文里误抠出来的残片，不是学科标记：

           benzfuro  「苯并呋喃并[2,3-f]喹啉」  ← `[2,3-f]` 是化学名的一部分
           to get laid 「[inf！]性交」          ← 源头自己的排版残渣
           stack dump 「[WIN,NT]堆栈转储」      ← 平台标注，不是学科

       58 种 174 条。量很小，但**「学科」这一桶将来要印在读者眼前**
       （2026-09-15 解开 kaikki topic 的展示），印出 `[P-]` 就是错不是缺
       （`[[dict-framework-doc]]`：错比缺更伤权威）。
    ⚠️ 判据是「有没有汉字」不是「长不长得像 slug」：第一版我按后者写，
       把 kaikki 的 `pesäpallo`（芬兰棒球）当成噪声误伤了 ——
       `[[criteria-narrower-than-you-think]]`，又一次判据比要描述的东西宽。
    """
    if mark in MARK_REGION:
        return "region"
    if mark in MARK_REGISTER:
        return "register"
    if not dbtool.has_han(mark):
        return None                      # 调用方据此整条丢掉并记账
    return "topic"


def collect(con):
    q = con.execute
    # 🔴🔴 排除的口径必须是「有**别的来源**的义项」，不是「有义项」。
    #    第一版写 `NOT EXISTS(SELECT 1 FROM sense …)` —— 重跑时上一轮**自己写的**
    #    ecdict 义项把这些词全排除掉了 ⇒ 清空之后重建出 0 条。
    #    **今天第三次栽在同一个形状**（`translate_examples.pool` 两次）：
    #    幂等脚本的取数口径里，不许把「本步自己的产物」算成「别人已经做过了」。
    rows = q("""SELECT g.word_id, g.text FROM legacy_gloss g
                WHERE g.published=1 AND NOT EXISTS(
                  SELECT 1 FROM sense_src ss WHERE ss.word_id=g.word_id
                    AND ss.src <> ?)""", (SRC,)).fetchall()
    senses, glosses, tags, srcs = [], [], [], []
    stat = collections.Counter()
    unmapped = collections.Counter()
    skipped = []
    # 「那个词有没有自己的页」：dict 里有这一行，且它有义项或有可出版的老词典释义
    word_of = dict(q("SELECT id, word FROM dict"))
    paged = collections.defaultdict(set)
    for (wid,) in q("SELECT DISTINCT word_id FROM sense UNION SELECT word_id FROM legacy_gloss WHERE published=1"):
        if wid in word_of:
            paged[word_key(word_of[wid])].add(wid)
    for wid, text in rows:
        if text and "\n" in text:
            new = prune_embedded(word_of.get(wid), text,
                                 lambda h, wid=wid: bool(paged.get(word_key(h), set()) - {wid}))
            if new != text:
                stat["清掉嵌入词条/格式行的词形"] += 1
                text = new
        if IPA_RE.search(text or ""):
            stat["跳过·释义里混着音标"] += 1
            skipped.append((wid, text))
            continue
        items, resid = parse(text)
        stat["残渣行"] += len(resid)
        if not items:
            stat["拆不出义项"] += 1
            continue
        stat["处理的词形"] += 1
        for rank, (pos_raw, marks, gloss) in enumerate(items):
            pos = POS_MAP.get(pos_raw)
            if pos is None and any(m in MARK_NAME for m in marks):
                pos = "name"          # `[人名] 坎斯` —— 源头自己说的，不是我猜的
            if pos_raw and pos_raw not in POS_MAP:
                unmapped[pos_raw] += 1
            senses.append((wid, rank, pos))
            glosses.append(gloss)
            tg = []
            if pos_raw in POS_AS_TAG:
                tg.append(POS_AS_TAG[pos_raw])
            for mk in marks:
                kind = bucket(mk)
                if kind is None:
                    stat["丢弃·非中文方括号残片"] += 1
                    continue
                tg.append((kind, mk))
            tags.append(tg)
            srcs.append((wid, "%s:%d:%d" % (SRC, wid, rank), gloss,
                         json.dumps({"pos_raw": pos_raw, "marks": marks},
                                    ensure_ascii=False)))
            stat["义项"] += 1
    return senses, glosses, tags, srcs, stat, unmapped, skipped


def _tagcount(ids):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n = 0
    for k in range(0, len(ids), 900):
        ck = ids[k:k + 900]
        n += con.execute("SELECT COUNT(*) FROM sense_tag WHERE sense_id IN (%s)"
                         % ",".join("?" * len(ck)), ck).fetchone()[0]
    con.close()
    return n


def gates(con, before, n_sense, n_word):
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("义项落库数对得上",
         q("SELECT COUNT(*) FROM sense_src WHERE src=?", SRC), n_sense),
        ("每条新义项都有中文",
         q("""SELECT COUNT(*) FROM sense_src ss WHERE ss.src=? AND NOT EXISTS(
              SELECT 1 FROM sense_gloss g WHERE g.sense_id=ss.sense_id
                AND g.lang='zh')""", SRC), 0),
        # 🔴🔴 负控①：**有 v3 义项的词，一条都不许被碰**（§〇 那条禁令守在这里）
        ("🔴 负控 有 kaikki 义项的词没被动",
         q("""SELECT COUNT(*) FROM sense_src ss JOIN dict d ON d.id=ss.word_id
              WHERE ss.src=? AND EXISTS(
                SELECT 1 FROM sense_src k WHERE k.word_id=d.id AND k.src<>?)""",
           SRC, SRC), 0),
        # 🔴 负控②：v3 那 178 万义项的中文一行没变
        ("🔴 负控 v3 的中文没被动",
         q("SELECT COUNT(*) FROM sense_gloss WHERE src IN ('model:def',"
           "'template:form_of','ecdict-core')"), before["v3zh"]),
        ("🔴 负控 v3 义项数没变",
         q("SELECT COUNT(*) FROM sense_src WHERE src<>?", SRC), before["v3src"]),
        # 🔴 出版层与证据层一一对应 —— v3 的核心不变量，加了新来源也必须成立
        ("🔴 sense 与 sense_src 仍一一对应",
         q("SELECT COUNT(*) FROM sense"), q("SELECT COUNT(*) FROM sense_src")),
        ("🔴 没有孤儿义项（sense_src 全挂上）",
         q("SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL"), 0),
        ("🔴 原文一个字节没改",
         q("SELECT COUNT(*) FROM legacy_gloss"), before["legacy"]),
        # 🔴 负控③：`un./na./st.` 判不准的，pos 必须是空，且原码留在 raw_tags
        ("🔴 负控 判不准的词性没被硬塞",
         q("""SELECT COUNT(*) FROM sense_src ss JOIN sense s ON s.id=ss.sense_id
              WHERE ss.src=? AND s.pos IS NOT NULL
                AND (ss.raw_tags LIKE '%"un."%' OR ss.raw_tags LIKE '%"na."%'
                     OR ss.raw_tags LIKE '%"st."%')""", SRC), 0),
        # 🔴 期望值第一版我写了 3 —— **数错了**，`n. 传真`／`vt. 发传真`／
        #    `[计] 传真系统`／`[计] 传真` 本来就是 4 条。闸红了先读，读完是我的断言错。
        ("负控 FAX 拆成 4 条",
         q("""SELECT COUNT(*) FROM sense s JOIN dict d ON d.id=s.word_id
              WHERE d.word='FAX'"""), 4),
        ("🔴 负控 FAX 的 [计] 覆盖了它那一行的两条",
         q("""SELECT COUNT(*) FROM sense_tag t JOIN sense s ON s.id=t.sense_id
              JOIN dict d ON d.id=s.word_id
              WHERE d.word='FAX' AND t.kind='topic' AND t.value='计'"""), 2),
        # 🔴 负控④（§16.7④，2026-10-29）：嵌入词条。数格式行的 A9 逮不到「整条别的词被当成本词内容留下」——
        #    第一版 `g.o` 与 `go1` 被判成同一个词，留下 568 条 `go` 的释义，而格式行已清干净、A9 是绿的。
        #    ⇒ 拿已知答案钉住三种形状：缩写后面粘着整条 go／变形词只该剩指针。
        ("🔴 负控 G.O.S.／g.o 里没有 go 的释义",
         q("""SELECT COUNT(*) FROM sense s JOIN dict d ON d.id=s.word_id JOIN sense_gloss g ON g.sense_id=s.id
              WHERE d.word IN ('G.O.S.','g.o') AND g.text LIKE '%前进%'"""), 0),
        ("🔴 负控 H.and.／piger／carrys 各只剩一行交叉引用",
         q("""SELECT COUNT(*) FROM sense s JOIN dict d ON d.id=s.word_id JOIN sense_gloss g ON g.sense_id=s.id
              WHERE d.word IN ('H.and.','piger','carrys')"""), 3),
        ("🔴 负控 kamakuras 只剩指针",
         q("""SELECT COUNT(*) FROM sense s JOIN dict d ON d.id=s.word_id JOIN sense_gloss g ON g.sense_id=s.id
              WHERE d.word='kamakuras' AND g.text='kamakura的复数'"""), 1),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-36s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    senses, glosses, tags, srcs, stat, unmapped, skipped = collect(con)
    q = con.execute
    before = {
        "sense": q("SELECT COUNT(*) FROM sense").fetchone()[0],
        "v3src": q("SELECT COUNT(*) FROM sense_src WHERE src<>?",
                   (SRC,)).fetchone()[0],
        "v3zh": q("SELECT COUNT(*) FROM sense_gloss WHERE src IN "
                  "('model:def','template:form_of','ecdict-core')").fetchone()[0],
        "legacy": q("SELECT COUNT(*) FROM legacy_gloss").fetchone()[0],
        # 🔴 取回新插入的 id 靠「> 插入前的最大 id」+ AUTOINCREMENT 的顺序保证。
        #    这个前提必须显式记下来，且插入后当场核对条数（见下面那个 assert）。
        "sense_maxid": q("SELECT COALESCE(MAX(id),0) FROM sense").fetchone()[0],
    }
    con.close()
    print("═══ 词条级释义 → 义项级 ═══")
    for k in ("处理的词形", "义项", "清掉嵌入词条/格式行的词形", "跳过·释义里混着音标", "拆不出义项", "残渣行"):
        if stat[k]:
            print("   %-22s %10s" % (k, format(stat[k], ",")))
    print("   ⇒ 平均每词 %.2f 条义项" % (stat["义项"] / max(stat["处理的词形"], 1)))
    if unmapped:
        print("\n   ⚠️ 有意不映射的词性（pos 留空，原码在 raw_tags）：")
        for k, v in unmapped.most_common(8):
            print("      %-8s %8s" % (k, format(v, ",")))
    print("\n   样本：")
    seen = set()
    for (wid, rank, pos), g, tg in zip(senses, glosses, tags):
        if wid in seen or len(seen) >= 4:
            continue
        seen.add(wid)
        same = [(p, gg, t) for (w, r, p), gg, t in zip(senses, glosses, tags)
                if w == wid]
        con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        w, = con2.execute("SELECT word FROM dict WHERE id=?", (wid,)).fetchone()
        con2.close()
        print("      %s" % w)
        for p, gg, t in same:
            print("        └ %-5s %s%s" % (p or "—",
                                           "".join("[%s]" % v for _, v in t),
                                           gg[:52]))
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0
    # 🔴 **幂等**：先清掉上一次本步写的，再重建。判据是 `sense_src.src`，
    #    不是 id 区间 —— id 区间会随别的步骤插入而失效。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    old = [r[0] for r in con.execute(
        "SELECT sense_id FROM sense_src WHERE src=?", (SRC,))]
    con.close()
    if old:
        print("\n■ 幂等：先清掉上一次写的 %s 条" % format(len(old), ","))
        with dbtool.session("keep-v3-legacy-sense-purge",
                            expect={"#sense": -len(old), "#sense_src": -len(old),
                                    "#sense_gloss": -len(old),
                                    "#sense_tag": -_tagcount(old)}) as s:
            s.executemany("DELETE FROM sense_tag WHERE sense_id=?",
                          [(i,) for i in old])
            s.executemany("DELETE FROM sense_gloss WHERE sense_id=?",
                          [(i,) for i in old])
            s.executemany("DELETE FROM sense_src WHERE sense_id=?",
                          [(i,) for i in old])
            s.executemany("DELETE FROM sense WHERE id=?", [(i,) for i in old])
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        before["sense_maxid"] = con.execute(
            "SELECT COALESCE(MAX(id),0) FROM sense").fetchone()[0]
        con.close()
    with dbtool.session("keep-v3-legacy-sense",
                        expect={"#sense": len(senses),
                                "#sense_src": len(senses),
                                "#sense_gloss": len(senses),
                                "#sense_tag": sum(len(t) for t in tags)}) as s:
        s.executemany("INSERT INTO sense (word_id,rank,pos) VALUES (?,?,?)", senses)
        ids = [r[0] for r in s.execute(
            "SELECT id FROM sense WHERE id > ? ORDER BY id",
            (before["sense_maxid"],)).fetchall()]
        # 🔴🔴 **id 与义项必须一一对上，否则中文会贴到别的义项上** ——
        #    今天刚在例句层被这个病咬过（`[[primary-key-is-not-enough]]`）。
        #    这里不是"应该对得上"，是**当场断言**，对不上立刻抛错回滚。
        if len(ids) != len(senses):
            raise RuntimeError("取回 %d 个 id，却要挂 %d 条义项 —— 中止"
                               % (len(ids), len(senses)))
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,'zh','equivalent',0,?,?)",
                      [(i, g, SRC) for i, g in zip(ids, glosses)])
        s.executemany("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,"
                      "text,raw_tags) VALUES (?,?,?,?,'zh',?,?)",
                      [(w, i, SRC, ref, tx, rt)
                       for i, (w, ref, tx, rt) in zip(ids, srcs)])
        s.executemany("INSERT OR IGNORE INTO sense_tag (sense_id,kind,value) "
                      "VALUES (?,?,?)",
                      [(i, k, v) for i, tg in zip(ids, tags) for k, v in tg])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = gates(con, before, len(senses), stat["处理的词形"])
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
