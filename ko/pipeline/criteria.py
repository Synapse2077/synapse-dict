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
import re
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


# ═══ B31：例句标签（2026-11-07）═══
# 源头在 `senses[].examples[]` 上标了 `tags`／`raw_tags`。ru（R25）、fr、en、de、es、vi 已做；
# **按语种解耦**：ko 的值域、白名单写在这里（ko 判据唯一的家），不 import 别门。
#
# 五份切片全量值域（2026-11-07 只读扫 1.4 秒）：
#   · en 版 9,844 条里带 414：`collocation` 199、`colloquial` 8、敬语体系 `honorific` 3／`polite` 3／
#     `formal` 2／`informal` 2、`vulgar` 2、`poetic`／`slang`／`literary` 各 1；地区（`Koryo-mar`／
#     `Hamgyong`／`dialectal`）、语法（`transitive`）不收；`raw_tags` 113 种只有 `proverb` 6／`idiom` 3
#     可归类，其余是方言地名（`Gyeongsang dialect, Changwon` 27）与自由文本（`casual` 12 是语体说明
#     但措辞不一 —— `casual polite`／`casual non-polite` 两个方向都有 ⇒ 不收）。
#   · ko 版：`tags` 0，但**正文前缀** `속담:`（谚语）5 条 —— `harvest_examples` 剥前缀时（LABEL_KEEP）
#     这是源头给的类型标记，进 `proverb`。`예문:`（例句）／`例:` 只是「例句」二字，不是标签。
#   · zh 繁体版带 20：`諺語` 1 进 `proverb`；其余是方言地名与自由文本。
#   · zh 简体版／ja 版：0。
# 判据（照 fr／en／de／es／vi 用户定的同一套口径）：逐字白名单；收类型、语体与**韩语敬语体系**
# （这门语言的显著区别，义项层 `KO_REGISTER_LABELS` 已有 `honorific` 敬语／`informal` 非格式体），
# 不收地区、语法、自由文本。
EXAMPLE_TAG_ORDER = (
    "collocation", "proverb", "idiom",
    "honorific", "polite", "formal", "informal",
    "colloquial", "slang", "literary", "poetic", "vulgar",
)
_EX_TAGS = {
    "collocation": "collocation",
    "honorific": "honorific", "polite": "polite", "formal": "formal", "informal": "informal",
    "colloquial": "colloquial", "slang": "slang", "literary": "literary", "poetic": "poetic",
    "vulgar": "vulgar",
}
_EX_RAW = {"proverb": "proverb", "idiom": "idiom", "諺語": "proverb"}
# 正文前缀（`harvest_examples.LABEL_KEEP` 剥掉的那个）→ 键
EX_PREFIX_TAG = {"속담": "proverb"}


def example_tag_set(x, prefix=None):
    """源头一条例句（dict）＋ 收割器剥掉的正文前缀 → 我们的键集合（可能为空）。"""
    ks = set()
    for t in x.get("tags") or ():
        k = _EX_TAGS.get(t)
        if k:
            ks.add(k)
    for t in x.get("raw_tags") or ():
        k = _EX_RAW.get(t)
        if k:
            ks.add(k)
    if prefix in EX_PREFIX_TAG:
        ks.add(EX_PREFIX_TAG[prefix])
    return ks


def join_example_tags(ks):
    """键集合 → 入库字符串（`|` 分隔、按 EXAMPLE_TAG_ORDER 排）；空 → None。"""
    out = [k for k in EXAMPLE_TAG_ORDER if k in ks]
    return "|".join(out) if out else None


def bad_example_tags(v):
    """回归闸的判据：值域外的键、重复、或没按 EXAMPLE_TAG_ORDER 排。"""
    if v is None:
        return False
    ks = v.split("|")
    if any(k not in EXAMPLE_TAG_ORDER for k in ks):
        return True
    return ks != [k for k in EXAMPLE_TAG_ORDER if k in ks]


# ═══ K20：关系边落到**具体词条**（2026-11-11）═══
# 谚文那一页是「词形」不是「词」：`부인` 页上有 婦人／否認／夫人 三个词。关系边原来只有 `target_norm`（词形），
#   读者到了页上得自己认是哪一个，而链接的悬停提示取的是**词形下排第一的释义** ——
#   实测括号汉字能唯一认出目标的 812 条里 **384 条（47%）提示的是别的同形词**（`조정(朝廷)` 提示「划船」）。
# ⇒ 派生列 `sense_relation.target_entry_id`，**只由下面两条规则产出**，认不准就 NULL（不猜）：
#   ① 目标带括号汉字 `부인(婦人)`：目标词形下 `entry.hanja` 与括号里的汉字**唯一相等**的那个词条。
#   ② 目标是**多字**纯汉字串 `不明`：全库 `entry.hanja` 等于它的**唯一**词条（`불명`）。
#      原来指向汉字页 `不明`，而那 1,567 页上没有释义、只有一条「→ 불명」指针 ⇒ 读者要点两次。
#      🔴 **且那个词条至少有一条可印义项**：第一版不带这条，1,144 条原来如实印成文本的会变成点进空白页、
#      43 条从有内容的汉字页改到空页（干跑按「旧落点 × 新落点」拆开才看见）。不满足 ⇒ 维持原样。
#      规则①不加这条：它不改落点（`target_norm` 本来就是那个词形），锚上空词条的效果只是悬停提示
#      不再冒充别的同形词（`무인(武人)` 不再提示「无人居住的」）。
#   ③ 源头页**本身是汉字词**（`詐欺`）上的指针 `hanja_form_of`／`hangeul` → `사기`：目标词形下汉字**等于源头页**的
#      唯一词条（这两种 kind 在语义上就是「这个汉字是那个词的写法」；别的 kind 不保证）。实测 +7,854。
#   ④ **单字**汉字页（`歐`）上的派生词 `구미`：目标词形下汉字**含有这个字**的唯一词条（歐美，不是 口味／龜尾）。
#      🔴 两条护栏，都是干跑逮到的：目标**带括号汉字**的不归它管（`애호(愛護)` 规则①故意留空——我们没有 愛護，
#      ④会把它错锚到 愛好）；目标词形下**有汉字未知的词条**就不锚（那个未知的也可能含这个字）。抽 20/20 对。
#   ③④ 都不改落点（`target_norm` 本来就是那个词形），只认准是哪个词条 ⇒ 不要求有义项。
#   ✗ **单字**汉字目标不锚：`単 alt_of 單` 指的是字符本身，按读音桥会落到 `단`（一堆同音词）。
#   ✗ 汉字表记那一族（`hanja_spelling`／`alt_hanja`）是注，从来不是链接。
# `target`（源头原文）与 `target_norm`（词形落点）一个字不动；新列可以整列撤回。
REL_NOTE_KINDS = frozenset({"hanja_spelling", "alt_hanja"})       # = 展示层 KO_ANNOTATION_KINDS
_K20_HAN = re.compile(r"^[\u3400-\u9fff\uf900-\ufaff\U00020000-\U0003ffff]+$")
_K20_PAREN = re.compile(r"^(.+?)\s*[(（]([^()（）]+)[)）]\s*$")


def relation_target_entry(target, target_norm, kind, entries_of, entries_by_hanja, has_senses, source_word=""):
    """→ (entry_id 或 None, 规则名 或 None)。
    entries_of(word_norm) → [(entry_id, hanja)]；entries_by_hanja(汉字串) → [entry_id]；
    has_senses(entry_id) → 这个词条有没有可印义项（规则②用）；source_word ＝ 这条边所在的页（规则③④用）。"""
    if kind in REL_NOTE_KINDS or not target:
        return None, None
    t = target.replace("^", "").strip()
    m = _K20_PAREN.match(t)
    if m:
        hz = m.group(2).replace(" ", "")
        if _K20_HAN.match(hz) and target_norm:
            hit = [e for e, h in entries_of(target_norm) if h == hz]
            return (hit[0], "括号汉字") if len(hit) == 1 else (None, None)
        return None, None
    tt = t.replace(" ", "")
    if len(tt) >= 2 and _K20_HAN.match(tt):
        hit = entries_by_hanja(tt)
        return (hit[0], "多字汉字") if len(hit) == 1 and has_senses(hit[0]) else (None, None)
    sw = (source_word or "").strip()
    if not target_norm or not sw or not _K20_HAN.match(sw):
        return None, None
    es = list(entries_of(target_norm))
    if kind in ("hanja_form_of", "hangeul"):
        hit = [e for e, h in es if h == sw]
        return (hit[0], "汉字页指针") if len(hit) == 1 else (None, None)
    if kind == "derived" and len(sw) == 1 and es and all(h for _e, h in es):
        hit = [e for e, h in es if sw in h]
        return (hit[0], "单字派生") if len(hit) == 1 else (None, None)
    return None, None
