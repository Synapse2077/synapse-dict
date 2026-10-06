#!/usr/bin/env python3
"""**vi 回归闸** —— 过去每一个修复，现在还在不在。2026-10-02（阶段 8）。

`dbtool._regression_check()` **每次写库之后自动调用** `check_brief()`。
⚠️ 它只报不拦（写库已经 commit，回归闸要读最终状态才准），
   但它让回归在**产生它的那次写库**上报出来，而不是十天后偶然撞见。

═══ 它与那十道层闸的分工 ═══
层闸查的是**不变量**（这一列的值域、这两张表对得上），回归闸查的是**修复**：
  ① 它**每次写库自动跑**，层闸要手动跑（`[[lesson-must-become-mechanism]]`：
     ko 的 11 道闸里 3 道从没人跑过、1 道红着一整天）；
  ② 它锁**非零的已接受基线** —— 那是层闸干不了的事（层闸的断言多半是「= 0」）；
  ③ 用户 2026-08-11 的原话：「同一个问题你修了，隔天修其他问题，你又发现之前的问题
     又出现了。」根因是修复写在**输出层**而输出层会被重建 —— es 上已知三次，
     三次全是**事后偶然撞见**的。

═══ 判据一律 import，不重写 ═══
`criteria` / `stage6_sources` / `etym_sources` / `coverage` 里的函数原样拿来用。
🔴 外锚闸今天（同一天）刚栽过这一跤的**更细一层**：判据 import 了，
   而「哪些行才真的落库」我又写了一遍，报 458 条假缺。
   ⇒ 这里凡是 Python 侧的判据，一律 `from ... import`；SQL 侧的，注释里写明它对着哪条修复。

═══ 🔴 基线规矩 ═══
**每条非零都必须在这里带理由，而且「锁数字不锁名字」**（`[[fix-regression-and-gate]]`）：
数字变了就红，哪怕换了一批词。调高任何一个基线都要写清为什么 ——
否则这就成了掩盖回归的开关。

═══ ⚠️ 「写入列 vs 读取路径」现在只有一半 ═══
`[[it-regression-gate]]` 的核心是**在写入列与读取路径各查一次**，两边数字不同就是被绕过。
vi 的展示层（`packages/dict-core/src/vietnamese.ts`）**还不存在** ⇒ 读取路径那一半建不了。
🔴 这不是写在注释里的提醒，是**带锁的豁免**：`R0` 一旦发现那个文件存在而
   `READ_PATH` 还是空的，当场判红。⇒ 阶段 9 一开工它就逼人补。

跑：
    python3 vi/tests/test_no_regression.py
    python3 vi/tests/test_no_regression.py --mutate
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE.parent / "fixes"))

import sqlite3                                                     # noqa: E402

import paths                                                       # noqa: E402
import coverage as COV                                             # noqa: E402
import stage6_sources as S6                                        # noqa: E402
# 🔴 W16 的中文列判据住在填充器里（`_decide`），**这里 import 它不重写** ——
#    第三份实现就是第三种口径，而外锚闸今天刚栽过「闸自己重写判据」那一跤。
import fix_w16_edition_gloss as FIXW16                             # noqa: E402
from criteria import (gloss_has_content, is_han_headword,           # noqa: E402
                      is_vi_markup_gloss, norm_vi, DUP_SENSE_WHY)

F = lambda n: format(n, ",")                                       # noqa: E731
ROOT = paths.ROOT
DISPLAY = ROOT / "packages" / "dict-core" / "src" / "vietnamese.ts"

# ══════════════════════════════════════════════════════════════════════════
# 读取路径那一半。2026-10-03 展示层落地之后补上（在此之前是 **R0 的带锁豁免**，
# 而 `vietnamese.ts` 一出现 R0 就当场判红、逼人写这一段 —— 机制兑现了）。
#
# ═══ 判据：**SQL 从 `vietnamese.ts` 抠真的那一条**，不自己写一套 ═══
# `[[it-regression-gate]]` 的核心是「在写入列与读取路径各查一次，两边数字不同
# 就是修复被绕过」。it 那门最值钱的一条缺陷（词头徽标归属）在**写入侧永远非零、
# 只在读取侧归零** —— 只量一侧看不见它。
#
# ⚠️ 每一条都锁**两个数**：写入列的总量，与展示层 WHERE 之后的量。
#    差额本身是一笔笔有名字的账（W12 的 186／ko 版标签行＋喃字正文 1,326／
#    B17 的 1,460／W8 的 7），**所以差额变了必须有人解释**。
#    光锁展示层那一个数的话，「把 hidden 判据整个关掉」会让它变大而不是变小 ——
#    那种方向的回归只有两个数一起看才逮得到。
# (编号, 名称, 写入列 SQL, 读取路径 SQL（抠自 vietnamese.ts）, 期望差额, 当初怎么坏的)
READ_PATH = [
    ("P1", "义项：写入列 vs 展示层（`s.hidden = 0`）",
     "SELECT COUNT(*) FROM sense",
     "SELECT COUNT(*) FROM sense WHERE hidden = 0", 1820,
     "🔴 **基线 186 → 1,817（2026-10-05，W25）**：折掉 1,631 条「同一个义项被两版各描述了一遍」。成因两种：**跨版重复 1,045 组**（en＋vi 624／en＋zh 388／三版 24／vi＋zh 9）＋**同一版自己重复 207 组**（源头给的是**嵌套释义** —— `glosses[0]` 是共享的父释义、`glosses[1]` 才是具体义项，我们两条都收了 ⇒ 父释义被印了 N 遍）。"
     "差额 186 ＝ W12 判掉的（141 条纯标点 ＋ 45 条源头词典标记缩写）。"
     "🔴 这两个数**必须一起锁**：只锁展示层那个数的话，判据被整个关掉时它会"
     "**变大**，而「变大」看起来像修好了"),

    ("P2", "例句：写入列 vs 展示层（`x.hidden = 0`）",
     "SELECT COUNT(*) FROM example",
     "SELECT COUNT(*) FROM example WHERE hidden = 0", 2057,
     "差额 1,514 ＝ 喃字正文 1,210 ＋ 整条就是词本身 71 ＋ **ko 版韩语标签行 45** ＋ 2 "
     "＋ **6e 清洗的 256**（源头没给越南语 110 ＋ 元数据 103 ＋ 整条只有出处 43）。"
     "🔴 **基线 2,011 → 2,057（2026-10-05，W25 的连带）**：折叠义项之后，两条义项的例句并到了同一格 ⇒ W24 的去重判据跟着生效，**又隐藏 46 条**。⭐ 这不是新缺陷，是 W24 的判据在新的数据上继续起作用 —— 而「折叠会制造新的同格重复」这件事我是从 `--sync` 报的「变成隐藏 46」里看出来的，**没有那一行输出我不会想到去查**。"
     "🔴 **基线 1,582 → 2,011（2026-10-05，W24）**：同一格里跨版重复的例句 **429 条**隐藏。⚠️ 分组键**必须带 `sense_id`** —— 展示层把带义项的例句印在各自义项下、`sense_id IS NULL` 的印在末尾「例句」区，所以按词形分组得到的 1,569 组**不是读者口径**；按读者口径只有 417 组。我第一次报的就是那个大 3.8 倍的数。"
     "🔴🔴 **基线 1,514 → 1,565 是第二次收窄，而那是付费跑批的产物报出来的**："
     "76,028 条译文里 22 条「没有一个汉字」，逐条读下去发现**模型拒绝翻译它们**"
     "（原样返回）—— `Coordinate term: mi` ×27 是关系元数据、"
     "`level tone: y` / `high rising: ý` ×18 是**字母条目的声调范式表**。"
     "⭐ 模型看出那不是句子，而我的判据没看出来。"
     "🔴🔴 那 45 条是 **2026-10-03 把例句渲染出来才看见的** —— 数据层五道闸全绿，"
     "而页面上印着 `같은 말 : yêu thương`（韩语的「同义词」标签）。"
     "同一轮还切掉了 2,381 处内嵌在 `text` 里的韩语译文。"
     "🔴🔴 **基线从 1,326 改成 1,514（2026-10-03）**，加的 188 条是阶段 6e 开跑前"
     "量 `example.text` 本身量出来的 —— 6e 要买的就是把这一列译成中文，"
     "所以开跑前必须先问「这一列里装的真是越南语例句吗」。最狠的是 111 条"
     "**外语原文**（`tử ngữ` 页上一整段《美丽新世界》英文散文、`tìm kiếm` 页上"
     "《小王子》法语原文，还有俄语/文言文/德语/拉丁语）—— 回 dump 核过，"
     "**源头自己就没有越南语正文**，`ref` 承诺的越译本不存在。"
     "⭐ 判据是**两条独立的并集**（符号判据漏掉非拉丁文字，"
     "拿我们自己 `dict` 当词表的音节判据补上），而两条互相逮出了对方的误伤"),

    ("P3", "关系：写入列 vs 展示层（`r.hidden = 0`）",
     "SELECT COUNT(*) FROM sense_relation",
     "SELECT COUNT(*) FROM sense_relation WHERE hidden = 0", 3698,
     "🔴 **基线从 1,460 改成 3,698（2026-10-03），原因必须写明**："
     "新增 2,238 行是 **W9**（目标含非国语字字母 ⇒ 不是越南语词形）。"
     "⚠️ 这不是「修好了 2,238 个」也不是回归，是**判据第一次覆盖到那一类** ——"
     "`[[ledger-numbers-lie]]`：改基线时不写清是哪条口径变了，"
     "下一个人会以为是哪次修复的功劳。原 1,460 全部是 B17，见 R6。"
     "⇒ 两段差额现在由 R6（1,460）与 P9（2,238）**各自单独锁住**，"
     "所以其中一段变了，这里和那一条会同时红，方向分得清。"
     "R6 锁「被隐藏的有多少」，这里锁「展示层少看见多少」—— "
     "`hidden_why` 被改名时 R6 会红而这一条不会，反之改 WHERE 子句时这一条红而 R6 不会"),

    ("P9", "W9：目标不是越南语词形而被隐藏的关系",
     "SELECT COUNT(*) FROM sense_relation",
     "SELECT COUNT(*) FROM sense_relation WHERE hidden_why <> 'target-not-quoc-ngu'"
     " OR hidden_why IS NULL", 2238,
     "🔴🔴 **2026-10-03 阶段 9 把关系渲染出来才看见的**：`nhà` 的「相关」里印着 "
     "`kościół`（波兰语「教堂」）。W9 此前只在**含韩文/假名**的那批里量过（已丢 108 行），"
     "而纯拉丁文本里的同一种污染**一条都抓不到，且我当时没量过它有多少**。"
     "实测 2,238 行，`target_id` 解析得上的 **0 行** —— 全部死链。"
     "逐类读过：en 版**字母条目**的 Unicode 变体（`o` 的 Ø ø Ǿ ɵ ⱺ ᴏ Ｏ Ꜵ）／"
     "**整段词源正文塞进 target**（`đâu. 3 From earlier *C-raː`，正是 W9 描述的形状）／"
     "带汉字表记的整串／ru-de-pl-fr 版的外语词。"
     "⚠️ 判据**不手抄越南语字母表**（`ă â ê ô ơ ư` 与带调元音都在扩展区，手抄必漏，"
     "而漏了就会把越南语自己的词判成外语）⇒ 交给 Unicode：NFD 去组合符后看基字母。"
     "⚠️ 用 `hidden` 不丢（照 B17 先例）：收词哪天把其中一个收进来，一条 UPDATE 就放得出来。",
     ),

    ("P4", "录音：写入列 vs 展示层（`hidden = 0`）",
     "SELECT COUNT(*) FROM audio",
     "SELECT COUNT(*) FROM audio WHERE hidden = 0", 7,
     "差额 7 ＝ W8 的张冠李戴（判据精确度只有 ~57%，3 条是假阳）。"
     "⚠️ 这 7 条**有意不删** —— 展示层永不播一条读错的音，而证据留着（可逆）"),
]

# ── 五条 W 欠账在读取路径上的**规模**。锁住它们是为了「有人用删数据来『修』欠账」
#    时当场红 —— 那不是修，是把问题藏起来。
READ_SCALE = [
    ("P5", "W6：按码位推定的表记（展示层必须标「未经核实」）",
     "SELECT (SELECT COUNT(*) FROM han_spelling WHERE rule_ver='codepoint-v1')"
     " + (SELECT COUNT(*) FROM nom_spelling WHERE rule_ver='codepoint-v1')", 14327,
     "实测这条判据只有 **70.8%** 对，且污染单向全在 han 侧。"
     "展示层据 `VI_SPELLING_RULE[ruleVer].trusted` 决定印不印「汉越字」三个字"),

    ("P6", "W7：按音节拼出来的音标（展示层必须标注）",
     "SELECT COUNT(*) FROM pronunciation WHERE src LIKE 'compose:%'", 96267,
     "阶段 3b 拼的。闸 R13 保证它只填空不覆盖；展示层据 `composed` 加标注。"
     "两条合起来才是完整的 W7：**数据层不许盖，展示层不许冒充**"),

    ("P7", "W10：带 `ref`（出处）的出版例句",
     "SELECT COUNT(*) FROM example WHERE hidden = 0 AND ref IS NOT NULL"
     " AND TRIM(ref) <> ''", 5282,
     "🔴 **基线 5,290 → 5,282（2026-10-05，W25 的连带）**：新隐藏的 46 条里 8 条带出处。"
     "🔴 **基线 5,293 → 5,290（2026-10-05，W24）**：3 组重复例句**两行都带同一条出处**，隐藏一行就少一条。⚠️ 另外 5 组只有一行有出处 —— 那 5 组一条都没少：「有出处的优先留」是 `dup_survivor_rank` 的第③条（决定 4 组），剩下 1 组被①②盖过、由**出处并到留下来那行**兜住。⭐ 这个 −3 是**能逐位对上的**，而「对得上」正是我敢改基线的唯一理由。"
     "vi 版 709 条 `translation` 里一条真译文都没有 ⇒ 那批进了 `ref`。"
     "展示层印成「出处：…」，**不许排在译文位置**。"
     "🔴 **基线从 6,005 改成 5,088（2026-10-03），原因**：展示层契约闸逮到 `ăn` 页面上"
     "印着「出处：창세기 2장 9절」（创世记 2 章 9 节）—— 切掉内嵌外语那一步我只用在 "
     "`text` 上、**`ref` 漏了**（判据漏用）。新增判据 `S6.ref_is_unreadable()`："
     "**一个拉丁字母都没有 ⇒ 对中文读者不可读 ⇒ 不发布**，去掉 917 条"
     "（韩语版圣经章节号 682 ＋ vi 版整串是 `.` 的 225 ＋ 其余 10）。"
     "⚠️ 判据**不是「含韩文就切」** —— 那会截断 56 条以拉丁为主、夹着原文人名的"
     "正当引文（`2021, Han Kang, …`），而**一条截断的引文比一条读不懂的更坏**。"
     "🔴 **基线从 5,088 再改成 5,191（同日第二次）**，算式必须对得上："
     "5,088 ＋ **202**（出处串在 `text` 首行而 `ref` 是空的 ⇒ 搬过去；"
     "《庄子》《论语》《西游记》的引文头、俳句的作者行）− **99**"
     "（新隐藏那 188 条里原本带 `ref` 的）＝ 5,191。"
     "⚠️ 三次改基线都不是「调松」：搬进来的是本该印出来的出处，减掉的是跟着整条一起下架的。"
     "🔴 **第三次 5,191 → 5,228（＋37）**：`_CITATION` 判据第二次收窄 —— "
     "第一版只认 `English/Vietnamese translation` / `, transl.` / `; quoted in`，"
     "而 `free 2003 translation by` 不含 `English`、`1932: Lệ Xuân, …` 一个关键词都没有。"
     "⇒ 改成认**出处的本质特征：以年份/世纪开头**。"
     "🔴🔴 **第四次 5,228 → 5,293（＋65），而这一次是分支写错了不是漏关键词。**"
     "`thối` 的例句原文 4 行译文 3 行，首行是 `1939: Ngô Tất Tố, Lều chõng` ——"
     "一条**用越南语写的出处**。漏掉它的原因是「越南语音节率 < 0.6」那道门，"
     "**而越南语写的出处音节率是 1.00**。那道门对关键词支是对的（防正文里引到"
     "`English translation`），对年份支**正好是反的**。"
     "⇒ 判据按**分支**写、不共用安全网；年份支换成结构信号（不以句末标点结尾"
     "／≥2 逗号／带引号书名）。实测多出 82 条（多行首行 65 ＋ 整条是出处 17），逐条读过全对。"
     "⭐ 同一条判据**一天之内收窄四次**，而逮到它的分别是：契约闸、付费跑批的产物、"
     "以及一条**本来空过的**契约检查（八个样本词里一条多行例句都没有）"),

    # 🔴 **2026-10-03 阶段 6e 开跑前的清洗。** 这一条是基线型（锁条数），
    #    另两条（P12/P13）是**残留型**，在 `py_checks` 里 —— 理由见那里。
    #      这个数变小 ＝ 隐藏判据被改窄（外语原文又回到页面上）
    #      这个数变大 ＝ 判据被改宽（咬到真例句，`Xa-tan` 那条差一点就是）
    ("P11", "6e 清洗：源头没给越南语正文而隐藏的例句",
     "SELECT COUNT(*) FROM example WHERE hidden_why='source-has-no-vietnamese'", 110,
     "`tử ngữ` 页上一整段《美丽新世界》的**英文**散文、`tìm kiếm` 页上《小王子》的"
     "**法语**原文，还有俄语/文言文/德语/拉丁语（《使徒信经》×3）。"
     "回 dump 核过：**源头自己就没有越南语正文**，`bold_text_offsets` 指向英文。"
     "⚠️ 这不是我们漏抽，是源头缺 ⇒ 隐藏并写明原因，**证据层一行不动**"),

    # ⭐⭐ **阶段 6e 的产物（付了钱的）必须有人盯着。**
    #    `[[answer-file-is-the-ledger]]` 的另一面：答案文件还在，但**库里的行会被
    #    后面某一步静默删掉**（`build_example_layer.py --rebuild` 就能删掉它们，
    #    所以那个开关里有一道「`example_gloss` 有 `model%` 行就拒绝重建」的保险）。
    #    ⚠️ 锁**两个数**：模型译文的总量，以及读者口径的覆盖率分子 ——
    #      只锁总量的话，「译文还在但挂到隐藏例句上了」不会变红。
    ("P14", "6e：花钱买来的例句中文译文（总量）",
     "SELECT COUNT(*) FROM example_gloss WHERE lang='zh' AND src LIKE 'model%'", 75524,
     "🔴 **基线 75,547 → 75,524（2026-10-05，W25 的连带）**：新隐藏的 46 条里 23 条带付费中文。⚠️ 这一批我是**删完之后才补验**答案文件的（上一批 407 条是删之前验的）—— 流程上退了一步。✅ 补验的结果更强：**库里 75,524 条付费中文的 id 全部（100%%）在答案文件里**，这是一条不变量而不只是一次抽查 ⇒ 已做成闸 **P25**。"
     "🔴🔴 **基线 75,954 → 75,547（2026-10-05，W24）：这是一次有意删除付费数据。**隐藏 429 条重复例句 ⇒ 闸 X8（隐藏的不许带译文）要求删掉它们的译文，其中 **407 条是买的**。⚠️ 敢删的三条理由，**缺一条都不该删**：①417 个重复组的**每一行都有中文**，所以留下来那行一定有一条有效译文；②删掉的是**同一句话的另一种措辞**（197 组措辞完全相同，220 组措辞不同而逐条读过都成立）；③**删之前逐条验过答案文件 `all.jsonl` 里 407/407 都在**（`[[answer-file-is-the-ledger]]`）—— 不是「应该在」，是查过。"
     "2026-10-03 实跑：6,337 批 ＋ 补跑 10 批，**失败 0**，7,712,853 ＋ 11,006 token，"
     "空闲半价 ≈ 19–21 元。单价 **101.4 token/条**（1% 切片预估 99.1，误差 2.3%）。"
     "⚠️ 补跑那 40 条是**必须的**：35 条因为判据再收窄一轮而 `text` 变了"
     "（旧译文把出处也译进去了），5 条是 temperature=0 下模型确定性漏掉的。"
     "🔴 回收时 `load(['redo-redo_ids', 'all'])` **顺序即优先级** —— "
     "`all.jsonl` 里那 35 条旧译文一旦先落地，新的就永远进不来（本函数幂等）"),

    ("P15", "6e：例句中文的**读者口径**覆盖（分子）",
     "SELECT COUNT(DISTINCT g.example_id) FROM example_gloss g "
     "JOIN example e ON e.id=g.example_id WHERE e.hidden=0 AND g.lang='zh'", 76167,
     "🔴 **基线 76,213 → 76,167（2026-10-05，W25 的连带）**：−46。读者口径覆盖率 **76,167 / 76,178 仍是 99.99%%**。"
     "🔴 **基线 76,642 → 76,213（2026-10-05，W24）**：−429，与隐藏的重复例句数相等。读者口径覆盖率 **76,213 / 76,224 仍是 99.99%** —— 分子分母一起降，⭐ 而「覆盖率没动」正是去重**没有伤到读者**的证据。"
     "76,642 / 76,653 ＝ **99.99%**（跑之前是 0.90%，而那 0.90% 是中文版白送的 688 条）。"
     "差的 12 条逐条读过：3 条是 **fr 版漏进来的 JavaScript 代码**"
     "（`',\\'vietphap\\',\\'on\\')\"morale`）、4 条不是例句、"
     "5 条本来就没什么可译的（`Ú, liu, cống, xê, xang, xừ.` 是越南传统音名、"
     "`Win XP`、`Lôm lốp` 叠音形式）。📋 那 3 条 JS 残渣记在 **W20**。"
     "⚠️ 这一条与 P14 **必须一起锁**：只锁总量的话，"
     "「译文还在但挂到隐藏例句上了」不会变红（而那正是 X8 要治的）"),

    # 🔴🔴 **6e 的残留账，数字和读法一起锁。**
    #    625 条多行例句里 17 条「译文行数 ≠ 原文行数」。逐条读完是**三类混在一起**，
    #    而只看总数这三类都看不见（`[[residual-bucket-is-not-evidence]]`）：
    #      ① **行数少是对的**：`Bàn Cổ` 的原文两行是「汉越音转写」＋「同一句的越南语」，
    #         模型给出汉文原文 `史臣吳士連曰：天地開肇之時…` 一行，正是读者要的那句
    #      ② **真的丢了内容**：`uất hận` 9 行→8 行，而丢掉的那一行**正含词头**
    #      ③ **我的清洗判据还漏**：`cò` 的首行是**不以年份开头的出处**
    #         （`Tú Xương, "Ông Cò (Mister Superintendent…)"`）、末行是**带越南语人名
    #         的英译**（`Hà Nam's most honoured person…` 里 `Hà` 带声调符
    #         ⇒ 我的「这一行一个越南语标记都没有」判据放过了它）
    #    ⚠️ **重译一轮不收敛**：17 条里 14 条仍然对不上，有几条更糟 ——
    #      `[[retry-must-converge-or-drop-loud]]`：不跑第三轮，大声记账。
    #      答案文件 `redo3.jsonl` 留着当证据，**没有入库**。
    #    ⇒ 根因在**数据层**：这 17 条的 `text` 不是「N 行平行的越南语」，
    #      而是出处/喃字/汉越音转写/英译混在不同的行上，模型建不起行对应。
    #      📋 欠账 **W21**：补两条判据（不以年份开头的出处；带越南语专名的英译行）。
    #    🔴 这个数**只许往下走**。它往上走意味着新的付费译文又开始丢行。
    ("P16", "6e 残留：多行例句里译文行数对不上的（**锁上限**）",
     "SELECT COUNT(*) FROM (SELECT e.id FROM example e "
     " JOIN example_gloss g ON g.example_id=e.id AND g.lang='zh' AND g.src LIKE 'model%' "
     " WHERE e.hidden=0 AND instr(e.text, char(10))>0 "
     "   AND LENGTH(e.text)-LENGTH(REPLACE(e.text, char(10), '')) "
     "    <> LENGTH(g.text)-LENGTH(REPLACE(g.text, char(10), '')))", 17,
     "见上面那段注释：三类混在一起，而只看总数三类都看不见。"
     "⭐ 逮到它的是一条**本来空过的**契约检查 —— 「多行例句的译文行数与原文一致」"
     "原先挂在 `mai` 上，而六个样本词**一条多行例句都没有** ⇒ `bad.length===0` 是"
     "白捡的、它永远绿。给样本词表加了 `thối` 之后它当场判红。"
     "⇒ ⭐ **样本词表不只是「好看的词」，它决定哪些代码路径被走到**"),

    ("P10", "B18：词源号与义项组对不上的词形（展示层必须单独成区印）",
     "SELECT COUNT(*) FROM (SELECT e.word_id FROM etymology e WHERE EXISTS"
     " (SELECT 1 FROM sense s WHERE s.word_id=e.word_id AND s.hidden=0)"
     " AND NOT EXISTS (SELECT 1 FROM sense s JOIN entry en ON en.id=s.entry_id"
     "   WHERE s.word_id=e.word_id AND s.hidden=0"
     "     AND CAST(en.etym_no AS INTEGER)=CAST(e.etym_no AS INTEGER))"
     " GROUP BY e.word_id)", 407,
     "🔴🔴 **B18 的形状在 vi 的视图里换个条件复发了**，而它是量出来的：词源只在"
     "「某个义项组的 `etymNo` 对得上」时才印 ⇒ 这 407 个词形（有词源的 1.6%）"
     "一个字都印不出来（`biên phòng` 就是其中之一）。"
     "两种成因：56 个的全部可出版义项挂不上词条（9,116 条义项 `entry_id` 为 NULL）；"
     "351 个挂上了词条但词源号对不上。"
     "⚠️ **这个数是数据侧的事实，不会因为展示层修好而变** —— 锁它是为了「哪天它涨了"
     "要有人知道」；展示层那一半由契约闸的 `biên phòng` 那条盯着。"
     "⚠️ 修法是**在义项之后单独成区**，不是「体面兜底」：它印的是库里真实存在、"
     "源头给的内容，而体面兜底是拿别的东西填缺口。"),

    ("P8", "W15：只有指针、没有任何可出版义项的词形",
     "SELECT COUNT(DISTINCT ss.word_id) FROM sense_src ss WHERE ss.sense_id IS NULL"
     " AND NOT EXISTS (SELECT 1 FROM sense s WHERE s.word_id = ss.word_id"
     "                  AND s.hidden = 0)", 16305,
     "🔴🔴 **16,305 个词形（24.5%）唯一的释义信息是一条指针** ——"
     "`UBND` = Ủy ban Nhân dân／`Tobago` → alternative form of Tô-ba-gô。"
     "比 W15 原先记的 222（空白页）大 73 倍：那 222 是**连音标都没有**的，"
     "而这 16,305 有音标、所以不算空白页，**读者却一样看不到意思**。"
     "⇒ 展示层在 `senses.length === 0` 时印 `pointers`"),
]

# ══════════════════════════════════════════════════════════════════════════
# SQL 侧的检查：(编号, 名称, SQL, 期望值, 当初是怎么坏的)
SQL_CHECKS = [
    # ── 阶段 6 的两个修复 ───────────────────────────────────────────────
    ("R5", "B12：同一 (词形, Commons 键) 没有两行",
     "SELECT COUNT(*) FROM (SELECT 1 FROM audio "
     "GROUP BY word_id, commons_key HAVING COUNT(*)>1)", 0,
     "schema 的 `UNIQUE(word_id,url)` **挡不住它** —— 同一个 Commons 文件在各版里"
     "有不同的 url（各维基内嵌转码后的 mp3）⇒ 按 url 只能并到 4,560，"
     "**1,450 行（31.8%）重复会落库**，页面上两个按钮播同一个文件。"
     "这一条不是 DDL 保证的，是 `S6.commons_key()` 保证的"),

    ("R6", "B17：兜底 related 的隐藏量还在**正确判据**的量级上",
     "SELECT COUNT(*) FROM sense_relation WHERE hidden_why='redundant-related'", 1460,
     "🔴 **已接受基线 1,460，而它是判据选择的产物不是数据的产物。**"
     "naive 判据（related 撞上**任何**别的 kind）命中 14,547 对、正确判据"
     "（撞上**语义**更具体的 kind）只有 1,317 对 —— **差 11 倍**，差的全是 "
     "`paronym+related`，而 paronym 是**语音**关系、不蕴含语义相关。"
     "⭐ 锁成具体数字正是为了「判据被改宽」会当场红：改回 naive 这个数会跳到一万以上。"
     "⚠️ 哪天 `S6.SUBSUME` 有理由变，**改基线时要同时写明是哪条 kind 进出了**"),

    ("R7", "vi 版例句的「出处」没有被当成译文收进来",
     "SELECT COUNT(*) FROM example_gloss g JOIN example e ON e.id=g.example_id "
     "WHERE g.lang='vi' AND e.hidden=0", 0,
     "vi 版 709 条 `example.translation` 里**一条真译文都没有**："
     "214 条整串是 `.`，290 条是 `(tục ngữ)`/作者名。照字段名收 ⇒ 读者看见「译文：.」。"
     "修法是 `S6.TR_LANG['vi-edition'] = None` ＋ 那批进 `example.ref`"),

    # ── 阶段 7 的两个修复 ───────────────────────────────────────────────
    ("R9", "词源正文里没有内嵌的 wiki 魔术字",
     "SELECT COUNT(*) FROM etymology WHERE text GLOB '*__[A-Z]*__*'", 0,
     "**5,390 段内嵌 `__NOEDITSECTION__`**（vi 版可出版段的 64.7%）。"
     "⭐ 它是 `dbtool.sample_check` 的抽样反验逮到的，**形状检查看不见** ——"
     "因为那一段**该收，只是脏**。修法：`ES.etym_skip_why` 改成**先清洗再判断**，"
     "入库存 `ES.clean_etym_text()` 的结果"),

    ("R10", "`etym_type` 只落在 **en 版建的** entry 上",
     "SELECT COUNT(*) FROM entry WHERE etym_type IS NOT NULL AND src<>'en-edition'", 0,
     "第一版写的是 `ent[(w,no)]`（**所有版**的 entry），于是 3 行落到 vi/zh 版建的 "
     "entry 上。`etymology_templates` 这个信号**只有 en 版有**，而"
     "「同一个 (词, 词源号)」在不同版里**不保证是同一个词源**（词源号都从 0 起编）。"
     "⭐ 骨架闸 S13 逮到的 —— 而 S13 原来的断言是「阶段 1 一列都不填」，"
     "**那条已经过期**，retarget 成这条之后才继续有信号"),

    # ── 阶段 3 的两个修复 ───────────────────────────────────────────────
    ("R12", "西贡音没有消失（它藏在 `note` 里，不在 `tags` 里）",
     "SELECT COUNT(*) FROM pronunciation WHERE dialect='sai-gon'", 86535,
     "🔴 **已接受基线 86,535。** 只读 `sounds[].tags` 的话西贡音整批拿不到 ——"
     "源头把它写在 `note` 字段里。P8 把这次栽跤做成了闸。"
     "⚠️ 这个数会随收词变（新词带音标就涨）⇒ **它涨了也要红**，"
     "红的时候回来确认是收词而不是判据被改宽，然后改基线并写明"),

    ("R13", "拼出来的音标没有盖在已有源头音标的词上",
     "SELECT COUNT(*) FROM (SELECT word_id FROM pronunciation GROUP BY word_id "
     "HAVING SUM(src LIKE 'compose:%')>0 AND SUM(src NOT LIKE 'compose:%')>0)", 0,
     "阶段 3b 按音节拼了 96,267 行音标。拼的东西**只许填空，不许覆盖** ——"
     "否则读者看到的是我们算的而不是源头写的，而两者分不开（欠账 W7 就是这件事的展示层那一半）"),

    # ── 阶段 5 的两个修复 ───────────────────────────────────────────────
    ("R15", "没有「可出版却没有中文释义」的义项（5b 的落点）",
     "SELECT COUNT(*) FROM sense s WHERE s.hidden=0 AND NOT EXISTS "
     "(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')", 0,
     "5b 花 22.8 元把 92,797 条释义译成中文，**中文覆盖词形 10.6% → 75.48%**。"
     "⚠️ 这条是 `= 0` 而不是覆盖率下限：覆盖率受收词稀释，而"
     "「可出版却没中文」是**结构性**的 —— 新收的词只要进了出版层就必须有中文"),

    ("R16", "指针义项还在证据层（E7：证据永不编辑）",
     "SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL", 33361,
     "🔴 **已接受基线 33,361。** W5：vi 版把指针写成 gloss 正文（`Xem X`／`Như X`）"
     "2,854 条、en 版 `Alternative form of X` 2,573 条 —— 只用结构字段判 ⇒ "
     "vi 独有报 99.2% 而真值 92.1%。它们走独立路径进证据层、不进出版层。"
     "⚠️ 这个数**掉下去**才是灾难（证据被删了）；涨是收词的正常结果 ⇒ 改基线时写明"),

    # ── 有意不建的三张表（阶段 0 的决定）────────────────────────────────
    ("R17", "有意不建的三张表没有偷偷长出来",
     "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
     "('inflection','pronunciation_entry','collocation')", 0,
     "越南语**零屈折** ⇒ `inflection` 不建（ko 那门这张表 114 万行）。"
     "⚠️ 它和「表是空的」不是一回事：空表会让「有意不建」在三个月后被人当成"
     "「还没做」而去填（`[[gate-registers-status-quo-as-spec]]`）"),
]


# ══════════════════════════════════════════════════════════════════════════
# Python 侧的检查：判据是函数，**一律 import**
def py_checks(con):
    """→ [(编号, 名称, 实测, 期望, 当初是怎么坏的)]"""
    out = []

    # R1 空白页：**两个数**，总数是基线、「源头也没给」必须是 0
    total, src_empty, ours = COV.blank_split(con)
    out.append(("R1", "🔴 空白页总数（读者口径：点进去什么都没有）", total, 0,
                "🔴🔴 **基线从 222 改成 0（2026-10-05），而改的是判据不是数据** ——"
                "`coverage.py` 的九条判据写在**展示层之前**（2026-10-02 建回归闸时定的，"
                "那时 `VietnameseEntryView` 还不存在），**不含「有可印的指针」**。"
                "而阶段 9a 之后视图在「没有可出版义项」时就印指针区 ⇒ "
                "**那 222 个从 9a 起就不是空白页了，是这张判据没跟上**。"
                "实测 222 个里 **222 个指针区都印得出东西**，其中 160 个本轮变成可点跳转。"
                "⚠️ `coverage.py` 自己写着「每加一条判据这个数都会降，那不是修好了是口径变了」——"
                "**这一次两样都有**：判据跟上了展示层（口径），而指针从不可点变成可点（修复）。"
                "⭐ 分辨方法只有一个：**去看读者那一页上有没有东西**。"
                "🔴 它现在是 0 ⇒ 任何一条新的空白页都会当场判红"))
    out.append(("R1b", "🔴 其中「源头也没给」的", src_empty, 0,
                "`[[dont-say-source-lacks-what-we-skipped]]`：「源头没写」和"
                "「我们没抽」**必须在结构上分开**。只报一个总数的话，"
                "「我们没印」会被当成「源头没有」—— 而那是会写进验收报告的谎。"
                "⚠️ **R1 归零之后这一条数学上必然是 0**（它是 R1 的子集）"
                "⇒ 它现在的作用只剩「分母没被悄悄换掉」。真正接着看这件事的是 R1c/R1d"))

    # 🔴🔴 **W15 的两个数一起锁** —— 只锁一个逮不到判据被改坏。
    #    `pointer` 变小 ＝ 指针区印得少了（读者又看不到源头说的话）
    #    `spelling` 变小 ＝ 「只是汉字表记」又被当成指针印出来了（79.7% 那个错标复发）
    n_ptr = con.execute("SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL "
                        "AND ptr_class='pointer'").fetchone()[0]
    n_sp = con.execute("SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL "
                       "AND ptr_class='spelling'").fetchone()[0]
    n_oth = con.execute("SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL "
                        "AND ptr_class='other'").fetchone()[0]
    out.append(("R1c", "W15：指针区**会印出来**的行（真指针）", n_ptr, 7238,
                "判据 `criteria.pointer_class()`，**五轮收窄**才到位。"
                "🔴🔴 第五轮逮到的是**语序假设错了**：前四轮一直在「关系词在前」那个方向加词"
                "（`alternative spelling of X` / `Dạng viết tắt của X`），"
                "而中文版是**目标在前、关系词在后**（`Mĩ的另一種拼寫法`、`ti vi 之首字母縮略詞`）"
                "—— 加词永远到不了，必须单开一支。"
                "⭐ 这不是「判据比它要描述的东西窄」的常见形状（词表不全），是**语序假设错了**"))
    out.append(("R1d", "🔴 W15：被判成「只是这个词的汉字表记」因此**不印**的行", n_sp, 26086,
                "🔴🔴 **这个数就是 W15 的真缺陷有多大**：读者在「这个词形指向」标题下"
                "看到的行里 **79.7% 整段只是这个词自己的汉字表记**（`nhất vị` → `一味`），"
                "而同一页**上方已经有「汉字表记」区**印着同一串字。"
                "⭐ 这是 **W2 的病在第三个地方复发**："
                "W2 ＝ 义项释义（69.2% 只是表记）／Y5 ＝ 词源正文（26,230 段里 21,239 段）／"
                "这里 ＝ 指针区（79.7%）—— 同一句话：**「这个词的汉字写法」被当成了"
                "「这个词的意思／来源／指向」**。判据 `gloss_is_just_spelling` 阶段 5a 就写好了，"
                "**只是展示层没用它**。🔴 这个数变小 ＝ 那个错标又回来了"))
    out.append(("R1e", "W15：`pointer_class` 判不出来的残差（**锁上限**）", n_oth, 37,
                "逐条点名写在 `criteria.py` 的 `_PTR_VI_LONG` 下方（6 种形状）。"
                "其中 1 条是 `:Template:vi-rdp of` —— **wikitext 模板残渣**，记在 W18 那一族。"
                "⚠️ **反向控制五轮一直是 0**（没有一条「只是表记」被指针判据抢走）——"
                "精度比召回重要：把表记错标成「指向」是读者看得见的错，"
                "漏标一条指针只是少一个链接（它仍然照原文印出来，一个字不丢）"))

    # ── 🔴🔴 **6e 开跑前清洗的两条「残留必须是 0」** ──
    #    ⚠️ 我第一版把它们写成 READ_SCALE 里的 SQL 基线，而**两个期望值都是推的**：
    #      P12 写 160 而实测 648 —— 我那条 SQL 圈的是「`ref` 含 translation 的全部例句」，
    #      库里本来就有 648 条，**根本圈不住我改的那 202 条**。
    #      `[[expectation-must-be-declared]]`：期望值要独立声明，
    #      而「独立声明」的前提是**我得真的知道这个数是什么的数**。
    #    ⇒ 改成**残留型**：把判据再跑一遍，还能命中的必须是 0。
    #      残留型比基线型强两点：① 期望值天然是 0，不用我去推；
    #      ② 它与判据**调同一个函数**，判据被删掉它当场变红
    #         （基线型则库和判据一起变、照样绿 —— 外锚闸的同一个盲点）。
    #
    # 🔴🔴🔴 **2026-10-05：这两条被我自己删掉过一次，而只有变异验证报了出来。**
    #    改 R1 的基线时我用 `s[:i] + new + s[j:]` 换掉一整段，而 P12/P13 正夹在
    #    R1b 和 R2 之间 ⇒ 一起被切走。**正常跑是「全绿」**（它们不在输出里，
    #    而没人数过输出该有几条），是 `--mutate` 报「🔴 没逮到 P12」才露出来的。
    #    ⇒ ⭐ **变异验证是闸的闸**（ko 的 K31 同一课）；
    #      ⇒ 并且这一次逼出了 `ROSTER` —— 见文件末尾 `run_all` 的花名册自检。
    syl = S6.vi_syllables(con)
    _ex = list(con.execute("SELECT id, text, ref, src FROM example WHERE hidden = 0"))
    left_cite = sum(1 for _i, t, r, _s in _ex
                    if not (r or "").strip() and S6.split_citation_prefix(t, syl)[0])
    out.append(("P12", "6e 清洗：出版正文里不许还有「首行是出处」的（残留）", left_cite, 0,
                "304 条出处串在 `text` 首行而 `ref` 是空的 —— 《庄子》《论语》"
                "《西游记》的引文头、俳句的作者行、年份开头的文献行。"
                "判据**按分支写**：关键词支（`English translation by`）要再满足"
                "「越南语音节率 < 0.6」，年份支（`1939: Ngô Tất Tố, Lều chõng`）"
                "**不许用音节率当安全网** —— 越南语写的出处音节率是 1.00。"
                "⚠️ 它直接关系到钱：6e 按 `text` 的字数付费，出处留在里面就是花钱翻出处"))
    # 🔴 **顺序必须与收割器一致**：先切出处首行，再找英译行。
    #    流水线里就是这个顺序（`collect()`），而我第一版在**原始 `text`** 上找英译 ——
    #    出处行本身就是英文（`Analects, 7.34; 1861 English translation by James Legge`）
    #    ⇒ P12 的变异一注入 P13 就跟着响。**不是连带，是我两处判据不同序。**
    left_en = sum(1 for _i, t, _r, sc in _ex
                  if sc in S6.INLINE_EN_IN_TEXT
                  and S6.split_inline_english(S6.split_citation_prefix(t, syl)[1])[1])
    out.append(("P13", "6e 清洗：出版正文里不许还有内嵌英译行（残留）", left_en, 0,
                "355 行英译夹在 `text` 里，**262 条库里原本没有英译** ⇒ 剥掉就丢数据，"
                "动作是搬进 `example_gloss(en)`。"
                "🔴 其中 17 条是**接在已有英译前面**：源头把英译的末行单独放进 "
                "`english` 字段、前面几行留在 `text`，拼回去才完整。"
                "🔴 而 `INLINE_EN_IN_TEXT` 这张**按版登记表**也是栽出来的："
                "没有它的时候 nl 版 2 行**荷兰语**被判成英译、存成 `lang='en'` ——"
                "**绕过了三语闸 X9**（X9 查 lang 不在三语里，而荷兰语被贴了 `en` 的标签）"))

    # ── 🔴🔴 **W16：出版正文（`text_pub`）—— 四条，两种类型各两条** ──
    # 🔴🔴🔴 **P17 是读者口径里最硬的一条**：`vietnamese.ts` 的例句查询 SELECT 的是
    #    `x.text_pub`，而那一列是派生列。重建／新收割路径忘了填它 ⇒ **页面上例句全空**。
    #    而展示层**有意不写 `COALESCE(text_pub, text)`** —— 写了兜底这件事就永远
    #    发现不了（`[[it-display-layer-stage8]]`：兜底越体面缺陷越难发现）。
    #    ⇒ 兜底不在代码里，就必须在闸里。这一条就是那个替代品。
    n_null = con.execute("SELECT COUNT(*) FROM example "
                         "WHERE hidden=0 AND text_pub IS NULL").fetchone()[0]
    out.append(("P17", "🔴 W16：可出版例句的**出版正文**不许为空（展示层 SELECT 的就是它）",
                n_null, 0,
                "`vietnamese.ts` 读 `x.text_pub AS text`，**没有 COALESCE 兜底**。"
                "这一列是 `S6.split_edition_gloss()` 的派生产物，由 `collect()` 填 ——"
                "哪天新开一条写入路径忘了它，页面上例句会**整片消失**，"
                "而数据层别的闸全都看不见（`text` 一个字没少）。"
                "⚠️ 这是**读者口径**那条规矩的字面执行：闸至少要有一条查展示层真正 SELECT 的列"))
    # 残留型：判据再跑一遍，库里的 `text_pub` 必须与它一致。
    # ⭐ 比「数一数切了几条」强在哪：它与收割器**调同一个函数**，
    #   判据被删掉／改坏，这条当场变红（基线型则库和判据一起变、照样绿）。
    _w16 = list(con.execute("SELECT e.id, d.word, e.text, e.text_pub, e.src "
                            "FROM example e JOIN dict d ON d.id=e.word_id"))
    mismatch = 0
    for _i, w, t, pub, sc in _w16:
        want = S6.split_edition_gloss(t, w, sc, syl)[0]
        if (pub or "") != want:
            mismatch += 1
    out.append(("P18", "W16：`text_pub` 与判据重算的结果逐行相等（残留）", mismatch, 0,
                "判据住在 `stage6_sources.split_edition_gloss()`，**本条 import 它**，"
                "不自己重写（ko 的外锚闸正是栽在「闸自己重写收割器的判据」上）。"
                "🔴 它逮的是两种事：① 判据改了而库没同步（`--sync` 没跑）"
                "② 库被别的路径改过而判据不知道。两种都会让页面与证据层漂开"))
    n_cut = con.execute("SELECT COUNT(*) FROM example "
                        "WHERE hidden=0 AND text_pub <> text").fetchone()[0]
    out.append(("P19", "W16：出版正文摘掉了本版释义尾巴的行", n_cut, 52,
                "fr 版 44 ／ en 版 6 ／ nl 版 2。fr 版维基词典本身是一部**越→法双语词典**，"
                "它的例句一格里装着「越南语搭配 : 法语释义」(`Nắng to : il fait grand soleil.`)"
                "—— 法语是**那一版的释义语言**，不是越南语里的法语借词"
                "（真的法语借词在**词源层**，1,115 个词形，早就收齐了）。"
                "🔴 两条**结构**安全网各拦下 1 条，别的 52 条一条没动："
                "ⓐ 尾巴整段是越南语音节（`Một cái biển có ghi : \" Nhà cho thuê \"`"
                "——招牌上写着「房屋出租」，是引文不是释义）"
                "ⓑ 切完头部括号不配对（`Mò mò (redoublement : sens plus fort).`"
                "——冒号在括号里，切了剩 `Mò mò (redoublement`，"
                "**而它看起来是完整的**，与阶段 9b 那条「截断的引文比读不懂的更坏」同形）。"
                "🔴🔴 第一版的安全网是「尾巴越南语音节率 < 0.34 且无越南语标记」，"
                "它把 **26 条法语尾巴判成「尾巴也是越南语」**（`Vải to : toile grossière.`"
                "的 `è` 被算成声调符、`Để tang : prendre le deuil` 的 `le`/`de` 在音节表里）"
                "—— **法语与越南语共用组合变音符本身**，比荷兰语那一课更狠"),)
    # 🔴 中文列的残留：W16 切过的行里，中文译文**不许再带分隔符后的那一段**。
    #    判据 import 自那个填充器 —— 第三份实现就是第三种口径。
    left_zh = sum(1 for row in FIXW16.plan(con)
                  if FIXW16._decide(row[5])[0] is not None)
    out.append(("P20", "W16：切过的行里，中文译文不许还粘着本版释义（残留）", left_zh, 0,
                "6e 是**按整格**买的译文，所以同一批行的中文里跟着译出了法语尾巴，四种结果："
                "①两半都译⇒**中文说两遍** 30（`大官：大人物，大人物。`）"
                "②尾巴没译⇒**法语漏进中文列** 7（`网球：balle de tennis。`）"
                "🔴③头没译⇒**越南语漏进中文列** 5（`Ang nước：水罐。`，方向反过来更坏）"
                "④模型自己丢了尾巴（对的）10。"
                "⭐ **修法是免费的**：要的那半就在译文里，确定性切分比重问模型可靠"
                "（W21 那 17 条刚证明重译可能**不收敛**）。"
                "🔴 而切中文时我把安全网漏掉了一个方向：`brackets_balanced` 的括号表里"
                "**只有半角括号**，于是 `轻飘飘――失重（字面意思：“非常轻”）` 被切成"
                "`轻飘飘――失重（字面意思` —— 中文译文里括号引号**全是全角**。"
                "⇒ 全角那一族补进 `_BRACKET_PAIRS`，而且这个函数**两边共用**"))

    # ── 🔴🔴 **W24：同一格里跨版重复的例句 —— 三条，其中 P22 是读者口径** ──
    # 🔴 P22 **残留型**：判据再跑一遍，可出版的例句里**不许还有同一格的重复**。
    #    期望值天然是 0，不用我去推；而它与收割器**调同一个函数**
    #    ⇒ §⑦ 被删掉／`example_dup_key` 被改宽改窄，这一条当场变红。
    _pub = list(con.execute("SELECT word_id, sense_id, text_pub FROM example WHERE hidden=0"))
    _seen, _again = set(), 0
    for _w, _s, _t in _pub:
        _k = (_w, _s, S6.example_dup_key(_t))
        if _k in _seen:
            _again += 1
        _seen.add(_k)
    out.append(("P22", "🔴 W24：同一格（同义项／同「例句」区）里不许有重复例句（残留）",
                _again, 0,
                "🔴🔴🔴 **我第一次报给用户的数错了 3.8 倍，而且量的是另一件事**："
                "按 `(word_id, text_pub)` 分组得 1,569 组／多余 1,616 行／1,054 个词形，"
                "而展示层**把带义项的例句印在各自的义项下面**、`sense_id IS NULL` 的印在末尾"
                "「例句」区 ⇒ 「同一个词形下文本相同」**不等于读者看见重复**。"
                "按读者口径（分组键带 `sense_id`）重量：**417 组／多余 429 行／235 个词形**。"
                "⭐ 这一条的分组键就是读者口径本身，所以它**在构造上不可能再量错一次**。"
                "⚠️ 差额那 1,374 组是**同一个义项被两版各描述了一遍**"
                "（`qua`：义项「幸存」[en 版] ／ 义项「脱离死亡」[vi 版]）—— "
                "根因在义项层没有跨版合并，去掉例句只会让其中一个义项变成「没有例句」，"
                "**更糟**。那笔账记 W25，不在这里处理"))
    out.append(("P23", "W24：被判成同格重复而隐藏的例句", con.execute(
        "SELECT COUNT(*) FROM example WHERE hidden_why=?",
        (S6.HIDDEN_DUP_IN_CELL,)).fetchone()[0], 475,
        "🔴 **基线 429 → 475（2026-10-05，W25 的连带）**：折叠义项把两条义项的例句并到一格，制造出 46 条新的同格重复 —— 判据没变，数据变了。"
     "429 ＝ 417 组多余的行数。归一只做三件事：压空白、去首尾标点、**小写**。"
        "🔴 小写是有风险的一步（越南语专名靠大小写区分）⇒ **单独量过它**："
        "只靠小写才合并的 136 组，逐条读过 10 组全是源头自己写了两遍"
        "（`có mùi thúi` / `Có mùi thúi.`）；唯一看着像专名的 `siêu nhân` / `Siêu Nhân` "
        "**同版、同义项、译文都是「超人」** ⇒ 源头写了两遍，不是两个词。"
        "⚠️ 不删行：证据层留着（两版确实各收了这一句），与 B17 的 `redundant-related`、"
        "W9 的死链目标同一个处置（`[[prefer-reversible-designs]]`）"))
    # 🔴🔴 **这一条是「删付费译文」那个决定的安全网，而它查的是决定的前提本身。**
    #    敢删 407 条付费译文的第一条理由是「留下来那行一定有中文」——
    #    这条检查就是去验那句话。它一红，说明去重把读者那一格的译文弄丢了。
    _nozh = con.execute(
        "SELECT COUNT(*) FROM example e WHERE e.hidden=0 AND EXISTS("
        "  SELECT 1 FROM example x WHERE x.word_id=e.word_id AND x.hidden=1 "
        "    AND x.hidden_why=? AND x.text_pub=e.text_pub) "
        "AND NOT EXISTS(SELECT 1 FROM example_gloss g WHERE g.example_id=e.id "
        "               AND g.lang='zh')", (S6.HIDDEN_DUP_IN_CELL,)).fetchone()[0]
    out.append(("P24", "🔴 W24：重复组里**留下来那行必须有中文**（删付费译文的前提）",
                _nozh, 0,
                "删 407 条付费译文的三条理由里，第一条是「每个重复组的每一行都有中文，"
                "所以留下来那行一定有一条有效译文」—— **这条检查就是去验那句话本身**。"
                "⚠️ 没有它的话，`dup_survivor_rank` 改一下次序就可能留下一个没有中文的行，"
                "而 P15（覆盖率分子）只会降 1、看不出来。"
                "⭐ `[[expectation-must-be-declared]]`：**前提也要被断言**，"
                "不能只在注释里写「因为 A 所以可以删 B」"))

    # ── 🔴🔴 **W25：同一个义项被两版各描述了一遍 —— 四条** ──
    # 🔴🔴🔴 **P26 是这一轮最重要的一条，而它逮到的是 W12 留下的洞。**
    #    展示层的 `bySense` 按 `senseId` 索引、**只遍历可见义项** ⇒ 一条可出版例句
    #    若挂在隐藏义项上，它**永远不渲染、页面上无声消失**。
    #    实测当场逮到 **7 条**，全是 **W12 修复时留下的**
    #    （`gloss-is-punctuation-only` 3 ／ `gloss-is-source-markup` 4）——
    #    W12 隐藏了那些义项而没管身上挂着什么，而这个洞躺了三天。
    # ⚠️ 收割器里本来就有落点②「该义项被隐藏 ⇒ 词条级」，但它**只对
    #    `sense_src.sense_id IS NULL` 生效** —— 对「义项层建好之后才被隐藏的」
    #    结构性失明。`criteria.merged_sense_map()` 补的就是这个失明。
    #    `[[correct-steps-can-compose-a-hole]]`：每步都对、跨步假设失效。
    _orphan_ex = con.execute(
        "SELECT COUNT(*) FROM example e JOIN sense s ON s.id = e.sense_id "
        " WHERE e.hidden = 0 AND s.hidden = 1").fetchone()[0]
    _orphan_rel = con.execute(
        "SELECT COUNT(*) FROM sense_relation r JOIN sense s ON s.id = r.sense_id "
        " WHERE r.hidden = 0 AND s.hidden = 1").fetchone()[0]
    out.append(("P26", "🔴🔴 可出版例句不许挂在**隐藏的义项**上（页面上会无声消失）",
                _orphan_ex, 0,
                "展示层 `bySense.get(s.id)` 只遍历可见义项 ⇒ 挂在隐藏义项上的例句"
                "**既不在义项下、也不在词条级「例句」区**，一行都印不出来。"
                "🔴 实测 7 条，**全是 W12 修复时留下的**（隐藏义项而没管身上挂着什么）——"
                "它躺了三天，是 W25 加这条断言才露出来的。"
                "⭐ 修法不是去 UPDATE `example.sense_id`（外锚闸的恒等式含这一列，"
                "会判红而它是对的），而是让收割器过 `merged_sense_map()` 自己解析成词条级"))
    out.append(("P27", "🔴 可出版关系不许挂在隐藏的义项上（同一个洞的关系层那一半）",
                _orphan_rel, 0,
                "与 P26 同一个形状。53 条义项级关系挂在被折叠的义项上 ⇒ "
                "`relBySense` 同样只遍历可见义项。"
                "⚠️ 关系层**没有 `--sync`**（只有 `--rebuild`），而 `--rebuild` 会"
                "**删掉 W17 手工收回来的 30 条** ⇒ 为此给它补了 `--sync` ＋ 一道"
                "「有别的写入方就拒绝 rebuild」的保险（与例句层的付费数据保险同一条规矩）"))
    out.append(("P28", "W25：被折叠的义项数", con.execute(
        "SELECT COUNT(*) FROM sense WHERE hidden_why=?",
        (DUP_SENSE_WHY,)).fetchone()[0], 1634,
        "1,255 组 / 1,634 条。⚠️ 其中 **3 条是第五次收窄（当天晚些）加的** —— 回答用户「是翻译质量不行吗」时去查「怎样才算读者分得开」，当场照出 3 条**只有共享中文、连英文也没有**的义项（`tiếng Việt`/`đá lửa`/`bảng cửu chương`，全来自中文版）。⭐ **写否定结论反而比花钱更值**：它逼我定义判据，而定义照出了真缺陷。"
        "判据 `criteria.dup_sense_groups()` **四次收窄**："
        "①同词形＋中文逐字相同 1,817 组 → ②🔴**扣掉跨 entry 的 484 组**"
        "（同一个中文词出现在两个词性下是**正当的**，`qua` 当动词和介词都译作「经过」，"
        "读者在两个词性标题下各看一次）→ ③🔴**扣掉 72 组「两条都有英文而内容不同」**"
        "（逐组读完 30 条，**混着真差异**：`hớt tóc` 的 `to give a haircut` / "
        "`to get a haircut` 是**理发师和顾客两个角色**、`công quốc` 的 "
        "`principality` / `duchy` 不是一回事 ⇒ 中文比英文**粗**，折叠会真丢信息，"
        "记 W26）→ ④1,252 组。"
        "⚠️ 那 72 组里确有 42 组是英文同义改写（`airfield`/`airport`），"
        "**但我分不开这 42 和那 30** ⇒ 整体不折：错折是读者看得见的错，漏折只多一行。"
        "⭐ 成因两种：**跨版重复 1,045 组** ＋ **同一版自己重复 207 组**"
        "（源头给的是**嵌套释义**，`glosses[0]` 是共享的父释义而 `glosses[1]` 才是"
        "具体义项，我们两条都收了 ⇒ 父释义被印了 N 遍。`em` 的 pron 条目印了 4 遍）"))
    # 🔴🔴 **P25：删付费译文的那个决定的兜底不变量。**
    #    W24 删 407 条时我是**删之前**逐条验答案文件的；W25 连带删 23 条时
    #    我是**删完才补验** —— 流程上退了一步，而补验的结果比抽查强：
    #    「凡是库里有付费中文的行，它的 id 必在答案文件里」是一条**不变量**。
    #    它一红就意味着库里出现了无处可追的付费数据（或答案文件被动过）。
    _paid_unrecoverable = 0
    try:
        import json as _json
        _have = set()
        for _f in sorted((paths.WORK / "example_zh").glob("*.jsonl")):
            with _f.open() as _fh:
                for _ln in _fh:
                    try:
                        _o = _json.loads(_ln)
                    except ValueError:
                        continue
                    if isinstance(_o.get("id"), int):
                        _have.add(_o["id"])
        _paid = {e for (e,) in con.execute(
            "SELECT example_id FROM example_gloss WHERE src LIKE 'model%'")}
        _paid_unrecoverable = len(_paid - _have)
    except OSError:
        _paid_unrecoverable = -1          # 答案文件不见了也要判红，不许静默过
    out.append(("P25", "🔴 付费例句译文的 id **全部**在答案文件里（删得掉也取得回）",
                _paid_unrecoverable, 0,
                "实测 75,524 / 75,524 ＝ 100%。`[[answer-file-is-the-ledger]]`：清库≠清答案文件。"
                "⭐ 这条闸是**倒过来**建的 —— 先有「我敢删付费数据」这个决定，"
                "再把那个决定赖以成立的前提做成断言。"
                "⚠️ 答案文件读不到时它返 **−1 而不是 0** —— "
                "`[[expectation-must-be-declared]]`：读不到文件的空结果**不是证据**"
                "（`dont-recast-deliverables-as-junk` 记的就是这一跤）"))

    # ── W17：被当例句收的关系数据，收进关系层 ──
    n_w17 = con.execute("SELECT COUNT(*) FROM sense_relation "
                        "WHERE src='w17-from-examples'").fetchone()[0]
    out.append(("P21", "W17：从 examples 里收回关系层的行", n_w17, 30,
                "🔴🔴 **这笔账的前提大半不成立，是量出来才知道的。** 账上写「103 条关系"
                "元数据我们没有收进关系层」，实测：18 条是**声调范式表**（属音标层，记 W23）；"
                "其余 85 条解出的目标里 **83 个关系层早就有了** —— "
                "源头把同一份数据给了两遍（规范的 `coordinate_terms` 字段 ＋ 又挤进 "
                "`examples`），我们从规范字段收过了。`[[measure-landing-not-source]]`。"
                "🔴 而我第一次量时用 `body.split(',')`，判据**既太宽又太窄**："
                "造出 13 条假目标（`in general`/`loosely or tightly)` —— "
                "`tàu hoả (“train”), tàu điện (“tram”)` 的括号限定语自带逗号被切断），"
                "同时**漏掉 11 条真目标**（`tàu` 的 7 个 meronym 整串被切残）。"
                "⇒ 正经解析器（括号内逗号不算分隔符）给出 **30 条**，全部打印逐条读过。"
                "⚠️ `near-synonym` 那 52 条**有意不收**：`KINDS` 里没有这个 kind，"
                "塞进 `synonym` 等于改写源头的分级，而它们的目标**全部已在关系层**"))

    # R2 纯表意词头（用户 2026-09-28 的决定）
    n = sum(1 for (w,) in con.execute("SELECT word FROM dict") if is_han_headword(w))
    out.append(("R2", "`dict` 里没有纯表意（汉字/喃字）词头", n, 0,
                "🔴🔴 **155 个躺在库里，而骨架闸 S6 明写这一条却报 0** ——"
                "因为断言和被断言的**用同一个坏判据**：`is_ideograph` 当时有两份实现，"
                "收词用的是**没有码位兜底**那一份，不认识 CJK 扩展 H（Unicode 15.0，"
                "而 Python 的 `unicodedata` 是 14.0）。是**关系闸 R19** 逮到的。"
                "⇒ 兜底搬进 `criteria`，`han_sources` 改成 `import` 它 —— "
                "**谓词从此物理上不可能再漂**"))

    # R3 出版层「不载信息」的释义（W12）
    pub = list(con.execute("SELECT g.lang, g.text FROM sense s JOIN sense_gloss g "
                           "ON g.sense_id=s.id WHERE s.hidden=0"))
    n_junk = sum(1 for _l, t in pub if not gloss_has_content(t))
    n_mark = sum(1 for l, t in pub if l == "vi" and is_vi_markup_gloss(t))
    out.append(("R3", "出版层没有「不载任何信息」的释义（W12）", n_junk, 0,
                "**141 条释义整串是 `.`**。🔴 义项层闸 **E4 查的是 `TRIM(text)=''`，"
                "而 `.` 不是空串** ⇒ 它穿过去了。"
                "🔴🔴 更该记的是：同一种源头残渣在**三个层**各出现过一次"
                "（例句 214／词源 122／义项 141），前两次我都只在本层挡掉、"
                "**没把判据收进 `criteria.py`** ⇒ 下一层照样中"))
    out.append(("R3b", "出版层没有源头的词典标记缩写（`Trgt.`/`Ph.`）", n_mark, 0,
                "45 条。它们是 5b 跑完**控制组**报出来的：模型把 `Trgt.` 原样回显，"
                "**那是对的 —— 没东西可译**，但它们本来就不该在出版层。"
                "⚠️ 判据是**枚举**不是形状：三次收窄都证明形状判据会误伤"
                "（「单 token 短释义」15,183 行、「没有 ≥3 字母的词」259 行、"
                "「句点缩写不在词库里」30 行，全是误伤）"))

    # R4 word_norm 与判据一致（声调是辨义的）
    bad = [(w, wn) for w, wn in con.execute("SELECT word, word_norm FROM dict")
           if norm_vi(w) != wn]
    out.append(("R4", "`word_norm` 与 `criteria.norm_vi` 逐行一致", len(bad), 0,
                "越南语**声调是辨义的**（`má` 妈／`mà` 而／`mả` 坟）⇒ 归一**不许剥声调**。"
                "这一条查的不是「判据对不对」，是**判据与落库有没有漂开** ——"
                "哪天有人改了 `norm_vi` 而没重建 `dict`，这里当场红"))

    # R14 关系目标不是别的文字系统（R19/R21 的落点）
    tg = [t for (t,) in con.execute(
        "SELECT DISTINCT target FROM sense_relation WHERE hidden=0")]
    n_han = sum(1 for t in tg if is_han_headword(t))
    n_for = sum(1 for t in tg if S6.has_non_vietnamese_script(t))
    out.append(("R14", "出版层的关系目标里没有纯表意词", n_han, 0,
                "汉字目标**必然死链**（汉字词头有意不进 `dict`）。"
                "⚠️ **不拿 `roman` 顶上** —— 那是那个汉字词的读音，"
                "不等于「这个词的 derived 是它」（那是编造关系）"))
    out.append(("R14b", "出版层的关系目标里没有假名/韩文字母", n_for, 0,
                "106 行：日语词／**越南语词+韩语释义拼在一个字段**／"
                "**整段标签塞进 target**（`파생어: cá biệt (個別), …`）——"
                "与 ko 自己那条「关系目标塞整段释义 2,192 行」同形。"
                "📋 ⚠️ 这条判据只覆盖**带那两种文字**的那批；同样的污染若出现在"
                "**纯拉丁文本**里（`Từ phái sinh: a, b, c`）它一条都抓不到 ⇒ 欠账 **W9**"))
    return out


def r0_read_path():
    """🔴 **带锁的豁免**：展示层一出现，`READ_PATH` 就必须有东西。

    `[[it-regression-gate]]` 的核心是**在写入列与读取路径各查一次**，
    两边数字不同就是「修复被绕过」。it 那门最值钱的一条正是这么来的：
    `dict.pos` 是**词形级**的斜杠串，而展示层 `entry.pos.split('/').some(...)`
    只要有一个名词用法就为真 ⇒ 把只对某一个词条成立的属性顶到了整词头上。
    **写入侧一直非零、读取侧修完才归零** —— 只量一侧的话这个缺陷看不见。

    vi 的展示层还不存在，所以这一半现在是空的。⚠️ 空着**不许靠注释提醒** ——
    `[[lesson-must-become-mechanism]]`：做成机制的全守住了，写成文字的一条没守住。
    """
    if DISPLAY.exists() and not READ_PATH:
        return [("R0", "🔴🔴 展示层 `%s` 已经存在，而 `READ_PATH` 还是空的 —— "
                       "**回归闸只量了写入列那一半**。it 那门最值钱的一条缺陷"
                       "（词头徽标归属）在写入侧永远非零、只在读取侧归零，"
                       "只量一侧看不见它。⇒ 去把展示层真的 SELECT 了哪几列抠出来"
                       % DISPLAY.relative_to(ROOT), 1, 0, "")]
    return []


# ══════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════
# 🔴🔴🔴 **花名册 —— 这道闸的闸。2026-10-05 加的，而加它的理由是我自己栽了。**
#
# 改 R1 的基线时我用 `s[:i] + new + s[j:]` 换掉一整段，而 **P12/P13 正夹在被换掉的
# 那一段里 ⇒ 一起被切走**。之后：
#     `python3 vi/tests/test_no_regression.py`  → **✅ 全绿**（它们不在输出里，
#                                                 而**没有任何东西数过输出该有几条**）
#     `--mutate`                                → 🔴 没逮到 P12 / 没逮到 P13
# ⇒ 只有变异验证报了出来，而它**不在写库后自动跑的那条路上**。
#
# ⭐ 这是 ko 的 K31 原话逐字重演：「**改测试时把一条检查删掉而闸报「全绿」** ⇒
#   加『闸自己的闸』」。那一课当时做进了**层闸**（`test_example_layer.ROSTER`）和
#   **账的闸**（`V0`：从检查表里删掉最后一条），**唯独漏了回归闸** ——
#   而回归闸是**每次写库由 `dbtool._regression_check()` 自动跑**的那一道，漏得最不该。
#   `[[lesson-must-become-mechanism]]`：做成机制的守住了，而**机制也要逐个路口都装**。
#
# ⚠️ 花名册**写成显式元组，不从现状推**（`[[expectation-must-be-declared]]`：
#   「编号连续」逮不到删掉最后一条，而最后一条最容易被删）。
ROSTER = (
    "R1", "R1b", "R1c", "R1d", "R1e", "R2", "R3", "R3b", "R4", "R5", "R6", "R7",
    "R9", "R10", "R12", "R13", "R14", "R14b", "R15", "R16", "R17",
    "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10",
    "P11", "P12", "P13", "P14", "P15", "P16",
    # 2026-10-05 W16/W17：P17 是**读者口径**那一条（展示层 SELECT `text_pub`），
    #   P18/P20 残留型（与判据调同一个函数），P19/P21 基线型。
    "P17", "P18", "P19", "P20", "P21",
    # 2026-10-05 W24：P22 残留型（**分组键就是读者口径**）／P23 基线 429 ／
    #   P24 断言「删付费译文」那个决定的**前提**（留下来那行必须有中文）。
    # 2026-10-05 W25：P26 是这一轮最重要的一条（它逮到 W12 留下的洞）／
    #   P27 是它的关系层那一半／P28 基线 1,631 ／P25 是「删付费数据」那个决定的不变量。
    "P22", "P23", "P24", "P25", "P26", "P27", "P28",
)


def roster_check(ids):
    """→ [(编号, 说明)]。花名册与实际跑出来的检查对不上就报。"""
    have, want = list(ids), list(ROSTER)
    bad = []
    if len(have) != len(set(have)):
        dup = sorted({x for x in have if have.count(x) > 1})
        bad.append(("R00", "有重复的检查编号：%s —— 重复会让一条失效而总数不变" % dup))
    miss = sorted(set(want) - set(have))
    extra = sorted(set(have) - set(want))
    if miss:
        bad.append(("R00", "🔴🔴 花名册上有而跑不出来的检查：%s —— "
                           "**多半是改别的东西时把它删掉了**（2026-10-05 我这么删过 "
                           "P12/P13，而正常跑报「全绿」）" % miss))
    if extra:
        bad.append(("R00", "跑出来而花名册上没有的检查：%s —— 加检查要同时登记" % extra))
    return bad


def run_all(con):
    """→ [(编号, 名称, 实测, 期望, 当初怎么坏的)]"""
    out = list(r0_read_path())
    for cid, name, sql, want, why in SQL_CHECKS:
        out.append((cid, name, con.execute(sql).fetchone()[0], want, why))
    out += py_checks(con)
    # ── 读取路径：每条锁的是**写入列与展示层 WHERE 之间的差额**
    for cid, name, w_sql, r_sql, want, why in READ_PATH:
        gap = con.execute(w_sql).fetchone()[0] - con.execute(r_sql).fetchone()[0]
        out.append((cid, name, gap, want, why))
    for cid, name, sql, want, why in READ_SCALE:
        out.append((cid, name, con.execute(sql).fetchone()[0], want, why))
    # 🔴 花名册自检**放在最后、混进同一个返回值**里 —— 这样 `check_brief()`／
    #    `dbtool._regression_check()` 不用改一个字就能看见它（契约是 dbtool 定的）。
    for cid, why in roster_check([r[0] for r in out]):
        out.append((cid, "🔴🔴 花名册自检（这道闸的闸）", 1, 0, why))
    return out


def check_brief():
    """给 `dbtool` 用：→ **[(编号, 名称, 说明)]**，空列表＝全绿。

    🔴🔴 **这个返回值的元数必须是 3，而我第一版写的是 2。** `vi/dbtool.py` 的
       `_regression_check()` 里是 `for cid, name, why in red:` ⇒ 2 元组当场
       `ValueError: not enough values to unpack`。
    ⚠️ 症状极坏：写库**已经 commit**，回归闸**真的逮到了一条红**，
      而它在打印那一条的时候自己炸了 —— 屏幕上只剩「有 1 条失效了」加一段 traceback，
      **到底哪一条看不见**。一道报不出内容的闸，和一道不存在的闸差别很小。
    ⇒ 契约是 `dbtool` 定的，这里跟着它；别反过来改 `dbtool`（那是八门共用的形状）。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        return [(cid, name[:36], "实测 %s，期望 %s" % (F(got), F(want)))
                for cid, name, got, want, _why in run_all(con) if got != want]
    finally:
        con.close()


def _pick_unrecoverable_example(con):
    """挑一条 `id` 不在答案文件里的可出版例句（给 P25 的变异当锚）。→ id 或 None"""
    import json as _json
    have = set()
    for f in sorted((paths.WORK / "example_zh").glob("*.jsonl")):
        with f.open() as fh:
            for ln in fh:
                try:
                    o = _json.loads(ln)
                except ValueError:
                    continue
                if isinstance(o.get("id"), int):
                    have.add(o["id"])
    # ⚠️ 锚的两个条件都要满足，而第二个是 **`en` 那一格空着**，不是中文：
    #    ① `example_gloss` 上有 `UNIQUE(example_id, lang)` ⇒ 不能往已占的格里插
    #    ② 🔴 **「既不在答案文件里、又没有中文」的行一条都没有** ——
    #      没中文的只有 11 条，而它们全在答案文件里（跑过、模型没给出东西）。
    #      第一版的 `assert` 当场炸出来，**而那正是对的报法**
    #      （`[[expectation-must-be-declared]]` / B20：前提不成立要 raise，
    #       不许印「没逮到」—— 后者会把人引去修判据而判据没坏）。
    #    ⇒ 改插 `en` 那一格：P25 查的是 `src LIKE 'model%'`，**不按语种过滤**，
    #      所以它照样响；而 P14/P15 只数 `lang='zh'` ⇒ 连带反而更少。
    for (i,) in con.execute(
            "SELECT e.id FROM example e WHERE e.hidden=0 AND NOT EXISTS("
            "  SELECT 1 FROM example_gloss g WHERE g.example_id=e.id AND g.lang='en')"
            " ORDER BY e.id"):
        if i not in have:
            return i
    return None


def mutate():
    """变异验证：每条检查**真的逮得到东西**。

    🔴 动真库，注入后立即还原（与外锚闸同一个做法）。末尾有总量回核。

    🔴🔴 **2026-10-03：这套变异整个跑不起来，而它看起来是绿的。**
       `check_brief()` 早先从 2 元组改成 3 元组（为了让 `dbtool` 印得出是哪条红），
       而本函数里三处解包 `for c, w in base` / `{x for x, _ in check_brief()}`
       **没跟着改** ⇒ `ValueError: too many values to unpack`。
    ⚠️ 为什么一直没人踩到：`base = check_brief()` 之后那个 `for` 循环
       **只在基线不绿时才执行**，而基线一直是绿的；真正会炸的是第一条变异。
       而 `vi/run_gates.py` 跑的是**不带 `--mutate`** 的那条路。
    ⇒ `[[lesson-must-become-mechanism]]`：「闸建好了」与「谁逼人跑它」是两件事，
      而**变异验证是闸的闸** —— 它不跑，上面那一长串 ✅ 说明不了它们逮得到东西。
      📋 已记欠账 **W19**：`run_gates.py` 该把 `--mutate` 也纳进去
      （代价是动真库，所以要单独一档，不能默认跑）。
    ⚠️ 不是每条都能变异：`R17`（有意不建的表）要建表，`R12`/`R16` 是基线型
       （改一行就偏离 ⇒ 用 UPDATE 制造偏离即可）。
    """
    base = check_brief()
    if base:
        print("🔴 基线就不绿，变异验证没有意义：")
        for c, _n, w in base:
            print("   %-5s %s" % (c, w))
        return False
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n0 = {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
          for t in ("dict", "sense", "sense_gloss", "sense_src", "example",
                    "example_gloss", "sense_relation", "etymology", "audio",
                    "pronunciation", "entry")}
    pick = {
        "aud": con.execute("SELECT id, word_id, url, commons_key, dialect, src "
                           "FROM audio LIMIT 1").fetchone(),
        "rel_h": con.execute("SELECT id FROM sense_relation WHERE hidden=1 LIMIT 1").fetchone(),
        "rel_v": con.execute("SELECT id, target FROM sense_relation WHERE hidden=0 LIMIT 1").fetchone(),
        "ety": con.execute("SELECT id, text FROM etymology LIMIT 1").fetchone(),
        "ent": con.execute("SELECT id, etym_type FROM entry WHERE etym_type IS NOT NULL "
                           "LIMIT 1").fetchone(),
        "pron": con.execute("SELECT id, dialect FROM pronunciation WHERE dialect='sai-gon' "
                            "LIMIT 1").fetchone(),
        "d": con.execute("SELECT id, word, word_norm FROM dict LIMIT 1").fetchone(),
        # 🔴🔴 **这里必须连 `sense_id` 和 `src` 一起取。** 2026-10-02 第一版只取了
        #    `(id, text)`，undo 里再用 `SELECT sense_id FROM sense_gloss WHERE id=?`
        #    去查 —— **那一行已经被删掉了** ⇒ 子查询返回空、INSERT 一行没插、
        #    **真丢了一条释义**，而 R15 从此一直红着，后面每条变异都报
        #    「未声明的连带 R15」、R17 也因此判错。
        #    ⇒ 原文是从 5b 的答案文件逐字取回来补上的（`[[answer-file-is-the-ledger]]`）。
        #    ⭐ 教训：**undo 需要的东西，必须在 do 之前全部取齐。**
        "gl": con.execute("SELECT g.id, g.sense_id, g.lang, g.text, g.src FROM sense s "
                          "JOIN sense_gloss g ON g.sense_id=s.id "
                          "WHERE s.hidden=0 AND g.lang='zh' LIMIT 1").fetchone(),
        "ss": con.execute("SELECT id FROM sense_src WHERE sense_id IS NULL LIMIT 1").fetchone(),
        "exg": con.execute("SELECT id, lang FROM example_gloss LIMIT 1").fetchone(),
        # 🔴🔴 **undo 需要的东西必须在 do 之前取齐。** 这套变异的 undo 曾经写坏过：
        #    删掉一条 `sense_gloss` 之后用子查询去读**已删除的那一行**取 `sense_id`
        #    ⇒ 什么都没插回去，真丢了一行释义，而它**伪装成五条检查的问题**
        #    （R15 一直红 ⇒ 后面每条都报「未声明的连带 R15」）。
        #    末尾那个「总量回核」是它被发现的唯一原因。
        # 6e 清洗那三条（P11/P12/P13）要用的锚，一律先取回原值：
        "p11": con.execute("SELECT id, hidden, hidden_why FROM example "
                           "WHERE hidden_why='source-has-no-vietnamese' "
                           "ORDER BY id LIMIT 1").fetchone(),
        "p12": con.execute("SELECT id, text, ref FROM example WHERE hidden=0 "
                           "AND ref IS NOT NULL AND TRIM(ref)<>'' "
                           "AND instr(text, char(10))=0 ORDER BY id LIMIT 1").fetchone(),
        "p13": con.execute("SELECT id, text FROM example WHERE hidden=0 "
                           "AND src='en-edition' AND instr(text, char(10))=0 "
                           "ORDER BY id LIMIT 1").fetchone(),
        # 🔴 P14/P15：**花钱买来的**那批。undo 要把整行原样插回去
        #    ⇒ 四列全部在 do 之前取齐（这套变异真丢过一行数据，就是因为 undo 回查已删行）
        # 🔴 W15 的两条锚：undo 要的原 `ptr_class` 在 do 之前取齐
        "sp1": con.execute("SELECT id FROM sense_src WHERE sense_id IS NULL "
                           "AND ptr_class='spelling' ORDER BY id LIMIT 1").fetchone(),
        "oth1": con.execute("SELECT id, ptr_class FROM sense_src WHERE sense_id IS NULL "
                            "AND ptr_class='other' ORDER BY id LIMIT 1").fetchone(),
        # 🔴 W16 的三条锚。`p17` 要一条**没被切过**的可出版行（切过的行拿来验
        #    「NULL」会和 P19 纠缠在一起）；`p20` 要一条**切过且有中文**的。
        "p17": con.execute("SELECT id, text_pub FROM example WHERE hidden=0 "
                           "AND text_pub = text ORDER BY id LIMIT 1").fetchone(),
        "p20": con.execute(
            "SELECT g.rowid, g.text, e.text FROM example e "
            "JOIN example_gloss g ON g.example_id=e.id AND g.lang='zh' "
            "WHERE e.hidden=0 AND e.text_pub <> e.text ORDER BY e.id LIMIT 1").fetchone(),
        "p21": con.execute("SELECT id, word_id, sense_id, kind, target, target_id, src, "
                           "src_ref FROM sense_relation WHERE src='w17-from-examples' "
                           "ORDER BY id LIMIT 1").fetchone(),
        # 🔴 W24 的两个锚。**必须在这里取** —— `con` 在变异开跑前就关掉了，
        #    我第一版把这两条查询写在变异那一段里，当场 `Cannot operate on a closed database`。
        #    ⭐ 这就是本文件反复写的那条规矩的又一次实证：**do 需要的东西在 do 之前取齐**。
        "p23": con.execute("SELECT id FROM example WHERE hidden_why=? ORDER BY id LIMIT 1",
                           (S6.HIDDEN_DUP_IN_CELL,)).fetchone(),
        # 🔴 W25 的三个锚。都要在 `con` 关掉之前取齐（P23/P24 那两条刚栽过）。
        "p26": con.execute(
            "SELECT s.id, s.hidden, s.hidden_why FROM sense s "
            " WHERE s.hidden=0 AND EXISTS(SELECT 1 FROM example e "
            "   WHERE e.sense_id=s.id AND e.hidden=0) ORDER BY s.id LIMIT 1").fetchone(),
        "p27": con.execute(
            "SELECT s.id, s.hidden, s.hidden_why FROM sense s "
            " WHERE s.hidden=0 AND EXISTS(SELECT 1 FROM sense_relation r "
            "   WHERE r.sense_id=s.id AND r.hidden=0) "
            " AND NOT EXISTS(SELECT 1 FROM example e WHERE e.sense_id=s.id AND e.hidden=0)"
            " ORDER BY s.id LIMIT 1").fetchone(),
        "p28": con.execute(
            "SELECT id, merged_into FROM sense WHERE hidden_why=? ORDER BY id LIMIT 1",
            (DUP_SENSE_WHY,)).fetchone(),
        # 🔴🔴 P25 的锚**必须算准**：要一条 `id` **确实不在答案文件里**的可出版例句。
        #    第一版我写的是「挑一条还没有中文的例句」，而它挑中的那条 id
        #    **恰好在答案文件里** ⇒ 前提没注入成，变异报「没逮到」。
        #    ⭐ 与 B20 记的那一族同形：**变异要动判据真正读的那个量**，
        #      而 P25 读的是「id 在不在答案文件里」，不是「有没有中文」。
        "p25": _pick_unrecoverable_example(con),
        "p24": con.execute(
            "SELECT g.id, g.example_id, g.text, g.src FROM example e "
            " JOIN example_gloss g ON g.example_id=e.id AND g.lang='zh' "
            " WHERE e.hidden=0 AND EXISTS(SELECT 1 FROM example x WHERE x.word_id=e.word_id "
            "   AND x.hidden=1 AND x.hidden_why=? AND x.text_pub=e.text_pub) "
            " ORDER BY e.id LIMIT 1", (S6.HIDDEN_DUP_IN_CELL,)).fetchone(),
        "p14": con.execute("SELECT g.id, g.example_id, g.text, g.src FROM example_gloss g "
                           "JOIN example e ON e.id=g.example_id "
                           "WHERE g.lang='zh' AND g.src LIKE 'model%' AND e.hidden=0 "
                           "ORDER BY g.id LIMIT 1").fetchone(),
    }
    con.close()

    def one(cid, name, do, undo, also=()):
        c = sqlite3.connect(paths.DB)
        try:
            do(c)
            c.commit()
        finally:
            c.close()
        try:
            hit = {r[0] for r in check_brief()}
        finally:
            c = sqlite3.connect(paths.DB)
            undo(c)
            c.commit()
            c.close()
        extra = hit - {cid} - set(also)
        ok = cid in hit and not extra
        tail = ""
        if hit & set(also):
            tail = "   （连带 %s，已声明）" % "、".join(sorted(hit & set(also)))
        if extra:
            tail = "   🔴 **未声明的连带 %s**" % "、".join(sorted(extra))
        print("   %s %-5s %s%s" % ("✅" if ok else
                                   ("🔴 连带未声明" if cid in hit else "🔴 没逮到"),
                                   cid, name, tail))
        return ok

    ok = True
    print("═══ 变异验证（动真库，注入后立即还原）═══")
    a = pick["aud"]
    ok &= one("R5", "B12：同一 Commons 键插成两行（换个 url）",
              lambda c: c.execute(
                  "INSERT INTO audio (word_id, url, commons_key, dialect, src, hidden) "
                  "VALUES (?,?,?,?,?,0)", (a[1], a[2] + "?x=1", a[3], a[4], a[5])),
              lambda c: c.execute("DELETE FROM audio WHERE url=?", (a[2] + "?x=1",)))
    ok &= one("R6", "🔴 把一条 B17 隐藏的关系放回出版层（判据被改宽的样子）",
              lambda c: c.execute("UPDATE sense_relation SET hidden=0, hidden_why=NULL "
                                  "WHERE id=?", (pick["rel_h"][0],)),
              lambda c: c.execute("UPDATE sense_relation SET hidden=1, "
                                  "hidden_why='redundant-related' WHERE id=?",
                                  (pick["rel_h"][0],)),
              # ⚠️ 连带 P3 **已声明**：放回一条隐藏关系必然让「写入列 vs 展示层」
              #    的差额少 1。不是判据写宽了，是同一件事被两条检查从两侧量，本该一起响。
              also=("P3",))
    e = pick["exg"]
    ok &= one("R7", "把一条例句译文的语言改成 vi（＝把出处当译文收了）",
              lambda c: c.execute("UPDATE example_gloss SET lang='vi' WHERE id=?", (e[0],)),
              lambda c: c.execute("UPDATE example_gloss SET lang=? WHERE id=?", (e[1], e[0])))
    y = pick["ety"]
    ok &= one("R9", "🔴 把内嵌魔术字塞回词源正文（清洗那步被去掉的样子）",
              lambda c: c.execute("UPDATE etymology SET text='__NOEDITSECTION__'||text "
                                  "WHERE id=?", (y[0],)),
              lambda c: c.execute("UPDATE etymology SET text=? WHERE id=?", (y[1], y[0])))
    en = pick["ent"]
    ok &= one("R10", "🔴 把 `etym_type` 写到一条非 en 版的 entry 上（S13 逮到的那个）",
              lambda c: c.execute("UPDATE entry SET etym_type='borrowed' WHERE id="
                                  "(SELECT id FROM entry WHERE src<>'en-edition' "
                                  " AND etym_type IS NULL LIMIT 1)"),
              lambda c: c.execute("UPDATE entry SET etym_type=NULL WHERE "
                                  "src<>'en-edition' AND etym_type IS NOT NULL"))
    p = pick["pron"]
    ok &= one("R12", "把一条西贡音改成别的方言（＝只读 tags 不读 note 的后果）",
              lambda c: c.execute("UPDATE pronunciation SET dialect='ha-noi' WHERE id=?",
                                  (p[0],)),
              lambda c: c.execute("UPDATE pronunciation SET dialect=? WHERE id=?",
                                  (p[1], p[0])))
    ok &= one("R13", "🔴 给一个已有源头音标的词补一条「拼的」",
              lambda c: c.execute(
                  "INSERT INTO pronunciation (word_id, ipa, dialect, src, src_ref) "
                  # 🔴 方言**写死 `ha-noi`**：第一版照抄被复制那一行的 dialect，
                  #    若它恰好是 `sai-gon` 就会把 R12 的基线顶高一行 ⇒ 未声明的连带。
                  #    变异要只动它想验的那一件事。
                  "SELECT word_id, 'mutant', 'ha-noi', 'compose:mutant', 'pron:MUTANT' "
                  "FROM pronunciation WHERE src NOT LIKE 'compose:%' LIMIT 1"),
              lambda c: c.execute("DELETE FROM pronunciation WHERE src_ref='pron:MUTANT'"),
              # ⚠️ 连带 P6 **已声明**：补一条 `compose:` 音标必然让「拼出来的音标总量」+1
              also=("P6",))
    g = pick["gl"]
    ok &= one("R15", "⭐ 删掉一条中文释义（义项又缺中文了）",
              lambda c: c.execute("DELETE FROM sense_gloss WHERE id=?", (g[0],)),
              # 五列全部来自 do 之前取的那一行，不再回查已删除的行
              lambda c: c.execute("INSERT INTO sense_gloss (id, sense_id, lang, text, src) "
                                  "VALUES (?,?,?,?,?)", g))
    ok &= one("R16", "🔴 删掉一条指针证据（证据层被编辑了）",
              lambda c: c.execute("UPDATE sense_src SET sense_id=1 WHERE id=?",
                                  (pick["ss"][0],)),
              lambda c: c.execute("UPDATE sense_src SET sense_id=NULL WHERE id=?",
                                  (pick["ss"][0],)),
              # ⚠️ 连带 R1c **已声明**：这一行是指针，把它挂上义项之后
              #    「指针区会印出来的行」必然少 1。R1c 是 2026-10-05 加的 ——
              #    **连带声明要跟着检查表一起长**。
              also=("R1c",))
    d = pick["d"]
    ok &= one("R4", "🔴 把一个词形的 `word_norm` 改成**剥掉声调**的（vi 最怕的那种改动）",
              lambda c: c.execute("UPDATE dict SET word_norm='mutant' WHERE id=?", (d[0],)),
              lambda c: c.execute("UPDATE dict SET word_norm=? WHERE id=?", (d[2], d[0])))
    r = pick["rel_v"]
    ok &= one("R14", "🔴 把一条出版关系的目标改成纯汉字（必然死链）",
              lambda c: c.execute("UPDATE sense_relation SET target='學生' WHERE id=?",
                                  (r[0],)),
              lambda c: c.execute("UPDATE sense_relation SET target=? WHERE id=?",
                                  (r[1], r[0])))
    ok &= one("R14b", "🔴 把一条出版关系的目标改成日语（假名）",
              lambda c: c.execute("UPDATE sense_relation SET target='彼ら' WHERE id=?",
                                  (r[0],)),
              lambda c: c.execute("UPDATE sense_relation SET target=? WHERE id=?",
                                  (r[1], r[0])))
    # R17：有意不建的表真建出来
    c = sqlite3.connect(paths.DB)
    c.execute("CREATE TABLE IF NOT EXISTS inflection (id INTEGER PRIMARY KEY)")
    c.commit()
    c.close()
    hit = {r[0] for r in check_brief()}
    c = sqlite3.connect(paths.DB)
    c.execute("DROP TABLE inflection")
    c.commit()
    c.close()
    good = "R17" in hit and hit == {"R17"}
    ok &= good
    print("   %s R17   手建 `inflection`（有意不建的那三张之一）%s"
          % ("✅" if good else ("🔴 连带未声明" if "R17" in hit else "🔴 没逮到"),
             ("   🔴 **未声明的连带 %s**" % "、".join(sorted(hit - {"R17"}))) if hit - {"R17"} else ""))

    # ── 6e 清洗那三条 ──
    h = pick["p11"]
    ok &= one("P11", "🔴 把一条「源头没给越南语」的例句放回出版层",
              lambda c: c.execute("UPDATE example SET hidden=0, hidden_why=NULL "
                                  "WHERE id=?", (h[0],)),
              lambda c: c.execute("UPDATE example SET hidden=?, hidden_why=? WHERE id=?",
                                  (h[1], h[2], h[0])),
              also=("P2", "P7"))   # 放出来会同时动「隐藏差额」和「带 ref 的出版例句」
    q = pick["p12"]
    ok &= one("P12", "🔴 把出处串回 `text` 首行并清空 `ref`（清洗那步被去掉的样子）",
              lambda c: c.execute(
                  "UPDATE example SET text=?, ref=NULL WHERE id=?",
                  ("Analects, 7.34; 1861 English translation by James Legge\n" + q[1], q[0])),
              lambda c: c.execute("UPDATE example SET text=?, ref=? WHERE id=?",
                                  (q[1], q[2], q[0])),
              # ⚠️ 连带四条，**都是声明过的**：`ref` 被清空 ⇒ P7 少一条；
              #    往 `text` 里加一行 ⇒ 行数与译文不再相等 ⇒ P16 多一条。
              # 🔴🔴 P18/P19 是 **2026-10-05 加 `text_pub` 之后才出现的连带**，
              #    而它们响得**完全正确**：改了 `text` 却没同步 `text_pub`，
              #    库与判据就是漂开了 —— ⭐ 这正是 P18 存在的意义，
              #    它顺手把「有人原地改 `text` 而忘了跑 `--sync`」变成了一道会响的闸。
              #    `[[replay-scripts-undo-fixes]]`：修复会被后一步静默撤销。
              # ⇒ **连带声明要跟着检查表一起长**（这是同一个文件里第三次了）。
              also=("P7", "P16", "P18", "P19"))
    r = pick["p13"]
    ok &= one("P13", "🔴 把内嵌英译行塞回 `text`（判据被去掉的样子）",
              lambda c: c.execute(
                  "UPDATE example SET text=? WHERE id=?",
                  (r[1] + "\nThe cold autumn pond; the clear water;", r[0])),
              lambda c: c.execute("UPDATE example SET text=? WHERE id=?", (r[1], r[0])),
              # 往 `text` 里加一行 ⇒ 行数与译文不再相等（P16）；
              # 改了 `text` 没同步 `text_pub` ⇒ P18/P19（见 P12 上方那段）
              also=("P16", "P18", "P19"))

    # ── W15：指针区的分类 ──
    # 🔴 **一条变异同时验两个数**，而那正是它们必须成对存在的理由：
    #    把一行「只是这个词的汉字表记」翻成「指针」⇒ R1c 多 1、R1d 少 1。
    #    只锁 R1c 的话这个方向看起来像「指针变多了」（像好事），只锁 R1d 同理。
    _sp = pick["sp1"]
    ok &= one("R1c", "🔴🔴 把一行「只是汉字表记」翻成「指针」（79.7% 那个错标复发的样子）",
              lambda c: c.execute("UPDATE sense_src SET ptr_class='pointer' WHERE id=?",
                                  (_sp[0],)),
              lambda c: c.execute("UPDATE sense_src SET ptr_class='spelling' WHERE id=?",
                                  (_sp[0],)),
              also=("R1d",))
    _ot = pick["oth1"]
    ok &= one("R1e", "把一条判不出来的残差改成 `pointer`（上限被突破的样子）",
              lambda c: c.execute("UPDATE sense_src SET ptr_class='pointer' WHERE id=?",
                                  (_ot[0],)),
              lambda c: c.execute("UPDATE sense_src SET ptr_class=? WHERE id=?",
                                  (_ot[1], _ot[0])),
              also=("R1c",))

    # ── 6e 的产物（付费数据）──
    g14 = pick["p14"]
    ok &= one("P14", "🔴🔴 删掉一条**花钱买来的**例句中文译文",
              lambda c: c.execute("DELETE FROM example_gloss WHERE id=?", (g14[0],)),
              lambda c: c.execute(
                  "INSERT INTO example_gloss(id, example_id, lang, text, src) "
                  "VALUES (?,?,?,?,?)", (g14[0], g14[1], "zh", g14[2], g14[3])),
              # ⚠️ 连带 P15 **已声明**：这两条**有意**一起响 ——
              #    P14 是总量、P15 是读者口径的分子，只锁一个就逮不到
              #    「译文还在但挂到隐藏例句上了」那种方向的回归。
              also=("P15",))

    # ── W16/W17（2026-10-05）──
    # ⚠️ 这五条里有**两条只能做成代码侧变异**，理由见各自注释 ——
    #    `[[expectation-must-be-declared]]` 的延伸：**变异要动判据真正读的那个量**。
    _p17 = pick["p17"]
    ok &= one("P17", "🔴🔴 把一条可出版例句的 `text_pub` 清空（展示层那一格会变空白）",
              lambda c: c.execute("UPDATE example SET text_pub=NULL WHERE id=?", (_p17[0],)),
              lambda c: c.execute("UPDATE example SET text_pub=? WHERE id=?",
                                  (_p17[1], _p17[0])),
              # ⚠️ 连带 P18 **已声明**：清空之后它与判据重算的结果当然不等。
              #    两条都该响才对 —— P17 是读者口径（页面空了），
              #    P18 是一致性（库与判据漂开了），**同一件事的两个面**。
              also=("P18",))
    # 🔴🔴 **P18 必须做成代码侧变异。** 它的职责是「判据被改坏而库没同步」，
    #    而用 SQL 改库只能验「库被改坏而判据没变」—— 方向正好相反，
    #    验不到它真正该拦的那件事（`[[criteria-from-meaning-not-form]]` 的孪生形态：
    #    **变异要走检查实际走的那条路**）。
    #    ⇒ 直接把按版登记表清空，这正是「有人把 §⑥ 整节删掉」的样子。
    _sep_saved = S6.EDITION_GLOSS_SEP
    try:
        S6.EDITION_GLOSS_SEP = {}
        hit18 = {r[0] for r in check_brief()}
    finally:
        S6.EDITION_GLOSS_SEP = _sep_saved
    g18 = hit18 == {"P18"}
    ok &= g18
    print("   %s P18   把 `EDITION_GLOSS_SEP` 登记表清空（§⑥ 被整节删掉的样子）%s"
          % ("✅" if g18 else ("🔴 连带未声明" if "P18" in hit18 else "🔴 没逮到"),
             ("   🔴 **未声明的连带 %s**" % "、".join(sorted(hit18 - {"P18"})))
             if hit18 - {"P18"} else ""))
    # 🔴🔴🔴 **P19 存在的全部理由，就是 P18 有一个盲点**：判据被删**而且**有人跟着
    #    重跑了 `--sync` —— 那时库与判据**一致地**都不切了，P18 照样绿。
    #    这与 `[[gate-registers-status-quo-as-spec]]` 同形：一致不等于对。
    #    ⇒ 这条变异必须把两边**一起**翻掉：登记表清空 ＋ 那 52 行的 `text_pub` 抹平。
    c = sqlite3.connect(paths.DB)
    c.execute("UPDATE example SET text_pub=text WHERE text_pub <> text")
    c.commit()
    c.close()
    try:
        S6.EDITION_GLOSS_SEP = {}
        hit19 = {r[0] for r in check_brief()}
    finally:
        S6.EDITION_GLOSS_SEP = _sep_saved
        c = sqlite3.connect(paths.DB)
        # 还原：判据恢复之后重算一遍写回去（**不存快照** —— 它就是派生列，
        # 而「重算得回来」正是 `ADD_COLUMNS` 注释里给它的定义）
        rs = list(c.execute("SELECT e.id, d.word, e.text, e.src FROM example e "
                            "JOIN dict d ON d.id=e.word_id"))
        syl2 = S6.vi_syllables(c)
        c.executemany("UPDATE example SET text_pub=? WHERE id=?",
                      [(S6.split_edition_gloss(t, w, sc, syl2)[0], i)
                       for i, w, t, sc in rs])
        c.commit()
        c.close()
    g19 = hit19 == {"P19"}
    ok &= g19
    print("   %s P19   登记表清空**且**库跟着抹平（P18 的盲点：一致地都不切了）%s"
          % ("✅" if g19 else ("🔴 连带未声明" if "P19" in hit19 else "🔴 没逮到"),
             ("   🔴 **未声明的连带 %s**" % "、".join(sorted(hit19 - {"P19"})))
             if hit19 - {"P19"} else ""))
    _p20 = pick["p20"]
    ok &= one("P20", "🔴 把一条中文译文还原成「法语尾巴也译进去」的样子",
              lambda c: c.execute("UPDATE example_gloss SET text=? WHERE rowid=?",
                                  (_p20[1] + "：une mutation grossière", _p20[0])),
              lambda c: c.execute("UPDATE example_gloss SET text=? WHERE rowid=?",
                                  (_p20[1], _p20[0])))
    _p21 = pick["p21"]
    ok &= one("P21", "🔴 删掉一条从 examples 收回来的关系（W17 被撤销的样子）",
              lambda c: c.execute("DELETE FROM sense_relation WHERE id=?", (_p21[0],)),
              # undo 要的八列全部在 do 之前取齐（这套变异真丢过一行数据）
              lambda c: c.execute(
                  "INSERT INTO sense_relation (id, word_id, sense_id, kind, target, "
                  "target_id, src, src_ref) VALUES (?,?,?,?,?,?,?,?)", _p21))

    # ── W24（2026-10-05）：三条 ──
    # 🔴 P23 ＋ P22：把一条被判成重复的例句放回出版层 ⇒ 页面上那一句又印两遍。
    #    ⚠️ 它**必然**同时打中 P22（残留回来了）、P2（隐藏差额）、P15（覆盖率分子 +0，
    #      因为译文已经删了 ⇒ 不动）。连带逐条声明。
    _d24 = pick["p23"]
    ok &= one("P23", "🔴 把一条同格重复的例句放回出版层（页面上那句又印两遍）",
              lambda c: c.execute("UPDATE example SET hidden=0, hidden_why=NULL WHERE id=?",
                                  (_d24[0],)),
              lambda c: c.execute("UPDATE example SET hidden=1, hidden_why=? WHERE id=?",
                                  (S6.HIDDEN_DUP_IN_CELL, _d24[0])),
              # P22 残留回来 1 条；P2 的隐藏差额少 1。
              # ⚠️ 我第一版还声明了 P24，而它**不响** —— `one()` 只拦未声明的连带，
              #    多声明一条会静默通过。**过度声明也是错的**：它让下一个人以为
              #    P23 与 P24 耦合，而实测没有。（P24 查的是「留下来那行有没有中文」，
              #    放一条被隐藏的行回出版层不改变任何留下来那行。）
              also=("P22", "P2"))
    # 🔴🔴 **P22 必须另有一条代码侧变异。** 上面那条验的是「库被改坏」，
    #    而 P22 真正要拦的是**判据被改坏** —— 两个方向，SQL 注入够不到后者。
    #    把归一函数改成「原样返回」（＝退回精确匹配）：库里 429 条隐藏不动，
    #    而重算出来的重复组从 417 掉到 211 ⇒ P22 仍是 0、**P23 的 429 变不了**……
    #    ⚠️ 所以单纯改窄 `example_dup_key` 这两条都逮不到，必须改**宽**：
    #      归一到「只剩越南语音节」会把不同的句子并成一组 ⇒ P22 当场冒出残留。
    #    ⭐ 这正说明 P22/P23 分别管一个方向，缺一个就有盲区。
    _key_saved = S6.example_dup_key
    try:
        S6.example_dup_key = lambda t: "".join(sorted(set((t or "").lower().split())))
        hit22 = {r[0] for r in check_brief()}
    finally:
        S6.example_dup_key = _key_saved
    g22 = hit22 == {"P22"}
    ok &= g22
    print("   %s P22   把 `example_dup_key` 改宽（判据被改坏，SQL 注入够不到的那个方向）%s"
          % ("✅" if g22 else ("🔴 连带未声明" if "P22" in hit22 else "🔴 没逮到"),
             ("   🔴 **未声明的连带 %s**" % "、".join(sorted(hit22 - {"P22"})))
             if hit22 - {"P22"} else ""))
    # 🔴 P24：把留下来那行的中文删掉（＝「删付费译文」那个决定的前提被破坏）
    _k24 = pick["p24"]
    ok &= one("P24", "🔴 删掉重复组里**留下来那行**的中文（删付费译文的前提被破坏）",
              lambda c: c.execute("DELETE FROM example_gloss WHERE id=?", (_k24[0],)),
              lambda c: c.execute(
                  "INSERT INTO example_gloss(id, example_id, lang, text, src) "
                  "VALUES (?,?,?,?,?)", (_k24[0], _k24[1], "zh", _k24[2], _k24[3])),
              also=("P14", "P15"))   # 删一条付费译文 ⇒ 总量与分子各少 1

    # ── W25（2026-10-05）：四条 ──
    # 🔴🔴 P26：把一条**带可出版例句**的可见义项悄悄隐藏掉 —— 这正是 W12 当年做的事，
    #    而它的例句会从页面上无声消失。
    _s26 = pick["p26"]
    ok &= one("P26", "🔴🔴 隐藏一条带可出版例句的义项（W12 那个洞复发的样子）",
              lambda c: c.execute("UPDATE sense SET hidden=1, hidden_why='mutant' "
                                  "WHERE id=?", (_s26[0],)),
              lambda c: c.execute("UPDATE sense SET hidden=?, hidden_why=? WHERE id=?",
                                  (_s26[1], _s26[2], _s26[0])),
              also=("P1",))     # 可见义项少 1 ⇒ 隐藏差额多 1
    # 🔴 P27：关系层那一半。锚要另挑一条**带可出版关系**的义项。
    _s27 = pick["p27"]
    ok &= one("P27", "🔴 隐藏一条带可出版关系的义项（同一个洞的关系层那一半）",
              lambda c: c.execute("UPDATE sense SET hidden=1, hidden_why='mutant' "
                                  "WHERE id=?", (_s27[0],)),
              lambda c: c.execute("UPDATE sense SET hidden=?, hidden_why=? WHERE id=?",
                                  (_s27[1], _s27[2], _s27[0])),
              also=("P1",))
    # 🔴 P28：把一条折叠放回来 ⇒ 页面上那条义项又重复出现。
    _s28 = pick["p28"]
    ok &= one("P28", "🔴 把一条被折叠的义项放回出版层（页面上那条义项又重复）",
              lambda c: c.execute("UPDATE sense SET hidden=0, hidden_why=NULL, "
                                  "merged_into=NULL WHERE id=?", (_s28[0],)),
              lambda c: c.execute("UPDATE sense SET hidden=1, hidden_why=?, "
                                  "merged_into=? WHERE id=?",
                                  (DUP_SENSE_WHY, _s28[1], _s28[0])),
              # ⚠️ 放回来之后它既不再被折（P28 少 1），又成了可见义项（P1 少 1）。
              also=("P1",))
    # 🔴🔴 P25：往 `example_gloss` 塞一条**追不回答案文件**的付费译文。
    #    这是「我敢删付费数据」那个决定的前提被破坏的样子。
    _e25 = pick["p25"]
    assert _e25 is not None, "找不到一条 id 不在答案文件里的可出版例句 —— 换个锚"
    ok &= one("P25", "🔴🔴 塞一条 id 不在答案文件里的付费译文（追不回源头的付费数据）",
              lambda c: c.execute(
                  "INSERT INTO example_gloss (example_id, lang, text, src) "
                  "VALUES (?,'en','mutant','model:mutant')", (_e25,)),
              lambda c: c.execute("DELETE FROM example_gloss WHERE src='model:mutant'"))

    # R0：展示层的带锁豁免 —— **代码侧变异**（真去建那个文件代价太大且会污染仓库）
    # 🔴🔴 **2026-10-03：这条变异的前提过期了，而它报的是「没逮到」。**
    #    R0 的判据是 `DISPLAY.exists() and not READ_PATH`。带锁豁免兑现之后
    #    `READ_PATH` 填进了 10 条 ⇒ 后半句永远为假 ⇒ 光把 `exists` 打成 True
    #    **再也不可能让它红**。
    # ⚠️ 这是**前提过期，不是锚过期** —— 与账的闸 V4 那次一模一样
    #    （`if "5" in done: return []` 在阶段 5 落成 ✅ 之后永远先返回）。
    #    **变异必须把它自己的前提也打掉**，否则它验的是「这条检查还在不在」，
    #    而不是「这条检查逮不逮得到东西」。
    # ⇒ 两个条件一起翻：文件存在 **且** `READ_PATH` 清空；再加一条反控制。
    global READ_PATH
    import unittest.mock as _m
    _saved = READ_PATH
    READ_PATH = []
    try:
        with _m.patch.object(Path, "exists", lambda self: True):
            hit0 = {x for x, _n, _g, _w, _y in run_all_safe()}
    finally:
        READ_PATH = _saved
    good0 = "R0" in hit0
    ok &= good0
    print("   %s R0    展示层文件一出现而 `READ_PATH` 还空着（前提一并翻掉）"
          % ("✅" if good0 else "🔴 没逮到"))
    # ⭐ 反控制：前提**不翻**的时候它必须**不响**，否则这条检查是恒红的
    #    （`[[permanently-red-gate-masks-real-reds]]`：恒红的闸信号量是零）。
    with _m.patch.object(Path, "exists", lambda self: True):
        hit0b = {x for x, _n, _g, _w, _y in run_all_safe()}
    good0b = "R0" not in hit0b
    ok &= good0b
    print("   %s R0    反控制：`READ_PATH` 填着的时候它不该响"
          % ("✅" if good0b else "🔴 恒红"))

    # 总量回核
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n1 = {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in n0}
    con.close()
    drift = {t: (n0[t], n1[t]) for t in n0 if n0[t] != n1[t]}
    print("   %s 还原回核：十一张表行数%s"
          % ("✅" if not drift else "🔴🔴",
             " 全部复原" if not drift else "**没复原** %s" % drift))
    return ok and not drift


def run_all_safe():
    """只跑 R0（给变异用；`Path.exists` 被 patch 时别去碰库）。"""
    return [(c, n, g, w, y) for c, n, g, w, y in r0_read_path()]


def main():
    if "--mutate" in sys.argv:
        raise SystemExit(0 if mutate() else 1)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = run_all(con)
    print("■ vi 回归闸：%d 条（过去每一个修复现在还在不在）" % len(rows))
    red = []
    for cid, name, got, want, _why in rows:
        mark = "✅" if got == want else "🔴"
        print("   %s %-5s %-48s %10s（期望 %s）" % (mark, cid, name[:48], F(got), F(want)))
        if got != want:
            red.append(cid)
    t, se, ours = COV.blank_split(con)
    print("\n   ── 空白页分两类：**源头也没给 %s** ／ 我们没印 %s（修法在展示层，W15）"
          % (F(se), F(ours)))
    print("   ── 读取路径那一半：%s"
          % ("⚠️ 展示层还不存在 ⇒ 带锁豁免（R0 会在它出现时判红）"
             if not DISPLAY.exists() else "%d 条" % len(READ_PATH)))
    con.close()
    if red:
        print("\n🔴 红 %d 条：%s" % (len(red), "、".join(red)))
    else:
        print("\n   ✅ 全绿（每一个修复都还在）")
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
