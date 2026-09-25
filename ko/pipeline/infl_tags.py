#!/usr/bin/env python3
"""变形 tag 的**分类表** —— 哪个 tag 说明这个 form 是什么。2026-09-21。

🔴 **这张表只许有一份**，阶段 2c 的变形层、2d 的关系层都 import 它。
   ja 上同一个 POS_MAP 写了两份，结果同一个概念在库里有两个码
   （`[[refactor-mindset-code-quality]]`）。

═══ 为什么要分类，而不是写一个黑名单 ═══
第一版判据写的是「排除 `romanization` / `transliteration` / `hanja` / `hangeul` /
元数据三个」，看着够用。实测 tag 值域**95 种**之后发现漏了四类：

    McCune-Reischauer  5,312     ← 罗马字，但**不带** `romanization` tag
    revised            5,259     ← 同上
    Yale               4,115     ← 同上
    eumhun             3,449     ← 汉字训读，属 `hanja_reading` 不属变形层

⇒ 黑名单只挡得住"我想到的"。改成**白名单 + 剩余必须显式分类 + 断言无漏网**：
  `classify()` 遇到没分类的 tag 直接抛异常，而不是默默把它当变形收进去
  （`PLAYBOOK` 7.2「闸自证」：库里出现的每一种取值必须在扫描表的值域里）。

═══ 五类的判据（按**含义**，不按 tag 长什么样）═══
  INFLECTION  这个 form 是原形的一个**活用/屈折形**        → `inflection` 表
  RELATION    这个 form 是**另一个词**（异体/方言/缩略）     → `sense_relation` 表
                🔴 `PLAYBOOK` 四.2f：**异体不是屈折，它的家在关系层**
  SCRIPT      这个 form 是同一个词的**另一种写法**（汉字/谚文/罗马字）
                → 汉字进 `entry.hanja`、谚文对应进关系层、罗马字阶段 3 处理
  META        这不是词形，是**关于活用表本身的元数据**       → `entry.conj_class` 等
  MODIFIER    修饰词，**自己不决定分类**（`usually` `sometimes` `common`）
                → 跟着同一个 form 上的其他 tag 走
"""

# 活用/屈折 —— 敬语阶 × 时制 × 语气 × 句式
INFLECTION = {
    "formal", "informal", "polite", "impolite", "honorific",
    "past", "non-past", "present", "future",
    "indicative", "interrogative", "imperative", "hortative", "assertive",
    "conditional", "causative", "contrastive", "determiner", "determinative-of",
    "conjunctive", "connective", "conjugative-of", "infinitive", "sequential",
    "motive-form", "noun-from-verb", "substantive", "negative",
    "short-form", "before-vowel",
    # ⚠️ `counter` **不在这儿** —— 见下面 RELATION：`나무 → 그루`（树→棵）是
    #    「这个名词用什么量词」，是词汇关系，不是 `나무` 的活用形。抽样逮到的。
}

# 另一个词 —— 异体 / 方言 / 语域 / 时代。**它们的家在关系层**
RELATION = {
    "alternative", "variant",
    # 方言与地域
    "dialectal", "Gyeongsang", "Jeolla", "Hamgyong", "Gangwon", "Yukjin",
    "Koryo-mar", "Yanbian", "Northern", "Southern", "Eastern", "Southeastern",
    "North-Korea", "South-Korea", "Seoul",
    "China", "Russia", "US", "Peru", "Panama", "Iran", "Uri",
    # 规范性与构词
    "nonstandard", "misspelling", "proscribed", "contraction", "abbreviation",
    "clipping", "initialism",
    # 语域
    "colloquial", "slang", "Internet", "literary", "poetic", "vulgar",
    "offensive", "derogatory", "humorous", "endearing",
    # 时代
    "archaic", "obsolete", "dated", "Modern", "Early", "Early-Modern-Korean",
    # 频度（单独出现时说明"这是个不常用的异体"）
    "rare", "uncommon",
    "-na",
    # 🔴 量词：`나무 → 그루`（树→棵）、`양 → 마리`（羊→只）。
    #    第一版把它放进了 INFLECTION，抽样时看见 `나무 → 그루` 才发现 ——
    #    量词是**另一个词**，不是这个词的屈折形。84 条。
    "counter",
}

# 另一种写法 —— 不是新词，是同一个词的不同 script
SCRIPT = {
    "romanization", "transliteration", "McCune-Reischauer", "revised",
    "revised-jeon", "Yale", "Cyrillic", "Leet",
    "hanja", "hangeul", "eumhun", "CJK",
}

# 关于活用表本身的元数据，不是词形
META = {
    "table-tags", "class", "inflection-template", "canonical",
    "error-unknown-tag",
}

# 修饰词：自己不决定分类，跟着同一个 form 上的其他 tag 走
MODIFIER = {"usually", "sometimes", "especially", "common"}

ALL = INFLECTION | RELATION | SCRIPT | META | MODIFIER


class UnknownTag(Exception):
    """🔴 出现了没分类的 tag。**抛异常，不默认归到任何一类** ——
    默认值的方向决定了它拦不拦得住人，而"默默当成变形收进去"是最糟的那个方向。"""


def classify(tags):
    """一组 tag → 'inflection' / 'relation' / 'script' / 'meta' / None。

    🔴 **返回 `None` 的一律不进变形层**（调用方负责落账）。实测 190 条：
        162 条**空 tag** —— 全部来自旧模板 `ko-conj-adj` 的残留，内容是
            表头文字被当成词形（`Formal non polite` / `해라체` / `해체`）
            ＋ 旧拼写的变形形（`가까와`，现代规范是 `가까워`）
            ＋ 带前缀的脏数据（`past: 가까왔냐`）
          ⚠️ 与 ja 阶段 2 那个教训同形：**扁平遍历 forms 看不见表**，
             表头会混进词形里（ja 那次 108 个词无一幸免）。
         28 条 `usually`/`sometimes` —— 汉字表记的可选性
            （`사랑 → no hanja`「通常不写汉字」／`사랑 → 思郞`「有时写作」），
            那是 K2 那批 alt_hanja 的同类，不是变形。

    优先级（高到低）：META > SCRIPT > RELATION > INFLECTION
    🔴 **SCRIPT 和 RELATION 压过 INFLECTION**，因为它们回答的是
      「这个 form 到底是不是原形的屈折」这个更前置的问题：
      `('Gyeongsang','dialectal','past')` 是**庆尚道方言的过去式** ——
      它首先是另一个词的形，不该混进标准语的活用表里。
    """
    ts = set(tags or [])
    unknown = ts - ALL
    if unknown:
        raise UnknownTag("没分类的 tag：%s（全部 tag：%s）" % (sorted(unknown), sorted(ts)))
    if ts & META:
        return "meta"
    if ts & SCRIPT:
        return "script"
    if ts & RELATION:
        return "relation"
    if ts & INFLECTION:
        return "inflection"
    return None            # 只有 MODIFIER，或空 tag —— 调用方自己决定


# ── 变形标签的中文名。**确定性规则组合**，不给 166 种组合各写一条 ──
# `PLAYBOOK` 二：「变位/变形语法标签，确定性规则组合」。
# 🔴 展示层的映射表**不在这儿也不在 App.tsx**，最终要搬进 `packages/dict-labels`
#    （`[[dict-labels-package]]`）。这里存的是**入库时就要算好的 `label_zh`**。
LABEL_ZH = {
    # 敬语阶（韩语的核心维度）
    "formal": "格式体", "informal": "非格式体",
    "polite": "尊敬", "impolite": "不尊敬", "honorific": "敬语",
    # 时制
    "past": "过去", "non-past": "非过去", "present": "现在", "future": "将来",
    # 语气/句式
    "indicative": "陈述", "interrogative": "疑问", "imperative": "命令",
    "hortative": "共动", "assertive": "断定",
    "conditional": "条件", "causative": "使动", "contrastive": "对比",
    "determiner": "冠形", "determinative-of": "冠形",
    "conjunctive": "连接", "connective": "连接", "conjugative-of": "活用",
    "infinitive": "不定", "sequential": "顺序",
    "motive-form": "意图", "noun-from-verb": "名词形",
    "substantive": "体言", "negative": "否定",
    "short-form": "缩略", "before-vowel": "元音前", "counter": "量词",
}


def label_zh(tags):
    """一组变形 tag → 中文标签（按 `LABEL_ZH` 的**声明顺序**拼，不按字母序）。

    🔴 顺序按语法维度固定（敬语阶 → 时制 → 语气），不按 `sorted(tags)` ——
       字母序会把「格式体过去陈述」排成「陈述格式体过去」，读起来是乱的。
       Python 3.7+ 的 dict 保序，`LABEL_ZH` 的书写顺序就是展示顺序。
    """
    ts = set(tags or [])
    parts = [zh for t, zh in LABEL_ZH.items() if t in ts]
    # 去重但保序（`determiner`/`determinative-of` 都映射到「冠形」）
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return "".join(out)
