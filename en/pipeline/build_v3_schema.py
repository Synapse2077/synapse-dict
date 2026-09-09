#!/usr/bin/env python3
"""阶段 0：英语库 v3 结构 —— 建 `dict` + 十一张出版层表，把老 `stardict` 改名冻存。2026-09-07。

结构照 `docs/SCHEMA.md`，**不重新设计**。计划见 `docs/EN_PLAN.md` 阶段 0。
本文件是 `de/pipeline/build_v3_schema.py` 的英语版（拷贝＋改语种特有部分，铁律①按语种解耦）。

═══ 🔴 en 的阶段 0 与前五门**性质不同** ═══
de/pt/fr 的阶段 0 是**迁移**：`dict` 早就存在，把 `definition`/`translation`/`meta`
三根按行号对齐的字符串拆成 `sense`/`sense_gloss`/`sense_tag`。

**en 没有可迁移的东西** —— 库里只有 ECDICT 形状的 `stardict`，而按 `EN_PLAN` §〇 的定调，
它的释义**不进 v3 释义层**（"义项分开不明显、没有例句"正是要甩掉的）。
⇒ 本步只做两件事：**建空表** ＋ **老表改名冻存**。数据在阶段 3a 从 kaikki 灌。

⭐ 因此 en 反而拿到一个前五门都没有的便宜：**可以不带历史包袱建表**。见下面两处「有意不照搬」。

═══ 两处有意不照搬 de ═══

① 🔴 **`dict` 不设 `ipa` 列。**
   de 的 `dict.ipa` 是 v3 之前留下的扁平列，阶段 8 换读取路径之后**读者就看不见它了**，
   而闸查原列永远绿 —— 那就是 de 收尾单 C41（`DE_PLAN` §四之五 / 阶段 4 那条按语）。
   de 是"改不掉了只能记账"，en 是**新建，压根不长这个器官**。
   ⇒ 音标只有 `pronunciation` 一个家。`[[fix-regression-and-gate]]` 第二种机制从结构上消失。

② 🔴 **`dict` 不设 `definition`/`translation`/`meta`/`collocation`/`example`。**
   同理：那五列在 de/pt 是迁移的**来源**，迁完要 `--drop-cols`（de 拖到 2026-09-05 才跑掉）。
   en 没有来源要迁，建出来就是等着将来有人往里写、然后与 `sense` 层各说各话。

═══ en 的一等字段 ═══
英语形态贫乏，**没有 de 那批**（性/属格/复数/助动词/强弱/可分/反身/比较级…）。
`dict` 上只留两类：
  · 身份与形态：`word` / `word_norm` / `is_lemma` / `pos`
  · 🔴 **ECDICT 真资产**：`collins` / `oxford` / `tag` / `bnc` / `frq`
    —— 五门都没有的东西，是**尺子**（阶段 3 收词优先级、1.5 买到哪条线、9 排序全靠它）。
    本步只建列，**阶段 1 才从 `legacy_dict` 挂进来**（挂得上率 98.2–100%，`EN_PLAN` §1.5①）。
  · `freq_zipf` 阶段 5。

⚠️ **英语的动词及物性 / 名词可数性要不要进 `entry`，本步不定** ——
   那是阶段 1 的活，且必须先量（`[[es-v3-structure-backfill]]`：先量这门语言有没有那个病）。
   ECDICT 的 `vt.`/`vi.`/`n.` 前缀是个现成的量法，但**没量之前不建列**（`PITFALLS` D1）。

═══ `pronunciation` 三列一次建齐（阶段 -1 实测，`docs/lang/en-CONVENTIONS.md` §四）═══
    pos       跨词性读音真对立 **951**（de 685/357，en 比 de 还多）
                              record noun /ˈɹɛk.ɔːd/ vs verb /ɹɪˈkɔːd/
    entry_id  同词性跨词条真对立 **720**（de 3,216，es 只有 14 故不建）
                              lead 铅 /lɛd/ vs 引导 /liːd/；bow 弓 vs 鞠躬
    region    🔴 **六门里只有 en 建这一列** —— 英美分列是英语本质。
              283,962 条带 IPA 的 sounds 里 **66.4% 自带地区标记**（GA+US 28.0% / RP+UK 25.9%）
              ⇒ 从 `tags` 推，**推不出落 null 不硬填**（`[[ipa-provenance-columns]]`）。
              澳/加/新/苏/印/爱合计 15.9% 原样进 `tags`，不硬塞进英美两边。

跑：
    cd en && python3 pipeline/build_v3_schema.py            # 干跑，只打算不写
    cd en && python3 pipeline/build_v3_schema.py --run
    cd en && python3 pipeline/build_v3_schema.py --verify   # 只跑闸
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import sqlite3

import dbtool
import paths

LEGACY = "stardict"
FROZEN = "legacy_dict"

# ══════════════════ DDL ══════════════════

DDL_DICT = """CREATE TABLE dict (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    word      TEXT NOT NULL,
    word_norm TEXT NOT NULL,          -- 归一形（去变音符/小写），检索用
    is_lemma  INTEGER NOT NULL,       -- 1=词元 0=变形；阶段 2 由 inflection 定
    pos       TEXT,                   -- 词形级粗词性；逐义项词性在 sense.pos
    -- ── ECDICT 真资产（阶段 1 从 legacy_dict 挂入，五门都没有）──
    collins   INTEGER,                -- 柯林斯星级 1–5
    oxford    INTEGER,                -- 牛津三千核心词标记
    exam_tag  TEXT,                   -- 考纲标签（zk/gk/cet4/cet6/ky/toefl/ielts/gre）
    bnc       INTEGER,                -- BNC 词频排名
    freq_rank INTEGER,                -- 当代语料词频排名（越小越常用）
    -- ── 阶段 5 ──
    freq_zipf REAL
)"""

# 🔴 `sense` 不设 `gender` —— 英语没有语法性。de 那列是为 der/das/die Band 建的。
DDL_SENSE = """CREATE TABLE sense (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,         -- → dict.id
    rank    INTEGER NOT NULL,         -- 展示顺序 1,2,3…
    pos     TEXT,                     -- 逐义项词性
    UNIQUE(word_id, rank)
)"""

DDL_SENSE_SRC = """CREATE TABLE sense_src (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id  INTEGER NOT NULL,
    sense_id INTEGER,                 -- 编入哪条出版义项；NULL = 尚未裁决
    src      TEXT NOT NULL,           -- en-edition / zh-edition / ecdict（记录的，非反推）
    src_ref  TEXT NOT NULL,           -- 回源坐标
    lang     TEXT NOT NULL,
    text     TEXT NOT NULL,
    raw_tags TEXT,
    UNIQUE(src_ref)
)"""

DDL_SENSE_GLOSS = """CREATE TABLE sense_gloss (
    sense_id INTEGER NOT NULL,
    lang     TEXT NOT NULL,           -- en / zh（加语言只往这里加行）
    kind     TEXT NOT NULL,           -- equivalent / definition
    seq      INTEGER NOT NULL,
    text     TEXT NOT NULL,
    src      TEXT,
    PRIMARY KEY(sense_id, lang, kind, seq)
)"""

DDL_SENSE_TAG = """CREATE TABLE sense_tag (
    sense_id INTEGER NOT NULL,
    kind     TEXT NOT NULL,           -- topic / region / register / number
    value    TEXT NOT NULL,
    PRIMARY KEY(sense_id, kind, value)
)"""

DDL_SENSE_RELATION = """CREATE TABLE sense_relation (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id  INTEGER NOT NULL,
    sense_id INTEGER,
    kind     TEXT NOT NULL,           -- synonym / antonym / hypernym / … / alt_of
    target   TEXT NOT NULL,           -- 目标词形原样，不解析成外键
    tags     TEXT,
    hidden   INTEGER NOT NULL DEFAULT 0,
    src      TEXT NOT NULL,
    src_ref  TEXT NOT NULL,
    UNIQUE(word_id, sense_id, kind, target)
)"""

# 🔴 三列一次建齐，理由见文件头。**六门里只有 en 有 region。**
DDL_PRONUNCIATION = """CREATE TABLE pronunciation (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id    INTEGER NOT NULL,
    entry_id   INTEGER,               -- → entry.id（阶段 1 才有表）；null = 整词通用
    ipa        TEXT NOT NULL,         -- 裸存，不带定界符（六语种统一约定）
    notation   TEXT NOT NULL,         -- phonemic | narrow
    region     TEXT,                  -- uk | us | 其它；推不出一律 null，不硬填
    tags       TEXT,                  -- 源头 tags 的 JSON 数组
    pos        TEXT,                  -- 这条读音属于哪个词性；null = 整词通用
    is_primary INTEGER NOT NULL DEFAULT 0,
    src        TEXT NOT NULL,         -- en-edition | en-selfgen（项目自产 115,955 条）
    src_ref    TEXT NOT NULL,
    UNIQUE(word_id, entry_id, ipa, notation)
)"""

DDL_EXAMPLE = """CREATE TABLE example (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    word            TEXT NOT NULL,
    sense_id        INTEGER,          -- 例句挂在义项上，不是挂在词上
    text            TEXT NOT NULL,
    bold            TEXT,             -- JSON [[start,end],…]
    ref             TEXT,
    src_gloss       TEXT,             -- 源里这条挂在哪条义项下（挂回义项的桥）
    src_translation TEXT,
    src_lang        TEXT,
    hidden          INTEGER NOT NULL DEFAULT 0,
    src             TEXT NOT NULL,
    UNIQUE(word, text)
)"""

DDL_EXAMPLE_GLOSS = """CREATE TABLE example_gloss (
    example_id INTEGER NOT NULL,
    lang       TEXT NOT NULL,
    text       TEXT NOT NULL,
    src        TEXT,
    PRIMARY KEY(example_id, lang)
)"""

DDL_COLLOCATION = """CREATE TABLE collocation (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id  INTEGER NOT NULL,
    sense_id INTEGER,
    text     TEXT NOT NULL,
    rank     INTEGER NOT NULL,
    UNIQUE(word_id, rank)
)"""

DDL_COLLOCATION_GLOSS = """CREATE TABLE collocation_gloss (
    collocation_id INTEGER NOT NULL,
    lang           TEXT NOT NULL,
    text           TEXT NOT NULL,
    src            TEXT,
    PRIMARY KEY(collocation_id, lang)
)"""

DDL_AUDIO = """CREATE TABLE audio (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    word       TEXT NOT NULL,
    file       TEXT NOT NULL,         -- Commons 文件名 = 录音身份（去重靠它，不是 URL）
    url_mp3    TEXT,
    url_ogg    TEXT,
    url_wav    TEXT,
    url_other  TEXT,
    ipa        TEXT,
    speaker    TEXT,
    region     TEXT,                  -- en-GB / en-US / …；判不出留空不猜
    region_src TEXT,                  -- tag | speaker | filename
    kind       TEXT NOT NULL,         -- human / tts-tool / browser-tts（方针④三级兜底）
    src        TEXT NOT NULL,
    UNIQUE(word, file)
)"""

DDL_FIELD_SRC = """CREATE TABLE field_src (
    word_id INTEGER NOT NULL,
    field   TEXT    NOT NULL,         -- dict 的列名
    src     TEXT    NOT NULL,         -- ecdict-vetted / ecdict-crowd / kk-2025 / en-llm / …
    PRIMARY KEY (word_id, field)
)"""

TABLES = [
    ("dict", DDL_DICT),
    ("sense", DDL_SENSE),
    ("sense_src", DDL_SENSE_SRC),
    ("sense_gloss", DDL_SENSE_GLOSS),
    ("sense_tag", DDL_SENSE_TAG),
    ("sense_relation", DDL_SENSE_RELATION),
    ("pronunciation", DDL_PRONUNCIATION),
    ("example", DDL_EXAMPLE),
    ("example_gloss", DDL_EXAMPLE_GLOSS),
    ("collocation", DDL_COLLOCATION),
    ("collocation_gloss", DDL_COLLOCATION_GLOSS),
    ("audio", DDL_AUDIO),
    ("field_src", DDL_FIELD_SRC),
]

# 🔴🔴 **索引名一律带 `dict_` 前缀，不能照抄 de 的 `idx_word`/`idx_norm`。**
#    实测（2026-09-07 第一次 --run 当场抛错、事务回滚）：
#    `ALTER TABLE stardict RENAME TO legacy_dict` **会把索引一起带过去**，
#    老库那三个（`idx_word` / `idx_stardict_word_nocase` / `idx_stardict_qual`）
#    现在挂在 `legacy_dict` 上，而 `idx_word` 正是 de 给 `dict` 用的名字 ⇒ 撞名。
#    de/pt/fr 都没撞过，因为**它们没有一张要改名的老表** —— 这是 en 独有的形状。
#    ⇒ 不去动冻结表的索引（它还要服务回核），改我自己的名字。
INDEXES = [
    "CREATE INDEX idx_dict_word ON dict(word COLLATE NOCASE)",
    # 🔴 BINARY 点查必须有自己的索引 —— NOCASE 列上做 BINARY 比较＝静默全表扫。
    #    本项目已撞过**四次**（`[[query-perf-collation-traps]]`），这次开工就建。
    "CREATE INDEX idx_dict_word_bin ON dict(word)",
    "CREATE INDEX idx_dict_norm ON dict(word_norm)",
    "CREATE INDEX idx_dict_freq ON dict(freq_rank)",
    "CREATE INDEX idx_sense_word ON sense(word_id)",
    "CREATE INDEX idx_sensesrc_word ON sense_src(word_id)",
    "CREATE INDEX idx_sensesrc_sense ON sense_src(sense_id)",
    "CREATE INDEX idx_glosslang ON sense_gloss(lang)",
    "CREATE INDEX idx_tag_kind ON sense_tag(kind, value)",
    "CREATE INDEX idx_rel_word ON sense_relation(word_id)",
    "CREATE INDEX idx_rel_sense ON sense_relation(sense_id)",
    "CREATE INDEX idx_pron_word ON pronunciation(word_id)",
    "CREATE INDEX idx_pron_entry ON pronunciation(entry_id)",
    "CREATE INDEX idx_pron_region ON pronunciation(region)",
    "CREATE INDEX idx_ex_word ON example(word)",
    "CREATE INDEX idx_ex_sense ON example(sense_id)",
    "CREATE INDEX idx_col_word ON collocation(word_id)",
    "CREATE INDEX idx_col_sense ON collocation(sense_id)",
    "CREATE INDEX idx_colg_lang ON collocation_gloss(lang)",
    "CREATE INDEX idx_audio_word ON audio(word)",
    "CREATE INDEX idx_fieldsrc_src ON field_src(src)",
]


# ══════════════════ 闸 ══════════════════

def gates(con, before_rows):
    """闸②：结构就位、老表逐字节还在。→ [(名字, 实际, 期望)]"""
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    idx = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")}
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("十三张新表全部建成", sum(t in have for t, _ in TABLES), len(TABLES)),
        ("索引全部建成", sum(i.split()[2] in idx for i in INDEXES), len(INDEXES)),
        ("老表已改名冻存", int(FROZEN in have), 1),
        ("老表名不再存在", int(LEGACY not in have), 1),
        ("冻存表行数逐条还在", q("SELECT COUNT(*) FROM %s" % FROZEN), before_rows),
        ("新表全部为空（数据归阶段 3a）",
         sum(q("SELECT COUNT(*) FROM %s" % t) for t, _ in TABLES), 0),
        # 🔴 判据不是"列数对不对"，是**这两根不该存在的器官确实没长出来**（文件头①②）
        ("dict 没有 ipa 列", int("ipa" not in _cols(con, "dict")), 1),
        ("dict 没有 translation 列", int("translation" not in _cols(con, "dict")), 1),
        ("dict 没有 definition 列", int("definition" not in _cols(con, "dict")), 1),
        ("pronunciation 有 region 列", int("region" in _cols(con, "pronunciation")), 1),
        ("pronunciation 有 pos 列", int("pos" in _cols(con, "pronunciation")), 1),
        ("pronunciation 有 entry_id 列", int("entry_id" in _cols(con, "pronunciation")), 1),
    ]
    return checks


def _cols(con, t):
    return {r[1] for r in con.execute("PRAGMA table_info(%s)" % t)}


def report(checks):
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-34s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


# ══════════════════ 主流程 ══════════════════

def main(run=False, verify=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    src = FROZEN if FROZEN in have else LEGACY
    before_rows = con.execute("SELECT COUNT(*) FROM %s" % src).fetchone()[0]
    con.close()

    if verify:
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        print("═══ 闸② 结构核对 ═══")
        bad = report(gates(con, before_rows))
        con.close()
        return 1 if bad else 0

    print("═══ 阶段 0 计划 ═══")
    print("   建表 %d 张：%s" % (len(TABLES), "、".join(t for t, _ in TABLES)))
    print("   建索引 %d 个" % len(INDEXES))
    print("   改名 %s → %s（%s 行，逐条不动）" % (LEGACY, FROZEN, format(before_rows, ",")))
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0

    # 🔴 `unfreeze` 只在这一步开，且只开 stardict —— 这是它唯一合法的一次用法。
    with dbtool.session("keep-v3-schema",
                        expect={"#%s" % LEGACY: -before_rows,
                                "#%s" % FROZEN: +before_rows},
                        unfreeze={LEGACY}) as s:
        s.execute("ALTER TABLE %s RENAME TO %s" % (LEGACY, FROZEN))
        for t, ddl in TABLES:
            s.execute(ddl)
        for i in INDEXES:
            s.execute(i)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② 结构核对 ═══")
    bad = report(gates(con, before_rows))
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv, verify="--verify" in _sys.argv))
