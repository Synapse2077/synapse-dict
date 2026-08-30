#!/usr/bin/env python3
"""阶段 5a — 频次层：给 `dict` 加 `freq_zipf`（wordfreq，离线、同输入同输出）。2026-08-30。

═══ 为什么加这一列 ═══
`level`（CEFR）是全库唯一**没有源、也无法回源**的字段：改不动、验不了。
⇒ 不修它，改为加一个**客观、可复现**的频次列。wordfreq 是离线词表，
同一个输入永远同一个输出，谁跑都一样。

🔴 **这一列是 G2P 决策的前置。** `[[es-audio-and-examples-wip]]`：es 第一轮按 `level`
   挑词**挑错了**（`es`/`hay`/`está` 六个最常用词一个合成音都没有，反而给了
   zipf 1.01 的 `lavaparabrisas`），因为 `level` 只给内容词打标、语法词全 NULL。
   pt 的 G2P 决策（`PT_PLAN` §四.2）就是等这一列到位才能算账。

═══ 🔴 判据只有一条：`tokenize(w, 'pt') == [w.lower()]` ═══
`[[wordfreq-ruler-traps]]` 的四个坑在葡语上**逐条实测**（不是从 fr 抄的）：

    -mente         tokenize → ['mente']              zipf 5.00   ❌ 查成了「心智」/「说谎」的变位
    anti-          tokenize → ['anti']               zipf 4.68   ❌ 前缀被静默剥掉
    guarda-chuva   tokenize → ['guarda','chuva']     zipf 4.55   ❌ 两个词拼出来的
    d'água         tokenize → ['d','água']           zipf 5.25   ❌ 同上
    não abdiques   tokenize → ['não','abdiques']     zipf 0.00   ❌ 多词
    São Paulo      tokenize → ['são','paulo']        zipf 5.61   ❌ 多词
    ababalhares    tokenize → 同词形                    zipf 0.00   ✅ 人称不定式，真的查不到
    ação           tokenize → 同词形                    zipf 5.21   ✅

⚠️ **葡语比法语更依赖这条判据的两个地方**：
   ① **连字符复合词特别多**（`guarda-chuva`/`pé-de-moleque`/`fim-d'águas`），
      全部会被拆开查成不相干的高频词。
   ② **否定命令式是两个词**（`não + 虚拟式`，葡语特有）——
      阶段 3 收进来十几万条这种形式，它们**注定量不了**。
      那是"测不了"，不是"很罕见"，所以必须是 NULL 不是 0.0。

⚠️ **wordfreq 的 `pt` 语料偏巴西**（实测 `ação` 5.21 vs 欧葡拼写 `acção` 4.36）。
   两种拼写都在表里，但数值有系统性偏差 ⇒ 这一列**不能**用来判"哪个拼写更标准"，
   只能用来排"读者更可能查到哪个词"。

═══ 0.0 与 NULL 的区别（不许混）═══
· `freq_zipf = 0.0`  —— **量过了，语料里没出现**。这是一个测量结果。
· `freq_zipf IS NULL` —— **量不了**（多词/词缀/带撇号，tokenize 判据没过）。
  硬给它们填一个数，就是把"测不了"伪装成"很罕见"。

用法（在 pt/ 目录下）：
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

LANG = "pt"
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
    """⭐ 变异验证：判据本体。用例**全部在葡语上实测过**，不是从 fr 抄的。"""
    print("═══ 变异验证：判据本体 ═══")
    cases = [
        ("🔴 前缀不许量（`anti-` → `anti`）", freq_of("anti-"), None),
        ("🔴 后缀不许量（`-mente` → `mente`＝心智/说谎的变位）", freq_of("-mente"), None),
        ("🔴 连字符复合词不许量（葡语特别多）", freq_of("guarda-chuva"), None),
        ("🔴 带撇号的不许量（`d'água` → `d` + `água`）", freq_of("d'água"), None),
        ("🔴 **否定命令式不许量**（`não`+虚拟式，葡语特有的两词形式）",
         freq_of("não abdiques"), None),
        ("🔴 多词专名不许量（`São Paulo`）", freq_of("São Paulo"), None),
        ("普通词量得了", freq_of("casa") > 5, True),
        ("专名只是折大小写，量得了", freq_of("Lisboa") > 4, True),
        ("带鼻音符的量得了（`coração` tokenize 不拆）", freq_of("coração") > 4, True),
        ("欧葡拼写也在表里（`acção`）", freq_of("acção") > 3, True),
        ("🔴 人称不定式是 0.0 不是 None（量过了，语料里没有）",
         freq_of("ababalhares"), 0.0),
    ]
    ok = 0
    for name, got, want in cases:
        good = got == want
        ok += good
        print("   %s %-52s → %s" % ("✅" if good else "🔴", name, got))
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
    # 🔴 `expect` 比的是**增量**不是总数。第一版写成 `len(rows)`（总数），
    #    补跑新收的词时就报「变化 +0，期望 +657,907」——
    #    **闸是对的、数据也是对的，错的是我的声明**（2026-08-30 实测）。
    #    ⇒ 增量 = 这次要写的行里，原本还是 NULL 的那些。
    ro2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    had = {i for (i,) in ro2.execute(
        "SELECT id FROM dict WHERE freq_zipf IS NOT NULL")} \
        if "freq_zipf" in {r[1] for r in ro2.execute("PRAGMA table_info(dict)")} else set()
    ro2.close()
    delta = sum(1 for _v, wid in rows if wid not in had)
    with dbtool.session("build-pt-freq-layer",
                        expect={"__rows__": 0, "freq_zipf": delta}) as s:
        s.addcolumn("freq_zipf", "REAL")
        s.executemany("UPDATE dict SET freq_zipf=? WHERE id=?", rows)
    print("\n■ 已写 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
