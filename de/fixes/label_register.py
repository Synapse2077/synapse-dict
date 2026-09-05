#!/usr/bin/env python3
"""收尾单 C36：变形标签把源头的**语域／时代标扔了**。de，2026-09-04。

═══ 起因：外审拿渲染成品挑错，三条指到同一件事 ═══
    `kömmt` 「现在时第三人称单数」   源头 tags = [archaic, dialectal, …]
    `gib`   「现在时第一人称单数」   源头 tags = [colloquial, …]
    `nimm`  同上
两家都判「错的，标准形是 kommt / gebe / nehme」。

🔴 **回源之后判两家都错**：英文版确实收了 `ich gib` 这个**口语**一单、
   `kömmt` 这个**古／方言**三单 —— 数据是对的。错的是我们只显示语法位置、
   把前提扔了，于是页面上是「kömmt 是 kommen 的现在时第三人称单数」这句
   **没有前提的话**。⇒ 这条记在「我判外审说错、但它指对了地方」那一栏。

═══ 判据收窄了两轮，两轮都是被数据打回来的 ═══
    第一版「带语域标就加前缀」            64,245 行
    第二版 去掉标签里已经写了的           14,548 行
    第三版 去掉 formal/rare              **4,510 行**  ← 真实规模
`formal`+`rare` 那 47,048 行**全部**落在虚拟式 II 上 = 英文版给整个范式打的
惯例标。给四万七千行统一加「正式·罕用」是加噪声不是加信息。

═══ 两件都要做，少一件都会被冲掉 ═══
① **生成侧** `infl_compose.compose()` 已改（本脚本 import 它的 `_with_register`）
   —— 判据只许一份；
② **已落库的 4,510 行**用本脚本补 —— 不重跑整个变形层（536 万行）。
⚠️ 只做 ② 是 `[[replay-scripts-undo-fixes]]`：变形层一重跑就把修复冲掉。
   只做 ① 则现在库里仍是错的。

用法：
    python3 fixes/label_register.py            # 试算
    python3 fixes/label_register.py --write
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths                                                    # noqa: E402
from infl_compose import _with_register, register_of, register_ok            # noqa: E402

f = lambda n: format(n, ",")


def plan(con):
    """→ [(id, 旧标签, 新标签)]，只列真正会变的行。"""
    rows = []
    stat = Counter()
    for iid, tags, lab in con.execute(
            "SELECT id, tags, label_zh FROM inflection "
            "WHERE tags IS NOT NULL AND tags <> ''"):
        try:
            t = set(json.loads(tags))
        except Exception:
            stat["tags 不是 JSON，跳过"] += 1
            continue
        if not register_of(t):
            continue
        stat["带语域标的行"] += 1
        if not lab:
            stat["  标签为空，不动"] += 1
            continue
        new = _with_register(t, lab)
        if new == lab:
            stat["  标签里已经写了／是「变形」，不动"] += 1
            continue
        rows.append((iid, lab, new))
        stat["🔴 该补前缀"] += 1
    return rows, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, stat = plan(con)
    con.close()
    for k, v in stat.most_common():
        print("   %-38s %8s" % (k, f(v)))

    print("\n■ 样本（前缀 → 标签）")
    seen = Counter()
    for iid, old, new in rows:
        pre = new.split(" · ")[0]
        if seen[pre] < 2:
            seen[pre] += 1
            print("   %-14s %-28s → %s" % (pre, old[:28], new[:44]))

    if not a.write:
        print("\n(未加 --write，未写库)")
        return 0

    import dbtool
    with dbtool.session("keep-v3-c36-label-register",
                        expect={}) as s:
        s.executemany("UPDATE inflection SET label_zh=? WHERE id=?",
                      [(new, iid) for iid, _, new in rows])

    # ═══ 闸：**直接断言不变量**，不问「再跑一遍等不等」。
    #    后者会把幂等性混进来当正确性验（我第一版就是那么写的，会报假红）。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = 0
    for iid, tags, lab in con.execute(
            "SELECT id, tags, label_zh FROM inflection "
            "WHERE tags IS NOT NULL AND tags <> ''"):
        try:
            t = set(json.loads(tags))
        except Exception:
            continue
        if not register_ok(t, lab):
            bad += 1
    print("\n■ 闸：库里还有 %s 行该带语域前缀而没带（期望 0）" % f(bad))
    con.close()
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
