#!/usr/bin/env python3
"""**账的闸（ko）** —— `docs/KO_PLAN.md` 说的话，与库和代码对不对得上。2026-09-21。

═══ 🔴🔴 它为什么迟到，以及迟到本身就是它要逮的病 ═══
ko 从阶段 -2 做到阶段 4b 都没有这个文件，而 `ko/dbtool.py` 的挂钩写着：

    p = HERE / "tests" / "test_plan_ledger.py"
    if not p.exists():
        return                      # ← 文件不在就**静默返回**

⇒ 每一次写库都什么都没做，而日志照样打「■ 不变量核对通过 ✓」。
ja 就是这样**盯着绿字做完九个阶段**的 —— 「账的闸通过 ✓」那一行从来没出现过，
而没出现的东西不会引起注意。2026-09-21 先把那个 `return` 改成出声，
再补这个文件。**一道不在场的闸和一道全绿的闸，日志上不能长得一样。**

═══ 这道闸拦什么 ═══
    P1  阶段表标着 ✅，交付物却是空的 / 文件不在   ← fr 阶段 5 真发生过（关系层 0 条，漏七天）
    P2  记账散落：欠账表之后不许再有游离的 📋
    P4  依赖倒挂：义项层（阶段 5）没完成，8/9 不许声明 ✅
    P6  **按读者口径**的覆盖率跌破下限            ← 收词稀释了它就红，行数闸对此失明
    P7  「有意不做」的行没写什么会推翻它
    P8  欠账表里同一个编号出现两次
    P9  别门的账混进本表（该去 `docs/BACKLOG.md`）
    P10 库里的 G2P 行与当前规则集**行为指纹**对不上   ← ko 独有
    P11 覆盖率判据恒等 100% ＝ 假闸                ← ja 真犯过（分母里套了分子的条件）
    P0  **这张检查表自己有没有缺口**（编号不连续）   ← 我删过一条检查而闸报"全绿"

用法：
    python3 ko/tests/test_plan_ledger.py
    python3 ko/tests/test_plan_ledger.py --mutate   # 变异验证：永远通过的检查等于没检查
"""
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                        # noqa: E402
sys.path.insert(0, str(HERE.parent / "pipeline"))

ROOT = paths.ROOT
PLAN = ROOT / "docs" / "KO_PLAN.md"
TABLE = "## 五、阶段表"
SHEET = "## 六、📋 欠账"


# ══════════════════════════════════════════════════════════════════
# 交付物三类。🔴 每一条都得**真的能红** —— fr 第一版把两个阶段写成 `SELECT 1`。
# ⚠️ 判据不许写「表非空」如果那条从更早的阶段起就为真（那对本阶段恒真＝没查）。
DELIVERABLE = {
    "0": [("v3 的 16 张表都建了",
           "SELECT (SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
           "('dict','entry','sense','sense_src','sense_gloss','sense_tag',"
           "'sense_relation','inflection','pronunciation','hanja_reading',"
           "'etymology','example','example_gloss','collocation','collocation_gloss',"
           "'audio'))=16")],
    "1": [("entry 词条层", "SELECT COUNT(*) FROM entry"),
          ("sense_src 证据层", "SELECT COUNT(*) FROM sense_src"),
          # 🔴 ko 的汉字音层是**阶段 1 途中翻案补建的**（§四.3）。不单列它，
          #    "阶段 1 完成"就可以在这一层整个缺席的情况下成立。
          ("hanja_reading 汉字音层", "SELECT COUNT(*) FROM hanja_reading"),
          # 🔴 ja 拖到阶段 1e 才回填认领关系。ko 声明的是"建库时就认领"，那就查它。
          # ⚠️ **方向不能写反。** 第一版我写的是「`sense_src.sense_id` 不许有 NULL」，
          #    当场红 26,419 条 —— 而那批是**证据层里没被出版的**（指针义项、元描述），
          #    两层模型本来就该这样（`[[two-layer-sense-model]]`）。
          #    有意义的不变量是反方向：**出版层每一条都得有证据层认领**，
          #    那才是"义项与释义错配"会踩响的地方。
          ("出版层每条义项都有证据层认领",
           "SELECT COUNT(*)=0 FROM sense s WHERE NOT EXISTS("
           "SELECT 1 FROM sense_src WHERE sense_id=s.id)")],
    "2": [("inflection 变形层", "SELECT COUNT(*) FROM inflection"),
          ("变形词形已降级成 is_lemma=0", "SELECT COUNT(*) FROM dict WHERE is_lemma=0"),
          ("sense_relation 关系层", "SELECT COUNT(*) FROM sense_relation"),
          # 2b 翻案来的两列：阶段 0 判过"英文版 0 条"，那个 0 是查错字段的结果
          # 🔴 2026-09-24 改名：阶段 2b 交付的是**源头的 `table-tags`**，
          #    它现在叫 `conj_table_tag`。真正的活用类是阶段 8 后补的（`conj_class`），
          #    **不归阶段 2b**——查错列，阶段 2b 就可以整个没跑而这条照样绿。
          ("entry.conj_table_tag（翻案阶段 0 决定⑤而来）",
           "SELECT COUNT(*) FROM entry WHERE conj_table_tag IS NOT NULL"),
          ("hanja_reading.eumhun（结清 K3）",
           "SELECT COUNT(*) FROM hanja_reading WHERE eumhun IS NOT NULL")],
    "3": [("pronunciation 读音层", "SELECT COUNT(*) FROM pronunciation"),
          # 🔴 ko 独有的一层。只查 pronunciation 非空，"发音形全空"也能宣布做完
          ("发音形谚文（拉丁七门都没有的那一层）",
           "SELECT COUNT(*) FROM pronunciation WHERE hangeul_phonetic IS NOT NULL"),
          # §四.2 用户拍板四套全存 ⇒ 四列都要查，少查一列那一列空着也能过
          ("罗马字 RR", "SELECT COUNT(*) FROM entry WHERE roman_rr IS NOT NULL"),
          ("罗马字 RR-translit",
           "SELECT COUNT(*) FROM entry WHERE roman_rr_translit IS NOT NULL"),
          ("罗马字 MR", "SELECT COUNT(*) FROM entry WHERE roman_mr IS NOT NULL"),
          ("罗马字 Yale", "SELECT COUNT(*) FROM entry WHERE roman_yale IS NOT NULL"),
          # 🔴 跨版背书是阶段 3 的**方法**，不是副产品。它归零说明四版并取没跑
          ("跨版背书（src 里含 `+` 的行）",
           "SELECT COUNT(*) FROM pronunciation WHERE src LIKE '%+%'")],
    "4a": [("中文释义（白送那一批，零模型调用）",
            "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND src NOT LIKE 'model:%'"),
           # 🔴 判据必须挑出**收词那一批的来源**，否则英文版建的库让它永远为真
           ("中文版两片收进来的词条",
            "SELECT COUNT(*) FROM entry WHERE src LIKE 'zh-edition%'"),
           ("韩文版收进来的词条",
            "SELECT COUNT(*) FROM entry WHERE src='ko-edition'"),
           # 韩文版指针是阶段 4a 单独攻的一块（两信号一致才收），不查它就可以整块缺席
           ("韩文版的汉字表记指针进了关系层",
            "SELECT COUNT(*) FROM sense_relation WHERE src='ko-edition'")],
    "4b": [("G2P 生成的读音行", "SELECT COUNT(*) FROM pronunciation WHERE src='g2p'"),
           # 🔴 **人工读音一行都不许被 g2p 顶替** —— 这是"只填空不覆盖"的落点
           ("g2p 没有落在已有人工读音的词形上",
            "SELECT COUNT(*)=0 FROM pronunciation p WHERE p.src='g2p' AND EXISTS("
            "SELECT 1 FROM pronunciation q WHERE q.word_id=p.word_id AND q.src<>'g2p')"),
           # 我们有意不生成长音符 ⇒ 出现就是串源了
           ("g2p 行不带长音符",
            "SELECT COUNT(*)=0 FROM pronunciation WHERE src='g2p' AND ipa LIKE '%ː%'")],
    # 🔴🔴 2026-09-24 补登记 5/6/7。**它们从声明 ✅ 那天起就一条交付物都没登记** ——
    #    P1 只查登记了的，没登记的那一层整个缺席它也全绿。
    #    这正是 ja 的事故形状：**词源层缺席三个月而阶段表全 ✅**
    #    （`[[ja-dict-pipeline]]`：阶段表对没列进去的层结构性失明）。
    #    ⇒ 每加一个 ✅，就得同时加它的交付物，否则那个 ✅ 不作数。
    "5": [("模型译出来的中文释义",
           "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND src LIKE 'model:%'"),
          # 🔴 只查"有中文"会被阶段 4a 白送的那批顶替 ⇒ 必须挑 `model:` 前缀，
          #    那才是阶段 5 自己的落点（`[[measure-landing-not-source]]`）
          # 🔴🔴 **这条 2026-09-25 改过一次口径，原因要写清楚，否则下次看像是放水。**
          #    它守的是一句话：**每一条模型译文都追得回一段源文，我们没有凭空造中文。**
          #    原判据只在 `sense_gloss` 里找源文 —— 而当天收了日文版的 927 条释义，
          #    **日语原文按三语方针进的是证据层 `sense_src`，不进出版层**
          #    （`harvest_ja_glosses.py`）。于是它当场报红，而数据是对的。
          #    ⇒ 源文在**出版层或证据层**都算，**守的那句话一个字没变**。
          #    ⚠️ 这不是"闸红了就放宽" —— 判据原来问的是「源文在不在 sense_gloss」，
          #      那是**目的的可观测代理**；现在问的是「源文在不在」，才是目的本身
          #      （`[[proxy-metric-gets-optimized]]`）。变异验证见 M11。
          ("每条模型译文都追得回源文（出版层或证据层）",
           "SELECT COUNT(*)=0 FROM sense_gloss g WHERE g.lang='zh' "
           "AND g.src LIKE 'model:%' AND NOT EXISTS("
           "SELECT 1 FROM sense_gloss h WHERE h.sense_id=g.sense_id "
           "AND h.lang<>'zh' AND h.src NOT LIKE 'model:%') AND NOT EXISTS("
           "SELECT 1 FROM sense_src ss WHERE ss.sense_id=g.sense_id "
           "AND ss.lang<>'zh')")],
    "6": [("example 例句层", "SELECT COUNT(*) FROM example"),
          # 6a 白送的译文：归零说明"中文版全角空格切分"那一支没跑
          ("例句译文（中文版白送的那批）",
           "SELECT COUNT(*) FROM example_gloss WHERE lang='zh'"),
          # 🔴 6b 是**从例句标签里再收一轮关系**，它与阶段 2d 的关系层是两个写入方。
          #    判据只能按 `src_ref` 的形状挑（K14：`src` 列分不开两支）
          ("从例句标签收来的关系边（6b）",
           "SELECT COUNT(*) FROM sense_relation WHERE src_ref LIKE '%:rel:%' "
           "AND src_ref NOT LIKE '%#%'"),
          ("audio 录音层（6c）", "SELECT COUNT(*) FROM audio"),
          # 🔴 Commons 那一路是 6c 的**主力**（dump 内嵌只有 636 条）。
          #    不单查它，"只抽了 dump、Commons 整块没跑"也能宣布做完
          ("Commons 真人录音（6c 的主力，不是 dump 内嵌那 636 条）",
           "SELECT COUNT(*) FROM audio WHERE src='commons'")],
    "7": [("etymology 词源层", "SELECT COUNT(*) FROM etymology"),
          # 🔴 ja 的 40,270 行栽在"展示层要自己重建一次键" ⇒ ko 存 entry_id，
          #    那就查它指得到。归零＝桥没建，NULL 多＝桥断了
          ("词源的 entry_id 都指得到",
           "SELECT COUNT(*)=0 FROM etymology e LEFT JOIN entry x ON x.id=e.entry_id "
           "WHERE x.id IS NULL")],
}

FILES = {
    "-2": [("源探测脚本（补了 ko 的本地名模式）", "scripts/probe_editions.py")],
    "-1": [("路径声明", "ko/paths.py"),
           ("写库闸门", "ko/dbtool.py"),
           ("写库闸门的变异验证", "ko/tests/test_dbtool_gate.py"),
           # 🔴 **本文件登记在这儿是有意的**：阶段 -1 已声明 ✅，
           #    所以它哪天被删掉，这道闸当场红。**它先逮自己。**
           ("账的闸（本文件）", "ko/tests/test_plan_ledger.py")],
    "0": [("schema 定型（16 张表一处声明）", "ko/pipeline/build_v3_schema.py")],
    "1": [("建库骨架", "ko/pipeline/build.py"),
          ("entry 层（POS_MAP 的唯一家）", "ko/pipeline/build_entry_layer.py"),
          ("义项两层", "ko/pipeline/build_sense_layer.py"),
          ("空白页判据（只写一份）", "ko/pipeline/coverage.py")],
    "2": [("变形层（收词形与建链同一事务）", "ko/pipeline/build_inflection_layer.py"),
          ("tag 分类表（认不出就抛，不默认）", "ko/pipeline/infl_tags.py"),
          ("关系层", "ko/pipeline/build_relation_layer.py"),
          # 🔴 回归闸在 ko 上**从阶段 2 就建**（ja/fr 拖到阶段 8）——
          #    理由是本项目四次缺陷都是抽样逮到的，闸越早越好
          ("回归闸", "ko/tests/test_no_regression.py")],
    "3": [("读音层", "ko/pipeline/build_pronunciation.py"),
          ("四套罗马字（一个写入方一次填全）", "ko/pipeline/fill_romanization.py")],
    "4a": [("跨版收词", "ko/pipeline/intake_editions.py")],
    # 🔴 阶段 4b 交付**四样**，少登记一样就是那一样干不干都能过。
    #    尤其是消融脚本：没有它，"两家外审的建议逐条量过"就无从复现。
    "4b": [("G2P 规则（纯函数两级）", "ko/pipeline/g2p.py"),
           ("外部锚闸（锚 표준발음법 条文例词）", "ko/tests/test_g2p_rules.py"),
           ("逐条消融测量", "ko/pipeline/ablate_g2p.py"),
           ("落库", "ko/pipeline/fill_g2p_pronunciation.py")],
    "5": [("跑批客户端（并发/重试/半价窗口播报都在这儿）", "ko/pipeline/ds_batch.py"),
          ("释义翻译", "ko/pipeline/translate_glosses.py")],
    "6": [("例句收割（LABEL_DROP/split_text 的唯一家）", "ko/pipeline/harvest_examples.py"),
          ("从例句标签再收关系", "ko/pipeline/harvest_relations_from_examples.py"),
          ("录音（Commons ＋ dump 两路）", "ko/pipeline/harvest_audio.py")],
    "7": [("词源层（宽桥：FROM entry，不是 FROM sense JOIN entry）",
           "ko/pipeline/build_etymology.py")],
    # 🔴 阶段 8 现在还是 🟡，P1 暂时不查它 —— **但先登记**。
    #    登记发生在声明 ✅ 之前，才不会出现"改成 ✅ 的那一刻没人记得补登记"。
    "8": [("共用判据的唯一家", "ko/pipeline/criteria.py"),
          ("外锚闸·义项", "ko/pipeline/verify_vs_dump.py"),
          ("外锚闸·例句/变形/读音", "ko/pipeline/verify_layers_vs_dump.py"),
          # 🔴 活用类这三件是**一套**：判据 / 反推填库 / 源头错形式的修正。
          #    少登记一件，那一件删掉了闸不会响。
          ("活用类判据的唯一家（含对照组与交叉闸）", "ko/pipeline/conj_class.py"),
          ("活用类反推与落库", "ko/pipeline/derive_conj_class.py"),
          ("修源头生成的错活用形（짝짓다/한숨짓다 那 92 个）",
           "ko/pipeline/fix_bad_inflected_forms.py"),
          ("按规则生成活用表（含留出法自测，跑不过不许写库）",
           "ko/pipeline/conj_generate.py")],
    # 🔴 阶段 9 这七件里，**五件是"把数据渲染出来读"才逮到的缺陷的修复**
    #    （`[[it-display-layer-stage8]]`：接上展示层是独立一道闸）。
    #    少登记一件，那一件删掉了闸不会响。
    "9": [("展示层值域覆盖闸（映射表 vs 库里实际值域，两个方向）",
           "ko/tests/test_display_labels.py"),
          ("展示层契约闸（真渲染 → 盯可见文字）",
           "apps/web/src/contract-check-ko.tsx"),
          ("韩语映射表（覆盖层，只放与全局表不同的）",
           "packages/dict-labels/src/ko.ts"),
          ("关系边链接落点解析（^ 专名标记 / 汉字括号注）",
           "ko/pipeline/resolve_relation_targets.py"),
          ("删掉冒充 IPA 的 X-SAMPA", "ko/pipeline/fix_xsampa_ipa.py"),
          ("音频文件名漏进罗马字与读音", "ko/pipeline/fix_audio_filename_leak.py"),
          ("同一条录音存了两行（转码名 vs 原始名）",
           "ko/pipeline/dedupe_audio_transcodes.py"),
          # 🔴 9d 这两件是**一套**：`analyze_db` 修好计划器，`query_plans` 保证它别再坏。
          #    只留前者＝这次修好了、下次重建库又回到 51 ms 而没人知道。
          ("统计信息（`ANALYZE`，热查询 51.45ms → 0.04ms）",
           "ko/pipeline/analyze_db.py"),
          ("查询计划闸（从 `korean.ts` 抠真 SQL，4 条变异全过）",
           "ko/probes/query_plans.py")],
}

# 阶段 9 的交付物是**展示层真的改了读取路径**（`[[it-display-layer-stage8]]`：
# 数据层全绿、库里查得到，而 `french.ts` 里 `FROM audio` 出现 0 次 ⇒ 39 万条录音没人看得见）。
# 🔴 §四.2 那条「四套罗马字只显示 RR」也在这儿站岗：**回归闸不查数据、查源码**。
CODE = {
    "9": [("读取层已接上韩语库", "packages/dict-core/src/korean.ts", "FROM sense"),
          ("展示层只显示 RR（另三套不许出现在源码里）",
           "apps/web/src/App.tsx", "roman_rr")],
}


# ══════════════════════════════════════════════════════════════════
# P6 —— **按读者口径问的覆盖率**
#
# 🔴 下限是**实测值往下留余量**，不是拍的。后续收词稀释到下限以下就该红，
#    那正是它存在的理由。⚠️ **别因为收了新词就调低下限** —— 调低＝把闸关掉
#    （`[[proxy-metric-gets-optimized]]`）。要调只能先把数据补上去。
COVERAGE = [
    # 🔴🔴🔴 2026-09-24：**这一条曾经是一道永远绿的假闸，而且是本仓库里最大的一次。**
    #    原判据问的是「这条义项有没有一行 `lang='zh'`」—— 那是**形式**。
    #    实测 206,091 行里 **200,233 行（97.2%）是元描述**：
    #        `汉字或谚汉混合表记：환면상송（換面相訟）`
    #    它讲的是这个词**怎么写**，不是它**什么意思**。
    #    ⇒ 闸报 74.09% 通过，而按读者口径真实覆盖率是 **2.11%**。
    #    ⚠️ 它是给例句搭桥时随手打印 30 条样本逮到的，**闸一次都没响**
    #      （`[[criteria-from-meaning-not-form]]`／`[[proxy-metric-gets-optimized]]`）。
    #    🔴 **下限故意留在 70.0 不动** —— 现在它会红，而它就该红：
    #      这是 K10 那笔真欠账，把下限调到 2.11% 就是"把闸关掉去迁就坏数据"。
    #    🔴🔴 **分母**故意用 `sense` 全表，**不排除 `hidden=1`** ——
    #      搬走元描述后那 200,207 条空壳义项被标了 hidden，若把它们从分母里拿掉，
    #      这个数立刻变成 7.5%，**"把有问题的藏起来"就成了让闸变绿的办法**
    #      （`[[proxy-metric-gets-optimized]]`）。藏不该改善分数。
    # 🔴🔴 **这一项从此是两个数**，与读音层「人工 / 含规则生成」同一条规矩。
    #    2026-09-24 阶段 5 落库后：
    #      读者能看到的义项（非 hidden）  77,946 / 77,948 = **100.00%**
    #      全部 sense 行（含空壳）        77,946 / 278,155 = **28.02%**
    #    只报前一个＝把 20 万条没有释义的词说成"已完成"；
    #    只报后一个＝把「读者实际看到的页面质量」说得比实际差。**两个都要在。**
    # ⚠️ 这个 100.00% **不是分母套分子那种假的 100%**（`[[expectation-must-be-declared]]`
    #    说的那个签名）—— 它差着 2 条（两条空译文），分母是独立数出来的。
    #    ⇒ 下限取 99.0 而不是 100.0，那 2 条就是它与恒等式的区别。
    ("读者能看到的义项里有中文的占比（非 hidden）", 99.0,
     "SELECT 100.0*SUM(CASE WHEN EXISTS(SELECT 1 FROM sense_gloss g"
     "   WHERE g.sense_id=s.id AND g.lang='zh') THEN 1 ELSE 0 END)/COUNT(*)"
     " FROM sense s WHERE COALESCE(s.hidden,0)=0",
     "实测 **100.00%**（77,946/77,948，差的 2 条是模型给了空译文）。"
     "阶段 5 落库 72,062 条模型译文 ＋ 白送 5,884 条"),
    # 🔴 2026-09-24 阶段 6d 落库后补的。`translate_examples.py` 的 `invalidates` 里
    #    写着「下限要在**确认落点之后**再设」—— 这就是那一步，声明与兑现在同一天。
    # ⚠️ 分母只算 `hidden=0`，理由与上面那条**相反**且各自成立：
    #    义项那条的 hidden 是「有问题被藏起来」⇒ 排除它会让闸变绿，所以不排除；
    #    例句这条的 hidden 是「源头给的根本不是例句」（成分拆解/占位标签/多行 blob，
    #    共 792 条）⇒ 它们**永远不会有译文也不该有**，留在分母里这个数就永远到不了顶，
    #    闸也就永远分不清「还没译」和「不该译」。
    # 🔴 下限 99.0 不是 100.0：留的余量是**将来补收例句**（外锚闸那 24 条词形不在 dict
    #    的，收词之后会进来且没有中文）。到那天该红的是"新例句没译"，不是这条闸本身。
    ("读者能看到的例句里有中文的占比", 99.0,
     "SELECT 100.0*SUM(CASE WHEN EXISTS(SELECT 1 FROM example_gloss g"
     "   WHERE g.example_id=e.id AND g.lang='zh') THEN 1 ELSE 0 END)/COUNT(*)"
     " FROM example e WHERE COALESCE(e.hidden,0)=0",
     "实测 **100.00%**（37,433/37,433）。模型译 33,139 条 ＋ 中文两片白送 4,294 条。"
     "⚠️ 残差已量：约 **30 条（0.1%）**半翻译（韩语词或英文词残留在中文句子里），"
     "记在 **K16**，上界如实报，不修判据去掩盖"),
    ("义项的中文覆盖率（**真释义**，元描述不算）", 70.0,
     "SELECT 100.0*COUNT(DISTINCT sense_id)/(SELECT COUNT(*) FROM sense) "
     "FROM sense_gloss WHERE lang='zh' AND NOT ("
     "  (text LIKE '汉字%' OR text LIKE '漢字%')"
     "  AND (text LIKE '%表记：%' OR text LIKE '%表記：%'"
     "    OR text LIKE '%标记：%' OR text LIKE '%標記：%'))",
     "实测 **28.02%**（77,946 / 278,155）。分母里有 200,207 条**空壳义项** —— "
     "它们一条释义都没有（K10），译也译不了（没有任何语言的源文）。"
     "这条红的是 K10 那笔账，不是阶段 5 没做完"),
    # 🔴🔴🔴 2026-09-24 新增 —— **比"空白页"更根本的那个读者口径**。
    #    「空白页」问的是"点进去有没有东西看"，而这 19.5 万个词**有**东西看
    #    （一行汉字表记 ＋ 一条 G2P 读音）⇒ 它们在空白页那条判据上是合法的绿。
    #    可读者要的是**这个词什么意思**，那条判据对此结构性失明
    #    （`[[correct-steps-can-compose-a-hole]]`：闸至少要有一条是读者口径）。
    #    ⚠️ **下限 20.0 是防稀释的，不是"接受 23%"**：再收一批没释义的词就会红。
    #    🔴 23.36% 这个数本身是欠账 K10，而且它**触发了用户 2026-09-20 定的推翻条件**
    #      （「补完 c/d 之后空白页仍 >10% 总词形，就回来重议出版那一半」）——
    #      那一半归用户定，闸只负责让这个数**永远说得出口**。
    ("词元里**有释义**的占比（任何语言，元描述不算）", 20.0,
     "SELECT 100.0*SUM(CASE WHEN EXISTS("
     "  SELECT 1 FROM sense s JOIN sense_gloss g ON g.sense_id=s.id"
     "   WHERE s.word_id=d.id AND NOT ("
     "     (g.text LIKE '汉字%' OR g.text LIKE '漢字%')"
     "     AND (g.text LIKE '%表记：%' OR g.text LIKE '%表記：%'"
     "       OR g.text LIKE '%标记：%' OR g.text LIKE '%標記：%')))"
     "  THEN 1 ELSE 0 END)/COUNT(*) FROM dict d WHERE d.is_lemma=1",
     "实测 **23.36%**（254,583 个词元里只有 59,470 个有释义）。"
     "剩下的 19.5 万个身上只有一行汉字表记和一条 G2P 读音 —— 见欠账 K10"),
    # 🔴🔴 **这一条是「两个数」规矩的落点。** 用户 2026-09-21 定了全量出版 G2P，
    #    而 G2P **不许把这个数抬高一分** —— 它问的是"有多少词有人做过的读音"。
    #    合成一个数就是把 98.73% 的规则结果说成人工源的品质。
    ("词元的**人工**读音覆盖率（g2p 不算）", 20.0,
     "SELECT 100.0*COUNT(DISTINCT CASE WHEN EXISTS("
     "  SELECT 1 FROM pronunciation p WHERE p.word_id=d.id AND p.src<>'g2p')"
     "  THEN d.id END)/COUNT(*) FROM dict d"
     " WHERE NOT EXISTS (SELECT 1 FROM inflection WHERE word_id=d.id)",
     "实测 23.52%。阶段 4a 收词把它从 93.5% 稀释到这里 —— **不是回归，是分母变了**；"
     "但**再往下掉就是回归**，这道闸盯的就是那个"),
    ("词元的读音覆盖率（含规则生成）", 78.0,
     "SELECT 100.0*COUNT(DISTINCT CASE WHEN EXISTS("
     "  SELECT 1 FROM pronunciation p WHERE p.word_id=d.id) THEN d.id END)"
     "/COUNT(*) FROM dict d"
     " WHERE NOT EXISTS (SELECT 1 FROM inflection WHERE word_id=d.id)",
     "实测 82.64%。与上一条**必须分开报**"),
    ("**不是**空白页的词形占比", 99.9,
     "SELECT 100.0 - 100.0*(SELECT COUNT(*) FROM dict d"
     " WHERE NOT EXISTS (SELECT 1 FROM sense          WHERE word_id=d.id)"
     "   AND NOT EXISTS (SELECT 1 FROM inflection     WHERE word_id=d.id)"
     "   AND NOT EXISTS (SELECT 1 FROM inflection     WHERE base_id=d.id)"
     "   AND NOT EXISTS (SELECT 1 FROM hanja_reading  WHERE word_id=d.id)"
     "   AND NOT EXISTS (SELECT 1 FROM hanja_reading  WHERE hanja=d.word)"
     "   AND NOT EXISTS (SELECT 1 FROM sense_relation WHERE word_id=d.id)"
     "   AND NOT EXISTS (SELECT 1 FROM pronunciation  WHERE word_id=d.id))"
     "/(SELECT COUNT(*) FROM dict)",
     "pt 栽在这儿：46.2% 的词形搜得到、点进去空白。ko 实测 99.999%（6 个）"),
    # 🔴🔴 2026-09-24 拆成两条（与读音层「人工 / 含规则生成」同一条规矩）。
    #    起因：阶段 8 补收韩文版 13,062 个词头（K13）之后这个数从 41.47% 掉到 34.52%，
    #    闸当场红。回库拆开看：
    #        英文版的用言词条   5,351 条，有活用类 4,685 ⇒ **87.55%**
    #        非英文版的用言词条 8,219 条，有活用类     0 ⇒ **0.00%**
    #    **活用类只有英文版给**（`table-tags`），所以 34.52% 是纯分母效应。
    #    ⚠️ 但**不许因此把下限调低就算了** —— 那 8,219 条用言对读者确实没有活用表，
    #      它就是欠账 **K8**（8,521 个 `-다` 词元一张活用表都没有）的同一笔账。
    #    ⇒ 一条盯「**我们已经有的数据别退化**」，一条**如实报读者看到的缺口**。
    # 🔴🔴 2026-09-24 **这两条量的东西换了**，不是数字变好看了。
    #    此前 `conj_class` 存的是源头的 `table-tags`（值域只有 irregular / no-table-tags）——
    #    **五种不同的不规则共用一个值 `irregular`，而 `no-table-tags` 根本不是活用类**。
    #    ⇒ 旧的 34.52% 数的是「有 table-tags 的行」，**不是「说得出是哪一类的行」**。
    #    与 K10（20 万条中文释义其实是元描述）同一个签名，本项目第二次。
    #    现在：老值改名进 `conj_table_tag`，`conj_class` 存真的类（여불규칙/ㅂ불규칙/…）。
    # ⚠️ **下限是新量的，不是把旧下限调低** —— 旧下限守的是另一个量，已经作废。
    ("源头给了活用表的用言，我们抽全了没有", 95.0,
     "SELECT 100.0*COUNT(DISTINCT CASE WHEN conj_class IS NOT NULL THEN id END)"
     "/COUNT(*) FROM entry WHERE conj_table_tag IS NOT NULL",
     "实测 **100.00%** —— 凡是源头给了活用表的，我们都定出了类。"
     "这一条问的是「源头给了的别漏」，掉下去才是真回归"),
    ("用言词条里能说出活用类的占比（全部来源）", 95.0,
     "SELECT 100.0*COUNT(DISTINCT CASE WHEN conj_class IS NOT NULL THEN id END)"
     "/COUNT(*) FROM entry WHERE pos_raw IN ('verb','adj','adjective') "
     "AND EXISTS(SELECT 1 FROM dict d WHERE d.id=entry.word_id AND d.word LIKE '%다')",
     "实测 **97.83%**（12,975/13,262）。K8 的主体已结："
     "5,019 条从实际活用形反推、7,956 条按后缀规则（表在 4,592 个带表原形上逐条验过）。"
     "🔴 剩 287 条**有意留 NULL**（`보다`/`맞다`/`타다` 这类，拼写定不了）—— "
     "填一个猜的值比留空更伤。⚠️ 另有 **K17**：同形异义词按词形判类，最坏 76 行（0.59%）会错"),
    # 🔴🔴 **这一条是上面那条变绿之后必须补的。**
    #    K8 原来的账是「8,219 条用言**一张活用表都没有**」—— 那说的是**表**，不是**标签**。
    #    我 2026-09-24 填的是活用类（읽者看不见的元数据），**没有生成一个活用形**。
    #    如果只留上面那条 97.83%，账的闸就会在「读者点进去仍然看不到活用形」的情况下全绿 ——
    #    那正是 `[[proxy-metric-gets-optimized]]`：**我会把闸对准好量的东西，而不是要的东西**。
    #    ⇒ 用**读者口径**再问一遍：这个用言词元有没有活用表可看。
    # ⚠️ 下限 90.0 原本是**有意定成必红**的（当时 35.98%），意思是"这笔账还欠着"。
    # ✅ 2026-09-24 当天补上了：`conj_generate.py` 按规则生成 7,591 个词元的活用表
    #    （745,037 行，标 `src='rule'`），**35.98% → 97.79%**，这条红转绿。
    # 🔴 **下限留在 90 不动** —— 它现在守的是"别退化"。
    #    生成物有实测残差 ≈322 个错误词形（0.043%，K18），那是另一笔账，不靠这条闸管。
    # 🔴🔴 **这一项必须是两个数**，与读音层「人工 / 含规则生成」同一条规矩。
    #    只报下面那个 97.79%，将来谁生成一堆垃圾也能让它绿 ——
    #    **闸分不出「表是源头给的」还是「我们算的」就不是闸**。
    #    ⇒ 这一条只数 `src<>'rule'`，盯的是**源头给的那批别退化**（它不会涨）。
    ("用言词元里有**源头给的**活用表的占比", 35.0,
     "SELECT 100.0*COUNT(DISTINCT CASE WHEN EXISTS("
     "  SELECT 1 FROM inflection i WHERE i.base=d.word AND i.src<>'rule') "
     "  THEN d.word END)"
     "/COUNT(DISTINCT d.word) FROM entry e JOIN dict d ON d.id=e.word_id "
     "WHERE e.pos_raw IN ('verb','adj','adjective') AND d.word LIKE '%다' AND d.is_lemma=1",
     "实测 **35.98%**（4,418/12,280）—— 这是**源头能给的上限**，"
     "生成多少都不会让它涨。它掉下去才是真回归（有人删了源头给的表）"),
    ("用言词元里有活用表可看的占比（读者口径）", 90.0,
     "SELECT 100.0*COUNT(DISTINCT CASE WHEN EXISTS("
     "  SELECT 1 FROM inflection i WHERE i.base=d.word) THEN d.word END)"
     "/COUNT(DISTINCT d.word) FROM entry e JOIN dict d ON d.id=e.word_id "
     "WHERE e.pos_raw IN ('verb','adj','adjective') AND d.word LIKE '%다' AND d.is_lemma=1",
     "实测 **97.79%**（2026-09-24 生成之后；之前是 35.98%）。"
     "🔴 剩下的 2.21% 是**有意不生成**的：269 个词元两条判据都定不出活用类，"
     "外加 ㄷ불규칙/으탈락/ㅎ불규칙/ㅅ불규칙/러불규칙 五类（留出法形式错率 1.2%–20.5%，"
     "**宁可留空**）。⚠️ 生成物的残差见 **K18**"),
    ("汉字音节里有音训的占比", 33.0,
     "SELECT 100.0*COUNT(DISTINCT CASE WHEN eumhun IS NOT NULL THEN hanja END)"
     "/COUNT(DISTINCT hanja) FROM hanja_reading",
     "实测 37.38%（结清 K3）。上限是源头的：英文版 `character` 条目只给这么多"),
]

# 🔴 P11 的白名单：**实测就是 100% 且有理由**的那几条。
#    不在名单里而量出 100% ⇒ 多半是分母里套了分子的条件（ja 真犯过：
#    「有词源正文的词里带词源正文的占比」恒等 100%，一道假闸）。
ALLOW_100 = {
    "变形形能指回原形的占比": "建链与收词形在同一事务里，指不回去在结构上不可能",
    "义项被证据层认领的占比": "建库时就认领，NULL 会被阶段 1 的交付物断言当场拦下",
    # 🔴 2026-09-24：P11 当场拦住了这一条，**它拦得对** —— 恒等 100% 要先交代清楚。
    #    分母 `example WHERE hidden=0` **完全不引用 `example_gloss`**，
    #    所以不是"分母里套了分子的条件"那种假闸；它是阶段 6d 把 33,139 条全译完的真结果。
    #    ⚠️ 它**会掉下来**：外锚闸那 24 条「词形不在 dict」的例句一旦随收词进来就没有中文。
    #      ⇒ 到那天这条红的是"新例句没译"，不是闸本身，**别靠调下限让它变绿**。
    "读者能看到的例句里有中文的占比":
        "阶段 6d 把 33,139 条缺中文的例句全译完了（＋白送 4,294）；"
        "分母只排除 `hidden=1` 那 792 条**根本不是例句**的行（成分拆解/占位标签/多行 blob），"
        "分母不引用 `example_gloss`，不是分母套分子",
}
COVERAGE += [
    ("变形形能指回原形的占比", 99.9,
     "SELECT 100.0*COUNT(CASE WHEN base_id IS NOT NULL THEN 1 END)/COUNT(*) "
     "FROM inflection", "实测 100%"),
    ("义项被证据层认领的占比", 99.9,
     "SELECT 100.0*COUNT(DISTINCT sense_id)/(SELECT COUNT(*) FROM sense) "
     "FROM sense_src WHERE sense_id IS NOT NULL", "实测 100%"),
]


# ══════════════════════════════════════════════════════════════════
ROW = re.compile(r"^\|\s*\**\s*(-?[0-9.]+[a-z]?)\s*\**\s*\|(.+?)\|(.+?)\|", re.M)
MARKS = ("✅", "🟡", "🔄", "📋", "⬜", "⚪")


def _status(state):
    """状态栏 → 里面**最先出现的那一个**标记。

    🔴 de 2026-09-03 的真事故：判据写成 `"✅" in state`（子串命中），
       而状态栏写的是「🔄 **1.5a ✅ 已落库**／1.5b 未跑」—— 一个诚实的进行中状态 ——
       整阶段被判成已完成。**闸没坏，是它读错了地方。**
    """
    pos = [(state.index(m), m) for m in MARKS if m in state]
    return min(pos)[1] if pos else None


def _table():
    s = PLAN.read_text(encoding="utf-8")
    i = s.index(TABLE)
    j = s.find("\n## ", i + 4)
    return s[i:j if j > 0 else len(s)]


def declared_done():
    out = {}
    for m in ROW.finditer(_table()):
        if _status(m.group(3)) == "✅":
            out[m.group(1)] = m.group(2).strip().strip("*").strip()
    return out


def p1(con):
    """阶段表声明 ✅ 的，交付物必须真的在。"""
    bad = []
    for num, title in sorted(declared_done().items()):
        for what, sql in DELIVERABLE.get(num, []):
            try:
                n = con.execute(sql).fetchone()[0]
            except sqlite3.Error as e:
                bad.append(("P1", "阶段 %s 的交付物查不了：%s（%s）" % (num, what, e)))
                continue
            if not n:
                bad.append(("P1", "阶段 %s「%s」声明 ✅，但**%s 是 0**"
                            % (num, title[:22], what)))
        for what, rel in FILES.get(num, []):
            if not (ROOT / rel).exists():
                bad.append(("P1", "阶段 %s「%s」声明 ✅，但**%s 不存在**（%s）"
                            % (num, title[:22], what, rel)))
        for what, rel, need in CODE.get(num, []):
            p = ROOT / rel
            if not p.exists():
                bad.append(("P1", "阶段 %s 声明 ✅，但 %s 不存在" % (num, rel)))
            elif need not in p.read_text(encoding="utf-8"):
                bad.append(("P1", "阶段 %s「%s」声明 ✅，但 %s 里找不到 `%s` —— "
                                  "**库里查得到 ≠ 读者看得见**"
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
             and not ln.lstrip().startswith(("|", ">", "#"))]
    return [("P2", "欠账表之后有 %d 条游离记账（应进表）：%s"
             % (len(stray), stray[0][:60]))] if stray else []


# P4 —— **义项层（阶段 5）没做完，闸与展示层不许声明完成。**
# 🔴 理由不是流程洁癖：fr 的阶段 5 声明 ✅ 而关系层 0 条、频次层根本不存在，
#    漏了七天才发现。在没有裁定过的义项上接展示层，等于在半成品上加层。
AFTER_SENSE = ("8", "9")


def p4():
    done = set(declared_done())
    if "5" in done:
        return []
    early = sorted(x for x in AFTER_SENSE if x in done)
    return [("P4", "阶段 5（义项与释义）还没完成，但阶段 %s 已声明 ✅ —— "
                   "在没裁定过的义项上接闸/展示层＝在半成品上加层"
             % "、".join(early))] if early else []


def p6(con):
    bad = []
    for name, floor, sql, why in COVERAGE:
        try:
            got = con.execute(sql).fetchone()[0]
        except sqlite3.Error as e:
            bad.append(("P6", "覆盖率判据跑不了：%s（%s）" % (name, e)))
            continue
        if got is None or got < floor:
            bad.append(("P6", "%s **%.2f%%**，低于下限 %.1f%% —— %s"
                        % (name, got or 0.0, floor, why)))
    return bad


# P7 —— 「有意不做」的行必须写清什么会推翻它（PLAYBOOK §7.5）。
# 🔴 判据**看含义不看符号**：`⚪` 在 pt/de/fr 三张计划表里是**另一个意思**
#    （「不是缺陷／我当初量错了」），按符号判会在 37 行上误报。
# 🔴 也**不问"有没有数字"** —— ja 阶段 6 那条原来是有数字的（206），照样烂掉。
#    缺的是"什么会让这个数字不再成立"。
NEGATIVE = ("有意不做", "不施行", "不出版", "不建")
FALSIFIER = ("什么会推翻", "推翻它需要", "推翻条件", "重新评估的条件", "会让它回来")


def p7():
    tbl = _table()
    bad = []
    for m in ROW.finditer(tbl):
        num, title, state = m.group(1), m.group(2), m.group(3)
        nl = tbl.find("\n", m.end())
        row = tbl[m.start():nl if nl > 0 else len(tbl)]
        # 🔴 「有意不做」必须出现在**状态列**里，不是整行里。
        #    搜整行会误报：详情的散文里提到这几个字的行多得很。
        if not any(k in state for k in NEGATIVE):
            continue
        if not any(k in row for k in FALSIFIER):
            bad.append(("P7", "阶段 %s「%s」声明了一个否定结论，但**没写什么会推翻它** —— "
                              "否定结论没有交付物，闸天然管不到它，"
                              "写下去就是永久前提" % (num, title.strip()[:24])))
    return bad


def _sheet_rows():
    s = PLAN.read_text(encoding="utf-8")
    if SHEET not in s:
        return []
    tail = s[s.index(SHEET):]
    j = tail.find("\n## ")
    return [ln for ln in (tail[:j] if j > 0 else tail).splitlines()
            if ln.lstrip().startswith("|")]


ID = re.compile(r"\|\s*\**~*\s*(K\d+)\s*~*\**\s*\|")


def p8():
    """欠账表里同一个编号不许出现两次。

    🔴 ja 2026-09-20：8 号有两行**而且结论相反**（一行 ✅ 收词闸建了、
       一行 🔴 清单没建）。两行各对一半，于是这张表同时说了"还了"和"没还"。
       ⇒ P1–P7 对它结构性失明：它们查登记了的那几条对不对，
         **没有一条查登记表本身有没有毛病**。
    """
    seen, dup = {}, []
    for ln in _sheet_rows():
        m = ID.search(ln)
        if not m:
            continue
        k = m.group(1)
        if k in seen:
            dup.append(k)
        seen[k] = ln
    return [("P8", "欠账表里编号重复：%s —— 同一个号两行，读者按哪行都不算读错"
             % "、".join(sorted(set(dup))))] if dup else []


# P9 —— 别门的账不许混进本表（规矩见 `docs/BACKLOG.md` 文件头）。
# 🔴 判据问的是**这条账的责任方是不是别门**，不是"这一行提没提别门"。
#    第一版写成后者，当场误伤 K9 —— 那是 ko 自己的账（ko 缺账本闸），
#    只是行文里出现了「八门里唯一一门」这句描述。
#    ⇒ 又一次「判据比它要描述的东西宽」（`[[criteria-narrower-than-you-think]]`）。
#    ⚠️ 代价说明白：这样收窄之后，一条**没用这些措辞**的跨门账混进来它逮不到。
#      这是有意的取舍 —— 误报会让人把闸关掉，漏报只是回到没有闸的状态。
OTHERS = ("不是 ko 的账", "不是ko的账", "这不是 ko 的", "跨门的账", "跨语种的账",
          "影响哪几门")


def p9():
    bad = []
    for ln in _sheet_rows():
        hit = [k for k in OTHERS if k in ln]
        if hit and ID.search(ln):
            bad.append(("P9", "欠账 %s 这一行带着「%s」—— 别门/跨门的账要去 "
                              "`docs/BACKLOG.md`，各门计划表只记自己的"
                        % (ID.search(ln).group(1), hit[0])))
    return bad


def p10(con):
    """🔴 ko 独有：库里的 G2P 行必须与**当前规则集的行为指纹**对得上。

    这一条兑现的是落库时在 `invalidates` 里写下的那句话：
    「规则集改了而旧行还躺着，没人会发现」。
    ⭐ 指纹取自「一组固定探针词上的输出」——**改注释不变、改行为就变**，
      比手写版本号强的地方在于它**不需要谁记得改**。
    """
    try:
        import g2p
    except Exception as e:
        return [("P10", "读不到 `ko/pipeline/g2p.py`（%s）—— 那本身要查" % e)]
    want = "g2p:" + g2p.fingerprint()
    rows = [r for r in con.execute(
        "SELECT src_ref, COUNT(*) FROM pronunciation WHERE src='g2p' "
        "GROUP BY src_ref")]
    bad = [(sr, n) for sr, n in rows if sr != want]
    if not bad:
        return []
    return [("P10", "库里 %s 行 G2P 读音的指纹是 %s，当前规则集是 %s —— "
                    "规则改了而旧行还躺着。**重算（--rebuild），不是重新盖章**"
             % (format(sum(n for _, n in bad), ","),
                "、".join(sr for sr, _ in bad), want))]


def p11(con):
    """🔴 覆盖率判据恒等 100% ＝ 假闸。

    ja 真犯过：「有词源正文的词里带词源正文的占比」——分母里套了分子的条件，
    这个数**恒等于 100%**，而它看起来是一道正经的覆盖率闸。
    ⇒ 量出 100% 的必须在 `ALLOW_100` 里登记并写明为什么。
    """
    bad = []
    for name, floor, sql, why in COVERAGE:
        try:
            got = con.execute(sql).fetchone()[0]
        except sqlite3.Error:
            continue                       # 跑不了是 P6 的事
        # 🔴 阈值是**精确 100.0**，不是"接近 100"。假闸的特征是分母套了分子的条件
        #    ⇒ 必然精确相等；而 99.999%（空白页 6 / 627,401）是**真测量**。
        #    第一版写成 `>= 99.999` 当场误伤它 —— 判据又一次比对象宽。
        if got is not None and got >= 100.0 and name not in ALLOW_100:
            bad.append(("P11", "「%s」量出 %.3f%% —— 恒等 100%% 的覆盖率多半是"
                               "分母里套了分子的条件（假闸）。真的是 100%% 就登记进 "
                               "`ALLOW_100` 并写明理由" % (name, got)))
    return bad


# ══════════════════════════════════════════════════════════════════
CHECKS = [("P1", p1), ("P2", p2), ("P4", p4), ("P6", p6), ("P7", p7),
          ("P8", p8), ("P9", p9), ("P10", p10), ("P11", p11)]
# 🔴 P3/P5 在 ko 上**有意不设**：P3（字面量闸）与 P5（备份保留策略）
#    在 ko 上分别由 `dbtool` 的 `_literal_gate` 和 `_prune_backups` 自己守着，
#    在这儿再设一条是两个写入方。⇒ 编号跳号是**有理由的**，登记在这里，
#    否则 P0 会把它当成缺口。
SKIP = {"P3": "字面量闸由 ko/dbtool.py 的 _literal_gate 守",
        "P5": "备份保留策略由 ko/dbtool.py 的 _prune_backups 守"}

# 🔴🔴 **花名册。P0 拿它比对，不靠"编号连不连续"推。**
#    第一版 P0 写的是「编号从 1 起连续」—— 变异验证当场证明它**逮不到删掉最后一条**：
#    删掉 P11 之后上界跟着降到 10，缺口自己消失了。
#    ⚠️ 而**最后一条恰恰是最容易被删的那条**（追加在末尾、改动时手最容易滑）。
#    ⇒ 判据必须是"应该有哪些"，不能是"现有的这些排得整不整齐" ——
#      后者是拿现状推期望，现状坏了期望跟着坏（`[[primary-key-is-not-enough]]` 同形）。
#    ⚠️ 加一条检查就要动这张表一次。**那个手工动作就是这道闸的价值**：
#      它逼人明说"我是有意加/减的"。
ROSTER = ("P1", "P2", "P4", "P6", "P7", "P8", "P9", "P10", "P11")


def p0():
    """**这张检查表自己有没有缺口。**

    🔴 2026-09-21 在回归闸上真发生过：我用字符串替换改测试，把 R1 整条删掉了，
       而闸报「全绿 10 条」—— 少一条检查和全部通过，输出上长得一模一样。
    """
    have = tuple(c[0] for c in CHECKS)
    if have == ROSTER:
        return []
    miss = [x for x in ROSTER if x not in have]
    extra = [x for x in have if x not in ROSTER]
    return [("P0", "检查表与花名册对不上：少了 %s，多了 %s（花名册 %s）"
             % (miss or "无", extra or "无", list(ROSTER)))]


def check_brief():
    """给 `dbtool` 用：→ [(编号, 原因)]，空列表＝全绿。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        red = p0()
        for _, fn in CHECKS:
            red += fn(con) if fn.__code__.co_argcount else fn()
        return red
    finally:
        con.close()


def main():
    mutate = "--mutate" in sys.argv
    red = check_brief()
    print("■ ko 账的闸：%d 条检查（跳号 %s）" % (len(CHECKS) + 1, "、".join(sorted(SKIP))))
    for cid, why in red:
        print("   🔴 %-4s %s" % (cid, why))
    if not red:
        print("   ✅ 全绿（计划表、欠账表与库和代码对得上）")
    if not mutate:
        raise SystemExit(1 if red else 0)

    print("\n═══ 变异验证：一条永远通过的检查等于没检查 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    orig_plan = PLAN.read_text(encoding="utf-8")
    ok = True

    def expect(cid, name, fn):
        nonlocal ok
        hit = any(c == cid for c, _ in fn())
        ok &= hit
        print("   %s %-5s %s" % ("✅" if hit else "🔴 没逮到", cid, name))

    # M1 阶段表把一个交付物是空的阶段声明成 ✅ → P1 必须红
    # 🔴🔴 2026-09-24：这条与 M8 一起**静默失效**过。它原来做两次 `replace`，
    #    第二次锚的是 `| **7x** | 词源层（**只有英文版有**，38,796 条）| ⬜ 未开始` ——
    #    而阶段 7 那天做完改成了 ✅，那句话不存在了 ⇒ 第二次 replace 空操作，
    #    注册的 `DELIVERABLE["7x"]` 又查的是真有 38,796 行的表 ⇒ **怎么都红不了**。
    #    ⚠️ 两层依赖都建在「阶段表此刻长什么样」上，而阶段表**本来就会变** ——
    #      变异必须只依赖稳定的东西（编号、以及它自己注入的内容）。
    inject1 = "| **98** | 这一步是变异注入的 | ✅ 假的完成 | |\n"
    assert "| **9** |" in orig_plan, "阶段 9 那行不在了 —— M1 的锚点要重定"
    try:
        # 交付物**保证为 0**：查一张肯定存在、但这个条件肯定没有行的表
        DELIVERABLE["98"] = [("一个保证为 0 的交付物",
                              "SELECT COUNT(*) FROM dict WHERE word = '__变异注入__'")]
        PLAN.write_text(orig_plan.replace("| **9** |", inject1 + "| **9** |", 1),
                        encoding="utf-8")
        expect("P1", "阶段声明 ✅ 而交付物是 0", lambda: p1(con))
    finally:
        DELIVERABLE.pop("98", None)
        PLAN.write_text(orig_plan, encoding="utf-8")

    # M2 交付物文件指到一个不存在的路径 → P1 必须红
    FILES["-1"].append(("假文件", "ko/nope_not_here.py"))
    expect("P1", "登记的交付物文件不存在", lambda: p1(con))
    FILES["-1"].pop()

    # M3 欠账表之后塞一条游离 📋 → P2 必须红
    PLAN.write_text(orig_plan + "\n\n📋 随手记一笔，没进表\n", encoding="utf-8")
    expect("P2", "欠账表之后有游离记账", p2)
    PLAN.write_text(orig_plan, encoding="utf-8")

    # M4 把一条覆盖率下限抬到实测之上 → P6 必须红（证明它真在读数）
    COVERAGE[0] = (COVERAGE[0][0], 99.9, COVERAGE[0][2], COVERAGE[0][3])
    expect("P6", "覆盖率跌破下限", lambda: p6(con))
    COVERAGE[0] = (COVERAGE[0][0], 70.0, COVERAGE[0][2], COVERAGE[0][3])

    # M5 把一条覆盖率改成「分母里套分子的条件」→ P11 必须逮到这道假闸
    COVERAGE.append(("假闸：分母里套了分子", 50.0,
                     "SELECT 100.0*COUNT(*)/(SELECT COUNT(*) FROM pronunciation "
                     "WHERE hangeul_phonetic IS NOT NULL) FROM pronunciation "
                     "WHERE hangeul_phonetic IS NOT NULL", "变异用"))
    expect("P11", "覆盖率判据恒等 100%（假闸）", lambda: p11(con))
    COVERAGE.pop()

    # M6 欠账表里造一个重号 → P8 必须红
    # ⚠️ 同 M7：锚钉在 `SHEET` 上。原来钉在 `| **K8** |`，K8 结清改成 `~~K8~~` 就失效了。
    #    造重号也**不借用现有编号**（那要求我知道哪个号现在还在用）——
    #    直接注入两行同号，自足。
    assert SHEET in orig_plan, "欠账表的节标题变了 —— M6 的锚点要重定"
    PLAN.write_text(orig_plan.replace(
        SHEET, SHEET + "\n| **K21** | 重号甲 | 1 | x | y |"
                       "\n| **K21** | 重号乙 | 1 | x | y |", 1),
        encoding="utf-8")
    expect("P8", "欠账编号重复", p8)
    PLAN.write_text(orig_plan, encoding="utf-8")

    # M7 欠账表里塞一条别门的账 → P9 必须红
    # 🔴🔴 **2026-09-24 一天之内，三条变异因为同一个原因静默失效**（M1／M8／本条）：
    #    它们各自锚在计划表的**某一行的行文**上（阶段标题、`| **K8** |`），
    #    而那天阶段 6/7 做完改了标题、K8 结清改成了 `~~K8~~` ⇒ `replace` 成空操作，
    #    **什么都没注入，检查于是"通过"**。
    #    ⚠️ 变异不报错，只是不再变异 —— 比断言过期更难发现。
    #    ⇒ **规矩：注入点一律钉在本文件里的常量**（`SHEET`／`TABLE`／阶段编号），
    #      不钉在会被正常编辑改掉的行文上；并且每条都 `assert` 锚点还在。
    assert SHEET in orig_plan, "欠账表的节标题变了 —— M7 的锚点要重定"
    PLAN.write_text(orig_plan.replace(
        SHEET, SHEET + "\n| **K20** | 这是跨门的账 | 1 | x | y |", 1),
        encoding="utf-8")
    expect("P9", "别门/跨门的账混进本表", p9)
    PLAN.write_text(orig_plan, encoding="utf-8")

    # M8 声明一个否定结论但不写推翻条件 → P7 必须红
    # 🔴🔴 2026-09-24：这条变异**静默失效过**。它原来锚在阶段 6 的**标题文本**上
    #    （`| **6** | 例句 / 关系 / 录音（录音要**另外量** Commons）| ⬜ 未开始 | |`），
    #    而那天阶段 6 做完、标题改成了「…／**例句翻译**」⇒ `replace` 成了空操作，
    #    **什么都没注入**，P7 于是"没逮到"。
    #    ⚠️ 变异锚在**会变的散文**上就会这样：它不报错，只是不再变异。
    #      `[[fix-regression-and-gate]]` 的「锁数字不锁名字」在变异上的同一条 ——
    #      ⇒ 改成**注入一行新的**，只依赖阶段编号这种稳定的东西。
    inject = "| **99** | 这一步有意不做 | ⚪ 有意不做 | 就是不做，没别的 |\n"
    assert "| **9** |" in orig_plan, "阶段 9 那行不在了 —— M8 的锚点要重定"
    PLAN.write_text(orig_plan.replace("| **9** |", inject + "| **9** |", 1),
                    encoding="utf-8")
    expect("P7", "否定结论没写什么会推翻它", p7)
    PLAN.write_text(orig_plan, encoding="utf-8")

    # M9 假装规则集变了 → P10 必须红
    import g2p as _g
    _fp = _g.fingerprint
    _g.fingerprint = lambda *a, **k: "deadbeef"
    expect("P10", "库里的 G2P 指纹与当前规则集对不上", lambda: p10(con))
    _g.fingerprint = _fp

    # M10 删掉一条检查 → P0 必须红
    _c = CHECKS.pop()
    expect("P0", "检查表自己有缺口（我删过一条而闸报全绿）", p0)
    CHECKS.append(_c)

    con.close()
    assert PLAN.read_text(encoding="utf-8") == orig_plan, "🔴 计划表没还原！"
    print("\n%s" % ("■ ko 账的闸变异验证通过 ✓（每一条验的是「它拦得住什么」）"
                    if ok else "🔴 有变异没被逮到 —— 那条检查是摆设"))
    raise SystemExit(0 if ok and not red else 1)


if __name__ == "__main__":
    main()
