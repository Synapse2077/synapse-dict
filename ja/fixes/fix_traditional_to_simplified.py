#!/usr/bin/env python3
"""修：中文版收来的释义/例句译文里的繁体 → 简体。2026-09-16（欠账 7）。

═══ 病灶 ═══
阶段 1.5a/3a 从中文版收的 83,234 条免费释义、阶段 5a 收的 8,586 条例句译文
**原样落库**，而中文版维基本身是繁简混排的：

    国内生产总值（简）   和   國際標準書號（繁）   躺在同一张表里

而两批付费翻译（21 万条）是纯简体 ⇒ **同一个页面上两种字形**。
实测繁转简会变的：释义 **11,244 条（13.5%）**、例句译文 **4,656 条（54.2%）**。

═══ 🔴🔴 不能直接 `t2s` 跑一遍 —— 它会改坏引文 ═══
这些释义会**引用日语的正字法**，而 `opencc` 不认识「这几个字是被引用的日文词形」：

    【敢え無くなる】死。          → 敢え无くなる   ← 日文词形被改坏
    【見頃】                    → 【见顷】       ← 同上，而且看着像个词
    「お暑く」、「問いて」变为…     → 「问いて」     ← 同上

`[[source-typo-fix-ours-not-quote]]` 的同一条：**改我们的出版文本，引文一个字不动。**

═══ 判据（量过 177 个 `【】` + 1,257 条含引用结构的释义才定的）═══
① **`【…】` 里的内容一律不转。** 这是中文版标注**日文词形**的约定。
   实测 177 个括号：含假名 103（确定日文）／纯汉字 36（其中 9 个转换会变，
   **逐条读全是日文词形**：鬱蒼・一所懸命・鳩舎・蝦蛄・絨毯・名詞・明視・毛頭・見頃）／
   拉丁数字 38（`【decilitre】`，`t2s` 本来就不动）。
   ⚠️ 我原本担心 `【數學】【化學】` 这类**中文学科标签**会被一起保护 ——
      实测当前数据里一条都没有。**担心要量过才知道是不是真的。**
② **`「」『』（）《》` 里含假名的不转。** 那是日文引用（29 条）。
   ⚠️ 不含假名的括注**要转** —— `（職務）`→`（职务）`、`（化學元素）`→`（化学元素）`
      正是我们要的。第一版我想把所有括号都保护起来，那会漏掉 900 多条该转的。
      **判据比它要描述的东西宽，代价是这次「修了等于没修」。**
③ 其余全部 `t2s`。

═══ ⚠️ 判据管不到的那一类，明说 ═══
**不带任何括号、直接内嵌的纯汉字日文词**，本判据识别不了，会被一起转。
量不出来（纯汉字串字形上分不出中日），所以不假装它不存在。
🔴 **推翻/收紧它需要**：出现一种能标出「这段是日文引用」的结构信号
（比如中文版改用统一的标注约定），或者有人报出实例。

跑（在仓库根）：
    python3 -u ja/fixes/fix_traditional_to_simplified.py
    python3 -u ja/fixes/fix_traditional_to_simplified.py --apply
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
KANA = re.compile(r"[ぁ-ゖァ-ヺ]")
# 🔴 `【】` 整段保护；其余括号**只在含假名时**保护。两条规则形状不同，别合并。
BRACKET_JA = re.compile(r"【[^】]*】")
QUOTE_ANY = re.compile(r"[「『（《][^」』）》]*[」』）》]")


def _fix(cv, s, cap=5):
    """把 `cv` 跑到**不动点**。

    🔴 `opencc` 的 `t2s` **不是幂等的**：跑一遍之后还剩 2 条会变
    （`芸薹`→`芸苔`、`惯於`→`惯于` —— 第一遍的产物又命中了第二条规则）。
    30 万条里只剩 2 条，**是闸的「必须为 0」逮到的**；写成「基本转完了」就漏过去了。
    ⚠️ 封顶 + 到顶大声报（`[[retry-must-converge-or-drop-loud]]`）——
       不收敛说明规则表里有环，那是要查的事，不是默默跑下去。
    """
    for _ in range(cap):
        t = cv(s)
        if t == s:
            return s
        s = t
    raise RuntimeError("opencc 转换 %d 轮仍不收敛：%r" % (cap, s[:60]))


def convert(text, cv):
    """→ (新文本, 被保护的片段数)。**保护段一个字节都不动。**"""
    spans = []
    for m in BRACKET_JA.finditer(text):
        spans.append((m.start(), m.end()))
    for m in QUOTE_ANY.finditer(text):
        if KANA.search(m.group(0)):
            spans.append((m.start(), m.end()))
    if not spans:
        return _fix(cv, text), 0
    spans.sort()
    out, pos = [], 0
    for a, b in spans:
        if a < pos:
            continue                      # 嵌套/重叠，外层已保护
        out.append(_fix(cv, text[pos:a]))
        out.append(text[a:b])             # ← 原样
        pos = b
    out.append(_fix(cv, text[pos:]))
    return "".join(out), len(spans)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    import opencc
    cv = opencc.OpenCC("t2s").convert

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    jobs = []      # (表, 主键列, 主键, 新文本)
    stat = {"sense_gloss": [0, 0, 0], "example_gloss": [0, 0, 0]}
    for tbl, key in (("sense_gloss", "rowid"), ("example_gloss", "rowid")):
        for rid, t in con.execute(
                "SELECT %s, text FROM %s WHERE lang='zh'" % (key, tbl)):
            stat[tbl][0] += 1
            new, prot = convert(t or "", cv)
            if prot:
                stat[tbl][2] += 1
            if new != t:
                stat[tbl][1] += 1
                jobs.append((tbl, key, rid, new))
    # 🔴 回核：**保护段真的一个字都没动**（不是"我相信代码对"）
    bad = 0
    for tbl, key, rid, new in jobs:
        old = con.execute("SELECT text FROM %s WHERE %s=?" % (tbl, key),
                          (rid,)).fetchone()[0]
        for m in BRACKET_JA.finditer(old):
            if m.group(0) not in new:
                bad += 1
                if bad <= 5:
                    print("   🔴 保护段被改：%r → %r" % (old[:40], new[:40]))
    con.close()

    for tbl, (tot, chg, prot) in stat.items():
        print("■ %-14s 总 %s ｜ 会变 %s ｜ 含保护段 %s"
              % (tbl, f(tot), f(chg), f(prot)))
    print("■ 待改 %s 条｜保护段回核：%s"
          % (f(len(jobs)), "✅ 一个字都没动" if not bad else "🔴 %d 条被改" % bad))
    if bad:
        _sys.exit(1)
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        for tbl, key, rid, new in jobs[:6]:
            old = con.execute("SELECT text FROM %s WHERE %s=?" % (tbl, key),
                              (rid,)).fetchone()[0]
            print("   %r\n → %r" % (old[:52], new[:52]))
        con.close()
        return

    with dbtool.session("ja-t2s", expect={
            "__rows__": 0, "#sense_gloss": 0, "#example_gloss": 0,
            "#entry": 0, "#sense": 0, "#example": 0}) as con:
        for tbl in ("sense_gloss", "example_gloss"):
            con.executemany(
                "UPDATE %s SET text=? WHERE rowid=?" % tbl,
                [(new, rid) for t, _k, rid, new in jobs if t == tbl])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = {}
    for tbl in ("sense_gloss", "example_gloss"):
        n = sum(1 for (t,) in con.execute(
            "SELECT text FROM %s WHERE lang='zh'" % tbl)
            if convert(t or "", cv)[0] != t)
        left[tbl] = n
    # 保护段里的繁体**应该还在**（那是日文词形，不是我们的出版文本）
    prot_left = sum(1 for (t,) in con.execute(
        "SELECT text FROM sense_gloss WHERE lang='zh'")
        for m in BRACKET_JA.finditer(t or "") if cv(m.group(0)) != m.group(0))
    checks = [
        ("释义里没有可转的繁体了", left["sense_gloss"] == 0),
        ("例句译文里没有可转的繁体了", left["example_gloss"] == 0),
        # 🔴 这一条**期望非零**：日文词形保住了才对。它为 0 说明保护没生效。
        ("日文词形（【】内）的原字保住了", prot_left > 0),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    print("   （【】内保留的日文原字 %s 处 —— **这个数不该是 0**）" % f(prot_left))
    con.close()
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
