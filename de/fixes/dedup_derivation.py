#!/usr/bin/env python3
"""删掉与构词行重复、且标签零信息的那批「变形」行。2026-09-04（收尾单 C32）。

═══ 缺陷（契约闸逮到的，也是那天唯一一条「红的是数据不是断言」）═══
同一个 (词形, 原形) 存了两行，说法还不一致：
    Reifen  kind=derivation  label=名词化不定式   ← 正确、有信息
            kind=inflection  label=变形          ← 泛泛，零信息
读者在页面上看到 `reifen` 两次，其中一次被标成「变形」——**正是 C13 那条外审意见要防的**
（`Häuslein ← Haus 指小词` 与 `Häuser ← Haus 复数` 并排会被当成格形式）。

═══ 判据：什么叫「冗余」═══
同一个 `(word_id, base)`：
  · 有一行 `kind='derivation'`（源头明确说这是构词）
  · **且**另一行 `kind<>'derivation'` 而 `label_zh` 恰好是光秃秃的「变形」
⇒ 删掉后者不丢任何信息。

🔴 **理由要写准**：不是「被构词行完全覆盖」—— 干跑抽样当场证伪了那个说法：
   `Tore` 的构词行本身是错的（`指小词 tags=["diminutive"] src=kk-zh-forms`，
   而 `Tore` 是 `Tor` 的**复数**）。真正站得住的理由是**两条**，缺一不可：
     · 被删的那行标签是光秃秃的「变形」⇒ **零信息**；
     · 同一个 `(word_id, base)` **另有其它行**（`Tore` 那对另有 6 条正确的变形行）。
   ⇒ 删一条零信息、且不是该对唯一一条的行，不可能让读者少看到东西。
   ⚠️ 那类"构词行本身标错"的问题另计：全库标成「指小词」却同对另有「复数」变形行的
     只有 **3 条**（`Tore`／`Spillbäume`／`Männerchen`），2,823 条指小词里的 0.1%，
     记账不追（收尾单 C33）。
⚠️ **对照组是量过的**：同样有构词行、但另一行标签**不**泛泛的只有 **16** 条 ——
   那 16 条各自说了别的事（真的语法形式），**不在删除范围**。
   判据窄到这一步才敢删（`[[criteria-narrower-than-you-think]]`）。

═══ ⚠️ 关于可逆 ═══
`[[prefer-reversible-designs]]`：删行不可逆。这里可接受，理由有三：
  ① 判据只圈中「被另一行完全覆盖」的，删掉不丢信息；
  ② `dbtool.session` 写库前自动备份（可整库回滚）；
  ③ 这些行**可以从 dump 重新生成** —— 它们是 2c/2d 扫 `form_of` 的产物，重跑就有。
🔴 但**根因在生成侧**：2c 读 `form_of` 时不知道同一对已经有构词行了。
   本轮先清存量并落账；下一轮重跑 2b/2c 时要在生成侧去重，否则会回来
   （`[[replay-scripts-undo-fixes]]`）。⇒ 已在回归闸加断言盯住。

用法（在 de/ 目录下）：
    python3 -u fixes/dedup_derivation.py
    python3 -u fixes/dedup_derivation.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

FIND = """
SELECT a.id, d.word, a.base, a.label_zh
  FROM inflection a JOIN dict d ON d.id = a.word_id
 WHERE a.kind <> 'derivation' AND a.label_zh = '变形'
   AND EXISTS(SELECT 1 FROM inflection b
               WHERE b.word_id = a.word_id AND b.base = a.base
                 AND b.kind = 'derivation')
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(FIND).fetchall()
    print("■ 冗余行 %s 条" % f(len(rows)))
    print("   样本（这一对已经有一条正确的构词行了）：")
    for rid, w, base, lab in rows[:8]:
        d = con.execute("SELECT label_zh FROM inflection i JOIN dict x ON x.id=i.word_id "
                        "WHERE x.word=? AND i.base=? AND i.kind='derivation' LIMIT 1",
                        (w, base)).fetchone()
        print("     %-22s → %-18s 删「%s」／留「%s」" % (w[:22], base[:18], lab, d[0] if d else "?"))
    con.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    # 🔴 `expect` 比的是**增量**，删除要传负数。第一版传了 `{}` ——
    #    `dbtool` 当场报「未声明的表 inflection 行数变了 -408」并给出回滚命令。
    #    **这是闸按设计工作**：没在 expect 里显式声明的表，行数必须零变化。
    with dbtool.session("keep-v3-c32-dedup-deriv",
                        expect={"#inflection": -len(rows)}) as s:
        s.executemany("DELETE FROM inflection WHERE id=?", [(r[0],) for r in rows])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = len(con.execute(FIND).fetchall())
    print("\n═══ 闸② ═══")
    print("   %s 冗余的泛泛「变形」行  %s  期望 0" % ("✓" if not left else "🔴", f(left)))
    con.close()
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
