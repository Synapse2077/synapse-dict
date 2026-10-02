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


def example_hidden_why(text, word, tags=()):
    """→ `hidden_why` 或 None（None ＝ 可出版）。"""
    t = (text or "").strip()
    if not t:
        return None                       # 空文本不入库，调用方跳过（不是隐藏）
    if not _has_quoc_ngu(t):
        return HIDDEN_NO_LATIN
    if set(tags) & {"Traditional-Chinese", "Simplified-Chinese", "Pinyin"}:
        return HIDDEN_SRC_CHINESE
    if norm_vi(t.rstrip(".!?…：:；;")) == norm_vi(word or ""):
        return HIDDEN_SAME_AS_WORD
    if len(t) < 3:
        return HIDDEN_TOO_SHORT
    return None


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
