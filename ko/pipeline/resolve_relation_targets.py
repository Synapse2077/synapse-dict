#!/usr/bin/env python3
"""给关系边补一列 `target_norm`：**这条边到底指向库里哪一页**。ko，2026-09-25（阶段 9）。

═══ 怎么发现的 ═══
写 `App.tsx` 之前先量「关系词点下去有没有东西」，实测 **34.6% 是死链**。
逐条读样本，发现死链里混着三种**根本不是"库里没这个词"**的东西：

    ^팔도          ← `^` 是 wiktextract 的**专名标记**，不是词的一部分
    경마(競馬)      ← 谚文词 ＋ **汉字注**，我们的词头是 `경마`
    령/영          ← 두음법칙（头音法则）的南北两读，**两支都是真词**

⭐ **逮到它的不是闸，是准备渲染时去量落点。**
   `[[measure-landing-not-source]]`：源头那格写着 `^팔도`，收割器原样收进来 ——
   两边恒等、闸全绿，而读者点下去是空白页。

═══ 为什么加一列，而不是把 `target` 改掉 ═══
🔴 括号里的汉字**是给读者看的信息**：`부인(婦人)` 与 `부인(否認)` 是两个词，
   把 target 就地改成 `부인` 就把这个区别抹掉了。
⇒ `target` 一个字不动（展示原文），`target_norm` 只回答「链接落到哪一页」。
   `[[prefer-reversible-designs]]`：加列可逆，就地改写不可逆。

═══ 判据（**阶梯式**：上一级查不到才走下一级）═══
  ① NFC(target) 直接在 `dict.word_norm` 里 —— 65.39%
  ② 去掉开头的 `^` 专名标记 ——（实测 `dict.word_norm` 含 `^` 的是 **0** 行，
     所以剥掉它不可能剥掉真词的一部分）
  ③ 去掉括号注 —— 再捞回 **3.39%**
  ④ 查不到 ⇒ `target_norm` 留 **NULL**，展示层据此印成纯文本、不做链接

🔴 **`령/영` 这种斜杠形有意不解析**（233 条）。两支都在库里，挑哪一支都是
   我们替源头做的断言，而源头没说。`[[dont-gate-facts-on-my-uncertainty]]` 的反面
   用法：不确定的时候不要**静默**挑一个，要让它显式地留白。

═══ 判据验过没有（`[[validate-criterion-where-source-is-right]]`）═══
拿**独立信号**验 ③：括号里的汉字 vs 目标词条**已知的**汉字（`entry.hanja`
＋ `hanja_spelling`/`alt_hanja` 边）。有汉字可比的 5,286 组里：

    一致 4,439 / 不一致 847  ⇒ 83.98%

🔴 逐条读过那 847 条，**没有一条是解析错了**，全是这两族：
    · 异体字/简繁：`癡漢/痴漢`、`郞君`↔`郎君`、`障碍人`↔`障礙人`、`结晶水`
    · **同形异义**：`부인` ＝ 婦人 / 否認 / 夫人 三个词共用一个谚文拼写
🔴🔴 第二族正是 `[[schema-redesign-doc]]` 记的那句核心判断 ——
   **谚文那一页是一个"词形"，不是一个"词"**。`부인(婦人)` 落到 `부인` 页是对的
   （我们只有词形级的页），但读者到了那一页得自己认哪个义项。
   ⇒ 这不是本步要修的东西，本步只保证**链接不空**；
     那笔账是 K20，`target` 原文保留是它将来能修的前提。

═══ 关系边里有一族**本来就不该是链接** ═══
`hanja_spelling` 51,254 条里 43,547 条"死链" —— 因为目标是 `換面相訟` 这种
**多字汉字串**，我们的词头里根本没有（只有 10,172 个单字汉字条目）。
那不是缺陷：汉字表记是**注**不是**词**。⇒ 展示层对
`hanja_spelling` / `alt_hanja` 印注、不印链接（`korean.ts` ⑥）。

跑（在仓库根）：
    python3 -u ko/pipeline/resolve_relation_targets.py
    python3 -u ko/pipeline/resolve_relation_targets.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import re
import sqlite3
import unicodedata as ud

import dbtool
import paths

f = lambda n: format(n, ",")

PAREN = re.compile(r"\([^()]*\)")
# 汉字族：目标是**注**不是词，不参与死链统计
ANNOTATION_KINDS = {"hanja_spelling", "alt_hanja"}


def nfc(s):
    return ud.normalize("NFC", s)


def resolve(target, have):
    """阶梯式解析。返回 (词形 或 None, 走到第几级)。"""
    n = nfc((target or "").strip())
    if n in have:
        return n, "直接命中"
    s = n.lstrip("^").strip()
    if s != n and s in have:
        return s, "去专名标记"
    t = PAREN.sub("", s).strip()
    if t != s and t in have:
        return t, "去括号注"
    return None, "未解析"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {r[0] for r in con.execute("SELECT word_norm FROM dict")}
    # 🔴 `^` 剥掉之前先证明它不可能是真词的一部分
    n_caret = con.execute(
        "SELECT COUNT(*) FROM dict WHERE word_norm LIKE '%^%'").fetchone()[0]
    print("■ 前提：`dict.word_norm` 里含 `^` 的行 %s %s"
          % (f(n_caret), "✅" if n_caret == 0 else "🔴 剥 ^ 的判据不成立，停"))
    if n_caret:
        raise SystemExit("🔴 有词头带 `^`，不能无条件剥")

    rows = con.execute(
        "SELECT id, kind, target FROM sense_relation "
        "WHERE COALESCE(hidden,0) = 0").fetchall()
    n_col_before = con.execute(
        "SELECT COUNT(*) FROM pragma_table_info('sense_relation')"
        " WHERE name='target_norm'").fetchone()[0]
    con.close()

    by_step = collections.Counter()
    dead_by_kind = collections.Counter()
    seen_by_kind = collections.Counter()
    out = []
    for rid, kind, target in rows:
        w, step = resolve(target, have)
        by_step[step] += 1
        seen_by_kind[kind] += 1
        if w is None:
            dead_by_kind[kind] += 1
        out.append((w, rid))

    tot = len(rows)
    print("\n■ 可见关系边 %s" % f(tot))
    for step in ("直接命中", "去专名标记", "去括号注", "未解析"):
        print("   %-8s %8s  (%5.2f%%)"
              % (step, f(by_step[step]), 100.0 * by_step[step] / tot))
    live = tot - by_step["未解析"]
    print("   ── 能链上的合计 %s  (%.2f%%)" % (f(live), 100.0 * live / tot))

    # 🔴 读者口径：汉字注那一族**本来就不是链接**，不该计进死链
    ann = sum(v for k, v in seen_by_kind.items() if k in ANNOTATION_KINDS)
    ann_dead = sum(v for k, v in dead_by_kind.items() if k in ANNOTATION_KINDS)
    link_tot = tot - ann
    link_dead = by_step["未解析"] - ann_dead
    print("\n■ 读者口径（排掉 `%s` —— 它们是注不是链接）"
          % "` / `".join(sorted(ANNOTATION_KINDS)))
    print("   当链接渲染的边 %s，其中点下去是空的 %s  (%.2f%%)"
          % (f(link_tot), f(link_dead), 100.0 * link_dead / link_tot))

    print("\n■ 未解析按 kind（前 10）")
    for k, n in dead_by_kind.most_common(10):
        tag = "（注，不是链接）" if k in ANNOTATION_KINDS else ""
        print("   %-18s %6s / %6s  %s" % (k, f(n), f(seen_by_kind[k]), tag))

    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-resolve-relation-target-norm",
            expect={"sense_relation.target_norm": live},
            invalidates=[]) as s:
        if not n_col_before:
            s.execute("ALTER TABLE sense_relation ADD COLUMN target_norm TEXT")
        s.executemany(
            "UPDATE sense_relation SET target_norm=? WHERE id=?", out)
        s.execute("CREATE INDEX IF NOT EXISTS idx_srel_target_norm"
                  " ON sense_relation(target_norm)")

    print("\n═══ 写后回核（从库里重算，不复用上面的变量）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("有 target_norm 的边", q(
            "SELECT COUNT(*) FROM sense_relation"
            " WHERE COALESCE(hidden,0)=0 AND target_norm IS NOT NULL"), live),
        # 🔴 反向：**每一个** target_norm 都必须真的在 dict 里
        ("target_norm 指不到词头的", q(
            "SELECT COUNT(*) FROM sense_relation r WHERE r.target_norm IS NOT NULL"
            " AND NOT EXISTS(SELECT 1 FROM dict d WHERE d.word_norm=r.target_norm)"), 0),
        # 🔴 `target` 一个字都没动（这是本步的核心承诺）
        ("target 含 `^` 的（原文应原样保留）", q(
            "SELECT COUNT(*) FROM sense_relation WHERE target LIKE '%^%'"), 291),
        # 🔴 隐藏边不该被解析（作用域闸）
        ("隐藏边被写了 target_norm 的", q(
            "SELECT COUNT(*) FROM sense_relation"
            " WHERE hidden=1 AND target_norm IS NOT NULL"), 0),
        ("斜杠形被静默挑了一支的", q(
            "SELECT COUNT(*) FROM sense_relation WHERE target LIKE '%/%'"
            " AND target NOT LIKE '%(%' AND target_norm IS NOT NULL"
            " AND target_norm <> target"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-34s %9s（期望 %s）"
              % ("✅" if good else "🔴", name, f(got), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
