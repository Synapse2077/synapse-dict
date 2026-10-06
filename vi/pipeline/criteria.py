#!/usr/bin/env python3
"""vi 的收词与归一判据 —— **只写一份，住在这里**。2026-09-28。

🔴 ko 建外锚闸时发现同一条判据在三个文件里各有一份（当时三份一样，但三份一定会漂，
   而闸正要靠它）。⇒ 收词器、闸、探针**都 import 这一份**，谁都不许重写
   （`[[refactor-mindset-code-quality]]`、`[[criteria-narrower-than-you-think]]`）。

═══ 🔴🔴 ko 的两条收词规则在 vi 上**都不能照搬，而且方向相反** ═══

① `NOT_A_WORD = {"romanization"}` —— **照搬会丢掉真词**
   ko 上 `pos=romanization` 只有 8 条，是罗马字拼写的韩语词，剔掉是对的。
   vi 上这个 pos 装的是**汉越音**：`y → Sino-Vietnamese reading of 衣`。
   实测 773 条 / 565 个词形，其中 **145 个词形只以这个 pos 出现** ——
   照搬 ko 就是删掉 145 个真实越南语音节。
   ⇒ **vi 的 `NOT_A_WORD` 是空集**，见下面的显式声明。

② 「单个汉字不收」不能写成 `pos == "character"` —— **两个方向都会错**
   用户 2026-09-28 定：汉字/喃字本身不进 `dict`，只喂汉字层。
   但 `pos` 切不出这批东西。实测三桶：

       A  pos=character 且全表意   8,704 条  有 IPA  0.0%  ← 要剔
       B  pos≠character 但全表意   6,619 条  有 IPA  0.0%  ← **只按 pos 剔会漏掉整批**
                                   pos 是 noun 3,561 / verb 1,101 / adj 924 / name 791
       C  pos=character 但不全表意   325 条  有 IPA 39.7%  ← **只按 pos 剔会误伤这批**
                                   它们是**越南语字母**：`A` `y` `X` `CH` `đ`

   ⇒ 判据必须落在**词形的字形**上，不是落在 pos 上。这正是用户那句话的字面意思：
     「它们是汉字/喃字本身，不是国语字词形」。

   ⭐ **两把独立的尺子在这里收敛**（`[[verification-gates-not-sampling]]` 的正面用法）：
     字形判据圈出的 B 桶，它的义项 **96.31%** 是 `chữ Hán/Nôm form of …` 指针。
     两条互不相干的路指向同一批 ⇒ 判据站得住。
     ⚠️ 残差 3.69%（260 条 gloss）是全表意词形却带真释义的，**已知会被一起剔**，
        它们走阶段 2 的汉字层，不是丢掉（`[[dont-say-source-lacks-what-we-skipped]]`）。
"""
import re
import unicodedata as ud

# ── ① pos 黑名单：**显式声明为空** ────────────────────────────────────
# 🔴 空集也要写出来并写明理由。`[[record-the-negative-decision]]`：
#    否定结论光落账不够，必须写「什么会推翻它」。
#    **什么会推翻**：源头出现一个 pos，它的词形整批不是越南语词（如 ko 的罗马字串）。
#    查法：`probe_primary_source.py` §A 的 pos 值域普查。
NOT_A_WORD: set[str] = set()


# ── ② 字形判据：表意文字交给 Unicode 答，别手抄码位 ──────────────────
# 🔴 实测手抄基本区漏 41.3%，漏掉的**全是喃字（扩展 B）**——
#    手抄范围不是漏边角，是把越南语自己的书写系统整个删掉。
#
# ═══ 🔴🔴 但「交给 Unicode 答」**也有版本上限**，而这个坑在本文件里栽了第二次 ═══
# Python 的 `unicodedata` 是 14.0.0，不认识 **CJK 扩展 H**（Unicode 15.0，2022）
# 与扩展 I（15.1）。`ud.name()` 对那些码位抛 `ValueError`，而
# `ud.category()` 返回 `Cn`（未分配）—— **它分不出「真未分配」和「我的库太旧」**。
#
# 2026-09-28 阶段 2 为此在 `han_sources.py` 里加了码位兜底、并做成闸 H6 盯着它。
# 🔴🔴 **而本文件这一份当时没改** —— 同一个谓词两份实现，修了一份。
#    `[[decision-not-propagated-across-editions]]`：一门做对了其余照旧错着。
#    2026-10-01 关系层闸 R19 把后果逮出来，逐条查下来是三件事叠在一起：
#
#      ① `dict` 里躺着 **139 个纯表意词形**（用户 2026-09-28 定的「不进 dict」被破了）
#      ② 汉字层的 S3 源（`chữ Hán/Nôm form of X`，**唯一带权威标注的那个源**）
#         用的就是本函数 ⇒ 扩展 H 的喃字词头**整批被跳过**，
#         其中 52 个连「该喂进汉字层」这一半也没做成
#      ③ 骨架闸 **S6 明写「表意文字词头一条都不许在 dict 里」而它报 0** ——
#         断言和被断言的东西用的是同一个坏判据 ⇒ **双方一致报全绿**。
#         与 ko 那天「词性表按 `pos_raw` 写而展示层读 `pos`，两边一致报全绿」同形。
#
# ⇒ 兜底搬进这里（**判据的唯一的家**），`han_sources` 改为 import 本函数，
#   物理上不可能再漂。码位表来自 Unicode 的 CJK 区块定义（外部事实，只增不改）。
_IDEO_BLOCKS = (
    (0x3400, 0x4DBF),      # 扩展 A
    (0x4E00, 0x9FFF),      # 通用区
    (0xF900, 0xFAFF),      # 兼容表意文字
    (0x20000, 0x2A6DF),    # 扩展 B  ← 喃字主场
    (0x2A700, 0x2EBEF),    # 扩展 C/D/E/F
    (0x2F800, 0x2FA1F),    # 兼容表意文字补充
    (0x2EBF0, 0x2EE5F),    # 扩展 I（Unicode 15.1）
    (0x30000, 0x323AF),    # 扩展 G/H（Unicode 13.0 / 15.0）
)


def is_ideograph(ch: str) -> bool:
    try:
        return ud.name(ch).startswith(("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH"))
    except ValueError:                       # 未命名码位：**可能只是我的 Unicode 库太旧**
        o = ord(ch)
        return any(lo <= o <= hi for lo, hi in _IDEO_BLOCKS)


# 整串汉字的词形里会夹着**汉字文化圈的标点与部件符号**，它们不是表意文字但也不是国语字：
#   `四肢發達，頭腦簡單／四肢发达，头脑简单`   ← 全角逗号与斜杠（成语的繁简两写）
#   `⿻古八`                                ← U+2FFB 表意文字描述符（IDS，描述字形构造）
# 🔴 第一版只放过空白 ⇒ 这类整串汉字的词形**溜进了 dict**，关系层闸 R19 当场逮到 23 条。
# ⚠️ 收窄得很紧：只放过**汉字文化圈专用**的那几个码位，
#    不放过 ASCII 标点 —— 否则 `a, b` 这种国语字串也会被判成汉字词头。
_CJK_PUNCT = "，。、；：！？（）《》〈〉「」『』【】〔〕—…·／＼～＃＊＋－＝"


def _ids_char(ch: str) -> bool:
    """表意文字描述符 U+2FF0–U+2FFF（⿰⿱⿲…）与笔画 U+31C0–U+31EF。"""
    o = ord(ch)
    return 0x2FF0 <= o <= 0x2FFF or 0x31C0 <= o <= 0x31EF


def is_han_headword(word: str) -> bool:
    """词形**整串**是表意文字（容许汉字圈标点/部件符号）⇒ 它是汉字/喃字本身。

    实测命中 14,523 个词形（A∪B）。用户 2026-09-28 定：**不进 `dict`，只喂汉字层**。
    ⚠️ 这是「我们这一步不收」，**不是**「源头没有」。
    """
    t = word.strip()
    if not t:
        return False
    if not any(is_ideograph(c) for c in t):
        return False                         # 一个表意文字都没有 ⇒ 不是汉字词头
    return all(is_ideograph(c) or c.isspace() or c in _CJK_PUNCT or _ids_char(c) for c in t)


# ── ③ 指针义项：结构字段兜不住，必须加正文判据（欠账 W5）──────────────
# 🔴 vi 版把指针写成 gloss 正文（`Xem X` 看 X／`Như X` 如同 X）2,854 条，
#    en 版写成 `Alternative form of X` 2,573 条，两版的 `form_of` **都装不下它们**。
#    只用结构字段判，vi 独有词形的「有真释义」会报 99.2% 而真值 92.1%。
#    与 ko「韩文版指针的 `form_of` 是 None、目标藏在空 tag 的 form 里」**同形**。
_PTR_EN = re.compile(
    r"^(alternative (form|spelling)|obsolete form|archaic form|nonstandard form|"
    r"misspelling of|romanization of|chữ (hán|nôm) form of|hán tự form of|"
    r"sino-vietnamese reading of)\b", re.I)
_PTR_VI = re.compile(r"^(Xem|Như|Xt\.?|Cv\.?|Nh\.?)\s+\S", re.I)


def is_pointer_sense(sense: dict) -> bool:
    """这条义项是不是「去看别的词」而不是释义。

    三路判据取并：结构字段 ／ 英文版正文写法 ／ 越南文版正文写法。
    """
    if sense.get("form_of") or sense.get("alt_of"):
        return True
    for g in sense.get("glosses") or []:
        t = g.strip()
        if t and (_PTR_EN.match(t) or _PTR_VI.match(t)):
            return True
    return False


# ── ④ 归一：NFC + 小写，**不去声调** ─────────────────────────────────
# 🔴 拉丁六门（es/pt/fr/it/de/nl）去重音是对的 —— 那些语言的重音不区别词义。
#    越南语的声调**区别词义**：`má` 妈 / `mà` 而 / `mả` 坟 / `mã` 码 / `mạ` 秧苗
#    是五个不同的词，去掉声调就合成一个。
# ⚠️ 与之配套：`dict.word_norm` **有意不带 `COLLATE NOCASE`** ——
#    SQLite 的 NOCASE 只折 ASCII，对越南语部分生效（`'Việt'=‘việt'` 成立而
#    `'VIỆT'=‘việt'` 不成立），而**部分生效最难发现**。归一只在这里做一次。
def norm_vi(word: str) -> str:
    return ud.normalize("NFC", word).strip().lower()


# ── ⑤ 音节数：空格与连字符都算分隔 ───────────────────────────────────
# 越南语正字法按音节分写，`sinh viên` 是 2 个音节。外来词用连字符：`An-ba-ni` 是 4 个。
# ⚠️ 只按空格数会把连字符词**整个算成 1 个音节**。
_SYL_SEP = re.compile(r"[\s­\-–—]+")


def syllables(word: str) -> int:
    parts = [p for p in _SYL_SEP.split(word.strip()) if p]
    return len(parts) or 1


# ── ⑥ entry_type：**只用源头 pos 直接映射，一律不猜** ──────────────────
# V1 说 `word` 只是页面标题，81.3% 含空格里混着短语/成语/自由搭配。
# 🔴 但「哪些含空格的是短语而不是复合词」源头没说，**这一步不判** ——
#    现在能确定的只有源头 pos 自己说清楚的那几类。其余一律 `word`，
#    留给后面有证据时再细分（`[[dont-gate-facts-on-my-uncertainty]]`：
#    这一列要写的是源头给的，不是我推出来的）。
_POS_TO_TYPE = {
    "phrase": "phrase",
    "proverb": "proverb",
    "affix": "bound_morpheme",
    "prefix": "bound_morpheme",
    "suffix": "bound_morpheme",
    "combining_form": "bound_morpheme",
}


# ── ⑦ 阶段 4 收词：哪些 gloss **根本不是释义** ────────────────────────────
# 🔴 中文版的 `pos=unknown` 条目里混着两类东西，抽样读过：
#     `bặng → 汉字：𠶉`         ← **音节→汉字对照表**，不是释义（而且里面有私用区字符）
#     `met  → :Template:越參/met` ← **模板残渣**
#   收进 `dict` ＝ 读者搜到 `bặng`、点进去看见「汉字：𠶉」当作释义。
#   ko 的 K10 正是这么被用户在页面上看见的。
#
# ⚠️ **这两条判据窄得刻意**：只认 `汉字：`/`漢字：` 开头与模板前缀，
#    绝**不**顺手去判「这条中文 gloss 是不是元描述」—— 那是欠账 **W2**，
#    我已经量过三次得到三个数，不许在这儿再写第四版
#    （`[[criteria-narrower-than-you-think]]`）。
# ⭐ 抽样验过：`全是汉字列表` 1,789 个词形抽 8 条全部确认；模板残渣 3 条全部确认。
_HAN_LIST = re.compile(r"^(汉字|漢字)\s*[:：]")
_TEMPLATE = re.compile(r"^\s*:?Template:|^\s*\{\{|^\s*模板\s*:")


def is_not_a_gloss(text: str) -> bool:
    """这条 gloss 是不是**压根不是释义**（汉字对照表 / 模板残渣）。"""
    t = (text or "").strip()
    return bool(t) and bool(_HAN_LIST.match(t) or _TEMPLATE.match(t))


# ── ⑧ 欠账 W2：中文 gloss 里有多少**只是汉字表记** ────────────────────────
# 🔴🔴 这条判据量过三次得到三个数（0.8% ／ 抽样当场打回 ／ D 桶 72.4% 上界）。
#    第四次之所以能收敛，不是因为判据更聪明，而是因为**对照表变全了**：
#
#        W2 第③版当时手上的汉字表记表   4,810 个词形（只有 en 的 forms）
#        现在                        33,104 个词形（五源并集，阶段 2 建的）
#
#    拿同一条「整条 gloss ＝ 该词的汉字表记」判据跑两遍：
#        旧表 ⇒ 命中 **0.4%**   （与 W2 记的 B 桶 0.3% 对上了）
#        新表 ⇒ 命中 **69.2%**
#    ⇒ 72.4% 那个「真释义上界」虚高，是因为**比不上的就被当成了真释义**。
#      `[[residual-bucket-is-not-evidence]]`：残差桶少一条消去器就虚胖。
#
# ⚠️ 判据是**读者口径**的，不是「这串汉字是不是真的中文词」：
#    页面上方已经印着 `汉字表记 社會`，中文释义栏再印一次 `社會` —— 对读者是零信息。
#    与 ko 那条「日本新字体译过来＝把早印着的再说一遍」（3,344 条有意不收）同形。
_PUNCT = re.compile(r"[（(].*?[）)]|[，,、；;。\s]")


def gloss_is_just_spelling(gloss: str, spellings) -> bool:
    """这条中文 gloss 是不是**就是该词的汉字表记**（去括号标点后也算）。"""
    t = (gloss or "").strip()
    if not t or not spellings:
        return False
    return t in spellings or _PUNCT.sub("", t).strip() in spellings


# ── ⑨ 释义里有没有「内容」—— 2026-10-02 花 5b 的钱之前逮到的 ────────────────
# 🔴🔴 出版层里有 **151 条释义整串是标点**（141 条 vi 的 `.` ＋ 10 条 zh 的）。
#    义项层闸 **E4** 查的是 `TRIM(text)=''`，而 `.` 不是空串 ⇒ 它穿过去了。
#    与例句层那 214 个 `.`、词源层那 122 个 `.` 是**同一种源头残渣**，
#    在三个层上各自出现一次，而我在前两层都只在本层处理了（判据没进 `criteria`）。
# ⚠️ **收窄得很紧：只判「有没有字母/数字/汉字」，不判长短。** 实测短释义全是真的：
#      `năm → 五`（1 个汉字）／`bần đạo → I`（1 个字母）／`bo → 硼`
#    494 条 zh 短释义 ＋ 9 条 en/vi 短释义**一条都不许动** ——
#    我差点按「短于 2 字符」去清，那会删掉五百条正确释义
#    （`[[criteria-narrower-than-you-think]]`：先读样本再定判据）。
# 🔴 字符类交给 Unicode 的范围写，**别手抄越南语字母表** ——
#    `ă đ ơ ư` 与所有带调元音都在扩展区（ko 那边手抄字符类差点删掉 5 条化学元素汉字名）。
_GLOSS_CONTENT = re.compile(r"[0-9A-Za-z\u00c0-\u1ef9\u3400-\u9fff\uf900-\ufaff]|[\U00020000-\U0003ffff]")


def gloss_has_content(text: str) -> bool:
    """这条释义里有没有一个字母/数字/表意文字。没有 ⇒ 整串是标点，对读者是零信息。"""
    return bool(_GLOSS_CONTENT.search(text or ""))


# ── ⑩ 越南语版的**词典标记缩写**被当成了释义 —— 5b 的控制组逮到的 ──────────
# 🔴 5b 跑完，形状检查报「译文里没有一个汉字」vi 侧 52 条。逐条读下来分两种：
#      `ngót → Ph.` / `kíp → Trgt.` / `tơ → I. D.`   ← **源头的词典标记缩写**，零信息
#      `thuộc → Thục.` / `oắt con → oắt.`            ← **裸交叉引用**（"见 X" 的简写）
#    模型把它们原样回显是对的 —— **没东西可译**。但它们本来就不该在出版层。
#
# ⚠️ **三条形式判据都试过，三条都太宽**，这是为什么最后用枚举：
#      「单 token 短释义」        15,183 行 —— `father`/`mother`/`Chết` 全是真释义
#      「没有 ≥3 字母的词」          259 行 —— `Ở`(在)/`Bé.`(小)/`I/me`/`to be` 全是真的
#      「句点缩写且不在词库里」       30 行 —— 90% 准，但会误伤 `Wien.`/`Cuba.`/`Tokyo.`
#    ⇒ **枚举**这批标记（下面这张表），每一个值我都读过它出现的那几行。
#      `[[criteria-narrower-than-you-think]]`：收窄到枚举不是偷懒，
#      是因为**这批东西的本质是源头的一套标记词汇表**，而词汇表就该枚举。
#
# 🔴 **什么会推翻 / 怎么发现漏的**：`test_sense_layer.py` 的 E13 是**只报数**的检查 ——
#    它用那条 90% 的形式判据扫，把不在本表里的命中**打出来**。
#    新缩写出现时它会报，人去读一眼再决定进不进本表。
#    （与词源闸 Y17「看守上界不是删除判据」同一个形状。）
_VI_MARKUP_GLOSS = {
    "trgt",      # Trạng từ   副词
    "đphg",      # Địa phương 方言/地方
    "trt",       # Trợ từ     助词
    "tht",       # Thán từ    叹词
    "gt",        # Giới từ    介词
    "dt",        # Danh từ    名词
    "ph",        # Phương ngữ 方言
    "khng",      # Không rõ?  —— 11 行里读过 2 行，确认是标记不是词
    "ng", "mt", "l", "t", "p", "d", "x",   # 单字母/双字母标记（含 X.＝Xem「见」）
    "i. d", "i.d",
}


def is_vi_markup_gloss(text: str) -> bool:
    """这条释义是不是**源头的词典标记缩写**（`Trgt.` `Ph.` `X.`），不是释义。

    判据：整条由句点缩写组成，且**每一段**都在上面那张枚举表里。
    ⚠️ 要求「每一段都在表里」而不是「有一段在」—— `Khng. đphg.` 两段都在，收；
       而 `Wien.` 不在表里，一行都不动。
    """
    t = (text or "").strip()
    if not t or len(t) > 24:
        return False
    parts = [x.strip().rstrip(".").strip().lower() for x in t.split(".") if x.strip()]
    return bool(parts) and all(p in _VI_MARKUP_GLOSS for p in parts)


# ══════════════════════════════════════════════════════════════════════════
# ⑨ **指针区该印什么** —— 阶段 9（W15）的判据，2026-10-03。
#
# ═══ 🔴🔴 这条判据存在的理由：读者看到的「这个词形指向」79.6% 是错标的 ═══
# 展示层在「这个词形没有任何可出版义项」时印 `sense_src` 里 `sense_id IS NULL` 的行，
# 标题写着「这个词形指向」。实测那 17,418 行逐条分类：
#     ② **13,728（78.8%）整段只是这个词自己的汉字表记**（`nhất vị` → `一味`）
#        —— 而同一个页面**上方已经有「汉字表记」区**印着同一串字
#     ① 2,646（15.2%）真指针（`alternative spelling of ghi-ta`）
#     ④   912（ 5.2%）也是真指针，只是写法 `_PTR_EN` 没列（`short for` / `abbreviation of`）
#     ③   132（ 0.8%）中文版的表记行（`汉字：檜 𨆝` / `征的漢越詞讀音`）
#
# 🔴 **这是 W2 的病在第三个地方复发**：W2 ＝ 义项释义（69.2% 只是表记）、
#    Y5 ＝ 词源正文（26,230 段里 21,239 段只是表记）、现在 ＝ 指针区（78.8%）。
#    ⭐ 三次都是同一句话：**「这个词的汉字写法」被当成了「这个词的意思/来源/指向」**。
#    判据 `gloss_is_just_spelling()` 阶段 5a 就写好了，**只是展示层没用它**。
#
# ⚠️ 为什么不去放宽 `is_pointer_sense`：那个函数决定**收割时**哪条义项是指针，
#    改它会改动已落库的分类口径（阶段 5a 的 33,361 行）。本函数只回答
#    **「这一行该印在指针区还是不该」**，是展示层的问题，不是收割的问题。
PTR_POINTER = "pointer"      # 真指针 ⇒ 印在「这个词形指向」
PTR_SPELLING = "spelling"    # 只是这个词的汉字表记 ⇒ 不印（上方「汉字表记」区已有）
PTR_OTHER = "other"          # 其余（真释义之类）⇒ 印，但不带「指向」语义


def pointer_class(text: str, spellings) -> str:
    """这一条 `sense_id IS NULL` 的证据，展示层该怎么对待。→ PTR_* 之一

    ⚠️ 顺序是判据的一部分：**先问「是不是指针写法」** ——
       `chữ Hán form of 國` 整段也含表意文字，但它**是**指针（它在说「去看那个字」），
       而 `一味` 只是表记。两者的区别在**有没有那句指路的话**，不在字形上。
       反过来排序会把 2,646 条真指针判成表记。
    """
    t = (text or "").strip()
    if not t:
        return PTR_OTHER
    if (_PTR_EN.match(t) or _PTR_VI.match(t) or _PTR_MORE.match(t)
            or _PTR_VI_LONG.match(t)):
        return PTR_POINTER
    # 🔴 中文版的「目标在前、关系词在后」那一支 —— 见 `_PTR_ZH` 上方那段
    if _PTR_ZH.search(t):
        return PTR_POINTER
    # `汉字：X Y Z` 是表记清单（`_HAN_LIST` 是 `is_not_a_gloss` 用的那条，不另写）
    if _HAN_LIST.match(t) or gloss_is_just_spelling(t, spellings) or is_han_headword(t):
        return PTR_SPELLING
    return PTR_OTHER


# `_PTR_EN` 之外的指针写法。**单列一份而不是改 `_PTR_EN`** ——
# 后者是收割判据，动它会改已落库的分类（见上）。
#
# ⚠️ **判据按结构写不按前缀枚举。** 我第一版枚举前缀（`short for|abbreviation of|…`
#    ＋ `[A-ZÀ-Ỹ][\w\s]{2,30} form of`），剩下 584 条**全还是指针**，只是写法超出枚举：
#        `alternative letter-case form of châu Á`      小写开头，`[A-ZÀ-Ỹ]` 不匹配
#        `eye dialect spelling of yêu`                 是 `spelling of` 不是 `form of`
#        `Central Vietnam and Southern Vietnam form of rốn`  41 字符，超过 `{2,30}`
#    ⇒ 这一族的共同**结构**是「以『…（某种）form/spelling/… of X』开头」——
#      一句指路的话，而不是某几个固定前缀。`[[criteria-from-meaning-not-form]]`。
# 🔴 什么会推翻：`pointer_class` 判成 `other` 的那批里出现**真释义**
#    （现在应接近 0；它一旦涨起来说明这条结构判据开始咬到释义了）。
_PTR_MORE = re.compile(
    r"^(?:short for|clipping of|synonym of|alternative name (?:of|for)"
    r"|(?:abbreviation|initialism|acronym|ellipsis)s? of"
    r"|[\w\s\-,()]{0,60}?\b(?:form|spelling|variant|name|reading|romanization|"
    r"transliteration|pronunciation|reduplication|misconstruction|misspelling|"
    r"diminutive|augmentative)s? of)\b",
    re.I)

# 🔴🔴 **越南文版用整句指路，而 `_PTR_VI` 只覆盖了词典式缩写。**
#    `_PTR_VI` 是 `^(Xem|Như|Xt\.?|Cv\.?|Nh\.?)` —— 那是 vi 版词典的简写体例。
#    而同一个版本也写完整的句子，实测这一批在 `other` 里剩了几百条：
#        `Dạng lỗi thời của hành chính`            过时形式
#        `Dạng viết tắt của sách đã dẫn`           缩写形式
#        `Từ viết tắt từ chữ đầu … của Công Nguyên` 首字母缩写
#        `Đồng nghĩa của nhà (thường dùng …)`      同义词
#        `Từ sai chính tả của xoi mói`             错别字
#        `Dạng thay thế của đéo`                   替代形式
#    ⇒ 结构是「**<关系词> … của X**」。
# ⚠️ **必须要求以关系词开头，不许只看 `của`** —— `của`（的/之）在真释义里到处都是
#    （`người đứng đầu của một tổ chức` ＝「一个组织的首领」），只看它会把释义全判成指针。
_PTR_VI_LONG = re.compile(
    r"^(?:\([^)]*\)\s*)?"                       # 可能带「(chủ yếu là Nam Việt Nam)」这种语域前缀
    r"(?:Dạng|Dang|Từ|Tu|Cách|Lối|Viết tắt|Nói tắt|Đồng nghĩa|Trái nghĩa|Biến thể|"
    r"Số nhiều|Số ít|Âm đọc|Âm|Láy|viết theo)\b"
    r"[^.!?]{0,60}?\bcủa\b", re.I)
# 🔴🔴🔴 **第五轮：中文版的语序是反的，我前四轮一直在往「关系词在前」上加词。**
#    英文 / 越南文：`alternative spelling of ghi-ta` ／ `Dạng viết tắt của sách đã dẫn`
#                   —— **关系词在前、目标在后**
#    中文版：        `Mĩ的另一種拼寫法` ／ `ti vi 之首字母縮略詞` ／
#                   `lập xuân (“立春”)的大小寫替代形式`
#                   —— **目标在前、关系词在后**
#    ⇒ 前四轮每一轮都在同一个方向上加词，而剩下的那批**结构上进不来**。
#    ⭐ 这是「判据比它要描述的东西窄」的一种特殊形状：**不是词表不全，是语序假设错了**。
#      加词永远到不了 —— 必须单开一支。
_PTR_ZH = re.compile(
    r"[的之]\s*[^，。；]{0,12}?"
    r"(?:拼寫法|拼写法|寫法|写法|縮寫|缩写|簡寫|简写|縮略詞|缩略词|縮拼詞|缩拼词|"
    r"替代形式|截斷形式|截断形式|形式|同義詞|同义词|喃字|大写形|大寫形|拼寫|拼写)")
# ⚠️ 中文版还有一族是**汉字表记清单**（`汉字：𩧍 \U000f02ee 𨆷`，约 30 条）——
#    `_HAN_LIST` 这条判据 `is_not_a_gloss` 早就在用，**不另写一份**。

# ⚠️ **到此为止：17,418 条里 `other` 只剩 6 条（0.03%），逐条点名如下。**
#    **反向控制五轮一直是 0**（没有一条「只是表记」被指针判据抢走）——
#    精度比召回重要：把表记错标成「指向」是读者看得见的错，
#    把一条指针漏标成 `other` 只是少一个链接（它仍然照原文印出来，一个字不丢）。
#      `(từ cũ) (miền Nam) Dạng viết khác của chính quốc.` ×2
#          —— `_PTR_VI_LONG` 只放过**一个**括号前缀，这条有两个
#      `bệnh的South Central Vietnam and 南部寫法` ×2
#          —— 中文语序，但 `的` 与关系词之间夹了 30 多个字符（超过 `{0,12}`）
#      `vô duyên的視覺方言拼法`
#          —— `拼法` 不在名词表里（表里有 `拼寫`/`拼寫法`）
#      🔴 `:Template:vi-rdp of`
#          —— **这条不是指针也不是表记，是 wikitext 模板残渣**，记在 W18 那一族
#    🔴 什么会推翻：这个数涨起来（说明源头出现了新的指路语序或新的关系词）。
# ⚠️ **到此为止，不再往下扩。** 第三轮之后 `other` 还剩约 90 条，逐条读是真混着的
#    （有真释义、有源头的用法说明），而每多一个关系名词就多一分咬到释义的风险。
#    `[[ship-dont-measure-in-circles]]`：残差当上界报，不追到 0。
#    ⭐ **反向控制一直是 0**（没有一条「只是表记」的行被这条判据抢走）—— 精度比召回重要：
#      把表记错标成「指向」是读者看得见的错，把一条指针漏标成 `other` 只是少一个链接。


def entry_type_of(word: str, pos_list) -> str:
    """值域：letter / phrase / proverb / bound_morpheme / word。

    ⚠️ `han_form` **不在这里出现** —— 全表意词形根本不进 `dict`（§4.5），
       它们在阶段 2 从 dump 直读。枚举值留着而没人写＝ B7 那种死条目。
    """
    poss = set(pos_list)
    # 越南语字母：源头 pos=character 但词形不是表意文字（实测 324 个词形：A y X CH đ）
    # 🔴 必须是**唯一**词性才算字母。实测 324 个里 **50 个（15.4%）同时是真词** ——
    #    `a` 的词性是 character/intj/noun/particle/pron/verb，把它标成「字母」是错的。
    #    判据写成「含 character」比它要描述的东西更宽（`[[criteria-narrower-than-you-think]]`）。
    if poss == {"character"} and not is_han_headword(word):
        return "letter"
    for p, t in _POS_TO_TYPE.items():
        if p in poss:
            return t
    return "word"


# ══════════════════════════════════════════════════════════════════════════
# §⑩ 同一个义项被两版各描述了一遍（W25）—— 2026-10-05
#
# ⭐ 这笔账是做 W24（例句重复）时量出来的，而**它比 W24 大**：
#    W24 第一版那 1,569 组里有 1,374 组挂的是**不同**义项，读那些义项一眼看出
#    根因不在例句层：
#        qua  义项「幸存」[en 版]          ／ 义项「脱离死亡」[vi 版]
#        be   义项「撑开袋口以便装满」[en]  ／ 义项「用手抬高斗口以量得更多」[vi]
#
# ═══ 🔴🔴 四次收窄，每一次都是「我的判据比它要描述的东西宽」═══
# ① 「同一词形下中文释义逐字相同」           1,817 组 / 2,257 条
# ② 🔴 **扣掉跨 entry 的 484 组** —— 其中 327 组不同词性、157 组不同词源号。
#    **同一个中文词出现在两个词性下是正当的**（`qua` 当动词和当介词都译作「经过」），
#    读者在两个词性标题下各看一次，不是重复。⇒ 判据必须钉在**同一个 entry 内**。
# ③ 🔴 **再扣掉 72 组「两条都有英文而内容不同」** —— 逐组读完 30 条，里面**混着真差异**：
#        hớt tóc   to give a haircut ／ to get a haircut   ← 理发师 vs 顾客，两个角色
#        công quốc principality ／ duchy                   ← 公国 vs 公爵领，不是一回事
#        trước     before ／ ago                           ← 不同的语法用法
#    ⭐ 这一类的缺陷**不是「义项重复」而是「中文比英文粗」** —— 折叠会真丢信息，
#      正确的修法是让中文分得开（付费重译），完全是另一件事。⇒ 记 W26，这里不碰。
#    ⚠️ 剩下的 42 组确实是英文同义改写（`airfield`/`airport`、`Scorpio`/`Scorpius`），
#      **但我分不开这 42 和那 30** ⇒ 72 组整体不折。`[[criteria-narrower-than-you-think]]`：
#      分不开的时候，**宁可少折不要误折**（错标是读者看得见的错，漏折只是多一行）。
# ④ 剩 **1,236 组 / 1,621 条多余义项**，三堆：
#        只有一条有英文（另一条是别版给的同一义项）  1,002 组
#        英文完全相同（含都为空）                      231 组
#        多条英文但内容相同                              3 组
#
# ═══ 留哪一条：三条优先级，每条都量过它实际决定多少组 ═══
#    ① 有英文释义的优先      1,005 组由它决定
#    ② 有越南语释义的优先       13 组
#    ③ `sense.id` 小的        218 组（＝页面上排在前面那条：展示层
#       `ORDER BY etym_no, s.rank, s.id` 而 **`rank` 102,673 条全是 0** ⇒ 实际按 id）
#       📋 `rank` 全 0 本身是一笔账（排序退化成 id 序），记 W27。
#
# 🔴🔴 **622 组是互补的** —— 一条只有英文、另一条只有越南语。
#    光隐藏会让读者丢一条释义 ⇒ **必须把释义并到留下来那条**
#    （`sense_gloss` 有 `UNIQUE(sense_id, lang, text)`，并过去天然幂等）。
#    这是 W24 那条「并，不是丢」在义项层的重演，而这次的量级是 622 比 1。
#
# ⭐ 折叠是**完全可逆的**：被折的义项 `hidden=1` 而**释义一条不删**
#    （实测现有 186 条隐藏义项 186 条都带释义 —— W12 定的「隐藏不删释义」）。
#    付费的中文一个字不丢，`merged_into` 清掉就全回来了。
DUP_SENSE_WHY = "duplicate-sense-in-entry"


def dup_sense_groups(con):
    """同一个 entry 内「中文释义逐字相同」而可以折叠的义项组。

    → [(留下来的 sense_id, [被折叠的 sense_id…])]，以及一份统计

    🔴 **只有一个家**：填充器、三道闸、两个收割器全都调它，谁都不许自己重写一遍。
    """
    import collections as _c
    zh = _c.defaultdict(list)
    for wid, sid, eid, t in con.execute(
            "SELECT s.word_id, s.id, s.entry_id, g.text FROM sense s "
            "  JOIN sense_gloss g ON g.sense_id = s.id AND g.lang = 'zh' "
            " WHERE s.hidden = 0"):
        zh[(wid, eid, (t or "").strip())].append(sid)
    cand = {k: v for k, v in zh.items() if len(v) > 1 and k[1] is not None}
    stat = _c.Counter()
    sids = [s for v in cand.values() for s in v]
    g = _c.defaultdict(dict)
    if sids:
        for sid, lang, t in con.execute(
                "SELECT sense_id, lang, text FROM sense_gloss WHERE sense_id IN (%s)"
                % ",".join(map(str, sids))):
            g[sid][lang] = (t or "").strip()
    out = []
    for v in cand.values():
        ens = {g[s].get("en") for s in v if g[s].get("en")}
        if len(ens) > 1:
            # ③ 两条都有英文而内容不同 ⇒ **有意不折**（中文比英文粗，记 W26）。
            # 🔴🔴 **但这一组里可能夹着「哑的」义项 —— 那些仍然是纯重复。**
            #    用户 2026-10-05 问「是之前翻译质量不行吗」，一查**不是**：
            #    `理发` 翻 `to give a haircut` 没错、翻 `to get a haircut` 也没错，
            #    中文的「理发」本身就同时覆盖两边。而**页面上已经分得开** ——
            #    展示层印 `vi-en`，读者看到的是
            #        动词  理发  to give a haircut
            #              理发  to get a haircut
            #    （`công quốc` 连例句「摩纳哥／卢森堡大公国」都把区别点明了）
            #    ⇒ 所以这 76 组不用花钱，W26 是一条**否定结论**。
            # ⚠️ **但查这件事的时候逮到了真缺陷**：组里有的义项**连英文也没有**，
            #    只带那条共享的中文 ⇒ 读者**一点区别都看不到**，它是纯重复。
            #    实测只有 **3 条**（`tiếng Việt` / `đá lửa` / `bảng cửu chương`，
            #    全来自中文版 —— 它只给中文，不给英文也不给越南语）。
            # ⭐ 这才是「否定结论要写清什么会推翻它」的正解：**推翻条件本身是可查的**，
            #    于是它变成一条闸（E19）而不是一句话。`[[record-the-negative-decision]]`。
            mute = [x for x in v if not g[x].get("en") and not g[x].get("vi")]
            talk = sorted(x for x in v if x not in mute)
            if mute and talk:
                out.append((talk[0], sorted(mute)))
                stat["哑义项折进有区别的那条（只有共享中文，别的一个字都没有）"] += len(mute)
            stat["有意不折：两条不同的英文（中文比英文粗，W26 ——"
                 "页面上靠已经印着的英文分得开）"] += 1
            continue
        order = sorted(v, key=lambda s: (0 if g[s].get("en") else 1,
                                         0 if g[s].get("vi") else 1, s))
        out.append((order[0], order[1:]))
        stat["可折的组"] += 1
        stat["可折的多余义项"] += len(order) - 1
    # ⚠️ 不折的那两批**单独报数**，不进 `out`。
    # 🔴 **第一版这里写错了**：它数的是 `entry_id IS NULL`（17 组），却印成
    #    「跨 entry」—— 而真正跨 entry 的是 484 组。报出来的数与标签不是一件事，
    #    正是 `[[measure-landing-not-source]]` 那条「报数前先问这个数量的是哪件事」。
    #    ⇒ 两个数各报各的，标签写准。
    stat["有意不折：entry_id 为空（取不到词性，无法判同不同）"] = sum(
        1 for k, v in zh.items() if len(v) > 1 and k[1] is None)
    byword = _c.defaultdict(set)
    for (wid, eid, t), v in zh.items():
        if eid is not None:
            byword[(wid, t)].add(eid)
    stat["有意不折：跨 entry（不同词性或词源号 ⇒ 正当，读者在两个标题下各看一次）"] = sum(
        1 for v in byword.values() if len(v) > 1)
    return out, stat


def merged_sense_map(con):
    """`sense_src.sense_id` → **例句/关系该挂到哪里**。→ {原 id: 目标 id 或 None}

    只收录需要改的那些；`None` 意思是「挂到词条级」（收割器的落点②）。

    ═══ 🔴🔴 两件事，而我第一版只做了第一件 ═══
    ① **被折叠的义项**（W25，`merged_into` 有值）⇒ 解析到留下来那条，沿链到底。
    ② 🔴 **被隐藏而没有去向的义项** ⇒ `None`（词条级）。
       第一版漏了这一半，于是 **7 条可出版例句挂在 W12 隐藏的义项上**
       （`gloss-is-punctuation-only` 3 条 ／ `gloss-is-source-markup` 4 条）——
       而展示层的 `bySense` 按 `senseId` 索引、**只遍历可见义项** ⇒
       这 7 条例句**永远不渲染，页面上无声消失**。
       ⭐ 这个洞是 **W12 修复时留下的**（隐藏义项却没管身上挂着什么），
         而它直到 W25 加了「可出版例句不许挂在隐藏义项上」这条断言才露出来 ——
         `[[correct-steps-can-compose-a-hole]]`：每步都对、跨步假设失效。
    ⚠️ 收割器里本来就有落点②「该义项被隐藏 ⇒ 词条级」，而它**只对
       `sense_src.sense_id IS NULL` 生效** —— 对「义项层建好之后才被隐藏的」
       结构性失明。本函数就是补这个失明。

    🔴🔴 两个收割器（例句层 / 关系层）的 `s2id` 都要过这一道，否则那 756 条
       可出版例句和 53 条关系在页面上整批消失。
    ⚠️ 做成「收割器解析」而不是「填充器去 UPDATE example.sense_id」的理由：
       外锚闸的例句恒等式**含 `sense_id`**，直接改库会判红而它会是对的
       （W16 刚栽过一次同形的）。让收割器自己产出解析后的值 ⇒ 闸仍是恒等式。
    ⚠️ 表里没有 `merged_into` 时只做第②件（填充器跑之前仍然成立）。
    """
    cols = {r[1] for r in con.execute("PRAGMA table_info(sense)")}
    has = "merged_into" in cols
    hidden = {i for (i,) in con.execute("SELECT id FROM sense WHERE hidden = 1")}
    raw = dict(con.execute("SELECT id, merged_into FROM sense "
                           "WHERE merged_into IS NOT NULL")) if has else {}
    out = {}
    for a in hidden:
        seen, b = {a}, raw.get(a)
        while b is not None and b in raw and b not in seen:   # 沿链走，并防自环
            seen.add(b)
            b = raw[b]
        # 🔴 链尾那条**自己也可能是隐藏的**（被别的判据隐藏）⇒ 那就落到词条级。
        #    不查这一步的话，例句会从一个看不见的义项搬到另一个看不见的义项。
        out[a] = b if (b is not None and b not in hidden) else None
    return out
