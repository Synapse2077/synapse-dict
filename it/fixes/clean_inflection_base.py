#!/usr/bin/env python3
"""把 `inflection` 的**原形指针**修正确（`base` 字符串 ↔ `base_id`）。2026-08-19。

═══ 怎么发现的 ═══
阶段 8 记账项「双复数展示」要按 `base_id` 反查一个名词的全部复数形，
`uovo` 却一条都查不到 —— 因为 `uova` 那行的 base 存的是 **`"uovo m"`**：

    uova   base="uovo m"   base_id=NULL   ← 源头把性别缀在词后，我们原样收了
    braccia base="braccio"  base_id=1972   ← 正常的长这样

`base_id` 是 NULL，于是**任何按 base_id 走索引的查询都看不见它**，
而按 `base` 字符串查又匹配不上词头 —— 两条路都堵死。

规模很小（10 行），但它挡住的是整条读取路径，所以先修。

═══ 写这两条断言之后又炸出两族旧问题（都是真的，一并修）═══
② **175 行 `base` 在 dict 里、`base_id` 却是 NULL** —— `solvatare`(46)、`risortire`(6)…
   成因是**词头比变形层后建**（阶段 3 跨版收词、阶段 3a 拆大小写都在变形层之后），
   当时解析不出来就留了空，后来词头有了也没人回填。
③ ⚠️ **3 行「`base_id` 指向大小写不同的另一行」查完不是缺陷** ——
   `auditore`→`Auditore`、`Lungotevere`→`lungotevere`、`Luigino`→`luigino`：
   **base 那个大小写的词形在库里根本不存在**，指向仅有的那一行是合理的
   大小写不敏感解析；断成 NULL 反而更糟（一个链接都没有）。
   ⇒ 断言放宽成「大小写不敏感地一致」。这是 A33 的第三种：**尺子错，不是数据错**。
⇒ 判据统一成一条：`base_id` 必须等于「`base` 精确匹配到的 dict 行」，
   精确匹配不到时允许大小写不敏感的那一行。

═══ 判据 ═══
`base` 结尾是 ` m` / ` f` / ` mf` / ` pl` / ` m pl` / ` f pl`，**且去掉之后能在 dict 里找到**。
去掉后找不到的不动 —— 那说明尾巴不是性别标记（`(formal, uncommon) quanti m pl`
这种整条就是噪声，剥了也没有对应词头）。

用法（在 it/ 目录下）：
    python3 fixes/clean_inflection_base.py            # 干跑
    python3 fixes/clean_inflection_base.py --apply
    python3 fixes/clean_inflection_base.py --verify
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

# 🔴 判据与**收词入口**共用一份（`build_inflection_layer.clean_base`）——
#    只修库不改入口，下次重收又会灌回 `uovo m`（`replay-scripts-undo-fixes`）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from build_inflection_layer import clean_base, _BASE_SUFFIX as SUFFIX   # noqa: E402


def scan(con):
    """→ [(inflection.id, 旧 base, 新 base, 新 base_id, 哪一族)]

    🔴 一次读一张表进字典再比，**不做 SQL 自连接** —— 124 万 × 150 万的自连接
       在这个项目里已经栽过三次（`query-perf-collation-traps`）。
    """
    words = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    out = []
    for rid, base, bid in con.execute("SELECT id, base, base_id FROM inflection"):
        if not base:
            continue
        # ① 尾巴上挂着性别/数标记：**无条件剥**，与收词入口 `clean_base` 同一把尺子。
        # ⚠️ 第一版这里多了个条件「剥完能在 dict 里找到词头才剥」，而入口是无条件剥 ——
        #    两把尺子，外锚闸当场逮到：`(formal, uncommon) quanti m pl` 入口会剥成
        #    `… quanti m`、库里还是 `… m pl`。剥完仍不是词形的那些 `base_id` 照样是 NULL，
        #    剥不剥都不影响可用性，**但必须与入口一致**，否则每次重收都报一条不符。
        clean = clean_base(base)
        if clean != base:
            out.append((rid, base, clean, words.get(clean), "①尾巴"))
            continue
        want = words.get(base)
        if want is None:
            continue                            # 悬空：源头真缺词头，不动
        if bid is None:
            out.append((rid, base, base, want, "②没回填"))
        elif bid != want:
            out.append((rid, base, base, want, "③指错行"))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("🔴 base 还带性别/数尾巴且可剥的", len(scan(con)), 0),
        # 🔴 剥完必须解析出 base_id，否则等于没修（读取路径照样看不见）
        ("🔴 base 在 dict 里、base_id 却是空的",
         q("SELECT count(*) FROM inflection i WHERE i.base_id IS NULL "
           "AND EXISTS(SELECT 1 FROM dict d WHERE d.word=i.base)"), 0),
        # 🔴 base_id 指向的词形必须与 base 一致 —— **大小写不敏感**，理由见文件头 ③
        ("🔴 base_id 指向的词与 base 不一致（折大小写后）",
         q("SELECT count(*) FROM inflection i JOIN dict d ON d.id=i.base_id "
           "WHERE d.word <> i.base COLLATE NOCASE"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-40s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = scan(ro)
    ro.close()
    print("■ 要改 %s 行" % f(len(rows)))
    from collections import Counter
    print("   " + "  ".join("%s %s" % (k, f(v)) for k, v in Counter(r[4] for r in rows).most_common()))
    for rid, old, new, bid, kind in rows[:14]:
        print("   %-6s %-24s → %-20s base_id=%s" % (kind, old[:24], new[:20], bid))
    if not a.apply or not rows:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("clean-inflection-base", expect={"__rows__": 0}) as s:
        s.executemany("UPDATE inflection SET base=?, base_id=? WHERE id=?",
                      [(new, bid, rid) for rid, _o, new, bid, _k in rows])
        s.written = len(rows)
    print("\n■ 已改 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
