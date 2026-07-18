"""
意大利语变位语法标签组合器（确定性规则）——it 独立文件，不 import 任何其他语种。

由 kaikki 变位 sense 的 tags 组合出中文语法标签，供 build.py 生成变位行的说明文本。
纯规则、只用 tag、固定段序；不逐行走豆包、不靠示例词猜。

段序：[非限定：不定式/副动词/分词] 或 [语气·时态]·[第X人称]·[单/复数]·[附加：尊称/否定]
  例：['indicative','present','third-person','singular'] → 陈述式现在时第三人称单数
      ['past','historic','first-person','singular']     → 远过去时第一人称单数（passato remoto）
      ['past','participle','feminine','plural']         → 过去分词阴性复数

术语为标准意语语法中译，待豆包抽真实组合验证后定稿（见 build.py 的 --dump-infl）。

用法：
    from infl_compose import compose
    zh = compose(tags)   # tags: kaikki sense 的 tags 列表
"""

# 语气（modo）
MOOD = [
    ("indicative", "陈述式"),
    ("subjunctive", "虚拟式"),
    ("conditional", "条件式"),
    ("imperative", "命令式"),
]
# 时态（tempo）。passato remoto = past+historic，单独特判见下。
TENSE = [
    ("present", "现在时"),
    ("imperfect", "未完成过去时"),
    ("future", "将来时"),
]
PERSON = [("first-person", "一"), ("second-person", "二"), ("third-person", "三")]
NUMBER = [("singular", "单数"), ("plural", "复数")]
GENDER = [("feminine", "阴性"), ("masculine", "阳性")]

# 非语法元标签：不进语法说明（变体类型标记）
DROP = {"form-of", "alt-of", "combined-form"}

# compose 识别的全部语法 tag（供 build.py drop-ledger 归桶）
COMPOSE_TAGS = (
    {k for pairs in (MOOD, TENSE, PERSON, NUMBER, GENDER) for k, _ in pairs}
    | {"historic", "past", "infinitive", "gerund", "participle",
       "negative", "formal", "informal", "second-person-semantically",
       "apocopic", "with-euphonic"}
    | DROP
)


def _pick(t, pairs):
    return [zh for k, zh in pairs if k in t]


def compose(tags):
    """kaikki tags → 中文语法说明；无法组合时返回 ''（调用方回退'变位形式'）。"""
    t = set(x for x in tags if x not in DROP)
    seg = []

    # —— 非限定形式（互斥优先）——
    if "infinitive" in t:
        return "不定式"
    if "gerund" in t:
        return "副动词"
    if "participle" in t:
        if "past" in t:
            base = "过去分词"
        elif "present" in t:
            base = "现在分词"
        else:
            base = "分词"
        # 过去分词有性数一致（用作形容词/复合时态）
        base += "".join(_pick(t, GENDER)) + "".join(_pick(t, NUMBER))
        return base

    # —— 限定形式：语气 + 时态 ——
    mo = _pick(t, MOOD)
    if mo:
        seg.append("/".join(mo))
    # 远过去时（passato remoto）= past + historic
    if "historic" in t:
        seg.append("远过去时")
    else:
        te = _pick(t, TENSE)
        if te:
            seg.append("/".join(te))

    # —— 主语人称 + 数 ——
    p = _pick(t, PERSON)
    if p:
        seg.append("第" + "/".join(p) + "人称")
    n = _pick(t, NUMBER)
    if n:
        seg.append("/".join(n))

    # —— 附加标记 ——
    if "formal" in t:
        seg.append("（尊称 Lei）")
    if "negative" in t:
        seg.append("（否定）")

    return "".join(seg)
