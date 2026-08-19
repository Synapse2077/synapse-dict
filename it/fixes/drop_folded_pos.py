#!/usr/bin/env python3
"""回收 `dict.pos` 里大小写折叠留下的假词性。2026-08-17。

═══ 是什么 ═══
建库时 `build.py:330` 用 `key = word.lower()` 把大小写折叠成一条记录，
于是**大写专名的词性并进了小写词形**：

    Molossi  name  一个姓氏          ┐
    molossi  noun  molosso 的复数    ┘→ 折叠成一条  rec["pos"] = {n, name}

后来大写行被拆成了独立的 `dict` 行（专名义项、中文都在那边，完好），
但小写行上那个**折叠过的 `pos` 没有回收**。用户看到的是：

    usa      → 徽标【动词 · 专名】   实际只是 usare 的变位（专名在 USA 行）
    marche   → 徽标【名词 · 专名】   实际只是 marca 的复数（专名在 Marche 行）
    angola   → 徽标【专名 · 动词】   实际只是 angolare 的变位（专名在 Angola 行）

`App.tsx` 的 `showStubPos = isLemma && pos && 没有任何义项带 pos` 会把它渲染出来
⇒ **1,523 行用户真看得见**（另有 2,069 行被逐义项词性顶掉，看不见但数据仍是错的）。

═══ 判据 ═══
`dict.pos` 里出现了**本行** `entry.pos ∪ sense.pos` 都没有的词性 ⇒ 删掉那一项。

    ⚠️ 只删不加。反方向（`dict.pos` 比源头**少**）有 4,371 行，**本轮不动** ——
       那是另一个问题：`aquila` 的 `name` 到底该不该在小写行上，取决于 entry 层
       自己有没有折叠过大小写，没查清之前加词性等于把未验证的判断写进数据。
       记账，见 docs/IT_PLAN.md。

    ⚠️ 源头为空的行（既无 entry 又无带词性的 sense）跳过 —— 无从判定，不是"该删"。

═══ 为什么不在展示层挡 ═══
`aim-for-perfect-not-cheap`：展示层补丁只治一个渲染点，而 `dict.pos` 还被搜索排序、
划词弹窗、以后的接口读。错在数据里就在数据里修。

用法（在 it/ 目录下）：
    python3 fixes/drop_folded_pos.py            # 干跑
    python3 fixes/drop_folded_pos.py --apply
    python3 fixes/drop_folded_pos.py --verify
    python3 fixes/drop_folded_pos.py --mutate
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build import POS_MAP   # noqa: E402


def truth_of(con):
    """→ {word_id: 本行有证据的词性集合}。entry 与 sense 都统一成展示短码。"""
    t = defaultdict(set)
    for wid, p in con.execute("SELECT word_id, pos FROM entry"):
        t[wid].add(POS_MAP.get(p, p))
    for wid, p in con.execute(
            "SELECT word_id, pos FROM sense WHERE COALESCE(hidden,0)=0 AND pos IS NOT NULL"):
        t[wid].add(POS_MAP.get(p, p))
    return t


def name_rows(con):
    """→ {小写键: 该词形的哪些行带专名义项}，用来证明 `name` 确实属于**另一行**。"""
    has_name = set()
    for (wid,) in con.execute(
            "SELECT DISTINCT word_id FROM sense WHERE pos='name' AND COALESCE(hidden,0)=0"):
        has_name.add(wid)
    for (wid,) in con.execute("SELECT DISTINCT word_id FROM entry WHERE pos='name'"):
        has_name.add(wid)
    by_key = defaultdict(set)
    for wid, w in con.execute("SELECT id, word FROM dict"):
        if wid in has_name:
            by_key[w.lower()].add(wid)
    return by_key


def scan(con):
    """→ [(word_id, 词形, 旧 pos, 新 pos, 删掉的)]

    🔴 判据收窄到**大小写折叠**这一族，三个条件同时成立才删：
       ① `dict.pos` 里有 `name`
       ② **本行**没有任何 `name` 证据（entry / 可见 sense 都没有）
       ③ 存在**大小写不同的另一行**，它确实带专名义项 —— 折叠的来源就在那儿

    ⚠️ 第一版判据是「`dict.pos` 里凡是 entry∪sense 没有的都删」，跑出来 3,591 行，
       其中 36 行不属于 name 那族，逐条读发现 **`sue` / `suoi` 被删掉 `det`+`pron`**
       —— 那是 `suo` 的物主限定词/代词读法，**真实存在**，只是我们 entry 层没收。
       ⇒ 「entry∪sense 就是真值」不成立：源头不全时，按它删就是照着自己的缺口切数据。
       收窄后那 36 行进记账基线，留给 entry 层补齐那一轮再看。
    """
    t = truth_of(con)
    nm = name_rows(con)
    out = []
    for wid, w, pos in con.execute("SELECT id, word, pos FROM dict WHERE pos IS NOT NULL"):
        have = pos.split("/")
        if "name" not in have:
            continue                                   # ①
        if "name" in t.get(wid, set()):
            continue                                   # ②：本行自己有专名证据，不动
        if not (nm.get(w.lower(), set()) - {wid}):
            continue                                   # ③：找不到折叠来源，不动
        keep = [p for p in have if p != "name"]
        if not keep:
            continue                                   # 🔴 全删会把 pos 清空，那是另一种错
        out.append((wid, w, pos, "/".join(keep), "name"))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    left = scan(con)
    t = truth_of(con)
    # 记账基线：本轮有意不动的两族
    miss = sum(1 for wid, pos in con.execute("SELECT id, pos FROM dict WHERE pos IS NOT NULL")
               if t.get(wid) and (t[wid] - set(pos.split("/"))))
    other = sum(1 for wid, pos in con.execute("SELECT id, pos FROM dict WHERE pos IS NOT NULL")
                if t.get(wid) and [p for p in pos.split("/") if p != "name" and p not in t[wid]])
    empty = con.execute(
        "SELECT count(*) FROM dict WHERE pos IS NOT NULL AND trim(pos)=''").fetchone()[0]
    checks = [
        ("🔴 折叠留下的假 name 已清零", len(left), 0),
        ("🔴 没有把 pos 清成空串", empty, 0),
        # 🔴 `sue`/`suoi` 那族：entry 层缺 det/pron，按 entry 删会切掉真读法
        ("（记账）非 name 的对不上，entry 层缺项，不动", other, other),
        ("（记账）dict.pos 比源头少的，本轮不动", miss, miss),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-40s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def mutate():
    """判据必须能识破四种情形。用假数据跑 `scan` 的核心逻辑。"""
    print("\n═══ 变异验证 ═══")
    def core(have, good, folded_elsewhere=True):
        """与 scan() 同形状的三条件判据。good = 本行 entry∪sense 的词性。"""
        parts = have.split("/")
        if "name" not in parts or "name" in good or not folded_elsewhere:
            return have
        keep = [p for p in parts if p != "name"]
        return "/".join(keep) if keep else have
    cases = [
        ("折叠留下的 name 要删掉", core("n/name", {"n"}), "n"),
        ("源头齐全 ⇒ 不动", core("n/v", {"n", "v"}), "n/v"),
        ("🔴 本行自己有专名证据 ⇒ 不动", core("n/name", {"n", "name"}), "n/name"),
        ("🔴 找不到大小写折叠来源 ⇒ 不动", core("n/name", {"n"}, False), "n/name"),
        ("🔴 只剩 name 一项 ⇒ 不动（清空是另一种错）", core("name", {"n"}), "name"),
        ("多项里只摘 name", core("adj/n/name/v", {"adj", "n", "v"}), "adj/n/v"),
        # 🔴 `sue`：entry 层只有 adj，det/pron 是真读法 —— 本轮判据不许碰它
        ("🔴 非 name 的对不上 ⇒ 不动（sue 的 det/pron）",
         core("adj/det/pron", {"adj"}), "adj/det/pron"),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-40s → %r" % ("✅" if good else "🔴", name, got))
        if not good:
            print("        期望 %r" % (want,))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1

    rows = scan(ro)
    f = lambda x: format(x, ",")
    print("■ 要回收的 %s 行" % f(len(rows)))
    for (o, n, e), k in Counter((r[2], r[3], r[4]) for r in rows).most_common(10):
        print("   %-16s → %-14s 删 %-8s %s" % (o, n, e, f(k)))
    for wid, w, o, n, e in rows[:8]:
        print("   %-22s %s → %s" % (w[:22], o, n))
    if not a.apply or not rows:
        ro.close()
        if not a.apply:
            print("\n(未加 --apply，不写库)")
        return 0
    ro.close()
    with dbtool.session("drop-folded-pos", expect={"__rows__": 0}) as s:
        s.executemany("UPDATE dict SET pos=? WHERE id=?", [(n, wid) for wid, _, _, n, _ in rows])
    print("\n■ 已回收 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
