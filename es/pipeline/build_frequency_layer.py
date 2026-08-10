#!/usr/bin/env python3
"""给 `dict` 加频次列：`freq_zipf` / `freq_lemma_zipf` / `freq_src`。2026-08-07。

═══ 为什么要这个 ═══
`level`（CEFR）是全库**唯一一个没有源、也无法回源**的字段 —— 它不是从 dump 抽的，
是 2026-07 那轮 `b_enrich.py` 让豆包凭一句「按该西语词实际频率与掌握难度判断」现编的，
10.5 万条，无锚点、无复核，同批重跑还不一致。

本脚本不动 `level` 一个字节，只**加两列客观频次**，来源 wordfreq 3.1.1（Apache-2.0，
离线包，同输入永远同输出）。拿到之后可以反查 `level` 错在哪儿，再决定徽章怎么办。

⭐ 加列是加法操作：不想用就不查这两列，要撤就 `UPDATE dict SET freq_zipf=NULL`。

═══ 🔴 wordfreq 的三个陷阱（实测，都会咬人）═══
① **多词条目的 zipf 是拼出来的，不是查出来的**
     vete a la mierda  4.16      mierda a vete la  4.16   ← 打乱语序，一模一样
     jirafa telescopio armario  2.86                      ← 现编的短语，比 pediculosis(1.62) 还"常用"
     el el el  6.97                                       ← 全库最高
   ⇒ 多词一律不填。

② **词缀会被静默剥掉再查**，比多词更阴 —— 它返回一个单 token，看起来是正常查表：
     -an   → token 'an'   4.43     a-  → token 'a'  7.36（介词 a 的频次！）
   ⇒ 判据不能用 token **个数**，要用「**查的是不是我这个词形本身**」：
       `tokenize(w, 'es') == [w.lower()]`
     这一条同时挡掉多词、带点缩写、词缀三类，不必手写正则去猜。

③ **大小写被折叠**：`Chad`/`chad`、`LED`/`led`、`Tabasco`/`tabasco` 各拿同一个数。
   全库 2,282 组 / 4,564 行同形。我们 2026-08-07 刚把它们拆成独立词条，
   wordfreq 分不开 ⇒ 照填，但 `freq_src` 打上 `/case` 标记，让下游知道这个数分不开。

═══ freq_lemma_zipf：范式加总（派生，标注清楚）═══
wordfreq 是**词形**表不是**词元**表。抽 600 个词实测：
    动词的范式合计比原形高 **+0.37** zipf，名词只高 +0.11
    conocer 原形 5.13 → 范式合计 5.74（83 个词形）
直接拿原形 zipf 排序，动词会整体显得比实际罕见 —— 而动词恰是初级词表的主体。

加总规则（两条都是**保守**取向，宁可低估不可高估）：
  · 只加 `is_lemma=0` 的词形。`vino`(酒) 自己是 lemma 行，不会被算进 `venir` 头上。
  · **一形多主的词形排除**：`fui` 的 exchange 是 `0:ir\\n0:ser` 两行，
    算给谁都是错的 ⇒ 谁都不算。
  🔴 `exchange` 是**多行**的，`ex[2:]` 会切出 `ir\\n0:ser` 这种垃圾键，必须按行拆。

═══ 三道闸（docs/SCHEMA.md §5.0）═══
① 可逆性回核：把库里每一行读回来，**重新查一遍 wordfreq 逐值比对**（全量，非抽样）
② 不变量断言：多词/词缀行必须全 NULL；zipf ∈ [0,8]；范式合计 ≥ 原形；非 lemma 行无合计
③ 抽样：确定性转换，不适用
⭐ 闸写完必须变异验证 —— `--mutate` 会故意破坏 5 处，闸全抓住才算数

用法（在仓库根）：
    python3 -m es.pipeline.build_frequency_layer            # 试算，不写库
    python3 -m es.pipeline.build_frequency_layer --apply
    python3 -m es.pipeline.build_frequency_layer --verify   # 只跑闸①②
    python3 -m es.pipeline.build_frequency_layer --mutate   # 变异验证：闸抓不抓得住
"""
import argparse
import collections
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

from wordfreq import tokenize, zipf_frequency   # noqa: E402

SRC = "wordfreq-3.1.1"
COLS = {"freq_zipf": "REAL", "freq_lemma_zipf": "REAL", "freq_src": "TEXT"}


def lookup(w: str) -> float | None:
    """查 wordfreq。**只认「查的就是这个词形本身」的情形**，否则一律 None。

    见 docstring 陷阱①②：多词是拼的、词缀是剥了再查的，两者都会返回一个
    像模像样的数字。`tokenize(w) == [w.lower()]` 是唯一能同时挡住两类的判据。
    """
    if tokenize(w, "es") != [w.lower()]:
        return None
    z = zipf_frequency(w, "es")
    return z if z > 0 else None          # wordfreq 用 0.0 表示"表里没有"


def paradigms(con):
    """原形 → 归它独有的变形词形集合。见 docstring「范式加总」两条保守规则。"""
    owner = collections.defaultdict(set)          # 词形 → 它声称的所有原形
    for w, ex in con.execute(
            "SELECT word, exchange FROM dict WHERE is_lemma=0 "
            "AND exchange IS NOT NULL AND exchange <> ''"):
        for ln in ex.splitlines():                # 🔴 exchange 是多行的
            ln = ln.strip()
            if ln.startswith("0:") and ln[2:]:
                owner[w].add(ln[2:])
    par = collections.defaultdict(set)
    dropped = 0
    for form, lems in owner.items():
        if len(lems) > 1:                         # 一形多主：算给谁都是错的
            dropped += 1
            continue
        par[next(iter(lems))].add(form)
    return par, dropped


def compute(con):
    """→ {row_id: (freq_zipf, freq_lemma_zipf, freq_src)}，以及统计。"""
    rows = con.execute("SELECT id, word, is_lemma FROM dict").fetchall()
    case_dup = collections.Counter(w.lower() for _, w, _ in rows)
    par, dropped = paradigms(con)

    zc: dict[str, float | None] = {}              # 词形 → zipf（查一次就够）
    for _, w, _ in rows:
        if w not in zc:
            zc[w] = lookup(w)

    plan, stat = {}, collections.Counter()
    stat["一形多主的词形（不计入任何范式）"] = dropped
    for rid, w, is_lem in rows:
        z = zc[w]
        if z is None:
            stat["查不到 / 多词 / 词缀 ⇒ 三列都 NULL"] += 1
            continue
        src = SRC + ("/case" if case_dup[w.lower()] > 1 else "")
        lz = None
        if is_lem:
            tot = 10 ** z
            for f in par.get(w, ()):
                fz = zc.get(f)
                if fz is None:
                    fz = zc[f] = lookup(f)
                if fz is not None:
                    tot += 10 ** fz
            lz = round(math.log10(tot), 4)
        plan[rid] = (round(z, 4), lz, src)
        stat["原形，含范式合计" if is_lem else "变形词形，只填词形频次"] += 1
        if "/case" in src:
            stat["  其中大小写同形（两行同值，分不开）"] += 1
    return plan, stat


# ═══════════════════════════ 闸 ═══════════════════════════

def gate1(con) -> bool:
    """闸① 可逆性回核：把库里的值重新算一遍，逐值比对（全量，非抽样）。"""
    print("\n═══ 闸① 可逆性回核（全量，非抽样）═══")
    want, _ = compute(con)
    have, n = {}, 0
    for rid, z, lz, src in con.execute(
            "SELECT id, freq_zipf, freq_lemma_zipf, freq_src FROM dict"):
        n += 1
        if src is not None or z is not None or lz is not None:
            have[rid] = (z, lz, src)
    bad = []
    for rid in set(want) | set(have):
        a, b = want.get(rid), have.get(rid)
        if a != b:
            bad.append((rid, a, b))
    print(f"  逐行重算 {n:,} 行，其中有值的 库里 {len(have):,} / 重算 {len(want):,}")
    print(f"  对不上的：{len(bad)}")
    for rid, a, b in bad[:5]:
        w = con.execute("SELECT word FROM dict WHERE id=?", (rid,)).fetchone()[0]
        print(f"     🔴 {w}  重算={a}  库里={b}")
    if bad:
        return False
    print("  ✅ 闸① 通过：库里每一行都能从 wordfreq 原样重算出来")
    return True


def gate2(con) -> bool:
    """闸② 不变量断言。"""
    print("\n═══ 闸② 不变量断言 ═══")
    ok = True
    checks = [
        # ⚠️ 这一条最初还写了 `word LIKE '%.%'`，落库后报了 5 行「违规」：
        #    `n.º` `M.ª` `S.A.D` `S.A.s` `D.ª`。回去查 `tokenize` 才发现它们
        #    **本来就是单个 token**，wordfreq 查的就是这个词形本身，值是真的 ——
        #    错的是我这道闸：带点 ≠ 多词，我拿手搓的近似判据当了规则。
        #    留下的两条是真·独立不变量：空格必然是复合、连字符会被 wordfreq 静默剥掉。
        ("含空格或连字符的行竟有频次",
         "SELECT COUNT(*) FROM dict WHERE freq_zipf IS NOT NULL "
         "AND (word LIKE '% %' OR word LIKE '-%' OR word LIKE '%-')"),
        ("zipf 超出 [0,8]",
         "SELECT COUNT(*) FROM dict WHERE freq_zipf NOT BETWEEN 0 AND 8 "
         "OR freq_lemma_zipf NOT BETWEEN 0 AND 8"),
        ("范式合计 < 原形（加总只能增不能减）",
         "SELECT COUNT(*) FROM dict WHERE freq_lemma_zipf IS NOT NULL "
         "AND freq_zipf IS NOT NULL AND freq_lemma_zipf < freq_zipf - 1e-6"),
        ("非原形行竟有范式合计",
         "SELECT COUNT(*) FROM dict WHERE is_lemma=0 AND freq_lemma_zipf IS NOT NULL"),
        ("有 freq_src 却没有 freq_zipf",
         "SELECT COUNT(*) FROM dict WHERE freq_src IS NOT NULL AND freq_zipf IS NULL"),
        ("有 freq_zipf 却没有 freq_src",
         "SELECT COUNT(*) FROM dict WHERE freq_zipf IS NOT NULL AND freq_src IS NULL"),
    ]
    for name, sql in checks:
        n = con.execute(sql).fetchone()[0]
        print(f"  {'🔴' if n else '  '} {name:<38}{n}")
        ok &= n == 0
    return ok


def mutate(con_path) -> None:
    """⭐ 变异验证：一条永远通过的检查等于没检查。故意破坏 5 处，看闸抓不抓得住。"""
    print("\n" + "=" * 60)
    print("⭐ 变异验证：在**副本**上故意制造 5 种错误，逐个看闸的反应")
    print("=" * 60)
    import shutil
    import tempfile
    muts = [
        ("① 改一行的 zipf（伪造频次）",
         "UPDATE dict SET freq_zipf = 7.5 WHERE word='casa'"),
        ("② 给一个多词条目填上频次",
         "UPDATE dict SET freq_zipf=4.19, freq_src='x' WHERE word='té verde'"),
        ("③ 给一个词缀填上频次（陷阱②那类）",
         "UPDATE dict SET freq_zipf=4.43, freq_src='x' WHERE word='-an'"),
        ("④ 把范式合计改成小于原形",
         "UPDATE dict SET freq_lemma_zipf=1.0 WHERE word='conocer'"),
        ("⑤ 清掉一行的值（漏填）",
         "UPDATE dict SET freq_zipf=NULL, freq_lemma_zipf=NULL, freq_src=NULL "
         "WHERE word='libro'"),
    ]
    caught = 0
    for name, sql in muts:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.sqlite"
            shutil.copy2(con_path, p)
            c = sqlite3.connect(p)
            c.execute(sql)
            c.commit()
            c.close()
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                good = gate1(c) and gate2(c)
            c.close()
            caught += not good
            print(f"  {'✅ 抓住' if not good else '🔴 漏过'}  {name}")
    print(f"\n  {caught}/5 被抓住" + ("" if caught == 5 else "  🔴 有闸是摆设，必须修"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    args = ap.parse_args()

    if args.verify or args.mutate:
        con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
        ok = gate1(con) and gate2(con)
        con.close()
        print(f"\n{'✅ 两道闸都通过' if ok else '🔴 有闸没过'}")
        if args.mutate:
            mutate(paths.DB)
        return

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    plan, stat = compute(con)
    print(f"待写 {len(plan):,} 行")
    for k, v in stat.most_common():
        print(f"  {k:<40}{v:>9,}")

    band = collections.Counter()
    for z, lz, _ in plan.values():
        v = lz if lz is not None else z
        band["zipf ≥ 6" if v >= 6 else "5 – 6" if v >= 5 else "4 – 5" if v >= 4
             else "3 – 4" if v >= 3 else "< 3"] += 1
    print("\n  分布（原形用范式合计，变形用词形值）：")
    for k in ("zipf ≥ 6", "5 – 6", "4 – 5", "3 – 4", "< 3"):
        print(f"    {k:<12}{band[k]:>9,}")

    ids = {w: i for i, w in con.execute("SELECT id, word FROM dict WHERE is_lemma=1")}
    dbtool.sample_check(
        [(w, con.execute("SELECT level FROM dict WHERE id=?", (ids[w],)).fetchone()[0] or "—",
          f"{plan[ids[w]][0]:.2f}" if ids.get(w) in plan else "—",
          f"{plan[ids[w]][1]:.2f}" if ids.get(w) in plan and plan[ids[w]][1] else "—")
         for w in ("casa", "agua", "comer", "conocer", "cuchara", "banco",
                   "nube", "pediculosis", "Wuhan", "chad")
         if w in ids],
        10, ("词", "level", "词形 zipf", "范式合计"))
    con.close()

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    n_lz = sum(1 for _, lz, _ in plan.values() if lz is not None)
    with dbtool.session("build-frequency-layer",
                        expect={"freq_zipf": len(plan), "freq_lemma_zipf": n_lz,
                                "freq_src": len(plan)}) as s:
        for c, t in COLS.items():
            s.addcolumn(c, t)
        s.executemany(
            "UPDATE dict SET freq_zipf=?, freq_lemma_zipf=?, freq_src=? WHERE id=?",
            [(z, lz, src, rid) for rid, (z, lz, src) in plan.items()])

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    ok = gate1(con) and gate2(con)
    con.close()
    if ok:
        print("\n✅ 两道闸都通过")
        return
    # ⚠️ 闸跑在 commit **之后**（它们要读已落库的值），所以这里已经写进去了。
    #    先前这里印的是「回滚」—— 那是句谎话，什么都没回滚。要撤得自己 cp 备份。
    last = sorted(paths.BACKUPS.glob("*.pre-build-frequency-layer-*.bak"))[-1]
    print(f"\n🔴 有闸没过。数据**已经写进库了**，要撤请手动回滚：\n"
          f"   cp {last} {paths.DB}")


if __name__ == "__main__":
    main()
