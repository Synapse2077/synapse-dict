#!/usr/bin/env python3
"""阶段 5a/5b：例句 → `example`，语义关系 → `sense_relation`。2026-09-08。零 API。

读中间件 `ingest/ex_rel.jsonl`（`harvest_ex_rel.py` 一次扫 dump 产出）。

═══ ⭐ en 独有：挂载是**确定性**的，不是文本匹配 ═══
`sense_src.src_ref` = `en-edition:<词>:<pos>:<etym>:<seq>#<义项序号>`，全表唯一。
收割时按同样规则重建这个键 ⇒ 挂载率应为 100%。
🔴 de 那轮靠「(词形, 德语释义原文) 逐字节匹配」只挂上 **51.3%**。**但要实测，不是假设。**

═══ 收哪些关系：先量、看样本，再定（不照抄 de）═══
实测各族的量与内容（`dictionary` 为例）：

    derived    → dictionarial / dictionarian / dictionaric / dictionarist   **构词族**
    related    → diction / encyclopedia / lexicon / thesaurus（有用）
                 free → friend（词源关联，不是语义关系）                    **质量混杂**
    synonyms   → dict / lexicon（对）｜ **dictionary → dictionary（自指！）**
    coordinate_terms → biographical dictionary / concordance / onomasticon  同位词

⇒ **收** synonym/antonym/hypernym/hyponym/holonym/meronym/coordinate/troponym
  **不收** derived（构词族）／ related（联想与词源，混杂）／ anagrams／proverbs
  —— 与 de 的结论相同，但理由是**在英语数据上重新看出来的**
  （`[[es-v3-structure-backfill]]`：照搬结构前先量这门语言有没有那个病）。
🔴 **自指必须滤掉**：`dictionary → dictionary` 说不出任何信息。

⚠️ 阶段 2 已写入 `alt_of` 174,483 行，本步**只增不动**。

    cd en && python3 -u pipeline/build_ex_rel.py
    cd en && python3 -u pipeline/build_ex_rel.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import sqlite3

import dbtool
import paths

ING = paths.WORK / "ingest" / "ex_rel.jsonl"
SRC = "en-edition"
# 复数 → 单数，与阶段 2 的 `alt_of` 同一命名风格
# 出版层默认显示的语义关系
KEEP = {"synonyms": "synonym", "antonyms": "antonym", "hypernyms": "hypernym",
        "hyponyms": "hyponym", "holonyms": "holonym", "meronyms": "meronym",
        "coordinate_terms": "coordinate", "troponyms": "troponym"}
# 🔴🔴 **收进来但默认不显示**（`hidden=1`）—— 2026-09-08 用户问「102 万丢掉？」问出来的。
#    我第一版照搬 de「构词族与联想词不是语义关系」把这 102 万条**不入库**，理由写的是
#    「弹窗里给查 dictionary 的人看 dictionarist 是噪声」。两个错：
#    ① **拿一个偏样本推断总体**：我只看了 `dictionary` 的派生族（字母相邻的生僻词）。
#       换常用词看完全不同 ——
#         book  derived  audio-book / back of the book / blot one's copy book / book account
#         book  related  incunable / scroll / tome / volume / document / manuscript
#         run   related  walk / gait / journey / rush / speedy / trajectory
#       **词组族与联想词是词典的正经栏目**，任何一本纸质词典都有。
#    ② **拿展示层的需求决定数据层收不收**。用户定过：产品是划词弹窗，
#       **但我们做的是词典，弹窗只是下游筛字段**（`[[dict-product-scope-popup]]`）。
#    ⇒ `sense_relation.hidden` 这一列就是为这种情况准备的：**数据进库，展示层默认不显示**。
#      入库时砍掉不可逆；`hidden` 可逆（`[[prefer-reversible-designs]]`）。
HIDDEN = {"derived": "derived", "related": "related", "proverbs": "proverb",
          "abbreviations": "abbreviation"}
DROP = ("anagrams",)   # 变位词是文字游戏，不是词条关系


def collect(con):
    q = con.execute
    wid = dict(q("SELECT word, id FROM dict"))
    sid = {}
    for ref, s in q("SELECT src_ref, sense_id FROM sense_src WHERE sense_id IS NOT NULL"):
        sid[ref] = s
    ex_rows, rel_rows = [], []
    ex_seen, rel_seen = set(), set()
    stat = collections.Counter()
    for line in ING.open(encoding="utf-8"):
        o = json.loads(line)
        w, base = o["w"], o["b"]
        i = wid.get(w)
        if i is None:
            stat["词不在库里"] += 1
            continue
        for e in o["ex"]:
            stat["ex 源"] += 1
            key = (w, e["t"])
            if key in ex_seen:
                stat["ex 去重"] += 1
                continue
            ex_seen.add(key)
            s = sid.get("%s#%d" % (base, e["i"]))
            stat["ex 挂上义项" if s else "ex 挂不上"] += 1
            ex_rows.append((w, s, e["t"], json.dumps(e["b"]) if e.get("b") else None,
                            e.get("r"), None, e.get("en"), "en" if e.get("en") else None,
                            0, SRC))
        for r in o["rel"]:
            k = r["k"]
            if k in DROP:
                stat["rel 不收:" + k] += 1
                continue
            kind = KEEP.get(k)
            hid = 0
            if kind is None:
                kind = HIDDEN.get(k)
                hid = 1
            if kind is None:
                stat["rel 未知族:" + k] += 1
                continue
            t = r["t"]
            if t == w:
                stat["🔴 rel 自指（滤掉）"] += 1
                continue
            s = sid.get("%s#%d" % (base, r["i"])) if r["i"] is not None else None
            key = (i, s, kind, t)
            if key in rel_seen:
                stat["rel 去重"] += 1
                continue
            rel_seen.add(key)
            stat[("hidden " if hid else "") + ("rel 挂上义项" if s else "rel 只挂词")] += 1
            rel_rows.append((i, s, kind, t,
                             json.dumps(r["g"], ensure_ascii=False) if r["g"] else None,
                             hid, SRC, "%s#%s" % (base, r["i"] if r["i"] is not None else "-")))
    return ex_rows, rel_rows, stat


def gates(con, n_ex, n_rel, alt_before):
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("example 行数", q("SELECT COUNT(*) FROM example"), n_ex),
        ("example.word 全在 dict 里",
         q("SELECT COUNT(*) FROM example e LEFT JOIN dict d ON d.word=e.word "
           "WHERE d.id IS NULL"), 0),
        ("example.sense_id 要么空要么真存在",
         q("SELECT COUNT(*) FROM example e LEFT JOIN sense s ON s.id=e.sense_id "
           "WHERE e.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        ("example.text 无空串", q("SELECT COUNT(*) FROM example WHERE TRIM(text)=''"), 0),
        # 🔴 阶段 2 的 alt_of 一行都不许动
        ("⭐ 阶段 2 的 alt_of 未被动过",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind='alt_of'"), alt_before),
        ("sense_relation 新增行数",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind<>'alt_of'"), n_rel),
        ("🔴 关系无自指",
         q("SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id "
           "WHERE r.target = d.word"), 0),
        # 🔴 收进来的那两族必须**全部** hidden=1；出版族必须**全部** hidden=0。
        #    两条一起才守得住 —— 只查一边，另一边错了照样绿。
        ("🔴 hidden 族里有没藏住的",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind IN (%s) AND hidden<>1"
           % ",".join("'%s'" % v for v in sorted(set(HIDDEN.values())))), 0),
        ("🔴 出版族里有被误藏的",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind IN (%s) AND hidden<>0"
           % ",".join("'%s'" % v for v in sorted(set(KEEP.values()) | {"alt_of"}))), 0),
        ("anagrams 一条都没进来",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind='anagram'"), 0),
        ("kind 只在白名单内",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind NOT IN (%s,'alt_of')"
           % ",".join("'%s'" % v for v in sorted(set(KEEP.values()) | set(HIDDEN.values())))), 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-40s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ex, rel, stat = collect(con)
    alt_before, = con.execute("SELECT COUNT(*) FROM sense_relation WHERE kind='alt_of'").fetchone()
    ex_now, = con.execute("SELECT COUNT(*) FROM example").fetchone()
    rel_now, = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()
    con.close()
    print("═══ 阶段 5a/5b 计划 ═══")
    print("   例句：源 %s ／ 去重 %s ／ **入库 %s**"
          % (format(stat["ex 源"], ","), format(stat["ex 去重"], ","), format(len(ex), ",")))
    tot = stat["ex 挂上义项"] + stat["ex 挂不上"]
    print("      ⭐ **挂上义项 %s / %s = %.2f%%**（de 那轮 51.3%%）"
          % (format(stat["ex 挂上义项"], ","), format(tot, ","),
             100 * stat["ex 挂上义项"] / max(tot, 1)))
    print("   关系：**入库 %s**（挂义项 %s ／ 只挂词 %s）"
          % (format(len(rel), ","), format(stat["rel 挂上义项"], ","),
             format(stat["rel 只挂词"], ",")))
    print("      🔴 自指滤掉 %s ／ 去重 %s" % (format(stat["🔴 rel 自指（滤掉）"], ","),
                                        format(stat["rel 去重"], ",")))
    print("      ⭐ 收进来但默认隐藏（hidden=1）：")
    for k in DROP:
        if stat["rel 不收:" + k]:
            print("         %-16s %s" % (k, format(stat["rel 不收:" + k], ",")))
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0
    with dbtool.session("keep-v3-5ab-ex-rel",
                        expect={"#example": len(ex) - ex_now,
                                "#sense_relation": len(rel) - (rel_now - alt_before)}) as s:
        s.execute("DELETE FROM example")
        s.execute("DELETE FROM sense_relation WHERE kind<>'alt_of'")
        s.executemany("INSERT INTO example (word,sense_id,text,bold,ref,src_gloss,"
                      "src_translation,src_lang,hidden,src) VALUES (?,?,?,?,?,?,?,?,?,?)", ex)
        s.executemany("INSERT INTO sense_relation (word_id,sense_id,kind,target,tags,"
                      "hidden,src,src_ref) VALUES (?,?,?,?,?,?,?,?)", rel)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = gates(con, len(ex), len(rel), alt_before)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
