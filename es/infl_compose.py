"""
A① 变位语法标签组合器（确定性规则）。

由 kaikki 变位 tag 组合出中文语法标签，供 build.py 生成变位行的 translation。
措辞经豆包一次性润色验证（195 个真实模式，153 与豆包一致、42 为规则改进），
现全部由规则确定性组合：只用 tag、固定段序、同维度多值斜杠合并，
不逐行走豆包、不靠示例词猜主语。

段序：[非限定|语气·时态]·[程度]·[派生]·[主语人称]·[主语性]·[主语数]·（voseo）·[自复]·
      [代词块: 与格/宾格·宾语人称·宾语性·宾语数]

用法：
    from infl_compose import compose
    zh = compose(tags)   # tags: kaikki sense 的 tags 列表(已去 form-of)
"""

MOOD     = [("indicative","陈述式"),("subjunctive","虚拟式"),("conditional","条件式"),("imperative","命令式")]
TENSE    = [("present","现在时"),("imperfect","未完成过去时"),("preterite","简单过去时"),("future","将来时")]
NONFIN   = [("infinitive","不定式"),("gerund","副动词"),("participle","过去分词")]
PERSON   = [("first-person","一"),("second-person","二"),("third-person","三")]
NUMBER   = [("singular","单"),("plural","复")]
GENDER   = [("feminine","阴"),("masculine","阳")]
DEGREE   = [("comparative","比较级"),("superlative","最高级")]
DERIV    = [("diminutive","指小形式"),("augmentative","增大形式")]
OBJPERS  = [("object-first-person","一"),("object-second-person","二"),("object-third-person","三")]
OBJGEN   = [("object-feminine","阴"),("object-masculine","阳")]
OBJNUM   = [("object-singular","单"),("object-plural","复")]

# 非语法元标签：不进语法标签（变体类型/语域/地区，交给 A④ 当注记）
DROP = {"form-of","alt-of","combined-form"}

# compose 识别的全部语法 tag（供 build.py 的 drop-ledger 归桶用）
COMPOSE_TAGS = (
    {k for pairs in (MOOD, TENSE, NONFIN, PERSON, NUMBER, GENDER, DEGREE,
                     DERIV, OBJPERS, OBJGEN, OBJNUM) for k, _ in pairs}
    | {"with-voseo", "reflexive", "dative", "accusative"} | DROP
)


def _pick(t, pairs):
    return [zh for k, zh in pairs if k in t]


def compose(tags):
    """kaikki tags -> 中文语法标签；纯变位无法组合时返回 ''（调用方回退'变位形式'）。"""
    t = set(x for x in tags if x not in DROP)
    seg = []
    nf = _pick(t, NONFIN)
    if nf:
        seg.append(nf[0])
    else:
        mo = _pick(t, MOOD)
        if mo:
            seg.append("/".join(mo))
        te = _pick(t, TENSE)
        if te:
            seg.append("/".join(te))
    seg += _pick(t, DEGREE)
    seg += _pick(t, DERIV)
    p = _pick(t, PERSON)
    if p:
        seg.append("第" + "/".join(p) + "人称")
    g = _pick(t, GENDER)
    if g:
        seg.append("/".join(g) + "性")
    n = _pick(t, NUMBER)
    if n:
        seg.append("/".join(n) + "数")
    if "with-voseo" in t:
        seg.append("（voseo）")
    if "reflexive" in t:
        seg.append("自复")
    # 附着代词块
    cl = []
    if "dative" in t:
        cl.append("与格")
    if "accusative" in t:
        cl.append("宾格")
    op = _pick(t, OBJPERS)
    if op:
        cl.append("第" + "/".join(op) + "人称宾语")
    og = _pick(t, OBJGEN)
    if og:
        cl.append("/".join(og) + "性")
    on = _pick(t, OBJNUM)
    if on:
        cl.append("/".join(on) + "数")

    return "·".join(seg + cl)
