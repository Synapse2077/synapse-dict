#!/usr/bin/env python3
"""**音标层闸（vi）** —— `pronunciation` 对不对。2026-09-28。

判据 import 自 `pron_sources.py`，一条都不重写。

═══ ⭐ P5 是**读者口径**的那一条，也是唯一会被「收词」弄红的一条 ═══
行数闸对稀释结构性失明：阶段 4 收词会把两万多个 vi/zh 独有的词形收进 `dict`，
而它们里有一批没有音标 —— **行数只会涨，覆盖率会掉**。
⇒ P5 锁的是**覆盖率下限**，不是行数。它红了不代表有 bug，代表
「你刚收了一批没音标的词，现在必须决定：补 G2P，还是把下限调下来并说明」。

🔴 `[[fix-regression-and-gate]]`：**ACCEPT 锁数字不锁名字**，
   「已接受」≠「不再看」。下限写成常量并注明是哪天、按什么量的。

═══ 🔴 P3 的 SQL **必须 GLOB 不能 LIKE** ═══
B10（X-SAMPA 冒充 IPA）的判据里有方括号字符类。
SQLite 的 `LIKE` **不认方括号**，`LIKE '%[0-9]%'` 只会去找字面上的 `[0-9]`
⇒ 写成 LIKE 就是一条**永远不响的闸**，而它看起来和真闸一模一样。

用法：
    python3 vi/tests/test_pron_layer.py
    python3 vi/tests/test_pron_layer.py --mutate
"""
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                          # noqa: E402
import pron_sources as PS                             # noqa: E402

_DOM = ",".join("'%s'" % d for d in sorted(set(PS.DIALECTS.values()) | {"unknown"}))

# 🔴 覆盖率下限。**这个数被改过一次，而两次都要记下来**：
#      2026-09-28 阶段 3 建完      94.7%（29,105 / 30,738）⇒ 下限 94.0
#      2026-09-28 阶段 4 收词后    73.7%  ← **P5 当场判红，这条闸第一次真的用上**
#      2026-09-28 阶段 3b 拼完     98.3%（65,535 / 66,657）⇒ 下限提到 **98.0**
#
# ⚠️ **提下限不是「调闸」，是把新达到的水平锁住**（`[[fix-regression-and-gate]]`：
#    ACCEPT 锁数字不锁名字）。留着 94.0 的后果是：从 98.3 掉到 94.1 也不会红，
#    **四个点的退化被下限的松弛吃掉** —— 那正是变异验证当场发现的
#    （插 3,000 个无音标词形，覆盖率掉到 94.1%，而 P5 没逮到）。
COVERAGE_FLOOR = 98.0


def _coverage(c):
    have = c.execute("SELECT COUNT(DISTINCT word_id) FROM pronunciation").fetchone()[0]
    tot = c.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    return 100.0 * have / max(tot, 1)


CHECKS = [
    ("P1", "pronunciation 非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM pronunciation").fetchone()[0] > 0, True),
    ("P2", "ipa 存裸（剥完壳不许还带 [] 或 //）", lambda c: c.execute(
        "SELECT COUNT(*) FROM pronunciation WHERE ipa GLOB '*[][/]*' "
        "OR TRIM(ipa)=''").fetchone()[0], 0),
    ("P3", "🔴 B10 没有 X-SAMPA 冒充 IPA（判据必须 GLOB）", lambda c: c.execute(
        "SELECT COUNT(*) FROM pronunciation WHERE ipa GLOB ?", (PS.XSAMPA_GLOB,)
    ).fetchone()[0], 0),
    ("P4", "dialect 都在 pron_sources 的值域里", lambda c: c.execute(
        "SELECT COUNT(*) FROM pronunciation WHERE dialect NOT IN (%s)" % _DOM
    ).fetchone()[0], 0),
    ("P5", "⭐ 读者口径：有音标的词形占比不低于下限", lambda c: _coverage(c) >= COVERAGE_FLOOR, True),
    ("P6", "每条都挂得上 dict", lambda c: c.execute(
        "SELECT COUNT(*) FROM pronunciation p LEFT JOIN dict d ON d.id=p.word_id "
        "WHERE d.id IS NULL").fetchone()[0], 0),
    # 🔴 `dialect` 进 UNIQUE 键是阶段 0 的核心决定（V4）。这条查它真的生效了：
    #    必须存在**六点齐全**的词。塌成一行的话这个数会变 0。
    ("P7", "六个方言点没有互相覆盖（存在六点齐全的词）", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT word_id FROM pronunciation "
        "WHERE dialect IN ('ha-noi','hue','sai-gon','vinh','thanh-chuong','ha-tinh') "
        "GROUP BY word_id HAVING COUNT(DISTINCT dialect)>=6)").fetchone()[0] > 0, True),
    # 🔴 西贡音在 en 版藏在 `note` 里。只读 `tags` 会让它整个消失 ——
    #    这条把那次栽跤做成了闸：sai-gon 必须是**主流量级**，不是零星几条。
    ("P8", "🔴 西贡音没有整个消失（它在 en 版藏在 note 里）", lambda c: c.execute(
        "SELECT COUNT(*) FROM pronunciation WHERE dialect='sai-gon'").fetchone()[0] > 10000, True),
    # 🔴 `compose:*` 是阶段 3b（按音节拼）引进的第四类 src。
    #    这条闸当场判红了，**而那是对的** —— 新值域必须显式登记，不许默默放行。
    ("P9", "src 都在登记过的值域里（含 compose:*）", lambda c: c.execute(
        "SELECT COUNT(*) FROM pronunciation WHERE src NOT IN "
        "('en-edition','vi-edition','zh-edition-trad') "
        "AND src NOT IN ('compose:vi-edition','compose:en-edition','compose:zh-edition-trad')"
    ).fetchone()[0], 0),
    # 🔴🔴 拼的音标**不许落在本来就有源头音标的词上** —— 那会让人写的和拼的混在一起，
    #    而读者分不出哪条是真人写的。阶段 9 展示层必须标注（欠账 W7）。
    ("P11", "🔴 拼的音标没有落在已有源头音标的词上", lambda c: c.execute(
        "SELECT COUNT(*) FROM pronunciation x WHERE x.src LIKE 'compose:%' "
        "AND EXISTS (SELECT 1 FROM pronunciation o WHERE o.word_id=x.word_id "
        "            AND o.src NOT LIKE 'compose:%')").fetchone()[0], 0),
    ("P10", "src_ref 唯一", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT src_ref FROM pronunciation "
        "GROUP BY src_ref HAVING COUNT(*)>1)").fetchone()[0], 0),
]
ROSTER = ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11")
UNMUTABLE = {
    "P1": "要变异就得清空整张表；它拦的是「表空了而所有 0 值检查全绿」。",
}


def run(con):
    red = []
    have = tuple(c[0] for c in CHECKS)
    # 🔴 比**集合**不比元组：顺序没有语义，而第一版按元组比，
    #    在往中间插一条检查时报出「少了 无，多了 无」—— 一个说不清楚的红。
    #    删掉一条仍然逮得到（集合会少一个），那才是这条检查要防的事。
    if set(have) != set(ROSTER):
        red.append(("P0", "检查表与花名册对不上：少了 %s，多了 %s"
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
    ("P2", "把一条 ipa 塞回方括号里",
     "UPDATE pronunciation SET ipa='['||ipa||']' WHERE id=(SELECT MIN(id) FROM pronunciation)", {}),
    ("P3", "🔴 写一条 X-SAMPA（`a:1` 这种带数字的）",
     "UPDATE pronunciation SET ipa='a:1' WHERE id=(SELECT MIN(id) FROM pronunciation)", {}),
    ("P4", "写一个没登记的方言值",
     "UPDATE pronunciation SET dialect='Da-Nang' WHERE id=(SELECT MIN(id) FROM pronunciation)", {}),
    ("P5", "⭐ 模拟阶段 4 收词：插 3,000 个没有音标的词形",
     "INSERT INTO dict(word,word_norm,pos,is_lemma,entry_type,syllables) "
     "SELECT 'zz-mut-'||value, 'zz-mut-'||value, 'noun',1,'word',1 "
     "FROM (WITH RECURSIVE s(value) AS (SELECT 1 UNION ALL SELECT value+1 FROM s WHERE value<3000) "
     "SELECT value FROM s)", {}),
    ("P6", "让一条指向不存在的 dict",
     "UPDATE pronunciation SET word_id=99999999 WHERE id=(SELECT MIN(id) FROM pronunciation)",
     {"P5": "那个词形的读音没了，覆盖率跟着掉（只掉一个词，不至于破下限）"}),
    # 🔴 这条变异**第一版写的是 `UPDATE … SET dialect='ha-noi'`（全塌成一个值）**，
    #    结果 SQLite 直接抛 `UNIQUE constraint failed: word_id, ipa, dialect, src` ——
    #    ⭐ 那正好证明了阶段 0 的 V4 决定是有效的：**`dialect` 在 UNIQUE 键里，
    #    库在物理上就不允许六条方言读音塌成一条**。塌不进去，只能删。
    ("P7", "🔴 删掉一个方言点（＝六点不再齐全）",
     "DELETE FROM pronunciation WHERE dialect='vinh'", {}),
    ("P8", "🔴 把西贡音整个删掉（＝只读 tags 不读 note 的后果）",
     "DELETE FROM pronunciation WHERE dialect='sai-gon'",
     {"P7": "西贡是六点之一，删了它就再没有六点齐全的词"}),
    ("P11", "🔴 给一个已有源头音标的词补一条「拼的」",
     "INSERT INTO pronunciation(word_id,ipa,dialect,src,src_ref) "
     "SELECT word_id,'zzz','ha-noi','compose:vi-edition','t-dup' FROM pronunciation "
     "WHERE src='vi-edition' LIMIT 1", {}),
    ("P9", "写一个不在值域里的 src",
     "UPDATE pronunciation SET src='guess' WHERE id=(SELECT MIN(id) FROM pronunciation)", {}),
    ("P10", "让两条 src_ref 撞车",
     "UPDATE pronunciation SET src_ref=(SELECT src_ref FROM pronunciation ORDER BY id LIMIT 1) "
     "WHERE id=(SELECT id FROM pronunciation ORDER BY id LIMIT 1 OFFSET 1)", {}),
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
        con.execute(sql)
        changed = con.execute("SELECT changes()").fetchone()[0]
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
        print("■ vi 音标层闸：%d 条检查" % (len(CHECKS) + 1))
        for cid, why in red:
            print("   🔴 %-5s %s" % (cid, why))
        if not red:
            print("   ✅ 全绿")
        print("   ── 读者口径覆盖率 **%.1f%%**（下限 %.1f%%）／ 共 %s 行 ／ 方言 %d 种"
              % (_coverage(con), COVERAGE_FLOOR,
                 format(con.execute("SELECT COUNT(*) FROM pronunciation").fetchone()[0], ","),
                 con.execute("SELECT COUNT(DISTINCT dialect) FROM pronunciation").fetchone()[0]))
    finally:
        con.close()
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
