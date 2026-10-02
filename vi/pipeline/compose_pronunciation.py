#!/usr/bin/env python3
"""阶段 3b：给没有音标的词形**按音节拼**音标。2026-09-28。

═══ 这不是 G2P，而且区别很重要 ═══
`PLAYBOOK` 3.3 写着「别用 G2P 重算」，理由是**字符替换表的顺序本身就是判据**，
而那是我编的。这里用的是另一条路：

    282,804 条源头音标里 **98.76% 按空格切开后与正字法音节数完全一致**
    （越南语没有连读、没有变调，一个音节的读音与它在词里的位置无关）

⇒ 从**真人写的音标**里抽 `(音节, 方言, 版) → IPA` 对照表，再按音节拼。
  每一个音节的读音都来自源头，我一个音标都没有编。

═══ 🔴🔴 第一版实验得出 56.17%，而那个数量的是别的东西 ═══
两个方法错误，都是当场量出来的：

  ① **真值不是单值**：同一 (词, 方言) 在源头里有 **19.0%** 给了多个不同 IPA
     ⇒「逐字符完全一致」这个指标本身不成立，要比的是「与**任何一条**真值相同」
  ② **三版的转写约定不一样**：词首喉塞音 ʔ 的比例 —— en 18.7% ／ **vi 0.0%** ／ zh 19.5%
     ⇒ 把三版混进一张音节表，拼出来的是**嵌合体**

按 (方言, 版) 切开、并改成比「与任何一条真值相同」之后：

    留出 20% 的**词形**（不是音节，按音节留出会作弊）
    拼得出的那批里准确率 **99.82%**（53,875 条测试，错 90 条）
    错的那 90 条抽看是自由变体（`ra` 在顺化读 ɹ 还是 ʐ）与字母名的声调

⇒ `[[reversal-needs-new-measurement]]`：改口前后手上的**数**必须变 —— 56.17 → 99.82。

═══ 🔴 落库约定：**拼的和源头的必须一眼分得开** ═══
`src` 写成 `compose:<版>`，一条 `DELETE FROM pronunciation WHERE src LIKE 'compose:%'`
就能全撤。⚠️ 阶段 9 展示层**必须**能区分并标注，否则读者会以为这是人写的
（与欠账 W6 同一形状 —— 已登记为 **W7**）。

跑（在仓库根）：
    python3 -u vi/pipeline/compose_pronunciation.py
    python3 -u vi/pipeline/compose_pronunciation.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import sqlite3

import dbtool
import paths
import pron_sources as PS
from criteria import _SYL_SEP

# 版的优先级：**越南文版优先** —— 它给六个方言点各一条、量最大、转写最一致
#（词首 ʔ 比例 0.0%，而 en/zh 各 ~19% 是混的）。
SRC_PREF = ["vi-edition", "en-edition", "zh-edition-trad"]
RULE = "compose-syllable-v1"


def syl(w):
    return [x for x in _SYL_SEP.split(w.strip()) if x]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(
        "SELECT d.word, p.ipa, p.dialect, p.src FROM pronunciation p "
        "JOIN dict d ON d.id=p.word_id").fetchall()
    nopron = con.execute(
        "SELECT d.id, d.word FROM dict d LEFT JOIN pronunciation p ON p.word_id=d.id "
        "WHERE p.id IS NULL").fetchall()
    con.close()

    tab = collections.defaultdict(collections.Counter)
    for w, i, d, sr in rows:
        ss = syl(w)
        ps = i.split()
        if len(ss) != len(ps):
            continue
        for s, p in zip(ss, ps):
            tab[(s.lower(), d, sr)][p] += 1
    best = {k: v.most_common(1)[0][0] for k, v in tab.items()}
    print("■ 对照表 %s 个 (音节, 方言, 版) 组合，来自 %s 条真值"
          % (format(len(best), ","), format(len(rows), ",")))

    out, stat = [], collections.Counter()
    for wid, w in nopron:
        ss = [s.lower() for s in syl(w)]
        made = 0
        for d in PS.MAIN_SIX:
            for sr in SRC_PREF:
                if all((s, d, sr) in best for s in ss):
                    ipa = " ".join(best[(s, d, sr)] for s in ss)
                    out.append((wid, ipa, d, "compose:%s" % sr,
                                "pron:compose:%s:%s:%s" % (sr, w, d)))
                    made += 1
                    break          # 一个方言只拼一次，按版优先级
        stat["拼出来了" if made else "一个方言都拼不出"] += 1
        stat["新增行"] += made
    print("■ 无音标词形 %s：拼出来 %s ／ 拼不出 %s"
          % (format(len(nopron), ","), format(stat["拼出来了"], ","),
             format(stat["一个方言都拼不出"], ",")))
    print("   新增 %s 行" % format(len(out), ","))
    bysrc = collections.Counter(r[3] for r in out)
    print("   按底表：%s" % "、".join("%s %s" % (k, format(v, ",")) for k, v in bysrc.most_common()))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    tot = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    have = con.execute("SELECT COUNT(DISTINCT word_id) FROM pronunciation").fetchone()[0]
    con.close()
    print("   ⇒ 覆盖率 %.1f%% → **%.1f%%**"
          % (100 * have / tot, 100 * (have + stat["拼出来了"]) / tot))

    dbtool.sample_check([(r[1], r[2], r[3]) for r in out], 8, ("拼出的音标", "方言", "底表"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    n = len(out)
    with dbtool.session(
            "compose-vi-pronunciation",
            expect={"__rows__": 0, "#pronunciation": n,
                    "pronunciation.ipa": n, "pronunciation.dialect": n},
            invalidates=["音标闸：覆盖率变了，重跑 test_pron_layer.py"]) as s:
        s.executemany(
            "INSERT INTO pronunciation (word_id, ipa, dialect, src, src_ref) "
            "VALUES (?,?,?,?,?)", out)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("新增行数", q("SELECT COUNT(*) FROM pronunciation WHERE src LIKE 'compose:%'"), n),
        # 🔴 拼的音标不许落在**本来就有源头音标**的词上
        ("没有拼到已有源头音标的词上",
         q("SELECT COUNT(*) FROM pronunciation c WHERE c.src LIKE 'compose:%' "
           "AND EXISTS (SELECT 1 FROM pronunciation o WHERE o.word_id=c.word_id "
           "            AND o.src NOT LIKE 'compose:%')"), 0),
        ("拼的也存裸", q("SELECT COUNT(*) FROM pronunciation WHERE src LIKE 'compose:%' "
                        "AND ipa GLOB '*[][/]*'"), 0),
        ("拼的也没有 X-SAMPA",
         q("SELECT COUNT(*) FROM pronunciation WHERE src LIKE 'compose:%' AND ipa GLOB ?",
           ) if False else con.execute(
             "SELECT COUNT(*) FROM pronunciation WHERE src LIKE 'compose:%' AND ipa GLOB ?",
             (PS.XSAMPA_GLOB,)).fetchone()[0], 0),
        ("一条 DELETE 就能全撤",
         q("SELECT COUNT(*) FROM pronunciation WHERE src LIKE 'compose:%'") == n, True),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-28s %10s（期望 %s）"
              % ("✅" if good else "🔴", name,
                 format(got, ",") if isinstance(got, int) else got,
                 format(want, ",") if isinstance(want, int) else want))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
