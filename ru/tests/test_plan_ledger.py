#!/usr/bin/env python3
"""**账的闸（ru）** —— `docs/RU_PLAN.md` 说的话，与库和代码对不对得上。2026-10-07。

═══ 它为什么在阶段 1 就建 ═══
ko 从阶段 -2 一路做到阶段 4b 都没有这个文件，而 `dbtool` 的挂钩当时是**静默返回** ——
每次写库什么都没做，日志照样打「■ 不变量核对通过 ✓」。
**ja 就是这样盯着绿字做完九个阶段的**（词源层整层缺席三个月而阶段表全 ✅）。
ru 的 `dbtool` 从第一天起把「不存在」喊出来（那是 ko 的教训做成的机制），
而喊完阶段 0 就该把它补上 —— **一道不在场的闸和一道全绿的闸，日志上不能长得一样。**
⚠️ `ru/gates.py` 的 `self_check()` ③ 给这个文件上了锁：
   **阶段表里阶段 1 一标 ✅ 而本文件还不在，它当场判红。**

═══ 🔴🔴 ko 那份的**结构性失明**，这里从第一天就堵上 ═══
ko 的 P1 是这么写的：

    for num, title in declared_done().items():
        for what, sql in DELIVERABLE.get(num, []):   # ← 没登记就是空列表

**一个阶段声明 ✅ 而没有登记任何交付物 ⇒ 循环体一次都不执行 ⇒ 静默全绿。**
ko 的阶段 5/6/7 正是这样。⇒ **V2 专治这个。**
`[[expectation-must-be-declared]]`：「没登记」和「登记了且通过」不许长得一样。

═══ 这道闸拦什么 ═══
    V0  **这张检查表自己有没有缺口**（拿花名册比，不拿「编号连不连续」推）
    V1  阶段表标着 ✅，交付物却是空的 / 文件不在 / 代码里找不到那句话
    V2  🔴🔴 阶段标着 ✅ 而**一条交付物都没登记**（ko 的结构性失明）
    V3  记账散落：欠账表之后不许再有游离的 📋
    V4  依赖倒挂：前一个阶段没完成，后面的不许声明 ✅
    V5  「有意不做/不建」的行没写什么会推翻它
    V6  欠账表里同一个编号出现两次
    V7  别门/跨门的账混进本表（该去 `docs/BACKLOG.md`）
    V8  **有意不建的四个对象**偷偷长出来了
    V9  闸名单自检 ＋ 有闸欠着没跑 ＋ **欠着变异没跑**
    V10 🔴🔴 **带锁的占位**：覆盖率判据表现在是空的（还没有任何内容层），
        而**空表必须自己会到期** —— 一旦库里出现义项/读音/词源，它当场判红。
    V11 🔴🔴 **R11 的锁**：阶段 1 算出的那批「落行语法标签」这一步没有家
        （`sense_tag` 要等阶段 5）；`sense` 一非空而 `grammar` 桶还空着就判红。

用法：
    python3 ru/tests/test_plan_ledger.py
    python3 ru/tests/test_plan_ledger.py --mutate   # 变异验证

⚠️ **`--mutate` 会在运行期间原地改写 `docs/RU_PLAN.md`**（写进去、跑完还原）。
   vi 那轮我在后台跑变异的同时去读计划表，读到的是**注入后的版本**，
   当场以为欠账表里多了一行残留。⇒ 跑变异时别碰那个文件。
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                        # noqa: E402

ROOT = paths.ROOT
PLAN = ROOT / "docs" / "RU_PLAN.md"
TABLE = "## 一、阶段表"
DEBT_HEAD = "### 📋 欠账"
# 🔴 状态标记**按出现顺序取第一个**，不许用子串命中 —— 见 `_status()`
MARKS = ("✅", "🔄", "⬜", "❌", "📋")
ROW = re.compile(r"^\|\s*\*{0,2}([-\w.]+)\*{0,2}\s*\|([^|]*)\|([^|]*)\|", re.M)

# ── 交付物登记表：阶段号 → [(是什么, SQL)]。SQL 返回的数 **必须 > 0** ──
DELIVERABLE = {
    "0": [("库里有表", "SELECT COUNT(*) FROM sqlite_master WHERE type='table'")],
    "1": [("dict 骨架", "SELECT COUNT(*) FROM dict"),
          ("entry 词条层", "SELECT COUNT(*) FROM entry"),
          # 🔴 不写「表非空」就完事：阶段 1 特有的那条是**屈折形真的被标出来了**，
          #    而那是用户 2026-10-07「屈折形先收」那个决定的唯一落点。
          ("is_lemma 真的分了（不是全 1）",
           "SELECT COUNT(*) FROM dict WHERE is_lemma=0"),
          ("entry_type 真的分了类（不是全 word）",
           "SELECT COUNT(DISTINCT entry_type)-1 FROM dict"),
          # 🔴 四个落列的语法字段，至少 aspect 要有值 —— 它带着归一判据（S4）
          ("entry.aspect 有值", "SELECT COUNT(*) FROM entry WHERE aspect IS NOT NULL")],
    "2": [("stress 重音层", "SELECT COUNT(*) FROM stress"),
          ("entry.stressed 派生列",
           "SELECT COUNT(*) FROM entry WHERE stressed IS NOT NULL AND TRIM(stressed)<>''"),
          # 🔴 不写「表非空」就完事。这一层特有的两条：
          #   ① 多候选真的收下来了（`алфа́вит`／`алфави́т` 两个都在）——
          #     只收主行的话这个数是 0，而**那正是裁决 C 要避免的「发明一套编码塞进单列」**；
          ("多候选真的保住了（variant_seq>0 存在）",
           "SELECT COUNT(*) FROM stress WHERE variant_seq>0"),
          #   ② 三个来源档都真的有行 —— 少掉 `语法标签` 那一档就是回到第一版
          #     那个窄判据（词元覆盖 15.73% 而不是 37.18%）。
          ("来源不止 canonical 一档",
           "SELECT COUNT(DISTINCT src)-1 FROM stress"),
          # 🔴 R13 的交付物要写成**正信号**。第一版写的是
          #    `1 - (带重音符的词头数)`，而豁免的 `◌́` 让它正好等于 0 ⇒ V1 当场判红
          #    —— **闸是对的，是我把「没有坏东西」写成了交付物**。
          #    「还剩几个带重音符的词头」是重音闸 T11 的活儿（那里才有白名单）。
          #    这里要查的是**合并真的发生了**：7 条 entry 的 `src_ref` 里还记着
          #    带重音的原词（证据层一个字不动），而它现在挂在无重音的孪生行上。
          ("R13 已结清（7 条 entry 搬到了孪生词形上，src_ref 仍留证据）",
           "SELECT COUNT(*) FROM entry e JOIN dict d ON d.id=e.word_id "
           "WHERE e.src_ref LIKE '%' || CHAR(769) || '%' "
           "AND d.word NOT LIKE '%' || CHAR(769) || '%'")],
    "3": [("inflection 屈折层", "SELECT COUNT(*) FROM inflection"),
          # 🔴 这一层特有的三条，钉的都是当天栽过跤的地方：
          #   ① `stressed` 真的收了（重音在变格中移动，不收就是半成品）；
          ("inflection.stressed 有值",
           "SELECT COUNT(*) FROM inflection WHERE stressed IS NOT NULL AND TRIM(stressed)<>''"),
          #   ② 不止一个源 —— 只收 ru 版就回到「只拿 ru 版比」那个高估 8.2 倍的度量；
          ("来源不止一版", "SELECT COUNT(DISTINCT src)-1 FROM inflection"),
          #   ③ ru-crit-9：形动词页真的从词元里分出去了。钉一个常量词，不锚现状（B20）。
          ("形动词页不算词元（ru-crit-9）",
           "SELECT COUNT(*) FROM dict WHERE word='взбулгаченный' AND is_lemma=0")],
    "4": [("pronunciation 音标层", "SELECT COUNT(*) FROM pronunciation"),
          # 🔴 这一层特有的三条，钉的都是当天的决定：
          #   ① entry_id 真的填了（同形异重音词要分得清 —— §11.3 的整个理由）
          ("pronunciation.entry_id 有值",
           "SELECT COUNT(*) FROM pronunciation WHERE entry_id IS NOT NULL"),
          #   ② 「源头说错的读音」真的存了下来而且不印
          ("错误/不推荐读音存而不印", "SELECT COUNT(*) FROM pronunciation WHERE hidden=1"),
          #   ③ ru-crit-10：姓氏变格形不算词元（钉常量词，B20）
          ("姓氏变格形不算词元（ru-crit-10）",
           "SELECT COUNT(*) FROM dict WHERE word='Хортову' AND is_lemma=0")],
    "5a": [("sense 出版层", "SELECT COUNT(*) FROM sense"),
           ("sense_src 证据层", "SELECT COUNT(*) FROM sense_src"),
           # 指针真的只进了证据层、且带结构目标
           ("指针目标有值", "SELECT COUNT(*) FROM sense_src WHERE pointer_target IS NOT NULL"),
           # R11 结清：entry 级语法标签真的落了
           ("R11 落下的 entry 级标签",
            "SELECT COUNT(*) FROM sense_tag WHERE src LIKE 'entry:%' OR src LIKE '%+entry'"),
           # zh 版白送的中文真的出版了
           ("zh 白送的中文", "SELECT COUNT(*) FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
                           "WHERE g.lang='zh' AND s.hidden=0")],
    "5b": [("模型中文译文", "SELECT COUNT(*) FROM sense_gloss WHERE src='model:deepseek-v4-flash'"),
           # 破例（用户 2026-10-23）：fr/vi/pl 证据只在空白页词元上出版、只挂模型中文
           ("破例义项", "SELECT COUNT(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
                      "WHERE x.lang IN ('fr','vi','pl')")],
    # 5c（2026-10-26）：落点是「词形另有**源头**中文、而这条义项的中文是模型的」—— 正是 5b 的 S1 有意跳过的那一半
    "5c": [("已有中文词形上的模型中文", "SELECT COUNT(*) FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
                                  "WHERE g.src='model:deepseek-v4-flash' AND EXISTS (SELECT 1 FROM sense s2 "
                                  "JOIN sense_gloss g2 ON g2.sense_id=s2.id WHERE s2.word_id=s.word_id "
                                  "AND g2.lang='zh' AND g2.src NOT LIKE 'model:%')")],
    "6a": [("可出版例句", "SELECT COUNT(*) FROM example WHERE hidden=0"),
           # 出版正文与原文分两列（vi W22）：清洗真的只落在 text_pub
           ("出版正文清洗", "SELECT COUNT(*) FROM example WHERE text_pub IS NOT NULL"),
           # zh-s 重切（R3 例句那一半）真的落了
           ("zh-s 重切成对", "SELECT COUNT(*) FROM example WHERE src_ref LIKE '%#p%'"),
           # 白捡的中文：源头给的 ＋ 同句借用
           ("源头中文译文", "SELECT COUNT(*) FROM example_gloss WHERE lang='zh'")],
    "6b": [("可出版关系", "SELECT COUNT(*) FROM sense_relation WHERE hidden=0"),
           # ru 版 «Родственные слова» 落成自己的 kind，不是 related（R1）
           ("构词词族", "SELECT COUNT(*) FROM sense_relation WHERE kind='word_family'"),
           ("体对", "SELECT COUNT(*) FROM sense_relation WHERE kind='aspect_pair'"),
           # ru 版 sense_index 真的把关系挂到了义项上
           ("挂到义项的关系", "SELECT COUNT(*) FROM sense_relation WHERE sense_id IS NOT NULL")],
    "6d": [("模型中文例句译文", "SELECT COUNT(*) FROM example_gloss WHERE src='model:deepseek-v4-flash'")],
    "7": [("可出版词源段", "SELECT COUNT(*) FROM etymology WHERE hidden=0"),
          # 白送的中文词源（zh 两版）真的出版了
          ("中文词源", "SELECT COUNT(*) FROM etymology WHERE hidden=0 AND src LIKE 'zh-%'"),
          # en 版模板推出的来源类型
          ("etym_type", "SELECT COUNT(*) FROM etymology WHERE etym_type IS NOT NULL"),
          # fr/vi/pl 进证据层（将来翻译时有原文可用）
          ("证据层词源（不出版）", "SELECT COUNT(*) FROM etymology WHERE hidden=1")],
    "6c": [("可播录音", "SELECT COUNT(*) FROM audio WHERE hidden=0"),
           # 张冠李戴藏而不删
           ("藏起来的张冠李戴", "SELECT COUNT(*) FROM audio WHERE hidden=1")],
}

# ── 文件交付物：阶段号 → [(是什么, 相对路径)] ──
FILES = {
    "-2": [("路径唯一真相源", "ru/paths.py"),
           ("写库闸门", "ru/dbtool.py")],
    "-1": [("源头探针", "ru/probes/probe_sources.py"),
           ("重音/关系探针", "ru/probes/probe_stress.py"),
           ("中文可用率探针", "ru/probes/probe_zh_gloss.py"),
           ("体/词族探针", "ru/probes/probe_aspect_relations.py"),
           ("建表依据探针", "ru/probes/probe_schema.py"),
           ("探测结果存档", "data/work/ru/probe/probe_sources.txt"),
           ("外审材料", "data/work/ru/probe/consult_20261007_stress_aspect.md"),
           ("外审答复（v4pro）", "data/work/ru/probe/consult_20261007_stress_aspect.v4pro.md"),
           ("外审答复（豆包）", "data/work/ru/probe/consult_20261007_stress_aspect.doubao.md")],
    "0": [("判据唯一的家", "ru/pipeline/criteria.py"),
          ("建表脚本", "ru/pipeline/build_v3_schema.py"),
          # 🔴 闸自己也是交付物。不登记 ⇒ 它被删掉不会有人说话
          #    （`ru/gates.py` 的 self_check ③ 反过来查这件事，两边互相当闸）
          ("结构闸", "ru/tests/test_schema.py"),
          ("闸台账", "ru/gates.py"),
          ("闸的跑批入口", "ru/run_gates.py")],
    "1": [("骨架建库", "ru/pipeline/build.py"),
          ("骨架闸", "ru/tests/test_skeleton.py"),
          ("账的闸", "ru/tests/test_plan_ledger.py")],
    "2": [("重音层收割器", "ru/pipeline/stress_layer.py"),
          ("重音闸", "ru/tests/test_stress.py"),
          ("落点探针", "ru/probes/probe_stress_layer.py"),
          ("落点探针存档", "data/work/ru/probe/probe_stress_layer.txt"),
          ("重音层统计存档", "data/work/ru/stage2_stress_stats.json")],
    "3": [("屈折层收割器", "ru/pipeline/inflection_layer.py"),
          ("屈折闸", "ru/tests/test_inflection.py"),
          ("落点探针", "ru/probes/probe_inflection_layer.py"),
          ("落点探针存档", "data/work/ru/probe/probe_inflection_layer.txt"),
          # 🔴 「没有变位表的词元是源头没给还是我们没收」—— 不登记它，
          #    I10 只锁下限的那个盲区就又回来了
          ("缺口回源探针", "ru/probes/probe_inflection_gaps.py"),
          ("缺口回源探针存档", "data/work/ru/probe/probe_inflection_gaps.txt"),
          # R16 的存档（`class` 512 种值没有家，**不许丢**）
          ("屈折层统计存档（含 R16 的 class 值域）", "data/work/ru/stage3_inflection_stats.json")],
    "4": [("音标层收割器", "ru/pipeline/pronunciation_layer.py"),
          ("音标闸", "ru/tests/test_pronunciation.py"),
          ("落点探针", "ru/probes/probe_pronunciation_layer.py"),
          ("落点探针存档", "data/work/ru/probe/probe_pronunciation_layer.txt"),
          ("音标层统计存档", "data/work/ru/stage4_pronunciation_stats.json")],
    "5a": [("义项层收割器", "ru/pipeline/sense_layer.py"),
           ("义项闸", "ru/tests/test_sense.py"),
           ("义项层探针", "ru/probes/probe_sense_layer.py"),
           ("义项层探针存档", "data/work/ru/probe/probe_sense_layer.txt"),
           ("义项层统计存档（含 R11 两个数）", "data/work/ru/stage5a_sense_stats.json")],
    "5b": [("翻译与回收", "ru/pipeline/translate_glosses.py"),
           ("跑批器（ru 专用拷贝）", "ru/pipeline/ds_batch.py"),
           # 🔴 答案文件**就是账本**（`[[answer-file-is-the-ledger]]`）—— 付费数据的唯一原件
           ("主体答案 ru", "data/work/ru/gloss_zh/ru-S1-slice2.jsonl"),
           ("主体答案 en", "data/work/ru/gloss_zh/en-S1-slice2.jsonl"),
           ("破例答案", "data/work/ru/gloss_zh/xl.jsonl")],
    "5c": [("翻译与回收（C1 范围）", "ru/pipeline/translate_glosses.py"),
           # 🔴 答案文件就是账本 —— 5c 付费数据的唯一原件
           ("5c 答案 ru", "data/work/ru/gloss_zh/ru-C1.jsonl"),
           ("5c 答案 en", "data/work/ru/gloss_zh/en-C1.jsonl")],
    "6a": [("例句层收割器", "ru/pipeline/example_layer.py"),
           ("例句闸", "ru/tests/test_example.py"),
           ("阶段 6 探针", "ru/probes/probe_stage6.py"),
           ("阶段 6 探针存档", "data/work/ru/probe/probe_stage6.txt"),
           ("例句层统计存档", "data/work/ru/stage6a_example_layer.txt")],
    "6b": [("关系层收割器", "ru/pipeline/relation_layer.py"),
           ("关系闸", "ru/tests/test_relation.py"),
           ("关系层统计存档", "data/work/ru/stage6b_relation_layer.txt")],
    "7": [("词源层收割器", "ru/pipeline/etymology_layer.py"),
          ("词源闸", "ru/tests/test_etymology.py"),
          ("词源探针", "ru/probes/probe_etymology.py"),
          ("词源探针存档", "data/work/ru/probe/probe_etymology.txt"),
          ("词源层统计存档", "data/work/ru/stage7_etymology_layer.txt")],
    "9": [("服务层", "packages/dict-core/src/russian.ts"),
          ("映射表", "packages/dict-labels/src/ru.ts"),
          ("展示层契约闸", "apps/web/src/contract-check-ru.tsx"),
          ("查询计划闸", "ru/probes/query_plans.py")],
    "8": [("外锚闸（九层 vs dump，三向恒等）", "ru/tests/test_dump_anchor.py"),
          ("回归闸（每次写库自动跑）", "ru/tests/test_no_regression.py")],
    "6d": [("翻译与回收", "ru/pipeline/translate_examples.py"),
           # 🔴 答案文件就是账本 —— 付费数据的唯一原件
           ("主体答案", "data/work/ru/example_zh/all.jsonl"),
           ("单条重发答案", "data/work/ru/example_zh/redo.jsonl"),
           ("全量审计存档", "data/work/ru/example_zh_all_audit.txt")],
    "6c": [("录音层收割器", "ru/pipeline/audio_layer.py"),
           ("录音闸", "ru/tests/test_audio.py"),
           ("录音层统计存档（含张冠李戴全部清单）", "data/work/ru/stage6c_audio_layer.txt")],
}

# ── 代码交付物：阶段号 → [(是什么, 文件, 必须出现的字符串)] ──
# 🔴 判据是「代码里有没有这句话」，钉在**常量/函数名**上不钉行号
CODE = {
    "0": [("有意不建的名单", "ru/pipeline/build_v3_schema.py", "NOT_BUILT"),
          ("aspect 值域断言", "ru/pipeline/build_v3_schema.py", "entry.aspect"),
          ("归一自检", "ru/dbtool.py", "_norm_selfcheck")],
    "1": [("屈折形指针读义项级", "ru/pipeline/criteria.py", "form_of")],
    # 🔴 阶段 2 这四条钉的都是**当天栽过跤的那个判据**，钉在常量/函数名上：
    "2": [("重音层收词判据只有一个家", "ru/pipeline/criteria.py", "stressed_spelling"),
          # 「无需标注」与「源头没给」必须分成两个数（vi 的 blank_split）
          ("无需标注的分桶判据", "ru/pipeline/criteria.py", "stress_not_needed"),
          # 预组合的 `ѐ` 让 `norm_ru` 剥不掉 ⇒ 落库前统一编码
          ("落库值统一成组合式重音符", "ru/pipeline/criteria.py", "to_combining_stress"),
          # 「哪些行才真的落库」也是判据，搬家之后两边共用一个
          ("挂钩靠重算 src_ref", "ru/pipeline/criteria.py", "class SrcRef")],
    "3": [("屈折行判据只有一个家", "ru/pipeline/criteria.py", "def inflection_rows"),
          ("张冠李戴的变位表登记", "ru/pipeline/criteria.py", "BAD_TABLE_TAGS"),
          # ru-crit-9 的第四条路 —— 注释里写了一个阶段而没做成判据的那件事
          ("形动词页算屈折形", "ru/pipeline/criteria.py", "PARTICIPLE_TAGS")],
    "4": [("音标拆格判据只有一个家", "ru/pipeline/criteria.py", "def pronunciation_parts"),
          # fr 版地名是录音者所在地 —— 地域白名单里不许有它
          ("地域只收白名单", "ru/pipeline/criteria.py", "DIALECT_MAP"),
          # 空表结构漂移的保险（DROP 不可逆，有数据就拒绝）
          ("空表才自动重建", "ru/pipeline/build_v3_schema.py", "_rebuild_empty_drifted")],
    "5a": [("指针判据只有一个家", "ru/pipeline/criteria.py", "def sense_pointer_via"),
           ("父释义拼接", "ru/pipeline/criteria.py", "def sense_text"),
           ("zh 最小清洗", "ru/pipeline/criteria.py", "def zh_gloss_tidy"),
           ("按 sense_id 取证据的索引", "ru/pipeline/build_v3_schema.py", "idx_sense_src_sense")],
    # 5c 的全部意义是「按**义项**判缺中文、不再按词形判」（5b 的 S1 按词形判 ⇒ 漏了已有中文词形上的 18.4 万条）
    "5c": [("5c 范围按义项判", "ru/pipeline/translate_glosses.py", "def gap_rows_5c"),
           ("回收时逮到的慰藉否决", "ru/pipeline/criteria.py", "ZH_SIMP_KEEP_PHRASE_PREV")],
    "6a": [("例句出版判据只有一个家", "ru/pipeline/criteria.py", "def example_hidden_why"),
           # 删节号不许剥 —— 第一版判据自己栽的那一跤
           ("只剥项目符号", "ru/pipeline/criteria.py", "_LEAD_MARK"),
           ("zh-s 重切", "ru/pipeline/criteria.py", "def zh_simp_pairs"),
           ("译文语种按版定", "ru/pipeline/criteria.py", "EX_TR_LANG")],
    "6b": [("关系 kind 登记表（认不出就抛错）", "ru/pipeline/criteria.py", "REL_KINDS"),
           ("有意不收的关系字段带推翻条件", "ru/pipeline/criteria.py", "REL_NOT_COLLECTED"),
           ("词族分组白名单（R10）", "ru/pipeline/criteria.py", "def family_groups"),
           ("体对按字段分支", "ru/pipeline/criteria.py", "def aspect_partner")],
    "7": [("字段名两版都读", "ru/pipeline/criteria.py", "ETYM_FIELDS"),
          ("占位与挂件的清洗只有一个家", "ru/pipeline/criteria.py", "def etymology_text_pub"),
          ("词源树找不到树根就不剥", "ru/pipeline/criteria.py", "_ETYM_TREE_ROOT"),
          ("来源类型只认 en 模板", "ru/pipeline/criteria.py", "ETYM_TYPE_OF_TEMPLATE")],
    "9": [("视图", "apps/web/src/App.tsx", "export function RussianEntryView"),
          ("分发接上 ru", "apps/web/src/App.tsx", "entry.lang === 'ru'"),
          ("语种注册", "packages/dict-core/src/index.ts", "new RussianDictService"),
          ("css 审计登记", "apps/web/src/css-audit.ts", "RussianEntryView"),
          ("分发闸登记", "apps/web/src/dispatch-audit.ts", "russian.ts"),
          ("语体标签的冻结名单", "packages/dict-labels/src/ru.ts", "RU_USAGE_UNPRINTED"),
          ("回归闸读取路径", "ru/tests/test_no_regression.py", "RP7")],
    "8": [("回归闸接上写库闸门", "ru/dbtool.py", "_regression_check"),
          ("回归闸的读取路径带锁豁免", "ru/tests/test_no_regression.py", "READ_PATH"),
          ("外锚闸断言没有第三类", "ru/tests/test_dump_anchor.py", "第三类")],
    "6c": [("张冠李戴的源头第二信号", "ru/pipeline/criteria.py", "def audio_same_sound_pairs"),
           ("B12 归一键", "ru/pipeline/criteria.py", "def commons_key")],
}

# 阶段 0 明写「有意不建」的四个对象。V8 查它们没有偷偷长出来。
# 🔴 **名单不在这儿手抄** —— 从 `build_v3_schema.NOT_BUILT` 读。
#    两张名单迟早漂开（`[[refactor-mindset-code-quality]]`：同一文件里两张重复映射表
#    已经发生过）。
def not_built_names():
    try:
        sys.path.insert(0, str(ROOT / "ru"))
        from pipeline.build_v3_schema import NOT_BUILT
        return tuple(NOT_BUILT)
    except Exception as e:                       # noqa: BLE001
        return ("«读不到 build_v3_schema.NOT_BUILT：%s»" % e,)


# ── 覆盖率判据表 ─────────────────────────────────────────────────────────
# 🔴🔴 **它现在是空的，而这是带锁的占位，不是豁免。**
#    vi 的教训（W14）：「例句的中文译文」原先只是 `COVERAGE` 末尾的一条注释，
#    于是阶段表、欠账表、这里**三处一致地看不见它**，最后是用户问出来的。
#    ⇒ 空表必须**自己会到期**：V10 查「库里出现了内容层而这张表还是空的」就判红。
#    `[[record-the-negative-decision]]`：否定结论必须写什么会推翻它。
# 🔴 第三个字段可以是 SQL 字符串，**也可以是一个 `f(con) -> 百分数`** ——
#    阶段 2 的「需要标注的词元」这个口径要用 `criteria.stress_not_needed` 分桶，
#    而那是判据、只许有一个家，**不许为了「能写成 SQL」在这里近似一遍**
#    （ko 的 K24／vi 的 R19：闸自己手写近似判据，同时更宽又更窄）。
def _cov_stress(con, key):
    sys.path.insert(0, str(ROOT / "ru"))
    from tests.test_stress import coverage
    return coverage(con)[key]


def _cov_sense(con, key):
    sys.path.insert(0, str(ROOT / "ru"))
    from tests.test_sense import coverage
    return coverage(con)[key]


def _cov_etym(con, key):
    sys.path.insert(0, str(ROOT / "ru"))
    from tests.test_etymology import coverage
    return coverage(con)[key]


def _cov_example(con, key):
    sys.path.insert(0, str(ROOT / "ru"))
    from tests.test_example import coverage
    return coverage(con)[key]


# 🔴 下限离实测太远等于没有锁：重音两项阶段 2 定的 35/37，今天三次修 is_lemma 后实测 50.54/52.54
#    ⇒ 跌回 40% 它也不响。2026-10-23 统一改成「实测 − 2 个点」，并登记 5b 的两个数。
COVERAGE = [
    ("词元·带重音拼写", 48.50,
     lambda con: _cov_stress(con, "pct_all"),
     "阶段 2 实测 37.18%，三次修 is_lemma 后 **50.54%**。下限留 2 个点的余量；**紧的那把锁在重音闸 T10**"
     "（已接受基线，只许涨不许跌）"),
    # 🔴🔴 **两个数一起登记，缺一个这张表就在撒谎。** 单报 37.18% 会被读成
    #    「六成词元源头没给重音」，而实测 6.59% 的词元**本来就不需要重音符**
    #    （含 ё／单音节）。vi 的 `coverage.blank_split()`：返回两个数不是一个。
    ("词元·需要标注的那批", 50.50,
     lambda con: _cov_stress(con, "pct_need"),
     "分母去掉「含 ё／单音节」那 42,155 个 ⇒ 实测 39.08%"),
    # 5b（2026-10-23）：模型中文落库后。**两个数一起登记**：「有可印义项」与「有可印中文」——
    #    只登记中文的话，「义项整批被藏」会让两者一起跌而看起来只是中文少了。紧的锁在义项闸 E12。
    ("词元·有可印义项", 93.50,
     lambda con: _cov_sense(con, "any_pct"),
     "5b 后实测 95.51%（5a 时 92.62%：破例给 1.1 万个空白页词元建了中文义项）"),
    ("词元·有可印中文", 93.50,
     lambda con: _cov_sense(con, "zh_pct"),
     "5b 后实测 **95.50%**（5a 时 23.89%）。剩下的缺口：无汉字译文不入库 88＋21／源头没有义项 13,082"),
    # 🔴 6a（2026-10-23）：例句的中文覆盖**现在就登记**，而它现在只有 10.33% —— vi 的 W14：
    #    「例句的中文译文」只活在一条注释里，阶段表/欠账表/覆盖率表三处一致看不见它。
    #    下限按实测写，6d 落库后上调（那时不调，V10 的「下限离实测太远」那条会逼人调）。
    ("可出版例句·有中文", 97.00,
     lambda con: _cov_example(con, "zh_pct"),
     "6a 实测 10.33%（源头 22,240 ＋ 同句借用 11,833）；**6d 落库后 98.99%**（模型 292,566）。"
     "下限按「实测 − 2 个点」；紧的锁在例句闸 X11（已接受基线）"),
    # 阶段 7（2026-10-24）：两个数一起登记 ——「有词源」与「有中文词源」。紧的锁在词源闸 Y10
    ("词元·有可出版词源", 24.50,
     lambda con: _cov_etym(con, "lemma_pct"),
     "实测 26.44%。🔴 ru 版 45.3 万段里 29.6 万段是 `От ??` 占位 ⇒ **源头没给**，不是我们没收"),
    ("词元·有中文词源", 3.50,
     lambda con: _cov_etym(con, "zh_pct"),
     "实测 3.85%（zh 两版白送）。词源译中文（7b）待拍板 —— 拍了之后上调"),
]
# 一旦下面任一张表非空，COVERAGE 就必须开始登记 —— 这是 V10 的锁
COVERAGE_TRIGGERS = ("sense", "sense_gloss", "pronunciation", "etymology",
                     "example", "stress", "inflection")


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


def _debt_text():
    s = _plan()
    i = s.find(DEBT_HEAD)
    if i < 0:
        return ""
    j = s.find("\n## ", i)
    return s[i:j if j > 0 else len(s)]


def declared_done():
    out = {}
    for m in ROW.finditer(_table_text()):
        if _status(m.group(3)) == "✅":
            out[m.group(1)] = m.group(2).strip().strip("*").strip()
    return out


def all_stages():
    out = {}
    for m in ROW.finditer(_table_text()):
        num = m.group(1)
        if num in ("阶段", "---"):
            continue
        out[num] = (m.group(2).strip(), _status(m.group(3)))
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
                bad.append(("V1", "阶段 %s（%s）声明 ✅，而交付物「%s」是 0"
                            % (num, title, what)))
        for what, rel in FILES.get(num, []):
            if not (ROOT / rel).exists():
                bad.append(("V1", "阶段 %s 声明 ✅，而交付物文件不在：%s（%s）"
                            % (num, rel, what)))
        for what, rel, needle in CODE.get(num, []):
            p = ROOT / rel
            if not p.exists():
                bad.append(("V1", "阶段 %s 的代码交付物文件不在：%s" % (num, rel)))
            elif needle not in p.read_text(encoding="utf-8", errors="replace"):
                bad.append(("V1", "阶段 %s 声明 ✅，而 %s 里找不到 %r（%s）"
                            % (num, rel, needle, what)))
    return bad


def v2():
    """🔴🔴 声明 ✅ 的阶段，必须**至少登记一条**交付物（ko 的结构性失明）。"""
    bad = []
    for num, title in sorted(declared_done().items()):
        if not (DELIVERABLE.get(num) or FILES.get(num) or CODE.get(num)):
            bad.append(("V2", "🔴🔴 阶段 %s（%s）声明 ✅ 而**一条交付物都没登记** ——"
                        "V1 的循环体对它一次都不执行，也就是**静默全绿**"
                        "（ko 的阶段 5/6/7 正是这样）" % (num, title)))
    return bad


def v3():
    """记账散落：欠账表之后不许再有游离的 📋。"""
    s = _plan()
    i = s.find(DEBT_HEAD)
    if i < 0:
        return [("V3", "找不到欠账表小节 %r —— 判据要跟着改，不许当成通过" % DEBT_HEAD)]
    bad = []
    for m in re.finditer(r"^.*📋.*$", s[i + len(DEBT_HEAD):], re.M):
        line = m.group(0).strip()
        # 表格行与「等某阶段再建」那类说明不算散落
        if line.startswith("|") or "等阶段" in line or "📋 等" in line:
            continue
        bad.append(("V3", "欠账表之后有游离的 📋 记账：%s" % line[:70]))
    return bad


def v4():
    """依赖倒挂：阶段 N 没完成，N+1 之后的不许声明 ✅。

    🔴🔴 **变异要自带前提**（`BACKLOG` B20：48 小时内四次「现状推进后变异静默失效」）。
       所以这条判据**不写死任何阶段号** —— 它按表里的实际顺序算。
    """
    # 🔴🔴 第一版这里写死了 `["-2", …, "5", …, "9"]` —— **与本函数文档的「不写死任何阶段号」
    #    正好相反**。2026-10-23 把阶段 5 拆成 5a/5b 时才看见：不在表里的阶段号会被**静默跳过**
    #    （5b 没做而 6 标 ✅，V4 一声不吭）。⇒ 按阶段表里**行出现的顺序**算。
    #    ⚠️ `all_stages()` 也会返回欠账表的行（R1、R2…）—— 只取**阶段号形状**的行，
    #       否则一条「✅ 已结清」的欠账会被当成排在阶段 9 后面的「阶段」而误报倒挂。
    st = all_stages()
    order = [k for k in st if re.fullmatch(r"-?\d+[a-z]?", k)]
    bad = []
    seen_undone = None
    for num in order:
        if num not in st:
            continue
        _title, mark = st[num]
        if mark != "✅" and seen_undone is None:
            seen_undone = num
        elif mark == "✅" and seen_undone is not None:
            bad.append(("V4", "阶段 %s 声明 ✅，而它前面的阶段 %s 还没完成 —— 依赖倒挂"
                        % (num, seen_undone)))
    return bad


def v5():
    """「有意不做/不建」的行必须写什么会推翻它（`PLAYBOOK` 7.5）。

    🔴 判据问**状态列在说什么**，不问它画了什么符号 —— 按符号判会在 37 行上误报
       （`⚪` 在 pt/de/fr 的计划表里是另一个意思）。
    ⚠️ 也**只看状态列**，不看整行：ja 的阶段 4b/6 是 ✅、只是详情散文里提了这四个字。
    """
    bad = []
    for m in ROW.finditer(_table_text()):
        state = m.group(3)
        if "有意不做" in state or "有意不建" in state or "有意为空" in state:
            rest = m.group(0)
            if "推翻" not in rest:
                bad.append(("V5", "阶段 %s 的状态是「有意不做/不建」而没写什么会推翻它"
                            % m.group(1)))
    # 欠账表与 `NOT_BUILT` 里的否定结论同理
    try:
        sys.path.insert(0, str(ROOT / "ru"))
        from pipeline.build_v3_schema import NOT_BUILT
        for name, why in NOT_BUILT.items():
            if "推翻" not in why:
                bad.append(("V5", "`NOT_BUILT['%s']` 没写什么会推翻它 —— "
                            "写不出推翻条件的否定结论会变成永久前提" % name))
    except Exception as e:                       # noqa: BLE001
        bad.append(("V5", "读不到 build_v3_schema.NOT_BUILT（%s）" % e))
    return bad


def v6():
    """欠账表里同一个编号不许出现两次。"""
    nums = re.findall(r"^\|\s*\*\*(R\d+)\*\*", _debt_text(), re.M)
    bad = []
    for n in sorted({x for x in nums if nums.count(x) > 1}):
        bad.append(("V6", "欠账编号 %s 在表里出现 %d 次" % (n, nums.count(n))))
    return bad


def v7():
    """别门/跨门的账混进本表 —— 该去 `docs/BACKLOG.md`。

    🔴 用户的规矩：「**你只有记在顶层，你才知道所有语言留下来的所有问题**」。
       各门的计划表只记它自己的账。
    """
    others = ("en", "es", "it", "fr", "pt", "de", "ja", "ko", "vi")
    bad = []
    for m in re.finditer(r"^\|\s*\*\*(R\d+)\*\*\s*\|(.*)$", _debt_text(), re.M):
        row = m.group(2)
        # 判据：这一行**声明影响别门**（而不是「顺带提到别门做过什么」）
        if re.search(r"影响\s*(哪几门|.*(%s))" % "|".join(others), row):
            bad.append(("V7", "欠账 %s 看起来是跨门的账（该记进 docs/BACKLOG.md）：%s"
                        % (m.group(1), row[:60])))
    return bad


def v8(con):
    """🔴 有意不建的对象偷偷长出来了。"""
    bad = []
    live = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    for name in not_built_names():
        if name in live:
            bad.append(("V8", "**有意不建的 `%s` 出现在库里** —— 要么它该建"
                        "（那就改 `NOT_BUILT` 并写明推翻了什么），要么是手滑" % name))
    return bad


def v9():
    """闸名单自检 ＋ 有闸欠着没跑 ＋ **欠着变异没跑**。"""
    bad = []
    try:
        sys.path.insert(0, str(ROOT / "ru"))
        import gates
    except Exception as e:                       # noqa: BLE001
        return [("V9", "读不到 `ru/gates.py`（%s）—— 这本身要查" % e)]
    # 🔴🔴 **把「本闸自己」排除掉，否则它永远红。**
    #    `gates.run()` 只在闸退出码 0 时划账，而这道闸**正因为那笔账而退 1**
    #    ⇒ 跑它→它报自己欠着→退 1→账划不掉→下次还报。死锁。
    #    ⭐ `[[permanently-red-gate-masks-real-reds]]`：一条永远红的闸信号量是零，
    #      而且会掩盖真红 —— 这是本文件里**同一形状的第二处**
    #      （第一处是 `mutate()` 的基线要求，见那边的注释）。
    #    ⚠️ **按文件认自己，不按名字**（`[[criteria-from-meaning-not-form]]`：
    #      判据问登记表，别写死一个会被改掉的字符串）。
    me = str(Path(__file__).resolve().relative_to(ROOT))
    self_names = {g["name"] for g in gates.GATES if g.get("file") == me}
    for b in gates.self_check():
        bad.append(("V9", "闸名单自检：" + b))
    for n, info in sorted(gates.load().items()):
        if n in self_names:
            continue
        bad.append(("V9", "闸 %s 欠着没跑（这次写库动了 %s）"
                    % (n, "、".join(info.get("tables") or []) or "?")))
    # 🔴 **变异欠账也算红。** 普通档全绿只说明「检查还在」，不说明「检查逮得到东西」。
    for n, why in gates.mutation_debt():
        if n in self_names:
            continue
        bad.append(("V9", "闸 %s **欠一次变异验证**：%s" % (n, why)))
    # 🔴 **自己那笔账照样印出来，只是不计入红** —— 不许因为「不算红」就不说。
    #    （`[[dont-recast-deliverables-as-junk]]`：空结果不是证据，沉默也不是。）
    mine = [n for n in gates.load() if n in self_names] + \
           [n for n, _ in gates.mutation_debt() if n in self_names]
    if mine:
        print("   ⚠️ 本闸自己在台账上欠着（%s）—— **有意不计入红**，"
              "否则它永远红（见 `v9()` 的注释）。跑 `python3 ru/run_gates.py --all` 划账。"
              % "、".join(sorted(set(mine))), file=sys.stderr)
    # 🔴 B14（2026-10-27）：展示层汇总闸在**当前源码**上跑绿过没有。改代码不经过写库，
    #    上面的欠账标不脏它（`css-audit` 红过一个月、etym/layout 红过三周，都没人看见）。
    #    按文件加载，不插 `scripts/` 进 sys.path —— 那会遮掉本门的同名模块。
    import importlib.util
    _sp = importlib.util.spec_from_file_location("display_stamp", ROOT / "scripts" / "display_stamp.py")
    _ds = importlib.util.module_from_spec(_sp)
    _sp.loader.exec_module(_ds)
    bad += [('V9', b) for b in _ds.check()]
    return bad


def v10(con):
    """🔴🔴 **带锁的占位**：`COVERAGE` 现在是空的，而空表必须自己会到期。

    vi 的 W14：「例句的中文译文」原先只是 `COVERAGE` 末尾的一条注释，于是
    阶段表、欠账表、这里**三处一致地看不见它**，最后是用户问出来的。
    ⇒ 一旦库里出现任何内容层（义项/读音/词源/例句/重音/屈折），
      这张表还空着就判红 —— 覆盖率判据必须跟着内容层一起长出来。
    """
    if COVERAGE:
        # 将来有了条目：恒等 100% ＝ 假闸（分母套分子必然精确相等）
        bad = []
        for name, floor, sql, why in COVERAGE:
            try:
                v = (sql(con) if callable(sql)
                     else (con.execute(sql).fetchone()[0] or 0))
            except sqlite3.Error as e:
                bad.append(("V10", "覆盖率 %s 查不了：%s" % (name, e)))
                continue
            if v < floor:
                bad.append(("V10", "覆盖率 %s ＝ %.2f%% 低于下限 %.2f%%（%s）"
                            % (name, v, floor, why[:40])))
            if abs(v - 100.0) < 1e-9:
                # 🔴 `100.00%%` 的 `%` 要转义。第一版写的是 `100.00%`，于是这条断言
                #    一触发就是 `TypeError` **而不是报红** —— 而它从建闸起
                #    **一次都没被执行过**（`COVERAGE` 一直是空的，走不到这一支）。
                #    ⭐ 逮到它的是阶段 2 改写后的 V10 变异：
                #      **带锁的豁免兑现之后，验它的变异必须跟着翻面** ——
                #      翻面的第一次运行就把这个躺了一天的 bug 打出来了。
                bad.append(("V10", "覆盖率 %s 恒等 100.00%% —— **假闸的签名**"
                            "（分母套了分子）" % name))
        return bad
    live = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in COVERAGE_TRIGGERS:
        if t not in live:
            continue
        n = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        if n:
            return [("V10", "🔴🔴 `%s` 已经有 %s 行，而 `COVERAGE` 还是**空的** ——"
                     "占位的锁到期了：覆盖率判据必须跟着内容层一起长出来"
                     "（vi 的 W14：三处一致地看不见一个该有的覆盖率）"
                     % (t, format(n, ",")))]
    return []


# ── 花名册：**独立声明，不从代码里数** ──────────────────────────────────
# `[[expectation-must-be-declared]]`：「编号连续」逮不到删掉最后一条，
# 而最后一条最容易被删。vi 2026-10-05 实证：整段替换切走了夹在中间的两条检查，
# **正常跑报「全绿」，只有 `--mutate` 报了出来**。
def v11(con):
    """🔴🔴 **R11 的锁**：落行的语法标签这一步没有家，而**它不许变成永久状态**。

    阶段 1 的 `criteria.entry_grammar()` 返回两份：落列的四个（已进 `entry`）和
    **落行的那些**（`transitive`／`plural-only`／`semelefactive`…）。
    后者的家是 `sense_tag(bucket='grammar')`，而 `sense` 层要到阶段 5 才有
    ⇒ 这一步它们**一条都没落库**（已存档进 `data/work/ru/stage1_grammar_rows.json`）。

    ⇒ 锁：**`sense` 一非空而 `sense_tag` 里还没有 `bucket='grammar'` 的行就判红。**
      `[[dont-say-source-lacks-what-we-skipped]]`：「源头没有」和「我们没抽」
      要在结构上分开 —— 这一批是**我们还没抽**，而没有锁它就会变成「源头没有」。

    🔴🔴 **2026-10-23 R11 结清之后这条锁自己变瞎过**：它原来查「grammar 桶非空」，
       而义项**自己的**标签里就有 grammar（16.6 万行大部分是义项级的）⇒ 哪天重建义项层时把
       R11 搬进来的 entry 级标签整批弄丢，它照样绿。⇒ 改查 **entry 级出处**
       （`src LIKE 'entry:%'` 或撞车合并的 `'%+entry'`，见 `sense_layer.py`）。
       ⚠️ 「两个数对得上存档」那一半在义项闸 E9，这里只锁「没有整批消失」。
    """
    try:
        ns = con.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
        ng = con.execute("SELECT COUNT(*) FROM sense_tag WHERE bucket='grammar' "
                         "AND (src LIKE 'entry:%' OR src LIKE '%+entry')").fetchone()[0]
    except sqlite3.Error as e:
        return [("V11", "R11 的锁查不了：%s" % e)]
    if ns and not ng:
        return [("V11", "🔴🔴 `sense` 已经有 %s 行，而 **entry 级出处**的 `sense_tag(bucket='grammar')` "
                 "是 0 —— **R11 的锁到期了／搬进来的那批整批消失了**：阶段 1 算出来的那批落行语法标签"
                 "（存档在 `data/work/ru/stage1_grammar_rows.json`）该搬进库了"
                 % format(ns, ","))]
    return []


ROSTER = ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10", "V11")


def v0(rows):
    """**这张检查表自己有没有缺口。**"""
    got = {cid for cid, _ in rows} | {cid for cid in _ran}
    bad = []
    for cid in ROSTER:
        if cid not in got:
            bad.append(("V0", "花名册里的 %s **一次都没跑** —— 检查被删掉了？" % cid))
    for cid in sorted(got - set(ROSTER)):
        bad.append(("V0", "跑了花名册没登记的 %s —— 加检查要同时动花名册" % cid))
    return bad


_ran = set()


def check_brief():
    """给 `dbtool` 用的简表 → [(编号, 说明)]，只含红的。"""
    _ran.clear()
    rows = []
    if not paths.DB.exists():
        return [("V?", "库不存在：%s" % paths.DB)]
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        for cid, fn in (("V1", lambda: v1(con)), ("V2", v2), ("V3", v3), ("V4", v4),
                        ("V5", v5), ("V6", v6), ("V7", v7), ("V8", lambda: v8(con)),
                        ("V9", v9), ("V10", lambda: v10(con)),
                        ("V11", lambda: v11(con))):
            _ran.add(cid)
            rows += fn()
    finally:
        con.close()
    return rows + v0(rows)


def report():
    rows = check_brief()
    print("■ 账的闸（ru）—— 花名册 %d 条" % len(ROSTER))
    if not rows:
        print("   ✅ 全绿（计划表与库、代码、闸台账都对得上）")
    for cid, why in rows:
        print("   🔴 %-4s %s" % (cid, why))
    print("■ %s" % ("通过 ✓" if not rows else "%d 条红" % len(rows)))
    return len(rows)


# ══════════════════════════════════════════════════════════════════════════
# 变异验证
# 🔴🔴 **变异必须自带前提**（`BACKLOG` B20）：不许寄托在「现状恰好是这样」上。
#    vi 48 小时内四次栽在这上面，而**它只在事情做对之后才发作** ——
#    闸红→修好→状态推进→变异所依赖的那个坏前提在现实里不复存在 ⇒ 变异从此空转。
#    ⇒ 下面每条变异都**自己造前提**（注入一个全新的阶段号／全新的欠账号），
#      与「阶段 N 现在是什么状态」彻底脱钩。
# ══════════════════════════════════════════════════════════════════════════
def _write_plan(text):
    PLAN.write_text(text, encoding="utf-8")


def _mutations(orig):
    """→ [(编号, 说明, 改写后的计划表全文)]。每条自带前提。"""
    out = []
    tbl = _table_text()
    head = tbl.split("\n")[3] if len(tbl.split("\n")) > 3 else ""

    # V1：注入一个**全新的阶段号** `X9`，声明 ✅ 且登记一个查不到的交付物
    #     —— 前提由变异自己造，不依赖任何现有阶段的状态
    row = "| **X9** | 变异用的假阶段 | ✅ | 占位 |\n"
    t = orig.replace(head + "\n", head + "\n" + row, 1) if head else orig
    out.append(("V1", "注入假阶段 X9（✅ ＋ 登记一个查不到的交付物）", t, {"X9": [
        ("绝不存在的表", "SELECT COUNT(*) FROM table_that_never_exists")]}))

    # V2：注入假阶段 Y9，声明 ✅ 而**不登记任何交付物**
    row = "| **Y9** | 变异用的假阶段 | ✅ | 占位 |\n"
    t = orig.replace(head + "\n", head + "\n" + row, 1) if head else orig
    out.append(("V2", "注入假阶段 Y9（✅ 而一条交付物都没登记）", t, None))

    # V3：在欠账表之后插一行游离的 📋
    i = orig.find(DEBT_HEAD)
    t = orig[:i] + DEBT_HEAD + "\n\n📋 这是一条游离的记账（变异注入）\n" + orig[i + len(DEBT_HEAD):]
    out.append(("V3", "欠账表之后插一行游离的 📋", t, None))

    # V4：注入**两个**假阶段，前一个未完成而后一个 ✅ —— 倒挂由变异自己造出来
    rows = "| **8** | 变异占位（覆盖真行） | ⬜ | 占位 |\n| **9** | 变异占位 | ✅ | 占位 |\n"
    t = re.sub(r"^\|\s*\*{0,2}8\*{0,2}\s*\|.*$", "", orig, flags=re.M)
    t = re.sub(r"^\|\s*\*{0,2}9\*{0,2}\s*\|.*$", "", t, flags=re.M)
    t = t.replace(head + "\n", head + "\n" + rows, 1) if head else t
    out.append(("V4", "注入「阶段 8 未完成而阶段 9 ✅」的倒挂", t, None))

    # V5：注入假阶段 Z9，状态写「有意不建」而不写推翻条件
    row = "| **Z9** | 变异用的假阶段 | ⬜ 有意不建 | 占位 |\n"
    t = orig.replace(head + "\n", head + "\n" + row, 1) if head else orig
    out.append(("V5", "注入「有意不建」而不写推翻条件的行", t, None))

    # V6：注入一个**全新的重复欠账号** R99 两次
    i = orig.find(DEBT_HEAD)
    j = orig.find("\n", orig.find("|---|", i))
    t = (orig[:j] + "\n| **R99** | 变异占位 | 占位 |\n| **R99** | 变异占位 | 占位 |"
         + orig[j:])
    out.append(("V6", "注入重复欠账号 R99 两次", t, None))

    # V7：注入一条带「影响哪几门」的跨门账
    t = (orig[:j] + "\n| **R98** | 变异占位 ｜ 影响哪几门：de / ja | 占位 |" + orig[j:])
    out.append(("V7", "注入一条跨门的账（该去 BACKLOG）", t, None))
    return out


def mutate():
    orig = _plan()
    # 🔴🔴 **基线判据要排除 V9，否则这道闸永远红。**
    #    V9 盯的是**闸台账的状态**（哪些闸欠着没跑、哪些欠一次变异），
    #    而**本闸自己也在那张台账上** ⇒
    #      「跑变异」需要基线绿 → 基线绿需要「本闸的变异跑过」→ 死锁。
    #    ⭐ `[[permanently-red-gate-masks-real-reds]]`：**一条永远红的闸信号量是零，
    #      而且会掩盖真红。** 换闸不是调低下限，是**换分母**：
    #      变异验证这个动作本身就是去还 V9 那笔账，拿它当前置条件是循环依赖。
    #    ⚠️ **但 V9 的内容照样原样印出来**（下面那几行），不许因为「不计入基线」就不说。
    rows = check_brief()
    # ⚠️ **不许叫 `v9`** —— 那会遮住同名的检查函数，而下面 V9 的变异要调它
    #    （第一版就是这样，报成 `TypeError: 'list' object is not callable`）。
    v9_rows = [(c, w) for c, w in rows if c == "V9"]
    base = [(c, w) for c, w in rows if c != "V9"]
    print("■ 账的闸（ru）—— 花名册 %d 条" % len(ROSTER))
    for cid, why in rows:
        print("   🔴 %-4s %s" % (cid, why))
    if not rows:
        print("   ✅ 全绿")
    if v9_rows:
        print("   ⚠️ 上面 %d 条 V9 **不计入变异的基线要求**（见 `mutate()` 的注释："
              "本闸自己在那张台账上，拿它当前置条件是循环依赖）" % len(v9_rows))
    if base:
        print("\n🔴 基线就不绿（V9 之外有 %d 条），先修基线再做变异验证"
              "（否则分不清是变异还是旧红）" % len(base))
        return 1
    muts = _mutations(orig)
    print("\n■ 变异验证（%d 条；**会原地改写 %s，跑完还原**）" % (len(muts), PLAN.name))
    fails = []
    try:
        for cid, why, text, extra_deliv in muts:
            _write_plan(text)
            saved = None
            if extra_deliv:
                saved = dict(DELIVERABLE)
                DELIVERABLE.update(extra_deliv)
            try:
                rows = check_brief()
                got = {c for c, _ in rows}
                if cid in got:
                    print("   ✅ %-4s %s" % (cid, why))
                elif got:
                    print("   🔴 %-4s 红了，但红的是 %s，不是它自己 —— %s"
                          % (cid, sorted(got), why))
                    fails.append(cid)
                else:
                    print("   🔴🔴 %-4s **一条都没红** —— 判据是假的，或变异是空操作：%s"
                          % (cid, why))
                    fails.append(cid)
            finally:
                if saved is not None:
                    DELIVERABLE.clear()
                    DELIVERABLE.update(saved)
    finally:
        _write_plan(orig)
    # 反控制：还原之后基线必须还是绿的。
    # 🔴 **同一个口径**（排除 V9）—— 第一版这里直接调 `report()`，于是 V9 的 4 条
    #    被印成「计划表没还原干净」。**报错指错了方向比不报更坏**：
    #    它会把人引去查计划表，而计划表是干净的。
    print()
    after = [(c, w) for c, w in check_brief() if c != "V9"]
    if after:
        print("\n🔴🔴 反控制失败：变异跑完后基线不绿了（V9 之外 %d 条）"
              "—— **计划表没还原干净**" % len(after))
        for c, w in after:
            print("   🔴 %-4s %s" % (c, w))
        return 1
    print("■ 反控制：还原之后基线（V9 之外）仍全绿 ✓")
    # 🔴 V8 / V9 / V10 **不靠改写计划表**，它们读的是库与闸台账 ⇒ 单独三条。
    #    花名册里有它们而没有变异 ＝ **两条没验过的检查**，那正是本文件要治的病。
    print("\n■ V8 / V9 / V10 单独验（它们读库与闸台账，不读计划表）：")
    import shutil
    import tempfile
    real = paths.DB
    not_built = not_built_names()[0]
    # ① V8：在库的副本里把「有意不建」的对象建出来
    with tempfile.TemporaryDirectory() as td:
        cp = Path(td) / real.name
        shutil.copy2(real, cp)
        con = sqlite3.connect(cp)
        con.execute("CREATE TABLE %s (id INTEGER PRIMARY KEY)" % not_built)
        con.commit()
        con.close()
        con = sqlite3.connect("file:%s?mode=ro" % cp, uri=True)
        hit = [b for _c, b in v8(con)]
        con.close()
        if hit:
            print("   ✅ V8   逮到：" + hit[0][:92])
        else:
            print("   🔴🔴 V8  没逮到「有意不建的 %s 长出来了」" % not_built)
            fails.append("V8")
    # ② V9：往闸台账里记一笔欠账，看它报不报（**真台账，跑完清掉**）
    try:
        sys.path.insert(0, str(ROOT / "ru"))
        import gates
        name0 = gates.GATES[0]["name"]
        before = gates.load()
        gates.mark([name0], "mutate-v9", ["dict"])
        hit = [b for _c, b in v9() if "欠着没跑" in b]
        gates._save(before)                    # 还原真台账
        if hit:
            print("   ✅ V9   逮到：" + hit[0][:92])
        else:
            print("   🔴🔴 V9  没逮到「有闸欠着没跑」")
            fails.append("V9")
    except Exception as e:                     # noqa: BLE001
        print("   🔴🔴 V9  变异自己炸了：%r" % e)
        fails.append("V9")
    # ③ V10 / V11：往触发表插一行 —— **两条锁同一个触发点、断言不同**，各自验
    with tempfile.TemporaryDirectory() as td:
        cp = Path(td) / real.name
        shutil.copy2(real, cp)
        paths.DB = cp
        try:
            con = sqlite3.connect(cp)
            # 🔴🔴 **B20 第三次（同一天同一个形状）**：第一版写 `id=99, word='беда'`，
            #    而阶段 1 落库后 id 99 与 `беда`（一个真俄语词）都被占用 ⇒ `UNIQUE` 炸。
            #    ⭐ 根子是同一句话：**「我造的那一行不会撞」本身就是一个关于现状的假设。**
            #    ⇒ 负数 id ＋ `«变异»` 前缀的词头，在任何真数据里都不可能存在。
            con.execute("INSERT INTO dict(id,word,word_norm) "
                        "VALUES (-99,'«变异»беда','«变异»беда')")
            con.execute("INSERT INTO sense(id,word_id) VALUES (-99,-99)")
            con.commit()
            con.close()
            # 🔴🔴🔴 **这条变异 2026-10-08 当天就失效了一次，而是它自己报出来的。**
            #    原文只验「空表豁免会到期」那一支（往触发表插一行 ⇒ 判红）。
            #    阶段 2 把 `COVERAGE` 填上之后，`v10()` 走的是**另一支**，
            #    于是插一行什么也不会发生 ⇒ **变异成了空操作而它看起来是绿的**。
            #    ⭐ 这正是 vi 的 V4 那一跤：**前提过期不是锚过期**，
            #      而带锁的豁免兑现之后，验它的变异必须跟着翻面。
            #    ⇒ 按 `COVERAGE` 的状态**分支验**，两支都要有人验：
            con = sqlite3.connect("file:%s?mode=ro" % cp, uri=True)
            if not COVERAGE:
                hit = [b for _c, b in v10(con)]
                con.close()
                branch = "空表豁免到期（插一行内容层 ⇒ 判红）"
            else:
                # 已兑现：改验**填上之后**的两条断言 —— 下限 ＋ 假闸签名。
                #    ⚠️ 直接改 `COVERAGE` 这个模块级常量，跑完还原 ——
                #      这里没有「改写计划表再还原」那条路，锚只能是常量本身。
                saved = list(COVERAGE)
                try:
                    COVERAGE[:] = [
                        ("«变异»下限", 99.99, lambda c: 1.0, "下限必须拦得住"),
                        ("«变异»假闸", 0.0, lambda c: 100.0, "恒等 100% 是假闸签名"),
                    ]
                    hit = [b for _c, b in v10(con)]
                finally:
                    COVERAGE[:] = saved
                con.close()
                branch = "已兑现：下限 ＋ 恒等 100% 两条断言"
                if len(hit) < 2:
                    print("   🔴🔴 V10 只逮到 %d 条，两条断言（下限/假闸签名）"
                          "**各自都要响**：%s" % (len(hit), hit))
                    fails.append("V10")
                    hit = []
            if hit:
                print("   ✅ V10  %s —— %s" % (branch, hit[0][:72]))
            elif "V10" not in fails:
                print("   🔴🔴 V10 锁没响（走的是「%s」那一支）" % branch)
                fails.append("V10")
            # 🔴 V11 同样要**按状态分支验**（V10 上面那一课，V11 当时没跟着翻面 ⇒ R11 结清当天
            #    变异报「锁没响」—— B20 的形状：**只在事情做对之后才发作**）：
            #    · 未结清（真库里还没有 entry 级出处的 grammar）：插一行 sense ⇒ 必须红（上面已插）
            #    · 已结清：在副本里**删掉 entry 级出处的那批** ⇒ 必须红
            rc = sqlite3.connect("file:%s?mode=ro" % real, uri=True)
            settled = rc.execute("SELECT COUNT(*) FROM sense_tag WHERE bucket='grammar' AND "
                                 "(src LIKE 'entry:%' OR src LIKE '%+entry')").fetchone()[0] > 0
            rc.close()
            if settled:
                con = sqlite3.connect(cp)
                con.execute("DELETE FROM sense_tag WHERE src LIKE 'entry:%' OR src LIKE '%+entry'")
                con.commit()
                con.close()
            con = sqlite3.connect("file:%s?mode=ro" % cp, uri=True)
            hit11 = [b for _c, b in v11(con)]
            con.close()
            if hit11:
                print("   ✅ V11  锁兑现（%s）：%s" % ("已结清支：删掉 entry 级标签" if settled
                                             else "未结清支：sense 非空", hit11[0][:72]))
            else:
                print("   🔴🔴 V11 锁没响 —— R11 会变成永久状态")
                fails.append("V11")
        finally:
            paths.DB = real
    print("\n%s" % ("■ 变异验证全过 ✓" if not fails
                    else "🔴 %d 条没逮到：%s" % (len(fails), fails)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    raise SystemExit(mutate() if a.mutate else (1 if report() else 0))


if __name__ == "__main__":
    main()
