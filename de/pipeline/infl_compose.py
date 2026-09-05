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

# ══════════════════════════════════════════════════════ 语域／时代（2026-09-04 加）
# 起因：外审拿渲染成品挑错，三条都指到同一件事 ——
#   `kömmt`「现在时第三人称单数」  源头 tags = [archaic, dialectal, …]
#   `gib`  「现在时第一人称单数」  源头 tags = [colloquial, …]（标准形是 gebe）
#   `nimm` 同上
# 两家都说「这是错的，标准形不是它」。**回源之后判两家都错**：英文版确实收了
# `ich gib` 这个**口语**一单、`kömmt` 这个**古／方言**三单，数据是对的 ——
# 错的是我们**把源头的语域标扔了**，只显示语法位置，于是读者看到的是
# 「kömmt 是 kommen 的现在时第三人称单数」这句**没有前提的话**。
#
# 🔴 判据收窄了两轮，两轮都是被数据打回来的（`[[criteria-narrower-than-you-think]]`）：
#   第一版「带语域标就加前缀」 → 64,245 行
#   第二版 去掉标签里已写的   → 14,548 行
#   第三版 ⇒ **4,510 行**，去掉了下面两族：
#     ① `formal`+`rare` 47,048 行 **全部**落在虚拟式 II 上 —— 那是英文版给整个
#        虚拟式 II 范式打的**惯例标**，不是这个形式的属性。给四万七千行统一加
#        「正式·罕用」是在**加噪声不是加信息**（`[[proxy-metric-gets-optimized]]`：
#        指标涨了、目的坏了）。⇒ `formal`/`rare` 一律不进前缀。
#     ② `kk-*-forms` 那族 10,251 行标签**本身就是**「废弃异体形式」「口语异体形式」，
#        再加前缀＝「废 · 废弃异体形式」。
# ⚠️ 保留「这个形式受限」这一族（废/古/旧/方言/口语/非规范/诗/谑/俚/书面），
#    去掉「有多罕见」那一族（rare/formal）—— 前者是读者用得上的前提，后者是频次。
REGISTER = [
    ("obsolete", "废"),
    ("archaic", "古"),
    ("dated", "旧"),
    ("dialectal", "方言"),
    ("regional", "地区"),
    ("colloquial", "口语"),
    ("informal", "口语"),
    ("nonstandard", "非规范"),
    ("slang", "俚"),
    ("poetic", "诗"),
    ("literary", "书面"),
    ("humorous", "谑"),
]
# 标签里已经把语域写进去了的那族（`kk-*-forms` 的「废弃异体形式」等），不再加前缀
REG_IN_LABEL = ("废弃", "口语", "古体", "罕用", "旧式", "非规范", "方言")


def register_of(tags):
    """→ 该加的语域前缀（`古/方言`），没有就 ''。**判据只许这一份**，闸 import 它。"""
    t = set(tags or ())
    out = []
    for k, zh in REGISTER:
        if k in t and zh not in out:
            out.append(zh)
    return "/".join(out)


def _with_register(t, lab):
    """把语域前缀接到语法说明前面。已经写在标签里的不重复加。

    🔴 **必须幂等**：这个函数既用在生成侧（tags → 新标签），也用在修复脚本
       （已落库标签 → 补前缀），还会被闸调用。不幂等的话「古 · 单数与格」
       再过一遍就变成「古 · 古 · 单数与格」，而闸会把这当成"没修好"报红。
       ⚠️ `REG_IN_LABEL` 挡不住它 —— 「古」不在那张表里（表里是「古体」）。
    """
    if lab == "变形" or any(a in lab for a in REG_IN_LABEL):
        return lab
    r = register_of(t)
    if not r or lab.startswith(r + " · "):
        return lab
    return "%s · %s" % (r, lab)


def register_ok(tags, lab):
    """→ 这一行的标签是不是已经带上了它该带的语域前缀。**闸问这个，不问"再跑一遍等不等"**。"""
    if not lab or lab == "变形":
        return True
    if any(a in lab for a in REG_IN_LABEL):
        return True
    r = register_of(tags)
    return (not r) or lab.startswith(r + " · ")

# compose 识别的全部语法 tag（供 build.py drop-ledger 归桶）
COMPOSE_TAGS = (
    {k for pairs in (MOOD, TENSE, PERSON, NUMBER, GENDER, CASE, STRENGTH, DEGREE, DERIV)
     for k, _ in pairs}
    | {"infinitive", "infinitive-zu", "participle", "predicative", "attributive",
       "definite", "indefinite", "without-article", "includes-article",
       "negative", "future", "future-i", "future-ii", "perfect", "pluperfect",
       "dependent", "independent"}
    | DROP
    | {k for k, _ in REGISTER}          # 2026-09-04 起语域标也被渲染，不再算"未识别"
)


def _pick(t, pairs):
    return [zh for k, zh in pairs if k in t]


# 变化类。**这张表和判据只许一份**，闸与修复脚本都 import 这里。
KLASSEN_ZH = ("强变化", "弱变化", "混合变化")


def klassen_run_together(label):
    """→ 这个标签是不是把多个变化类**连写**了（收尾单 C15 的那个 bug）。

    🔴 判据问的是「**有没有分隔**」，不是「有几个」——
       `强变化/弱变化/混合变化阳性单数宾格` 有三个变化类，但它是**对的**：
       源头说这个形式在强/弱/混合变化下都一样。
       `强变化弱变化混合变化阳性单数宾格` 才是 bug —— 德语里没有这个词。
    ⚠️ 2026-09-04 修完 C15 之后，回归闸的 B3 仍报 122,356 ——
       **那时是闸的判据过期了**（它数的是个数）。而修复脚本里另写了一份带分隔符检查的，
       两份判据打架 ⇒ 抽到这里，谁都别再自己写一遍。
    """
    if not label:
        return False
    n = sum(label.count(k) for k in KLASSEN_ZH)
    if n <= 1:
        return False
    # 连写 = 两个变化类之间**紧挨着**，中间没有分隔符
    for a in KLASSEN_ZH:
        for b in KLASSEN_ZH:
            if a + b in label:
                return True
    return False


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
    lab = _grammar(t, legacy)
    # `legacy` 是「按七月建库那天算」，语域前缀是九月加的 ⇒ 不进 legacy（同 DERIV）
    if legacy or not lab:
        return lab
    return _with_register(t, lab)


def _grammar(t, legacy=False):
    """tags 集合 → 纯语法说明（不含语域前缀）。"""
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
    # 🔴🔴 **收尾单 C15：同一个函数里两种拼法，多值时连写成一个不存在的词。**
    #    源头会把三种变化类打包在一个条目里（这个形式在强/弱/混合变化下都一样），
    #    而 `"".join` 把它拼成 `强变化弱变化混合变化` —— **德语里没有这个词**。
    #    性和格从一开始就用 `"/".join`（`阳性/中性`、`主格/宾格`），是对的；
    #    级、变化类、数漏了。**全库 122,356 行。**
    #    ⇒ 五项统一用 `/`：它们表达的都是「这几种情况下都一样」，不是「先 A 后 B」。
    parts = []
    for x in (deg, st, g, n, ca):
        if x:
            parts.append("/".join(x))
    return "".join(parts)
