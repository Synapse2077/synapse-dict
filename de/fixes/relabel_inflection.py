#!/usr/bin/env python3
"""把 `inflection.label_zh` 从存着的 `tags` **重算一遍**。2026-09-04（收尾单 C15 + C16）。

═══ 一次修两族，因为它们是同一个动作的两半 ═══
    C15  变化类连写      122,356 行  `强变化弱变化混合变化阳性单数宾格`
    C16  异体被标成变形   56,332 行  tags 说 `["alternative","Switzerland",…]`、标签却是「变形」

═══ 🔴 为什么是「重算」而不是「替换字符串」═══
标签是 `tags` 的**函数**。既然 `tags` 原样存着，正确的修法就是**拿修好的生成侧再算一遍**，
而不是去猜哪些字符串该换成什么。后者是形式代理，而且改不动没预料到的组合。
⇒ 本文件不写任何映射表，只调两个现成的判据：
    · `infl_compose.compose(tags)`            —— 语法形式（C15 的 bug 已在那里修掉）
    · `link_blank_forms.is_spelling_variant`  —— 这条是不是「另一种写法」
      `link_blank_forms.variant_label(tags)`  —— 是的话该叫什么
  ⚠️ 后两个是阶段 2d 写的，**当时就已经在用**（2d 落的 18,199 行标签是对的）。
     C16 那 56,332 行只是**早于 2d**、没享受到同一份判据。

═══ 🔴 必须同时修生成侧，否则下一轮重跑会把修复冲掉 ═══
`[[replay-scripts-undo-fixes]]`：修复只做在一层、后一步从另一层重灌 ⇒ 静默倒退。
本轮 `infl_compose.compose()` 已改（C15 的根因），所以重跑 2b/2c 只会得到同样的结果。

用法（在 de/ 目录下）：
    python3 -u fixes/relabel_inflection.py            # 干跑（列出会变的形状）
    python3 -u fixes/relabel_inflection.py --apply
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

import dbtool                                                   # noqa: E402
import paths                                                    # noqa: E402
from infl_compose import compose                                # noqa: E402
from link_blank_forms import is_spelling_variant, variant_label  # noqa: E402

f = lambda n: format(n, ",")


def want_label(tags):
    """→ 这行**应该**叫什么。判据全部 import，本文件不发明。"""
    if not tags:
        return None                       # 没证据就别动它
    if is_spelling_variant(tags):
        return variant_label(tags)
    return compose(tags) or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, stat, ex = [], Counter(), {}
    for rid, tags_s, old in con.execute(
            "SELECT id, tags, label_zh FROM inflection WHERE tags IS NOT NULL"):
        try:
            tags = json.loads(tags_s)
        except Exception:
            stat["tags 不是合法 JSON（不动）"] += 1
            continue
        new = want_label(tags)
        if new is None or new == old:
            stat["不变" if new == old else "算不出（不动）"] += 1
            continue
        rows.append((new, rid))
        k = "%s → %s" % (old[:26], new[:30])
        stat["改：%s" % k] += 1
        ex.setdefault(k, tags)

    print("■ 待改 %s 行" % f(len(rows)))
    for k, v in stat.most_common(14):
        print("   %-64s %9s" % (k[:64], f(v)))
    con.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("keep-v3-c15c16-relabel", expect={}) as s:
        s.executemany("UPDATE inflection SET label_zh=? WHERE id=?", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n═══ 闸② 不变量断言 ═══")
    # C15：一个标签里出现多个变化类 —— 判据与回归闸 B3 同源
    bad15 = sum(1 for (x,) in con.execute(
        "SELECT label_zh FROM inflection WHERE label_zh IS NOT NULL")
        if sum(x.count(k) for k in ("强变化", "弱变化", "混合变化")) > 1
        and "/" not in x)
    # C16：tags 说是异体、标签却还是光秃秃的「变形」
    bad16 = 0
    for t, lab in con.execute("SELECT tags, label_zh FROM inflection WHERE tags IS NOT NULL"):
        if lab != "变形":
            continue
        try:
            if is_spelling_variant(json.loads(t)):
                bad16 += 1
        except Exception:
            pass
    checks = [("🔴 C15 变化类仍连写（无分隔符）", bad15, 0),
              ("🔴 C16 异体仍被标成「变形」", bad16, 0),
              ("🔴 label_zh 变空", q("SELECT COUNT(*) FROM inflection "
                                   "WHERE label_zh IS NULL OR label_zh=''"), 0)]
    ok = True
    for name, got, exp in checks:
        good = got == exp
        ok &= good
        print("   %s %-36s %10s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(exp)))
    con.close()
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
