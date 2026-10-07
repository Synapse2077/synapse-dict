#!/usr/bin/env python3
"""**阶段 6 的判据：例句 / 关系 / 量词 / 录音** —— 只写一份，住在这里。2026-10-01。

四个收割器、三道闸、一个探针都 `import` 这一份，谁都不许重写
（`[[criteria-narrower-than-you-think]]`、`[[refactor-mindset-code-quality]]`；
ko 的 K10 就是「判据漏用、我在量它的时候自写了一版更宽的」那个形状）。

═══ 🔴🔴 第一条：vi 版的 `example.translation` **不是译文** ═══
照字段名收会往出版层灌一批垃圾。实测 vi 版 709 条 `translation`：

    199 条（28.1%）整串就是 `.`        ← 纯标点残渣
    193 条（27.2%）是 `(…)` 形状       ← `(tục ngữ)` 谚语 / `(ca dao)` 民歌 / `(Truyện Kiều)`
    其余是 `(Khẩu ngữ) bốn mươi tám`   ← 语体标注 ＋ 越南语全写，仍然不是译文
    ⇒ **一条真译文都没有。**

⇒ 译文的语种按**版**定，不按字段名定（下面的 `TR_LANG`）。
  vi 版那批**不丢**，它是文献出处 ⇒ 进 `example.ref`。
  `[[criteria-from-meaning-not-form]]`、`[[clitic-compound-gloss-defect]]`（gloss＝元描述同形）。

═══ 🔴🔴 第二条：B17 的「兜底 related」判据，naive 版比正确版宽 **11 倍** ═══
`BACKLOG` B17 问的是「兜底 `related` 撞上更具体的 kind 时，读者会在两个标题下
看见同一个词」。实测 108,298 个 (词, 目标) 对：

    naive「related 撞上**任何**别的 kind」      14,547（13.4%）
    正确「related 撞上**语义上更具体**的 kind」   1,317（1.2%）   ⇒ 差 11.0 倍

差的那 13,230 全是 `paronym + related`（法语版同时列 *paronymes* 与 *apparentés*）。
**`paronym` 是语音关系，不是语义关系** —— 两个词读音相近**并不意味着**它们语义相关，
所以 `related` 在旁边仍然带信息，吞掉它是丢数据。
⇒ `SUBSUME` 里**有意排除 `paronym`**（也排除 `related` 自己）。
  🔴 `[[consult-two-models-on-rules]]`：「兜底分支要单独量」—— v4pro 那句
     「其余降为 related」在 ko 的数据里是 41.8%，照做＝修好 0 弄坏 2,739。
  🔴 **什么会推翻**：若将来发现某门把 `paronym` 当语义关系用（源头 tag 里出现
     语义限定），把它移进 `SUBSUME` 并重跑关系层。

═══ ⚠️ 第三条：录音的「张冠李戴」—— 判据能用，但**精确度只有 57%**，所以只隐藏不删 ═══
Lingua Libre 的文件名里**嵌着被录的那个词**（`LL-Q9199 (vie)-<录音者>-<词>.wav`），
这是一把源头自带的尺子。实测 7,839 个 LinguaLibre 文件里 27 个「文件名里的词 ≠ 词形」。

逐条读过那 27 条，真错只有 4 条（`sáo`←`sáu`、`số liệu`←`số hiệu`、
`đinh ba`←`dăm ba`、`thuyền quyên`←`mĩ nhân`），其余 23 条是**正字法异写**
（`chìa khoá/khóa`、`kĩ/kỹ năng`、`lí/lý do`、`đồi trụy/truỵ`、`Toà/Tòa`…）。

🔴 **第一版判据拿「两个词形的 IPA 集合有没有交集」当第二信号 —— 它错得很整齐**：
   把 `chìa khoá/chìa khóa`、`bất kì/bất kỳ`、`đồi trụy/đồi truỵ` 全判成张冠李戴。
   根因是阶段 3b 早就量过的那件事：**三版的转写约定不同**（词首 ʔ：en 18.7%／
   vi 0.0%／zh 19.5%）⇒ 「IPA 字符串不相等」量的是**哪一版给的音标**，不是读音不同。
   `[[criterion-true-half-vouches-for-false-half]]`：判据前半句（文件名嵌词）是真的，
   它给后半句（IPA 可以当同音判据）背了书。

✅ 换成**源头有没有说这两个词形是一回事**（`forms[alternative]` ／ `synonyms` ／
   `related` ／ `alt_of` ／ `form_of` 的无向对，64,781 对）：7 条命中，4 真 3 假。
   ⇒ 精确度 57%，**不够格去删**（`[[criteria-narrower-than-you-think]]`：
     宽判据会连带删掉 23 条对的）。⇒ `hidden=1` + `hidden_why`，可逆，
     而展示层永不播一条读错的音（`FRAMEWORK`：**错比缺更伤权威**）。
   ⚠️ 已知残差 3 条（`Toà Bạch Ốc`／`X`←`ích xì`／`ô-kê`←`OK`）记成欠账 **W8**。

═══ 🔴 第四条：`UNIQUE(word_id, url)` **挡不住 B12** ═══
实测 8,148 条原始录音 → 按 `(word_id, url)` 去重剩 4,560 → 按 Commons 归一键再并
**只剩 3,110**。也就是说光靠 schema 的唯一键，**1,450 行重复会落进库**，
而页面上会排出两个按钮播同一个文件。各版内嵌的是**转码后**的 mp3 名，
Commons 收割拿到的是原始名 —— 判据不是我们定的，是 MediaWiki 的标题归一规则。
⇒ 入库前按 `scripts/commons_filename.commons_key()` 并，**那一份是八门共用的唯一一份**。
"""
import re
import sys
import unicodedata as ud
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / "scripts"))

from commons_filename import commons_key, original_name          # noqa: E402,F401
from criteria import norm_vi                                      # noqa: E402

# ══════════════════════════════════════════════════════════════════════════
# ① 十二份切片。**顺序即优先级**（同一条证据多版都有时谁的 src 留在前面）
#    ⚠️ 别凭大小判断价值：`pl` 版整份只有 2,733 行，却给了 **970 条录音**
#    （占它自己 35.6%），比 `vi` 版的 186 条多五倍（`[[cross-edition-harvest]]`）。
EDITIONS = [
    ("en-edition", "en"), ("vi-edition", "vi"),
    ("zh-edition-trad", "zh"), ("zh-edition-simp", "zh"),
    ("fr-edition", "fr"), ("ja-edition", "ja"), ("ko-edition", "ko"),
    ("pl-edition", "pl"), ("ru-edition", "ru"), ("nl-edition", "nl"),
    ("pt-edition", "pt"), ("de-edition", "de"),
]

# ② 例句译文的语种：**按版定，不按字段名定**。
#    `None` ＝ 这一版的 `translation` 不是可出版的译文，逐条写明为什么。
TR_LANG = {
    "en-edition": "en",        # `english`/`translation`，13,753 条真英文译文
    "zh-edition-trad": "zh",   # 698 条真中文译文 —— **白送的中文，阶段 5b 要花钱买的东西**
    "zh-edition-simp": "zh",
    # 🔴 不是译文，是文献出处/语体标注 ⇒ 进 `example.ref`，见文件头第一条
    "vi-edition": None,
    # ⚠️ 第四语言：`[[gloss-three-languages]]` 只留 中+英+本语言。
    #    例句的译文与释义同理 —— 中文读者读不了法语/德语/韩语。
    #    **这是「我们有意不收」，不是「源头没有」**（`[[dont-say-source-lacks-what-we-skipped]]`）：
    #    fr 15,780 条 / de 903 / nl 532 / ru 71 / pt 46 / ko 41 / pl 12 / ja 4 都在源头里。
    #    🔴 什么会推翻：方针从三语放宽，或决定花钱把越南语例句本身译成中文（阶段 6d 那条路）。
    "fr-edition": None, "ja-edition": None, "ko-edition": None,
    "pl-edition": None, "ru-edition": None, "nl-edition": None,
    "pt-edition": None, "de-edition": None,
}

# ③ 例句的 `ref`：哪些版的 `translation` 其实是出处
#    （vi 版那 709 条；`ref` 字段本身所有版都直接用）
REF_FROM_TRANSLATION = {"vi-edition"}

# ══════════════════════════════════════════════════════════════════════════
# ④ 例句：哪些**压根不是可出版的例句**。顺序有意义，第一条命中即定案。
#
# ⚠️ 判据窄得刻意：只认「形式上根本不成例句」的四种，
#    **不**去判「这条例句好不好 / 够不够常用」—— 那是没有源头依据的事。
# ⭐ 实测落点在 dict 的 78,388 条里命中 1,352（1.7%），按版拆开看：
#       ko 版 730 ／ en 版 479 条是喃字正文（ko 版的「例句」本身就是汉字串 `沔南`）
#       vi 版 53 ／ en 版 13 条是「整条就是该词本身」（`Chi?` 之于 `chi`）
#    `[[report-business-not-housekeeping]]` 的反面教训（K15）：**形状检查报出来的
#    要分两堆读** —— 一堆是判据太宽，一堆是真的渣。按版拆开才分得出来。
HIDDEN_NO_LATIN = "nom-script-quotation"     # 喃字/汉字正文，国语字一个字母都没有
HIDDEN_SAME_AS_WORD = "same-as-headword"     # 整条就是该词本身，零信息
HIDDEN_TOO_SHORT = "too-short"
HIDDEN_SRC_CHINESE = "source-says-chinese"   # 源头自己标了 Traditional-Chinese/Pinyin
# 🔴🔴 2026-10-03 **阶段 9 把例句渲染出来才看见的**（数据层五道闸全绿）：
#    ko 版 1,718 条可出版例句里 **1,655 条（96.3%）的 `text` 内嵌着韩语译文**，
#    源头把两者挤在同一格、**没有独立译文字段**（只有 `bold_text_offsets`）——
#    与 ko 那门「中文译文用全角空格挤在 text 同一格」是**同一个形状的镜像**。
#    三语方针（中＋英＋越）下韩语不该出现在页面上，而它占了正文一半长度。
#    ⇒ 切掉韩语那半（见 `strip_foreign_translation`）。
#    ⚠️ 切完**剩不下越南语**的 45 条，根本不是例句：
#        `같은 말 : yêu thương`（同义词）／`비슷한말:`（近义词）／`비교 :`（比较）／
#        `고유명사는 Nhật 참조`（专有名词参见）——**是关系数据和元说明**。
#      与 ko 自己记的「韩文版 examples 里混着 3,267 行关系数据」同形，
#      而 vi 从 ko 版收割所以照样中。⇒ 隐藏它们，并记欠账（那批关系我们没收）。
HIDDEN_KO_LABEL = "ko-edition-label-line"    # 整条是韩语标签/关系数据，不是例句

# 哪些版把**译文挤在 `text` 同一格里**。⚠️ 这是**按版登记**，不是形状判据 ——
#    别写成「只要含韩文就切」：那会在哪天 en 版引用一句韩语时把它切掉。
TRANSLATION_INSIDE_TEXT = {"ko-edition"}
_HANGUL = ((0xAC00, 0xD7A3), (0x1100, 0x11FF), (0x3130, 0x318F))


def _is_hangul(ch):
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in _HANGUL)


def strip_foreign_translation(text):
    """把挤在同一格里的韩语译文切掉，只留越南语。→ 切完的串（可能是空的）。

    🔴 **不是「从第一个韩文字符截断」那么简单**：源头有一格里越南语与韩语
       **交替出现多次**的形状 ——
           `Bây giờ là mấy giờ ? 지금은 몇 시입니까? / Hai giờ . 두 시요. / Hai giờ rồi à ? …`
       整串从第一个韩文字符截断，会把后面两句越南语一起丢掉。
    ⇒ 判据：**按 ` / ` 分段，每段各自从它自己的第一个韩文字符起丢掉**。
      实测 1,655 条里 1,610 条（97.3%）切完仍有越南语；剩 45 条一个字母都不剩
      ⇒ 那 45 条本来就不是例句（`HIDDEN_KO_LABEL`）。
    """
    out = []
    for seg in (text or "").split(" / "):
        i = next((k for k, ch in enumerate(seg) if _is_hangul(ch)), None)
        kept = (seg[:i] if i is not None else seg).strip()
        if kept:
            out.append(kept)
    return " / ".join(out)

# 越南语字母表（含全部带调元音）。🔴 **不手抄「拉丁基本区」** ——
#    `ă đ ơ ư` 与所有带调元音都在扩展区，手抄会把越南语自己的字母删掉。
_VI_LETTER = re.compile(r"[a-z]", re.I)


def _has_quoc_ngu(t):
    """这串里有没有国语字（拉丁字母，含带调的）。

    判据交给 Unicode 答：先 NFD 拆出基字母再找 ASCII a–z，
    这样 `đường` / `Việt` / `ă` 都算有，而 `沔南` / `𠊛` 不算。
    `[[criteria-narrower-than-you-think]]` 的正面用法：别手抄码位范围。
    """
    return bool(_VI_LETTER.search(ud.normalize("NFD", t or "")))


def ref_is_unreadable(ref):
    """这条出处对中文读者**完全不可读** ⇒ 不发布。→ True/False

    🔴🔴 **2026-10-03 展示层契约闸逮到的，而它逮到的是「判据漏用」**：
       切掉内嵌韩语译文那一步我只用在 `text` 上，`ref` 漏了 ⇒ `ăn` 页面上
       印着「出处：창세기 2장 9절」（创世记 2 章 9 节）。
    ⚠️ **判据不是「含韩文就切」** —— 我的第一反应是把 `strip_foreign_translation`
       也套在 `ref` 上，量过之后发现那会**截断 56 条正当引文**：
           `2021 [2016], Han Kang, "Mưa tuyết", in Hà Linh …`
       英文版的引文里带韩国作者名的原文，从第一个韩文字符截断 ⇒ 引文断在中间，
       **一条截断的引文比一条读不懂的引文更坏**（它看起来是完整的）。
    ⇒ 判据按「可读性」写：**一个拉丁字母都没有**就不可读（679 条，全是韩语版的圣经章节号）；
      以拉丁为主、夹着原文人名的那 56 条**原样保留**。
      `[[criteria-narrower-than-you-think]]` 的正面用法：先量，再定宽窄。
    """
    t = (ref or "").strip()
    return bool(t) and not _has_quoc_ngu(t)


# ══════════════════════════════════════════════════════════════════════════
# ⑤ **2026-10-03：阶段 6e 开跑前逮到的四类「这行根本不是例句」。**
#
# 🔴🔴 **这是「花钱之前先逮到本层的缺陷」第二次兑现**（ko 的 1% 定价切片逮到 K15
#    把 385 条谚语成分拆解当例句收了）。这一次**连切片都还没跑** —— 因为 6e 要买的
#    就是「把 `text` 译成中文」，所以开跑前必须先问一句「`text` 里装的真是例句吗」。
#    ⇒ ⭐ **要花钱加工某一列之前，先把那一列本身量一遍。**
#
# ⚠️ 这四条**都不是「例句质量」判据**，与上面 ④ 同一条纪律：只认「形式上根本不成例句」。
#
# 📋 **有意不处理、已记欠账 W16**：「越南语 + ` : ` + 法语释义」挤一格 31 条
#    （`Nắng to : il fait grand soleil.`，fr 版 30 ／ en 版 1）。它需要一个
#    **政策决定**（法语尾巴是丢掉还是留在证据层），而三语方针说页面上不该有法语。
#    那一条不在用户 2026-10-03 批准的范围里（批准的是「越南语正文缺失」那批），
#    所以 `is_not_vietnamese` **显式把它放过**，见函数里的 `_mixed_vi_head`。

HIDDEN_META_NOT_EXAMPLE = "metadata-not-example"   # 近义词表／交叉引用注，不是例句
HIDDEN_CITATION_ONLY = "citation-only"             # 整条只有出处，正文缺失
HIDDEN_NO_VIETNAMESE = "source-has-no-vietnamese"  # 外语原文，源头没给越南语正文

# ── ⑤a 近义词/反义词元数据 ──────────────────────────────────────────────
# 实测 52 条：`Near-synonym: sự` / `Near-synonyms: trong, trong vắt, …`
# 🔴 源头把 `synonyms` 那一族塞进了 `examples`，与 ko 版那 45 条韩语标签行
#    （`같은 말 :` / `비슷한말:`）是**同一个形状，不同的语言** ——
#    `HIDDEN_KO_LABEL` 只靠「切完韩语不剩字母」抓得住，英文版这批**一个韩文字都没有**，
#    所以那条判据在这里结构性失明。⇒ 必须单列一条。
# ⚠️ 判据钉在行首，不是「含 synonym 就算」：`Near-synonyms` 出现在例句正文里是正常的。
# 📋 这批关系数据我们**没有收**（与 ko 的同一笔欠账同形），记在 W17。
#
# 🔴🔴 **2026-10-03 第二次收：第一版这张表漏了一半，是付费跑批的产物报出来的。**
#    全量 76,028 条译文里「没有一个汉字（多半没翻译）」22 条，逐条读下去是：
#        `Coordinate term: mi` ×27     关系元数据（最大的一漏）
#        `level tone: y` / `high rising: ý` ×18  **声调范式表**（字母条目 `y`/`ơ`/`ô`
#                                       列它那个元音的六个声调），是音系元数据不是例句
#        `Meronyms: tàu hoả (…)` ×1 ／ `cf: đồng cảm` ×2
#    ⭐ **模型拒绝翻译它们**（原样返回）—— 它看出那不是句子，而我的判据没看出来。
#      这是「花钱之后才逮到」的那一类，与 ko 的 K15（385 条谚语成分拆解）同形。
# ⇒ 判据改成**登记表**：kaikki 把关系字段压进 `examples` 时用的那套英文显示名，
#   加上越南语的六个声调名。`[[criteria-from-meaning-not-form]]`：
#   这批东西的本质是**源头的一张标签表**，就该用枚举而不是形状去对。
# 🔴 什么会推翻：源头新增一种关系字段名（查法：`probes/probe_stage6.py` 的行首标签普查）。
_META_LABELS = (
    # ① kaikki 的关系字段显示名（单复数都要，源头两种都出现过）
    "synonym", "synonyms", "near-synonym", "near-synonyms",
    "antonym", "antonyms", "near-antonym", "near-antonyms",
    "hypernym", "hypernyms", "hyponym", "hyponyms",
    "meronym", "meronyms", "holonym", "holonyms",
    "coordinate term", "coordinate terms", "comeronym", "comeronyms",
    "troponym", "troponyms", "derived term", "derived terms",
    "related term", "related terms", "see also", "cf",
    # ② 越南语六声的英文名 —— 字母条目的声调范式表，不是例句
    "level tone", "high rising", "high rising glottalized",
    "low", "low falling", "low glottalized", "dipping-rising", "falling",
)
_META_LINE = re.compile(
    r"^\s*(?:%s)\s*:\s" % "|".join(re.escape(x) for x in _META_LABELS), re.I)
# `For examples of this term in chữ Nôm, see 𤈜, 奵.` —— 交叉引用注，实测 1 条
_XREF_LINE = re.compile(r"For examples of this term in chữ Nôm")


def is_meta_not_example(text):
    """这条是**元数据/交叉引用注**，不是例句。→ True/False"""
    t = (text or "").strip()
    return bool(_META_LINE.search(t) or _XREF_LINE.search(t))


# ── ⑤b 出处 ───────────────────────────────────────────────────────────
# 源头把引文的出处行塞进了 `text`，而 kaikki 的 `ref` 字段是空的。两种后果：
#   ⑤b-1 多行：出处在**首行**，越南语正文在后面 ⇒ **可修**，首行搬进 `ref`（201 条）
#   ⑤b-2 单行：整条**只有**出处，正文根本不在 ⇒ 隐藏（24 条）
# 实测两类的 `ref` **200/201 与 24/24 都是空的**，搬过去不会覆盖任何东西。
# 🔴🔴 **2026-10-03 第二次收：第一版漏了 36 条，也是付费跑批报出来的。**
#    全量里「行数不对」30 条，大半根因是**出处还留在 `text` 首行**，模型把它
#    当正文译了或原样返回：
#        `c. 11th - 7th century BCE, Classic of Poetry, free 2003 translation by Tạ Quang Phát`
#        `1932: Lệ Xuân, "Nhà đại ký-giả thời-sự", Phụ Nữ Tân Văn, issue 150, page 12 http://…`
#        `19th century, Nguyễn Đình Chiểu, Tale of Lục Vân Tiên, 1916 Nôm version, lines 443-444`
#    我第一版只认 `English/Vietnamese translation` / `, transl.` / `; quoted in` ——
#    而 `free 2003 translation by` 不含 `English`，`1932: …` 一个关键词都没有。
# ⇒ 判据改成**出处的本质特征：以年份/世纪开头**。引文出处几乎一律先写时间，
#   而越南语例句正文**不会**以「四位数年份＋标点」开头。
#   ⚠️ 仍然要与「越南语音节率 < 0.6」**同时成立**（见 `is_citation_line`）——
#     单靠年份会咬到正文里真的以年份开头的句子。
#
# 🔴🔴🔴 **第三次收窄（同一天）—— 这一次是分支写错了，不是漏了关键词。**
#    `thối` 的那条例句：原文 4 行、译文 3 行，而首行是
#        `1939: Ngô Tất Tố, Lều chõng`
#    —— 一条**用越南语写的出处**。它被漏掉的原因不是关键词不够，而是
#    `is_citation_line` 要求「越南语音节率 < 0.6」，**而越南语写的出处音节率是 1.00**。
#    ⇒ 那道音节门对「关键词」那一支是对的（防「正文里引到 English translation」），
#      对「年份开头」那一支**正好是反的**：它恰恰把越南文献的出处全挡住了。
#    ⭐ 这是 vi 阶段 7 那一课的重演：**同一个形式判据在两个地方意思相反**
#      （「整段都是表意文字」用在词头上是「这是表记」、用在词源段上却可能正是中文词源）。
#      ⇒ 判据按**分支**写，不共用安全网。
#    实测放开后多出 **82 条**（多行首行 65 ＋ 整条就是出处 17），**逐条读完全是真出处**。
# ⚠️ 年份那一支换一个**结构**安全信号（不是音节）：出处是参考文献不是句子 ⇒
#    「不以句末标点结尾」**或**「有文献式结构（≥2 个逗号／带引号书名）」。
#    两条各自漏 4 / 3 条，并起来正好覆盖 82 条。
#    🔴 什么会推翻：出现以 `1945,` 开头、带两个逗号、不以句号结尾的**真句子**
#      （查法：把 `_CITATION_YEAR` 的命中集重读一遍）。
_CITATION_KW = re.compile(
    r"(English|Vietnamese|vietnamienne?)\s+translation"   # `; English translation by …`
    r"|\btransl(ation|ated)?\b\s+(by|from|of)\b"          # `free 2003 translation by …`
    r"|,\s*transl\."                                      # `in Nguyễn Thành Long, transl.,`
    r"|;\s*quoted (and translated )?in ")                 # `; quoted and translated in …`
_CITATION_YEAR = re.compile(
    r"^\s*(c?\.?\s*\d{3,4}\s*(\[\d{3,4}\])?\s*[,:]"       # `1932: …` / `2012 [1943], …`
    r"|\d{1,2}(st|nd|rd|th)\s+century\b"                  # `19th century, Nguyễn Đình Chiểu…`
    r"|c\.\s*\d+.{0,24}\bBCE\b)")                         # `c. 11th - 7th century BCE, …`
_SENTENCE_END = re.compile(r"[.!?…。！？]\s*$")


def is_citation_line(line, syllables):
    """这一行是**出处**不是正文。→ True/False

    **两支，各带各自的安全网** —— 见 `_CITATION_YEAR` 上方那段（第三次收窄的理由）。

    ① 关键词支（`English translation by` / `, transl.` / `; quoted in`）：
       🔴 必须再满足「越南语音节率 < 0.6」。只看关键词 ⇒ 越南语**正文**里
          引到「English translation」的句子会被当出处。
    ② 年份支（`1939:` / `19th century,` / `c. 11th … BCE,`）：
       🔴 **不许用音节率当安全网** —— 越南语写的出处音节率是 1.00，那道门把它们全挡了。
          换成**结构**信号：出处是参考文献不是句子 ⇒ 不以句末标点结尾，
          或带文献式结构（≥2 个逗号／引号书名）。
    """
    t = (line or "").strip()
    if _CITATION_KW.search(t) and vi_syllable_rate(t, syllables) < 0.60:
        return True
    if _CITATION_YEAR.match(t):
        return (not _SENTENCE_END.search(t)
                or t.count(",") >= 2 or '"' in t or "“" in t)
    return False


def split_citation_prefix(text, syllables):
    """多行例句的首行是出处 ⇒ 切出来。→ (出处 或 None, 正文)

    ⚠️ **只切首行**。源头的形状是「出处 ⏎ 正文 ⏎ 正文…」，而出处行**只有一行**；
       写成「把所有像出处的行都切掉」会咬掉正文里的作者引语。
    """
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    if len(lines) > 1 and is_citation_line(lines[0], syllables):
        return lines[0], "\n".join(lines[1:])
    return None, "\n".join(lines)


# ── ⑤c 越南语音节率：判据**用我们自己的 `dict` 当词表，不手抄字母表** ──────
# 🔴🔴 第一版判据是「NFD 之后没有组合符 ⇒ 不是越南语」，它漏掉了**带 `é` 的法语、
#    全部俄语/文言文/德语/拉丁语**（`Credo in Deum Patrem omnipotentem` 出现 3 次）。
#    换成「例句里有多少 token 是 `dict` 里的越南语单音节」之后那些全被逮到。
# ⭐ 这是 `[[criteria-from-meaning-not-form]]` 的正面用法：
#    「这是不是越南语」的含义是「它的词是不是越南语词」，而我们手上**正好有一张
#    30 万词形的越南语词表** —— 不必、也不该去手抄哪些字母算越南语。
# ⚠️ 它依赖 `dict` 的内容 ⇒ **收词变了这个数会变**。所以它不适合锁成常量，
#    回归闸锁的是「命中这条的行数」而不是「音节表有多大」。


def vi_syllables(src):
    """越南语单音节词形表（判据的唯一来源）。→ set[str]

    `src` 可以是**数据库连接/游标**，也可以是**词形的可迭代物** ——
    🔴 两种入口一个实现。收割器手上只有 `wid` 这个 dict、闸手上是连接，
       而我第一版给收割器手抄了一遍 `{w.lower() for w in wid if " " not in w}` ——
       **同一条判据的第二份实现**，正是 `[[refactor-mindset-code-quality]]` 和
       vi 阶段 6 那一跤（同一个谓词两份实现只修了一份 ⇒ 155 个汉字词头躺在 dict 里）。

    ⚠️ 只取**不含空格**的词形：多音节词的每个音节几乎都单独成词，
       而把多音节词整条放进表里会让 token 级的比对永远不命中。
    """
    words = ((w for (w,) in src.execute("SELECT word FROM dict"))
             if hasattr(src, "execute") else src)
    return {w.lower() for w in words if w and " " not in w}


_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def vi_syllable_rate(text, syllables):
    """这串里有多少比例的 token 是越南语音节。→ 0.0–1.0（无可判 token 时返 1.0）

    单字母 token 不参与（`I` `a` `à` 在两种语言里都成立，是噪声不是信号）。
    """
    toks = [t.lower() for t in _TOKEN.findall(text or "")]
    toks = [t for t in toks if len(t) > 1]
    if not toks:
        return 1.0
    return sum(1 for t in toks if t in syllables) / len(toks)


_VI_MARK_D = "đĐ"
_SEP_GLOSS = re.compile(r"\s+[:：—―]\s+|\s*[:：]\s+")


def vi_mark_count(text):
    """越南语标记数（组合声调符 ＋ `đ`）。0 ⇒ 这串里**一个越南语专有符号都没有**。"""
    n = ud.normalize("NFD", text or "")
    return (sum(1 for c in n if ud.combining(c))
            + sum(1 for c in (text or "") if c in _VI_MARK_D))


_EN_STOP = frozenset("""the of and in to is was that with for have has their they this
    which from are were it as by not but he she you your his her its be been at on or
    we there""".split())
_FR_STOP = frozenset("""le la les de des du et est que qui dans pour une un il elle ne
    pas avec sur au aux ou se son sa ses en par plus""".split())


def _foreign_by_stopwords(text):
    """判据 A：**一个越南语专有符号都没有**，且含 ≥2 个英/法虚词。

    ⚠️ 单独用它召回不全（带 `é` 的法语、俄语、文言文全漏），所以它只是并集的一半。
    """
    if vi_mark_count(text) > 0:
        return False
    ws = [t.lower() for t in _TOKEN.findall(text or "")]
    return (sum(1 for w in ws if w in _EN_STOP) >= 2
            or sum(1 for w in ws if w in _FR_STOP) >= 2)


def _mixed_vi_head(text, word, syllables):
    """句首那段是越南语（且含词头）、分隔符后面才是外语释义 ⇒ **不属于「正文缺失」**。

    📋 2026-10-03 建它时只为一件事：把 W16 那一族从 `is_not_vietnamese` 手里**放过**。
    ✅ 2026-10-05 它有了第二个调用方：`split_edition_gloss()` 拿它当**结构安全网**。
       ⭐ 「词头必须出现在头里」这一条看着不起眼，却是**唯一**能把
            `Người linh mục nói : cha cầu Chúa cho các con`（词头 `cha` 在**尾巴**里）
         这种整句越南语从「词条:释义」里分出来的判据 —— 音节率、变音符都分不开
         （法语与越南语共用组合变音符，见 §⑥）。
    ⚠️ 两个调用方口径必须一致：一个说「这不是正文缺失」、另一个说「所以尾巴是释义」，
       说的是同一件事。**所以只能有这一份实现。**
    """
    if not _SEP_GLOSS.search(text or ""):
        return False
    head = _SEP_GLOSS.split(text, 1)[0]
    wl = (word or "").lower()
    return (vi_syllable_rate(head, syllables) >= 0.5
            and bool(wl) and wl in head.lower())


def is_not_vietnamese(text, word, syllables):
    """整条例句**不是越南语** —— 源头给了外语原文而越南语正文缺失。→ True/False

    🔴🔴🔴 **2026-10-03 实测 112 条可出版例句落在这里**，而五道数据层闸全绿：
        `tử ngữ`（死语）页上印着一整段《美丽新世界》的**英文**散文
        `tìm kiếm` 页上是《小王子》的**法语**原文
        还有俄语（`Подо́бно Петру́ I, большевики́…`）、文言文（`至周莊王時…`）、
        德语（`Der Mensch ist im wörtlichsten Sinn…`）、拉丁语（《使徒信经》×3）
    回 dump 核过 —— **源头自己就没有越南语正文**：
        tử ngữ  ref  : …Hiếu Tân, transl., Thế giới mới tươi đẹp, translation of Brave New World
                text : The Director interrupted himself. "You know what Polish is, I suppose?"…
                bold_text_offsets [[75, 88]]   ← 指向英文里的 "A dead language"
    `ref` 承诺的越译本在 dump 里**根本不存在**，词头的引证是靠英文成立的。
    ⇒ **这不是我们漏抽，是源头缺**（`[[dont-say-source-lacks-what-we-skipped]]`）——
      但它作为**越南语**例句不可出版：读者在越南语词头下看到的是一段英文散文。
      隐藏，证据层一行不动；哪天源头补了越南语正文就能放回来。

    ⭐ **两条独立判据的并集，各自都漏**（`[[verification-gates-not-sampling]]`）：
       A 符号判据（无声调符 ＋ 英/法虚词）：漏掉带 `é` 的法语和全部非拉丁文字
       B 音节判据（越南语音节率 < 0.30，≥6 个 token）：补上了 A 漏的那些
       两条交叉读过 84／124 两批，A 的 2 条误伤正是 B 帮着认出来的。
    """
    t = (text or "").strip()
    if not t:
        return False
    if _mixed_vi_head(t, word, syllables):
        return False                       # W16 那一族，有意放过
    if _foreign_by_stopwords(t):
        return True
    toks = [x for x in _TOKEN.findall(t) if len(x) > 1]
    return len(toks) >= 6 and vi_syllable_rate(t, syllables) < 0.30


# ── ⑤d 内嵌英译行：**搬进 `example_gloss`，不是删** ────────────────────
# 实测 281 条多行例句的 `text` 里夹着英译行，而其中 **262 条库里没有英译**
# ⇒ 🔴 剥掉就**丢了英译**。正确动作是搬进 `example_gloss(lang='en')`，顺手白捡 262 条。
#   剩 19 条已有 `example_gloss(en)` ⇒ 内嵌那行是重复，剥掉不丢数据。
#
# 🔴🔴 **不能复用 `strip_foreign_translation`**（韩语那条）：它靠「字符是不是韩文」
#    切，而英语和越南语**共用拉丁字母**，字形上分不开。⇒ 必须换一条判据。
# ⚠️ 判据按**行**走，不按 ` / ` 分段：源头这一族的形状是「越南语行 ⏎ 英译行」，
#    与 ko 那族「同一行里交替」正相反。同一个病在两个版里形状不同，
#    这正是 `TRANSLATION_INSIDE_TEXT` **按版登记而不写成形状判据**的理由。
_EN_WORD = re.compile(r"[A-Za-z]{2,}")

# 哪些版把**英译**按行塞在 `text` 里。🔴 **按版登记，不是形状判据** ——
#    与 `TRANSLATION_INSIDE_TEXT` 同一条规矩，而这次是**当场栽进去的**：
#    第一版没有这张表，于是 `nl` 版的 2 行**荷兰语**被判成英译、存成 `lang='en'`：
#        text  `#*: Chuyện ấy xảy ra từ bao giờ? – Wanneer is dat gebeurd?`
#        存进去 gloss[en] = `naar een tijdstip in het verleden als aan het eind van de zin`
#    ⚠️ 它**绕过了三语闸 X9**（X9 查 `lang NOT IN ('zh','en','vi')`，
#      而荷兰语被贴上了 `en` 的标签）⇒ 形状判据配上「贴错标签」就对闸隐身。
#    ⇒ 判据问登记表。荷兰语与英语共用拉丁字母，字形上永远分不开。
# 🔴 什么会推翻：别的版也开始按行塞英译（查法：`collect()` 的
#    「内嵌英译行搬进译文（<版>）」统计项出现新的版名）。
INLINE_EN_IN_TEXT = {"en-edition"}


def split_inline_english(text):
    """切出夹在多行例句里的英译行。→ (越南语正文, [英译行…])

    判据：**整块里至少有一行带越南语标记**（否则这是 `is_not_vietnamese` 的事，
    不是本函数的事），而**这一行一个越南语标记都没有且有 ≥4 个英文词**。
    ⚠️ `≥4 个词` 这道门槛挡的是 `Sao?` `[...]` 这种短行 —— 它们不是英译，
      切掉会把正文弄残。实测 384 行命中，逐条读过零误伤
      （`The little guerrilla damsel holds her rifle high.`）。
    """
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    if not any(vi_mark_count(l) for l in lines):
        return "\n".join(lines), []        # 整块无越南语 ⇒ 不是本函数的事
    body, en = [], []
    for l in lines:
        if not vi_mark_count(l) and len(_EN_WORD.findall(l)) >= 4:
            en.append(l)
        else:
            body.append(l)
    return "\n".join(body), en


# ── ⑤e 标记残渣：**出版正文里不许留 wiki 标记** ────────────────────────
# 🔴 这一族是 `INLINE_EN_IN_TEXT` 那个洞**顺带照出来的**（nl 版那 2 行一看就是
#    `#*: Chuyện ấy xảy ra từ bao giờ? – Wanneer is dat gebeurd?`）。
#    ⭐ 一个缺陷的修复过程照出另一个缺陷，是「把数据渲染/打印出来读」的红利。
#
# 三族，实测落点都在**可出版**正文里（读者看得见）：
#     `#*: ` 行首 wiki 标记              2 条（nl 版）
#     落单的 `]]` / `[[`                  6 条（vi 版，`Cá cắn câu]].`）
#     `^([sic])` 上标               45＋13 处（kaikki 把上标渲染成 `^(…)`）
#
# 🔴🔴 **`[sic]` 不许删，只许改成可读的。** `[[source-typo-fix-ours-not-quote]]`：
#    源头本身写错时，改我们的出版文本，**引文与证据层一个字不动**。而 `[sic]`
#    正是「这个错在原文里就有」的编辑标记 —— 删掉它就等于把引文改成没错过。
#    ⇒ `^([sic – meaning tổ])` → `[sic – meaning tổ]`，内容一字不丢，只去掉 `^(` `)`。
#
# 📋 **有意不在这里处理、记欠账 W18**：
#    `ref` 里的 93 处 `^(https://vi.wikisource.org/…)`（Truyện Kiều 的 wikisource 链接）
#    以及 `sense_gloss` 46 行 / `etymology` 3 行里的同族残渣。
#    理由：它们**不在 6e 的付费载荷里**（6e 只翻 `example.text`），
#    而 `ref` 里的 URL 该不该上页面是另一个问题。⚠️ 不是「不存在」，是「另一笔」。

# `#*: ` —— 要求有 `#`，或 `*`/`:` 至少两个。**不写成 `^[#*:]+`**：
#   单个 `:` 或 `*` 开头在正文里是可能的（对白、项目符号），一刀切会削掉正文第一个字。
_WIKI_PREFIX = re.compile(r"^[ \t]*(?:#[#*:]*|[*:]{2,})[ \t]*", re.M)
_STRAY_LINK = re.compile(r"\[\[|\]\]")
# `^([sic])` → `[sic]`。**只认方括号那一族** —— `^(https://…)` 是另一回事（W18），
#   而且它在 `ref` 里不在正文里。
_SUPERSCRIPT_NOTE = re.compile(r"\^\((\[[^\]]*\])\)")


def clean_markup(text):
    """去掉出版正文里的 wiki 标记残渣。→ 清洗后的串

    ⚠️ 三条都是**纯标记**或**渲染错误**，没有一条在删内容：
       `[sic]` 的字一个不少，只是不再带着 `^(` `)`。

    🔴🔴 **空白归一只作用在它自己改过的那些行上。** 第一版无条件 `" ".join(l.split())`
       收尾，实测 **267 条改动里 212 条是空白改的** —— 四倍于它要修的那个缺陷，
       而且其中有 `c.\\u200911th`（窄空格，引文里的字符）被换成普通空格。
       `[[criteria-narrower-than-you-think]]`：函数叫 `clean_markup`，
       空白不在它的名字里；**不在名字里的副作用，量级还比主作用大，就是个洞**。
       ⇒ 删标记之后那一行可能留下双空格或行首空白（是我弄出来的）⇒ 只收拾那一行。
    """
    out = []
    for line in (text or "").split("\n"):
        new = _STRAY_LINK.sub("", _WIKI_PREFIX.sub("", _SUPERSCRIPT_NOTE.sub(r"\1", line)))
        if new != line:                      # 只有被我改过的行才整理空白
            new = " ".join(new.split())
        out.append(new)
    return "\n".join(l for l in out if l.strip())


# ── ⑤f 同一族残渣在**别的列**上：W18 的判据之家。2026-10-06 ──────────────
# 📋 W18 这笔账开着两天，而**它一直没有一道闸** —— 账上写着「`ref` 93 处 ／
#    `sense_gloss` 46 行 ／ `etymology` 3 行」，可那三个数没有任何东西数过。
#    `[[fix-regression-and-gate]]`：量过、写进账本、**然后就没人再看了**，
#    是这仓库最常见的一种失明。今天给它判据之家＋三个锁。
#
# ⚠️ 判据写成**残留型**（`[[proxy-metric-gets-optimized]]` 的反面）：
#    它先跑一遍 `clean_markup` 再问「还留着吗」。于是两个方向都有信号 ——
#      · 哪天 `clean_markup` 伸到这三列上 ⇒ 三个数掉下来 ⇒ 闸红 ⇒ **逼人回来改账**；
#      · 哪天 `_SUPERSCRIPT_NOTE` 被删掉 ⇒ 例句正文那 58 处又冒出来 ⇒ 闸红。
#    若写成裸正则 `LIKE '%^(%'`，第一个方向就哑了（判据和被判据的东西脱钩）。
_SUP_LEFT = re.compile(r"\^\(")


def sup_residue(text):
    """→ True ＝ `clean_markup` 之后这一串里**还留着** `^(…)` 上标残渣（W18）。

    kaikki 把维基的上标渲染成 `^(…)`。`clean_markup` 只认**方括号那一族**
    （`^([sic])` → `[sic]`，因为 `[sic]` 的字一个都不许丢）；
    `^(https://vi.wikisource.org/…)` 这类 URL 是另一回事，也在另外三列上。
    """
    return bool(_SUP_LEFT.search(clean_markup(text or "")))


# ── ⑤g fr 版把 JavaScript 实参列表漏进例句正文：W20 的判据之家 ───────────
# 🔴 法语维基词典的页面上有 `onclick="javascript:…('morale','vietphap','on')"`，
#    kaikki 抽 `examples` 时把属性值的尾巴也带了进来：
#        `','vietphap','on')"morale`      ← 整条**一个可读的越南语词都没有**
#    ⭐ 逮到它的是**阶段 6e 的付费跑批**：模型拿到它没东西可译、原样返回，
#      而「译文里没有一个汉字」这条异常检查把它捞了出来
#      （`[[measure-landing-not-source]]` 的另一面：**跑批产物的异常输出是独立的缺陷探测器**）。
#
# ⚠️ 判据按**结构**写不按词表写：匹配的是「引号括起来的实参 ＋ 收尾的 `)"`」——
#    HTML 属性值的边界。写成 `'vietphap'` 那种词表判据的话，
#    换一个法语模板名就一条都抓不到（`[[criteria-from-meaning-not-form]]`）。
# 🔴 **而它必须比「有残渣」更窄：是「整条只剩残渣」。** 同一版里还有四条
#    **带着可读内容**的标记残渣（`'tỉnh, province` ／ `'huyện, division du phủ…`
#    ／ `'chuồng ngựa` ／ `'âm hưởng' phòng hòa nhạc`，行首落单的单引号是同一个
#    JS 调用被截断留下的）—— 那四条**不是 W20**：前两条是 fr 版的「越南语词＋法语释义」
#    （W16 那一族，只是分隔符是逗号不是 ` : `），后两条是正文带个多余的引号。
#    把它们一起判成「不是例句」会**删掉可读的内容**，而那比留着残渣更坏
#    （`[[source-typo-fix-ours-not-quote]]`：一条被截断的引文看起来是完整的）。
_JS_ARG_RESIDUE = re.compile(r"','[^']*'\)\"")

HIDDEN_JS_RESIDUE = "js-markup-residue"   # 整条只是 JS 标记残渣，不是例句


# ── ⑤h W22 的度量键：`example.text` 被原地改过的行数 ─────────────────────
# 📋 W22 记的是一个**结构不一致**：例句层有五种清洗，**四种直接改 `text`**
#    （ko 版内嵌韩语 1,655 条／出处串进首行 202 条／内嵌英译 282 行／标记残渣 55 条），
#    第五种（W16 的本版释义尾巴）**不改 `text`**，只算一条派生的出版正文 `text_pub`。
# 🔴 真实代价不是「风格不统一」，是**外锚闸的第③向（键对上而内容不一样）锚的是
#    清洗后的 `text`** ⇒ 它问不了「源头原文是什么」，而那正是
#    `[[external-anchor-gates]]` 要的那种锚（锚外部 dump 的闸永不过期）。
# ⇒ 2026-10-06 的动作：**先把这件事变成一个会被数的数**，而不是一句话。
#    收割器在末尾拿最终 `text` 与 dump 原文比一次，记在这个键上；
#    外锚闸 `X源⑥` 锁住它。四种清洗哪天迁到 `text_pub`，它归 0 ⇒ 闸红 ⇒ 逼人划账。
# ⚠️ 这不是结清 W22，是给它配一道闸（结清要做的是迁移，而迁移会动 7.8 万行的
#    `text`，那是一次有付费数据在场的大改，要单独一轮）。
TEXT_MUTATED_IN_PLACE = "🔴 W22：`text` 被原地改过（与 dump 原文逐字不同）"


def is_js_residue(text):
    """→ True ＝ 整条只是 JavaScript 标记残渣，不是例句（W20）。"""
    return bool(_JS_ARG_RESIDUE.search(text or ""))


# ── ⑥ 本版自己的释义语言挤在同一格里（W16）────────────────────────────
# 🔴 **先把「法语和越南语关系密切」这件事摘清楚**（用户 2026-10-05 问的就是这个）：
#    关系是真的 —— 实测 **1,115 个词形有法语来源的词源**，页面上印着：
#        cao su ← Từ tiếng Pháp caoutchouc  ／ phim ← film  ／ ban ← balle
#    但那件事的家是**词源层**，而且早就收齐了，不欠账。
# ⚠️ 本节这批法语**不是那个东西**：fr 版维基词典本身是一部**越→法双语词典**，
#    它的 `examples` 一格里装的是「越南语搭配 ＋ 它的法语译文」：
#        Nắng to : il fait grand soleil.
#    这里的法语是**那一版的释义语言**，不是越南语里的法语借词。
#    ⇒ 与 ko 版那 1,655 条内嵌韩语译文**同一个形状**（`TRANSLATION_INSIDE_TEXT`）。
#
# ═══ 为什么它曾经是个「政策决定」，以及为什么已经不是 ═══
# 📋 W16 挂了两天没动，理由是「法语尾巴丢掉还是留着，要用户拍板」。
# 🔴🔴 而 2026-10-05 一量才发现**阶段 6e 已经花钱把法语尾巴也译成中文了**，
#    52 条里译出四种结果，两种是读者看得见的错：
#        ①两半都译 ⇒ **中文说两遍**        18  `大官：大人物，大人物。` `大树：一棵大树。`
#        ②尾巴没译 ⇒ **法语漏进中文列**     4  `网球：balle de tennis。`
#      🔴③头没译 ⇒ **越南语漏进中文列**     2  `Ang nước：水罐。`（方向反过来，更坏）
#        ④模型自己丢了尾巴（对的）           7  `制动鼓`
#    ⭐ 所以「要不要留」这个问题本身是过期的 —— **钱已经花在它身上了**，
#      而花出去的那一列正在印错东西。`[[frozen-is-not-an-excuse]]`。
#
# ═══ 判据：按版登记分隔符，**不写成形状判据** ═══
# 与 `TRANSLATION_INSIDE_TEXT` / `INLINE_EN_IN_TEXT` 同一条规矩，而这次**必须**如此：
# 🔴🔴 **`vi_mark_count` 分不开法语和越南语。** 我第一版拿「尾巴越南语音节率 < 0.34
#    且一个越南语标记都没有」当安全网，于是 26 条**法语尾巴被判成「尾巴也是越南语」**：
#        Vải to : toile grossière.      ← `grossière` 的 `è` 被算成越南语声调符
#        Để tang : prendre le deuil     ← `le`/`de` 都在越南语音节表里
#    文件里早写过荷兰语那一课（「与英语共用拉丁字母，字形上永远分不开」），
#    **法语更严重：它与越南语共用组合变音符本身。** ⇒ 安全网必须换掉。
#
# 真正管用的是两条**结构**安全网，它们刚好拦下我逐条读 54 条读出来的那两条：
#   ⓐ 尾巴**整段都是越南语音节** ⇒ 这是越南语引文不是外语释义
#        biển  `Một cái biển có ghi : " Nhà cho thuê "`（招牌上写着「房屋出租」）
#   ⓑ 切完之后**头部括号/引号不配对** ⇒ 冒号在括号里面，切了就残
#        mò    `Mò mò (redoublement : sens plus fort).` → `Mò mò (redoublement`
#      🔴 这与阶段 9b 刚写下的那一课同形：**一条截断的引文比一条读不懂的更坏，
#        因为它看起来是完整的**。
# ⚠️ 两条网各自只拦 1 条、合起来 2 条，**别的 52 条一条没动**（反向控制）。
# 🔴 什么会推翻：fr/nl 版换了分隔符，或别的版也开始这么挤
#    （查法：`probes/probe_stage6.py` 的按版分隔符普查）。
EDITION_GLOSS_SEP = {
    # fr 版：`越南语搭配 : 法语释义。` —— 空格冒号空格，46 条候选
    "fr-edition": (re.compile(r"\s+:\s+"), "fr"),
    # nl 版：`Hôm qua — gisteren.` —— em/en dash
    "nl-edition": (re.compile(r"\s+[—–]\s+"), "nl"),
    # en 版：`đốt mía ― internode of a sugarcane` —— U+2015 HORIZONTAL BAR
    # ⚠️ **只登记这一个分隔符，不登记冒号**。en 版的冒号是正常句读：
    #   `Tổng thống duy nhất chưa bao giờ lấy vợ: James Buchanan.`
    #   （唯一没结过婚的总统：James Buchanan.）整句都是越南语，切了就残。
    #   —— 这条是我第一版的误伤，**按版登记顺手把它排除掉了**，
    #   而形状判据（「冒号后面没有越南语音节」）会照样咬住它。
    "en-edition": (re.compile(r"\s+―\s+"), "en"),
}

# 释义语种在三语方针（中＋英＋越）之内 ⇒ 尾巴**搬进 `example_gloss`**；
# 之外 ⇒ 只从出版正文里摘掉，证据层 `example.text` 一个字不动（用户 2026-10-05 定）。
GLOSS_LANG_PUBLISHABLE = frozenset(("zh", "en", "vi"))

# 🔴 **全角那一族不是可选项。** 只写半角时 `轻飘飘――失重（字面意思` 被判成「配对」
#    ⇒ 安全网形同不存在。中文译文里括号引号**全是全角**，而这个函数两边都要用。
_BRACKET_PAIRS = (("(", ")"), ("«", "»"), ("[", "]"), ("“", "”"), ("‘", "’"),
                  ("（", "）"), ("「", "」"), ("『", "』"), ("〔", "〕"),
                  ("【", "】"), ("《", "》"), ("〈", "〉"))


def brackets_balanced(s):
    """括号/引号成对。切点落在括号里面时这个会是 False。

    🔴🔴 **两个方向都要用它，而我第一版只装了一个方向。**
       源头侧装上之后（`split_edition_gloss` 的安全网ⓑ），中文侧忘了装 ⇒
           `轻飘飘――失重（字面意思：“非常轻”）`  →  `轻飘飘――失重（字面意思`
       模型在括号**里面**又写了一个 `：`，我按它切就留下一个不配对的括号。
       ⭐ 这正是 `[[criteria-narrower-than-you-think]]` 的孪生形态：
         判据对了，**施用点漏了一个**。所以它必须是公开函数、两处都 import，
         而不是各自写一遍（`vi/fixes/fix_w16_edition_gloss.py` 用的就是这一个）。
    """
    for a, b in _BRACKET_PAIRS:
        if s.count(a) != s.count(b):
            return False
    return s.count('"') % 2 == 0 and s.count("'") % 2 == 0


def split_edition_gloss(text, word, src, syllables):
    """切开「越南语词条 ＋ 本版分隔符 ＋ 本版释义」。→ (出版正文, 释义, 释义语种)

    不该切时返回 `(text, None, None)` —— **调用方据第二项是不是 None 判断**，
    不许自己再比一次字符串（那就是第二份实现）。
    """
    t = (text or "").strip()
    reg = EDITION_GLOSS_SEP.get(src)
    if not reg or not t or "\n" in t:
        return t, None, None            # 多行例句不是这一族（这一族都是单行词条）
    sep, lang = reg
    if not sep.search(t):
        return t, None, None
    # 结构要求：头是越南语、**且词头出现在头里** ⇒ 这才是「词条:释义」而不是整句带冒号
    if not _mixed_vi_head(t, word, syllables):
        return t, None, None
    head, tail = sep.split(t, 1)
    if vi_syllable_rate(tail, syllables) >= 1.0:
        return t, None, None            # ⓐ 尾巴整段是越南语 ⇒ 引文，不是释义
    if not brackets_balanced(head):
        return t, None, None            # ⓑ 切点在括号里 ⇒ 切了就残
    return head.strip(), tail.strip(), lang


# ── ⑦ 同一格里跨版重复的例句（W24）──────────────────────────────────────
# 🔴🔴🔴 **这笔账我第一次报的数错了 3.8 倍，而且量的是另一件事。**
#    第一版按 `(word_id, text_pub)` 分组 ⇒ 1,569 组／多余 1,616 行／1,054 个词形。
#    但**展示层把带义项的例句印在各自的义项下面**、`sense_id IS NULL` 的印在末尾的
#    「例句」区 ⇒ 「同一个词形下文本相同」**不等于读者看见重复**。
#    按读者口径（分组键带 `sense_id`）重量：**417 组／多余 429 行／235 个词形**。
#    ⭐ `[[measure-landing-not-source]]`／「报数前先问这个数量的是哪件事」。
#
# ⚠️ 差额那 1,374 组**不是本节的事，而且去重会让它更糟**：同一句挂在两个**不同**
#    已出版义项上，而读那些义项一眼就看出是**同一个义项被两版各描述了一遍**：
#        qua   义项「幸存」[en 版]        ／ 义项「脱离死亡」[vi 版]
#        be    义项「撑开袋口以便装满」[en] ／ 义项「用手抬高斗口以量得更多」[vi]
#    ⇒ 根因在**义项层没有跨版合并**，例句重复只是症状。把例句去掉一条，
#      读者仍然看见两个几乎一样的义项，而其中一个变成**没有例句**（更糟）。
#      📋 单独记账（W25），不在本节处理。
#
# ═══ 归一到什么程度 ═══
# 精确匹配只逮到 211 组；加「压空白＋去首尾标点＋小写」到 417 组。
# 🔴 小写是有风险的一步（越南语专名靠大小写区分），所以**单独量了它**：
#    只靠小写才合并的 136 组，逐条读过 10 组全是源头自己写了两遍
#    （`có mùi thúi` / `Có mùi thúi.`；`Khổng Tử san kinh thi.` / `… Kinh Thi.`）。
#    唯一看着像专名的 `siêu nhân` / `Siêu Nhân` —— **同版、同义项、译文都是「超人」**
#    ⇒ 源头自己写了两遍，不是两个词。
#
# ═══ 留哪一行：五条优先级，每一条都量过它实际决定多少组 ═══
#    ① **没有源头 zh 译文的优先**（15＋6＝21 组决定）——源头侧的 zh 是**中文版白送的
#      繁体**（`開庭/審判`，681 条全部来自 `zh-edition-*`），而另一条带的是 6e 买的
#      简体。留错了就是把繁体留在页面上、把买来的简体删掉。
#    ② **有源头英译的优先**（11＋6 组决定）
#    ③ **有出处的优先**（5 组决定）—— 并且**出处还会被并到留下来那行**（见 ④）
#    ④ `EDITIONS` 登记顺序（371 组走到这里，它们每行都没有源头 gloss ⇒ 任选皆可，
#       要的只是**确定性**：不确定的话每次重跑隐藏的是不同的行）
#    ⑤ `src_ref` 字典序（纯兜底）
# ⚠️ **并，不是丢**：留下来那行缺出处时从被隐藏的行搬过来 ⇒ 源头给的信息一条不丢。
#    这件事必须在 `collect()` 里做，不能在修复脚本里 —— 否则外锚闸第③向
#    （键对上而内容不一样）会判红，而它会是对的（W16 刚栽过一次同形的）。
#
# 🔴 被隐藏那行的**付费中文译文会被删掉**（闸 X8：隐藏的不许带译文）。
#    这是可以接受的，理由必须写明：417 组的**每一行都有中文**，所以留下来那行
#    一定有一条有效译文；删掉的是**同一句话的另一种措辞**（197 组措辞完全相同，
#    220 组措辞不同但逐条读过都成立）。原文在答案文件 `all.jsonl` 里
#    （`[[answer-file-is-the-ledger]]`），重算得回来。
# 🔴 什么会推翻：读者口径的重复组数不再是 417（闸 X15 锁它），
#    或者出现「留下来那行没有中文」的组（闸 X16 查这个，期望 0）。
HIDDEN_DUP_IN_CELL = "duplicate-in-same-cell"

_DUP_STRIP = " .。!！?？:：;；,，、…　"
EDITION_RANK = {s: i for i, (s, _l) in enumerate(EDITIONS)}


def example_dup_key(text_pub):
    """同一格里「读者看作同一句」的归一键。→ 字符串

    ⚠️ **只归一「源头写法不一致」那几种差异**：空白、首尾标点、大小写。
       不碰内部标点、不去声调符（声调是辨义的 —— 剥声调会把 `má`/`mà` 并成一组）。
    """
    return re.sub(r"\s+", " ", (text_pub or "")).strip().strip(_DUP_STRIP).lower()


def dup_survivor_rank(gloss_lang, has_ref, src, src_ref):
    """重复组里**留哪一行**的排序键（越小越先留）。见 §⑦ 的五条优先级。

    ⚠️ 参数是**显式的四个事实**而不是一个行元组 —— 这样闸可以用同一个函数，
       而不必知道收割器的元组布局（那布局变过一次，W16 把 `pub` 挂在末位就是为此）。
    """
    return (1 if gloss_lang == "zh" else 0,    # ① 源头 zh ＝ 白送的繁体 ⇒ 最后留
            0 if gloss_lang == "en" else 1,    # ② 带源头英译的优先
            0 if has_ref else 1,               # ③ 带出处的优先
            EDITION_RANK.get(src, 99),         # ④ 登记顺序（确定性）
            src_ref or "")                     # ⑤ 兜底


def example_hidden_why(text, word, tags=(), syllables=None):
    """→ `hidden_why` 或 None（None ＝ 可出版）。

    ⚠️ `syllables` 省略时 **⑤c／⑤b 两条判据整个不参与** —— 它们需要越南语音节表。
       收割阶段（阶段 6）拿不到建好的 `dict`，所以那两条是**阶段 6e 开跑前**
       由 `vi/fixes/fix_example_defects.py` 补判的。
       🔴 这个「有条件生效」本身是个洞：收词变了之后新收的例句不会被重判。
          ⇒ 回归闸 R23/R24 锁住命中行数，收词一变就红。
    """
    t = (text or "").strip()
    if not t:
        return None                       # 空文本不入库，调用方跳过（不是隐藏）
    # 🔴🔴 **W20 必须判在这里，而不是由 `fixes/` 脚本去 UPDATE。** 2026-10-06。
    #    我第一版就是写了个 fix 脚本直接 `UPDATE example SET hidden=1` ——
    #    **外锚闸当场报「2 条键对上了而内容不一样」，而它是对的**：
    #    收割器 `collect()` 产不出这个 `hidden_why`，于是库不再是收割器的产物，
    #    而 `--rebuild`／`--sync` 会把它冲掉。
    #    ⭐ 这一跤项目里刚记过（6e 那轮）：**判据搬进收割器，不是搬进闸** ——
    #      搬进闸则 `--rebuild` 会把脏数据写回而闸照样绿。这次是搬进 fix 脚本，同一个洞。
    #    ⚠️ 排在最前：整条是 JS 残渣的行**不含越南语也不含汉字**，
    #      放在后面会被 `HIDDEN_NO_LATIN`／`HIDDEN_TOO_SHORT` 之类先抢走，
    #      那时页面上虽然也看不见它，**但原因是错的**（而原因是会被读的：X13 查值域、
    #      P33 按这个原因计数、以后清洗这一族的人按这个原因找行）。
    if is_js_residue(t):
        return HIDDEN_JS_RESIDUE
    if is_meta_not_example(t):
        return HIDDEN_META_NOT_EXAMPLE
    if not _has_quoc_ngu(t):
        return HIDDEN_NO_LATIN
    # 🔴 切掉韩语译文之后一个国语字字母都不剩 ⇒ 整条是韩语标签/关系数据，不是例句。
    #    ⚠️ 判据顺序要紧：放在 `_has_quoc_ngu` **之后** —— 否则喃字正文那批
    #      （1,208 条，有它们自己的原因 `nom-script-quotation`）会被这一条抢走。
    if not _has_quoc_ngu(strip_foreign_translation(t)):
        return HIDDEN_KO_LABEL
    if set(tags) & {"Traditional-Chinese", "Simplified-Chinese", "Pinyin"}:
        return HIDDEN_SRC_CHINESE
    if norm_vi(t.rstrip(".!?…：:；;")) == norm_vi(word or ""):
        return HIDDEN_SAME_AS_WORD
    if len(t) < 3:
        return HIDDEN_TOO_SHORT
    if syllables is not None:
        # ⚠️ 顺序要紧：⑤b-2「整条只有出处」要排在 ⑤c「不是越南语」**前面**。
        #    出处行本来就以英文为主（`Analects, 7.34; 1861 English translation by
        #    James Legge`）⇒ 两条都会命中，而「正文缺失」是更准确的那个原因。
        lines = [l.strip() for l in t.split("\n") if l.strip()]
        if len(lines) == 1 and is_citation_line(lines[0], syllables):
            return HIDDEN_CITATION_ONLY
        # 🔴🔴 **「不是越南语」必须判在切干净的正文上，不是判在原始块上。**
        #    2026-10-03 第一版判在原始块上，当场差点隐藏一条好例句：
        #        id=12702 `Xa-tan`
        #          行0 `Matthew 4:10; 2011 Vietnamese translation from KPA version; …`（出处）
        #          行1 `Xa-tan kia, xéo đi !`                                      ← 越南语正文**在**
        #          行2 `Away with you, Satan!`                                      （英译）
        #    越南语只有 5 个 token，被首行出处和末行英译的 token 压到音节率 0.2 以下
        #    ⇒ 整块判成「源头没给越南语」。**而它给了。**
        #    这是 `[[criteria-narrower-than-you-think]]` 的第 N 次：判据对的是「正文」，
        #    那就必须先有「正文」—— 把出处和英译切掉之后剩下的才是它。
        body = split_citation_prefix(t, syllables)[1]
        body = split_inline_english(body)[0]
        if not body.strip() or is_not_vietnamese(body, word, syllables):
            return HIDDEN_NO_VIETNAMESE
    return None


# ── 关系目标的**正字法判据**（欠账 W9 的落点）───────────────────────────────
# 🔴🔴 **2026-10-03 阶段 9 把关系渲染出来才看见的**：`nhà` 的「相关」里印着
#    `kościół`（波兰语「教堂」）。W9 记的正是这一类 ——
#    「整段标签/释义塞进 target」此前只在**含韩文/假名**的那批里量过（已丢 108 行），
#    而同样的污染出现在**纯拉丁文本**里时，`has_non_vietnamese_script` 一条都抓不到，
#    **而我当时没有量过它有多少**。
#
# 实测：出版层 143,625 行关系里 **2,238 行**的 target 含非国语字字母，
# 而它们的 `target_id` 解析得上的是 **0 行** —— 全部是死链。逐类读过：
#     1,690+ 行  en 版**字母条目**的 Unicode 变体（`o` 的 `Ø ø Ǿ ɵ ⱺ ᴏ Ｏ Ꜵ`、`s` 的 `ſ`）
#       某些行  **整段词源正文塞进 target**：`đâu. 3 From earlier *C-raː`  ← W9 描述的形状
#       某些行  带汉字表记的整串：`vô tuyến truyền hình [無線傳形`
#       31 行   ru/de/pl/fr 版的外语词（`kościół`）
#
# ⇒ 判据：**基字母（NFD 去掉组合符之后）不是 a–z 的，就不是国语字**。
#   🔴 **不手抄「越南语字母表」** —— `ă â ê ô ơ ư` 和全部带调元音都在扩展区，
#     手抄必然漏，而漏了就会把越南语自己的词判成外语（`[[criteria-narrower-than-you-think]]`）。
#     交给 Unicode 答：拆 NFD、丢组合符、看基字母。`đ` 是唯一需要显式放过的例外
#     （它的"横杠"不是组合符，是字母本身的一部分）。
# ⚠️ **用 `hidden` 不用丢**（照 B17 的先例）：万一哪天收词把其中某个词形收进来了，
#   一条 UPDATE 就能放出来；丢掉就只能重建整层。`[[prefer-reversible-designs]]`。
HIDDEN_TARGET_FOREIGN = "target-not-quoc-ngu"


def non_quoc_ngu_letters(t):
    """→ 这串里**不属于国语字**的字母集合（空集 ＝ 全是国语字）。"""
    bad = set()
    for ch in t or "":
        if not ch.isalpha() or ch in "\u0111\u0110":     # đ / Đ
            continue
        base = "".join(x for x in ud.normalize("NFD", ch) if not ud.combining(x))
        if not re.fullmatch(r"[A-Za-z]", base):
            bad.add(ch)
    return bad


# ══════════════════════════════════════════════════════════════════════════
# ⑤ 关系：源头字段名 → 我们的 kind。**值域就是这张表**，认不出的一律报红。
# 🔴 兜底不许静默吞 —— 与 `pron_sources.classify()` 同一条规矩：
#    源头哪天加一种关系，我们要当场知道，而不是把它归进 `related` 再也看不见。
KINDS = {
    "synonyms": "synonym", "antonyms": "antonym",
    "derived": "derived", "related": "related",
    "hypernyms": "hypernym", "hyponyms": "hyponym",
    "coordinate_terms": "coordinate",
    "meronyms": "meronym", "holonyms": "holonym",
    "descendants": "descendant", "proverbs": "proverb",
    # fr 版独有，17,637 条（它自己总关系量的 77.4%）。**语音关系**，见文件头第三条
    "paronyms": "paronym",
    # vi 版独有 29 条：越南语叠词（`lơ mơ`/`lơ thơ`）。量小但是 vi 的特色
    "reduplicatives": "reduplicative",
    "compounds": "compound", "abbreviations": "abbreviation",
    "instances": "instance", "phrases": "phrase",
    "expressions": "expression", "phraseology": "phraseology",
}

# 🔴 **兜底 `related` 只被「语义上更具体」的 kind 吞掉。**
#    有意排除 `paronym`（语音关系，不蕴含语义相关）与 `related` 自己。见文件头第二条。
SUBSUME = set(KINDS.values()) - {"related", "paronym"}
HIDDEN_REDUNDANT_RELATED = "redundant-related"   # B17


# 🔴🔴 第三类死链：**目标里混着假名/韩文字母** —— 106 行，全部 `target_id` 解析不到。
#    回源读过，三种东西混在一起：
#      `彼ら` / `オレンジブック`                       ← 日语词（ja 版的派生词，没标 lang_code）
#      `bất khả kháng lực 불가항력`                 ← **越南语词 ＋ 韩语释义拼在一个字段里**
#      `베트남 한자:` / `파생어: cá biệt (個別), …`    ← **整段标签/列表塞进了 target**
#    后两种与 ko 自己那条「关系目标塞整段释义 2,192 行」完全同形 ——
#    **源头的关系抽取在那一版上是坏的**，不是我们读错了。
# ⚠️ 判据交给 Unicode 的**字符名**答，不手抄码位区间
#    （vi 上「手抄区间」已经栽过两次，第二次是扩展 H 的喃字）。
_NON_VI_SCRIPTS = ("HIRAGANA", "KATAKANA", "HANGUL")


def has_non_vietnamese_script(s):
    """含假名/韩文字母 ⇒ 不可能是越南语词形（这两套文字在越南语里一个字都不出现）。"""
    for ch in s or "":
        try:
            if ud.name(ch).startswith(_NON_VI_SCRIPTS):
                return True
        except ValueError:
            continue
    return False


def relation_target(item):
    """关系项 → (目标词形, 丢弃原因 or None)。

    🔴 **目标不一定是国语字词形**：en 版汉字词头下的 `derived` 全是汉字
       （`馬 → 兵馬`，而真正的越南语词形躺在 `roman` 里：`binh mã`）。
       这些汉字词头我们有意不进 `dict`（用户 2026-09-28 的决定），
       所以这种目标必然是死链。实测 512 条（0.3%），其中 482 条连 `roman` 都没有。
    ⚠️ 这里**不替源头拿 `roman` 顶上** —— `roman` 是那个汉字词的越南语读音，
       不等于「这个词的 derived 是 binh mã」。跨一步就成了编造关系（es 的 3,890 个）。
    """
    t = (item.get("word") or "").strip()
    if not t:
        return None, "目标空"
    lc = item.get("lang_code")
    if lc and lc != "vi":
        return None, "目标是别的语言（lang_code=%s）" % lc
    return t, None


# ══════════════════════════════════════════════════════════════════════════
# ⑥ 录音：Lingua Libre 文件名里嵌着被录的词 —— 一把源头自带的尺子
_LL = re.compile(r"^lL-Q\d+ \([a-z]{3}\)-.*?-(.+)\.(wav|ogg|oga|mp3|flac|opus)$", re.I)
HIDDEN_WRONG_WORD = "filename-word-mismatch"


def _fold(s):
    """对照文件名与词形：折大小写 + NFC + 去空白/连字符。**不去声调**。

    ⚠️ 去声调会把 `sáo`（箫）和 `sáu`（六）之外的真错也一起抹平；
       这里要的恰恰是让声调差异留下来。
    """
    return re.sub(r"[\s\-–_]+", "", ud.normalize("NFC", (s or "")).strip().lower())


def filename_word(key):
    """Commons 归一键 → 文件名里嵌着的那个词；不是 Lingua Libre 命名则 None。

    实测 8,148 条录音里 7,839 条（96.2%）是这种命名 ⇒ 这把尺子覆盖面够。
    """
    m = _LL.match(key or "")
    return m.group(1) if m else None


def audio_hidden_why(word, key, variant_pairs):
    """→ `hidden_why` 或 None。

    `variant_pairs` ＝ 源头说「这两个词形是一回事」的无向对集合
    （`frozenset({norm_vi(a), norm_vi(b)})`）。**第二信号必须来自源头，
    不许是我算的**（第一版拿 IPA 交集当第二信号，把 3 条正字法异写判成了张冠李戴）。
    """
    fw = filename_word(key)
    if fw is None or _fold(fw) == _fold(word):
        return None
    if frozenset((norm_vi(fw), norm_vi(word))) in variant_pairs:
        return None                        # 源头说它们是一回事 ⇒ 同一条录音挂两个异写，对的
    return HIDDEN_WRONG_WORD


def variant_pair_key(a, b):
    return frozenset((norm_vi(a), norm_vi(b)))
