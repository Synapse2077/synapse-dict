#!/usr/bin/env python3
"""阶段 5d —— 词频层 `dict.freq_zipf`（wordfreq，确定性、零成本）。2026-09-03。

═══ 🔴 这把尺子有四个陷阱，每一个都会**静默**给出错的数 ═══
`[[wordfreq-ruler-traps]]`（es 那轮踩出来的），德语上逐条实测复现：

    -heit      tokenize → ['heit']              zipf **3.06**  ← 连字符被静默剥掉，
                                                                查的是"heit"这个词
    un-        tokenize → ['un']                zipf **4.77**  ← 同上
    fährt mit  tokenize → ['fährt', 'mit']      zipf **4.78**  ← 多词被拼起来算
    Haus/haus  tokenize → ['haus'] 两者都是      zipf 5.41      ← 大小写折叠

⇒ **唯一可用的判据是 `tokenize(w, 'de') == [w.lower()]`**：
  它同时挡住前三样，而放行第四样 —— 这是对的，德语名词首字母大写是正字法，
  `Haus` 折叠成 `haus` 之后查到的就是这个词形的频次。

🔴 **判据不是"看起来像不像一个词"**（含不含连字符、含不含空格都是形式代理，
   `[[criteria-from-meaning-not-form]]`）。判据是**问尺子本身**：
   「你把这个串切成了什么？切出来的还是它自己吗？」不是就别信这个数。

⚠️ **`freq_zipf` 是词形的频次，不是词元的频次。** `Häuser` 4.57 / `Haus` 5.41
   是两个不同的、都正确的数。别拿它当"这个词有多常用"的唯一尺子 ——
   `[[wordfreq-ruler-traps]]` 里「反查证明 level 没我说的那么烂」就是这个教训。

用法（在 de/ 目录下）：
    python3 -u pipeline/fill_freq.py           # 干跑
    python3 -u pipeline/fill_freq.py --apply
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool            # noqa: E402
import paths             # noqa: E402
from wordfreq import tokenize, zipf_frequency   # noqa: E402

f = lambda n: format(n, ",")


def usable(w):
    """→ 这个词形能不能问 wordfreq（**第一关**：尺子切出来的还是它自己吗）。"""
    try:
        return tokenize(w, "de") == [w.lower()]
    except Exception:
        return False


def unambiguous(w, groups):
    """→ 尺子**分得清**这个词形吗（**第二关**，`groups` = {小写形: 该组词形数}）。

    🔴 干跑的反验当场逮到的：全大写缩写拿到了功能词的频次 ——
         MIT → 麻省理工学院    拿了介词 `mit` 的 zipf
         DAS → 哥伦比亚情报局  拿了冠词 `das` 的
         Die → 裸芯片          拿了冠词 `die` 的
         IN  → 紧急联系人      拿了介词 `in` 的
       给 `MIT` 打 6.x 等于说「麻省理工是德语最常用词之一」，
       任何按频次排序的功能都会被带歪。**这不是误差，是张冠李戴。**

    ⚠️ 但**不能一刀切掉所有大写形** —— 德语名词首字母大写是正字法，
       `Haus` 折叠成 `haus` 查到的就是它自己（库里没有小写的 `haus` 词条）。
       第一关放行大小写折叠是**对的**，问题只出在**同一个小写形下挤着多个不同的词**。

    🔴🔴 **我为修 `MIT` 写的第一版判据「组里有多个就只给小写形」立刻被负控打回**：
       `Haus` / `Frau` / `Mann` / `Wasser` / `Buch` / `Zeit` —— 最基本的德语名词
       **全被误杀**，因为库里另有小写同形词（`haus` 是 `hausen` 的命令式、
       `frau` 是泛指代词、`zeit` 是介词）。

    ⚠️ 然后我试的第二版「名词优先」同样错：`Die`（裸芯片，n）会顶掉 `die`（冠词）。
       ⇒ **两个方向的启发式都会错**，因为 wordfreq 折叠大小写、
         它给的本来就是 **token 频次，无法归属到某一个同形词**。这不是我能判的。

    ⇒ 判据只收窄到**唯一有正字法依据的那一点**：**德语没有全大写的词。**
      全大写条目必定是缩写（`MIT` `DAS` `EUROPOL` `NASDAQ`），
      那个 token 频次属于同组里的普通词，不属于它。
      · 组里有非全大写的同形词，而 `w` 是全大写 → 留空
      · 其余一律给值
    ⚠️ **残差诚实记账**：`Die`（裸芯片）这类**首字母大写**的同形词仍会拿到
      `die` 的频次。判不出就是判不出，落进收尾单，不假装解决了
      （`[[record-the-negative-decision]]`）。
    """
    if not (len(w) >= 2 and w.isupper()):
        return True
    # 全大写：只有当同组还有非全大写的词形时才让位
    return groups.get(w.lower(), 0) <= 1


def _bad_caps(con):
    """→ 落库了但按**生成侧的判据**本该留空的行数。

    闸不重写判据，直接调 `unambiguous()`。这样判据改一次两边同时改，
    不会出现「闸在报自己的 bug」（`[[fix-regression-and-gate]]`）。
    """
    rows = con.execute("SELECT word, freq_zipf FROM dict").fetchall()
    groups = Counter(w.lower() for w, _ in rows)
    return sum(1 for w, z in rows if z is not None and not unambiguous(w, groups))


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("有 freq_zipf 的行数 == 期望",
         q("SELECT count(*) FROM dict WHERE freq_zipf IS NOT NULL"), expect["rows"]),
        ("🔴 值域外（zipf 合理范围 0–8）",
         q("SELECT count(*) FROM dict WHERE freq_zipf IS NOT NULL "
           "AND (freq_zipf < 0 OR freq_zipf > 8)"), 0),
        # 🔴 判据只许一份：闸不重写一遍 `usable`，而是查"被判据挡住的那批有没有混进值"。
        ("🔴 多词词形却有频次（多词是拼出来的，不可信）",
         q("SELECT count(*) FROM dict WHERE freq_zipf IS NOT NULL AND word LIKE '% %'"), 0),
        # 🔴 德语没有全大写的词：全大写条目是缩写，不该拿同组普通词的 token 频次。
        # 🔴🔴 **这一条必须在 Python 里查，不能写成 SQL** ——
        #    SQLite 的 `upper()`/`lower()` **只处理 ASCII**，德语的 ä/ö/ü 原样不动：
        #        SQLite:  upper('KöR') = 'KöR'  ⇒ 它以为 `KöR` 是全大写
        #        Python:  'KöR'.isupper() = False（ö 是小写字母）⇒ 生成侧判得对
        #    第一版把这条写成 SQL，报红 2 行（`KöR` `öD`），而**数据是对的、闸是错的**。
        #    ⇒ `[[fix-regression-and-gate]]` 第三种机制：**闸与它守的逻辑用了两个不同判据**。
        #      规矩是「判据只许一份、闸 import 生成侧那份」—— 下面就是这么做的。
        ("🔴 全大写缩写却拿到了同组普通词的频次", _bad_caps(con), 0),
        ("🔴 词缀词形却有频次（连字符被静默剥掉）",
         q("SELECT count(*) FROM dict WHERE freq_zipf IS NOT NULL "
           "AND (word LIKE '-%' OR word LIKE '%-')"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %10s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    has_col = any(r[1] == "freq_zipf"
                  for r in con.execute("PRAGMA table_info(dict)"))
    words = [(i, w) for i, w in con.execute("SELECT id, word FROM dict")]
    con.close()
    print("■ 库内词形 %s ／ `freq_zipf` 列%s" % (f(len(words)), "已建" if has_col else "**还没建**"))

    groups = Counter(w.lower() for _, w in words)
    rows, stat, dist, amb = [], Counter(), Counter(), []
    for wid, w in words:
        if not usable(w):
            stat["不问尺子（切出来的不是它自己）"] += 1
            continue
        if not unambiguous(w, groups):
            stat["留空（全大写缩写，频次属于同组的普通词）"] += 1
            amb.append(w)
            continue
        z = zipf_frequency(w, "de")
        if z <= 0:
            stat["尺子说 0（语料里没见过）"] += 1
            continue
        rows.append((round(z, 2), wid))
        stat["拿到频次"] += 1
        dist[int(z)] += 1

    for k, v in stat.most_common():
        print("   %-34s %s" % (k, f(v)))
    print("\n■ zipf 分布（整数桶）")
    for k in sorted(dist, reverse=True):
        print("   %d.x  %8s  %s" % (k, f(dist[k]), "█" * int(40 * dist[k] / max(dist.values()))))

    # 反验：最高频的应该是功能词，最低频的应该是长复合词
    top = sorted(rows, key=lambda r: -r[0])[:10]
    bot = [r for r in sorted(rows, key=lambda r: r[0])[:10]]
    byid = dict(words)
    print("\n── 反验：最高频 10 个（应该是功能词）──")
    print("   " + " ".join("%s(%.1f)" % (byid[i], z) for z, i in top))
    print("── 反验：最低频 10 个（应该是长复合词/生僻词）──")
    print("   " + " ".join("%s(%.1f)" % (byid[i][:24], z) for z, i in bot))
    if amb:
        print("── 被第二关挡下的样本（这些词形不该拿功能词的频次）──")
        print("   " + " ".join(sorted(amb, key=lambda x: -sum(1 for c in x if c.isupper()))[:16]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    print("\n■ 将写入 freq_zipf %s 行" % f(len(rows)))
    with dbtool.session("keep-v3-5d-freq", expect={"freq_zipf": len(rows)}) as s:
        if not has_col:
            s.execute("ALTER TABLE dict ADD COLUMN freq_zipf REAL")
        s.executemany("UPDATE dict SET freq_zipf=? WHERE id=?", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok = gate2(con, {"rows": len(rows)})
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
