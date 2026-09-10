#!/usr/bin/env python3
"""回归闸：**过去每一个决定，现在还成不成立**。en 版，2026-09-08（阶段 7）。

═══ 为什么必须有这个 ═══
用户 2026-08-11（es 上）：「同一个问题你修了，隔天修其他问题，你又发现之前的问题
又出现了。**这才是导致无穷无尽的根本原因**。」

修复消失有**五种**机制（`[[fix-regression-and-gate]]`），后四种都不会报错：
被抹掉／换读取路径被绕过／A 层搬到 B 层／ACCEPT 按名字豁免＝不再看／变异自己过期。

═══ 三条纪律（照 de，一字不改） ═══
1. 🔴 **判据一律 `import` 生成侧那一份**，绝不在闸里重写一遍
   —— 闸与它守的逻辑一旦用两个判据，闸就在报自己的 bug。
2. 🔴 **`ACCEPT` 锁数字不锁名字**：`{名: (期望值, 理由)}`，超了红、低了要求收紧。
   pt 那轮 B4 从修好那天起没人再看，就是因为按名字豁免。
3. 🔴 **每加一条断言就补一条变异**，且变异必须**自己造缺陷**，
   不许依赖「库里恰好还没做完某件事」——那种前提会自己消失。

═══ en 独有的两件 ═══
⭐ **F 组是六门里唯一有的外锚**：核心 5.9 万词的 **ECDICT 人工中文**。
   它不是「正确答案」（`[[verify-before-claiming-confirmed]]`），是**负控** ——
   模型中文与人工中文**大面积对不上**才是信号，不是「不一致就算错」。
🔴 **D 组是 5e 当天新长出来的**：例句层刚花了 246 元，
   而它的三个缺陷（不是例句的行／出处粘正文／译文漏出处）全是**落库后抽读**才发现的。

    python3 tests/test_no_regression.py
    python3 tests/test_no_regression.py --mutate
"""
import sys as _sys
import pathlib as _pl
_ROOT = _pl.Path(__file__).resolve().parent.parent
_sys.path.insert(0, str(_ROOT))
_sys.path.insert(0, str(_ROOT / "pipeline"))
_sys.path.insert(0, str(_ROOT / "fixes"))

import re
import sqlite3

import paths

# 🔴 判据一律从生成侧取，不在这里重写
from build_ex_rel import KEEP, HIDDEN, DROP                     # noqa: E402
from hide_non_examples import WHERE as NOT_EXAMPLE              # noqa: E402
from split_quote_ref import YEAR, ref_leaked                    # noqa: E402
from translate_examples import SRC as EX_SRC                    # noqa: E402

TS = _ROOT.parent / "packages" / "dict-core" / "src" / "english.ts"
V3 = ("dict", "entry", "sense", "sense_src", "sense_gloss", "sense_tag",
      "sense_relation", "inflection", "pronunciation", "example", "example_gloss",
      "collocation", "collocation_gloss", "audio", "legacy_gloss", "field_src",
      "search_prefix")
CJK = re.compile(r"[㐀-䶿一-鿿]")
ANYYEAR = re.compile(r"(1[4-9]\d\d|20[0-2]\d)")

# ══════════════════ 已接受的基线：{名: (期望值, 理由)} ══════════════════
# 🔴 **锁数字**：超了红（回归），低了要求收紧（结尾单独汇总）。
#    「已接受」不等于「不再看」—— 基线长大恰恰是回归最常见的样子。
ACCEPT = {
    "A3 义项没有中文": (
        4_376,
        # 🔴 **2026-09-10 基线 4,332 → 4,376（+44），是一次有意的「错换缺」。**
        #    废除 1.5b「免费直接贴」、11,479 条改走 1.5c 重翻之后，模型对其中 44 条
        #    按规则 6（「释义看不懂或信息不足时输出空字符串」）留了空 ——
        #    这 44 条原来顶着一段**没验过内容**的 ECDICT 词条级原文
        #    （`Te` 的埃及冥界义顶着「[化] 碲；[医] 破伤风」那种）。
        #    ⇒ 方向与 `FRAMEWORK §一`「错比缺更伤权威」一致，**基线上调，理由落账**。
        #    ⚠️ 同一次改动把 `thy`（freq_rank 10,004）打成了「核心词一条中文都没有」，
        #       已由 `fixes/publish_legacy_when_no_zh.py` 放行 29 行词条级兜底补回，F1 回 0。
        #       —— **词条级的中文就该在词条级显示，别按义项贴。**
        "4,332 条，逐块对得上账：**指针义项 3,360**（`fill_pointer_gloss` 的模板拼不出，"
        "见 E3）＋**实义项 972**。那 972 条基本是**元描述型**释义 —— "
        "`Used to replace censor profanities.`／`Of or pertaining to.`／`amic.` —— "
        "说的是这个符号/词缀**怎么用**，不是它是什么意思。🔴 强行给中文就是造 "
        "（`[[blind-gloss-inference-ceiling]]`：无源可查按构词猜，错误率卡在 24-25%）。"
        "**宁可缺，不可错。**"
        "2026-09-10 起 +44：1.5b 废除后重翻，模型对 44 条留空（详见上面那段注释）。"),
    "A6 同词形下重复的英文释义（取 glosses[-1] 的证据）": (
        7_700,
        "🔴🔴 **这条不是缺陷，是阶段 1c 那个决定的活证据。**kaikki 的 `glosses` 是"
        "从泛到具体的一条路径，取 `[0]` 会把 43,443 条义项压成重复"
        "（`free` 六条全变 `Unconstrained.`）。取末之后同词形重复剩 7,700。"
        "⇒ **这个数跳到 5 万级就说明有人改回了取首。**期望值必须钉死，不许调宽。"),
    "B2 变形悬空原形（base_id 为空）": (
        960,
        "960 / 535,784（0.18%）。`base` 文本都在，只是原形词头不在 `dict` 里 —— "
        "源头指向的是库外的词。**不是缺陷是收词边界**。"
        "⚠️ 展示层查变形必须走 `inflection.word_id`，别走 `base_id`。"),
    "B8 空白页（无义项、无出版释义）": (
        208_194,
        "208,194 ＝ **208,136 条 `qual='low'`** ＋ 58 条真·什么都没有。"
        "那 208,136 全是 ECDICT 的网络抓取垃圾（`Sbobs → '[网络] 苯甲酰氧苯磺酸钠'`、"
        "`Bilzerian → '[网络] 平底锅'`，而 Bilzerian 是个姓氏）。阶段 3b 有意 `published=0`。"
        "🔴 **印出去是错，不印是缺；错比缺更伤权威**（`[[dict-framework-doc]]`）。"
        "⚠️ 2026-09-08 我在 `publish_legacy_when_no_zh.py` 里差点从后门放了 26 条 low 出去，"
        "是补写第四条负控才逮到的。"),
    "C2 核心词没有音标": (
        1,
        "1 个：`airstream`（freq_rank 31,007）。阶段 -1 量过：核心 59,137 词里两侧全空只有 3 条，"
        "六个外版一版不收（净增益 ≈ 0）。这 1 条是尾巴，不值得为它开一轮取数。"),
    "D1 可见例句没有中文": (
        2_087,
        "2,087 ＝ **构词式 1,177**（`magnesium + -a → magnesia`，有意排出翻译池 —— "
        "留着展示、但没有可翻的东西）＋ **模型明确返回空串 886**（规则 7「看不懂就留空」，"
        "全是重方言书证：`Aw teuk me seat be day an' neet.`）＋ **3 条从没送出去或被配对核对挡下**。"
        "🔴 逐条查过：**「有答案却没落库」＝ 0**。"),
    "D6 出处漏进了译文": (
        0,   # 🔴 2026-09-09 从 2 收紧到 0：**是闸自己报「⬇ 该收紧」我才来改的**，
             #    不是我记得。低了不改 ＝ 下次涨回去它一声不吭（pt 那条死基线的教训）。
        "466 → 21 → **2**。第一轮清库后数字纹丝不动，根因是**清库不等于清答案文件** —— "
        "`zh.jsonl` 是那 246 元的资产**也是续跑账本**，不从账本里划掉就不会重问。"
        "第二轮降到 21，逐条读**全是误报**：正文写 `1991-99`／`Jan 76`／`(4/21/99)`，"
        "模型展开成四位年份是对的，判据看不见两位形式。收窄后剩 2 条。"),
    "D7 中文里没有一个汉字": (
        441,
        "439 条。**多数是模型守规则的结果，不是失败**：`edge on, side on, end on, face on`"
        "（并列词组）／`eff you see kay why oh you.`（字母拼读）／`Tickhill, Tickham, …`"
        "（地名表，规则 4「没有通行译名保留原文」）／整段古吉拉特语歌词（规则 6「外语引文原样保留」）。"
        "其中 10 条是构词式，来自加过滤器之前跑的切片。"),
    "D8 例句译文错开一位（下限）": (
        10,
        "248 → 43 → 14 → **10**，三轮修下来降了 96%。剩下的 10 条**逐条读过，全是判据的假阳性**："
        "缩写展开时中文本来就比英文长得多 —— `USPS`→「美国邮政服务」／`FRS`→「皇家学会会员」／"
        "`YKTV`→「你知道那种氛围的缩写」／`EOE M/F/V/H`→「平等机会雇主（少数族裔/女性/…）」。"
        "🔴 **这条基线不许读成「还有 10 条没修」** —— 它是长度比这个判据的固有噪声底。"
        "⚠️ 而且它是**下限不是总量**：长度相近的错位这个判据永远逮不到，"
        "真正的防线是 `translate_examples.load_answers()` 的配对核对（模型回抄原文前几个词）。"),
    "E3 指针义项没有中文": (
        3_360,
        "3,360 / 706,345 ＝ **0.48%**。`infl_compose` 拼不出 tag 组合、且没有 `alt_of` 目标可套模板的那批。"
        "🔴 **绝不回退成泛泛的「变形」** —— de 收尾单 C16 的 5.6 万行「变形」其实是异体拼写，"
        "正是回退默认值造成的。拼不出就不产生行（B1 守着这条）。"
        "⭐ 这批词形里若有 ECDICT 人工中文，已由 `fixes/publish_legacy_when_no_zh.py` 从词条级补上"
        "（2026-09-08 放行 1,927 个词，`oneself` 就在其中）。"),
}

_Q_NO_ZH = ("SELECT COUNT(*) FROM sense s WHERE NOT EXISTS("
            "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')")


def _shifted(con):
    """→ 「配给下一条明显更合理」的条数。判据与 `fixes/fix_shifted_examples.py` 同源。"""
    import math
    import statistics
    rows = con.execute(
        "SELECT e.id, e.text, g.text FROM example e "
        "JOIN example_gloss g ON g.example_id=e.id "
        "WHERE e.hidden=0 ORDER BY e.id").fetchall()
    if len(rows) < 3:
        return 0
    lr = lambda a, b: math.log(max(len(b), 1) / max(len(a), 1))
    base = statistics.median(lr(t, z) for _, t, z in rows)
    n = 0
    for k in range(len(rows) - 1):
        i1, t1, z1 = rows[k]
        i2, t2, _ = rows[k + 1]
        if i2 - i1 > 3:
            continue
        if abs(lr(t1, z1) - base) - abs(lr(t2, z1) - base) > 1.2:
            n += 1
    return n


def _in(vals):
    """→ SQL 的 IN 列表。🔴 不用 `%r % (tuple,)`：单元素元组会渲染成
    `('x',)`，尾逗号 SQLite 直接语法错误（写这个闸时当场踩到）。"""
    return "(%s)" % ",".join("'%s'" % str(v).replace("'", "''") for v in vals)


class _Stop(Exception):
    def __init__(self, v):
        self.v = v


def _has(con, t):
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())


def build(con, only=None):
    """→ [(组, 断言名, 值)]。**每条都是「坏东西有几个」，0 ＝ 好。**"""
    q = lambda s: con.execute(s).fetchone()[0]
    C = []

    def add(g, name, got):
        C.append((g, name, got))
        if only is not None and name == only:
            raise _Stop(got)

    # ── A 组：结构与义项层 ────────────────────────────────────
    add("A", "A1 v3 的表少了任何一张",
        len(V3) - q("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                    "AND name IN %s" % _in(V3)))
    # 🔴 阶段 0 定的：en 新建库，**结构上不长这些器官**（de/pt 是迁移来源列）
    add("A", "A2 dict 长出了被禁的迁移列",
        len({c for c in ("ipa", "definition", "translation", "meta", "collocation",
                         "example", "phonetic")}
            & {r[1] for r in con.execute("PRAGMA table_info(dict)")}))
    add("A", "A3 义项没有中文", q(_Q_NO_ZH))
    add("A", "A4 sense_gloss 指向不存在的义项",
        q("SELECT COUNT(*) FROM sense_gloss g LEFT JOIN sense s ON s.id=g.sense_id "
          "WHERE s.id IS NULL"))
    add("A", "A5 sense_src 没挂上出版义项",
        q("SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL"))
    # 🔴🔴 阶段 1c 最硬的一条：义项文本取 `glosses[-1]` 不是 `[0]`。
    #    取首会把 43,443 条义项压成重复（`free` 六条全变 "Unconstrained."）。
    #    ⇒ 这条一旦跳到 5 万级，说明有人改回了取首。
    add("A", "A6 同词形下重复的英文释义（取 glosses[-1] 的证据）",
        q("SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM sense s "
          "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' "
          "GROUP BY s.word_id, g.text HAVING c>1)"))

    # ── A7/A8：老词典层拆成义项级之后的两条不变量（2026-09-09）───────
    # 🔴🔴 A8 守的是 `EN_PLAN` §〇 那条禁令：**「把词形级整块拆开贴到 kaikki 的
    #    义项上就是义项错配」**。`build_legacy_sense.py` 只处理**没有 kaikki 义项**
    #    的词；一旦有词两种来源的义项并存，就说明那条禁令被破了。
    add("A", "A7 老词典层的义项没有中文",
        q("SELECT COUNT(*) FROM sense_src ss WHERE ss.src='ecdict' "
          "AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=ss.sense_id "
          "AND g.lang='zh')"))
    add("A", "A8 同一个词里两种来源的义项并存（§〇 禁令）",
        q("SELECT COUNT(*) FROM (SELECT word_id FROM sense_src GROUP BY word_id "
          "HAVING COUNT(DISTINCT CASE WHEN src='ecdict' THEN 1 ELSE 0 END)>1)"))

    # ── B 组：变形与关系 ──────────────────────────────────────
    # 🔴 收尾单 C16（de）：5.6 万行「变形」其实是异体拼写，正是回退默认值造成的。
    #    en 的 `infl_compose` 拼不出就**不产生行**，所以这里必须恒为 0。
    add("B", "B1 变形中文回退成泛泛的「变形」",
        q("SELECT COUNT(*) FROM inflection WHERE label_zh IN ('变形','变位','形式')"))
    add("B", "B2 变形悬空原形（base_id 为空）",
        q("SELECT COUNT(*) FROM inflection WHERE base_id IS NULL"))
    # 🔴 `alt_of` 是异体拼写＝它自己的词头，塞进变形层会让 17 万个正经词头被印成「某词的变形」
    # 🔴🔴 **SQL `LIKE` 里 `_` 是单字符通配符** —— 第一版写 `LIKE '%alt_of%'`，
    #    它把库里真正存的 `alt-of` 也匹配上了，报 9 条。
    #    回源一读，那 9 条**同时**带 `form-of` 和 `alt-of`（`annots.` 确实是
    #    `annot.` 的复数，源头两个都说），中文「复数」是对的 ⇒ **不是缺陷**。
    #    ⇒ ① 用 `LIKE ... ESCAPE` 或直接查连字符写法；
    #      ② 判据收窄成「**只有 alt-of、没有 form-of**」才算混进来。
    add("B", "B3 纯 alt-of 混进了变形层",
        q("SELECT COUNT(*) FROM inflection WHERE COALESCE(tags,'') LIKE '%alt-of%' "
          "AND COALESCE(tags,'') NOT LIKE '%form-of%'"))
    add("B", "B4 关系 kind 跑出值域",
        q("SELECT COUNT(*) FROM sense_relation WHERE kind NOT IN %s"
          % _in(sorted(set(KEEP.values()) | set(HIDDEN.values()) | {"alt_of"}))))
    add("B", "B5 被丢弃的关系族又混进来了",
        q("SELECT COUNT(*) FROM sense_relation WHERE kind IN %s"
          % _in(set(DROP) | {d.rstrip("s") for d in DROP})) if DROP else 0)
    # 🔴 出版族被误藏 / 隐藏族没藏住 —— 两个方向各一条（`hide_non_examples` 同形）
    # 🔴 「有意藏掉的坏数据」不算「误藏」 —— 2026-09-09 `clean_wiki_artifacts.py`
    #    藏了 47 条 wikitext 损坏的 target（`panther[Panthera`），本条当场报红。
    #    数据没错，是**判据没有把这两件事分开**：藏一条还原不了的坏目标是对的，
    #    藏一条**干净**的出版族关系才是缺陷。⇒ 判据加「target 方括号配对」。
    #    ⚠️ 收窄之后这条仍然守得住它该守的：`clean_wiki_artifacts` 若哪天误伤
    #      一条干净的关系，方括号是配对的 ⇒ 立刻红。
    add("B", "B6 出版关系族被误藏（target 干净的）",
        sum(1 for (x,) in con.execute(
            "SELECT target FROM sense_relation WHERE hidden=1 AND kind IN %s"
            % _in(sorted(KEEP.values())))
            if (x or "").count("[") == (x or "").count("]")))
    add("B", "B7 隐藏关系族没藏住",
        q("SELECT COUNT(*) FROM sense_relation WHERE hidden=0 AND kind IN %s"
          % _in(sorted(HIDDEN.values()))))
    add("B", "B8 空白页（无义项、无出版释义）",
        q("SELECT COUNT(*) FROM dict d WHERE NOT EXISTS("
          "SELECT 1 FROM sense s WHERE s.word_id=d.id) AND NOT EXISTS("
          "SELECT 1 FROM legacy_gloss g WHERE g.word_id=d.id AND g.published=1)"))

    # ── C 组：音标 ────────────────────────────────────────────
    # 🔴🔴 `UNIQUE` 里必须有 `region`：库里 6 万条是「同 IPA 不同地区」，
    #    漏掉这一列会把它们静默压成一条（de 记过这个 bug）。
    #    这里从**反面**守：同一 (word_id, ipa, notation) 下地区多于一个的必须还在。
    add("C", "C1 同 IPA 不同地区被压成一条",
        0 if q("SELECT COUNT(*) FROM (SELECT 1 FROM pronunciation "
               "GROUP BY word_id, ipa, notation HAVING COUNT(DISTINCT region)>1)") > 0
        else 1)
    add("C", "C2 核心词没有音标",
        q("SELECT COUNT(*) FROM dict d WHERE d.freq_rank IS NOT NULL AND NOT EXISTS("
          "SELECT 1 FROM pronunciation p WHERE p.word_id=d.id)"))
    # 🔴 六语种统一：音标存**裸**的，展示层再加 `/…/`
    add("C", "C3 音标带了斜杠或方括号",
        q("SELECT COUNT(*) FROM pronunciation WHERE ipa LIKE '/%' OR ipa LIKE '[%'"))

    # ── D 组：例句层（5e，2026-09-08 花了 246 元） ─────────────
    add("D", "D1 可见例句没有中文",
        q("SELECT COUNT(*) FROM example e WHERE e.hidden=0 AND NOT EXISTS("
          "SELECT 1 FROM example_gloss g WHERE g.example_id=e.id)"))
    # 🔴 藏了正文却留着译文 ＝ 读者看不见、统计还会把它算成"已翻"
    add("D", "D2 藏起来的例句留着中文",
        q("SELECT COUNT(*) FROM example e JOIN example_gloss g ON g.example_id=e.id "
          "WHERE e.hidden=1"))
    # 🔴 判据 import `hide_non_examples.WHERE`，不在这里重抄一遍族名
    add("D", "D3 不是例句的三族又回到了例句区",
        q("SELECT COUNT(*) FROM example WHERE hidden=0 AND (%s)" % NOT_EXAMPLE))
    add("D", "D4 书证的出处该拆而没拆",
        sum(1 for t, r in con.execute("SELECT text, ref FROM example WHERE hidden=0")
            if YEAR.match(t.strip()) and "\n" in t and not r))
    add("D", "D5 同一句英文有多个中文",
        q("SELECT COUNT(*) FROM (SELECT 1 FROM example_gloss g "
          "JOIN example e ON e.id=g.example_id GROUP BY e.text "
          "HAVING COUNT(DISTINCT g.text)>1)"))
    # 🔴 prompt 规则 5「文献出处不出现在译文里」。判据：译文里有**只在 ref 里出现**的年份。
    # 🔴 判据 `import` 生成侧那一份，闸里不重写 —— 第一版我在这里另抄了一遍，
    #    于是修 `split_quote_ref` 的误报时闸还按旧判据报 21 条。
    add("D", "D6 出处漏进了译文",
        sum(1 for t, r, z in con.execute(
            "SELECT e.text, e.ref, g.text FROM example e "
            "JOIN example_gloss g ON g.example_id=e.id "
            "WHERE e.hidden=0 AND e.ref IS NOT NULL AND e.ref <> ''")
            if ref_leaked(t, r, z)))
    # 🔴🔴🔴 **D8 是这一轮最贵的一条教训。**
    #    外审照出「`flutter` 的例句译文完全无关」，回源发现是**整批错开一位**：
    #      825882 `little flutters of breeze…` → 「学过拉丁语之后，西班牙语…」
    #      825883 `After studying Latin, Spanish was a breeze.` → 「换乘东米德兰铁路…」
    #    `id` 发出去也回来了（`slot_translate` 有硬闸守着），
    #    但**模型把 id 与内容配错了行**。实测 134 片、约 1.3 万行受影响。
    #    ⚠️ **落库那六条闸全绿** —— 行数、空串、同句一译、覆盖数、来源、id 是真主键，
    #      错位一条都不违反，因为它不改变任何计数，只把内容挪了一格。
    #      ⇒ **计数型的闸对「错配」是结构性失明的**（`[[verification-gates-not-sampling]]`）。
    #    判据：中文/英文长度比的中位数是稳定的；若 `zh(X)` 配 `en(X+1)` 明显更合理，就是错位。
    #    ⚠️ 它只逮得到长度差得开的那些，是**下限不是总量** —— 所以修的时候按整批扩。
    add("D", "D8 例句译文错开一位（下限）", _shifted(con))
    add("D", "D7 中文里没有一个汉字",
        sum(1 for (z,) in con.execute("SELECT text FROM example_gloss")
            if not CJK.search(z or "")))

    # ── E 组：读者口径（阶段 8 之后，库里有 ≠ 到得了读者） ──────
    # 🔴🔴 `[[it-display-layer-stage8]]`：三层数据全绿，真渲染立刻看见缺陷。
    #    判据查 `FROM`/`JOIN` 后面的表名 —— de 那次查"表名在不在文件里"，
    #    `sense` 命中 `senses:`、`entry` 命中 `const entry =`，凭空"接上"3 张。
    src = TS.read_text("utf-8") if TS.exists() else ""
    used = set(re.findall(r"(?:FROM|JOIN)\s+([a-z_]+)", src))
    add("E", "E1 展示层没接上的 v3 表",
        len([t for t in ("dict", "sense", "sense_gloss", "sense_relation", "sense_tag",
                         "inflection", "pronunciation", "example", "example_gloss",
                         "audio", "legacy_gloss", "search_prefix") if t not in used]))
    # 🔴 PITFALLS I1：只渲染义项级关系，**词条级一条到不了读者**（de 的 Wasser 813 条）
    add("E", "E2 展示层不查词条级关系（sense_id IS NULL）",
        0 if re.search(r"sense_id\s+IS\s+NULL", src) else 1)
    # 🔴 PITFALLS I2：「不翻」不等于「不给中文」—— 指针义项 70 万条
    # 🔴 指针判据与 `fill_pointer_gloss.py` **同一份**：`sense_src.raw_tags` 里的
    #    `form-of`/`alt-of`。阶段 1d 有意没把指针义项的 tag 入 `sense_tag`
    #    （那批 tag 说的是"它是谁的复数"，不是"这条义项用于复数"），
    #    所以**不能**去查 `sense_tag` —— 查了会恒为 0，是个假绿。
    add("E", "E3 指针义项没有中文",
        q("SELECT COUNT(*) FROM sense_src ss WHERE (ss.raw_tags LIKE '%\"form-of\"%' "
          "OR ss.raw_tags LIKE '%\"alt-of\"%') AND ss.sense_id IS NOT NULL "
          "AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=ss.sense_id "
          "AND g.lang='zh')"))

    # ── F 组：外锚（en 独有）──────────────────────────────────
    # ⭐ ECDICT 的人工中文是**负控不是答案**。这里只问一件事：
    #    核心词里「我们给了中文、而人工中文一个字都对不上」的比例有没有异常。
    #    🔴 **不一致 ≠ 错**（`[[verify-before-claiming-confirmed]]`）——
    #      它是一个**要解释的数**，不是一条要修的缺陷。
    add("F", "F1 核心词一条中文都没有",
        q("SELECT COUNT(*) FROM dict d WHERE d.freq_rank IS NOT NULL "
          "AND NOT EXISTS(SELECT 1 FROM sense s JOIN sense_gloss g "
          "ON g.sense_id=s.id AND g.lang='zh' WHERE s.word_id=d.id) "
          "AND NOT EXISTS(SELECT 1 FROM legacy_gloss lg WHERE lg.word_id=d.id "
          "AND lg.published=1)"))
    # 🔴 尺子被改动必须当场知道（`field_src.src='ecdict'` 是它们的来源）
    add("F", "F2 尺子少了（collins/oxford/exam_tag/bnc/freq_rank）",
        sum(1 for c in ("collins", "oxford", "exam_tag", "bnc", "freq_rank")
            if q("SELECT COUNT(*) FROM dict WHERE %s IS NOT NULL" % c) == 0))
    return C


def run(verbose=True, con=None):
    own = con is None
    if own:
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        C = build(con)
    finally:
        if own:
            con.close()
    red, tighten = [], []
    if verbose:
        print("═══ 回归闸（en）═══")
    g0 = None
    for g, name, got in C:
        if g != g0:
            g0 = g
            if verbose:
                print()
        want, why = ACCEPT.get(name, (0, None))
        if got > want:
            red.append((name, got, want, why))
            mark = "🔴"
        elif got < want:
            tighten.append((name, got, want))
            mark = "⬇"
        else:
            mark = "✅"
        if verbose:
            print("   %s %-46s %s%s" % (mark, name, format(got, ","),
                                        "" if want == 0 else " / 已接受 %s" % format(want, ",")))
    if verbose:
        for name, got, want, why in red:
            print("\n   🔴 %s：%s（已接受 %s）" % (name, format(got, ","), format(want, ",")))
            if why:
                print("      理由原文：%s" % why[:200])
        # ⭐ 「低了」也要出声：基线该收紧却没人改，就是 pt 那条死基线的开始
        for name, got, want in tighten:
            print("\n   ⬇ %s 只有 %s（已接受 %s）—— **该收紧基线**，"
                  "低了不改＝下次涨回去它一声不吭" % (name, format(got, ","), format(want, ",")))
        print("\n   %s" % ("✅ 没有回归" if not red else "🔴 %d 条回归" % len(red)))
    return red


def check_brief(db=None):
    """`dbtool.session` 每次写库后调这个。→ **[(组, 名称, 数值)]**，只含没有理由的红。

    🔴 契约是**三元组**（`dbtool._run_gate` 用 `"%-5s %-38s %s" % r` 打）——
       第一版我直接 `return run(verbose=False)` 返回四元组，
       结果**每次写库都在 dbtool 里炸 TypeError**。
       ⚠️ 闸自己崩掉比闸误报更糟：它一条结论都给不出。
    ⚠️ 它**只报不拦**：写库已经 commit 了，不是每次红都该回滚。
    """
    con = sqlite3.connect("file:%s?mode=ro" % (db or paths.DB), uri=True)
    try:
        C = build(con)
    finally:
        con.close()
    return [(g, n, format(v, ",")) for g, n, v in C
            if v > ACCEPT.get(n, (0, ""))[0]]


# ══════════════════ 变异 ══════════════════

def mutate():
    """⭐ 每条规则造一个反例。**一条永远通过的检查等于没检查。**

    🔴 **变异必须自己造缺陷**，不许依赖「库里恰好还有没做完的事」——
       那种前提会随项目推进自己消失（de 2026-09-03、en 账闸 2026-09-08 各踩过一次）。
       ⇒ 全部在**内存里的临时库**上跑：建最小表、灌注入行、直接打 `build()`。
    """
    print("═══ 变异验证 ═══")
    real = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok = n = 0

    def case(name, want_assert, setup):
        nonlocal ok, n
        n += 1
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
        setup(con)
        try:
            build(con, only=want_assert)
            got = None
        except _Stop as s:
            got = s.v
        # 🔴 门槛是 **0**，不是 `ACCEPT` 的生产基线。
        #    变异跑在**空的内存库**上，那里没有生产数据 ——
        #    拿 `A3=4,332` 这种基线当门槛，注入一条缺陷只报 1，就被判成"没逮住"。
        #    变异问的是「**这条断言能不能记到注入的缺陷**」，
        #    不是「它有没有超过生产基线」。（第一版写错，14 条里 6 条假阴性。）
        good = got is not None and got > 0
        ok += good
        print("   %s  %-42s → %s" % ("✓" if good else "🔴 没逮住", name,
                                     "报 %s" % got if got is not None else "断言没跑到"))
        con.close()

    case("义项没有中文", "A3 义项没有中文",
         lambda c: c.executemany("INSERT INTO sense(id,word_id,rank) VALUES(?,1,0)",
                                 [(1,)]))
    case("取 glosses[0] ⇒ 同词形重复释义", "A6 同词形下重复的英文释义（取 glosses[-1] 的证据）",
         lambda c: (c.executemany("INSERT INTO sense(id,word_id,rank) VALUES(?,1,0)",
                                  [(1,), (2,)]),
                    c.executemany("INSERT INTO sense_gloss(sense_id,lang,text) "
                                  "VALUES(?,'en','Unconstrained.')", [(1,), (2,)])))
    case("老词典义项没有中文", "A7 老词典层的义项没有中文",
         lambda c: (c.execute("INSERT INTO sense(id,word_id,rank) VALUES(1,1,0)"),
                    c.execute("INSERT INTO sense_src(id,sense_id,word_id,src,raw_tags)"
                              " VALUES(1,1,1,'ecdict','{}')")))
    case("两种来源的义项并存（§〇 禁令被破）",
         "A8 同一个词里两种来源的义项并存（§〇 禁令）",
         lambda c: (c.execute("INSERT INTO sense_src(id,sense_id,word_id,src,raw_tags)"
                              " VALUES(1,1,7,'ecdict','{}')"),
                    c.execute("INSERT INTO sense_src(id,sense_id,word_id,src,raw_tags)"
                              " VALUES(2,2,7,'en-edition','{}')")))
    case("纯 alt-of 混进变形层", "B3 纯 alt-of 混进了变形层",
         lambda c: c.execute("INSERT INTO inflection(word_id,base_id,tags) "
                             "VALUES(1,2,'[\"alt-of\",\"alternative\"]')"))
    case("关系 kind 跑出值域", "B4 关系 kind 跑出值域",
         lambda c: c.execute("INSERT INTO sense_relation(word_id,kind,target,hidden) "
                             "VALUES(1,'anagram','x',0)"))
    case("干净的出版族关系被误藏", "B6 出版关系族被误藏（target 干净的）",
         lambda c: c.execute("INSERT INTO sense_relation(word_id,kind,target,hidden) "
                             "VALUES(1,'synonym','felid',1)"))
    case("隐藏关系族没藏住", "B7 隐藏关系族没藏住",
         lambda c: c.execute("INSERT INTO sense_relation(word_id,kind,target,hidden) "
                             "VALUES(1,'derived','x',0)"))
    case("音标带了斜杠", "C3 音标带了斜杠或方括号",
         lambda c: c.execute("INSERT INTO pronunciation(word_id,ipa,notation,region) "
                             "VALUES(1,'/kæt/','ipa',NULL)"))
    case("可见例句没有中文", "D1 可见例句没有中文",
         lambda c: c.execute("INSERT INTO example(id,word,text,hidden) "
                             "VALUES(1,'cat','A cat sat.',0)"))
    case("藏了正文却留着译文", "D2 藏起来的例句留着中文",
         lambda c: (c.execute("INSERT INTO example(id,word,text,hidden) "
                              "VALUES(1,'cat','Near-synonym: x',1)"),
                    c.execute("INSERT INTO example_gloss(example_id,lang,text) "
                              "VALUES(1,'zh','近义词：x')")))
    case("不是例句的行回到例句区", "D3 不是例句的三族又回到了例句区",
         lambda c: (c.execute("INSERT INTO example(id,word,text,hidden) VALUES"
                              "(1,'x','For quotations using this term, see Citations:x.',0)"),
                    c.execute("INSERT INTO example_gloss(example_id,lang,text) "
                              "VALUES(1,'zh','中')")))
    case("出处粘在正文上", "D4 书证的出处该拆而没拆",
         lambda c: (c.execute("INSERT INTO example(id,word,text,ref,hidden) VALUES"
                              "(1,'x','1722, Daniel Defoe, p. 86,\nSome Houses were.',NULL,0)"),
                    c.execute("INSERT INTO example_gloss(example_id,lang,text) "
                              "VALUES(1,'zh','有些房子。')")))
    case("出处漏进译文", "D6 出处漏进了译文",
         lambda c: (c.execute("INSERT INTO example(id,word,text,ref,hidden) VALUES"
                              "(1,'x','Some Houses were.','1722, Daniel Defoe, p. 86,',0)"),
                    c.execute("INSERT INTO example_gloss(example_id,lang,text) "
                              "VALUES(1,'zh','1722年，笛福，第86页，有些房子。')")))
    # 🔴 D8 的基准是**中位数**，只注入两条的话 `base` 就从这两条自己算出来 ⇒ 判据自证、
    #    变异永远报 0。**要先铺够"正常"的背景行，才谈得上"这一条反常"。**
    #    （第一版就这么写的，`--mutate` 当场 15/16 把它挑了出来 —— 变异验的正是这个。）
    def _bg(c, n=14):
        for k in range(10, 10 + n):
            en = "This is a perfectly ordinary English sentence number %d here." % k
            c.execute("INSERT INTO example(id,word,text,hidden) VALUES(?,'x',?,0)",
                      (k, en))
            c.execute("INSERT INTO example_gloss(example_id,lang,text) VALUES(?,'zh',?)",
                      (k, "这是第%d个完全普通的英语句子。" % k))

    case("例句译文错开一位", "D8 例句译文错开一位（下限）",
         lambda c: (_bg(c),
                    c.execute("INSERT INTO example(id,word,text,hidden) VALUES"
                              "(1,'x','Halt in the name of the law!',0)"),
                    c.execute("INSERT INTO example(id,word,text,hidden) VALUES"
                              "(2,'x','We may be quite sure, therefore, that in some "
                              "shape, if we, the people of England, tolerate crimes "
                              "committed in our name, we shall answer for it.',0)"),
                    c.execute("INSERT INTO example_gloss(example_id,lang,text) VALUES"
                              "(1,'zh','因此我们可以确信，无论以何种形式，如果我们英格兰人民"
                              "容忍以我们的名义犯下的血腥罪行，我们终将为此负责。')"),
                    c.execute("INSERT INTO example_gloss(example_id,lang,text) "
                              "VALUES(2,'zh','以法律的名义，站住！')")))
    case("译文里没有汉字", "D7 中文里没有一个汉字",
         lambda c: (c.execute("INSERT INTO example(id,word,text,hidden) "
                              "VALUES(1,'x','a + b → c',0)"),
                    c.execute("INSERT INTO example_gloss(example_id,lang,text) "
                              "VALUES(1,'zh','a + b → c')")))
    case("指针义项没有中文", "E3 指针义项没有中文",
         lambda c: (c.execute("INSERT INTO sense(id,word_id,rank) VALUES(1,1,0)"),
                    c.execute("INSERT INTO sense_src(id,sense_id,raw_tags) "
                              "VALUES(1,1,'[\"form-of\",\"plural\"]')"),
                    c.execute("INSERT INTO sense_gloss(sense_id,lang,text) "
                              "VALUES(1,'en','plural of cat')")))
    # 🔴 负控：一条**干净**的库必须全绿 —— 没有它，分不清「变异逮到了」和「闸恒红」
    n += 1
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    clean = [x for x in build(con) if x[2] > ACCEPT.get(x[1], (0, None))[0]]
    con.close()
    # 空库里 C1（"同 IPA 不同地区被压成一条"）必然报 1 —— 它是**反面**判据，
    # 空库里本来就没有多地区行。这是判据本身的性质，不是缺陷 ⇒ 负控里豁免它。
    # ⚠️ 空库上**天然非零**的两条，负控里豁免并写明原因：
    #   · C1 是**反面**判据（"多地区行被压没了吗"）—— 空库里本来就没有多地区行
    #   · F2 数的是"尺子少了几把"—— 空库里五把全没有
    #   其余任何一条在空库上报非零，都说明判据把"没有数据"当成了"有缺陷"。
    EMPTY_OK = ("C1 ", "F2 ")
    clean = [x for x in clean if not x[1].startswith(EMPTY_OK)]
    good = not clean
    ok += good
    print("   %s  %-42s → %s" % ("✓" if good else "🔴 负控失败", "负控：干净的空库必须全绿",
                                 "全绿" if good else "误报 " + "、".join(x[1] for x in clean)))
    real.close()
    print("\n   变异 %d/%d" % (ok, n))
    return ok == n


SCHEMA = """
CREATE TABLE dict(id INTEGER PRIMARY KEY, word TEXT, word_norm TEXT, is_lemma INT,
  pos TEXT, collins INT, oxford INT, exam_tag TEXT, bnc INT, freq_rank INT, freq_zipf REAL);
CREATE TABLE entry(id INTEGER PRIMARY KEY, word_id INT);
CREATE TABLE sense(id INTEGER PRIMARY KEY, word_id INT, rank INT);
CREATE TABLE sense_src(id INTEGER PRIMARY KEY, sense_id INT, word_id INT, src TEXT, raw_tags TEXT);
CREATE TABLE sense_gloss(sense_id INT, lang TEXT, text TEXT, src TEXT);
CREATE TABLE sense_tag(sense_id INT, kind TEXT, value TEXT);
CREATE TABLE sense_relation(id INTEGER PRIMARY KEY, word_id INT, sense_id INT,
  kind TEXT, target TEXT, tags TEXT, hidden INT, src TEXT, src_ref TEXT);
CREATE TABLE inflection(id INTEGER PRIMARY KEY, word_id INT, entry_id INT,
  kind TEXT, base TEXT, base_id INT, label_zh TEXT, desc_en TEXT, tags TEXT,
  src TEXT, src_ref TEXT);
CREATE TABLE pronunciation(id INTEGER PRIMARY KEY, word_id INT, entry_id INT,
  ipa TEXT, notation TEXT, region TEXT, src TEXT);
CREATE TABLE example(id INTEGER PRIMARY KEY, word TEXT, sense_id INT, text TEXT,
  bold TEXT, ref TEXT, src_gloss TEXT, src_translation TEXT, src_lang TEXT,
  hidden INT DEFAULT 0, src TEXT);
CREATE TABLE example_gloss(example_id INT, lang TEXT, text TEXT, src TEXT);
CREATE TABLE collocation(id INTEGER PRIMARY KEY, text TEXT);
CREATE TABLE collocation_gloss(collocation_id INT, lang TEXT, text TEXT);
CREATE TABLE audio(id INTEGER PRIMARY KEY, word TEXT);
CREATE TABLE legacy_gloss(id INTEGER PRIMARY KEY, word_id INT, published INT);
CREATE TABLE field_src(id INTEGER PRIMARY KEY, src TEXT);
CREATE TABLE search_prefix(id INTEGER PRIMARY KEY);
"""


def main():
    if "--mutate" in _sys.argv:
        return 0 if mutate() else 1
    return 1 if run() else 0


if __name__ == "__main__":
    _sys.exit(main())
