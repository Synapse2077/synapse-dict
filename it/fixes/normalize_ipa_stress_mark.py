#!/usr/bin/env python3
"""音标里的撇号当重音符用（`'luːna`）→ 归一成 IPA 的 `ˈ`（U+02C8）。2026-08-18（阶段 8）。

═══ 怎么发现的 ═══
阶段 8 把展示层切到 `pronunciation` 之后，翻多读音词的渲染结果，`pesca` 出来四条：

    ˈpɛska (en 版)   ˈpeska (en 版)   'peska (fr 版)   'pɛska (fr 版)

后两条与前两条是**同一个读音**，只是重音符写成了 ASCII 撇号。用户看到的是
「这个词有四个读音」，而真相是两个。

🔴 又是 `dict.ipa` 那一列 **0 条**、`pronunciation` **7,089 条** ——
   与两天前的拉丁 `g` 完全同一个形状（写入侧干净、读取侧有货）。
   区别在于：`g` 是回归闸自己报出来的，这次是**接上展示层才看见的**
   （闸里没有「重音符必须是 U+02C8」这一条 —— 现在补上了）。

═══ 为什么这是归一，不是改数据 ═══
IPA 的主重音符是 U+02C8 `ˈ`，**没有** U+0027 / U+2019 / U+2032 这三个码位；
fr 版与 it 版的社区习惯是直接敲键盘上的撇号。两者指同一件事，替换无损。
（判据与 `normalize_ipa_latin_g` 同源：**回权威源能证明的码位差**才归一，
 「看着不像意语」那种猜测一律不做。）

来源分布：fr 版 6,746 / it 版 343（含 4 条弯撇号、1 条 prime）。

⚠️ 同时改 `ipa_variants.norm_ipa`，**下次重扫 dump 才不会又灌回来**
   （`replay-scripts-undo-fixes`）。

用法（在 it/ 目录下）：
    python3 fixes/normalize_ipa_stress_mark.py            # 干跑
    python3 fixes/normalize_ipa_stress_mark.py --apply
    python3 fixes/normalize_ipa_stress_mark.py --verify
    python3 fixes/normalize_ipa_stress_mark.py --mutate
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool                              # noqa: E402
import paths                               # noqa: E402
import build_pronunciation_layer as B      # noqa: E402
from ipa_variants import STRESS_ALIASES, norm_ipa   # noqa: E402

f = lambda n: format(n, ",")
LIKE = " OR ".join("ipa LIKE '%'||?||'%'" for _ in STRESS_ALIASES)


def scan(con, table="pronunciation"):
    """→ [(id, 原串, 归一后)]。判据只有一条：串里有 STRESS_ALIASES 里的字符。"""
    out = []
    for rid, ipa in con.execute(
            "SELECT id, ipa FROM %s WHERE %s" % (table, LIKE), tuple(STRESS_ALIASES)):
        fixed = norm_ipa(ipa)
        if fixed != ipa:
            out.append((rid, ipa, fixed))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("🔴 pronunciation 里没有撇号式重音符了", len(scan(con)), 0),
        ("🔴 dict.ipa 里也没有", len(scan(con, "dict")), 0),
        ("🔴 每个词形恰好一条 is_primary",
         q("SELECT count(*) FROM (SELECT word_id FROM pronunciation "
           "GROUP BY word_id HAVING sum(is_primary)<>1)"), 0),
        ("🔴 归一函数入口已拦住（norm_ipa 不再吐撇号）",
         0 if norm_ipa("'luːna") == "ˈluːna" else 1, 0),
        # 🔴 可逆性：删/改都不许伤到「从表重建 dict.ipa」
        ("🔴 可逆性：逐字节重建 dict.ipa 对不上的",
         q("SELECT count(*) FROM dict d WHERE trim(COALESCE(d.ipa,''))<>'' "
           "AND NOT EXISTS(SELECT 1 FROM pronunciation p WHERE p.word_id=d.id "
           "AND p.ipa=d.ipa AND p.src_ref LIKE '%dict.ipa%')"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-44s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def mutate():
    print("═══ 变异验证：判据本体 ═══")
    cases = [
        ("直撇号 → ˈ", norm_ipa("'luːna"), "ˈluːna"),
        ("🔴 串中间的也要换", norm_ipa("man'nad͡ʒːa"), "manˈnad͡ʒːa"),
        ("🔴 一串里有两个", norm_ipa("'konversa'tsjone"), "ˈkonversaˈtsjone"),
        # 🔴 顺序判据：撇号必须在「折重音符前的音节点」之前换掉（见 norm_ipa 的注释）
        ("🔴 fr 版 `a.'ba.te` 要折成 aˈba.te", norm_ipa("a.'ba.te"), "aˈba.te"),
        ("弯撇号 U+2019", norm_ipa("’luna"), "ˈluna"),
        ("prime U+2032", norm_ipa("′luna"), "ˈluna"),
        ("已经是 ˈ 的不动", norm_ipa("ˈluna"), "ˈluna"),
        ("🔴 次重音 ˌ 不许被动", norm_ipa("ˌkonverˈsare"), "ˌkonverˈsare"),
        # ⚠️ 期望值是 `ˈdɔn.na` 不是 `ˈdɔnna` —— `norm_ipa` **只折重音符前的音节点**，
        #    词中的点是源头的音节切分，有信息量，存的时候要留（折不折是 `cmp_key` 的事，
        #    两把尺子分开，A52）。第一版我把期望写成去点的，变异 7/8，错的是用例不是判据。
        ("🔴 别的字符不许被动", norm_ipa("ˈdɔn.na"), "ˈdɔn.na"),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-36s → %s" % ("✅" if good else "🔴", name, got))
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
    hits = scan(ro)
    dc = scan(ro, "dict")
    print("■ pronunciation %s 行 / dict.ipa %s 行 用撇号当重音符" % (f(len(hits)), f(len(dc))))
    for _i, old, new in hits[:8]:
        print("     %-24s → %s" % (old[:24], new[:24]))
    # 归一之后会撞 UNIQUE(word_id, ipa, notation) 的：`'peska`(fr) 与 `ˈpeska`(en)
    # 本来就是同一个读音的两种记法，撞上的那条**删掉**（不是改），is_primary 交接。
    meta = {rid: (wid, ipa, nt, prim) for rid, wid, ipa, nt, prim in ro.execute(
        "SELECT id, word_id, ipa, notation, is_primary FROM pronunciation")}
    exist = {(wid, ipa, nt): (rid, prim) for rid, (wid, ipa, nt, prim) in meta.items()}
    ro.close()
    upd, drop = [], []
    for rid, _old, new in hits:
        wid, _o, nt, _p = meta[rid]
        (drop if (wid, new, nt) in exist else upd).append((new, rid))
    print("   其中：改写 %s 行 / 因与已有行同读音而删除 %s 行" % (f(len(upd)), f(len(drop))))
    if not a.apply or not hits:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("normalize-ipa-stress-mark",
                        expect={"__rows__": 0, "ipa": 0, "#pronunciation": -len(drop)}) as s:
        s.executemany("UPDATE pronunciation SET ipa=? WHERE id=?", upd)
        if drop:
            s.execute("DELETE FROM pronunciation WHERE id IN (%s)"
                      % ",".join(str(i) for _n, i in drop))
        s.executemany("UPDATE dict SET ipa=? WHERE id=?", [(n, i) for i, _o, n in dc])
        s.written = len(upd) + len(drop) + len(dc)
    print("\n■ 已归一 %s 行、删同读音重复 %s 行；重选 is_primary…" % (f(len(upd)), f(len(drop))))
    B.restamp(dry=False)     # 🔴 删掉的可能正是 is_primary 那条，复用写入侧的选举判据
    return 0


if __name__ == "__main__":
    sys.exit(main())
