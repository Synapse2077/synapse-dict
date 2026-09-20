#!/usr/bin/env python3
"""重跑 `ANALYZE` —— 让规划器的统计信息跟上库的现状。2026-09-20。

═══ 为什么这个文件今天才出现 ═══
阶段 9 把「`ANALYZE` 从来没跑过」列为**头号**性能缺陷（搜索最慢 40.9 → 7.1 ms，
`build_search_prefix.py` 文件头写着），可是**当时是手敲 sqlite3 跑的一次，没做成步骤**。
于是整个仓库里 `ANALYZE` 这个词**只出现在一句注释里，没有任何代码会执行它**。

结果 2026-09-20 加完词源层一查：

    sqlite_stat1 里 dict = 710,264 行      ← 陈的
    库里实际       dict = 714,173 行
    etymology                              ← 统计信息里**压根没有这张表**

🔴🔴 **这正是这个仓库最爱犯的那个错：修复做成了「手工动作」而不是「步骤」。**
   手工动作没法重跑、没人知道它跑过、也不会有人想起来该再跑一次 ——
   它和「写成文字的教训」是同一族（`[[lesson-must-become-mechanism]]`）。
   ⚠️ 而阶段 9 的账**查的是 `sqlite_stat1` 存不存在**，不查它新不新 ——
   典型的「行数型判据对陈旧结构性失明」（`[[fix-regression-and-gate]]`）。
   ⇒ 本脚本 ＋ 回归闸 X3「统计信息不许比库陈太多」一起补这个洞。

═══ 为什么走 `dbtool.session` ═══
`ANALYZE` 会写 `sqlite_stat1`。本仓库**任何写库都必须过闸门**（备份 + 回归闸 + 账的闸），
没有「这次改动很小所以直接写」这种例外 —— 那是 `[[dbtool-and-golden-tests]]` 的全部意义。

用法（仓库根）：
    python3 ja/pipeline/run_analyze.py          # 干跑：只报现状差多少
    python3 ja/pipeline/run_analyze.py --run
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dbtool  # noqa: E402
import paths  # noqa: E402

# 🔴 只列**读取路径真的会用到**的大表。判据是「规划器会不会拿它的选择性做决定」，
#    不是「这张表大不大」—— 小表估错了也不影响计划。
WATCH = ("dict", "entry", "sense", "sense_gloss", "sense_relation",
         "inflection", "pronunciation", "example", "etymology")


def survey(con):
    """→ [(表名, 库里实际行数, 统计信息里的行数 or None)]"""
    out = []
    for t in WATCH:
        try:
            real = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        except sqlite3.OperationalError:
            continue                      # 这门没有这张表
        row = con.execute(
            "SELECT stat FROM sqlite_stat1 WHERE tbl=? LIMIT 1", (t,)).fetchone()
        out.append((t, real, int(row[0].split()[0]) if row else None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = survey(con)
    con.close()

    print("═══ 统计信息 vs 库的现状 ═══")
    print("  %-16s %12s %12s   %s" % ("表", "库里实际", "统计信息", "差"))
    print("  " + "─" * 56)
    stale = []
    for t, real, stat in rows:
        if stat is None:
            note, bad = "🔴 **统计信息里没有这张表**", True
        else:
            d = real - stat
            pct = abs(d) / max(real, 1) * 100
            bad = pct >= 0.5
            note = ("🔴 差 %+d（%.1f%%）" % (d, pct)) if bad else "✅"
        stale.append(bad)
        print("  %-16s %12s %12s   %s"
              % (t, format(real, ","), format(stat, ",") if stat is not None else "—", note))

    if not any(stale):
        print("\n✅ 统计信息是新的，不用重跑。")
        return 0
    if not a.run:
        print("\n(干跑。加 --run 才重跑 ANALYZE)")
        return 0

    # 🔴 `expect` 里写 `"#sqlite_stat1": None` ＝「允许变但不校验具体数值」——
    #    ANALYZE 产生几行取决于索引数与数据分布，**写死一个数字下次必然假红**。
    #    ⚠️ 其余表一个都不写 ⇒ 闸门会确保它们**一行都没动**，
    #      这正是我们要的：ANALYZE 只许碰统计信息。
    with dbtool.session("ja-analyze", expect={"#sqlite_stat1": None}) as s:
        s.execute("ANALYZE")

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    after = survey(con)
    con.close()
    print("\n═══ 重跑后 ═══")
    for t, real, stat in after:
        print("  %-16s %12s %12s   %s"
              % (t, format(real, ","), format(stat, ",") if stat is not None else "—",
                 "✅" if stat is not None and abs(real - stat) / max(real, 1) < 0.005 else "🔴"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
