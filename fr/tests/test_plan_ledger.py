#!/usr/bin/env python3
"""**账的闸** —— 计划表和收尾单说的话，与库里的事实对不对得上。2026-08-27。

═══ 为什么会有这个文件 ═══
用户 2026-08-27：「你自己定的规矩，自己的经验教训，你自己为什么不执行呢」。

查这次会话自己的记录，结论很干净：

    守住了的   `think=False` 硬默认 / `DOUBAO_DISABLED` / `dbtool.session` /
               `slot_translate` 的落盘键唯一性检查        ← **全是机制**
    没守住的   `[[ship-dont-measure-in-circles]]` /
               `[[criteria-narrower-than-you-think]]` /
               `[[regex-alternation-order]]`              ← **全是文字**

不是态度差别：`think=False` 我根本不需要想起它。而"别在原地打转"这条，只在我
主动问"这件事该不该做"的时候才会响 —— 可我刚发现一个真缺陷的时候从来不问那个
问题，**发现本身感觉就是答案了**。

⇒ 所以这次不再往记忆里写"要记得 X"。写会自己响的东西。

═══ 这道闸拦的是**两个已经发生过的**具体失败 ═══

**P1 — 阶段表标着 ✅，交付物却是空的。**
   `docs/FR_PLAN.md` 的阶段表从 08-22 起没更新过。于是我打开计划**读不出还剩
   什么**，只能靠往下撞：阶段 8 之后的评审族已经做到第五个（A–E），而阶段 5 的
   **关系层（同义/反义/上下位/派生）0 条、频次层根本不存在**。
   这条闸把「完成的定义」变成可执行的：**声明做完了，就必须交得出东西。**

**P2 — 记账散落。**
   28 条 📋 散在本文件 2,965 行里，没有一处汇总；it 完结那天是**一处、5 条**
   （`[[it-plan-2026-08-12]]`）。我抄了 it 的阶段表、**没抄它的收尾单**。
   这条闸要求：收尾单之后不许再出现游离的 📋 —— 新记账只能进那张表。

⚠️ 本文件**不查数据质量**，那是 `test_no_regression.py` 的事。
   它查的是**我的账**。两者都由 `dbtool.session` 每次写库时跑。

用法：
    python3 tests/test_plan_ledger.py          # 明细
    python3 tests/test_plan_ledger.py --mutate # 变异验证：一条永远通过的检查等于没检查
"""
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths                                     # noqa: E402

PLAN = HERE.parent.parent / "docs" / "FR_PLAN.md"
SHEET = "# 📋 fr 收尾单"

# ⭐ **「完成的定义」就是这张表。** 阶段表里声明 ✅ 的阶段，必须在这里交得出东西。
#    🔴 判据写成「这一层非空」而不是「行数 ≥ 某个数」——
#      写死行数的断言必然过期（`[[fix-regression-and-gate]]`：旧闸 20 条红全是
#      断言过期不是数据错）。而「整层是不是 0」永远不会过期。
DELIVERABLE = {
    "0": [("v3 表结构", "SELECT COUNT(*) FROM sense_src")],
    "1": [("entry 词条层", "SELECT COUNT(*) FROM entry"),
          ("sense_src 证据层", "SELECT COUNT(*) FROM sense_src")],
    "1.5": [("法语原文释义", "SELECT COUNT(*) FROM sense_gloss WHERE lang='fr'"),
            ("中文释义", "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh'")],
    "2": [("inflection 变形层", "SELECT COUNT(*) FROM inflection")],
    "3": [("收词后的 dict", "SELECT COUNT(*) FROM dict")],
    "4": [("pronunciation 音标层", "SELECT COUNT(*) FROM pronunciation")],
    # 🔴 阶段 5 是本闸的头号案例：例句和搭配都做了，**关系和频次没做**，
    #    而阶段表当时标着未完成、实际另外几层已完成 —— 表里读不出任何一边。
    "5": [("example 例句层", "SELECT COUNT(*) FROM example"),
          ("collocation 搭配层", "SELECT COUNT(*) FROM collocation"),
          ("关系层（不含 alt_of —— 那是变形指针不是语义关系）",
           "SELECT COUNT(*) FROM sense_relation WHERE kind<>'alt_of'"),
          ("频次层", "SELECT COUNT(*) FROM pragma_table_info('dict') WHERE name='freq_zipf'")],
    "6": [("audio 录音元数据", "SELECT COUNT(*) FROM audio")],
    "7": [("回归闸", "SELECT 1")],          # 文件存在性单独查
    "8": [("展示层已切到音标表", "SELECT COUNT(*) FROM pronunciation WHERE is_primary=1")],
    # 🔴 原来写的是 `SELECT 1` —— **那是个永远为真的断言**，和 it 那轮的
    #    `return {ok:true}` 健康检查同一个毛病。阶段 9 真正的库侧交付物是
    #    搜索前缀预计算表（`fr/pipeline/build_search_prefix.py`，1 字符前缀 265ms→1ms）。
    "9": [("搜索前缀预计算表", "SELECT COUNT(*) FROM search_prefix")],
}

# 阶段表的行：`| **5** | **例句…** | **✅ 已完成** | 1 | … |`
ROW = re.compile(r"^\|\s*\**\s*(-?[0-9.]+)\s*\**\s*\|(.+?)\|(.+?)\|", re.M)


def declared_done():
    """→ {阶段号: 标题}，只含**工期栏声明 ✅** 的。"""
    s = PLAN.read_text(encoding="utf-8")
    i = s.index("## 三、阶段表")
    tbl = s[i:s.index("\n---", i)]
    out = {}
    for m in ROW.finditer(tbl):
        num, title, dur = m.group(1), m.group(2), m.group(3)
        if "✅" in dur:
            out[num] = title.strip().strip("*").strip()
    return out


def p1(con):
    """阶段表声明 ✅ 的阶段，交付物必须非空。"""
    bad = []
    for num, title in sorted(declared_done().items()):
        for what, sql in DELIVERABLE.get(num, []):
            try:
                n = con.execute(sql).fetchone()[0]
            except sqlite3.Error as e:
                bad.append(("P1", "阶段 %s 的交付物查不了：%s（%s）" % (num, what, e)))
                continue
            if not n:
                bad.append(("P1", "阶段 %s「%s」声明✅，但**%s 是 0**"
                            % (num, title[:22], what)))
    if not (HERE / "test_no_regression.py").exists() and "7" in declared_done():
        bad.append(("P1", "阶段 7 声明✅，但回归闸文件不存在"))
    return bad


def p2():
    """收尾单之后不许有游离的 📋 —— 新记账只能进那张表。"""
    s = PLAN.read_text(encoding="utf-8")
    if SHEET not in s:
        return [("P2", "收尾单章节不存在（%s）—— 记账没有家，必然重新散开" % SHEET)]
    tail = s[s.index(SHEET):]
    # 🔴 豁免只给**表格行**（`|`）与**引文**（`>`），以及收尾单自己那一行标题。
    #    第一版把所有 `#` 开头的行都豁免了 —— 我当天就自己走过这个洞：
    #    在收尾单后面写了个 `### 📋 记账：…` 的小节标题，闸一声不吭。
    #    豁免开得比它的理由宽，闸就等于不存在（`[[criteria-narrower-than-you-think]]`）。
    stray = [ln.strip() for ln in tail.splitlines()
             if "📋" in ln and not ln.startswith(SHEET)
             and not ln.lstrip().startswith(("|", ">"))]
    return [("P2", "收尾单之后有 %d 条游离记账（应进表）：%s"
             % (len(stray), stray[0][:60]))] if stray else []


def report(verbose=True):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        red = p1(con) + p2()
    finally:
        con.close()
    if verbose:
        print("═══ 账的闸（fr）：计划表与收尾单说的话，库里对不对得上 ═══")
        done = declared_done()
        print("   阶段表声明已完成：%s" % "、".join(sorted(done)))
        for cid, why in red:
            print("   🔴 %-4s %s" % (cid, why))
        print("\n   %s" % ("✅ 全部通过" if not red else "🔴 %d 条要看" % len(red)))
    return red


def check_brief():
    """给 `dbtool` 挂钩用：静默跑，只回报红的。"""
    return report(verbose=False)


def mutate():
    """⭐ 变异验证：把闸该逮的东西造出来，看它红不红。
    `[[dbtool-and-golden-tests]]`：写完测试要变异验证，否则可能是一条永远绿的检查。
    """
    ok = 0
    src = PLAN.read_text(encoding="utf-8")

    # M1：把一个**交付物确实是 0** 的阶段，在文档里改成声明 ✅ —— P1 必须红。
    # 🔴 第一版这条是"看看现有状态红不红"，当前阶段 5 没声明 ✅ 于是走了
    #    "本来就不该红"的分支、记 1 分 —— **等于没验**，正是本文件开头说的
    #    "一条永远通过的检查等于没检查"。必须真的改文档、真的看它红。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    empty = [(n, w) for n, ds in DELIVERABLE.items() for w, q in ds
             if _safe(con, q) == 0]
    con.close()
    if not empty:
        # 🔴 所有交付物都非空之后要走这条兜底分支。第一版塞的假阶段号是 `__x__`，
        #    **不匹配阶段表的数字正则** `^\|\s*\**\s*(-?[0-9.]+)` ⇒ `declared_done()`
        #    根本读不到它，变异造不出来、白记一分 —— 与 M1 第一版同一个毛病：
        #    **变异本身要先验证它真的变异了**。改用数字号 `99`。
        print("   M1 —— 当前没有任何交付物是 0；改用**假阶段 99** 造变异")
        empty = [("99", "不存在的交付物")]
        DELIVERABLE["99"] = [("不存在的交付物", "SELECT 0")]
        mut = src.replace("| **2** |",
                          "| **99** | 假阶段（变异用） | **✅ 已完成** | — | — |\n| **2** |", 1)
    else:
        n, _w = empty[0]
        # 把该阶段那一行的工期栏换成 ✅
        mut = re.sub(r"(^\|\s*\**\s*%s\s*\**\s*\|[^|]*\|)[^|]*\|" % re.escape(n),
                     r"\1 **✅ 已完成** |", src, count=1, flags=re.M)
    try:
        PLAN.write_text(mut, encoding="utf-8")
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        got = [r for r in p1(con) if ("阶段 %s" % empty[0][0]) in r[1]]
        con.close()
        print("   M1 %s（阶段 %s「%s」是 0）"
              % ("✅ 逮到" if got else "🔴 **漏了**：声明✅ 而交付物是 0，闸没红",
                 empty[0][0], empty[0][1][:30]))
        ok += bool(got)
    finally:
        PLAN.write_text(src, encoding="utf-8")
        DELIVERABLE.pop("99", None)

    # M2：在收尾单后面塞一条游离 📋 —— P2 必须红
    try:
        PLAN.write_text(src + "\n📋 变异用的游离记账，马上删。\n", encoding="utf-8")
        print("   M2 %s" % ("✅ 逮到游离记账" if p2() else "🔴 **漏了**：游离 📋 没红"))
        ok += bool(p2())
    finally:
        PLAN.write_text(src, encoding="utf-8")

    # M3：删掉收尾单标题 —— P2 必须红
    try:
        PLAN.write_text(src.replace(SHEET, "# 无关标题"), encoding="utf-8")
        print("   M3 %s" % ("✅ 逮到收尾单消失" if p2() else "🔴 **漏了**：收尾单没了却不红"))
        ok += bool(p2())
    finally:
        PLAN.write_text(src, encoding="utf-8")
    print("\n   变异 %d/3" % ok)
    return ok


def _safe(con, q):
    try:
        return con.execute(q).fetchone()[0]
    except sqlite3.Error:
        return -1


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(0 if mutate() == 3 else 1)
    sys.exit(1 if report() else 0)
