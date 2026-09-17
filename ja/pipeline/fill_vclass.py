#!/usr/bin/env python3
"""欠账 4 —— 活用类落到 `entry.vclass`。零模型调用。2026-09-16。

═══ 这笔账从阶段 2 挂到现在 ═══
阶段 2 建变形层时发现：日语版给**每一个形**都打了 `godan`/`ichidan`/`sa-row`/`irregular`，
而那是**这个词的属性**，不是这个形的属性 —— 照译会让每一行变形都拖着「サ行変格」。
当时的处置是归进 `infl_compose.CLASS_TAGS` **不出字**，账上写着：

    它该落 `entry` 的一列（像 de 的 `vclass`），**本轮没落，见欠账 4**。

⇒ 结果这个信息**只在 dump 里**，库里一个字都没有。

═══ 活用类 ＝ 标签组合，不是单个标签 ═══
    irregular + sa-row   15,681   サ行変格（`保護`する／`杞憂`する）
    godan     + ra-row      900   五段・ラ行
    godan                   737   五段（源头没说行）
    ichidan                 664   一段
    irregular + ka-row        2   カ行変格（`来る`／`やってくる`）
    nidan / yodan             3   文语二段・四段

🔴 **`irregular` 单独没有意义** —— 它总是和某个行一起出现，
   `irregular+sa-row` 是サ変、`irregular+ka-row` 是カ変，两者是不同的活用类。
   只存 `irregular` 等于把两种不同的东西合成一个。

⚠️ **拼不出唯一类的不猜**：4 个词条同时带 `godan+nidan`／`godan+ichidan`
   （源头自己在列两种可能的活用），⇒ `vclass` 留空并记账，不挑一个写进去。

═══ 🔴🔴 **有意不做「按读音传播到汉字写法」** ═══
日语版把词条挂在**假名词头**下（`あるく`），而读者搜的是 `歩く` ——
所以 `歩く`／`書く`／`読む` 这些最常用的写法**拿不到活用类**。
我试过按读音传播，并加了「这个读音唯一对应一个活用类」当保险。**那个保险是假的**：

    犬 [いぬ] 名词  → godan-na    ← 犬是「狗」，いぬ 碰巧也是动词 `去ぬ`
    国 [こく] 名词  → godan-ka
    数 [すう] 名词  → godan-wa    ← すう 是 `吸う`

唯一性只检查了**日语版动词条目内部**的歧义，看不见「犬 和 去ぬ 是两个完全不同的词」。
⇒ 判据比它要描述的东西宽得多，**放弃**。没有结构信号能把假名词条和汉字词条连起来。
🔴 **推翻它需要**：日语版给出汉字写法字段，或出现别的能连接两种写法的结构信号。

═══ pos=noun 的 1,299 条是「名詞＋する」═══
`保護` 本身是名词，`保護する` 才活用。**照收** —— 读者查 `保護` 时要知道它能サ変。
判据按源头给的标签走，不按词性筛。

用法（在仓库根）：
    python3 -u ja/pipeline/fill_vclass.py
    python3 -u ja/pipeline/fill_vclass.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import sqlite3

import dbtool
import paths
from pipeline.build import norm_ja

f = lambda n: format(n, ",")
ROWS = ("ka-row", "sa-row", "ta-row", "na-row", "ha-row", "ma-row",
        "ya-row", "ra-row", "wa-row", "ba-row", "ga-row", "a-row")
STEMS = ("godan", "ichidan", "nidan", "yodan", "irregular",
         "shimo-ichidan", "kami-ichidan", "shimo-nidan", "kami-nidan")


def vclass_of(tags):
    """标签集合 → 规范化的活用类代码，或 None（拼不出唯一类）。

    🔴 返回 None 就是**不猜**。源头同时给 `godan` 和 `nidan` 时，
       它自己在列两种可能，挑一个写进库等于替源头做裁决。
    """
    stems = [t for t in STEMS if t in tags]
    rows = [t for t in ROWS if t in tags]
    if len(stems) != 1 or len(rows) > 1:
        return None
    stem, row = stems[0], (rows[0] if rows else None)
    if stem == "irregular":
        # `irregular` 单独没有意义，必须跟着行
        return ("%s-irregular" % row.split("-")[0]) if row else None
    return "%s-%s" % (stem, row.split("-")[0]) if row else stem


def scan():
    out, st = {}, collections.Counter()
    for line in open(paths.EDITION, encoding="utf-8"):
        o = json.loads(line)
        tags = set()
        for fm in (o.get("forms") or []):
            tags.update(fm.get("tags") or [])
        tags &= set(ROWS) | set(STEMS)
        if not tags:
            continue
        st["有活用类标签的词条"] += 1
        vc = vclass_of(tags)
        if vc is None:
            st["⚠️ 拼不出唯一类（源头自己在列两种）"] += 1
            continue
        w = norm_ja(o["word"])
        if w in out and out[w] != vc:
            st["⚠️ 同词形两种活用类（取先到的，记账）"] += 1
            continue
        out.setdefault(w, vc)
        st["⭐ " + vc] += 1
    return out, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    vc, st = scan()
    for k in sorted(st):
        print("   %-40s %s" % (k, f(st[k])))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, blocked = [], collections.Counter()
    for eid, w, pos in con.execute(
            "SELECT e.id, d.word, e.pos FROM entry e JOIN dict d ON d.id=e.word_id"):
        k = norm_ja(w)
        if k not in vc:
            continue
        cls = vc[k]
        # 🔴🔴 **按词形匹配会把类写到该词形的每一条 entry 上，包括不活用的那些。**
        #    实测污染 170 条：`そう`（副词/感叹词/接尾）拿到了动词 `添う` 的 `godan-wa`、
        #    `メス`（名词）拿到了 `召す` 的 `godan-sa`、`ある`（连体词）拿到了 `godan-ra`。
        #    ⇒ 判据要问**这个词性会不会活用**：
        #      · 动词 —— 什么类都收
        #      · 名词/专名/形容动词 —— **只收 `sa-irregular`**（名詞＋する，`保護`する）
        #      · 连体词/副词/感叹词/接尾辞/短语 —— 一律不收，它们不活用
        if pos == "v":
            pass
        elif cls == "sa-irregular" and pos in ("n", "name", "adj", "adj_noun", "adv"):
            # ⚠️ `adv` 放开是量出来的：挡它会丢 285 条，而**副詞＋する 是能产的**
            #    （`はっきりする`／`ゆっくりする`，擬態語＋する）。
            #    `phr`/`intj`/`kanji` 仍然挡着 —— 那几类 `する` 接不上去。
            pass
        else:
            blocked["%s ← %s" % (pos, cls)] += 1
            continue
        rows.append((cls, eid))
    con.close()
    if blocked:
        print("\n   ⚪ 按词性挡下（不活用的词性）%s 行：" % f(sum(blocked.values())))
        for k, n in blocked.most_common(6):
            print("      %4d  %s" % (n, k))
    print("\n■ 词形 %s 个有活用类 ⇒ 命中 entry %s 行" % (f(len(vc)), f(len(rows))))
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        return

    with dbtool.session("ja-fill-vclass", expect={
            "__rows__": 0, "#entry": 0, "#sense": 0, "#example": 0,
            "#inflection": 0, "#sense_relation": 0}) as con:
        try:
            con.execute("ALTER TABLE entry ADD COLUMN vclass TEXT")
        except sqlite3.OperationalError:
            pass
        con.execute("UPDATE entry SET vclass=NULL")   # 可重跑：先清再灌
        con.executemany("UPDATE entry SET vclass=? WHERE id=?", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("vclass 落了行", q("SELECT COUNT(*) FROM entry WHERE vclass IS NOT NULL") > 15000),
        # 🔴 `irregular` 不许单独出现 —— 它必须带着行（サ変/カ変是两个类）
        ("没有光秃秃的 irregular", q(
            "SELECT COUNT(*) FROM entry WHERE vclass='irregular'") == 0),
        # 🔴 直接断言那条判据：不活用的词性一条 vclass 都不许有
        # ⚠️ `adv` **有意不在这张单子里** —— 副詞＋する 是能产的（见上面那条判据）。
        #    断言和判据必须同步改：我放开了 adv 却忘了改这条，闸当场报红。**闸是对的。**
        ("不活用的词性（连体词/感叹词/接尾/助词）没有 vclass", q(
            "SELECT COUNT(*) FROM entry WHERE vclass IS NOT NULL"
            " AND pos IN ('adnom','intj','suf','pref','phr','part','conj','kanji')") == 0),
        ("非动词只允许 sa-irregular（名詞＋する）", q(
            "SELECT COUNT(*) FROM entry WHERE vclass IS NOT NULL"
            " AND pos<>'v' AND vclass<>'sa-irregular'") == 0),
        ("副詞＋する 收进来了（>200，擬態語那一族）", q(
            "SELECT COUNT(*) FROM entry WHERE pos='adv' AND vclass='sa-irregular'") > 200),
        ("每个 vclass 取值都在白名单里", sum(
            1 for (v,) in con.execute(
                "SELECT DISTINCT vclass FROM entry WHERE vclass IS NOT NULL")
            if not (v in STEMS or "-" in v)) == 0),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    for v, n in con.execute(
            "SELECT vclass, COUNT(*) FROM entry WHERE vclass IS NOT NULL"
            " GROUP BY 1 ORDER BY 2 DESC LIMIT 12"):
        print("   %-18s %s" % (v, f(n)))
    con.close()
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
