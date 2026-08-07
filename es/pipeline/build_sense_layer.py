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
    """CREATE TABLE sense (
         id      INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id INTEGER NOT NULL,        -- → dict.id
         rank    INTEGER NOT NULL,        -- 展示顺序 1,2,3…（v1 那个混来源的 idx 取消）
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

    🔴 **本步骤 1:1，一条源义项 = 一条出版义项，不做任何合并。**
    理由是可验证性：1:1 时闸①（可逆性回核）能做到逐字节精确 ——
    每条 `sense_src.src_ref` 都能定位回原始的 (dict 行, 第几行)，比对不上就是错配。
    合并（按 `en_i` 把 en 义项编进 es 义项）是**第二步**，单独建、单独验。

    `sense_gloss.seq` 本步骤恒为 0：拆「眼睛；眼」这类多对应词是编纂决策，
    不是机械转换，留给后续步骤。
    """
    srcs, senses, glosses, tags = [], [], [], []
    stat = collections.Counter()
    untagged = collections.Counter()
    sid = 0

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
            senses.append((sid, did, idx, m.get("pos"), m.get("g")))
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
            if z:
                # zh 从哪边翻来的，决定它是对应词还是定义
                glosses.append((sid, "zh", "equivalent" if e else "definition", 0, z,
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
    # ═══ B 组：sense_es 西语版自有义项（另一套编号，不合并）═══
    nxt = collections.Counter()   # word_id → 下一个可用 rank（接着 A 组往后排）
    for s in senses:
        nxt[s[1]] = max(nxt[s[1]], s[2])

    for esid, did, gl, zh, zsrc, tj, pt, epos in con.execute(
            "SELECT id, dict_id, gloss, zh, zh_src, tags, pos_title, pos FROM sense_es "
            "ORDER BY word, idx"):
        tl = json.loads(tj) if tj else []
        sid += 1
        nxt[did] += 1
        # 🔴 pos / gender 别留 NULL：`sense_es.pos` 与 `pos_title` 本来就有
        #    （`pos_title` 100% 非空，且性别就写在标题里：Sustantivo masculino）。
        #    第一版把这两列写死成 None，等于把源头现成的东西丢了。
        senses.append((sid, did, nxt[did],
                       POS_MAP.get(epos, epos) if epos else None,
                       gender_of(pt, tl)))
        srcs.append((did, sid, "es-edition", f"sense_es:{esid}", "es", gl, tj))
        stat["B 组义项（sense_es）"] += 1
        glosses.append((sid, "es", "definition", 0, gl, "es-edition"))
        if zh:
            glosses.append((sid, "zh", "definition", 0, zh, zsrc))
        for t in tl:
            k, v = tag_kind(t)
            if k == "__gram":
                stat["  B 组语法标签（有专列，不进 sense_tag）"] += 1
            elif k:
                tags.append((sid, k, v))
            else:
                untagged[t] += 1

    stat["__a_end"] = a_end
    return srcs, senses, glosses, tags, stat, untagged


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    senses, glosses, tags, stat, untagged = collect(con)
    con.close()

    print("═══ 来源分流 ═══")
    for k, v in stat.most_common():
        if not k.startswith("__"):
            print(f"  {k:<26}{v:>10,}")
    print(f"\nsense       {len(senses):>10,}")
    print(f"sense_gloss {len(glosses):>10,}")
    print(f"sense_tag   {len(tags):>10,}")

    lang = collections.Counter((g[1], g[2]) for g in glosses)
    print("\nsense_gloss 按 (lang, kind)：")
    for (la, ki), v in lang.most_common():
        print(f"  {la:<4}{ki:<12}{v:>10,}")
    kinds = collections.Counter(t[1] for t in tags)
    print("\nsense_tag 按 kind：" + "  ".join(f"{k}={v:,}" for k, v in kinds.most_common()))
    # 🔴「跳过」那栏必须逐条看得见
    print(f"\nsense_es.tags 里未归桶的 tag：{len(untagged)} 种 / {sum(untagged.values()):,} 次")
    print(f"  前 12：{[k for k, _ in untagged.most_common(12)]}")

    # ═══ 断言 ═══
    ids = {s[0] for s in senses}
    assert len(ids) == len(senses), "sense id 重复"
    assert {g[0] for g in glosses} <= ids, "sense_gloss 指向不存在的 sense"
    assert {t[0] for t in tags} <= ids, "sense_tag 指向不存在的 sense"
    dup = collections.Counter((s[1], s[2]) for s in senses)
    bad = [k for k, v in dup.items() if v > 1]
    print(f"\n断言① (word_id, idx) 重复：{len(bad)}  {bad[:3]}")
    assert not bad
    gdup = collections.Counter((g[0], g[1], g[2]) for g in glosses)
    gbad = [k for k, v in gdup.items() if v > 1]
    print(f"断言② (sense_id, lang, kind) 重复：{len(gbad)}  {gbad[:3]}")
    assert not gbad
    nozh = len(senses) - lang[("zh", "equivalent")] - lang[("zh", "definition")]
    print(f"断言③ 没有中文的义项：{nozh}")
    assert nozh == 0, "全库义项应 100% 有中文"

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
            "INSERT INTO sense (id, word_id, idx, pos, gender, src, src_ref) "
            "VALUES (?,?,?,?,?,?,?)", senses)
        s.executemany(
            "INSERT INTO sense_gloss (sense_id, lang, kind, text, src) VALUES (?,?,?,?,?)",
            glosses)
        s.executemany(
            "INSERT OR IGNORE INTO sense_tag (sense_id, kind, value) VALUES (?,?,?)", tags)

    # ═══ 写后核对：新表不在 dbtool.snapshot 视野里，自己验 ═══
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    q = lambda x: con.execute(x).fetchone()[0]          # noqa: E731
    print("\n落库核对：")
    print(f"  sense        {q('SELECT COUNT(*) FROM sense'):>10,}")
    print(f"  sense_gloss  {q('SELECT COUNT(*) FROM sense_gloss'):>10,}")
    print(f"  sense_tag    {q('SELECT COUNT(*) FROM sense_tag'):>10,}")
    orphan = q("SELECT COUNT(*) FROM sense WHERE word_id NOT IN (SELECT id FROM dict)")
    og = q("SELECT COUNT(*) FROM sense_gloss WHERE sense_id NOT IN (SELECT id FROM sense)")
    print(f"  悬空 word_id {orphan}   悬空 sense_id {og}")
    print(f"  已分配 concept_id 的义项 "
          f"{q('SELECT COUNT(*) FROM sense WHERE concept_id IS NOT NULL')}（应为 0）")
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
