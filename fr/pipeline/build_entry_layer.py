#!/usr/bin/env python3
"""阶段 1：建 `entry` 词条层与 `sense_src` 证据层，把每条义项锚回 dump。2026-08-22。

设计见 `docs/SCHEMA.md` §10，计划见 `docs/FR_PLAN.md` 阶段 1。
**一次计算产出两样东西**，因为它们本来就是同一件事：

    复刻 build.py 生成 `definition` 的循环
      → 每一行义项来自哪个 entry（entry 层）
      → 每一行义项在 dump 里的原文与坐标（sense_src 证据层）

═══ 复刻的是哪条规则（读自 `fr/pipeline/build.py:380-490`）═══
遍历 `lang_code=='fr'` 的 dump entry（文件顺序）→ 每个 entry 的 senses（顺序）→
  · `fo = form_of or alt_of`，且该词非词缀 ⇒ 当作变形指针，进 `infl`，**不算义项**
  · 否则取 `glosses[0]`、`\\s+` 归一为单空格、strip ⇒ 一行义项
  · **按 `word.lower()` 去重**：同一折叠词形内文字完全相同的义项只留第一条
⇒ 给定同一份 dump，输出逐字节可复现。

═══ 🔴 fr 与 it 的五处不同 —— 逐条量过，不是照搬 ═══

① **`is_affix` 是四值不是六值**：`fr/build.py:403` 用 `{suffix, prefix, infix, interfix}`，
   而 `it/build_entry_layer.py` 的 `AFFIX_POS` 有六个（多 circumfix / combining_form）。
   照搬六值会让复刻与建库当年的行为不一致，闸①直接红。

② 🔴 **主键必须用原始词性，不能用 `POS_MAP` 映射后的**：
   `POS_MAP` 把 `phrase` 和 `prep_phrase` 都映射成 `phr`。实测碰撞 **1 组**（`de rien`，
   同时有 phrase 和 prep_phrase 两条词条）。一组也足够毁掉 UNIQUE 约束。
   ⇒ `src_ref` 与 seq 分配都用 `pos_raw`；`entry.pos` 存映射后的值供展示。

③ **词形里没有一个含冒号**（实测 0 个）⇒ `src_ref` 的冒号分隔安全。

④ **重复键 1,024 组，音标与词源文本 100% 相同 ⇒ 全部可合并，`seq` 恒为 0。**
   （it 那轮 1,813 组里有 2 组不同、需要 seq 区分。fr 一组都没有，但断言照留 ——
   换一份 dump 就可能有。）

⑤ 🔴 **`build.py` 用 `key = word.lower()` 折叠了大小写**（`build.py:388`）。
   dump 里 388,992 个法语词形被压成 385,216 行 —— **吃掉 3,776 个词形**，
   其中 **3,451 族两边词性还不同**（`Abbasside` 名词 / `abbasside` 形容词并成一行，
   `A` character / `a` character+noun+pron+verb）。
   本脚本**必须复刻这条折叠**，否则闸①会在几千个词形上报警。
   ⭐ 而 `entry.word_src` 保留 dump 的**真实大小写** —— 这正是阶段 3 拆分专名的凭据，
      也是 `entry` 层对 fr 的价值大于对 it 的地方（es 上同一族缺陷已修 pos 3,558 行）。

═══ 🔴 本步会量出、但**不在本步修**的缺陷 ═══
`build.py:464` 写的是 `fo = s.get("form_of") or s.get("alt_of")` ——
**把 `alt_of` 和 `form_of` 一起当变形丢了**。可 `alt_of` 是异体/缩写/误拼
（`&`→`et`、`1er`→`premier`、`'tain`→`putain`），它们是**独立词条、有自己的释义**。
实测代价：**5,011 条义项被丢**，**4,141 个词形因此一条释义都没有**。
（it 上同一缺陷 7,028 个词形，es 上 5,701 个 —— **三门语言全中**。）
⚠️ 本步的任务是**忠实复刻当年的行为**，好让闸①能逐字节回核。修复归阶段 2。
   本脚本把这批义项**照样写进 `sense_src` 证据层**（`src_kind='alt_of'`），
   阶段 2 直接从证据层捞，不用再扫一遍 dump。

═══ 三道闸 ═══
① **可逆性回核**：复刻算出的义项序列，必须与库里已有的 `sense`+`sense_gloss(en)`
   **逐词、逐序、逐字节**相同（100%，非抽样）。对不上一条就中止 ——
   这同时证明了"锚对了"和"阶段 0 没搬错"。
② 不变量断言：每条 en 侧 sense 恰好一条 sense_src / entry 无孤儿 / src_ref 无重复 /
   `word_src` 折叠后必须等于 `dict.word` 折叠后。
③ 抽样：确定性复刻，无判断成分，不适用。

用法（在 fr/ 目录下）：
    python3 pipeline/build_entry_layer.py            # 试算 + 闸①，不写库
    python3 pipeline/build_entry_layer.py --apply    # 建表并写入
    python3 pipeline/build_entry_layer.py --mutate   # 变异验证：闸必须报出人为破坏
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SRC = "en-edition"

# 🔴 与 `fr/pipeline/build.py:403` 逐字一致的四值。**不要改成 it 的六值。**
AFFIX_POS = {"suffix", "prefix", "infix", "interfix"}

# 与 `fr/pipeline/build.py:46` 的 POS_MAP 一致；只用于 `entry.pos` 展示值，不参与主键
POS_MAP = {
    "noun": "n", "verb": "v", "adj": "adj", "adv": "adv", "pron": "pron",
    "prep": "prep", "conj": "conj", "det": "det", "num": "num", "intj": "intj",
    "name": "name", "prefix": "pref", "suffix": "suf", "phrase": "phr",
    "prep_phrase": "phr", "proverb": "prov", "article": "art",
    "contraction": "contr", "particle": "part", "character": "char",
    "symbol": "sym",
}

DDL_ENTRY = """CREATE TABLE entry (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  word_id  INTEGER NOT NULL,        -- → dict.id（折叠后的词形，仍是搜索与身份单位）
  word_src TEXT NOT NULL,           -- 🔴 dump 里的**真实大小写**；dict 折叠掉了 3,776 个词形
  pos      TEXT NOT NULL,           -- POS_MAP 映射后的展示值
  pos_raw  TEXT NOT NULL,           -- dump 原始词性；phrase/prep_phrase 都映射成 phr，主键必须用它
  etym_no  TEXT NOT NULL,           -- 词源号；源头可能是 "1.1" 这种串，没编号记 "0"
  seq      INTEGER NOT NULL,        -- 同键内序号，正常 0（音标或词源不同才 >0）
  aux      TEXT,                    -- 法语一等字段，本步只建列不填（见 FR_PLAN §五-4）
  vgroup   TEXT,
  pp       TEXT,
  gender   TEXT,
  src      TEXT NOT NULL,           -- 🔴 照 it 不照 es：行级来源，全收之后分不清就再也分不清了
  src_ref  TEXT NOT NULL,           -- kk-en:<word_src>:<pos_raw>:<etym_no>:<seq>  内容派生、稳定
  UNIQUE(src_ref)
)"""
IDX_ENTRY = [
    "CREATE INDEX idx_entry_word ON entry(word_id)",
    "CREATE INDEX idx_entry_wordsrc ON entry(word_src)",
]


def norm_gloss(s):
    return re.sub(r"\s+", " ", s).strip()


def replay(dump_path, words):
    """复刻 build.py 的循环。
    → per_word[折叠词形] = [(gloss, entkey, occ, sense_idx, tags, raw_tags), …]
      entries[entkey] = {...}
      alt_lost[折叠词形] = [(gloss, entkey, occ, sense_idx, tags, raw_tags, alt_targets), …]
    只处理库里存在的折叠词形。"""
    per_word = defaultdict(list)
    alt_lost = defaultdict(list)
    entries = {}
    dup_groups = defaultdict(list)
    stat = Counter()
    seen = defaultdict(set)        # 折叠词形 → 已出现过的 gloss（复刻按词形去重）
    occ_of = Counter()             # (word_src,pos_raw,etym) → 该键已出现过几条 JSON entry
    # 🔴 dump 内的全局次序。阶段 2a 要把 alt_of 义项**按原位**插回去（不是追加到末尾），
    #    而 per_word / alt_lost 是两个字典，交错顺序在里面丢了。
    #    ordinal 单调递增 ⇒ 两边合并后按它排序就能还原 dump 顺序。
    ordinal = 0

    with open(dump_path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                stat["坏行"] += 1
                continue
            if e.get("lang_code") != "fr":
                continue
            w0 = (e.get("word") or "").strip()
            if not w0:
                continue
            # 🔴 复刻 build.py:388 的 `key = word.lower()`
            w = w0.lower()
            if w not in words:
                stat["🔴 dump 有、库里没有的折叠词形"] += 1
                continue
            if w0 != w:
                stat["大小写被折叠的 entry（阶段 3 要拆）"] += 1

            pos_raw = e.get("pos") or ""
            # ⚠️ 词源号**不是整数**：源头可能有 "1.1" 这种值，按原样当字符串用
            etym = str(e.get("etymology_number") or 0)
            key0 = (w0, pos_raw, etym)
            ipas = frozenset(s["ipa"] for s in (e.get("sounds") or []) if s.get("ipa"))
            etext = (e.get("etymology_text") or "")[:200]
            dup_groups[key0].append((ipas, etext))
            # 🔴 同一个键可能对应多条 JSON entry（wiktextract 把一个维基章节切开了，
            #    fr 实测 1,024 组）。它们合并成一个 entry，但**义项下标各自从 0 开始** ——
            #    只用 <下标> 做 src_ref 会撞 UNIQUE。加一个 dump 内的出现序号 occ。
            #    occ 是**冻结的外部文件里的坐标**，不是库内行序引用，不违反 §2.0.1。
            occ = occ_of[key0]
            occ_of[key0] += 1
            stat["dump entry"] += 1

            # 🔴 每个 dump entry 都建行，**不管它有没有产出义项** ——
            #    纯 form_of 的 entry 也带读音，只给"有义项的 entry"建行，读音就没地方挂。
            # 🔴 键里必须带 ipas：只用 key0 的话，`setdefault` 会让同键的第二条 JSON
            #    复用第一条的音标集，而 `assign_seq` 恰恰是**按音标集**拆 seq 的。
            ent = entries.setdefault(
                (key0, ipas),
                {"pos_raw": pos_raw, "etym": etym, "ipas": ipas, "etext": etext,
                 "word_src": w0, "word_fold": w, "n_visible": 0, "n_hidden": 0,
                 "n_formof": 0, "n_altof": 0})
            is_affix = pos_raw in AFFIX_POS

            for i, s in enumerate(e.get("senses") or []):
                fo, ao = s.get("form_of"), s.get("alt_of")
                g = norm_gloss((s.get("glosses") or [""])[0])
                ordinal += 1
                item = (g, (key0, ipas), occ, i, s.get("tags") or [],
                        s.get("raw_tags") or [], ordinal)
                # ── 复刻 build.py:464-465：form_of **或** alt_of，且非词缀 ⇒ 丢
                if (fo or ao) and not is_affix:
                    if fo:
                        stat["变形指针义项（form_of，不算义项）"] += 1
                        ent["n_formof"] += 1
                    else:
                        # 🔴 这一支是**缺陷**不是设计：alt_of 是异体/缩写，有自己的释义。
                        #    忠实复刻（照丢），但把证据留进 sense_src 供阶段 2 修。
                        stat["🔴 alt_of 义项（被当变形丢了，阶段 2 修）"] += 1
                        ent["n_altof"] += 1
                        if g:
                            alt_lost[w].append(item + (
                                [a.get("word") for a in (ao or [])],))
                    continue
                if not g:
                    stat["空 gloss（跳过）"] += 1
                    continue
                if g in seen[w]:
                    stat["🔴 按折叠词形去重被吃掉的义项"] += 1
                    ent["n_hidden"] += 1
                    continue
                seen[w].add(g)
                ent["n_visible"] += 1
                per_word[w].append(item)
                stat["义项"] += 1
    return per_word, alt_lost, entries, dup_groups, stat


def assign_seq(dup_groups, verbose=True):
    """同 (词形,原始词性,词源号) 的多条 JSON：音标与词源文本都相同才合并成一个 entry。
    → {(key0, ipas): seq}。fr 实测 1,024 组全部可合并、seq 恒为 0，
    但断言照留 —— 换一份 dump 就可能不是。"""
    seq_of = {}
    stat = Counter()
    for k, lst in dup_groups.items():
        if len(lst) == 1:
            seq_of[(k, lst[0][0])] = 0
            continue
        ipas = {x[0] for x in lst}
        ets = {x[1] for x in lst}
        if len(ipas) == 1 and len(ets) == 1:
            stat["重复键·可安全合并"] += 1
            seq_of[(k, lst[0][0])] = 0
        else:
            stat["🔴 重复键·音标或词源不同，用 seq 分开"] += 1
            for n, ip in enumerate(sorted(ipas, key=lambda s: sorted(s))):
                seq_of[(k, ip)] = n
    if verbose and stat:
        for k, v in stat.items():
            print("   %-40s %8s" % (k, f"{v:,}"))
    return seq_of


def ref_of(key0, seq):
    return "kk-en:%s:%s:%s:%d" % (key0[0], key0[1], key0[2], seq)


# ════════════════════════ 闸① 复刻回核 ════════════════════════

def db_sequences(con):
    """库里每个词形的英文义项序列（按 rank）。"""
    have = defaultdict(list)
    for w, text in con.execute(
            "SELECT d.word, g.text FROM sense s "
            "JOIN dict d ON d.id = s.word_id "
            "JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='en' AND g.kind='equivalent' "
            "ORDER BY s.word_id, s.rank"):
        have[w.lower()].append(text)
    return have


def gate1(con, per_word, show=6):
    """闸① 复刻结果 vs 库里已有的义项序列，逐词逐序逐字节比对（100%，非抽样）。"""
    print("\n═══ 闸① 复刻回核（全量，非抽样）═══")
    have = db_sequences(con)
    got = {w: [x[0] for x in items] for w, items in per_word.items()}
    keys = set(have) | set(got)
    bad = [w for w in keys if have.get(w, []) != got.get(w, [])]
    print("   库里有英文义项的词形 %s；复刻出的词形 %s"
          % (f"{len(have):,}", f"{len(got):,}"))
    print("   %s 对不上的词形 %s" % ("✓" if not bad else "🔴", f"{len(bad):,}"))
    for w in sorted(bad)[:show]:
        a, b = have.get(w, []), got.get(w, [])
        print("   🔴 %-20s 库 %d 条 %s\n        复刻 %d 条 %s"
              % (w, len(a), a[:3], len(b), b[:3]))
    return not bad


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("entry 条数 == 期望", q("SELECT count(*) FROM entry"), expect["entry"]),
        ("sense_src(en-edition) == 期望",
         q("SELECT count(*) FROM sense_src WHERE src='en-edition'"), expect["sense_src"]),
        # 🔴 2026-08-22：这条原来写成 `raw_tags LIKE '%\"__alt_of__\"%'`。
        #    **`_` 在 SQL LIKE 里是通配符**，而键名 `__alt_of__` 全是下划线 ——
        #    去掉引号的写法 `LIKE '%__alt_of__%'` 对同一批数据数出 5,046 而非 5,011。
        #    带引号那版碰巧精确，但那是运气不是判据。⇒ 改成 JSON 解析，判据不含通配符。
        ("其中 alt_of 证据 == 期望",
         sum(1 for (r,) in con.execute(
             "SELECT raw_tags FROM sense_src WHERE src='en-edition' AND raw_tags IS NOT NULL")
             if "__alt_of__" in json.loads(r)),
         expect["alt_src"]),
        ("孤儿 entry（word_id 不在 dict）",
         q("SELECT count(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id WHERE d.id IS NULL"), 0),
        ("孤儿 sense_src（word_id 不在 dict）",
         q("SELECT count(*) FROM sense_src s LEFT JOIN dict d ON d.id=s.word_id "
           "WHERE d.id IS NULL"), 0),
        # 🔴 2026-08-22：这条断言第一版写成 SQL 的 `lower(e.word_src) <> lower(d.word)`，
        #    报出 113 行红 —— **红的是断言不是数据**。
        #    SQLite 内置的 `lower()`/`upper()` **只处理 ASCII**：`lower('École')` 原样返回，
        #    而 `build.py` 折叠用的是 Python 的 `str.lower()`（走 Unicode）。
        #    那 113 行全是带重音符的大写词（`À` `Ç` `Œ` `Écosse` `Érythrée`），
        #    Python 侧比对 0 行不一致。⇒ 断言必须用**与建库同一套折叠**。
        #    ⚠️ 同源陷阱：`COLLATE NOCASE` 在 SQLite 里同样是 ASCII-only
        #       （`[[query-perf-collation-traps]]`），阶段 8 的搜索路径要当心。
        ("🔴 word_src 折叠后 != dict.word（Python 折叠）",
         sum(1 for a, b in con.execute(
             "SELECT e.word_src, d.word FROM entry e JOIN dict d ON d.id=e.word_id")
             if a.lower() != b.lower()), 0),
        ("有英文义项却没挂上 entry 的 sense",
         q("SELECT count(*) FROM sense s "
           "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' "
           "WHERE s.entry_id IS NULL"), 0),
        ("挂到不存在 entry 上的 sense",
         q("SELECT count(*) FROM sense s LEFT JOIN entry e ON e.id=s.entry_id "
           "WHERE s.entry_id IS NOT NULL AND e.id IS NULL"), 0),
        # 🔴 阶段 0 那 58 条「无英文、只有中文」的义项按设计没有 dump 锚点，
        #    必须**正好是 58 条**没有 sense_src —— 不是"允许有一些"。
        ("无 sense_src 的 sense == 58（阶段 0 的中文孤儿）",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_src x ON x.sense_id=s.id "
           "WHERE x.sense_id IS NULL"), 58),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-42s %10s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    return ok


def mutate(con, per_word):
    """🔴 变异验证：破坏 5 处复刻结果，闸①必须全部报出。一次一个，每次从干净副本重来。"""
    print("\n═══ 变异验证（不写库，只破坏内存里的复刻结果）═══")
    base = {w: list(v) for w, v in per_word.items()}
    have = db_sequences(con)
    multi = [w for w in base if len(base[w]) > 1][:3]
    solo = [w for w in base if len(base[w]) == 1][:2]
    cases = []

    def broke(name, mutator):
        got = {w: list(v) for w, v in base.items()}     # 每次从干净副本重来
        mutator(got)
        seqs = {w: [x[0] for x in items] for w, items in got.items()}
        n = sum(1 for w in set(have) | set(seqs) if have.get(w, []) != seqs.get(w, []))
        cases.append(n > 0)
        print("   %s  %-44s 闸%s" % ("✓" if n else "🔴", name,
                                     "报出 %d 个词形" % n if n else "没报"))

    for w in multi:
        broke("义项顺序颠倒：%s" % w,
              lambda g, w=w: g.__setitem__(w, list(reversed(g[w]))))
    broke("整条义项丢失：%s" % solo[0], lambda g: g.pop(solo[0]))
    broke("义项文字改一个字符：%s" % solo[1],
          lambda g: g.__setitem__(solo[1], [(g[solo[1]][0][0] + "X",) + g[solo[1]][0][1:]]))
    ok = all(cases)
    print("\n%s" % ("✓ 五条变异全部被闸①逮到" if ok else "🔴 有变异没被逮到 —— 闸是瞎的"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
    fold = {w.lower(): i for w, i in words.items()}
    print("■ 库内词形 %s（折叠键 %s）" % (f"{len(words):,}", f"{len(fold):,}"))

    print("■ 复刻 build.py 的义项循环…")
    per_word, alt_lost, entries, dup_groups, stat = replay(paths.KK, fold)
    for k, v in stat.items():
        print("   %-44s %10s" % (k, f"{v:,}"))
    seq_of = assign_seq(dup_groups)

    n_alt = sum(len(v) for v in alt_lost.values())
    print("\n   %-44s %10s" % ("→ entry 行（合并后）", f"{len({(ref_of(k[0], seq_of.get(k, 0))) for k in entries}):,}"))
    print("   %-44s %10s" % ("→ sense_src 行（可见义项）", f"{sum(len(v) for v in per_word.values()):,}"))
    print("   %-44s %10s" % ("→ sense_src 行（alt_of 证据，阶段 2 用）", f"{n_alt:,}"))
    print("   %-44s %10s" % ("🔴 因 alt_of 被丢而零释义的词形",
                             f"{len(set(alt_lost) - set(per_word)):,}"))

    if a.mutate:
        return mutate(con, per_word)
    ok1 = gate1(con, per_word)
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0 if ok1 else 1
    if not ok1:
        print("\n🔴 闸①未过，中止 —— 锚没对上就不写库")
        return 1

    # ── 组装行 ──────────────────────────────────────────────────────
    ent_rows, ent_id = {}, {}
    for k in entries:
        key0, ipas = k
        seq = seq_of.get(k, 0)
        r = ref_of(key0, seq)
        if r in ent_rows:
            continue
        e = entries[k]
        ent_rows[r] = (fold[e["word_fold"]], e["word_src"],
                       POS_MAP.get(e["pos_raw"], e["pos_raw"]), e["pos_raw"],
                       e["etym"], seq, SRC, r)

    # sense_id：库里每个折叠词形的 en 义项按 rank 排 —— 与复刻序列一一对应（闸①已证）
    sids = defaultdict(list)
    for sid, w in con.execute(
            "SELECT s.id, d.word FROM sense s JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' AND g.kind='equivalent' "
            "ORDER BY s.word_id, s.rank"):
        sids[w.lower()].append(sid)

    src_rows, link = [], []
    for w, items in per_word.items():
        for n, (g, k, occ, i, tags, raw, _ord) in enumerate(items):
            key0 = k[0]
            r = "kk-en:%s:%s:%s:%d#%d" % (key0[0], key0[1], key0[2], occ, i)
            sid = sids[w][n]
            src_rows.append((fold[w], sid, SRC, r, "en", g,
                             json.dumps({"tags": tags, "raw_tags": raw}, ensure_ascii=False)))
            link.append((ref_of(key0, seq_of.get(k, 0)), sid))
    for w, items in alt_lost.items():
        for (g, k, occ, i, tags, raw, _ord, targets) in items:
            key0 = k[0]
            r = "kk-en:%s:%s:%s:%d#%d" % (key0[0], key0[1], key0[2], occ, i)
            src_rows.append((fold[w], None, SRC, r, "en", g,
                             json.dumps({"tags": tags, "raw_tags": raw,
                                         "__alt_of__": targets}, ensure_ascii=False)))

    now = dbtool.snapshot()
    expect = {"#entry": len(ent_rows) - now.get("#entry", 0),
              "#sense_src": len(src_rows) - now.get("#sense_src", 0)}
    with dbtool.session("keep-v3-entry", expect=expect) as s:
        s.execute("DROP TABLE IF EXISTS entry")
        s.execute(DDL_ENTRY)
        for q in IDX_ENTRY:
            s.execute(q)
        for col, decl in (("entry_id", "INTEGER"), ("hidden", "INTEGER NOT NULL DEFAULT 0")):
            if col not in {r[1] for r in s.execute("PRAGMA table_info(sense)")}:
                s.execute("ALTER TABLE sense ADD COLUMN %s %s" % (col, decl))
        s.execute("CREATE INDEX IF NOT EXISTS idx_sense_entry ON sense(entry_id)")
        s.execute("DELETE FROM sense_src")
        s.executemany(
            "INSERT INTO entry (word_id,word_src,pos,pos_raw,etym_no,seq,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?)", list(ent_rows.values()))
        s.executemany(
            "INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags) "
            "VALUES (?,?,?,?,?,?,?)", src_rows)
        eid = dict(s.execute("SELECT src_ref, id FROM entry"))
        s.executemany("UPDATE sense SET entry_id=? WHERE id=?",
                      [(eid[r], sid) for r, sid in link])

    con.close()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok2 = gate2(con, {"entry": len(ent_rows),
                      "sense_src": len(src_rows), "alt_src": n_alt})
    print("\n%s" % ("✓ 两道闸全过" if ok2 else "🔴 有闸未通过"))
    return 0 if ok2 else 1


if __name__ == "__main__":
    sys.exit(main())
