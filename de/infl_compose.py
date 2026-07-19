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

# 非语法元标签：不进语法说明
DROP = {"form-of", "alt-of", "combined-form", "multiword-construction",
        "table-tags", "inflection-template", "class"}

# compose 识别的全部语法 tag（供 build.py drop-ledger 归桶）
COMPOSE_TAGS = (
    {k for pairs in (MOOD, TENSE, PERSON, NUMBER, GENDER, CASE, STRENGTH, DEGREE)
     for k, _ in pairs}
    | {"infinitive", "infinitive-zu", "participle", "predicative", "attributive",
       "definite", "indefinite", "without-article", "includes-article",
       "negative", "future", "future-i", "future-ii", "perfect", "pluperfect",
       "dependent", "independent"}
    | DROP
)


def _pick(t, pairs):
    return [zh for k, zh in pairs if k in t]


def compose(tags):
    """kaikki tags → 中文语法说明；无法组合时返回 ''（调用方回退'变形'）。"""
    t = set(x for x in tags if x not in DROP)

    # —— 动词非限定形式（互斥优先）——
    if "infinitive-zu" in t:
        return "带 zu 不定式"
    if "infinitive" in t:
        return "不定式"
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
