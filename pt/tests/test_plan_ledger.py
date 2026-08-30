#!/usr/bin/env python3
"""**账的闸** —— `docs/PT_PLAN.md` 说的话，与库和代码对不对得上。2026-08-29 随 pt 阶段 -2 建。

═══ 为什么 pt 一开工就有这个文件 ═══
fr 是做到第七天、被用户问「你自己定的规矩自己为什么不执行」之后才建的。
查那次会话的记录，结论很干净：

    守住了的   `think=False` 硬默认 / `DOUBAO_DISABLED` / `dbtool` 的 expect 闸  ← **全是机制**
    没守住的   「别在原地打转」「判据要收窄」「正则选择支按长度排」            ← **全是文字**

不是态度差别：`think=False` 我根本不需要想起它；而「别在原地打转」只在我主动问
"这件事该不该做"的时候才响 —— 可我刚发现一个真缺陷的时候从来不问那个问题，
**发现本身感觉就是答案了**。

⇒ 所以 pt 不等到第七天。阶段 -2 就把它建出来。

═══ 这道闸拦的两件事（都是 fr 上真发生过的）═══

**P1 —— 阶段表标着 ✅，交付物却是空的。**
   fr 的阶段表从 08-22 起没更新过，于是打开计划读不出还剩什么：阶段 8 之后的评审族
   已经做到第五个，而阶段 5 的**关系层 0 条、频次层根本不存在**。
   这条闸把「完成的定义」变成可执行的：**声明做完了，就必须交得出东西。**

**P2 —— 记账散落。**
   fr 的 28 条 📋 散在 2,965 行里没有一处汇总。收尾单之后不许再出现游离的 📋。

🔴 **交付物的判据不许写成永远为真的断言。** fr 第一版把阶段 7 写成 `SELECT 1`、
   阶段 9 也写成 `SELECT 1` —— 和 it 那轮 `return {ok:true}` 的健康检查同一个毛病，
   是这道闸自己逮出来的。所以本文件把交付物分成三类，每一类都得**真的能红**：

     DELIVERABLE  库里那一层非空吗          （SQL）
     FILES        那个闸的文件真的存在吗      （路径）
     CODE         代码里真的接上了吗          （文件里必须出现某个串）

⚠️ 本文件**不查数据质量**，那是 `tests/test_no_regression.py` 的事（阶段 7 建）。
   它查的是**账**。两者都由 `dbtool.session` 每次写库时跑。

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

ROOT = HERE.parent.parent
PLAN = ROOT / "docs" / "PT_PLAN.md"
SHEET = "# 📋 pt 收尾单"

# ⭐ **「完成的定义」就是这三张表。** 阶段表里声明 ✅ 的阶段，必须在这里交得出东西。
#    🔴 判据写成「这一层非空」而不是「行数 ≥ 某个数」——
#      写死行数的断言必然过期（`[[fix-regression-and-gate]]`：fr 旧闸 20 条红
#      全是断言过期不是数据错）。而「整层是不是 0」永远不会过期。
DELIVERABLE = {
    # 🔴 2026-08-29 改对：fr 那份把阶段 0 的交付物写成 `sense_src` 非空，
    #    但 **`sense_src` 是阶段 1 才填的**（阶段 0 只建空表 + 搬义项）。
    #    fr 上没暴露，因为它阶段 0 和阶段 1 是同一天做完的 —— 闸从没在中间那一刻跑过。
    #    ⇒ 阶段 0 真正的交付物是「表建成 + `dict` 的内容列搬进来了」。
    "0": [("sense 出版层", "SELECT COUNT(*) FROM sense"),
          ("sense_gloss 释义", "SELECT COUNT(*) FROM sense_gloss"),
          ("collocation 搭配", "SELECT COUNT(*) FROM collocation"),
          ("十一张表都建了",
           "SELECT (SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
           "('sense_src','sense','sense_gloss','sense_tag','sense_relation','pronunciation',"
           "'example','example_gloss','collocation','collocation_gloss','audio'))=11")],
    "1": [("entry 词条层", "SELECT COUNT(*) FROM entry"),
          ("sense_src 证据层", "SELECT COUNT(*) FROM sense_src")],
    "1.5": [("葡语原文释义", "SELECT COUNT(*) FROM sense_gloss WHERE lang='pt'"),
            ("中文释义", "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh'")],
    "2": [("inflection 变形层", "SELECT COUNT(*) FROM inflection")],
    # 🔴 判据不能写「inflection 非空」——阶段 2b 已经让它非空了，那条断言对 2c 永远为真。
    #    2c 交付的是**阶段 3 新收的变形接回了词元**，那批链接的 `src` 一定不是 en-edition
    #    （2b 只读英文版 `form_of`）⇒ 「非 en-edition 的变形链非空」是它独有的、且永不过期。
    "2c": [("阶段 3 新收变形的链接（src 非 en-edition）",
            "SELECT COUNT(*) FROM inflection WHERE src<>'en-edition'")],
    "3": [("收词后的 dict", "SELECT COUNT(*) FROM dict")],
    # ⚠️ pt 是**双读音**语言。这里只断言「音标层非空」，收紧成「巴葡和欧葡都非空」
    #    要等阶段 4 把表结构定下来 —— 已记进收尾单 C3，不留在注释里烂掉。
    "4": [("pronunciation 音标层", "SELECT COUNT(*) FROM pronunciation")],
    # 🔴 阶段 5 是这道闸在 fr 上的头号案例：例句和搭配都做了，**关系和频次没做**，
    #    而阶段表读不出任何一边。四层各查一次，缺一层就红。
    "5": [("example 例句层", "SELECT COUNT(*) FROM example"),
          ("collocation 搭配层", "SELECT COUNT(*) FROM collocation"),
          ("关系层（不含 alt_of —— 那是变形指针不是语义关系）",
           "SELECT COUNT(*) FROM sense_relation WHERE kind<>'alt_of'"),
          ("频次层", "SELECT COUNT(*) FROM pragma_table_info('dict') WHERE name='freq_zipf'")],
    "6": [("audio 录音元数据", "SELECT COUNT(*) FROM audio")],
    "9": [("搜索前缀预计算表", "SELECT COUNT(*) FROM search_prefix")],
}

# 阶段 7 的交付物是**两道闸的文件**，不是库里的行。
# 🔴 fr 那版把它写成 `SELECT 1` —— 永远为真，等于没查。
FILES = {
    "-1": [("取数表与字段归属", "docs/lang/pt-CONVENTIONS.md"),
           ("逐源实测存档", "data/work/pt/probe/count_slices_20260829.txt"),
           ("音标落点存档", "data/work/pt/probe/ipa_landing_20260829.txt"),
           ("词汇残差存档", "data/work/pt/probe/residual_v2_20260829.txt")],
    "-2": [("写库闸门", "pt/dbtool.py"),
           ("账的闸（本文件）", "pt/tests/test_plan_ledger.py"),
           ("备份保留策略的行为测试", "pt/tests/test_prune_backups.py")],
    "7": [("回归闸", "pt/tests/test_no_regression.py"),
          ("契约闸", "apps/web/src/contract-check-pt.tsx")],
}

# 阶段 8 的交付物是**展示层真的改了读取路径**。
# 🔴 判据来自 `[[it-display-layer-stage8]]` 与 2026-08-29 fr 上的复发：
#    数据层全绿、库里查得到，而 `french.ts` 里 `FROM audio` 出现 **0 次**
#    ⇒ 39 万条录音一个用户都看不见。**"落库成功"证明不了"到达用户"。**
#    老单表版的 `portuguese.ts` 只有 `FROM dict`；切到 v3 之后必然出现 `FROM sense`。
CODE = {
    "8": [("展示层已切到多表（不再只查 dict）",
           "packages/dict-core/src/portuguese.ts", "FROM sense")],
}

# 阶段表的行：`| **5** | **例句…** | **✅ 已完成** | 1 | … |`
# ⚠️ 阶段号可以带字母后缀（`2c`）。fr 没有过这种编号，照抄来的正则只认数字，
#    结果是**带字母的阶段声明 ✅ 也不会被查** —— 闸静默漏掉一整个阶段。
ROW = re.compile(r"^\|\s*\**\s*(-?[0-9.]+[a-z]?)\s*\**\s*\|(.+?)\|(.+?)\|", re.M)


def declared_done():
    """→ {阶段号: 标题}，只含**状态栏声明 ✅** 的。"""
    s = PLAN.read_text(encoding="utf-8")
    i = s.index("## 二、阶段表")
    tbl = s[i:s.index("\n---", i)]
    out = {}
    for m in ROW.finditer(tbl):
        num, title, state = m.group(1), m.group(2), m.group(3)
        if "✅" in state:
            out[num] = title.strip().strip("*").strip()
    return out


def p1(con):
    """阶段表声明 ✅ 的阶段，交付物必须真的在。"""
    bad = []
    done = declared_done()
    for num, title in sorted(done.items()):
        for what, sql in DELIVERABLE.get(num, []):
            try:
                n = con.execute(sql).fetchone()[0]
            except sqlite3.Error as e:
                bad.append(("P1", "阶段 %s 的交付物查不了：%s（%s）" % (num, what, e)))
                continue
            if not n:
                bad.append(("P1", "阶段 %s「%s」声明✅，但**%s 是 0**"
                            % (num, title[:22], what)))
        for what, rel in FILES.get(num, []):
            if not (ROOT / rel).exists():
                bad.append(("P1", "阶段 %s「%s」声明✅，但**%s 不存在**（%s）"
                            % (num, title[:22], what, rel)))
        for what, rel, need in CODE.get(num, []):
            p = ROOT / rel
            if not p.exists():
                bad.append(("P1", "阶段 %s 声明✅，但 %s 不存在" % (num, rel)))
            elif need not in p.read_text(encoding="utf-8"):
                bad.append(("P1", "阶段 %s「%s」声明✅，但 %s 里找不到 `%s`"
                            % (num, what, rel, need)))
    return bad


def p2():
    """收尾单之后不许有游离的 📋 —— 新记账只能进那张表。"""
    s = PLAN.read_text(encoding="utf-8")
    if SHEET not in s:
        return [("P2", "收尾单章节不存在（%s）—— 记账没有家，必然重新散开" % SHEET)]
    tail = s[s.index(SHEET):]
    # 🔴 豁免只给**表格行**（`|`）与**引文**（`>`），以及收尾单自己那一行标题。
    #    fr 第一版把所有 `#` 开头的行都豁免了，当天就自己走过这个洞：
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
        print("═══ 账的闸（pt）：计划表说的话，库与代码对不对得上 ═══")
        done = declared_done()
        print("   阶段表声明已完成：%s" % ("、".join(sorted(done)) if done else "（无，尚未开工）"))
        for cid, why in red:
            print("   🔴 %-4s %s" % (cid, why))
        print("\n   %s" % ("✅ 全部通过" if not red else "🔴 %d 条要看" % len(red)))
    return red


def check_brief():
    """给 `dbtool` 挂钩用：静默跑，只回报红的。"""
    return report(verbose=False)


def _safe(con, q):
    try:
        return con.execute(q).fetchone()[0]
    except sqlite3.Error:
        return -1


def mutate():
    """⭐ 变异验证：把闸该逮的东西造出来，看它红不红。
    `[[dbtool-and-golden-tests]]`：写完测试要变异验证，否则可能是一条永远绿的检查。

    🔴 fr 那版的 M1 第一版是"看看现有状态红不红"，而当时那个阶段本来就没声明 ✅，
       于是走了"本来就不该红"的分支、白记一分 —— **等于没验**。
       必须真的改文档、真的看它红。
    """
    ok = 0
    src = PLAN.read_text(encoding="utf-8")

    def with_plan(text, fn):
        try:
            PLAN.write_text(text, encoding="utf-8")
            return fn()
        finally:
            PLAN.write_text(src, encoding="utf-8")

    def declare(num, extra_row=None):
        """把阶段 num 那一行的状态栏改成 ✅（没有这一行就插一条假的）。"""
        if extra_row:
            return src.replace("| **-2** |", extra_row + "\n| **-2** |", 1)
        return re.sub(r"(^\|\s*\**\s*%s\s*\**\s*\|[^|]*\|)[^|]*\|" % re.escape(num),
                      r"\1 **✅ 已完成** |", src, count=1, flags=re.M)

    # M1：库侧交付物是 0 的阶段，声明 ✅ —— P1 必须红
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    empty = [n for n, ds in DELIVERABLE.items() for w, q in ds if _safe(con, q) <= 0]
    con.close()
    num = empty[0]

    def _m1():
        con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        got = [r for r in p1(con2) if ("阶段 %s" % num) in r[1]]
        con2.close()
        return got
    got = with_plan(declare(num), _m1)
    print("   M1 %s（阶段 %s 的库侧交付物是 0）"
          % ("✅ 逮到" if got else "🔴 **漏了**：声明✅ 而交付物是 0，闸没红", num))
    ok += bool(got)

    # M6：**带字母后缀的阶段号**（`2c`）声明 ✅ 而链接层还是空的 —— P1 必须红。
    #     这一条同时验两件事：① 2c 的交付物判据真的能红
    #     ② `ROW` 正则认得出 `2c` —— 照抄 fr 的那版只认数字，`2c` 会被**静默跳过**，
    #     那种漏法不会报错、只会安静地少查一个阶段，光看"✅ 全部通过"根本发现不了。
    def _m6():
        con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        got6 = [r for r in p1(con2) if "阶段 2c" in r[1]]
        con2.close()
        return got6
    got = with_plan(declare("2c"), _m6)
    print("   M6 %s（阶段 2c 声明✅ 而非 en-edition 的变形链是 0）"
          % ("✅ 逮到" if got else "🔴 **漏了**：带字母的阶段号被正则漏掉了"))
    ok += bool(got)

    # M2：阶段 7 声明 ✅ 而闸文件不存在 —— P1 必须红（这条专打 `SELECT 1` 那个坑）
    def _m2():
        con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        got2 = [r for r in p1(con2) if "阶段 7" in r[1]]
        con2.close()
        return got2
    got = with_plan(declare("7"), _m2)
    print("   M2 %s（阶段 7 声明✅ 而回归闸/契约闸文件还不存在）"
          % ("✅ 逮到" if got else "🔴 **漏了**：文件不存在却不红 —— 这就是 `SELECT 1` 的毛病"))
    ok += bool(got)

    # M3：阶段 8 声明 ✅ 而 portuguese.ts 还是老单表版 —— P1 必须红
    def _m3():
        con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        got3 = [r for r in p1(con2) if "阶段 8" in r[1]]
        con2.close()
        return got3
    got = with_plan(declare("8"), _m3)
    print("   M3 %s（阶段 8 声明✅ 而展示层还只查 dict）"
          % ("✅ 逮到" if got else "🔴 **漏了**：展示层没接却不红"))
    ok += bool(got)

    # M4：收尾单后面塞一条游离 📋 —— P2 必须红
    got = with_plan(src + "\n📋 变异用的游离记账，马上删。\n", p2)
    print("   M4 %s" % ("✅ 逮到游离记账" if got else "🔴 **漏了**：游离 📋 没红"))
    ok += bool(got)

    # M5：删掉收尾单标题 —— P2 必须红
    got = with_plan(src.replace(SHEET, "# 无关标题"), p2)
    print("   M5 %s" % ("✅ 逮到收尾单消失" if got else "🔴 **漏了**：收尾单没了却不红"))
    ok += bool(got)

    print("\n   变异 %d/6" % ok)
    return ok


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(0 if mutate() == 6 else 1)
    sys.exit(1 if report() else 0)
