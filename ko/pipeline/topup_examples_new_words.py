#!/usr/bin/env python3
"""阶段 8 补丁：给**补收进来的词形**补例句。2026-09-24。

═══ 为什么需要这一步 ═══
`harvest_examples.main()` 里有一行
    `miss = [r for r in rows if r["word"] not in indict]`   # 不在 `dict` 就不收
那是对的 —— 例句挂不到不存在的词形上。但它让例句层**与当时的 `dict` 绑死**：
K13 补收 13,062 个词头之后，那批词在源头里的例句**没有人回头收**。

🔴 这是 K13 之后**第三个**需要定向补的下游层（前两个：罗马字 `--topup`、关系层）。
   `[[replay-scripts-undo-fixes]]` 的同族问题：A 层变了，B 层不会自己跟上。
   ⇒ 已落账 `BACKLOG` **B3**：收词之后该补哪些层，得有一张单子，
     而不是我每次想起一个补一个 —— 这一条恰恰是**想不起来**、靠外锚闸才逮到的。

═══ 它**不是**第二个写入方 ═══
判据与取值**全部**来自 `harvest_examples.harvest()`（一个字不重写），
本脚本只做两件事：把范围限制在「库里还没有的 (word, text)」，
以及「词形现在在 `dict` 里」。`[[enrich-not-rebuild]]`。

跑（在仓库根）：
    python3 -u ko/pipeline/topup_examples_new_words.py
    python3 -u ko/pipeline/topup_examples_new_words.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import sqlite3

import dbtool
import paths
import harvest_examples as HE

f = lambda n: format(n, ",")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows, _lab, _resid, _stat = HE.harvest()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[0] for r in con.execute("SELECT word FROM dict")}
    have = {(w, t) for w, t in con.execute("SELECT word, text FROM example")}
    todo = [r for r in rows
            if r["word"] in indict and (r["word"], r["text"]) not in have]
    n_sid = HE.bridge(con, todo)
    before = con.execute("SELECT COUNT(*) FROM example").fetchone()[0]
    before_g = con.execute("SELECT COUNT(*) FROM example_gloss").fetchone()[0]
    con.close()

    n_zh = sum(1 for r in todo if r["zh"])
    n_en = sum(1 for r in todo if r["en"])
    print("■ 收割器产出 %s ／ 库里已有 %s ／ **要补 %s**"
          % (f(len(rows)), f(before), f(len(todo))))
    print("   挂得上义项 %s ／ 白送中文 %s ／ 白送英文 %s"
          % (f(n_sid), f(n_zh), f(n_en)))
    for r in todo[:20]:
        print("   + %-14s [%s] %s" % (r["word"], r["src"], r["text"][:60]))
    if not todo:
        print("\n■ 没有要补的 —— 例句层与当前 `dict` 已经对齐 ✓")
        return
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    ex = [(r["word"], r["sense_id"], r["text"], r["ref"], r["src_gloss"],
           r["src_translation"], r["src_lang"], r["roman"], r["hidden"], r["src"])
          for r in todo]
    with dbtool.session(
            "ko-topup-examples",
            # 🔴 列要**单独声明**，写行数不等于声明了列（写库闸门当场拦下过一次：
            #    `example.src_translation` 没声明 —— ja 版的日语译文存在这一列，
            #    而 `[[gloss-three-languages]]` 不让它进 `example_gloss`）。
            #    ⚠️ 闸的价值正在于**声明发生在写之前**：想不清楚就写不出 expect。
            expect={"#example": len(ex), "#example_gloss": n_zh + n_en,
                    "example.src_translation": sum(
                        1 for r in todo if r["src_translation"])},
            invalidates=[
                "例句总数变了：`test_plan_ledger` 的例句条数、`coverage.py` 的例句覆盖率",
                "阶段 6d 例句翻译的待译条数（本步补进来的也要译）",
            ]) as s:
        s.executemany(
            "INSERT OR IGNORE INTO example (word, sense_id, text, ref, src_gloss,"
            " src_translation, src_lang, roman, hidden, src)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)", ex)
        ids = {(w, t): i for i, w, t in s.execute(
            "SELECT id, word, text FROM example").fetchall()}
        gl = []
        for r in todo:
            eid = ids.get((r["word"], r["text"]))
            if eid is None:
                continue
            if r["zh"]:
                gl.append((eid, "zh", r["zh"], r["src"]))
            if r["en"]:
                gl.append((eid, "en", r["en"], r["src"]))
        if gl:
            s.executemany(
                "INSERT OR IGNORE INTO example_gloss (example_id, lang, text, src)"
                " VALUES (?,?,?,?)", gl)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x, *p: con.execute(x, p).fetchone()[0]
    checks = [
        ("example 行数", q("SELECT COUNT(*) FROM example"), before + len(ex)),
        ("example_gloss 行数", q("SELECT COUNT(*) FROM example_gloss"),
         before_g + n_zh + n_en),
        ("🔴 正文里没有谚文的",
         q("SELECT COUNT(*) FROM example WHERE text NOT GLOB '*[가-힣]*'"), 0),
        ("🔴 挂到了不存在的义项上",
         q("SELECT COUNT(*) FROM example e WHERE e.sense_id IS NOT NULL "
           "AND NOT EXISTS (SELECT 1 FROM sense s WHERE s.id=e.sense_id)"), 0),
        # 🔴 按**含义**查，不按 id 边界：`example.id` 是 AUTOINCREMENT，
        #    拿行数当边界会踩 K13 那次踩过的坑（`dict` 有 19 个 id 空洞）。
        ("本步补的词形确实有例句了",
         q("SELECT COUNT(DISTINCT word) FROM example WHERE word IN (%s)"
           % ",".join("?" * len({r["word"] for r in todo})),
           *sorted({r["word"] for r in todo})),
         len({r["word"] for r in todo})),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-28s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              f(got), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
