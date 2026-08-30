#!/usr/bin/env python3
"""阶段 0 前置清洗：搭配行的**分隔符**归一，让迁移 100% 可逆。2026-08-29。

═══ 为什么需要这一步 ═══
阶段 0 的可逆性回核（`build_v3_schema.py` 闸①）逮到 **2 行**：

    原: 'paquera casual  casual调情'      ← 分隔处两个空格
    建: 'paquera casual casual调情'       ← 重建成一个

`split_colloc` 两边都 `.strip()`、重建时用单空格拼回 ⇒ 这 2 行搬进新表后**搬不回来**。
15,369 行里只有这 2 行。

═══ 为什么不是"记账放着" ═══
可逆性回核的**全部价值**在于它是 100%、非抽样 —— 它把「义项和释义有没有配错」
从抽样问题变成**可判定**问题（`[[verification-gates-not-sampling]]`，用户 2026-08-07：
「不要把义项和释义错配了，那才是真灾难」）。
留 2 行不可逆，这道闸就从"可判定"降级成"99.99%"，以后每次报红都要先想"是不是那 2 行"。

═══ 为什么不是"加一列存原始分隔符" ═══
为 2 行给 `collocation` 表加一列是过度设计，而且那一列此后永远要维护。

═══ 🔴 判据是语义的不是形式的 ═══
不写「含连续空格的行」（那是**形式代理**，`[[criteria-from-meaning-not-form]]`：
我写「不是长句翻译」，模型把 `Saint-Léger (Charente).` 压成「圣莱热」，坏掉 1,528 条）。
判据直接就是我们真正在意的那件事：

    **这一行按 `split_colloc` 拆开、再拼回去，等不等于原串。**

不等 ⇒ 修；等 ⇒ 一个字节都不碰。这条判据与闸①用的是**同一个函数**（import 来的，
不手抄），所以不存在"判据两份、闸在报自己的 bug"（`[[fix-regression-and-gate]]` 第三种机制）。

⚠️ 本步**只改分隔符不改内容**：拆出来的葡语部分和中文部分逐字节不变，
   变的只有它们之间的空白。改完 `collocation` 列的非空行数不变（13,551），
   所以 `dbtool` 的 expect 里它是 0 —— 未声明即必须为 0，闸自己会拦。

用法（在 pt/ 目录下）：
    python3 fixes/fix_colloc_separator.py            # 只看要改哪些行
    python3 fixes/fix_colloc_separator.py --apply    # 走 dbtool 闸门写库
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool                                        # noqa: E402
import paths                                         # noqa: E402
# 🔴 判据只许一份：直接 import 闸用的那个函数，不手抄
#    （`[[regex-alternation-order]]`：抽了常量却在另一文件又手抄一份窄的，坏了 43 条）
from pipeline.build_v3_schema import split_colloc    # noqa: E402


def roundtrip(ln):
    """按 `split_colloc` 拆开再拼回 —— 与闸①的重建逻辑逐字一致。"""
    a, b = split_colloc(ln)
    if a is None:                       # 切不出葡语部分：原样搬，本来就可逆
        return ln
    return a + (" " + b if b else "")


def find(con):
    """→ [(dict.id, word, 原 collocation, 新 collocation, [(原行, 新行)…])]"""
    out = []
    for rid, w, c in con.execute(
            "SELECT id, word, collocation FROM dict "
            "WHERE collocation IS NOT NULL AND collocation<>'' ORDER BY id"):
        new_lines, changed = [], []
        for ln in c.split("\n"):
            if not ln.strip():
                new_lines.append(ln)
                continue
            rt = roundtrip(ln)
            new_lines.append(rt)
            if rt != ln:
                changed.append((ln, rt))
        if changed:
            out.append((rid, w, c, "\n".join(new_lines), changed))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = find(con)
    con.close()

    print("■ 需要归一分隔符的行：%d 条（分布在 %d 个词条）" % (
        sum(len(x[4]) for x in todo), len(todo)))
    for rid, w, _, _, changed in todo:
        for old, new in changed:
            print("   id=%-8s %-22s" % (rid, w))
            print("      原 %r" % old)
            print("      新 %r" % new)
    if not todo:
        print("✓ 没有要改的 —— 迁移已经 100% 可逆")
        return 0
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    # 🔴 `collocation` 列的**非空行数不变**（只改内容不改有无）⇒ expect 里它是 0。
    #    未声明即必须为 0，所以这里连写都不用写 —— 闸自己会拦住"改到了别的列"。
    plan = [(new, rid) for rid, _, _, new, _ in todo]
    with dbtool.session("colloc-separator", expect={}) as s:
        s.executemany("UPDATE dict SET collocation=? WHERE id=?", plan)

    # 抽样反验：不变量只能证明"没改到不该改的范围"，证明不了"改对了内容"
    dbtool.sample_check(
        [(w, changed[0][0], changed[0][1]) for _, w, _, _, changed in todo],
        n=len(todo), cols=("词", "改前", "改后"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
