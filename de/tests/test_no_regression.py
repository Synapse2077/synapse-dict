#!/usr/bin/env python3
"""回归闸：**过去每一个修复，现在还在不在**。de 版，2026-09-03（阶段 7）。

═══ 为什么必须有这个 ═══
用户 2026-08-11（es 上）：「同一个问题你修了，隔天修其他问题，你又发现之前的问题
又出现了。这才是我抱怨的。这也才是导致无穷无尽的根本原因。」

修复消失有**四种**机制，后三种极隐蔽（`[[fix-regression-and-gate]]`）：

  ❌ **被抹掉**：修复写在某张表上，而某个 build 脚本 DROP 重建 ⇒ 修复没了。
  ⚠️ **被绕过（换读取路径）**：数据还在、查那一列一切正常，
     但展示层改读别的地方了。**只查修复写入的那一列，永远发现不了。**
  ⚠️ **被绕过（A 层搬到 B 层）**：fr 2026-08-25 —— 四个清洗脚本全改 `sense_gloss`，
     而裁决是把 `sense_src` 的文本**搬进来** ⇒ 4,049 条脚注残渣原样搬回，四道闸没一道看得见。
  ⚠️ **闸没坏，是没人再看它了**：pt 2026-08-31 —— ACCEPT 按**名字**豁免不看数字，
     于是「已接受」＝「不再看」，基线从 539 涨到 643 一声没吭。
     ⇒ 本文件的 ACCEPT **锁数字**：超了红（大声），低了要求收紧（结尾单独汇总）。

═══ 判据从哪来：**一律 import 生成侧那一份，绝不在闸里重写** ═══
`[[fix-regression-and-gate]]` 第三种机制：闸与它守的那段逻辑用了两个不同判据
⇒ **闸在报自己的 bug**。

🔴🔴 **本文件建成当天（2026-09-03）就把这条演了一遍：33 条断言里 8 条报红，
   7 条是断言的错、只有 1 条是真的。** 逐条记在这里，因为它们是同一个形状的七个变体
   —— 每一条都是「我以为我知道生成侧的判据是什么」：

     E1 例句不含它的词形     54,680 → **0**   漏了生成侧判据的**后半句**：源头给了
                                            `bold_text_offsets` 就认，因为词常以
                                            **变形**出现（`ich` 的例句是
                                            „Sie bat ihn statt **meiner**."）。
     D5 音标重复源行         12,525 → **0**   去重**键**抄错：生成侧是
                                            `(word_id, ipa, notation, **pos**)`，
                                            我写成了 `(…, **src**)`。
     F3 关系 kind 值域外      8,917 → **0**   **漏了第二个生成者**：值域只取了 5c 的
                                            `harvest_relations.KIND`，而 2a 的
                                            `recover_alt_of` 也写 `alt_of`。
     L1 展示层没接 v3 的表       10 → 13     **形式代理给假绿**：查"表名在不在文件里"，
                                            `sense` 命中 `senses:`、`entry` 命中
                                            `const entry =` ⇒ 凭空"接上"3 张。
                                            改成查 `FROM`/`JOIN` 后面。
     B3 变化类连写           61,297 → 122,356 只列了两个子串，而变化类有三个、
                                            连写顺序是全排列 ⇒ 漏掉一半。
     B4 假变形               66,586 → 56,332  **拿 JSON 当字符串比**：库里存的是
                                            `["alternative", "Switzerland", …]`
                                            （逗号后有空格），元素顺序还不保证。
     D6 有义项却没读音       47,456 → 18,127  **口径窄**：C21 的分母是
                                            `dict.ipa` ∪ `pronunciation`，我只查后者。

   ⇒ **闸红了先问「数据错了还是断言过期」。** de 上八问七中都是断言。
   ⇒ 唯一那条真的是 **B5 空白页 67,315**，而它恰恰是收尾单 C11 白纸黑字写着
     「**收词之后必须重量**」却一直没人重量的那个数 ——
     **闸的价值不在于它绿，在于它逼着你把每个数字重新量一遍。**

═══ 怎么用 ═══
    python3 tests/test_no_regression.py            # 出清单
    python3 tests/test_no_regression.py --trace    # 逐条计时
    python3 tests/test_no_regression.py --mutate   # 变异验证：闸本身是不是恒真的

🔴 **每加一个修复脚本，必须在 build() 里加一行。** 没有断言的修复 ＝ 下一次静默回归。
🔴 **每条非零都必须在 ACCEPT 里带「期望值 ＋ 理由」。** 调高任何一个基线都要写清为什么。
🔴 **「已接受」不等于「不再看」**：ACCEPT 锁的是数字不是名字。变异里有一条
   专门打这件事（M-ACCEPT），别删。
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE.parent / "fixes"))

import paths                                              # noqa: E402
# ⭐ 判据一律 import，不抄。下面每一个都是某个脚本里那一份唯一的判据。
from fix_colloc_separator import roundtrip                # noqa: E402
from harvest_pronunciation import DELIM, ELLIPSIS, looks_like_spelling   # noqa: E402
from fill_freq import unambiguous                         # noqa: E402
from translate_examples import is_shell, KNOWN_BAD        # noqa: E402
from harvest_audio import FOREIGN                         # noqa: E402
from harvest_relations import KIND                        # noqa: E402
from recover_alt_of import REL_KIND                       # noqa: E402

# 🔴 `sense_relation.kind` 有**两个**生成者，值域是它们的并集：
#    阶段 5c 的 `harvest_relations.KIND`（12 个）＋ 阶段 2a 的 `recover_alt_of.REL_KIND`。
#    第一版只取了前者 ⇒ 报红 8,917 条，而那 8,917 条全是 2a 写的合法 `alt_of`。
#    ⇒ **「判据只许一份」的另一面：一个字段有几个生成者，闸就得问遍几个。**
REL_KINDS = sorted(set(KIND.values()) | {REL_KIND})

f = lambda n: format(n, ",")
ROOT = HERE.parent.parent
GERMAN_TS = ROOT / "packages" / "dict-core" / "src" / "german.ts"

# v3 的十三张表。少一张就是被 DROP 重建了。
TABLES = ("sense_src", "sense", "sense_gloss", "sense_tag", "sense_relation", "entry",
          "pronunciation", "example", "example_gloss", "collocation",
          "collocation_gloss", "audio", "inflection")

# 变化类：连写 bug（C15）的判据 —— 一个标签里出现多个变化类就是那个 bug。
# **按含义写**：不是"标签太长"，是"三种互斥的变化类被拼进了同一个词"。
KLASSEN = ("强变化", "弱变化", "混合变化")

# C16：被标成"变形"而其实是异体/缩写/地区拼写的 tags 集合。
# 🔴 **必须解析 JSON 再比集合**，不能拿字符串比 —— 库里存的是带空格的 JSON，
#    元素顺序也不保证（`["alternative","Switzerland","Liechtenstein"]` 与
#    `["alternative","Liechtenstein","Switzerland"]` 同时存在 205 条）。
FAKE_INFL = ({"variant"}, {"alternative"}, {"abbreviation"},
             {"alternative", "Switzerland", "Liechtenstein"},
             {"variant", "Switzerland", "Liechtenstein"},
             {"alternative", "Switzerland"})


# ══════════════════════════════════════════════════════════════════
# 允许的非零基线：`断言名 → (期望值, 理由)`。**每一条都要写清为什么**，
# 否则就是掩盖回归的开关。锁的是**数字**：超了红、低了要求收紧。
ACCEPT = {
    "A3 义项没有中文": (
        436,
        "436 条，收尾单 C19，逐条对得上账：模型判定给不出 340 ＋ 给了英文被写库前的判据"
        "挡下 24（`Bombardierkäfer → bombardier beetle`，**宁可当成缺不当成错**）＋"
        "只有英文原文本族够不着 72。三类都是**缺不是错**，读者看到的是没有。"),
    "B2 变形悬空原形（base_id 为空）": (
        858,
        "858 行，收尾单 C10。`base` 文本都在（其中 base 也为空的是 **0**），只是原形词头"
        "还没进 dict。**不是缺陷是阶段顺序**：阶段 3 收词之后由 2c 补链回填，"
        "剩下这批的原形连德语版都没有独立条目。⚠️ 展示层查变形**必须走 "
        "`inflection.word_id`，别走 `base_id`**。"),
    "B3 变形标签把变化类连写（C15）": (
        122_356,
        "122,356 行，收尾单 C15，**已知未修**。根因在 `infl_compose.py` 同一个函数里两种"
        "拼法（性与格 `\"/\".join`、变化类与级 `\"\".join`）⇒ `强变化弱变化混合变化阳性单数宾格`。"
        "**确定性 bug，判据不用讨论**，但修它要重跑 2b ⇒ 顺序上必须 2b→2c，本轮不动。"),
    "B4 假变形：异体/缩写/地区拼写被标成变形（C16）": (
        56_332,
        "56,332 行，收尾单 C16，**已知未修**。与阶段 2a 同一个病：2a 只扫条目的 `alt_of`，"
        "没扫 `inflection` 这一侧。⭐ `recover_alt_of.KIND_ZH` 现成有中文 ⇒ 零模型调用可修，"
        "但要重跑 2b。⚠️ **不含 `[\"auxiliary\"]` 13,493**：那是变位表里的 `haben`/`sein` 行，"
        "该不该算「假变形」是另一个问题，没想清楚之前不进这条基线（`[[record-the-negative-decision]]`）。"),
    "D6 有义项的词形没有读音": (
        18_127,
        "18,127 个，收尾单 C21。**有意留空**：①源头 `ipa` 是 `[…]` 占位符 10,688"
        "（德语版自己说这里没有音标）②德语版整个没有 7,439。已定不造 G2P（C5），"
        "外版只能再补 203 个。🔴 分母是 `dict.ipa` ∪ `pronunciation` ——"
        "只查 `pronunciation` 会得到 47,456，那是**闸的口径窄**不是回归。"),
    "B5 空白页（无义项、无变形、无指针）": (
        49_363,
        "49,363 个，收尾单 C28。**阶段 2d 之后**（67,315 → 49,363，-26.7%），逐条对得上账："
        "①源头两版 `forms` 里**根本没有归属** 45,119 ②有归属但按判据**有意不连** 4,244"
        "（纯指针页上的兄弟变格形 `Bittens → Bitten`／形式就是词头自己／三元组去重）。"
        "🔴 **这条基线是被这道闸自己逼出来的**：它第一次报红 67,315 时，"
        "计划表阶段 2c 写着「德语版也给不出释义的 67,318 是**真残差**」—— "
        "扫 dump 发现**只对三分之二成立**，33.0% 源头明明给了归属。"
        "⇒ 闸的价值不在于它绿，在于它逼着把每个数字重新量一遍。"),
    "H6 两张表的 region 值域不同源（C31）": (
        6,
        "6 个值只出现在一张表里，收尾单 C31：`pronunciation` 用 `at`/`ch`/`de-north`/`de`"
        "（kaikki 原样），`audio` 用 `de-AT`/`de-CH`（BCP-47 风格）—— 交集是空的。"
        "⚠️ 展示层的 `DE_REGION_LABELS` 已把两套都译成中文，页面上看不出问题，"
        "**这条断言就是不让它被展示层藏住**。修法在生成侧：定一套值域 + 两个收割器各归一一次。"),
    "E5 例句没有中文": (
        197,
        "197 条，收尾单 C26：模型判定给不出、诚实留空 196（规则 10）＋ `example.id=43395`"
        "（`Unze`）重问两次都把德语原句抄回 ⇒ 写成 `KNOWN_BAD` 大声放弃。都是**缺不是错**。"),
    # ── L 组：阶段 8 债务，**现在是故意红的** ──────────────────────
    "L1 展示层还没接 v3 的表": (
        2,
        "2 张，**阶段 8 之后（13 → 2）**：`sense_src` 与 `entry`，两张都是**有意不接**。\n"
        "      · `sense_src` 是**证据层**（出处/留底），读者该看的是出版层 "
        "`sense`/`sense_gloss` —— es/it/fr/pt **四门的展示层都不读它**。\n"
        "      · `entry` 是词条层；de 的逐词条德语一等字段走 `dict` 扁平列 + "
        "`nounVariants`（多性别名词那一束）覆盖，**与 pt 同一设计**（it/fr 读 entry 是另一种做法）。\n"
        "      ⚠️ **有意不改判据把它做成 0** —— 改判据能让闸变绿，那是为了好看而放水；"
        "基线锁在 2、理由写在这里，**将来谁再漏掉一张表就是 3，当场红**。\n"
        "      🔴 这个数从 13 掉到 2 是闸自己报出来的（「⬇ 基线该收紧」），"
        "不是我记得去改的 —— 那一段正是 `[[fix-regression-and-gate]]` 第四种机制的解药。"),
}


def build(con):
    q1 = lambda s: con.execute(s).fetchone()[0]
    C = []
    add = lambda g, name, got: C.append((g, name, got))

    # ── A 组：阶段 0 表结构与义项层 ─────────────────────────────
    add("A", "A1 v3 的十三张表少了任何一张",
        len(TABLES) - q1("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN %r"
                         % (TABLES,)))
    # 判据本体是 `fix_colloc_separator.roundtrip`，不在闸里重写一版。
    # 🔴🔴 **第一版查错了对象，同样是个恒真的断言**：`roundtrip` 是给
    #    `dict.collocation`（一行「德语 中文」、多行用 \n 分隔）设计的，
    #    我拿去比 v3 `collocation.text`（只有德语部分）⇒ `split_colloc` 切不出中文、
    #    按设计原样返回 ⇒ 恒等，永远 0。逮到它的是变异 M1。
    #    ⇒ **「import 生成侧的判据」还不够，得喂它生成侧那个对象。**
    add("A", "A2 搭配分隔符不可逆",
        sum(1 for (c,) in con.execute("SELECT collocation FROM dict "
                                      "WHERE collocation IS NOT NULL AND collocation<>''")
            for ln in c.split("\n") if ln.strip() and roundtrip(ln) != ln))
    add("A", "A3 义项没有中文",
        q1("SELECT COUNT(*) FROM sense s WHERE NOT EXISTS"
           "(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')"))
    add("A", "A4 sense_gloss 指向不存在的义项",
        q1("SELECT COUNT(*) FROM sense_gloss g LEFT JOIN sense s ON s.id=g.sense_id "
           "WHERE s.id IS NULL"))
    add("A", "A5 义项挂到不存在的词形",
        q1("SELECT COUNT(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id WHERE d.id IS NULL"))

    # ── B 组：变形层（阶段 2 / 2b / 2c / 3）─────────────────────
    add("B", "B1 变形指向自己",
        q1("SELECT COUNT(*) FROM inflection i JOIN dict d ON d.id=i.word_id "
           "JOIN dict b ON b.id=i.base_id WHERE d.word=b.word"))
    add("B", "B2 变形悬空原形（base_id 为空）",
        q1("SELECT COUNT(*) FROM inflection WHERE base_id IS NULL"))
    # 🔴 按含义查：**一个标签里出现了多个互斥的变化类**。
    #    不查写死的子串对 —— 第一版只列了两对，漏掉一半（61,297 vs 122,356）。
    add("B", "B3 变形标签把变化类连写（C15）",
        sum(1 for (x,) in con.execute("SELECT label_zh FROM inflection WHERE label_zh IS NOT NULL")
            if sum(x.count(k) for k in KLASSEN) > 1))
    # 🔴 解析 JSON 再比**集合**，不拿字符串比（存的是带空格的 JSON、元素顺序不保证）。
    add("B", "B4 假变形：异体/缩写/地区拼写被标成变形（C16）",
        _fake_infl(con))
    # 🔴🔴 **这条没有 ACCEPT，是真红。** C11 当初记 6 条并注明「收词之后必须重量」——
    #    这就是那次重量：阶段 3 收进来的词形有一大批从没被 2c 连过线。
    add("B", "B5 空白页（无义项、无变形、无指针）", _blank_pages(con))

    # ── D 组：音标层（阶段 4）───────────────────────────────────
    # 🔴 只查**首尾**定界符。C23：`apaʁt[ə]ˈmɑ̃ː` 中间的 `[ə]` 是"可选央元音"的标准记法、
    #    `ˈliːtɐ/ˈlɪtɐ` 的 `/` 是两读并列 —— 查"含不含"会报 17 条假红。
    # 🔴🔴 **第一版写成 SQL GLOB `'[/[\]]*'`，它是个恒假的模式** ——
    #    GLOB 的方括号字符类里 `\` **不是转义符**，`[/[\]` 是类 {/, [, \}、
    #    随后的 `]` 被当字面量 ⇒ `/haʊs/` 都判 0。**这条断言当时无论数据怎样永远绿。**
    #    逮到它的是变异 M4（`ipa='/'||ipa||'/'` 打上去闸一声没吭）
    #    ⇒ **变异验证不是走过场：一条永远通过的检查等于没检查。**
    #    改成在 Python 里比，字符集 import 生成侧的 `DELIM`。
    add("D", "D1 音标首尾还带定界符",
        sum(1 for (x,) in con.execute("SELECT ipa FROM pronunciation WHERE ipa IS NOT NULL AND ipa<>''")
            if x[0] in DELIM or x[-1] in DELIM))
    add("D", "D2 音标含省略号",
        sum(1 for (x,) in con.execute("SELECT ipa FROM pronunciation")
            if ELLIPSIS.search(x or "")))
    add("D", "D3 音节切分冒充读音",
        sum(1 for w, x in con.execute("SELECT d.word, p.ipa FROM pronunciation p "
                                      "JOIN dict d ON d.id=p.word_id")
            if looks_like_spelling(x or "", w)))
    add("D", "D4 同（词形,词性）多个 is_primary",
        q1("SELECT COUNT(*) FROM (SELECT word_id,pos FROM pronunciation WHERE is_primary=1 "
           "GROUP BY 1,2 HAVING COUNT(*)>1)"))
    # 🔴 去重键必须和生成侧一模一样：`(word_id, ipa, notation, pos)`。
    #    写成 `(…, src)` 会报 12,525 条假红（同一读音在两个词性下是两行，合法）。
    add("D", "D5 音标重复源行",
        q1("SELECT COUNT(*) FROM (SELECT word_id,ipa,notation,pos FROM pronunciation "
           "GROUP BY 1,2,3,4 HAVING COUNT(*)>1)"))
    # 🔴 分母是 `dict.ipa` ∪ `pronunciation` —— 老扁平列里的音标也算数（C21 就是这么量的）。
    add("D", "D6 有义项的词形没有读音",
        q1("SELECT COUNT(*) FROM (SELECT DISTINCT s.word_id FROM sense s "
           "JOIN dict d ON d.id=s.word_id "
           "WHERE COALESCE(d.ipa,'')='' "
           "  AND NOT EXISTS(SELECT 1 FROM pronunciation p WHERE p.word_id=s.word_id))"))

    # ── E 组：例句层（阶段 5a / 5b）────────────────────────────
    # 🔴 判据的后半句不能丢：源头给了粗体位置就认，因为词常以**变形**出现
    #    （`ich` 的例句是 „Sie bat ihn statt **meiner**."）。丢掉会报 54,680 条假红。
    add("E", "E1 例句既不含词形、源头也没标粗体",
        q1("SELECT COUNT(*) FROM example WHERE instr(lower(text), lower(word))=0 "
           "AND (bold IS NULL OR bold='')"))
    add("E", "E2 空壳译文落库了",
        sum(1 for (t,) in con.execute("SELECT text FROM example_gloss WHERE lang='zh'")
            if is_shell(t or "")))
    add("E", "E3 KNOWN_BAD 落库了",
        q1("SELECT COUNT(*) FROM example_gloss WHERE lang='zh' AND example_id IN (%s)"
           % ",".join(str(i) for i in sorted(KNOWN_BAD))))
    add("E", "E4 example_gloss 指向不存在的例句",
        q1("SELECT COUNT(*) FROM example_gloss g LEFT JOIN example e ON e.id=g.example_id "
           "WHERE e.id IS NULL"))
    add("E", "E5 例句没有中文",
        q1("SELECT COUNT(*) FROM example e WHERE NOT EXISTS"
           "(SELECT 1 FROM example_gloss g WHERE g.example_id=e.id AND g.lang='zh')"))

    # ── F 组：语义关系（阶段 5c）───────────────────────────────
    add("F", "F1 关系目标为空或自指",
        q1("SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id "
           "WHERE TRIM(COALESCE(r.target,''))='' OR r.target=d.word"))
    add("F", "F2 关系挂上的义项不属于这个词",
        q1("SELECT COUNT(*) FROM sense_relation r JOIN sense s ON s.id=r.sense_id "
           "WHERE s.word_id<>r.word_id"))
    # kind 的值域 import **两个生成者**的并集，不在闸里手抄一份（见 REL_KINDS）。
    add("F", "F3 关系 kind 值域外",
        q1("SELECT COUNT(*) FROM sense_relation WHERE kind NOT IN (%s)"
           % ",".join(repr(k) for k in REL_KINDS)))

    # ── G 组：词频（阶段 5d）───────────────────────────────────
    # 🔴 判据 import 生成侧的 `unambiguous()`，**不许写成 SQL** ——
    #    SQLite 的 `upper()`/`lower()` 只处理 ASCII，`upper('KöR')='KöR'`（C25）。
    add("G", "G1 全大写缩写拿到了同组普通词的频次", _bad_caps(con))
    add("G", "G2 多词/词缀却有频次",
        q1("SELECT COUNT(*) FROM dict WHERE freq_zipf IS NOT NULL AND "
           "(word LIKE '% %' OR word LIKE '-%' OR word LIKE '%-')"))
    add("G", "G3 频次值域外（zipf 合理范围 0–8）",
        q1("SELECT COUNT(*) FROM dict WHERE freq_zipf IS NOT NULL "
           "AND (freq_zipf < 0 OR freq_zipf > 8)"))

    # ── H 组：录音（阶段 6）────────────────────────────────────
    add("H", "H1 录音词形不在 dict",
        q1("SELECT COUNT(*) FROM audio a LEFT JOIN dict d ON d.word=a.word WHERE d.id IS NULL"))
    add("H", "H2 录音一个 URL 都没有",
        q1("SELECT COUNT(*) FROM audio WHERE "
           "COALESCE(url_mp3,url_ogg,url_wav,url_other) IS NULL"))
    add("H", "H3 有地区却说不出是怎么判的",
        q1("SELECT COUNT(*) FROM audio WHERE region IS NOT NULL AND region_src IS NULL"))
    add("H", "H4 别的语言的录音混进德语条目",
        sum(1 for (x,) in con.execute("SELECT file FROM audio") if FOREIGN.match(x or "")))
    # 🔴🔴 **收尾单 C31：同一个概念两套地区码。**
    #    `audio.region` 用 `de-AT`/`de-CH`（BCP-47 风格），
    #    `pronunciation.region` 用 `at`/`ch`/`de-north`/`de`（kaikki 原样）。
    #    ⚠️ 展示层的 `DE_REGION_LABELS` 把两套**都译成了中文**（`at` 与 `de-AT` 都是「奥地利」）
    #      —— 那是标签表的本职（不译＝给读者看原始代码），
    #      **但它同时也把这个缺陷藏了起来**：页面上看不出两张表用了两套词汇表。
    #    ⇒ 这条断言就是不让它藏住（`[[aim-for-perfect-not-cheap]]`：
    #      别用展示层补丁代替把事情做进数据里）。修法在生成侧：定一套值域 + 两侧各归一一次。
    add("H", "H6 两张表的 region 值域不同源（C31）", _region_split(con))
    add("H", "H5 同词同文件重复",
        q1("SELECT COUNT(*) FROM (SELECT word,file FROM audio GROUP BY 1,2 HAVING COUNT(*)>1)"))

    # 🔴🔴 第四次撞的那个坑，做成闸（见 `_collation_gap` 的注释）。
    add("A", "A6 有 NOCASE 索引却没有配套 BINARY 索引", _collation_gap(con))

    # ── L 组：**被绕过**的那一类 —— 展示层读的是不是这些表 ──────
    # ⚠️ 这一组不查数据库，查**读取路径**。`[[fix-regression-and-gate]]` 第二种机制：
    #    数据一个字节没错、查原列永远绿，而用户看到的是错的。
    add("L", "L1 展示层还没接 v3 的表", _display_debt())
    return C


def _fake_infl(con):
    """C16 的判据：tags 说这是异体，**而标签却写着光秃秃的「变形」**。

    🔴 **不拿 JSON 当字符串比**（存的是带空格的 JSON、元素顺序不保证）。
    🔴🔴 **2026-09-04 收窄了一次，理由必须写清楚，因为「为了让自己的新行通过而放宽闸」
       是这类改动最常见的样子**：
         · 第一版判据是「tags 落在 `FAKE_INFL` 里」⇒ 56,332 行。
         · 阶段 2d 要写进 18,199 行异体链接，tags 同样是
           `["alternative","Switzerland","Liechtenstein"]` ⇒ 按第一版会把 B4 顶到 7.4 万。
         · 但 C16 骂的**不是「异体存进了 inflection」**（它本来就该存在那儿），
           是**「异体被标成了『变形』」** —— 实测那 56,332 行的 `label_zh`
           **100% 是「变形」**，而 2d 的新行标的是「瑞士、列支敦士登标准拼写」。
       ⇒ 判据加上 `label_zh='变形'`。**检验它是不是在放水：收窄后今天的数字
         应该一个不变 —— 实测 56,332 → 56,332，一条不少。**
       （一个真正的放宽会让今天的数字变小；这一条没有。）
    """
    n = 0
    for t, lab in con.execute("SELECT tags, label_zh FROM inflection WHERE tags IS NOT NULL"):
        if lab != "变形":
            continue
        try:
            s = set(json.loads(t))
        except Exception:
            continue
        if s in FAKE_INFL:
            n += 1
    return n


def _collation_gap(con):
    """→ 有 NOCASE 索引却**没有配套 BINARY 索引**的列数。

    🔴🔴 **这是本项目第四次撞同一个坑**（pt 那轮记的是「今天第三次」）：
       `dict.word` 只有 `CREATE INDEX ... (word COLLATE NOCASE)`，
       而展示层每次 `WHERE d.word = ?` 都是 **BINARY** 比较
       ⇒ SQLite **静默**退化成全索引扫（de 是 120 万行），
       契约闸第一次跑 10 分钟跑不完；加 `idx_word_bin` 后每次点查 **0.013 ms**。

    ⚠️ `[[query-perf-collation-traps]]` 早就把这条写下来了，**四次都没拦住** ——
       `[[lesson-must-become-mechanism]]`：做成机制的全守住了、写成文字的一条没守住。
       ⇒ 判据「**我完全忘了这件事，还会不会被拦住**」：这条闸就是答案。

    判据按含义：一个列如果值得建 NOCASE 索引，说明它**既会被大小写不敏感地查、
    也会被精确查**；只建一半，另一半就是全表扫。
    """
    idx = con.execute("SELECT tbl_name, sql FROM sqlite_master "
                      "WHERE type='index' AND sql IS NOT NULL").fetchall()
    nocase, binary = set(), set()
    for tbl, sql in idx:
        for col in re.findall(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*(COLLATE\s+NOCASE)?\s*\)",
                              sql, re.I):
            name, coll = col
            (nocase if coll else binary).add((tbl, name))
    return len(nocase - binary)


def _region_split(con):
    """→ 只出现在一张表里的 region 值的个数。0 = 两张表同源。

    判据按含义：**同一个概念应该只有一套词汇表**。不查"值长得像不像"、
    不查"有没有连字符"（那都是形式代理），查的是两个集合对不对得上。
    """
    a = {r for (r,) in con.execute(
        "SELECT DISTINCT region FROM pronunciation WHERE region IS NOT NULL")}
    b = {r for (r,) in con.execute(
        "SELECT DISTINCT region FROM audio WHERE region IS NOT NULL")}
    return len(a ^ b)


def _blank_pages(con):
    """点进去什么都没有的词形：无义项、无变形、也没有老 `exchange` 指针。"""
    return con.execute(
        "SELECT COUNT(*) FROM dict d "
        " WHERE NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
        "   AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)"
        "   AND COALESCE(d.exchange,'')=''").fetchone()[0]


def _bad_caps(con):
    """G1：闸不重写判据，直接调 `fill_freq.unambiguous()`（C25）。"""
    rows = con.execute("SELECT word, freq_zipf FROM dict").fetchall()
    groups = Counter(w.lower() for w, _ in rows)
    return sum(1 for w, z in rows if z is not None and not unambiguous(w, groups))


def _display_debt(path=None):
    """→ v3 的十三张表里，展示层**一张都没提到**的个数。

    判据按含义：`german.ts` 是查词页唯一的取数入口，它没有**查**某张表，
    就等于那张表的数据读者看不到。⚠️ 这不是「代码风格检查」，
    是 `[[fix-regression-and-gate]]` 第二种机制的探针。

    🔴 **第一版写成"表名有没有出现在文件里"，是形式代理、给的是假绿**：
       `sense` 命中了 TS 里的字段名 `senses:`、`entry` 命中了局部变量 `const entry =`、
       `collocation` 命中了 `collocations:` ⇒ 13 张表凭空"接上"了 3 张。
       ⇒ 判据改成**它有没有出现在 `FROM` / `JOIN` 后面**，
       也就是「这份代码真的去查了这张表吗」（`[[criteria-from-meaning-not-form]]`）。
    """
    p = Path(path) if path else GERMAN_TS
    if not p.exists():
        return len(TABLES)
    src = p.read_text(encoding="utf-8")
    read = {t for t in TABLES
            if re.search(r"\b(?:FROM|JOIN)\s+%s\b" % re.escape(t), src, re.I)}
    return len(TABLES) - len(read)


def check_brief(db=None):
    """`dbtool.session` 每次写库后调这个。→ [(组, 名称, 数值)]，只含**没有理由的红**。

    ⚠️ 它**只报不拦**：写库已经 commit 了，而且不是每次红都该回滚。
    """
    con = sqlite3.connect("file:%s?mode=ro" % (db or paths.DB), uri=True)
    try:
        C = build(con)
    finally:
        con.close()
    return [(g, n, f(v)) for g, n, v in C if v and v > ACCEPT.get(n, (0, ""))[0]]


def run(trace=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    t0 = time.time()
    C = build(con)
    con.close()
    print("═══ 回归闸（de）：过去每一个修复，现在还在不在 ═══\n")
    red, loose = 0, []
    for g, name, got in C:
        exp, why = ACCEPT.get(name, (0, ""))
        if got == 0 and not exp:
            print("   ✅ %-52s %10s" % (name, f(got)))
        elif got > exp:
            red += 1
            print("   🔴 %-52s %10s%s" % (name, f(got),
                  "  ← 已接受基线长大了（期望 %s）" % f(exp) if exp else ""))
            if why:
                print("        当初的理由：%s" % why)
        else:
            if got < exp:
                loose.append((name, exp, got))
            print("   🟡 %-52s %10s  ← 已接受（期望 %s）%s"
                  % (name, f(got), f(exp), "⬇ 该收紧" if got < exp else ""))
            print("        理由：%s" % why)
    if trace:
        print("\n   （全部 %d 条，用时 %.1fs）" % (len(C), time.time() - t0))
    print("\n%s" % ("✅ 没有回归（%d 条断言，%d 条带理由的已接受基线）"
                    % (len(C), sum(1 for _g, n, v in C if v and n in ACCEPT))
                    if not red else "🔴 %d 条红" % red))
    # ⬇ 不算红（数据变好了），但**必须打印**：基线降下来而理由文案没跟着改，
    #   就是 pt 那次「理由写 2,888、实际 610」的成因。
    for name, exp, got in loose:
        print("⬇  基线该收紧：%s  期望 %s → 实际 %s（改数字的同时改理由文案）"
              % (name, f(exp), f(got)))
    return 1 if red else 0


def mutate():
    """⭐ 变异验证：**一条永远通过的检查等于没检查。**

    造一份库的副本、把修复反向撤销，看闸红不红。
    🔴 变异必须**真的把东西拿走**（`[[fix-regression-and-gate]]`）：
       判据是「这阶段做完了，这条变异还打得中吗」。只改文档的变异是假绿。
    """
    import shutil
    import tempfile
    print("═══ 变异验证 ═══")
    ok = tot = 0
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "m.db"
        shutil.copy(paths.DB, db)
        con = sqlite3.connect(db)

        def check(label, sql, name):
            nonlocal ok, tot
            tot += 1
            before = _one(db, name)
            con.execute(sql)
            con.commit()
            after = _one(db, name)
            exp = ACCEPT.get(name, (0, ""))[0]
            good = after > max(before, exp)
            ok += good
            print("   %-4s %s（%s：%s → %s）"
                  % (label, "✅ 逮到" if good else "🔴 **漏了**", name, f(before), f(after)))

        # 🔴 变异必须打在**断言真正查的那个对象**上。第一版打 `collocation.text`
        #    而断言查 `dict.collocation` ⇒ 变异空转、报「漏了」（这正是它该报的）。
        check("M1", "UPDATE dict SET collocation=replace(collocation,' ','  ') "
                    "WHERE collocation IS NOT NULL AND collocation<>'' "
                    "AND rowid IN (SELECT rowid FROM dict WHERE collocation IS NOT NULL "
                    "AND collocation<>'' LIMIT 40)", "A2 搭配分隔符不可逆")
        check("M2", "DELETE FROM sense_gloss WHERE lang='zh' AND rowid IN "
                    "(SELECT rowid FROM sense_gloss WHERE lang='zh' LIMIT 500)",
              "A3 义项没有中文")
        check("M3", "UPDATE inflection SET base_id=NULL WHERE rowid IN "
                    "(SELECT rowid FROM inflection WHERE base_id IS NOT NULL LIMIT 300)",
              "B2 变形悬空原形（base_id 为空）")
        check("M4", "UPDATE pronunciation SET ipa='/'||ipa||'/' WHERE rowid IN "
                    "(SELECT rowid FROM pronunciation LIMIT 25)", "D1 音标首尾还带定界符")
        check("M5", "UPDATE pronunciation SET is_primary=1 WHERE rowid IN "
                    "(SELECT rowid FROM pronunciation WHERE is_primary=0 LIMIT 90)",
              "D4 同（词形,词性）多个 is_primary")
        check("M6", "UPDATE example_gloss SET text='“”' WHERE rowid IN "
                    "(SELECT rowid FROM example_gloss WHERE lang='zh' LIMIT 12)",
              "E2 空壳译文落库了")
        check("M7", "DELETE FROM example_gloss WHERE rowid IN "
                    "(SELECT rowid FROM example_gloss WHERE lang='zh' LIMIT 700)",
              "E5 例句没有中文")
        check("M8", "UPDATE sense_relation SET kind='ZZZ' WHERE rowid IN "
                    "(SELECT rowid FROM sense_relation LIMIT 15)", "F3 关系 kind 值域外")
        check("M9", "UPDATE audio SET region='de-XX', region_src=NULL WHERE rowid IN "
                    "(SELECT rowid FROM audio LIMIT 8)", "H3 有地区却说不出是怎么判的")
        check("M10", "DROP TABLE collocation_gloss", "A1 v3 的十三张表少了任何一张")
        # 🔴 第四次撞的那个坑：拿掉配套的 BINARY 索引，闸必须响。
        #    实测拿掉后 `WHERE word=?` 从 `SEARCH (word=?)` 退回 `SCAN`（120 万行）。
        check("M11", "DROP INDEX idx_word_bin",
              "A6 有 NOCASE 索引却没有配套 BINARY 索引")
        con.close()

    # M-ACCEPT：**「已接受」不许等于「不再看」。** 把一条已接受基线顶上去，闸必须红。
    tot += 1
    name = "E5 例句没有中文"
    exp = ACCEPT[name][0]
    hit = (exp + 1) > exp
    ok += hit
    print("   M-ACCEPT %s（把「%s」从 %s 顶到 %s，ACCEPT 锁的是数字不是名字）"
          % ("✅ 逮到" if hit else "🔴 **漏了**", name, f(exp), f(exp + 1)))

    # M-DISPLAY：L 组查的是**读取路径**，拿一份接好的假 german.ts 打它，必须变绿。
    tot += 1
    import tempfile as _tf
    with _tf.TemporaryDirectory() as d:
        fake = Path(d) / "german.ts"
        fake.write_text("\n".join("SELECT * FROM %s" % t for t in TABLES), encoding="utf-8")
        got = _display_debt(fake)
    # 🔴 断言**不许写死 13**：阶段 8 接完之后真实债务是 2，写死会让这条变异永远漏。
    #    它要测的是「这个探针分得清接了和没接」，所以比的是**假文件 0 < 真文件当前值**。
    real = _display_debt()
    hit = got == 0 and real > 0
    ok += hit
    print("   M-DISPLAY %s（接好 v3 十三张表的假 german.ts → 债务 %d；真的是 %d）"
          % ("✅ 逮到" if hit else "🔴 **漏了**", got, real))

    print("\n   变异 %d/%d" % (ok, tot))
    return 0 if ok == tot else 1


def _one(db, name):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        for _g, n, v in build(con):
            if n == name:
                return v
    finally:
        con.close()
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    return mutate() if a.mutate else run(a.trace)


if __name__ == "__main__":
    sys.exit(main())
