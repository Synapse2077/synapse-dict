#!/usr/bin/env python3
"""中文释义不带句末句号 —— 全库 30 万条都是这个体例，A5 重写的那批破了例。2026-08-28。

═══ 怎么发现的 ═══
不是闸逮到的，是我在给 A5 重写结果做**盲测 A/B 材料**时，两版并排一眼看见的：

    adepte   甲：能手，专家
             乙：在教派或科学领域中被传授奥秘的人。      ← 只有重写的这一版带句号

量落点（`[[measure-landing-not-source]]`）：

    A5 重写的 816 条        以 `。` 结尾 **292 条 = 36%**
    既有 `model:gloss` 抽 30,000 条   以句号结尾 **6 条 = 0.0%**
      └ 而那 6 条全是 `…Anthericum ramosum L.`——**拉丁学名的命名人缩写**，句号是对的

⇒ 这是**我这一轮引入的体例回归**：`fix_gloss_wrong.SYS_RT` 里没写「不带句末标点」。
   根因已补进那份 prompt；本脚本清存量。

═══ 判据窄到不能再窄 ═══
只剥**中文句号 `。`**，一个字符。
🔴 **不碰拉丁点 `.`** —— `L.` `sp.` `etc.` 里的点是词的一部分，
   剥了就把「Anthericum ramosum L.」变成错的（`[[criteria-narrower-than-you-think]]`：
   判据比它要描述的东西更宽，这条是我今天第三次在同一形状上收窄）。

用法（在 fr/ 目录下）：
    python3 -u fixes/strip_zh_gloss_period.py            # 只报数
    python3 -u fixes/strip_zh_gloss_period.py --apply
    python3 -u fixes/strip_zh_gloss_period.py --mutate
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


def trailing_period(text):
    """判据本体 —— **写入侧与闸共用这一份**（`[[fix-regression-and-gate]]`）。

    → 剥掉句末中文句号之后的文本；没有可剥的返回 None。
    """
    if not text:
        return None
    s = text.rstrip()
    if not s.endswith("。"):
        return None
    s = s.rstrip("。").rstrip()
    return s or None            # 整条只有一个句号 ⇒ 不动（返回 None）


def plan(con):
    out = []
    for sid, seq, t in con.execute(
            "SELECT sense_id, seq, text FROM sense_gloss WHERE lang='zh' AND text LIKE '%。'"):
        new = trailing_period(t)
        if new and new != t:
            out.append((sid, seq, t, new))
    return out


def mutate():
    print("═══ 变异验证：判据本体 ═══")
    cases = [
        ("🔴 句末中文句号", trailing_period("在教派中被传授奥秘的人。"), "在教派中被传授奥秘的人"),
        ("🔴 句号后有空白", trailing_period("认证签名真实性的行为。 "), "认证签名真实性的行为"),
        ("负控 拉丁学名的命名人缩写（点是词的一部分）",
         trailing_period("百合科白花草本植物，Anthericum ramosum L."), None),
        ("负控 句中有句号但结尾没有", trailing_period("甲。乙"), None),
        ("负控 普通释义", trailing_period("黄色"), None),
        ("负控 整条只有一个句号 ⇒ 不动", trailing_period("。"), None),
        ("负控 空", trailing_period(""), None),
    ]
    ok = 0
    for name, got, want in cases:
        good = got == want
        ok += good
        print("   %s %-40s → %r" % ("✅" if good else "🔴", name, got))
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
    rows = plan(con)
    con.close()
    print("■ 中文释义句末带句号 %s 条" % f(len(rows)))
    for sid, seq, old, new in rows[:8]:
        print("      #%-7s %s → %s" % (sid, old[:44], new[:44]))
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    with dbtool.session("keep-v3-zh-gloss-period", expect={}) as s:
        s.executemany("UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='zh' AND seq=?",
                      [(new, sid, seq) for sid, seq, _o, new in rows])
    print("✓ 剥掉 %s 条" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
