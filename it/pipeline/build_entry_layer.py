#!/usr/bin/env python3
"""阶段 1 + v3：建 `entry` 层与 `sense_src` 证据层，把每条义项锚回 dump。2026-08-13。

设计见 `docs/SCHEMA.md` §10。**一次计算产出两样东西**，因为它们本来就是同一件事：

    复刻 build.py 生成 `definition` 的循环
      → 每一行义项来自哪个 entry（entry 层）
      → 每一行义项在 dump 里的原文与坐标（sense_src 证据层）

═══ 复刻的是哪条规则（读自已冻结的 build.py:387-416）═══
遍历该词形的所有 dump entry（文件顺序）→ 每个 entry 的 senses（顺序）→
  · 有 `form_of`/`alt_of` 且该词非词缀 ⇒ 变形指针，进 `infl`，不算义项
  · 否则取 `glosses[0]`、`\\s+` 归一为单空格、strip ⇒ 一行义项
  · **按词形去重**：同一词形内文字完全相同的义项只留第一条
按 dump 顺序追加。⇒ 给定同一份 dump，输出逐字节可复现。

🔴 去重规则有个必须记账的副作用：`accettano` 的两个 entry
（atˈtʃɛttano / atˈtʃettano，是两个不同的动词）释义文字完全相同，
去重后只剩一行 —— **第二个 entry 连同它的读音整个不可见**。本脚本会数出这类有多少。

═══ entry 的主键 ═══
`src_ref = kk-en:<词形>:<词性>:<词源号>:<seq>` —— **内容派生、稳定**，不是行序
（§2.0.1 的教训：行号不是契约，主键才是）。
wiktextract 会把同一维基章节切成多条 JSON（`banana` 果实/颜色），实测 1,813 组重复键里
1,811 组的音标与词源文本完全相同 ⇒ 合并为一个 entry，**合并前逐组断言**，
不同的（实测 2 组）用 `seq=1` 分开。

═══ 三道闸 ═══
① **可逆性回核**：复刻算出的义项序列，必须与库里已有的 `sense`+`sense_gloss(en)`
   **逐词、逐序、逐字节**相同（100%，非抽样）。对不上一条就中止 ——
   这同时证明了"锚对了"和"阶段 0 没搬错"。
② 不变量断言：每条 sense 恰好一条 sense_src / entry 无孤儿 / src_ref 无重复。
③ 抽样：本步是确定性复刻，无判断成分，不适用。

用法（在 it/ 目录下）：
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
# build.py 判定"词缀词条"的规则（affix 的 form_of 义项不算变形指针）
AFFIX_POS = {"prefix", "suffix", "infix", "interfix", "circumfix", "combining_form"}

DDL_ENTRY = """CREATE TABLE entry (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  word_id  INTEGER NOT NULL,        -- → dict.id（词形不变，仍是搜索与身份单位）
  pos      TEXT NOT NULL,           -- 单一词性，不再是 "n/v" 这种串
  etym_no  TEXT NOT NULL,           -- 词源号；源头可能是 "1.1" 这种串，没编号记 "0"
  seq      INTEGER NOT NULL,        -- 同键内序号，正常 0（wiktextract 切分且音标不同时才 >0）
  aux      TEXT,                    -- 词条级助动词（阶段 1.5 之后填）
  conj     TEXT,
  src      TEXT NOT NULL,
  src_ref  TEXT NOT NULL,           -- kk-en:<词形>:<词性>:<词源号>:<seq>  内容派生、稳定
  UNIQUE(src_ref)
)"""
IDX_ENTRY = ["CREATE INDEX idx_entry_word ON entry(word_id)"]


def norm_gloss(s):
    return re.sub(r"\s+", " ", s).strip()


def replay(dump_path, words):
    """复刻 build.py 的循环。→ {word: [(gloss, entry_key, sense_idx, tags, raw_tags), …]}
    以及 {entry_key: {pos, etym, ipas, etym_text}}。只处理库里存在的词形。"""
    per_word = defaultdict(list)
    entries = {}
    dup_groups = defaultdict(list)      # (word,pos,etym) → [ipa 集合, …]，用于合并断言
    stat = Counter()
    seen = defaultdict(set)             # word → 已出现过的 gloss（复刻按词形去重）
    occ_of = Counter()                  # (词形,词性,词源号) → 该键已出现过几条 JSON entry

    with open(dump_path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                stat["坏行"] += 1
                continue
            w0 = e.get("word")
            # 🔴 复刻 build.py:325 的 `key = word.lower()` —— 建库时按小写折叠了词形，
            #    `Delfico`（姓氏）并进了 `delfico`。不复刻这一条，闸①会在 3,657 个词形上报警。
            #    entry 的 src_ref 里保留 dump 的**真实大小写**，正是阶段 3 拆分专名的凭据。
            w = (w0 or "").strip().lower()
            if w not in words:
                continue
            if w0 != w0.lower():
                stat["大小写被折叠的 entry（阶段 3 要拆）"] += 1
            pos = e.get("pos") or ""
            # ⚠️ 词源号**不是整数**：实测有 "1.1" 这种值，按原样当字符串用
            etym = str(e.get("etymology_number") or 0)
            key0 = (w0, pos, etym)
            ipas = frozenset(s["ipa"] for s in (e.get("sounds") or []) if s.get("ipa"))
            etext = (e.get("etymology_text") or "")[:200]
            dup_groups[key0].append((ipas, etext))
            # 🔴 同一个键可能对应多条 JSON entry（wiktextract 把一个维基章节切开了，
            #    实测 1,811 组）。它们合并成一个 entry，但**义项下标各自从 0 开始** ——
            #    只用 <下标> 做 src_ref 会撞 UNIQUE。加一个 dump 内的出现序号 occ。
            #    occ 是**冻结的外部文件里的坐标**（同 pronunciation.src_ref 的约定），
            #    不是库内行序引用，不违反 §2.0.1。
            occ = occ_of[key0]
            occ_of[key0] += 1
            stat["entry"] += 1

            # 🔴 每个 dump entry 都建行，**不管它有没有产出义项**：
            #    `abbagliati` 的两个读音（abˈbaʎʎati 命令式+ti / abbaʎˈʎati 分词复数）
            #    分属两个纯 form_of 的 entry —— 只给"有义项的 entry"建行，读音就没地方挂。
            # 🔴 键里必须带 ipas。只用 key0 的话，`setdefault` 会让同键的第二条 JSON
            #    复用第一条的音标集 —— 而 `assign_seq` 恰恰是**按音标集**把它们拆成
            #    seq 0/1 的，于是 seq=1 那行永远建不出来，它的义项还会被挂到 seq 0 上。
            #    全库 2 例（`infrociare` / `sorti`），2026-08-13 由语法层的闸①逮到。
            ent = entries.setdefault((key0, ipas),
                                     {"pos": pos, "etym": etym, "ipas": ipas,
                                      "etext": etext, "n_visible": 0,
                                      "n_hidden": 0, "n_formof": 0})
            is_affix = pos in AFFIX_POS
            for i, s in enumerate(e.get("senses") or []):
                # 🔴 2026-08-13（阶段 2）：`alt_of` **不是**变形指针，不能和 `form_of` 一起丢。
                #    `alt_of` = 异体/缩写/误拼（`bce`→`Banca Centrale Europea` 是首字母缩写，
                #    `abaca`→`abacà` 是异体写法），它们是**独立词条**，有自己的释义。
                #    原来一起丢掉的后果：7,028 个词形界面上一条释义都没有，只显示一句错话
                #    「Banca Centrale Europea 的变位形式」。这是 `SCHEMA` §9.1 那条缺陷的 it 版本，
                #    es 上是 5,701 个词（`levantarse` / `Méjico`）。实测两者无交集（0 条同时有）。
                is_alt = bool(s.get("alt_of")) and not s.get("form_of")
                if s.get("form_of") and not is_affix:
                    stat["变形指针义项（不算义项）"] += 1
                    ent["n_formof"] += 1
                    continue
                if is_alt and not is_affix:
                    stat["alt_of 义项（异体/缩写，算义项）"] += 1
                g = norm_gloss((s.get("glosses") or [""])[0])
                if not g:
                    stat["空 gloss（跳过）"] += 1
                    continue
                if g in seen[w]:
                    stat["🔴 按词形去重被吃掉的义项"] += 1
                    ent["n_hidden"] += 1
                    continue
                seen[w].add(g)
                ent["n_visible"] += 1
                per_word[w].append((g, (key0, ipas), occ, i, s.get("tags") or [],
                                    s.get("raw_tags") or [],
                                    [a.get("word") for a in (s.get("alt_of") or [])]
                                    if (is_alt and not is_affix) else None))
                stat["义项"] += 1
    return per_word, entries, dup_groups, stat


def n_entry_rows(entries, seq_of):
    """entry 表实际行数：同 (键, 音标) 合并后按 src_ref 去重。"""
    return len({"kk-en:%s:%s:%s:%d" % (k[0][0], k[0][1], k[0][2],
                                       seq_of.get((k[0], k[1]), 0))
                for k in entries})


def assign_seq(dup_groups, verbose=True):
    """同 (词形,词性,词源号) 的多条 JSON：音标与词源文本都相同才合并成一个 entry。
    → {(key0, ipas_frozenset): seq}；同时报出不能合并的组。"""
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
            print("   %-38s %8s" % (k, f"{v:,}"))
    return seq_of


def gate1(con, per_word, verbose=True):
    """闸① 复刻结果 vs 库里已有的义项序列，逐词逐序逐字节比对（100%，非抽样）。"""
    print("\n═══ 闸① 复刻回核（全量，非抽样）═══")
    # 🔴 阶段 3a 拆开大小写之后，一个小写词形可能对应两行 dict（`abate`/`Abate`）。
    #    原来把它们按 `word_id, rank` 拼成一条序列去对 dump 顺序 —— 顺序必然对不上
    #    （`arcadio` 的两条义项在 dump 里是 Arcadius 在前，拆行后按 id 排就反了）。
    #    ⇒ 改成**按 dump 的真实大小写分组**：复刻侧也按 entry 的原始大小写切开。
    have = defaultdict(list)
    for w, rank, text in con.execute(
            "SELECT d.word, s.rank, g.text FROM sense s "
            "JOIN dict d ON d.id = s.word_id "
            "JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='en' AND g.kind='equivalent' "
            "ORDER BY s.word_id, s.rank"):
        have[w].append(text)
    # 复刻侧按 entry 的真实大小写重新分组（per_word 的键是小写）
    per_case = defaultdict(list)
    for w, items in per_word.items():
        for it in items:
            per_case[it[1][0][0]].append(it)     # it[1] = (key0, ipas)，key0[0] = 真实大小写
    bad, samples = 0, []
    words = set(have) | set(per_case)
    for w in words:
        a = have.get(w, [])
        b = [x[0] for x in per_case.get(w, [])]
        if a != b:
            bad += 1
            if len(samples) < 6:
                samples.append((w, a[:3], b[:3], len(a), len(b)))
    # 🔴 **已接受基线：5 个词形，且必须正好是这 5 个**（不是"允许 5 个对不上"）。
    #    `fixes/fill_from_en_edition.py`（08-17）补了英文版有真释义、而当初那版解析漏收的
    #    5 个词。本闸是拿**当初那版解析**现场重刻，所以它刻不出这 5 条 ——
    #    差额来自修复，不是回归。⚠️ 名单写死：换了别的词就说明是新问题。
    BASELINE = {"natel", "cretacico", "allovino", "limosino", "calendario dell'avvento"}
    diff = {w for w, a, b, na, nb in
            [(w, have.get(w, []), [x[0] for x in per_case.get(w, [])], 0, 0) for w in words]
            if a != b} if False else {w for w in words
                                      if have.get(w, []) != [x[0] for x in per_case.get(w, [])]}
    print("   库里有英文义项的词形 %s；复刻出的词形 %s" % (f"{len(have):,}", f"{len(per_word):,}"))
    unexpected = diff - BASELINE
    missing = BASELINE - diff
    print("   %s 对不上的词形 %s（其中已接受基线 %s）"
          % ("✓" if not unexpected else "🔴", f"{bad:,}", f"{len(diff & BASELINE):,}"))
    for w, a, b, na, nb in samples:
        mark = "（基线内）" if w in BASELINE else "🔴 新的"
        print("   %s %s  库 %d 条 %s\n        复刻 %d 条 %s" % (mark, w, na, a, nb, b))
    if unexpected:
        print("   🔴 基线之外的：%s" % sorted(unexpected)[:5])
    if missing:
        print("   ⚠️ 基线里的这几个现在对上了，说明修复被撤销或口径变了：%s" % sorted(missing))
    return not unexpected


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        # 🔴 2026-08-18 改口径（A28）。本闸的期望值是**从英文版 dump 现场重推**出来的，
        #    而 `entry` 表后来还进了 fr 版 169,822 条、it 版 16,234 条（阶段 3 收词）。
        #    拿"英文版应有多少"去对"全表有多少"，红的是断言不是数据 ⇒ 两侧都限定 en-edition。
        ("entry 条数（en-edition 侧）== 期望",
         q("SELECT count(*) FROM entry WHERE src='en-edition'"), expect["entry"]),
        # 🔴 2026-08-13：`sense_src` 现在是**多来源**的证据层（阶段 1.5 灌进了意语版）。
        #    这几条断言原来写死了"库里只有英文版"，多一个来源就误报 —— 红的是断言口径不是数据。
        #    ⇒ 一律按 `src='en-edition'` 限定；意语版的完整性由 `ingest_it_edition.py` 自己的闸守。
        # 🔴 **已接受基线 +5，附理由**：`fixes/fill_from_en_edition.py`（08-17）补了
        #    5 个英文版**有真释义、原始解析漏收**的词（`natel` / `cretacico` / `allovino` /
        #    `limosino` / `calendario dell'avvento`）。本闸的期望值是用**当初那版解析**
        #    现场重推的，所以它推不出这 5 条 —— 差额是修复带来的，不是回归。
        #    ⚠️ 差额**超过 5** 就要查：那说明来了新的、没人认领的证据行。
        ("sense_src(en-edition) 条数 == 期望 + 5（见注释）",
         q("SELECT count(*) FROM sense_src WHERE src='en-edition'"), expect["src"] + 5),
        # ⚠️ 断言要分两种：有 dump 来源的必须恰好一条；**只有中文的那 23 条本来就没有来源**
        #    （22 个词条：ganga/Jehova/autoritativo…，见 SCHEMA §10 与 it-CONVENTIONS 记账）。
        #    第一版写成"每条 sense 都恰好一条"，红的是断言不是数据。
        # 🔴 同上：阶段 1.5 之后，一条义项可以**同时**有英文版与意语版两条证据
        #    （`sense_src` 是证据层，多源是常态）⇒ 断言限定在 en-edition 证据上。
        # 🔴 口径要按**义项自己的来源**，不能按 entry 的来源：entry 层是共用的 ——
        #    阶段 1.5/2 之后有 18,506 条**意语版来的义项**也挂在英文版的 entry 上（这是对的）。
        #    仍然成立的不变量：**有英文版证据的义项，恰好只有一条英文版证据**。
        ("有 en-edition 证据的 sense，恰好只有一条",
         q("SELECT count(*) FROM (SELECT x.sense_id FROM sense_src x "
           "WHERE x.src='en-edition' AND x.sense_id IS NOT NULL "
           "GROUP BY x.sense_id HAVING count(*)<>1)"), 0),
        ("无 entry 的 sense 都没有 sense_src",
         q("SELECT count(*) FROM sense s JOIN sense_src x ON x.sense_id=s.id "
           "WHERE s.entry_id IS NULL AND x.src='en-edition'"), 0),
        # 同上：按义项自己的来源算，才是这道闸当初想守的东西
        # 同一批 5 条（见上面 `sense_src` 那条的理由）
        ("由 en-edition 证据裁决出的 sense == 期望 + 5",
         q("SELECT count(DISTINCT sense_id) FROM sense_src "
           "WHERE src='en-edition' AND sense_id IS NOT NULL"), expect["sense_with_entry"] + 5),
        ("孤儿 entry（word_id 不在 dict）",
         q("SELECT count(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
           "WHERE d.id IS NULL"), 0),
        ("孤儿 sense.entry_id",
         q("SELECT count(*) FROM sense s LEFT JOIN entry e ON e.id=s.entry_id "
           "WHERE s.entry_id IS NOT NULL AND e.id IS NULL"), 0),
        # `sense_id IS NULL` 是**合法状态**（「尚未裁决」，意语版证据全是这个状态）；
        # 这条断言逮的是"指到了一个不存在的 sense"，所以要排除 NULL 再判。
        ("sense_src 指向不存在的 sense",
         q("SELECT count(*) FROM sense_src x LEFT JOIN sense s ON s.id=x.sense_id "
           "WHERE x.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        ("entry 的 pos 含 '/'（不该有）",
         q("SELECT count(*) FROM entry WHERE pos LIKE '%/%'"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-34s %10s  期望 %s" % ("✓" if good else "🔴", name,
                                            f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--verify", action="store_true", help="只跑两道闸，不写库")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {w.lower() for (w,) in con.execute("SELECT DISTINCT word FROM dict")}
    print("■ 库里词形 %s，开始复刻 %s" % (f"{len(words):,}", paths.KK.name))
    per_word, entries, dup_groups, stat = replay(paths.KK, words)
    for k, v in stat.items():
        print("   %-34s %10s" % (k, f"{v:,}"))

    seq_of = assign_seq(dup_groups)
    hidden = [k for k, v in entries.items()
              if v["n_visible"] == 0 and v["n_hidden"] > 0]
    formonly = [k for k, v in entries.items()
                if v["n_visible"] == 0 and v["n_hidden"] == 0 and v["n_formof"] > 0]
    print("   %-34s %10s" % ("entry 行（含纯变形 entry）",
                                     f"{n_entry_rows(entries, seq_of):,}"))
    print("   %-34s %10s" % ("  其中纯变形 entry（正常）", f"{len(formonly):,}"))
    print("   %-34s %10s" % ("  🔴 义项被去重吃光、整个不可见", f"{len(hidden):,}"))
    print("      样例：%s" % [("%s/%s/%s" % k[0]) for k in hidden[:5]])

    if a.mutate:
        return mutate(con, per_word)

    if a.verify:
        ok1 = gate1(con, per_word)
        n_ent = len({("kk-en:%s:%s:%s:%d" % (k[0][0], k[0][1], k[0][2],
                                             seq_of.get((k[0], v["ipas"]), 0)))
                     for k, v in entries.items()})
        ok2 = gate2(con, {"entry": n_ent,
                          "src": sum(len(v) for v in per_word.values()),
                          "sense_with_entry": sum(len(v) for v in per_word.values())})
        print("\n%s" % ("✓ 两道闸全过" if ok1 and ok2 else "🔴 有闸未通过"))
        return 0 if (ok1 and ok2) else 1

    ok1 = gate1(con, per_word)
    if not ok1:
        print("\n🔴 闸①未通过 —— 复刻规则与 build.py 不一致，先查清楚再写库")
        return 1
    if not a.apply:
        print("\n■ 将写入：entry %s 行 / sense_src %s 行" % (
            f"{n_entry_rows(entries, seq_of):,}",
            f"{sum(len(v) for v in per_word.values()):,}"))
        print("(未加 --apply，不写库)")
        return 0
    return apply(con, per_word, entries, seq_of)


def apply(con, per_word, entries, seq_of):
    # sense.id 按 (word_id, rank) 取；复刻序列与 rank 一一对应（闸①已证）
    sense_id = {}
    for sid, wid, rank, word in con.execute(
            "SELECT s.id, s.word_id, s.rank, d.word FROM sense s JOIN dict d ON d.id=s.word_id"):
        sense_id[(word.lower(), rank)] = (sid, wid)

    ent_rows, ent_id = [], {}
    # ⚠️ 键里含 frozenset，`sorted` 不能直接比 —— frozenset 的 `<` 是子集关系（偏序），
    #    排出来的次序不确定。显式给一把全序的排序键。
    for k, v in sorted(entries.items(), key=lambda kv: (kv[0][0], sorted(kv[0][1]))):
        (w, pos, etym), ipas = k
        seq = seq_of.get((k[0], ipas), 0)
        ref = "kk-en:%s:%s:%s:%d" % (w, pos, etym, seq)
        if ref in ent_id:                       # 合并后的同一个 entry
            continue
        ent_id[ref] = len(ent_rows) + 1
        ent_rows.append((ent_id[ref], None, pos, etym, seq, SRC, ref, w))

    src_rows, link = [], []
    for w, items in per_word.items():
        for rank, (g, k, occ, idx, tags, raw, alt) in enumerate(items, start=1):
            sid, wid = sense_id[(w, rank)]
            (w0, pos0, etym0), ipas0 = k        # k 现在是 (key0, ipas)，见 replay 里的说明
            seq = seq_of.get((k[0], ipas0), 0)
            ref = "kk-en:%s:%s:%s:%d" % (w0, pos0, etym0, seq)
            link.append((ent_id[ref], sid))
            src_rows.append((wid, sid, SRC, "%s#%d.%d" % (ref, occ, idx), "en", g,
                             json.dumps(sorted(set(tags) | set(raw)), ensure_ascii=False)
                             if (tags or raw) else None))
    # entry.word_id 用词形反查
    wid_of = {w.lower(): i for i, w in con.execute("SELECT id, word FROM dict")}
    ent_rows = [(i, wid_of[w.lower()], pos, etym, seq, SRC, ref)
                for (i, _, pos, etym, seq, src, ref, w) in ent_rows]
    con.close()

    # 🔴 这个函数是**一次性引导**：它 DROP entry、DELETE 整张 sense_src。
    #    阶段 Q1 之后 entry 上有了 `aux`、阶段 1.5 之后 sense_src 里有 92,385 条意语证据
    #    和 23,523 条已裁决的 sense_id —— 重跑会把它们**静默抹掉**，而行数闸拦不住
    #    （删掉一批、又插回一批，净变化可能正好对得上）。
    #    这就是 `replay-scripts-undo-fixes` 那条教训的现场：UNIQUE 保证不重复，不保证不倒退。
    guard = con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    other = guard.execute("SELECT count(*) FROM sense_src WHERE src<>?", (SRC,)).fetchone()[0]
    aux_n = guard.execute("SELECT count(*) FROM entry WHERE aux IS NOT NULL").fetchone()[0] \
        if guard.execute("SELECT count(*) FROM sqlite_master WHERE name='entry'").fetchone()[0] else 0
    guard.close()
    if other or aux_n:
        print("\n🔴 拒绝重跑：库里已经有本脚本会抹掉的下游成果 ——")
        print("   sense_src 里非 en-edition 的证据 %s 条；entry.aux 已填 %s 行"
              % (f"{other:,}", f"{aux_n:,}"))
        print("   这个 --apply 是一次性引导，不是增量脚本。要改结构请写针对性的 fixes/ 脚本。")
        return 2

    now = dbtool.snapshot()
    expect = {"#sense_src": len(src_rows) - now.get("#sense_src", 0),
              "#entry": len(ent_rows) - now.get("#entry", 0)}
    with dbtool.session("keep-v3-entry", expect=expect) as s:
        s.execute("DROP TABLE IF EXISTS entry")
        s.execute(DDL_ENTRY)
        for q in IDX_ENTRY:
            s.execute(q)
        s.executemany("INSERT INTO entry (id,word_id,pos,etym_no,seq,src,src_ref) "
                      "VALUES (?,?,?,?,?,?,?)", ent_rows)
        cols = {r[1] for r in s.conn.execute("PRAGMA table_info(sense)")}
        if "entry_id" not in cols:
            s.execute("ALTER TABLE sense ADD COLUMN entry_id INTEGER")
            s.execute("CREATE INDEX idx_sense_entry ON sense(entry_id)")
        s.executemany("UPDATE sense SET entry_id=? WHERE id=?", link)
        s.execute("DELETE FROM sense_src")
        s.executemany("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags) "
                      "VALUES (?,?,?,?,?,?,?)", src_rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok = gate2(con, {"entry": len(ent_rows), "src": len(src_rows),
                     "sense_with_entry": len(link)})
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


def mutate(con, per_word):
    """变异验证：破坏复刻结果，闸①必须报出来。"""
    print("\n═══ 变异验证 ═══")
    ws = [w for w, v in per_word.items() if len(v) > 2][:4]
    cases = []

    def broke(name, f):
        pw = {k: list(v) for k, v in per_word.items()}
        f(pw)
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = gate1(con, pw, verbose=False)
        cases.append((name, not ok))
        print("   %s  %-44s 闸%s" % ("✓" if not ok else "🔴", name, "报出" if not ok else "没报"))

    broke("调换 %s 的前两条义项顺序" % ws[0],
          lambda pw: pw.__setitem__(ws[0], [pw[ws[0]][1], pw[ws[0]][0]] + pw[ws[0]][2:]))
    broke("删掉 %s 的最后一条义项" % ws[1], lambda pw: pw.__setitem__(ws[1], pw[ws[1]][:-1]))
    broke("改掉 %s 第一条义项的一个字符" % ws[2],
          lambda pw: pw.__setitem__(ws[2], [(pw[ws[2]][0][0][:-1],) + tuple(pw[ws[2]][0][1:])]
                                    + pw[ws[2]][1:]))
    broke("给 %s 多插一条义项" % ws[3],
          lambda pw: pw.__setitem__(ws[3], pw[ws[3]] + [("XXX", ("x", "noun", "0"), 0, 0, [], [])]))
    ok = all(x for _, x in cases)
    print("\n%s" % ("✓ 四条变异全部被闸①逮到" if ok else "🔴 有变异没被逮到"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
