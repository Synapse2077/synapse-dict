#!/usr/bin/env python3
"""阶段 0：意语库 v2 结构迁移 —— 建十二张表，把 `dict` 的内容列搬进去。2026-08-12。

结构照 `docs/SCHEMA.md` v2，**不重新设计**。计划见 `docs/IT_PLAN.md` 阶段 0。

═══ 这一步到底在干什么 ═══
`dict` 现在把「一个词的所有义项」粘在一个字符串里，用 `\\n` 分行：

    definition  = "to do\\nto make\\nto provoke…"      （英文，198,026 行义项）
    translation = "做\\n制作，制造\\n引起（生理感受）…"    （中文，逐行对齐）
    meta        = [{"pos":"v"},{"pos":"v","lex":["informal"]},…]   （逐元素对齐）

迁移把「第 N 行」变成 `sense.id` —— **这是本次重构最硬的理由**（`SCHEMA` §2.0.1）：
es 把 752 万 tokens 算出的 8 万条对齐存成"definition 第几行"，
四个脚本重排过它，那批映射**静默作废、没有任何报错**。行号不是契约，主键才是。

═══ 迁移前已全量核对（`probes/audit_sense_shape.py`）═══
    definition 行 198,026 == translation 行 198,026 == meta 元素 198,026     零错位
    definition 内空行 0 条；中文为空的义项行 2 条（都在 `in men che niente`）
    lex/reg 数组无重复值、已字典序 ⇒ `sense_tag` 的 (kind,value) 主键不丢信息

🔴 **变形层的判据是 `translation == infl`（指针文本），不是"有没有 definition"。**
   全库 432,512 个无 definition 的行里，432,490 行的 translation 与 infl **逐字节相同**
   （模板生成的 "pio 的 复数"），可以安全丢弃 —— `infl` 列本来就留着。
   但剩下 **22 行不是变形**：`ganga`（恒河；便宜货）、`sonata da chiesa`（教堂奏鸣曲）、
   `autoritativo`（权威的）—— 它们没有英文释义、`infl` 为 NULL，但中文是**真释义**。
   按"无 definition 即变形层"迁移会把这 22 条释义直接丢掉。它们照常建 `sense`。

═══ 三道闸（`SCHEMA` §5.0）═══
① **可逆性回核**：从新表重建 `definition` / `translation` / `meta` / `collocation`
   四列的每一行，与迁移前**逐字节**比对（`meta` 因 JSON 键序不保证，按解析后的值比对）。
   **100%，非抽样** —— 它把"义项和释义有没有配错"从抽样问题变成可判定问题。
② **不变量断言**：行数守恒（期望值先算出来）/ 无孤儿 / 主键无重 / 每条 sense 至少一条 gloss。
③ 抽样：本步是确定性转换，没有需要判断的部分，不适用。

用法（在 it/ 目录下）：
    python3 pipeline/build_v2_schema.py              # 试算 + 跑闸，不写库
    python3 pipeline/build_v2_schema.py --apply      # 建表并写入（走 dbtool 闸门）
    python3 pipeline/build_v2_schema.py --verify     # 只对已落库的结果跑三道闸
    python3 pipeline/build_v2_schema.py --mutate     # 🔴 变异验证：闸必须报出 5 处人为破坏
    python3 pipeline/build_v2_schema.py --drop-cols  # 闸①通过后，才把 dict 降到 19 列
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

CJK = re.compile(r"[一-鿿　-〿＀-￯]")

# 迁出后要从 dict 删掉的列（`SCHEMA` §3；it 版：26 列 → 19 列）
MOVED = ["definition", "translation", "translation_src", "meta", "collocation"]
DEAD = ["example", "flag"]          # 两列都是 0 行死数据

NEW_TABLES = ("sense_src", "sense", "sense_gloss", "sense_tag", "sense_relation",
              "pronunciation", "example", "example_gloss",
              "collocation", "collocation_gloss", "audio")

DDL = [
    # ── 义项两层：证据层 / 出版层（`SCHEMA` §2.-1）────────────────────────
    """CREATE TABLE sense_src (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,       -- → dict.id
         sense_id INTEGER,                -- 编入哪条出版义项；NULL = 尚未裁决
         src      TEXT NOT NULL,          -- en-edition / it-edition（记录的，非反推）
         src_ref  TEXT NOT NULL,          -- 回源坐标：dict:<id>#<行号> 或 kk:<word>:<pos>#<下标>
         lang     TEXT NOT NULL,          -- 这句原文是什么语言
         text     TEXT NOT NULL,          -- 原文
         raw_tags TEXT,                   -- 原始标签原样留底，归一失败时能回查
         UNIQUE(src_ref)
       )""",
    """CREATE TABLE sense (
         id      INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id INTEGER NOT NULL,        -- → dict.id
         rank    INTEGER NOT NULL,        -- 展示顺序 1,2,3…
         pos     TEXT,                    -- 逐义项词性（il fine 目的 / la fine 结尾）
         gender  TEXT,                    -- 逐义项性别
         UNIQUE(word_id, rank)
       )""",
    """CREATE TABLE sense_gloss (
         sense_id INTEGER NOT NULL,
         lang     TEXT NOT NULL,          -- en / it / zh …（加语言只往这里加行）
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
    """CREATE TABLE sense_relation (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,       -- → dict.id（关系的出发点）
         sense_id INTEGER,                -- → sense.id；NULL = 只知道属于这个词
         kind     TEXT NOT NULL,          -- synonym / antonym / hypernym / … / derived
         target   TEXT NOT NULL,          -- 目标词形原样，不解析成外键
         tags     TEXT,                   -- 源头 tags 的 JSON 数组
         src      TEXT NOT NULL,
         src_ref  TEXT NOT NULL,
         UNIQUE(word_id, sense_id, kind, target)
       )""",
    # ── 读音（阶段 4 填）──────────────────────────────────────────────
    """CREATE TABLE pronunciation (
         id         INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id    INTEGER NOT NULL,     -- → dict.id
         ipa        TEXT NOT NULL,        -- 裸存，不带定界符（六语种统一约定）
         notation   TEXT NOT NULL,        -- phonemic | narrow
         region     TEXT,                 -- it-IT / it-CH…；null = 通用或判不出
         tags       TEXT,                 -- 源头 tags/raw_tags 的 JSON 数组
         is_primary INTEGER NOT NULL DEFAULT 0,
         src        TEXT NOT NULL,        -- en-edition / fr-edition / it-edition / rule
         src_ref    TEXT NOT NULL,        -- kk:<word>:<pos>#<sounds 下标>
         UNIQUE(word_id, ipa, notation)
       )""",
    # ── 例句 / 搭配 / 录音（阶段 5、6 填）──────────────────────────────
    """CREATE TABLE example (
         id              INTEGER PRIMARY KEY AUTOINCREMENT,
         word            TEXT NOT NULL,
         sense_id        INTEGER,         -- → sense.id（例句挂在义项上，不是挂在词上）
         text            TEXT NOT NULL,   -- 意语原句
         bold            TEXT,            -- JSON [[start,end],…]，词形在句中的位置
         ref             TEXT,            -- 文献出处
         src_gloss       TEXT,            -- 源里这条例句挂在哪条义项下（挂回义项的桥）
         src_translation TEXT,            -- 源自带的译文（各版自己的语言，非中文）
         src_lang        TEXT,
         src             TEXT NOT NULL,
         UNIQUE(word, text)
       )""",
    """CREATE TABLE example_gloss (
         example_id INTEGER NOT NULL,
         lang       TEXT NOT NULL,        -- zh / vi …
         text       TEXT NOT NULL,
         src        TEXT,
         PRIMARY KEY(example_id, lang)
       )""",
    """CREATE TABLE collocation (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,       -- → dict.id
         sense_id INTEGER,                -- → sense.id；本轮全 NULL，挂回义项是编纂工作
         text     TEXT NOT NULL,          -- 意语短语原文
         rank     INTEGER NOT NULL,       -- 该词内顺序，保源序
         UNIQUE(word_id, rank)
       )""",
    """CREATE TABLE collocation_gloss (
         collocation_id INTEGER NOT NULL,
         lang           TEXT NOT NULL,
         text           TEXT NOT NULL,
         src            TEXT,
         PRIMARY KEY(collocation_id, lang)
       )""",
    """CREATE TABLE audio (
         id         INTEGER PRIMARY KEY AUTOINCREMENT,
         word       TEXT NOT NULL,
         file       TEXT NOT NULL,        -- Commons 文件名 = 录音身份（去重靠它，不是 URL）
         url_mp3    TEXT,
         url_ogg    TEXT,
         url_wav    TEXT,
         url_other  TEXT,
         ipa        TEXT,                 -- 这条录音对应哪个读音
         speaker    TEXT,
         region     TEXT,
         region_src TEXT,                 -- tag / speaker / filename
         kind       TEXT NOT NULL,        -- human / tts-tool / browser-tts（方针④三级兜底）
         src        TEXT NOT NULL,
         UNIQUE(word, file)
       )""",
]
IDX = [
    "CREATE INDEX idx_sense_word ON sense(word_id)",
    "CREATE INDEX idx_sensesrc_word ON sense_src(word_id)",
    "CREATE INDEX idx_sensesrc_sense ON sense_src(sense_id)",
    "CREATE INDEX idx_glosslang ON sense_gloss(lang)",
    "CREATE INDEX idx_tag_kind ON sense_tag(kind, value)",
    "CREATE INDEX idx_rel_word ON sense_relation(word_id)",
    "CREATE INDEX idx_pron_word ON pronunciation(word_id)",
    "CREATE INDEX idx_ex_word ON example(word)",
    "CREATE INDEX idx_ex_sense ON example(sense_id)",
    "CREATE INDEX idx_col_word ON collocation(word_id)",
    "CREATE INDEX idx_col_sense ON collocation(sense_id)",
    "CREATE INDEX idx_colg_lang ON collocation_gloss(lang)",
    "CREATE INDEX idx_audio_word ON audio(word)",
]

# 中文释义的来源：`translation_src` 整列是空的（0 行），逐条来源**证明不了**。
# 按 [[ipa-provenance-columns]] 的规矩，证明不了就写 unknown，不猜。
ZH_SRC = "unknown"
EN_SRC = "en-edition"       # `definition` 由 build.py 从 kaikki 英文版切片建，可证


def lines(s):
    return [] if s is None or s == "" else s.split("\n")


def split_colloc(ln):
    """→ (意语, 中文|None)。判据 = **第一个汉字之前的最后一个空格**（`SCHEMA` §7.1）。
    不是"第一个汉字处"——那样 `pH 值` / `do maggiore C大调` 这类会切错，
    而跨语言的那个符号本来就属于中文那半。es 上旧判据 99.48%，本判据 100%。"""
    m = CJK.search(ln)
    if not m:
        return ln, None
    i = ln.rfind(" ", 0, m.start())
    if i <= 0:
        return None, ln
    return ln[:i].strip(), ln[i + 1:].strip()


def collect(con):
    """把 dict 的四列拆成新表的行。**只搬不改**：一个字符都不修。"""
    senses, glosses, tags = [], [], []
    cols, colglosses = [], []
    stat = Counter()
    sid = cid = 0

    for did, pos0, d, t, m, infl in con.execute(
            "SELECT id, pos, definition, translation, meta, infl FROM dict ORDER BY id"):
        dl, tl = lines(d), lines(t)
        meta = json.loads(m) if m else []

        if dl:                                        # ① 有英文释义的词条
            stat["有 definition 的词条"] += 1
            for i, en in enumerate(dl):
                sid += 1
                o = meta[i] if i < len(meta) else {}
                senses.append((sid, did, i + 1, o.get("pos") or pos0, o.get("g")))
                glosses.append((sid, "en", "equivalent", 0, en, EN_SRC))
                stat["义项"] += 1
                zh = tl[i] if i < len(tl) else ""
                if zh != "":
                    glosses.append((sid, "zh", "equivalent", 0, zh, ZH_SRC))
                    stat["  有中文"] += 1
                else:
                    stat["  🔴 中文为空"] += 1
                for v in (o.get("lex") or []):
                    tags.append((sid, "register", v))
                for v in (o.get("reg") or []):
                    tags.append((sid, "region", v))
        elif t is not None and t == infl:             # ② 变形层：指针文本，丢弃
            stat["变形行（translation==infl，丢弃）"] += 1
        elif t:                                       # ③ 🔴 无英文释义、但中文是真释义
            stat["🔴 无 definition 却有真中文释义的词条"] += 1
            for i, zh in enumerate(tl):
                sid += 1
                senses.append((sid, did, i + 1, pos0, None))
                if zh != "":
                    glosses.append((sid, "zh", "equivalent", 0, zh, ZH_SRC))
                stat["  义项"] += 1
        else:
            stat["无 definition 也无 translation"] += 1

    for did, raw in con.execute(
            "SELECT id, collocation FROM dict WHERE collocation IS NOT NULL ORDER BY id"):
        rank = 0
        for ln in raw.split("\n"):
            ln = ln.strip()
            if not ln:
                stat["搭配空行（丢）"] += 1
                continue
            it_, zh = split_colloc(ln)
            if it_ is None:
                # 🔴 切不出意语部分的 2 条，是**源数据缺陷**不是判据缺陷：
                #    `AC` → "AC米兰 AC Milan"（中英写反）、`pasticci` → "弄出乱子"（没有意语）。
                #    阶段 0 的边界是"只搬不改"，所以原样搬进 text、不产生中文 gloss
                #    （这样重建仍逐字节一致）。缺陷记账，交阶段 5 搭配层处理。
                stat["🔴 搭配切不出意语（原样搬，记账）"] += 1
                it_, zh = ln, None
            cid += 1
            rank += 1
            cols.append((cid, did, rank, it_))
            stat["搭配"] += 1
            if zh:
                colglosses.append((cid, "zh", zh, "dict-collocation"))
            else:
                stat["  🔴 搭配无中文"] += 1
    return senses, glosses, tags, cols, colglosses, stat


# ════════════════════════ 闸① 可逆性回核 ════════════════════════

def rebuild(con):
    """从新表重建四列 → {列名: {dict.id: 值}}。**不读原列**，否则回核就是自证。"""
    gl = {}
    for sid, lang, text in con.execute(
            "SELECT sense_id, lang, text FROM sense_gloss WHERE kind='equivalent' AND seq=0"):
        gl.setdefault(sid, {})[lang] = text
    ranks = {}
    for sid, wid, rank in con.execute("SELECT id, word_id, rank FROM sense ORDER BY word_id, rank"):
        ranks.setdefault(wid, []).append((rank, sid))
    tg = {}
    for sid, kind, value in con.execute("SELECT sense_id, kind, value FROM sense_tag"):
        tg.setdefault(sid, {}).setdefault(kind, []).append(value)
    pg = {}
    for sid, pos, gender in con.execute("SELECT id, pos, gender FROM sense"):
        pg[sid] = (pos, gender)

    out = {"definition": {}, "translation": {}, "meta": {}}
    for wid, rs in ranks.items():
        rs.sort()
        en = [gl.get(s, {}).get("en") for _, s in rs]
        zh = [gl.get(s, {}).get("zh", "") for _, s in rs]
        if any(x is not None for x in en):                 # 有英文 = 词条层
            out["definition"][wid] = "\n".join(x or "" for x in en)
            out["translation"][wid] = "\n".join(zh)
            meta = []
            for _, s in rs:
                pos, g = pg[s]
                o = {"pos": pos}
                if tg.get(s, {}).get("register"):
                    o["lex"] = sorted(tg[s]["register"])
                if tg.get(s, {}).get("region"):
                    o["reg"] = sorted(tg[s]["region"])
                if g:
                    o["g"] = g
                meta.append(o)
            out["meta"][wid] = meta
        else:                                              # 只有中文的那 22 条
            out["translation"][wid] = "\n".join(zh)

    colgl = dict(con.execute(
        "SELECT collocation_id, text FROM collocation_gloss WHERE lang='zh'"))
    col = {}
    for cid_, wid, rank, text in con.execute(
            "SELECT id, word_id, rank, text FROM collocation ORDER BY word_id, rank"):
        zh = colgl.get(cid_)
        col.setdefault(wid, []).append(text + (" " + zh if zh else ""))
    out["collocation"] = {k: "\n".join(v) for k, v in col.items()}
    return out


def gate1(con, orig, verbose=True):
    """把重建结果与**迁移前的原值**逐字节比对。orig = {列: {id: 原值}}。"""
    print("\n═══ 闸① 可逆性回核（全量，非抽样）═══")
    got = rebuild(con)
    bad = Counter()
    samples = []
    for colname in ("definition", "translation", "meta", "collocation"):
        o, g = orig[colname], got.get(colname, {})
        keys = set(o) | set(g)
        for k in keys:
            a, b = o.get(k), g.get(k)
            if colname == "meta":
                a = json.loads(a) if a else None
                # 原 meta 的数组元素键序不保证，比对解析后的值
                if a is not None:
                    a = [{kk: (sorted(vv) if isinstance(vv, list) else vv)
                          for kk, vv in e.items()} for e in a]
            if a != b:
                bad[colname] += 1
                if len(samples) < 8:
                    samples.append((colname, k, repr(a)[:90], repr(b)[:90]))
    for colname in ("definition", "translation", "meta", "collocation"):
        n = bad[colname]
        print("   %-12s %s" % (colname, "✓ 逐行一致" if n == 0 else "🔴 %d 行对不上" % n))
    for s in samples:
        print("   🔴 %s id=%s\n      原: %s\n      建: %s" % s)
    return sum(bad.values()) == 0


def gate2(con, expect, verbose=True):
    """不变量断言。expect 是**迁移前先算出来的期望值**，不是事后照抄结果。"""
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("sense 条数 == 期望", q("SELECT count(*) FROM sense"), expect["sense"]),
        ("sense_gloss en == 期望", q("SELECT count(*) FROM sense_gloss WHERE lang='en'"),
         expect["gloss_en"]),
        ("sense_gloss zh == 期望", q("SELECT count(*) FROM sense_gloss WHERE lang='zh'"),
         expect["gloss_zh"]),
        ("sense_tag == 期望", q("SELECT count(*) FROM sense_tag"), expect["tag"]),
        ("collocation == 期望", q("SELECT count(*) FROM collocation"), expect["colloc"]),
        ("孤儿 sense（word_id 不在 dict）",
         q("SELECT count(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id WHERE d.id IS NULL"), 0),
        ("孤儿 sense_gloss",
         q("SELECT count(*) FROM sense_gloss g LEFT JOIN sense s ON s.id=g.sense_id "
           "WHERE s.id IS NULL"), 0),
        ("孤儿 sense_tag",
         q("SELECT count(*) FROM sense_tag t LEFT JOIN sense s ON s.id=t.sense_id "
           "WHERE s.id IS NULL"), 0),
        ("孤儿 collocation_gloss",
         q("SELECT count(*) FROM collocation_gloss g LEFT JOIN collocation c ON c.id=g.collocation_id "
           "WHERE c.id IS NULL"), 0),
        ("没有任何 gloss 的 sense",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_gloss g ON g.sense_id=s.id "
           "WHERE g.sense_id IS NULL"), 0),
        ("rank 不从 1 连续的词",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-34s %10s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    return ok


def snapshot_orig(con):
    """迁移前把四列原值全读进内存（约 150 MB 字符串，够用）。"""
    orig = {c: {} for c in ("definition", "translation", "meta", "collocation")}
    for rid, d, t, m, c in con.execute(
            "SELECT id, definition, translation, meta, collocation FROM dict"):
        if d is not None:
            orig["definition"][rid] = d
        if m is not None:
            orig["meta"][rid] = m
        if c is not None:
            orig["collocation"][rid] = c
        # 🔴 translation 只回核**没被丢弃**的那部分：指针文本按设计丢弃，
        #    它的可逆性由 `infl` 列保证（迁移前已全量核对：432,490 行逐字节相同）。
        if t is not None:
            orig["translation"][rid] = t
    return orig


def drop_pointer_translations(con, orig):
    """把按设计丢弃的指针文本从回核集合里剔除，并**当场证明它可以从 infl 重建**。"""
    n_ok = n_bad = 0
    for rid, t, infl in con.execute(
            "SELECT id, translation, infl FROM dict WHERE definition IS NULL"):
        if t is not None and t == infl:
            orig["translation"].pop(rid, None)
            n_ok += 1
        elif t is not None:
            n_bad += 1                       # 那 22 条真释义，留在回核集合里
    print("   指针文本 %s 行（可由 infl 逐字节重建，剔出回核集）；"
          "非指针的无释义行 %s 条（留在回核集内）" % (f"{n_ok:,}", f"{n_bad:,}"))
    return orig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="建表并写入")
    ap.add_argument("--verify", action="store_true", help="只对已落库结果跑闸")
    ap.add_argument("--mutate", action="store_true", help="变异验证：闸必须报出人为破坏")
    ap.add_argument("--drop-cols", action="store_true", help="闸①通过后把 dict 降列")
    a = ap.parse_args()

    if a.drop_cols:
        return drop_cols()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    if a.verify or a.mutate:
        if "sense" not in have:
            sys.exit("🔴 新表还没建，先跑 --apply")
        orig = snapshot_orig(con)
        con.close()
        # 回核要读**迁移前**的原列；降列之后这些列就没了，那时改用备份库比对。
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        cols = {r[1] for r in con.execute("PRAGMA table_info(dict)")}
        if "definition" not in cols:
            sys.exit("🔴 dict 已降列，原列不在了：回核请对着 backups/ 里的 keep-v2-schema 备份跑")
        orig = drop_pointer_translations(con, orig)
        if a.mutate:
            return mutate(con, orig)
        ok1 = gate1(con, orig)
        senses, glosses, tags, cols_, colgl, stat = collect(con)
        ok2 = gate2(con, expected(stat, senses, glosses, tags, cols_))
        print("\n%s" % ("✓ 两道闸全过" if ok1 and ok2 else "🔴 有闸未通过"))
        return 0 if (ok1 and ok2) else 1

    print("■ 试算（只读）")
    senses, glosses, tags, cols_, colgl, stat = collect(con)
    for k, v in stat.items():
        print("   %-40s %10s" % (k, f"{v:,}"))
    print("\n   %-40s %10s" % ("→ sense 行", f"{len(senses):,}"))
    print("   %-40s %10s" % ("→ sense_gloss 行", f"{len(glosses):,}"))
    print("   %-40s %10s" % ("→ sense_tag 行", f"{len(tags):,}"))
    print("   %-40s %10s" % ("→ collocation 行", f"{len(cols_):,}"))
    print("   %-40s %10s" % ("→ collocation_gloss 行", f"{len(colgl):,}"))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    orig = snapshot_orig(con)
    orig = drop_pointer_translations(con, orig)
    con.close()

    # 出版层各表的**行数增量**要显式声明（重跑时是从已有行数算差），
    # 否则 dbtool 会以"动到了不该动的表"拦下来 —— 这正是它该拦的。
    now = dbtool.snapshot()
    expect = {"#sense": len(senses) - now.get("#sense", 0),
              "#sense_gloss": len(glosses) - now.get("#sense_gloss", 0),
              "#sense_tag": len(tags) - now.get("#sense_tag", 0),
              "#collocation": len(cols_) - now.get("#collocation", 0),
              "#collocation_gloss": len(colgl) - now.get("#collocation_gloss", 0)}
    # 🔴 tag 带 keep：结构大改的备份永不被保留策略淘汰
    with dbtool.session("keep-v2-schema", expect=expect) as s:
        for t in NEW_TABLES:
            s.execute("DROP TABLE IF EXISTS %s" % t)
        for sql in DDL:
            s.execute(sql)
        for sql in IDX:
            s.execute(sql)
        s.executemany("INSERT INTO sense (id,word_id,rank,pos,gender) VALUES (?,?,?,?,?)", senses)
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,?,?,?,?,?)", glosses)
        s.executemany("INSERT INTO sense_tag (sense_id,kind,value) VALUES (?,?,?)", tags)
        s.executemany("INSERT INTO collocation (id,word_id,rank,text) VALUES (?,?,?,?)", cols_)
        s.executemany("INSERT INTO collocation_gloss (collocation_id,lang,text,src) "
                      "VALUES (?,?,?,?)", colgl)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok1 = gate1(con, orig)
    ok2 = gate2(con, expected(stat, senses, glosses, tags, cols_))
    print("\n%s" % ("✓ 两道闸全过 —— 可以跑 --drop-cols 降列了"
                    if ok1 and ok2 else "🔴 有闸未通过，先别降列"))
    return 0 if (ok1 and ok2) else 1


def expected(stat, senses, glosses, tags, cols_):
    """期望值来自**源列的统计**，不是查新表得来的（否则就是自证）。"""
    return {
        "sense": stat["义项"] + stat["  义项"],
        "gloss_en": stat["义项"],
        "gloss_zh": stat["义项"] - stat["  🔴 中文为空"] + stat["  义项"],
        "tag": len(tags),
        "colloc": stat["搭配"],
    }


def mutate(con, orig):
    """🔴 变异验证：在**内存副本**上人为破坏 5 处，闸必须全部报出来。

    `IT_PLAN` 阶段 0 判据 5：打乱 3 条映射 + 改坏 2 条搬运结果，五条必须全被报出。
    一条永远通过的检查等于没检查。
    """
    print("\n═══ 变异验证（不写库，只破坏内存里的重建结果）═══")
    base = rebuild(con)
    ids = sorted(base["definition"])[:5]
    cases = []

    def broke(name, mutator):
        got = {k: dict(v) for k, v in base.items()}
        mutator(got)
        bad = 0
        for colname in ("definition", "translation", "meta", "collocation"):
            o, g = orig[colname], got.get(colname, {})
            for k in set(o) | set(g):
                a, b = o.get(k), g.get(k)
                if colname == "meta":
                    a = json.loads(a) if a else None
                    if a is not None:
                        a = [{kk: (sorted(vv) if isinstance(vv, list) else vv)
                              for kk, vv in e.items()} for e in a]
                if a != b:
                    bad += 1
        cases.append((name, bad > 0))
        print("   %s  %-40s 闸%s" % ("✓" if bad else "🔴", name, "报出 %d 行" % bad if bad else "没报"))

    # ①②③ 打乱三条"义项↔释义"映射（把中文行首尾对调 = 错配）
    for i in ids[:3]:
        def m(g, i=i):
            ls = g["translation"][i].split("\n")
            if len(ls) > 1:
                g["translation"][i] = "\n".join(ls[::-1])
            else:
                g["translation"][i] = ls[0] + "X"
        broke("打乱映射：id=%d 的中文行倒序" % i, m)
    # ④ 改坏一条搬运结果（英文释义少一个字符）
    broke("搬运改坏：id=%d 的英文释义截断" % ids[3],
          lambda g: g["definition"].__setitem__(ids[3], g["definition"][ids[3]][:-1]))
    # ⑤ 丢一条 meta 标签
    victim = next(i for i in base["meta"] if any("lex" in e for e in base["meta"][i]))
    def drop_tag(g):
        g["meta"][victim] = [{k: v for k, v in e.items() if k != "lex"} for e in g["meta"][victim]]
    broke("搬运改坏：id=%d 的 meta 丢掉 lex 标签" % victim, drop_tag)

    ok = all(x for _, x in cases)
    print("\n%s" % ("✓ 五条变异全部被闸①逮到" if ok else "🔴 有变异没被逮到 —— 闸是瞎的"))
    return 0 if ok else 1


def drop_cols():
    """闸①通过后，把 dict 从 26 列降到 19 列。`SCHEMA` §3。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    cols = [r[1] for r in con.execute("PRAGMA table_info(dict)")]
    todo = [c for c in MOVED + DEAD if c in cols]
    if not todo:
        print("已经降过列了，dict 现有 %d 列" % len(cols))
        return 0
    snap = dbtool.snapshot()
    print("■ 将删除 %d 列：%s" % (len(todo), "、".join(todo)))
    print("   dict %d 列 → %d 列" % (len(cols), len(cols) - len(todo)))
    con.close()
    # 每个被删的列，非空计数从 N 掉到 0 —— 必须逐列显式声明，闸门才拦得住删错列
    expect = {c: -snap[c] for c in todo if c in snap}
    with dbtool.session("keep-v2-dropcols", expect=expect) as s:
        for c in todo:
            s.execute("ALTER TABLE dict DROP COLUMN %s" % c)
    print("✓ 降列完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
