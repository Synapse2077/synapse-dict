#!/usr/bin/env python3
"""B31（fr）— 例句标签：判据唯一的家 ＋ 回填 `example.tags`。2026-11-06。

═══ 是什么 ═══
源头在 `senses[].examples[]` 上标了 `tags`／`raw_tags`。ru 已做成模板（ru R25，
`ru/pipeline/criteria.example_tags`）；**按语种解耦**（`[[multilang-decoupling-essence]]`），
fr 的值域、白名单写在这里，不 import ru。

fr 七份来源里只有两份带标签（2026-11-05 只读摸底，`docs/BACKLOG.md`「B31 逐门摸底」）：
  · en 版 20,355 条里 3,135 条带：`collocation` 3,082 —— 这条「例句」其实是固定搭配
  · fr 版 712,767 条里 3,041 条带：几乎没有「例句类型」，是**义项用法标注落在例句上**
    （`figuratively`／`broadly`／`analogy`／`familiar`…）
  · el／nl／ru／ja／tr 版：0

═══ 判据（用户 2026-11-05／06 定）═══
· **逐字白名单**，不做子串匹配：`raw_tags` 是自由文本（238 种），子串一匹配
  `Parfois ironique`（「有时」反讽）就会被印成「讽刺」。
· 收：类型（搭配／谚语／习语）、语体、**义的引申方式**（广义／类比／夸张／转喻／罕用，
  用户 11-06 定收 —— ru 值域里没有，fr 因此比 ru 宽）。
· 不收：
  - 地区 `UK`／`US`：回源看样本，标的是**英文译文**是英式还是美式（`promotion` 同一句
    两条英文译文各标一个），印在法语例句旁是错的；`Québec`／`Canada` 11 条，地区是另一个
    维度，义项层已有地区标签（用户 11-06 定不收）。
  - 语法（`pronominal`／`transitive`／`Absolument`／`Par apposition`…）、学科名
    （义项层已有学科标签）、引文年代（`XVIᵉ siècle`，出处里有）、en 版自由文本。
· 同一（词，句子）在多份来源／多个义项下出现时，入库只留一行（`UNIQUE(word,text)`），
  **标签取所有出现处的并集** —— 否则 en 版标的搭配会被先到的 fr 版那一行静默吞掉。

用法（在 fr/ 目录下）：
    python3 -u pipeline/example_tags.py              # 干跑：扫 dump，报会写多少
    python3 -u pipeline/example_tags.py --apply      # 写 `example.tags`
    python3 -u pipeline/example_tags.py --verify
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 印出来的顺序：类型 → 语体（高到低）→ 年代／频度 → 态度 → 引申方式。
# ⚠️ 这也是**受控值域**：库里出现这之外的值＝回归闸 E4 红、契约闸查不到中文名。
EXAMPLE_TAG_ORDER = (
    "collocation", "proverb", "idiom",
    "familiar", "colloquial", "slang", "formal", "literary", "poetic",
    "dated", "archaic", "obsolete", "rare",
    "vulgar", "derogatory", "euphemistic", "ironic",
    "figurative", "broadly", "by-analogy", "metonymically", "hyperbole",
)

# `tags`（wiktextract 归一过的英文键）→ 我们的键。逐字。
_TAGS = {
    "collocation": "collocation", "proverb": "proverb",
    "familiar": "familiar", "colloquial": "colloquial", "slang": "slang",
    "formal": "formal", "literary": "literary", "poetic": "poetic",
    "dated": "dated", "archaic": "archaic", "obsolete": "obsolete", "rare": "rare",
    "vulgar": "vulgar", "pejorative": "derogatory", "euphemism": "euphemistic",
    "ironic": "ironic", "figuratively": "figurative", "broadly": "broadly",
    "analogy": "by-analogy", "metonymically": "metonymically", "hyperbole": "hyperbole",
}
# `raw_tags`（源头原文，自由文本）→ 我们的键。**逐字白名单**，一个字符不同就不收。
_RAW = {
    "Proverbial": "proverb",            # fr 32
    "idiom": "idiom",                   # en 1
    "Par plaisanterie": "ironic",       # fr 16（ru 同款：jocular／戲謔 → ironic）
    "jocular": "ironic",                # en 1
    "Ironiquement": "ironic", "Par ironie": "ironic", "Sarcasme": "ironic",
    "Figuré": "figurative",
}
# ⚠️ 有意不收（写在这里，免得下一个人以为是漏了）：
#   `Plus rare`（较罕见，与 `rare` 是两级，不抹平）、`Parfois ironique`（「有时」）、
#   `Par moquerie`／`Par dérision`（嘲弄，非讽刺）、`Expression`／`American saying`（各 1，含义不明）。


def example_tags(x):
    """源头一条例句（dict）→ 我们的键集合（可能为空）。"""
    out = set()
    for t in x.get("tags") or ():
        k = _TAGS.get(t)
        if k:
            out.add(k)
    for t in x.get("raw_tags") or ():
        k = _RAW.get(t)
        if k:
            out.add(k)
    return out


def join_tags(keys):
    """键集合 → 入库字符串（`|` 分隔、按 EXAMPLE_TAG_ORDER 排）；空集 → None。"""
    ks = [k for k in EXAMPLE_TAG_ORDER if k in keys]
    return "|".join(ks) if ks else None


def bad_tag_value(v):
    """回归闸 E4 的判据：值域外的键、重复、或没按 EXAMPLE_TAG_ORDER 排。"""
    if v is None:
        return False
    ks = v.split("|")
    if any(k not in EXAMPLE_TAG_ORDER for k in ks):
        return True
    return ks != [k for k in EXAMPLE_TAG_ORDER if k in ks]


# 回填后带标签的行数 —— **独立声明**，不从现状推（`[[expectation-must-be-declared]]`）。
# 回归闸 E5 用它：少了＝标签被某次重建静默丢掉。改它必须写理由。
EXPECT_TAGGED = 4909   # 2026-11-06 首次回填：dump 给的（词,句）4,909 个，库里全部找到


def _con_ro():
    import paths
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def collect():
    """→ {(word,text): tags字符串}。复用 `ingest_examples.harvest` 的同一套读法与去重键。"""
    import ingest_examples as IE
    con = _con_ro()
    rows, st = IE.harvest(con)
    con.close()
    return {(r["word"], r["text"]): r["tags"] for r in rows if r.get("tags")}, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    import dbtool
    import paths

    if a.verify:
        return verify()

    want, st = collect()
    con = _con_ro()
    have = {(w, t): i for i, w, t in con.execute("SELECT id, word, text FROM example")}
    has_col = any(r[1] == "tags" for r in con.execute("PRAGMA table_info(example)"))
    cur = dict(con.execute("SELECT id, tags FROM example WHERE tags IS NOT NULL")) if has_col else {}
    con.close()

    miss = [k for k in want if k not in have]
    upd = [(v, have[k]) for k, v in want.items() if k in have and cur.get(have[k]) != v]
    by = Counter()
    for v in want.values():
        for k in v.split("|"):
            by[k] += 1
    print("■ dump 里带标签的（词，句子）%s 个；库里找得到 %s；找不到 %s"
          % (format(len(want), ","), format(len(want) - len(miss), ","), format(len(miss), ",")))
    for k in EXAMPLE_TAG_ORDER:
        print("   %-14s %6s" % (k, format(by[k], ",")))
    for k in miss[:5]:
        print("   找不到：%s ｜ %s" % (k[0], k[1][:70]))
    print("■ 要写 %s 行（库里已有且相同的不写）" % format(len(upd), ","))
    if miss:
        # 找不到＝ingest 之后被删掉的行（E1 那类非例句）—— 必须为 0 才说明键对得上
        print("🔴 有标签的句子在库里找不到 —— 先查清再写")
        return 1
    if not a.apply:
        print("(未加 --apply，未写库)")
        return 0
    # ⚠️ fr 的 dbtool 只追踪 `dict` 的列和各表行数，`example.tags` 不在它的清单里 ⇒
    #    expect 写空（行数一条都不许变），列的计数由下面自己断言。
    before = len(cur)
    with dbtool.session("b31-example-tags", expect={}) as s:
        if not has_col:
            s.execute("ALTER TABLE example ADD COLUMN tags TEXT")
        s.executemany("UPDATE example SET tags=? WHERE id=?", upd)
    con = _con_ro()
    after = con.execute("SELECT count(*) FROM example WHERE tags IS NOT NULL").fetchone()[0]
    con.close()
    if after != len(want):
        print("🔴 写后带标签 %s 行 ≠ dump 给的 %s（写前 %s）" % (after, len(want), before))
        return 1
    return verify()


def verify():
    con = _con_ro()
    n = con.execute("SELECT count(*) FROM example WHERE tags IS NOT NULL").fetchone()[0]
    bad = sum(1 for (v,) in con.execute("SELECT tags FROM example WHERE tags IS NOT NULL")
              if bad_tag_value(v))
    print("■ example.tags 非空 %s 行（期望 %s）｜ 值域外／乱序 %d"
          % (format(n, ","), EXPECT_TAGGED, bad))
    ok = bad == 0 and (EXPECT_TAGGED is None or n == EXPECT_TAGGED)
    print("✓ 通过" if ok else "🔴 未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
