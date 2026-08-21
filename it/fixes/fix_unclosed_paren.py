#!/usr/bin/env python3
"""关系目标里的括号残渣：切碎的说明片段 + 被截断的学名。2026-08-21。

═══ 怎么发现的 ═══
把 12 个词的**渲染成品**送豆包 pro 与 v4-pro 外审，两家**都判 `gatto`「无问题」** ——
而 `gatto` 的下位词区就躺着 6 条 `gatto della giungla ( Felis chaus` 这样的断括号。
⇒ 记一笔：形式特征明确的残渣是**确定性判据**的活儿，模型看不见；
   模型强在语言学判断（同一轮它逮到了 `treno` 首义漏掉「火车」、`fare` 的
   「赠送」与意语原文 `ricevere`「收到」方向相反）。两者互补，不能互相替代。

═══ 根因不是「括号没闭合」，是切分 ═══
意语版的同义词/下位词列表里带括号说明，收录时按逗号切分，把括号里的内容切碎了：

    (perlopiù malavitoso, criminale)    →  '(perlopiù malavitoso'  +  'criminale)'
    kiwi australe (Apteryx australis)   →  'kiwi australe ('       +  'Apteryx australis)'

全库 808 条残片（573 条缺右括号 + 235 条缺左括号）。
🔴 **根因在收录脚本的切分逻辑**，本脚本只止血；根因已记账（不重跑整层收录）。

═══ 判据：形状，不是查词表 ═══
🔴 第一版判据是「剥掉括号后如果是库里的真词形就保留」——**两头都错**：
   · 误留 `(da` `(talvolta` `(classe` —— 剥出来确实是真词，但在这里是说明片段的头
     （`(da qualcosa)` 被切成 `(da` + `qualcosa)`）
   · 误删 `kiwi australe` `gatto selvatico africano` `tordo bottaccio` —— 是真的
     意语动植物名，只因库里没有这些**多词**条目就被判死
⇒ 改用**位置形状**：括号在哪一头决定这条是什么，与词表无关。

    尾部孤立左括号   `kiwi australe (`            → 剥掉 ` (`，保留（191 条，全是动植物名）
    首部左括号       `(inglesismo che significa`  → 说明片段的头，藏（381 条）
    尾部孤立右括号   `criminale)`                 → 说明片段的尾，藏（209 条）
    形状更杂的                                     → **27 条，名单写死**（见 BY_HAND）

═══ 为什么是藏不是删 ═══
`sense_relation` 加 `hidden` 列，与 `sense`/`example` 一致。删行不可逆，而且
收录脚本重放时 `INSERT OR IGNORE` 会把删掉的行原样填回来（`replay-scripts-undo-fixes`）——
标记则不会被重放覆盖。
🔴 **加列必须同步改读取路径**，否则等于没做：`italian.ts` 的 `relationQuery`/`altQuery`
   要加 `COALESCE(hidden,0)=0`。

用法（在 it/ 目录下）：
    python3 fixes/fix_unclosed_paren.py            # 干跑
    python3 fixes/fix_unclosed_paren.py --apply
    python3 fixes/fix_unclosed_paren.py --verify
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")


def classify(target):
    """→ 'strip' / 'hide' / 'other' / ''（不是残渣）。

    🔴 这个函数是**判据本身**，回归闸 D1 直接 import 它，不另写一套。
    """
    s = (target or "").strip()
    has_l, has_r = "(" in s, ")" in s
    if has_l == has_r:
        return ""                                   # 括号成对或都没有 ⇒ 不是残渣
    if has_l and s.endswith("(") and s.count("(") == 1:
        return "strip"                              # `kiwi australe (`
    if has_l and s.startswith("(") and s.count("(") == 1:
        return "hide"                               # `(inglesismo che significa`
    if has_r and s.endswith(")") and s.count(")") == 1:
        return "hide"                               # `criminale)`
    return "other"                                  # 形状杂 ⇒ 交给 BY_HAND


def stripped(target):
    """`strip` 那批清理后的值：剥掉尾部的 ` (`。"""
    return target.strip()[:-1].strip()


# ── 27 条形状杂的，**逐条读过**后写死。值 = 改成什么；None = 藏 ──────────────
# 判断依据是**归属词**：`renna`（驯鹿）的上位词 `essere vivente`（生物）成立；
# `bambina` 的 `(civiltà) in embrione`（萌芽中的文明）与「女孩」无关。
BY_HAND = {
    59816:  "essere vivente",            # renna（驯鹿）的上位词，成立
    61878:  "terracotta non smaltata",   # biscotto 有「素烧陶」义
    62246:  None,                        # bambina ← `(civiltà) in embrione`，无关
    69302:  None,                        # lumaca ← 整条是一句说明
    80402:  None,                        # religione ← `):`
    86467:  "dose eccessiva",            # overdose 的同义
    91484:  "metà del globo",            # emisfero（半球）
    100236: "situazione logica",         # paradosso 的反义
    177745: "movimento involontario",    # riflesso（反射）
    198940: "diritto acquisito",         # titolo（权利证书）
    211810: "classe colturale",
    241985: "pagamento dell’ammenda",    # oblazione（罚金）
    249933: None,                        # cittadini ← `(guerre) intestine` 是形容词
    304474: None,                        # assedi ← `togli l’assedio` 是祈使句不是词条
    360207: "stare insieme",             # coesistere（共存）
    387682: "vendicandosi",              # dimenticando 的反义
    405130: "fatti con sforzo",          # forzati
    436800: None,                        # scandagliata ← 残句
    460481: "fasci vascolari",           # nervatura（叶脉）
    481434: "passera di mare",           # passera（鲽鱼）
    537859: "bolognese",                 # rossoblù ← 红蓝队色，博洛尼亚队
    561340: None,                        # porzana ← `) e`
    596993: None,                        # Asparagacee ← `) e`
    # ⚠️ Brassicacee（十字花科）→ stella alpina（高山火绒草）：火绒草是**菊科**，
    #    这条归属本身就错，`stella alpina` 虽是真词也不能挂在这里 ⇒ 藏。
    597218: None,
    598424: None, 598434: None,          # Dipsaco / dipsaco ← `) e lo`
    598540: None,                        # Rubiali ← `) e lo`
}


def scan(con):
    """→ (要剥括号的, 要藏的)，两个都是 [(id, word, kind, old, new)]。"""
    strip_rows, hide_rows = [], []
    for rid, w, k, t in con.execute(
            "SELECT r.id, d.word, r.kind, r.target FROM sense_relation r "
            "JOIN dict d ON d.id=r.word_id"):
        c = classify(t)
        if not c:
            continue
        if c == "other":
            if rid not in BY_HAND:
                # 名单没覆盖 ⇒ 说明数据变了，宁可报错也不要默默处理
                raise SystemExit("🔴 BY_HAND 没覆盖 id=%d %r —— 数据变了，先逐条读" % (rid, t))
            new = BY_HAND[rid]
            (strip_rows if new else hide_rows).append((rid, w, k, t, new))
        elif c == "strip":
            strip_rows.append((rid, w, k, t, stripped(t)))
        else:
            hide_rows.append((rid, w, k, t, None))
    return strip_rows, hide_rows


def gate(con):
    """--verify：修完之后，读取路径上不该再有任何括号残渣。"""
    cols = {r[1] for r in con.execute("PRAGMA table_info(sense_relation)")}
    if "hidden" not in cols:
        print("🔴 sense_relation 还没有 hidden 列")
        return False
    left = sum(1 for (t,) in con.execute(
        "SELECT target FROM sense_relation WHERE COALESCE(hidden,0)=0") if classify(t))
    print("■ 读取路径上剩余括号残渣：%s 条" % f(left))
    return left == 0


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        ok = gate(ro)
        ro.close()
        return 0 if ok else 1
    strip_rows, hide_rows = scan(ro)
    ro.close()
    print("■ 剥括号保留 %s 条 / 藏 %s 条" % (f(len(strip_rows)), f(len(hide_rows))))
    for rid, w, k, t, new in strip_rows[:8]:
        print("     改  %-14s %-9s %r → %r" % (w[:14], k, t, new))
    for rid, w, k, t, _ in hide_rows[:6]:
        print("     藏  %-14s %-9s %r" % (w[:14], k, t))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("fix-unclosed-paren", expect={"__rows__": 0}) as s:
        cols = {r[1] for r in s.execute("PRAGMA table_info(sense_relation)")}
        if "hidden" not in cols:
            s.execute("ALTER TABLE sense_relation ADD COLUMN hidden INTEGER DEFAULT 0")
        for rid, _w, _k, _t, new in strip_rows:
            s.execute("UPDATE sense_relation SET target=? WHERE id=?", (new, rid))
        if hide_rows:
            s.execute("UPDATE sense_relation SET hidden=1 WHERE id IN (%s)"
                      % ",".join(str(r[0]) for r in hide_rows))
        s.written = len(strip_rows) + len(hide_rows)
    print("\n■ 已改 %s 条、藏 %s 条" % (f(len(strip_rows)), f(len(hide_rows))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
