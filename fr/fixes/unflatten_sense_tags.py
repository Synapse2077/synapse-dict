#!/usr/bin/env python3
"""收尾单 A4 — 标签被**多条源义项压平**到同一条出版义项上。2026-08-28。

═══ 🔴 我记账里的诊断是错的 ═══
收尾单原文写的是「族 C 地区优先级：`cervelle` 印「路易斯安那 古语」，
而法文版给的是通用义 ⇒ 等有了法语地区词表再做」。
地区词表在族 C 第二段已经补齐了，回头做这件事，一查**根本不是优先级问题**：

    出版层 `cervelle` 只有 2 条义项，而源头有 6 条：
      en #0  Louisiana / archaic / derogatory     ← 路易斯安那法语里"笨蛋"那个义
      en #1  （无）
      fr #0.0  anatomy                            ← r1「大脑，脑」真正对应的是这条
      fr #0.1  colloquial / metonymically / pejorative
      fr #0.2  especially / cuisine
      fr #0.3  figuratively
    ⇒ 六条证据的标签**全堆到 r1 上**，于是核心义「大脑」旁边印着「路易斯安那 古语 贬义」。

这与族 B 的徽标串味、A2 的 `mf` 压平**完全同源**：
**把多个义项的属性压到一个载体上**（`[[case-folding-contaminates-columns]]`）。

═══ 规模：47,310 是上界，真值 4,516 ═══
「一条出版义项挂着 ≥2 条带不同标签的证据」有 47,310 条，但**大多数是对的**：

    chien「狗」  en 给 ['masculine']、fr 给 ['Cynologie']   ← 两版各说一面，合并正确
    book「投资组合」 en ['masculine']、fr ['Anglicism','photography']  ← 同上

⇒ 真压平的信号是**同一版内多条义项**带不同标签落到同一条出版义项上：

    livre「书籍」 fr #0.2 metonymically/plural · #0.8 commerce · #0.9 diplomacy · #0.10 collectively
    abandon「放弃」 fr #0.5 broadly · #0.7 law · #0.8 law · #0.12 finance · #0.13 psychology

    跨版互补（正确）  43,630
    🔴 同版压平        4,516

═══ 怎么知道该留哪一条：**按文本回指** ═══
`sense_gloss.src` 只记版本、不记是哪条义项。但**出版层的法语定义是从某一条证据
逐字来的**（`clean()` 只删不改写，这一点由 `reclean_published_fr_defs` 的子序列闸保证）
⇒ 拿 `clean(证据文本, 词) == 出版定义` 回指。实测：

    唯一命中一条证据   630,589 / 631,457 = **99.9%**
    命中多条（文本相同）     369
    匹配不上                499     ← 这两类一律**不动**

═══ 只删「串过来的」，不碰别的 ═══
删除判据必须同时满足：
  ① 该标签**不来自**命中的那条 fr 证据
  ② 该标签**不来自**任何 en-edition 证据（跨版互补要留）
  ③ 该标签**确实来自**某条没命中的 fr 证据（＝证明它是串过来的，不是别处来的）

🔴 ③ 不能省。`sense_tag` 里还有 17,860 行是本轮之前的老流水线写的、来源不明；
   少了 ③ 就会把它们一起删掉 —— 那是"重算一遍再覆盖"，不是"删掉串味的"。

⚠️ 分桶表与 skip 表**全部 import**，不在这里抄第二份
（`[[refactor-mindset-code-quality]]`；族 C 那轮的 `table()` 抄错一次已经付过学费）。

用法（在 fr/ 目录下）：
    python3 -u fixes/unflatten_sense_tags.py            # 只报数
    python3 -u fixes/unflatten_sense_tags.py --apply
"""
import argparse
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402
from gloss_clean import clean                    # noqa: E402
from ingest_fr_tags import maps, skip_set        # noqa: E402
from ingest_fr_topics import topic_keys          # noqa: E402

f = lambda n: format(n, ",")


# 🔴 分桶表只读一次。第一版把 `maps()/skip_set()/topic_keys()` 写在函数体里，
#    于是**每条证据都重读一遍那几个 .ts 文件** —— 83 万次文件 IO，跑不完。
#    （`[[enrich-perf-discipline]]`：小切片先计时。）
_TBL = None


def _tables():
    global _TBL
    if _TBL is None:
        _TBL = maps() + (skip_set(), topic_keys())
    return _TBL


def bucket_all(raw):
    """一条证据的 raw_tags → {(kind, value)}。**判据与 ingest 两步共用同一批表。**"""
    topic, region, reg, zh_topic, zh_region, zh_reg, skip, tk = _tables()
    out = set()
    try:
        d = json.loads(raw or "{}")
    except ValueError:
        return out
    for t in (d.get("topics") or []):
        if t in tk:
            out.add(("topic", t))
    for t in (d.get("tags") or []) + (d.get("raw_tags") or []):
        if t in skip:
            continue
        for tbl, kind, zh in ((topic, "topic", zh_topic), (region, "region", zh_region),
                              (reg, "register", zh_reg)):
            if t in tbl and tbl[t] in zh:
                out.add((kind, tbl[t]))
                break
        else:
            for zh, kind in ((zh_topic, "topic"), (zh_region, "region"), (zh_reg, "register")):
                if t in zh:
                    out.add((kind, t))
                    break
    return out


def plan(con):
    words = dict(con.execute("SELECT id, word FROM dict"))
    # 🔴🔴 一条出版义项可以带**多条**法语定义。第一版写成 `pub[sid] = t`
    #    ⇒ **后来的覆盖先来的**，回指到了 seq=1 那条，于是把 seq=0 的
    #    `astronomy` 当成"串过来的"要删掉（`solstice d'été` 就是这么被误判的）。
    #    ⇒ `pub[sid]` 必须是**一个集合**，命中也不是一条而是一批。
    pub = defaultdict(set)
    for sid, t in con.execute(
            "SELECT g.sense_id, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
            "WHERE g.lang='fr' AND g.kind='definition' AND s.hidden=0"):
        pub[sid].add(t.strip())
    ev = defaultdict(list)
    for sid, src, txt, raw, wid in con.execute(
            "SELECT sense_id, src, text, raw_tags, word_id FROM sense_src "
            "WHERE sense_id IS NOT NULL"):
        ev[sid].append((src, txt, raw, wid))
    have = defaultdict(set)
    for sid, k, v in con.execute("SELECT sense_id, kind, value FROM sense_tag"):
        have[sid].add((k, v))

    drop, st = [], Counter()
    for sid, ptexts in pub.items():
        rows = ev.get(sid) or []
        frs = [r for r in rows if r[0] == "fr-edition"]
        if len(frs) < 2:
            continue                                  # 只有一条 fr 证据 ⇒ 无从压平
        w = words.get(frs[0][3], "")
        m = [r for r in frs if clean(r[1], w).strip() in ptexts]
        if not m:
            st["📋 一条都回指不上 ⇒ **不动**"] += 1
            continue
        if len(m) < len(ptexts):
            st["📋 有出版定义回指不上 ⇒ **不动**"] += 1
            continue                                  # 宁可不动，也不拿半张地图删东西
        keep = set()
        for r in m:
            keep |= bucket_all(r[2])                  # 命中的**每一条**都算 keep
        for r in rows:
            if r[0] != "fr-edition":
                keep |= bucket_all(r[2])              # ② 跨版互补一律保留
        stray = set()
        for r in frs:
            if r not in m:
                stray |= bucket_all(r[2])             # ③ 确实来自没命中的 fr 证据
        bad = (stray - keep) & have[sid]              # ① 且不来自任何命中的那些
        if bad:
            drop.append((sid, w, sorted(bad)))
            st["🔴 有串过来的标签"] += 1
            for k, _v in bad:
                st["   删 · " + k] += 1
    return drop, st


def gates(con, drop):
    print("\n═══ 闸 ═══")
    ok = True

    def g(name, got, want):
        nonlocal ok
        ok &= got == want
        print("   %s %-52s %s（期望 %s）" % ("✅" if got == want else "🔴", name, f(got), f(want)))

    have = defaultdict(set)
    for sid, k, v in con.execute("SELECT sense_id, kind, value FROM sense_tag"):
        have[sid].add((k, v))
    g("① 要删的行必须真的存在（不凭空 DELETE）",
      sum(1 for sid, _w, bad in drop for kv in bad if kv not in have[sid]), 0)
    g("② 不许把一条义项的标签删空",
      sum(1 for sid, _w, bad in drop if not (have[sid] - set(bad))), 0)
    vis = {s for (s,) in con.execute("SELECT id FROM sense WHERE hidden=0")}
    g("③ 只动可见义项", sum(1 for sid, _w, _b in drop if sid not in vis), 0)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--read", type=int, default=12)
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    drop, st = plan(con)
    n = sum(len(b) for _s, _w, b in drop)
    print("■ 标签被压平的可见义项 %s 条，要删 %s 行" % (f(len(drop)), f(n)))
    for k, v in st.most_common(10):
        print("   %-34s %s" % (k, f(v)))
    print("\n── 抽读（判据不是真值，落库前我要自己看）──")
    for sid, w, bad in random.Random(11).sample(drop, min(a.read, len(drop))):
        zh = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' "
                         "ORDER BY seq LIMIT 1", (sid,)).fetchone()
        print("   【%s】%s\n        删：%s" % (w, (zh[0] if zh else "")[:26],
                                            "、".join("%s/%s" % kv for kv in bad)))
    ok = gates(con, drop)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1
    with dbtool.session("keep-v3-unflatten-tags", expect={"#sense_tag": -n}) as s:
        s.executemany("DELETE FROM sense_tag WHERE sense_id=? AND kind=? AND value=?",
                      [(sid, k, v) for sid, _w, bad in drop for k, v in bad])
    print("✓ 删掉 %s 行串过来的标签（涉及 %s 条义项）" % (f(n), f(len(drop))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
