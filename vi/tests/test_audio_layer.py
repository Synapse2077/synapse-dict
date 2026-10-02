#!/usr/bin/env python3
"""**录音层闸（vi）** —— `audio`。2026-10-01。

判据 import 自 `stage6_sources.py` 与 `scripts/commons_filename.py`（八门共用的唯一一份）。

═══ 🔴🔴 A4 是这道闸的理由：**schema 的唯一键挡不住 B12** ═══
`UNIQUE(word_id, url)` 只拦「同一个 url 插两次」。而同一个 Commons 文件在各版里
有**不同的 url**（各维基内嵌转码后的 mp3，Commons 原始名是 `.wav`/`.oga`）：

    原始 8,148 行 → 按 url 去重 4,560 → 按 `commons_key` 并 **3,110**

⇒ 不自己并的话 **1,450 行重复落库**，页面上两个按钮播同一个文件。
A4 查的就是「同一 (词, Commons 键) 只有一行」—— 这是 B12 的**落点**，
而它**不是 DDL 保证的**，所以必须有一条闸。

═══ ⭐ A8：这道闸同时盯着「跨版收割到底净增了多少」 ═══
`paths.py` 当初写「录音只有 en 版有」，那是只比 en 与 vi 得出的。
实测十版有录音，但**去重之后净增只有 654 条（+26.6%）** —— `pl` 版 900 个文件里
664 个 en 已经有了。⇒ A8 查**非 en 版的行数仍在量级上**，
它掉到 0 意味着跨版收割那一步被删掉了而总行数只掉两成（不容易看出来）。

═══ ⚠️ A6：张冠李戴那批必须**还在库里且 hidden=1** ═══
判据精确度只有 ~57%（7 组里真错 4、假阳 3，欠账 W8）⇒ 不许删。
A6 两头都查：隐藏的量级在、而且没有一条隐藏的没写理由。
"""
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                                      # noqa: E402
import pron_sources as PS                                         # noqa: E402
import stage6_sources as S6                                       # noqa: E402

# 🔴 下限按 2026-10-01 实测写死。⚠️ 距现状 ≤3 个点（账的闸 V10 查这件事）
COVER_FLOOR = 3.5           # 实测 4.27%（2,839 / 66,502 个词形有录音）
CROSS_EDITION_FLOOR = 400   # 实测非 en 版贡献 654 行；跨版收割被删掉就掉到 0
MISMATCH_FLOOR = 5          # 实测隐藏 7 行
MISMATCH_CEIL = 60          # 🔴 上限：判据被放宽（比如拿 IPA 交集当第二信号）会涨到 27+
_DOM = ",".join("'%s'" % d for d in sorted(set(PS.DIALECTS.values()) | {"unknown"}))


def _cover(c):
    n = c.execute("SELECT COUNT(DISTINCT word_id) FROM audio WHERE hidden=0").fetchone()[0]
    t = c.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    return 100.0 * n / max(t, 1)


CHECKS = [
    ("A1", "audio 非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM audio").fetchone()[0] > 0, True),
    ("A2", "url 非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM audio WHERE url IS NULL OR TRIM(url)=''").fetchone()[0], 0),
    ("A3", "commons_key 都填了（B12 的判据列）", lambda c: c.execute(
        "SELECT COUNT(*) FROM audio WHERE commons_key IS NULL OR TRIM(commons_key)=''"
    ).fetchone()[0], 0),
    # 🔴🔴 B12 的落点。**DDL 不保证这一条**，所以它必须是一道闸
    ("A4", "🔴🔴 B12：同一 (词, Commons 键) 只有一行（唯一键挡不住）", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT word_id, commons_key FROM audio "
        "GROUP BY word_id, commons_key HAVING COUNT(*)>1)").fetchone()[0], 0),
    ("A5", "每条都挂得上 dict", lambda c: c.execute(
        "SELECT COUNT(*) FROM audio a LEFT JOIN dict d ON d.id=a.word_id "
        "WHERE d.id IS NULL").fetchone()[0], 0),
    ("A6", "⚠️ 张冠李戴那批还在库里且 hidden=1（判据只有 57% 准，不许删）",
     lambda c: MISMATCH_FLOOR <= c.execute(
         "SELECT COUNT(*) FROM audio WHERE hidden_why=?",
         (S6.HIDDEN_WRONG_WORD,)).fetchone()[0] <= MISMATCH_CEIL, True),
    ("A7", "隐藏的都写了为什么", lambda c: c.execute(
        "SELECT COUNT(*) FROM audio WHERE hidden=1 AND "
        "(hidden_why IS NULL OR TRIM(hidden_why)='')").fetchone()[0], 0),
    # ⭐ 跨版收割真的在起作用 —— 只查总行数的话，删掉十一版只掉两成
    ("A8", "⭐ 跨版收割仍在起作用（非 en 版的行数在量级上）", lambda c: c.execute(
        "SELECT COUNT(*) FROM audio WHERE src<>'en-edition'"
    ).fetchone()[0] >= CROSS_EDITION_FLOOR, True),
    ("A9", "🔴 dialect 都在 pron_sources 的值域里（兜底不许静默归 unknown）",
     lambda c: c.execute("SELECT COUNT(*) FROM audio WHERE dialect NOT IN (%s)" % _DOM
                         ).fetchone()[0], 0),
    ("A10", "⭐ 读者口径：有录音的词形占比不低于下限",
     lambda c: _cover(c) >= COVER_FLOOR, True),
    # 🔴 url 必须是**真能播的 Commons 地址**，不是文件名
    ("A11", "🔴 url 是 http(s) 地址（不是文件名）", lambda c: c.execute(
        "SELECT COUNT(*) FROM audio WHERE url NOT GLOB 'http*://*'").fetchone()[0], 0),
    # ⚠️ `commons_key` 不许带转码后缀 —— 带了说明 `original_name()` 没起作用
    ("A12", "⚠️ commons_key 不带转码后缀（`X.ogg.mp3` 要先还原成 `X.ogg`）",
     lambda c: c.execute(
         "SELECT COUNT(*) FROM audio WHERE commons_key GLOB '*.og[ga].mp3' "
         "OR commons_key GLOB '*.wav.mp3' OR commons_key GLOB '*.flac.mp3'"
     ).fetchone()[0], 0),
]
ROSTER = tuple("A%d" % i for i in range(1, 13))
UNMUTABLE = {
    "A1": "要变异就得清空整张表；它拦的是「表空了而所有 0 值检查全绿」。",
}


def run(con):
    red = []
    have = tuple(c[0] for c in CHECKS)
    if set(have) != set(ROSTER):
        red.append(("A0", "检查表与花名册对不上：少了 %s，多了 %s"
                    % (sorted(set(ROSTER) - set(have)) or "无",
                       sorted(set(have) - set(ROSTER)) or "无")))
    for cid, name, fn, want in CHECKS:
        try:
            got = fn(con)
        except sqlite3.Error as e:
            red.append((cid, "%s —— 查不了：%s" % (name, e)))
            continue
        if got != want:
            red.append((cid, "%s：得到 %s，期望 %s" % (name, got, want)))
    return red


MUTATIONS = [
    ("A2", "把一条 url 清空",
     "UPDATE audio SET url='' WHERE id=(SELECT MIN(id) FROM audio)",
     {"A11": "空串也不是 http 地址"}),
    ("A3", "把一条 commons_key 清空",
     "UPDATE audio SET commons_key=NULL WHERE id=(SELECT MIN(id) FROM audio)", {}),
    ("A4", "🔴🔴 B12：同一条录音插成两行（换个 url，Commons 键相同）",
     "INSERT INTO audio(word_id,url,commons_key,dialect,hidden,src) "
     "SELECT word_id, url || '?x=1', commons_key, dialect, hidden, src "
     "FROM audio WHERE id=(SELECT MIN(id) FROM audio)", {}),
    ("A5", "让一条录音指向不存在的 dict",
     "UPDATE audio SET word_id=99999999 WHERE id=(SELECT MIN(id) FROM audio)", {}),
    ("A6", "⚠️ 把张冠李戴那批**删掉**（判据只有 57% 准，删＝丢掉 3 条对的）",
     "DELETE FROM audio WHERE hidden_why='filename-word-mismatch'", {}),
    ("A7", "隐藏一条而不写为什么",
     "UPDATE audio SET hidden=1, hidden_why=NULL WHERE id=(SELECT MIN(id) FROM audio)", {}),
    ("A8", "⭐ 把跨版收割的那批删掉（总行数只掉两成，不容易看出来）",
     "DELETE FROM audio WHERE src<>'en-edition'",
     {"A6": "被删的行里有张冠李戴那批（zh/fr 版各一条）",
      "A10": "覆盖率跟着掉到下限以下"}),
    ("A9", "写一个值域外的 dialect",
     "UPDATE audio SET dialect='Da-Nang' WHERE id=(SELECT MIN(id) FROM audio)", {}),
    ("A10", "⭐ 删掉九成录音（覆盖率掉下去）",
     "DELETE FROM audio WHERE id % 10 <> 0",
     {"A6": "隐藏的那 7 行多半也被删了", "A8": "非 en 版的也被删到量级以下"}),
    ("A11", "写一个不是 http 地址的 url",
     "UPDATE audio SET url='Vi-xin.ogg' WHERE id=(SELECT MIN(id) FROM audio)", {}),
    ("A12", "⚠️ 把转码后缀塞回 commons_key（`original_name()` 失效的样子）",
     "UPDATE audio SET commons_key = commons_key || '.mp3' "
     "WHERE commons_key GLOB '*.ogg' AND id=(SELECT MIN(id) FROM audio "
     "  WHERE commons_key GLOB '*.ogg')", {}),
]


def mutate():
    con = sqlite3.connect(paths.DB)
    base = run(con)
    if base:
        print("🔴 基线就不绿：")
        for c, w in base:
            print("   %s %s" % (c, w))
        return False
    ok, covered = True, set()
    print("═══ 变异验证：%d 条注入 ═══" % len(MUTATIONS))
    for cid, desc, sql, also in MUTATIONS:
        con.execute("SAVEPOINT m")
        changed = 0
        for stmt in sql.split(";"):
            if stmt.strip():
                con.execute(stmt)
                changed += con.execute("SELECT changes()").fetchone()[0]
        hit = set(c for c, _ in run(con))
        undeclared = hit - {cid} - set(also)
        good = changed > 0 and cid in hit and not undeclared
        ok &= good
        covered.add(cid)
        note = ""
        if changed == 0:
            note = "  🔴🔴 **什么都没改** —— 变异自己坏了"
        elif cid not in hit:
            note = "  🔴 没逮到"
        elif undeclared:
            note = "  🔴 **未声明的连带** %s" % sorted(undeclared)
        elif also:
            note = "  （连带 %s，已声明）" % "、".join(sorted(also))
        print("   %s %-5s %s%s" % ("✅" if good else "🔴", cid, desc, note))
        con.execute("ROLLBACK TO m")
        con.execute("RELEASE m")
    con.rollback()
    print("\n── 没有变异覆盖的（必须逐条说明）")
    for c in [x for x in ROSTER if x not in covered]:
        why = UNMUTABLE.get(c)
        if why:
            print("   ⚠️ %-5s %s" % (c, why))
        else:
            ok = False
            print("   🔴 %-5s **没有变异、也没写为什么**" % c)
    con.close()
    return ok


def main():
    if "--mutate" in sys.argv:
        raise SystemExit(0 if mutate() else 1)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        red = run(con)
        print("■ vi 录音层闸：%d 条检查" % (len(CHECKS) + 1))
        for cid, why in red:
            print("   🔴 %-5s %s" % (cid, why))
        if not red:
            print("   ✅ 全绿")
        q = lambda x: con.execute(x).fetchone()[0]                  # noqa: E731
        print("   ── 读者口径录音覆盖 **%.2f%%**（下限 %.1f%%）" % (_cover(con), COVER_FLOOR))
        print("   ── 录音 %s 行（隐藏 %s）／ 非 en 版贡献 %s ／ 方言 %s 种"
              % (format(q("SELECT COUNT(*) FROM audio"), ","),
                 format(q("SELECT COUNT(*) FROM audio WHERE hidden=1"), ","),
                 format(q("SELECT COUNT(*) FROM audio WHERE src<>'en-edition'"), ","),
                 q("SELECT COUNT(DISTINCT dialect) FROM audio")))
        for d, n in con.execute("SELECT dialect, COUNT(*) FROM audio GROUP BY dialect "
                                "ORDER BY 2 DESC"):
            print("      %-24s %6s" % (d, format(n, ",")))
    finally:
        con.close()
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
