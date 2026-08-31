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

ROOT = HERE.parent.parent
PLAN = ROOT / "docs" / "FR_PLAN.md"
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


# ══════════════════════════════════════════════════════════════════
# P3 —— **收尾单里说「已做」的，必须交得出东西。**
#
# 🔴🔴 起因就在这张表上：C29 白纸黑字写着「fr 今天已修（复用 es/it 的 `.sense-src`）」，
#    而组件那两行从没切过去 —— `styles.css:763` 的规则写好了、JSX 没改。
#    2026-08-31 用户读 fr 的 `banco` 页才发现，中间隔了四天。
#    **P1 只核阶段表的 ✅，收尾单里的「已做」一直是纯自述。**
#    ⚠️ 判决性实验：把源语言行退回旧写法，`contract-check-fr.tsx` 当场报 6,646 条红 ——
#      **闸是真的，它只是没人跑**（展示层改动不写库 ⇒ 任何闸都不触发）。
#
# ⚠️ fr 的收尾单与 pt 不同：C1–C28 是「**有理由地不修**」的决定，不是完成声明，
#    P3 不管它们。它守的是**自称做了**的那几条。
CLAIM = re.compile(r"^\|\s*(C[0-9]+[a-z]*)\s*\|(.*)$", re.M)
# ⚠️ 「不成立」也算：**否定结论同样是结论**（`[[record-the-negative-decision]]`）。
#    C32 判「这不是缺陷」，它的交付物就是那条例句**还在**——我得证明我没顺手删掉它。
CLAIM_WORDS = ("✅", "已做", "已解决", "已改正", "已修", "不成立")


def _has(rel, *needles):
    def f(_con):
        t = (ROOT / rel).read_text(encoding="utf-8") if (ROOT / rel).exists() else ""
        miss = [x for x in needles if x not in t]
        return (not miss), ("%s 里缺 %s" % (rel, miss) if miss else rel)
    return f


def _sql(q, want):
    def f(con):
        try:
            n = con.execute(q).fetchone()[0]
        except sqlite3.Error as e:
            return False, "查不了：%s" % e
        return (n > 0 if want == "非空" else n == 0), "%s = %s" % (want, n)
    return f


def _both(*fs):
    def f(con):
        for g in fs:
            ok, why = g(con)
            if not ok:
                return False, why
        return True, "全部满足"
    return f


DONE = {
    # C29：法语原文行必须带 FR 徽标，且契约闸里那条断言还在
    "C29": _both(_has("apps/web/src/App.tsx", '<span className="sense-src-lang">FR</span>'),
                 _has("apps/web/src/contract-check-fr.tsx", "源语言行必须带认得出的语种标签")),
    # C30：变位形式必须用带原形的 `inflections`，不是只有标签的 `inflNotes`
    "C30": _has("apps/web/src/App.tsx", "entry.inflections.length > 0", "的{x.label}"),
    # C31：日语版的对译格子已隐
    "C31": _both(_has("fr/fixes/hide_ja_translation_cells.py", "is_cell"),
                 _sql("SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0 "
                      "  AND src='ja-edition' AND (text GLOB '*[一-鿿]*' "
                      "   OR text GLOB '*[ぁ-ヿ]*')", "为零")),
    # C28：录音必须真的接上了 —— 服务层查了、展示层画了、限量规则是共用那份
    "C28": _both(_has("packages/dict-core/src/french.ts", "FROM audio", "audioQuery"),
                 _has("apps/web/src/App.tsx", "audios={entry.audio}", "export function capAudios"),
                 _sql("SELECT COUNT(*) FROM audio WHERE kind='human'", "非空")),
    # C34 自指：P3 这套机制自己在跑，就是它的交付物
    "C34": lambda _c: (len(DONE) >= 4 and bool(claims()),
                       "DONE %d 条 / 收尾单自称已做 %d 条" % (len(DONE), len(claims()))),
    # C32 判「不成立」——它的交付物就是那条例句**还在**（我没有误删它）
    "C32": _sql("SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0 "
                "  AND text LIKE 'I know I know%'", "非空"),
}


def claims():
    s = PLAN.read_text(encoding="utf-8")
    tail = s[s.index(SHEET):]
    return [(m.group(1), m.group(2).strip()) for m in CLAIM.finditer(tail)
            if any(w in m.group(2) for w in CLAIM_WORDS)]


def p3(con):
    bad = []
    for cid, rest in claims():
        f = DONE.get(cid)
        if not f:
            bad.append(("P3", "收尾单 %s 自称已做，但 DONE 里没有判据（C29 就是这么烂了四天的）：%s"
                        % (cid, rest[:44])))
            continue
        try:
            ok, why = f(con)
        except Exception as e:                      # noqa: BLE001
            bad.append(("P3", "收尾单 %s 的判据跑不了：%s" % (cid, e)))
            continue
        if not ok:
            bad.append(("P3", "收尾单 %s 说「已做」，但判据不成立：%s" % (cid, why)))
    return bad


def report(verbose=True):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        red = p1(con) + p2() + p3(con)
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
