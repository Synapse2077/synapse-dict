#!/usr/bin/env python3
"""阶段 1.5a：出版义项层 + **免费**的中文与日语原文释义。零模型调用。2026-09-15。

═══ 三层怎么变成出版层 ═══
    sense_src   证据层（阶段 1 建，149,410 行，永不编辑）
      └ 非指针的 141,773 行 → `sense` 出版层（逐词 rank 1..N）
        └ sense_gloss(lang='en')  英文 gloss，源头白送
          + sense_gloss(lang='zh')  中文版白送
          + sense_gloss(lang='ja')  日语版原文定义
🔴 指针义项（7,637 条）**不出版** —— 它们描述的是关系不是词义，归阶段 2 的变形/关系层。

═══ 🔴 配对一律用 1:1 规则，**有意不做更好的对齐** ═══
「两边都只有一条义项时才配，多条一律不猜」—— 与 `de/pipeline/ingest_de_senses.py:261` 同。
量过之后这是个**有数支撑的决定**，不是偷懒（`JA_PLAN` §四.1）：

    1:1 规则   免费 13,242 ｜ 要买 128,531 条 ｜ ≈ 19.0 元
    完美对齐   免费 40,638 ｜ 要买 101,135 条 ｜ ≈ 15.0 元
    ⇒ 做更好的对齐最多省 4.1 元

而代价是**义项错配**：es 那轮自动判重 186 条里 **12.4% 错配**（「棋子」并进了「行人」）。
多一条义项是「缺」，义项错配是「错」，**错比缺更伤权威**。为 4 块钱不值。

═══ 🔴 判「是不是中文」不能用「有没有汉字」 ═══
日语的释义本来就全是汉字。中文版那边用 `has_kana` 反向判（带假名 ⇒ 一定不是中文），
日语版那边反过来（带假名 ⇒ 是日语）。
⚠️ `ja/dbtool.py` 里**没有 `has_han` 这个名字**，从别的语种拷脚本过来会当场 AttributeError。

跑（在仓库根）：
    python3 -u ja/pipeline/ingest_ja_senses.py
    python3 -u ja/pipeline/ingest_ja_senses.py --apply
    python3 -u ja/pipeline/ingest_ja_senses.py --verify
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import gzip
import json
import re
import sqlite3

import dbtool
import paths

CJK = re.compile(r"[一-鿿]")
# 🔴 `POINTER` **只许有一份**。2026-09-16 建外锚闸时发现它在本文件和
#    `intake_edition_words` 里各写了一遍 —— 两份现在恰好一样，
#    而「恰好一样」是靠不住的：改了一份、另一份静默漂开，
#    两边各自的闸都不会响（`[[refactor-mindset-code-quality]]`：
#    同一文件里两张重复映射表已经发生过）。
from intake_edition_words import POINTER            # noqa: E402,F401


def free_zh():
    """中文版 → {词形: [中文释义…]}。判据：含汉字、**不含假名**、不等于词头。"""
    out = collections.defaultdict(list)
    for line in gzip.open(paths.ZH_EDITION, "rt", encoding="utf-8"):
        if '"lang_code": "ja"' not in line:
            continue
        o = json.loads(line)
        if o.get("lang_code") != "ja":
            continue
        w = o.get("word")
        for s in (o.get("senses") or []):
            tg = s.get("tags") or []
            if s.get("form_of") or s.get("alt_of") or "form-of" in tg:
                continue
            for g in (s.get("glosses") or []):
                g = (g or "").strip()
                # 🔴 `dbtool.is_chinese_text` 的同一条判据，带来源：zh-edition 的纯汉字算中文
                if g and g != w and CJK.search(g) and not dbtool.has_kana(g):
                    out[w].append(g)
    return out


def free_ja():
    """日语版 → {词形: [日语原文定义…]}。

    🔴 **判据是来源，不是形式。** 第一版写的是"带假名才算日语" —— 那是形式代理，
       实测 **9,823 条（5.91%）日语定义是纯汉字**（`現代、現在。`／`顔色。表情。`／`藍色。`），
       全被它漏掉；而 `（古語・雅語）十一月` 反倒因为 `・` 被误放进来。
       ⇒ 日语版为日语词条写的定义**就是日语**，这是来源说的，不用再从字形上猜
       （`[[criteria-from-meaning-not-form]]`）。
    ⚠️ 仍留一条弱过滤：正文必须含 CJK 或假名 —— 那不是判语言，是挡纯拉丁的残渣。
    """
    out = collections.defaultdict(list)
    for line in open(paths.EDITION, encoding="utf-8"):
        o = json.loads(line)
        w = o.get("word")
        for s in (o.get("senses") or []):
            tg = s.get("tags") or []
            if s.get("form_of") or s.get("alt_of") or "form-of" in tg:
                continue
            for g in (s.get("glosses") or []):
                g = (g or "").strip()
                if g and g != w and (CJK.search(g) or dbtool.has_kana(g)):
                    out[w].append(g)
    return out


def build():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    entry_id = {r: i for i, r in con.execute("SELECT id, src_ref FROM entry")}
    rows = con.execute(
        "SELECT x.id, x.word_id, d.word, x.src_ref, x.text, x.raw_tags, e.pos"
        " FROM sense_src x JOIN dict d ON d.id=x.word_id"
        " LEFT JOIN entry e ON e.src_ref = substr(x.src_ref, 1, instr(x.src_ref,'#')-1)"
        " ORDER BY x.id").fetchall()
    con.close()

    stat = collections.Counter()
    senses, links, glosses = [], [], []
    per_word = collections.Counter()
    ours = collections.Counter()          # 词形 → 非指针义项数（配对要用）
    keep = []
    for sid, wid, word, ref, text, rt, pos in rows:
        tg = json.loads(rt or "[]")
        if any(t in POINTER for t in tg):
            stat["指针义项·不出版"] += 1
            continue
        keep.append((sid, wid, word, ref, text, pos))
        ours[word] += 1
    zh, jadef = free_zh(), free_ja()

    for sid, wid, word, ref, text, pos in keep:
        per_word[word] += 1
        rank = per_word[word]
        eid = entry_id.get(ref.split("#")[0])
        senses.append((wid, eid, rank, pos))
        links.append((sid, wid, rank))
        glosses.append((wid, rank, "en", "definition", 0, text, "en-edition"))
        stat["sense"] += 1
        # 🔴 1:1 规则：两边都只有一条才配，多条一律不猜
        if ours[word] == 1 and len(zh.get(word, ())) == 1:
            glosses.append((wid, rank, "zh", "equivalent", 0, zh[word][0], "zh-edition"))
            stat["免费中文（1:1）"] += 1
        if ours[word] == 1 and len(jadef.get(word, ())) == 1:
            glosses.append((wid, rank, "ja", "definition", 0, jadef[word][0], "ja-edition"))
            stat["日语原文定义（1:1）"] += 1
    stat["有中文版释义可配的词形"] = sum(1 for w in ours if zh.get(w))
    stat["有日语版定义可配的词形"] = sum(1 for w in ours if jadef.get(w))
    return senses, links, glosses, stat


def verify(exp=None):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    g = lambda l: q("SELECT COUNT(*) FROM sense_gloss WHERE lang='%s'" % l)
    n_sense = q("SELECT COUNT(*) FROM sense")
    checks = [
        ("sense 行数", n_sense, exp["sense"] if exp else n_sense),
        ("每条 sense 都有英文 gloss", q(
            "SELECT COUNT(*) FROM sense s WHERE NOT EXISTS("
            "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='en')"), 0),
        ("sense_src 认领率（非指针）", q(
            "SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL AND raw_tags NOT LIKE '%form-of%'"
            " AND raw_tags NOT LIKE '%alt-of%' AND raw_tags NOT LIKE '%romanization%'"), 0),
        ("孤儿 sense（word_id 不在 dict）", q(
            "SELECT COUNT(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id WHERE d.id IS NULL"), 0),
        ("🔴 中文 gloss 里混进假名（判据用错就会这样）", q(
            "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND ("
            "text GLOB '*[ぁ-ゖ]*' OR text GLOB '*[ァ-ヺ]*')"), 0),
        # ⚠️ **不要求日语 gloss 带假名** —— 5.91% 的日语定义是纯汉字（`現代、現在。`）。
        #    断言只挡"纯拉丁残渣"，与 `free_ja` 用同一条规则。
        ("🔴 日语 gloss 既无汉字也无假名（纯拉丁残渣）", q(
            "SELECT COUNT(*) FROM sense_gloss WHERE lang='ja' AND NOT ("
            "text GLOB '*[一-鿿]*' OR text GLOB '*[ぁ-ゖ]*' OR text GLOB '*[ァ-ヺ]*')"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-40s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    print("   ⭐ 释义三语覆盖：en %s ｜ zh %s (%.1f%%) ｜ ja %s (%.1f%%)"
          % (format(g("en"), ","), format(g("zh"), ","), 100 * g("zh") / n_sense,
             format(g("ja"), ","), 100 * g("ja") / n_sense))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.verify:
        return verify()

    senses, links, glosses, stat = build()
    for k, v in stat.most_common():
        print("   %-26s %9s" % (k, format(v, ",")))
    paid = stat["sense"] - stat["免费中文（1:1）"]
    print("\n   ⇒ 1.5b 要买的：%s 条 ≈ %.1f 元（按 pt 实测 0.000148 元/条）"
          % (format(paid, ","), paid * 8.9 / 60167))
    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    import sqlite3 as _sq
    _c = _sq.connect("file:%s?mode=ro" % paths.DB, uri=True)
    old_s = _c.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
    old_g = _c.execute("SELECT COUNT(*) FROM sense_gloss").fetchone()[0]
    _c.close()
    # 🔴 重跑模式：本步是 `sense`/`sense_gloss` 的**唯一写者**，先删后插；
    #    `expect` 写**净变化**不是总数（`dbtool` 的 expect 是增量）。
    with dbtool.session("ja-sense-layer", expect={
            "#sense": len(senses) - old_s, "#sense_gloss": len(glosses) - old_g}) as s:
        if old_s or old_g:
            print("■ 重跑：先删 sense %s / sense_gloss %s" % (f"{old_s:,}", f"{old_g:,}"))
            s.execute("UPDATE sense_src SET sense_id=NULL")
            s.execute("DELETE FROM sense_gloss")
            s.execute("DELETE FROM sense")
        s.executemany("INSERT INTO sense (word_id, entry_id, rank, pos) VALUES (?,?,?,?)", senses)
        # 🔴 回填 `sense_src.sense_id`：证据层与出版层的桥。
        #    **按 (word_id, rank) 查主键，不按插入顺序猜 id**（`[[model-answer-files-key-by-id]]`）。
        #
        # 🔴🔴 **先把映射物化成一张以 src_id 为主键的表，再回填。**
        #    第一版写成一条相关子查询：
        #        UPDATE sense_src SET sense_id=(SELECT … FROM sense JOIN _lnk … WHERE l.src_id=sense_src.id)
        #    `_lnk` 上没有 `src_id` 索引 ⇒ 每行全扫 141,773 行 ⇒ 2×10¹⁰ 次操作。
        #    实跑 7 分钟 100% CPU 还没完，杀掉回滚（`sense` 0 / 认领 0 / integrity ok）。
        #    ⚠️ 这正是 `PITFALLS` F 组的「相关子查询入口」（`[[query-perf-collation-traps]]`）——
        #       我整场都在引用它，然后自己写了一条。判据：`EXPLAIN QUERY PLAN` 出现 SCAN 就是没走索引。
        s.execute("CREATE TEMP TABLE _lnk(src_id INT, word_id INT, rank INT)")
        s.executemany("INSERT INTO _lnk VALUES (?,?,?)", links)
        s.execute("CREATE TEMP TABLE _map(src_id INTEGER PRIMARY KEY, sense_id INTEGER)")
        s.execute("INSERT INTO _map(src_id, sense_id) SELECT l.src_id, s.id FROM _lnk l"
                  " JOIN sense s ON s.word_id=l.word_id AND s.rank=l.rank")
        s.execute("UPDATE sense_src SET sense_id="
                  "(SELECT m.sense_id FROM _map m WHERE m.src_id=sense_src.id)"
                  " WHERE id IN (SELECT src_id FROM _map)")
        s.execute("CREATE TEMP TABLE _g(word_id INT, rank INT, lang TEXT, kind TEXT,"
                  " seq INT, text TEXT, src TEXT)")
        s.executemany("INSERT INTO _g VALUES (?,?,?,?,?,?,?)", glosses)
        s.execute("INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src)"
                  " SELECT s.id, g.lang, g.kind, g.seq, g.text, g.src FROM _g g"
                  " JOIN sense s ON s.word_id=g.word_id AND s.rank=g.rank")

    print("\n═══ 写后回核 ═══")
    verify(stat)


if __name__ == "__main__":
    main()
