#!/usr/bin/env python3
"""**账的闸** —— `docs/DE_PLAN.md` 说的话，与库和代码对不对得上。2026-08-31 随 de 阶段 -2 建。

═══ 为什么 de 一开工就有这个文件 ═══
fr 是做到第七天、被用户问「你自己定的规矩自己为什么不执行」之后才建的。
查那次会话的记录，结论很干净：

    守住了的   `think=False` 硬默认 / `DOUBAO_DISABLED` / `dbtool` 的 expect 闸  ← **全是机制**
    没守住的   「别在原地打转」「判据要收窄」「正则选择支按长度排」            ← **全是文字**

不是态度差别：`think=False` 我根本不需要想起它；而「别在原地打转」只在我主动问
"这件事该不该做"的时候才响 —— 可我刚发现一个真缺陷的时候从来不问那个问题，
**发现本身感觉就是答案了**。

⇒ 所以 de 和 pt 一样不等到第七天。阶段 -2 就把它建出来。

═══ 这道闸拦的三件事（P1/P2 是 fr 上真发生过的，P3 是 pt 上真发生过的）═══

**P1 —— 阶段表标着 ✅，交付物却是空的。**
   fr 的阶段表从 08-22 起没更新过：阶段 8 之后的评审族已经做到第五个，
   而阶段 5 的**关系层 0 条、频次层根本不存在**。
   这条闸把「完成的定义」变成可执行的：**声明做完了，就必须交得出东西。**

**P2 —— 记账散落。** 收尾单之后不许再出现游离的 📋。

**P3 —— 收尾单里说「已做」的，必须交得出东西。**
   fr 的收尾单 C29 白纸黑字写着「fr 今天已修」，**代码里没有**；
   而 P1 只核阶段表的 ✅，收尾单那几十行「已做」一直是纯自述。

🔴 **交付物的判据不许写成永远为真的断言。** fr 第一版把阶段 7、阶段 9 都写成 `SELECT 1`
   —— 和 it 那轮 `return {ok:true}` 的健康检查同一个毛病。所以交付物分三类，每类都得**真的能红**：

     DELIVERABLE  库里那一层非空吗          （SQL）
     FILES        那个闸/存档真的存在吗      （路径）
     CODE         代码里真的接上了吗          （文件里必须出现某个串）

🔴🔴 **本文件与 pt 那版有一处故意的不同**：`__main__` 里 pt 写的是
   `sys.exit(0 if mutate() == 6 else 1)`，而它自己打印的是「变异 %d/8」——
   **8 条变异挂 2 条仍然退出 0**。那正是本文件通篇在骂的"假绿"。
   de 这版用 `mutate() == len(MUTATIONS)`，条数由列表长度决定，加一条变异不用改判据。

⚠️ 本文件**不查数据质量**，那是 `tests/test_no_regression.py` 的事（阶段 7 建）。
   它查的是**账**。两者都由 `dbtool.session` 每次写库时跑。

用法：
    python3 tests/test_plan_ledger.py          # 明细
    python3 tests/test_plan_ledger.py --mutate # 变异验证：一条永远通过的检查等于没检查
"""
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
# C15/C16/C31 的判据要 import 生成侧与修复侧那一份（判据只许一份）。
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE.parent / "fixes"))
# P5 要 import 回归闸的模块级判据常量（共用的一律 import，不重写）
sys.path.insert(0, str(HERE))

import paths                                     # noqa: E402

ROOT = HERE.parent.parent
PLAN = ROOT / "docs" / "DE_PLAN.md"
SHEET = "# 📋 de 收尾单"

# ⭐ **「完成的定义」就是下面三张表。** 阶段表里声明 ✅ 的阶段，必须在这里交得出东西。
#    🔴 判据写成「这一层非空」而不是「行数 ≥ 某个数」——
#      写死行数的断言必然过期（`[[fix-regression-and-gate]]`：fr 旧闸 20 条红
#      全是断言过期不是数据错）。而「整层是不是 0」永远不会过期。
DELIVERABLE = {
    # 阶段 0 只建空表 + 把 `dict` 的内容列搬进来；`sense_src` 是阶段 1 才填的
    # （pt 那版从 fr 抄来时把这两件事搞混过，fr 上没暴露是因为 0 和 1 同一天做完）。
    "0": [("sense 出版层", "SELECT COUNT(*) FROM sense"),
          ("sense_gloss 释义", "SELECT COUNT(*) FROM sense_gloss"),
          ("collocation 搭配", "SELECT COUNT(*) FROM collocation"),
          ("十一张表都建了",
           "SELECT (SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
           "('sense_src','sense','sense_gloss','sense_tag','sense_relation','pronunciation',"
           "'example','example_gloss','collocation','collocation_gloss','audio'))=11")],
    "1": [("entry 词条层", "SELECT COUNT(*) FROM entry"),
          ("sense_src 证据层", "SELECT COUNT(*) FROM sense_src")],
    "1.5": [("德语原文释义", "SELECT COUNT(*) FROM sense_gloss WHERE lang='de'"),
            ("中文释义", "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh'")],
    # 🔴 阶段 2 交付的是**两件事**，只查一件等于另一件干不干都能过
    #    （pt 收尾单 C3 那条：旧断言只查「音标层非空」，补了一种读音、另一种是 0 也绿）。
    #    2b 的变形层 + 2a 的 alt_of 归位，各查一条。
    "2": [("2b inflection 变形层", "SELECT COUNT(*) FROM inflection"),
          ("2a alt_of 归位成的关系", "SELECT COUNT(*) FROM sense_relation WHERE kind='alt_of'"),
          # 2a 的目的不是"写了几条关系"，是**让那些词形不再只有一句假的「X 的 变形」**。
          # ⇒ 直接断言目的：有 alt_of 关系的词形，必须都拿到了真义项。
          ("2a 的目的：有 alt_of 关系的词形都有真义项",
           "SELECT COUNT(*)=0 FROM (SELECT DISTINCT r.word_id FROM sense_relation r "
           " WHERE r.kind='alt_of' AND NOT EXISTS("
           "   SELECT 1 FROM sense s WHERE s.word_id=r.word_id))")],
    # 🔴 2c 的判据不能写「inflection 非空」——阶段 2 已经让它非空了，那条对 2c 永远为真。
    #    2c 交付的是**阶段 3 新收的变形接回了词元**，那批链接的 `src` 一定不是 en-edition。
    "2c": [("阶段 3 新收变形的链接（src 非 en-edition）",
            "SELECT COUNT(*) FROM inflection WHERE src<>'en-edition'")],
    "3": [("收词后的 dict", "SELECT COUNT(*) FROM dict")],
    # 🔴🔴 **de 的阶段 4 判据必须分层，理由和 pt 的双读音是同一个形状、不同的病**：
    #    pt 那轮旧断言只查「音标层非空」——补了巴葡、欧葡是 0 也能过（收尾单 C3）。
    #    de 不是双读音语言，但**它的缺口 100% 在变形层**（lemma 层开工当天就 99.8%）：
    #    只查整表非空，等于「把已经有音标的 lemma 搬进新表」就能宣布阶段 4 做完。
    #    ⇒ 第二条断言专问变形层，**这一门的全部工作都在那一层**。
    "4": [("pronunciation 音标层", "SELECT COUNT(*) FROM pronunciation"),
          ("变形层的音标（de 的缺口全在这一层）",
           "SELECT COUNT(*) FROM pronunciation p JOIN dict d ON d.id=p.word_id "
           " WHERE d.is_lemma=0")],
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

# 阶段 -1 / -2 / 7 的交付物是**文件**，不是库里的行。
# 🔴 fr 那版把阶段 7 写成 `SELECT 1` —— 永远为真，等于没查。
FILES = {
    "-1": [("取数表与字段归属", "docs/lang/de-CONVENTIONS.md"),
           ("逐源实测存档（6 源）", "data/work/de/probe/count_slices_20260831.txt"),
           ("建库主源实测存档", "data/work/de/probe/count_slices_en_20260831.txt"),
           # 🔴 建库主源本身也是阶段 -1 的交付物：它 2026-08-31 当天不在盘上
           #    （`DE_PLAN` 1.4），而外锚闸/证据层/义项级关系/例句四样都要重扫它。
           ("建库主源 dump", "data/dumps/kaikki.org-dictionary-German.jsonl")],
    "-2": [("写库闸门", "de/dbtool.py"),
           ("账的闸（本文件）", "de/tests/test_plan_ledger.py"),
           ("备份保留策略的行为测试", "de/tests/test_prune_backups.py"),
           ("字面量闸", "de/tests/test_no_literal_counts.py")],
    "7": [("回归闸", "de/tests/test_no_regression.py"),
          ("契约闸", "apps/web/src/contract-check-de.tsx")],
}

# 契约闸：**光有文件不算交付物，跑得过才算。**
# 🔴🔴 2026-08-31 在 fr 上验过：把源语言行退回旧写法，`contract-check-fr.tsx` 当场报 6,646 条红
#    —— 闸是真的，它只是**没人跑**。数据层的闸挂在 `dbtool.session` 上每次写库自动跑，
#    而展示层的改动**不写库**，于是一路绿到用户读页面。
#    ⇒ 把契约闸接进这道闸：阶段 7 一旦声明 ✅，每次写库顺带跑一遍。
CONTRACT = ("apps/web/src/contract-check-de.tsx", ["--limit", "60"])

# 阶段 8 的交付物是**展示层真的改了读取路径**。
# 🔴 判据来自 `[[it-display-layer-stage8]]`：数据层全绿、库里查得到，而 `french.ts` 里
#    `FROM audio` 出现 0 次 ⇒ 39 万条录音一个用户都看不见。**"落库成功"证明不了"到达用户"。**
#    老单表版的 `german.ts` 只有 `FROM dict`；切到 v3 之后必然出现 `FROM sense`。
CODE = {
    "8": [("展示层已切到多表（不再只查 dict）",
           "packages/dict-core/src/german.ts", "FROM sense")],
}

# 阶段表的行：`| **5** | **例句…** | **✅ 已完成** | 1 | … |`
# ⚠️ 阶段号可以带字母后缀（`2c`）。fr 照抄来的正则只认数字 ⇒ **带字母的阶段声明 ✅ 也不会被查**，
#    闸静默漏掉一整个阶段。
ROW = re.compile(r"^\|\s*\**\s*(-?[0-9.]+[a-z]?)\s*\**\s*\|(.+?)\|(.+?)\|", re.M)


MARKS = ("✅", "🔄", "📋")


def _status(state):
    """状态栏 → 三个标记里**最先出现的那一个**（没有则 None）。

    🔴 2026-09-03：原来写的是 `if "✅" in state`（子串命中）。我把阶段 1.5 的状态栏
       改成「🔄 **1.5a ✅ 已落库**／1.5b 付费段未跑」——**一个诚实的进行中状态**——
       闸立刻把 1.5 判成了「已完成」，于是 P4（1.5 没完成就不许声明后面的阶段）
       整个失效。**闸没坏，是它读错了地方**：它在读整个单元格的散文，
       而状态只由**开头那个标记**表示。
    ⚠️ 修法有两个，选了这个：
       ① 改我的文案，不许在状态栏里出现第二个 ✅  ⇒ 靠人记，下次照犯
       ② 改判据，只认第一个标记                  ⇒ 文案怎么写都拦得住
       `[[lesson-must-become-mechanism]]`：交付物是一道自己会响的闸，不是一条记性。
    """
    pos = [(state.index(m), m) for m in MARKS if m in state]
    return min(pos)[1] if pos else None


def declared_done():
    """→ {阶段号: 标题}，只含**状态栏首标记为 ✅** 的。"""
    s = PLAN.read_text(encoding="utf-8")
    i = s.index("## 二、阶段表")
    tbl = s[i:s.index("\n---", i)]
    out = {}
    for m in ROW.finditer(tbl):
        num, title, state = m.group(1), m.group(2), m.group(3)
        if _status(state) == "✅":
            out[num] = title.strip().strip("*").strip()
    return out


def _run_contract():
    """跑一遍契约闸。→ (过没过, 说明)。跑不起来也算没过 —— 一个跑不起来的闸不是闸。"""
    import subprocess
    try:
        r = subprocess.run(
            ["npx", "tsx", "--tsconfig", "apps/web/tsconfig.json", CONTRACT[0], *CONTRACT[1]],
            cwd=ROOT, capture_output=True, text=True, timeout=180)
    except Exception as e:                      # noqa: BLE001
        return False, "跑不起来：%s" % e
    if r.returncode == 0:
        return True, "通过"
    # ⚠️ 不能用「这行含 🔴」来挑 —— **断言的名字本身就带 🔴**。
    #    契约闸的红行长这样：`   🔴 <名字>`（通过的是 `   ✅ <名字>`）。
    tail = [x.strip() for x in (r.stdout or "").splitlines() if x.startswith("   🔴")]
    return False, ("／".join(tail[:2]) if tail else (r.stderr or "")[-160:].strip())


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
            elif rel == CONTRACT[0]:
                ok, why = _run_contract()
                if not ok:
                    bad.append(("P1", "阶段 %s 的契约闸**跑不过**：%s" % (num, why)))
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
    #    fr 第一版把所有 `#` 开头的行都豁免了，当天就自己走过这个洞。
    stray = [ln.strip() for ln in tail.splitlines()
             if "📋" in ln and not ln.startswith(SHEET)
             and not ln.lstrip().startswith(("|", ">"))]
    return [("P2", "收尾单之后有 %d 条游离记账（应进表）：%s"
             % (len(stray), stray[0][:60]))] if stray else []


# ══════════════════════════════════════════════════════════════════
# P4 —— **1.5b 翻译没做完，后面的阶段一个都不许声明完成。**
#
# 🔴 用户 2026-09-01 定的：「后面的工作不准备做了，必须等翻译这一步做完再说」。
#    起因是我问「没翻译完先做阶段 4 有风险吗」，自己答了「风险低」并准备往下走。
#    用户的判断更严：**顺序上没风险 ≠ 应该这么排**。
#
# ⚠️ 这条**必须是闸，不能是备注**（`[[lesson-must-become-mechanism]]`）：
#    同场会话已经验证过——做成机制的规矩守住了，写成文字的一条没守住，
#    而「往下一个阶段走」恰恰是我最不会回忆起这条约束的时刻。
#
# 🔴 顺带堵住我自己在同一次对话里点名的两个风险，把它们写成这条闸的理由：
#    ① **付费池必须在开跑前重算**——现在这个 119,606 条是快照，
#       阶段 4/5 一动义项它就过期；拿过期快照批全量正是
#       `[[control-must-cover-every-output-field]]` 烧掉 418 万 token 的形状。
#       停在 1.5 上，池子就不会在我背后变。
#    ② 阶段 4 会动 `dict.ipa` / `ipa_src`，而回归闸（阶段 7）还没建 ——
#       少一个并行的战场，就少一处「谁改坏的」说不清的地方。
AFTER_15 = ("4", "5", "5a", "5b", "5c", "6", "7", "8", "9")


def p4():
    """1.5 未完成时，它后面的阶段不许声明 ✅。"""
    done = set(declared_done())
    if "1.5" in done:
        return []
    early = sorted(x for x in AFTER_15 if x in done)
    if not early:
        return []
    return [("P4", "阶段 1.5（翻译）还没完成，但阶段 %s 已声明 ✅ —— "
                   "用户 2026-09-01：「必须等翻译这一步做完再说」" % "、".join(early))]


# ══════════════════════════════════════════════════════════════════
# P3 —— **收尾单里说「已做」的，必须交得出东西。**
CLAIM = re.compile(r"^\|\s*(C[0-9]+[a-z]*)\s*\|(.*)$", re.M)
CLAIM_WORDS = ("✅", "已做", "已解决", "已改正")


def claims():
    """→ [(编号, 该行原文)]，只含收尾单里**自称已做**的行。"""
    s = PLAN.read_text(encoding="utf-8")
    if SHEET not in s:
        return []
    return [(m.group(1), m.group(2)) for m in CLAIM.finditer(s[s.index(SHEET):])
            if any(w in m.group(2) for w in CLAIM_WORDS)]


def _safe(con, q):
    try:
        return con.execute(q).fetchone()[0]
    except sqlite3.Error:
        return -1


def _sql(q, want):
    def f(con):
        n = _safe(con, q)
        return (n > 0 if want == "非空" else n == 0), "%s = %s" % (want, n)
    return f


def _file(*rels):
    def f(_con):
        miss = [r for r in rels if not (ROOT / r).exists()]
        return (not miss), ("缺 %s" % miss if miss else "、".join(rels))
    return f


def _has(rel, *needles):
    def f(_con):
        t = (ROOT / rel).read_text(encoding="utf-8") if (ROOT / rel).exists() else ""
        miss = [x for x in needles if x not in t]
        return (not miss), ("%s 里缺 %s" % (rel, miss) if miss else rel)
    return f


def _both(*fs):
    def f(con):
        for g in fs:
            ok, why = g(con)
            if not ok:
                return False, why
        return True, "全部满足"
    return f


# ⚠️ 判据不许写成永远为真（`SELECT 1` 那个毛病，本文件开头就在骂它）。
#    每一条问的都是「**这件事真做了才会成立**的那个具体事实」。
def _zero(sql, label):
    """判据 = 这条 SQL 必须数出 0。**问的是数据，不是文件在不在。**"""
    def f(con):
        n = con.execute(sql).fetchone()[0]
        return n == 0, ("%s = %d" % (label, n))
    return f


def _py(fn, label):
    """判据 = 一个 Python 谓词（用于 SQLite 表达不了的，比如 ASCII-only 的大小写）。"""
    def f(con):
        n = fn(con)
        return n == 0, ("%s = %d" % (label, n))
    return f


def _c15(con):
    """变化类连写。判据 import 生成侧 `klassen_run_together`，SQL 只做**预筛**。

    ⚠️ 预筛必须**只放宽不收紧**：连写＝两个变化类紧挨着，而三个类名都以「变化」结尾，
       所以连写必然出现「变化强」「变化弱」「变化混」之一。反过来不成立
       （命中的不一定是连写）—— 那没关系，真判据在后面。
    🔴 不下推的代价：把 536 万行 `label_zh` 整列拉进 Python **32.7 秒**，
       而这道闸挂在每次写库上。下推后 **2.6 秒**。
    """
    from infl_compose import klassen_run_together
    return sum(1 for (x,) in con.execute(
        "SELECT label_zh FROM inflection WHERE label_zh LIKE '%变化强%' "
        "OR label_zh LIKE '%变化弱%' OR label_zh LIKE '%变化混%'")
        if klassen_run_together(x))


def _c16(con):
    import json as _j
    from link_blank_forms import is_spelling_variant
    # ⚠️ `label_zh='变形'` 下推到 SQL（原来在 Python 里 `continue`）：27.0 秒 → 约 5 秒。
    n = 0
    for t, lab in con.execute("SELECT tags, label_zh FROM inflection "
                              "WHERE label_zh='变形' AND tags IS NOT NULL"):
        if lab != "变形":
            continue
        try:
            if is_spelling_variant(_j.loads(t)):
                n += 1
        except Exception:
            pass
    return n


def _c36(con):
    """C36：变形标签该带语域前缀而没带的行。判据 import 生成侧 `infl_compose.register_ok`。

    ⚠️ **先用 SQL 把范围缩到「tags 里出现过语域词」的那批**（约 1.5 万行），
       再逐行 JSON 解析。第一版对全表 536 万行逐行 `json.loads`，
       而这道闸挂在 `dbtool.session` 上 —— **每次写库都要跑一遍**，
       一条判据把每次写库拖慢一分多钟。
    🔴 预筛必须**由 `REGISTER` 自己生成**，不许在这里手抄一份词表：
       手抄的那份会随着 `REGISTER` 增删而悄悄漏掉新词 ⇒ 闸静默变宽。
       预筛只能**放宽**不能收紧（`LIKE '%archaic%'` 会多捞，真判据仍是 `register_ok`）。
    """
    import json as _j
    from infl_compose import register_ok, REGISTER
    # 🔴 **必须用字面量拼，不能用 `LIKE ?`**：这条预筛靠局部索引 `idx_infl_register`
    #    （索引谓词就是下面这串 OR），而 SQLite **无法证明 `?` 蕴含索引谓词** ——
    #    实测参数化 8.44 秒走全表扫、字面量 0.03 秒走索引，**行数一模一样 14,967**。
    #    ⚠️ 拼字符串前先断言键是纯 ASCII 字母（不是"我记得它们是"）。
    #    ⚠️ `REGISTER` 改了而索引没跟着改 ⇒ 只是变慢、**不会变错**（回退成全表扫），
    #      而计时闸会当场把它报出来。这是有意选的失败方式。
    assert all(k.isascii() and k.isalpha() for k, _ in REGISTER), "REGISTER 的键必须是纯字母"
    where = " OR ".join("tags LIKE '%%%s%%'" % k for k, _ in REGISTER)
    n = 0
    for t, lab in con.execute(
            "SELECT tags, label_zh FROM inflection WHERE (%s)" % where):
        try:
            tt = set(_j.loads(t))
        except Exception:
            continue
        if not register_ok(tt, lab):
            n += 1
    return n


def _c37(con):
    """C37：源头把关系绑在某一条义项上、而那条义项我们没收 —— 这种行不许可见。

    🔴 **锁的是数字不是名字**（`[[fix-regression-and-gate]]` 第四种机制：
       「已接受」＝「不再看」）。这批是**源头本来就没给下标**的真·词条级关系，
       词级显示是对的。超了 ⇒ 有新的「第 N 义的关系被说成整个词的」溜进来；
       低了 ⇒ 说明判据能收得更紧，要回来改这个数而不是让它默默变小。

    ⭐ **锁当天就兑现了一次**：C38 把 33 条「目标是德语版词类小标题」
       （`stehen` 的派生栏印着 `Adjektive`/`Substantive`/`Verben`）改成 `hidden=1`，
       这个数从 188,494 掉到 **188,461**，闸立刻报红要求我来改这个数字。
       换成「按名字豁免」的写法，这 33 条的消失就会一声不吭 —— 那正是它要防的。
    """
    n = con.execute(
        "SELECT COUNT(*) FROM sense_relation "
        "WHERE src='de-edition' AND sense_id IS NULL AND hidden=0").fetchone()[0]
    return 0 if n == 188_461 else n


def _c31(con):
    from normalize_region import DOMAIN
    a = {r for (r,) in con.execute("SELECT DISTINCT region FROM pronunciation "
                                   "WHERE region IS NOT NULL")}
    b = {r for (r,) in con.execute("SELECT DISTINCT region FROM audio WHERE region IS NOT NULL")}
    return len((a | b) - DOMAIN)


def _c43(con):
    """C43：`sense_relation.kind` 里有没有**读者会看到英文名**的值。

    🔴 判据必须两侧都取真的：一侧是库里**可见**的 kind 值域（`hidden=0`），
       另一侧是展示层那张标签表 `packages/dict-labels/src/common.ts` 的 `REL_LABELS`。
       ⚠️ TS 没法 import，只能正则取 —— 于是**必须给取数本身加一道自检**：
         取不到 ≥8 个键就说明表结构变了、正则失效，这时要**报红而不是报 0**。
         一个「解析失败 ⇒ 集合为空 ⇒ 差集为空 ⇒ 绿」的闸是最坏的那种假绿。
    """
    src = (ROOT / "packages" / "dict-labels" / "src" / "common.ts").read_text(encoding="utf-8")
    m = re.search(r"REL_LABELS[^=]*=\s*\{(.*?)\}", src, re.S)
    keys = set(re.findall(r"'?([A-Za-z_][\w-]*)'?\s*:", m.group(1))) if m else set()
    if len(keys) < 8:
        return -1                    # 解析失败：报红，别报 0
    # 🔴 **判据第一版比它要描述的东西宽**（`[[criteria-narrower-than-you-think]]`）：
    #    它拿「库里所有可见 kind」去比，于是把 `alt_of` 也算了进来 —— 而 `alt_of`
    #    **根本不走 `REL_LABELS` 这条渲染路径**：`german.ts` 的关系查询写着
    #    `AND r.kind <> 'alt_of'`，它由单独的「异体」区渲染（契约闸另有两条断言盯着）。
    #    ⇒ 值域必须与**取数那一侧**对齐：只算真的会流经这张标签表的 kind。
    have = {k for (k,) in con.execute(
        "SELECT DISTINCT kind FROM sense_relation "
        " WHERE COALESCE(hidden,0)=0 AND kind <> 'alt_of'")}
    return len(have - keys)


def _c41(con):
    """C41 的「已做那一档」：英文版音标层收进来了、且**一行都没越界**。

    🔴 两条都要查，缺一条都能被绕过：
      ① 只查「层在不在」—— 补到已经有德语版音标的词形上也算绿，那是重复读音；
      ② 只查「没越界」—— 一行都没写也是 0 越界，**永远通过的检查等于没检查**。
    ⚠️ 越界那条的判据与 `fixes/fill_ipa_from_en.py` 闸③说的是同一件事。
    """
    over = con.execute(
        "SELECT COUNT(DISTINCT p.word_id) FROM pronunciation p WHERE p.src='en-edition' "
        "  AND EXISTS(SELECT 1 FROM pronunciation q WHERE q.word_id=p.word_id "
        "             AND q.src='de-edition')").fetchone()[0]
    if over:
        return over
    n = con.execute("SELECT COUNT(*) FROM pronunciation WHERE src='en-edition'").fetchone()[0]
    # ⚠️ 这个下限问的是「**那一轮到底跑没跑**」，不是「有多少行」——
    #    行数由 P5 锁在文档那一栏（判据只许一份，期望值只许一份）。
    # 🔴 第一版写 27,000（＝落库当天的行数），**同一天就红了**：C42 清掉 1,290 条
    #    半截音标之后剩 25,830。把「这一步做了吗」的判据钉在一个会被正常清理改动的
    #    精确数上，等于给自己造一条**会因为做对事而报红**的闸。
    #    ⇒ 下限放到「空的/几千条的都说明那一轮没跑或没落库」这个量级（同 C29 的写法）。
    return 0 if n >= 20_000 else 1


DONE = {
    # 🔴 下面四条 2026-09-04 加。判据**一律 import 生成侧/修复侧那一份**，
    #    问的是「**这件事真做了才会成立的那个数据事实**」，不是「脚本文件在不在」。
    "C15": _py(_c15, "变化类仍连写的行"),
    "C16": _py(_c16, "tags 说是异体、标签仍是「变形」的行"),
    "C31": _py(_c31, "region 落在登记值域之外的值"),
    # C42：判据 import 修复侧那一份（`drop_half_ipa.bad_rows` → `truncated`），
    # 闸不自己写一遍「音标开头有没有连字符」—— 那正是本文件开头骂的第三种机制。
    "C42": _py(lambda con: len(__import__("drop_half_ipa").bad_rows(con)), "半截音标"),
    "C43": _py(_c43, "关系分组名读者会看到英文的 kind 值"),
    # C41 仍是 🟡（残 16,483 补不了：今天的英文版不给了），但「补英文版那一档」已做完
    # ⇒ 同 C29 的处理：不改文案绕过去，给它一条只有真做了才成立的判据。
    "C41": _py(_c41, "英文版音标层缺失或越界补到德语版已覆盖的词形上"),
    # ⚠️ C21 与 C41 **共用同一条判据**，不各写一版：C21 行里那句「已补 12,847」
    #    说的就是 C41 这一件事。两行各写一版 SQL ⇒ 两道闸各自都绿、锁的却是两个数。
    "C21": _py(_c41, "英文版音标层缺失或越界补到德语版已覆盖的词形上（同 C41）"),
    # C29 仍是 🟡（①③ 两档有意不做），但行里写了「②那一档已做完」⇒ 闸把它算作自称已做，
    # **这是对的**。⇒ 不改文案绕过去（那是「靠人记」），给它一条**只有真做了才成立**的判据：
    #   ① 裁决层非空且不是零头 —— 空的/几百条的都说明那一轮没跑或没落库；
    #   ② 同一义项没有逐字重复的德语释义 —— v1 有 561 条，v2 靠源侧去重清成 0。
    #      这一条尤其要留着：它是 v1 那个缺陷的**专用闸**，重跑退化会当场红。
    "C29": _both(
        _zero("SELECT CASE WHEN (SELECT COUNT(*) FROM sense_gloss "
              "WHERE lang='de' AND src='de-edition-adjudicated') >= 40000 THEN 0 ELSE 1 END",
              "裁决层为空或明显偏小"),
        _zero("SELECT COALESCE(SUM(c-1),0) FROM (SELECT sense_id,text,COUNT(*) c "
              "FROM sense_gloss WHERE lang='de' GROUP BY 1,2 HAVING COUNT(*)>1)",
              "同一义项挂了逐字相同的德语释义"),
    ),
    # C38：外审残单一次清。五族各一条判据，**都是「真做了才成立」的数据事实**。
    "C38": _both(
        _zero("SELECT COUNT(*) FROM sense_gloss g WHERE g.lang='zh' "
              "AND (TRIM(g.text) LIKE '%：' OR TRIM(g.text) LIKE '%:')",
              "中文释义仍以冒号结尾（把小标题当定义）"),
        _zero("SELECT COUNT(*) FROM sense_gloss g WHERE g.lang='de' AND g.text LIKE '%====%' "
              "AND NOT EXISTS(SELECT 1 FROM sense_gloss z WHERE z.sense_id=g.sense_id "
              "               AND z.lang IN ('zh','en'))",
              "wikitext 残渣且该义项无中英文"),
        _zero("SELECT COUNT(*) FROM inflection WHERE tags LIKE '%causative%' "
              "AND kind<>'derivation'", "使役派生仍算在变形里"),
        # ⚠️ `section_rels` 返回的是 id 列表，`_py` 要的是计数 —— 这里 len 一下。
        _py(lambda con: len(__import__("review_residue").section_rels(con)),
            "德语版词类小标题仍作为关系可见"),
    ),
    # C7：**造出来的比较级已清**（254 条）。判据 import 修复侧那一份 ——
    #    两个独立信号相交：`entry` 没给（＝kaikki 没给）＋ 声称的形式在全库不存在。
    #    ⚠️ C7 整条**没做完**（还剩 27,008 条说不出来源），但它声称做完的**那一部分**
    #      必须交得出东西 —— 这正是 P3 要拦的：局部的「已做」也是「已做」。
    "C7": _py(lambda con: len(__import__("drop_bad_comparatives").bad_rows(con)),
              "造出来的比较级（无 entry 背书且形式不存在）"),
    # C40：判据已改（`…` 合法当且仅当词形本身也有 `…`）。
    #    它声称的是**生成侧的判据变了**，所以判据要问一件「真改了才成立的数据事实」：
    #    库里不许存在按新判据算的「半截音标」。与回归闸 D2 同一份 `truncated`。
    #    ⚠️ 那 10 条待落的数据**不在这条判据里** —— 它们是「缺」，而这条问的是「有没有错」。
    "C40": _py(lambda con: sum(
        1 for w, x in con.execute("SELECT d.word, p.ipa FROM pronunciation p "
                                  "JOIN dict d ON d.id=p.word_id")
        if __import__("harvest_pronunciation").truncated(x or "", w)),
        "库里按新判据算仍是半截的音标"),
    # C1：来源列已回填。判据问「有值却说不出来源」—— 注意 `unknown` **也算说得出**
    #    （`[[ipa-provenance-columns]]`：证明不了就写 unknown，那是一个诚实的答案，
    #    不是空值）。空着才是「从没回填」。
    "C1": _both(
        _zero("SELECT COUNT(*) FROM dict WHERE COALESCE(ipa,'')<>'' "
              "AND COALESCE(ipa_src,'')=''", "有 ipa 却说不出来源"),
        _zero("SELECT COUNT(*) FROM dict WHERE COALESCE(gender,'')<>'' "
              "AND COALESCE(gender_src,'')=''", "有 gender 却说不出来源"),
        # 反向：没有值就不许写来源，否则来源列自己变成噪声源
        _zero("SELECT COUNT(*) FROM dict WHERE COALESCE(ipa,'')='' "
              "AND COALESCE(ipa_src,'')<>''", "没有 ipa 却写了来源"),
    ),
    # C2：两列从来没填过 ⇒ 随降列消失。两条各查一次：
    #    ①锚点列真的一列不剩 ②`example` 的家（v3 的表）真的有东西。
    #    只查①的话，「把表也删了」同样能让它绿 —— 那正是「消失」和「搬走」的区别。
    "C2": _both(
        _zero("SELECT COUNT(*) FROM pragma_table_info('dict') WHERE name IN "
              "('definition','translation','translation_src','meta','collocation',"
              "'example','flag')", "迁移锚点列还剩几列没删"),
        _zero("SELECT CASE WHEN (SELECT COUNT(*) FROM example) > 0 THEN 0 ELSE 1 END",
              "example 表为空"),
    ),
    # C36/C37：2026-09-04 外审那轮加。两条都 import 生成侧的判据，不另抄一份。
    "C36": _py(_c36, "该带语域前缀而没带的变形行"),
    "C37": _py(_c37, "可见且未挂义项的德语版关系（锁 188,461，超或低都要看）"),
    # C34：冠词被写成名词的变格形式。判据 import `drop_article_forms.bad_rows`，
    #      不在这里重写一遍 SQL（那 12 个冠词的表只许一份）。
    "C34": _py(lambda con: __import__("drop_article_forms").bad_rows(con),
               "冠词指向非冠词词元的行"),
    "C32": _zero(
        "SELECT COUNT(*) FROM inflection a WHERE a.kind<>'derivation' AND a.label_zh='变形' "
        "AND EXISTS(SELECT 1 FROM inflection b WHERE b.word_id=a.word_id AND b.base=a.base "
        "AND b.kind='derivation')", "与构词行重复的泛泛「变形」行"),
    # C3：建库主源重下 + MANIFEST 重跑。两件事各查一次 ——
    #     只查文件在，会漏掉"下回来了但清单还在说谎"。
    "C3": _both(_file("data/dumps/kaikki.org-dictionary-German.jsonl"),
                _has("data/MANIFEST.md", "kaikki.org-dictionary-German.jsonl")),
}


# 🔴🔴 **一条判据自己跑多久，也要有人看着**（2026-09-05 加）。
#    起因：C32 的判据里有个相关子查询跑在 536 万行的 `inflection` 上而缺覆盖索引，
#    **一次要 15 分钟以上**。它从 09-04 建 C32 那天就是这样，而我一整天都以为
#    「写库本来就慢」—— 因为**闸是绿的**，绿的东西不会有人去看它花了多久。
#    ⇒ 加一条上限：任何一条判据超过 `SLOW` 秒就报出来。
#      与 `[[fix-regression-and-gate]]` 第四种机制同源：**「通过了」不等于「还健康」。**
#    ⚠️ **阈值不能是一个绝对秒数**：冷缓存下扫一整列 536 万行就要 14 秒，
#      写死 20 秒会在冷启动时误报 —— 而误报的闸最后会被无视（狼来了）。
#      ⇒ 预算**自校准**：拿本次运行里「扫一整列」的实测成本当单位，
#        任何一条判据不许超过 **3 个全列扫**。冷暖都成立，且量级判断不变
#        （C32 那条 15 分钟的 ≈ 60 个全列扫，照样当场红）。
#      ⚠️ **第一版标定太紧（3 倍 / 下限 6 秒），当场在冷暖之间抖了**：
#        同一条 C32，暖缓存 1.18 秒、冷缓存 7.9 秒 —— 后者报红，而它没有任何毛病。
#        标定查询自己会被前面的语句焐热，而各条判据打的是冷页 ⇒ 单位偏小。
#        ⇒ 放宽到 **10 倍 / 下限 30 秒**。这**不是**「调高上限让它变绿」：
#          我先把每一条都真的改快了（C32 15 分钟→1.2 秒、C36 8.5→0.09 秒），
#          现在最慢的一条暖 3.7 秒／冷 8 秒，离 30 秒还有一个量级；
#          而它要抓的那种病（C32 原来 900 秒 ≈ 450 个全列扫）照样一眼报红。
#        **判据是「量级」不是「秒数」** —— 抖动会让闸被无视，那比没有闸更糟。
SLOW_FACTOR = 10.0
SLOW_FLOOR = 30.0


def _slow_budget(con):
    """→ 本次运行的单条判据耗时预算（秒）。**用实测的全列扫当单位。**"""
    import time
    t0 = time.time()
    con.execute("SELECT COUNT(label_zh) FROM inflection").fetchone()
    return max(SLOW_FLOOR, (time.time() - t0) * SLOW_FACTOR)


def p3(con):
    """收尾单里说「已做」的，必须交得出东西 —— **而且判据自己要跑得动**。"""
    import time
    slow = _slow_budget(con)
    bad = []
    for cid, rest in claims():
        f = DONE.get(cid)
        if not f:
            bad.append(("P3", "收尾单 %s 自称已做，但 DONE 里没有判据 —— "
                              "这正是 fr 的 C29 那个洞（账说修了，代码里没有）：%s"
                        % (cid, rest[:44])))
            continue
        t0 = time.time()
        try:
            ok, why = f(con)
        except Exception as e:                      # noqa: BLE001
            bad.append(("P3", "收尾单 %s 的判据跑不了：%s" % (cid, e)))
            continue
        dt = time.time() - t0
        if dt > slow:
            bad.append(("P3", "收尾单 %s 的判据跑了 %.1f 秒（本次预算 %.1f＝10 个全列扫）—— "
                              "它挂在每次写库上，先去看查询计划缺哪条索引、"
                              "或把过滤下推到 SQL，**不要靠调高倍数让它变绿**" % (cid, dt, slow)))
        if not ok:
            bad.append(("P3", "收尾单 %s 说「已做」，但判据不成立：%s" % (cid, why)))
    return bad


# ══════════════════════════════════════════════════════════════════
# **P5 —— 收尾单「规模」那一栏的数字，也要锁。**
#
# 🔴🔴 起因（2026-09-05）：用户问「剩下还有哪些工作」，我拿收尾单回答之前
#    先用库复核了 11 条，**6 条对不上**：
#        C4  18,127 → 18,124   C19 436 → 416
#        C13  5,264 →  7,161   C10 590 → 857
#        C9      64 →     48   C17 475,237 → 475,018
#        C23     17 →     14   C33   3 → **5（涨了）**
#    回归闸的 ACCEPT 早就锁数字了（低了会自己喊「⬇ 该收紧」，2026-09-05 当天喊对了四次），
#    **而收尾单没有这个机制** —— 于是它一路漂到现在没人吭声。
#    这正是 `[[fix-regression-and-gate]]` 第四种机制：「已接受」＝「不再看」，
#    只不过这次的载体是**文档**不是闸。
#
# ⇒ 规矩两条：
#    ① 末栏是纯数字的行，要么在 `SIZES` 里给一条**能从库里重算**的判据，
#      要么在 `SIZE_EXEMPT` 里写清**为什么重算不了**。两样都没有 ⇒ 红。
#      这一条是**覆盖锁**：以后新增带数字的记账行，必须当场表态。
#    ⚠️ `SIZES` 的值**只有 (判据, 说明) 两项，没有期望数字** —— 期望值只许有一份，
#      就是文档那一栏。第一版我顺手多留了个数字字段（P5 根本不读它），
#      **字面量闸当场逮到 8 处「期望值写死」** —— 它是对的：那种字段迟早会跟文档打架。
#    ② 已声明 ✅ 的行不进 P5 —— 它们由 `DONE` 锁着，**判据只许一份**。
#
# ⚠️ 四条与回归闸共用的判据 **import 回归闸的模块级常量**，不在这里重写 SQL。
#    两道闸各写一版 SQL、各自都绿、锁的却是两个不同的数 —— 那比不锁更糟。
SIZES = {
    # C2 由降列解决：判据从「那一列是不是空的」换成「**那一列还在不在**」。
    # ⚠️ 旧判据在列被删掉的那一刻**直接抛异常**（`no such column: example`）——
    #    是 P5 当场报出来的。一个查已消失对象的判据不是绿也不是红，是**跑不了**，
    #    而跑不了的判据等于没有判据。⇒ 判据必须跟着它描述的东西一起演进。
    "C2":  ("SELECT COUNT(*) FROM pragma_table_info('dict') "
            "WHERE name IN ('definition','translation','translation_src','meta',"
            "'collocation','example','flag')",
            "迁移锚点列还剩几列没删"),
    "C9":  ("SELECT COUNT(DISTINCT r.sense_id) FROM sense_relation r "
            "WHERE r.kind='alt_of' AND r.sense_id IS NOT NULL AND NOT EXISTS"
            "(SELECT 1 FROM sense_gloss g WHERE g.sense_id=r.sense_id AND g.lang='zh')",
            "alt_of 义项没有中文"),
    "C10": ("@Q_INFL_ORPHAN_BASE", "变形悬空原形（base_id 为空）"),
    "C13": ("SELECT COUNT(*) FROM inflection WHERE kind='derivation'",
            "构词行（阶段 8 必须与变形分区）"),
    "C17": ("SELECT COUNT(*) FROM inflection WHERE label_zh='变形' "
            "AND REPLACE(REPLACE(tags,' ',''),'\"','')='[form-of]'",
            "标签是光秃秃「变形」且源头只给了 form-of"),
    "C19": ("@Q_SENSE_NO_ZH", "义项没有中文"),
    "C21": ("@Q_WORD_NO_IPA", "有义项的词形没有读音"),
    "C23": ("SELECT COUNT(*) FROM pronunciation WHERE ipa LIKE '%[ə]%'",
            "音标中间的可选央元音 [ə]（不是没剥干净）"),
    "C26": ("@Q_EXAMPLE_NO_ZH", "例句没有中文"),
    "C28": ("@_blank_pages", "空白页（无义项、无变形、无指针）"),
    # C41：只有遗留列 `dict.ipa` 有值、读者看不见的词形。**能重算就锁死**。
    "C41": ("SELECT COUNT(*) FROM (SELECT DISTINCT s.word_id FROM sense s "
            "JOIN dict d ON d.id=s.word_id WHERE COALESCE(d.ipa,'')<>'' "
            "AND NOT EXISTS(SELECT 1 FROM pronunciation p WHERE p.word_id=s.word_id))",
            "只有 dict.ipa 有值、pronunciation 没有行的词形"),
    "C29": ("SELECT COUNT(*) FROM (SELECT DISTINCT s.word_id FROM sense s WHERE NOT EXISTS"
            "(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='de'))",
            "缺德语原文释义的词形"),
    "C33": ("SELECT COUNT(*) FROM inflection a WHERE a.label_zh LIKE '指小词%' "
            "AND EXISTS(SELECT 1 FROM inflection b WHERE b.word_id=a.word_id "
            "AND b.base=a.base AND b.label_zh LIKE '%复数%')",
            "标「指小词」而同一(词形,原形)另有「复数」行"),
}

# 重算不了的，**必须写清为什么**。豁免本身是可见的，不是沉默。
SIZE_EXEMPT = {
    "C39": "1,374 是**扫法语版 dump + 跑消去阶梯**得出的（真值集 "
           "`data/work/de/probe/fr_de_ipa_sets.tsv`，按词形聚合），库里没有对应的可重算计数。"
           "⭐ 归一链**已经固化成代码**了（`probes/ipa_conventions.py` 16 类消去器 + "
           "`c39_fr_audit.py` 的争议读法族），重跑 `python3 -u probes/c39_fr_audit.py` 就能复算 —— "
           "但它依赖 700MB 的法语版 dump，不适合放进每次都跑的闸里。"
           "🔴 旧文案说的 36,090 与那份 `fr_de_ipa_pairs.tsv` **都已作废**："
           "它每个词形只放我们的一条音标、而且不是首选那条（`du` 拿 `daɪ̯n` 去比）。",
    "C40": "10 条是**扫德语版 dump** 数出来的（判据 `harvest_pronunciation.truncated`），"
           "库里查不到「源头有而我们没收」这件事。判据本身由回归闸 D2 盯着；"
           "下次重跑音标层这 10 条落库后，这一行应改成 ✅ 并由 D2 锁死。",
    "C4":  "阶段 4 当时的快照口径（分母是那时的词形集），阶段 3 收词之后分母变了 ⇒ "
           "**现役口径是 C21**（18,124，已锁）。这一行留作历史，不再单独重算。",
    "C7":  "🔴 末栏那个数（27,008）问的是「有多少值**说不出来源**」，而判据本身就是"
           "「没有来源标记」—— 库里没有可重算的标记。回填 `*_src`（C1）之后才变成可锁的，"
           "届时移进 SIZES。⚠️ C7 里**已经做完的那部分**（254 条造出来的比较级）"
           "由 DONE 锁着，不在这条豁免范围内。",
    "C8":  "要重扫 dump 逐条比对才能重算，成本与 21 条的收益不匹配。",
    "C11": "6 个空白页是漂移基线里「上游不再产生变形」那一桶的子集，判据在漂移基线那边。",
    "C14": "3 个**具名**可分动词（zutreffen/einleuchten/vorfallen）的一次性核对，不是可重算的集合。",
    "C18": "51 条来自一次抽样（功能词的语法定义会被规则 5 判成留空），没有全量判据。",
    "C20": "88/129 是一次抽样的**比例**结论（判据比它要描述的东西宽），不是库里的一个计数。",
    "C22": "10,486 要扫**法语版 dump** 才能重算 —— 这条本身就是「待做」，做的时候会顺带锁上。",
    "C24": "19,066 是 `fill_freq` 一次运行时**挡下**的条数，不是库里现存的一个集合。",
    "C25": "残 2 是当时**闸自身 bug** 报出的假红条数（已改成 import 生成侧的 `unambiguous()`），"
           "属于历史记录，库里没有对应物。",
    "C27": "703 是 5b 控制判据的一次抽样结论（三条判据偏宽），不是可重算计数。",
    "C30": "1,733 是 1.5c 一次运行时被词性关挡下的条数，同 C24。",
}


def _size_criteria():
    """把 `@名字` 解析成回归闸里那一份判据。**共用的一律 import，不重写。**"""
    import test_no_regression as reg
    return {"@Q_INFL_ORPHAN_BASE": reg.Q_INFL_ORPHAN_BASE,
            "@Q_SENSE_NO_ZH": reg.Q_SENSE_NO_ZH,
            "@Q_WORD_NO_IPA": reg.Q_WORD_NO_IPA,
            "@Q_EXAMPLE_NO_ZH": reg.Q_EXAMPLE_NO_ZH,
            "@_blank_pages": reg._blank_pages}


SIZE_ROW = re.compile(r"^\|\s*(C\d+)\s*\|(.+)\|\s*([\d,]+)\s*\|\s*$", re.M)


def p5(con):
    """收尾单末栏的数字，必须与库里重算出来的一致。"""
    s = PLAN.read_text(encoding="utf-8")
    if SHEET not in s:
        return []
    sheet = s[s.index(SHEET):]
    named = _size_criteria()
    bad = []
    for m in SIZE_ROW.finditer(sheet):
        cid, body, num = m.group(1), m.group(2), int(m.group(3).replace(",", ""))
        if any(w in body[:14] for w in ("✅",)):
            continue                                  # 由 DONE 锁着，判据只许一份
        spec = SIZES.get(cid)
        if not spec:
            if cid in SIZE_EXEMPT:
                continue
            bad.append(("P5", "收尾单 %s 末栏写着数字 %s，却**既没有判据也没有豁免理由** —— "
                              "带数字的记账行必须当场表态（SIZES 或 SIZE_EXEMPT）"
                        % (cid, format(num, ","))))
            continue
        sql, label = spec
        try:
            got = named[sql](con) if sql.startswith("@") and callable(named.get(sql)) \
                else con.execute(named.get(sql, sql)).fetchone()[0]
        except Exception as e:                        # noqa: BLE001
            bad.append(("P5", "收尾单 %s 的规模判据跑不了：%s" % (cid, e)))
            continue
        if got != num:
            arrow = "涨了" if got > num else "少了（账没跟上，去改数字**并改理由文案**）"
            bad.append(("P5", "收尾单 %s 账上写 %s，库里实际 %s —— %s（%s）"
                        % (cid, format(num, ","), format(got, ","), arrow, label)))
    return bad


def report(verbose=True):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        red = p1(con) + p2() + p3(con) + p4() + p5(con)
    finally:
        con.close()
    if verbose:
        print("═══ 账的闸（de）：计划表说的话，库与代码对不对得上 ═══")
        done = declared_done()
        print("   阶段表声明已完成：%s" % ("、".join(sorted(done)) if done else "（无，尚未开工）"))
        print("   收尾单自称已做：%s" % ("、".join(c for c, _ in claims()) or "（无）"))
        for cid, why in red:
            print("   🔴 %-4s %s" % (cid, why))
        print("\n   %s" % ("✅ 全部通过" if not red else "🔴 %d 条要看" % len(red)))
    return red


def check_brief():
    """给 `dbtool` 挂钩用：静默跑，只回报红的。"""
    return report(verbose=False)


# ══════════════════════════════════════════════════════════════════
# ⭐ 变异验证：把闸该逮的东西造出来，看它红不红。
#
# 🔴🔴 **每一条都必须真的把被断言的东西拿走** —— pt 那轮 M2/M3/M6 三条只把**文档**
#    的状态栏翻成 ✅，然后指望**世界**还是没做完的样子。写它们那天确实还没做完，
#    做完之后**变异什么都没变**，闸当然不红，三条一起报「漏了」。
#    ⇒ 库侧删行/删表、文件侧指向不存在的路径、代码侧指向退回老单表版的副本。
_SRC = None


def _with_plan(text, fn):
    """临时把计划改成 text 跑一遍 fn，无论如何都还原。"""
    try:
        PLAN.write_text(text, encoding="utf-8")
        return fn()
    finally:
        PLAN.write_text(_SRC, encoding="utf-8")


def _declare(num):
    """把阶段 num 那一行的状态栏改成 ✅（不动其他列）。"""
    return re.sub(r"(^\|\s*\**\s*%s\s*\**\s*\|[^|]*\|)[^|]*\|" % re.escape(num),
                  r"\1 **✅ 已完成** |", _SRC, count=1, flags=re.M)


def _broken_db(*sqls):
    """复制一份库、在副本上执行破坏语句 → 只读连接。

    ⚠️ 用 `DROP TABLE IF EXISTS` / `DELETE` 都行：表还没建时是空操作，
       交付物查询会报 no such table ⇒ P1 走「查不了」那一支，**同样是红的**。
       这样同一条变异在阶段做完之前和之后都成立。
    """
    d = tempfile.mkdtemp()
    db = Path(d) / "m.db"
    shutil.copy(paths.DB, db)
    w = sqlite3.connect(db)
    for q in sqls:
        w.execute(q)
    w.commit()
    w.close()
    return sqlite3.connect("file:%s?mode=ro" % db, uri=True)


def _red_for(stage, plan_text, con=None):
    own = con is None
    con = con or sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        return _with_plan(plan_text, lambda: [r for r in p1(con)
                                              if ("阶段 %s" % stage) in r[1]])
    finally:
        if own:
            con.close()


def m_stage4():
    """M1：阶段 4 声明 ✅ 而音标层被删光 —— P1 必须红。"""
    con = _broken_db("DROP TABLE IF EXISTS pronunciation")
    try:
        return _red_for("4", _declare("4"), con)
    finally:
        con.close()


def m_stage2c():
    """M6：**带字母后缀的阶段号**（`2c`）声明 ✅ 而链接层空 —— P1 必须红。

    同时验两件事：① 2c 的交付物判据真能红 ② `ROW` 正则认得出 `2c`
    —— 只认数字的那版会**静默跳过**整个阶段，光看"✅ 全部通过"根本发现不了。
    """
    con = _broken_db("DROP TABLE IF EXISTS inflection")
    try:
        return _red_for("2c", _declare("2c"), con)
    finally:
        con.close()


def m_stage7():
    """M2：阶段 7 声明 ✅ 而闸文件不存在 —— P1 必须红（专打 `SELECT 1` 那个坑）。

    ⚠️ **不碰真文件**（跑挂了就把闸自己弄丢了），改成把清单指向不存在的路径。
    """
    keep = FILES["7"]
    try:
        FILES["7"] = [("回归闸（变异：指向不存在的路径）", "de/tests/__no_such_gate__.py")]
        return _red_for("7", _declare("7"))
    finally:
        FILES["7"] = keep


def m_stage8():
    """M3：阶段 8 声明 ✅ 而展示层退回老单表版 —— P1 必须红。"""
    keep = CODE["8"]
    with tempfile.TemporaryDirectory() as d:
        old = Path(d) / "german_old.ts"
        old.write_text("export const q = `SELECT id, word, translation FROM dict`;\n",
                       encoding="utf-8")
        try:
            CODE["8"] = [("展示层已切到多表（变异：换成老单表版）", str(old), "FROM sense")]
            return _red_for("8", _declare("8"))
        finally:
            CODE["8"] = keep


def m_stage_minus1():
    """M9（de 新增）：阶段 -1 声明 ✅ 而探测存档不存在 —— P1 必须红。

    🔴 这条不是凑数：阶段 -1 **今天就是 ✅**，而它的四个交付物里有一个
       （`docs/lang/de-CONVENTIONS.md`）在闸建成的那一刻还不存在 ——
       这道闸建出来第一次跑就对着我自己的计划报了红。
    """
    keep = FILES["-1"]
    try:
        FILES["-1"] = [("存档（变异：指向不存在的路径）", "data/work/de/probe/__no_such__.txt")]
        return _red_for("-1", _declare("-1"))
    finally:
        FILES["-1"] = keep


def m_fake_claim():
    """M7：**收尾单里凭空加一条「✅ 已做」** —— P3 必须红。

    打的正是 fr 的 C29 那个洞：**账说做了、什么都没做，而闸一声不吭**。
    """
    fake = _SRC.replace(SHEET, SHEET + "\n\n| # | 事 | 规模 |\n|---|---|---|\n"
                        "| C99 | ✅ **已做**：一件根本没做的事 | 0 |")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        return _with_plan(fake, lambda: [r for r in p3(con) if "C99" in r[1]])
    finally:
        con.close()


def m_broken_claim():
    """M8：**登记了判据但判据不成立**也要红（不只是"有没有登记"）。

    ⚠️ 造一条合成的 C98 而不是弄坏真的 C3 —— 收尾单开工当天只有一条自称已做的，
       弄坏它就得改真文档；合成的这条从第一天就成立，以后也不随收尾单变化而失效。
    """
    fake = _SRC.replace(SHEET, SHEET + "\n\n| # | 事 | 规模 |\n|---|---|---|\n"
                        "| C98 | ✅ **已做**：登记了判据，但判据不成立 | 0 |")
    DONE["C98"] = lambda _c: (False, "变异：假装这件事没做成")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        return _with_plan(fake, lambda: [r for r in p3(con)
                                         if "C98" in r[1] and "判据不成立" in r[1]])
    finally:
        con.close()
        DONE.pop("C98", None)


def m_stray():
    """M4：收尾单后面塞一条游离 📋 —— P2 必须红。"""
    return _with_plan(_SRC + "\n📋 变异用的游离记账，马上删。\n", p2)


def m_no_sheet():
    """M5：删掉收尾单标题 —— P2 必须红。"""
    return _with_plan(_SRC.replace(SHEET, "# 无关标题"), p2)


def _set_stage(src, num, state):
    """把阶段 `num` 的状态栏换成 `state`。→ 新文本，换不动就返回 None。

    🔴 2026-09-03 第二次：M10 原来靠 `replace("… | 📋 未开工", "… | ✅ 已完成")`
       给阶段 5 施加变化。**阶段 5 的状态是会动的** —— 它走到 🔄 再走到 ✅，
       那个字符串就再也匹配不上，变异静默失效、报「漏了」。
       和下面 `_set_15` 的注释是**同一个机制**，只是上次我只给 1.5 补了前提，
       没想到「被打 ✅ 的那个阶段」同样需要前提（`[[fix-regression-and-gate]]` 第四种）。
    ⇒ 变异要施加的两端**都**得自带前提：先把状态栏钉成已知值，再断言。
    """
    m = re.search(r"^\|\s*\*\*%s\*\*\s*\|([^|]*)\|([^|]*)\|" % re.escape(num),
                  src, re.M)
    if not m:
        return None
    return src[:m.start(2)] + " " + state + " " + src[m.end(2):]


def _set_15(src, state):
    """把阶段 1.5 的状态栏换成 `state`。→ 新文本，换不动就返回 None。

    🔴 2026-09-03：M10/M11 原来直接改真计划表，**前提是「1.5 还没完成」**。
       1.5 一做完（当天 12:13），两条变异同时报「漏了」—— 闸没坏，
       是**断言的前提消失了**（`[[fix-regression-and-gate]]` 第四种机制：
       闸还在，但它已经不测任何东西了）。
    ⇒ 变异必须**自带前提**：先把 1.5 按回进行中，再施加要测的那个变化。
       这样无论项目走到哪一步，这两条都还在测同一件事。
    """
    return _set_stage(src, "1.5", state)      # 判据只许一份


def m_before_15():
    """P4：1.5 还没完成，却给阶段 5 打上 ✅ —— 用户 2026-09-01 明令的顺序约束。"""
    s1 = _set_15(_SRC, "🔄 变异：按回进行中")
    if s1 is None:
        return None                     # 计划表格式变了，变异本身失效 —— 当作没逮到
    # 🔴 两端都要自带前提：1.5 按回进行中（上面），阶段 5 钉成 ✅（这里）。
    #    不能靠 replace 一个当前值 —— 阶段 5 的状态会随项目推进而变。
    s2 = _set_stage(s1, "5", "✅ 变异：钉成已完成")
    if s2 is None or s2 == s1:
        return None
    return _with_plan(s2, lambda: bool(p4()))


def m_prose_check():
    """M11：状态栏是**进行中**，但散文里提到了子步骤的 ✅ —— 不许算成已完成。

    🔴 这条变异是照着 2026-09-03 的真事故写的：我把 1.5 的状态栏改成
       「🔄 **1.5a ✅ 已落库**／1.5b 付费段未跑」，原判据 `"✅" in state` 子串命中，
       1.5 被判成已完成 ⇒ **P4 连着失效**，阶段 4–9 随时可以打 ✅ 而没人拦。
       闸当时是**绿的**，绿在它读错了地方（`[[fix-regression-and-gate]]`）。
    ⚠️ 变异要打在**闸真正盯着的落点**上（`PITFALLS` G3）：落点是 `declared_done()`
       认不认 1.5，不是 P4 自己的逻辑 —— 所以这里直接查 1.5 在不在返回值里。
    """
    s2 = _set_15(_SRC, "🔄 **1.5a ✅ 已落库**／1.5b 未跑")
    if s2 is None:
        return None                     # 状态栏格式变了，变异本身失效 —— 当作没逮到
    return _with_plan(s2, lambda: "1.5" not in declared_done())


MUTATIONS = [
    ("M1", "阶段 4 声明✅ 而音标层被删光", m_stage4),
    ("M2", "阶段 7 声明✅ 而闸文件不存在", m_stage7),
    ("M3", "阶段 8 声明✅ 而展示层还只查 dict", m_stage8),
    ("M4", "收尾单之后有游离 📋", m_stray),
    ("M5", "收尾单标题消失", m_no_sheet),
    ("M6", "带字母后缀的阶段号 2c 声明✅ 而变形层被删光", m_stage2c),
    ("M7", "收尾单凭空多一条「✅ 已做」而 DONE 里没有判据", m_fake_claim),
    ("M8", "登记了判据但判据不成立", m_broken_claim),
    ("M9", "阶段 -1 声明✅ 而探测存档不存在", m_stage_minus1),
    ("M10", "🔴 翻译（1.5）没完成就给后面的阶段打 ✅", m_before_15),
    ("M11", "🔴 进行中的状态栏里散文提到子步骤 ✅，被当成整阶段完成", m_prose_check),
]


def mutate():
    global _SRC
    _SRC = PLAN.read_text(encoding="utf-8")
    ok = 0
    for tag, why, fn in MUTATIONS:
        try:
            got = fn()
        except Exception as e:                      # noqa: BLE001
            got = None
            why += "  🔴 变异自己抛异常：%s" % e
        print("   %s %s（%s）" % (tag, "✅ 逮到" if got else "🔴 **漏了**", why))
        ok += bool(got)
    print("\n   变异 %d/%d" % (ok, len(MUTATIONS)))
    return ok


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        # 🔴 判据是**全中**，不是"中够几条"。pt 那版写的是 `== 6` 而它有 8 条变异 ——
        #    挂 2 条仍然退出 0，正是本文件通篇在骂的假绿。
        sys.exit(0 if mutate() == len(MUTATIONS) else 1)
    sys.exit(1 if report() else 0)
