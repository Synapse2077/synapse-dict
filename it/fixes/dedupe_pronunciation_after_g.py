#!/usr/bin/env python3
"""归一拉丁 g 之后冒出来的 317 组重复读音，按行键合并。2026-08-18（阶段 7）。

═══ 为什么会冒出来 ═══
`normalize_ipa_latin_g.py` 把 `g`（U+0067）换成 `ɡ`（U+0261）之后，
原来"看着不同"的两行变成了同一个读音：

    tago       ˈta.ɡo（en 版，列值锚点）   ↔  ˈtaɡo（it 版）      ← 只差音节点
    Guatemala  ɡwa.teˈma.la（en 版）      ↔  ɡwateˈmala（it 版）

`UNIQUE(word_id, ipa, notation)` 拦不住它们（字节确实不同），拦得住的是
**行键判据 `cmp_key`**（折掉音节点/tie-bar/滑音之后同一个读音只该有一行）——
阶段 4 的闸④正是查这个，归一之后它报了 317 组。

═══ 合并方向：留优先级高的那条，但**锚点不许动** ═══
🔴 **298 组里含「列值锚点」**（`src_ref` 带 `dict.ipa` 的那行）。
   锚点是「从表逐字节重建 `dict.ipa`」的唯一依据（阶段 4 闸①），删掉它可逆性就断了。
   ⇒ 判据：**锚点行永远留下**；没有锚点的组按 `en > it > fr > rule…` 留优先级高的。
   被删那行若是 `is_primary`，把标记交接给幸存行。

═══ 这个脚本是**可重复使用的**，不是一次性的 ═══
2026-08-18 阶段 8 又跑了一次：`normalize_ipa_stress_mark.py` 把撇号换成 `ˈ` 之后，
`norm_ipa` 顺带折掉了「重音符前的音节点」，于是 `a.'ba.te` 与 `aˈba.te` 变成同一个行键
—— 新冒出 **1,140 组**，同一个形状。
⇒ **每次动 `norm_ipa` 之后都要跑这个脚本**（闸④会红，别把它当断言过期）。

用法（在 it/ 目录下）：
    python3 fixes/dedupe_pronunciation_after_g.py            # 干跑
    python3 fixes/dedupe_pronunciation_after_g.py --apply
    python3 fixes/dedupe_pronunciation_after_g.py --verify
"""
import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool                                        # noqa: E402
import paths                                         # noqa: E402
from build_pronunciation_layer import PRIO           # noqa: E402
from ipa_variants import cmp_key                     # noqa: E402

LEGACY = "dict.ipa"
f = lambda n: format(n, ",")


def groups(con):
    """→ [(留下的 id, [要删的 id], 要不要把 is_primary 交接给留下的)]"""
    g = defaultdict(list)
    for rid, wid, ipa, nt, prim, src, ref in con.execute(
            "SELECT id, word_id, ipa, notation, is_primary, src, src_ref FROM pronunciation"):
        g[(wid, cmp_key(ipa), nt)].append((rid, prim, src, LEGACY in ref))
    out = []
    for k, rows in g.items():
        if len(rows) < 2:
            continue
        # 判据：锚点行优先留（可逆性），其次按来源优先级，再次按 id 稳定定序
        rows.sort(key=lambda r: (not r[3], PRIO.get(r[2], 9), r[0]))
        keep, drop = rows[0], rows[1:]
        out.append((keep[0], [r[0] for r in drop], any(r[1] for r in drop) and not keep[1]))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    left = groups(con)
    # 可逆性：每个有 dict.ipa 的词形仍要有恰好一个锚点，且逐字节对得上
    legacy = {}
    for wid, ipa, ref in con.execute(
            "SELECT word_id, ipa, src_ref FROM pronunciation "
            "WHERE src_ref LIKE '%|" + LEGACY + "' OR src_ref LIKE '" + LEGACY + ":%'"):
        legacy[wid] = ipa
    col = {i: t for i, t in con.execute(
        "SELECT id, ipa FROM dict WHERE trim(COALESCE(ipa,''))<>''")}
    checks = [
        ("🔴 折排版后重复的行键", len(left), 0),
        ("🔴 可逆性：逐字节重建 dict.ipa 对不上的",
         sum(1 for i, t in col.items() if legacy.get(i) != t), 0),
        ("🔴 锚点数 == 列非空数", len(legacy), len(col)),
        ("🔴 每个词形恰好一条 is_primary",
         q("SELECT count(*) FROM (SELECT word_id FROM pronunciation "
           "GROUP BY word_id HAVING sum(is_primary)<>1)"), 0),
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
    gs = groups(ro)
    ro.close()
    drops = [i for _k, ds, _p in gs for i in ds]
    promote = [k for k, _d, p in gs if p]
    print("■ 重复组 %s，要删 %s 行，is_primary 交接 %s 条" % (f(len(gs)), f(len(drops)), f(len(promote))))
    if not a.apply or not gs:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("dedupe-pronunciation-after-g",
                        expect={"__rows__": 0, "#pronunciation": -len(drops)}) as s:
        s.execute("DELETE FROM pronunciation WHERE id IN (%s)"
                  % ",".join(str(i) for i in drops))
        if promote:
            s.execute("UPDATE pronunciation SET is_primary=1 WHERE id IN (%s)"
                      % ",".join(str(i) for i in promote))
        s.written = len(drops)
    print("\n■ 已删 %s 行" % f(len(drops)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
