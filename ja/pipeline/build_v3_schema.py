#!/usr/bin/env python3
"""阶段 0（下半）：建 v3 十四张表。2026-09-15。

═══ 🔴 ja 没有「迁移」，所以这里只建表不搬数据 ═══
de/pt 的同名脚本要把 `dict` 的 v2 遗留列搬进新表，还要做可逆性回核。
ja 的 `dict` 从一开始就没建那些列（见 `build.py` 文件头）⇒ 本步是**纯 DDL**。

═══ 建空表也要现在建 ═══
`dbtool.TRACK_TABLES` 里写着这些表名。表不存在时快照静默跳过，
**建出来的那一刻闸自动开始守** —— 不靠「记得回来加」。

═══ 日语相对前六门改了三处，每处都有实测依据 ═══
① `entry` 加三列读音（`kana` / `kana_hist` / `romaji`）
   读音是 entry 的**属性**不是主键分量：3,951 条 entry 一条里就有 ≥2 个读音
   （`爺` = じい/じじ/じじい）。主键仍是 `(word_src, pos_raw, etym_no, seq)` ——
   实测 `(词形,词性,etym_no)` 单独就分开 85.5%，加 seq 归零。见 `JA_PLAN` §二。
② `pronunciation` 加两列声调（`pitch_mark` / `pitch_pos`）
   东京式声调。⚠️ **唯一可用来源是中文版**：日语版那份在抽取时就毁了
   （10,215 条里 10,212 条的 `other` 字面是 `"("`，重音位置全丢），且存活的是京阪式。
   🔴 **不立「声调型」列**（Heiban/Nakadaka/…）：类型与标记 100% 同时出现、
   从 `ꜜ` 位置反推类型准确率 99.99% ⇒ 类型是派生量，展示层一个 CASE 就够，
   落列是同一个信息存两份（`[[refactor-mindset-code-quality]]`）。
③ `pronunciation.notation` **必须真的用起来**
   日语 IPA 99.98% 是 `[...]`（窄式／实际音值），前六门是 `/.../`（音位）。
   六语种的存储约定是**裸存**，这条 ja 照跟；但展示层必须读 `notation` 决定加
   `[ ]` 还是 `/ /` —— 给窄式记音套音位定界符是**记法错误**不是风格问题。
   这列 v3 早就有，六门一直没用起来，ja 是第一个必须用它的。

跑（在仓库根）：
    python3 -u ja/pipeline/build_v3_schema.py
    python3 -u ja/pipeline/build_v3_schema.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sqlite3

import dbtool
import paths

DDL = [
    # ── 词条层。日语一等字段（读音三列）本层就留位 ──────────────────────
    """CREATE TABLE entry (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,       -- → dict.id
         word_src TEXT NOT NULL,          -- dump 里的真实拼写；🔴 ja 不折叠 ⇒ 恒等于 dict.word
         pos      TEXT NOT NULL,          -- POS_MAP 映射后的展示值
         pos_raw  TEXT NOT NULL,          -- dump 原始词性，主键用它
         etym_no  TEXT NOT NULL,          -- 词源号；没编号记 "0"
         seq      INTEGER NOT NULL,       -- 同键内序号，正常 0
         -- ── 日语一等字段 ──
         kana      TEXT,                  -- 假名读音。权威字段是 head_templates 里
                                          --   **第一个纯假名的数字位参数** ——
                                          --   🔴 不是 args["1"]：那里有 34,993 条装的是
                                          --   词性名（proper/adverb/suffix），`ja-pos` 的读音在 args["2"]
         kana_src  TEXT,                  -- head_templates / ruby / sounds（会变的字段才加 *_src）
         kana_hist TEXT,                  -- 历史假名遣（月 がち 的 ぐわち）
         romaji    TEXT,                  -- 修正ヘボン式，**存源头的不自己算**
                                          --   （算的与源头严格一致率仅 64.27%，
                                          --    算不出的是词界空格和 おう→ō/ou 的形态判断）
                                          --   ⚠️ 检索键可以算（归一后一致率 98.91%），那是另一回事
         kanji_grade TEXT,                -- 字种等级（常用/教育/人名用/表外）—— 单字条目才有
         src      TEXT NOT NULL,
         src_ref  TEXT NOT NULL,          -- kk-ja:<word_src>:<pos_raw>:<etym_no>:<seq>
         UNIQUE(src_ref)
       )""",
    # ── 义项两层：证据层 / 出版层（`SCHEMA` §2.-1）────────────────────────
    """CREATE TABLE sense_src (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,       -- → dict.id
         sense_id INTEGER,                -- 编入哪条出版义项；NULL = 尚未裁决
         src      TEXT NOT NULL,          -- en-edition / ja-edition / zh-edition
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
         rank     INTEGER NOT NULL,
         pos      TEXT,
         hidden   INTEGER NOT NULL DEFAULT 0,
         UNIQUE(word_id, rank)
       )""",
    """CREATE TABLE sense_gloss (
         sense_id INTEGER NOT NULL,
         lang     TEXT NOT NULL,          -- ja / en / zh（`[[gloss-three-languages]]` 只留三语）
         kind     TEXT NOT NULL,          -- equivalent / definition
         seq      INTEGER NOT NULL,
         text     TEXT NOT NULL,
         src      TEXT,
         PRIMARY KEY(sense_id, lang, kind, seq)
       )""",
    """CREATE TABLE sense_tag (
         sense_id INTEGER NOT NULL,
         kind     TEXT NOT NULL,          -- topic / region / register / usage / grammar
         value    TEXT NOT NULL,
         PRIMARY KEY(sense_id, kind, value)
       )""",
    """CREATE TABLE sense_relation (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,
         sense_id INTEGER,
         kind     TEXT NOT NULL,          -- synonym / antonym / … / alt_of / kyujitai
                                          -- 🔴 `soft-redirect` 的**一对一**那批（37,820 条）
                                          --   进这里（异表记）；**≥2 个目标的 7,079 条不进** ——
                                          --   `いぬ → 犬 狗 戌 率寝 寝ぬ 去ぬ` 是同音索引页，
                                          --   当异体写进来是 6,681 条规模的错。见 JA_PLAN §二.5
         target   TEXT NOT NULL,
         tags     TEXT,
         hidden   INTEGER NOT NULL DEFAULT 0,
         src      TEXT NOT NULL,
         src_ref  TEXT NOT NULL,
         UNIQUE(word_id, sense_id, kind, target)
       )""",
    # ── 变形层（阶段 2 填）──────────────────────────────────────────────
    """CREATE TABLE inflection (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,
         entry_id INTEGER,
         kind     TEXT NOT NULL,          -- inflection 活用 / derivation 构词
         base     TEXT NOT NULL,
         base_id  INTEGER,
         label_zh TEXT NOT NULL,
         desc_en  TEXT,
         tags     TEXT,
         src      TEXT NOT NULL,          -- 🔴 活用表在**日语版**：英文版只给 7.0% 的动词
         src_ref  TEXT NOT NULL
       )""",
    # ── 读音层（阶段 4 填）──────────────────────────────────────────────
    """CREATE TABLE pronunciation (
         id         INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id    INTEGER NOT NULL,
         entry_id   INTEGER,              -- → entry.id；null = 整词通用
         ipa        TEXT NOT NULL,        -- 裸存，不带定界符（六语种统一约定）
         notation   TEXT NOT NULL,        -- phonemic | narrow
                                          -- 🔴 日语 99.98% 是 narrow：展示层必须读这列决定
                                          --   加 [ ] 还是 / /，给窄式套音位定界符是记法错误
         pitch_mark TEXT,                 -- 声调标记原样（[néꜜkò]）
         pitch_pos  INTEGER,              -- 核位置；0 = 平板。由 ꜜ 位置派生
                                          -- 🔴 **不立「声调型」列**：类型与标记 100% 同现，
                                          --   反推准确率 99.99% ⇒ 派生量不落列
         region     TEXT,
         tags       TEXT,
         pos        TEXT,
         is_primary INTEGER NOT NULL DEFAULT 0,
         src        TEXT NOT NULL,        -- 🔴 声调唯一可用来源是 zh-edition
         src_ref    TEXT NOT NULL,
         UNIQUE(word_id, entry_id, ipa, notation)
       )""",
    # ── 例句（阶段 5 填，≈26,352 条）─────────────────────────────────────
    """CREATE TABLE example (
         id              INTEGER PRIMARY KEY AUTOINCREMENT,
         word            TEXT NOT NULL,
         sense_id        INTEGER,
         text            TEXT NOT NULL,   -- 日语原句
         bold            TEXT,
         ref             TEXT,
         src_gloss       TEXT,            -- 源里这条挂在哪条义项下（挂回义项的桥）
         src_translation TEXT,
         src_lang        TEXT,
         hidden          INTEGER NOT NULL DEFAULT 0,
         src             TEXT NOT NULL,
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
                                          --   ja **还没有这一层**，真要做先解决出处问题
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
    # ⚠️ `audio` 建表但**阶段 6 有意不做**：三版并集只有 206 个词形有 mp3_url，
    #    不是 `[[cross-edition-harvest]]` 记的 436 倍。建空表只为「万一走 Commons 直查」
    #    时闸立刻开始守；不排工（`[[record-the-negative-decision]]`：不做也是结论，要落账）。
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
         src        TEXT NOT NULL,
         UNIQUE(word, file)
       )""",
]

DDL_INDEX = [
    "CREATE INDEX idx_entry_word ON entry(word_id)",
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
    "CREATE INDEX idx_pron_word ON pronunciation(word_id)",
    "CREATE INDEX idx_pron_entry ON pronunciation(entry_id)",
    "CREATE INDEX idx_ex_word ON example(word)",
    "CREATE INDEX idx_ex_sense ON example(sense_id)",
    "CREATE INDEX idx_col_word ON collocation(word_id)",
    "CREATE INDEX idx_audio_word ON audio(word)",
]

TABLES = [q.split("CREATE TABLE ")[1].split(" ")[0].strip() for q in DDL]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    todo = [t for t in TABLES if t not in have]
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
    with dbtool.session("build-ja-v3-schema", expect={}) as s:
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
    nonzero = {t: n for t, n in nrow.items() if n}
    print("\n═══ 写后回核 ═══")
    print("   %s 十四张表都在      缺 %d 张" % ("✅" if not miss else "🔴", len(miss)))
    print("   %s 新建的表都是空的    非空 %d 张 %s"
          % ("✅" if not nonzero else "🔴", len(nonzero), nonzero or ""))
    if miss or nonzero:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
