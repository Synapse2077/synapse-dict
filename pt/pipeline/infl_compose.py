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

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层

MOOD = [
    ("indicative", "陈述式"),
    ("subjunctive", "虚拟式"),
    ("conditional", "条件式"),
    ("imperative", "命令式"),
]

# ══════ 时态：判据只许一份 ══════
# 🔴 **葡语的时态名本身是复合的**，源头用**多个 tag 编码同一个时态**，不是"几选一"。
#    2026-08-30 外审逮到；回源用规则动词 falar/comer/partir 逐条对上：
#
#      comerei   future+present            = futuro do presente   → 将来时
#      comeria   future+past               = futuro do pretérito  → **条件式**（不是将来时！）
#      comi      past（裸）/ perfect+preterite = pretérito perfeito    → 简单过去时
#      comia     past+continuative / imperfect+preterite = pretérito imperfeito → 未完成过去时
#      partira   pluperfect(+perfect)      = mais-que-perfeito     → 过去完成时
#
#    修之前 `"/".join(tense)` 把它们当成并列，后果分三档：
#      ① 说成**另一个时态**：comeria 标「陈述式将来时」，和 comerei 撞成同一个标签（38,989 条）
#      ② 多出一个不存在的时态：「现在时/将来时」「简单过去时/未完成过去时」（46,779+8,293 条）
#      ③ 时态整个丢掉：`continuative` 根本不在 COMPOSE_TAGS 里被静默丢弃，
#         `past` 不在 TENSE 里 ⇒ comia/comi/comesse 都只剩「陈述式第一人称单数」（125,845 条）
#
# ⚠️ **「/」不是一律错的**：comemos = 现在时 **且** 简单过去时（真同形，-er/-ir 动词第一人称复数）。
#    所以判据不能写成"多个时态 tag 就合并"，必须**逐个签名裁**。
#
# 表按「最具体的排前面」，第一条命中即停 —— `[[regex-alternation-order]]` 那条教训的推广：
# 选择支从左到右 first-match，短的排前面会挡住长的。
TENSE_RULES = [
    # (必须全含,                      中文,              语气覆盖)
    (frozenset({"future", "past"}),        "",              "条件式"),   # futuro do pretérito
    (frozenset({"future", "present"}),     "将来时",         None),
    (frozenset({"past", "continuative"}),  "未完成过去时",    None),
    (frozenset({"imperfect", "preterite"}),"未完成过去时",    None),
    (frozenset({"perfect", "pluperfect"}), "过去完成时",      None),
    (frozenset({"perfect", "preterite"}),  "简单过去时",      None),
    (frozenset({"present", "preterite"}),  "现在时/简单过去时", None),  # ← 真同形，保留「/」
    (frozenset({"pluperfect"}),            "过去完成时",      None),
    (frozenset({"imperfect"}),             "未完成过去时",    None),
    (frozenset({"preterite"}),             "简单过去时",      None),
    (frozenset({"future"}),                "将来时",         None),
    (frozenset({"present"}),               "现在时",         None),
    (frozenset({"past"}),                  "简单过去时",      None),  # 裸 past = pretérito perfeito
]
TENSE_TAGS = frozenset(t for r in TENSE_RULES for t in r[0])

# 源头的同义/无意义 tag：`conjunctive` 是 subjunctive 的欧葡叫法；
# fr 版给**每一个**变位形式都打 `personal`（模板产物，不是"人称不定式"那个 personal）。
SYNONYM_DROP = {"conjunctive"}

PERSON = [("first-person", "一"), ("second-person", "二"), ("third-person", "三")]
NUMBER = [("singular", "单数"), ("plural", "复数")]
GENDER = [("feminine", "阴性"), ("masculine", "阳性")]

DROP = {"form-of", "alt-of", "combined-form"}

COMPOSE_TAGS = (
    {k for pairs in (MOOD, PERSON, NUMBER, GENDER) for k, _ in pairs}
    | TENSE_TAGS
    | {"continuative", "perfect", "conjunctive"}
    | {"personal", "infinitive", "gerund", "participle",
       "negative", "short-form", "long-form"}
    | DROP
)


def _pick(t, pairs):
    return [zh for k, zh in pairs if k in t]


def resolve_tense(t):
    """tag 集合 → (中文时态, 语气覆盖)。表里没有的组合返回 ('', None)。"""
    for need, zh, mood in TENSE_RULES:
        if need <= t:
            return zh, mood
    return "", None


def compose(tags):
    """kaikki tags → 中文语法说明；无法组合时返回 ''（调用方回退'变位形式'）。"""
    t = set(x for x in tags if x not in DROP and x not in SYNONYM_DROP)
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
    # 🔴 先解析时态（可能覆盖语气：futuro do pretérito 的中文名就是「条件式」）
    zh_te, mood_override = resolve_tense(t)
    # 🔴 `conditional` 出现时，语气只写「条件式」。
    #    葡语传统语法把 futuro do pretérito 归在**陈述式**下（所以 fr 版打 conditional+indicative），
    #    中文语法书则单列为条件式；两个都写渲染成「陈述式/条件式」——**不是两种可能，是同一个东西**。
    if "conditional" in t:
        mood_override = "条件式"
    if mood_override:
        seg.append(mood_override)
    else:
        mo = _pick(t, MOOD)
        if mo:
            seg.append("/".join(mo))
    if zh_te:
        seg.append(zh_te)
    te = [zh_te] if zh_te else []
    mo = [mood_override] if mood_override else _pick(t, MOOD)

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
