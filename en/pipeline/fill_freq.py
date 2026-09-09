#!/usr/bin/env python3
"""阶段 5d：词频层 `dict.freq_zipf`（wordfreq，确定性、零成本）。2026-09-08。

🔴 **不碰 `freq_rank`/`bnc`** —— 那两列是 ECDICT 的尺子，**五门里只有 en 有**
   （`EN_PLAN` §2.3）。本步只填 `freq_zipf`，两把尺子并存互不覆盖。

═══ 🔴 这把尺子的四个陷阱，在英语上逐条实测 ═══
`[[wordfreq-ruler-traps]]`（es 踩出来、de 复现过）。英语的形状不同，要重验：

    -ability    tokenize → ['ability']          ← 连字符被**静默剥掉**，查的是别的词
    mobile phone tokenize → ['mobile','phone']  ← 多词被拆开
    Lead        tokenize → ['lead']             ← 大小写折叠

⇒ 判据只能是 **`tokenize(w, 'en') == [w.lower()]`**：挡住前两样，放行第三样。
  放行大小写是对的 —— 英语里 `Lead`(专名) 和 `lead`(铅) 的**语料频次本来就是一个数**，
  wordfreq 不区分大小写，这是尺子的口径，不是错。
  ⚠️ 但这正是阶段 1a 那个坑的另一面：**尺子不区分，我们的词条区分**。
     所以 `freq_zipf` 只能当"这串字符有多常见"，**不能当"这个词条有多常用"** ——
     后者用 ECDICT 的 `freq_rank`（它是按词条给的）。两把尺子量的不是同一件事。

🔴 **判据不是"看起来像不像一个词"**（含不含连字符/空格都是形式代理）。
   判据是**问尺子本身**：「你把这串切成了什么？切出来还是它自己吗？」

⚠️ 量不出来的**留 NULL，不填 0** —— 0 是"极罕见"这个事实，NULL 是"我不知道"。

    cd en && python3 -u pipeline/fill_freq.py
    cd en && python3 -u pipeline/fill_freq.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import sqlite3

from wordfreq import tokenize, zipf_frequency

import dbtool
import paths

LANG = "en"


def collect():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    plan, stat = [], collections.Counter()
    ex = collections.defaultdict(list)
    for wid, w, cur in con.execute("SELECT id, word, freq_zipf FROM dict"):
        stat["rows"] += 1
        try:
            tk = tokenize(w, LANG)
        except Exception:
            stat["tokenize 抛错"] += 1
            continue
        if tk != [w.lower()]:
            # 分类记账，不静默丢
            why = ("切成多个词" if len(tk) > 1 else
                   "切成 0 个（纯符号/数字）" if not tk else "切出来不是它自己")
            stat[why] += 1
            if len(ex[why]) < 3:
                ex[why].append((w, tk))
            continue
        z = zipf_frequency(w, LANG)
        stat["可量"] += 1
        if z <= 0:
            stat["  其中 zipf=0（语料里没有）"] += 1
        if cur is None or abs((cur or 0) - z) > 1e-9:
            plan.append((z, wid))
    con.close()
    return plan, stat, ex


def gates(con, n_plan, before):
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("freq_zipf 有值的行", q("SELECT COUNT(*) FROM dict WHERE freq_zipf IS NOT NULL"), n_plan),
        ("🔴 量不出的必须留 NULL，不许填 0 冒充",
         q("SELECT COUNT(*) FROM dict WHERE freq_zipf IS NULL") > 0, True),
        # 🔴 **不许写死这两个数** —— 它们是"写库前是多少，写库后必须还是多少"，
        #    写成字面量既会被字面量闸报警，又会在下次 1a 补挂后过期（非单调判据）。
        ("🔴 ECDICT 尺子 freq_rank 未被动过",
         q("SELECT COUNT(*) FROM dict WHERE freq_rank IS NOT NULL"), before["freq_rank"]),
        ("🔴 ECDICT 尺子 bnc 未被动过",
         q("SELECT COUNT(*) FROM dict WHERE bnc IS NOT NULL"), before["bnc"]),
        ("zipf 落在合理区间 [0, 8]",
         q("SELECT COUNT(*) FROM dict WHERE freq_zipf IS NOT NULL "
           "AND (freq_zipf < 0 OR freq_zipf > 8)"), 0),
        # 负控：多词/带缀的必须**没有**值（它们被判据挡住了）
        ("负控 多词词条无 zipf（mobile phone）",
         q("SELECT COUNT(*) FROM dict WHERE word='mobile phone' AND freq_zipf IS NOT NULL"), 0),
        ("负控对照 单词有 zipf（phone）",
         q("SELECT COUNT(*) FROM dict WHERE word='phone' AND freq_zipf IS NOT NULL"), 1),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-40s %s / %s" % ("✅" if ok else "🔴", name, got, want))
    return bad


def main(apply_=False):
    plan, stat, ex = collect()
    print("═══ 阶段 5d 计划 ═══")
    print("   dict 行数            %11s" % format(stat["rows"], ","))
    print("   ⭐ 可量（判据放行）     %11s  %.1f%%"
          % (format(stat["可量"], ","), 100 * stat["可量"] / stat["rows"]))
    print("      其中 zipf=0        %11s" % format(stat["  其中 zipf=0（语料里没有）"], ","))
    print("   🔴 判据挡下（留 NULL）：")
    for k in ("切成多个词", "切出来不是它自己", "切成 0 个（纯符号/数字）", "tokenize 抛错"):
        if stat[k]:
            print("      %-22s %11s" % (k, format(stat[k], ",")))
            for w, tk in ex.get(k, []):
                print("          %-24s → %s" % (w[:24], tk))
    print("   本次要写 %s 行" % format(len(plan), ","))
    if not apply_:
        print("\n(干跑。加 --apply 才写库)")
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    now, = con.execute("SELECT COUNT(*) FROM dict WHERE freq_zipf IS NOT NULL").fetchone()
    before = {c: con.execute("SELECT COUNT(*) FROM dict WHERE %s IS NOT NULL" % c).fetchone()[0]
              for c in ("freq_rank", "bnc")}
    con.close()
    with dbtool.session("keep-v3-5d-freq", expect={"freq_zipf": stat["可量"] - now}) as s:
        s.executemany("UPDATE dict SET freq_zipf=? WHERE id=?", plan)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = gates(con, stat["可量"], before)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(apply_="--apply" in _sys.argv))
