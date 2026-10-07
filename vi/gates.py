#!/usr/bin/env python3
"""**写库之后哪几道闸过期了** —— 名单、依赖、欠账状态，都在这一个文件里。vi，2026-09-28。

机制照搬 ko 的 **K31**（那部分与语言无关）。它为什么存在，一句话：
2026-09-26 发现 ko 有两道外锚闸**从前一天起一直红着**，两条都不是新缺陷，
是「修了数据没跟着重跑闸」—— 而流程里**没有任何一条机制逼人重跑**。
`[[lesson-must-become-mechanism]]`：**做成机制的全守住了，写成文字的一条没守住。**

═══ ⭐ vi 与 ko 的差别：这张名单现在**很短，而那是诚实的** ═══
ko 那份有 11 道闸，是九个阶段攒出来的。vi 刚做完阶段 1，真正存在的闸只有两道。
🔴 **别为了让名单好看而把不存在的闸写进去** —— 那正是 `self_check()` ③ 要拦的事
（ko 的教训：文件在、八门都写了、`package.json` 里没有入口，谁也没跑过）。
名单会随阶段长，长的时候每一道都要带 `why`。

═══ 判据：依赖写成「这道闸读了哪些表」，且**有意偏宽** ═══
🔴 `dict` 几乎被所有查询连着，动 `dict` 会脏掉几乎所有闸。
   宽的代价是多跑几分钟；窄的代价是漏跑（ko 那两条红了一整天）。
   **这一处宽是有意的，这句话本身就是判据的一部分，别哪天当成 bug「修窄」。**
"""
import datetime
import json
import subprocess
import sys
from pathlib import Path

import paths

ROOT = paths.ROOT
# 欠账状态跟**这个库**走，所以放在库边上而不是代码目录里
#（库不在 git 里，欠账也不该在 —— 换台机器就是另一个库、另一份欠账）。
PENDING = paths.DATA / "db" / ".vi-gates-pending.json"


# ── 闸名单 ──────────────────────────────────────────────────────────────────
# deps=None ＝ **已声明「动数据不会让它过期」**，必须同时写清为什么。
#   （与 `session(invalidates=[])` 同一个设计：空和没填要在结构上分得开。）
GATES = [
    dict(
        name="骨架闸",
        cmd="python3 -u vi/tests/test_skeleton.py",
        mutate="python3 -u vi/tests/test_skeleton.py --mutate",
        file="vi/tests/test_skeleton.py",
        deps=frozenset({"dict", "entry"}),
        why="阶段 1 的 15 条不变量。**它们原本只写在 `build.py --apply` 分支里** ——"
            "只在建库那一刻跑过一次，之后谁改坏了库都没人说话。"
            "其中一条是**读者口径**（`dict.pos` 的每个斜杠段），治的是 ko 的 K31。",
    ),
    dict(
        name="汉字层闸",
        cmd="python3 -u vi/tests/test_han_layer.py",
        mutate="python3 -u vi/tests/test_han_layer.py --mutate",
        file="vi/tests/test_han_layer.py",
        deps=frozenset({"dict", "entry", "han_spelling", "nom_spelling"}),
        why="阶段 2 的 9 条不变量。⭐ 其中 **H6 盯的是我的判据会不会过期** —— "
            "`is_ideograph` 的兜底码位表锚在一份会更新的外部数据（Unicode）上，"
            "库里出现连兜底都兜不住的字符就红。实测兜底当下救回 **286 个字符**，"
            "全是 Python 的 `unicodedata` 14.0 还不认识的扩展 H 喃字。",
    ),
    dict(
        name="音标层闸",
        cmd="python3 -u vi/tests/test_pron_layer.py",
        mutate="python3 -u vi/tests/test_pron_layer.py --mutate",
        file="vi/tests/test_pron_layer.py",
        deps=frozenset({"dict", "pronunciation"}),
        why="阶段 3 的 10 条不变量。⭐ 其中 **P5 是读者口径的覆盖率下限**，"
            "而它是这套闸里**唯一会被「收词」弄红的一条** —— 行数闸对稀释结构性失明。"
            "P3 的判据**必须 GLOB 不能 LIKE**（LIKE 不认方括号字符类 ⇒ 永远不响）。"
            "P8 把「西贡音藏在 note 里」那次栽跤做成了闸。",
    ),
    dict(
        name="义项层闸",
        cmd="python3 -u vi/tests/test_sense_layer.py",
        mutate="python3 -u vi/tests/test_sense_layer.py --mutate",
        file="vi/tests/test_sense_layer.py",
        deps=frozenset({"dict", "entry", "sense", "sense_src", "sense_gloss",
                        "han_spelling", "nom_spelling"}),
        why="阶段 5a 的 11 条不变量。⭐ **E9 是 W2 那条判据的落点**："
            "出版层里不许出现「中文释义就是该词的汉字表记」—— 那是 69.2% 的 zh gloss。"
            "E7 守「证据层永不编辑」：被隐藏的 33,615 条必须还在 `sense_src` 里。"
            "⚠️ 依赖里带 `han_spelling`/`nom_spelling` 是**有意的** —— "
            "W2 的判据拿表记当尺子，表记层一变这道闸的答案就变。",
    ),
    dict(
        name="例句层闸",
        cmd="python3 -u vi/tests/test_example_layer.py",
        mutate="python3 -u vi/tests/test_example_layer.py --mutate",
        file="vi/tests/test_example_layer.py",
        deps=frozenset({"dict", "sense", "example", "example_gloss"}),
        why="阶段 6a 的 14 条不变量。🔴 **X7 是这一层最该守的那条**："
            "vi 版的 `example.translation` 里**一条真译文都没有**"
            "（214 条整串是 `.`，290 条是 `(tục ngữ)` 这种出处）—— 照字段名收"
            "读者就会看见「译文：.」。X7 查出版层没有 vi 语译文，收回来当场红。"
            "X8 守「隐藏的例句不带译文」—— 阶段 6d 若去买翻译是按「有没有译文」挑行的，"
            "钱会花在不出版的行上（ko 的 6d 正是这个口径）。"
            "X12 查**十二份切片都有例句落进来**，只查「表非空」的话少收十一版也全绿。",
    ),
    dict(
        name="关系与量词闸",
        cmd="python3 -u vi/tests/test_relation_layer.py",
        mutate="python3 -u vi/tests/test_relation_layer.py --mutate",
        file="vi/tests/test_relation_layer.py",
        deps=frozenset({"dict", "sense", "sense_relation", "noun_classifier"}),
        why="阶段 6b/6c 的 20 条不变量。🔴 **R8/R9/R10 三条一起守 B17**，而守的是"
            "**正确那一版判据**：naive 版（兜底 `related` 撞上任何别的 kind）命中 14,547 对，"
            "正确版（撞上**语义**更具体的 kind）只有 1,317 对 —— 差 11 倍，"
            "差的全是 `paronym+related`，而 paronym 是**语音**关系不蕴含语义相关。"
            "只查「隐藏了多少」挡不住判据被放宽；R9 是上限、R10 是反向断言。"
            "⚠️ R19 2026-10-01 **逮到一个真缺陷**（155 个纯表意词形躺在 dict 里），"
            "根因是 `is_ideograph` 当时有两份实现而收词用的是没兜底那份。",
    ),
    dict(
        name="录音层闸",
        cmd="python3 -u vi/tests/test_audio_layer.py",
        mutate="python3 -u vi/tests/test_audio_layer.py --mutate",
        file="vi/tests/test_audio_layer.py",
        deps=frozenset({"dict", "audio"}),
        why="阶段 6d 的 12 条不变量。🔴🔴 **A4 是这道闸存在的理由**："
            "schema 的 `UNIQUE(word_id, url)` **挡不住 B12** —— 同一个 Commons 文件在"
            "各版里有不同的 url（各维基内嵌转码后的 mp3），按 url 去重只能并到 4,560，"
            "按 `commons_key` 并才到 3,110 ⇒ **1,450 行重复会落库**，"
            "页面上两个按钮播同一个文件。这一条**不是 DDL 保证的**。"
            "A8 盯着跨版收割（去重后净增只有 654 条 +26.6%，删掉它总行数只掉两成）。",
    ),
    dict(
        name="词源层闸",
        cmd="python3 -u vi/tests/test_etymology_layer.py",
        mutate="python3 -u vi/tests/test_etymology_layer.py --mutate",
        file="vi/tests/test_etymology_layer.py",
        deps=frozenset({"dict", "entry", "etymology", "etymology_gloss", "han_spelling"}),
        why="阶段 7a 的 17 条不变量。🔴🔴 **Y5 是这道闸存在的理由**："
            "zh 版 26,230 段「词源」里 **21,239 段整段只是 `thư viện［書院］`** —— "
            "那是汉字表记不是词源，归阶段 2。收进词源栏 ⇒ 读者在「词源」里看见一串汉字，"
            "而页面上方「汉字表记」栏印着同一串（W2 那个病换了个栏目）。"
            "Y5 查的是**出版层里有没有**，不是「跳过了多少段」—— 后者在判据被改宽时仍为真。"
            "Y7 治的是 **5,390 段内嵌 `__NOEDITSECTION__`**（vi 版可出版段的 64.7%），"
            "⭐ 那是 `sample_check` 的抽样反验逮到的，形状检查看不见（这段**该收，只是脏**）。"
            "⚠️ 依赖里带 `han_spelling` 是**有意的** —— Y5 的变异拿表记当素材。",
    ),
    dict(
        name="查询计划闸",
        cmd="python3 -u vi/probes/query_plans.py",
        mutate="python3 -u vi/probes/query_plans.py --mutate",
        file="vi/probes/query_plans.py",
        deps=frozenset({"dict", "entry", "sense", "sense_gloss", "sense_relation",
                        "pronunciation", "etymology", "example", "example_gloss",
                        "audio", "han_spelling", "nom_spelling", "noun_classifier",
                        "sense_src"}),
        why="**展示层真正跑的 15 条查询，走的是索引还是全表扫**。判据从 "
            "`vietnamese.ts` **原文抠**（抠不到或多出来没登记都直接红 —— 闸自己的闸）。"
            "🔴 它当场逮到两个真缺陷：**W15 的指针查询 `SCAN sense_src`**（136,034 行，"
            "每开一个词条页跑一次，14.40 ms ＝ 同页其余五条的 100 倍）／"
            "**词源查询 `SCAN etymology`**（36,089 行）—— 两处都是「建表时没人按 word_id 查它」，"
            "热路径是阶段 9 才出现的。加索引后 14.40 → **0.018 ms**。"
            "🔴🔴 **vi 的结论与 ko 相反**：ko 是「`ANALYZE` 一条就够、加索引计划器不肯用」，"
            "vi 实测**索引是全部功劳、`ANALYZE` 之后没有可测变化** ⇒ 别把别门的结论当结论。"
            "⚠️ 它自己的两条判据**都按含义改写过**：①`stats` 的 `COUNT(*)` 扫全表是"
            "工作本身，不是缺陷；②临时 B 树的代价取决于**排序的行数**（门槛 200 行）——"
            "第一版把 15 条里的 9 条判红，而它们排的是 10–200 行、热态 0.015–0.8 ms。"
            "改成白名单登记那 9 条就是 `[[gate-registers-status-quo-as-spec]]`。"
            "🔴 **NOCASE 审计的判据也收窄过**：第一版在 DDL 文本里找 `NOCASE` 字样，"
            "把 `dict` 那条「**有意不带** COLLATE NOCASE」的注释判成了违规 ⇒ 先剥注释再找。"
            "⚠️ 入口 `npm run gate:vi-plans`（B15）。5 条变异全过。",
    ),
    dict(
        name="展示层契约闸",
        cmd="npm run gate:vi-display",
        mutate=None,
        mutate_why="⚠️ **有意没有 `--mutate` 档，而这是一笔明写的欠账而不是「不需要」。** 它的 32 条断言是 tsx，变异要动的是**库**（让某条断言该红）—— 技术上做得到，代价是给 tsx 加一套 do/undo，而 Node 侧没有 `dbtool` 的备份保护。📋 它的变异至今是**手动**做的（W28 那次：把 `lang: 'vi',` 从返回对象里删掉），手动做过的那几次都逮到了东西 —— 但「手动做过」不是机制。",
        file="apps/web/src/contract-check-vi.tsx",
        deps=frozenset({"dict", "entry", "sense", "sense_gloss", "sense_relation",
                        "pronunciation", "etymology", "example", "example_gloss",
                        "audio", "han_spelling", "nom_spelling", "noun_classifier",
                        "sense_src"}),
        why="**把 `VietnameseEntryView` 渲染成静态 HTML，断言可见文字**。"
            "⭐ `[[it-display-layer-stage8]]`：接上展示层是独立一道闸 —— "
            "vi 这一轮它当天兑现了 8 次，全是数据层十一道闸报绿时逮到的。"
            "🔴 最狠的四个：查 `mai`（清晨/梅）显示的是 `Mai`（姓氏，`word_norm` 冲突 1,263 组，"
            "**1,291 页打不开且内容是错的**）／例句里印着韩语（1,655 条内嵌译文）／"
            "关系里印着波兰语 `kościół`（2,238 行非国语字目标，全死链）／"
            "关系目标印成 `hoahòahọahỏa`×3（缺分隔符＋缺去重）。"
            "⭐ 它同时是**五条欠账的读者口径**：W6 不许把按码位猜的表记印成「汉越字」／"
            "W7 拼的音标要标注／W10 `ref` 印「出处：」／W13 折叠但**不隐藏**／"
            "W15 没有可出版义项时印指针。"
            "⭐ **值域覆盖跨全库查，不只查抽样词**（关系 18 种／方言 13／词性 27／"
            "词源类型 5／来源版 4，全部有中文名）—— 抽样扫不到的值一样会印给读者。"
            "🔴🔴 它自己的判据**收窄过两次**：①关系徽标只看 `vi-rel-kind` 那一格，"
            "查整页会把英文释义里的 `related to` 当成原码漏出（ko 那份第一版报过 14 处假阳）；"
            "②韩文只盯**例句正文**，查整页会误伤 7 条以拉丁为主、夹着原文人名的正当引文"
            "（`Hồng Lâu Mộng, Tào Tuyết Cần 홍루몽, 조설근`）。"
            "⚠️ 依赖几乎是全表：它渲染整页，任何一层变了渲染结果就变。"
            "⚠️ 入口是 `npm run gate:vi-display`（B15：闸有文件而没人跑得动它＝没有闸）。",
    ),
    dict(
        name="回归闸",
        cmd="python3 -u vi/tests/test_no_regression.py",
        mutate="python3 -u vi/tests/test_no_regression.py --mutate",
        file="vi/tests/test_no_regression.py",
        deps=frozenset({"dict", "entry", "sense", "sense_src", "sense_gloss",
                        "sense_relation", "pronunciation", "etymology", "example",
                        "example_gloss", "audio", "han_spelling", "nom_spelling"}),
        why="**过去每一个修复现在还在不在**（18 条，14 条变异全过）。"
            "⭐ 它与层闸的分工：层闸查**不变量**（多半是「= 0」）、要手动跑；"
            "回归闸查**修复**，**每次写库由 `dbtool._regression_check()` 自动跑**，"
            "而且它锁**非零的已接受基线**（B17 的 1,460／西贡音 86,535／指针证据 33,361／"
            "空白页 222）—— 那是层闸干不了的事。"
            "🔴 用户 2026-08-11 的原话：「同一个问题你修了，隔天修其他问题，"
            "你又发现之前的问题又出现了。」es 上已知三次，三次全是事后偶然撞见的。"
            "🔴🔴 **R1 的空白页分两个数**：总数 222 是基线，而「源头也没给」必须是 0 —— "
            "实测 222 个在证据层**都有指针义项**（`UBND`=Ủy ban Nhân dân、`ôtô`、`São Tomé`），"
            "源头给了而我们没印 ⇒ 欠账 **W15**。`[[dont-say-source-lacks-what-we-skipped]]`："
            "只报一个总数的话，「我们没印」会被当成「源头没有」。"
            "⚠️ **「读取路径」那一半现在是空的**（展示层 `vietnamese.ts` 还不存在）——"
            "但那是**带锁的豁免**：`R0` 一旦发现那个文件出现而 `READ_PATH` 还空着，当场判红。"
            "⚠️ 依赖带 `dict` 是有意的偏宽（动词形会变空白页和 `word_norm` 那两条的答案）。",
    ),
    dict(
        name="外锚闸·例句/关系/词源/录音/量词",
        cmd="python3 -u vi/pipeline/verify_layers_vs_dump.py",
        mutate="python3 -u vi/pipeline/verify_layers_vs_dump.py --mutate",
        file="vi/pipeline/verify_layers_vs_dump.py",
        deps=frozenset({"dict", "entry", "sense_src", "example", "example_gloss",
                        "sense_relation", "etymology", "audio", "noun_classifier"}),
        why="**五层 vs dump 的三向恒等式**（源头缺／库里多／**键对上而内容不一样**）。"
            "前八道闸锚的都是库自己 ⇒ 对「收割器整批漏抽」失明；这一道锚外部 dump ⇒ "
            "`[[external-anchor-gates]]` **永不过期**。"
            "⭐ 它**一个判据都不重写**，五层各 import 收割器的 `collect()` —— 为此把四个"
            "收割器埋在 `main()` 里的逻辑抽成了 `index()`/`collect()`。"
            "🔴 ko 那道同名闸判据写错过两次（例句太宽报 3 万假缺、读音太细报 7,163 假缺），"
            "根因都是「闸自己重写了收割器的判据」。"
            "🔴🔴 **而这一道第一次跑就逮到我自己两条**：`src.endswith('-edition')` 认不出 "
            "`zh-edition-trad`（690 条真译文被判成第三类）／「哪些行才真的落库」我又写了一遍"
            "（漏掉「可出版」那半句，458 条假缺）⇒ **import 判据还不够，落库口径也要共用一个函数**。"
            "⚠️ 依赖故意写得宽（带 `dict`/`entry`/`sense_src`）：它们是收割的索引，"
            "动了它们恒等式的答案就变。⚠️ 跑一趟要扫 12 份 dump × 5 层（分钟级）—— "
            "**所以它不在写库后自动跑的那几道里**，靠 `gates.mark()` 记账＋账的闸拦着（ko 的 K31 机制）。",
    ),
    # 🔴🔴 **2026-10-06 补登记：账的闸自己从来不在这张名单里。**
    #    它每次写库由 `dbtool._ledger_check()` 自动跑，所以「真被跑」那一关它一直过 ——
    #    而正因为如此，**它从没有被当成一道闸来管**：
    #      ① `run_gates.py --all` 跑不到它（换台机器时「全跑一遍」漏掉它）
    #      ② W19 新建的**变异档机制覆盖不到它的 13 条变异**（含今天新加的 V12 四条）
    #    ⇒ 登记。`deps=None` 并说明：它读库（V1/V8/V10/V11 都查表），但判的是
    #      「计划表/欠账表与库和代码对不对得上」—— 那是**写库这个动作**本身弄脏的，
    #      而 `dbtool` 已经在每次写库时跑它了，不需要再靠 deps 记一次账。
    dict(
        name="账的闸",
        cmd="python3 -u vi/tests/test_plan_ledger.py",
        mutate="python3 -u vi/tests/test_plan_ledger.py --mutate",
        file="vi/tests/test_plan_ledger.py",
        deps=None,
        why="V0–V12 ＋ 花名册自检。**每次写库由 `dbtool` 自动跑**，登记进这张名单"
            "为的是另两件事：`--all` 跑得到它、以及**变异档有人逼着跑**（W19）。"
            "⚠️ 写 `deps=None` 而不是列表：它的「过期」由写库这个动作本身触发，"
            "而那条路已经有人走了 —— 再按表记一次账只会让欠账表天天非空"
            "（`[[permanently-red-gate-masks-real-reds]]`：恒红等于没有信号）。",
    ),
    dict(
        name="表结构闸",
        cmd="python3 -u vi/pipeline/build_v3_schema.py --check",
        mutate=None,
        mutate_why="⚠️ **有意没有**：它比的是 DDL（25 个对象在不在），变异＝真去 DROP 一张表，而那不可逆（表里有 6e 买来的数据）。⇒ 这一道的「变异」是 `--check` 自己：少一个对象它当场红，而「少一个对象」正是唯一能让它漏报的改动。",
        file="vi/pipeline/build_v3_schema.py",
        deps=None,
        why="⚠️ **有意没有数据依赖**：它比的是 DDL（25 个对象在不在、"
            "以及**有意不建的三张表有没有偷偷出现**），一行数据都不读。"
            "插多少行都不会让它过期，**建表/删表**才会 —— 而那不走 `session()`。"
            "⇒ 它进这张名单不是为了「写库后跑」，而是为了 `run_gates.py --all` "
            "和 `self_check()` 管得到它。写成 `deps=None` 而不是空集合，"
            "是为了让「想过了」和「忘了填」分得开。",
    ),
    # 🔴🔴 **2026-10-06 补登记两道「本来就存在、而 vi 从没把它们纳入 `--all`」的闸。**
    #    `[[lesson-must-become-mechanism]]`：「闸存在／有入口／覆盖这门语言／真被跑」
    #    是四道独立关卡 —— 这两道都过了前三道，**第四道一直靠我手动跑**。
    dict(
        name="样式孤儿闸",
        cmd="npm run --silent gate:css-audit",
        mutate=None,
        mutate_why="⚠️ **有意没有 `--mutate` 档**：它读的是源码（类名 vs CSS 规则），变异＝删一条 CSS 规则再还原，代价是改仓库里的文件。📋 手动做过一次并逮到东西（55 个 `vi-*` 类名零条规则时它判红）。与契约闸同一笔欠账。",
        file="apps/web/src/css-audit.ts",
        deps=None,
        why="视图里用到的每个 className，`styles.css` 里必须真有规则。"
            "⚠️ **有意没有数据依赖**：它只读源码。"
            "🔴 它逮到过 vi 的 **55 个零规则类名，而当时契约闸 23 条全绿** ——"
            "契约闸读文本、**看不见样式**。而那次它能逮到的前提是 vi 先被登记进它的 "
            "`VIEWS`（在此之前 vi 从没被它覆盖过）。"
            "🔴 本行补登记的理由：它从 2026-10-03 起就覆盖 vi，"
            "但 **`vi/run_gates.py --all` 的 13 道里没有它**，每次都靠我手动跑 ——"
            "而「靠人记得」正是这一课说不管用的那种。",
    ),
    dict(
        name="分发闸",
        cmd="npm run --silent gate:dispatch-audit",
        mutate=None,
        mutate_why="⚠️ **有意没有 `--mutate` 档**，但它是四道里唯一**变异验证真的起过作用**的：2026-10-06 建它时第一版判据 `lang:\\s*'vi'` 把**类型声明也算上了**，于是把 `lang: 'vi',` 从返回对象里删掉之后它照样绿 —— **是手动变异当场报出来的**，才拆成 `inType`/`inObject` 两条。⇒ 这一道的变异必须做成机制，记在 W19 的残留里。",
        file="apps/web/src/dispatch-audit.ts",
        deps=None,
        why="🔴🔴🔴 **页面真的走到那个视图了吗。** 2026-10-06 用户看越南语词条页，"
            "上面只有一行 `🧩 「」的展示层还没接上` —— 而 `「」` 是空的。"
            "根因两个：`vietnamese.ts` 的类型和 `getEntry()` 返回对象**都没有 `lang`**"
            "（`korean.ts`/`japanese.ts` 都有）⇒ `entry.lang === 'vi'` 永远为假、"
            "**`VietnameseEntryView` 一次都没渲染过**；外加兜底白名单里没有 `vi`。"
            "⚠️ **当时三道闸全绿，每道都有结构性理由看不见它**："
            "契约闸**直接 `createElement(VietnameseEntryView, …)`**、从不走 `App.tsx` 的分发"
            "（它测「视图对不对」不测「视图被调到没」）；`css-audit` 只问「视图登记了没」；"
            "TypeScript 抓不到，因为 `App.tsx` 本地的 `ViEntry` 是**手抄的镜像**、"
            "声明了 `lang: 'vi'`，而分发处是 `entry as ViEntry` 强转。"
            "⇒ 那四道关卡之后还有**第五道：页面真的走到它**。"
            "🔴 它自己的判据**第一版就宽了**：`lang:\\s*'vi'` 把**类型声明**也算上"
            "（`lang: 'vi';` 分号 vs `lang: 'vi',` 逗号），而本次缺陷恰恰是"
            "「类型声明了、返回对象没给」⇒ 删掉返回对象里那行它照样绿。"
            "**是变异验证当场报出来的**，已拆成两条分别查。3 个变异全过。",
    ),
]

# ── 没有任何闸盯着的表：**必须在这儿逐张说明，并且带一个会失效的条件** ──────
# 🔴 这不是豁免清单，是**带锁的豁免**：条件写成「还是 0 行」，
#    哪天有人往里写了第一行，`self_check()` 当场红，逼人去登记一道闸。
#    光写一句「以后再说」＝ ja 的 `sense_tag` 空了整个项目而阶段表全 ✅。
_LATER = "（0 行）。落第一行之前必须先登记一道闸 —— 要验的是覆盖率与内容对不对，不是行数。"
UNCLAIMED = {
    "sense_tag":        "义项标签" + _LATER,
    "etymology_gloss":  "词源正文的中文" + _LATER,
    "field_src":        "字段来源登记" + _LATER,
}
# ⭐ **2026-10-01：五张表从这张名单里毕业了** —— `example` / `example_gloss` /
#    `sense_relation` / `noun_classifier` / `audio`。
#    这个「带锁的豁免」机制当天验过一次真的：四次写库，每次落第一行
#    `self_check()` 都当场判红、逼我去登记闸，一次都没让我往下走。
#    ⚠️ 它们原来各自带着一句「哪道闸该管它」（B17 归关系闸、B12 归录音闸）——
#      那两句话现在真的变成了 R8/R9/R10 与 A4。**写在名单里的提醒兑现了才算数。**
# ⭐ **2026-10-02：`etymology` 也毕业了**（阶段 7a）。它原来带的那句是
#    「B18（词源正文对读者不可见）要在那道闸里」—— ⚠️ **这一句只兑现了一半**：
#    数据层的闸（Y1–Y17）建了，而 B18 问的是**读者看不看得见**，那要等阶段 9 的
#    展示层契约闸。⇒ B18 现在是一笔**真欠账**（之前库里 0 行，它连欠账都算不上）。


def by_name(name):
    for g in GATES:
        if g["name"] == name:
            return g
    return None


# ── 从一次写库的 diff 算出过期的闸 ──────────────────────────────────────────
def table_of(key):
    """`diff()` 的键 → 它属于哪张表。

    键有三种形状（见 `dbtool.snapshot`）：`__rows__` / `表.列` / `#表`。
    裸列名（`pos`、`freq_zipf`）属于主表 `dict`。
    """
    import dbtool
    if key == "__rows__":
        return dbtool.TABLE
    if key.startswith("#"):
        return key[1:]
    return key.split(".", 1)[0] if "." in key else dbtool.TABLE


def dirty(d, extra_tables=()):
    """→ (过期的闸名列表, 动过的表集合)。

    🔴🔴 **`d`（计数差）和 `extra_tables`（从 SQL 抠的表名）两个都要，后者是主的。**
       ko 的第一版只看 `d`，当天就被一次纯内容 `UPDATE` 穿过去：
       20 条例句译文改了、所有计数一个没变、欠账是空的。
       `[[primary-key-is-not-enough]]`：**计数型判据对内容改动结构性失明。**
       留着 `d` 是因为它能认出**加列**这种 SQL 里看不出表名的变化。
    """
    touched = {table_of(k) for k in d} | {str(t).lower() for t in extra_tables}
    out = [g["name"] for g in GATES
           if g["deps"] is not None and (g["deps"] & touched)]
    return sorted(out), touched


# ══════════════════════════════════════════════════════════════════════════════
# 🔴🔴🔴 **变异欠账：W19 的结清交付物。2026-10-06。**
#
# W19 记的那件事是：回归闸的变异验证**整个跑不起来，而它看起来是绿的**
# （`check_brief()` 从 2 元组改成 3 元组，`mutate()` 里三处解包没跟着改；
#  而那个 for 循环只在基线不绿时才执行，于是一直没人踩到）。
# 解包当天就修了，**而账上剩下的那一句一直开着**：
#     「`run_gates.py` 里加一档「跑变异」，让『谁逼人跑变异』也成为机制。」
#
# ⭐ `[[lesson-must-become-mechanism]]`：**变异验证是闸的闸** —— 它不跑，
#   上面那一长串 ✅ 只说明「检查还在」，不说明「检查逮得到东西」。
#   而「存在／有入口／覆盖这门语言／真被跑」是四道独立关卡，变异档卡在**第四关**。
#
# ═══ 判据：**闸的文件变了就必须重跑它的变异** ═══
# 🔴 不是「每次写库都跑」（变异动真库，代价太大，而数据变了不代表判据变了）；
#    也不是「每天跑一次」（时间不是判据，`[[external-anchor-gates]]`）。
#    真正会让变异失效的事件只有一个：**有人动了那道闸的代码**
#    —— 改断言、改基线、整段替换（而我 2026-10-05 就是这么把 P12/P13 切掉的，
#       正常跑报「全绿」，**只有 `--mutate` 报了出来**）。
# ⇒ 记下每道闸**上次跑变异时那个文件的 sha256**；对不上就是欠一次变异。
# ⚠️ 这条判据也认「文件改回去了」：sha 一样就不欠 —— 它锚的是内容不是时间。
MUTLOG = paths.DATA / "db" / ".vi-mutations.json"


def file_sha(g):
    """→ 这道闸的闸文件内容 sha256（前 16 位）；文件不在返回 None。"""
    import hashlib
    p = ROOT / g["file"]
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def mutation_log():
    """→ {闸名: {"sha":…, "when":…, "ok": bool}}。读不动就抛（不许静默当空）。"""
    if not MUTLOG.exists():
        return {}
    try:
        return json.loads(MUTLOG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit("🔴 变异台账读不动：%s（%s）—— 别当成「没欠」" % (MUTLOG, e))


def record_mutation(name, ok):
    log = mutation_log()
    log[name] = {"sha": file_sha(by_name(name)), "ok": bool(ok),
                 "when": datetime.datetime.now().isoformat(timespec="seconds")}
    MUTLOG.parent.mkdir(parents=True, exist_ok=True)
    MUTLOG.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def mutation_debt():
    """→ [(闸名, 原因)]。空 ＝ 每一道有变异档的闸，都在**当前这版代码**上跑绿过。"""
    log = mutation_log()
    out = []
    for g in GATES:
        if not g.get("mutate"):
            # 🔴 `mutate=None` 的必须写明为什么 —— 与 `deps=None` 同一条规矩：
            #    「想过了」和「忘了填」要在结构上分得开。
            if not g.get("mutate_why", "").strip():
                out.append((g["name"], "🔴 `mutate=None` 而没写 `mutate_why`"))
            continue
        rec = log.get(g["name"])
        sha = file_sha(g)
        if rec is None:
            out.append((g["name"], "从没在这套机制下跑过变异"))
        elif not rec.get("ok"):
            out.append((g["name"], "上次跑变异是**红的**（%s）" % rec.get("when", "?")))
        elif rec.get("sha") != sha:
            out.append((g["name"], "闸文件改过了（上次跑变异时 sha=%s，现在 %s）"
                        % (rec.get("sha"), sha)))
    return out


def run_mutation(name, verbose=True):
    """跑一道闸的变异档。→ True/False。**跑绿才记台账**（与 `run()` 同一条规矩）。"""
    g = by_name(name)
    if g is None:
        raise SystemExit("🔴 没有这道闸：%r" % name)
    if not g.get("mutate"):
        raise SystemExit("🔴 %s 没有变异档（理由：%s）" % (name, g.get("mutate_why", "没写")))
    if verbose:
        print("\n── %s（变异）\n   $ %s" % (name, g["mutate"]))
    r = subprocess.run(g["mutate"], shell=True, cwd=str(ROOT))
    ok = r.returncode == 0
    record_mutation(name, ok)
    if verbose:
        print("   %s %s 变异（退出码 %d）" % ("✅" if ok else "🔴", name, r.returncode))
    return ok


# ── 欠账状态 ────────────────────────────────────────────────────────────────
def load():
    """→ {闸名: {"tag":…, "when":…, "tables":[…]}}。

    🔴 文件不存在 ＝ 没欠账（初始状态，安全）。
       文件**读不动** ≠ 没欠账 —— 那种时候抛，别静默当空。
    """
    if not PENDING.exists():
        return {}
    try:
        obj = json.loads(PENDING.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit("🔴 欠账文件读不动（%s）：%s\n"
                         "   **不许当成「没欠账」** —— 手动查明，或删掉它并把所有闸跑一遍。"
                         % (e, PENDING))
    if not isinstance(obj, dict):
        raise SystemExit("🔴 欠账文件不是对象：%s" % PENDING)
    return obj


def _save(obj):
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True),
                       encoding="utf-8")


def mark(names, tag, tables=()):
    """记上欠账。已经欠着的保留**最早**那次的 tag（谁弄脏的才是线索）。"""
    if not names:
        return {}
    cur = load()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for n in names:
        if n not in cur:
            cur[n] = {"tag": tag, "when": now, "tables": sorted(tables)}
    _save(cur)
    return cur


def clear(name):
    """划掉一笔。**只该由「闸真的退出码 0」调用**（见 `run_gates.py`）。"""
    cur = load()
    if name in cur:
        del cur[name]
        _save(cur)
        return True
    return False


def clear_all():
    if PENDING.exists():
        PENDING.unlink()


def announce(cur=None, out=None):
    """把欠账大声说出来。**说在写库输出的最末尾** —— 那是人还在看屏幕的时候。"""
    out = out or sys.stdout
    cur = load() if cur is None else cur
    if not cur:
        return 0
    print("\n🔴🔴 **以下闸已过期，必须重跑**", file=out)
    for n in sorted(cur):
        v = cur[n]
        print("     · %-20s ← %s（%s）" % (n, v.get("tag", "?"), v.get("when", "?")), file=out)
    print("   ⇒ 一条命令跑完欠的那几道：**python3 vi/run_gates.py**", file=out)
    print("      （每道跑绿才划掉自己那一笔；跑不绿的留着，账的闸 **V9** 会一直红）", file=out)
    return len(cur)


# ── 闸自己的闸 ──────────────────────────────────────────────────────────────
def self_check():
    """→ 问题列表（空 ＝ 通过）。这道自检查的是**名单本身**对不对。"""
    import sqlite3
    bad = []
    seen, claimed = set(), set()
    for g in GATES:
        if g["name"] in seen:
            bad.append("闸名重复：%s" % g["name"])
        seen.add(g["name"])
        if not (ROOT / g["file"]).exists():
            bad.append("闸文件不存在：%s（%s）" % (g["file"], g["name"]))
        if not g.get("why", "").strip():
            bad.append("%s 没写 why —— 依赖为什么是这些，得说得出来" % g["name"])
        if g["deps"] is not None:
            if not g["deps"]:
                bad.append("%s 的 deps 是**空集合** —— 想过了要写 `deps=None` 并说明，"
                           "空集合分不清「没依赖」和「忘了填」" % g["name"])
            claimed |= g["deps"]

    # ① 每张追踪中的表，至少要有一道闸盯着
    import dbtool
    tables = set(dbtool.TRACK_TABLES) | {dbtool.TABLE}
    for t in sorted(tables - claimed - set(UNCLAIMED)):
        bad.append("🔴 表 `%s` **没有任何闸盯着** —— 动了它一道闸都不会脏。"
                   "登记一道闸，或写进 UNCLAIMED 并带一个会失效的条件" % t)

    # ② UNCLAIMED 里的表必须**还是 0 行**（带锁的豁免，不是永久豁免）
    if paths.DB.exists():
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        try:
            live = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for t, why in sorted(UNCLAIMED.items()):
                if t not in tables:
                    bad.append("UNCLAIMED 里的 `%s` 不在追踪名单里 —— 名单漂了" % t)
                    continue
                if t not in live:
                    continue
                n = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                if n:
                    bad.append(
                        "🔴🔴 `%s` 已经有 **%s 行**，而它还挂在 UNCLAIMED（理由写的是"
                        "「%s」）—— 豁免的条件已经不成立，**去登记一道闸盯着它**"
                        % (t, format(n, ","), why[:40]))
        finally:
            con.close()
    else:
        bad.append("库不存在，UNCLAIMED 的「还是 0 行」这一条查不了：%s" % paths.DB)

    # ③ 每道闸都得在账的闸的交付物名单里（登记了，被删掉才会有人说话）
    try:
        sys.path.insert(0, str(ROOT / "vi"))
        from tests.test_plan_ledger import FILES
        listed = {p for items in FILES.values() for _n, p in items}
        for g in GATES:
            if g["file"] not in listed:
                bad.append("%s（%s）**不在账的闸的交付物名单里** —— "
                           "它被删掉不会有人说话" % (g["name"], g["file"]))
    except Exception as e:                       # noqa: BLE001
        bad.append("读不到 test_plan_ledger.FILES（%s）—— 那本身要查" % e)

    # ④ npm 入口的闸，`package.json` 里真有那个 script（B15：文件在而没人跑得动它）
    try:
        pj = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = pj.get("scripts", {})
        for g in GATES:
            if g["cmd"].startswith("npm run"):
                key = g["cmd"].split()[-1]
                if key not in scripts:
                    bad.append("%s 的入口 `npm run %s` **在 package.json 里不存在**（B15）"
                               % (g["name"], key))
    except Exception as e:                       # noqa: BLE001
        bad.append("读不到 package.json（%s）" % e)

    # ⑤ **登记的变异档 vs 闸文件里真的有没有那条路**（W19，2026-10-06）
    # 🔴 两个方向都查，而第二个方向才是值钱的那个：
    #    · 登记了 `mutate=` 而文件里没有 `--mutate` 的分支 ⇒ 跑它等于跑一遍普通档，
    #      **退出码 0、台账记绿，而一条变异都没跑过** —— 一道「看起来跑过」的空档。
    #    · 文件里有 `--mutate` 而登记表里是 `None` ⇒ 这道闸有变异而没人逼人跑它，
    #      那正是 W19 本身。
    # ⚠️ 判据**问登记表也问文件**，不靠我记得（`[[gate-registers-status-quo-as-spec]]`：
    #    闸「如实登记现状」之后就再也不会问现状对不对）。
    for g in GATES:
        p = ROOT / g["file"]
        has = p.exists() and "--mutate" in p.read_text(encoding="utf-8", errors="replace")
        if g.get("mutate") and not has:
            bad.append("🔴🔴 %s 登记了 `mutate=%r`，而 `%s` 里**没有 `--mutate` 这条路** ——"
                       "跑它会静默退 0 并把台账记成绿的" % (g["name"], g["mutate"], g["file"]))
        if (not g.get("mutate")) and has:
            bad.append("🔴 %s 的文件里有 `--mutate` 而登记表写着没有变异档 —— "
                       "那就是 W19 本身：有变异而没有任何东西逼人跑它" % g["name"])
        if (not g.get("mutate")) and not g.get("mutate_why", "").strip():
            bad.append("%s 没有变异档也没写 `mutate_why` —— "
                       "「想过了」和「忘了填」要分得开（与 `deps=None` 同一条规矩）"
                       % g["name"])
    return bad


def run(name, verbose=True):
    """跑一道闸。→ True/False。**绿了才划账**，而「绿」的定义是退出码 0。"""
    g = by_name(name)
    if g is None:
        raise SystemExit("🔴 没有这道闸：%r" % name)
    if verbose:
        print("\n── %s\n   $ %s" % (name, g["cmd"]))
    r = subprocess.run(g["cmd"], shell=True, cwd=str(ROOT))
    ok = r.returncode == 0
    if ok:
        clear(name)
    else:
        # 🔴 **跑红了也要记一笔** —— 哪怕它本来不在欠账里。
        #    只做「绿了划账」的话，一道**本来就红着**的闸（没有任何写库弄脏它）
        #    跑出红之后欠账还是空的、账的闸照样绿 ——
        #    那正是 ko 那两条的处境：**红着而没有任何东西记得它红。**
        mark([name], "run-red（跑出红，不是写库弄脏的）", ("（跑红）",))
    if verbose:
        print("   %s %s（退出码 %d）" % ("✅" if ok else "🔴", name, r.returncode))
    return ok


if __name__ == "__main__":
    bad = self_check()
    print("■ vi 闸名单自检：%d 道闸" % len(GATES))
    for b in bad:
        print("   🔴 " + b)
    print("   %s" % ("✅ 通过" if not bad else "🔴 %d 个问题" % len(bad)))
    n = announce()
    if not n:
        print("\n■ 当前没有欠跑的闸 ✓")
    raise SystemExit(1 if (bad or n) else 0)
