#!/usr/bin/env python3
"""把源头的 tag 组合确定性地拼成中文语法说明。2026-09-15。零模型调用。

═══ 为什么能确定性做 ═══
日语活用的 tag 词汇是**有界的**：真形态行里只出现 31 个 tag，
adj 23 种组合、verb 76 种。能用规则做的一律不问模型（`PLAYBOOK` §5.3）。

═══ 🔴 顺序就是判据 ═══
日语的活用是**黏着**的，一个形式上可以叠好几层：
    食べさせられなかった = 使役 + 被动 + 否定 + 过去
中文说明必须按**贴着词干由内往外**的顺序排，排反了意思就变了
（`[[regex-alternation-order]]` 记的是同一类病：顺序本身就是判据）。
⇒ `ORDER` 里的次序不许随手改。

═══ 六活用形用学校文法的名字 ═══
源头的 tag 是西洋语法的说法，日语读者（和中文读者）熟悉的是学校文法的六个名字：
    irrealis→未然形  continuative→连用形  terminative→终止形
    attributive→连体形  hypothetical→假定形  imperative→命令形
⚠️ `stem` 与它们同现时不单独出字（`continuative+stem` 就是连用形），
   单独出现时才叫「词干」。

自检：python3 ja/pipeline/infl_compose.py
"""
import re

# 🔴 次序＝贴着词干由内往外。改这个列表就是改语义。
ORDER = [
    # ⓪⁻ 语体（文語/口語）—— 放在最前，先告诉读者「这是哪一套语法」
    #    2026-09-19 补：源头用 `ja-conj-bungo` 模板把文語表单独分了块，我们原来**把这个
    #    分隔符整个丢了**，864 个词的文語形混进现代活用里印（70 个词两套并排）。
    "bungo",
    # ⓪ 同形歧义的提示 —— 放最前
    "possibly",
    # ① 语态/态（最贴词干）
    "causative", "passive", "potential", "desiderative",
    # 2026-09-16 补：`fixes/recover_pointer_senses.py` 从英文版指针正文里
    # 抽出的短语用到这五个，而本表原来没有 ⇒ `compose()` 拼不出、9 个词形留空。
    # 🔴 **补进这一张表，不另建** —— 两张表迟早漂开
    # （`[[refactor-mindset-code-quality]]`：同一文件里两张重复映射表已经发生过）。
    "nominalized",
    # ② 体
    # 🔴 `progressive` 是 2026-09-19 新建的 tag，不是源头给的：源头把进行体组
    #    整组标成了 `desiderative`（`食べています` 印成「愿望敬体」）。
    "progressive",
    "perfect", "perfective", "imperfective", "completive",
    # ③ 敬体/简体
    "formal", "polite", "honorific", "humble", "informal", "archaic",
    # ④ 极性
    "negative",
    # ⑤ 时
    "past",
    # ⑥ 活用形名（最外层，说明它在句中怎么用）
    "irrealis", "continuative", "terminative", "attributive",
    "hypothetical", "conditional", "realis-conditional", "imperative", "volitional",
    "adverbial", "realis", "conjunctive", "contrastive", "-tari",
    "evidential", "noun-from-verb", "stem",
    "emphatic", "topicalized", "plural",
    # ⑦ 限定语 —— 源头写在**格子里**的（`short form: 食べさす`），加括号挂在最后。
    #    放最后是为了让主干先读完：「可能敬体（ら抜き）」而不是「可能ら抜き敬体」。
    "standard", "colloquial", "written", "spoken", "short-form", "contraction",
    "request", "nasai", "prohibitive", "ra-nuki",
]

TAG_ZH = {
    "possibly": "可作",          # 同形歧义：`保護される` 可作被动也可作敬语
    "causative": "使役", "passive": "被动", "potential": "可能", "desiderative": "愿望",
    "nominalized": "体言化",      # `読むこと` 这类把用言变成体言的形
    "humble": "谦让语",           # 与 `honorific`（尊敬语）相对，日语敬语的另一侧
    "emphatic": "强调",
    "topicalized": "提示",        # `は` 提示主题
    "plural": "复数",
    "perfect": "完成", "perfective": "完成体", "imperfective": "未完成体",
    "completive": "完了",
    # ⚠️ `formal`（英文版）与 `polite`（日语版）说的是同一件事 —— **丁寧語＝敬体**，
    #    两版用词不同而已。`honorific` 才是尊敬语（`される`/`なさる`），别混。
    "formal": "敬体", "polite": "敬体", "honorific": "尊敬语",
    "informal": "简体", "archaic": "古语",
    "negative": "否定", "past": "过去",
    # ── 六活用形：用学校文法的名字 ──
    "irrealis": "未然形", "continuative": "连用形", "terminative": "终止形",
    "attributive": "连体形", "hypothetical": "假定形", "imperative": "命令形",
    "conditional": "条件形", "volitional": "意志形", "adverbial": "连用形（作状语）",
    "realis": "已然形", "conjunctive": "接续形", "contrastive": "对比形",
    # 全量跑一遍逐个对照，只有这一个组合拼不出来（`-tari+stem`，1 行）。补上而不是丢掉：
    # たり形是并列列举（「食べたり飲んだり」），是真的活用形不是噪声。
    "-tari": "たり形（列举）",
    "evidential": "样态形",          # あおそうだ「看起来蓝」
    "noun-from-verb": "体言化",      # 保護すること
    "stem": "词干",
    # ── 2026-09-19 补：修表结构时新建的 tag（源头没有或标错了）──
    "bungo": "文語",                 # 文語（古典语法）那一套，与现代活用分开
    "progressive": "进行体",         # ている：源头整组标成了 `desiderative`
    # 已然形+ば＝順接確定条件（「因为…」），与未然形+ば 的仮定条件不是一回事。
    # 源头把它标成了 `causative`。
    "realis-conditional": "已然形条件形",
    # 括号里的是**限定语**，源头写在格子里：`short form: 食べさす`
    "standard": "（标准）", "colloquial": "（口语）",
    "written": "（书面）", "spoken": "（口头）",
    "short-form": "（短缩）", "contraction": "（缩约）",
    "ra-nuki": "（ら抜き）",         # 食べれる：口语里省掉「ら」的可能形，非规范书面
    # 命令形那一组，源头把四件事打成同一个 `imperative`。不区分的话
    # `食べないでください`（礼貌请求）与 `食べるな`（禁止）会同印「否定命令形」。
    "request": "（请求）",           # 〜てください
    "nasai": "（なさい）",           # 〜なさい：语气缓和的命令
    "prohibitive": "（禁止）",       # 〜な
}

# 源头自己的抽取报错 —— 不是词形属性，整行丢弃并记账
ERROR_TAG = re.compile(r"^error-")
# 这几个在真形态行里是**杂质**（各 ≤9 条），不参与组合
# 🔴 **活用类是「这个词」的属性，不是「这个形」的属性** —— 不进逐形的中文说明。
#    日语版给每个形都打上 `sa-row`（サ行変格）/`godan`（五段）/`irregular`，
#    照译会让每一行都拖着「サ行変格」，是噪声不是信息；它该落 `entry` 的一列
#    （像 de 的 `vclass`），本轮先不落，记在 JA_PLAN 待办。
#    ⚠️ `active`（主动，默认语态）与 `intransitive`（不及物，词的属性）同理。
CLASS_TAGS = {
    "godan", "ichidan", "kamiichidan", "shimoichidan", "nidan", "shimonidan",
    "yodan", "irregular", "active", "intransitive",
    "a-row", "ka-row", "ga-row", "sa-row", "za-row", "ta-row", "da-row",
    "na-row", "ha-row", "ba-row", "ma-row", "ra-row", "wa-row",
}
IGNORE = {"kanji", "alternative", "name", "hiragana", "katakana"} | CLASS_TAGS


def compose(tags):
    """tag 集合 → 中文语法说明。拼不出返回 None（调用方据此丢弃并记账）。"""
    t = {x for x in tags if x not in IGNORE and not ERROR_TAG.match(x)}
    if not t:
        return None
    # `stem` 与六活用形同现时不单独出字：`continuative+stem` 就是连用形
    if "stem" in t and len(t) > 1:
        t.discard("stem")
    # 仮定形**就是**条件形，两个 tag 同现时只出一个（`倍増すれば` 不该印「假定形条件形」）
    if "hypothetical" in t:
        t.discard("conditional")
    parts = [TAG_ZH[x] for x in ORDER if x in t]
    unknown = t - set(TAG_ZH)
    if unknown or not parts:
        return None
    return "".join(parts)


def has_error(tags):
    return any(ERROR_TAG.match(x) for x in tags)


if __name__ == "__main__":
    CASES = [
        (["past"], "过去"),
        (["stem"], "词干"),
        (["continuative", "stem"], "连用形"),
        (["formal", "negative", "past"], "敬体否定过去"),
        (["causative", "passive", "negative", "past"], "使役被动否定过去"),
        (["imperative", "stem"], "命令形"),
        (["error-unrecognized-form"], None),
        (["kanji"], None),
        # ── 2026-09-19：这八条就是「表结构四个缺陷已修」在拼装层的判据 ──
        # 用户在 `食べる` 页上看见的那四行，修好之后应该印成这样：
        (["volitional", "polite"], "敬体意志形"),            # 食べましょう（曾印「敬体命令形」）
        (["causative", "passive", "polite"], "使役被动敬体"),  # 食べさせられます（曾印「敬体条件形」）
        (["progressive", "polite"], "进行体敬体"),            # 食べています（曾印「愿望敬体」）
        (["bungo", "realis-conditional"], "文語已然形条件形"),  # 食ぶれば（曾印「使役」）
        (["polite", "past"], "敬体过去"),                    # 食べました（曾与食べます同印「敬体」）
        (["potential", "ra-nuki", "polite"], "可能敬体（ら抜き）"),
        (["bungo", "stem", "terminative"], "文語终止形"),
        (["progressive", "contraction"], "进行体（缩约）"),
        # 命令形那一组的四件事必须分得开（否则 `食べないでください` 与 `食べるな` 同名）
        (["imperative", "negative", "request"], "否定命令形（请求）"),
        (["imperative", "negative", "prohibitive"], "否定命令形（禁止）"),
        (["imperative", "nasai"], "命令形（なさい）"),
    ]
    ok = True
    for tg, want in CASES:
        got = compose(tg)
        hit = got == want
        ok &= hit
        print("%s %-44s → %-16s（期望 %s）" % ("✅" if hit else "🔴", "+".join(tg),
                                              got or "(丢弃)", want or "(丢弃)"))
    # 🔴 顺序必须真的起作用：把 ORDER 打乱应该得到不同的字串，否则这个列表是摆设
    import random
    saved = ORDER[:]
    random.seed(0)
    random.shuffle(ORDER)
    shuffled = compose(["causative", "passive", "negative", "past"])
    ORDER[:] = saved
    print("\n变异：打乱 ORDER 后同一组 tag → %s（正常是「使役被动否定过去」）" % shuffled)
    ok &= shuffled != "使役被动否定过去"
    raise SystemExit(0 if ok else 1)
