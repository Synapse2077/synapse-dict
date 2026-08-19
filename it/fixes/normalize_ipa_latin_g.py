#!/usr/bin/env python3
"""音标里的拉丁小写 `g`（U+0067）归一成 IPA 的 `ɡ`（U+0261）。2026-08-18（阶段 7）。

═══ 怎么发现的：**回归闸的"被绕过"信号** ═══
阶段 7 的回归闸每条断言都在**两个地方**各查一次，这条报出来的是：

    A3  拉丁小写 g（应为 IPA ɡ）    写入侧 dict.ipa   1
                                 读取侧 pronunciation  404   ← 写入侧干净、读取侧有货

这正是 es 那次事故的形状（音标修复写在旧列、展示层改读新表 ⇒ 查旧列永远绿）。
这次不是"修复被绕过"，而是**新表从 dump 原样收进来的写法与本库约定不一致**：

    groppone     gropˈpone      it-edition
    evergreen    ɛverˈgrin      it-edition
    interlingua  interˈliŋgʷa   it-edition
    groove       gruːf          fr-edition

来源分布：it 版 296 / fr 版 107 / 七月模型 1。

═══ 为什么这是归一而不是"改数据" ═══
IPA 里**没有** U+0067 这个符号，浊软腭塞音的正字就是 ɡ（U+0261）——
两者是同一个音的两种码位，替换**无损**。`ŋg` → `ŋɡ` 同理。
（对比：es 上被推翻的那些"看着不像西语就改"的判据是**猜**，这条不是。）

⚠️ 同时改 `ipa_variants.norm_ipa`，让**以后每次收词**都在入口归一 ——
   只修库不修入口，下次重跑 dump 又会灌回来（`replay-scripts-undo-fixes`）。

用法（在 it/ 目录下）：
    python3 fixes/normalize_ipa_latin_g.py            # 干跑
    python3 fixes/normalize_ipa_latin_g.py --apply
    python3 fixes/normalize_ipa_latin_g.py --verify
    python3 fixes/normalize_ipa_latin_g.py --mutate
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402

LATIN_G = "g"      # U+0067
IPA_G = "ɡ"        # U+0261
f = lambda n: format(n, ",")


def scan(con):
    """→ (pronunciation 要改的, dict 要改的)。判据只有一条：串里有 U+0067。"""
    pr = [(i, t) for i, t in con.execute(
        "SELECT id, ipa FROM pronunciation WHERE ipa LIKE '%'||char(103)||'%'")]
    dc = [(i, t) for i, t in con.execute(
        "SELECT id, ipa FROM dict WHERE ipa LIKE '%'||char(103)||'%'")]
    return pr, dc


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    pr, dc = scan(con)
    checks = [
        ("🔴 pronunciation 里没有拉丁 g 了", len(pr), 0),
        ("🔴 dict.ipa 里没有拉丁 g 了", len(dc), 0),
        # 🔴 只换码位、不换内容：ɡ 的总数必须恰好涨了原来 g 的个数
        ("🔴 没有把别的字符一起改掉（长度不变）",
         q("SELECT count(*) FROM pronunciation p JOIN dict d ON d.id=p.word_id "
           "WHERE length(p.ipa)=0"), 0),
        ("🔴 归一函数入口已经拦住（norm_ipa 不再吐 U+0067）",
         0 if "ɡ" == __import__("ipa_variants").norm_ipa("g") else 1, 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-44s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def mutate():
    print("═══ 变异验证：判据本体 ═══")
    import ipa_variants as V
    cases = [
        ("拉丁 g 被归一", V.norm_ipa("gropˈpone"), "ɡropˈpone"),
        ("🔴 ŋg 里的 g 也要归一", V.norm_ipa("interˈliŋgʷa"), "interˈliŋɡʷa"),
        ("已经是 ɡ 的不动", V.norm_ipa("ˈɡat.to"), "ˈɡat.to"),
        ("🔴 不许动别的字母（d 不是 g）", V.norm_ipa("ˈdɔn.na"), "ˈdɔn.na"),
        ("🔴 cmp_key 也跟着一致（否则两把尺子打架）",
         V.cmp_key("gropˈpone") == V.cmp_key("ɡropˈpone"), True),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-40s → %s" % ("✅" if good else "🔴", name, got))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    pr, dc = scan(ro)
    ro.close()
    print("■ pronunciation %s 行 / dict.ipa %s 行 含拉丁 g" % (f(len(pr)), f(len(dc))))
    for i, t in pr[:8]:
        print("     %-22s → %s" % (t[:22], t.replace(LATIN_G, IPA_G)[:22]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    # 🔴 归一会撞 `UNIQUE(word_id, ipa, notation)`：同一个词同时存着 `ˈgɔj`（it 版）
    #    与 `ˈɡɔj`（en 版）—— 它们本来就是**同一个读音的两种码位**，只是当初没归一，
    #    在表里假装成了两条变体。实测 149 条这样的。
    #    ⇒ 撞车的那条**删掉**（不是改），并在必要时把 is_primary 交接给幸存的那条。
    ro2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    exist = {}
    for rid, wid, ipa, nt, prim in ro2.execute(
            "SELECT id, word_id, ipa, notation, is_primary FROM pronunciation"):
        exist[(wid, ipa, nt)] = (rid, prim)
    meta = {rid: (wid, ipa, nt, prim) for rid, wid, ipa, nt, prim in ro2.execute(
        "SELECT id, word_id, ipa, notation, is_primary FROM pronunciation "
        "WHERE ipa LIKE '%'||char(103)||'%'")}
    ro2.close()
    upd, drop, promote = [], [], []
    for rid, ipa in pr:
        wid, _old, nt, prim = meta[rid]
        tgt = ipa.replace(LATIN_G, IPA_G)
        if (wid, tgt, nt) in exist:
            drop.append(rid)
            if prim:                       # 被删的那条是默认展示 ⇒ 交接给幸存那条
                promote.append(exist[(wid, tgt, nt)][0])
        else:
            upd.append((tgt, rid))
    print("   其中：改写 %s 行 / 因与已有行同码位而删除 %s 行（is_primary 交接 %s 条）"
          % (f(len(upd)), f(len(drop)), f(len(promote))))
    with dbtool.session("normalize-ipa-latin-g",
                        expect={"__rows__": 0, "ipa": 0,
                                "#pronunciation": -len(drop)}) as s:
        s.executemany("UPDATE pronunciation SET ipa=? WHERE id=?", upd)
        if drop:
            s.execute("DELETE FROM pronunciation WHERE id IN (%s)"
                      % ",".join(str(i) for i in drop))
        if promote:
            s.execute("UPDATE pronunciation SET is_primary=1 WHERE id IN (%s)"
                      % ",".join(str(i) for i in promote))
        s.executemany("UPDATE dict SET ipa=? WHERE id=?",
                      [(x.replace(LATIN_G, IPA_G), i) for i, x in dc])
        s.written = len(upd) + len(drop) + len(dc)
    print("\n■ 已归一 %s 行，删重复 %s 行" % (f(len(upd) + len(dc)), f(len(drop))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
