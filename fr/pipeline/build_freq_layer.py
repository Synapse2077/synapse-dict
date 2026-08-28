#!/usr/bin/env python3
"""阶段 5 补做 — 频次层：给 `dict` 加 `freq_zipf`（wordfreq，离线、同输入同输出）。2026-08-27。

═══ 为什么加这一列 ═══
`level`（CEFR）是全库唯一**没有源、也无法回源**的字段：改不动、验不了。
⇒ 不修它，改为加一个**客观、可复现**的频次列。wordfreq 是离线词表，
同一个输入永远同一个输出，谁跑都一样。

🔴 阶段 5 声明的四层里这一层整层没做（收尾单 B2）。做族 E 探针要按"读者真会
   查到的词"分臂时，我只能在探针里现算 wordfreq —— 那就是这一列缺席的代价。

═══ 🔴 判据只有一条：`tokenize(w, 'fr') == [w.lower()]` ═══
`[[wordfreq-ruler-traps]]` 四个坑里最狠的一个 —— **词缀会被静默剥掉再查**，
法语上同样成立（实测）：

    anti-           tokenize → ['anti']                     zipf 4.88   ❌ 查的是别的东西
    -ment           tokenize → ['ment']                     zipf 4.19   ❌ 查的是动词 mentir 的变位
    pomme de terre  tokenize → ['pomme','de','terre']       zipf 4.19   ❌ 三个词拼出来的
    l'eau           tokenize → ['l','eau']                  zipf 5.45   ❌ 同上
    C'est-à-dire    tokenize → ['c','est','à','dire']       zipf 5.87   ❌ 同上
    Paris           tokenize → ['paris']                    zipf 5.71   ✅ 只是折了大小写
    recroquevil…ons tokenize → 同词形                          zipf 0.0    ✅ 真的查不到

不加这条判据，前五行会得到**看着很高、其实完全不相干**的频次，而且没有任何报错。
⚠️ 法语的多词条目和带撇号条目**特别多**（`aux Essarts` / `l'eau` / `c'est-à-dire`），
   这条判据在 fr 上比在 it 上更要紧。

═══ 0.0 与 NULL 的区别（不许混）═══
· `freq_zipf = 0.0`  —— **量过了，语料里没出现**。这是一个测量结果。
· `freq_zipf IS NULL` —— **量不了**（多词/词缀/带撇号，tokenize 判据没过）。
  硬给它们填一个数，就是把"测不了"伪装成"很罕见"。

用法（在 fr/ 目录下）：
    python3 pipeline/build_freq_layer.py            # 干跑
    python3 pipeline/build_freq_layer.py --apply
    python3 pipeline/build_freq_layer.py --verify
    python3 pipeline/build_freq_layer.py --mutate
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool                                   # noqa: E402
import paths                                    # noqa: E402
from wordfreq import tokenize, zipf_frequency   # noqa: E402

LANG = "fr"
f = lambda n: format(n, ",")


def measurable(w):
    """判据本体（写入与闸**共用这一份**）→ 这个词形的频次量不量得了。

    🔴 `[[fix-regression-and-gate]]`：闸与它守的那段逻辑用两个判据 ⇒ 闸在报自己的 bug。
    """
    try:
        return tokenize(w, LANG) == [w.lower()]
    except Exception:
        return False


def freq_of(w):
    """→ zipf 频次；**量不了返回 None，不是 0.0**。"""
    return zipf_frequency(w, LANG) if measurable(w) else None


def scan(con):
    rows, c = [], Counter()
    for wid, w in con.execute("SELECT id, word FROM dict"):
        v = freq_of(w)
        c["量得了" if v is not None else "量不了（多词/词缀/带撇号）"] += 1
        if v is not None:
            c["  其中语料里出现过" if v > 0 else "  其中语料里查不到（0.0）"] += 1
            rows.append((v, wid))
    return rows, c


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    # 判据本体**全量复算**（不抽样）：库里给了值的必须都过 tokenize 判据，且值对得上
    bad_rule = bad_val = 0
    for w, v in con.execute("SELECT word, freq_zipf FROM dict WHERE freq_zipf IS NOT NULL"):
        if not measurable(w):
            bad_rule += 1
        elif abs(zipf_frequency(w, LANG) - v) > 1e-9:
            bad_val += 1
    miss = sum(1 for (w,) in con.execute(
        "SELECT word FROM dict WHERE freq_zipf IS NULL") if measurable(w))
    checks = [
        ("🔴 ① 给了值却过不了 tokenize 判据（词缀被静默剥掉那族）", bad_rule, 0),
        ("🔴 ① 值与 wordfreq 重算对不上（全量复算）", bad_val, 0),
        ("🔴 ① 明明量得了却留空", miss, 0),
        ("🔴 ② 值必须在 0–8 之间",
         q("SELECT COUNT(*) FROM dict WHERE freq_zipf IS NOT NULL "
           "AND (freq_zipf < 0 OR freq_zipf > 8)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-50s %s（期望 %s）" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def mutate():
    """⭐ 变异验证：判据本体。用例全是**法语上实测过**的，不是从 it 抄的。"""
    print("═══ 变异验证：判据本体 ═══")
    cases = [
        ("🔴 前缀不许量（`-` 被剥掉后查的是别的词）", freq_of("anti-"), None),
        ("🔴 后缀不许量（`-ment` → `ment`，查成了 mentir 的变位）", freq_of("-ment"), None),
        ("🔴 多词不许量（拆成三个词拼）", freq_of("pomme de terre"), None),
        ("🔴 带撇号的不许量（`l'eau` → `l` + `eau`）", freq_of("l'eau"), None),
        ("🔴 连字符多词不许量（`c'est-à-dire` 拆成四段）", freq_of("c'est-à-dire"), None),
        ("普通词量得了", freq_of("maison") > 5, True),
        ("专名只是折大小写，量得了", freq_of("Paris") > 5, True),
        ("带合字的量得了（`œuf` tokenize 不拆）", freq_of("œuf") > 3, True),
        ("🔴 生僻变位是 0.0 不是 None（量过了，语料里没有）",
         freq_of("recroquevillassions"), 0.0),
    ]
    ok = 0
    for name, got, want in cases:
        good = got == want
        ok += good
        print("   %s %-50s → %s" % ("✅" if good else "🔴", name, got))
    print("\n   变异 %d/%d" % (ok, len(cases)))
    return ok == len(cases)


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows, c = scan(ro)
    ro.close()
    print("■ 词形 %s" % f(sum(v for k, v in c.items() if not k.startswith("  "))))
    for k, v in c.most_common():
        print("     %-34s %s" % (k, f(v)))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("build-fr-freq-layer",
                        expect={"__rows__": 0, "freq_zipf": len(rows)}) as s:
        s.addcolumn("freq_zipf", "REAL")
        s.executemany("UPDATE dict SET freq_zipf=? WHERE id=?", rows)
    print("\n■ 已写 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
