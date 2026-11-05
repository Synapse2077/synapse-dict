#!/usr/bin/env python3
"""K27：例句标签那一支的关系边，括号里的内容整段丢了 ⇒ `target` 存回源文原样。ko，2026-11-03。

═══ 缺陷 ═══
`harvest_relations_from_examples` 存 `target` 时用的是 `clean()` 剥过括号的词，而建库那一支（12,631 条）
存的是源文原样（`경마(競馬)`）、展示层原样印、链接走 `target_norm`。于是这一支丢了：
    汉字表记  `성두(星斗)`  `편주(片舟/扁舟)`  `기(箕)키`        地区  `굿재이(강원, 경남, 전남, 충북)`
    语态      `부정되다 (피동)`／`부정하다 (능동)`               ……
账上的方案是「按语义分三堆、各进各的地方」，量完改了：⚠️ **不拆**。
    · 三堆之外还有 210 条混写（`속임수(―數)`、`宀(면)`）—— 拆就得再造第四、第五堆；
    · `tags` 的值域是源头标签（`["Gyeongsang"]`），把 `강원, 경남` 映射过去是我编的对照表；
    · 同一张表里另一个写入方早就是「原文进 `target`」，这一支对齐它 ＝ 不丢信息、不混语义、不新增约定。

═══ 判据（唯一的家：`harvest_relations_from_examples.shown()`）═══
片段**只多了括号组**（去掉括号组 ＝ clean 后的目标），且没有空括号。`() 도시락밥`、散文、`어두움 > 어둠` 不动。
同一条边对应源文里**两种不同的括号**（`선하다(先―)`／`선하다(善―)`，同形异义）⇒ 判不了是哪个，不动。
⭐ 顺带：认括号的切分器让源文 `우격 (> 우격다짐,우격으로)` 第一次切出 `우기다 → 우격`（K19 记下的那 1 条）——
   括号里的 `>` 是「再派生」，随括号一起剥掉；顶层的 `어두움 > 어둠`（旧形>新形）规则不变。

跑（在仓库根）：
    python3 -u ko/fixes/fix_k27_relation_paren_text.py            # 干跑
    python3 -u ko/fixes/fix_k27_relation_paren_text.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import collections
import sqlite3

import dbtool
import paths
import harvest_relations_from_examples as H
import resolve_relation_targets as R      # 链接落点的判据：import，不重写

f = lambda n: format(n, ",")
WRITER = "harvest_relations_from_examples"     # 改的是这一支已落库的行（`relation_writers` 登记过）


def plan(con):
    """→ (upd [(新 target, id)], 同形不动的 [(kind, target, {候选})], 新切分器才切得出的边)。回归闸 R31 import 它。"""
    indict = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    want = collections.defaultdict(set)
    for aid, k, b, _g, _src, _a, raw, t in H.candidates(indict, collections.Counter(), collections.Counter()):
        if b == t:
            want[(aid, k, t)].add(H.shown(raw, t))
    upd, ambiguous = [], []
    # 🔴 按**剥掉括号之后**的目标去对源文，不按库里现在的 `target` —— 后者存回原文之后就再也对不上任何
    #    一条源文，「还要存回的」恒为 0，写后回核与回归闸 R31 都成了恒绿（第一版就是这么写的）
    for i, wid, k, tgt in con.execute(
            "SELECT id, word_id, kind, target FROM sense_relation WHERE writer = ?", (WRITER,)):
        base = H._BRACKETS.sub("", tgt).strip()
        s = want.get((wid, k, base), set()) - {base}
        if len(s) > 1:
            ambiguous.append((k, base, s))
            continue
        desired = s.pop() if s else base
        if tgt != desired:
            upd.append((desired, i))
    # 旧切分器（先切再去括号）切不出、新切分器切得出的 ⇒ 这一轮新收的边。
    # ⚠️ 按**不分方向的词对**比：`derived`／`본말` 会把方向反过来（目标才是起点）
    old = set()
    for _src, word, lab, payload in H.load_rows():
        if lab in H.M and lab not in H.DROP and word in indict:
            old |= {frozenset((word, H.clean(r))) for r in H.SPLIT.split(payload)}
    id2w = {i: w for w, i in indict.items()}
    edges, _stat, _unk = H.build(con)
    gain = [e for e in edges
            if frozenset((id2w[e[0]], H._BRACKETS.sub("", e[3]).strip())) not in old]
    return upd, ambiguous, gain


def norms(con):
    """→ [(target_norm, id)]：可见、还没有落点、而落点判据现在解得出的边。

    `resolve_relation_targets.PAREN` 原来只认半角圆括号 ⇒ `target` 存回原文后，`귀때기 [俗]`／`아니다（不是）`
    这类重跑解析会丢掉现有的链接（4 行），一起改成与收割器同一套括号。放宽后新解出 7 行：新边 `우격` ＋
    6 条原本就是死链的（`아름답다（美好的）`、`운율 [韻律]`）。⚠️ 只补 NULL，不动已有落点（2,446 行是别的步骤有意写的）。
    """
    have = {r[0] for r in con.execute("SELECT word_norm FROM dict")}
    out = []
    for i, t in con.execute("SELECT id, target FROM sense_relation "
                            "WHERE target_norm IS NULL AND COALESCE(hidden,0) = 0"):
        n, _step = R.resolve(t, have)
        if n:
            out.append((n, i))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    upd, amb, gain = plan(con)
    nrm = norms(con)
    total = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    show = {i: t for t, i in upd}
    for i, tgt in con.execute("SELECT id, target FROM sense_relation WHERE id IN (%s) ORDER BY id LIMIT 12"
                              % ",".join(str(i) for i in list(show)[:12])):
        print("   %-12s → %s" % (tgt, show[i]))
    for k, tgt, s in amb:
        print("   同形不动：%s %s ← %s" % (k, tgt, " ／ ".join(sorted(s))))
    print("■ `target` 存回源文：%s 行；同形两种括号判不了、不动：%s 组" % (f(len(upd)), f(len(amb))))
    for e in gain:
        print("   新边 word_id=%d %s → %s" % (e[0], e[2], e[3]))
    print("■ 新切分器才切得出的边：%d 条" % len(gain))
    for n, i in nrm:
        print("   落点 id=%d → %s" % (i, n))
    print("■ 补链接落点：%d 行（新边自己的落点在下一次运行补）" % len(nrm))
    con.close()
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return
    if not (upd or gain or nrm):
        print("■ 没有要写的")
        return
    with dbtool.session("ko-k27-relation-paren-text",
                        expect={"#sense_relation": len(gain),
                                "sense_relation.target": len(gain),
                                "sense_relation.writer": len(gain),
                                "sense_relation.target_norm": len(nrm)},
                        invalidates=[]) as s:
        s.executemany("UPDATE sense_relation SET target=? WHERE id=?", upd)
        s.executemany(
            "INSERT INTO sense_relation (word_id, sense_id, kind, target, tags, src, src_ref, writer)"
            " VALUES (?,?,?,?,?,?,?,'%s')" % WRITER, gain)
        s.executemany("UPDATE sense_relation SET target_norm=? WHERE id=? AND target_norm IS NULL", nrm)

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left, _amb, left_gain = plan(con)
    checks = [("行数", con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0], total + len(gain)),
              ("还要存回原文的", len(left), 0),
              ("还没收的新边", len(left_gain), 0),
              ("还没补的落点（新边除外）", len(norms(con)), len(gain))]
    red = 0
    for name, got, want in checks:
        red += got != want
        print("   %s %-14s %s（期望 %s）" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    if red:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
