#!/usr/bin/env python3
"""**写库之后哪几道闸过期了** —— 名单、依赖、欠账状态、变异台账，都在这一个文件里。ru，2026-10-07。

机制照搬 vi（它又照搬 ko 的 **K31**，那部分与语言无关）。为什么存在，一句话：
2026-09-26 发现 ko 有两道外锚闸**从前一天起一直红着**，两条都不是新缺陷，
是「修了数据没跟着重跑闸」—— 而流程里**没有任何一条机制逼人重跑**。
`[[lesson-must-become-mechanism]]`：**做成机制的全守住了，写成文字的一条没守住。**

═══ ⭐ 名单只登记**真正存在**的闸（阶段 3 收尾时五道：结构／骨架／账／重音／屈折）═══
🔴 **别为了让名单好看而把不存在的闸写进去** —— 那正是 `self_check()` 要拦的事
（ko 的教训：文件在、八门都写了、`package.json` 里没有入口，谁也没跑过；
 「存在／有入口／覆盖这门语言／真被跑」是**四道独立关卡**）。
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
PENDING = paths.DATA / "db" / ".ru-gates-pending.json"
MUTLOG = paths.DATA / "db" / ".ru-mutations.json"

# ── 闸名单 ──────────────────────────────────────────────────────────────────
# deps=None ＝ **已声明「动数据不会让它过期」**，必须同时写清为什么。
#   （与 `session(invalidates=[])` 同一个设计：空和没填要在结构上分得开。）
GATES = [
    dict(
        name="结构闸",
        cmd="python3 -u ru/tests/test_schema.py",
        mutate="python3 -u ru/tests/test_schema.py --mutate",
        file="ru/tests/test_schema.py",
        # 🔴 为什么是这三张：S4 读 `entry.aspect` 的值域、S5 读 `stress` 的主行唯一性，
        #    而 `dict` 在这儿是**结构变更的信号** —— `dbtool.addcolumn()` 改结构时
        #    会把 `dict` 加进 touched，于是任何 DDL 都会脏掉这道闸。
        deps=frozenset({"dict", "entry", "stress"}),
        why="阶段 0 的 5 条结构不变量。⭐ 其中 **S3 盯「有意不建的有没有偷偷出现」**"
            "（`pronunciation_entry`／`collocation`／`aspect_pair` 专表／`word_family` 专表"
            "四个都带推翻条件），**S4 盯 `entry.aspect` 的归一**"
            "（ru 版源头标 `perfect`、en 版标 `perfective`，不归一就是同一列两个值域）。"
            "🔴 它治的是 B7 那个形状：`CREATE TABLE IF NOT EXISTS` 对已存在的表是空操作，"
            "**改了建表语句老库一个字都不会变**，而只数对象名的核对会照样报全绿。",
    ),
    dict(
        name="骨架闸",
        cmd="python3 -u ru/tests/test_skeleton.py",
        mutate="python3 -u ru/tests/test_skeleton.py --mutate",
        file="ru/tests/test_skeleton.py",
        deps=frozenset({"dict", "entry"}),
        why="阶段 1 的 11 条不变量。⭐ **K3 是读者口径**（`dict.pos` 的每个斜杠段都要在"
            "值域里）—— ko 的 K31：词性表按长码写而展示层读短码，**我的覆盖闸也查长码**"
            "⇒ 双方一致报全绿而每个徽标都是空的。"
            "⭐ **K10 是 vi 那门最狠的那个缺陷**：`word_norm` 一对多 ⇒ 展示层 `.get()` "
            "只取第一行 ⇒ **1,291 个页面打不开且内容是错的**。它带已接受基线（锁数字不锁名字），"
            "**解在展示层不在归一层** —— 归一层去折会毁掉 ё 的辨义。"
            "🔴 K9 查**七份源每一份都有行落进来**（只查「表非空」的话少收六版也全绿，vi 的 X12）。",
    ),
    dict(
        name="账的闸",
        cmd="python3 -u ru/tests/test_plan_ledger.py",
        mutate="python3 -u ru/tests/test_plan_ledger.py --mutate",
        file="ru/tests/test_plan_ledger.py",
        # 🔴 它读的是**计划表 ＋ 库 ＋ 闸台账**。库那一侧的依赖写宽：
        #    V1 的交付物 SQL 会随阶段长，而漏跑的代价比多跑几秒大得多。
        deps=frozenset({"dict", "entry", "sense", "stress", "inflection"}),
        why="10 条（V0–V10）。⭐ **V2 专治 ko 那份的结构性失明**："
            "一个阶段声明 ✅ 而一条交付物都没登记 ⇒ V1 的循环体一次都不执行 ⇒ 静默全绿"
            "（ko 的阶段 5/6/7 正是这样，ja 的词源层缺席三个月同形）。"
            "**V10 是带锁的占位**：`COVERAGE` 现在是空的，而一旦库里出现任何内容层"
            "（义项/读音/词源/例句/重音/屈折）它当场判红 —— vi 的 W14 是"
            "「例句的中文译文」只存在于一条注释里，阶段表、欠账表、覆盖率表**三处一致地看不见它**。"
            "🔴 V9 把「闸欠着没跑」和「**欠着变异没跑**」都算红。",
    ),
    dict(
        name="重音闸",
        cmd="python3 -u ru/tests/test_stress.py",
        mutate="python3 -u ru/tests/test_stress.py --mutate",
        file="ru/tests/test_stress.py",
        # 🔴 `dict` 在这儿不是陪衬：T2/T5/T11 都要拿 `dict.word` 去比，
        #    而 R13 正是「`dict` 的身份单位里混进了重音符」。
        deps=frozenset({"dict", "entry", "stress"}),
        why="阶段 2 的 11 条（T1–T11）。⭐ **T2 是「收它的判据和查它的判据必须是同一个"
            "函数」** —— 闸直接调 `criteria.stressed_spelling` 复核每一行出版值"
            "（ko 的 K24／vi 的 R19 都是闸手写一版近似判据，**同时更宽又更窄**）。"
            "⭐ **T4 三个方向都断言**：`entry.stressed` 是派生列，只查一个方向的话"
            "「真值全删」和「派生列全清」各能过一个。"
            "🔴 **T5/T6 治的是「没有信息的行比空着更坏」**：源头把重音符写成游离的"
            "（`крем для бритья ́`），修掉之后剩下的串与词头一字不差 —— 印在读者页的"
            "「重音写法」栏里它看起来正常而什么都没说。T6 另治**预组合 vs 组合式**"
            "两种编码（`ѐ` U+0450 `strip_stress` 剥不掉 ⇒ 重音符会活着流进检索键），"
            "**这一条是写这道闸的时候逮到的，当场逼出一次 `--rebuild`**。"
            "⭐ **T10 锁两个口径**（全体词元 37.18% ／ 需要标注的 39.08%）——"
            "单锁一个会把「6.59% 的词元本来不需要重音符」读成缺口。",
    ),
    dict(
        name="屈折闸",
        cmd="python3 -u ru/tests/test_inflection.py",
        mutate="python3 -u ru/tests/test_inflection.py --mutate",
        file="ru/tests/test_inflection.py",
        # 🔴 `dict` 不是陪衬：I10 的分母是 `dict.is_lemma=1`。2026-10-23 ru-crit-9
        #    把 62,576 个形动词页 1→0，**I10 的覆盖率当场变了而一行屈折都没动** ——
        #    不依赖 `dict` 的话这道闸不会被标脏。
        deps=frozenset({"dict", "entry", "inflection"}),
        why="阶段 3 的 13 条（I1–I13）。⭐ **I2 用收它的那个函数复核每一行**"
            "（`criteria.inflection_rows`，638 万行不抽样，约 8 分钟）。"
            "⭐ **I11 是第二个信号的落点**：`forms` 里 45.8 万行拉丁转写，而 en/fr 版会发出"
            "「只带语法标签的转写行」（12 万行）⇒ 光按 tag 挡挡不住，出版层一个拉丁字母都不许有。"
            "🔴 **I12 治张冠李戴**：en 版代词表模板 `g` 把整张人称代词范式印在每个代词页上"
            "（`я → ты`）。**I13 是 R16 的锁**（`class` 512 种值没有家，一出现装它的列就红）。"
            "🔴 这道闸写好之后**一天没登记**（10-09 → 10-23），是账的闸的 V9 报出来的："
            "`inflection` 有 638 万行而还挂在空表豁免里。",
    ),
    dict(
        name="音标闸",
        cmd="python3 -u ru/tests/test_pronunciation.py",
        mutate="python3 -u ru/tests/test_pronunciation.py --mutate",
        file="ru/tests/test_pronunciation.py",
        # 🔴 `stress` 在这儿：Q11 拿重音层做独立复核；`entry` 在这儿：Q3 查 entry 属于同一个词形；
        #    `dict` 在这儿：Q10 的分母是 is_lemma（同一天 ru-crit-9/10 两次改了它）。
        deps=frozenset({"dict", "entry", "stress", "pronunciation"}),
        why="阶段 4 的 12 条（Q1–Q12）。⭐ **这一层最容易出的错是「这条读音属于谁、能不能印」**："
            "Q3 查 entry 属于同一个词形、Q4 两个方向锁复数读音（挂词元＝张冠李戴）、"
            "**Q11 用重音层做独立复核**（主重音位置 vs 这个 entry 的全部重音候选，实测 98.64% 一致）。"
            "🔴 **Q5 从 tags 重算 hidden/dialect 对「判据本身写坏」是瞎的**（同一个坏函数两边一致）"
            "⇒ **Q12 钉已知答案**（`агент ˈaɡʲɪnt` 必须 hidden、`замок` 两个 entry 各挂各的）。"
            "**Q8 是读者口径的锁**：fr 版的 `Russie (Saint-Pétersbourg)` 是录音者所在地，不许进 dialect。",
    ),
    dict(
        name="义项闸",
        cmd="python3 -u ru/tests/test_sense.py",
        mutate="python3 -u ru/tests/test_sense.py --mutate",
        file="ru/tests/test_sense.py",
        # `dict` 在这儿：E12/E13 的分母是 is_lemma；`entry`：E3 查归属。
        deps=frozenset({"dict", "entry", "sense", "sense_src", "sense_gloss", "sense_tag"}),
        why="阶段 5a 的 13 条（E1–E13）。⭐ **E5/E6 是「有意不出版」的锁**：指针（「лука́ 的复数属格」）"
            "与 fr/vi/pl 证据只进证据层，一松读者就把元描述当释义。"
            "🔴 **E4 从证据原文重算 hidden，对判据本身写坏是瞎的** ⇒ **E11 钉已知答案**"
            "（`голубь → 鴿子` 必须印、`бочечка` 的 zh 元描述必须藏）。"
            "⭐ **E9 是 R11 的结清**：库里重数「落下的」＋统计里「有意不落的」＝阶段 1 存档，逐个标签。"
            "⭐ **E13 把空白页按成因分四类锁**（全藏／只有指针／只有 fr-vi-pl／源头没有），"
            "「源头没给」与「我们没出版」在结构上分开。🔴 这道闸第一次跑**10 分钟没跑完** ——"
            "`sense_src` 缺 `sense_id` 索引（vi 阶段 9 那一笔的同形），已建进表结构。",
    ),
    dict(
        name="例句闸",
        cmd="python3 -u ru/tests/test_example.py",
        mutate="python3 -u ru/tests/test_example.py --mutate",
        file="ru/tests/test_example.py",
        # `sense`：X5 查例句只挂可出版义项；`dict`：X11 的分母是 is_lemma
        deps=frozenset({"dict", "entry", "sense", "example", "example_gloss"}),
        why="阶段 6a 的 12 条（X1–X12）。⭐ **X3/X4 用收它的那两个函数逐行复核**"
            "（`criteria.example_text_pub`／`example_hidden_why`，33 万行不抽样）；"
            "判据本身写坏时两边一致 ⇒ **X10 钉已知答案**（fr 法语尾巴切掉、zh-s 重切成对、"
            "`...` 删节号不许剥 —— 最后这条是第一版判据自己栽的）。"
            "⭐ **X7 是三语方针在例句层的锁**：fr/vi/pl 的译文一条都不许进 `example_gloss`。"
            "⭐ **X9 锁借来的中文**：`<版>:同句` 必须在同词形下找得到一字不差的出处。"
            "**X8 是读者口径**：同一格里不印两条同一句。",
    ),
    dict(
        name="关系闸",
        cmd="python3 -u ru/tests/test_relation.py",
        mutate="python3 -u ru/tests/test_relation.py --mutate",
        file="ru/tests/test_relation.py",
        # `dict`：R4 解析 target_id；`sense`/`sense_gloss`：R5 与 R10 的义项挂靠
        deps=frozenset({"dict", "entry", "sense", "sense_gloss", "sense_relation"}),
        why="阶段 6b 的 12 条（R1–R12）。⭐ **R4 两个方向锁 target_id**（指错／该解析没解析）；"
            "**R8 两个方向锁 B17**（该藏没藏／藏了却没有更具体的那条 —— 只断言一边，「全藏」也能过）。"
            "⭐ **R9 锁词族分组只有一套键**（源头俄语标签与 wiktextract 英文 tags 归到同一套，ko K8/K10）。"
            "🔴 判据写坏时两边一致 ⇒ **R10 钉已知答案**（`ё → йо` 挂在招呼语义项、`принудить → принуди́ловка`"
            "不许是体对、`полвека` 的残渣标签 ⇒ 分组记空）。",
    ),
    dict(
        name="录音闸",
        cmd="python3 -u ru/tests/test_audio.py",
        mutate="python3 -u ru/tests/test_audio.py --mutate",
        file="ru/tests/test_audio.py",
        deps=frozenset({"dict", "entry", "audio"}),
        why="阶段 6c 的 9 条（A1–A9）。⭐ **这一层的错是「读者点播放听到的不是这个词」**："
            "A3 锁 B12（同一个文件按 Commons 归一键只留一行，vi 实测按 url 去重会漏 31.8%）；"
            "A4/A5 用收它的函数重算张冠李戴，**第二信号来自源头**（同音/异写），`form_of` 有意不算"
            "（`нога ⇐ ноги` 录的是复数）。判据写坏两边一致 ⇒ **A8 钉已知答案**"
            "（`лесть ⇐ лезть` 是源头声明的同音词、必须可播）。",
    ),
    dict(
        name="词源闸",
        cmd="python3 -u ru/tests/test_etymology.py",
        mutate="python3 -u ru/tests/test_etymology.py --mutate",
        file="ru/tests/test_etymology.py",
        deps=frozenset({"dict", "entry", "etymology"}),
        why="阶段 7 的 12 条（Y1–Y12）。⭐ **这一层最大的坑是把占位印成词源**：ru 版 29.6 万段是 `От ??`，"
            "**Y3 用收它的函数逐段复核、Y7 独立地查读者看见什么**（判据写坏时 Y3 与它一致，只有 Y7 拦得住）。"
            "⭐ **Y6 是三语方针的锁**（fr/vi/pl 一段都不许出版）；**Y12 锁字段名两版不同**"
            "（en 单数 `etymology_text`、其余复数 —— 只认单数是 ko K36）。判据写坏两边一致 ⇒ **Y9 钉已知答案**。",
    ),
    dict(
        name="外锚闸",
        cmd="python3 -u ru/tests/test_dump_anchor.py",
        mutate="python3 -u ru/tests/test_dump_anchor.py --mutate",
        file="ru/tests/test_dump_anchor.py",
        # 九层全读 ⇒ 动哪张内容表都脏它（约 20 分钟，七份 dump 各扫九遍）
        deps=frozenset({"dict", "entry", "stress", "inflection", "pronunciation", "sense", "sense_src",
                        "sense_gloss", "sense_tag", "example", "example_gloss", "sense_relation", "audio",
                        "etymology"}),
        why="阶段 8。**九层 vs dump，三向恒等**（源头有库里没有／库里有追不回源头／**键对上而内容不一样**）。"
            "⭐ `[[external-anchor-gates]]`：前面的闸锚的都是库自己，对「收割器整批漏抽」「后来某一步静默 UPDATE」结构性失明；"
            "这一道锚外部 dump ⇒ 永不过期。🔴 **一个判据都不重写**：每层 import 收割器的 `collect()` 本身"
            "（ko 那道同名闸判据写错两次、方向相反，根因都是闸自己重写判据）。"
            "已知的「库里多」只有两类（5b 模型中文＋破例义项／6d 模型中文例句），**断言没有第三类**。"
            "⚠️ 它逮不到「收割器判据本身写错」—— 那是各层「已知答案」与「读者口径」的活。",
    ),
    dict(
        name="回归闸",
        cmd="python3 -u ru/tests/test_no_regression.py",
        mutate="python3 -u ru/tests/test_no_regression.py --mutate",
        file="ru/tests/test_no_regression.py",
        deps=frozenset({"dict", "pronunciation", "sense", "sense_src", "sense_gloss", "example", "example_gloss",
                        "audio", "etymology", "sense_relation", "inflection"}),
        why="阶段 8。**每次写库由 `dbtool._regression_check()` 自动跑**（层闸要手动跑）；锁**非零的已接受基线**、"
            "锁数字不锁名字。⭐ **P5/P8 锁两笔付费数据**（5b 331,639／6d 292,566 条模型中文）——"
            "一次误操作的 `--rebuild` 能静默清掉它们，而层闸只看比例、比例会跟着分母一起掉。"
            "**R0 是读取路径那一半的带锁豁免**：`russian.ts` 一出现而 READ_PATH 还空着就判红（阶段 9 逼人补）。",
    ),
    dict(
        name="展示层契约闸",
        cmd="npm run -s gate:ru-display",
        mutate="npm run -s gate:ru-display -- --mutate",
        file="apps/web/src/contract-check-ru.tsx",
        # 渲染读的是全部内容层 ＋ 展示层源码（源码改动由闸文件哈希/变异台账盯，不在 deps 里）
        deps=frozenset({"dict", "entry", "stress", "inflection", "pronunciation", "sense", "sense_src",
                        "sense_gloss", "sense_tag", "example", "example_gloss", "sense_relation", "audio",
                        "etymology"}),
        why="阶段 9b。**用真服务数据渲染 `RussianEntryView`、断言读者看见什么**（21 条＋11 条变异）。"
            "⭐ 逮到的方式只有一个：把数据渲染出来读 —— 9a 第一次渲染就逮到四个（同形异重音并组／指针目标带重音解析不到／"
            "en 版变格表混着旧正字法与相关词 ⇒ 认不出是名词表／标签漏键）。"
            "🔴 **C11 是全值域标签覆盖**：抽样页只逮到 `emphatic` 一个，全值域一查是 59＋27＋51 个漏映射；"
            "语体标签要么映射、要么在冻结的「有意不印」名单里 —— 新值进来就红，不再 `?? null` 静默丢。"
            "⚠️ 两条检查（C3/C5）第一版写宽了（查整页而不是表/分组标题内），**是变异逮到的**，收窄后当场照出真缺陷。",
    ),
    dict(
        name="查询计划闸",
        cmd="python3 ru/probes/query_plans.py",
        mutate="python3 ru/probes/query_plans.py --mutate",
        file="ru/probes/query_plans.py",
        deps=frozenset({"dict", "entry", "stress", "inflection", "pronunciation", "sense", "sense_src",
                        "sense_gloss", "sense_tag", "example", "example_gloss", "sense_relation", "audio",
                        "etymology"}),
        why="阶段 9c。从 `russian.ts` **原文抠** 17 条查询（抠不到/多出没登记的都红），查走索引、临时 B 树、热态上限。"
            "⭐ 逮到：关系查询在最重的页（`ебать` 5,640 条）上临时 B 树排序 15.6 ms，而那个顺序视图根本不用 ⇒ 改成 ORDER BY id，2.7 ms。"
            "⚠️ `search` 单字母前缀 `п`（15.5 万词形）37.5 ms —— **量过之后有意不做预计算**（上限 50 ms，推翻条件写在闸里）。"
            "ANALYZE 无可测变化（与 vi 同、与 ko 反）。索引侧的变异**跑在副本上**，真库一次都没写。",
    ),
]

# 🔴 **带锁的豁免，不是永久豁免。** 这里登记「追踪名单里有、而还没有闸盯着」的表。
#    判据：**它必须还是 0 行** —— 一有数据落进去，`self_check()` 当场红，
#    逼人去登记一道闸。`[[gate-registers-status-quo-as-spec]]`：
#    闸「如实登记现状」之后就再也不会问现状对不对，所以豁免必须自带失效条件。
UNCLAIMED = {
    t: "阶段 0 刚建出空表，这一层的闸排在它自己的阶段。豁免条件：**还是 0 行**"
    for t in ("etymology_gloss", "field_src")
}


def by_name(name):
    for g in GATES:
        if g["name"] == name:
            return g
    return None


def table_of(key):
    """快照键 → 表名。`#tbl` ＝ 表行数；`tbl.col` ＝ 某表某列；裸列名 ＝ 主表。"""
    k = str(key)
    if k.startswith("#"):
        return k[1:].lower()
    if k.startswith("__"):
        return "dict"
    return (k.split(".", 1)[0] if "." in k else "dict").lower()


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
# 变异台账：**闸的文件变了就欠一次变异**
#
# ⭐ `[[lesson-must-become-mechanism]]`：**变异验证是闸的闸** —— 它不跑，
#   那一串 ✅ 只说明「检查还在」，不说明「检查逮得到东西」。
# 🔴 判据不是「每次写库都跑」（变异动库，代价大，而数据变了不代表判据变了），
#    也不是「每天跑一次」（时间不是判据）。真正让变异失效的事件只有一个：
#    **有人动了那道闸的代码** —— 改断言、改基线、整段替换
#    （vi 2026-10-05 就是这么把两条检查切掉的，正常跑报「全绿」，
#      **只有 `--mutate` 报了出来**）。
# ⇒ 记下每道闸上次跑变异时那个文件的 sha256；对不上就是欠一次。
# ⚠️ 这条判据也认「文件改回去了」：sha 一样就不欠 —— 它锚的是内容不是时间。
def file_sha(g):
    import hashlib
    p = ROOT / g["file"]
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def mutation_log():
    try:
        return json.loads(MUTLOG.read_text(encoding="utf-8"))
    except Exception:                            # noqa: BLE001
        return {}


def record_mutation(name, ok):
    g = by_name(name)
    log = mutation_log()
    log[name] = {"sha": file_sha(g), "ok": bool(ok),
                 "at": datetime.datetime.now().isoformat(timespec="seconds")}
    MUTLOG.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def mutation_debt():
    """→ [(闸名, 原因)]。欠一次变异的那些。"""
    log = mutation_log()
    out = []
    for g in GATES:
        if not g.get("mutate"):
            continue
        rec = log.get(g["name"])
        sha = file_sha(g)
        if rec is None:
            out.append((g["name"], "**从没跑过变异**"))
        elif not rec.get("ok"):
            out.append((g["name"], "上次跑变异是红的（%s）" % rec.get("at", "?")))
        elif rec.get("sha") != sha:
            out.append((g["name"], "闸文件改过了（台账里是 %s，现在是 %s）"
                        % (rec.get("sha"), sha)))
    return out


def run_mutation(name, verbose=True):
    g = by_name(name)
    if g is None or not g.get("mutate"):
        raise SystemExit("🔴 %r 没有变异档" % name)
    if verbose:
        print("\n── %s（变异档）\n   $ %s" % (name, g["mutate"]))
    r = subprocess.run(g["mutate"], shell=True, cwd=str(ROOT))
    ok = r.returncode == 0
    record_mutation(name, ok)
    return ok


# ── 欠账状态 ────────────────────────────────────────────────────────────────
def load():
    try:
        return json.loads(PENDING.read_text(encoding="utf-8"))
    except Exception:                            # noqa: BLE001
        return {}


def _save(obj):
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def mark(names, tag, tables=()):
    cur = load()
    for n in names:
        cur[n] = {"tag": tag, "tables": sorted(str(t) for t in tables),
                  "at": datetime.datetime.now().isoformat(timespec="seconds")}
    _save(cur)


def clear(name):
    cur = load()
    if name in cur:
        del cur[name]
        _save(cur)


def clear_all():
    _save({})


def announce(cur=None, out=None):
    """**说在最后** —— 那是人还在看屏幕的时候。"""
    out = out or sys.stderr
    cur = load() if cur is None else cur
    debt = mutation_debt()
    if not cur and not debt:
        return 0
    if cur:
        print("\n🔴 **以下闸已过期，跑绿为止**（欠账记在 %s）"
              % PENDING.name, file=out)
        for n, info in sorted(cur.items()):
            g = by_name(n)
            print("     · %-12s  因为这次写库动了 %s"
                  % (n, "、".join(info.get("tables") or []) or "?"), file=out)
            if g:
                print("       $ %s" % g["cmd"], file=out)
    if debt:
        print("\n🔴 **以下闸欠一次变异验证**（变异验证是闸的闸）", file=out)
        for n, why in debt:
            g = by_name(n)
            print("     · %-12s %s" % (n, why), file=out)
            if g:
                print("       $ %s" % g["mutate"], file=out)
    return len(cur) + len(debt)


# ── 闸自己的闸 ──────────────────────────────────────────────────────────────
def self_check():
    """→ 问题列表（空 ＝ 通过）。这道自检查的是**名单本身**对不对。"""
    import sqlite3
    bad = []
    # 🔴 **名单不许是空的。** 空名单 ⇒ `dirty()` 恒返回 []、`announce()` 什么都不说
    #    ＝ 一个恒绿的机制。那正是 B23 的形状（分发闸的自检比的两个集合有一边恒为空，
    #    从建成起空过了一整天，**只有变异验证逮得到**）。
    if not GATES:
        bad.append("🔴🔴 闸名单是**空的** —— 这不是「没有闸过期」，是「没有闸」。"
                   "一个恒绿的机制比没有机制更坏（B23）")
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
                        "「%s」）—— **豁免的条件已经不成立，去登记一道闸盯着它**"
                        % (t, format(n, ","), why[:40]))
        finally:
            con.close()
    else:
        bad.append("库不存在，UNCLAIMED 的「还是 0 行」这一条查不了：%s" % paths.DB)

    # ③ 每道闸都得在账的闸的交付物名单里（登记了，被删掉才会有人说话）
    # 🔴 **带锁的豁免**：账的闸是阶段 1 的交付物，现在还不存在。
    #    文件不在 ⇒ 只警告（它真的还没建）；
    #    而**阶段 1 一旦在计划表里标 ✅ 而文件还不在，就判红** ——
    #    那正是 `[[record-the-negative-decision]]` 要的那种触发条件，
    #    不然「等阶段 1 再建」会变成一句永久前提（ja 阶段 6 引用了三次零复核）。
    ledger = ROOT / "ru" / "tests" / "test_plan_ledger.py"
    if not ledger.exists():
        try:
            plan = (ROOT / "docs" / "RU_PLAN.md").read_text("utf-8")
        except OSError:
            plan = ""
        stage1_done = "| 1 |" in plan and "✅" in plan.split("| 1 |", 1)[1].split("\n", 1)[0]
        msg = ("账的闸 `ru/tests/test_plan_ledger.py` **尚未建**（阶段 1 的交付物）—— "
               "现在没有任何东西检查「这道闸被删掉了」")
        if stage1_done:
            bad.append("🔴🔴 " + msg + "，**而阶段表里阶段 1 已标 ✅** ⇒ 豁免条件不成立")
        else:
            print("   ⚠️ " + msg + "。豁免条件：阶段 1 一标 ✅ 就判红。", file=sys.stderr)
    else:
        try:
            sys.path.insert(0, str(ROOT / "ru"))
            from tests.test_plan_ledger import FILES
            listed = {p for items in FILES.values() for _n, p in items}
            for g in GATES:
                if g["file"] not in listed:
                    bad.append("%s（%s）**不在账的闸的交付物名单里** —— "
                               "它被删掉不会有人说话" % (g["name"], g["file"]))
        except Exception as e:                   # noqa: BLE001
            bad.append("读不到 test_plan_ledger.FILES（%s）—— 那本身要查" % e)

    # ④ **登记的变异档 vs 闸文件里真的有没有那条路**（vi 的 W19）
    # 🔴 两个方向都查，而第二个方向才是值钱的那个：
    #    · 登记了 `mutate=` 而文件里没有 `--mutate` 分支 ⇒ 跑它等于跑一遍普通档，
    #      **退出码 0、台账记绿，而一条变异都没跑过** —— 一道「看起来跑过」的空档。
    #    · 文件里有 `--mutate` 而登记表写着 None ⇒ 有变异而没人逼人跑它。
    for g in GATES:
        p = ROOT / g["file"]
        has = p.exists() and "--mutate" in p.read_text(encoding="utf-8", errors="replace")
        if g.get("mutate") and not has:
            bad.append("🔴🔴 %s 登记了 `mutate=%r`，而 `%s` 里**没有 `--mutate` 这条路** ——"
                       "跑它会静默退 0 并把台账记成绿的" % (g["name"], g["mutate"], g["file"]))
        if (not g.get("mutate")) and has:
            bad.append("🔴 %s 的文件里有 `--mutate` 而登记表写着没有变异档 —— "
                       "有变异而没有任何东西逼人跑它" % g["name"])
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
    return ok
