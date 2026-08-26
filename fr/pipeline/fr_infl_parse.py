#!/usr/bin/env python3
"""把**法文版**的变形说明（法语句子）解析成 kaikki tags。2026-08-22。

═══ 为什么需要这个 ═══
法文版的 `form_of` 义项 **tags 里只有 `form-of` 一个**，没有任何语法标签
（实测 1,940,322 条里 100% 喂给 `infl_compose.compose()` 都退化成「变位形式」四个字）。
语法信息在**法语 gloss 文本**里：

    "Première personne du singulier de l’indicatif présent de encyclopédier."
    "Pluriel de page."
    "Participe passé masculin singulier du verbe aimer."

⇒ 解析成 kaikki tags，再喂给**已有的** `compose()` —— 中文措辞复用七月验证过的那套
   （库里现有 153 种标签），不另起炉灶。

═══ 为什么敢解析文本（这次和"判据用形式代理"不是一回事）═══
这些是**模板生成**的字符串，词表封闭、结构组合式：
    75.0% = {人称} personne du {数} {语气时态} du verbe «X».
    25.0% = {Pluriel | Féminin/Masculin + 数 | Participe passé/présent + 性数} de «X».
实测 4,122 种骨架里**前 200 种覆盖 99.71%**。
⚠️ 但仍然守两条：**① 词表从数据里抽，不凭我对法语语法的记忆写**；
   ② **解析不出来的一律报出来、不猜**（`compose()` 拿不到 tags 就返回 ''，调用方回退）。

═══ 源头自己也有错别字，照收不误 ═══
`su subjonctif imparfait`（应为 du）、`du présent du subjoctif`（应为 subjonctif）、
`de l’'indicatif présent`（多一个撇号）—— 都在词表里显式列出，各几条，不值得写模糊匹配。
"""
import re

# ── 时态短语 → kaikki tags。**键全部来自实测**（`probes/` 那轮扫出来的完整清单）──
# 约定与英文版侧一致（库里已有 153 种标签就是这么来的）：
#   · passé simple = past + historic（**不带 indicative**）⇒ compose 出「简单过去时…」
#   · 光 impératif 不带 présent ⇒「命令式第二人称单数」，带 présent ⇒「命令式现在时…」
TENSE = {
    "du futur": ["indicative", "future"],
    "du futur simple": ["indicative", "future"],
    "du futur de l'indicatif": ["indicative", "future"],
    "du futur simple de l'indicatif": ["indicative", "future"],
    "de l'indicatif futur": ["indicative", "future"],
    "de l'indicatif futur simple": ["indicative", "future"],
    "du conditionnel present": ["conditional", "present"],
    "du conditionnel": ["conditional"],
    "du present du conditionnel": ["conditional", "present"],
    "du present conditionnel": ["conditional", "present"],
    "du passe simple": ["past", "historic"],
    "de l'indicatif passe simple": ["past", "historic"],
    "du passe simple de l'indicatif": ["past", "historic"],
    "de l'imparfait du subjonctif": ["subjunctive", "imperfect"],
    "du subjonctif imparfait": ["subjunctive", "imperfect"],
    "su subjonctif imparfait": ["subjunctive", "imperfect"],        # 源头错别字（su←du）
    "de l'imparfait d subjonctif": ["subjunctive", "imperfect"],    # 源头错别字
    "de l'indicatif present": ["indicative", "present"],
    "du present de l'indicatif": ["indicative", "present"],
    "du present indicatif": ["indicative", "present"],
    "a l'indicatif present": ["indicative", "present"],
    "de l''indicatif present": ["indicative", "present"],           # 源头多一个撇号
    "de l'indicatif": ["indicative"],
    "de l'indicatif imparfait": ["indicative", "imperfect"],
    "de l'imparfait de l'indicatif": ["indicative", "imperfect"],
    "de l'imparfait indicatif": ["indicative", "imperfect"],
    "du l'imparfait de l'indicatif": ["indicative", "imperfect"],   # 源头错别字（du←de）
    "du l'imparfait indicatif": ["indicative", "imperfect"],
    "a l'imparfait de l'indicatif": ["indicative", "imperfect"],
    "de l'imparfait": ["indicative", "imperfect"],
    "du subjonctif present": ["subjunctive", "present"],
    "du present du subjonctif": ["subjunctive", "present"],
    "du present subjonctif": ["subjunctive", "present"],
    "du present du subjoctif": ["subjunctive", "present"],          # 源头错别字
    "de subjonctif present": ["subjunctive", "present"],
    "du subjonctif": ["subjunctive"],
    "de l'imperatif": ["imperative"],
    "de l'imperatif present": ["imperative", "present"],
    "du present de l'imperatif": ["imperative", "present"],
    "du present impratif": ["imperative", "present"],
    "du present impératif": ["imperative", "present"],
    "du present": ["present"],
}
PERSON = {"premiere": "first-person", "deuxieme": "second-person", "troisieme": "third-person"}
NUMBER = {"singulier": "singular", "pluriel": "plural"}
GENDER = {"masculin": "masculine", "feminin": "feminine"}


def _norm(s):
    """归一：小写、弯撇→直撇、去重音符（法语的 é/è 在模板里不区分意义）、压空白。

    ⚠️ 去重音符只用于**匹配键**，不影响任何输出。
    """
    s = s.replace("’", "'").replace("ʼ", "'")
    s = s.lower()
    for a, b in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("â", "a"),
                 ("î", "i"), ("ô", "o"), ("û", "u"), ("ù", "u"), ("ç", "c")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


# 动词式：{人称} personne du {数} {时态} (du verbe|de) X.
_VERB = re.compile(
    r"^(premiere|deuxieme|troisieme) personne d[ue]s? (singulier|pluriel) (.+?)"
    r"(?: du verbe| de| d')\s*\S.*$")
# 分词式
_PART_GN = re.compile(r"^participe (passe|present) (masculin|feminin) (singulier|pluriel)\b")
_PART = re.compile(r"^participe (passe|present)\b")
_MPP = re.compile(r"^(masculin|feminin) (singulier|pluriel) du participe (passe|present)\b")
# 性数式
_GN = re.compile(r"^(?:ancien |anciennes? )?(masculin|feminin) (singulier|pluriel)\b")
_N = re.compile(r"^(?:ancien |anciennes? )?(pluriel|singulier)\b")
_G = re.compile(r"^(masculin|feminin)\b")


def parse(gloss):
    """法语变形说明 → kaikki tags；解析不出来返回 None（**不猜**）。"""
    s = _norm(gloss)
    m = _VERB.match(s)
    if m:
        t = TENSE.get(_norm(m.group(3)))
        if t is None:
            return None
        return ["form-of", PERSON[m.group(1)], NUMBER[m.group(2)]] + t
    m = _PART_GN.match(s)
    if m:
        return ["form-of", "participle", "past" if m.group(1) == "passe" else "present",
                GENDER[m.group(2)], NUMBER[m.group(3)]]
    m = _MPP.match(s)
    if m:
        return ["form-of", "participle", "past" if m.group(3) == "passe" else "present",
                GENDER[m.group(1)], NUMBER[m.group(2)]]
    m = _PART.match(s)
    if m:
        return ["form-of", "participle", "past" if m.group(1) == "passe" else "present"]
    m = _GN.match(s)
    if m:
        return ["form-of", GENDER[m.group(1)], NUMBER[m.group(2)]]
    m = _N.match(s)
    if m:
        return ["form-of", NUMBER[m.group(1)]]
    m = _G.match(s)
    if m:
        return ["form-of", GENDER[m.group(1)]]
    return None


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__file__.rsplit("/", 1)[0]))
    from infl_compose import compose
    CASES = [
        ("Première personne du singulier de l’indicatif présent de encyclopédier.",
         "陈述式现在时第一人称单数"),
        ("Troisième personne du pluriel du passé simple du verbe aimer.",
         "简单过去时第三人称复数"),
        ("Deuxième personne du singulier de l’impératif du verbe finir.", "命令式第二人称单数"),
        ("Deuxième personne du pluriel de l’impératif présent du verbe finir.",
         "命令式现在时第二人称复数"),
        ("Première personne du pluriel de l’imparfait du subjonctif du verbe être.",
         "虚拟式未完成过去时第一人称复数"),
        ("Pluriel de page.", "复数"),
        ("Féminin singulier de beau.", "阴性单数"),
        ("Masculin pluriel de beau.", "阳性复数"),
        ("Participe passé masculin singulier de aimer.", "过去分词阳性单数"),
        ("Participe présent du verbe aimer.", "现在分词"),
        ("Féminin de chien.", "阴性"),
    ]
    bad = 0
    for g, want in CASES:
        got = compose(parse(g) or [])
        ok = got == want
        bad += not ok
        print("   %s %-62s → %-24s %s" % ("✓" if ok else "🔴", g[:62], got,
                                          "" if ok else "期望 " + want))
    print("\n%s" % ("✓ 全部通过" if not bad else "🔴 %d 条不符" % bad))
    sys.exit(1 if bad else 0)
