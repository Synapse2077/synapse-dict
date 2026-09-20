#!/usr/bin/env python3
"""核心词等级（`dict.core_level`）。2026-09-19。零模型调用、零成本。

═══ 🔴🔴 这一列**不是权威难度，是内部尺子** ═══
JLPT 官方**自 2010 年改制后就不再公布词汇表**，而且是有意不公布（不鼓励照词表背）。
市面上所有 N5–N1 表都是民间按 2010 年前旧《出題基準》重建并重新切级的，
**没有一份是官方的**。我们用的这份（Waller 表，CC BY）整理者自己写着
「essentially an educated guess」，编于 10 年前，且有 N1 词出现在 2021 年 N2 考卷上。

⇒ **只当内部尺子**：挑核心词、算覆盖率、排序参考。
  **不作读者可见的难度标签** —— 印成「JLPT N2」就是断言一件我们保证不了的事，
  而本项目铁律是**错比缺更伤权威**。
  回归闸 **X2** 锁住「这一列不出现在任何渲染输出里」，改主意要先动那条闸。

═══ 为什么要有它 ═══
`docs/JA_PLAN.md` §四.2 挂着「声调够不够上页面」，那需要**核心词覆盖率**而不是全库覆盖率
（全库 24.9 万词元里大量是生僻词，7.4% 这个数没有决策价值）。
接上之后实测：核心词 42.4%、前 1,000 内容词 49.9% —— 与自有 `freq_zipf` 前 5,000 的
42.6% **两把独立尺子收敛**，结论不依赖任何一份词表。

═══ 判据 ═══
- 匹配**只用词形**（先汉字写法、再假名写法），**不做「按假名读音兜底」**。
  实测兜底只能多捞 3 条，而它要在多个同音词里随便挑一个 ——
  那就是 `baseOf LIMIT 1` 那个老毛病：**随便挑一个＝在页面上断言一件假事**。
- 同一词形跨级的 179 条取**最基础的那一级**（`私` 在 N5 与 N1 各有一条，
  因为 わたし 与 わたくし 是两个读音）。读者第一次遇到这个词形就是那一级。

跑（在仓库根）：
    python3 -u ja/pipeline/intake_core_level.py
    python3 -u ja/pipeline/intake_core_level.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import csv
import sqlite3

import dbtool
import paths

# N5 最基础 → 1；N1 最高阶 → 5。**存序数不存字符串**：排序、范围约束、索引都更干净，
# 而且序数不长得像官方等级标签（`core_level=1` 不会被误读成「JLPT N1」）。
LEVEL = {"n5": 1, "n4": 2, "n3": 3, "n2": 4, "n1": 5}
SRC = "waller-n5n1-ccby@2026-09-19"


def _assert_ja():
    assert paths.DB.name == "synapse-dict-ja.sqlite", "🔴 paths 不是 ja 的：%s" % paths.DB


def load():
    """→ `[(汉字写法, 假名写法, 级序数), …]`，原样返回两种写法，**不在这里挑**。

    🔴 挑哪一种写法要等到**查过库之后**才知道：第一版在这里就把词形定死成汉字写法，
       于是 `迚も`（＝とても）、`亜爾加里`（＝アルカリ）、`若し`（＝もし）这类
       **异表记/送假名差异**全部落空 —— 维基词典不收这些旧写法当词头，但假名写法收。
       63 条「未命中」里大部分是这么来的，而它们个个都是核心词。
       `[[criteria-narrower-than-you-think]]`：**先挑再查 ＝ 判据比它要描述的东西窄。**
    """
    rows = []
    stat = collections.Counter()
    for tag, lv in LEVEL.items():
        f = paths.CORE_LIST / ("%s.csv" % tag)
        assert f.exists(), "🔴 词表缺文件：%s（见该目录 README）" % f
        for r in csv.DictReader(open(f, encoding="utf-8")):
            stat["词表·%s" % tag.upper()] += 1
            rows.append((r["kanji"].strip(), r["kana"].strip(), lv))
    return rows, stat


def match(rows, w2i):
    """`[(汉字, 假名, 级)]` × dict → `({word_id: 级}, 未命中的条目)`。

    先试汉字写法、查不到退到假名写法；**不做「按假名读音兜底」** ——
    实测只多捞 3 条，而它要在多个同音词里随便挑一个，那就是 `baseOf LIMIT 1` 的老毛病。
    同一词形跨级取**最基础**的一级（`私` 在 N5 与 N1 各有一条，因为 わたし／わたくし 是两个读音）。
    """
    hit, miss = {}, []
    for kanji, kana, lv in rows:
        for form in (kanji, kana):
            if form and form in w2i:
                i = w2i[form]
                hit[i] = min(hit.get(i, 99), lv)
                break
        else:
            miss.append(kanji or kana)
    return hit, miss


def main():
    _assert_ja()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows, stat = load()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    w2i = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    have_col = "core_level" in {r[1] for r in con.execute("PRAGMA table_info(dict)")}
    before = con.execute("SELECT COUNT(core_level) FROM dict").fetchone()[0] if have_col else 0
    con.close()

    hit, miss = match(rows, w2i)
    for k, v in stat.most_common():
        print("   %-16s %6s" % (k, format(v, ",")))
    print("\n   词表 %s 条 ｜命中 dict %s 个词形 ｜**未命中 %s 条 = %.1f%%**"
          % (format(len(rows), ","), format(len(hit), ","),
             format(len(miss), ","), 100 * len(miss) / len(rows)))
    print("   未命中（残差必须说得出理由，不是「漏收」）：%s" % "、".join(sorted(miss)[:10]))
    by = collections.Counter(hit.values())
    print("   分级：" + " ｜ ".join("%s=%s" % (n, format(by[v], ","))
                                  for n, v in (("N5", 1), ("N4", 2), ("N3", 3),
                                               ("N2", 4), ("N1", 5))))

    i2w = {i: w for w, i in w2i.items()}
    dbtool.sample_check([(i2w[i], str(lv)) for i, lv in list(hit.items())[::max(1, len(hit) // 14)]],
                        12, ("词形", "级序数(1=N5)"))
    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    # 🔴 **先加列、再入库**（`[[ipa-provenance-columns]]`）：列进了 `dbtool.TRACK`，
    #    快照对「还不存在的列」是跳过的，所以同一个 session 里建列+填值是安全的。
    # ⚠️ `expect` 的键必须与 `dbtool.TRACK` 里写的**一字不差**：TRACK 登记的是
    #    裸列名 `core_level`（默认表就是 `dict`），我第一版写成 `dict.core_level`，
    #    闸当场报「未声明的列 core_level 变了 +7,989」—— 它没认错，是我写了两个名字。
    with dbtool.session("ja-core-level", expect={
            "core_level": len(hit) - before,
            "core_src": len(hit) - before}, invalidates=[]) as s:
        if not have_col:
            s.execute("ALTER TABLE dict ADD COLUMN core_level INTEGER")
            s.execute("ALTER TABLE dict ADD COLUMN core_src TEXT")
        s.executemany("UPDATE dict SET core_level=?, core_src=? WHERE id=?",
                      [(lv, SRC, i) for i, lv in hit.items()])


if __name__ == "__main__":
    main()
