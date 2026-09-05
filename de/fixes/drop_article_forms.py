#!/usr/bin/env python3
"""删掉「冠词被写成名词变格形式」的行。2026-09-04（收尾单 C34）。

═══ 缺陷（读渲染成品读出来的，闸够不到）═══
`die` 的词条页上「词形还原」一栏印着：

    20-Jährige 主格 ／ 20-Jährige 宾格 ／ 20-Jähriger 主格 …

**这是在说 `die` 是 `20-Jährige` 的主格形式** —— 错的。`die` 是冠词。
根因：源头的名词变格表**带冠词列**（`das Junge` / `die Frau`），
解析时把冠词那一格当成了「词形」。主力来源 `kk-fr-forms`（法语版变格表）。

⚠️ 与阶段 3 拦下的那个是**同一个病、不同的列**：那次是「德语变位表把**主语代词**
   写进单元格」（`ich abstottre`），靠抽样反验在写进计划前就拦下了；
   这次是**冠词列**，混在 536 万行变形里，**任何按行数/不变量做的闸都看不见**
   —— 只有把 `die` 的页面渲染出来才看得见。
   （`[[it-display-layer-stage8]]`：接上展示层是独立一道闸。）

═══ 判据：按含义 ═══
**冠词不可能是名词的变格形式。**
  · 词形本身是冠词族（`der/die/das/den/dem/des/ein/eine/…`）
  · **且** `base` 不在冠词族里（`die ← der 阴性单数主格` 是**对的**，`der` 是定冠词词元）
⇒ 两条同时成立才删。
🔴 第一版只写了第一条，量出 3,206 行 —— 里面混着 213 行**正确**的冠词内部变格。
   收窄后 2,993 行。**「冠词出现在变形层」不是缺陷，「冠词指向名词」才是。**

⚠️ 可逆性：删行不可逆，但这些行可从 dump 重生成（`[[prefer-reversible-designs]]`），
   且 `dbtool.session` 写库前自动整库备份。
🔴 **根因在生成侧**：`link_edition_forms` 读 `forms` 时不认得"这一格是冠词列"。
   本轮先清存量并落账；重跑 2c 会让它回来 ⇒ 回归闸加断言盯住
   （`[[replay-scripts-undo-fixes]]`）。

用法（在 de/ 目录下）：
    python3 -u fixes/drop_article_forms.py
    python3 -u fixes/drop_article_forms.py --apply
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

# 冠词族。**这张表只许一份**，回归闸 import 它。
# ⚠️ 只列**冠词**，不列指示代词（`dieser`）与关系代词（`welcher`）——
#    那些确实可能出现在别的表里，没量过就不动（`[[criteria-narrower-than-you-think]]`）。
ARTICLES = ("der", "die", "das", "den", "dem", "des",
            "ein", "eine", "einen", "einem", "eines", "einer")
_PH = ",".join("?" * len(ARTICLES))

FIND = ("SELECT i.id, d.word, i.base, i.label_zh, i.src "
        "  FROM inflection i JOIN dict d ON d.id = i.word_id "
        " WHERE d.word IN (%s) AND i.base NOT IN (%s)" % (_PH, _PH))
COUNT = ("SELECT COUNT(*) FROM inflection i JOIN dict d ON d.id = i.word_id "
         " WHERE d.word IN (%s) AND i.base NOT IN (%s)" % (_PH, _PH))


def bad_rows(con):
    """→ 命中的行数。**回归闸 import 这个函数，不自己写一遍 SQL。**"""
    return con.execute(COUNT, ARTICLES + ARTICLES).fetchone()[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(FIND, ARTICLES + ARTICLES).fetchall()
    by_src, by_word = Counter(), Counter()
    for _rid, w, _b, _l, src in rows:
        by_src[src] += 1
        by_word[w] += 1
    print("■ 命中 %s 行" % f(len(rows)))
    print("   按来源：" + "  ".join("%s=%s" % (k, f(v)) for k, v in by_src.most_common()))
    print("   按词形：" + "  ".join("%s=%s" % (k, f(v)) for k, v in by_word.most_common(6)))
    print("   样本：")
    for _rid, w, b, lab, src in rows[:6]:
        print("     %-6s ← base=%-20s %-14s %s" % (w, b[:20], lab, src))
    keep = con.execute(
        "SELECT d.word, i.base, i.label_zh FROM inflection i JOIN dict d ON d.id=i.word_id "
        " WHERE d.word IN (%s) AND i.base IN (%s) LIMIT 5" % (_PH, _PH),
        ARTICLES + ARTICLES).fetchall()
    print("   ── 反验：保留的（冠词内部变格，**不该删**）──")
    for w, b, lab in keep:
        print("     %-6s ← base=%-20s %s" % (w, b, lab))
    con.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("keep-v3-c34-article-forms",
                        expect={"#inflection": -len(rows)}) as s:
        s.executemany("DELETE FROM inflection WHERE id=?", [(r[0],) for r in rows])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = bad_rows(con)
    print("\n═══ 闸② ═══")
    print("   %s 冠词指向非冠词词元  %s  期望 0" % ("✓" if not left else "🔴", f(left)))
    con.close()
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
