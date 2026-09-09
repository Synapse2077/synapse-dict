#!/usr/bin/env python3
"""把**不是例句**的三族从例句区藏起来（`hidden=1`）。2026-09-08，阶段 5e 开跑前。

═══ 怎么发现的 ═══
5e 切片 7,000 条里有 22 条空输出、11 条译文无汉字。**那不是模型的错** ——
回源一看，那些行根本不是例句：

    For quotations using this term, see Citations:orange.   ← MediaWiki 维护行
    Near-synonyms: unappreciative, unthankful               ← 关系数据错放进例句表
    poison + -ous → poisonous                               ← 构词式

模型原样回传是**对的**（规则 6/7）。错的是这些行出现在例句表里，
而 `english.ts` 只过滤 `hidden=0` ⇒ **它们正在当例句渲染给读者**。

═══ 🔴 判据宁可窄（[[criteria-narrower-than-you-think]]）═══
同一次扫描里还有两族**看着像但不是**的，逐条回源读过，**一条都不动**：

  · 无空格 1,408 条 —— `a-` 下举 `asunder`、`pink` 下举 `pink-collar`。
    **前缀/构词成分的词条下举派生词是正经用法**，藏了就是丢信息。
  · `See also` / `Compare …` 92 条 —— 打出来读，全是真句子
    （`Compare Milton's Epics with the other great Epics of the world.`）。
    **靠开头几个词判断内容，正是"拿形式当判据"那个病。**

═══ ⭐ 藏不删（[[prefer-reversible-designs]]）═══
`hidden=1` 保留全部行与 `sense_id` 挂载。将来若要把 `Near-synonyms:`
提升成真正的关系层，源数据一个字节没丢。

    cd en && python3 -u fixes/hide_non_examples.py          # 干跑
    cd en && python3 -u fixes/hide_non_examples.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import sqlite3

import dbtool
import paths

# (族名, WHERE 片段) —— 每一族都逐条回源读过样本
FAMS = [
    ("维护提示 For quotations…see Citations:",
     "text LIKE 'For quotations using this term, see Citations:%'"),
    # 🔴 `INSTR(text,':')<=14` 不是可有可无的收窄：没有它，
    #    `'Synonym%:%'` 会命中「Synonyms are useful in writing: …」这种**真句子**。
    #    实测当前 3,840 条冒号**全部**在 14 字符内（放宽模式后专门回源查的），
    #    但"今天恰好没有反例"不等于判据安全 ⇒ **把核验写进判据本身**。
    ("关系数据错放：*-nyms:",
     "INSTR(text,':') BETWEEN 1 AND 14 AND "
     "(text LIKE 'Near-synonym%:%' OR text LIKE 'Synonym%:%' "
     "OR text LIKE 'Antonym%:%' OR text LIKE 'Hypernym%:%' "
     "OR text LIKE 'Hyponym%:%' OR text LIKE 'Meronym%:%' "
     "OR text LIKE 'Holonym%:%')"),
    # 🔴 `[see title]` 是维基词典的占位符，意思是「引文就是标题（见 ref）」——
    #    它不是例句。100 条，而我们**为它买过中文**（模型老实地把标题译了）。
    # 方括号与圆括号两种写法都有 —— 只补一种就是「修了报出来的那一个」
    ("占位符 [see title]",
     "TRIM(text) IN ('[see title]', '(see title)')"),
    ("关系数据错放：Coordinate term:",
     "INSTR(text,':') BETWEEN 1 AND 20 AND text LIKE 'Coordinate term%:%'"),
]
WHERE = " OR ".join("(%s)" % w for _, w in FAMS)


def report(con):
    q = con.execute
    tot, = q("SELECT COUNT(*) FROM example").fetchone()
    print("═══ 不是例句的三族 ═══")
    n_all = 0
    for name, w in FAMS:
        n, = q("SELECT COUNT(*) FROM example WHERE hidden=0 AND (%s)" % w).fetchone()
        n_all += n
        print("   %-34s %6s" % (name, format(n, ",")))
    print("   %-34s %6s ／ 全库 %s ＝ %.2f%%"
          % ("合计（当前可见的）", format(n_all, ","), format(tot, ","),
             100 * n_all / max(tot, 1)))
    print("\n   ⚠️ **有意不动**的两族（回源读过，是正经内容）：")
    for name, w in (("无空格（前缀词条下的派生词）", "INSTR(text,' ')=0"),
                    ("See also / Compare 开头（真句子）",
                     "text LIKE 'See also%' OR text LIKE 'Compare %'")):
        n, = q("SELECT COUNT(*) FROM example WHERE hidden=0 AND (%s)" % w).fetchone()
        print("      %-32s %6s" % (name, format(n, ",")))
    return n_all


def gates(con, moved, before):
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("三族在例句区一条不剩",
         q("SELECT COUNT(*) FROM example WHERE hidden=0 AND (%s)" % WHERE), 0),
        ("藏起来的正好是这么多",
         q("SELECT COUNT(*) FROM example WHERE hidden=1"), before["hidden"] + moved),
        ("🔴 总行数没变（藏不删）",
         q("SELECT COUNT(*) FROM example"), before["tot"]),
        # 🔴 负控①：有意不动的两族必须**还在**
        ("🔴 负控 前缀派生词没被误伤",
         q("SELECT COUNT(*) FROM example WHERE hidden=0 AND INSTR(text,' ')=0"),
         before["nospace"]),
        ("🔴 负控 See also/Compare 没被误伤",
         q("SELECT COUNT(*) FROM example WHERE hidden=0 AND "
           "(text LIKE 'See also%' OR text LIKE 'Compare %')"), before["seealso"]),
        # 🔴 负控②：构词式**有意留在例句区**（只排出翻译池，见 translate_examples.pool）
        ("🔴 负控 构词式仍可见",
         q("SELECT COUNT(*) FROM example WHERE hidden=0 AND text LIKE '%+%' "
           "AND text LIKE '%→%'"), before["formula"]),
        # 🔴🔴 **常驻不变量：藏起来的例句不许留着中文。**
        #    第一次跑闸就在这里报了 55 条 —— 切片里模型老实地把
        #    `Near-synonym: whitlow` 译成「近义词：瘭疽。」，当例句渲染就是废话。
        #    藏了正文却留着译文 ＝ 读者看不见、库里还占着位、下一轮统计还会把它算成"已翻"。
        ("🔴 藏起来的例句没有留下中文",
         q("SELECT COUNT(*) FROM example e JOIN example_gloss g ON g.example_id=e.id "
           "WHERE e.hidden=1"), 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-32s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n = report(con)
    q = con.execute
    before = {
        "tot": q("SELECT COUNT(*) FROM example").fetchone()[0],
        "hidden": q("SELECT COUNT(*) FROM example WHERE hidden=1").fetchone()[0],
        "nospace": q("SELECT COUNT(*) FROM example WHERE hidden=0 "
                     "AND INSTR(text,' ')=0").fetchone()[0],
        "seealso": q("SELECT COUNT(*) FROM example WHERE hidden=0 AND "
                     "(text LIKE 'See also%' OR text LIKE 'Compare %')").fetchone()[0],
        "formula": q("SELECT COUNT(*) FROM example WHERE hidden=0 AND text LIKE '%+%' "
                     "AND text LIKE '%→%'").fetchone()[0],
    }
    print("\n   样本：")
    for name, w in FAMS:
        for (t,) in q("SELECT text FROM example WHERE hidden=0 AND (%s) LIMIT 2" % w):
            print("      %s" % t[:88])
    con.close()
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0
    # 🔴 `expect` 是**增量不是总数**（这个坑今天已经踩过两次）：先算出这次要
    #    连带删掉多少条译文，再申报。写死数字会被字面量闸拦下，也必然过期。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    drop, = con.execute(
        "SELECT COUNT(*) FROM example_gloss g JOIN example e ON e.id=g.example_id "
        "WHERE e.hidden=1 OR (e.hidden=0 AND (%s))"
        % WHERE.replace("text", "e.text")).fetchone()
    con.close()
    with dbtool.session("keep-v3-hide-non-examples",
                        expect={"#example_gloss": -drop}) as s:
        s.execute("UPDATE example SET hidden=1 WHERE hidden=0 AND (%s)" % WHERE)
        # 正文藏了，译文跟着走 —— 见闸里那条常驻不变量
        s.execute("DELETE FROM example_gloss WHERE example_id IN "
                  "(SELECT id FROM example WHERE hidden=1)")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = gates(con, n, before)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
