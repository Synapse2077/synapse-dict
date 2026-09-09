#!/usr/bin/env python3
"""**写死行数的断言**扫描闸 —— 2026-09-06 随 en 阶段 -2 建（拷自 de/pt）。

═══ 为什么 en 这一轮特别需要它 ═══
pt 的脚本从 fr 拷来改，fr 的断言里写死了 fr 的行数，移植当天咬了**三次**
（三次的数据都完全正确，红的全是断言）。

**en 是至今移植量最大的一次** —— 阶段 0 起要从 de/pt 整套拷 `build_v3_schema`、
`build_entry_layer`、`build_inflection_layer`、`harvest_*`、`verify_vs_dump` …
形状与 pt→de 那轮完全相同，所以这道闸第一天就挂上，不等它咬。

⚠️ **它同时是「en 数字必须重测」那条纪律的机械形式**：
   `EN_PLAN` 头部写着「所有 kaikki 侧的数字都来自老包，阶段 -1 必须重测」。
   写成文字的守不住（`[[lesson-must-become-mechanism]]`）——
   一旦有人把老包的数字写进断言，这道闸会当场报出来。

═══ 判据 ═══
在 `("名字", 实际值, 期望值)` 这类断言元组里，期望值不许是**大于阈值的整数字面量**。
期望值应该来自：另一条查询（问**不同的问题**，不是自证）／调用方写库前拍的快照／
0 或 1 这种真常量（"孤儿必须为 0" 永远不会过期）。

⚠️ **判据故意收窄**（`[[criteria-narrower-than-you-think]]`）：
   只看断言元组的**最后一项**，不扫全文的数字 —— 扫全文会把注释里的历史数字、
   DDL 里的长度限制全报出来，噪声淹没真信号。

用法（在 en/ 目录下）：
    python3 tests/test_no_literal_counts.py
    python3 tests/test_no_literal_counts.py --mutate   # 变异：造一条，闸必须报
    python3 tests/test_no_literal_counts.py --all      # 连历史脚本一起扫（见 SKIP_DIRS）
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                  # en/
MAX_LITERAL = 100

# 允许写死的场合：这些名字里的数字是**真常量**不是行数
ALLOW_NAME = ("阈值", "上限", "最多", "最少", "长度", "位数")

# 🔴🔴 **这里原本要跳过 `probes/` 与 `fixes/`（44 个 ECDICT 形状的历史脚本），
#      理由是"它们必然一堆改不动的红，而长期红着的闸等于没有闸"。
#      我把这个理由写完了才去量 —— 实测全量 53 个文件命中 0 条，前提根本不成立。**
#      （`[[measure-landing-not-source]]`：新数字先假设我的度量错了；
#        这里更基本 —— **先量再写理由，别先写理由再补量。**）
#   ⇒ 排除名单清空。多扫 44 个文件的代价是零，而少扫一个目录就是一个盲区。
#     `--all` 开关保留但已无差别，留着是为了万一将来真需要排除时有个入口。
SKIP_DIRS = set()


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


def _files(include_legacy=False):
    out = []
    for p in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        rel = p.relative_to(ROOT)
        if not include_legacy and rel.parts and rel.parts[0] in SKIP_DIRS:
            continue
        out.append(p)
    return out


def run(verbose=True, include_legacy=False):
    red = []
    files = _files(include_legacy)
    for p in files:
        for lineno, name, val in scan_file(p):
            red.append((p.relative_to(ROOT), lineno, name, val))
    if verbose:
        skipped = "" if (include_legacy or not SKIP_DIRS) \
            else "，跳过 %s" % "/".join(sorted(SKIP_DIRS))
        print("═══ 写死行数的断言（扫 %d 个文件%s）═══" % (len(files), skipped))
        for f, ln, name, val in red:
            print("   🔴 %s:%d  期望值写死成 %s" % (f, ln, f"{val:,}"))
            print("      断言：%s" % name[:70])
        print("\n   %s" % ("✅ 没有写死的行数断言" if not red
                           else "🔴 %d 条 —— 期望值要从数据算，不许写字面量" % len(red)))
    return red


def check_brief():
    return run(verbose=False)


def mutate():
    """⭐ 变异：造一条写死的断言，闸必须报出来。

    🔴 **一条永远通过的检查等于没检查**（de 阶段 7 逮到过两条恒真断言）——
       所以每条规则都要有一个"它确实会红"的反例。
    """
    print("═══ 变异验证 ═══")
    cases = [
        ('checks = [("孤儿 sense", q("x"), 0)]', False, "0 是真常量，不该报"),
        ('checks = [("义项总数", q("x"), 1738464)]', True, "写死老包义项数，必须报"),
        ('checks = [("词头数", q("x"), 1356506)]', True, "写死老包词头数，必须报"),
        ('checks = [("dict 行数", q("x"), 3929564 + 527000)]', True, "写死的加法，必须报"),
        ('checks = [("义项总数", q("x"), before["sense"])]', False, "从快照来，不该报"),
        ('checks = [("义项总数", q("x"), q("y"))]', False, "从另一条查询来，不该报"),
        ('checks = [("批大小上限", q("x"), 4096)]', False, "名字里有「上限」，豁免"),
    ]
    ok = 0
    for src, should_red, why in cases:
        got = bool(scan_file(Path("<mem>"), src))
        good = got == should_red
        ok += good
        print("   %s  %-42s %s" % ("✓" if good else "🔴 没逮住", why, src[:52]))
    print("\n   变异 %d/%d" % (ok, len(cases)))
    return ok == len(cases)


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(0 if mutate() else 1)
    sys.exit(1 if run(include_legacy="--all" in sys.argv) else 0)
