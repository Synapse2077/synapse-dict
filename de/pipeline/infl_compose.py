"""
德语变位/变格语法标签组合器（确定性规则）——de 独立文件，不 import 任何其他语种。

由 kaikki 变位 sense 的 tags 组合出中文语法标签，供 build.py 生成变位行说明文本。
纯规则、只用 tag、固定段序；不逐行走豆包、不靠示例词猜。

德语两大变形体系：
  · 动词变位：[非限定：不定式/分词] 或 [语气·时态]·[第X人称]·[单/复数]
      ['indicative','present','third-person','singular'] → 陈述式现在时第三人称单数
      ['subjunctive-ii','preterite','first-person','plural'] → 虚拟式II第一人称复数
      ['participle','past'] → 过去分词  ['participle','present'] → 现在分词
  · 名词/形容词变格：[比较级/最高级]·[强/弱/混合变化]·[性]·[单/复数]·[格]
      ['genitive','singular'] → 属格单数
      ['strong','nominative','masculine','singular'] → 强变化阳性单数主格
      ['comparative','dative','feminine','plural','weak'] → 比较级弱变化阴性复数与格

术语为标准德语语法中译。四格：主/属/与/宾（Nominativ/Genitiv/Dativ/Akkusativ）。

用法：
    from infl_compose import compose
    zh = compose(tags)   # tags: kaikki sense 的 tags 列表
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层

# 语气（Modus）
MOOD = [
    ("indicative", "陈述式"),
    ("subjunctive-i", "虚拟式I"),
    ("subjunctive-ii", "虚拟式II"),
    ("subjunctive", "虚拟式"),
    ("imperative", "命令式"),
]
# 时态（Tempus）——限定动词层
TENSE = [
    ("present", "现在时"),
    ("preterite", "过去时"),
    ("past", "过去时"),
]
PERSON = [("first-person", "一"), ("second-person", "二"), ("third-person", "三")]
NUMBER = [("singular", "单数"), ("plural", "复数")]
GENDER = [("masculine", "阳性"), ("feminine", "阴性"), ("neuter", "中性")]
# 四格（Kasus）
CASE = [
    ("nominative", "主格"),
    ("genitive", "属格"),
    ("dative", "与格"),
    ("accusative", "宾格"),
]
# 强弱变格（形容词/名词随冠词）
STRENGTH = [("strong", "强变化"), ("weak", "弱变化"), ("mixed", "混合变化")]
# 比较级
DEGREE = [("comparative", "比较级"), ("superlative", "最高级")]

# ── 构词（Wortbildung）—— **不是屈折**，2026-09-01 补 ───────────────────────
# 🔴 这一族原来 `compose()` 根本不认识，于是 `diminutive`/`gerund`/`agent` 被静默丢掉，
#    只剩下这个**派生词自己的**性与变化类被印出来，读起来却像是原形的一个格：
#        Häuschen  tags=[diminutive,form-of,neuter,strong] → 「Haus 的 强变化中性」
#        Lehrer    tags=[agent,form-of,masculine,strong]   → 「lehren 的 强变化阳性」
#        Reifen    tags=[gerund,form-of,neuter,strong]     → 「reifen 的 强变化中性」
#    `Lehrer` 是**教师**，不是 lehren 的一个格。实测 5,263 行 / 4,780 个词形**没有任何
#    真义项** ⇒ 页面上就只有这一句错话。「错比缺更伤权威」。
# ⚠️ 性与变化类**有意不进这个标签**：德语指小词一律中性、施动者名词一律阳性 ——
#    它们由后缀决定，是冗余信息；而且本项目已定「**德语性别是词条级的**」
#    （`sense.gender` 全空那条断言），性别不该出现在变形标签里。
# ⚠️ 实测 5,262/5,263 是纯构词、不带格与数；唯一的例外 `Leutchen`（`Leute` 是复数词）
#    带 plural ⇒ 保留把格/数接在后面的能力，别为一条特例砍掉它。
# ⭐ 术语在 2026-09-01 送两家外审之后定稿，逐条有理由，不是谁票多：
#   · `diminutive`→**指小词**（原写"指小形式"，"形式"会和变格变位那种"形式"混）
#   · `agent`→**施事名词**（原写"施动者名词"，偏理论且更长）
#   · `gerund`→**名词化不定式** —— 🔴 **两家在这条上意见相反**（豆包说"动名词"可以，
#     v4-pro 说不行）。按"不取多数、回源"：德语的 `gerund` 在 kaikki 里指
#     `substantivierter Infinitiv`（`das Eifern`），而中文"动名词"几乎专指英语 `-ing`，
#     套上去会让读者产生英语语法印象。⇒ 采 v4-pro。
DERIV = [
    ("diminutive", "指小词"),
    ("augmentative", "增大词"),
    ("gerund", "名词化不定式"),
    ("agent", "施事名词"),
    ("collective", "集合形式"),
]

# 非语法元标签：不进语法说明
DROP = {"form-of", "alt-of", "combined-form", "multiword-construction",
        "table-tags", "inflection-template", "class"}

# compose 识别的全部语法 tag（供 build.py drop-ledger 归桶）
COMPOSE_TAGS = (
    {k for pairs in (MOOD, TENSE, PERSON, NUMBER, GENDER, CASE, STRENGTH, DEGREE, DERIV)
     for k, _ in pairs}
    | {"infinitive", "infinitive-zu", "participle", "predicative", "attributive",
       "definite", "indefinite", "without-article", "includes-article",
       "negative", "future", "future-i", "future-ii", "perfect", "pluperfect",
       "dependent", "independent"}
    | DROP
)


def _pick(t, pairs):
    return [zh for k, zh in pairs if k in t]


def compose(tags, legacy=False):
    """kaikki tags → 中文语法说明；无法组合时返回 ''（调用方回退'变形'）。

    🔴 `legacy=True` = **按 2026-07 建库那天的行为算**（不认构词族）。
       只有一个调用方该用它：阶段 2b 的闸① —— 它拿重建结果和七月建的 `dict.infl`
       列逐字节比，用来证明「我只是搬，没有改」。
       如果闸也用新行为，我 2026-09-01 加的构词族改进会让它一次报红 5,263 条，
       **把那 61 条真正的上游漂移整个淹掉** —— 闸就从"检查"退化成了噪声源。
       ⇒ 表里存**新值**、闸问**旧值**（`build_inflection_layer.replay_infl` 一行算两个标签）。
         判据仍然只有一份，只是它知道自己被问的是哪个版本。
       ⚠️ 反过来做——表存旧值、另开脚本 UPDATE——是 `[[replay-scripts-undo-fixes]]`：
         变形层一重跑就把修复冲掉。**修复必须做在产生这个值的地方。**
    """
    t = set(x for x in tags if x not in DROP)

    # —— 构词：优先级最高，且**互斥于**格的组合（它不是一个格）——
    if not legacy:
        for k, zh in DERIV:
            if k in t:
                tail = "".join(_pick(t, NUMBER)) + "/".join(_pick(t, CASE))
                return zh + ("（%s）" % tail if tail else "")

    # —— 动词非限定形式（互斥优先）——
    if "infinitive-zu" in t:
        return "带 zu 不定式"
    if "infinitive" in t:
        return "不定式"
    # 🔴 德语版用**单独一个 `perfect`** 表示第二分词（`Partizip Perfekt des Verbs dezidieren`），
    #    不带 `participle` ⇒ 下面那条 `participle` 规则够不着它，实测 **14,440 条**组不出中文。
    #    与 `diminutive` 同一形状：**tag 在 `COMPOSE_TAGS` 里、却没有任何规则渲染它**。
    #    ⚠️ `passive,perfect`（5 条）不在此列，量太小不单独造词。
    if "perfect" in t and "participle" not in t and "passive" not in t:
        return "过去分词（Partizip II）"
    if "participle" in t:
        if "past" in t:
            return "过去分词（Partizip II）"
        if "present" in t:
            return "现在分词（Partizip I）"
        return "分词"

    seg = []
    # —— 限定动词：语气 + 时态 + 人称 + 数 ——
    mo = _pick(t, MOOD)
    te = _pick(t, TENSE)
    p = _pick(t, PERSON)
    is_verb_form = bool(mo or p or (te and not _pick(t, CASE)))

    if is_verb_form:
        if mo:
            seg.append(mo[0])
        if te:
            seg.append(te[0])
        if p:
            seg.append("第" + "/".join(p) + "人称")
        n = _pick(t, NUMBER)
        if n:
            seg.append("/".join(n))
        if "negative" in t:
            seg.append("（否定）")
        # ── 可分动词的不分离形式（2026-09-01 外审后加）────────────────────
        # 🔴 **两家意见相反**：豆包「学习者自然会知道，别标」；v4-pro「必须标，
        #    否则划词看到 `mitfährst` 只写『现在时第二人称单数』，读者会写出
        #    `du mitfährst`（错，主句要写 `du fährst mit`）」。
        #    回源验 v4-pro 的前提：`dependent` 15,103 行里 **15,089 行（99.9%）
        #    的原形是可分动词**（余下 14 行的原形其实也可分，只是 `entry.sep_prefix`
        #    没填上）；而 `independent` 全库 **0 行** ⇒ 前提成立，采 v4-pro。
        # ⚠️ 措辞取「从句中不分离」而不是「从句形式」：后者会让读者以为**另有**
        #    一个主句形式的词条，而主句里它根本不是一个词（`fährst … mit`）。
        if not legacy and ("dependent" in t or "subordinate-clause" in t):
            seg.append("（从句中不分离）")
        # 🔴 德语版把这件事的**两面**都标了出来，而英文版只标了一面：
        #      main-clause        分离形式    `setzt an` ← ansetzen   161,751 条
        #      subordinate-clause 不分离形式  `einführen` ← einfahren 135,790 条
        #      dependent（英文版） 不分离形式  `mitfährst` ← mitfahren  15,103 条
        #    `setzt an` 这类分离形式正是阶段 3 收进来的 82,650 条多词条目 ——
        #    不标出来，读者会以为它和 `mitfährst` 是同一种东西。
        elif not legacy and "main-clause" in t:
            seg.append("（主句中分离）")
        return "".join(seg)

    # —— 名词/形容词变格：比较级 + 强弱 + 性 + 数 + 格 ——
    deg = _pick(t, DEGREE)
    st = _pick(t, STRENGTH)
    g = _pick(t, GENDER)
    n = _pick(t, NUMBER)
    ca = _pick(t, CASE)
    parts = []
    if deg:
        parts.append("".join(deg))
    if st:
        parts.append("".join(st))
    if g:
        parts.append("/".join(g))
    if n:
        parts.append("".join(n))
    if ca:
        parts.append("/".join(ca))
    return "".join(parts)
