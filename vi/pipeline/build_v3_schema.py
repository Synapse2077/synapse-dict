#!/usr/bin/env python3
"""vi 阶段 0：建 v3 结构。2026-09-28。**幂等**，重跑不改已有数据。

照 `docs/SCHEMA.md`（`PLAYBOOK` 零：**结构在写第一行业务代码之前定死，别自己再设计一遍**）。
与 ko 一样是 **v3 原生**，没有 v2 迁移包袱；`dict` 的建表语句也在本文件 ——
ja 把它藏在 `build.py` 里，于是"这门语言的结构长什么样"散在两个文件。

═══ 🔴 每一条与八门不同的地方，都是量出来的，不是想出来的 ═══
`SCHEMA` §13.1 定的方法：**一等字段落在哪张表，用「一条记录内多值的比例」判。**
下面每条决定后面都跟着 2026-09-28 的实测数（`vi/probes/probe_sources.py` 与阶段 0 探测）。

  ① **`pronunciation.dialect` 是主键的一部分，不是可选列**
     源头**本来就是按方言组织的**：vi 版每个词给 **6 个方言点各一条**
     （Hà-Nội / Huế / Saigon / Vinh / Thanh-Chương / Hà-Tĩnh，各 34,773 条**完全等量**）。
     ⇒ 记录内 IPA 多值率 **vi 版 100%、en 版 96.5%**。
     不把 dialect 放进主键，六条读音会塌成一堆分不开的字符串 —— 正是 `SCHEMA` §1.3
     「音标正在丢变体」那条。
     ⚠️ 两家外审都说「至少存河内＋西贡两套」，**它们低估了：源头给了六个点。**

  ② **`pronunciation_entry` 不建**
     实测「同一词形的不同词条给了不同读音」只有 **7 个词形**。
     对照：es 14 ⇒ 不建／ko 429（0.75%）⇒ 不建／it 282,060 行 ⇒ 建。
     `UNIQUE` 里含 `entry_id`，这 7 个复制成两行就装下了。
     🔴 **什么会推翻**：若某层做完后「复制出来的读音行」超过 `pronunciation` 总行的 5%。

  ③ **汉字表记独立成表，不是 `entry` 上的一列**
     实测**同一词形对应 ≥2 个不同汉字的占 54.9%**（2,640 / 4,806；分布 2字 943、3字 632、
     4字 436、5字 275）。ko 那边是 1,944 个词形多值、放 `entry.hanja` 加一张
     `hanja_spelling` 兜多候选；vi 的多值是**主流不是例外** ⇒ 直接独立成表。

  ④ **汉越字与喃字拆两张表**（`VI_PLAN` V3）
     实测 13,018 对里：全通用区 **6,792（52.2%）** ／ 含扩展区 **6,226（47.8%）**，几乎对半。
     对中文读者认知价值天差地别：汉越字是正迁移，喃字是设备可能没字体的生僻字。
     🔴 判据用**码位**而不是源头标签 —— 源头的 `Hán-Nôm` 标签**整个只有 2 条**
     （`CJK` 标签 13,016 条且通用/扩展混在一起）。⚠️ 码位 ≠ 字源，见欠账 **W1**。

  ⑤ **`inflection` 整张表不建**（`VI_PLAN` V2）
     越南语是分析语。英文版 `forms` 33,020 行里**零屈折**，装的是
     CJK 13,361 ／ Hán-Nôm 9,799 ／ alternative 4,647 ／ classifier 4,344。
     🔴 **什么会推翻**：源头出现带屈折 tag（tense/number/case/person…）的 form。
     ⚠️ 不建 ⇒ 也**不许列进 `dbtool.TRACK_TABLES`**，否则它就是 B7 那种死条目。

  ⑥ **`noun_classifier` 量词关系表**（`VI_PLAN` V5）
     `classifier` 在源头躺在 `forms` 里，**但它根本不是词形**。实测 2,882 个名词有量词标注，
     **34.6% 配 2 个以上**（`cái bàn`／`chiếc bàn`）⇒ 单值列（像西语阴阳性那样）装不下。

  ⑦ **`dict.entry_type`**（`VI_PLAN` V1）
     `word` 含空格占 47.9%（en）／81.3%（vi），里面混着大量短语、成语、自由搭配 ——
     `word` 只是页面标题，不是词法判断过的"词"。不分开，量词搭配、汉字层、
     重叠词关系都会把"短语"和"词"混在一起。

═══ ⚠️ 两条归一化约定，写在建表这一步是因为它们决定了能不能对齐 ═══
· **IPA 存裸**：en 版 **100% 带方括号**（`[sïŋ˧˧]`），vi 版 **0%**。
  不剥括号，同一个读音在两版里是两个字符串。`[[ipa-bare-storage-convention]]`。
· **方言归属在 en 版分裂成两个字段**：`tags:["Hà-Nội"]` 与 **`note:"Saigon"`**。
  🔴🔴 只读 `tags` ⇒ **西贡音整个消失**（实测漏 38,996 行，其中 38,960 是 Saigon）。
  ⚠️ 这是 vi 上**第二次**「同一个概念在源头有两个字段名」（第一次是
     `etymology_text` / `etymology_texts`，漏了会丢 42.2% 的词源）。
     ⇒ **抽任何一个字段之前，先把该版的字段名全打出来看一眼。**

用法：
    python3 vi/pipeline/build_v3_schema.py            # 建表（幂等）
    python3 vi/pipeline/build_v3_schema.py --check    # 只核对，不写
"""
import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dbtool                                                   # noqa: E402
import paths                                                    # noqa: E402

# ══════════════════════════════════════════════════════════════════
# 🔴 表的顺序＝依赖顺序。`dict` 是身份单位（词形），`entry` 是同形异义的分界单位。
DDL = [
    # ── 骨架：词形 ────────────────────────────────────────────────
    ("dict", """
    CREATE TABLE IF NOT EXISTS dict (
      id          INTEGER PRIMARY KEY,
      word        TEXT NOT NULL,                 -- 含空格的完整词：`sinh viên` 是一条
      -- NFC + 小写，**在 Python 侧做**。⚠️ 不去声调：
      --   去掉声调会把 `má/mà/mả/mã/mạ` 合成一个词（拉丁六门去重音是对的，越南语不行）
      -- 🔴🔴 **这一列有意不带 `COLLATE NOCASE`**（2026-09-28 建库前拆掉，当时库是空的）。
      --   SQLite 的 NOCASE 只折 ASCII A–Z，对越南语是**部分生效**，而部分生效最难发现：
      --       'Việt' = 'việt' COLLATE NOCASE → 1   ← 只有首字母是 ASCII，看着像能用
      --       'VIỆT' = 'việt' COLLATE NOCASE → 0   ← 带变音符的大写一个都折不了
      --   `[[it-display-layer-stage8]]`：兜底越体面缺陷越难发现。
      --   既然 Python 侧已经 `NFC + lower()`（实测 'ĐƯỜNG'→'đường' 正确），
      --   NOCASE 只剩负作用：`[[query-perf-collation-traps]]` NOCASE 列上做 BINARY 比较
      --   ＝静默全表扫。⇒ 归一只在一个地方做，索引是真索引。
      word_norm   TEXT NOT NULL,
      -- V1：`word` 只是页面标题。81.3% 含空格里混着短语/成语/自由搭配。
      -- 值域：word / phrase / proverb / bound_morpheme / letter
      --   判据只用源头 pos 直接映射，**一律不猜**（`vi/pipeline/criteria.py` §⑥）
      --   `letter` ＝ 越南语字母（`A` `y` `CH` `đ`），且必须是**唯一**词性才算
      --              （324 个里 50 个同时是真词，`a` 还是代词/动词）
      -- 🔴 **`han_form` 有意不在值域里**：用户 2026-09-28 定，纯表意文字词头
      --   （实测 14,523 个词形）**不进 dict**，阶段 2 从 dump 直读去喂汉字层。
      --   留一个没人写的枚举值＝ B7 那种死条目。
      entry_type  TEXT NOT NULL DEFAULT 'word',
      is_lemma    INTEGER NOT NULL DEFAULT 1,    -- vi 无屈折 ⇒ 基本恒为 1，见 ⑤
      pos         TEXT,                          -- 短码。⚠️ ko 的 K31 教训：展示层读哪一列，
                                                 --   闸就查哪一列，别让长码/短码两套并存
      syllables   INTEGER,                       -- 音节数 ＝ 空格数+1。搜索要按长到短最长匹配
      freq_zipf   REAL,
      UNIQUE(word, entry_type)
    )"""),
    ("idx_dict_norm", "CREATE INDEX IF NOT EXISTS idx_dict_norm ON dict(word_norm)"),
    ("idx_dict_syl", "CREATE INDEX IF NOT EXISTS idx_dict_syl ON dict(syllables)"),

    # ── 词条层：同形异义的分界（SCHEMA §10.3）─────────────────────
    ("entry", """
    CREATE TABLE IF NOT EXISTS entry (
      id        INTEGER PRIMARY KEY,
      word_id   INTEGER NOT NULL REFERENCES dict(id),
      pos       TEXT,
      etym_no   TEXT NOT NULL DEFAULT '0',       -- 源头没编号记 '0'
      seq       INTEGER NOT NULL DEFAULT 0,      -- wiktextract 把一个维基章节切成多条时用
      -- 词源类型：sino_vietnamese / native / borrowed / mixed / unknown
      -- 🔴 **不能只放词级**：同一个拉丁词形可能同时有汉越词源和纯越词源
      etym_type TEXT,
      src       TEXT NOT NULL,                   -- en-edition / vi-edition / zh-edition-trad …
      src_ref   TEXT NOT NULL,                   -- kk-<版>:<词>:<词性>:<词源号>:<seq>
      UNIQUE(src_ref)
    )"""),
    ("idx_entry_word", "CREATE INDEX IF NOT EXISTS idx_entry_word ON entry(word_id)"),

    # ── 义项两层（SCHEMA §2.-1）───────────────────────────────────
    ("sense_src", """
    CREATE TABLE IF NOT EXISTS sense_src (
      id        INTEGER PRIMARY KEY,
      word_id   INTEGER NOT NULL REFERENCES dict(id),
      entry_id  INTEGER REFERENCES entry(id),
      sense_id  INTEGER REFERENCES sense(id),    -- NULL ＝ 证据层收了但不出版
      lang      TEXT NOT NULL,                   -- 这条证据是用哪种语言写的
      text      TEXT NOT NULL,
      src       TEXT NOT NULL,
      src_ref   TEXT NOT NULL,
      UNIQUE(src_ref)
    )"""),
    # 🔴🔴 **2026-10-03 阶段 9 的查询计划闸逮到的**：展示层的 W15 指针查询
    #    （`WHERE word_id = ? AND sense_id IS NULL`）在**每开一个词条页**都跑，
    #    而这张表上一个索引都没有（只有 `UNIQUE(src_ref)` 的自动索引）⇒
    #    `EXPLAIN QUERY PLAN` 报 **SCAN sense_src**，实测 **14.40 ms**，
    #    是同一页其余五条查询（0.07–1.15 ms）的 **100 倍**。
    #    ⚠️ 这条热路径是**阶段 9 才出现的** —— 建表的时候 `sense_src` 只是证据层、
    #      没人按 `word_id` 查它。`[[query-perf-collation-traps]]`：
    #      **性能要等数据长大、或等读取路径出现才咬人。**
    ("idx_sense_src_word", "CREATE INDEX IF NOT EXISTS idx_sense_src_word "
                           "ON sense_src(word_id)"),
    ("sense", """
    CREATE TABLE IF NOT EXISTS sense (
      id        INTEGER PRIMARY KEY,
      word_id   INTEGER NOT NULL REFERENCES dict(id),
      entry_id  INTEGER REFERENCES entry(id),
      rank      INTEGER NOT NULL DEFAULT 0,
      -- 🔴 ko 的教训：`hidden` 背到第四种意思才拆。vi 从第一天就分开
      hidden    INTEGER NOT NULL DEFAULT 0,
      hidden_why TEXT
    )"""),
    ("idx_sense_word", "CREATE INDEX IF NOT EXISTS idx_sense_word ON sense(word_id)"),
    ("sense_gloss", """
    CREATE TABLE IF NOT EXISTS sense_gloss (
      id       INTEGER PRIMARY KEY,
      sense_id INTEGER NOT NULL REFERENCES sense(id),
      lang     TEXT NOT NULL,                    -- 三语：zh / vi / en（`[[gloss-three-languages]]`）
      text     TEXT NOT NULL,
      src      TEXT NOT NULL,
      UNIQUE(sense_id, lang, text)
    )"""),
    ("sense_tag", """
    CREATE TABLE IF NOT EXISTS sense_tag (
      id       INTEGER PRIMARY KEY,
      sense_id INTEGER NOT NULL REFERENCES sense(id),
      bucket   TEXT NOT NULL,                    -- topic / register / region / grammar / usage
      value    TEXT NOT NULL,
      src      TEXT NOT NULL,
      UNIQUE(sense_id, bucket, value)
    )"""),

    # ── 读音：**dialect 进主键**，见 ① ───────────────────────────
    ("pronunciation", """
    CREATE TABLE IF NOT EXISTS pronunciation (
      id       INTEGER PRIMARY KEY,
      word_id  INTEGER NOT NULL REFERENCES dict(id),
      ipa      TEXT NOT NULL,                    -- **存裸**，不带 [] 或 //
      -- 六个方言点：Hà-Nội / Huế / Saigon / Vinh / Thanh-Chương / Hà-Tĩnh
      -- 🔴 源头没标就写 'unknown'，**不许假装是标准音**（VI_PLAN V4）
      dialect  TEXT NOT NULL DEFAULT 'unknown',
      src      TEXT NOT NULL,
      src_ref  TEXT NOT NULL,
      -- 🔴 dialect 在 UNIQUE 里：没有它，六条方言读音会互相覆盖
      UNIQUE(word_id, ipa, dialect, src)
    )"""),
    ("idx_pron_word", "CREATE INDEX IF NOT EXISTS idx_pron_word ON pronunciation(word_id)"),

    # ── 汉字层：两张表，见 ③④ ────────────────────────────────────
    ("han_spelling", """
    CREATE TABLE IF NOT EXISTS han_spelling (
      id       INTEGER PRIMARY KEY,
      word_id  INTEGER NOT NULL REFERENCES dict(id),
      entry_id INTEGER REFERENCES entry(id),     -- 能定到哪个词条就定，定不了留 NULL，**不猜**
      han      TEXT NOT NULL,                    -- 汉越字（中文读者认得的那半套）
      -- 🔴🔴 **2026-09-28 补**：这一列原本只给 `nom_spelling`，是配反了。
      --   实测拿源头自己的 `chữ Hán/Nôm form of` 标注当真值验码位判据：
      --       扩展区 ⇒ 喃字   99.4% 对（1,386 对里错 8）
      --       通用区 ⇒ 汉越字 **只有 70.8% 对**（9,148 对里 2,671 其实是喃字）
      --   ⇒ **污染全在 han 这一侧**（借用通用汉字表喃音，W1 预言的那种），
      --     所以更需要 rule_ver 的是 han 不是 nom。
      --   值域见 `vi/pipeline/han_sources.py` 的 RULES，一条一条写明可信度。
      rule_ver TEXT NOT NULL DEFAULT 'unknown',
      src      TEXT NOT NULL,
      src_ref  TEXT NOT NULL,
      UNIQUE(word_id, han, src)
    )"""),
    ("nom_spelling", """
    CREATE TABLE IF NOT EXISTS nom_spelling (
      id       INTEGER PRIMARY KEY,
      word_id  INTEGER NOT NULL REFERENCES dict(id),
      entry_id INTEGER REFERENCES entry(id),
      nom      TEXT NOT NULL,                    -- 喃字（扩展区为主，中文读者多半不认识）
      -- 🔴 判据是**码位**不是字源，已知会把"借用通用汉字的喃字"判进 han_spelling。
      --    这一列记的是判据版本，翻案时能找到是哪一批（欠账 W1）
      rule_ver TEXT NOT NULL DEFAULT 'codepoint-v1',
      src      TEXT NOT NULL,
      src_ref  TEXT NOT NULL,
      UNIQUE(word_id, nom, src)
    )"""),
    ("idx_han_word", "CREATE INDEX IF NOT EXISTS idx_han_word ON han_spelling(word_id)"),
    ("idx_nom_word", "CREATE INDEX IF NOT EXISTS idx_nom_word ON nom_spelling(word_id)"),

    # ── 量词：关系表，见 ⑥ ───────────────────────────────────────
    ("noun_classifier", """
    CREATE TABLE IF NOT EXISTS noun_classifier (
      id            INTEGER PRIMARY KEY,
      word_id       INTEGER NOT NULL REFERENCES dict(id),   -- 名词
      classifier    TEXT NOT NULL,                          -- 量词的词形（`cái`/`con`/`chiếc`）
      classifier_id INTEGER REFERENCES dict(id),            -- 量词自己的词条；收不到留 NULL
      note          TEXT,                                   -- 敬称/贬义/口语/书面 等语用差别
      src           TEXT NOT NULL,
      src_ref       TEXT NOT NULL,
      UNIQUE(word_id, classifier, src)
    )"""),

    # ── 关系 / 词源 / 例句 ───────────────────────────────────────
    ("sense_relation", """
    CREATE TABLE IF NOT EXISTS sense_relation (
      id        INTEGER PRIMARY KEY,
      word_id   INTEGER NOT NULL REFERENCES dict(id),
      sense_id  INTEGER REFERENCES sense(id),    -- NULL ＝ 词条级关系
      kind      TEXT NOT NULL,                   -- synonym / antonym / derived / related …
      target    TEXT NOT NULL,
      target_id INTEGER REFERENCES dict(id),
      -- 🔴 B17：兜底 `related` 撞上更具体的 kind 时读者会在两个标题下看见同一个词。
      --    ko 的做法是 hidden=1 + hidden_why（**不删**），vi 从第一天就留好位置
      hidden    INTEGER NOT NULL DEFAULT 0,
      hidden_why TEXT,
      src       TEXT NOT NULL,
      src_ref   TEXT NOT NULL,
      UNIQUE(src_ref)
    )"""),
    ("idx_rel_word", "CREATE INDEX IF NOT EXISTS idx_rel_word ON sense_relation(word_id)"),
    ("etymology", """
    CREATE TABLE IF NOT EXISTS etymology (
      id       INTEGER PRIMARY KEY,
      word_id  INTEGER NOT NULL REFERENCES dict(id),
      entry_id INTEGER REFERENCES entry(id),
      etym_no  TEXT NOT NULL DEFAULT '0',
      text     TEXT NOT NULL,
      -- 🔴 三版字段名不同：en 版 `etymology_text`（单数），vi/zh 版 `etymology_texts`（复数）。
      --    只认单数会丢 42.2%。这一列记的是从哪个字段抽来的，出问题能定位
      src_field TEXT NOT NULL,
      src      TEXT NOT NULL,
      src_ref  TEXT NOT NULL,
      UNIQUE(src_ref)
    )"""),
    # 🔴 **2026-10-03 查询计划闸逮到的第二个**：展示层按 `word_id` 查词源
    #    （每开一个词条页一次），而这张表 36,089 行上一个索引都没有 ⇒ `SCAN etymology`。
    #    与 `idx_sense_src_word` 同一天、同一个成因：**建表时没人按 word_id 查它**。
    ("idx_etym_word", "CREATE INDEX IF NOT EXISTS idx_etym_word ON etymology(word_id)"),
    ("etymology_gloss", """
    CREATE TABLE IF NOT EXISTS etymology_gloss (
      id           INTEGER PRIMARY KEY,
      etymology_id INTEGER NOT NULL REFERENCES etymology(id),
      lang         TEXT NOT NULL,
      text         TEXT NOT NULL,
      src          TEXT NOT NULL,
      UNIQUE(etymology_id, lang)
    )"""),
    ("example", """
    CREATE TABLE IF NOT EXISTS example (
      id       INTEGER PRIMARY KEY,
      word_id  INTEGER NOT NULL REFERENCES dict(id),
      sense_id INTEGER REFERENCES sense(id),
      text     TEXT NOT NULL,
      -- 文献出处（`1820, Nguyễn Du, Đoạn trường tân thanh` / `(tục ngữ)` 谚语）。
      -- 🔴 阶段 6 补的列。源头有两个字段装它：`ref`（en/vi 版，规整的书目）
      --    与 **`translation`（vi 版，而那个字段名是骗人的）** ——
      --    vi 版 709 条 `translation` 里**一条真译文都没有**：199 条整串是 `.`，
      --    193 条是 `(tục ngữ)`/`(ca dao)`/作者名。照字段名收 ⇒ 读者看见
      --    「译文：.」。`[[criteria-from-meaning-not-form]]`：字段名不是内容判据。
      ref      TEXT,
      hidden   INTEGER NOT NULL DEFAULT 0,
      hidden_why TEXT,
      src      TEXT NOT NULL,
      src_ref  TEXT NOT NULL,
      UNIQUE(src_ref)
    )"""),
    ("idx_example_word", "CREATE INDEX IF NOT EXISTS idx_example_word ON example(word_id)"),
    ("idx_example_sense", "CREATE INDEX IF NOT EXISTS idx_example_sense ON example(sense_id)"),
    ("example_gloss", """
    CREATE TABLE IF NOT EXISTS example_gloss (
      id         INTEGER PRIMARY KEY,
      example_id INTEGER NOT NULL REFERENCES example(id),
      lang       TEXT NOT NULL,
      text       TEXT NOT NULL,
      src        TEXT NOT NULL,
      UNIQUE(example_id, lang)
    )"""),
    ("audio", """
    CREATE TABLE IF NOT EXISTS audio (
      id       INTEGER PRIMARY KEY,
      word_id  INTEGER NOT NULL REFERENCES dict(id),
      url      TEXT NOT NULL,
      -- B12：同一条录音被存成两行。`commons_key` 是 MediaWiki 标题归一后的键，
      --      从第一天就存，别等八门都中招了再回头补
      commons_key TEXT,
      dialect  TEXT,
      -- 🔴 **`UNIQUE(word_id, url)` 挡不住 B12**（阶段 6 实测）：各维基版内嵌的是
      --    转码后的 mp3 名、Commons 原始名是 .wav/.oga ⇒ 同一个文件有多个 url。
      --    按 url 去重只能并到 4,560，按 `commons_key` 并才到 3,110 ——
      --    **1,450 行重复会落进库**。⇒ 入库前必须自己按 `commons_key` 并。
      --    唯一键留着不动（它拦的是同一个 url 插两次），但它**不是** B12 的判据。
      hidden   INTEGER NOT NULL DEFAULT 0,
      hidden_why TEXT,
      src      TEXT NOT NULL,
      UNIQUE(word_id, url)
    )"""),
    ("field_src", """
    CREATE TABLE IF NOT EXISTS field_src (
      id       INTEGER PRIMARY KEY,
      tbl      TEXT NOT NULL,
      row_id   INTEGER NOT NULL,
      col      TEXT NOT NULL,
      src      TEXT NOT NULL,                    -- 表里有行 ＝ 这个值没有源头背书（de §12）
      UNIQUE(tbl, row_id, col)
    )"""),
]

# 🔴 **有意不建**，每条都写了推翻条件（`PLAYBOOK` 7.5）。
#    ⚠️ 不建 ⇒ 也不许列进 `dbtool.TRACK_TABLES`，否则就是 B7 那种死条目。
NOT_BUILT = {
    "inflection": "越南语是分析语，源头 forms 里**零屈折**（33,020 行全是汉字表记/异体/量词）。"
                  "推翻：源头出现带屈折 tag（tense/number/case/person）的 form",
    "pronunciation_entry": "实测「同一词形的不同词条给了不同读音」只有 **7 个词形**"
                           "（es 14 不建／ko 429 不建／it 282,060 建）。"
                           "推翻：复制出来的读音行超过 pronunciation 总行的 5%",
    "collocation": "搭配层五门 99.3% 是模型凭记忆写的、无外部出处。"
                   "vi 不从这条路起步。推翻：找到有外部出处的搭配源",
}


# ══════════════════════════════════════════════════════════════════
# 🔴 **后补的列**。`CREATE TABLE IF NOT EXISTS` 对已存在的表是空操作 ——
#    改了上面的建表语句，**老库上一个字都不会变**，而 `--check` 只数对象名
#    于是照样报全绿。那正是 B7 的形状（只审计表、不审计列），`dbtool._track_audit`
#    已经为此修过一次，建表这一侧当时没修。
# ⇒ 这张表列「表.列 → 类型」，建表时逐条补、`--check` 时逐条查。
ADD_COLUMNS = [
    # 阶段 6 补：例句的文献出处。见 `example` 的建表注释
    ("example", "ref", "TEXT"),
    # 阶段 6 补：录音也要能「留着但不出版」。
    # 🔴 建表时 `audio` 是唯一没有 `hidden`/`hidden_why` 的内容表 —— 当时还没有录音层，
    #    没想到会有「这条录音读的是别的词」这种事（实测 7 行，判据精确度只有 57%
    #    ⇒ **不能删**，而没有 hidden 列就只剩「删」或「印错的音」两条路，两条都不行）。
    #    `[[prefer-reversible-designs]]`：不可逆往往是方案设计窄造成的。
    ("audio", "hidden", "INTEGER NOT NULL DEFAULT 0"),
    ("audio", "hidden_why", "TEXT"),
]


def build(con, check=False):
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
    made = []
    for name, sql in DDL:
        if name in have:
            continue
        if not check:
            con.execute(sql)
        made.append(name)
    # 后补的列：表必须已经在（不在的话上面刚建出来，新建的就带着这些列）
    for tbl, col, typ in ADD_COLUMNS:
        if tbl in made:
            continue                       # 刚新建，建表语句里已经有了
        if tbl not in have:
            made.append("%s（表不在，列 %s 也就无从补）" % (tbl, col))
            continue
        cols = {r[1] for r in con.execute("PRAGMA table_info(%s)" % tbl)}
        if col in cols:
            continue
        if not check:
            con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tbl, col, typ))
        made.append("%s.%s" % (tbl, col))
    return made, have


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只核对，不写")
    a = ap.parse_args()

    if a.check:
        if not dbtool.db_exists():
            print("库还不存在（%s）—— 先不带 --check 跑一次" % paths.DB.name)
            raise SystemExit(1)
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        made, have = build(con, check=True)
        print("■ 结构核对：应有 %d 个对象 ＋ %d 个后补的列，缺 %d 项"
              % (len(DDL), len(ADD_COLUMNS), len(made)))
        for n in made:
            print("   🔴 缺 %s" % n)
        # 🔴 反向：**有意不建的东西，不许偷偷出现**。
        #    它出现了要么是有人加的（那得改 NOT_BUILT 的说法），要么是从别门拷脚本带进来的
        sneaked = [t for t in NOT_BUILT if t in have]
        for t in sneaked:
            print("   🔴🔴 `%s` **有意不建，而它在库里** —— 要么改这条决定，要么查谁建的\n"
                  "        原决定：%s" % (t, NOT_BUILT[t]))
        raise SystemExit(1 if (made or sneaked) else 0)

    # 🔴 `PLAYBOOK` 1.4：写库一律走闸门。建表是 DDL，不插行 ⇒ expect 全 0。
    with dbtool.session("build-v3-schema", expect={}, invalidates=[]) as s:
        made, _ = build(s.conn)
        print("■ 建了 %d 个对象：%s" % (len(made), "、".join(made) or "（都已存在）"))
    print("\n■ 有意不建（%d 项，每条都有推翻条件）：" % len(NOT_BUILT))
    for t, why in NOT_BUILT.items():
        print("   ⚪ %-22s %s" % (t, why))


if __name__ == "__main__":
    main()
