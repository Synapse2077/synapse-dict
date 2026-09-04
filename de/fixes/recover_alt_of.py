#!/usr/bin/env python3
"""阶段 2a：把被误判成「变形」的异体/缩写词条移回词条层。de 版，2026-09-01。

═══ 缺陷（四门语言全中，同一套解析逻辑必然复现）═══
`de/pipeline/build.py:450` 写的是 `fo = s.get("form_of") or s.get("alt_of")` ——
建库时 `alt_of` 和 `form_of` 被一起当成变形指针丢掉了。可它们根本不是一回事：

    form_of  = 真变形     `Häuser` 是 `Haus` 的复数        → 变形层（阶段 2b）
    alt_of   = 独立词条   `dat` 是 `das` 的鲁尔方言异体     → **词条层，本步**
                          `A` 是 `Ampere` 的缩写
                          `in` 是 `in + den` 的缩合形式

⚠️ 实测两者**无交集**（同时有 `form_of` 和 `alt_of` 的义项 0 条），判据干净。

阶段 1 已经把这批**照原样写进 `sense_src` 证据层**（`sense_id` 留空），
所以本步不用再扫一遍 dump 找它们 —— 但要拿 `alt_of` 数组里的**目标词**拼中文，
而那个字段没进库。⇒ **import `build_entry_layer.scan()`**（它已在阶段 2a 前补上 `targets`），
**不许在这里自己写一遍「哪条算 alt_of」** —— `[[criteria-narrower-than-you-think]]`
的教训是判据抄成两份就必然分叉。

═══ 🔴 关系类型的判据：两路，都不是「猜文本形状」═══
（fr 那轮的实证，pt 已复用，de 不重新设计）
第一版用「第一个 ` of` 之前那段」当关系名 —— **那是形式代理**，立刻造出
`standard of`、`capital of` 这种伪类型。改成两路，优先级 **短语 → tag**：
  ① **封闭白名单短语**（`PHRASE`）：每一条都是 Wiktionary 的**模板名**，
     不是我从文本里归纳的形状。它比 tag 更细 —— tag 只有 `alternative`，
     而模板能分 form / spelling / letter-case。
  ② **kaikki 结构化 tag**（`KIND_TAG`）：短语没命中时用。

═══ 🔴 中文只在「短语路」生成 —— 这条是 fr 花了一轮才收窄的 ═══
tag 说它**是**缩略关系（真的），但 **gloss 可能是词义不是指针**：
fr 的 `poste` gloss 是 'a receiver, an electronic device'（收音机），
生成「poste de radio 的缩写」会**用指针顶掉真词义** —— 那正是这一整步要修的病本身。
⇒ tag 路只记 `sense_relation`，gloss 保持 gloss，中文留空等阶段 1.5。

═══ 中文标签用模板确定性生成，零模型调用 ═══
`[[llm-as-evaluator-discipline]]` ⑩：能确定性回源比对的根本别问模型。
关系类型来自源头结构化字段，中文是模板拼的。

用法（在 de/ 目录下）：
    python3 -u fixes/recover_alt_of.py            # 干跑（判据覆盖率 + 中文样本 + 影响面）
    python3 -u fixes/recover_alt_of.py --apply
    python3 -u fixes/recover_alt_of.py --verify
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build_entry_layer import SRC, scan   # noqa: E402
from build import POS_MAP                 # noqa: E402

# ── 关系类型 → 中文。🔴 这张表就是最终产物：错了就是几千个词条一起错。────────
# 本步写进 `sense_relation.kind` 的值。**抽成常量是为了让闸 import 它** ——
# 2026-09-03 建回归闸时，F3「kind 值域外」报红 8,917 条，而那 8,917 条全是本步写的
# 合法 `alt_of`：闸的值域只取了 `harvest_relations.KIND`，**漏了第二个生成者**。
# `[[fix-regression-and-gate]]`：判据只许一份，闸 import 生成侧那份。
REL_KIND = "alt_of"

KIND_ZH = {
    "alternative": "异体形式",
    "spelling": "异体拼写",
    "letter-case": "大小写变体",
    "abbreviation": "缩写",
    "initialism": "首字母缩写",
    "acronym": "首字母缩略词",
    "clipping": "截短形式",
    "apocopic": "截尾形式",   # 外审：「省尾」太术语，两家都提
    "ellipsis": "省略式",
    "contraction": "缩合形式",
    "pronunciation-spelling": "读音拼写",
    # 🔴 原写「方言音写」是错的：`eye dialect spelling` 不是方言，是**用非标准拼写
    #    摹写口语发音**（`Kaputschino` ← Cappuccino）。v4-pro 指出，回源核对属实。
    "eye-dialect": "读音拼写（摹写口音）",
    "misspelling": "误拼（非规范写法）",
    "misconstruction": "误构形式（非规范）",
    "hypercorrect": "矫枉过正形式（非规范）",
    # ── 🔴 德语专属的两个大族（1,794 条 ＝ 定不出类型那批的 98.6%）──────────
    #    fr/pt 都没有这两条，是 2026-09-01 干跑把「两路都定不出」逐条打出来才发现的。
    "swiss-standard": "瑞士、列支敦士登标准拼写",
    "pre-1996": "旧拼写（1996 年正字法改革前）",
    "pre-1902": "旧拼写（1902 年废止）",
}
# 这三类自带"非规范"警示，**不再叠加时代/语域修饰**，否则会出现「废弃的误拼（非规范写法）」
NO_MOD = {"misspelling", "misconstruction", "hypercorrect",
          # 这两个中文里已经写明「旧拼写」和年份，再叠「废弃/古体」＝「Tal 的废弃旧拼写（1902 年废止）」
          "pre-1996", "pre-1902"}

MOD_ZH = {"obsolete": "废弃", "archaic": "古体", "dated": "旧式", "rare": "罕用",
          "nonstandard": "非规范", "informal": "口语", "colloquial": "口语",
          "literary": "书面", "poetic": "诗体", "proscribed": "不合规范",
          "superseded": "旧", "honorific": "敬称", "regional": "地区"}

# ① 封闭白名单：每条都是 Wiktionary 模板名 → (kind, modifier)
#    🔴 **不许凭印象往里加** —— 干跑会把「两路都定不出」的原文逐条打出来，
#       按打出来的实际短语补，补完再跑一遍看覆盖率。
PHRASE = {
    # ── 🔴 德语专属两条，与 pt「地区信息一律不进中文标签」的先例**有意不同** ──────
    #    pt 那条的理由是：`louisiana form of` 映射成 modifier='regional' 时拼出
    #    「Debaltseve 的地区异体形式」——「地区」这个词**含糊**，既没说清是哪种变体，
    #    也不像中文。⇒ 含糊的修饰不进中文。
    #    而下面这两个不是含糊修饰，是**有名字的正字法标准**：
    #      · 瑞士/列支敦士登废除 ß 全写 ss（`gross`/`groß`、`Fuss`/`Fuß`）—— 1,178 条
    #      · 1996 年正字法改革前的旧拼写（`daß`→`dass`、`Nuß`→`Nuss`）—— 616 条
    #    查 `gross` 的读者需要知道的正是「这在瑞士是标准写法，不是错字」。
    #    ⇒ 判据不是「地区信息进不进中文」，是**「这条信息具体到能不能指着用」**。
    "switzerland and liechtenstein standard spelling of": ("swiss-standard", None),
    "switzerland and liechtenstein standard form of": ("swiss-standard", None),
    "formerly standard spelling of": ("pre-1996", None),
    "formerly standard form of": ("pre-1996", None),
    # ⚠️ **不要**往里加 `standard of` —— 那不是模板，是真释义的开头：
    #    `Lebensstandard → standard of living`（生活水准）、`Wissensstand → standard of knowledge`
    #    被 kaikki 误标成了 alt_of。与 fr 那轮的 `niveau de vie → standard of living` 同一条。
    #    它们走「两路都定不出 ⇒ 当普通释义收录」这条路，**正好是对的**。
    "honorific alternative letter-case form of": ("letter-case", "honorific"),
    "alternative letter-case form of": ("letter-case", None),
    "alternative spelling of": ("spelling", None),
    "alternative form of": ("alternative", None),
    "obsolete spelling of": ("spelling", "obsolete"),
    "obsolete form of": ("alternative", "obsolete"),
    "obsolete and rare spelling of": ("spelling", "obsolete"),
    "archaic spelling of": ("spelling", "archaic"),
    "archaic form of": ("alternative", "archaic"),
    "dated form of": ("alternative", "dated"),
    "dated spelling of": ("spelling", "dated"),
    "nonstandard spelling of": ("spelling", "nonstandard"),
    "nonstandard form of": ("alternative", "nonstandard"),
    "rare spelling of": ("spelling", "rare"),
    "rare form of": ("alternative", "rare"),
    "informal spelling of": ("spelling", "informal"),
    "informal form of": ("alternative", "informal"),
    "superseded spelling of": ("spelling", "superseded"),
    "eye dialect spelling of": ("eye-dialect", None),
    "pronunciation spelling of": ("pronunciation-spelling", None),
    "misspelling of": ("misspelling", None),
    "misconstruction of": ("misconstruction", None),
    "abbreviation of": ("abbreviation", None),
    "initialism of": ("initialism", None),
    "acronym of": ("acronym", None),
    "clipping of": ("clipping", None),
    "ellipsis of": ("ellipsis", None),
    "contraction of": ("contraction", None),
    "apocopic form of": ("apocopic", None),
    "shortened form of": ("clipping", None),
    "short for": ("clipping", None),
    "variant of": ("alternative", None),
    # ── 干跑第二轮按实际打出来的短语补的两条（各 5 条，模板名，不是我归纳的形状）──
    "uncommon spelling of": ("spelling", "rare"),
    "obsolete typography of": ("spelling", "obsolete"),
    # ⚠️ **到此为止**（`PITFALLS` A4：判据改到第三轮就停手，残差当上界如实报）。
    #    剩下的 16 条是地区形式的 singleton（`Upper German form of` / `Bavaria form of` /
    #    `Austria form of` / `Central Germany form of` …）每种 1 条 ——
    #    为 16 条建一张德语方言区表，等于给自己造一张**没有负控的表**
    #    （`[[criteria-narrower-than-you-think]]`）。它们当普通释义收录，
    #    英文 gloss 里的地区信息一个字没丢。
}
PHRASE_ORDER = sorted(PHRASE, key=len, reverse=True)   # 长的先匹配
#  🔴 长的先匹配是硬要求，不是优化：`alternative form of` 会挡住
#     `honorific alternative letter-case form of`（`[[regex-alternation-order]]` 同一形状，
#     那条 bug 我犯过三次）。

# ② tag 兜底，按优先级：更具体的在前
KIND_TAG = ["error-misspelling", "misspelling", "misconstruction", "hypercorrect",
            "acronym", "initialism", "abbreviation", "clipping", "apocopic",
            "ellipsis", "contraction", "pronunciation-spelling", "alternative"]
TAG_ALIAS = {"error-misspelling": "misspelling"}
MOD_TAG = ["obsolete", "archaic", "dated", "rare", "nonstandard",
           "informal", "colloquial", "literary", "poetic", "proscribed"]

# 🔴 德语性别是**词条级**的（der/das/die Band 是三个词条），`sense.gender` 一律留空
#    —— 阶段 0 的闸②里就有这条断言，本步不许破坏它。

# ── 多目标（fr 那轮抽样逮到的）──────────────────────────────────
# kaikki 的 `alt_of` 是数组，里面混着三种东西：多数 [0] 是目标、其余是英文释义或语法注记；
# 少数是**真的多个目标**（缩略词展开被逗号劈开）。
# 🔴 判据「目标是不是库里的真词形」单独用会错（碰巧同形）。
# ⭐ 判据是**语义的**：**异体形式指向唯一的规范形式；而缩写/缩略可以展开成多个词。**
MULTI_OK = {"abbreviation", "initialism", "acronym", "clipping", "apocopic",
            "ellipsis", "contraction"}

# 🔴 目标串本身带模板残渣的，拼出来是垃圾 ⇒ **不生成中文**（宁可空着也不给错的）
TARGET_JUNK = (" form of ", " spelling of ", " plural of ")

# 🔴🔴 **kaikki 把整段从句塞进了 `alt_of[0].word`** —— 实测 975 条。
#    `targets = ['Abend which was deprecated in the spelling reform']`
#    照抄就会拼出「Abend which was deprecated in the spelling reform 的旧拼写」。
#    ⚠️ 判据**不能**用「目标含空格 / 目标太长」那种形式代理，两条都实测反证过：
#      · 含空格：`da sein`、`Weißes Meer` 都是合法多词目标（CH 族里 8 条）；
#      · 太长：`ARD → Arbeitsgemeinschaft der öffentlich-rechtlichen Rundfunkanstalten
#        der Bundesrepublik Deutschland`（7 词）是**完全正确**的缩略语展开。
#      ⇒ 只剥**实测出来的那几个具体尾巴**，一个封闭列表。
#    ⭐ 顺带发现：尾巴里带着**这条异体属于哪次正字法改革**，而那正是读者要的信息 ——
#      所以尾巴不只是要剥掉的垃圾，它还能把 kind 定得更细（见 `refine_kind`）。
TAILS = [
    (" which was deprecated in the spelling reform", "pre-1996"),   # 1996 年改革，616
    (" which was deprecated in ", "pre-1902"),                      # 1901/02 会议，344
    (" used in some older texts", None),                            # ue/oe/ae 变通写法，15
]


def clean_target(t):
    """→ (剥掉从句后的目标, 尾巴指出的 kind|None)。剥不动就原样返回。"""
    for tail, kind in TAILS:
        i = t.find(tail)
        if i > 0:
            return t[:i].strip(), kind
    return t, None


def refine_kind(kind, targets):
    """短语路定完 kind 之后，用**目标里的尾巴**把正字法改革定得更细。

    `Thal` 的 gloss 开头是 `Obsolete spelling of` ⇒ 短语路给「废弃异体拼写」，对但笼统；
    而尾巴写着 `which was deprecated in 1902 following the Second Orthographic
    Conference of 1901` —— 这是**哪一次改革**，读者要的正是这个。
    ⚠️ 只在 kind 本来就是「拼写/异体」这两类时才细化，别去动缩写/误拼那些。
    """
    if kind not in ("alternative", "spelling") or not targets:
        return kind
    return clean_target(targets[0])[1] or kind


def pick_targets(kind, targets, known, self_word=None):
    """→ 拼接用的目标串；None = 不生成中文。known = 库里的词形集合（德语**不折叠大小写**）。"""
    if not targets:
        return None
    targets = [clean_target(t)[0] for t in targets]
    # 🔴 **自指：目标就是这个词自己 ⇒ 零信息，而且读起来是错的。**
    #    2026-09-01 外审逮到 `in`：gloss 是 `contraction of in + den`，
    #    可 kaikki 的 `alt_of[0].word` 只有 `in` ⇒ 拼出「in 的缩合形式」——
    #    `in` 是介词 `in` 与 `den` 的缩合**结果**，不是 `in` 的缩合形式。
    #    全库 8 条（`in`/`Di`/`Schild`/`ietwas`/`jmd`…），量小但 `in` 是高频词。
    #    ⇒ 中文不生成、关系也不写，gloss 原样留给阶段 1.5 翻译（它翻得出来）。
    #    先例：pt 收尾单 C53「关系指向自己 669 条」同一形状。
    if self_word is not None and targets[0] == self_word:
        return None
    if any(j in targets[0] for j in TARGET_JUNK):
        return None
    if kind in ("pre-1996", "pre-1902") and targets[0] not in known:
        # 剥完还落不到库里 ⇒ 说明这条的目标本来就不是我以为的那个，不猜
        #    （这两族的目标是现行正字法，库里一定有；落不到就是我剥错了）
        return None
    if (len(targets) > 1 and kind in MULTI_OK
            and all(t in known for t in targets)):
        return "、".join(targets)
    return targets[0]


def classify(text, tags):
    """→ (kind|None, modifier|None, 判据来源)。kind 为 None ⇒ 当普通释义收录。"""
    low = text.strip().lower()
    for p in PHRASE_ORDER:
        if low.startswith(p):
            k, m = PHRASE[p]
            return k, m, "phrase"
    for t in KIND_TAG:
        if t in tags:
            k = TAG_ALIAS.get(t, t)
            m = next((x for x in MOD_TAG if x in tags), None)
            return k, m, "tag"
    return None, None, "none"


def label_zh(kind, mod, target, how="phrase"):
    """确定性拼中文。**只有 `how=='phrase'` 才生成**（见文件头那段）。"""
    if kind is None or how != "phrase":
        return None
    base = KIND_ZH[kind]
    if kind in NO_MOD or not mod:
        return "%s 的%s" % (target, base)
    return "%s 的%s%s" % (target, MOD_ZH.get(mod, ""), base)


def build():
    """→ merged[word] = 按 dump 顺序排好的 [(is_alt, (ei, si, gloss, tags, targets)), …]

    🔴 排序键是 **(entry_idx, sense_idx)** ＝ dump 里的出现顺序。
       新义项按这个顺序**插进现有序列**，不是追加到末尾 ——
       `A` 的五条缩写义项在源头就排在最前面，追到末尾等于把词条读乱。
    """
    entries, senses_by_word, src_rows, _noun, stat = scan()
    merged = defaultdict(list)
    for word, ei, si, kind, gloss, tags, targets in src_rows:
        if kind == "dup":
            continue                      # 同词形内重复 gloss，建库时就丢了，本步不复活
        merged[word].append((ei, si, kind == "alt_of", gloss, tags, targets))
    for w in merged:
        merged[w].sort(key=lambda x: (x[0], x[1]))
    return {w: [(is_alt, (ei, si, g, t, tg)) for ei, si, is_alt, g, t, tg in v]
            for w, v in merged.items()}, entries, stat


def diagnose(merged, known):
    st, kinds, unclassified = Counter(), Counter(), []
    for w, rows in merged.items():
        for is_alt, (ei, si, g, tags, targets) in rows:
            if not is_alt:
                continue
            k, m, how = classify(g, set(tags))
            if how == "phrase":
                k = refine_kind(k, targets)
            st["判据：%s" % {"phrase": "① 白名单短语", "tag": "② 结构化 tag",
                            "none": "🔴 两路都定不出"}[how]] += 1
            if k:
                kinds["%s%s" % (k, "+" + m if m else "")] += 1
            else:
                unclassified.append((w, g))
    n_alt = sum(st.values())
    print("\n■ alt_of 义项 %s" % f"{n_alt:,}")
    for k, v in sorted(st.items()):
        print("   %-26s %6s  %5.2f%%" % (k, f"{v:,}", 100.0 * v / max(n_alt, 1)))
    print("\n── 关系类型分布（前 18）──")
    for k, v in kinds.most_common(18):
        print("   %6s  %s" % (f"{v:,}", k))
    print("\n── 定不出类型的 %d 条（当普通释义收录，不加关系标签）──" % len(unclassified))
    for w, g in unclassified[:25]:
        print("   %-20s %s" % (w, g[:66]))
    if len(unclassified) > 25:
        print("   …… 其余 %d 条" % (len(unclassified) - 25))

    print("\n── 中文标签样本（每种类型+修饰组合各一条）──")
    shown = set()
    for w, rows in sorted(merged.items()):
        for is_alt, (ei, si, g, tags, targets) in rows:
            if not is_alt:
                continue
            k, m, how = classify(g, set(tags))
            if how == "phrase":
                k = refine_kind(k, targets)
            sig = "%s|%s|%s" % (k, m, how)
            if k and sig not in shown:
                tgt = pick_targets(k, targets, known, w)
                shown.add(sig)
                print("   %-18s %-44s → %s" % (w, g[:44],
                      (label_zh(k, m, tgt, how) if tgt else None)
                      or "（不生成，等阶段 1.5 翻译）"))
    print("   （共 %d 种组合）" % len(shown))
    return n_alt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(con)

    print("■ 复刻建库循环（import build_entry_layer.scan，判据只许一份）…")
    merged, entries, stat = build()
    known = {w for (w,) in con.execute("SELECT word FROM dict")}
    diagnose(merged, known)

    # ── 影响面 ────────────────────────────────────────────────────
    # 🔴 判据在这里被自己打回一次：第一版写的是「没有 sense **且** `infl IS NULL`」，
    #    报出来是 **0**，看着像"这一步没事可做"。可 `infl IS NULL` 恰恰把目标人群
    #    整个排除了 —— 这批词当年正是被当成变形写进 `infl` 的（`gross` 的 infl 是
    #    「groß 的 变形」），它们**永远不满足 `infl IS NULL`**。
    #    ⇒ 又一次「判据把它要找的东西挡在外面」（`[[llm-as-evaluator-discipline]]` ⑫
    #      内连接漏掉 147,405 条那条的同族）。正确判据是**有没有 sense 行**。
    words = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    zero_now = {w for (w,) in con.execute(
        "SELECT d.word FROM dict d WHERE NOT EXISTS("
        "  SELECT 1 FROM sense s WHERE s.word_id=d.id)")}
    gain = {w for w, rows in merged.items()
            if w in zero_now and any(ia for ia, _ in rows)}
    n_mid = sum(1 for w, rows in merged.items()
                if any(ia for ia, _ in rows) and any(not ia for ia, _ in rows)
                and [ia for ia, _ in rows] != sorted([ia for ia, _ in rows]))
    print("\n■ 影响面")
    print("   现在没有任何义项行的词形（点进去只有「X 的 变形」）%8s" % f"{len(zero_now):,}")
    print("   🔴 其中本步会补上**真义项**的                     %8s" % f"{len(gain):,}")
    print("   其余（真变形，归阶段 2b）                         %8s"
          % f"{len(zero_now) - len(gain):,}")
    print("   🔴 alt 义项**夹在中间**、需重排 rank 的词形 %5s" % f"{n_mid:,}")

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    return apply_(con, words, merged, known, entries)


def apply_(con, words, merged, known, entries):
    have = defaultdict(list)
    for sid, rank, w in con.execute(
            "SELECT s.id, s.rank, d.word FROM sense s "
            "JOIN dict d ON d.id=s.word_id ORDER BY s.word_id, s.rank"):
        have[w].append((rank, sid))
    srcid = dict(con.execute("SELECT src_ref, id FROM sense_src WHERE src=?", (SRC,)))
    # 证据行的坐标必须与阶段 1 写进 `sense_src.src_ref` 的**逐字一致**，
    # 否则 relink 一条都挂不上。阶段 1 的格式：`kk-en:词:pos:etym:seq#sense下标`。
    eref = {i: "kk-en:%s:%s:%s:%d" % (w, pos, etym, seq)
            for i, (w, pos, etym, seq, _f1) in enumerate(entries)}
    epos = {i: e[1] for i, e in enumerate(entries)}          # entry 下标 → pos_raw

    new_senses, new_gloss, new_tag, new_rel, relink, reranks = [], [], [], [], [], []
    stat = Counter()
    nid = con.execute("SELECT max(id) FROM sense").fetchone()[0]

    for w, rows in merged.items():
        if w not in words:
            stat["⚠️ 上游新增词形，库里没有 dict 行（阶段 3 收词）"] += 1
            continue
        wid = words[w]
        cur = [sid for _, sid in have.get(w, [])]
        vis = [x for ia, x in rows if not ia]
        if len(cur) != len(vis):
            # 🔴 上游 dump 换过版：143 个词条释义被改写、9 个不再产生义项、370 个新增
            #    ⇒ 这些词的现有序列与复刻序列对不齐，**跳过不动**（阶段 1 闸①(a) 的基线里有名单）
            stat["词形：库内 sense 数与复刻不符（上游漂移，跳过）"] += 1
            continue
        it_vis = iter(cur)
        final = []
        for is_alt, x in rows:
            if not is_alt:
                final.append(("old", next(it_vis), x))
            else:
                nid += 1
                final.append(("new", nid, x))
        old_rank = {s: r for r, s in have.get(w, [])}
        for rank, (kind, sid, x) in enumerate(final, 1):
            ei, si, g, tags, targets = x
            if kind == "old":
                if old_rank[sid] != rank:
                    reranks.append((rank, sid))
                continue
            k, m, how = classify(g, set(tags))
            if how == "phrase":
                k = refine_kind(k, targets)
            # 🔴 `gender` 一律 None：德语性别是**词条级**的（der/das/die Band 是三个词条），
            #    阶段 0 的闸②里有「sense.gender 全为空」这条断言，本步不许破坏它。
            new_senses.append((sid, wid, rank, POS_MAP.get(epos[ei], epos[ei]), None))
            new_gloss.append((sid, "en", "equivalent", 0, g, SRC))
            tgt = pick_targets(k, targets, known, w) if k else None
            zh = label_zh(k, m, tgt, how) if tgt else None
            if zh:
                new_gloss.append((sid, "zh", "equivalent", 0, zh, "template:alt_of"))
                stat["中文由模板生成"] += 1
            else:
                stat["🔴 无中文（tag 路或定不出，等阶段 1.5 翻译）"] += 1
            for t in tags:
                if t in MOD_TAG:
                    new_tag.append((sid, "register", t))
            src_ref = "%s#%d" % (eref[ei], si)
            # 关系层存**剥干净的**目标（`clean_target`），不是 kaikki 那个带从句的原串 ——
            # 展示层会拿它去 dict 里查能不能点，带从句的永远查不到。
            #
            # 🔴 **关系的条件不许绑在中文的条件上**（第一版写的是 `if k and tgt`，
            #    被闸②最后一条逮到，8 个词形因此既没关系也没变形行）：
            #      · 中文生成不了，是因为我**拿不准**（目标剥完落不到库里 ⇒ 不猜）；
            #      · 而关系**是源头的事实**，与我拿不拿得准无关。
            #    `ebensowenig → ebenso wenig`、`Brüßler → Brüssler` 的目标都是对的，
            #    只是这些词库里还没有（阶段 3 才收）。把它们一起吞掉 = 用「我的不确定」
            #    删掉「源头的确定」。⇒ 两个条件分开。
            # ⚠️ 与上面那条「关系不绑中文」不冲突：自指时**关系本身**是零信息，
            #    不是"我拿不准"。判据 import 同一个 `pick_targets`，不另写一份。
            if k and targets and clean_target(targets[0])[0] \
                    and clean_target(targets[0])[0] != w:
                new_rel.append((wid, sid, REL_KIND, clean_target(targets[0])[0],
                                json.dumps({"kind": k, "mod": m}, ensure_ascii=False),
                                SRC, src_ref))
            if src_ref in srcid:
                relink.append((sid, srcid[src_ref]))
                stat["证据行回挂（sense_src.sense_id 补上）"] += 1
            stat["新建义项"] += 1

    print("\n■ 将写入")
    for k, v in sorted(stat.items()):
        print("   %-46s %8s" % (k, f"{v:,}"))
    print("   %-46s %8s" % ("rank 需要重排的现有义项", f"{len(reranks):,}"))
    print("   %-46s %8s" % ("sense_relation", f"{len(new_rel):,}"))

    now = dbtool.snapshot()
    expect = {"#sense": len(new_senses),
              "#sense_gloss": len(new_gloss),
              "#sense_tag": len(new_tag),
              "#sense_relation": len(new_rel)}
    with dbtool.session("keep-v3-altof", expect=expect) as s_:
        # ⚠️ `UNIQUE(word_id, rank)`：先把要动的行挪到负数区，再落最终值 ——
        #    否则新旧 rank 在中途撞车。
        s_.executemany("UPDATE sense SET rank=-rank WHERE id=?", [(i,) for _, i in reranks])
        s_.executemany("UPDATE sense SET rank=? WHERE id=?", reranks)
        s_.executemany(
            "INSERT INTO sense (id,word_id,rank,pos,gender) VALUES (?,?,?,?,?)", new_senses)
        s_.executemany(
            "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) VALUES (?,?,?,?,?,?)",
            new_gloss)
        s_.executemany("INSERT OR IGNORE INTO sense_tag (sense_id,kind,value) VALUES (?,?,?)",
                       new_tag)
        s_.executemany(
            "INSERT OR IGNORE INTO sense_relation (word_id,sense_id,kind,target,tags,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?)", new_rel)
        s_.executemany("UPDATE sense_src SET sense_id=? WHERE id=?", relink)

    con.close()
    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


def verify(con):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("rank 不从 1 连续的词形",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("没有任何 gloss 的 sense",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_gloss g ON g.sense_id=s.id "
           "WHERE g.sense_id IS NULL"), 0),
        ("孤儿 sense_relation（sense_id 指向不存在的义项）",
         q("SELECT count(*) FROM sense_relation r LEFT JOIN sense s ON s.id=r.sense_id "
           "WHERE r.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        ("🔴 sense.gender 全为空（德语性别是词条级）",
         q("SELECT count(*) FROM sense WHERE gender IS NOT NULL"), 0),
        ("🔴 一条释义都没有、也不是变形的词形（本步的目标）",
         q("SELECT count(*) FROM dict d WHERE NOT EXISTS("
           "SELECT 1 FROM sense s WHERE s.word_id=d.id) AND d.infl IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-48s %8s  期望 %s" % ("✓" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
