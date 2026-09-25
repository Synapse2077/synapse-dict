#!/usr/bin/env python3
"""删掉 98 行**冒充 IPA 的 X-SAMPA**。ko，2026-09-25（阶段 9 接展示层时逮到）。

═══ 怎么发现的 ═══
阶段 9 写完 `korean.ts` 跑冒烟测，打印 `를` 的读音，看见：

    ɾɯɭ    (narrow)  ← 对
    4mL`   (phonemic) ← 🔴 这不是 IPA

`4mL\\`` 是 `ɾɯɭ` 的 **X-SAMPA** 写法（X-SAMPA 用 ASCII 表 IPA：
`4`＝ɾ、`M`＝ɯ、`L\\`＝ɭ、`_h`＝送气、`ts\\`＝t͡ɕ）。日文版的 `sounds.ipa`
里混着这一套，我们的收割器**照单全收**，于是页面上会把 `를`（韩语最基本的助词之一）
的读音印成 `/4mL\\/`。

🔴🔴 **这与 fr 那轮是同一个病，而教训没有跨语种传过来。**
   `[[criteria-narrower-than-you-think]]` 里记着：fr 把判据收窄成
   「IPA 里不该有大写拉丁字母」，**当场逮到 150 条 X-SAMPA 冒充 IPA**
   （`absOlysjO~` = `absɔlysjɔ̃`、`libR` = `libʁ`）。
   ⇒ 那次只修了 fr。ko 建库时没人想起来查。落账 `BACKLOG` **B10**（其余六门）。

⭐ **逮到它的不是闸，是把数据渲染出来看。**
   五道闸全绿、外锚闸双向恒等 —— 因为**源头确实就这么写**，
   恒等式问「我们收得对不对」，问不了「源头给的是不是 IPA」。
   `[[it-display-layer-stage8]]`：**接上展示层是独立一道闸。**

═══ 判据 ═══
IPA **不使用** ASCII 数字、反引号、反斜杠、下划线；X-SAMPA 这四样全用。
    `ipa GLOB '*[0-9`\\_]*'`
⚠️ **必须用 `GLOB` 不能用 `LIKE`**：SQL 的 `LIKE '%_%'` 里 `_` 是**通配符**，
   匹配任意单字符 ⇒ 我第一版用 LIKE，当场"命中" **298,951 行（整库）**。
   `[[criteria-narrower-than-you-think]]` 的又一面：这次宽在 SQL 语法上。

实测：**98 行，全部 `src='ja-edition'`，逐条打出来看过，零假阳性**；
**删掉之后没有一个词会失去读音**（98 个词形都另有正确的 IPA 行）。

跑（在仓库根）：
    python3 -u ko/pipeline/fix_xsampa_ipa.py
    python3 -u ko/pipeline/fix_xsampa_ipa.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")

# 🔴 用 GLOB，不用 LIKE（见文件头）。字符类里是**只可能是 X-SAMPA 的字符**。
WHERE = "ipa GLOB '*[0-9`\\_]*'"
BAD = re.compile(r"[0-9`\\_]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(
        "SELECT p.id, d.word, p.ipa, p.src FROM pronunciation p "
        "JOIN dict d ON d.id = p.word_id WHERE " + WHERE).fetchall()
    # 🔴 写之前验**反向**：删了之后这个词还有没有读音
    orphan = []
    for pid, w, ipa, src in rows:
        others = [r[0] for r in con.execute(
            "SELECT ipa FROM pronunciation p JOIN dict d ON d.id=p.word_id "
            "WHERE d.word=? AND p.id<>?", (w, pid))]
        if not [o for o in others if not BAD.search(o)]:
            orphan.append((w, ipa, src))
    n_before = con.execute("SELECT COUNT(*) FROM pronunciation").fetchone()[0]
    srcs = sorted({r[3] for r in rows})
    con.close()

    print("■ 疑似 X-SAMPA 的读音行 %s" % f(len(rows)))
    print("   来源：%s" % ", ".join(srcs))
    print("   %s 删掉之后会失去读音的词：%s"
          % ("✅" if not orphan else "🔴", f(len(orphan))))
    for x in orphan[:10]:
        print("      %s" % (x,))
    if orphan:
        raise SystemExit("🔴 有词会因此没有读音 —— 先想清楚怎么办，别直接删")
    print("\n■ 抽样（逐条看过全部 %d 条，这里打前 12）" % len(rows))
    for _pid, w, ipa, _src in rows[:12]:
        print("   %-12s %s" % (w, ipa))

    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    ids = [r[0] for r in rows]
    with dbtool.session(
            "ko-drop-xsampa-ipa",
            expect={"#pronunciation": -len(ids)},
            invalidates=[
                "读音层行数变了：`test_plan_ledger` 的读音覆盖率、`coverage.py`",
                "外锚闸 `verify_layers_vs_dump.py` 读音层：**它会红** —— "
                "源头（日文版）确实有这 98 行，我们有意不收，要在那道闸里登记",
            ]) as s:
        s.executemany("DELETE FROM pronunciation WHERE id=?", [(i,) for i in ids])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("库里不再有 X-SAMPA", q("SELECT COUNT(*) FROM pronunciation WHERE " + WHERE), 0),
        ("读音行数", q("SELECT COUNT(*) FROM pronunciation"), n_before - len(ids)),
        # 🔴 反向闸：那 98 个词形**每一个都还有读音**
        ("那批词形都还有读音",
         q("SELECT COUNT(*) FROM (SELECT DISTINCT d.word FROM dict d WHERE d.word IN (%s)"
           " AND NOT EXISTS(SELECT 1 FROM pronunciation p WHERE p.word_id=d.id))"
           % ",".join("'%s'" % w.replace("'", "''") for _p, w, _i, _s in rows)), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-26s %9s（期望 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))
    print("\n■ `를` 现在的读音")
    for r in con.execute(
            "SELECT p.ipa, p.notation, p.hangeul_phonetic, p.src FROM pronunciation p "
            "JOIN dict d ON d.id=p.word_id WHERE d.word='를'"):
        print("   %s" % (r,))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
