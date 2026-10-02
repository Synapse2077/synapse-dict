#!/usr/bin/env python3
"""vi 阶段 6c：**量词层**（`noun_classifier`）—— vi 的特色层。2026-10-01。

裁决见 `vi/probes/probe_stage6.py` §D（可重跑）。

═══ 这一层为什么是**关系表**而不是 `dict` 上的一列（`VI_PLAN` V5）═══
`classifier` 在源头躺在 `forms` 里，**但它根本不是词形** —— 把它当 form 收，
就会出现「`bàn` 的一个变形是 `cái`」这种假数据（照搬别门的 `build_inflection_layer`
正是这个后果）。而且它**不是单值**：实测 2,875 个名词里 **34.6% 配 2 个以上量词**
（`cái bàn` 一张桌 ／ `chiếc bàn` 一张桌，语用不同），像西语阴阳性那样放一列装不下。

⭐ **阶段 0 定这条时写的是 34.6%，阶段 6 重量仍然是 34.6%** —— 两次独立度量一致。

═══ ⚠️ 源只有 en 版一份，而那是**源头事实**不是我们漏抽 ═══
十二份切片里只有 en 版有 `forms[tags=classifier]`（4,336 条），其余十一版 **0 条**。
`[[dont-say-source-lacks-what-we-skipped]]`：这一句是**查过的**，
见探针 §A 的字段普查表（量词那一列）。

═══ ⚠️ 「量词只修饰名词」这句话**不要写成判据** ═══
实测带量词标注的 2,875 个词形里，词性集合里没有 noun/name/pron 的只有 **1 个** ——
但那 1 个不是缺陷，越南语的量词也能修饰动名化成分。
⇒ 收的时候**不按词性过滤**，只按源头有没有标。
🔴 什么会推翻：若这个数涨到两位数以上，回去读那批，可能是源头的 tag 被误用了。

用法：
    python3 vi/pipeline/build_classifier_layer.py [--apply]
"""
import argparse
import collections
import gzip
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import dbtool                                                     # noqa: E402
import paths                                                      # noqa: E402
from criteria import norm_vi                                       # noqa: E402

F = lambda n: format(n, ",")                                      # noqa: E731
SRC = "en-edition"


def rd(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def index(con):
    """→ (wid, 精确词形→id, 归一词形→id, 词形→词性集合, 词形总数)。

    🔴 **抽出来是为了外锚闸能 import 同一个函数**（纯搬移，逻辑一行没动）。
    """
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    norm_exact, norm_any = {}, {}
    for i, w, wn in con.execute("SELECT id, word, word_norm FROM dict ORDER BY id"):
        norm_exact.setdefault(w, i)
        norm_any.setdefault(wn, i)
    pos_of = collections.defaultdict(set)
    for w, p in con.execute("SELECT d.word, e.pos FROM entry e JOIN dict d ON d.id=e.word_id"):
        pos_of[w].add(p)
    return wid, norm_exact, norm_any, pos_of, len(wid)


def collect(wid, norm_exact, norm_any, pos_of):
    """收割 ⇒ (最终行, 统计, 词形→量词集合, 不是名词性的词形)。去重在里面。

    🔴 **抽出来是为了外锚闸能 import 同一个函数** —— 闸自己重写判据就是在报
       它自己的 bug（ko 那道外锚闸的原形）。
    ⭐ 本层只有 en 版一个源（`forms[].tags` 含 `classifier`），恒等式最干净。
    """
    rows, stat, per = [], collections.Counter(), collections.defaultdict(set)
    notnoun = []
    for e in rd(paths.KK):
        w = (e.get("word") or "").strip()
        got = [f for f in (e.get("forms") or [])
               if "classifier" in (f.get("tags") or []) and (f.get("form") or "").strip()]
        if not got:
            continue
        if w not in wid:
            stat["源词不在 dict（汉字词头等，有意不收）"] += len(got)
            continue
        if not ({"noun", "name", "pron"} & pos_of.get(w, set())):
            notnoun.append(w)
        for f in got:
            c = f.get("form").strip()
            # 量词自己的词条；收不到留 NULL（**不猜**）
            cid = norm_exact.get(c) or norm_any.get(norm_vi(c))
            stat["✅ 量词自己有词条" if cid else "⚠️ 量词没有词条 ⇒ classifier_id NULL"] += 1
            # 源头在 tags 里除 classifier 之外还说了什么（语用差别），存进 note
            extra = [t for t in (f.get("tags") or []) if t != "classifier"]
            note = "、".join(extra) or None
            per[w].add(c)
            # 🔴🔴 **`src_ref` 不许比表自己的 `UNIQUE` 更细。**
            #    第一版写的是 `cls:en:<词>:<量词>:<第几个>`，比
            #    `UNIQUE(word_id, classifier, src)` 多一节 ⇒ 我按 src_ref 去重掉 40 行，
            #    而按表的唯一键该去 51 行 —— **剩下的 11 行会在 INSERT 时撞 UNIQUE**。
            #    回源读过那 50 组（`bom` 的 `quả`、`gai` 的 `cây`…）：都是同一个词
            #    在 en 版有两条 entry（两个词源号）而两条都标了同一个量词，
            #    **是同一个事实说两遍**，collapse 是对的 —— 那正是 schema 当初
            #    把 `i` 排除在唯一键外的意思。`[[primary-key-is-not-enough]]` 的反面：
            #    主键比唯一键细，会让「我的去重」和「表的去重」答案不一样。
            rows.append((wid[w], c, cid, note, SRC, "cls:en:%s:%s" % (w, c)))

    seen, out = set(), []
    for r in rows:
        if r[5] in seen:
            stat["同源重复（去重）"] += 1
            continue
        seen.add(r[5])
        out.append(r)
    rows = out
    return rows, stat, per, notnoun


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid, norm_exact, norm_any, pos_of, tot = index(con)
    con.close()

    rows, stat, per, notnoun = collect(wid, norm_exact, norm_any, pos_of)

    d = collections.Counter(len(v) for v in per.values())
    multi = 100.0 * sum(v for k, v in d.items() if k >= 2) / max(len(per), 1)
    print("■ 量词 %s 行 / %s 个名词；配 ≥2 个量词 **%.1f%%**"
          "（阶段 0 定这条时量的是 34.6%% —— 两次独立度量要一致）"
          % (F(len(rows)), F(len(per)), multi))
    print("   分布 %s" % dict(sorted(d.items())))
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print("   %-44s %8s" % (k, F(v)))
    print("   ⚠️ 词性里没有 noun/name/pron 的 %d 个（%s）—— **不按词性过滤**，"
          "量词也修饰动名化成分" % (len(notnoun), "、".join(notnoun[:5]) or "无"))
    print("   最常见的量词：%s"
          % "、".join("%s(%s)" % (c, F(n)) for c, n in
                      collections.Counter(r[1] for r in rows).most_common(8)))
    print("■ 读者口径：有量词的词形 **%s（%.2f%%）**" % (F(len(per)), 100.0 * len(per) / tot))

    dbtool.sample_check([(r[1], r[3] or "—", "有链" if r[2] else "无链") for r in rows],
                        8, ("量词", "语用注", "链"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session(
            "build-vi-classifier-layer",
            expect={"__rows__": 0, "#noun_classifier": len(rows),
                    "noun_classifier.classifier": len(rows)},
            invalidates=["量词层落第一行 ⇒ `noun_classifier` 从 UNCLAIMED 里拿出来，"
                         "关系层闸必须登记并跑绿（`vi/tests/test_relation_layer.py`）"]) as s:
        s.executemany(
            "INSERT INTO noun_classifier (word_id, classifier, classifier_id, note, "
            "src, src_ref) VALUES (?,?,?,?,?,?)", rows)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]                      # noqa: E731
    checks = [
        ("noun_classifier 行数", q("SELECT COUNT(*) FROM noun_classifier"), len(rows)),
        ("每条都挂得上 dict",
         q("SELECT COUNT(*) FROM noun_classifier c LEFT JOIN dict d ON d.id=c.word_id "
           "WHERE d.id IS NULL"), 0),
        ("classifier_id 要么空要么真指向一条 dict",
         q("SELECT COUNT(*) FROM noun_classifier c LEFT JOIN dict d ON d.id=c.classifier_id "
           "WHERE c.classifier_id IS NOT NULL AND d.id IS NULL"), 0),
        # 🔴 反向断言：量词**不许**等于被修饰的那个名词自己
        ("量词不是该名词自己",
         q("SELECT COUNT(*) FROM noun_classifier c JOIN dict d ON d.id=c.word_id "
           "WHERE d.word = c.classifier"), 0),
    ]
    for name, got, want in checks:
        print("   %s %-38s %s（期望 %s）"
              % ("✅" if got == want else "🔴", name, F(got), F(want)))
    con.close()
    if any(g != w for _n, g, w in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
