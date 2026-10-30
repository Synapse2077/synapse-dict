#!/usr/bin/env python3
"""K36②：收韩文版的词源正文进 `etymology`。2026-10-28。**免费，不调模型。**

═══ 盘子（2026-10-28 干跑实测，见 `--apply` 前的打印）═══
韩文版 46,120 个条目有 `etymology_texts`（**复数**）。判据 `criteria.ko_etymology`（唯一的家，闸也 import 它）：
    不收 · 汉字写法已在页面上   「한자 X.」而这一页早印着 X（`entry.hanja`／`hanja_spelling`／`alt_hanja`）
    不收 · 只有例句或标记       多词源条目里源头把**义项例句**塞进了词源字段（`:* …`），剔掉后什么都不剩
    不收 · 模板占位             `(어원 서술)`
    收   · 构词                 `아침 + 잠`、`발안(한자 發案) + 하다`
    收   · 来源                 `< 영어 helmet`、`< 중세 한국어 ᄌᆞᆫ자리 (…1481)`
    收   · 汉字写法（页面上没有） `재야` 页面上一个汉字都没有，源头写着「한자 在野」
    收   · 正文                 `한자어 ‘寸劇’에서 유래.`、`'가는 토요일'의 준말 …`

═══ 落点与挂法 ═══
照 K36①（中文版）：一份来源一行，`edition='ko-edition'`；同源 entry 认得到就挂 `entry_id`
（键用 `intake_editions.iter_entries()`，建 entry 时的同一套推导），认不到挂在词上、
展示层页尾「其余词源」区兜住（K36① 已建）。

═══ 改源头的只有一处，而且是删整行 ═══
例句行／标记行／占位行整行剔掉；留下的行**一个字节不改**。

跑（在仓库根）：
    python3 -u ko/pipeline/harvest_ko_etymology.py            # 干跑 ＋ 每类抽 8 条人眼看
    python3 -u ko/pipeline/harvest_ko_etymology.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import random
import sqlite3

import dbtool
import paths
from criteria import ko_etymology
from intake_editions import iter_entries

f = lambda n: format(n, ",")
EDITION = "ko-edition"


def known_hanja(con):
    """→ {词形: 读者这一页上已印着的汉字表记}。"""
    known = collections.defaultdict(set)
    for w, h in con.execute("SELECT d.word, e.hanja FROM entry e JOIN dict d ON d.id=e.word_id "
                            "WHERE e.hanja IS NOT NULL AND e.hanja<>''"):
        known[w].add(h)
    for w, t in con.execute("SELECT d.word, r.target FROM sense_relation r JOIN dict d ON d.id=r.word_id "
                            "WHERE r.kind IN ('hanja_spelling','alt_hanja') AND r.hidden=0"):
        known[w].add(t)
    return known


def harvest(con):
    """→ (rows, stat, samples)。rows = (word_id, entry_id|None, edition, etym_no, text, src, src_ref)"""
    eref = {r[0]: r[1] for r in con.execute("SELECT src_ref, id FROM entry")}
    wid = {r[0]: r[1] for r in con.execute("SELECT word, id FROM dict")}
    known = known_hanja(con)
    rows, stat, samples = [], collections.Counter(), collections.defaultdict(list)
    for src, _glang, w, praw, etym, seq, d in iter_entries():
        if src != EDITION:
            continue
        text, kind = ko_etymology(d.get("etymology_texts"), known.get(w, ()))
        if kind == "无":
            continue
        stat["有词源字段"] += 1
        if text is None:
            stat[kind] += 1
            samples[kind].append((w, "\n".join(d.get("etymology_texts") or [])))
            continue
        if w not in wid:
            stat["不收·词不在 dict"] += 1
            continue
        ref = "%s:%s:%s:%s:%d" % (src, w, praw, etym, seq)
        eid = eref.get(ref)
        stat["收·" + kind] += 1
        stat["  其中挂 entry" if eid else "  其中挂在词上"] += 1
        samples["收·" + kind].append((w, text))
        rows.append((wid[w], eid, EDITION, etym, text, paths.EDITION.name, ref))
    return rows, stat, samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = con.execute("SELECT COUNT(*) FROM etymology WHERE edition=?", (EDITION,)).fetchone()[0]
    if have:
        raise SystemExit("🔴 已有 %s 行韩文版词源 —— 本脚本只做首次收录" % f(have))
    before = dict(con.execute("SELECT edition, COUNT(*) FROM etymology GROUP BY 1").fetchall())
    rows, stat, samples = harvest(con)
    con.close()
    print("■ K36② 韩文版词源")
    for k, v in sorted(stat.items()):
        print("   %-34s %7s" % (k, f(v)))
    print("   %-34s %7s" % ("── 要写的", f(len(rows))))
    if not a.apply:
        random.seed(11)
        for k in sorted(samples):
            print("\n   ── %s" % k)
            for w, t in random.sample(samples[k], min(8, len(samples[k]))):
                print("      %-12s %s" % (w, t.replace("\n", " ⏎ ")[:120]))
        print("\n（干跑。加 --apply 才写库）")
        return

    with dbtool.session(
            "ko-k36-harvest-ko-etymology",
            expect={"#etymology": len(rows)},
            invalidates=[
                "`etymologyEditions` 多出 ko-edition ⇒ 韩文版多词源组没有词源时开始如实印「源头未给出」",
                "展示层：`entry_id` 为空的 %s 条只在页尾「其余词源」区印" % f(sum(1 for r in rows if r[1] is None)),
            ]) as s:
        s.executemany(
            "INSERT INTO etymology (word_id, entry_id, edition, etym_no, text, src, src_ref)"
            " VALUES (?,?,?,?,?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    want_e = sum(1 for r in rows if r[1] is not None)
    checks = [
        ("韩文版词源行数", q("SELECT COUNT(*) FROM etymology WHERE edition='ko-edition'"), len(rows)),
        ("其中挂 entry", q("SELECT COUNT(*) FROM etymology WHERE edition='ko-edition' AND entry_id IS NOT NULL"), want_e),
        ("🔴 挂的 entry 来源与 edition 不一致",
         q("SELECT COUNT(*) FROM etymology t JOIN entry e ON e.id=t.entry_id WHERE t.edition<>e.src"), 0),
        ("🔴 挂的 entry 词源号不一致",
         q("SELECT COUNT(*) FROM etymology t JOIN entry e ON e.id=t.entry_id WHERE t.etym_no<>e.etym_no"), 0),
        ("🔴 挂的 entry 不属于这个词",
         q("SELECT COUNT(*) FROM etymology t JOIN entry e ON e.id=t.entry_id WHERE t.word_id<>e.word_id"), 0),
        ("🔴 正文里有例句行", q("SELECT COUNT(*) FROM etymology WHERE edition='ko-edition' "
                            "AND (text LIKE ':*%' OR text LIKE '%' || char(10) || ':*%')"), 0),
    ] + [("🔴 %s 行数变了" % ed, q("SELECT COUNT(*) FROM etymology WHERE edition='%s'" % ed), n)
         for ed, n in sorted(before.items())]
    red = 0
    print("\n■ 写后回核（从库里重算）")
    for name, got, want in checks:
        red += got != want
        print("   %s %-30s %8s  期望 %8s" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    con.close()
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


if __name__ == "__main__":
    main()
