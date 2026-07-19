"""
葡萄牙语变位语法标签组合器（确定性规则）——pt 独立文件，不 import 任何其他语种。

由 kaikki 变位 sense 的 tags 组合出中文语法标签，供 build.py 生成变位行的说明文本。
纯规则、只用 tag、固定段序；不逐行走豆包、不靠示例词猜。

段序：[非限定：不定式/人称不定式/副动词/分词] 或 [语气·时态]·[第X人称]·[单/复数]·[性]
  例：['indicative','present','third-person','singular'] → 陈述式现在时第三人称单数
      ['preterite','indicative','first-person','singular'] → 简单过去时第一人称单数（pretérito perfeito）
      ['personal','infinitive','first-person','plural']    → 人称不定式第一人称复数（infinitivo pessoal，葡语专属）
      ['pluperfect','indicative','third-person','plural']  → 过去完成时第三人称复数（mais-que-perfeito）
      ['participle','past','feminine','plural']            → 过去分词阴性复数

葡语时态经 kaikki tag：present/preterite(perfeito)/imperfect/pluperfect(mais-que-perfeito)/
future/conditional；语气 indicative/subjunctive(conjuntivo)/imperative。

用法：
    from infl_compose import compose
    zh = compose(tags)
"""

MOOD = [
    ("indicative", "陈述式"),
    ("subjunctive", "虚拟式"),
    ("conditional", "条件式"),
    ("imperative", "命令式"),
]
# 时态。pretérito perfeito=preterite；mais-que-perfeito=pluperfect。
TENSE = [
    ("present", "现在时"),
    ("preterite", "简单过去时"),
    ("imperfect", "未完成过去时"),
    ("pluperfect", "过去完成时"),
    ("future", "将来时"),
]
PERSON = [("first-person", "一"), ("second-person", "二"), ("third-person", "三")]
NUMBER = [("singular", "单数"), ("plural", "复数")]
GENDER = [("feminine", "阴性"), ("masculine", "阳性")]

DROP = {"form-of", "alt-of", "combined-form"}

COMPOSE_TAGS = (
    {k for pairs in (MOOD, TENSE, PERSON, NUMBER, GENDER) for k, _ in pairs}
    | {"personal", "past", "infinitive", "gerund", "participle",
       "negative", "short-form", "long-form"}
    | DROP
)


def _pick(t, pairs):
    return [zh for k, zh in pairs if k in t]


def compose(tags):
    """kaikki tags → 中文语法说明；无法组合时返回 ''（调用方回退'变位形式'）。"""
    t = set(x for x in tags if x not in DROP)
    seg = []

    # —— 非限定形式（互斥优先）——
    # 人称不定式（infinitivo pessoal，葡语专属）：infinitive + personal，随人称变位
    if "infinitive" in t and "personal" in t:
        base = "人称不定式"
        p = _pick(t, PERSON)
        if p:
            base += "第" + "/".join(p) + "人称"
        n = _pick(t, NUMBER)
        if n:
            base += "".join(n)
        return base
    if "infinitive" in t:
        return "不定式"
    if "gerund" in t:
        return "副动词（gerúndio）"
    if "participle" in t:
        if "past" in t:
            base = "过去分词"
        elif "present" in t:
            base = "现在分词"
        else:
            base = "分词"
        base += "".join(_pick(t, GENDER)) + "".join(_pick(t, NUMBER))
        return base

    # —— 限定形式：语气 + 时态 ——
    mo = _pick(t, MOOD)
    if mo:
        seg.append("/".join(mo))
    te = _pick(t, TENSE)
    if te:
        seg.append("/".join(te))

    p = _pick(t, PERSON)
    is_verb_form = bool(mo or seg or p)

    # —— 名词性变位（形容词/名词/分词：性+数，无语气/时态/人称）→ 性 + 数 ——
    if not is_verb_form:
        g = _pick(t, GENDER)
        n = _pick(t, NUMBER)
        return ("/".join(g) + "/".join(n))

    # —— 限定动词：主语人称 + 数 ——
    if p:
        seg.append("第" + "/".join(p) + "人称")
    n = _pick(t, NUMBER)
    if n:
        seg.append("/".join(n))

    if "negative" in t:
        seg.append("（否定）")

    return "".join(seg)
