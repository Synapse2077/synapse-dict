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

import sqlite3                                                     # noqa: E402

import paths                                                       # noqa: E402
import coverage as COV                                             # noqa: E402
import stage6_sources as S6                                        # noqa: E402
from criteria import (gloss_has_content, is_han_headword,           # noqa: E402
                      is_vi_markup_gloss, norm_vi)

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
     "SELECT COUNT(*) FROM sense WHERE hidden = 0", 186,
     "差额 186 ＝ W12 判掉的（141 条纯标点 ＋ 45 条源头词典标记缩写）。"
     "🔴 这两个数**必须一起锁**：只锁展示层那个数的话，判据被整个关掉时它会"
     "**变大**，而「变大」看起来像修好了"),

    ("P2", "例句：写入列 vs 展示层（`x.hidden = 0`）",
     "SELECT COUNT(*) FROM example",
     "SELECT COUNT(*) FROM example WHERE hidden = 0", 1326,
     "差额 1,326 ＝ 喃字正文 1,208 ＋ 整条就是词本身 71 ＋ **ko 版韩语标签行 45** ＋ 2。"
     "🔴🔴 那 45 条是 **2026-10-03 把例句渲染出来才看见的** —— 数据层五道闸全绿，"
     "而页面上印着 `같은 말 : yêu thương`（韩语的「同义词」标签）。"
     "同一轮还切掉了 2,381 处内嵌在 `text` 里的韩语译文"),

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
     " AND TRIM(ref) <> ''", 5088,
     "vi 版 709 条 `translation` 里一条真译文都没有 ⇒ 那批进了 `ref`。"
     "展示层印成「出处：…」，**不许排在译文位置**。"
     "🔴 **基线从 6,005 改成 5,088（2026-10-03），原因**：展示层契约闸逮到 `ăn` 页面上"
     "印着「出处：창세기 2장 9절」（创世记 2 章 9 节）—— 切掉内嵌外语那一步我只用在 "
     "`text` 上、**`ref` 漏了**（判据漏用）。新增判据 `S6.ref_is_unreadable()`："
     "**一个拉丁字母都没有 ⇒ 对中文读者不可读 ⇒ 不发布**，去掉 917 条"
     "（韩语版圣经章节号 682 ＋ vi 版整串是 `.` 的 225 ＋ 其余 10）。"
     "⚠️ 判据**不是「含韩文就切」** —— 那会截断 56 条以拉丁为主、夹着原文人名的"
     "正当引文（`2021, Han Kang, …`），而**一条截断的引文比一条读不懂的更坏**"),

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
    out.append(("R1", "空白页总数（读者口径：点进去什么都没有）", total, 222,
                "🔴 **已接受基线 222，而这个数的解释比数字重要**：实测 222 个里"
                "**222 个在证据层都有指针义项**（`UBND`=Ủy ban Nhân dân、"
                "`giấu diếm`/`dấu diếm`、`ôtô`、`São Tomé`）—— 源头明明说了"
                "「X 是 Y 的异写/缩写」，**而那正是读者要看的那句话**，我们没印。"
                "📋 修法在展示层（把指针印成链接）⇒ 欠账 **W15**，归阶段 9，"
                "那时这个基线该掉到接近 0。"
                "⚠️ 判据见 `pipeline/coverage.py`，**每加一条判据这个数都会降，"
                "那不是修好了是口径变了**"))
    out.append(("R1b", "🔴 其中「源头也没给」的", src_empty, 0,
                "`[[dont-say-source-lacks-what-we-skipped]]`：「源头没写」和"
                "「我们没抽」**必须在结构上分开**。只报一个总数的话，"
                "「我们没印」会被当成「源头没有」—— 而那是会写进验收报告的谎。"
                "这一条是 0 ⇒ 现在**没有任何一页是源头的锅**"))

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


def mutate():
    """变异验证：每条检查**真的逮得到东西**。

    🔴 动真库，注入后立即还原（与外锚闸同一个做法）。末尾有总量回核。
    ⚠️ 不是每条都能变异：`R17`（有意不建的表）要建表，`R12`/`R16` 是基线型
       （改一行就偏离 ⇒ 用 UPDATE 制造偏离即可）。
    """
    base = check_brief()
    if base:
        print("🔴 基线就不绿，变异验证没有意义：")
        for c, w in base:
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
            hit = {x for x, _ in check_brief()}
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
                                  (pick["rel_h"][0],)))
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
              lambda c: c.execute("DELETE FROM pronunciation WHERE src_ref='pron:MUTANT'"))
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
                                  (pick["ss"][0],)))
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
    hit = {x for x, _ in check_brief()}
    c = sqlite3.connect(paths.DB)
    c.execute("DROP TABLE inflection")
    c.commit()
    c.close()
    good = "R17" in hit and hit == {"R17"}
    ok &= good
    print("   %s R17   手建 `inflection`（有意不建的那三张之一）%s"
          % ("✅" if good else ("🔴 连带未声明" if "R17" in hit else "🔴 没逮到"),
             ("   🔴 **未声明的连带 %s**" % "、".join(sorted(hit - {"R17"}))) if hit - {"R17"} else ""))

    # R0：展示层的带锁豁免 —— **代码侧变异**（真去建那个文件代价太大且会污染仓库）
    global READ_PATH
    import unittest.mock as _m
    with _m.patch.object(Path, "exists", lambda self: True):
        hit0 = {x for x, _n, _g, _w, _y in run_all_safe()}
    good0 = "R0" in hit0
    ok &= good0
    print("   %s R0    展示层文件一出现而 `READ_PATH` 还空着" % ("✅" if good0 else "🔴 没逮到"))

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
