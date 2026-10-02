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
