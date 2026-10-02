#!/usr/bin/env python3
"""阶段 3：音标层 —— `pronunciation`。2026-09-28。

判据全部 import 自 `pron_sources.py`（方言归一、剥壳、B10），本文件一条都不重写。

═══ 🔴 一个要当场更正的数 ═══
`VI_PLAN` 阶段 -1 写着「音标并集 58.3%，**41.7% 没有音标** ⇒ 要不要做 G2P（§4.2）」。
那个 58.3% 的分母是**三源并集 84,328 个词形**，而当前 `dict` 只有 30,738 个（英文版那一侧）。
按**当前库**重量：

    dict 里有音标的词形 **29,105 / 30,738 ＝ 94.7%**，没有的只有 **1,633 个**

⇒ **G2P 在这一步远没有计划里说的那么紧迫**。
⚠️ 但 41.7% 那个数**不是错的，它量的是另一件事**（收完三源之后的样子）——
   阶段 4 收词会把两万多个 vi/zh 独有的词形收进来，那时候比例会掉下去。
   `[[measure-landing-not-source]]`：**量落点不量源头**。§4.2 因此不结清，只改口径。

═══ 方言：三类东西混在同两个字段里 ═══
`tags` 与 `note` 里装着 **方言点 / 非越南语读音 / 压根不是方言** 三类。
判据与完整值域在 `pron_sources.py`。这里只说结果：
`General-American` / `US` / `China` 那 328 条是**英语和汉语读音**，整条丢掉 ——
印在越南语词条上会让读者照着读错。

═══ 🔴 认不出的值**一律红**，不静默归 unknown ═══
静默归 unknown ＝ 源头哪天加个新方言点我们悄悄吞掉，而所有闸都绿。

跑（在仓库根）：
    python3 -u vi/pipeline/build_pronunciation.py
    python3 -u vi/pipeline/build_pronunciation.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import gzip
import json
import sqlite3

import dbtool
import paths
import pron_sources as PS

SRC = [("en-edition", paths.KK), ("vi-edition", paths.EDITION),
       ("zh-edition-trad", paths.ZH_TRAD)]


def rd(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def harvest(indict):
    rows = {}
    stat = collections.Counter()
    unknown = collections.Counter()
    for src, p in SRC:
        for e in rd(p):
            w = e["word"]
            for s in e.get("sounds", []) or []:
                raw = s.get("ipa")
                if not raw:
                    continue
                stat["源头带 ipa 的 sounds"] += 1
                dia, verdict = PS.classify(s.get("tags"), s.get("note"))
                if verdict == "drop-not-vietnamese":
                    stat["丢弃·不是越南语读音（英/汉）"] += 1
                    continue
                if verdict == "unknown-value":
                    # 🔴 不静默吞掉 —— 攒起来，让 main 报红
                    for v in (list(s.get("tags") or []) + ([str(s["note"])] if s.get("note") else [])):
                        if v not in PS.DIALECTS and v not in PS.NOT_A_DIALECT:
                            unknown[(src, v)] += 1
                    stat["🔴 方言值认不出"] += 1
                    continue
                ipa = PS.strip_shell(raw)
                if not ipa:
                    stat["丢弃·剥壳后是空的"] += 1
                    continue
                if w not in indict:
                    stat["推迟·词形还不在 dict 里"] += 1
                    continue
                # src_ref 是**内容派生**的，永不用行号
                key = (indict[w], ipa, dia, src)
                if key in rows:
                    stat["同源重复（去重）"] += 1
                    continue
                rows[key] = (indict[w], ipa, dia, src,
                             "pron:%s:%s:%s:%s" % (src, w, dia, ipa))
                stat["收"] += 1
    return list(rows.values()), stat, unknown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    con.close()

    rows, stat, unknown = harvest(indict)
    print("■ 三源收割")
    for k in ("源头带 ipa 的 sounds", "丢弃·不是越南语读音（英/汉）", "🔴 方言值认不出",
              "丢弃·剥壳后是空的", "推迟·词形还不在 dict 里", "同源重复（去重）", "收"):
        if stat[k]:
            print("   %-32s %9s" % (k, format(stat[k], ",")))

    # 🔴 认不出的值：**红**，不是警告
    if unknown:
        print("\n🔴🔴 有 %d 个方言值不在 `pron_sources.DIALECTS` 里 —— "
              "**不许静默归成 unknown**，去把它们登记了：" % len(unknown))
        for (src, v), n in unknown.most_common(20):
            print("     %-16s %-40s %s" % (src, v[:40], format(n, ",")))
        raise SystemExit(1)

    dia = collections.Counter(r[2] for r in rows)
    print("\n■ 方言分布")
    for k, v in dia.most_common():
        mark = "" if k in PS.MAIN_SIX else ("  ← 小地点/未标" if k != "unknown" else "  ← 源头没标")
        print("   %-14s %8s%s" % (k, format(v, ","), mark))

    srcc = collections.Counter(r[3] for r in rows)
    print("\n■ 按源：%s" % "、".join("%s %s" % (k, format(v, ",")) for k, v in srcc.most_common()))

    wid = {r[0] for r in rows}
    print("   覆盖 dict 里 **%s / %s（%.1f%%）** 个词形，无音标的 %s 个"
          % (format(len(wid), ","), format(len(indict), ","),
             100 * len(wid) / len(indict), format(len(indict) - len(wid), ",")))

    xs = [r for r in rows if PS.looks_like_xsampa(r[1])]
    print("   🔴 B10 疑似 X-SAMPA：**%s 条**%s"
          % (format(len(xs), ","), "" if not xs else "  例 " + str([r[1] for r in xs[:4]])))

    dbtool.sample_check([(r[1], r[2], r[3]) for r in rows], 8, ("音标(裸)", "方言", "源"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    n = len(rows)
    with dbtool.session("build-vi-pronunciation",
                        expect={"__rows__": 0, "#pronunciation": n,
                                "pronunciation.ipa": n, "pronunciation.dialect": n},
                        invalidates=["pron-layer：阶段 4 收词后必须重跑 —— 现在有 %s 条"
                                     "因为词形不在 dict 里被推迟了" % format(stat["推迟·词形还不在 dict 里"], ",")]) as s:
        s.executemany(
            "INSERT INTO pronunciation (word_id, ipa, dialect, src, src_ref) "
            "VALUES (?,?,?,?,?)", rows)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("pronunciation 行数", q("SELECT COUNT(*) FROM pronunciation"), n),
        ("ipa 非空", q("SELECT COUNT(*) FROM pronunciation WHERE TRIM(ipa)=''"), 0),
        # 🔴 存裸：剥完壳不许还带着 [] 或 //
        ("ipa 存裸（没有 []//）",
         q("SELECT COUNT(*) FROM pronunciation WHERE ipa GLOB '*[][/]*'"), 0),
        # 🔴 B10 判据**必须 GLOB**：LIKE 不认方括号字符类，写成 LIKE 就是永远不响的闸
        ("B10 没有 X-SAMPA",
         q("SELECT COUNT(*) FROM pronunciation WHERE ipa GLOB '%s'" % PS.XSAMPA_GLOB), 0),
        ("dialect 都在值域内",
         q("SELECT COUNT(*) FROM pronunciation WHERE dialect NOT IN (%s)"
           % ",".join("'%s'" % d for d in sorted(set(PS.DIALECTS.values()) | {"unknown"}))), 0),
        ("每条都挂得上 dict",
         q("SELECT COUNT(*) FROM pronunciation p LEFT JOIN dict d ON d.id=p.word_id "
           "WHERE d.id IS NULL"), 0),
        # 🔴 dialect 在 UNIQUE 键里，所以六个方言点不该互相覆盖 ——
        #    抽一个六点齐全的词，它必须真有六行
        ("六个方言点没有互相覆盖",
         q("SELECT COUNT(*) FROM (SELECT word_id FROM pronunciation "
           "WHERE dialect IN ('ha-noi','hue','sai-gon','vinh','thanh-chuong','ha-tinh') "
           "GROUP BY word_id HAVING COUNT(DISTINCT dialect)>=6)") > 0, True),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-26s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ",") if isinstance(got, int) else got,
                                              format(want, ",") if isinstance(want, int) else want))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
