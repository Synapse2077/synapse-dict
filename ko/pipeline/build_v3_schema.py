#!/usr/bin/env python3
"""阶段 0：建 ko 的 v3 十六张表。2026-09-20。

═══ 🔴 与 ja 的分工不同：**`dict` 的 DDL 也在本文件里** ═══
ja 把 `dict` 的建表语句藏在 `build.py`（阶段 1）里，于是「这门语言的结构长什么样」
散在两个文件。ko 没有 v2 迁移包袱 ⇒ **全部 DDL 集中在这儿，阶段 1 的 `build.py`
只负责灌数据**。本步不插一行。

═══ 韩语相对前七门改了六处，**每一处都有实测依据**（2026-09-20 五源全量扫）═══

① `entry` 加**四套罗马字**（`roman_rr` / `roman_rr_translit` / `roman_mr` / `roman_yale`）
   放 entry 而不是 pronunciation，判据是**实测的多值性**：
       同一条记录内，同一套罗马字有 ≥2 个值的：MR 5 条 / Yale 55 条（占 0.08%）
       同一条记录内，IPA 有 ≥2 个值的：          15,928 条（占 22.6%）
   ⇒ **罗马字是词条层面的转写（一条一套），IPA 是读音层面的（一条可多个）**。
   四套成套出现（各 84,489 条，完全等量），要么四套全有要么全无。
   🔴 列名**有意起成能被源码扫描认出来的样子**：`KO_PLAN` §四.2 定了「四套全存、
      页面只显示 RR」，而「只显示 RR」这个决定要靠**回归闸扫展示层源码**站岗
      （照搬 ja 给 `core_level` 做的 X3）。叫 `roman1/2/3` 就扫不出来了。

② `entry.hanja` 汉字表记 —— **单值列，覆盖 99.4%**
   实测：有汉字表记的 18,564 条记录里，一条记录内只有 1 个 hanja 的 18,453 条（99.4%），
   2 个 89 条、3 个 11 条。那 100 条多值的是**异体字/数字写法**
   （`기적` = 奇跡/奇蹟/奇迹、`시월` = 10月/十月）⇒ 它们的家在关系层，不是这一列。
   🔴 **但 `hanja` 绝不能放 `dict`**：1,944 个**词形**对应 ≥2 个不同汉字
   （`양` → 壤/兩/良/陽/孃/洋/量/羊 八个），它们分属不同 entry。
   放 `dict` 上等于对这 1,944 个词说谎 —— 与 ja 的 `kana` 同构的理由，而数字更硬。

③ `pronunciation` 加 `hangeul_phonetic`（**发音形谚文**）
   `읽다` 的实际读法是 `익따`（连音·同化·紧音化之后）。102,389 条，
   与 IPA 大多一一对应（(1,1) 43,701 ／ (2,2) 21,686 ／ (4,4) 2,755）。
   **拉丁七门和 ja 都没有这一层** —— 别到别人的 schema 里找它的位置。
   ⭐ 它还是 §四.1-c 那件事的**真值标尺**：中文版收进来的 15.7 万词要靠
      谚文→IPA 规则生成补读音，而这 10 万条就是现成的对照组。

④ 🔴 **不建 `pitch_mark` / `pitch_pos`**（ja 有，ko 没有）
   量的是什么：韩语标准语（首尔话）的音高重音。
   量出来多少：韩文版 IPA 的 tags 值域**只有 `SK-Standard` 和 `Seoul` 两个值、
   且成对出现 104,259 次**，没有任何声调标记字段。
   什么会推翻它：若要收庆尚道/咸镜道方言（那些方言**有**音高重音），或找到标注了
   音高的源 —— 那时再加这两列，`ALTER TABLE` 是纯加法。
   （`[[es-v3-structure-backfill]]`：照搬别的语言结构前，先量这门语言有没有那个病。）

⑤ 🔴 **不建 `entry.vclass`**（活用类：ㅂ불규칙 / ㄷ불규칙 / 르불규칙…）
   量的是什么：源头给不给「这个用言属于哪一类活用」。
   量出来多少：**英文版 0 条**（5,351 个用言条目，一条标记都没有）；
   韩文版只在 `categories` 里给了 **452 条 / 17 种**，覆盖它自己 10,632 个用言的 4.3%
   —— 而韩语实际的不规则用言远多于 4.3%，**源头本身就不全**。
   ⚠️ 上一轮我差点用**行级预筛**（`if 'irregular' not in line`）得出这个结论，
      那是 `PITFALLS` B 组明令禁止的；本节的数是**全量重扫**出来的。
   为什么不要紧：vclass 是「怎么生成变形」的元信息，而我们**直接有变形本身**
   （英文版 359,583 个变形词形）。需要的东西已经在手上了。
   什么会推翻它：要做「输入原形自动生成活用表」这类功能时（我们现在不做），
   或找到覆盖率足够的活用类源。

⑥ `etymology` **从第一天就建**
   ja 是做完九个阶段、打完完结标记之后才发现这张表整个不存在的
   （英文版 46,196 个条目带 `etymology_text`，一条没抽，而阶段表全 ✅）。
   根因是**阶段表对没列进去的层结构性失明**。
   ⇒ ko 的词源只有英文版有（38,796 条 / 60.8%），表现在就建出来，
     `dbtool.TRACK_TABLES` 立刻开始守它的行数。

跑（在仓库根）：
    python3 -u ko/pipeline/build_v3_schema.py
    python3 -u ko/pipeline/build_v3_schema.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sqlite3

import dbtool
import paths

DDL = [
    # ── 词形层。**搜索与身份单位**，一个词形一行 ────────────────────────
    """CREATE TABLE dict (
         id          INTEGER PRIMARY KEY AUTOINCREMENT,
         word        TEXT NOT NULL,       -- 书写形，**原样不折叠**（谚文/汉字/混排）
         word_norm   TEXT NOT NULL,       -- 检索归一。只用于匹配不用于身份
                                          -- 🔴 韩语的归一 = **NFC**。实测两版词头
                                          --   **100% 已经是 NFC**（英文版 63,773 / 韩文版
                                          --   108,909，分解形 0 条）⇒ 入库侧零转换。
                                          -- ⚠️ **但检索侧必须归一**：macOS/iOS 的输入法与
                                          --   剪贴板会产出 NFD 谚文（`가` 拆成 ᄀ+ᅡ），
                                          --   长得一模一样、字节不同、`=` 匹配不上。
                                          --   「源头干净」不等于「不需要归一」——
                                          --   这两件事分开（`[[dont-say-source-lacks-what-we-skipped]]`）
         is_lemma    INTEGER NOT NULL,    -- 有没有至少一条非指针义项
         pos         TEXT,                -- 聚合词性（逐义项词性在 sense.pos）
         -- ── 🔴 这里**有意不放**汉字表记 ──
         --    1,944 个词形对应 ≥2 个不同汉字（`양` → 壤/兩/良/陽/孃/洋/量/羊），
         --    它们分属不同 entry。放这儿等于对这 1,944 个词说谎。见 `entry.hanja`。
         -- ── 🔴 这里也**有意不放**读音 ──
         --    同 ja：一个词形可以有多个词条各读各的音。读音在 `pronunciation`。
         level       TEXT,                -- CEFR / TOPIK；🔴 TOPIK 的授权**尚未查**
                                          --   （`KO_PLAN` §四.4），查清前一律 NULL
         freq_zipf   REAL                 -- 阶段 5 填；量不出来的留 NULL **不填 0**
       )""",
    # ── 词条层 = (词形, 词性, 词源号)。韩语一等字段住这儿 ──────────────
    """CREATE TABLE entry (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,       -- → dict.id
         word_src TEXT NOT NULL,          -- dump 里的真实拼写
         pos      TEXT NOT NULL,          -- POS_MAP 映射后的展示值
         pos_raw  TEXT NOT NULL,          -- dump 原始词性，主键用它
         etym_no  TEXT NOT NULL,          -- 词源号；没编号记 "0"
         seq      INTEGER NOT NULL,       -- 同键内序号，正常 0
         -- ── 韩语一等字段 ──
         hanja     TEXT,                  -- 汉字表记（`사기` 的 詐欺 / 士氣 / 沙器…）
                                          -- 单值列覆盖 99.4%（18,453/18,564 条记录）。
                                          -- 🔴 剩 100 条一条里有 2–3 个的是**异体字/数字写法**
                                          --   （奇跡/奇蹟/奇迹、10月/十月）⇒ 归关系层
                                          --   `sense_relation.kind='alt_hanja'`，不挤进这一列
         hanja_src TEXT,                  -- 会变的字段才加 *_src（`[[ipa-provenance-columns]]`）
         -- 四套罗马字。**成套出现**（各 84,489 条，完全等量），记录内 99.92% 单值
         --   ⇒ 它是词条属性，不是读音属性（对照：IPA 有 22.6% 的记录是多值的）
         -- 🔴 列名必须**可被源码扫描认出**：`KO_PLAN` §四.2 定了「页面只显示 RR」，
         --    那个决定靠回归闸扫展示层源码站岗（照搬 ja 的 X3）。别改成 roman1/2/3。
         roman_rr          TEXT,          -- Revised Romanization，韩国 2000 年起的官方国标
         roman_rr_translit TEXT,          -- RR 的**转写**变体（逐字母，不是逐音）
         roman_mr          TEXT,          -- McCune-Reischauer（英语学术文献与旧地名）
         roman_yale        TEXT,          -- Yale（语言学界）
         roman_src         TEXT,
         -- 🔴 **有意不建 `vclass`**（活用类）：英文版 0 条、韩文版只给 452 条＝它自己
         --    用言的 4.3%，而我们**直接有 359,583 个变形词形**。见文件头 ⑤
         src      TEXT NOT NULL,
         src_ref  TEXT NOT NULL,          -- kk-ko:<word_src>:<pos_raw>:<etym_no>:<seq>
         UNIQUE(src_ref)
       )""",
    # ── 义项两层：证据层 / 出版层（`SCHEMA` §2.-1）────────────────────────
    """CREATE TABLE sense_src (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,       -- → dict.id
         sense_id INTEGER,                -- 编入哪条出版义项；NULL = 尚未裁决
                                          -- 🔴 ja 拖到阶段 1e 才回填这一列（此前两版全 NULL）。
                                          --   ko 从建库那一步起就要写，`dbtool.TRACK` 列着它
         src      TEXT NOT NULL,          -- en-edition / ko-edition / zh-edition-simp
                                          --   / zh-edition-trad / ja-edition / hanja-edition
                                          -- 🔴 中文版是**两片**，两个名字都要有
         src_ref  TEXT NOT NULL,
         lang     TEXT NOT NULL,          -- 这句原文是什么语言
         text     TEXT NOT NULL,
         raw_tags TEXT,
         UNIQUE(src_ref)
       )""",
    """CREATE TABLE sense (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,       -- → dict.id
         entry_id INTEGER,                -- → entry.id
         rank     INTEGER NOT NULL,       -- 🔴 从 1 起。`rank=0` 当哨兵咬过一次
                                          --   （`[[zh-gloss-reverse-search-plan]]`）
         pos      TEXT,
         hidden   INTEGER NOT NULL DEFAULT 0,
         UNIQUE(word_id, rank)
       )""",
    """CREATE TABLE sense_gloss (
         sense_id INTEGER NOT NULL,
         lang     TEXT NOT NULL,          -- ko / en / zh（`[[gloss-three-languages]]` 只留三语）
                                          -- 🔴 日文版那 29,671 条**日语**释义不进这儿，
                                          --   它只用来给 IPA 交叉背书
         kind     TEXT NOT NULL,          -- equivalent / definition
         seq      INTEGER NOT NULL,
         text     TEXT NOT NULL,
         src      TEXT,
         PRIMARY KEY(sense_id, lang, kind, seq)
       )""",
    """CREATE TABLE sense_tag (
         sense_id INTEGER NOT NULL,
         kind     TEXT NOT NULL,          -- topic / region / register / usage / grammar
         value    TEXT NOT NULL,          -- 🔴 值用**源头原词**，不改写
         PRIMARY KEY(sense_id, kind, value)
       )""",
    """CREATE TABLE sense_relation (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,
         sense_id INTEGER,
         kind     TEXT NOT NULL,          -- synonym / antonym / derived / …
                                          --   / alt_hanja  ← 一条 entry 有多个汉字表记时，
                                          --     主表记进 `entry.hanja`，其余异体进这儿
                                          --     （奇跡 / 奇蹟 / 奇迹）
         target   TEXT NOT NULL,
         tags     TEXT,
         hidden   INTEGER NOT NULL DEFAULT 0,
         src      TEXT NOT NULL,
         src_ref  TEXT NOT NULL,
         UNIQUE(word_id, sense_id, kind, target)
       )""",
    # ── 变形层（阶段 2 填）。🔴 韩语的活用表在**英文版** ────────────────
    """CREATE TABLE inflection (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,
         entry_id INTEGER,                -- 🔴 语义＝**原形的那个 entry**（it 阶段 8 定死）：
                                          --   「这个变形形属于原形的哪一个词条」。定不了留 NULL，**不猜**
         kind     TEXT NOT NULL,          -- inflection 活用 / derivation 构词
         base     TEXT NOT NULL,
         base_id  INTEGER,
         label_zh TEXT NOT NULL,
         desc_en  TEXT,
         tags     TEXT,                   -- 敬语阶 × 时制 × 语气：formal 213,689 /
                                          --   informal 209,529 / polite 156,902 /
                                          --   past 107,444 / non-past 86,848 …
         src      TEXT NOT NULL,          -- 🔴 **英文版**给 359,583 个变形词形（99.6% 的条目带
                                          --   forms），韩文版只有 30,982 —— **与 ja 正好相反**，
                                          --   照 ja 的结论走这一层会缩水 91%
         src_ref  TEXT NOT NULL
       )""",
    # ── 读音层（阶段 3 填）──────────────────────────────────────────────
    """CREATE TABLE pronunciation (
         id         INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id    INTEGER NOT NULL,
         entry_id   INTEGER,              -- → entry.id；NULL = 该词形各词条共用
                                          -- 🔴 查询写 `entry_id = ? OR entry_id IS NULL`，
                                          --   **不是**「取不到再回落」（it 的 A57）
         ipa        TEXT NOT NULL,        -- 裸存，不带定界符（八语种统一约定）
         notation   TEXT NOT NULL,        -- phonemic | narrow
                                          -- 🔴 韩语 98.6% 是 narrow（`[ka̠]`）：实测
                                          --   narrow 104,311 / bare 1,514 / phonemic 8。
                                          --   展示层**必须读这一列**决定加 [ ] 还是 / /
         hangeul_phonetic TEXT,           -- ⭐ **发音形谚文** —— 韩语独有，别门都没有。
                                          --   `읽다` 实际读作 `익따`（连音·同化·紧音化之后）。
                                          --   102,389 条，与 IPA 大多一一对应
         region     TEXT,                 -- ⚠️ 源头值域**只有 SK-Standard / Seoul 两个值，
                                          --   且成对出现 104,259 次** ⇒ 我们拿到的是**韩国
                                          --   标准语**，没有朝鲜（北）标准音。这不是缺陷，
                                          --   是要写清楚的边界
         tags       TEXT,
         pos        TEXT,
         is_primary INTEGER NOT NULL DEFAULT 0,
         src        TEXT NOT NULL,
         src_ref    TEXT NOT NULL,
         -- 🔴 **有意不建 pitch_mark / pitch_pos**（ja 有）：韩语标准语没有音高重音，
         --    韩文版 IPA 的 tags 值域里一个声调标记都没有。见文件头 ④
         UNIQUE(word_id, entry_id, ipa, notation)
       )""",
    # ── 词源层（阶段 7 填）。🔴 **从第一天就建**，见文件头 ⑥ ──────────
    """CREATE TABLE etymology (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,
         entry_id INTEGER,
         edition  TEXT NOT NULL,          -- 🔴 ja 在这儿栽过：服务层只取裸词源号而
                                          --   这一列写 `en-edition` ⇒ 40,270 行一条到不了
                                          --   页面且一声不吭，入库闸/写后回核/tsc 全绿
         etym_no  TEXT NOT NULL,
         text     TEXT NOT NULL,
         src      TEXT NOT NULL,          -- 🔴 **只有英文版有**：38,796 条（60.8%）。
                                          --   另外四份源**全是 0 条** —— 不是少，是没有
         src_ref  TEXT NOT NULL,
         UNIQUE(src_ref)
       )""",
    # ── 例句（阶段 6 填）────────────────────────────────────────────────
    """CREATE TABLE example (
         id              INTEGER PRIMARY KEY AUTOINCREMENT,
         word            TEXT NOT NULL,
         sense_id        INTEGER,
         text            TEXT NOT NULL,   -- 韩语原句
         bold            TEXT,
         ref             TEXT,
         src_gloss       TEXT,            -- 源里这条挂在哪条义项下（挂回义项的桥）
         src_translation TEXT,
         src_lang        TEXT,
         roman           TEXT,            -- 例句的罗马字转写（源头给才存，不自己算）
         hidden          INTEGER NOT NULL DEFAULT 0,
         src             TEXT NOT NULL,
                                          -- 🔴 中文版的 `examples` 里混着**关系数据**：
                                          --   `近义词：추` / `派生詞：늦가을，올가을…` /
                                          --   `季节：봄 - 여름 - 가을 - 겨울`。
                                          --   抽取时必须先过滤，它们是关系层的料
                                          --   （`KO_PLAN` §二判据 2）
         UNIQUE(word, text)
       )""",
    """CREATE TABLE example_gloss (
         example_id INTEGER NOT NULL,
         lang       TEXT NOT NULL,
         text       TEXT NOT NULL,
         src        TEXT,
         PRIMARY KEY(example_id, lang)
       )""",
    """CREATE TABLE collocation (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,
         sense_id INTEGER,
         text     TEXT NOT NULL,
         rank     INTEGER NOT NULL,
         src      TEXT,                   -- ⚠️ 五门的搭配层 99.3% 是模型凭记忆写的、无外部出处
                                          --   （`[[collocation-layer-is-llm-generated]]`）。
                                          --   ko 建空表，**要做先解决出处问题**
         UNIQUE(word_id, rank)
       )""",
    """CREATE TABLE collocation_gloss (
         collocation_id INTEGER NOT NULL,
         lang           TEXT NOT NULL,
         text           TEXT NOT NULL,
         src            TEXT,
         PRIMARY KEY(collocation_id, lang)
       )""",
    """CREATE TABLE field_src (
         word_id INTEGER NOT NULL,
         field   TEXT    NOT NULL,
         src     TEXT    NOT NULL,        -- 'unsourced' = 无源头背书
         PRIMARY KEY (word_id, field)
       )""",
    # ── 汉字音层（2026-09-20 阶段 1 途中补建，见下）─────────────────────
    # 🔴🔴 **这张表是我在 `KO_PLAN` §4.3 里判断"不需要"之后、建库途中被数据推翻的。**
    #   当时的判据是「`한자` 切片只能净增 619 个字头」—— 那句话本身是真的，
    #   但它**回答的不是这个问题**（`[[criterion-true-half-vouches-for-false-half]]`）：
    #   韩语汉字音的数据根本不在 `한자` 切片里，在**英文版的 `pos=syllable` 条目**里。
    #   建义项层时抽样看见 `주` 有 53 条"义项"、`의` 有 75 条，内容只是一个汉字，才发现。
    #
    #   实测：**8,640 条义项，99.4% 是汉字音格式，100% 落在 `pos=syllable` 上、
    #   100% 是单音节谚文，集中在 343 个音节**（`사` 171 条／`정` 154／`주` 131）。
    #   那是一张**音→字对照表**，不是义项：全量放进出版层，`사` 的页面会出现
    #   171 条只有一个汉字、没有释义的"义项"。
    #
    # ⚠️ 与 ja 的 `kanji_reading` **方向相反**：那张是「汉字 → 一组分类读音」
    #   （呉音/漢音/訓…），这张是「谚文音节 → 一组汉字」。同名不同物，别照搬它的列。
    """CREATE TABLE hanja_reading (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,       -- → dict.id（谚文音节，如 `사`）
         entry_id INTEGER,                -- → entry.id（`pos_raw='syllable'` 那条）
         hanja    TEXT NOT NULL,          -- 汉字，如 `事`
         gloss_en TEXT,                   -- 英文释义，如 `matter, affair`；源头常常没有
         eumhun   TEXT,                   -- 훈음（韩语训读），如 `일 사` —— 韩语汉字的一等信息
         mc       TEXT,                   -- 中古汉语音（`MC dzriH`），源头 1,810 条
         src      TEXT NOT NULL,
         src_ref  TEXT NOT NULL,
         UNIQUE(src_ref)
       )""",
    # ── 录音（阶段 6 填）。⭐ ko **与 ja 不同**：韩文版词条里真的嵌了音频 ──
    """CREATE TABLE audio (
         id         INTEGER PRIMARY KEY AUTOINCREMENT,
         word       TEXT NOT NULL,
         file       TEXT NOT NULL,        -- Commons 文件名 = 录音身份（去重靠它不靠 URL）
         url_mp3    TEXT,
         url_ogg    TEXT,
         url_wav    TEXT,
         url_other  TEXT,
         ipa        TEXT,
         speaker    TEXT,
         region     TEXT,
         region_src TEXT,
         kind       TEXT NOT NULL,        -- human / tts-tool / browser-tts
         src        TEXT NOT NULL,        -- ⭐ 韩文版 1,017 个内嵌 mp3_url（ja 是 0），
                                          --   中文繁体 124 / 日文版 54 / **英文版只有 27**。
                                          --   ⚠️ 这只是 dump 这一个入口，Commons 要另外量
         UNIQUE(word, file)
       )""",
]

DDL_INDEX = [
    "CREATE INDEX idx_dict_norm ON dict(word_norm)",
    "CREATE INDEX idx_entry_word ON entry(word_id)",
    "CREATE INDEX idx_entry_hanja ON entry(hanja)",
    "CREATE INDEX idx_sense_word ON sense(word_id)",
    "CREATE INDEX idx_sense_entry ON sense(entry_id)",
    "CREATE INDEX idx_sensesrc_word ON sense_src(word_id)",
    "CREATE INDEX idx_sensesrc_sense ON sense_src(sense_id)",
    "CREATE INDEX idx_glosslang ON sense_gloss(lang)",
    "CREATE INDEX idx_tag_kind ON sense_tag(kind, value)",
    "CREATE INDEX idx_rel_word ON sense_relation(word_id)",
    "CREATE INDEX idx_rel_sense ON sense_relation(sense_id)",
    "CREATE INDEX idx_infl_word ON inflection(word_id)",
    "CREATE INDEX idx_infl_base ON inflection(base)",
    # 🔴 `base_id` 也要索引 —— 第一版只索引了 `base`（词形字符串）。
    #    「这个词形是不是某个变形形的原形」这个问题走的是 `base_id`，
    #    而它正是**空白页判据**的一半（`pipeline/coverage.py` R1）。
    #    没有它，那条判据要在 40 万行 × 37.8 万次上全表扫。
    "CREATE INDEX idx_infl_baseid ON inflection(base_id)",
    "CREATE INDEX idx_pron_word ON pronunciation(word_id)",
    "CREATE INDEX idx_pron_entry ON pronunciation(entry_id)",
    "CREATE INDEX idx_etym_word ON etymology(word_id)",
    "CREATE INDEX idx_ex_word ON example(word)",
    "CREATE INDEX idx_ex_sense ON example(sense_id)",
    "CREATE INDEX idx_col_word ON collocation(word_id)",
    "CREATE INDEX idx_audio_word ON audio(word)",
    "CREATE INDEX idx_hanja_word ON hanja_reading(word_id)",
    # 反查「这个汉字读什么音」要靠这个索引 —— 表是按音节存的，反向查得有路
    "CREATE INDEX idx_hanja_char ON hanja_reading(hanja)",
]

TABLES = [q.split("CREATE TABLE ")[1].split(" ")[0].strip() for q in DDL]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    # 🔴 库可能还不存在（ko 的第一步就是本文件）—— 那不是异常。
    #    `dbtool.session` 的 `_ALLOW_EMPTY_PREFIX="build"` 允许 build- 开头的 tag 从空库开始。
    have = set()
    if paths.DB.exists():
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
    todo = [t for t in TABLES if t not in have]
    print("■ 库：%s" % (paths.DB if paths.DB.exists() else "（还不存在，本步建它）"))
    print("■ 已有表：%s" % (", ".join(sorted(have)) or "（无）"))
    print("■ 本步建：%d 张 —— %s" % (len(todo), ", ".join(todo)))
    if not todo:
        print("（都已存在，无事可做）")
        return
    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    # 纯 DDL：不插一行，所以 `expect` 全空 —— 未声明的表行数必须零变化，
    # 而新建的空表行数就是 0，闸自然过。
    with dbtool.session("build-ko-v3-schema", expect={}) as s:
        for q in DDL:
            if q.split("CREATE TABLE ")[1].split(" ")[0].strip() in todo:
                s.execute(q)
        for q in DDL_INDEX:
            try:
                s.execute(q)
            except sqlite3.OperationalError as e:
                if "already exists" not in str(e):
                    raise

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    now = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    nrow = {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in TABLES}
    con.close()
    miss = [t for t in TABLES if t not in now]
    # 🔴 **只检查「本步新建的」那些表是空的**，不是所有表。
    #    第一版写的是 `nrow.items()` 全集 —— 首次建库时恰好全空所以看着对，
    #    而 2026-09-20 补建 `hanja_reading` 时（`dict`/`entry` 已灌好数据）当场假红：
    #    「新建的表都是空的 🔴 非空 2 张 {dict: 51155, entry: 57637}」。
    #    写库闸本身是通过的，红的只有这条回核 —— **判据比它要描述的东西宽**，
    #    而这种假红最贵的地方是它让人习惯忽略红字（`[[fix-regression-and-gate]]`）。
    nonzero = {t: n for t, n in nrow.items() if n and t in todo}
    print("\n═══ 写后回核 ═══")
    print("   %s %d 张表都在      缺 %d 张" % ("✅" if not miss else "🔴", len(TABLES), len(miss)))
    print("   %s 本步新建的 %d 张表都是空的    非空 %d 张 %s"
          % ("✅" if not nonzero else "🔴", len(todo), len(nonzero), nonzero or ""))
    if miss or nonzero:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
