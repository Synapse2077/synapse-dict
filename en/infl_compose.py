#!/usr/bin/env python3
"""把 kaikki 的形态 tag 组合拼成中文语法说明 —— **判据只许这一份**。2026-09-07。

═══ 为什么是组合式，不是枚举组合 ═══
实测 form_of 义项上有 **900 种** tag 组合，前 30 种覆盖 99.5%。
枚举组合能盖住那 30 种，但**剩下 870 种会静默落空**；而且换一版 dump 就会冒出新组合。
⇒ 按**特征**拆开识别（时态/体/数/人称/级/语气），再按固定顺序拼 ——
   没见过的组合也拼得出来。

═══ 🔴 屈折 vs 构词分开（`kind` 列）═══
de 阶段 2 外审时两家一致的结论：**指小词/施事名词是「派生出的新词」**，
与 `houses → house` 并排展示会让读者以为是同一个词的格形式。
en 同族：`agent`（施事）/`diminutive`（指小）/`feminine`（阴性形式）/`morpheme`（构词成分）
⇒ `kind='derivation'`，其余 `kind='inflection'`。

═══ 🔴 拼不出来就不拼 ═══
识别不出核心特征的组合**不产生 inflection 行**，落 drop-ledger。
**绝不回退成泛泛的「变形」** —— de 收尾单 C16 记着「5.6 万行『变形』其实是异体拼写」，
那正是回退默认值造成的。**宁可缺，不可错。**

自检：python3 infl_compose.py
"""

# 修饰语（拼在最前，按此顺序）
MOD = [("obsolete", "废弃"), ("archaic", "古体"), ("dated", "旧时"),
       ("nonstandard", "非标准"), ("proscribed", "受非议"), ("rare", "罕用"),
       ("uncommon", "少见"), ("dialectal", "方言"), ("informal", "非正式"),
       ("UK", "英式"), ("US", "美式"), ("Australia", "澳式"), ("Canada", "加式"),
       ("plural-only", "仅复数"), ("in-compounds", "构词中")]

# 构词（不是屈折）—— 见文件头
DERIV = {"agent": "施事形式", "diminutive": "指小形式", "feminine": "阴性形式",
         "masculine": "阳性形式", "morpheme": "构词成分", "augmentative": "指大形式"}

PERSON = {"first-person": "第一人称", "second-person": "第二人称", "third-person": "第三人称"}


def compose(tags):
    """→ (label_zh, kind) 或 (None, None) 表示拼不出

    tags: 该义项的 tag 列表（`form-of` 本身可在可不在）
    """
    t = set(tags or ())
    t.discard("form-of")
    mods = [zh for k, zh in MOD if k in t]

    # ── 构词优先判：它不是屈折
    for k, zh in DERIV.items():
        if k in t:
            return ("".join(mods) + zh, "derivation")

    past = "past" in t
    present = "present" in t
    part = "participle" in t
    ger = "gerund" in t
    plural = "plural" in t
    singular = "singular" in t
    person = next((zh for k, zh in PERSON.items() if k in t), None)
    comp = "comparative" in t
    sup = "superlative" in t

    core = None
    if comp:
        core = "比较级"
    elif sup:
        core = "最高级"
    elif part and past:
        core = "过去分词"
    elif part and present and ger:
        core = "现在分词（动名词）"
    elif part and present:
        core = "现在分词"
    elif ger:
        core = "动名词"
    elif person and singular:
        # thou/he 形式：第三人称单数现在时、第二人称单数过去时…
        core = "%s单数%s时" % (person, "过去" if past else "现在")
    elif person:
        core = "%s%s时" % (person, "过去" if past else "现在")
    elif "infinitive" in t:
        core = "不定式"
    elif "dative" in t:
        core = "与格"
    elif past:
        core = "过去式"
    elif present:
        # 🔴 对称性缺陷：`past` 单独出现能拼「过去式」，`present` 却掉进 ledger（25 条）。
        #    量小，但**判据不对称本身就是缺陷**，与它命中多少行无关。
        core = "现在时" if "perfect" not in t else "现在完成时"
    elif plural:
        core = "复数"
    elif singular:
        core = "单数"
    elif "imperative" in t:
        core = "祈使形式"
    elif "subjunctive" in t:
        core = "虚拟式"
    elif "genitive" in t:
        core = "属格"

    if core is None:
        # 🔴 拼不出就返回 None，**不回退成「变形」**（de 收尾单 C16 那个病）
        return (None, None)
    if plural and core not in ("复数",) and "复数" not in core:
        core += "（复数）"
    return ("".join(mods) + core, "inflection")


if __name__ == "__main__":
    CASES = [
        (["form-of", "plural"], "复数", "inflection"),
        (["form-of", "participle", "past"], "过去分词", "inflection"),
        (["form-of", "gerund", "participle", "present"], "现在分词（动名词）", "inflection"),
        (["form-of", "indicative", "present", "singular", "third-person"],
         "第三人称单数现在时", "inflection"),
        (["form-of", "past"], "过去式", "inflection"),
        (["form-of", "comparative"], "比较级", "inflection"),
        (["form-of", "superlative"], "最高级", "inflection"),
        (["form-of", "archaic", "indicative", "present", "singular", "second-person"],
         "古体第二人称单数现在时", "inflection"),
        (["form-of", "archaic", "indicative", "past", "singular", "second-person"],
         "古体第二人称单数过去时", "inflection"),
        (["form-of", "obsolete", "participle", "past"], "废弃过去分词", "inflection"),
        (["form-of", "plural", "rare"], "罕用复数", "inflection"),
        (["form-of", "UK", "participle", "past"], "英式过去分词", "inflection"),
        (["form-of", "agent"], "施事形式", "derivation"),
        (["form-of", "diminutive"], "指小形式", "derivation"),
        (["form-of", "morpheme", "plural"], "构词成分", "derivation"),
        # 🔴 拼不出的必须返回 None，不许回退成「变形」
        (["form-of"], None, None),
        (["form-of", "attributive"], None, None),
        (["form-of", "uncommon"], None, None),
        # 对称性：past 有的分支 present 也要有
        (["form-of", "present"], "现在时", "inflection"),
        (["form-of", "perfect", "present"], "现在完成时", "inflection"),
        (["form-of", "dialectal", "indicative", "present"], "方言现在时", "inflection"),
        (["form-of", "infinitive", "plural-of"], "不定式", "inflection"),
        (["form-of", "dative", "plural-of"], "与格", "inflection"),
    ]
    bad = 0
    for tags, wz, wk in CASES:
        gz, gk = compose(tags)
        ok = (gz == wz and gk == wk)
        bad += not ok
        print("   %s %-48s → %s / %s%s"
              % ("✅" if ok else "🔴", "+".join(t for t in tags if t != "form-of") or "(无)",
                 gz, gk, "" if ok else "   期望 %s / %s" % (wz, wk)))
    print("\n   %s" % ("✅ %d/%d" % (len(CASES), len(CASES)) if not bad else "🔴 %d 条不符" % bad))
    raise SystemExit(1 if bad else 0)
