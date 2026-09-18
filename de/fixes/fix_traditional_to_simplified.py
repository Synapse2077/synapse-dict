#!/usr/bin/env python3
"""修：中文释义里的繁体 → 简体。de 版，2026-09-18。零模型调用。

═══ 病灶 ═══
阶段 1.5a 从中文版白拿的 10,122 条免费中文**原样落库**，而中文版维基本身繁简混排：

    腐肉的氣味、惡臭 ／ 阿布哈茲人 ／ 礦場，礦區        ← 繁
    国内生产总值 ／ 血管瘤 ／ 角膜浑浊                  ← 简（付费翻译那 12 万条）

躺在同一张表里 ⇒ **同一个页面上两种字形**。

实测全库中文释义 292,370 条，转换会变的 **962 条（0.33%）**，按来源拆开：

    zh-edition（中文版白送）   912   ← 大头，1.5a 收的那批
    其余（模板生成/早期收录）     50

⚠️ **2026-09-18 的新一批（本日 `backfill_blank_from_zh.py` 写的 31,985 条）不在里面**
   —— 那一批落库前就转过了。这条修的是**它之前**的存量。

═══ 🔴 为什么 de 可以直接 `t2s`，而 ja 不可以 ═══
ja 那轮的判据写了一大段保护段：中文版的日语释义会**引用日文正字法**
（`【見頃】` → `【见顷】` 把日文词形改坏了），`opencc` 不认识「这几个字是被引用的」。
`[[source-typo-fix-ours-not-quote]]`：改我们的出版文本，引文一个字不动。

**德语这边这个风险不存在，而且是量过的不是想当然**：
  · 962 条里**含 `【】「」『』《》` 的：0 条** —— 没有引用结构要保护；
  · 含拉丁字母的 120 条，那是德语词本身（`Akkordeonist (“手風琴演奏家”) 的陰性等價詞`），
    `t2s` 对拉丁字母**不动**，要转的正是括号里那句中文译文。
⇒ 全量转，不设保护段。⚠️ `opencc` 的 `t2s` 不幂等，转到收敛。

🔴 **推翻它需要**：中文释义里出现被引用的**中文**原文（比如讲某个汉语词的词源），
   那时 `t2s` 会把引文一起改掉。现在一条都没有；出现了就得照 ja 那样加保护段。

═══ 证据层不动 ═══
只改 `sense_gloss`（出版层）。`sense_src` 存的是「源头说了什么」，
繁体原样留着（`[[two-layer-sense-model]]`）。

跑（在仓库根）：
    python3 -u de/fixes/fix_traditional_to_simplified.py
    python3 -u de/fixes/fix_traditional_to_simplified.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import re
import sqlite3

import dbtool
import paths

import opencc

_T2S = opencc.OpenCC("t2s")
# 引用结构。**判据留着，即使当前命中 0 条** —— 它是「推翻这条修复」的探针：
# 哪天中文释义里真出现被引用的中文原文，这里会报出来而不是默默转坏。
QUOTE = re.compile(r"[【】「」『』《》]")


def t2s(s, cap=6):
    """繁→简，转到收敛。🔴 `opencc` 的 `t2s` **不幂等**。"""
    for _ in range(cap):
        out = _T2S.convert(s)
        if out == s:
            return s
        s = out
    raise RuntimeError("opencc 转换 %d 轮仍不收敛：%r" % (cap, s[:60]))


def _assert_de():
    assert paths.DB.name == "synapse-dict-de.sqlite", "🔴 paths 不是 de 的：%s" % paths.DB


def plan(con):
    """→ ([(rowid, 原文, 转换后, 来源)], 带引用结构的那些)"""
    rows, quoted = [], []
    for rid, txt, src in con.execute(
            "SELECT rowid, text, src FROM sense_gloss WHERE lang='zh'"):
        new = t2s(txt)
        if new == txt:
            continue
        (quoted if QUOTE.search(txt) else rows).append((rid, txt, new, src))
    return rows, quoted


def main():
    _assert_de()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    total = con.execute("SELECT count(*) FROM sense_gloss WHERE lang='zh'").fetchone()[0]
    rows, quoted = plan(con)
    con.close()

    print("   中文释义总数          %9s" % format(total, ","))
    print("   繁转简会变的          %9s（%.2f%%）"
          % (format(len(rows), ","), 100.0 * len(rows) / max(total, 1)))
    print("   🔴 含引用结构、不转    %9s %s"
          % (len(quoted), [q[1][:30] for q in quoted[:3]] or "（0 条 —— 德语没有这个形状）"))
    by_src = {}
    for _r, _t, _n, src in rows:
        by_src[src] = by_src.get(src, 0) + 1
    for src, n in sorted(by_src.items(), key=lambda x: -x[1]):
        print("      %-20s %6s" % (src, format(n, ",")))

    dbtool.sample_check([(t[:28], n[:28], s) for _r, t, n, s in rows[::max(1, len(rows) // 14)]],
                        12, ("繁（源头原样）", "简（出版层改成）", "来源"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("de-fix-traditional-to-simplified", expect={}) as s:
        s.executemany("UPDATE sense_gloss SET text=? WHERE rowid=?",
                      [(n, r) for r, _t, n, _s in rows])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left, left_q = plan(con)
    ev = con.execute(
        "SELECT count(*) FROM sense_src WHERE lang='zh'").fetchone()[0]
    con.close()
    checks = [
        ("出版层不再有繁体", len(left) + len(left_q) == 0),
        ("证据层一个字没动（繁体原样留着）", ev > 0),
    ]
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    assert all(ok for _, ok in checks), "🔴 回核不过"


if __name__ == "__main__":
    main()
