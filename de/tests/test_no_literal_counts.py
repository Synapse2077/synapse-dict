#!/usr/bin/env python3
"""**写死行数的断言**扫描闸 —— 2026-08-31 随 de 阶段 -2 建（拷自 pt）。

═══ 为什么有这个文件 ═══
pt 的脚本是从 fr 拷过来改的。fr 的断言里写死了 fr 的行数，
移植当天这条坑咬了**三次**（de 这一轮从 pt 拷，形状完全相同 ⇒ 这道闸第一天就挂上，
不等它咬）：

    build_entry_layer.py   「无 sense_src 的 sense == 58」      pt 真值 21
    recover_alt_of.py      同一条，第二个文件里又抄了一遍          pt 真值 21
    split_case_folded.py   dict 行数 388,992 / 义项 124,766 /
                           变形 331,377                        三条全是 fr 的数

三次的数据都是**完全正确**的，红的全是断言。这正是 `[[fix-regression-and-gate]]`
记的那条：**闸红了先问「数据错了还是断言过期」** —— 而且

    **写死行数的断言必然过期；跨语种移植更是必然错。**

一条一条改不解决问题（改完下一份移植脚本还带着）。⇒ 写一个会自己响的。

═══ 判据 ═══
在 `checks = [...]` 这类断言列表里，期望值不许是**大于阈值的整数字面量**。
期望值应该来自：
  · 另一条查询（问**不同的问题**，不是自证），或
  · 调用方写库前拍的快照，或
  · 0 / 1 这种真正的常量（"孤儿必须为 0" 永远不会过期）

⚠️ **判据故意收窄**（`[[criteria-narrower-than-you-think]]`）：
   只看**断言元组的最后一项**（`("名字", 实际值, 期望值)`），不扫全文的数字 ——
   扫全文会把注释里的历史数字、DDL 里的长度限制全报出来，噪声淹没真信号。
   阈值 `MAX_LITERAL = 100`：0/1/2 这种是真常量；三位数以上基本都是行数。

用法（在 de/ 目录下）：
    python3 tests/test_no_literal_counts.py
    python3 tests/test_no_literal_counts.py --mutate   # 变异：造一条，闸必须报
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                  # de/
MAX_LITERAL = 100

# 允许写死的场合：这些名字里的数字是**真常量**不是行数
ALLOW_NAME = ("阈值", "上限", "最多", "最少", "长度", "位数")


def scan_file(path, src=None):
    """→ [(行号, 断言名, 字面量)]"""
    src = src if src is not None else path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [(getattr(e, "lineno", 0), "🔴 语法错误，扫不了", -1)]
    bad = []
    for node in ast.walk(tree):
        # 断言元组的形状：("名字", 实际值表达式, 期望值)
        if not isinstance(node, ast.Tuple) or len(node.elts) != 3:
            continue
        name, _got, want = node.elts
        if not isinstance(name, ast.Constant) or not isinstance(name.value, str):
            continue
        # 期望值必须是**裸的整数字面量**才算违规；表达式（含算术、函数调用）都放行
        if isinstance(want, ast.Constant) and isinstance(want.value, int):
            if abs(want.value) > MAX_LITERAL and not any(k in name.value for k in ALLOW_NAME):
                bad.append((node.lineno, name.value, want.value))
        # `a + b` 形式里如果两边都是大字面量（fr 那条 `385216 + 3776`），同样违规
        elif isinstance(want, ast.BinOp):
            nums = [n.value for n in ast.walk(want)
                    if isinstance(n, ast.Constant) and isinstance(n.value, int)]
            if nums and all(abs(v) > MAX_LITERAL for v in nums):
                bad.append((node.lineno, name.value, sum(nums)))
    return bad


def run(verbose=True):
    red = []
    files = sorted(p for p in ROOT.rglob("*.py") if "__pycache__" not in str(p))
    for p in files:
        for lineno, name, val in scan_file(p):
            red.append((p.relative_to(ROOT), lineno, name, val))
    if verbose:
        print("═══ 写死行数的断言（扫 %d 个文件）═══" % len(files))
        for f, ln, name, val in red:
            print("   🔴 %s:%d  期望值写死成 %s" % (f, ln, f"{val:,}"))
            print("      断言：%s" % name[:70])
        print("\n   %s" % ("✅ 没有写死的行数断言" if not red
                           else "🔴 %d 条 —— 期望值要从数据算，不许写字面量" % len(red)))
    return red


def check_brief():
    return run(verbose=False)


def mutate():
    """⭐ 变异：造一条写死的断言，闸必须报出来。"""
    print("═══ 变异验证 ═══")
    cases = [
        ('checks = [("孤儿 sense", q("x"), 0)]', False, "0 是真常量，不该报"),
        ('checks = [("义项总数", q("x"), 124766)]', True, "写死 124,766，必须报"),
        ('checks = [("dict 行数", q("x"), 385216 + 3776)]', True, "写死的加法，必须报"),
        ('checks = [("义项总数", q("x"), before["sense"])]', False, "从快照来，不该报"),
        ('checks = [("批大小上限", q("x"), 4096)]', False, "名字里有「上限」，豁免"),
    ]
    ok = 0
    for src, should_red, why in cases:
        got = bool(scan_file(Path("<mem>"), src))
        good = got == should_red
        ok += good
        print("   %s  %-46s %s" % ("✓" if good else "🔴 没逮住", why, src[:48]))
    print("\n   变异 %d/%d" % (ok, len(cases)))
    return ok == len(cases)


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(0 if mutate() else 1)
    sys.exit(1 if run() else 0)
