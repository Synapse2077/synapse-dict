#!/usr/bin/env python3
"""自反式被标成「变位形式」—— 改成「自反形式」。2026-08-19。

═══ 用户看得到 ═══
    lavarsi  显示成「lavare 的 变位形式」   ← 错
             应该是「lavare 的 自反形式」

源头写得很清楚（`desc_en = "reflexive of lavare"`、`tags = ["form-of","reflexive"]`），
是我们的标签合成器 `infl_compose.compose()` 没认这个 tag，落到了兜底值「变位形式」。
**全库 1,418 条**（记账本原记 211，那个数是按 `-rsi` 词尾数的 —— 词尾判据把
`apersi`/`persi` 这类远过去时也算了进去，又漏了不以 -rsi 结尾的。**判据要用 tags 不用词尾**）。

═══ 为什么改这个标签以前"不敢动" ═══
记账本写着「改标签会让闸①a 对不上七月的 `dict.infl` 旧列 ⇒ 等阶段 8 删旧列时一起改」。
现在有 A83 的做法了：**同一处留两套** ——
`compose(tags)` 冻结成七月行为给复刻用，`compose(tags, legacy=False)` 给新表用。
旧列一个字节不动，闸①a 照常全绿。

用法（在 it/ 目录下）：
    python3 fixes/relabel_reflexive_forms.py            # 干跑
    python3 fixes/relabel_reflexive_forms.py --apply
    python3 fixes/relabel_reflexive_forms.py --verify
    python3 fixes/relabel_reflexive_forms.py --mutate
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool                      # noqa: E402
import paths                       # noqa: E402
from infl_compose import compose   # noqa: E402

f = lambda n: format(n, ",")


# 兜底值。**只动这个值的行** —— 见 scan() 的说明。
FALLBACK = "变位形式"


def scan(con):
    """→ [(id, 词形, 旧 label, 新 label)]，**只含「兜底值 → 自反形式」这一族**。

    🔴 第一版判据是「拿 tags 重算一遍，与现值不同就改」，干跑显示要改 **4,541 行**，
       其中 **3,112 行是把已经正确的「阴性形式」改回兜底值「变位形式」** ——
       那些是后来某个脚本改好的，`compose()` 本身产生不了。
       **重放式判据会静默撤销已完成的修复**（`replay-scripts-undo-fixes`，这是第 N 次）。
    ⇒ 收窄成两个条件同时成立：① 现值**正好是兜底值**（说明没人改过它）
       ② 重算结果不是兜底值。既补上了缺的，又不可能覆盖别人的成果。
    """
    out = []
    for rid, w, lab, tags in con.execute(
            "SELECT i.id, d.word, i.label_zh, i.tags FROM inflection i "
            "JOIN dict d ON d.id=i.word_id WHERE i.tags IS NOT NULL AND i.label_zh=?",
            (FALLBACK,)):
        try:
            t = json.loads(tags)
        except Exception:
            continue
        want = compose(t, legacy=False)
        if want and want != lab:
            out.append((rid, w, lab, want))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    left = scan(con)
    checks = [
        ("🔴 还是兜底值、但 tags 算得出真标签的", len(left), 0),
        # 🔴 反面：`reflexive` 的一条都不许再叫「变位形式」
        ("🔴 tags 带 reflexive 却标成变位形式的",
         q("SELECT count(*) FROM inflection WHERE tags LIKE '%reflexive%' "
           "AND label_zh='变位形式'"), 0),
        # ⚠️ 旧列必须一个字节没动 —— 那是闸①a 的锚
        ("·  dict.infl 非空行数（不该变）", q("SELECT count(*) FROM dict WHERE infl IS NOT NULL"),
         444043),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-40s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def mutate():
    print("═══ 变异验证：标签判据 ═══")
    cases = [
        ("🔴 自反式（新表）", compose(["form-of", "reflexive"], legacy=False), "自反形式"),
        ("🔴 自反式（复刻路径必须保持七月的空值）", compose(["form-of", "reflexive"]), ""),
        ("带语域的自反式也认", compose(["form-of", "literary", "reflexive"], legacy=False), "自反形式"),
        ("🔴 普通变位不受影响",
         compose(["form-of", "third-person", "singular", "present", "indicative"], legacy=False),
         "陈述式现在时第三人称单数"),
        ("🔴 复刻路径的普通变位也不受影响",
         compose(["form-of", "third-person", "singular", "present", "indicative"]),
         "陈述式现在时第三人称单数"),
        ("不定式不受影响", compose(["form-of", "infinitive"], legacy=False), "不定式"),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-40s → %r" % ("✅" if good else "🔴", name, got))
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
    rows = scan(ro)
    ro.close()
    from collections import Counter
    print("■ 要改 %s 行" % f(len(rows)))
    for (old, new), n in Counter((r[2], r[3]) for r in rows).most_common(10):
        print("   %-16s → %-16s %s 行" % (old[:16], new[:16], f(n)))
    for r in rows[:6]:
        print("     %-20s 「%s」→「%s」" % (r[1][:20], r[2], r[3]))
    if not a.apply or not rows:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("relabel-reflexive-forms", expect={"__rows__": 0, "infl": 0}) as s:
        s.executemany("UPDATE inflection SET label_zh=? WHERE id=?",
                      [(new, rid) for rid, _w, _o, new in rows])
        s.written = len(rows)
    print("\n■ 已改 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
