#!/usr/bin/env python3
"""日语版的**对译表格子**被当成法语例句。2026-08-31 渲染评审读出来的。

═══ 怎么发现的 ═══
用 `render-dump` 把 fr 的 28 个词按用户真正看到的样子导出来读，在 `pies` 那页看见：

    œuvres pies - 慈善事業      ← 例句原文里粘着**繁体中文译文**
    慈善事业                     ← 下一行才是我们的中文

顺着查：这一族全部来自 **ja-edition**，是日语版维基词典的**对译表格子**，不是例句：

    eau chaude - 湯          vingt ans - 20歳       bière forte - 強いビール
    chat noir 黒猫           en semaine 平日に      aller au zoo 動物園に行く
    記: Tu とその活用形は…（纯日文用法说明）

⚠️ **不带破折号的也是同一回事**（`chat noir 黒猫`）—— 所以判据不能写成「含 ` - `」。

═══ 判据（按含义）═══
「**来自日语版、且文本里有日文**」⇒ 它是对译格子，不是法语例句。
🔴 **不许写成「含 CJK 就删」**：`pinyiniser` 的例句
   `Ceci dit, 盆栽 en chinois standard se prononce ou se pinyinise pénzāi - cultiver dans un pot.`
   是**真法语句子**（来自 fr-edition），只是在讨论一个汉字词。按来源限定才躲得开它。
⚠️ ja-edition 另有 144 条**不含日文**的（`Je l'aime.`／`raison d'être`），**一条不动** ——
   里面既有真句子也有词组，不是同一族。

`hidden=1`，不删数据。

用法（在 fr/ 目录下）：
    python3 fixes/hide_ja_translation_cells.py
    python3 fixes/hide_ja_translation_cells.py --apply
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

JA = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")

# ⭐ 负控：这条**必须**留下 —— 真法语句子，只是在讨论汉字词，且来自 fr 版。
NEG = ("fr-edition",
       "Ceci dit, 盆栽 en chinois standard se prononce ou se pinyinise "
       "pénzāi - cultiver dans un pot.")


def is_cell(src, text):
    """判据：来自日语版 **且** 含日文 ⇒ 对译表格子。"""
    return src == "ja-edition" and bool(JA.search(text or ""))


def main(a):
    print("■ 负控：真法语句子（fr 版、句中含汉字）必须留下")
    print("   %s %s" % ("🔴 被误删" if is_cell(*NEG) else "✅", NEG[1][:56]))
    if is_cell(*NEG):
        return 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = [(i, w, t) for i, w, t, s in con.execute(
        "SELECT id, word, text, src FROM example WHERE COALESCE(hidden,0)=0")
        if is_cell(s, t)]
    keep = con.execute(
        "SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0 AND src='ja-edition'"
    ).fetchone()[0] - len(todo)
    con.close()
    f = lambda n: format(n, ",")
    print("\n■ 对译格子（要隐）：%s 条；ja 版**不含日文**的 %s 条一条不动" % (f(len(todo)), f(keep)))
    for _i, w, t in todo[:10]:
        print("   %-18s %s" % (w[:18], t[:52]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("hide-fr-ja-cells") as s:
        s.executemany("UPDATE example SET hidden=1 WHERE id=?", [(i,) for i, *_ in todo])
    print("\n✓ 已隐 %s 条（数据没删）" % f(len(todo)))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
