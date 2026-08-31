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
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths                                     # noqa: E402
sys.path.insert(0, str(HERE.parent / 'pipeline'))
from harvest_pronunciation import is_sampa as _is_sampa   # noqa: E402

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
    # 🔴 同理，2d 的判据不能写「inflection 非空」也不能写「非 en-edition 非空」——
    #    那两条 2b/2c 早就让它为真了。2d 独有的交付物是**页面级 form_of**
    #    那一批，它自己带 `src` 标记 ⇒ 这条判据永不过期，且 2d 一被撤销立刻红。
    "2d": [("页面级 form_of 补进来的变形（阶段 2d）",
            "SELECT COUNT(*) FROM inflection WHERE src='pt-edition-page'")],
    # 同理，2e 独有的交付物是**法语版页面**那一批，自带 src 标记，永不过期。
    "2e": [("法语版页面 form_of 补进来的变形（阶段 2e）",
            "SELECT COUNT(*) FROM inflection WHERE src='fr-edition-page'")],
    # 2f 交付的是**关系层**的异体指针，自带 src_ref 前缀，永不过期。
    "2f": [("空白词形接上的异体指针（阶段 2f）",
            "SELECT COUNT(*) FROM sense_relation WHERE src_ref LIKE 'alt-form:%'")],
    "3": [("收词后的 dict", "SELECT COUNT(*) FROM dict")],
    # ⚠️ pt 是**双读音**语言。旧版只断言「音标层非空」——**补了一种读音、另一种是 0 也能过**。
    # ⭐ 2026-08-31 收紧（收尾单 C3 销账）：阶段 4 的表结构早已定下，实测
    #    pt-BR 321,540 / pt-PT 297,241，两边都非空 ⇒ 现在两边各查一次，缺一边就红。
    "4": [("pronunciation 音标层", "SELECT COUNT(*) FROM pronunciation"),
          ("巴葡读音 pt-BR", "SELECT COUNT(*) FROM pronunciation WHERE region='pt-BR'"),
          ("欧葡读音 pt-PT", "SELECT COUNT(*) FROM pronunciation WHERE region='pt-PT'")],
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

# 阶段 7 的契约闸：**光有文件不算交付物，跑得过才算。**
#
# 🔴🔴 2026-08-31：fr 的源语言行徽标被改回了无标签写法，而 `contract-check-fr.tsx`
#    里那条断言**一直在、也真的抓得住**（实测退回旧写法当场报 6,646 条红）——
#    它只是**没人跑**。数据层的闸挂在 `dbtool.session` 上，每次写库自动跑；
#    而展示层的改动**不写库**，于是任何闸都不会被触发，一路绿到用户读页面。
#    ⇒ 把契约闸接进这道闸：每次写库顺带跑一遍（实测 4 秒）。
#    ⚠️ 仍然只覆盖「写库时」。展示层单改不写库那一次仍然漏 —— 那要靠提交前跑，
#      已记进收尾单 C49，不留在注释里烂掉。
CONTRACT = ("apps/web/src/contract-check-pt.tsx", ["--limit", "60"])

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
    # ⚠️ 不能用「这行含 🔴」来挑 —— **断言的名字本身就带 🔴**，
    #    第一次写成那样，红的时候打印出来的是一条**通过**的断言，看着莫名其妙。
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
    #    fr 第一版把所有 `#` 开头的行都豁免了，当天就自己走过这个洞：
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
# 🔴🔴 2026-08-31 用户看 fr 的 `banco` 逮到的：法语原文行没有语种徽标。
#    而 `docs/FR_PLAN.md` 的收尾单 C29 白纸黑字写着「**fr 今天已修**（复用 es/it 的 `.sense-src`）」
#    —— **代码里没有**。账说做了，事没做，而**没有任何闸在核这件事**：
#    P1 只核**阶段表**的 ✅，收尾单那几十行「✅ 已做」一直是纯自述。
#
#    这比任何单个渲染缺陷都要紧：它决定「我说做完了」这句话你能不能信。
#    ⇒ P3：收尾单里每一条标了 ✅／已做／已解决／已改正 的，
#      **必须在 DONE 里登记一条能跑的判据**；没登记的和跑不过的，一律红。
#
# ⚠️ 判据不许写成永远为真（`SELECT 1` 那个毛病，本文件开头就在骂它）。
#    每一条问的都是「**这件事真做了才会成立**的那个具体事实」。
CLAIM = re.compile(r"^\|\s*(C[0-9]+[a-z]*)\s*\|(.*)$", re.M)
CLAIM_WORDS = ("✅", "已做", "已解决", "已改正")


def _sql(q, want):
    def f(con):
        n = _safe(con, q)
        return (n > 0 if want == "非空" else n == 0), "%s = %s" % (want, n)
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


DONE = {
    "C2":  _sql("SELECT COUNT(*) FROM example", "非空"),
    # 判据 import 生成侧那份，不在这里重写（`is_sampa` 只许有一份）
    "C5":  lambda con: (
        (lambda n: (n == 0, "X-SAMPA 冒充 IPA = %d" % n))(
            sum(1 for (v,) in con.execute("SELECT ipa FROM pronunciation")
                if _is_sampa({"ipa": v})))),
    "C8":  _sql("SELECT COUNT(*) FROM (SELECT word_id,base,label_zh FROM inflection "
                "GROUP BY 1,2,3 HAVING COUNT(*)>1)", "为零"),
    "C20": _sql("SELECT COUNT(*) FROM sense_gloss WHERE src='xref:resolved'", "非空"),
    "C21b": _sql("SELECT COUNT(*) FROM inflection WHERE src='pt-edition-prose'", "非空"),
    # C33 说的是「例句中文补完了」⇒ 问覆盖率，不问行数（行数会随收词变）
    "C33": lambda con: (
        (lambda a, b: (b and a * 100 // b >= 97,
                       "可见例句有中文 %d/%d" % (a, b)))(
            con.execute("SELECT COUNT(DISTINCT g.example_id) FROM example_gloss g "
                        " JOIN example e ON e.id=g.example_id "
                        " WHERE g.lang='zh' AND COALESCE(e.hidden,0)=0").fetchone()[0],
            con.execute("SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0"
                        ).fetchone()[0])),
    # C3 说的是「阶段 4 的交付物判据收紧成双读音各查一次」⇒ 问这道闸自己
    "C3":  lambda _con: (len(DELIVERABLE.get("4", [])) >= 3,
                         "阶段 4 交付物 %d 条" % len(DELIVERABLE.get("4", []))),
    "C39": _sql("SELECT COUNT(*) FROM sense_gloss WHERE src='invariant-plural'", "非空"),
    # C40 的交付物与 C20 同一个 src ⇒ 用它自己点名的那条内容来核，不数行数
    "C40": _sql("SELECT COUNT(*) FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
                " JOIN dict d ON d.id=s.word_id "
                " WHERE d.word='arrancamento' AND g.lang='zh'", "非空"),
    "C41": _both(_has("packages/dict-core/src/portuguese.ts", "relBySense"),
                 _has("apps/web/src/App.tsx", "sense-rels")),
    "C42": _both(
        _sql("SELECT COUNT(*) FROM pragma_table_info('sense_relation') WHERE name='hidden'",
             "非空"),
        _sql("SELECT COUNT(*) FROM sense_relation r WHERE r.sense_id IS NULL "
             "  AND COALESCE(r.hidden,0)=0 AND EXISTS("
             "  SELECT 1 FROM sense_relation q WHERE q.word_id=r.word_id AND q.kind=r.kind "
             "    AND q.target=r.target AND q.sense_id IS NOT NULL "
             "      AND COALESCE(q.hidden,0)=0)", "为零")),
    "C44": _both(_has("apps/web/src/App.tsx", "alt-of-row"),
                 _has("apps/web/src/contract-check-pt.tsx", "异体指针没渲染")),
    "C45": _both(_has("pt/pipeline/build_search_prefix.py", "blake2b"),
                 lambda con: ((lambda v: (len(v.split(":")[-1]) > 8,
                                          "库里存的指纹 %s" % v))(
                     con.execute("SELECT v FROM search_prefix_meta "
                                 " WHERE k='dict_fingerprint'").fetchone()[0]))),
    "C46": _both(_has("packages/dict-core/src/portuguese.ts", "altOfBySense"),
                 _has("apps/web/src/App.tsx", "sense-altof")),
    "C47": _has("apps/web/src/App.tsx", "x.senseId === null).slice(0, 12)"),
    # C49 自指：P3 这套机制自己在跑，就是它的交付物
    "C49": lambda _c: (len(DONE) >= 16 and bool(claims()),
                       "DONE %d 条 / 收尾单自称已做 %d 条" % (len(DONE), len(claims()))),
    "C50": _both(_has("pt/tests/test_plan_ledger.py", "_run_contract", "CONTRACT = ("),
                 lambda _c: _run_contract()),
    "C52": _both(_has("apps/web/src/App.tsx",
                      '<span className="sense-src-lang">FR</span>'),
                 _has("apps/web/src/contract-check-fr.tsx", "源语言行必须带认得出的语种标签")),
    "C53": _both(
        # ① 自指关系已隐；② 拆出来的行在库里
        _sql("SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id "
             " WHERE r.target=d.word AND COALESCE(r.hidden,0)=0", "为零"),
        _sql("SELECT COUNT(*) FROM sense_relation WHERE src_ref LIKE 'split-target:%'",
             "非空"),
        _sql("SELECT COUNT(*) FROM sense_relation WHERE COALESCE(hidden,0)=0 "
             "  AND target LIKE '%/%'", "为零")),
    "C54": _has("apps/web/src/App.tsx", "REF_SEE_ALSO"),
    "C55": _both(_has("pt/fixes/hide_citation_examples.py", "For quotations using this term"),
                 _sql("SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0 "
                      "  AND text LIKE '%see Citations:%'", "为零")),
    "C56": _both(_has("apps/web/src/App.tsx", "dupLabel", "HumanAudioRow"),
                 # 发音必须在音标之后、释义之前 —— 位置本身就是这条的交付物
                 lambda _c: ((lambda t: (
                     t.index("<HumanAudioRow", t.index("export function PortugueseEntryView"))
                     < t.index("<h3>释义</h3>", t.index("export function PortugueseEntryView")),
                     "发音区块在释义之前"))(
                     (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")))),
    # C59：pt 的例句块必须与五门通用标记一致 —— **独一份的那套类名不许再出现**
    # ⚠️ 只看**真实的 `className=`**，不看注释里提到的类名 ——
    #    第一版写成「文件里不许出现 example-list」，被我自己写在注释里的那句说明打红了。
    "C59": lambda _c: ((lambda t: (
        'className="example-list"' not in t and 'className="example-item"' not in t
        and t.count('className="ex-pt"') >= 2 and 'className="ex-ref"' in t,
        "App.tsx 里 pt 例句块的类名"))(
        (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8"))),
    "C48": _both(_has("apps/web/src/styles.css", ".alt-of-zh", ".ex-pt"),
                 lambda _c: ((lambda t: ("margin-left" in t.split(".base-pos {")[1][:200],
                                         ".base-pos 的左边距"))(
                     (ROOT / "apps/web/src/styles.css").read_text(encoding="utf-8")))),
}


def claims():
    """→ [(条目号, 处置文本)]，只含**自称已做**的行。"""
    s = PLAN.read_text(encoding="utf-8")
    tail = s[s.index(SHEET):]
    out = []
    for m in CLAIM.finditer(tail):
        cid, rest = m.group(1), m.group(2)
        if any(w in rest for w in CLAIM_WORDS):
            out.append((cid, rest.strip()))
    return out


def p3(con):
    """收尾单里说「已做」的，必须交得出东西。"""
    bad = []
    for cid, rest in claims():
        f = DONE.get(cid)
        if not f:
            bad.append(("P3", "收尾单 %s 自称已做，但 DONE 里没有判据 —— "
                              "这正是 fr 的 C29 那个洞（账说修了，代码里没有）：%s"
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
    #
    # 🔴🔴 **2026-08-31 修**：旧版是「在**真库**里找一个交付物恰好为 0 的阶段来打」。
    #    阶段全做完之后**一个都找不着** ⇒ `empty[0]` 直接 IndexError ——
    #    **账的闸的变异验证从那时起就一次都没跑起来过**（回归闸的 `mutate()` 同日
    #    发现同一类毛病：临时连接漏注册 `same_sentence`）。
    #    ⇒ 判据不许依赖「库里恰好还有没做完的事」。改成**确定性**的：
    #      打一份库的副本、把某个阶段的交付物删掉，看闸红不红。
    #    这里挑阶段 2d（`src='pt-edition-page'`，上一轮新做的那步）。
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "m.db"
        shutil.copy(paths.DB, db)
        w = sqlite3.connect(db)
        w.execute("DELETE FROM inflection WHERE src='pt-edition-page'")
        w.commit()
        w.close()
        con2 = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        got = [r for r in p1(con2) if "阶段 2d" in r[1]]
        con2.close()
    print("   M1 %s（阶段 2d 声明✅ 而把它的交付物删光）"
          % ("✅ 逮到" if got else "🔴 **漏了**：声明✅ 而交付物是 0，闸没红"))
    ok += bool(got)

    # M6：**带字母后缀的阶段号**（`2c`）声明 ✅ 而链接层还是空的 —— P1 必须红。
    #     这一条同时验两件事：① 2c 的交付物判据真的能红
    #     ② `ROW` 正则认得出 `2c` —— 照抄 fr 的那版只认数字，`2c` 会被**静默跳过**，
    #     那种漏法不会报错、只会安静地少查一个阶段，光看"✅ 全部通过"根本发现不了。
    # 🔴🔴 **2026-08-31：M6/M2/M3 三条一起修，同一个根因** ——
    #    它们只把**文档**的状态栏翻成 ✅，然后指望**世界**还是没做完的样子。
    #    写它们那天（08-30）阶段 2c/7/8 确实还没做完，所以"假装声明"就够了；
    #    做完之后**变异什么都没变**，闸当然不红，三条一起报「漏了」。
    #    ⇒ 变异必须**真的把被断言的东西拿走**：库侧删行、文件侧指向不存在的路径、
    #      代码侧指向一份退回老单表版的副本。（M1 同日同因，已改成删副本的行。）
    def _red_for(stage, con=None):
        con2 = con or sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        try:
            return [r for r in p1(con2) if ("阶段 %s" % stage) in r[1]]
        finally:
            con2.close()

    # M6：**带字母后缀的阶段号**（`2c`）—— 这一条同时验两件事：
    #     ① 2c 的交付物判据真的能红
    #     ② `ROW` 正则认得出 `2c` —— 照抄 fr 的那版只认数字，`2c` 会被**静默跳过**，
    #     那种漏法不会报错、只会安静地少查一个阶段，光看"✅ 全部通过"根本发现不了。
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "m6.db"
        shutil.copy(paths.DB, db)
        w = sqlite3.connect(db)
        w.execute("DELETE FROM inflection WHERE src<>'en-edition'")
        w.commit()
        w.close()
        got = _red_for("2c", sqlite3.connect("file:%s?mode=ro" % db, uri=True))
    print("   M6 %s（阶段 2c 声明✅ 而非 en-edition 的变形链删光）"
          % ("✅ 逮到" if got else "🔴 **漏了**：带字母的阶段号被正则漏掉了"))
    ok += bool(got)

    # M2：阶段 7 声明 ✅ 而闸文件不存在 —— P1 必须红（这条专打 `SELECT 1` 那个坑）
    #     ⚠️ **不碰真文件**（跑挂了就把闸自己弄丢了），改成把清单指向不存在的路径 ——
    #     要证明的是「这条检查能不能红」，`SELECT 1` 那种写法在这里必然过不去。
    keep_files = FILES["7"]
    try:
        FILES["7"] = [("回归闸（变异：指向不存在的路径）", "pt/tests/__no_such_gate__.py")]
        got = _red_for("7")
    finally:
        FILES["7"] = keep_files
    print("   M2 %s（阶段 7 声明✅ 而闸文件不存在）"
          % ("✅ 逮到" if got else "🔴 **漏了**：文件不存在却不红 —— 这就是 `SELECT 1` 的毛病"))
    ok += bool(got)

    # M3：阶段 8 声明 ✅ 而展示层退回老单表版 —— P1 必须红
    keep_code = CODE["8"]
    with tempfile.TemporaryDirectory() as d:
        old = Path(d) / "portuguese_old.ts"
        old.write_text("export const q = `SELECT id, word, translation FROM dict`;\n",
                       encoding="utf-8")
        try:
            CODE["8"] = [("展示层已切到多表（变异：换成老单表版）", str(old), "FROM sense")]
            got = _red_for("8")
        finally:
            CODE["8"] = keep_code
    print("   M3 %s（阶段 8 声明✅ 而展示层还只查 dict）"
          % ("✅ 逮到" if got else "🔴 **漏了**：展示层没接却不红"))
    ok += bool(got)

    # M7：**收尾单里凭空加一条「✅ 已做」** —— P3 必须红。
    #     这一条打的正是 fr 的 C29 那个洞：**账说做了、什么都没做，而闸一声不吭**。
    def _m7():
        con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        try:
            return [r for r in p3(con2) if "C99" in r[1]]
        finally:
            con2.close()
    fake = src.replace(SHEET, SHEET + "\n\n| # | 事 | 规模 |\n|---|---|---|\n"
                       "| C99 | ✅ **已做**：一件根本没做的事 | 0 |")
    got = with_plan(fake, _m7)
    print("   M7 %s（收尾单凭空多一条「✅ 已做」而 DONE 里没有判据）"
          % ("✅ 逮到" if got else "🔴 **漏了**：账可以随便说已做，没人核"))
    ok += bool(got)

    # M8：**判据不成立时也要红**（不只是"有没有登记"）。
    #     把 C42 的判据换成一个必然不成立的，P3 必须报出来。
    keep = DONE["C42"]
    try:
        DONE["C42"] = lambda _c: (False, "变异：假装这件事没做成")
        con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        got = [r for r in p3(con2) if "C42" in r[1]]
        con2.close()
    finally:
        DONE["C42"] = keep
    print("   M8 %s（登记了判据但判据不成立）"
          % ("✅ 逮到" if got else "🔴 **漏了**：判据挂了却不红"))
    ok += bool(got)

    # M4：收尾单后面塞一条游离 📋 —— P2 必须红
    got = with_plan(src + "\n📋 变异用的游离记账，马上删。\n", p2)
    print("   M4 %s" % ("✅ 逮到游离记账" if got else "🔴 **漏了**：游离 📋 没红"))
    ok += bool(got)

    # M5：删掉收尾单标题 —— P2 必须红
    got = with_plan(src.replace(SHEET, "# 无关标题"), p2)
    print("   M5 %s" % ("✅ 逮到收尾单消失" if got else "🔴 **漏了**：收尾单没了却不红"))
    ok += bool(got)

    print("\n   变异 %d/8" % ok)
    return ok


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(0 if mutate() == 6 else 1)
    sys.exit(1 if report() else 0)
