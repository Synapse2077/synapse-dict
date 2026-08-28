#!/usr/bin/env python3
"""收尾单 A1 — 连诵形读音：**标注**，并把顶在词头的那几条挪下去。2026-08-27。

═══ 🔴 我的记账把规模写错了两个数量级 ═══
收尾单第一版写的是「主读音里含连诵符 ‿ ⇒ **32,051** 条错音标」。
拿数据一看，**那些绝大多数是对的**：

    Saint-André        sɛ̃.t‿ɑ̃.dʁe        ✅ 多词条目内部连诵，法语的真实语音事实
    maisons d'arrêt    mɛ.zɔ̃ d‿a.ʁɛ       ✅
    ouest-asiatiques   wɛs.t‿a.zja.tik     ✅

判据「含有 ‿」是**形式代理**（`[[criteria-from-meaning-not-form]]`：我在音标判据上
已经连写错三版了，这是第四次）。真缺陷的意思是「**拿连诵形冒充这个词自己的读音**」，
形式上的表现是 **`‿` 悬空**（尾巴上挂着，后面什么都没有）：

    les    lɛ.z‿      🔴 les 是 /le/，/le.z‿/ 是它在元音前的连诵形
    mon    mɔ̃.n‿     🔴
    quand  kɑ̃.t‿     🔴

═══ 收窄之后还得再收一次 ═══
悬空 160 条里有 41 条**仍然是对的** —— 词本身以**省音撇或连字符结尾**时，
连诵是它固有的，后面本来就不可能有音：

    lors d'          lɔʁ d‿       ✅   tandis qu'    tɑ̃.di k‿   ✅
    au moyen d'      o mwa.jɛ̃ d‿  ✅   non-          nɔ̃.n‿     ✅

⇒ 判据 = **`‿` 悬空** 且 **词本身不以 `'` / `’` / `-` 结尾**。⇒ **119 条**。
⭐ 上面那 41 条就是负控（`[[criteria-from-meaning-not-form]]`：负控用例 =
   我上一版判据误杀过的数据）。

═══ 再量一次落点，规模又小一个数量级 ═══
119 条里 **114 条的词头已经是对的** —— 法文版的正常读音早就占着 `is_primary`
（`les` 词头显示 /lɛ/，连诵形只是躺在读音表里）。

    🔴 顶在词头、读者直接看到错的     **6**    ← 出版阻断
    🟡 在读音表里没有标注             119    ← 读者看到的是**真读音**，只是没说它是连诵

`[[measure-landing-not-source]]`：**量落点不量源头。** 32,051 → 119 → 6。

═══ 怎么修：标注，不删 ═══
连诵形是**真信息**（`les` 在元音前确实读 /le.z‿/），删掉就丢了。
⇒ 加一列 `pronunciation.context`，这 119 条写 `'liaison'`。

🔴 **不塞进 `notation`**：那一列的含义是**转写风格**（phonemic 音位式 / narrow 音值式），
   而"连诵"是**语境变体**，两回事。塞进去就是把两个维度压成一个，
   而且 `pronQuery` 的排序和展示层的 `/…/` vs `[…]` 都读那一列。

顶在词头的 6 条，分两种处置：
  · 该词另有正常读音（`jusques` 有 /ʒysk/、`dins` 有 /dɛ̃/）⇒ **把主读音让给它**
  · 只有连诵形这一条（`m'n` / `keusse-dix` / `-(s)`）⇒ **不动**。
    没有别的读音时，"有一个带连诵标记的读音"好过"一个读音都没有"，
    标注上了读者就知道那是什么。
  · `Haut-Pyrénéens` 的 `‿` 悬在**开头**（那是连**进来**的音）⇒ 剥掉前导符。

用法（在 fr/ 目录下）：
    python3 -u fixes/mark_liaison_readings.py            # 只报数
    python3 -u fixes/mark_liaison_readings.py --apply
    python3 -u fixes/mark_liaison_readings.py --mutate
"""
import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                   # noqa: E402
import paths                                    # noqa: E402

f = lambda n: format(n, ",")
LINK = "‿"          # ‿ UNDERTIE
ELIDED = ("'", "’", "-")


def dangling(word, ipa):
    """判据本体 —— **写入侧与闸共用这一份**（`[[fix-regression-and-gate]]`）。

    「拿连诵形冒充这个词自己的读音」= `‿` 悬空 **且** 词本身不以省音撇/连字符结尾。
    """
    if not ipa or LINK not in ipa:
        return False
    s = ipa.strip()
    if not (s.endswith(LINK) or s.startswith(LINK)):
        return False                     # 词内连诵 —— 正确，不碰
    return not word.rstrip().endswith(ELIDED)


def plan(con):
    rows = con.execute(
        "SELECT p.id, d.id, d.word, p.ipa, p.is_primary FROM pronunciation p "
        "JOIN dict d ON d.id=p.word_id WHERE p.ipa LIKE ?", ("%" + LINK + "%",)).fetchall()
    mark, promote, strip = [], [], []
    for pid, wid, w, ipa, pri in rows:
        if not dangling(w, ipa):
            continue
        mark.append((pid, w, ipa, pri))
        if ipa.strip().startswith(LINK):
            strip.append((pid, w, ipa, ipa.strip().lstrip(LINK)))
        if pri:
            alt = con.execute(
                "SELECT id, ipa FROM pronunciation WHERE word_id=? AND id<>? "
                "AND ipa NOT LIKE ? ORDER BY CASE WHEN notation='phonemic' THEN 0 ELSE 1 END, "
                "LENGTH(ipa) LIMIT 1", (wid, pid, "%" + LINK + "%")).fetchone()
            if alt:
                promote.append((pid, alt[0], w, ipa, alt[1]))
    return mark, promote, strip


def gates(con, mark, promote):
    print("\n═══ 闸 ═══")
    ok = True

    def g(name, got, want):
        nonlocal ok
        ok &= got == want
        print("   %s %-52s %s（期望 %s）" % ("✅" if got == want else "🔴", name, f(got), f(want)))

    # ① 负控：词内连诵、以及以省音撇结尾的，**一条都不许进来**
    inner = sum(1 for (i, w, ipa) in con.execute(
        "SELECT p.id, d.word, p.ipa FROM pronunciation p JOIN dict d ON d.id=p.word_id "
        "WHERE p.ipa LIKE ?", ("%" + LINK + "%",))
        if LINK in ipa.strip()[1:-1] and not dangling(w, ipa))
    ids = {m[0] for m in mark}
    g("① 词内连诵（Saint-André 那族）一条都没被圈进来",
      sum(1 for (i, w, ipa) in con.execute(
          "SELECT p.id, d.word, p.ipa FROM pronunciation p JOIN dict d ON d.id=p.word_id "
          "WHERE p.ipa LIKE ?", ("%" + LINK + "%",))
          if i in ids and not (ipa.strip().endswith(LINK) or ipa.strip().startswith(LINK))), 0)
    g("② 省音撇/连字符结尾的词（lors d' 那族）一条都没被圈进来",
      sum(1 for m in mark if m[1].rstrip().endswith(ELIDED)), 0)
    g("③ 让位后每个词仍恰好有一条主读音",
      sum(1 for pid, aid, w, _o, _n in promote
          if con.execute("SELECT COUNT(*) FROM pronunciation WHERE word_id="
                         "(SELECT word_id FROM pronunciation WHERE id=?) AND is_primary=1",
                         (pid,)).fetchone()[0] != 1), 0)
    print("   ℹ️ 词内连诵（正确、不动）：%s 条" % f(inner))
    return ok


def mutate():
    print("═══ 变异验证：判据本体 ═══")
    cases = [
        ("🔴 les 的连诵形（悬空）", dangling("les", "lɛ.z‿"), True),
        ("🔴 quand 的连诵形（悬空）", dangling("quand", "kɑ̃.t‿"), True),
        ("负控 Saint-André（词内连诵，正确）",
         dangling("Saint-André", "sɛ̃.t‿ɑ̃.dʁe"), False),
        ("负控 maisons d'arrêt（词内连诵，正确）",
         dangling("maisons d'arrêt", "mɛ.zɔ̃ d‿a.ʁɛ"), False),
        ("负控 lors d'（词以省音撇结尾，连诵固有）",
         dangling("lors d'", "lɔʁ d‿"), False),
        ("负控 tandis qu'（同上，弯撇号也要认）",
         dangling("tandis qu’", "tɑ̃.di k‿"), False),
        ("负控 non-（词以连字符结尾）", dangling("non-", "nɔ̃.n‿"), False),
        ("🔴 悬在开头也算（连进来的音）",
         dangling("Haut-Pyrénéens", "‿o.pi.ʁe.neɛ̃"), True),
        ("不含连诵符的普通音标", dangling("maison", "mɛ.zɔ̃"), False),
    ]
    ok = 0
    for name, got, want in cases:
        good = got == want
        ok += good
        print("   %s %-46s → %s" % ("✅" if good else "🔴", name, got))
    print("\n   变异 %d/%d" % (ok, len(cases)))
    return ok == len(cases)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    mark, promote, strip = plan(con)
    print("■ 判为「拿连诵形冒充自身读音」 %s 条" % f(len(mark)))
    print("   其中顶在词头（is_primary=1）  %s" % f(sum(1 for m in mark if m[3])))
    print("   ├ 有正常读音可让位 ⇒ 换主读音  %s" % f(len(promote)))
    print("   └ 只有这一条 ⇒ 不动，只标注    %s"
          % f(sum(1 for m in mark if m[3]) - len(promote)))
    print("   前导连诵符要剥掉               %s" % f(len(strip)))
    for pid, aid, w, old, new in promote:
        print("      【%s】主读音 %s → %s" % (w, old, new))
    for pid, w, old, new in strip:
        print("      【%s】剥前导符 %s → %s" % (w, old, new))
    ok = gates(con, mark, promote)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1
    with dbtool.session("keep-v3-liaison-mark", expect={}) as s:
        cols = {r[1] for r in s.execute("PRAGMA table_info(pronunciation)")}
        if "context" not in cols:
            # 🔴 先加列再写值（`[[ipa-provenance-columns]]`）
            s.execute("ALTER TABLE pronunciation ADD COLUMN context TEXT")
        s.executemany("UPDATE pronunciation SET context='liaison' WHERE id=?",
                      [(m[0],) for m in mark])
        for pid, aid, _w, _o, _n in promote:
            s.execute("UPDATE pronunciation SET is_primary=0 WHERE id=?", (pid,))
            s.execute("UPDATE pronunciation SET is_primary=1 WHERE id=?", (aid,))
        for pid, _w, _o, new in strip:
            s.execute("UPDATE pronunciation SET ipa=? WHERE id=?", (new, pid))
    print("✓ 标注 %s 条 · 换主读音 %s 处 · 剥前导符 %s 处"
          % (f(len(mark)), f(len(promote)), f(len(strip))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
