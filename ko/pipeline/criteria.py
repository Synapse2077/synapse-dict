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
