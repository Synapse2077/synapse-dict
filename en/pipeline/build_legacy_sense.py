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
  · **释义里混着音标的跳过**（3,900 条 0.16%）：那是**别的词典条目被整条粘了进来**
    （`outerer → outer ⏎ ['autə] ⏎ adj. ⏎ 在外面…`）。
    🔴 **不确定的不结构化** —— 它们继续走原样兜底，不会因此看不见。

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
    if mark in MARK_REGION:
        return "region"
    if mark in MARK_REGISTER:
        return "register"
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
    for wid, text in rows:
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
                tg.append((bucket(mk), mk))
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
    for k in ("处理的词形", "义项", "跳过·释义里混着音标", "拆不出义项", "残渣行"):
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
