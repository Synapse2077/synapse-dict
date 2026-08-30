#!/usr/bin/env python3
"""阶段 8 渲染时逮到：`example` 里有 214 行**根本不是例句，是引文行**。2026-08-30。

═══ 怎么发现的 ═══
阶段 8 把展示层切到 v3 之后，用 `render-dump` 按**用户真正看到的样子**导出 ——
`[[it-display-layer-stage8]]`：三层数据的闸全绿、库里查不出异常，
**真渲染出来立刻看见缺陷**。这次看见的是：

    Esse número tem duas casas decimais
    这个数字有两位小数。
    .                      ← ref 是一个孤零零的点

顺着查出三族源头残渣：

    ref 是纯标点        200 条   展示层清（不动数据）
    ref 含空字段        812 条   展示层清（`, Olgário Paulo Vogt, , EDUNISC`）
    🔴 text 是引文行     214 条   **本步处理** —— 它不是例句

    1997, República Exemplares 9 a 14, pag: 111
    2008. Maria Sylvia Cardoso Carneiro. Adultos com síndrome de Down…
    2013, Beto Silva, Júlio sumiu, Objetiva, página: 4

⇒ fr 那轮的同族（「456 行根本不是例句，全来自英文版」）在 pt 上是 214 行。

═══ 判据 ═══
**按含义**：这一行是「年份 + 作者 + 书名 + 页码」的著录格式，不是一句葡萄牙语。
形式上以四位年份开头、跟逗号或句点 —— 葡语例句不会这样起头。
⚠️ `hidden=1` **不删数据**，随时可 revert；阶段 8 之后若要改成渲染成出处行也还来得及。

用法（在 pt/ 目录下）：
    python3 fixes/hide_citation_examples.py
    python3 fixes/hide_citation_examples.py --apply
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 判据两版。第一版只认「年份 + 逗号/句点」，**反向查打回 14 条** ——
# `2024 Carlos Moedas, Liderar com as Pessoas, pag:?` 中间是**空格**，同样是引文。
# ⚠️ 但放宽不能一放到底：`2010: Odisseia Dois`（电影《2010太空漫游》的葡语名）
#    和 `2041 Como a inteligência artificial vai mudar sua vida…`（书名）
#    **是真词条的例句**，误伤了就是把内容删掉。
# ⇒ 收窄成「年份 + 分隔符 + 后文带**著录标记**」：`pag`/`página`/`p.`/`In:`/`ISBN`/出版社逗号串。
CITATION = re.compile(
    r"^\s*(1[5-9]|20)\d\d\s*[,.]"                      # ① 年份后直接跟逗号或句点
    r"|^\s*(1[5-9]|20)\d\d[\s:]+.*"                      # ② 年份后跟空格/冒号，且后文有著录标记
    r"(\bp[áa]g(ina)?\b|\bpag:|\bp\.\s*\d|\bIn:|ISBN|→ISBN)", re.I)


def plan(con):
    return [(i, w, t) for i, w, t in con.execute(
        "SELECT id, word, text FROM example WHERE COALESCE(hidden,0)=0")
        if CITATION.match(t)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = plan(con)
    # 反向查：判据会不会误伤真例句（以年份开头的正常句子）
    keep = [t for (_i, _w, t) in
            [(0, 0, r[0]) for r in con.execute(
                "SELECT text FROM example WHERE COALESCE(hidden,0)=0")]
            if re.match(r"^\s*(1[5-9]|20)\d\d\b", t) and not CITATION.match(t)]
    con.close()
    print("■ 引文行（要隐掉）：%d 条" % len(todo))
    for _i, w, t in todo[:8]:
        print("   %-14s %s" % (w[:14], t[:72]))
    print("\n■ 以年份开头但**不**判为引文的（判据放过的，人工核）：%d 条" % len(keep))
    for t in keep[:6]:
        print("   %s" % t[:72])
    if not todo or not a.apply:
        print("\n(未加 --apply，不写库)" if todo else "\n✓ 没有要改的")
        return 0
    with dbtool.session("fix-pt-hide-citations", expect={}) as s:
        s.executemany("UPDATE example SET hidden=1 WHERE id=?", [(i,) for i, _w, _t in todo])
    print("\n✓ 已隐掉 %d 条（**数据没删**）" % len(todo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
