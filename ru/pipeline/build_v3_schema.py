#!/usr/bin/env python3
"""ru 阶段 0：建 v3 结构。2026-10-07。**幂等**，重跑不改已有数据。

照 `docs/SCHEMA.md`（`PLAYBOOK` 零：**结构在写第一行业务代码之前定死，别自己再设计一遍**）。
与 ko/vi 一样是 **v3 原生**，没有 v2 迁移包袱；`dict` 的建表语句也在本文件 ——
ja 把它藏在 `build.py` 里，于是「这门语言的结构长什么样」散在两个文件。

═══ 🔴 每一条与九门不同的地方，都是量出来的 ═══
依据全在 `docs/RU_PLAN.md` §二 与 §六，判据可重跑（`ru/probes/*.py`）。

  ① **`stress` 独立成表，`entry.stressed` 是派生展示列**（RU_PLAN §5.1）
     俄语重音**辨义**（`замо́к` 锁／`за́мок` 城堡）**且屈折时移动**（`беда́ бе́ды беды́`），
     而源头的词头**一个重音符都不带**（七源合计 8 个条目／0.00%）。
     实测多候选 3,342 个条目里 **93.7%（3,131）是纯重音变体**
     （`алфави́т`／`алфа́вит`、`Украи́на`／`Укра́ина`）。
     ⇒ 照 **ko 的 `entry.hanja` ＋ `hanja_spelling`** 那个形状：单值展示列 ＋ 多候选表。
     🔴 **不用「列里存数组」**：SQLite 没有数组类型，那就是 JSON 或分隔符串，
        而 `SCHEMA` §10.4.1 明确反对「塞进单列就要发明一套编码 ——
        发明的编码既失真、又会变成第二份真值」。
     ⚠️ 外审两家在这一条上给了**相反**的结论（一家 C 一家 B），
        而**两家都在引用我给它们的那条判据**。采 C 的理由是上面那个先例，不是两家中的任一个。

  ② **`inflection` 要建，而且是九门里最大的一层**（用户 2026-10-07：「可以先收，用不用另说」）
     en 版 `forms` 291 万行 ／ **ru 版 440 万行**，预计超过 de 的 536 万。
     ⚠️ **「先收」不等于「都印」** ⇒ `dict.is_lemma` ＋ 展示层 WHERE，两个数一起锁。
     🔴 `inflection.stressed` 是**独立的一列**，不能从词元重音推 —— 重音在变格中移动。

  ③ **`aspect` 落 `entry` 列，而 `transitivity`／`number` 落行**（RU_PLAN §6.1）
     实测「entry 内不一致」：aspect 1.45%（而**那 6,394 条 100% 是屈折形**，
     成因是一个变位形同时挂在两个动词下；真词元只有 2 个）⇒ 单值，落列。
     number **2.43%** ⇒ 落行。
     transitivity 的决定性数据**不在那一列**：ru 版**词级 tags 自身多值 18,543 条**
     （`намельчить ['intransitive','transitive']`）⇒ 落行。
     ⭐ **「单值还是多值」要在两个口径上同时问**（entry 内一致性 ＋ 单个 tags 数组内多值），
       只看前者会把 transitivity 判成单值。

  ④ **`aspect` 的值域要归一**（RU_PLAN §6.5）
     ru 版标 `perfect`（23,534）、en/zh-t 版标 `perfective` —— **同一件事两个词**。
     归一到 `perfective`（`perfect` 在语言学里指完成**时**，wiktextract 在 ru 版用错了词）。
     原词留在证据层。本文件的 `--check` 断言这一列的值域只有三个。

  ⑤ **`sense_relation` 要两个新 `kind`：`aspect_pair` 与 `word_family`**（RU_PLAN §5.2/5.3）
     体对不是屈折关系、也不是派生关系（异根体对 `говорить ↔ сказать`）⇒ 自己的 kind，
     带 `subkind` 区分纯体对与方式体（源头给了 `semelefactive`／`iterative` 标签，**不用猜**）。
     构词词族（«Родственные слова» 428 万条）不能并进 `derived`（含多阶派生与复合）
     ⇒ 自己的 kind，带 `rel_group`（词性分组）与 `form_group`（构词形式分组）。
     🔴 `related` 兜底**只被语义上更具体的 kind 吞掉**（B17：vi 上 naive 判据宽 11 倍）。

  ⑥ **`entry.etym_no` 是 INTEGER**（RU_PLAN §6.4）
     源头混类型（en 版 `str` 14,875 ＋ `NoneType` 427,719；ru/zh-t 版全无编号）。
     vi 的 **B18** 就是它的下游：存成 TEXT ⇒ 字典序 ⇒「10」排在「2」前面。

  ⑦ **`pronunciation` 不把 dialect 放进主键**（与 vi 相反）
     vi 的源头**本来就按六个方言点成套给**（记录内多值率 100%）；
     俄语没有那个结构 —— 读音变体是重音/正字法变体，归 `stress` 表。
     🔴 **什么会推翻**：源头出现成套的地域读音标注（现为 0）。

  ⑧ **`pronunciation_entry` 不建** —— 门槛照 es 14／ko 429（0.75%）不建、it 282,060 建。
     ru 待量（阶段 4 量「同一词形的不同词条给了不同读音」有多少），
     🔴 **量完之前这张表不许出现在 `dbtool.TRACK_TABLES` 里**（B7 那种死条目）。

═══ ⚠️ 三条归一化约定，写在建表这一步是因为它们决定了能不能对齐 ═══
· **`word_norm` 只去 U+0301/U+0300 ＋ 小写，绝不 NFD**。实现与 import 时自检在
  `ru/dbtool.py`（`norm_ru`/`_norm_selfcheck`）。NFD 会把 **й→и、ё→е**，
  而 ё **辨义**（`всё`／`все`）。vi 那门归一出事＝1,291 个页面显示别的词的内容。
· **IPA 存裸**，而要剥的定界符是**一个集合**：`[]`（en/ru/zh 版）、`//`、
  **`\…\`（法语版 19,818 行）**、真裸（pl 版）。判据 `criteria.ipa_delimiter`。
  🔴 另有 pl 91 ＋ ru 1 条用 **ASCII 撇号当重音符**，入库走 `criteria.normalize_ipa`。
· **「这是个屈折形」的指针读 `senses[].form_of`**（382,715 条），
  只读 `word.form_of`（28 条）会漏 **99.99%**。

用法：
    python3 ru/pipeline/build_v3_schema.py            # 建表（幂等）
    python3 ru/pipeline/build_v3_schema.py --check    # 只核对，不写
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
      word        TEXT NOT NULL,                 -- 原样，**不去重音符、不折大小写**
      -- 检索键：`norm_ru()` ＝ 去 U+0301/U+0300 ＋ 小写。
      -- 🔴🔴🔴 **绝不 NFD**：它会把 й→и、ё→е，而 ё 辨义（`всё` 一切／`все` 所有人）。
      --   实现与 import 时自检在 `ru/dbtool.py`，谁改回 NFD 版 import 当场炸。
      -- 🔴 **也不折 ё→е**：源头与用户都常把 ё 写成 е，那是**检索召回**问题，
      --   归展示层解（查询时双写），**不许靠毁掉数据层的键来解**。
      -- 🔴🔴 **有意不带 `COLLATE NOCASE`**：SQLite 的 NOCASE 只折 ASCII A–Z，
      --   对西里尔**完全不生效**（`'МОСКВА' = 'москва' COLLATE NOCASE → 0`）。
      --   既然 Python 侧已经 lower()，NOCASE 只剩负作用
      --   （`[[query-perf-collation-traps]]`：NOCASE 列上做 BINARY 比较＝静默全表扫）。
      word_norm   TEXT NOT NULL,
      -- 值域：word / phrase / proverb / prefix / suffix / letter / abbrev
      --   判据只用源头 pos 直接映射，**一律不猜**（`ru/pipeline/criteria.py`）
      entry_type  TEXT NOT NULL DEFAULT 'word',
      -- 🔴 **这一列决定一切覆盖率的分母。** 用户 2026-10-07 定「屈折形先收」
      --   ⇒ 97.7 万词形里绝大多数 is_lemma=0。
      --   ⚠️ 「先收」不等于「都印」：收与用是两件事，展示层的 WHERE 与这一列
      --   **两个数一起锁**（vi 的 P1–P9 教训：只锁写入列，
      --   「把判据整个关掉」那种反方向回归逮不到）。
      is_lemma    INTEGER NOT NULL DEFAULT 1,
      pos         TEXT,                          -- 短码。ko 的 K31：展示层读哪一列闸就查哪一列
      freq_zipf   REAL,
      -- 🔴🔴 **按 `word` 唯一，不是 `(word, entry_type)`。** 第一版写成后者，于是
      --   同一个拼写在不同词性下成了**多个 dict 行**：骨架闸 K10 报出 `word_norm`
      --   一对多 56,379 组，而**其中 84.2%（47,460 组）是这个** —— 不是数据问题，
      --   **是我的设计错**。
      --       按 (word, entry_type)   1,023,872 行
      --       按 word               **976,762** 行  ← 正是阶段 -1 量到的七源并集
      --   ⚠️ 代价是读者可见的：一个词形两个页面，而展示层按 `word_norm` 查会取第一行
      --   —— vi 那门正是这样让 **1,291 个页面显示别的词的内容**。
      --   ⇒ `entry_type` 按词唯一，判据 `criteria.entry_type_for_word`
      --     （**两个独立信号一致**：源头词性 ＋ 词头自己的形式）。
      UNIQUE(word)
    )"""),
    ("idx_dict_norm", "CREATE INDEX IF NOT EXISTS idx_dict_norm ON dict(word_norm)"),
    # R30（2026-10-25）：ё 召回键的索引 —— 搜索走它的前缀区间（查询计划闸守着）
    ("idx_dict_fold", "CREATE INDEX IF NOT EXISTS idx_dict_fold ON dict(word_fold)"),
    ("idx_dict_lemma", "CREATE INDEX IF NOT EXISTS idx_dict_lemma ON dict(is_lemma)"),

    # ── 词条层：同形异义的分界（SCHEMA §10.3）─────────────────────
    ("entry", """
    CREATE TABLE IF NOT EXISTS entry (
      id        INTEGER PRIMARY KEY,
      word_id   INTEGER NOT NULL REFERENCES dict(id),
      pos       TEXT,
      -- 🔴 **INTEGER 不是 TEXT**（RU_PLAN §6.4）：源头混类型（en 版是 str），
      --   而 vi 的 B18 就是存成 TEXT 的下游 —— 字典序让「10」排在「2」前面。
      --   ⚠️ 只有 en 版有编号；ru/zh-t 版全无编号（一律 0）。
      etym_no   INTEGER NOT NULL DEFAULT 0,
      seq       INTEGER NOT NULL DEFAULT 0,      -- wiktextract 把一个章节切成多条时用
      -- ── 一等语法字段：**落列的那几个，每个都量过「entry 内是不是单值」** ──
      -- 体。值域**只有三个**：imperfective / perfective / biaspectual。
      -- 🔴 ru 版源头标 `perfect`、en/zh-t 版标 `perfective` ⇒ **归一到 perfective**
      --   （`perfect` 在语言学里指完成**时**，wiktextract 在 ru 版用错了词）。
      --   原词留在证据层；`--check` 断言这一列的值域只有三个。
      -- ⚠️ entry 内不一致率 1.45%，而**那 6,394 条 100% 是屈折形**
      --   （一个变位形同时挂在两个动词下）；真词元只有 2 个 ⇒ 落列成立。
      aspect    TEXT,
      -- 性。不一致率 0.31%，不一致的是数词（`два ['masculine','neuter']` 同形）
      -- ⇒ 落列，而**多值的那批落 `sense_tag(bucket='grammar')`**，列上不许塞组合值。
      gender    TEXT,
      -- 动物性（俄语里它决定宾格形态：动物名词宾格＝属格）。不一致率 0.08%
      animacy   TEXT,
      -- 变格类。实测 **entry 内不一致 0 条**，ru 版 125,726 条有值（en 版几乎没有）
      declension TEXT,
      src       TEXT NOT NULL,                   -- en-edition / ru-edition / zh-edition-trad …
      src_ref   TEXT NOT NULL,                   -- kk-<版>:<词>:<词性>:<词源号>:<seq>
      UNIQUE(src_ref)
    )"""),
    ("idx_entry_word", "CREATE INDEX IF NOT EXISTS idx_entry_word ON entry(word_id)"),

    # ── 🆕 重音层：**九门里第一次有这一层**，见 ① ──────────────────
    ("stress", """
    CREATE TABLE IF NOT EXISTS stress (
      id          INTEGER PRIMARY KEY,
      word_id     INTEGER NOT NULL REFERENCES dict(id),
      -- 🔴 **挂在 entry 上而不是 word 上**：`о́рган`（器官）／`орга́н`（管风琴）
      --   是同一个 `word` 的两个 entry，重音不同。定不到 entry 就留 NULL，**不猜**。
      entry_id    INTEGER REFERENCES entry(id),
      stressed    TEXT NOT NULL,                 -- 带 U+0301 的干净拼写
      -- 多候选的排序。实测 3,342 个条目有 ≥2 个候选，其中 93.7% 是纯重音变体
      -- （`алфави́т`／`алфа́вит`）。⚠️ 剩 6.3% 不是：支配格不同、源头重复行、词缀带/不带符。
      variant_seq INTEGER NOT NULL DEFAULT 0,
      -- 展示默认行。**它是派生值**：`entry.stressed` 从这一行取。
      -- 🔴 一个 entry 最多一个 is_primary=1 —— `--check` 查这条。
      is_primary  INTEGER NOT NULL DEFAULT 0,
      -- 三个源，**各自带 src 不许并成一堆**（`[[ipa-provenance-columns]]`）：
      --   en-canonical  423,676（99.93% 带重音符）← 主力
      --   ru-stressed     2,367（源头专门为这件事留的字段，精度最高）
      --   ru-forms    4,170,656（屈折形的，落 `inflection.stressed` 不落这儿）
      src         TEXT NOT NULL,
      src_ref     TEXT NOT NULL,
      UNIQUE(src_ref)
    )"""),
    ("idx_stress_word", "CREATE INDEX IF NOT EXISTS idx_stress_word ON stress(word_id)"),
    ("idx_stress_entry", "CREATE INDEX IF NOT EXISTS idx_stress_entry ON stress(entry_id)"),

    # ── 屈折层：九门里最大的一层，见 ② ───────────────────────────
    ("inflection", """
    CREATE TABLE IF NOT EXISTS inflection (
      id       INTEGER PRIMARY KEY,
      -- 🔴 语义照 it 阶段 8 定死的那条：**`entry_id` 是「原形的那个 entry」**，
      --    不是「这个屈折形自己的 entry」。
      entry_id INTEGER NOT NULL REFERENCES entry(id),
      form     TEXT NOT NULL,                    -- 不带重音符的拼写
      -- 🔴 **独立的一列，不能从词元重音推** —— 俄语重音在变格中移动：
      --    `беда́ → бе́ды → беды́ → беде́ → бе́дам → беду́`
      --    实测 ru 版 `forms` 里 **4,170,656 条（94.83%）带重音符**。
      stressed TEXT,
      -- 源头的语法标签原样（nominative/genitive/…×singular/plural×三性，动词体/分词/命令式）
      tags     TEXT,
      -- 🔴 源头的变位表模板名。**它不是「变格类」** —— ko 的 K8/K10 同签名那笔账：
      --    `conj_class` 存的是源头 `table-tags`，五种不规则共用一个值 ⇒
      --    「数的是有值的行，不是有信息的行」。真正的变格类在 `entry.declension`。
      table_tag TEXT,
      src      TEXT NOT NULL,
      src_ref  TEXT NOT NULL,
      UNIQUE(src_ref)
    )"""),
    ("idx_infl_entry", "CREATE INDEX IF NOT EXISTS idx_infl_entry ON inflection(entry_id)"),
    ("idx_infl_form", "CREATE INDEX IF NOT EXISTS idx_infl_form ON inflection(form)"),

    # ── 义项两层（SCHEMA §2.-1）───────────────────────────────────
    ("sense_src", """
    CREATE TABLE IF NOT EXISTS sense_src (
      id        INTEGER PRIMARY KEY,
      word_id   INTEGER NOT NULL REFERENCES dict(id),
      entry_id  INTEGER REFERENCES entry(id),
      sense_id  INTEGER REFERENCES sense(id),    -- NULL ＝ 证据层收了但不出版
      lang      TEXT NOT NULL,                   -- 这条证据是用哪种语言写的
      text      TEXT NOT NULL,
      -- 🔴 指针义项的目标（`form_of`／`alt_of` 的结构字段）。
      --    **必须是一列，不许在展示层从 `text` 里用正则抠**（vi 的 W15 教训）。
      --    ⚠️ 判据读 `senses[].form_of`（382,715 条），
      --    只读 `word.form_of`（28 条）会漏 **99.99%**。
      pointer_target TEXT,
      src       TEXT NOT NULL,
      src_ref   TEXT NOT NULL,
      UNIQUE(src_ref)
    )"""),
    # 🔴 这个索引是 vi 阶段 9 的**查询计划闸**逮到的（`SCAN sense_src` 14.40 ms，
    #    是同一页其余五条查询的 **100 倍**；加索引后 0.018 ms）。
    #    ⚠️ 成因是**建表的时候没人按 `word_id` 查它** —— 那条热路径是阶段 9 才出现的。
    #    ⇒ ru 从第一天就建。`[[query-perf-collation-traps]]`：
    #      性能要等数据长大、或等读取路径出现才咬人。
    ("idx_sense_src_word", "CREATE INDEX IF NOT EXISTS idx_sense_src_word "
                           "ON sense_src(word_id)"),
    ("sense", """
    CREATE TABLE IF NOT EXISTS sense (
      id        INTEGER PRIMARY KEY,
      word_id   INTEGER NOT NULL REFERENCES dict(id),
      entry_id  INTEGER REFERENCES entry(id),
      rank      INTEGER NOT NULL DEFAULT 0,
      -- ko 的教训：`hidden` 背到第四种意思才拆。ru 从第一天就分开
      hidden    INTEGER NOT NULL DEFAULT 0,
      hidden_why TEXT
    )"""),
    ("idx_sense_word", "CREATE INDEX IF NOT EXISTS idx_sense_word ON sense(word_id)"),
    # 🆕 2026-10-23（阶段 5a）：**按 `sense_id` 取证据**。没有它，义项闸「每条出版义项都有证据」
    #    是 70 万次 × 170 万行的全表扫描（10 分钟没跑完）。⚠️ 这正是 vi 阶段 9 的那一笔：
    #    `SCAN sense_src` 每个词条页一次、14.40ms ＝ 同页其余的 100 倍 —— **建表时没人按这一列查，
    #    热路径是后来才出现的**。展示层同样要按 sense_id 取证据，所以这里建在表结构里，不建在闸里。
    ("idx_sense_src_sense", "CREATE INDEX IF NOT EXISTS idx_sense_src_sense ON sense_src(sense_id)"),
    ("idx_sense_entry", "CREATE INDEX IF NOT EXISTS idx_sense_entry ON sense(entry_id)"),
    ("sense_gloss", """
    CREATE TABLE IF NOT EXISTS sense_gloss (
      id       INTEGER PRIMARY KEY,
      sense_id INTEGER NOT NULL REFERENCES sense(id),
      lang     TEXT NOT NULL,                    -- 三语：zh / ru / en（`[[gloss-three-languages]]`）
      text     TEXT NOT NULL,
      src      TEXT NOT NULL,
      UNIQUE(sense_id, lang, text)
    )"""),
    ("sense_tag", """
    CREATE TABLE IF NOT EXISTS sense_tag (
      id       INTEGER PRIMARY KEY,
      sense_id INTEGER NOT NULL REFERENCES sense(id),
      -- topic / register / region / grammar / usage
      -- 🔴 **落行的那几个语法字段住在这儿**（RU_PLAN §6.1）：
      --    `number`（entry 内不一致 2.43%）、`transitivity`（ru 版词级 tags
      --    自身多值 18,543 条）、`actionality`（semelefactive／iterative，ru 版 631 条）、
      --    以及 gender／animacy 里**多值的那一小批**。
      bucket   TEXT NOT NULL,
      value    TEXT NOT NULL,                    -- 源头原词，不改写
      src      TEXT NOT NULL,
      UNIQUE(sense_id, bucket, value)
    )"""),

    # ── 读音：dialect 不进主键，见 ⑦ ─────────────────────────────
    ("pronunciation", """
    CREATE TABLE IF NOT EXISTS pronunciation (
      id       INTEGER PRIMARY KEY,
      word_id  INTEGER NOT NULL REFERENCES dict(id),
      -- **存裸**。要剥的定界符是一个集合：`[]`（en/ru/zh 版）／`//`／
      -- **`\\…\\`（法语版 19,818 行）**／真裸（pl 版）。判据 `criteria.normalize_ipa`，
      -- 它顺带把 ASCII 撇号换成 `ˈ`（pl 91 ＋ ru 1 条，欠账 R6）。
      ipa      TEXT NOT NULL,
      -- 🔴 源头没标就写 'unknown'，**不许假装是标准音**（照 vi 的 V4）。
      --    阶段 4 实测（RU_PLAN §11.2）：en 版有零星地域标签（Moscow 46／Saint-Petersburg 77／
      --    Ukraine 81…），**不成套** ⇒ 只收白名单里的地域，其余一律 unknown。
      --    🔴 **fr 版的 `Russie (Saint-Pétersbourg)` 不进这一列**：3,266/3,275 条与录音同在
      --       一个对象里 ⇒ 那是**录音者所在地**，不是这条读音的方言（只进 `tags`）。
      dialect  TEXT NOT NULL DEFAULT 'unknown',
      -- 🆕 2026-10-23（§11.3）**这条读音来自哪个 entry**。同形异重音词
      --    （`подать` ˈpodətʲ／pɐˈdatʲ、`горы`、`знаком`）只挂 word_id 就分不清哪个读音
      --    对应哪个意思。源头每一行就是一个 entry ⇒ 这一列**照抄来源，不推断**。
      --    NULL ＝ 挂不上 entry（如复数读音挂到了复数词形上，那个词形自己的 entry 未必有）。
      --    照 de/ko 先例；`pronunciation_entry`（多对多）仍不建（⑧）。
      entry_id INTEGER REFERENCES entry(id),
      -- `phonemic`（`//`、fr 版 `\…\`、en 的 `phoneme` 标签）／`narrow`（`[]`）／
      -- `unmarked`（源头没有定界符 —— **如实记，不替源头猜**）。展示层按它选括号。
      notation TEXT NOT NULL,
      -- 源头 tags ＋ raw_tags 原样（JSON 对象 `{"tags":[…],"raw_tags":[…]}`，**两边分开**：
      --   闸要从这一列重算 dialect/hidden，而两边的判法不同）。质量标记（`неправильно`/`proscribed`）、
      -- 录音者所在地、`Junior/Senior norm` 都在这里，**一个都不丢**。
      tags     TEXT,
      -- 「源头说这是错的/不推荐的读音」⇒ **存但不印**，且 `hidden_why` 说清为什么。
      --    照本库 `audio` 表同名两列（vi 的教训：`hidden` 背到第四种意思才拆出 `_why`）。
      hidden   INTEGER NOT NULL DEFAULT 0,
      hidden_why TEXT,
      src      TEXT NOT NULL,
      src_ref  TEXT NOT NULL,
      UNIQUE(src_ref)
    )"""),
    ("idx_pron_word", "CREATE INDEX IF NOT EXISTS idx_pron_word ON pronunciation(word_id)"),
    ("idx_pron_entry", "CREATE INDEX IF NOT EXISTS idx_pron_entry ON pronunciation(entry_id)"),

    # ── 关系：两个新 kind，见 ⑤ ──────────────────────────────────
    ("sense_relation", """
    CREATE TABLE IF NOT EXISTS sense_relation (
      id        INTEGER PRIMARY KEY,
      word_id   INTEGER NOT NULL REFERENCES dict(id),
      -- 🆕 2026-10-23（阶段 6b）：ru 版的关系是**条目级**的（`да` 语气词／连词各一套词族）
      entry_id  INTEGER REFERENCES entry(id),
      sense_id  INTEGER REFERENCES sense(id),    -- NULL ＝ 词条级关系
      -- 值域是一张**显式映射表**（`ru/pipeline/criteria.py`），认不出的源头字段一律报红，
      -- 不许归进 `related` 再也看不见。ru 比八门多两个：
      --   `aspect_pair`  体对（видовые пары）
      --   `word_family`  构词词族（«Родственные слова»，428 万条）
      kind      TEXT NOT NULL,
      -- 🆕 `aspect_pair` 用它区分**纯体对**与**方式体**：
      --   外审两家一致指出 `работать → порабо́тать`（限时体 делимитатив）、
      --   `висеть → повисе́ть` **不是纯体对**，`учиться → научи́ться` 才是。
      --   ⭐ 而**源头给了标签**（`semelefactive` 437／`iterative` 194），不用猜也不用问模型。
      subkind   TEXT,
      -- 🆕 `word_family` 用这两列装源头的分组（77.42% 带词性分组标签）。
      --   🔴 展示层给不给读者看是**阶段 9 的决定**（外审两家在这一点上相反），
      --   数据层两种展示都要做得到 ⇒ 现在就存。
      rel_group  TEXT,                           -- существительные / прилагательные / глаголы …
      form_group TEXT,                           -- уменьш.-ласк. формы / увелич. формы …
      target    TEXT NOT NULL,
      target_id INTEGER REFERENCES dict(id),
      -- B17：兜底 `related` 撞上**语义上更具体**的 kind 时读者会在两个标题下看见同一个词。
      -- 做法是 hidden=1 ＋ hidden_why（**不删**）。
      -- 🔴 vi 的实证：naive 判据（撞上**任何**别的 kind）宽 11 倍。
      hidden    INTEGER NOT NULL DEFAULT 0,
      hidden_why TEXT,
      src       TEXT NOT NULL,
      src_ref   TEXT NOT NULL,
      UNIQUE(src_ref)
    )"""),
    ("idx_rel_word", "CREATE INDEX IF NOT EXISTS idx_rel_word ON sense_relation(word_id)"),
    ("idx_rel_kind", "CREATE INDEX IF NOT EXISTS idx_rel_kind ON sense_relation(kind)"),

    # ── 词源 ─────────────────────────────────────────────────────
    ("etymology", """
    CREATE TABLE IF NOT EXISTS etymology (
      id       INTEGER PRIMARY KEY,
      word_id  INTEGER NOT NULL REFERENCES dict(id),
      entry_id INTEGER REFERENCES entry(id),
      etym_no  INTEGER NOT NULL DEFAULT 0,       -- 见 ⑥，INTEGER 不是 TEXT
      etym_sub INTEGER NOT NULL DEFAULT 0,       -- 🆕 2026-10-24：与 entry 同（`1.1`/`1.2` 两支）
      -- 🆕 2026-10-24（阶段 7）：照例句层 —— `text` 是 dump 原文一个字不动，`text_pub` 是出版正文
      --    （剥掉 ru 版 30 万行 `От ??` 占位、wiki 维护提示、词源树挂件残渣；NULL ＝ 与 text 相同）
      text     TEXT NOT NULL,
      text_pub TEXT,
      -- fr/vi/pl 的词源散文**进证据层不出版**（三语方针）；指针段（「见主词条的词源」）也不出版
      hidden   INTEGER NOT NULL DEFAULT 0,
      hidden_why TEXT,
      -- 🔴🔴 **字段名两版不同**：en 版 `etymology_text`（单数，45,823 条），
      --    ru/fr/zh 版 `etymology_texts`（**复数**，ru 版 453,534 条＝en 版的 9.9 倍）。
      --    只认单数 ⇒ ru 版报 0.0% ⇒ 会写下「只有英文版有词源」这个结论（ko 的 K36）。
      --    这一列记的是从哪个字段抽来的，出问题能定位。
      src_field TEXT NOT NULL,
      -- 词源类型。🔴 vi 靠源头 `etymology_templates` 推它，而那个字段
      --    **只有 en 版有**（44,866 条／10.14%）⇒ ru 的 `etym_type` 上限就是 10.14%，
      --    其余只能留 NULL。**别假设能照搬 vi。**
      etym_type TEXT,
      src      TEXT NOT NULL,
      src_ref  TEXT NOT NULL,
      UNIQUE(src_ref)
    )"""),
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

    # ── 例句 ─────────────────────────────────────────────────────
    ("example", """
    CREATE TABLE IF NOT EXISTS example (
      id       INTEGER PRIMARY KEY,
      word_id  INTEGER NOT NULL REFERENCES dict(id),
      -- 🆕 2026-10-23（阶段 6a）：同形异义词各有各的例句（`замок` за́мок／замо́к），
      --    挂到义项之外还要能挂到 entry（义项没进出版层的那 1.6%–98% 才有家）
      entry_id INTEGER REFERENCES entry(id),
      sense_id INTEGER REFERENCES sense(id),
      -- 🔴 `text` ＝ dump 原文、一个字不动（外锚闸逐字比）；`text_pub` ＝ 印给读者的
      --    （NULL ＝ 与 text 相同）。vi 的 W22：清洗原地改 text ⇒ 一列两个意思。
      --    付费翻译只翻 text_pub。判据 `criteria` §⑪。
      text     TEXT NOT NULL,
      text_pub TEXT,
      ref      TEXT,                             -- 文献出处
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

    # ── 录音 ─────────────────────────────────────────────────────
    ("audio", """
    CREATE TABLE IF NOT EXISTS audio (
      id       INTEGER PRIMARY KEY,
      word_id  INTEGER NOT NULL REFERENCES dict(id),
      -- 🆕 2026-10-23（阶段 6c）：照音标层 —— 复数录音挂到主格复数那个词形、entry_id NULL
      entry_id INTEGER REFERENCES entry(id),
      url      TEXT NOT NULL,
      -- B12：同一条录音被存成两行。`commons_key` 是 MediaWiki 标题归一后的键，
      -- **从第一天就存**（vi 实测：按 url 去重并到 4,560，按 commons_key 才到 3,110
      -- ⇒ 1,450 行 31.8% 的重复会落进库）。
      -- ⚠️ `UNIQUE(word_id, url)` **挡不住 B12**，它拦的是同一个 url 插两次。
      commons_key TEXT,
      hidden   INTEGER NOT NULL DEFAULT 0,
      hidden_why TEXT,
      src      TEXT NOT NULL,
      UNIQUE(word_id, url)
    )"""),
    ("idx_audio_key", "CREATE INDEX IF NOT EXISTS idx_audio_key ON audio(commons_key)"),

    # ── 字段级来源（de §12）─────────────────────────────────────
    ("field_src", """
    CREATE TABLE IF NOT EXISTS field_src (
      id       INTEGER PRIMARY KEY,
      tbl      TEXT NOT NULL,
      row_id   INTEGER NOT NULL,
      col      TEXT NOT NULL,
      src      TEXT NOT NULL,                    -- 表里有行 ＝ 这个值没有源头背书
      UNIQUE(tbl, row_id, col)
    )"""),
]

# 🔴 **有意不建**，每条都写了推翻条件（`PLAYBOOK` 7.5）。
#    ⚠️ 不建 ⇒ 也不许列进 `dbtool.TRACK_TABLES`，否则就是 B7 那种死条目。
NOT_BUILT = {
    "pronunciation_entry":
        "门槛照 es 14（不建）／ko 429 即 0.75%（不建）／it 282,060（建）。"
        "**ru 尚未量** ⇒ 推翻：阶段 4 量出「同一词形的不同词条给了不同读音」"
        "超过 `pronunciation` 总行的 5% 就建。"
        "🔴 量完之前不许进 `TRACK_TABLES`。",
    "collocation":
        "搭配层五门 99.3% 是模型凭记忆写的、无外部出处（`[[collocation-layer-is-llm-generated]]`）。"
        "ru 不从这条路起步。推翻：找到有外部出处的俄语搭配源。",
    "aspect_pair":
        "**有意不建专表** —— 体对走 `sense_relation(kind='aspect_pair')`。"
        "判据是项目既有的「专表的门槛是它不是词形／不是一对一」，而体对**是词对词关系**。"
        "⚠️ 外审一家建议建专表（理由是需要 sense_id ＋ 纯体对标记 ＋ 置信度），"
        "那些是**加字段**不是**建表**。推翻：若体对需要的列超过 3 个且与别的 kind 完全不共用。",
    "word_family":
        "同上 —— 构词词族走 `sense_relation(kind='word_family')` ＋ `rel_group`/`form_group`。"
        "推翻：若将来要存**词根与派生层级的树形结构**（那不是词对词关系）。",
}

# 🔴 **后补的列**。`CREATE TABLE IF NOT EXISTS` 对已存在的表是空操作 ——
#    改了上面的建表语句，**老库上一个字都不会变**，而只数对象名的 `--check`
#    会照样报全绿（B7 的形状：只审计表、不审计列）。
# ⇒ 这张表列「表.列 → 类型」，建表时逐条补、`--check` 时逐条查。
ADD_COLUMNS = [
    # 🔴🔴 **词源子编号**。源头有 `etymology_number = '1.1'/'1.2'`（实测 2 行，
    #    `лиственник` 的两支词源）。存 TEXT ⇒ 字典序（vi 的 B18）；
    #    截断成 `1` ⇒ **把两支不同的词源合成一支**。⇒ 拆两个 INTEGER 列。
    #    ⚠️ 它是判据自己拦下来的：`etym_no_pair` 在转不动时 `raise` 而不是兜底成 0。
    ("entry", "etym_sub", "INTEGER NOT NULL DEFAULT 0"),
    # 🔴 `entry.stressed` 是**派生展示列**（真值在 `stress` 表，取 is_primary 那一行）。
    #    列在这儿而不是写进 `entry` 的 DDL，是为了让「它是派生的」这件事在代码里显形：
    #    它由 `stress` 表算出来，重算一遍就能复原 —— 不是第二份真值。
    ("entry", "stressed", "TEXT"),
    # 🆕 2026-10-25（R29）：中文的**出版正文**（简体）。`text` 是源头／模型原话一个字不动（外锚闸逐字比），
    #    `text_pub` ＝ `criteria.zh_simp(text, src)`，与 `text` 相同就存 NULL（照 `example.text_pub`）。
    #    只填 `lang='zh'` 的行。由 `zh_pub.py --sync` 同步，回归闸 P22 逐行比判据。
    ("sense_gloss", "text_pub", "TEXT"),
    ("example_gloss", "text_pub", "TEXT"),
    ("sense_src", "text_pub", "TEXT"),
    # 🆕 2026-10-25（R30）：ё 召回键 `dbtool.fold_ru(word)`（`norm_ru` 再折 ё→е）。**不是身份键**：
    #    `все`/`всё` 在它上面相同。只给搜索「省写 ё 也找得到」用，认词仍按 `word`/`word_norm`。
    ("dict", "word_fold", "TEXT"),
]


def connect(ro=False):
    if ro:
        return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    return sqlite3.connect(paths.DB)


def objects(conn):
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}


def cols(conn, tbl):
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % tbl)}



def _norm_sql(s):
    """把建表语句归一到可比较的形状：去注释、去 `IF NOT EXISTS`、压空白。

    🔴 **只做这三种归一，绝不调用任何业务转换器**（`PLAYBOOK` 7.2 的那条设计要点）。
    """
    import re as _re
    s = _re.sub(r"--[^\n]*", " ", s or "")
    s = _re.sub(r"\bIF\s+NOT\s+EXISTS\b", " ", s, flags=_re.I)
    s = _re.sub(r"\s+", " ", s)
    return s.strip().rstrip(";").lower()


_CONSTRAINT_KW = ("unique", "primary key", "foreign key", "check", "constraint")


def _split_table(sql):
    """建表语句 → (列定义集合, 约束集合)。**按顶层逗号切，括号内不切。**

    🔴 为什么不比整串：后补的列（`ADD_COLUMNS`）是 `ALTER TABLE` 加的，
       SQLite 把它们**插在最后一个列定义之后、约束之前** ——
       比整串会把这当成不一致（S6 第一版就是这样假红了一次）。
    ⚠️ 这里用「顶层逗号」切，而不是 `split(",")`：`NUMERIC(10,2)` 那种括号里有逗号。
    """
    s = _norm_sql(sql)
    i = s.index("(")
    body = s[i + 1:s.rindex(")")]
    items, buf, depth = [], [], 0
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    items.append("".join(buf).strip())
    cols, cons = set(), set()
    for it in items:
        if not it:
            continue
        (cons if it.startswith(_CONSTRAINT_KW) else cols).add(it)
    return cols, cons


def check(verbose=True):
    """→ 红的条目列表。**四类都查**，缺一类就是一道半瞎的闸。"""
    bad = []
    if not paths.DB.exists():
        # 🔴 **不许静默 return。** 第一版这里直接 `return [...]`，绕过了下面的打印块
        #    ⇒ `--check` 什么都不印、退出码 1。**静默的红比红更坏**：
        #    看屏幕的人只知道"它失败了"，不知道失败在哪。
        #    （同一形状：vi 的「一条空过的检查比没有检查更坏」。）
        msg = "库不存在：%s —— 先跑一次不带 `--check` 的本脚本建表" % paths.DB
        if verbose:
            print("🔴 结构核对未通过：1 条\n   " + msg)
        return [msg]
    conn = connect(ro=True)
    try:
        have = objects(conn)
        # ① 声明要建的对象，一个都不许少
        for name, _ in DDL:
            if name not in have:
                bad.append("缺对象 %s" % name)
        # ② 后补的列，一个都不许少（B7 的另一半）
        for tbl, col, _ in ADD_COLUMNS:
            if tbl in have and col not in cols(conn, tbl):
                bad.append("缺列 %s.%s" % (tbl, col))
        # ③ 🔴 **有意不建的有没有偷偷出现** —— vi 用变异验过这一条
        for name, why in NOT_BUILT.items():
            if name in have:
                bad.append("**有意不建的 %s 出现了** —— 要么它该建（那就改 NOT_BUILT "
                           "并写明推翻了什么），要么是手滑。原因：%s" % (name, why[:60]))
        # ④ 值域断言：`entry.aspect` 归一之后只许三个值（RU_PLAN §6.5）
        if "entry" in have and "aspect" in cols(conn, "entry"):
            vals = {r[0] for r in conn.execute(
                "SELECT DISTINCT aspect FROM entry WHERE aspect IS NOT NULL")}
            extra = vals - {"imperfective", "perfective", "biaspectual"}
            if extra:
                bad.append("`entry.aspect` 出现值域外的值 %s —— ru 版源头标 `perfect`、"
                           "en 版标 `perfective`，**必须归一到 perfective**"
                           "（RU_PLAN §6.5）。源头原词留证据层。" % sorted(extra))
        # ⑤ 🔴🔴 **建表语句本身要对账** —— 不只对象名和列名。
        #    2026-10-08 实证：我把 `dict` 的唯一键从 `(word, entry_type)` 改成 `(word)`，
        #    而 `CREATE TABLE IF NOT EXISTS` 对已存在的表是**空操作** ⇒
        #    **库里还是旧的唯一键，而这道闸报全绿**。
        #    ⭐ 那正是本文件头警告过的那件事（B7 的形状），而**原来的五条判据
        #      只数对象名和列名，对「唯一键/约束/类型变了」结构性失明** ——
        #      它是被一次变异验证的 `IntegrityError` 撞出来的，不是读代码读出来的。
        #    🔴 **而 S6 自己第一版也假红了一次**：它比整串，于是把 `ALTER TABLE`
        #      后补的列（`ADD_COLUMNS`）当成了不一致。⇒ 改成**按列定义与约束逐项对账**，
        #      期望的列集合 ＝ DDL 的列 ∪ 这张表的 `ADD_COLUMNS`。
        #      ⚠️ 这样 SQLite 把后补列插在哪儿都不影响，报错也能指出差的是哪一项。
        #    （见 `docs/BACKLOG.md` **B24**：另八门一处都没有这个对账。）
        added = {}
        for tbl, col, decl in ADD_COLUMNS:
            added.setdefault(tbl, set()).add(_norm_sql("%s %s" % (col, decl)))
        for name, sql in DDL:
            if not sql.strip().lower().startswith("create table"):
                continue
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
            if row is None or row[0] is None:
                continue                       # 缺对象那一条已经由 ① 报了
            try:
                live_cols, live_cons = _split_table(row[0])
                want_cols, want_cons = _split_table(sql)
            except ValueError as e:
                bad.append("表 `%s` 的建表语句切不开（%s）—— 本判据坏了，不是通过" % (name, e))
                continue
            want_cols |= added.get(name, set())
            if live_cols != want_cols or live_cons != want_cons:
                diff = []
                for lab, lv, wv in (("列", live_cols, want_cols),
                                    ("约束", live_cons, want_cons)):
                    if lv - wv:
                        diff.append("库里多的%s：%s" % (lab, sorted(lv - wv)[:3]))
                    if wv - lv:
                        diff.append("DDL 有而库里没有的%s：%s" % (lab, sorted(wv - lv)[:3]))
                bad.append(
                    "表 `%s` **库里的建表语句与 DDL 不一致** —— "
                    "`CREATE TABLE IF NOT EXISTS` 对已存在的表是空操作，"
                    "改了 DDL 老库一个字都不会变。**要迁移或重建。**\n      %s"
                    % (name, " ｜ ".join(diff)))

        # ⑥ 一个 entry 最多一行 is_primary（`entry.stressed` 是从它派生的）
        if "stress" in have:
            n = conn.execute(
                "SELECT COUNT(*) FROM (SELECT entry_id FROM stress WHERE is_primary=1 "
                "AND entry_id IS NOT NULL GROUP BY entry_id HAVING COUNT(*)>1)").fetchone()[0]
            if n:
                bad.append("`stress` 里有 %d 个 entry 有多行 is_primary=1 —— "
                           "`entry.stressed` 是从它派生的，多行就没有唯一的派生值了" % n)
    finally:
        conn.close()
    if verbose:
        if bad:
            print("🔴 结构核对未通过：%d 条" % len(bad))
            for b in bad:
                print("   " + b)
        else:
            print("■ 结构核对通过 ✓（%d 个对象 ／ %d 个后补列 ／ %d 个有意不建"
                  " ／ 建表语句逐表对账）"
                  % (len(DDL), len(ADD_COLUMNS), len(NOT_BUILT)))
    return bad


def _rebuild_empty_drifted(conn):
    """库里的建表语句与 DDL 不一致的表：**0 行就按新 DDL 重建，有数据就拒绝。**

    2026-10-23 为 `pronunciation` 补列时立的（那时它还是 0 行）。
    🔴 为什么不放宽到「有数据也重建」：`DROP` 掉一张有数据的表是不可逆的，
       而 `CREATE TABLE IF NOT EXISTS` 的空操作让人以为改 DDL 就够了（B24）。
       ⇒ 有数据的表要写迁移，并在这里报错时说清是哪张表。
    ⚠️ 只看列定义与约束（与 S6 同一个对账函数），不看注释和空白。
    """
    live = {r[0]: r[1] for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table'")}
    added = {}
    for tbl, col, decl in ADD_COLUMNS:
        added.setdefault(tbl, set()).add(_norm_sql("%s %s" % (col, decl)))
    for name, sql in DDL:
        if not sql.strip().lower().startswith("create table") or name not in live:
            continue
        lc, lk = _split_table(live[name])
        wc, wk = _split_table(sql)
        # 后补列可以**还没加上**（这一轮 ALTER 正要加它）：介于「DDL」与「DDL＋后补列」之间都算一致。
        #   🔴 第一版写成 `lc == wc | added` ⇒ 新登记一个后补列时，有数据的表被判成「结构漂移」（R29 撞上）
        if wc <= lc <= (wc | added.get(name, set())) and lk == wk:
            continue
        n = conn.execute("SELECT COUNT(*) FROM %s" % name).fetchone()[0]
        if n:
            raise SystemExit(
                "🔴 表 `%s` 的结构与 DDL 不一致，而它有 %s 行 —— **不自动重建**（DROP 不可逆）。"
                "写一个迁移。" % (name, format(n, ",")))
        print("■ 表 `%s` 结构与 DDL 不一致且为空 ⇒ 按新 DDL 重建" % name)
        for (idx,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? "
                "AND sql IS NOT NULL", (name,)).fetchall():
            conn.execute("DROP INDEX %s" % idx)
        conn.execute("DROP TABLE %s" % name)


def build():
    # 🔴 建库走 `dbtool.session` 的 `build` 前缀 —— 只有它允许从「库还不存在」开始，
    #    别的 tag 遇到空库会报错（库被误删／路径写错时静默从零开始比报错危险得多）。
    with dbtool.session("build-v3-schema", expect={}, invalidates=[]) as s:
        _rebuild_empty_drifted(s.conn)
        # 顺序：表 → 后补列 → 索引。🔴 索引可以建在后补列上（R30 的 `idx_dict_fold`），
        #    先跑全部 DDL 的话 `CREATE INDEX` 会撞上「还没有这一列」
        is_tbl = lambda q: q.strip().lower().startswith("create table")       # noqa: E731
        for name, sql in DDL:
            if is_tbl(sql):
                s.conn.execute(sql)
        for tbl, col, decl in ADD_COLUMNS:
            if col not in cols(s.conn, tbl):
                s.conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tbl, col, decl))
        for name, sql in DDL:
            if not is_tbl(sql):
                s.conn.execute(sql)
        s.touched.add("dict")          # 改了结构 ⇒ 读者口径的闸一律重跑
    print("\n■ 建表完成。")
    return check()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只核对，不写")
    a = ap.parse_args()
    bad = check() if a.check else build()
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
