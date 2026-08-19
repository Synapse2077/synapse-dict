#!/usr/bin/env python3
"""阶段 5：频次层 —— 给 `dict` 加 `freq_zipf`（wordfreq，离线、同输入同输出）。2026-08-18。

═══ 为什么加这一列（A12）═══
`level`（CEFR）是全库唯一**没有源、也无法回源**的字段：改不动、验不了。
⇒ 不修它，改为加一个**客观、可复现**的频次列。wordfreq 是离线词表，
同一个输入永远同一个输出，谁跑都一样。

═══ 🔴 判据只有一条：`tokenize(w, 'it') == [w.lower()]` ═══
这是 `wordfreq-ruler-traps` 那条记的四个坑里最狠的一个 —— **词缀会被静默剥掉再查**：

    a-                   tokenize → ['a']                  zipf 7.21   ❌ 查的是介词 a
    moto d'acqua         tokenize → ['moto','d','acqua']   zipf 4.59   ❌ 查的是三个词拼的
    Roma                 tokenize → ['roma']               zipf 5.63   ✅ 只是折了大小写
    ricamucchierebbero   tokenize → 同词形                   zipf 0.0    ✅ 真的查不到

不加这条判据，前两行会得到**看着很高、其实完全不相干**的频次，而且没有任何报错。

═══ 0.0 与 NULL 的区别（不许混）═══
· `freq_zipf = 0.0` —— **量过了，语料里没出现**。这是一个测量结果。
· `freq_zipf IS NULL` —— **量不了**（多词/词缀/带符号，tokenize 判据没过）。
  硬给它们填一个数，就是把"测不了"伪装成"很罕见"。

用法（在 it/ 目录下）：
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

import dbtool                                  # noqa: E402
import paths                                   # noqa: E402
from wordfreq import tokenize, zipf_frequency   # noqa: E402

LANG = "it"
f = lambda n: format(n, ",")


def measurable(w):
    """判据本体（写入与闸共用）→ 这个词形的频次量不量得了。"""
    try:
        return tokenize(w, LANG) == [w.lower()]
    except Exception:
        return False


def freq_of(w):
    """→ zipf 频次；量不了返回 None。"""
    return zipf_frequency(w, LANG) if measurable(w) else None


def scan(con):
    rows, c = [], Counter()
    for wid, w in con.execute("SELECT id, word FROM dict"):
        v = freq_of(w)
        c["量得了" if v is not None else "量不了（多词/词缀/带符号）"] += 1
        if v is not None:
            c["其中语料里出现过" if v > 0 else "其中语料里查不到（0.0）"] += 1
            rows.append((v, wid))
    return rows, c


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    # 判据本体全量复算：库里给了值的，必须都能通过 tokenize 判据，且值要对得上
    bad_rule = bad_val = 0
    for w, v in con.execute("SELECT word, freq_zipf FROM dict WHERE freq_zipf IS NOT NULL"):
        if not measurable(w):
            bad_rule += 1
        elif abs(zipf_frequency(w, LANG) - v) > 1e-9:
            bad_val += 1
    miss = 0
    for w, in con.execute("SELECT word FROM dict WHERE freq_zipf IS NULL"):
        if measurable(w):
            miss += 1
    checks = [
        ("🔴 ① 给了值却过不了 tokenize 判据的（词缀被静默剥掉那族）", bad_rule, 0),
        ("🔴 ① 值与 wordfreq 重算对不上的（全量复算）", bad_val, 0),
        ("🔴 ① 明明量得了却留空的", miss, 0),
        ("🔴 ② 值必须在 0–8 之间",
         q("SELECT count(*) FROM dict WHERE freq_zipf IS NOT NULL "
           "AND (freq_zipf < 0 OR freq_zipf > 8)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-50s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def mutate():
    print("═══ 变异验证：判据本体 ═══")
    cases = [
        ("🔴 词缀不许量（tokenize 会把 `-` 剥掉）", freq_of("a-"), None),
        ("🔴 多词不许量（会被拆成三个词拼）", freq_of("moto d'acqua"), None),
        ("普通词量得了", freq_of("casa") > 5, True),
        ("专名只是折大小写，量得了", freq_of("Roma") > 4, True),
        ("🔴 生僻词是 0.0 不是 None（量过了，语料里没有）",
         freq_of("ricamucchierebbero"), 0.0),
        ("🔴 带撇号的多词形不许量", freq_of("l'altro ieri"), None),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-46s → %s" % ("✅" if good else "🔴", name, got))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


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
    print("■ 词形 %s" % f(sum(v for k, v in c.items() if k.startswith(("量得了", "量不了")))))
    for k, v in c.most_common():
        print("     %-34s %s" % (k, f(v)))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("build-freq-layer", expect={"__rows__": 0, "freq_zipf": len(rows)}) as s:
        s.addcolumn("freq_zipf", "REAL")
        s.executemany("UPDATE dict SET freq_zipf=? WHERE id=?", rows)
    print("\n■ 已写 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
