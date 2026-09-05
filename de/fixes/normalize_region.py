#!/usr/bin/env python3
"""统一 `pronunciation.region` 与 `audio.region` 的值域。2026-09-04（收尾单 C31）。

═══ 缺陷 ═══
同一个概念，两张表两套代码：
    audio.region          de-AT (3,737)  de-CH (7)                    ← BCP-47 风格
    pronunciation.region  at (365)  ch (169)  de-north (182)  de (34) ← kaikki 原样
**交集是空的。** 读者会在同一页看到两种标法。

═══ 🔴 为什么不在展示层映射掉 ═══
`DE_REGION_LABELS` 确实已经把两套都译成中文了 —— 那是标签表的**本职**
（不译＝给读者看 `at`/`de-AT`）。但那同时也**把缺陷藏了起来**：页面上看不出两套词汇表。
`[[aim-for-perfect-not-cheap]]`：别用展示层补丁代替把事情做进数据里。
⇒ 回归闸 H6 专门盯它，本步在**数据里**修掉。

═══ 判据：选哪一套 ═══
选 **BCP-47 风格**（`de-AT`/`de-CH`/`de-DE`）—— 理由不是"好看"：
  · 它是**有标准可依**的（IETF BCP 47），而 `at`/`ch` 是 kaikki 的内部约定；
  · `audio` 那 3,744 行已经是这套，改动面更小；
  · 未来接 TTS / 浏览器 `lang` 属性时，BCP-47 是直接能用的那种。
⚠️ `de-north`（北德）**不是国家**，BCP-47 里没有对应的区域码 ⇒ 保留原样，
   并在这里写清楚它是有意的例外，免得下一轮有人"顺手统一"掉。

用法（在 de/ 目录下）：
    python3 -u fixes/normalize_region.py
    python3 -u fixes/normalize_region.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

# kaikki 原样 → BCP-47。**只列实测出现过的值**，不凭空补（`[[criteria-narrower-than-you-think]]`）。
MAP = {"at": "de-AT", "ch": "de-CH", "de": "de-DE"}
# ⚠️ 有意不映射：`de-north`/`de-south` 是方言区不是国家/地区，BCP-47 无对应码。保留原样。
# ⭐ 2026-09-05（C41）：`de-south` 是这次才第一次出现的值（英文版 `Southern-Germany` 3 条）。
#    C31 当天库里没有这个值，所以没登记 —— 而本脚本的「没登记就先别动」那道拦阻
#    **当场拦住了它**，没有让一个没想清楚的值溜进去。这正是那道拦阻该干的活。
KEEP = {"de-north", "de-south"}

# 🔴 **登记值域**：两张表的 region 都必须落在这里面。判据只许一份，回归闸 H6 import 它。
#    ⚠️ 判据**不是**「两张表值域相同」—— 第一版那么写，修完当场报 1，
#      因为 `de-DE` 只在音标表有：阶段 6 定了 `De-` 前缀只表示「德语」不表示「德国」，
#      录音表**有意**不写 `de-DE`。那是**覆盖面差异，不是词汇表冲突**。
#      C31 骂的是「同一个地区被两张表用不同代码表示」，
#      所以判据该问「**值在不在同一张登记表里**」。
#    ⭐ 检验这不是放水：拿修之前的数据跑，`at`/`ch`/`de` 都不在域里 ⇒ 照样报红。
DOMAIN = {"de-AT", "de-CH", "de-DE", "de-north", "de-south"}

# 🔴🔴 **2026-09-05：C31 修了落库的行，没修生成侧 —— 于是它会被重跑撤销。**
#    C41 补英文版音标时复用了阶段 4 的 `REGION` 映射表，那张表还在产 C31 之前的
#    词汇表（`at`/`ch`/`de`），577 行当场把 C31 撤销了一半。
#    `[[replay-scripts-undo-fixes]]`：**A 层搬到 B 层前先问 B 被修过吗** ——
#    这次是反过来，B（落库的行）被修过，而 A（生成它的映射表）没有。
#    ⇒ 阶段 4 的 `REGION` 现在**直接产登记值域里的值**，并在 import 时断言值域包含关系；
#      本脚本从此是一次性的历史修复，重跑应当无事可做。
#    ⚠️ 逮到它的是 `harvest_pronunciation.gate2` 的 region 断言，而那条断言
#      **在 C31 之后就一直是过期的**（它写死的是 C31 之前的值域），
#      只是从 C31 到今天没有人跑过它 —— **没人跑的闸等于没有闸**。


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("■ 改动前")
    for t in ("pronunciation", "audio"):
        vals = con.execute("SELECT region, COUNT(*) FROM %s WHERE region IS NOT NULL "
                           "GROUP BY 1 ORDER BY 2 DESC" % t).fetchall()
        print("   %-14s %s" % (t, "  ".join("%s=%s" % (r, f(n)) for r, n in vals)))
    todo = {k: con.execute("SELECT COUNT(*) FROM pronunciation WHERE region=?",
                           (k,)).fetchone()[0] for k in MAP}
    # 🔴 2026-09-05 改：原来是 `- set(MAP) - KEEP`，**于是本脚本跑第二遍就会拒绝执行**
    #    —— 它把自己刚写进去的 `de-AT`/`de-CH`/`de-DE` 当成了「没登记的值」。
    #    一次性脚本这么写还能用，而 C41 之后它变成了「生成侧被修好之后的补丁路径」，
    #    必须可重跑。⇒ 判据换成「**不在登记值域里、也没法映射进去**」，
    #    那才是「没登记」的意思（`[[criteria-from-meaning-not-form]]`）。
    unknown = {r for (r,) in con.execute(
        "SELECT DISTINCT region FROM pronunciation WHERE region IS NOT NULL")} - set(MAP) - DOMAIN
    con.close()
    print("\n■ 将改 %s 行：%s" % (f(sum(todo.values())),
                              "  ".join("%s→%s(%s)" % (k, MAP[k], f(v))
                                        for k, v in todo.items() if v)))
    print("   ⚠️ 有意保留：%s（方言区，BCP-47 无对应码）" % "、".join(sorted(KEEP)))
    if unknown:
        print("   🔴 表里还有没登记的值：%s —— **先弄清楚再动**" % unknown)
        return 1
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("keep-v3-c31-region", expect={}) as s:
        for k, v in MAP.items():
            s.execute("UPDATE pronunciation SET region=? WHERE region=?", (v, k))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    A = {r for (r,) in con.execute("SELECT DISTINCT region FROM pronunciation "
                                   "WHERE region IS NOT NULL")}
    B = {r for (r,) in con.execute("SELECT DISTINCT region FROM audio WHERE region IS NOT NULL")}
    print("\n■ 改动后  pronunciation=%s  audio=%s" % (sorted(A), sorted(B)))
    # 判据与回归闸 H6 同源：两张表的值都必须落在登记值域 `DOMAIN` 里。
    split = (A | B) - DOMAIN
    print("\n═══ 闸② ═══")
    print("   %s region 值落在登记值域之外  %s  期望 0%s"
          % ("✓" if not split else "🔴", len(split),
             ("  ← %s" % sorted(split)) if split else ""))
    con.close()
    return 0 if not split else 1


if __name__ == "__main__":
    sys.exit(main())
