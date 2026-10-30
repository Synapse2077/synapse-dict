#!/usr/bin/env python3
"""B17：兜底的 `related` 撞上更具体的 kind —— **跨门共用的唯一一份判据**。2026-10-27。

═══ 读者看见的 ═══
同一页、同一个目标，既印在「相关词」下又印在「派生词／近义词／下位词…」下：

    de Herzog   下位词 Erzherzog … ／ 派生词 Erzherzog … ／ 相关词 Erzherzog …
    es tu       近义 su ／ 相关 su

`related` 是兜底的袋子，更具体的那个说得更多，兜底那条不提供新信息。

═══ 判据按「读者那一页」写，不按数据范围写 ═══
账上原口径只量了**词条级**（`sense_id IS NULL`）的同目标 —— de 4,449／ja 2,532／es 67。
渲染出来读之后，重复还有两种形状（2026-10-27 量）：
  · 同一条**义项内**两个 kind 撞（de 4,413 条：`synonym` 页义项 1「反义 antonym ／ 相关 antonym」）
  · 词条级 `related`、而某条义项里已经有更具体的 kind（de 3,772 条）
以及 ja 独有的一种：ja 视图把 `derived` **上浮到页尾「构词」区**（`JA_RELATION_SECTION`），
所以义项 2 的「相关词 猫舌」和页尾的「派生词 猫舌」是同一页上的重复，哪怕数据里挂在不同义项上。

⇒ 一条 `related` 是冗余的，当且仅当同页同目标在 `subsume` 里的某个 kind 下也印着，并且：
     ① 两条在同一范围（同一义项，或都在词条级）；或
     ② `related` 在词条级（它说"适用于整个词"，而某条义项已经说得更具体）；或
     ③ 更具体的那条是**全页可见**的（词条级，或这门视图上浮到页尾的 kind）。
  **保留**的只有：两条挂在不同义项上、且都留在义项里 —— 那是各义项自己的信息
  （布局闸早就认定「同一个近义词出现在两条义项下」是合法的逐义项信息）。

═══ `subsume` 由各门按自己的值域列，不许照抄 ═══
  · 只放**语义上更具体**的 kind（含构词 `derived`、惯用语/谚语）。
  · 🔴 不放**书写系统**一族（`alt_of`／`abbreviation`／`kyujitai`；ko 的 `hangeul`／`hanja_*`）：
    ko 第一版没排除它们 ⇒ 宽了 13 倍。
  · 🔴 不放**语音**关系 `paronym`：vi 实测 naive 判据宽 11 倍，差的全是 `paronym+related`。
  · 不放同为兜底的 `see_also`（谁也不比谁具体）。
"""
from collections import defaultdict
import unicodedata

# 各门登记：更具体的 kind ／ 视图上浮到页尾、全页可见的 kind。
# 🔴 值域取自 2026-10-27 各库 `SELECT DISTINCT kind`；新 kind 进来不会自动算「更具体」，
#    跨门闸 `scripts/test_redundant_related_gate.py` 的 K0 会把未登记的 kind 报出来。
SUBSUME_BASE = frozenset({"derived", "synonym", "antonym", "hyponym", "hypernym",
                          "coordinate", "meronym", "holonym"})
REGISTRY = {
    "de": dict(subsume=SUBSUME_BASE | {"expression", "proverb"}, floated=frozenset(),
               not_subsume=frozenset({"alt_of"})),
    "ja": dict(subsume=SUBSUME_BASE | {"proverb"}, floated=frozenset({"derived"}),
               not_subsume=frozenset({"alt_of", "abbreviation", "kyujitai", "see_also"})),
    "es": dict(subsume=SUBSUME_BASE, floated=frozenset(), not_subsume=frozenset()),
}


def _fold(t):
    """目标的比较键：去掉组合重音符（ru/es 偶有带重音与不带两种写法），其余原样。"""
    d = unicodedata.normalize("NFD", t or "")
    return unicodedata.normalize("NFC", d.replace("́", "").replace("̀", ""))


def redundant(rows, subsume, floated=frozenset()):
    """rows: 可见关系 (id, word_id, sense_id, kind, target)。→ 冗余的 `related` 的 id 列表。"""
    scope = defaultdict(set)     # (词, 范围, 目标) → kinds
    page = defaultdict(set)      # (词, 目标) → 全页可见的 kinds（词条级 ＋ 上浮的）
    sensed = defaultdict(set)    # (词, 目标) → 挂在任一义项上的 kinds
    for _i, w, s, k, t in rows:
        t = _fold(t)
        scope[(w, s, t)].add(k)
        if s is None or k in floated:
            page[(w, t)].add(k)
        if s is not None:
            sensed[(w, t)].add(k)
    out = []
    for i, w, s, k, t in rows:
        if k != "related":
            continue
        t = _fold(t)
        if (scope[(w, s, t)] & subsume                       # ①
                or (s is None and sensed[(w, t)] & subsume)  # ②
                or page[(w, t)] & subsume):                  # ③
            out.append(i)
    return out
