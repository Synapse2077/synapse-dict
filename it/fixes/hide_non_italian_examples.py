#!/usr/bin/env python3
"""例句正文不是意大利语 —— 藏掉。2026-08-19。

═══ 用户看得到 ═══
    piova      例句「mais d'autre part, qui esgarde septentrion, n'a que vens et pluies」← 古法语
    mezzaluna  例句「Demi-lune, ouvrage de fortification correspondant à une porte…」  ← 法语版的**法语释义**
    Vinegia    例句「Il fu voir que au tens qe Baudoin estoit enperaor…」            ← 马可波罗原文（古法语）
    università 例句「Quid sī enim numerō istō dēnāriō ūniversitās…」                 ← 拉丁

中文用户查意大利语词，例句必须是意大利语。这几族在源头里确实收在意语词条下
（词源引文/借词用例），学理上没错，但**对一部划词词典没有用处，还看着像错**。

═══ 🔴 判据不是判据，是一份逐条读过的名单 ═══
账本原记「47 条，判据（法语功能词多于意语功能词）够普查不够删数据」。
2026-08-19 重跑那把尺子得到 **167 条**，逐条读完发现它烂在根上：

    de / qui / et / un / la / le / lo —— 这些"法语功能词"
    **在古意大利语和罗马方言里就是意大利语词**

于是《太阳兄弟赞歌》的「Laudato si mi signore per frate vento et per aere et
nubilo et sereno」、彼特拉克的「solo et pensoso i piú deserti campi」、
罗马方言的「C'ho na porzioncina abbondante de pajata de vitella」全被判成法语。
**50 条是我的尺子误伤**（`criteria-from-meaning-not-form`：判据不许用形式代理）。

⇒ 167 条规模足够小 ⇒ **逐条读、逐条定，不发明判据**。名单写死在下面。
   代价说清楚：这份名单只覆盖那把粗尺子扫到的 167 条，
   **扫不到的非意语例句不知道有多少** —— 按上界记账，不假装量清了。

═══ 三族里只处理一族 ═══
    · 50 条 古意语/方言          → 不动（判据误伤）
    · 30 条 法语版把译文粘在正文后 → **另一件事**，见记账本（`Sono cose che capitano.
      Ce sont des choses qui arrivent.` —— 意语部分是对的，只是后面粘了法语译文）
    · 87 条 真非意语              → 本脚本藏掉

═══ 为什么加列不删行 ═══
`prefer-reversible-designs`。`example` 表原本没有 `hidden` 列，这里加一列
（与 `sense.hidden` 同一个约定）。判错了改回 0 就行，删行不可逆。

用法（在 it/ 目录下）：
    python3 fixes/hide_non_italian_examples.py            # 干跑
    python3 fixes/hide_non_italian_examples.py --apply
    python3 fixes/hide_non_italian_examples.py --verify
    python3 fixes/hide_non_italian_examples.py --mutate
"""
import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

# ═══ 真非意语（87 条）—— 逐条读过 ═══
# 三个来源各占一块：
#   en 版：马可波罗古法语原文、拉丁引文、中古法语
#   fr 版：法语版自己的**法语释义**被当成了例句；以及拿意语词当外来词的法语句子
#   it 版：拉丁引文
NON_IT = [  # 87 条
    # ── 法语版：把法语释义当例句 ──
    72961,  # mezzaluna  Demi-lune, ouvrage de fortification…
    69717,  # mutazione  Mutation, modification spontanée…
    74967, 74969,  # secondario 两条法语释义
    67856,  # lente      Lentille, masse de sédiment…
    73692,  # prelievo   Prélèvement, action de prélever…
    75861, 75862,  # dimostrativo 法语语法条目正文
    72209, 70374, 72480,  # -ente / -si / -sione 法语构词说明
    # ── 法语版：法语句子里嵌意语借词 ──
    76004, 70778, 73593, 76649, 76071, 74803, 73691, 75893, 76691, 75689,
    75763, 70785, 76733, 76741, 76746, 68037, 68230, 67365, 68358, 73080,
    71571, 72284, 70759, 75844, 72884, 71019, 67342, 75754, 69587, 67187,
    76262, 73462, 72875,
    # ── 英文版：马可波罗/古法语/中古法语 ──
    44937, 46226, 39475, 44595, 48996, 48458, 46618, 46619, 46228, 46227,
    48830, 45909, 45793, 48461, 48103, 44510, 44511, 42982, 47054, 41428,
    48295, 46671, 43002, 45129, 42588, 45858, 48106, 39841, 39843, 48615,
    # ── 拉丁 ──
    48471, 48078, 54571, 45174, 45902, 48880, 44706, 43001, 42032, 42037,
    43896, 43897, 40270,
]

# ═══ 另一件事：法语版把译文粘在正文后（30 条）—— 本脚本**不动**，只用来核对名单不重叠 ═══
GLUED = [
    71868, 72061, 72062, 70154, 74602, 69917, 69918, 74545, 68519, 74272,
    70675, 76586, 71636, 70740, 72268, 67860, 70903, 67862, 67138, 73649,
    67869, 69135, 72005, 69251, 72239, 69310, 72858, 70406, 69394, 67880,
]


def has_col(con):
    return any(r[1] == "hidden" for r in con.execute("PRAGMA table_info(example)"))


def gate(con):
    ok = True
    if not has_col(con):
        print("   🔴 example 还没有 hidden 列（先 --apply）")
        return False
    got = con.execute("SELECT count(*) FROM example WHERE COALESCE(hidden,0)=1").fetchone()[0]
    good = got == len(NON_IT)
    ok &= good
    print("   %s 已藏的例句 %s（应 %s）" % ("✅" if good else "🔴", f(got), f(len(NON_IT))))
    # 反错配：藏的必须**恰好**是名单里那些 id，不多不少
    ids = {r[0] for r in con.execute("SELECT id FROM example WHERE COALESCE(hidden,0)=1")}
    extra, miss = ids - set(NON_IT), set(NON_IT) - ids
    good = not extra and not miss
    ok &= good
    print("   %s 藏的就是名单本身（多 %s 少 %s）"
          % ("✅" if good else "🔴", len(extra), len(miss)))
    # 名单自身不许重叠：真非意语与"粘了译文"是互斥的两族
    dup = set(NON_IT) & set(GLUED)
    ok &= not dup
    print("   %s 两族名单不重叠（重叠 %s）" % ("✅" if not dup else "🔴", len(dup)))
    # 🔴 反向：粘译文那 30 条必须**还在显示**。本脚本刻意不碰它们 ——
    #    要是哪天有人把判据放宽顺手也藏了，这里当场报红。
    hid = con.execute("SELECT count(*) FROM example WHERE COALESCE(hidden,0)=1 AND id IN (%s)"
                      % ",".join(map(str, GLUED))).fetchone()[0]
    ok &= hid == 0
    print("   %s 粘了译文那 30 条仍在显示（被藏 %s，应 0）"
          % ("✅" if hid == 0 else "🔴", hid))
    return ok


def mutate():
    cases = [
        ("放出一条古法语例句", "UPDATE example SET hidden=0 WHERE id=%d" % NON_IT[0]),
        ("多藏一条名单外的例句",
         "UPDATE example SET hidden=1 WHERE id=(SELECT id FROM example "
         "WHERE COALESCE(hidden,0)=0 LIMIT 1)"),
        ("顺手把「粘了译文」那族也藏了", "UPDATE example SET hidden=1 WHERE id=%d" % GLUED[0]),
    ]
    passed = 0
    for name, sql in cases:
        d = Path(tempfile.mkdtemp())
        shutil.copy(paths.DB, d / "m.sqlite")
        con = sqlite3.connect(d / "m.sqlite")
        con.execute(sql)
        con.commit()
        print("\n── 变异：%s" % name)
        red = not gate(con)
        con.close()
        shutil.rmtree(d)
        print("   %s" % ("✅ 闸报红" if red else "🔴 闸没报 —— 这道检查是假的"))
        passed += red
    print("\n■ 变异 %s/%s" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return mutate()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    dup = set(NON_IT) & set(GLUED)
    if dup:
        print("🔴 两族名单重叠：%s" % sorted(dup))
        return 1
    print("■ 真非意语 %s 条（本步藏）／粘了译文 %s 条（不动，记账）"
          % (f(len(NON_IT)), f(len(GLUED))))
    for eid, w, src, t in ro.execute(
            "SELECT id, word, src, text FROM example WHERE id IN (%s) ORDER BY word LIMIT 8"
            % ",".join(map(str, NON_IT))):
        print("   [%s] %-16s %s" % (src[:2], w[:16], " ".join(t.split())[:74]))
    if not a.apply:
        ro.close()
        print("\n(未加 --apply，不写库)")
        return 0
    add = not has_col(ro)
    ro.close()
    with dbtool.session("hide-non-italian-examples", expect={"__rows__": 0}) as s:
        if add:
            s.execute("ALTER TABLE example ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
        s.execute("UPDATE example SET hidden=1 WHERE id IN (%s)"
                  % ",".join(map(str, NON_IT)))
    print("■ 已藏 %s 条" % f(len(NON_IT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
