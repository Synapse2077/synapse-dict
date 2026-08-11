#!/usr/bin/env python3
"""迁移第 1 步：建 `sense` / `sense_gloss` / `sense_tag` 只读镜像。2026-08-06。

见 `docs/SCHEMA.md` §2.1 与 §5。本步骤**只从现有列生成，`dict` 一个字节不动**，
展示层可以逐步切过去，出问题随时切回（`DROP TABLE` 就回到原状）。

═══ 这三张表解决什么 ═══
① **加一门目标语言 = 往 `sense_gloss` 加行**，不改表结构、不动任何已有数据。
   这就是「可插拔」：`sense_gloss(sense_id, lang, kind, text)`，越南语来了就
   `INSERT ... lang='vi'`，`dict` / `sense` / 已有的 zh 行一个字节不用碰。
   （对比：往 `dict` 加 `translation_vi` 列也能work，但每加一门语言就多一列，
     而且继承了下面②那个脆弱契约。）
② **义项有稳定主键**。例句、搭配、同义词现在只能挂在「词」上，`escalera` 的
   「楼梯上被击毙」那条例句和「扑克顺子」那条义项分不开。
③ **行号对齐契约作废**。`definition`/`translation`/`meta` 三列靠行号一一对应，
   已经咬过三次（`novia` 中英错位 / `esquela` 重编号错位 / 指针混在释义列）。
   一义项一行之后这三类错误在结构上不可能发生。

═══ 🔴 `translation` 那 100% 是假象，必须按内容分流 ═══
`dict.translation` 全库非空，但**其中 1,080,665 行是模板生成的指针文本**
（`pie 的 阳性·复数`），只有 217,352 行是真释义。整列搬会往 `sense_gloss` 里
灌进一百万条不是释义的东西。

判据用展示层同一条（`App.tsx:529`）：**半角空格包着的「的」**——
中文释义里的「的」不带空格（`品德高尚的女性`），所以不会误伤。
⚠️ 边界已实测：中文是指针、同一行却有 en/es 释义的 **0 条**，判据无歧义。
指针不进 `sense_gloss`（`dict.infl` 里本来就有，且 `exchange` 有机读版本）。

═══ 义项来自两套编号，都收，不合并 ═══
    A 组  `dict` 的行号对齐义项集     217,352   src_ref = dict:<id>#<行号>
    B 组  `sense_es` 西语版自有义项   173,422   src_ref = sense_es:<id>
两套切分不同（`hacer` 我们 15 条、西语版 59 条），**本步骤一条都不合并**。
合并靠 `concept_id`（§2.0，非破坏、可随时清掉），本脚本把该列建出来但全留 NULL
= 完全堆叠状态，往后每确认一批分配一批。

═══ `kind`：对应词 vs 定义 ═══
    en → equivalent   英文版给的是 eye / keyhole 这类**对应词**
    es → definition   西语版给的是「Órgano sensible a la luz…」这类**单语定义**
    zh → 看它是从哪边翻来的：有 en 就是 equivalent，只有 es 就是 definition
展示规则随之固定：**对应词作标题、定义作副行**，缺哪个降级哪个。

═══ ⚠️ 这是**生成表**，不是编辑表 ═══
数据流单向 `dict`/`sense_es` → 这三张表。`--apply` 会先 DROP 再重建，
所以**别在这三张表上手工改数据**，改了会被下一次重建抹掉。
（与 `sense_es` 那类「只填空不覆盖」的表规矩相反，因为它们性质不同：
  一个是生成物，一个是原始数据。见 [[replay-scripts-undo-fixes]] 的区分。）

用法（在仓库根）：
    python3 -m es.pipeline.build_sense_layer            # 只统计，不写库
    python3 -m es.pipeline.build_sense_layer --apply
"""
import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool   # noqa: E402
import paths    # noqa: E402
from pipeline.build import POS_MAP, REGIONS, REGISTERS, NUMBER, IGNORE_TAGS  # noqa: E402

# App.tsx:529 —— 变形指针的判据，与展示层逐字一致
PTR = re.compile(r"^.+ 的 \S+$")

# ═══ 西语版自己那套标签词汇 ═══
# 🔴 它和 kaikki 英文版**不是同一套命名**。第一版直接拿 `build.py` 的 REGIONS/REGISTERS
#    去归桶，18,897 次落在桶外被默默丢掉 —— 逐条看那一栏才发现里面全是真数据：
#    西班牙各省（Salamanca/Murcia/Cantabria/Álava…）、墨西哥各州（Yucatán/Hidalgo…）、
#    智利分区（Chiloé/Southern-Chile…），以及 4,188 次 `outdated`。
#
# 语域**归一到 kaikki 名**：否则按「dated」筛会漏掉西语版那 4,188 条 `outdated`。
ES_REGISTER = {
    "outdated": "dated", "figurative": "figuratively",
    "jocular": "humorous", "euphemism": "euphemistic",
    "academic": "academic",          # kaikki 无对应，保留原名
}
# 地区**保留原名**：它们是实实在在不同的地方，与 kaikki 那套基本不重叠，
# 只归一确实指同一处的几个。
ES_REGION_ALIAS = {
    "Río-de-la-Plata": "Rioplatense", "America": "Latin-America",
    "Canaries": "Canary-Islands", "Basque Country": "Basque-Country",
    "La Rioja": "La-Rioja", "La Rioja (Argentina)": "La-Rioja-Argentina",
}
# 西语版特有、确认是地区的（kaikki REGIONS 里没有）
ES_REGION_EXTRA = {
    "Chiloé", "Salamanca", "South-Cone", "León", "Murcia", "Cantabria", "Navarra",
    "Álava", "Extremadura", "Southern-Chile", "Yucatán", "Castile", "Hidalgo",
    "Zamora", "Burgos", "Mexico-City", "Palencia", "Cádiz", "Córdoba", "Michoacán",
    "Grenada", "Rioja", "Ceuta", "Chiapas", "Veracruz", "Northern-Argentina",
    "Guadalajara", "Campeche", "Sinaloa", "Brazil", "Soria", "Northern-Chile",
    "Nuevo-León", "San-Luis-Potosí", "Almería", "Chihuahua", "Oaxaca", "Huelva",
    "New-Mexico", "Jalisco", "Sonora", "Guanajuato", "Balearic-Islands",
    "Central-Mexico", "Vizcaya", "Querétaro", "Lower-California", "Central-Chile",
    "Chubut", "Europe", "Antioquia", "Portugal", "Tlaxcala", "Zacatecas",
    "Ribera-Navarra", "Zulia",
}
# 语法/词性标签：不进 sense_tag（pos 与 gender 各有自己的列）
ES_GRAM = {"noun", "adjective", "verb", "adverb", "conjunction", "pronominal",
           "transitive", "vocative", "masculine", "feminine", "singular",
           "form-of", "lower case", "repeated"}
# 西语版的 `plural`（288 次）= 「该义项用于复数」（`ademán` 的复数 ademanes = 举止），
# **不是** kaikki 的 `plural-only`（只以复数存在）—— 映成后者是在强化源头没说的话。
# 用 kaikki 自己词表里意思对得上的 `in-plural`。
# ⚠️ 已知不对称：A 组（kaikki）的 `in-plural` 被 `build.py` 归进 IGNORE_TAGS 丢掉了，
#    所以这个标签目前只有 B 组有。记在这儿，别当成 bug 反复查。
ES_NUMBER = {"plural": "in-plural"}

# `pos_title` → 性别。西语版把性别写在标题里，100% 非空，比 tags 全。
PT_GENDER = [
    (re.compile(r"(masculino y femenino|femenino y masculino|ambiguo)", re.I), "mf"),
    (re.compile(r"(femenino|femenina)", re.I), "f"),
    (re.compile(r"(masculino|masculina)", re.I), "m"),
]

DDL = [
    # ═══ 证据层：某一版对这个词说的一句话。永不删改 ═══
    """CREATE TABLE sense_src (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,       -- → dict.id
         sense_id INTEGER,                -- 编入哪条出版义项；NULL = 尚未裁决
         src      TEXT NOT NULL,          -- en-edition / es-edition（记录的，非反推）
         src_ref  TEXT NOT NULL,          -- 回源坐标：dict:<id>#<行号> 或 sense_es:<id>
         lang     TEXT NOT NULL,          -- 这句原文是什么语言
         text     TEXT NOT NULL,          -- 原文
         raw_tags TEXT,                   -- 原始标签原样留底，归一失败时能回查
         UNIQUE(src_ref)
       )""",
    # ═══ 出版层：用户读到的 1. 2. 3. ═══
    # 🔴 **没有 parent_id**。2026-08-07 曾设计成「英文义项作父、西语义项作子」，
    #    并行请教豆包 pro 与 v4-pro，两家各自独立否掉了它的前提：
    #      v4-pro：「不要用英文维基的义项树做父结构」——`ojo` 的 es#3「与眼睑开口相似的
    #              平面几何形」能对齐到 eye，只是因为英文维基把「形状像眼的东西」也收进
    #              了那一条，**那是英语的词汇化方式，不是语义分类学**。它不是一种眼睛。
    #      豆包 pro：「对齐结果是**语义相似度匹配**，不是词典学层面的**义位归并**，
    #              仅能作为挂载参考」；并指出照搬会把「孔眼」义族（针眼/网眼/桥孔…）拆散。
    #    ⇒ 层级要做也该基于**语义义族**，那是编纂工作，对齐结果给不了。
    """CREATE TABLE sense (
         id      INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id INTEGER NOT NULL,        -- → dict.id
         rank    INTEGER NOT NULL,        -- 展示顺序 1,2,3…
         pos     TEXT,                    -- 逐义项词性（el radio 半径 / la radio 收音机）
         gender  TEXT,                    -- 逐义项性别
         UNIQUE(word_id, rank)
       )""",
    """CREATE TABLE sense_gloss (
         sense_id INTEGER NOT NULL,
         lang     TEXT NOT NULL,          -- en / es / zh …（加语言只往这里加行）
         kind     TEXT NOT NULL,          -- equivalent（对应词）/ definition（定义式）
         seq      INTEGER NOT NULL,       -- 第几个对应词（「眼睛」「眼」是两行）
         text     TEXT NOT NULL,
         src      TEXT,
         PRIMARY KEY(sense_id, lang, kind, seq)
       )""",
    """CREATE TABLE sense_tag (
         sense_id INTEGER NOT NULL,
         kind     TEXT NOT NULL,          -- topic / region / register / number
         value    TEXT NOT NULL,
         PRIMARY KEY(sense_id, kind, value)
       )""",
]
IDX = [
    "CREATE INDEX idx_src_word ON sense_src(word_id)",
    "CREATE INDEX idx_src_sense ON sense_src(sense_id)",
    "CREATE INDEX idx_sense_word ON sense(word_id)",
    "CREATE INDEX idx_gloss_lang ON sense_gloss(lang, kind)",
    "CREATE INDEX idx_tag_kv ON sense_tag(kind, value)",
]
TABLES = ("sense_src", "sense", "sense_gloss", "sense_tag")


def al(s):
    return (s or "").split("\n")


def tag_kind(t):
    """原始 tag → (kind, 归一后的 value)。桶外返回 (None, None)，由调用方计入「未归桶」。

    两套词汇都认：kaikki 英文版（A 组 meta 用的）与西语版（B 组 tags 用的）。
    """
    if t in ES_GRAM:
        return "__gram", None          # 语法标签，有自己的列，不进 sense_tag
    if t in ES_REGISTER:
        return "register", ES_REGISTER[t]
    if t in ES_NUMBER:
        return "number", ES_NUMBER[t]
    if t in ES_REGION_ALIAS:
        return "region", ES_REGION_ALIAS[t]
    if t in REGIONS or t in ES_REGION_EXTRA:
        return "region", t
    if t in REGISTERS:
        return "register", t
    if t in NUMBER:
        return "number", t
    if t in IGNORE_TAGS:
        return "__gram", None
    return None, None


def gender_of(pos_title, tags):
    """B 组义项的性别：先看 `pos_title`（100% 非空、最全），再看 tags 兜底。"""
    for rx, g in PT_GENDER:
        if pos_title and rx.search(pos_title):
            return g
    hf, hm = "feminine" in tags, "masculine" in tags
    if hf and hm:
        return "mf"
    return "f" if hf else ("m" if hm else None)


def collect(con):
    """→ (srcs, senses, glosses, tags, stat, untagged)。全部是待 executemany 的元组。

    ═══ 归并原则：**西语定义 = 义项本体，英文对应词 = 译词候选** ═══
    （2026-08-07 定，两家顾问一致意见 + 我的复核。原则来自 v4-pro：
      「不要用英文维基的义项树做父结构，应该用西语维基的义项定义做义项主体，
        英文对应词当作翻译候选和排序参考。」）

    `en_i` 说的是「这条西语义项对应英文版的第几条义项」（⚠️ **是义项行号，不是
    英文释义序号** —— `mona` 给出铁证，见 `fixes/fix_en_i_criterion.py`）。
    按**有多少条西语义项认领同一条英文义项**分三档：

        ① 独占（49,328 条）  → **合并**：英文那条不再单独成义项，它的证据与
                               对应词并入这条西语义项。免费拿到短对应词。
        ② 共享（31,479 条，12,845 组）→ **不搬对应词**：一个「眼睛」搬给 4 条会变成
                               「眼睛」×4，用户以为是重复条目。英文证据挂到 rank 最小
                               的那条，对应词留空，交后续「短标签」步骤逐条精化。
        ③ 英文版没有（92,615 条）→ 各自独立，无对应词可搬

        英文侧无人认领（85,541 条）→ 各自独立成义项，自带短对应词
                               （西语版缺这些意思，一条都不能丢）

    ⭐ **`en_i` 从此不再是行号**。它原本指向 `dict.definition` 的第几行（已经咬过三次
       的脆弱契约），这里被翻译成 `sense_src.sense_id` → `sense.id` 的主键引用。

    🔴 **没有 parent_id**：曾设计成英文作父/西语作子，两家顾问各自独立否掉，见 DDL 注释。

    `sense_gloss.seq` 恒为 0：拆「眼睛；眼」这类多对应词是编纂决策，
    不是机械转换，留给后续步骤。
    """
    srcs, senses, glosses, tags = [], [], [], []
    stat = collections.Counter()
    untagged = collections.Counter()
    sid = 0
    # 🔴 (dict_id, **义项行号**) → sense id。键必须是**原始行号 i**，不是「第几条英文释义」。
    #    `mona` 的第 1 行英文为空、中文是「母猴」，而 sense_es[mona#0]「雌猴」的
    #    en_i 正是 1 —— 模型匹配的是义项行，不是英文串。用错键就是错配。
    row_sid = {}
    nxt_rank = collections.Counter()      # dict_id → 已用到的最大 rank
    # 🔴 (dict_id, 西语原文) → sense id。用于「逐字相同即同一条义项」的确定性合并。
    #    `ingest_edition`（8-03）与 `ingest_missing_propers`（8-06）把西语版释义写进了
    #    `dict.definition_es`，而 `ingest_es_senses`（8-05）又把**同一份 dump** 收进了
    #    `sense_es` —— 后者的 docstring 明说「宁可内容重复，换一张含义均匀的表」。
    #    这些词多数没有英文（`en_i` 为空），走不到上面按对齐结果的合并，
    #    于是 `Cefalópodos` 的同一条释义会在界面上出现两遍。
    #    实测 61,241 组 / 多余 61,268 条 / 涉及 54,784 个词（= 当初收词那一批）。
    #    ⇒ 原文逐字相同就是同一条义项，**这不需要判断，是可判定的**。
    es_text_sid = {}

    # ═══ A 组：dict 的行号对齐义项集 ═══
    for did, lem, de, des, tr, mj, tsrc in con.execute(
            "SELECT id, is_lemma, definition, definition_es, translation, meta, "
            "translation_src FROM dict"):
        meta = []
        if mj:
            try:
                meta = json.loads(mj)
            except json.JSONDecodeError:
                stat["meta 解析失败"] += 1
        E, S, Z = al(de) if de else [], al(des) if des else [], al(tr) if tr else []
        n = max(len(E), len(S), len(Z))
        idx = 0
        for i in range(n):
            e = E[i].strip() if i < len(E) else ""
            s = S[i].strip() if i < len(S) else ""
            z = Z[i].strip() if i < len(Z) else ""
            if not (e or s or z):
                stat["三列全空的占位行（丢）"] += 1
                continue
            if z and PTR.match(z) and not e and not s:
                stat["🔴 指针行（丢，infl 里已有）"] += 1
                continue
            m = meta[i] if i < len(meta) and isinstance(meta[i], dict) else {}
            sid += 1
            idx += 1
            senses.append([sid, did, idx, m.get("pos"), m.get("g")])
            row_sid[(did, i)] = sid          # ⚠️ 键是原始行号 i
            nxt_rank[did] = idx
            stat["A 组义项"] += 1
            # 证据层：这一行的原文由哪一版给出。⚠️ 同一行可能两版都有话说
            # （`definition` 与 `definition_es` 并存），那就是两条 sense_src 编入同一条 sense
            # —— 本步骤唯一会出现的「多对一」，且它由数据本身决定，不是判断。
            if e:
                srcs.append((did, sid, "en-edition", f"dict:{did}#{i}:en", "en", e, None))
                glosses.append((sid, "en", "equivalent", 0, e, "en-edition"))
            if s:
                srcs.append((did, sid, "es-edition", f"dict:{did}#{i}:es", "es", s, None))
                glosses.append((sid, "es", "definition", 0, s, "es-edition"))
                es_text_sid.setdefault((did, s), sid)   # 见下面「逐字相同」的合并
            if z:
                # 🔴 `kind` 按**中文是从哪种原文翻来的**判，不是按「有没有英文」判。
                #    第一版写的是 `"equivalent" if e else "definition"`，把
                #    「只有中文、两版原文都没有」那 8,808 行判成了定义式 —— 可它们是
                #    `女朋友` / `拳击场` / `母猴` 这类 LLM 直接生成的**短对应词**
                #    （中位 7 字，与英文侧的 6 字同量级）。判错的后果被闸② 逮到：
                #    它们与并进来的西语定义撞成 280 条 (sense_id,zh,definition) 重复。
                glosses.append((sid, "zh", "definition" if s else "equivalent", 0, z,
                                m.get("src") or tsrc))
            if not (e or s):
                # 只有中文、两版原文都没有的行（LLM 补的义项），也要留证据坐标
                srcs.append((did, sid, "zh-only", f"dict:{did}#{i}:zh", "zh", z, None))
                stat["  只有中文、无原文的行"] += 1
            # A 组的 meta 已经按 top/reg/lex/num 分好了桶，但**取值仍要过 tag_kind 归一**，
            # 否则两套词汇并存：按 `dated` 筛会漏掉西语版那 4,188 条 `outdated`。
            for kk, kind in (("top", "topic"), ("reg", "region"),
                             ("lex", "register"), ("num", "number")):
                for v in (m.get(kk) or []):
                    k2, v2 = tag_kind(v)
                    tags.append((sid, kind, v2 if (k2 == kind and v2) else v))

    a_end = sid
    # ═══ B 组：sense_es 西语版自有义项 —— 西语做骨架，英文对应词并进来 ═══
    rows = con.execute(
        "SELECT id, dict_id, idx, gloss, zh, zh_src, tags, pos_title, pos FROM sense_es "
        "ORDER BY dict_id, idx").fetchall()
    en_i_of = dict(con.execute("SELECT id, en_i FROM sense_es"))
    # 先数每条英文义项被几条西语义项认领 —— 决定「搬不搬对应词」
    claimers = collections.defaultdict(list)
    for esid, did, *_ in rows:
        e = en_i_of.get(esid)
        if e is not None and (did, e) in row_sid:
            claimers[(did, e)].append(esid)
    by_sid = {s[0]: s for s in senses}          # 并入时要回填 pos/gender

    for esid, did, idx, gl, zh, zsrc, tj, pt, epos in rows:
        tl = json.loads(tj) if tj else []
        e = en_i_of.get(esid)
        grp = claimers.get((did, e), []) if e is not None else []
        # 只有该组的**第一位**认领者与英文义项合并；其余各自独立
        # （否则一条「眼睛」会搬给 4 条义项，用户以为是重复条目）
        if grp and grp[0] == esid:                      # 按 en_i 对齐结果合并
            merge_into = row_sid[(did, e)]
            stat["① 并入英文义项（独占）" if len(grp) == 1
                 else "② 并入英文义项（共享组首条）"] += 1
        elif (did, gl) in es_text_sid:                  # 西语原文逐字相同 ⇒ 同一条
            merge_into = es_text_sid[(did, gl)]
            stat["④ 并入原文逐字相同的义项（去重）"] += 1
        else:
            merge_into = None
        if merge_into is not None:
            tgt = merge_into
        else:
            sid += 1
            nxt_rank[did] += 1
            # 🔴 pos / gender 别留 NULL：`sense_es.pos` 与 `pos_title` 本来就有
            #    （`pos_title` 100% 非空，性别就写在标题里：Sustantivo masculino）
            s = [sid, did, nxt_rank[did],
                 POS_MAP.get(epos, epos) if epos else None, gender_of(pt, tl)]
            senses.append(s)
            by_sid[sid] = s
            tgt = sid
            stat["③ 独立成义项（英文版没有或共享组非首条）"] += 1

        srcs.append((did, tgt, "es-edition", f"sense_es:{esid}", "es", gl, tj))
        glosses.append((tgt, "es", "definition", 0, gl, "es-edition"))
        if zh:
            glosses.append((tgt, "zh", "definition", 0, zh, zsrc))
        # 并入时回填 pos/gender：英文义项的 meta 常常没有性别，而西语版的
        # `pos_title` 100% 非空且性别写在标题里（Sustantivo masculino）⇒ 补空不覆盖
        if merge_into is not None:
            s = by_sid[tgt]
            if not s[3] and epos:
                s[3] = POS_MAP.get(epos, epos)
            if not s[4]:
                s[4] = gender_of(pt, tl)
        for t in tl:
            k, v = tag_kind(t)
            if k == "__gram":
                stat["  B 组语法标签（有专列，不进 sense_tag）"] += 1
            elif k:
                tags.append((tgt, k, v))
            else:
                untagged[t] += 1

    # ═══ C 组：`sense_add` 补收义项（2026-08-10）═══
    # 来源见 `ingest_sense_gap.py`：两份 dump 里有、库里没落地的 1,963 条。
    # 🔴 **必须在这里读、不能事后往 `sense` 表插行** —— 本函数所在的脚本是
    #    DROP 重建四张表的，事后插的行下一次重建就没了（[[replay-scripts-undo-fixes]]：
    #    `UNIQUE` 保证不重复，不保证不倒退）。放在输入端，重建才幂等。
    #
    # 三种落法，`dup_of` 由翻译那步与中文**一次调用产出**（多吐一个字段零成本）：
    #   · `dup_of` 有值 → 并进那条已有义项，只添原文/中文的另一种说法，**不新起一条**
    #     （`qué onda` 的 `what's up?, what's wrong?` 不该和已有的「你好吗」并排显示两遍）
    #   · `meta.parent` 有值且父义项在本词里找得到 → 挂在父义项下（`teléfono` 的「手机」
    #     是 `telephone (…)` 的子义，平铺出来看不出从属，`Como` 的 8 个美国小镇更是噪音）
    #   · 其余 → 独立成条，排在该词末尾
    if con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                   "AND name='sense_add'").fetchone()[0]:
        # 两张定位表，键都是**原文**不是下标/id —— 出版层每次重建 id 都会变，
        # 存 id 或下标就是「按行号对齐」那个已经咬过三次的契约的又一变体。
        wid_of = {s[0]: s[1] for s in senses}
        en_text_sid, zh_text_sid = {}, {}
        for sid_, la, ki, _s, tx, _src in glosses:
            if la == "en":
                en_text_sid.setdefault((wid_of[sid_], tx), sid_)   # → meta.parent 找上位义
            elif la == "zh":
                zh_text_sid.setdefault((wid_of[sid_], tx), sid_)   # → dup_zh 找判重目标

        # 🔴 挂在上位义下的**只能是枚举**，判据是「这个父义带几个子义」。
        #    带 1–3 个的是真·独立义项：`teléfono` 的「手机」「转盘电话」、
        #    `Carintia` 的两个地名 —— 挂上去就看不见了，因为展示层一条义项只取
        #    **最短和最长**两条中文（`spanish.ts` buildUnified），中间的全被吞掉。
        #    「补回来却显示不出来，等于没补。」
        #    带 ≥4 个的全是枚举：`lastón`「Grass from any of several species:」13 个物种、
        #    `San Fernando`「Several cities in the Philippines」7 个地名 ——
        #    这些平铺进弹窗就是噪音，折进父义项才对。
        kid_n = collections.Counter()
        for w_, mj_ in con.execute("SELECT word, meta FROM sense_add WHERE meta LIKE '%parent%'"):
            try:
                p_ = json.loads(mj_).get("parent")
            except json.JSONDecodeError:
                p_ = None
            if p_:
                kid_n[(w_, p_)] += 1
        ENUM_MIN = 4

        # 🔴 判重复核（2026-08-11）：`dup_verdict` ∈ {bad, weak} 的**不采纳合并**。
        #    186 条判重里 21 条错配、28 条存疑（v4-pro 全量普查，186/186；
        #    负控 28/28 该家可用，豆包同批 4/30 已作废）。典型错配：
        #      peón「pawn / checker」并进「行人。」 / fierro「race car」并进「油门」
        #    用户 2026-08-07：「不要把义项和释义错配了，那才是真灾难。」
        #    ⚠️ 判决存在 `sense_add.dup_verdict`，`dup_zh` **原样保留** ——
        #       想改主意（比如放行 weak）只改下面这个集合，不必重跑判官。
        DUP_BLOCK = ("bad", "weak")
        has_verdict = bool(con.execute(
            "SELECT COUNT(*) FROM pragma_table_info('sense_add') "
            "WHERE name='dup_verdict'").fetchone()[0])
        vsel = ", dup_verdict" if has_verdict else ", NULL"
        if not has_verdict:
            print("  ⚠️ `sense_add` 没有 dup_verdict 列 —— 判重复核结论未落库，"
                  "本轮按「全部采纳」重建（先跑 fixes/apply_dup_verdicts.py）")

        for aid, w, did, lang, gl, apos, apt, tj, mj, zh, zsrc, dup, dver in con.execute(
                "SELECT id, word, dict_id, lang, gloss, pos, pos_title, tags, meta, "
                "zh, zh_src, dup_zh" + vsel + " FROM sense_add ORDER BY id"):
            if dver in DUP_BLOCK:
                stat[f"C① 判重复核不通过（{dver}）⇒ 独立成条"] += 1
                dup = None
            if did is None:
                stat["C 组 dict_id 为空（跳过）"] += 1
                continue
            try:
                m = json.loads(mj) if mj else {}
            except json.JSONDecodeError:
                m = {}
            tl = json.loads(tj) if tj else []

            tgt = None
            if dup and (did, dup) in zh_text_sid:
                tgt = zh_text_sid[(did, dup)]
                stat["C① 并入已有义项（判重）"] += 1
            elif dup:
                stat["C① 判重目标的中文在本轮找不到（当独立处理）"] += 1
            # C⓪ 中文逐字相同 ⇒ 同一条义项。**不需要判断，是可判定的**，
            # 与上面第④档「原文逐字相同」同理。同一个概念英文版和西语版各说一遍、
            # 各自翻成同一句中文的很常见（`Cretáceo` 两条都译作「白垩纪」，
            # 不并就在界面上出现两遍）。两边原文都留着，走 seq 各占一行。
            if tgt is None and zh and (did, zh) in zh_text_sid:
                tgt = zh_text_sid[(did, zh)]
                stat["C⓪ 并入中文逐字相同的义项（去重）"] += 1
            elif (m.get("parent") and (did, m["parent"]) in en_text_sid
                  and kid_n[(w, m["parent"])] >= ENUM_MIN):
                tgt = en_text_sid[(did, m["parent"])]
                stat[f"C② 折进上位义项（枚举，同父 ≥{ENUM_MIN} 条）"] += 1
            elif m.get("parent"):
                stat["C② 有上位义但不是枚举（≤3 条）⇒ 独立成条"] += 1
            if tgt is None:
                sid += 1
                nxt_rank[did] += 1
                senses.append([sid, did, nxt_rank[did], apos, gender_of(apt, tl)])
                wid_of[sid] = did
                tgt = sid
                stat["C③ 独立成义项"] += 1

            srcs.append((did, tgt, "en-edition" if lang == "en" else "es-edition",
                         f"sense_add:{aid}", lang, gl, tj))
            glosses.append((tgt, lang, "equivalent" if lang == "en" else "definition",
                            0, gl, "sense_add"))
            if zh:
                glosses.append((tgt, "zh", "equivalent" if lang == "en" else "definition",
                                0, zh, zsrc))
                zh_text_sid.setdefault((did, zh), tgt)   # 让后面的 C 行能并到这条上
            for t in tl:
                k, v = tag_kind(t)
                if k and k != "__gram":
                    tags.append((tgt, k, v))

    # ═══ 归属覆盖 `sense_owner`：把义项还给它真正所属的词形 ═══
    # 🔴 2026-08-10 血的教训：`split_case_homographs.py` / `recheck_emptied_lowercase.py`
    #    直接 `UPDATE sense.word_id` 把 4,501 条义项从小写行挪到了大写专名行
    #    （`argentina`→`Argentina`、`chad`→`Chad`）。本脚本是 **DROP 重建**的，
    #    跑一次就把那两个脚本的成果**全部撤销**，`Argentina` 的义项当场归零。
    #    这正是 [[replay-scripts-undo-fixes]]，而且是我写完警告之后自己踩的。
    # ⇒ 归属做成**数据**（`sense_owner` 表），键是 `src_ref` —— 重建后仍稳定的回源坐标。
    #    ⚠️ 绝不能存 `sense.id`：每次重建都重新编号。那两个脚本的模型判定缓存
    #    （`split_case_llm.jsonl`）就是按 `sense.id` 存的，重跑会把判定套到错误的义项上。
    if con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                   "AND name='sense_owner'").fetchone()[0]:
        did_of_word = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
        owner = {}
        for ref, w_ in con.execute("SELECT src_ref, word FROM sense_owner"):
            if w_ in did_of_word:
                owner[ref] = did_of_word[w_]
        # 一条义项可能有多条证据；只要有一条被指名，整条义项跟着走（拆分就是整条搬）
        move = {}
        for did_, sid_, _src, ref, *_ in srcs:
            if ref in owner:
                move.setdefault(sid_, owner[ref])
        by_sid_ = {s[0]: s for s in senses}
        moved = 0
        for sid_, new_did in move.items():
            s_ = by_sid_.get(sid_)
            if s_ and s_[1] != new_did:
                s_[1] = new_did
                moved += 1
        # 证据层的 word_id 跟着义项走，否则 `sense_src.word_id` 与 `sense.word_id` 打架
        srcs = [(move.get(sid_, did_), sid_, *rest) for did_, sid_, *rest in srcs]
        # rank 重排：搬家之后 (word_id, rank) 会撞，按原顺序在新主人下重新编号
        seq_ = collections.Counter()
        for s_ in senses:
            seq_[s_[1]] += 1
            s_[2] = seq_[s_[1]]
        stat["归属覆盖：义项改挂到专名词头"] = moved

    # ═══ seq：同一 (义项, 语言, kind) 下可以有多条文本 ═══
    # 🔴 这不是补丁，正是 `seq` 存在的理由。两个来源对同一条义项各说了一遍时：
    #      文本**相同** → 去重留一条（`adra` 的 `definition_es` 与 `sense_es` 是同一份
    #                    dump 的冻结副本，逐字一致，留两条只是噪声；
    #                    两个来源的证据仍完整保留在 `sense_src` 里，溯源不丢）
    #      文本**不同** → 各占一行（`pata` 的「平局；打平」与「平局，打平」是两次独立
    #                    翻译，都对，谁也不比谁权威 ⇒ 都留着，展示层取 seq=0）
    # 闸② 的 (sense_id, lang, kind, seq) 唯一性由此成立。
    # ⚠️ 2026-08-10 试过在这里再加一道「中文跨 kind 逐字相同就去重」，**被闸①拦下**，
    #    已撤回。闸①要核「`translation` 第 i 行的中文在不在该义项的**对应 kind** 下」，
    #    删掉其中一个 kind 的行，回核当场对不上。
    #    而且那样想也不对：`Cretáceo` 的 zh/equivalent（译自英文 `the Cretaceous`）
    #    与 zh/definition（译自西语定义）**是两条来源不同的记录**，逐字撞车是巧合，
    #    删一条就丢了「这句中文是从哪边翻来的」。全库 646 条这种。
    #    ⇒ 数据两条都留，**由展示层取唯一中文**（见 `spanish.ts` 的 buildUnified）。
    seen, out = collections.defaultdict(list), []
    for sid_, la, ki, _seq, tx, src in glosses:
        bucket = seen[(sid_, la, ki)]
        if tx in bucket:
            stat["  两来源文本一致，去重"] += 1
            continue
        out.append((sid_, la, ki, len(bucket), tx, src))
        bucket.append(tx)
    stat["  两来源文本不同，seq 各占一行"] = sum(
        len(v) - 1 for v in seen.values() if len(v) > 1)

    stat["__a_end"] = a_end
    return srcs, senses, out, tags, stat, untagged


def verify_reversible(con) -> None:
    """闸① 可逆性回核 —— **100% 全量，不是抽样**。

    🔴 用户 2026-08-07：「不要把义项和释义错配了，那才是真灾难」。
    这类错（`novia` 那一族）**必须靠设计防住**：抽 100 条看不出 0.3% 的错配，
    而 0.3% 就是一千多个词条给用户看错的中文。

    做法是把问题从「抽样」变成「可判定」——**双向**逐字节比对：

      正向：每条 sense_src 按 `src_ref` 定位回原始 (dict 行, 第几行)，
            比对 `text` 与该行原文；再比对挂在同一条 sense 上的 zh gloss
            与 `translation` 的**同一行**。错配一定会在这里露出来。
      反向：`dict` 里每一条**非指针**的义项行都必须有对应的 sense_src。
            少一条就是静默漏收 —— 只做正向查不出来。

    两个方向都过，才说明「一条不多、一条不少、一条不错位」。
    """
    print("\n═══ 闸① 可逆性回核（全量，非抽样）═══")
    dic = {i: (de, des, tr) for i, de, des, tr in con.execute(
        "SELECT id, definition, definition_es, translation FROM dict")}
    ses = {i: (g, z) for i, g, z in con.execute(
        "SELECT id, gloss, zh FROM sense_es")}
    # C 组（`sense_add`，2026-08-10 补收）。⚠️ 加这一支之前，`src_ref` 以
    # `sense_add:` 开头的 1,963 条在下面的 if/elif 里**静默落空** —— 闸看着通过，
    # 其实一条都没核。「一条永远通过的检查等于没检查」的活标本。
    add = {i: (la, g, z) for i, la, g, z in con.execute(
        "SELECT id, lang, gloss, zh FROM sense_add")} \
        if con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                       "AND name='sense_add'").fetchone()[0] else {}
    # 🔴 键必须带 kind：合并之后一条义项有**两条中文**——从英文对应词翻来的
    #    zh/equivalent（眼睛）和从西语定义翻来的 zh/definition（对光敏感…）。
    #    只按 lang 建键会让后者覆盖前者，核对就形同虚设。
    #    值是**集合**：同一 (语言, kind) 下可以有多条（seq 0,1…），
    #    两个来源对同一条义项各说了一遍且措辞不同时就会这样。核对看「在不在其中」。
    zh_of = collections.defaultdict(lambda: collections.defaultdict(set))
    for sid, la, ki, tx in con.execute(
            "SELECT sense_id, lang, kind, text FROM sense_gloss"):
        zh_of[sid][(la, ki)].add(tx)

    bad = collections.Counter()
    ex = []
    seen_lines = set()
    n = 0
    for sid, wid, src, ref, lang, text in con.execute(
            "SELECT sense_id, word_id, src, src_ref, lang, text FROM sense_src"):
        n += 1
        if ref.startswith("dict:"):
            body = ref[5:]
            did_s, rest = body.split("#", 1)
            i_s, which = rest.split(":", 1)
            did, i = int(did_s), int(i_s)
            seen_lines.add((did, i))
            de, des, tr = dic[did]
            col = {"en": de, "es": des, "zh": tr}[which]
            want = al(col)[i].strip() if col and i < len(al(col)) else ""
            if want != text:
                bad["sense_src.text 与源行对不上"] += 1
                if len(ex) < 6:
                    ex.append((ref, text[:40], want[:40]))
            # 🔴 `sense_gloss` 里的原文行也要核。2026-08-07 变异验证逮出的洞：
            #    此前只核 `sense_src.text`，`sense_gloss` 那一份被篡改**抓不住**
            #    （`sense_es` 来源那一支核了，`dict` 这一支漏了）。
            gk = ("en", "equivalent") if which == "en" else \
                 ("es", "definition") if which == "es" else None
            if gk and want and want not in zh_of[sid][gk]:
                bad[f"🔴 sense_gloss 的 {gk[0]} 原文与源行对不上"] += 1
                if len(ex) < 6:
                    ex.append((ref + f" [{gk[0]}]", str(sorted(zh_of[sid][gk]))[:40],
                               want[:40]))
            # 中文必须来自**同一行**，错位就在这里现形。
            # dict 来源的中文：从西语定义翻来的是定义式，其余（英文对应词、
            # LLM 直接生成的短对应词）都是对应词式。与 collect() 里的判据必须一致。
            kind = "definition" if which == "es" else "equivalent"
            z = zh_of[sid][("zh", kind)]
            wz = al(tr)[i].strip() if tr and i < len(al(tr)) else ""
            if wz and wz not in z:
                bad["🔴 中文与原文不同行（错配）"] += 1
                if len(ex) < 6:
                    ex.append((ref + f" [zh/{kind}]", str(sorted(z))[:40], wz[:40]))
        elif ref.startswith("sense_add:"):
            aid = int(ref.split(":", 1)[1])
            la, g, z = add[aid]
            gk = ("en", "equivalent") if la == "en" else ("es", "definition")
            if g != text:
                bad["sense_src.text 与 sense_add 对不上"] += 1
            if g not in zh_of[sid][gk]:
                bad[f"🔴 sense_gloss 的 {la} 原文与 sense_add 对不上"] += 1
            if z and z not in zh_of[sid][("zh", gk[1])]:
                bad["🔴 中文与 sense_add 对不上"] += 1
        elif ref.startswith("sense_es:"):
            esid = int(ref.split(":", 1)[1])
            g, z = ses[esid]
            if g not in zh_of[sid][("es", "definition")]:
                bad["原文与 sense_es 对不上"] += 1
            if g != text:
                bad["sense_src.text 与 sense_es 对不上"] += 1
            # sense_es 的中文永远是定义式
            if z and z not in zh_of[sid][("zh", "definition")]:
                bad["🔴 中文与 sense_es 对不上"] += 1

    print(f"  正向：核对 {n:,} 条 sense_src")
    for k, v in bad.most_common():
        print(f"    {k:<26}{v:>8,}")
    for r, got, want in ex:
        print(f"      {r}\n        新表={got!r}\n        原文={want!r}")

    # 反向：dict 里每条非指针义项行都必须被收进来
    miss = 0
    for did, (de, des, tr) in dic.items():
        E, S, Z = al(de) if de else [], al(des) if des else [], al(tr) if tr else []
        for i in range(max(len(E), len(S), len(Z))):
            e = E[i].strip() if i < len(E) else ""
            s = S[i].strip() if i < len(S) else ""
            z = Z[i].strip() if i < len(Z) else ""
            if not (e or s or z):
                continue
            if z and PTR.match(z) and not e and not s:
                continue
            if (did, i) not in seen_lines:
                miss += 1
    print(f"  反向：dict 里未被收进 sense_src 的非指针义项行 {miss:,}")
    nes = con.execute("SELECT COUNT(*) FROM sense_es").fetchone()[0]
    nsrc_es = con.execute(
        "SELECT COUNT(*) FROM sense_src WHERE src_ref LIKE 'sense_es:%'").fetchone()[0]
    print(f"        sense_es 未被收进的 {nes - nsrc_es:,}")
    nadd = len(add)
    nsrc_add = con.execute(
        "SELECT COUNT(*) FROM sense_src WHERE src_ref LIKE 'sense_add:%'").fetchone()[0]
    print(f"        sense_add 未被收进的 {nadd - nsrc_add:,}")

    ok = not bad and miss == 0 and nes == nsrc_es and nadd == nsrc_add
    print(f"  {'✅ 闸① 通过：一条不多、一条不少、一条不错位' if ok else '🔴 闸① 未通过'}")
    assert ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    srcs, senses, glosses, tags, stat, untagged = collect(con)
    con.close()

    print("═══ 来源分流 ═══")
    for k, v in stat.most_common():
        if not k.startswith("__"):
            print(f"  {k:<26}{v:>10,}")
    print(f"\nsense_src   {len(srcs):>10,}   证据层（永不删改）")
    print(f"sense       {len(senses):>10,}   出版层（本步骤 1:1，不合并）")
    print(f"sense_gloss {len(glosses):>10,}")
    print(f"sense_tag   {len(tags):>10,}")
    print("\nsense_src 按 src：" + "  ".join(
        f"{k}={v:,}" for k, v in collections.Counter(s[2] for s in srcs).most_common()))

    lang = collections.Counter((g[1], g[2]) for g in glosses)
    print("\nsense_gloss 按 (lang, kind)：")
    for (la, ki), v in lang.most_common():
        print(f"  {la:<4}{ki:<12}{v:>10,}")
    kinds = collections.Counter(t[1] for t in tags)
    print("\nsense_tag 按 kind：" + "  ".join(f"{k}={v:,}" for k, v in kinds.most_common()))
    # 🔴「跳过」那栏必须逐条看得见
    print(f"\nsense_es.tags 里未归桶的 tag：{len(untagged)} 种 / {sum(untagged.values()):,} 次")
    print(f"  前 12：{[k for k, _ in untagged.most_common(12)]}")

    # ═══ 闸② 不变量断言 ═══
    print("\n═══ 闸② 不变量断言 ═══")
    ids = {s[0] for s in senses}
    assert len(ids) == len(senses), "sense id 重复"
    assert {g[0] for g in glosses} <= ids, "sense_gloss 指向不存在的 sense"
    assert {t[0] for t in tags} <= ids, "sense_tag 指向不存在的 sense"
    assert {s[1] for s in srcs} <= ids, "sense_src 指向不存在的 sense"
    dup = collections.Counter((s[1], s[2]) for s in senses)
    bad = [k for k, v in dup.items() if v > 1]
    print(f"  (word_id, rank) 重复：{len(bad)}  {bad[:3]}")
    assert not bad
    gdup = collections.Counter((g[0], g[1], g[2], g[3]) for g in glosses)
    gbad = [k for k, v in gdup.items() if v > 1]
    print(f"  (sense_id, lang, kind, seq) 重复：{len(gbad)}  {gbad[:3]}")
    assert not gbad
    rdup = collections.Counter(s[3] for s in srcs)
    rbad = [k for k, v in rdup.items() if v > 1]
    print(f"  src_ref 重复（回源坐标必须唯一）：{len(rbad)}  {rbad[:3]}")
    assert not rbad
    # ⚠️ 不能用「义项数 − zh 行数」算：合并后一条义项可能**同时**有
    #    zh/equivalent（眼睛）与 zh/definition（对光敏感…），减法会算出负数
    have_zh = {g[0] for g in glosses if g[1] == "zh"}
    nozh = len(ids - have_zh)
    print(f"  没有中文的义项：{nozh}")
    assert nozh == 0, "全库义项应 100% 有中文"
    # ⚠️ 集合先建好再取交，别写进循环里（第一版每条义项都重建两个 39 万元素的集合）
    zh_eq = {g[0] for g in glosses if g[1] == "zh" and g[2] == "equivalent"}
    zh_df = {g[0] for g in glosses if g[1] == "zh" and g[2] == "definition"}
    print(f"  同时有短对应词与定义的义项：{len(zh_eq & zh_df):,}  ← 合并的直接产物")
    print(f"  🔴 只有长定义、缺短对应词：{len(zh_df - zh_eq):,}  ← 弹窗里扫不动的那批")
    noev = len(senses) - len({s[1] for s in srcs})
    print(f"  没有任何证据的义项：{noev}")
    assert noev == 0, "每条出版义项都必须至少有一条 sense_src"

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    with dbtool.session("build-sense-layer", expect={}) as s:
        for t in TABLES:
            s.execute(f"DROP TABLE IF EXISTS {t}")
        for d in DDL:
            s.execute(d)
        for i in IDX:
            s.execute(i)
        s.executemany(
            "INSERT INTO sense (id, word_id, rank, pos, gender) VALUES (?,?,?,?,?)", senses)
        s.executemany(
            "INSERT INTO sense_src (word_id, sense_id, src, src_ref, lang, text, raw_tags) "
            "VALUES (?,?,?,?,?,?,?)", srcs)
        s.executemany(
            "INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src) "
            "VALUES (?,?,?,?,?,?)", glosses)
        s.executemany(
            "INSERT OR IGNORE INTO sense_tag (sense_id, kind, value) VALUES (?,?,?)", tags)

    # ═══ 写后核对：新表不在 dbtool.snapshot 视野里，自己验 ═══
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    q = lambda x: con.execute(x).fetchone()[0]          # noqa: E731
    print("\n落库核对：")
    for t in TABLES:
        print(f"  {t:<12}{q(f'SELECT COUNT(*) FROM {t}'):>10,}")
    orphan = q("SELECT COUNT(*) FROM sense WHERE word_id NOT IN (SELECT id FROM dict)")
    og = q("SELECT COUNT(*) FROM sense_gloss WHERE sense_id NOT IN (SELECT id FROM sense)")
    osr = q("SELECT COUNT(*) FROM sense_src WHERE sense_id NOT IN (SELECT id FROM sense)")
    print(f"  悬空 word_id {orphan}   悬空 sense_id {og} / {osr}")
    verify_reversible(con)
    # 验收标准（§7）：加一门语言只需往 sense_gloss 加行
    print("\n⭐ 加一门语言的样子（不改结构、不动已有数据）：")
    print("     INSERT INTO sense_gloss (sense_id, lang, kind, text, src)")
    print("     SELECT id, 'vi', 'equivalent', ?, 'llm' FROM sense WHERE …")
    need_vi = q("SELECT COUNT(*) FROM sense s WHERE NOT EXISTS ("
                "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='vi')")
    print(f"     缺越南语的义项数：{need_vi:,}   ← 这句查询就是「该不该把越南语放进"
          "语言列表」的判据（§7.3）")
    con.close()
    assert orphan == 0 and og == 0


if __name__ == "__main__":
    main()
