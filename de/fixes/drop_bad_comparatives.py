#!/usr/bin/env python3
"""收尾单 C7：**清掉造出来的比较级／最高级**（形式在全库根本不存在的那批）。de，2026-09-05。

═══ C7 是什么 ═══
七月建库时用豆包给德语一等字段补空，**没留来源标记**，且已知含错：
`in` 的页面上印着「比较级 iner／最高级 am insten」。
C7 自己写着判据：`entry` 落地之后这件事**已经是确定性的** ——
kaikki 给的值会进 `entry`，豆包补的不会。实测「仅 dict 有」**27,262 条**
（comparative/superlative 各 6,205、plural 9,009、genitive 3,711、其余 2,132）。

═══ 🔴 判据被数据打回**三次**，每次都收窄 ═══
① **按词性圈**（比较级只属于形容词）⇒ 命中 **0 条**。
   `in` 的 pos 是 `adj/contr/prep` —— 德语 `in` 确实能当形容词（「时髦的」）。
② **按「说不出来源」整批圈**（27,262）⇒ 读样本发现**绝大多数是对的**：
   `sorgen für → gesorgt`、`Van-Allen-Gürtel → Van-Allen-Gürtel`（复数同形）、
   `Kernchemie → -`（有意写「无复数」）、`offenes Ohr → offenen Ohres`。
   ⇒ **「说不清来源」不等于「错」**。那是 C1 回填 `_src` 的事，不是删。
③ **按源头的 `not-comparable` 标圈**（5,998）⇒ 控制组分离得极漂亮
   （有 entry 背书的 0.4% vs 无背书的 96.7%，240 倍），**但它是规定性的、覆盖过宽**：
   `parlamentarisch → parlamentarischer`、`steinhart → steinharter`、
   `telefonisch → telefonischer` 德语实际都在用，删了是丢真数据。

═══ ⭐ 第四版才对：**这个形式在全库 120 万词形里存不存在** ═══
两个**独立**信号交叉之后才看清：③ 的 5,998 条里，
  · 形式**存在**的 5,827 条 —— 争议在「该不该比较」，是词典学判断，**不动**；
  · 形式**不存在**的 171 条 —— 毛病根本不是「不该比较」，**是拼错**：
      `anglophon → anglophonerer`（双重比较级）  `inhaliert → inhaltierter`（凭空多个 t）
      `disziplinarisch → disziplinärischer`（元音变错）  `handzahm → handzamer`（吞掉 h）
      `stellar → stellarrer`（多个 r）  `esslöffelweise → esslöffelweisier`

⇒ 判据 = **无 entry 背书 且 声称的比较级不在 `dict` 里**，命中 **254 条**。
  逐条读过：英法外来词硬套德语规则（`butch → butcher`、`crazy → crazier`、
  `awkward → awkwarder`、`porno → pornoser`、`passé → passéer`、`online → onlineer`）
  ＋ 拼写错（`lettisch → letischer` 漏了个 t、`arkan → arkanker`）。

**控制组（判据要是对的，两边应当天差地别）**：
    有 entry 背书的比较级里，形式不存在      8 / 5,832 = **0.14%**
    无背书的里，            形式不存在    254 / 6,205 = **4.10%**   ⇒ 29 倍分离

═══ 残差如实报（`[[measure-landing-not-source]]`：修判据三轮就停手，残差当上界）═══
· 254 里有少数其实是对的（`lauwarm → lauwärmer`、`klitschnass → klitschnässer` 德语在用）
  ⇒ 删掉它们是**拿「错」换「缺」**，方向与 `FRAMEWORK §一` 一致，代价如实记在 C7。
· 5,827 条「源头说不可比较、形式却存在」的**有意不动** —— 那是源头的规定性标注与
  实际用法之争，不是我们的数据缺陷。
· 最高级无法用同一把尺子验（`am …sten` 是短语，永远不会是词头）
  ⇒ **跟着比较级一起删**：同一个过程造出来的，比较级是假的，最高级也是。

用法：
    python3 fixes/drop_bad_comparatives.py            # 试算
    python3 fixes/drop_bad_comparatives.py --write
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                                                    # noqa: E402

f = lambda n: format(n, ",")

# 无 entry 背书 —— C7 自己定的判据（kaikki 给的值会进 entry，豆包补的不会）
UNBACKED = ("d.comparative IS NOT NULL AND TRIM(d.comparative)<>'' AND NOT EXISTS("
            "SELECT 1 FROM entry e WHERE e.word_id=d.id "
            "AND e.comparative IS NOT NULL AND TRIM(e.comparative)<>'')")
# 声称的形式在全库不存在 —— 第二个**独立**信号
ABSENT = "NOT EXISTS(SELECT 1 FROM dict x WHERE x.word=d.comparative)"
SQL = ("SELECT d.id, d.word, d.pos, d.comparative, d.superlative FROM dict d "
       "WHERE (%s) AND %s" % (UNBACKED, ABSENT))


def bad_rows(con):
    """→ [(id, 词形, 词性, 比较级, 最高级)]。**判据只许这一份**，闸 import 它。"""
    return con.execute(SQL).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = bad_rows(con)
    nc = sum(1 for r in rows if (r[3] or "").strip())
    ns = sum(1 for r in rows if (r[4] or "").strip())
    print("■ 要清 %s 个词形 ／ 比较级 %s 个值 ／ 最高级 %s 个值" % (f(len(rows)), f(nc), f(ns)))
    for _, w, p, c, s in rows[:10]:
        print("   %-24s %-14s → %-18s %s" % (w[:24], (p or "")[:14], (c or "")[:18], (s or "")[:22]))
    # 控制组每次都打出来：判据要是漂了，这两个数会靠拢
    tot = con.execute("SELECT COUNT(*) FROM dict d WHERE %s" % UNBACKED).fetchone()[0]
    bk = con.execute(
        "SELECT COUNT(*) FROM dict d WHERE d.comparative IS NOT NULL AND TRIM(d.comparative)<>'' "
        "AND EXISTS(SELECT 1 FROM entry e WHERE e.word_id=d.id AND e.comparative IS NOT NULL "
        "AND TRIM(e.comparative)<>'')").fetchone()[0]
    bka = con.execute(
        "SELECT COUNT(*) FROM dict d WHERE d.comparative IS NOT NULL AND TRIM(d.comparative)<>'' "
        "AND EXISTS(SELECT 1 FROM entry e WHERE e.word_id=d.id AND e.comparative IS NOT NULL "
        "AND TRIM(e.comparative)<>'') AND %s" % ABSENT).fetchone()[0]
    print("\n■ 控制组   无背书 %s/%s = %.2f%%   ｜   有背书 %s/%s = %.2f%%"
          % (f(len(rows)), f(tot), 100.0 * len(rows) / max(tot, 1),
             f(bka), f(bk), 100.0 * bka / max(bk, 1)))
    con.close()

    if not a.write:
        print("\n(未加 --write，未写库)")
        return 0

    import dbtool
    with dbtool.session("keep-v3-c7-bad-comparatives",
                        expect={"comparative": -nc, "superlative": -ns}) as s:
        s.executemany("UPDATE dict SET comparative=NULL, superlative=NULL WHERE id=?",
                      [(r[0],) for r in rows])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = len(bad_rows(con))
    kept = con.execute(
        "SELECT COUNT(*) FROM dict d WHERE d.comparative IS NOT NULL AND EXISTS("
        "SELECT 1 FROM entry e WHERE e.word_id=d.id AND e.comparative IS NOT NULL "
        "AND TRIM(e.comparative)<>'')").fetchone()[0]
    print("\n■ 闸：造出来的比较级 → %s（期望 0）" % f(left))
    # ⚠️ 反向闸：**有背书的一条都不许被误伤**。「不在判据范围内」要真的能验，不能靠我读代码确信。
    print("■ 反向闸：有 entry 背书的比较级仍在 → %s（本步之前 5,832）" % f(kept))
    con.close()
    return 0 if left == 0 and kept == 5832 else 1


if __name__ == "__main__":
    sys.exit(main())
