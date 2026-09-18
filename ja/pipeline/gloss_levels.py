#!/usr/bin/env python3
"""kaikki 的 `glosses` 是**层级数组** —— 拆开它。2026-09-17。

═══ 这个文件为什么存在 ═══
kaikki 每条义项的 `glosses` 不是「一条释义」，是**从伞形到具体的一条路径**：

    ['to exist, to be, to have',  '有る: (inanimate) to exist, be in existence']
    ['in kabuki:',                'the left side of the stage in the Edo-style']
    ["one's cousin (…):",  '従兄弟: a male cousin',  '従兄: an older male cousin']
     └─────── 伞形 ───────┘  └──────── 具体（最后一层）────────┘

🔴🔴 **建库时三处都写的是 `glosses[0]`** —— 伞形留下、具体释义整条丢掉：
    `ある` 的 19 条义项里 12 条共用伞形「to exist, to be, to have」⇒ 落库后同一句印 7 遍
    `長谷川` 的 40 条不同河流共用伞形「Nagatani River (…)」⇒ 40 条河全丢，40 行都写「长谷川」
    而伞形单独看常常没有信息：`in kabuki:` / `short for various terms:` /
    `After the て-form of a verb:` —— 读者拿到一个冒号结尾的半句话。

⚠️ **代价不只是丢内容，还花了钱**：这批里 1,746 条已经翻成中文，翻的是伞形，
   产出是「你」×2、「有」×7。

═══ 判据：为什么是「最后一层是具体，其余是伞形」 ═══
层数实测（三版全量，非抽样）：
    en 版  1 层 181,129 ／ 2 层 1,854 ／ 3 层 15
    ja 版  1 层 176,665 ／ 2 层 2,093
    zh 版  1 层 146,164 ／ 2 层   563 ／ 3 层 16
3 层的那 31 条逐条读过，确认是**同一条路径继续细分**
（`一个人的表亲` → `従兄弟: 男性表亲` → `従兄: 年长的男性表亲`），
不是三条并列 ⇒ `[:-1]` 当伞形、`[-1]` 当具体，对 2 层和 3 层同时成立。

🔴 **只有一层时没有伞形**（返回 None），不是返回空串 ——
   「没有伞形」和「伞形是空的」要分得开，展示层靠它决定印不印小标题。

⚠️ 三处调用方（`build_entry_layer` 收 en 版、`intake_edition_words` 收 ja/zh 版、
   `fixes/fix_hierarchical_gloss` 回填已落库的）**都 import 这一份**。
   `[[etymology-layer-acceptance]]`：同一个假设写在两处、只改一处，三层全绿而端到端才逮到。
"""


def split_levels(glosses):
    """→ (伞形 or None, 具体释义 or None)。

    >>> split_levels(['cat'])
    (None, 'cat')
    >>> split_levels(['in kabuki:', 'the left side of the stage'])
    ('in kabuki:', 'the left side of the stage')
    >>> split_levels(["one's cousin:", '従兄弟: a male cousin', '従兄: an older male cousin'])
    ("one's cousin: 従兄弟: a male cousin", '従兄: an older male cousin')
    >>> split_levels([])
    (None, None)
    """
    gs = [g.strip() for g in (glosses or []) if g and g.strip()]
    if not gs:
        return None, None
    if len(gs) == 1:
        return None, gs[0]
    return " ".join(gs[:-1]), gs[-1]


def specific(glosses):
    """只要具体释义 —— 给那些原来写 `glosses[0]` 的地方替换用。"""
    return split_levels(glosses)[1]


if __name__ == "__main__":
    import doctest
    r = doctest.testmod()
    print("✅ %d 例全过" % r.attempted if not r.failed else "🔴 %d 例失败" % r.failed)
