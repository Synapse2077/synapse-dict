#!/usr/bin/env python3
"""**账的闸（ja）** —— `docs/JA_PLAN.md` 说的话，与库和代码对不对得上。2026-09-15。

═══ 🔴🔴 这个文件迟到了，而迟到本身就是它要逮的那个病 ═══
`ja/` 从阶段 -2 一路做到阶段 4b，**一个 tests 目录都没有**。而 `ja/dbtool.py`
（从 `de/dbtool.py` 拷来）的三道挂钩全是这个形状：

    p = HERE / "tests" / "test_plan_ledger.py"
    if not p.exists():
        return                      # ← 文件不在就**静默返回**

⇒ `_ledger_gate` / `_regression_check` / `_literal_gate` 在 ja 的**每一次写库**上
   都什么都没做，而写库日志照样打「■ 不变量核对通过 ✓」。
   我看着那行绿字做完了九个阶段，**没注意到「账的闸通过 ✓」那一行从来没出现过**。

⚠️ 这不是 dbtool 写错了 —— 拷贝一份新语种时那三个文件确实还不存在，
   静默跳过是对的。错的是**没有任何东西提醒我把它们补上**。
   ⇒ 本文件的 FILES["-2"] 把这三个文件登记成阶段 -2 的交付物：
     阶段 -2 已经声明 ✅，所以少任何一个，这道闸当场红。**它先逮自己。**

═══ 这道闸拦的四件事 ═══
**P1 —— 阶段表标着 ✅，交付物却是空的。**（fr 上真发生过：阶段 5 声明完成，
   而关系层 0 条、频次层根本不存在，漏了七天）
**P2 —— 记账散落。** 欠账表之后不许再有游离的 📋。
**P4 —— 依赖倒挂。** 翻译（3b）没完成，后面的阶段一个都不许声明 ✅。
**P6 —— 🔴 覆盖率过期。**（**ja 独有，见下**）

═══ P6 为什么是 ja 才有的 ═══
阶段 4b 的事故：阶段 1 报「读音覆盖 99.90%」，那个数当时**是真的**；
阶段 3a 收词之后库里多了 13.4 万个一个读音都没有的词元，覆盖率掉到 **39.8%**，
而**没有任何一道闸会响** —— 阶段 1 的写库闸门锁的是「当时写进去多少行」。

    行数闸问的是「我写了多少」        ← 自比，后面再插进来一批空的它照样全绿
    覆盖率闸问的是「读者拿到多少」      ← 分母会变，稀释了它就红

同一个形状 pt 上发生过一次（收词之后变形层没重跑，46.2% 空白页），
ja 上又发生了一次（读音层）。**两次我都写了教训，第二次照犯**
（`[[lesson-must-become-mechanism]]`：写成文字的守不住，做成机制的守得住）。
⇒ P6 不再写教训，它**按读者口径**问三个数，任何后续收词稀释了都会响。

用法：
    python3 ja/tests/test_plan_ledger.py          # 明细
    python3 ja/tests/test_plan_ledger.py --mutate # 变异验证：一条永远通过的检查等于没检查
"""
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                        # noqa: E402

ROOT = paths.ROOT
PLAN = ROOT / "docs" / "JA_PLAN.md"
TABLE = "## 五、阶段表"
SHEET = "## 六、📋 欠账"


# ══════════════════════════════════════════════════════════════════
# 交付物三类，每类都得**真的能红**。
# 🔴 fr 第一版把阶段 7、9 写成 `SELECT 1` —— 永远为真，等于没查。
DELIVERABLE = {
    "0":   [("dict 词形表", "SELECT COUNT(*) FROM dict"),
            ("十四张 v3 表都建了",
             "SELECT (SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
             "('entry','sense_src','sense','sense_gloss','sense_tag','sense_relation',"
             "'pronunciation','inflection','example','example_gloss','collocation',"
             "'collocation_gloss','audio','field_src'))=14")],
    "1":   [("entry 词条层", "SELECT COUNT(*) FROM entry"),
            ("sense_src 证据层", "SELECT COUNT(*) FROM sense_src")],
    # 🔴 1.5a 交付的是**免费**那一段，判据不能写「sense_gloss 非空」——
    #    那条从阶段 1 起就为真。要问的是三种语言各自到位没有。
    "1.5a": [("出版义项层", "SELECT COUNT(*) FROM sense"),
             ("英文释义", "SELECT COUNT(*) FROM sense_gloss WHERE lang='en'"),
             ("日语原文释义", "SELECT COUNT(*) FROM sense_gloss WHERE lang='ja'"),
             ("免费中文释义（零模型调用那一批）",
              "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND src NOT LIKE 'model:%'")],
    "1.5b": [("英译中的付费释义",
              "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' "
              "AND src='model:deepseek-v4-flash'")],
    # 🔴🔴 阶段 1f（2026-09-20 补）。**这一层在 ja 上整个缺席过三个月**：
    #    `scripts/ingest_etymology.py` 2026-09-14 就有，ja 09-15 开建却没进它的语种名单 ——
    #    而当时阶段表全 ✅、四道闸全绿，因为**阶段表对没列进阶段表的层结构性失明**。
    # 🔴 第二条断言不能省。「表非空」挡不住这一层最典型的失效方式：
    #    `etymology.edition` 写 `en-edition` 而展示层的键取裸词源号（`1`），
    #    两边各自自洽、拼起来对不上 ⇒ **40,270 行一条都到不了页面，而且一声不吭**
    #    （`[[correct-steps-can-compose-a-hole]]`）。⇒ 要问的是「配对得上几条」。
    "1f":  [("etymology 词源正文层", "SELECT COUNT(*) FROM etymology"),
            ("正文与义项那一侧的键真的配得上（不是各自自洽）",
             "SELECT COUNT(*)>30000 FROM etymology e WHERE EXISTS("
             "  SELECT 1 FROM entry en WHERE en.word_id=e.word_id"
             "   AND en.src=e.edition AND en.etym_no=e.etym_no)")],
    "2":   [("inflection 变形层", "SELECT COUNT(*) FROM inflection"),
            # 变形词形必须真的降级成 is_lemma=0，否则"建了变形层"只是多了一张表
            ("变形词形已降级", "SELECT COUNT(*) FROM dict WHERE is_lemma=0")],
    # 🔴 阶段 3a 的判据不能写「dict 非空」——阶段 0 就为真。
    #    它交付的是**跨版收词 + 回头重连 base_id** 两件事，各查一条。
    "3a":  [("日语版/中文版收进来的 entry",
             "SELECT COUNT(*) FROM entry WHERE src IN ('ja-edition','zh-edition')"),
            ("重连后的 base_id（悬空必须基本清干净）",
             "SELECT COUNT(*)<2000 FROM inflection WHERE base_id IS NULL")],
    "3b":  [("日译中的付费释义",
             "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' "
             "AND src='model:deepseek-v4-flash:from-ja'")],
    # 🔴 阶段 4 的四样东西是**四种不同的数据**，只查 pronunciation 非空
    #    等于「补了假名、声调是 0」也能宣布做完（pt 收尾单 C3 就是这个病）。
    "4":   [("pronunciation 音标层", "SELECT COUNT(*) FROM pronunciation"),
            ("声调（唯一可用来源是中文版）",
             "SELECT COUNT(*) FROM pronunciation WHERE pitch_mark IS NOT NULL"),
            ("IPA", "SELECT COUNT(*) FROM pronunciation WHERE ipa IS NOT NULL")],
    # 4b 交付的是**收词那一批补上了读音**，判据必须挑出那一批的来源，
    # 否则阶段 1 写的 head_templates 让它永远为真。
    "4b":  [("收词那批补上的读音",
             "SELECT COUNT(*) FROM entry WHERE kana_src IN ('ja-edition','zh-gloss-head')")],
    "5":   [("example 例句层", "SELECT COUNT(*) FROM example"),
            ("关系层（不含 alt_of —— 那是变形指针不是语义关系）",
             "SELECT COUNT(*) FROM sense_relation WHERE kind<>'alt_of'"),
            ("频次层", "SELECT COUNT(*) FROM pragma_table_info('dict') WHERE name='freq_zipf'")],
    # 🔴 5d 的判据不能写「alt_of 非空」—— 阶段 5b 已经让它非空了，那条对 5d 永远为真。
    #    5d 交付的是**补收的那批词形真的能搜到、且点进去不是空白页**，两条分开断言。
    "5d":  [("补收的 soft-redirect 词形进了 dict",
             "SELECT COUNT(*)>25000 FROM dict d WHERE EXISTS("
             "  SELECT 1 FROM sense_relation r WHERE r.word_id=d.id AND r.kind='alt_of')"
             " AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"),
            ("它们都拿到了指向（不是空白页）",
             "SELECT COUNT(*)=0 FROM dict d WHERE NOT EXISTS("
             "  SELECT 1 FROM sense s WHERE s.word_id=d.id) AND NOT EXISTS("
             "  SELECT 1 FROM inflection i WHERE i.word_id=d.id) AND NOT EXISTS("
             "  SELECT 1 FROM sense_relation r WHERE r.word_id=d.id) AND d.is_lemma=1"
             " AND d.id > (SELECT MAX(id)-31202 FROM dict)")],
    "6":   [("audio 录音元数据", "SELECT COUNT(*) FROM audio")],
    # 🔴 阶段 9 交付的不只是「表非空」——**表在而内容陈旧**是它最典型的失效方式。
    #    第二条断言直接问「预计算的第一名和实时查询的第一名一样吗」。
    "9":   [("搜索前缀预计算表", "SELECT COUNT(*) FROM search_prefix"),
            ("预计算表记了指纹（没记就无从判断陈旧）",
             "SELECT COUNT(*) FROM search_prefix_meta WHERE k='dict_fingerprint'"),
            ("优化器统计信息在（没有它规划器会从选择性最差那头入手）",
             "SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'"),
            ("读取路径的索引在（inflection.base_id，缺它每开一个词条页全扫 56 万行）",
             "SELECT COUNT(*) FROM sqlite_master WHERE type='index'"
             " AND name='idx_infl_baseid'")],
}

FILES = {
    "-2": [("路径声明", "ja/paths.py"),
           ("写库闸门", "ja/dbtool.py"),
           # 🔴 下面三条就是本文件开头说的那个洞。阶段 -2 已声明 ✅ ⇒ 少一个当场红。
           ("账的闸（本文件）", "ja/tests/test_plan_ledger.py"),
           ("字面量闸", "ja/tests/test_no_literal_counts.py"),
           ("备份保留策略的行为测试", "ja/tests/test_prune_backups.py")],
    "-1": [("三份源的实测存档", "docs/JA_PLAN.md")],
    # 🔴 词源层是**七门共用一个脚本**，ja 的交付物就是「它的名单里有 ja」＋「跨门那道闸认 ja」。
    #    第二个文件登记在这儿是有意的：这一层缺席三个月**正是因为跨门的闸没登记 ja**，
    #    只登记入库脚本，等于把当初那个洞原样留着。
    "1f": [("词源层入库脚本（七门共用）", "scripts/ingest_etymology.py"),
           ("跨语种词源契约闸", "apps/web/src/contract-check-etym.tsx")],
    # 🔴 阶段 7 交付**两道**闸，不是一道。只登记回归闸等于另一道干不干都能过 ——
    #    而它们问的是**没有交集的两个问题**（`[[external-anchor-gates]]`）：
    #    回归闸问「过去的修复还在不在」（锚自己，会过期），
    #    外锚闸问「源头有而我们没有的还剩多少」（锚 dump，永不过期）。
    "7":  [("回归闸", "ja/tests/test_no_regression.py"),
           ("外锚闸", "ja/pipeline/verify_vs_dump.py")],
    "9":  [("搜索预计算构建器", "ja/pipeline/build_search_prefix.py")],
    "8":  [("展示层契约闸", "apps/web/src/contract-check-ja.tsx"),
           ("服务层 API 契约闸", "scripts/contract/service_api.ts"),
           ("日语标签层", "packages/dict-labels/src/ja.ts")],
}

# 阶段 8 的交付物是**展示层真的改了读取路径**。
# 🔴 判据来自 `[[it-display-layer-stage8]]`：数据层全绿、库里查得到，而 `french.ts` 里
#    `FROM audio` 出现 0 次 ⇒ 39 万条录音一个用户都看不见。**"落库成功"证明不了"到达用户"。**
CODE = {
    # 🔴 阶段 8 交付**三样**，少登记一样就是那一样干不干都能过：
    #    读取层（真的查了多表）／视图（真的渲染了日语特有字段）／展示层契约闸。
    "8": [("读取层已接上日语库", "packages/dict-core/src/japanese.ts", "FROM sense"),
          ("读取层已在服务注册表里", "packages/dict-core/src/index.ts",
           "JapaneseDictService"),
          # `[[it-display-layer-stage8]]`：库里查得到 ≠ 读者看得见。
          # fr 那轮 39 万条录音躺在库里，而 `french.ts` 里 `FROM audio` 出现 0 次。
          ("视图印了假名读音", "apps/web/src/App.tsx", "JapaneseEntryView"),
          ("词性走了日语覆盖层（不是全局表）", "apps/web/src/App.tsx",
           "JA_POS_LABELS"),
          # 🔴 兜底白名单：未接线的语种必须**明说没接**，不许悄悄落进西语视图
          ("展示层兜底不再是「其余全部走西语」", "apps/web/src/App.tsx",
           "'de', 'ja'].includes(entry.lang)")],
}


# ══════════════════════════════════════════════════════════════════
# P6 —— **按读者口径问的覆盖率**。见文件头「P6 为什么是 ja 才有的」。
#
# 🔴 阈值都是**实测值往下留一点余量**，不是拍的；后续收词把它稀释到阈值以下就该红，
#    那正是这道闸存在的理由。⚠️ 别因为收了一批新词就把阈值调低 —— 调低＝把闸关掉。
COVERAGE = [
    ("义项的中文覆盖率", 95.0,
     "SELECT 100.0*COUNT(DISTINCT g.sense_id)/(SELECT COUNT(*) FROM sense) "
     "FROM sense_gloss g WHERE g.lang='zh'",
     "阶段 1.5b/3b 的落点。3a 收词那次它从 98.66% 掉到 70.77%"),
    ("词元的假名读音覆盖率", 75.0,
     "SELECT 100.0*COUNT(DISTINCT CASE WHEN kana IS NOT NULL THEN word_id END)"
     "/COUNT(DISTINCT word_id) FROM entry",
     "阶段 4b 的落点，实测 81.5%。3a 收词那次它从 99.90% 掉到 39.8% 而没有闸会响"),
    # 🔴 判据 2026-09-16 加了第三档「有跳转」。**改判据之前先把数据建出来了**：
    #    阶段 5b 补收 31,202 个 `soft-redirect` 词形（`あいする`/`いんりょく`/`AA`），
    #    它们没有义项也没有变形，有的是**指向**（`→ 愛する`）。
    #    读者点进去看到一条跳转不是空白页，那正是源头说它是的东西。
    #    ⚠️ 顺序不能反：先补数据、再放宽判据。反过来就是
    #       `[[proxy-metric-gets-optimized]]`——为了让指标好看而动指标。
    #       实测轨迹可查：补完词 93.9%（闸红了），建完关系 98.3%。
    # 阶段 4c（2026-09-18）。🔴 **分母是「常用汉字」不是「全部汉字」** ——
    #   全库 15,492 个 character 条目里 11,339 是**表外字**，读者基本不查，
    #   拿全库当分母算出来是 10.1%，那个数既不反映读者体验也不会因回归而动
    #   （`[[measure-landing-not-source]]` 的分母版本）。
    #   ⚠️ 上限就在 53.5% 附近：缺的 956 个常用字里 **953 个日语版根本没有条目**
    #   （逐字验过，不是抽样），`評` 那 2 条源头没给分类标记、属 `entry.kana` 那一层。
    #   **源头没写 ≠ 我们没抽**（`[[dont-say-source-lacks-what-we-skipped]]`）⇒
    #   这个数涨不上去是正常的，**掉下来才是回归**。
    ("常用汉字的音訓読み覆盖率", 50.0,
     "SELECT 100.0*COUNT(DISTINCT CASE WHEN EXISTS("
     "  SELECT 1 FROM kanji_reading k WHERE k.entry_id=e.id) THEN e.id END)"
     "/COUNT(DISTINCT e.id) FROM entry e"
     " WHERE e.pos_raw='character' AND e.kanji_grade='常用'",
     "阶段 4c 的落点，实测 53.5%。这一层是补一条写滑了的判据才有的："
     "JA_PLAN §二.4 从「汉字没有**单一**读音」推到了「不用补」，"
     "而汉字有的是一组**分类**读音（呉音/漢音/唐音/訓/古訓/名乗り），日语版写了我们没抽"),
    # 阶段 1d（2026-09-18）。⚠️ 8.3% 看着低，但**上限就在这儿**：源头带非结构性
    #   标签的义项本来就只有这么多，而 ja/zh 两版的 `sense_src.sense_id` 全是 NULL、
    #   挂不回去（见阶段 1d 那行）。⇒ 这个数涨不上去是正常的，**掉下来才是回归**。
    #   🔴 它与词元数挂钩：阶段 3a 那种收词会**稀释分母**，而行数闸对此结构性失明
    #      （60,469 行一条没少，覆盖率却掉了）。
    ("义项标签覆盖率", 5.0,
     "SELECT 100.0*COUNT(DISTINCT sense_id)/(SELECT COUNT(*) FROM sense) FROM sense_tag",
     "阶段 1d 的落点，实测 8.3%。这张表建好之后**空了整整一个项目** —— "
     "行数闸问「我写了多少」，0 行也是一致的，逮到它的是逐张表数了一遍"),
    # 阶段 2 修表结构（2026-09-19）。🔴 **分母是「带现代活用表的动词」不是全部动词** ——
    #   英文版只给 108 个词完整的 `ja-conj-ex` 表，而它们正好是读者最常查的
    #   （`食べる`/`書く`/`見る`/`する`/`来る`）。
    #   ⚠️ 这一条盯的是**普通体那几列还在不在**：修之前它们被当成源头抽取报错
    #   整行丢掉，`食べる` 页上有「食べます」没有「食べない」，而**行数闸全绿**
    #   （少收的那 10.3% 从来没被计入过分母）。
    #   🔴 计数型断言（回归闸 I3）问「有没有」，0 也可能是一致的；这条问「占比」，
    #   源头哪天多给 100 张表而只修好一半，它会掉下来。
    ("带现代活用表的动词里有普通体的占比", 90.0,
     "SELECT 100.0*COUNT(DISTINCT CASE WHEN p.base IS NOT NULL THEN t.base END)"
     "/COUNT(DISTINCT t.base) FROM"
     " (SELECT DISTINCT base FROM inflection WHERE src_ref LIKE '%:ja-conj-ex#%') t"
     " LEFT JOIN (SELECT DISTINCT base FROM inflection"
     "   WHERE src_ref LIKE '%:ja-conj-ex#%' AND tags='[\"negative\"]') p"
     " ON p.base=t.base",
     "阶段 2 修表结构的落点。修之前是 0% —— 源头认不出的格子打 "
     "`error-unrecognized-form`，我们整行丢弃，丢的正好是普通体那几列"),
    # 阶段 4/§四.2（2026-09-19）。🔴 **这一条就是「声调够不够上页面」的判据本身。**
    #   全库词元的声调覆盖只有 7.4%，但全库里大量是生僻词，那个数没有决策价值；
    #   换成核心词（`core_level` 来自 Waller 表）＝ 42.4%，而自有 `freq_zipf` 前 5,000
    #   给出 42.6% —— **两把独立的尺子收敛**，结论不依赖任何一份词表。
    #   ⚠️ 上限就在这儿：中文版 dump 里带声调的只有 18,534 个词形，我们收了 18,469，
    #   **是源头天花板不是抽漏**（逐条回源数过）。⇒ 这个数涨不上去正常，**掉下来才是回归**。
    ("核心词的声调覆盖率", 35.0,
     "SELECT 100.0*COUNT(DISTINCT CASE WHEN EXISTS("
     "  SELECT 1 FROM pronunciation p WHERE p.word_id=d.id AND p.pitch_pos IS NOT NULL)"
     "  THEN d.id END)/COUNT(*) FROM dict d WHERE d.core_level IS NOT NULL",
     "§四.2 的判据。实测 42.4%，N5 55.1% → N1 35.6%。"
     "结案为 auxiliary（有则显示、不做默认模块），推翻条件见 JA_PLAN §四.2"),
    # 词源层（2026-09-20）。🔴 **分母是「源头这一支写了正文的」不是全部词条** ——
    #   英文版 46,196 个条目带 `etymology_text`（23.2%），其余是源头自己没写，
    #   拿全库当分母算出来的数只反映维基的编纂密度，不反映我们抽没抽。
    #   ⚠️ 这一层在 ja 上**整个缺席过三个月**，而阶段表全 ✅、三道闸全绿 ——
    #   是收尾时逐个点名核对六门共有的层才看见的。⇒ 掉下来就是它又没跑。
    # 🔴 **第一版我把分母写成了「有词源正文的词」** —— 分母里套了
    #   `EXISTS(… FROM etymology …)`，于是这个数**恒等于 100%**，是一道假闸。
    #   同一天我刚因为这个毛病修过 P6 的 M1d（变异稀释量够不到下限），**自己又犯一次**。
    #   ⇒ 分母换成「有 en-edition 词条的词形」：收词会稀释它，层没重跑它会掉。
    ("有英文版词条的词里带词源正文的占比", 30.0,
     "SELECT 100.0*(SELECT COUNT(DISTINCT word_id) FROM etymology)"
     "/(SELECT COUNT(DISTINCT word_id) FROM entry WHERE src='en-edition')",
     "实测 36.74%（36,607 / 99,632）。上限就在这儿：英文版 dump 里只有 23.2% 的条目"
     "带 `etymology_text`，日语版与中文版**各 0 条** ⇒ 涨不上去正常，掉下来才是回归"),
    ("**不是**空白页的词形占比", 95.0,
     "SELECT 100.0*(SELECT COUNT(*) FROM dict d WHERE EXISTS("
     "  SELECT 1 FROM sense s WHERE s.word_id=d.id) OR EXISTS("
     "  SELECT 1 FROM inflection i WHERE i.word_id=d.id) OR EXISTS("
     "  SELECT 1 FROM sense_relation r WHERE r.word_id=d.id AND r.kind IN ('alt_of','see_also')))"
     "/(SELECT COUNT(*) FROM dict)",
     "pt 栽在这儿：46.2% 的词形搜得到、点进去空白"),
]


def p6(con):
    bad = []
    for name, floor, sql, why in COVERAGE:
        try:
            got = con.execute(sql).fetchone()[0]
        except sqlite3.Error as e:
            bad.append(("P6", "覆盖率判据跑不了：%s（%s）" % (name, e)))
            continue
        if got is None or got < floor:
            bad.append(("P6", "%s **%.1f%%**，低于下限 %.1f%% —— %s"
                        % (name, got or 0.0, floor, why)))
    return bad


# ══════════════════════════════════════════════════════════════════
# 阶段表的行：`| **4b** | **读音回补** | **✅ 已完成** | 3a,4 | … |`
# ⚠️ 阶段号可以带字母后缀（`4b`）。只认数字的正则会**静默漏掉一整个阶段**。
ROW = re.compile(r"^\|\s*\**\s*(-?[0-9.]+[a-z]?)\s*\**\s*\|(.+?)\|(.+?)\|", re.M)
MARKS = ("✅", "🔄", "📋", "⬜", "⚪")


def _status(state):
    """状态栏 → 三个标记里**最先出现的那一个**。

    🔴 de 2026-09-03 的真事故：判据写成 `"✅" in state`（子串命中），
       而我把状态栏写成「🔄 **1.5a ✅ 已落库**／1.5b 未跑」—— 一个诚实的进行中状态 ——
       整阶段被判成已完成，连着 P4 失效。**闸没坏，是它读错了地方**：
       状态只由开头那个标记表示，后面是散文。
    """
    pos = [(state.index(m), m) for m in MARKS if m in state]
    return min(pos)[1] if pos else None


def declared_done():
    """→ {阶段号: 标题}，只含**状态栏首标记为 ✅** 的。"""
    s = PLAN.read_text(encoding="utf-8")
    i = s.index(TABLE)
    tbl = s[i:s.index("\n## ", i + 4)]
    out = {}
    for m in ROW.finditer(tbl):
        num, title, state = m.group(1), m.group(2), m.group(3)
        if _status(state) == "✅":
            out[num] = title.strip().strip("*").strip()
    return out


def p1(con):
    """阶段表声明 ✅ 的阶段，交付物必须真的在。"""
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
    """欠账表之后不许有游离的 📋 —— 新记账只能进那张表。"""
    s = PLAN.read_text(encoding="utf-8")
    if SHEET not in s:
        return [("P2", "欠账表章节不存在（%s）—— 记账没有家，必然重新散开" % SHEET)]
    tail = s[s.index(SHEET):]
    stray = [ln.strip() for ln in tail.splitlines()
             if "📋" in ln and not ln.startswith(SHEET)
             and not ln.lstrip().startswith(("|", ">"))]
    return [("P2", "欠账表之后有 %d 条游离记账（应进表）：%s"
             % (len(stray), stray[0][:60]))] if stray else []


# P4 —— **翻译（3b）没做完，后面的阶段一个都不许声明完成。**
# 🔴 理由与 de 的 P4 相同（用户 2026-09-01「必须等翻译这一步做完再说」），
#    但 ja 的付费翻译分两段：1.5b 英译中、3b 日译中。**卡在后一段**——
#    因为 3a 收词把中文覆盖从 98.66% 打到 70.77%，1.5b 做完并不代表读者拿到了中文。
AFTER_TRANS = ("4", "4b", "5", "5a", "5b", "6", "7", "8", "9")


def p4():
    done = set(declared_done())
    if "3b" in done:
        return []
    early = sorted(x for x in AFTER_TRANS if x in done)
    if not early:
        return []
    return [("P4", "阶段 3b（日译中）还没完成，但阶段 %s 已声明 ✅ —— "
                   "收词后中文覆盖只有 70.77%%，翻译没落库就往下走＝在半成品上加层"
             % "、".join(early))]


# ══════════════════════════════════════════════════════════════════
# P7 —— **「有意不做」的行必须写清什么会推翻它**（PLAYBOOK §7.5）。
#
# 🔴🔴 起因是 ja 阶段 6 的真事故：账上写着「三版并集只有 206 个词形有 mp3_url，
#    **别排工**」。事实对、结论错 —— 那句话把「dump 里没有」等同于「拿不到」，
#    而日语版维基词典只是不在词条里嵌音频，Commons 分类里有约 1,500 个文件。
#    实际收到 1,038 条 / 953 个词形，最常用 500 个词里 16.2% 有录音。
#
# ⚠️ **闸天然管不到这一类**：P1 核的是「声明做了的，交付物在不在」。
#    声明**不做**的行没有交付物，于是它一写下去就成了永久前提 ——
#    我引用了三次都没回源核，最后是用户问出来的。
#
# ⚠️ 而 `PLAYBOOK` §十一.2 早就写着「先问是不是已经有人做好了」，
#    **点名的例子就是「真人录音」**。原则在、例子在、照样踩第四次。
#    ⇒ `[[lesson-must-become-mechanism]]`：再写一句话没用。这就是那个"会响的东西"。
#
# 判据：**行里写着「有意不做」**的，详情里必须出现推翻条件。
#
# 🔴 判据**不看 ⚪ 这个符号**。第一版我写的是「状态栏首标记是 ⚪」——
#    又一次拿形式当判据。实测：`⚪` 在 pt/de/fr 的计划表里是**另一个意思**，
#    pt 的图例白纸黑字写着「⚪ **不是缺陷** ｜ 我当初量错了 / 已被后续步骤解决」。
#    按符号判会在**37 行**上误报，而那些行说的是"已解决"，不是"决定不做"。
#    ⇒ 同一个符号在六张计划表里含义不同；判据要问**这一行在说什么**
#      （`[[criteria-from-meaning-not-form]]`）。
#    ⭐ 顺带：换成含义判据之后，这道闸**可以原样搬到别的语种**而不会误报 ——
#      形式判据搬不动，含义判据搬得动。
#
# 🔴 判据故意**不问「有没有数字」**—— ja 阶段 6 原来**是有数字的**（206），
#    有数字照样烂掉。缺的是"什么会让这个数字不再成立"。
NEGATIVE = "有意不做"
FALSIFIER = ("推翻它需要", "什么会推翻", "重新评估的条件", "重新开工的条件")


def p7():
    s = PLAN.read_text(encoding="utf-8")
    i = s.index(TABLE)
    tbl = s[i:s.index("\n## ", i + 4)]
    bad = []
    for m in ROW.finditer(tbl):
        num, title, state = m.group(1), m.group(2), m.group(3)
        nl = tbl.find("\n", m.end())
        row = tbl[m.start():nl if nl > 0 else len(tbl)]
        # 🔴 **「有意不做」必须出现在状态列里**，不是整行里。
        #    第一版我搜整行 ⇒ 阶段 4b 和阶段 6 当场误报：它们是 ✅，
        #    只是**详情的散文里提到了这四个字**（4b 写着「有意不做的两件事」，
        #    6 写着「原来标着⚪有意不做，那个结论是错的」）。
        #    判据要问的是**这一行的状态是什么**，而不是"这一行有没有提过这个词"。
        #    ⚠️ 同一轮里我已经把判据收窄过一次（符号 → 含义），这是第二次：
        #       换成含义判据之后，**范围**又宽了。判据对、范围宽，症状一样。
        if NEGATIVE not in state:
            continue
        if not any(k in row for k in FALSIFIER):
            bad.append(("P7", "阶段 %s「%s」标着⚪有意不做，但**没写什么会推翻它** —— "
                              "否定结论不写推翻条件就是永久前提（PLAYBOOK §7.5，"
                              "ja 阶段 6 正是这么烂掉的）" % (num, title.strip()[:24])))
    return bad


def p8():
    """🔴🔴 **欠账表里同一个编号不许出现两次。**

    2026-09-20 用户问「ja 的欠账不是都完成了吗」，一解析发现 **8 号有两行，而且结论相反**：
    一行 ✅（收词闸建了）、一行 🔴（清单没建）。两行各对一半，于是**这张表同时说了"还了"
    和"没还"**，读者按哪行都不算读错。

    ⇒ 而 P1–P7 对它**结构性失明**：它们查阶段交付物在不在、查 ⚪ 有没有写推翻条件，
      **没有一条查账本自己的完整性**。与同一轮里逮到的两个洞是同一个形状 ——
      「闸查的是登记了的那几条对不对，没有一条查登记表本身有没有毛病」
      （`contract-check-etym.tsx` 的 `registryGate`、`gen_manifest.py` 的未登记自检）。
    """
    s = PLAN.read_text(encoding="utf-8")
    # 🔴 表整个不在是 **P2 的职责**，P8 只管「表里有没有重号」。
    #    第一版这里直接 `s.index(SHEET)` ⇒ 标题一没就抛异常，**当场把已有的变异 M9 打坏了**
    #    （报「变异自己抛异常」而不是「M9 被逮到」）。
    #    ⚠️ 新加一条断言**把别人的变异弄死**，比这条断言本身漏报更难发现 ——
    #      它看起来像"变异写错了"，而不是"我刚加的东西越界了"。
    if SHEET not in s:
        return []
    tail = s[s.index(SHEET):]
    tail = tail[:tail.index("\n# ")] if "\n# " in tail else tail
    seen, dup = {}, []
    for ln in tail.splitlines():
        if not ln.startswith("| ") or ln.startswith("| #") or set(ln) <= set("| -"):
            continue
        num = ln.strip("|").split("|")[0].strip()
        if not num or not num[0].isdigit():
            continue
        if num in seen:
            dup.append(num)
        seen[num] = seen.get(num, 0) + 1
    return [("P8", "欠账表里编号 %s 出现了 %d 次 —— **同一笔账写两行，结论可能相反**，"
                   "读者按哪行都不算读错。合并成一行，把两半都写进去"
             % (n, seen[n])) for n in sorted(set(dup))]


BACKLOG = ROOT / "docs" / "BACKLOG.md"


def p9():
    """🔴🔴 **这一门的欠账表里不许寄存别门的账。**

    2026-09-20 用户问：「把所有的账都记在顶层，为什么要记在个别语言下？
    你只有记在顶层，才知道所有语言留下来的所有问题啊？」—— 而当时 `JA_PLAN`
    的 24 行欠账里 **12 行牵涉别门**，其中两条干脆就是别人的账：
      · en 的 `Late`/`Middle`（从 ja 开工起躺在这儿，**做 en 的人看不到**）
      · `split_colloc` 的空格判据，写着「日语开工前必须先改」——
        而这个前提早已失效（ja 没有搭配层），**没人会去复查躺在别人账本里的前提**。
    ⇒ 已建 `docs/BACKLOG.md` 当唯一顶层账本，两条搬过去了。

    **判据按含义不按形式**（`[[criteria-from-meaning-not-form]]`）：
    不扫语种码 —— ja 的行里为了对照提到 es/de 是正常的，扫码会满屏假红
    （P7 早就记过这一课：同一个符号在六张计划表里含义不同，按符号判误报 37 行）。
    判据是**「我不得不写下『这不是 ja 的账』」这个动作本身** ——
    写得出这句话，就说明它该搬走。

    ⚠️ 同时验顶层账本**存在**：判据引用它，它没了这条就该红。
    """
    bad = []
    if not BACKLOG.exists():
        return [("P9", "顶层账本 `docs/BACKLOG.md` 不存在 —— 跨门的账没有家，"
                       "必然重新寄存进某一门的计划表")]
    s = PLAN.read_text(encoding="utf-8")
    tail = s[s.index(SHEET):] if SHEET in s else ""
    tail = tail[:tail.index("\n# ")] if "\n# " in tail else tail
    for ln in tail.splitlines():
        if not ln.startswith("| ") or "不是 ja 的账" not in ln:
            continue
        num = ln.strip("|").split("|")[0].strip()
        bad.append(("P9", "欠账 %s 自己写着「不是 ja 的账」——**别门的账不许寄存在这张表里**，"
                          "搬到 `docs/BACKLOG.md`（做那门的人永远不会来 ja 的计划表里找账）"
                    % num))
    return bad


def report(verbose=True):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        red = p1(con) + p2() + p4() + p6(con) + p7() + p8() + p9()
    finally:
        con.close()
    if verbose:
        print("═══ 账的闸（ja）：计划表说的话，库与代码对不对得上 ═══")
        done = declared_done()
        print("   阶段表声明已完成：%s" % ("、".join(sorted(done)) if done else "（无）"))
        con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        for name, floor, sql, _ in COVERAGE:
            try:
                print("   %-22s %6.2f%%（下限 %.1f%%）"
                      % (name, con2.execute(sql).fetchone()[0] or 0.0, floor))
            except sqlite3.Error:
                print("   %-22s 查不了" % name)
        con2.close()
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
# 🔴🔴 **每一条都必须真的把被断言的东西拿走**（pt 那轮有三条只改了文档的状态栏，
#    然后指望世界还是没做完的样子；做完之后变异什么都没变，闸当然不红）。
#    ⇒ 库侧用临时副本删行、文件侧指向不存在的路径、代码侧改表。
import shutil                                        # noqa: E402
import tempfile                                      # noqa: E402

_SRC = None


def _with_plan(text, fn):
    try:
        PLAN.write_text(text, encoding="utf-8")
        return fn()
    finally:
        PLAN.write_text(_SRC, encoding="utf-8")


def _in_table(num, sub_pat, repl):
    """在**阶段表范围内**对阶段 num 那一行做一次替换。→ 新全文，或 None。

    🔴 这个函数存在的唯一理由：**切表这件事只许有一个入口。**
       我先在 `_declare` 里修好了"先切阶段表再替换"（变异 M5 逮到的），
       然后在它旁边写 M13 的变异时又直接 `re.sub(..., re.M)` 了一遍全文 ——
       于是又撞上第二节判据表里更早的 `| 6 |` 行，详情写进了错的表，
       变异什么都没改、闸当然照旧红，报「漏了」。
       **同一个坑，修好之后隔十行再踩一次** ⇒ 判据/工具只许一份
       （`[[refactor-mindset-code-quality]]`：同一文件里两张重复映射表已经发生过）。
    """
    i = _SRC.index(TABLE)
    j = _SRC.index("\n## ", i + 4)
    head, tbl, tail = _SRC[:i], _SRC[i:j], _SRC[j:]
    tbl2, n = re.subn(sub_pat % re.escape(num), repl, tbl, count=1, flags=re.M)
    return head + tbl2 + tail if n == 1 else None


def _set_detail(num, text):
    """把阶段 num 那一行的**详情列**（第 5 列）换成 text。"""
    return _in_table(num, r"(^\|\s*\**\s*%s\s*\**\s*\|[^|]*\|[^|]*\|[^|]*\|)[^|]*\|",
                     r"\1 " + text.replace("\\", "\\\\") + " |")


def _declare(num, mark="**✅ 已完成**"):
    """把**阶段表里**阶段 num 那一行的状态栏改成 mark（不动其他列）。

    🔴 **必须先切到阶段表再替换。** 第一版直接在全文上 `count=1` 替换，于是
       `_declare("7")` 改的是**第二节判据表**的 `| 7 | inflection 装得下 |` ——
       那一行在文件里更早。变异 M5 因此什么都没做，闸当然不红，报「漏了」。
       典型的正则 first-match：**先撞上的那个不一定是你要的那个**
       （`[[regex-alternation-order]]` 的同族，第四次）。
    ⚠️ 逮到它的不是我读代码，是**变异验证**：M5 是十一条里唯一挂的一条。
       这就是为什么变异必须逐条真的把东西拿走 —— 假变异会跟着假绿一起过。
    """
    return _in_table(num, r"(^\|\s*\**\s*%s\s*\**\s*\|[^|]*\|)[^|]*\|",
                     r"\1 " + mark + " |")


def _with_db(sqls, fn):
    """在库的**临时副本**上跑 sqls，再跑 fn。绝不动真库。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / "t.sqlite"
        shutil.copy(paths.DB, tmp)
        con = sqlite3.connect(tmp)
        for s in sqls:
            con.execute(s)
        con.commit()
        con.close()
        real = paths.DB
        try:
            paths.DB = tmp
            return fn()
        finally:
            paths.DB = real


def m_stage4():
    """阶段 4 声明✅ 而声调被删光 —— 只查 pronunciation 非空的判据逮不到。"""
    return _with_db(["UPDATE pronunciation SET pitch_mark=NULL"],
                    lambda: any(c == "P1" and "声调" in w for c, w in check_brief()))


def m_stage4b():
    """阶段 4b 声明✅ 而收词那批的读音没补 —— 阶段 1 写的 head_templates 让整表永远非空。"""
    return _with_db(["UPDATE entry SET kana=NULL, kana_src=NULL "
                     "WHERE kana_src IN ('ja-edition','zh-gloss-head')"],
                    lambda: any(c == "P1" and "收词那批" in w for c, w in check_brief()))


def m_cov_zh():
    """P6：中文释义被删掉一大半 —— 行数闸全绿，覆盖率闸必须红。"""
    return _with_db(["DELETE FROM sense_gloss WHERE lang='zh' AND sense_id % 2 = 0"],
                    lambda: any(c == "P6" and "中文覆盖" in w for c, w in check_brief()))


def m_cov_kana():
    """🔴 P6 的头号场景：**收了一批新词元，一个读音都没有**（阶段 3a 真发生过）。

    ⚠️ 变异要打在闸真正盯着的落点上：落点是**词元覆盖率的分母变大**，
       不是「读音行被删了」。所以这里插新词元而不是删读音 —— 删读音谁都逮得到，
       稀释才是那次没人逮到的形状。
    """
    return _with_db([
        "INSERT INTO dict(word, word_norm, is_lemma) "
        "SELECT word||'㋿'||id, word||'㋿'||id, 1 FROM dict LIMIT 200000",
        "INSERT INTO entry(word_id, word_src, pos, pos_raw, etym_no, seq, src, src_ref) "
        "SELECT id, word, 'n', 'noun', '0', 0, 'mutation', 'mut:'||id "
        "FROM dict WHERE word LIKE '%㋿%'",
    ], lambda: any(c == "P6" and "读音覆盖" in w for c, w in check_brief()))


def m_cov_kanji_reading():
    """🔴 P6 阶段 4c：**常用汉字的音训读没了，表外字的还在**。

    ⚠️ 这条变异要证的不是「删了会红」，是**分母选对了**。
       全库 15,492 个 `character` 条目里 11,339 是表外字 ⇒ 按全库分母算，
       删掉常用字这 1,115 条只把覆盖率从 10.1% 压到 ≈2.6%，一个宽松下限
       照样接得住；按**常用汉字**分母算会直接掉到 0%。
       读者查的是常用字，判据的分母就得是常用字
       （`[[measure-landing-not-source]]` 的分母版本）。
    """
    return _with_db([
        "DELETE FROM kanji_reading WHERE entry_id IN"
        " (SELECT id FROM entry WHERE pos_raw='character' AND kanji_grade='常用')",
    ], lambda: any(c == "P6" and "音訓読み" in w for c, w in check_brief()))


def m_cov_sense_tags():
    """🔴 P6 阶段 1d：**收词稀释**，行数闸对此结构性失明。

    ⚠️ 变异打在**分母**上（插 20 万条新义项、一条标签都没有），不是删标签 ——
       删标签谁都逮得到；阶段 3a 真实发生过的形状是"后面又插进来一批没有的"，
       那时 `sense_tag` 一行没少，行数闸全绿。
    """
    # 🔴 2026-09-19 修：原来写的是 `LIMIT 200000`，**稀释量根本够不到下限** ——
    #    35,181 / (296,549 + 200,000) ＝ 7.08%，下限是 5.0%，永远逮不到。
    #    这条变异从写下来那天起就没跑过 `--mutate`，于是那道 P6 闸一直是假的：
    #    **一条逮不住蓄意破坏的闸，本身就是个没响过的警报器。**
    #    现在插两轮（各一份全量拷贝）⇒ 35,181 / 889,647 ＝ 3.95%，跌破下限。
    return _with_db([
        "INSERT INTO sense(word_id, rank, pos, hidden) "
        "SELECT word_id, rank + 900000, pos, 0 FROM sense",
        "INSERT INTO sense(word_id, rank, pos, hidden) "
        "SELECT word_id, rank + 1900000, pos, 0 FROM sense WHERE rank < 900000",
    ], lambda: any(c == "P6" and "义项标签覆盖" in w for c, w in check_brief()))


def m_cov_plain_forms():
    """🔴 P6 阶段 2：**普通体那几列又被当成源头抽取报错整行丢掉**。

    ⚠️ 变异删的是**普通体**（`tags='["negative"]'`），不是随便删几行 ——
       这正是修之前的状态：`食べる` 页上有「食べます」没有「食べない」，
       而整张表 56 万行**一行都不少**，行数闸全绿。
    """
    return _with_db([
        "DELETE FROM inflection WHERE src_ref LIKE '%:ja-conj-ex#%'"
        " AND tags='[\"negative\"]'",
    ], lambda: any(c == "P6" and "普通体" in w for c, w in check_brief()))


def m_cov_core_pitch():
    """🔴 P6 §四.2：**核心词集合被稀释**，而声调一行都没少。

    ⚠️ 变异打在**分母**上（把一万个生僻词也标成核心词），不是删声调 ——
       删声调谁都逮得到；真正会悄悄发生的是「换了一份更大的核心词表」
       或「收词之后核心词判定跟着变宽」，那时 `pronunciation` 一行不少，
       行数闸全绿，而这个数掉下去。
    """
    return _with_db([
        "UPDATE dict SET core_level=5, core_src='mut' WHERE core_level IS NULL"
        " AND id IN (SELECT id FROM dict WHERE is_lemma=1 AND id NOT IN"
        "            (SELECT word_id FROM pronunciation) LIMIT 10000)",
    ], lambda: any(c == "P6" and "核心词的声调覆盖" in w for c, w in check_brief()))


def m_cov_etymology():
    """🔴 P6 阶段 1f：**词源层整批没跑**（或收词把它稀释了）。

    ⚠️ 变异删掉一半词源行 —— 36.74% → 约 18%，跌破 30% 下限。
       这一层曾经**整个不存在三个月**而所有闸全绿，这道覆盖率闸就是补那个洞的。
    """
    return _with_db([
        "DELETE FROM etymology WHERE id % 2 = 0",
    ], lambda: any(c == "P6" and "词源正文" in w for c, w in check_brief()))


def m_stage7():
    """阶段 7 声明✅ 而回归闸文件不存在 —— **真的把文件挪走**。

    🔴🔴 2026-09-16：本条一度变成**空变异**。原来写的是「把阶段 7 声明成 ✅」，
       那天阶段 7 还是 ⬜、文件也还不存在，所以它红得理直气壮。
       阶段 7 做完之后，声明一遍什么都没变 ⇒ 闸当然不红，报「漏了」，
       而**闸本身是好的**。这正是 de 文件头点名的 pt 失败模式：
       「只把文档的状态栏翻成 ✅，然后指望世界还是没做完的样子」。
    ⇒ 变异必须真的把**被断言的东西**拿走：把文件挪到一边，跑完再挪回来。
    """
    f = ROOT / "ja" / "tests" / "test_no_regression.py"
    if not f.exists():
        return None                       # 文件本来就不在 ⇒ 这条变异没意义
    tmp = f.with_suffix(".py.mutation-bak")
    f.rename(tmp)
    try:
        return any(c == "P1" and "回归闸" in w for c, w in check_brief())
    finally:
        tmp.rename(f)


def m_stage8():
    """阶段 8 声明✅ 而展示层没有日语那份。

    ⚠️ **预先按 M5 的教训写**：阶段 8 还没做，所以「声明 ✅ + 文件不存在」现在就能红；
       但阶段 8 一落地，那种写法立刻变成空变异（见 `m_stage7` 的说明）。
       ⇒ 两条路都留着：文件在就把它挪走，文件不在就靠声明。
    """
    f = ROOT / "packages" / "dict-core" / "src" / "japanese.ts"
    if f.exists():
        tmp = f.with_suffix(".ts.mutation-bak")
        f.rename(tmp)
        try:
            return any(c == "P1" and "japanese.ts" in w for c, w in check_brief())
        finally:
            tmp.rename(f)
    s2 = _declare("8")
    return s2 is not None and _with_plan(
        s2, lambda: any(c == "P1" and "japanese.ts" in w for c, w in check_brief()))


def m_suffix():
    """带字母后缀的阶段号 `5a` 也要被认出来 —— 只认数字的正则会静默漏掉整个阶段。"""
    global _SRC
    _s = _SRC
    try:
        _SRC = re.sub(r"^\| \*\*5\*\* \|", "| **5a** |", _SRC, count=1, flags=re.M)
        s2 = _declare("5a")
    finally:
        _SRC = _s
    return s2 is not None and _with_plan(s2, lambda: "5a" in declared_done())


def m_stray():
    """欠账表之后有游离 📋。"""
    return _with_plan(_SRC + "\n\n📋 顺手记一笔：某某该修\n",
                      lambda: any(c == "P2" for c, w in check_brief()))


def m_no_sheet():
    """欠账表标题消失 —— 记账没有家。"""
    return _with_plan(_SRC.replace(SHEET, "## 六、杂项"),
                      lambda: any(c == "P2" for c, w in check_brief()))


def m_before_trans():
    """🔴 3b 没完成就给阶段 5 打 ✅。"""
    s2 = _declare("3b", "🔄 跑批中")
    if s2 is None:
        return None
    _s = _SRC
    try:
        globals()["_SRC"] = s2
        s3 = _declare("5")
    finally:
        globals()["_SRC"] = _s
    return s3 is not None and _with_plan(s3, lambda: any(c == "P4" for c, w in check_brief()))


def m_prose():
    """状态栏是进行中、散文里提到子步骤 ✅ —— 不许算成已完成。"""
    s2 = _declare("5", "🔄 例句已抽 ✅／关系层未做")
    return s2 is not None and _with_plan(s2, lambda: "5" not in declared_done())


def m_silent_negative():
    """🔴 把阶段 6 改回「⚪ 有意不做」且不写推翻条件 —— 必须红。

    ⚠️ 变异要真的把被断言的东西拿走：这里连**详情列一起换掉**，
       否则原来那段散文里可能恰好带着推翻条件，变异就成了假的。
    """
    global _SRC
    _s = _SRC
    try:
        _SRC = _declare("6", "⚪ **有意不做**") or _SRC
        s2 = _set_detail("6", "三版并集只有 206 个词形有 mp3_url，别排工")
    finally:
        _SRC = _s
    return s2 is not None and _with_plan(s2, lambda: any(c == "P7" for c, w in check_brief()))


def m_negative_with_falsifier():
    """⚪ 但**写了**推翻条件 ⇒ 不许红。（否则 P7 变成"禁止有意不做"，那是另一回事）"""
    global _SRC
    _s = _SRC
    try:
        _SRC = _declare("6", "⚪ **有意不做**") or _SRC
        s2 = _set_detail("6", "Commons 分类实测 1,500 个文件。推翻它需要："
                              "分类文件数超过 5,000，或出现新的开放录音源")
    finally:
        _SRC = _s
    return s2 is not None and _with_plan(s2, lambda: not any(c == "P7" for c, w in check_brief()))


def m_dup_sheet_row():
    """🔴🔴 P8：同一笔欠账写成两行 —— **这是 2026-09-20 的真事故，不是假想的。**

    8 号当时就是两行：一行 ✅（收词闸建了）、一行 🔴（清单没建），
    于是这张表同时说了"还了"和"没还"。变异照原样复制一行已有的欠账，编号不变。
    """
    import re as _re
    m = _re.search(r"^\| 12 \|.*$", _SRC, _re.M)
    if not m:
        return False
    s2 = _SRC[:m.end()] + "\n" + m.group(0) + _SRC[m.end():]
    return _with_plan(s2, lambda: any(c == "P8" for c, w in check_brief()))


def m_foreign_row():
    """🔴🔴 P9：往 ja 的欠账表里寄存一条**别门的账**（2026-09-20 之前的真实状态）。"""
    import re as _re
    m = _re.search(r"^\| 12 \|.*$", _SRC, _re.M)
    if not m:
        return False
    row = "| 99 | **某某** | en | 🔴 挂着。⚠️ **这不是 ja 的账，是 en 的** |"
    s2 = _SRC[:m.end()] + "\n" + row + _SRC[m.end():]
    return _with_plan(s2, lambda: any(c == "P9" for c, w in check_brief()))


MUTATIONS = [
    ("M15", "🔴🔴 P9：ja 的欠账表里寄存了别门的账（搬到顶层之前的真实状态）",
     m_foreign_row),
    ("M14", "🔴🔴 P8：同一笔欠账写成两行（8 号当时就是这样，两行结论相反）",
     m_dup_sheet_row),
    ("M1", "阶段 4 声明✅ 而声调被删光（只查整表非空逮不到）", m_stage4),
    ("M2", "阶段 4b 声明✅ 而收词那批的读音没补", m_stage4b),
    ("M3", "🔴 P6：中文释义被删掉一半", m_cov_zh),
    ("M4", "🔴🔴 P6：新收 20 万词元、一个读音都没有（阶段 3a 的真形状）", m_cov_kana),
    ("M4c", "🔴 P6：常用汉字的音训读没了（表外字还在 —— 验分母选对没有）",
     m_cov_kanji_reading),
    ("M1d", "🔴 P6：收词稀释了义项标签覆盖率（行数闸对此失明）", m_cov_sense_tags),
    ("M2b", "🔴 P6：普通体那几列又被整批丢掉（56 万行一行不少，行数闸全绿）",
     m_cov_plain_forms),
    ("M4d", "🔴 P6：收词把核心词稀释了（声调一条没少，覆盖率却掉了）", m_cov_core_pitch),
    ("M1f", "🔴 P6：词源层整批没跑（这一层曾经缺席三个月而所有闸全绿）", m_cov_etymology),
    ("M5", "阶段 7 声明✅ 而回归闸文件不存在", m_stage7),
    ("M6", "阶段 8 声明✅ 而展示层没有 japanese.ts", m_stage8),
    ("M7", "带字母后缀的阶段号 5a 要被认出来", m_suffix),
    ("M8", "欠账表之后有游离 📋", m_stray),
    ("M9", "欠账表标题消失", m_no_sheet),
    ("M10", "🔴 翻译（3b）没完成就给阶段 5 打 ✅", m_before_trans),
    ("M11", "进行中的状态栏里散文提到 ✅，被当成整阶段完成", m_prose),
    ("M12", "🔴🔴 ⚪「有意不做」但没写什么会推翻它（ja 阶段 6 的真事故）", m_silent_negative),
    ("M13", "⚪ 写了推翻条件就不许红（P7 不是「禁止有意不做」）", m_negative_with_falsifier),
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
        # 🔴 判据是**全中**，不是"中够几条"。pt 那版写 `== 6` 而它有 8 条变异 ——
        #    挂 2 条仍然退出 0，正是本文件通篇在骂的假绿。
        sys.exit(0 if mutate() == len(MUTATIONS) else 1)
    sys.exit(1 if report() else 0)
