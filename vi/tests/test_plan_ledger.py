#!/usr/bin/env python3
"""**账的闸（vi）** —— `docs/VI_PLAN.md` 说的话，与库和代码对不对得上。2026-09-28。

═══ 它为什么在阶段 1 就建 ═══
ko 从阶段 -2 一路做到阶段 4b 都没有这个文件，而 `dbtool` 的挂钩当时是**静默返回** ——
每次写库什么都没做，日志照样打「■ 不变量核对通过 ✓」。
ja 就是这样**盯着绿字做完九个阶段**的。
vi 的 `dbtool` 从第一天起就把「不存在」喊出来（那是 ko 的教训做成的机制），
而喊了四个阶段之后该把它补上 —— **一道不在场的闸和一道全绿的闸，日志上不能长得一样。**

═══ 🔴🔴 ko 那份的**结构性失明**，这里从第一天就堵上 ═══
ko 的 P1 是这么写的：

    for num, title in declared_done().items():
        for what, sql in DELIVERABLE.get(num, []):   # ← 没登记就是空列表

**一个阶段声明 ✅ 而没有登记任何交付物 ⇒ 循环体一次都不执行 ⇒ 静默全绿。**
ko 的阶段 5/6/7 正是这样：声明 ✅ 却一条交付物没登记，闸对它们完全看不见
（ja 的词源层缺席三个月，同一个形状）。
⇒ **V2 专治这个**：声明 ✅ 的阶段，必须在 DELIVERABLE / FILES / CODE 里**至少登记一条**。
   `[[expectation-must-be-declared]]`：期望值要独立声明，不能从现状推 ——
   「没登记」和「登记了且通过」在 ko 那份里长得一模一样。

═══ 这道闸拦什么 ═══
    V1  阶段表标着 ✅，交付物却是空的 / 文件不在 / 代码里找不到那句话
    V2  🔴🔴 阶段标着 ✅ 而**一条交付物都没登记**（ko 的结构性失明）
    V3  记账散落：欠账表之后不许再有游离的 📋
    V4  依赖倒挂：义项层（阶段 5）没完成，阶段 8/9 不许声明 ✅
    V5  「有意不做/不建」的行没写什么会推翻它
    V6  欠账表里同一个编号出现两次
    V7  别门/跨门的账混进本表（该去 `docs/BACKLOG.md`）
    V8  **有意不建的三张表**（inflection / pronunciation_entry / collocation）偷偷长出来了
    V9  闸名单自检 ＋ 有闸欠着没跑
    V10 覆盖率判据：恒等 100% ＝ 假闸；**下限比现状低太多也判红**（松弛会藏退化）
    V11 🔴🔴 **带锁的豁免**：有意不进 V10 的覆盖率必须登记在 `COVERAGE_PENDING`，
        两头都查 —— 账被划掉而数据没变会红，数据爬过门槛而没搬进 `COVERAGE` 也会红。
        （2026-10-02：「例句的中文译文」原先只是 `COVERAGE` 末尾的一条注释，
         于是阶段表、欠账表、这里**三处一致地看不见它**，是用户问出来的。）
    V0  **这张检查表自己有没有缺口**（拿花名册比，不拿「编号连不连续」推）

用法：
    python3 vi/tests/test_plan_ledger.py
    python3 vi/tests/test_plan_ledger.py --mutate   # 变异验证

⚠️ **`--mutate` 会在运行期间原地改写 `docs/VI_PLAN.md`**（每条变异写进去、跑完还原）。
   2026-10-02 我在后台跑这套变异的同时去读计划表，读到的是**注入后的版本**，
   当场以为欠账表里多了一行 `| **W1** | 占位 |` 残留。
   ⇒ 跑这套变异的时候别碰那个文件；看到计划表里有 `占位` 先确认没有变异在跑。
"""
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))
import paths                                        # noqa: E402

ROOT = paths.ROOT
PLAN = ROOT / "docs" / "VI_PLAN.md"
TABLE = "## 三、阶段表"
SHEET = "## 五、📋 欠账"

MARKS = ("✅", "⬜", "🔄", "❌", "⚪")
ROW = re.compile(r"^\|\s*\*{0,2}(-?\d+[a-z]?)\*{0,2}\s*\|([^|]*)\|([^|]*)\|", re.M)


# ══════════════════════════════════════════════════════════════════════════
# 交付物三类。🔴 每一条都得**真的能红**。
# ⚠️ 判据不许写「表非空」如果那条从更早的阶段起就为真 —— 那对本阶段恒真＝没查。
DELIVERABLE = {
    "0": [("v3 的 16 张表都建了",
           "SELECT (SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
           "('dict','entry','sense','sense_src','sense_gloss','sense_tag',"
           "'sense_relation','pronunciation','etymology','etymology_gloss',"
           "'example','example_gloss','audio','field_src','han_spelling',"
           "'nom_spelling','noun_classifier'))>=16")],
    "5": [("sense_src 证据层", "SELECT COUNT(*) FROM sense_src"),
          ("sense 出版层", "SELECT COUNT(*) FROM sense"),
          ("sense_gloss 三语都有",
           "SELECT (SELECT COUNT(DISTINCT lang) FROM sense_gloss)>=3"),
          # 🔴 阶段 5 特有的：**W2 的判据真的在起作用**（隐藏了两万条以上）
          ("W2 判据在起作用（隐藏的证据 > 2 万）",
           "SELECT (SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL)>20000"),
          # 🔴 阶段 5b：**模型译文真的落库了，而且与白送的 zh 版释义在 `src` 上分得开**
          #    ⚠️ 这一条在 5b 回收之前是 0 ⇒ 阶段 5 的状态栏在那之前**不许写 ✅**
          ("5b 的模型译文落库了（src 分得开）",
           "SELECT (SELECT COUNT(*) FROM sense_gloss "
           "        WHERE src='model:deepseek-v4-flash')>50000"),
          # 🔴 出版层没有「整串是标点」的释义（W12，判据 import 自 criteria）
          ("出版层没有纯标点释义（W12）",
           "SELECT (SELECT COUNT(*) FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
           "        WHERE s.hidden=0 AND TRIM(g.text,'.。…:：-·　 ')='')=0")],
    "4": [("收词把库扩了一倍以上（dict > 6 万）", "SELECT (SELECT COUNT(*) FROM dict) > 60000"),
          # 🔴 阶段 4 特有的：**新收的词真的有 entry**（pt 就是栽在这 —— 收了词没人连线）
          ("本语言版/中文版建的 entry 非空",
           "SELECT COUNT(*) FROM entry WHERE src IN "
           "('vi-edition','zh-edition-trad','zh-edition-simp')")],
    "3": [("pronunciation 音标层", "SELECT COUNT(*) FROM pronunciation"),
          # 🔴 阶段 3 特有的：**六个方言点真的分开存着**。
          #    塌成一个值的话这个数会掉到 1，而行数一点没变。
          ("六个方言点都在（不是塌成一个值）",
           "SELECT (SELECT COUNT(*) FROM (SELECT DISTINCT dialect FROM pronunciation "
           "WHERE dialect IN ('ha-noi','hue','sai-gon','vinh','thanh-chuong','ha-tinh')))>=6")],
    "2": [("han_spelling 汉越字", "SELECT COUNT(*) FROM han_spelling"),
          ("nom_spelling 喃字", "SELECT COUNT(*) FROM nom_spelling"),
          # 🔴 不写「表非空」就完事：阶段 2 特有的是**定性依据真的分了档**，
          #    全是 codepoint-v1 就说明四个源白收了
          ("rule_ver 真的分了档（不是只有码位）",
           "SELECT COUNT(DISTINCT rule_ver)-1 FROM han_spelling")],
    # ⭐ **阶段 6e 的三条，每条都是「这一层真的到位了」而不是「表非空」。**
    #    🔴 V2 当场判红过：6e 声明 ✅ 而这里一条交付物都没登记 ——
    #      正是 ko 阶段 5/6/7 与 ja 词源层那种「阶段表对没列进去的层结构性失明」。
    # ⭐ **阶段 6e 的三条，每条都是「这一层真的到位了」而不是「表非空」。**
    #    🔴 V2 当场判红过：6e 声明 ✅ 而这里一条交付物都没登记 ——
    #      正是 ko 阶段 5/6/7 与 ja 词源层那种「阶段表对没列进去的层结构性失明」。
    #    ⚠️ 每条都写成「判据式」SQL（返回真/假），与阶段 6/7 现有那几条同一写法。
    "6e": [("花钱买来的例句中文译文 > 7 万条",
            "SELECT (SELECT COUNT(*) FROM example_gloss "
            "        WHERE lang='zh' AND src LIKE 'model%') > 70000"),
           # 🔴 **读者口径**，不是「表里有多少行」
           ("读者口径：可出版例句里有中文译文的 ≥ 97%",
            "SELECT 100.0 * (SELECT COUNT(DISTINCT g.example_id) FROM example_gloss g "
            " JOIN example e ON e.id=g.example_id WHERE e.hidden=0 AND g.lang='zh') "
            " / (SELECT COUNT(*) FROM example WHERE hidden=0) >= 97.0"),
           # 🔴 **反向断言**：隐藏的例句上不许有花钱买的译文（与例句层闸 X8 同一条规矩）
           ("隐藏的例句上没有付费译文",
            "SELECT (SELECT COUNT(*) FROM example_gloss g JOIN example e "
            "        ON e.id=g.example_id WHERE e.hidden=1 "
            "        AND g.src LIKE 'model%') = 0")],
    "6": [("example 例句层", "SELECT COUNT(*) FROM example"),
          ("sense_relation 关系层", "SELECT COUNT(*) FROM sense_relation"),
          ("noun_classifier 量词层", "SELECT COUNT(*) FROM noun_classifier"),
          ("audio 录音层", "SELECT COUNT(*) FROM audio"),
          # 🔴 阶段 6 特有的三条，每条都是「这一层的判据真的在起作用」而不是「表非空」：
          #    ① B17 的隐藏量在**正确判据**的量级上（naive 判据会是它的 11 倍）
          ("B17 判据在起作用且没被放宽（1,200–5,000 行）",
           "SELECT (SELECT COUNT(*) FROM sense_relation "
           "        WHERE hidden_why='redundant-related') BETWEEN 1200 AND 5000"),
          #    ② B12 真的被自己并过（schema 的唯一键挡不住）
          ("B12：同一 (词, Commons 键) 没有两行",
           "SELECT (SELECT COUNT(*) FROM (SELECT word_id, commons_key FROM audio "
           "        GROUP BY word_id, commons_key HAVING COUNT(*)>1))=0"),
          #    ③ 跨版收割真的收了十二版（只查表非空的话少收十一版也全绿）
          ("例句真的收了十二份切片",
           "SELECT (SELECT COUNT(DISTINCT src) FROM example)>=12")],
    "7": [("etymology 词源层", "SELECT COUNT(*) FROM etymology"),
          # 🔴 阶段 7 特有的三条，都是「这一层的判据真的在起作用」而不是「表非空」：
          #    ① `entry.etym_type` 真的填了 —— 这一列从阶段 0 建着、到阶段 6 一直是 0 行
          ("entry.etym_type 真的填了（> 2 万行）",
           "SELECT (SELECT COUNT(*) FROM entry WHERE etym_type IS NOT NULL)>20000"),
          #    ② 新加的 `compound` 值域真的有行（加了值域而没人写＝ B7 那种死条目）
          ("etym_type 的新值 `compound` 有行",
           "SELECT (SELECT COUNT(*) FROM entry WHERE etym_type='compound')>5000"),
          #    ③ **中文词源是白送的** —— zh 那一支掉了就说明判据把它判成垃圾了
          ("中文词源收进来了（zh 覆盖 > 3,000 词形）",
           "SELECT (SELECT COUNT(DISTINCT word_id) FROM etymology "
           "        WHERE src LIKE 'zh-%')>3000")],
    "1": [("dict 骨架", "SELECT COUNT(*) FROM dict"),
          ("entry 词条层", "SELECT COUNT(*) FROM entry"),
          # 🔴 不写「表非空」就完事：阶段 1 特有的那条是**表意词头一个都没混进来**，
          #    而它是用户 2026-09-28 那个决定的唯一落点。
          ("entry_type 真的分了类（不是全 word）",
           "SELECT COUNT(DISTINCT entry_type)-1 FROM dict")],
}

FILES = {
    "-2": [("路径唯一真相源", "vi/paths.py"),
           ("写库闸门", "vi/dbtool.py")],
    "-1": [("阶段 -1 探针", "vi/probes/probe_sources.py"),
           ("探测结果存档", "data/work/vi/probe/probe_sources.txt")],
    "0": [("建表脚本", "vi/pipeline/build_v3_schema.py")],
    "1": [("判据唯一的家", "vi/pipeline/criteria.py"),
          ("骨架建库", "vi/pipeline/build.py"),
          ("词条层建库", "vi/pipeline/build_entry_layer.py"),
          ("主源裁决探针", "vi/probes/probe_primary_source.py"),
          # 🔴 闸自己也是交付物。不登记 ⇒ 它被删掉不会有人说话
          #    （`vi/gates.py` 的 self_check ③ 反过来查这件事，两边互相当闸）
          ("骨架闸", "vi/tests/test_skeleton.py"),
          ("闸名单", "vi/gates.py"),
          ("闸的跑批入口", "vi/run_gates.py")],
    "4": [("收词脚本", "vi/pipeline/ingest_editions.py")],
    "6e": [("例句翻译跑批", "vi/pipeline/translate_examples.py"),
           ("DeepSeek 跑批器（带定价窗口无条件播报）", "vi/pipeline/ds_batch.py"),
           ("答案文件（第一版全量）", "data/work/vi/example_zh/all.jsonl"),
           ("答案文件（判据收窄后的补跑）", "data/work/vi/example_zh/redo2.jsonl")],
    "6": [("阶段 6 判据唯一的家", "vi/pipeline/stage6_sources.py"),
          ("阶段 6 裁决探针", "vi/probes/probe_stage6.py"),
          ("裁决存档", "data/work/vi/probe/probe_stage6.txt"),
          ("例句层建库", "vi/pipeline/build_example_layer.py"),
          ("关系层建库", "vi/pipeline/build_relation_layer.py"),
          ("量词层建库", "vi/pipeline/build_classifier_layer.py"),
          ("录音层建库", "vi/pipeline/build_audio_layer.py"),
          ("例句层闸", "vi/tests/test_example_layer.py"),
          ("关系与量词闸", "vi/tests/test_relation_layer.py"),
          ("录音层闸", "vi/tests/test_audio_layer.py"),
          # R19 逮到的那个缺陷的修复脚本 —— 登记它，被删掉才会有人说话
          ("纯表意词头清理（R19 逮到的）", "vi/fixes/fix_ideograph_headwords.py")],
    "7": [("词源判据唯一的家", "vi/pipeline/etym_sources.py"),
          ("词源层建库", "vi/pipeline/build_etymology_layer.py"),
          ("词源层闸", "vi/tests/test_etymology_layer.py")],
    "5": [("义项层建库", "vi/pipeline/build_sense_layer.py"),
          ("义项层闸", "vi/tests/test_sense_layer.py"),
          # 阶段 5b
          ("跑批器（带定价窗口播报）", "vi/pipeline/ds_batch.py"),
          ("中文释义翻译", "vi/pipeline/translate_glosses.py"),
          ("纯标点释义清理（W12）", "vi/fixes/fix_punctuation_glosses.py")],
    "3": [("音标判据唯一的家", "vi/pipeline/pron_sources.py"),
          ("按音节拼音标（阶段 3b）", "vi/pipeline/compose_pronunciation.py"),
          ("拼法的留出验证探针", "vi/probes/probe_syllable_ipa.py"),
          ("验证存档", "data/work/vi/probe/probe_syllable_ipa.txt"),
          ("音标层建库", "vi/pipeline/build_pronunciation.py"),
          ("音标层闸", "vi/tests/test_pron_layer.py")],
    "2": [("汉字表记判据唯一的家", "vi/pipeline/han_sources.py"),
          ("汉字层建库", "vi/pipeline/build_han_layer.py"),
          ("汉字层闸", "vi/tests/test_han_layer.py")],
    # 阶段 8。🔴 外锚闸登记在这里**而不是阶段 6/7** —— 它是阶段 8 的交付物，
    #    锚的是五层。登记它之后 `gates.self_check()` 第③条才不报红（两边互相当闸：
    #    2026-10-02 建完闸没登记，**V9 当场逮到**）。
    "8": [("外锚闸·五层 vs dump", "vi/pipeline/verify_layers_vs_dump.py"),
          ("回归闸", "vi/tests/test_no_regression.py"),
          ("空白页判据唯一的家", "vi/pipeline/coverage.py")],
    # 阶段 9：展示层。🔴 三件都登记 —— 服务层/映射表/视图任意一个被删掉都该有人说话。
    "9": [("服务层", "packages/dict-core/src/vietnamese.ts"),
          ("映射表唯一的家", "packages/dict-labels/src/vi.ts"),
          ("展示层契约闸", "apps/web/src/contract-check-vi.tsx"),
          ("查询计划闸", "vi/probes/query_plans.py")],
}

# 「库里查得到 ≠ 读者看得见」——声明 ✅ 的阶段，代码里必须真有那句话
CODE = {
    "1": [("收词判据没被 pos 代理偷换", "vi/pipeline/criteria.py", "def is_han_headword"),
          ("不去声调的归一", "vi/pipeline/criteria.py", "def norm_vi"),
          ("读者口径的词性值域", "vi/tests/test_skeleton.py", "_pos_seg_bad")],
    "0": [("有意不建的三张表写了推翻条件", "vi/pipeline/build_v3_schema.py", "NOT_BUILT")],
    "4": [("不收哪些的判据写在 criteria 里", "vi/pipeline/criteria.py", "def is_not_a_gloss")],
    "5": [("W2 的判据写进 pipeline 且可 import",
           "vi/pipeline/criteria.py", "def gloss_is_just_spelling"),
          ("证据层永不编辑有闸守着", "vi/tests/test_sense_layer.py", "E7"),
          # 🔴 5b：定价窗口**无条件播报**（这条规则我记了三次仍说错两次 ⇒ 只能做成机制）
          ("跑批前无条件播报定价窗口", "vi/pipeline/ds_batch.py", "def announce_window"),
          ("控制组覆盖每一种坏法", "vi/pipeline/translate_glosses.py", "PROBE"),
          ("释义有没有内容的判据在 criteria 里", "vi/pipeline/criteria.py",
           "def gloss_has_content")],
    "6e": [# 🔴 开跑前量 `example.text` 自己的那四条判据，一条都不许消失
           ("不是例句：元数据按登记表判", "vi/pipeline/stage6_sources.py", "_META_LABELS"),
           ("不是例句：源头没给越南语正文", "vi/pipeline/stage6_sources.py",
            "def is_not_vietnamese"),
           ("出处判据**按分支**写、不共用安全网", "vi/pipeline/stage6_sources.py",
            "_CITATION_YEAR"),
           ("内嵌英译**按版登记**，不写成形状判据", "vi/pipeline/stage6_sources.py",
            "INLINE_EN_IN_TEXT"),
           # 🔴 6e 之后例句层只能原地同步 —— `--rebuild` 会删掉付费数据
           ("6e 之后的原地同步路径", "vi/pipeline/build_example_layer.py", "def _sync"),
           ("回收顺序即优先级（新版本压住旧的）", "vi/pipeline/translate_examples.py",
            "replace=rep"),
           ("行数归一在代码里做、不靠 prompt", "vi/pipeline/translate_examples.py",
            "src_lines == 1")],
    "6": [("译文语种按版定、不按字段名定", "vi/pipeline/stage6_sources.py", "TR_LANG"),
          ("B17 的 SUBSUME 有意排除 paronym", "vi/pipeline/stage6_sources.py", "SUBSUME"),
          ("B12 用八门共用那一份归一键", "vi/pipeline/build_audio_layer.py", "commons_key"),
          # 🔴 R19 逮到的根因做成机制：判据只能有一份，`han_sources` 从 criteria import
          ("表意文字判据只有一份（兜底在 criteria 里）",
           "vi/pipeline/han_sources.py", "from criteria import _IDEO_BLOCKS, is_ideograph"),
          ("收词判据容许汉字圈标点/IDS", "vi/pipeline/criteria.py", "_CJK_PUNCT")],
    "7": [("「整段是汉字」在词源段上**有意是严格版**",
           "vi/pipeline/etym_sources.py", "def _all_ideographs"),
          ("魔术字先清洗再判断（内嵌 5,390 段）",
           "vi/pipeline/etym_sources.py", "def clean_etym_text"),
          ("来源模板逐个读过 expansion 才归档",
           "vi/pipeline/etym_sources.py", "ORIGIN_TEMPLATES"),
          ("有意不建 origin_lang 列并写了推翻条件",
           "vi/pipeline/etym_sources.py", "etymology_origin")],
    "3": [("方言值域与三类混装写在判据里", "vi/pipeline/pron_sources.py", "NOT_VIETNAMESE"),
          ("B10 的判据是 GLOB 不是 LIKE", "vi/tests/test_pron_layer.py", "GLOB")],
    "2": [("汉越字/喃字的定性依据逐条写了可信度", "vi/pipeline/han_sources.py", "RULES"),
          ("Unicode 版本上限有兜底且有闸盯着", "vi/tests/test_han_layer.py", "h6_unicode_ceiling")],
}

# 阶段 0 明写「有意不建」的三张表。V8 查它们没有偷偷长出来。
NOT_BUILT_TABLES = ("inflection", "pronunciation_entry", "collocation")


def _plan():
    return PLAN.read_text(encoding="utf-8")


def _status(state):
    """状态栏 → 里面**最先出现的那一个**标记。

    🔴 de 2026-09-03 的真事故：判据写成 `"✅" in state`（子串命中），
       而状态栏写的是「🔄 **1.5a ✅ 已落库**／1.5b 未跑」—— 一个诚实的进行中状态 ——
       整阶段被判成已完成。**闸没坏，是它读错了地方。**
    """
    pos = [(state.index(m), m) for m in MARKS if m in state]
    return min(pos)[1] if pos else None


def _table_text():
    s = _plan()
    i = s.index(TABLE)
    j = s.find("\n## ", i + 4)
    return s[i:j if j > 0 else len(s)]


def declared_done():
    out = {}
    for m in ROW.finditer(_table_text()):
        if _status(m.group(3)) == "✅":
            out[m.group(1)] = m.group(2).strip().strip("*").strip()
    return out


# ══════════════════════════════════════════════════════════════════════════
def v1(con):
    """阶段表声明 ✅ 的，交付物必须真的在。"""
    bad = []
    for num, title in sorted(declared_done().items()):
        for what, sql in DELIVERABLE.get(num, []):
            try:
                n = con.execute(sql).fetchone()[0]
            except sqlite3.Error as e:
                bad.append(("V1", "阶段 %s 的交付物查不了：%s（%s）" % (num, what, e)))
                continue
            if not n:
                bad.append(("V1", "阶段 %s「%s」声明 ✅，但**%s 是 0**"
                            % (num, title[:20], what)))
        for what, rel in FILES.get(num, []):
            if not (ROOT / rel).exists():
                bad.append(("V1", "阶段 %s「%s」声明 ✅，但**%s 不存在**（%s）"
                            % (num, title[:20], what, rel)))
        for what, rel, need in CODE.get(num, []):
            p = ROOT / rel
            if not p.exists():
                bad.append(("V1", "阶段 %s 声明 ✅，但 %s 不存在" % (num, rel)))
            elif need not in p.read_text(encoding="utf-8"):
                bad.append(("V1", "阶段 %s「%s」声明 ✅，但 %s 里找不到 `%s` —— "
                                  "**库里查得到 ≠ 读者看得见**" % (num, what, rel, need)))
    return bad


def v2():
    """🔴🔴 声明 ✅ 的阶段，**必须至少登记过一条交付物**。

    这是 ko 那份的结构性失明：`DELIVERABLE.get(num, [])` 拿不到就是空列表，
    循环一次都不跑 ⇒ 阶段 5/6/7 声明 ✅ 而闸完全看不见它们。
    `[[gate-registers-status-quo-as-spec]]` 的近亲：**闸「没查」和「查过且通过」
    在输出上长得一样，于是再也不会有人问它查没查。**
    """
    bad = []
    for num, title in sorted(declared_done().items()):
        n = len(DELIVERABLE.get(num, [])) + len(FILES.get(num, [])) + len(CODE.get(num, []))
        if n == 0:
            bad.append(("V2", "阶段 %s「%s」声明 ✅，而 DELIVERABLE/FILES/CODE 里"
                              "**一条交付物都没登记** —— 这道闸对它是瞎的。"
                              "先登记再声明完成。" % (num, title[:24])))
    return bad


def v3():
    """欠账表之后不许有游离的 📋 —— 新记账只能进那张表。"""
    s = _plan()
    if SHEET not in s:
        return [("V3", "欠账表章节不存在（%s）—— 记账没有家，必然重新散开" % SHEET)]
    tail = s[s.index(SHEET):]
    loose = [ln.strip() for ln in tail.splitlines()
             if ln.strip().startswith("📋") and not ln.strip().startswith("|")]
    if loose:
        return [("V3", "欠账表之后有 %d 条游离记账（应进表）：%s"
                 % (len(loose), loose[0][:50]))]
    return []


def v4():
    """依赖倒挂：后面的阶段不许在它依赖的阶段之前声明 ✅。

    🔴🔴 **2026-10-02：这条检查一度结构性恒绿，而是它的变异报出来的。**
    第一版只有一条规则「阶段 5 没完成 ⇒ 8/9 不许 ✅」。阶段 5 在 2026-10-02 落成 ✅
    之后，`if "5" in done: return []` 这一句**永远先返回** ⇒ V4 再也不可能响，
    而变异 M4（把 9 标成 ✅）当场「没逮到」。
    ⚠️ 这是**前提过期**，不是锚过期 —— 锚（结构）好得很，是它要创造的那个**条件**
    在现实里已经不可能了。`[[permanently-red-gate-masks-real-reds]]` 的镜像：
    **一条永远绿的检查信号量也是零。**
    ⇒ 不删不松，**改成一张会随进度推进的依赖表**：每条规则各自带前提，
      只要还有一条前提成立，V4 就仍有信号。
    """
    done = declared_done()
    bad = []
    # (前提阶段, 后续阶段们, 为什么)
    for dep, laters, why in (
            ("5", ("8", "9"),
             "**闸与展示层建在还没有内容的库上，会把「空」登记成「规格」**"),
            # ⭐ 阶段 5 完成后接棒的那一条：展示层不许抢在闸之前。
            #    `[[it-display-layer-stage8]]`：接上展示层是独立一道闸，
            #    而没有数据层的闸兜着，展示层的绿灯什么也不保证。
            ("8", ("9",),
             "**没有验收闸兜着的展示层，绿灯什么也不保证**（it 那门的教训）"),
    ):
        if dep in done:
            continue
        late = [n for n in laters if n in done]
        if late:
            bad.append(("V4", "阶段 %s 还没完成，但阶段 %s 已声明 ✅ —— %s"
                        % (dep, "、".join(late), why)))
    return bad


# 🔴 **引用别门的否定结论 ≠ vi 自己下了否定结论。**
#    第一版判据只找关键词，当场把 §2.4 的「⇒ ko「有意不做 `search_prefix`」的前提
#    在 vi 上不成立」判红 —— 那句话是在**引用 ko 的决定并说它对 vi 不适用**，
#    本身不需要推翻条件。`[[criteria-narrower-than-you-think]]`：判据比它要描述的东西宽。
#    ⚠️ 收窄得很紧：必须是「<别门>「…有意不X…」」这个带引号的归属形式才放过，
#      光提到 ko 两个字不算（否则 vi 自己的决定只要行里提一句 ko 就能蒙混过去）。
_CITED = re.compile(r"(ko|ja|es|it|fr|pt|de|en|ru|nl|zh)「[^」]*有意不[做建填收][^」]*」")


def v5():
    """「有意不做/不建」必须写什么会推翻它。

    🔴 `[[record-the-negative-decision]]`：否定结论**光落账不够** ——
       闸天然管不到否定结论（它没有交付物），ja 那条错结论我引用三次零复核。
    """
    bad = []
    keys = ("有意不做", "有意不建", "有意为空", "有意不收", "有意不填")
    undo = ("推翻", "什么会推翻", "翻案")
    for ln in _plan().splitlines():
        if not any(k in ln for k in keys):
            continue
        if _CITED.search(ln):
            continue
        if any(u in ln for u in undo):
            continue
        bad.append(("V5", "这一行声明了否定结论却**没写什么会推翻它**：%s"
                    % ln.strip()[:72]))
    return bad


def _sheet_rows():
    s = _plan()
    if SHEET not in s:
        return []
    tail = s[s.index(SHEET):]
    out = []
    for ln in tail.splitlines():
        m = re.match(r"^\|\s*\*{0,2}~?~?(W\d+)~?~?\*{0,2}\s*\|", ln.strip())
        if m:
            out.append((m.group(1), ln))
    return out


def v6():
    """欠账表里同一个编号出现两次 —— 读者按哪行都不算读错。"""
    seen, dup = set(), []
    for num, _ in _sheet_rows():
        if num in seen:
            dup.append(num)
        seen.add(num)
    if dup:
        return [("V6", "欠账表里编号重复：%s" % "、".join(sorted(set(dup))))]
    return []


def v7():
    """别门/跨门的账混进本表 —— 该去 `docs/BACKLOG.md`。

    🔴 `[[top-level-backlog]]`：建顶层账本之前六门六种格式，
       「这仓库总共欠什么」没人答得出。
    """
    # 🔴🔴 **判据收窄过一次（2026-10-03），而逮到它的是一条正当的行文。**
    #    第一版是**子串**匹配 `"de "` —— 于是 W9 行里的「Unico**de** 变体」被判成
    #    「这一行带着 de（德语）的账」。`[[criteria-narrower-than-you-think]]`：
    #    判据比它要描述的东西宽。⇒ 语种码必须是**独立的词**（前面不是字母）。
    #    ⚠️ 收窄之后仍然逮得到它要治的东西：`es 那边也有这个毛病` 里的 `es` 在词边界上
    #      （M7 那条变异就是这个形状，收窄后实测照样红）。
    # 🔴🔴 **第二次收窄（2026-10-03）**：`fr 版` 被判成「这一行带着 fr 的账」，
    #    而在 vi 的语境里 **`<lang> 版` 指的是「那个语言的维基版本」** —— 我们收割
    #    十二个版本，谈论 `fr 版`/`ko 版`/`nl 版` **正是 vi 自己的事**，不是别门的账。
    #    ⚠️ 两次收窄是同一个病的两种形状：第一次 `de ` 匹配到了**单词内部**
    #      （Unico**de**），这一次匹配到了**正当的语义单位**（`fr 版`）。
    #      `[[criteria-narrower-than-you-think]]`：判据比它要描述的东西宽，又一次。
    #    ⇒ 语种码后面跟着 `版` / `-edition` / `版的` 的，一律放过。
    _LANGS = ("es", "it", "fr", "pt", "de", "ja", "ko", "en", "ru", "nl", "pl")
    others = re.compile(r"(?<![A-Za-z])(%s)(?=[\s　])(?!\s*(版|-edition))"
                        % "|".join(_LANGS))
    groups = ("八门", "六门", "跨门", "跨语种")
    bad = []
    for num, ln in _sheet_rows():
        # 「对照」「同形」这类是**引用别门的教训**，不是别门的账，要放过。
        # 🔴🔴 **第三次收窄（2026-10-05）：豁免表原先硬编码 `与 ko`/`ja 的` 两个语种**
        #    ⇒ 2026-10-05 写 W27 时引用的是 **en** 那边的一个 bug
        #      （「与 en 那边 `sense.rank=0` 哨兵的 bug **不是同一件事**」），当场判红。
        #    ⚠️ 这是**枚举式豁免的通病**：它对「同一种写法、换个语种」结构性失明，
        #      而被咬的时候人的第一反应是去改自己的行文（我差点就那么做了）。
        #    ⇒ 按**含义**改：`与 <语种>` / `<语种> 的` / `<语种> 那边` 都是**引用**，
        #      而真正的别门账长成「es 那边也有这个毛病」（V7 的变异就是这一句）——
        #      区别在于引用里那个语种码后面跟的是「的」「那边」「同形」这类**指代词**。
        #    ⚠️ 收窄之后变异仍然红（跑过 `--mutate` 确认），所以不是把闸拆松了。
        if any(x in ln for x in ("对照", "同形", "教训")):
            continue
        if any("与 %s" % lg in ln or "%s 的" % lg in ln or "%s 那边的" % lg in ln
               for lg in _LANGS):
            continue
        m = others.search(ln)
        hit = ([m.group(1)] if m else []) + [g for g in groups if g in ln]
        if hit:
            bad.append(("V7", "欠账 %s 这一行带着「%s」—— 别门/跨门的账要去 "
                              "`docs/BACKLOG.md`，各门计划表只记自己的"
                        % (num, hit[0].strip())))
    return bad


def v8(con):
    """🔴 **反向断言**：阶段 0 明写「有意不建」的三张表，不许偷偷长出来。

    ⚠️ 这条与 `build_v3_schema.py --check` 是同一件事的两个入口。
       留两份不是重复 —— `--check` 要人主动跑，这一条**每次写库自动跑**。
       下次从别门拷脚本，`inflection` 就会被带回来（B7 那个形状）。
    """
    live = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    bad = []
    for t in NOT_BUILT_TABLES:
        if t in live:
            bad.append(("V8", "`%s` **有意不建，而它在库里** —— "
                              "要么是从别门拷脚本带回来的，要么是有人翻了案而没改计划。"
                              "翻案的话先去 `build_v3_schema.NOT_BUILT` 把推翻条件划掉" % t))
    return bad


def v9():
    """闸名单自检 ＋ 有闸欠着没跑。

    🔴 `[[lesson-must-become-mechanism]]`：闸建好了而「谁逼人跑它」从来没做成机制 ——
       ko 的 11 道闸里 3 道从没人跑过、1 道红着一整天。
       「存在／有入口／覆盖这门语言／真被跑」是四道独立关卡，这一条守最后一关。
    """
    try:
        sys.path.insert(0, str(ROOT / "vi"))
        import gates
    except Exception as e:                       # noqa: BLE001
        return [("V9", "读不到 `vi/gates.py`（%s）—— 整套机制靠它" % e)]
    bad = [("V9", "闸名单自身有问题：" + b) for b in gates.self_check()]
    try:
        cur = gates.load()
    except BaseException as e:                   # noqa: BLE001
        return bad + [("V9", "欠账文件读不动：%s" % e)]
    for n in sorted(cur):
        bad.append(("V9", "闸「%s」欠着没跑（%s 弄脏的）⇒ `python3 vi/run_gates.py`"
                    % (n, cur[n].get("tag", "?"))))
    return bad


# ── V10：覆盖率判据自检 ──────────────────────────────────────────────────
# 🔴🔴 **恒等 100% 的覆盖率 ＝ 假闸**。ja 真犯过：分母里套了分子的条件
#    （「有释义的词形 / 有释义的词形」＝ 100%，而它看起来和真闸一模一样）。
# 🔴 第二件事同样重要：**下限低于现状 ＝ 把退化藏进松弛里**。
#    音标闸上实测过 —— 覆盖率到了 98.3% 而下限留在 94.0，掉四个点都不会红。
#    ⇒ V10 两头都查：**恒等 100% 判红，现状比下限高出 3 个点以上也判红**。
COVERAGE = {
    "释义（读者口径）": (
        "SELECT COUNT(DISTINCT s.word_id) FROM sense s JOIN sense_gloss g "
        "ON g.sense_id=s.id WHERE s.hidden=0",
        "SELECT COUNT(*) FROM dict", 75.0),
    "音标（读者口径）": (
        "SELECT COUNT(DISTINCT word_id) FROM pronunciation",
        "SELECT COUNT(*) FROM dict", 98.0),
    "汉字表记": (
        "SELECT COUNT(DISTINCT word_id) FROM "
        "(SELECT word_id FROM han_spelling UNION SELECT word_id FROM nom_spelling)",
        # 🔴 这个下限**第一版写的是 45.0，而 V10 当场判红**：实测 49.7%，
        #    高出 4.7 个点 ⇒ 掉四个点都不会红。提到 48.0。
        #    ⭐ V10 第一次跑就逮到我自己设松的下限 —— 它要治的正是这件事。
        "SELECT COUNT(*) FROM dict", 48.0),
    # ── 阶段 6 的四条，**都是读者口径**（有多少词形真的能看见这一层）────────
    "例句（读者口径）": (
        "SELECT COUNT(DISTINCT word_id) FROM example WHERE hidden=0",
        "SELECT COUNT(*) FROM dict", 35.0),
    "语义关系（读者口径）": (
        "SELECT COUNT(DISTINCT word_id) FROM sense_relation WHERE hidden=0",
        "SELECT COUNT(*) FROM dict", 28.5),
    "量词": (
        "SELECT COUNT(DISTINCT word_id) FROM noun_classifier",
        "SELECT COUNT(*) FROM dict", 4.0),
    "录音": (
        "SELECT COUNT(DISTINCT word_id) FROM audio WHERE hidden=0",
        "SELECT COUNT(*) FROM dict", 3.5),
    "词源（读者口径）": (
        "SELECT COUNT(DISTINCT word_id) FROM etymology",
        "SELECT COUNT(*) FROM dict", 36.5),
    # ⭐ 阶段 5b 的落点：**中文释义覆盖从 10.6% 跳到 75.48%**，与总释义覆盖相等
    #    ——「每个有可出版释义的词形都有中文」。下限在**确认落点之后**才上调（不是提前调）。
    "中文释义（读者口径）": (
        "SELECT COUNT(DISTINCT s.word_id) FROM sense s JOIN sense_gloss g "
        "ON g.sense_id=s.id WHERE s.hidden=0 AND g.lang='zh'",
        "SELECT COUNT(*) FROM dict", 73.0),
    # ⭐⭐ **阶段 6e 的落点，2026-10-03 从 `COVERAGE_PENDING` 搬过来的。**
    #    搬家不是我想起来的，是 **V11 的带锁豁免当场判红**逼的：
    #      「豁免项『例句中文（读者口径）』已经到 99.98%（门槛 50.0%）——
    #        把它从 `COVERAGE_PENDING` 搬进 `COVERAGE` 并锁下限，豁免不许当 V10 的后门」
    #    ⇒ 这条机制是 2026-10-02 **因为同一笔账差点整个消失**才建的（当时阶段 6e
    #      在阶段表/欠账表/本表里三处一致地不存在），**建好的第二天它就兑现了一次**。
    #      `[[lesson-must-become-mechanism]]` 的正面例子。
    # ⚠️ 下限 **97.5**：实测 99.98%（76,658 / 76,670），差的 12 条逐条读过 ——
    #    🔴 我第一版写 96.0，**V10 当场判红**（超出下限 4.0 点 > SLACK 3.0）——
    #      「松弛会把退化藏起来」。留 2.5 个点给源头增量，不留更多。
    #    3 条是 fr 版漏进来的 JavaScript 代码、4 条不是例句、
    #    5 条本来就没什么可译的（`Ú, liu, cống, xê, xang, xừ.` 是越南传统音名、
    #    `Win XP`、`Lôm lốp` 叠音形式）。留 4 个点的余量给源头增量，不留更多
    #    （`[[ship-dont-measure-in-circles]]`：松弛会把退化藏起来，V10 盯着这件事）。
    "例句中文（读者口径）": (
        "SELECT COUNT(DISTINCT g.example_id) FROM example_gloss g "
        "JOIN example e ON e.id=g.example_id WHERE e.hidden=0 AND g.lang='zh'",
        "SELECT COUNT(*) FROM example WHERE hidden=0", 97.5),
}
SLACK = 3.0

# ══════════════════════════════════════════════════════════════════════════
# 🔴🔴 **带锁的豁免**：有意不进 `COVERAGE` 的覆盖率，必须在这里登记，不许写成注释。
#
# ═══ 它是怎么来的（2026-10-02，用户问出来的）═══
# 「例句的中文译文」原先是 `COVERAGE` 末尾的一条注释，写着「有意不进这张表：实测 0.66%，
# 下限只能写 0，而 0 对 V10 的松弛判据没有意义」。**那个理由在局部是对的** ——
# 正因为它对，它就再也没有被质疑过，于是：
#     阶段表没有 6e 行 ／ 欠账表没有编号 ／ 这里只有一条注释
# 三处一致地看不见它，而 ko 的阶段 6 标题里「例句翻译」是写明的子阶段（6d，覆盖 100.00%）。
# 用户问「计划里为什么没有例句翻译」时，闸一次都没响。
# `[[criterion-true-half-vouches-for-false-half]]`：判据前半句真，就给后半句背了书。
# `[[lesson-must-become-mechanism]]`：**做成机制的全守住了、写成文字的一条没守住。**
#
# ═══ 锁是双向的（单向的锁只是个下限）═══
#   ① 账那头：现状还在门槛以下 ⇒ 欠账表里那一行**必须开着**。
#      把账划掉而数据没变 ⇒ 红（`[[fix-regression-and-gate]]`：「已接受」≠「不再看」）。
#   ② 数据那头：现状爬过门槛 ⇒ 红，**逼人把它搬进 `COVERAGE` 并锁下限**。
#      ——「跑完了却没人把下限锁上」正是 V10 要治的那种松弛，豁免不该成为它的后门。
#
# 写法：名字 → (分子 SQL, 分母 SQL, 门槛%, 欠账编号)
# ⭐ **2026-10-03：这张表现在是空的，而它空着本身是一条记录。**
#    唯一的住户「例句中文（读者口径）」在 6e 跑完之后被 V11 判红、搬进了 `COVERAGE`
#    （下限 96.0）。⚠️ **不要因为空了就把这套机制删掉** —— 它从建成到兑现只隔了一天，
#    而它要治的那个病（「有意不量」的理由在局部成立、于是永不被质疑）是反复发作的。
#    下一个「现在只能写 0 所以先不进 COVERAGE」的东西，登记到这里来。
COVERAGE_PENDING: dict[str, tuple[str, str, float, str]] = {}


def v11(con):
    """带锁的豁免：`COVERAGE_PENDING` 的两头都查。"""
    bad = []
    rows = dict(_sheet_rows())
    for name, (num_sql, den_sql, until, wid) in sorted(COVERAGE_PENDING.items()):
        try:
            n = con.execute(num_sql).fetchone()[0]
            d = con.execute(den_sql).fetchone()[0]
        except sqlite3.Error as e:
            bad.append(("V11", "豁免项「%s」查不了：%s" % (name, e)))
            continue
        if not d:
            bad.append(("V11", "豁免项「%s」的分母是 0" % name))
            continue
        pct = 100.0 * n / d
        # ① 数据那头
        if pct >= until:
            bad.append(("V11", "🔴🔴 豁免项「%s」已经到 %.2f%%（门槛 %.1f%%）—— "
                               "**把它从 `COVERAGE_PENDING` 搬进 `COVERAGE` 并锁下限**，"
                               "豁免不许当 V10 的后门" % (name, pct, until)))
        # ② 账那头
        ln = rows.get(wid)
        if ln is None:
            bad.append(("V11", "豁免项「%s」指着欠账 **%s**，而欠账表里没有这一行 —— "
                               "豁免必须有账，否则它就是一条注释（2026-10-02 的原形）"
                        % (name, wid)))
        elif "✅" in ln:
            bad.append(("V11", "🔴 欠账 **%s** 标成已结清，而「%s」还只有 %.2f%%（门槛 %.1f%%）"
                               " —— 账划掉了而数据没变" % (wid, name, pct, until)))
    return bad


def v10(con):
    bad = []
    for name, (num, den, floor) in sorted(COVERAGE.items()):
        try:
            n = con.execute(num).fetchone()[0]
            d = con.execute(den).fetchone()[0]
        except sqlite3.Error as e:
            bad.append(("V10", "覆盖率「%s」查不了：%s" % (name, e)))
            continue
        if not d:
            bad.append(("V10", "覆盖率「%s」的分母是 0" % name))
            continue
        pct = 100.0 * n / d
        if n == d:
            bad.append(("V10", "🔴🔴 覆盖率「%s」**恒等 100%%**（%s/%s）—— "
                               "多半是分母里套了分子的条件，那是假闸（ja 犯过）"
                        % (name, format(n, ","), format(d, ","))))
        elif pct < floor:
            bad.append(("V10", "覆盖率「%s」%.1f%% **低于下限 %.1f%%** —— "
                               "要么补数据，要么调下限并写明为什么" % (name, pct, floor)))
        elif pct - floor > SLACK:
            bad.append(("V10", "覆盖率「%s」%.1f%% 比下限 %.1f%% 高出 %.1f 个点 —— "
                               "**松弛会把退化藏起来**，把下限提到当前水平附近"
                        % (name, pct, floor, pct - floor)))
    return bad


CHECKS = [("V1", v1), ("V2", v2), ("V3", v3), ("V4", v4), ("V5", v5),
          ("V6", v6), ("V7", v7), ("V8", v8), ("V9", v9), ("V10", v10),
          ("V11", v11)]

# ── 跳号：**必须带一个会自己到期的条件**，否则就是永久豁免 ──────────────────
# 🔴 `[[record-the-negative-decision]]`：否定结论必须写什么会推翻它。
#    这里更进一步 —— 推翻条件**做成了代码**（`_skip_expired()`），不是一句话。
# 🔴 2026-10-01：`sense` 落第一行，`_skip_expired()` 当场判红，V10 补上了。
#    跳号名单现在是空的 —— **而这个空是它自己逼出来的，不是我记得**。
SKIP = {}


def _skip_expired(con):
    """跳号的到期条件。**`sense` 落第一行的那天，V10 必须存在** —— 否则这条红。

    ⚠️ 这不是「以后再说」，是一条会自己响的闸：
       阶段 5 一开始写义项，这里当场逼人补 V10（读者口径的覆盖率）。
    """
    bad = []
    try:
        n = con.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
    except sqlite3.Error:
        return bad
    if n and "V10" in SKIP:   # noqa: SIM102 —— 条件已到期，SKIP 现在是空的
        bad.append(("V0", "🔴🔴 `sense` 已经有 %s 行，而 **V10（覆盖率判据自检）"
                          "还挂在 SKIP 里** —— 跳号的条件已经不成立。"
                          "补上 V10 再往下做。" % format(n, ",")))
    return bad


# 🔴🔴 **花名册。别拿「编号连不连续」推。**
#    ko 实测：第一版写「编号从 1 起连续」，变异当场证明它**逮不到删掉最后一条** ——
#    删掉最后一条之后上界跟着降，缺口自己消失了。而最后一条最容易被手滑删掉。
ROSTER = ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10", "V11")


def v0(con):
    """**这张检查表自己有没有缺口。**

    🔴 ko 2026-09-21 真发生过：用字符串替换改测试，把一整条检查删掉了，
       而闸报「全绿」—— **少一条检查和全部通过，输出上长得一模一样。**
    """
    have = tuple(c[0] for c in CHECKS)
    bad = []
    if set(have) != set(ROSTER):
        bad.append(("V0", "检查表与花名册对不上：少了 %s，多了 %s"
                    % (sorted(set(ROSTER) - set(have)) or "无",
                       sorted(set(have) - set(ROSTER)) or "无")))
    overlap = set(SKIP) & set(ROSTER)
    if overlap:
        bad.append(("V0", "这些编号同时在花名册和跳号名单里：%s" % sorted(overlap)))
    return bad + _skip_expired(con)


def check_brief():
    """给 `dbtool` 用：→ [(编号, 原因)]，空列表＝全绿。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        red = v0(con)
        for _, fn in CHECKS:
            red += fn(con) if fn.__code__.co_argcount else fn()
        return red
    finally:
        con.close()


# ── 变异验证 ────────────────────────────────────────────────────────────
# 🔴🔴 **锚一律钉常量**：ko 一天内四条变异静默失效，`replace` 空操作、
#    什么都没注入而检查「通过」。⇒ 每条变异都先断言它**真的改了文本**。
def _mutate_plan(orig, old, new):
    if old not in orig:
        return None                 # 锚失效
    return orig.replace(old, new, 1)


# 🔴🔴 **别拿阶段行的「状态文字」当锚** —— 一天之内栽了两次，形状完全一样：
#    V1 锚 `| **5** | 义项与释义 | ⬜ 未开始`，阶段 5 一开工就失效；
#    V2 锚 `| **7** | 词源层 | ⬜ 未开始`，阶段 7 一做完就失效。
#    两次都不是判据错，是**锚钉在会动的行文上**，而失效的表现是
#    「什么都没注入而这条变异静默作废」（ko 一天内四条同形）。
#    ⚠️ 更该记的是：第一次只修了 V1 —— **修一半比不修更危险**，
#      因为它让人以为这类问题已经解决了（`dbtool._track_audit` 的注释里记着同一句）。
# ⇒ 锚改成**结构**：行首的 `| **<编号>** |` ＋ 第三个单元格的位置。
#   行文怎么改都不影响，而编号变了会立刻「锚失效」报出来。
_STAGE_ROW = r"^(\|\s*\*{0,2}%s\*{0,2}\s*\|[^|]*\|)([^|]*)(\|)"


def _set_stage_mark(orig, num, mark):
    """把阶段表里 `num` 那一行的**状态单元格**改写成 `mark`。锚是结构不是行文。"""
    pat = re.compile(_STAGE_ROW % re.escape(num), re.M)
    m = pat.search(orig)
    if not m or m.group(2).strip() == mark:
        return None                 # 锚失效 / 本来就是这个值（那样注入等于空操作）
    return orig[:m.start()] + m.group(1) + " " + mark + " " + m.group(3) + orig[m.end():]


def mutate():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    base = check_brief()
    if base:
        print("🔴 基线就不绿，变异验证没有意义：")
        for c, w in base:
            print("   %-4s %s" % (c, w))
        con.close()
        return False
    orig = PLAN.read_text(encoding="utf-8")
    ok = True

    def expect(cid, name, mutated_plan):
        nonlocal ok
        if mutated_plan is None:
            ok = False
            print("   🔴🔴 %-4s %s —— **锚失效，什么都没注入**" % (cid, name))
            return
        PLAN.write_text(mutated_plan, encoding="utf-8")
        try:
            hit = any(c == cid for c, _ in check_brief())
        finally:
            PLAN.write_text(orig, encoding="utf-8")
        ok &= hit
        print("   %s %-4s %s" % ("✅" if hit else "🔴 没逮到", cid, name))

    print("═══ 变异验证 ═══")
    # M1 把一个交付物是 0 的阶段声明成 ✅ → V1 红
    # 🔴 第一版只改了阶段表，**V1 没逮到而 V2 逮到了** —— 因为阶段 5 一条交付物都没登记，
    #    V1 的循环体一次都不执行。那正是 V2 存在的理由，但也说明
    #    **这条变异根本没走到 V1 的代码里去**（`[[wait-loops-lie-about-progress]]` 的同一族：
    #    看着通过了，其实那条路径没跑）。
    #    ⇒ 变异必须**同时登记交付物**，才算真的在验 V1。
    #
    # 🔴🔴 **第二版（2026-10-02）：锚失效了，什么都没注入而这条变异静默作废。**
    #    第二版锚的是 `| **5** | 义项与释义 | ⬜ 未开始` —— 阶段 5 一开工那行就变成
    #    `🔄 5a 已完成…`，锚再也匹配不上。`_mutate_plan` 返回 None、`expect()` 报
    #    「锚失效」⇒ 这一条**是靠那句报警才被发现的，不是靠它判红**。
    #    与 ko 那天「一天内四条变异静默失效，`replace` 空操作而检查『通过』」同形。
    #    ⇒ 不再去改**已有**的阶段行（它们的行文天天在动），改成**插一个新行**：
    #      锚是表头那一行，它是这张表的结构，不是某个阶段的状态文字。
    _HDR = "| # | 阶段 | 状态 | 依赖 | vi 特有的差别 |"
    DELIVERABLE["99"] = [("一个永远查不到的交付物",
                          "SELECT (SELECT COUNT(*) FROM dict WHERE word='<不存在的词>')")]
    try:
        expect("V1", "往阶段表插一条声明 ✅ 而交付物是 0 的新阶段（锚＝表头，不会过期）",
               _mutate_plan(orig, _HDR,
                            _HDR + "\n| **99** | 变异用的假阶段 | ✅ 已完成 | — | — |"))
    finally:
        del DELIVERABLE["99"]
    # M2 把一个**没登记交付物**的阶段声明成 ✅ → V2 红（ko 的结构性失明）
    # 🔴🔴 **第一版拿阶段 9 当「没登记交付物的阶段」，而 2026-10-03 阶段 9/6e 都登记了
    #    交付物 ⇒ 这条变异再也验不到 V2。** 当场是这条 `assert` 拦住的（它比沉默好，
    #    但它只能告诉我「坏了」不能替我修）。
    # ⚠️ 这是**前提过期**，与 V4 第一版、与回归闸 R0 的变异是同一个病：
    #    变异把前提**寄托在现状**上，而现状正是它要验的东西在推进。
    #    ⇒ 和 V1 那条一样，**注入一个全新的阶段号**：它定义上就没有交付物登记，
    #      前提**不可能**过期（锚是表头那一行，它是表的结构不是某个阶段的状态文字）。
    assert "98" not in declared_done(), "阶段 98 居然存在？换一个号"
    expect("V2", "🔴 插一条没登记任何交付物的新阶段并声明 ✅（前提不会过期）",
           _mutate_plan(orig, _HDR,
                        _HDR + "\n| **98** | 变异用的假阶段（没登记交付物）| ✅ 已完成 | — | — |"))
    # M3 欠账表之后塞一条游离记账 → V3 红
    expect("V3", "在欠账表之后塞一条游离的 📋",
           orig + "\n\n📋 新记一笔：这条没进表，V3 必须逮到。\n")
    # M4 依赖倒挂 → V4 红（锚是结构，不是行文）
    # 🔴🔴 **第一版只改阶段 9，而 2026-10-02 阶段 5 落成 ✅ 之后它再也造不出倒挂** ——
    #    V4 当场「没逮到」。那不是锚失效（`_set_stage_mark` 照样注入成功），
    #    是**这条变异要创造的条件在现实里已经不可能**。⇒ 两条依赖各验一条，
    #    而且**前一条必须自己把前提也打掉**（把 5 按回 ⬜），不许依赖现状。
    expect("V4", "依赖倒挂①：把阶段 5 按回 ⬜ 而阶段 9 标 ✅（自己造出前提）",
           _set_stage_mark(_set_stage_mark(orig, "5", "⬜ 未开始") or orig,
                           "9", "✅ 已完成"))
    # 🔴🔴🔴 **同一个病的第二条也中了，而且是前一条的注释正下方。**
    #    ①修好之后②还写着「阶段 8 未完成（🔄）」—— 它**寄托在现状上**：
    #    2026-10-05 把阶段 8 的状态文字从过期的 🔄 改成 ✅ 之后，这条变异只改阶段 9，
    #    **造不出任何倒挂** ⇒ V4 当场「没逮到」。
    # ⚠️ 代价是它**只在事情做对之后才发作** —— 把过期的状态文字订正成真实状态，
    #    是一次纯粹的改进，而它悄悄把一条变异变成了空操作。
    #    这是 48 小时内的**第五次**（V4①／R0／V2／V11／这一条）⇒ 顶层 **B20**。
    # ⇒ 规矩写死：**每条变异都要把自己的前提一起注入**，一个 `现状` 字都不许依赖。
    expect("V4", "依赖倒挂②：把阶段 8 按回 🔄 而阶段 9 标 ✅（自己造出前提）",
           _set_stage_mark(_set_stage_mark(orig, "8", "🔄 进行中") or orig,
                           "9", "✅ 已完成"))
    # M5 加一条没有推翻条件的否定结论 → V5 红
    expect("V5", "加一条「有意不做」而不写推翻条件",
           orig + "\n\n- 这一层**有意不做**。\n")
    # M6 欠账编号重复 → V6 红
    expect("V6", "欠账表里让 W1 出现两次",
           _mutate_plan(orig, "| **W1** |", "| **W1** | 占位 | 占位 | 占位 | 占位 |\n| **W1** |"))
    # M7 把别门的账写进本表 → V7 红
    expect("V7", "把一条 `es ` 的账塞进欠账表",
           _mutate_plan(orig, "| **W1** |", "| **W9** | es 那边也有这个毛病 | — | — | — |\n| **W1** |"))
    # M7b/M7c 带锁的豁免，**两头各验一次**（单向的锁只是个下限）
    #
    # 🔴🔴🔴 **第一版锚在真实的 W14 上，而 6e 跑完之后 W14 结清、
    #    `COVERAGE_PENDING` 清空 ⇒ 三条 V11 变异全部锚失效。**
    #    这是**同一个病今天第三次**（回归闸 R0、本闸 V2，现在 V11），
    #    加上 2026-10-02 的 V4 是第四次。形状完全一样：
    #      **变异把自己的前提寄托在现状上，而现状正是它要验的东西在推进。**
    #    ⇒ ⭐ **变异必须自带前提**：临时往 `COVERAGE_PENDING` 注入一个**假的**豁免项
    #      （指向一个假的欠账号），再对那一条做两头的变异。
    #      这样它与「6e 做完没做完」「W14 结清没结清」**彻底脱钩**。
    _FK = "变异用的假豁免项"
    COVERAGE_PENDING[_FK] = (
        "SELECT COUNT(*) FROM example WHERE hidden=0",     # 分子＝分母 ⇒ 100%
        "SELECT COUNT(*) FROM example WHERE hidden=0",
        999.0,          # 门槛设得极高 ⇒ 数据那头**不会**响，只验账那头
        "W97")
    _FAKE_ROW = "| **W97** | 🔴 **新开**：变异用的假欠账 | — | — | — |\n"
    _withfake = _mutate_plan(orig, "| **W1** |", _FAKE_ROW + "| **W1** |")
    try:
        expect("V11", "账那头：豁免指着的欠账被标成已结清，而现状还在门槛以下（自带前提）",
               _withfake.replace("| **W97** | 🔴 **新开**", "| **W97** | ✅ **已结清**"))
        expect("V11", "账那头：豁免指着的欠账整行不见了（自带前提）", orig)
    finally:
        del COVERAGE_PENDING[_FK]
    con.close()

    # M7d 数据那头：现状爬过门槛而没搬进 `COVERAGE` ⇒ V11 必须红。
    # ⚠️ 这是**代码侧**的变异（把门槛压到现状以下），不是数据侧 ——
    #    数据侧要灌约 4 万条 `example_gloss` 才能把 0.90% 推过 50%，
    #    代价与它验的东西不成比例。M1 注入 `DELIVERABLE["99"]`、M9 弹掉 `CHECKS`
    #    是同一种做法。**等价性**：V11 判的是 `pct >= until`，压门槛与抬覆盖率
    #    走的是同一个分支、同一条消息。
    # ⚠️ 同样**自带前提**：注入一个门槛压到 0 的假豁免项，它一定爬过门槛。
    #    等价性：V11 判的是 `pct >= until`，压门槛与抬覆盖率走同一个分支、同一条消息。
    _K = "变异用的假豁免项（数据那头）"
    COVERAGE_PENDING[_K] = (
        "SELECT COUNT(*) FROM example WHERE hidden=0",
        "SELECT COUNT(*) FROM example WHERE hidden=0", 0.5, "W15")
    hit11 = any(c == "V11" for c, _ in check_brief())
    del COVERAGE_PENDING[_K]
    ok &= hit11
    print("   %s V11  数据那头：现状爬过门槛而没搬进 `COVERAGE`"
          % ("✅" if hit11 else "🔴 没逮到"))

    # M8 有意不建的表真建出来 → V8 红（这条动库不动文档）
    con2 = sqlite3.connect(paths.DB)
    con2.execute("CREATE TABLE IF NOT EXISTS inflection (id INTEGER PRIMARY KEY)")
    con2.commit()
    hit8 = any(c == "V8" for c, _ in check_brief())
    con2.execute("DROP TABLE inflection")
    con2.commit()
    con2.close()
    ok &= hit8
    print("   %s V8   手建 `inflection`（有意不建的表）" % ("✅" if hit8 else "🔴 没逮到"))

    # M9 花名册缺口 → V0 红
    saved = CHECKS.pop()
    hit0 = any(c == "V0" for c, _ in check_brief())
    CHECKS.append(saved)
    ok &= hit0
    print("   %s V0   从检查表里删掉最后一条（**最容易被手滑删的那条**）"
          % ("✅" if hit0 else "🔴 没逮到"))
    return ok


def main():
    if "--mutate" in sys.argv:
        raise SystemExit(0 if mutate() else 1)
    red = check_brief()
    print("■ vi 账的闸：%d 条检查（跳号 %s）"
          % (len(CHECKS) + 1, "、".join(sorted(SKIP)) or "无"))
    for cid, why in red:
        print("   🔴 %-4s %s" % (cid, why))
    if not red:
        print("   ✅ 全绿（计划表、欠账表与库和代码对得上）")
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
