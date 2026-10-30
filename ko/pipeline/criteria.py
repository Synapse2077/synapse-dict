#!/usr/bin/env python3
"""**ko 的共用判据，唯一的家。** 2026-09-24（阶段 8 建外锚闸时抽出来的）。

═══ 为什么抽出来 ═══
建外锚闸时发现 `is_pointer_sense` **在三个文件里各写了一份**
（`build.py` / `intake_editions.py` / `build_sense_layer.py`），
`norm_ko` 写了两份。抽出来的那一刻三份**完全一样** —— 但：

🔴 **闸与收词器的判据一旦漂开，闸报的就是它自己的 bug。**
   fr 那轮从 it 抄了一条「词缀豁免」，当场报 42 条假缺口，逐条读下来 40 条
   是纯指针、收词器跳过是对的。ja 阶段 1 的罗马字断言自己重写了一条规则，报 6 条假红。
   ⇒ 外锚闸**必须 import 收词器用的那一份**，不许重抄。而"那一份"得先存在。

⚠️ 本次抽取是**纯搬运，行为一字不改**（三份原文逐字比对过，完全相同）。
   `[[refactor-mindset-code-quality]]`：同一个映射/判据出现两次就该合并，
   别等它漂开之后再来查是谁改的。

═══ 判据本身 ═══
· `norm_ko`          检索归一＝**NFC**。只用于匹配，不用于身份。
                     源头两版词头 100% 已是 NFC，但 macOS 输入法产出 NFD，
                     长得一样、字节不同、`=` 匹配不上（`KO_PLAN` §二判据 8）。
· `is_pointer_sense` 这条义项是不是「指向别的词」而不是自己有释义。
                     韩语的指针大户是汉字表记（`犬` → "hanja form of 견"）。
                     🔴 判据取**源头逐义项说清楚的字段/标签**，不用形式代理。
· `is_hanja_reading_sense`  `pos_raw=='syllable'` 一刀切 —— 两个方向都验过
                     （正向 99.4% 是汉字音；反向非 syllable 的只有 18 条且都是真义项）。
· `NOT_A_WORD`       ko 真正该拦的只有 `romanization`。
                     🔴 **不要照抄 ja 的 `{soft-redirect, romanization}`** ——
                     ko 的 pos 值域里根本没有 `soft-redirect`。
"""
import unicodedata

NOT_A_WORD = {"romanization"}


def norm_ko(s: str) -> str:
    """检索归一：**NFC**。只用于匹配，不用于身份。"""
    return unicodedata.normalize("NFC", s or "")


def is_pointer_sense(se) -> bool:
    """这条义项是不是「指向别的词」而不是自己有释义。

    韩语的指针大户是汉字表记：`犬` → "hanja form of 견（dog）"，
    `noun` 里就有 12,536 条、`character` 里 2,314 条。
    """
    tg = se.get("tags") or []
    return bool(se.get("form_of") or se.get("alt_of")
                or "form-of" in tg or "alt-of" in tg or "romanization" in tg)


def is_hanja_reading_sense(pos_raw: str) -> bool:
    """这条是不是「汉字音」那种元义项（`주` 有 53 条"义项"、内容只是一个汉字）。"""
    return pos_raw == "syllable"


def real_senses(o):
    """→ [(gloss 文本, 这条义项的原始对象), ...]，**排除指针义项**。

    ⚠️ gloss 取 `glosses[-1]`（层级 gloss 的末项＝本义），与 `build_sense_layer`
       落 `sense_src.text` 时取的是同一项 —— 闸要拿它跟库里比，取法必须一致。
    """
    out = []
    for se in o.get("senses") or []:
        g = se.get("glosses") or []
        if not g:
            continue
        if is_pointer_sense(se):
            continue
        out.append((g[-1], se))
    return out


# ═══ K36②：韩文版词源正文的分类（2026-10-28）═══
# 韩文版 `etymology_texts`（**复数** —— K36 本身就是读单数读出的 0）46,120 条，成分实测：
#   汉字写法「한자 X.」23,136（页面上已印着同一个汉字 ⇒ 不收）／构词式 `A + B` 15,376／
#   来源 `< 영어 date`、`< 중세 한국어 …` 2,734／汉字写法而页面上没有 3,516／其他正文约 1,350。
# 🔴 多词源条目里，源头把**每个义项的例句**也塞进了这个字段（`:* 기적이 일어나기를 빌다.`）
#    ⇒ 以 `:*`／`*:`／`:#`／`#:` 开头的行**整行不是词源**，剔掉；只有标记的行同理。
# 🔴 `(어원 서술)`（＝「词源描述」）是没填的模板占位，不是词源。
ETYM_BULLET = (":*", "*:", ":#", "#:")
ETYM_PLACEHOLDER = {"(어원 서술)", "(어원)", "어원 서술"}


def _all_han(s):
    return bool(s) and all(unicodedata.name(c, "").startswith("CJK") for c in s)


def ko_etym_hanja_line(line):
    """「한자 X.」或裸「X」（X 全是汉字）⇒ X；否则 None。"""
    s = line.strip()
    if s.startswith("한자"):
        s = s[2:].strip()
    s = s.rstrip(".").strip()
    return s if " " not in s and "(" not in s and _all_han(s) else None


def ko_etymology(texts, known_hanja):
    """韩文版一个条目的词源 → (要收的正文 | None, 类别)。

    `known_hanja`：**读者这一页上已经印着的汉字表记**（`entry.hanja` ∪ 未隐藏的
    `hanja_spelling`／`alt_hanja` 目标）。整段只是汉字写法、且全都已在页面上 ⇒ 不收：
    收进来就是把页面上早印着的再说一遍（与阶段 5 日文版「只是汉字」那 3,344 条同一个决定）。
    只要有一个汉字页面上没有，就**整段原样收**（不拆行改写源头）。
    """
    if isinstance(texts, str):
        texts = [texts]
    lines = [l.strip() for t in (texts or []) for l in (t or "").split("\n") if l.strip()]
    body = [l for l in lines
            if not l.startswith(ETYM_BULLET) and any(unicodedata.category(c)[0] in "LN" for c in l)]
    if not body:
        return None, "不收·只有例句或标记" if lines else "无"
    if all(l in ETYM_PLACEHOLDER for l in body):
        return None, "不收·模板占位"
    body = [l for l in body if l not in ETYM_PLACEHOLDER]
    hans = [ko_etym_hanja_line(l) for l in body]
    text = "\n".join(body)
    if all(hans):
        if set(hans) <= set(known_hanja):
            return None, "不收·汉字写法已在页面上"
        return text, "汉字写法（页面上没有）"
    rest = [l for l, h in zip(body, hans) if not h]
    if any("+" in l for l in rest):
        return text, "构词"
    if rest[0][0] in "<＜":
        return text, "来源"
    return text, "正文"
