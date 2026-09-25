#!/usr/bin/env python3
"""把 `entry.conj_class` 变成**真的活用类**。2026-09-24（阶段 8 后补，结清 K8 的一半）。

═══ 这一步在改什么 ═══
    改名  `conj_class`  →  `conj_table_tag`   （它存的一直是源头的 `table-tags`，
                                               值域只有 irregular / no-table-tags）
    新建  `conj_class`                        （여불규칙 / ㅂ불규칙 / … 见 `conj_class.CLASSES`）
    新建  `conj_class_src`                    （`forms` 反推 ／ `suffix` 后缀规则）

🔴 **为什么是改名不是加列**：列名承诺了「活用类」而内容是「表的 tag」，
   留着它就是留着一个会继续骗人的名字 —— 计划表和账的闸已经拿它当活用类覆盖率数过一轮了
   （K8 那笔账因此比记的小）。`grep` 全仓确认**展示层一处都没读它**，
   阶段 9 一接上就得动前端 ⇒ **现在改最便宜**。

═══ 两个来源，先后有序 ═══
① `forms`  —— 有活用表的原形，从实际形式反推。**证据在库里**，最可信。
② `suffix` —— 没有活用表的，按构词后缀推（那张表在 4,592 个带表原形上逐条验过）。
🔴 **① 优先**：有实际形式就不猜。两者都有时以 ① 为准，而 `cross_check()`
   保证这种情况下两者一致（不一致的 2 个已回源修掉）。

═══ 不填的那一档，**有意留 NULL** ═══
两条都不适用的留空。`[[dont-gate-facts-on-my-uncertainty]]` 的正面用法：
这一行要写的是**我推出来的**，推不出来就别写。
🔴 填一个猜的值比留空更伤（`[[dict-framework-doc]]` 错比缺更伤权威）——
   落在这一档的恰恰是 `보다`/`맞다`/`타다`/`묻다` 这类**最常用**且拼写定不了的词。

跑（在仓库根）：
    python3 -u ko/pipeline/derive_conj_class.py
    python3 -u ko/pipeline/derive_conj_class.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import sqlite3

import dbtool
import paths
import conj_class as CC

f = lambda n: format(n, ",")
POS = ("verb", "adj", "adjective")


def forms_index(con):
    """{原形: {变形词形}}。"""
    d = collections.defaultdict(set)
    for base, w in con.execute(
            "SELECT i.base, d.word FROM inflection i JOIN dict d ON d.id=i.word_id"):
        d[base].add(w)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info(entry)")}
    renamed = "conj_table_tag" in cols
    byform = forms_index(con)

    # ── 写之前的两道前提，**判据自己的闸** ──
    print("■ 判据自检")
    bad = CC.check_gold(byform)
    print("   %s 对照组 %d/%d" % ("✅" if not bad else "🔴",
                                  len(CC.GOLD) - len(bad), len(CC.GOLD)))
    for w, want, got in bad:
        print("      🔴 %s 期望 %s 实得 %s" % (w, want, got))
    xs = CC.cross_check(byform)
    print("   %s 交叉闸（后缀 vs 形式反推）不一致 %d 个" % ("✅" if not xs else "🔴", len(xs)))
    for b, s, d in xs:
        print("      🔴 %-12s 后缀说 %-8s 形式说 %s" % (b, s, d))
    if bad or xs:
        raise SystemExit("🔴 判据自检没过 —— 先别写库"
                         "（交叉闸红 = 数据坏了，去回源，不是放宽判据）")

    # ── 算 ──
    rows = con.execute(
        "SELECT e.id, d.word, e.pos_raw FROM entry e JOIN dict d ON d.id=e.word_id "
        "WHERE e.pos_raw IN (%s) AND d.word LIKE '%%다'"
        % ",".join("?" * len(POS)), POS).fetchall()
    out, stat, src_stat = {}, collections.Counter(), collections.Counter()
    for eid, w, _p in rows:
        fs = byform.get(w)
        c = CC.derive_from_forms(w, fs) if fs else None
        s = "forms"
        if c is None:
            c, s = CC.by_suffix(w), "suffix"
        if c is None:
            stat["🔴 两条判据都不适用 ⇒ 留 NULL"] += 1
            continue
        out[eid] = (c, s)
        stat[c] += 1
        src_stat[s] += 1

    print("\n■ 用言词条 %s 条（`-다` 结尾）" % f(len(rows)))
    for k, v in stat.most_common():
        print("   %-28s %6s  %5.1f%%" % (k, f(v), 100.0 * v / len(rows)))
    print("   ── 来源 ──")
    for k, v in src_stat.most_common():
        print("   %-28s %6s" % (k, f(v)))
    print("   %-28s %6s  %5.1f%%" % ("⇒ 能定出活用类的", f(len(out)),
                                     100.0 * len(out) / len(rows)))
    before = con.execute(
        "SELECT COUNT(*) FROM entry WHERE conj_class IS NOT NULL").fetchone()[0]
    print("\n   改之前 `conj_class` 非空 %s 条（那是 `table-tags`，不是活用类）" % f(before))
    con.close()

    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-derive-conj-class",
            # 🔴 改名之后 `entry.conj_class` 的非空数会**从 4,697 跳到 %d** ——
            #    不是"多填了"，是**换了一列东西**。expect 必须把三列都写出来，
            #    否则写库闸门只会说"conj_class 变了 +N"，而真实变化是"这一列换了含义"。
            expect={"entry.conj_class": len(out) - before,
                    "entry.conj_table_tag": 0 if renamed else before,
                    "entry.conj_class_src": len(out)},
            invalidates=[
                "🔴 账的闸 P6「用言词条里有活用类的占比」：**它量的东西变了** —— "
                "从「有 table-tags 的行」变成「真能说出是哪一类的行」，下限要重新定",
                "`fill_conj_class.py` 写的是 `conj_table_tag` 了，重跑它之前要先改那个脚本",
                "展示层（阶段 9）：活用类要显示 `conj_class`（韩语术语），"
                "`conj_table_tag` 是证据不上页面",
            ]) as s:
        if not renamed:
            s.execute("ALTER TABLE entry RENAME COLUMN conj_class TO conj_table_tag")
            s.execute("ALTER TABLE entry ADD COLUMN conj_class TEXT")
            s.execute("ALTER TABLE entry ADD COLUMN conj_class_src TEXT")
        s.executemany("UPDATE entry SET conj_class=?, conj_class_src=? WHERE id=?",
                      [(c, src, eid) for eid, (c, src) in out.items()])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    dom = {r[0] for r in con.execute(
        "SELECT DISTINCT conj_class FROM entry WHERE conj_class IS NOT NULL")}
    checks = [
        ("conj_class 非空", q("SELECT COUNT(*) FROM entry WHERE conj_class IS NOT NULL"),
         len(out)),
        ("conj_table_tag 非空（老值原样保住）",
         q("SELECT COUNT(*) FROM entry WHERE conj_table_tag IS NOT NULL"), before),
        # 🔴 值域必须落在声明过的集合里 —— 多出一个值就是判据漏了分支
        ("值域都在 CLASSES 里", len(dom - set(CC.CLASSES)), 0),
        ("每条有类的都说得出来源",
         q("SELECT COUNT(*) FROM entry WHERE conj_class IS NOT NULL "
           "AND conj_class_src IS NULL"), 0),
        # 🔴 反向：非用言不许有活用类
        ("非用言没有活用类",
         q("SELECT COUNT(*) FROM entry WHERE conj_class IS NOT NULL "
           "AND pos_raw NOT IN ('verb','adj','adjective')"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-32s %8s（期望 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))
    print("\n■ 抽样：老列与新列并排")
    for r in con.execute(
            "SELECT d.word, e.conj_table_tag, e.conj_class, e.conj_class_src "
            "FROM entry e JOIN dict d ON d.id=e.word_id "
            "WHERE d.word IN ('걷다','곱다','낫다','푸르다','하다','먹다','임명하다','반짝거리다') "
            "AND e.conj_class IS NOT NULL LIMIT 10"):
        print("   %-10s tag=%-14s 类=%-10s 来源=%s" % r)
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
