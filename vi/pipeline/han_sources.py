#!/usr/bin/env python3
"""**汉字表记：四个源怎么读、以及汉越字/喃字怎么分** —— 只写一份。2026-09-28。

判据住在这里，建库脚本与闸都 import 它，谁都不许重写
（ko 建外锚闸时**自己重写了收割器的判据**，同一道闸里判据写错两次、方向相反）。

═══ 🔴🔴 W1 有救了：源头自己标了，而我原来打算用的码位判据错 25.66% ═══
计划里 W1 写的是「只能用码位（通用区 vs 扩展区），已知会把借用通用汉字的喃字判错」。
开工前拿源头自己的 `chữ Hán form of` / `chữ Nôm form of` 当真值验了一遍：

    码位判据总体            对 74.34% ／ **错 25.66%**（10,435 对）
      ├ 扩展区 ⇒ 喃字        对 **99.4%**（1,386 对里错 8）   ← 这半条可靠
      └ 通用区 ⇒ 汉越字      对 **70.8%**（9,148 对里 2,671 其实是喃字） ← 这半条不可靠

**污染是单向的，全在「判成汉越字」这一侧** —— 正是 W1 预言的「借用通用汉字表喃音」
（`犬` 读 `chó`、`馬` 读 `mứa`/`mựa`/`mả`）。⇒ `han_spelling` 才是更需要 `rule_ver` 的那张表。
⚠️ 字符级先验救不了：S3 里 86.1% 的字只当一种用，可**两种都当过的 580 个恰好是最常用的**
   （`馬` hán 19 / nôm 4，`西` hán 31 / nôm 3）。

═══ 四个源，以及每个源凭什么定 hán/nôm ═══
    S3 反向·带标注   表意词头的义项自己说 `chữ Hán/Nôm form of X`   **权威**，10,534 对
    S2 zh 词源括号   `cổ tích［古迹 古昔］`                          ⇒ hán，见下面的判别测试
    S4 en 词源散文   `Sino-Vietnamese word from 正 and 案.`         ⇒ hán，源头明说
    S1 en forms     `forms[tags∈{CJK,Hán-Nôm}]`                    **混装**，只能靠码位

⭐ **判别测试**（S2/S4 凭什么算 hán）：拿 S3 的两组标注当对照组，看码位分布 ——

    S3 标 chữ Hán 的   通用区 **99.9%**      ← 对照组 A
    S3 标 chữ Nôm 的   通用区   66.8%        ← 对照组 B
    S2 zh 词源括号     通用区 **99.7%**      ← 与 A 几乎重合
    S1 en forms        通用区   54.6%        ← 与 A、B 都不像 ⇒ 混装，不能整源定性

═══ 🔴🔴 我自己在这两个源上各写错一条判据，交叉验证从 82.38% 升到 94.40% ═══
① **S2：我把括号里的空格抹掉了。** 源头写 `cổ tích［古迹 古昔］` —— **空格分隔的多个候选**，
   `.replace(" ","")` 把它们粘成 `古迹古昔`。于是「zh 是单候选」这个结论也是错的
   （真值：21,136 词形 / 21,741 对，**604 个一形多字**）。
② **S4：`Sino-Vietnamese word from 正 and 案.` 被我截成了 `正`。**
   复合词源用 `and` 连接，正则只抓第一段 ⇒ 1,430 条少抓一半。

   修完之后 S2×S4 在 **4,628 个词形**上交叉验证 ⇒ **94.40% 对得上**
   （修之前 82.38%）。剩下 259 条分歧抽看基本是**异体字**（`豔/艷`、`分布/分佈`、`詞章/辭章`），
   两边都对。⇒ 这回答了欠账 **W4**：上次能比的只有 87 个词形，这次是 4,628 个。

═══ ⭐ 一条贯穿四个源的硬约束：**字数 ＝ 音节数** ═══
越南语一个音节对一个表意字。`sàm ngôn`（2 音节）的表记必须是 2 个字。
这条既是**切分依据**（604 个多候选靠它拆开），也是**过滤器**（挡掉 23 条对不上的）。
⚠️ 它挡掉的那 23 条里有真东西（`cây bí đao→冬瓜` 是意译不是表记），**有意不收**，
   推翻条件：找到一条判据能把「意译」与「表记」分开。
"""
import re
import unicodedata as ud

# 通用区（中文读者日常见到的）：基本区 + 扩展 A + 兼容表意文字。
# 扩展 B 及以上几乎全是喃字。
# 🔴 这里**只写这一个区间常量**，是因为它要表达的就是「码位分块」这件事本身；
#    「这个字符是不是表意文字」仍然交给 `unicodedata` 答（手抄会漏喃字 41.3%）。
_BASIC = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF))


# 🔴🔴 **「判据交给 Unicode 答」这条本身有个版本上限** —— 2026-09-28 撞到的。
#    Python 自带的 `unicodedata` 是 **14.0.0**，而 **CJK 扩展 H（U+31350–U+323AF）
#    是 Unicode 15.0 才加的** ⇒ `ud.name()` 对它们抛 ValueError，
#    我的 `is_ideograph` 于是判它们「不是表意文字」，实测丢掉 **436 行**，
#    而那些**全是喃字**（`may → 𱜿`、`sâu bọ → 蝼𲀇`）。
#
#    ⚠️ 这是 ko 那条教训（「别手抄码位范围，交给 Unicode 答」）的**下一层** ——
#    交给 Unicode 答是对的，但 **Unicode 数据本身是个版本快照**。
#    `ud.category()` 也救不了：它对这些字返回 `Cn`（未分配），
#    **分不出「Python 不认识的表意字」和「真的未分配」**。
#
#    ⇒ 只能补一层码位兜底，而且**明写它是兜底、会过期**：
#      名字认得出 ⇒ 信名字；名字认不出 ⇒ 落在表意文字平面区间里就算。
#    ⚠️ **这张表要随 Unicode 版本更新**，`test_han_layer.py` 有一条闸盯着
#      「库里有没有字符连这张表都兜不住」。
# ═══ 🔴🔴 2026-10-01：这张表与这个函数**搬到 `criteria.py` 去了** ═══
# 原因不是重构洁癖，是它真的漂了并且造成了后果：
# 同一个谓词当时有两份实现（这里有兜底、`criteria.py` 没有），而**收词用的是没兜底那份** ——
#   · `dict` 里躺着 139 个纯表意词形（用户 2026-09-28 定的「不进 dict」被破了）
#   · 本文件的 S3 源（`chữ Hán/Nôm form of X`，唯一带权威标注的那个）
#     调的是 `criteria.is_han_headword` ⇒ 扩展 H 的喃字词头整批被跳过
#   · 骨架闸 S6 明写「表意词头一条都不许在 dict 里」而它报 0（**两边一致报全绿**）
# ⇒ 从 `criteria` import，**物理上不可能再有第二份**。
#   `[[decision-not-propagated-across-editions]]`、`[[refactor-mindset-code-quality]]`。
# ⚠️ `_IDEO_BLOCKS` 仍然导出，因为 `test_han_layer.py` 的 H6 盯着它
#   （「库里有没有字符连这张兜底表都兜不住」）。
from criteria import _IDEO_BLOCKS, is_ideograph                    # noqa: E402,F401


def all_ideographs(s):
    return bool(s) and all(is_ideograph(c) for c in s)


def in_basic_block(s):
    """整串都落在通用区 ⇒ 中文读者大概率认得这些字形。"""
    return all(any(lo <= ord(c) <= hi for lo, hi in _BASIC) for c in s if is_ideograph(c))


# ── rule_ver 的值域：**每条都写明可信度**，翻案时找得到是哪一批 ────────────
RULES = {
    "src-label-v1":   "源头义项自己标了 `chữ Hán/Nôm form of` —— 权威，无需推断",
    "src-zh-etym-v1": "zh 版词源栏的 `词形［漢字］`。凭两条定性为汉越字："
                      "① 码位分布与 S3 的 chữ Hán 对照组几乎重合（99.7% vs 99.9%）"
                      "② 与 S4 在 4,628 个词形上交叉验证 94.40% 一致",
    "src-en-etym-v1": "en 版词源散文明说 `Sino-Vietnamese word from …` —— 源头直接断言",
    "codepoint-v1":   "🔴 **只有码位可依据**（S1 en forms 是混装的）。"
                      "扩展区⇒喃字实测 99.4% 可信；**通用区⇒汉越字只有 70.8%**，"
                      "余下 29.2% 是借用通用汉字表喃音（欠账 W1 的残留）。"
                      "⚠️ 展示层读到这个值时不该印「汉越字」三个字，只印「汉字表记」",
}


# ── S3：反向源，表意词头的义项自己标 ────────────────────────────────────
# 🔴🔴 **`(\S+)` 是错的，而且错得最狠** —— 越南语的词**自带空格**。
#    `chữ Hán form of yên tâm (“to be reassured”)` 会被截成 `yên`，
#    于是「字数＝音节数」那条约束把它判成对不上 ⇒ **丢掉 6,233 条，
#    而且丢的恰好全是多音节词**（多音节占越南语词汇的八成）。
#    与我同一天在 S4 上犯的是**同一个错**（`from 正 and 案` 截成 `正`）——
#    两处都是「正则在第一个空白处停下，而越南语的词跨空白」。
#    ⇒ 抓到**括号或行尾**为止，括号里是英文释义不是词形。
_S3 = re.compile(r"^chữ (Hán|Nôm) form of\s+(.+?)\s*(?:[(（]|$)", re.I)


def s3_label(gloss):
    """→ ("hán"|"nôm", 越南语词) 或 None。"""
    m = _S3.match(gloss.strip())
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip(".,;:\"“” ")


# ── S5：en forms 的**反向**那一半 ───────────────────────────────────────
# 🔴 S1 被「字数≠音节数」挡掉的 10,244 行里，**9,794 行是反向的**：
#    词头本身是表意文字，`form` 是它的国语字读音（`車` → `xa`/`xe`/`xế`）。
#    那不是噪声，是**第五个源**，形状与 S3 相同（表意字 → 越南语词）。
#    ⚠️ 我差点把它当成「判据挡掉的垃圾」整批扔掉 ——
#      `[[residual-bucket-is-not-evidence]]` 今天第三次：**被挡掉的那堆要看一眼**。
def s5_candidate(headword, form, syl_of):
    """词头是表意文字时，`form` 是国语字读音 → (越南语词, 汉字) 或 None。"""
    t = form.strip()
    if not t or any(is_ideograph(c) for c in t):
        return None                      # 反向源的 form 必须是国语字
    if syl_of(t) != len(headword):
        return None                      # 同一条硬约束：一个音节一个字
    return t, headword


# ── S2：zh 版词源栏的括号表 ─────────────────────────────────────────────
# 判据收窄了三层：① 整段必须是 `<词形>［…］` ② 头部必须等于词形
#                ③ 每个候选必须全是表意文字**且字数 ＝ 音节数**
_S2 = re.compile(r"^\s*(.+?)\s*[［\[]([^］\]]+)[］\]]\s*[。.]?\s*$")


def s2_candidates(word, text, syl):
    """→ [汉字串…]。🔴 **按空白切** —— 源头用空格分隔多个候选，粘起来就是造假。"""
    m = _S2.match(text.strip())
    if not m or m.group(1) != word:
        return []
    return [c for c in m.group(2).split() if all_ideographs(c) and len(c) == syl]


# ── S4：en 版词源散文 ───────────────────────────────────────────────────
_S4 = re.compile(r"Sino-Vietnamese (?:word|reading) (?:from|of)\s+(.+?)(?:\.\s|\.$|$)")
_RUN = re.compile(r"[^\W\d_]+", re.UNICODE)


def s4_candidates(text, syl):
    """→ [汉字串…]。

    🔴 两种写法都要接住，只抓第一段会少抓 1,430 条：
        `Sino-Vietnamese word from 學生.`          ← 一整串
        `Sino-Vietnamese word from 正 and 案.`     ← **用 and 连的复合词源**
    """
    m = _S4.search(text)
    if not m:
        return []
    clause = m.group(1)
    out = [r for r in _RUN.findall(clause) if all_ideographs(r) and len(r) == syl]
    if not out:
        chars = [c for c in clause if is_ideograph(c)]
        if syl > 1 and len(chars) == syl:
            out = ["".join(chars)]
    return out


# ── S1：en 版 forms ─────────────────────────────────────────────────────
S1_TAGS = {"CJK", "Hán-Nôm"}


def s1_candidate(form, syl):
    """→ 汉字串 或 None。⚠️ S1 是**混装**的（通用区 54.6%），定性只能靠码位。"""
    g = "".join(c for c in form if is_ideograph(c))
    return g if g and len(g) == syl else None


# ── 定性：这一对是汉越字还是喃字 ────────────────────────────────────────
def classify(han, label=None, src_kind=None):
    """→ ("han"|"nom", rule_ver)。

    优先级**就是可信度排序**，不是随手排的：
      ① 源头自己标了            权威
      ② 源头语义天然只装汉越字   S2/S4，两条独立证据支持
      ③ 只剩码位                扩展区可信 99.4%，通用区只有 70.8%
    """
    if label in ("hán", "nôm"):
        return ("han" if label == "hán" else "nom"), "src-label-v1"
    if src_kind == "zh-etym":
        return "han", "src-zh-etym-v1"
    if src_kind == "en-etym":
        return "han", "src-en-etym-v1"
    return ("han" if in_basic_block(han) else "nom"), "codepoint-v1"
