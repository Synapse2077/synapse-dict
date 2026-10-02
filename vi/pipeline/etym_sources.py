#!/usr/bin/env python3
"""**词源层的判据：哪些段是词源、以及 `etym_type` 怎么定** —— 只写一份。2026-10-02。

收割器、闸、探针都 import 这一份。
⚠️ §I 的 `bare_table` 判据原来住在 `vi/probes/probe_primary_source.py` 里，
   **而探针里还另有一份 `is_ideograph`（第三份，且是没有扩展 H 兜底的那版）** ——
   阶段 6 的 R19 刚因为「同一个谓词两份实现只修了一份」付过学费，
   所以这一层开工第一件事是把判据收到这里、`is_ideograph` 一律从 `criteria` 取。

═══ 🔴🔴 最该记的一条：**同一个形式判据，在两个地方意思相反** ═══
「整段都是表意文字」这个判据：

    用在**词头**上（`criteria.is_han_headword`）⇒ 它是汉字/喃字表记，**不收进 dict**
    用在**词源段**上                        ⇒ ❗它可能正是**用中文写的词源**，**最该收**

阶段 6 给 `is_han_headword` 加了「容许汉字圈标点」（为了 `四肢發達，頭腦簡單`）。
我一度想「为了一致」把同一条容许度搬到词源段上 —— **实测那会删掉 2,032 段真词源**：

    严格（表意＋空白）     命中    11 段   ← 对的，`𢆥 𣎃`、`金牛的汉越音`
    容许汉字圈标点         命中 2,043 段   ← **多出来的全是 `漢越詞，來自學習。`**

中文散文**由构造就是「表意文字＋全角标点」**，容许标点等于把所有中文词源判成垃圾。
而那 2,032 段是**中文读者唯一能直接读的词源**（阶段 7b 要花钱买的东西，这里白送）。
⇒ 本文件的 `_all_ideographs()` **有意是严格版**，且不许「为了与 criteria 一致」改宽。
  `[[criteria-narrower-than-you-think]]` 的镜像：**判据不是越窄越好，是要对准它在量的那件事。**

═══ 🔴 有意**不加**的判据：元描述正则 ═══
`paths.py` 当年记过「`的喃字` 是我漏掉的元描述写法」，所以我本想加一条
`(漢越音|越南語讀音|的喃字)` 的元描述判据。**量过之后不加**：命中 13 段，逐条读过，
其中 ≥10 段是**真词源只是顺带提到汉越音**：

    liếm → 繼承自原始越語 *-lɛːmʔ（舔），繼承自原始孟-高棉語…      ← 真词源
    nóc  → …源自上古漢語 脰（白-沙；**漢越音**：đậu）              ← 真词源
    Ma Kết → 摩羯的非汉越音（汉越音：Ma Yết）                    ← 偏元描述，但仍带信息

⇒ 13 段里只有 2–3 段偏元描述，而它们也告诉读者「这是 摩羯 的非汉越读法」。
  收益 3 条、代价 10 条 ⇒ **不加**。
  🔴 什么会推翻：若这个数涨到三位数，回去抽样重判。

═══ ⚠️ `etym_type` 的两处值域改动，都是量出来的 ═══
阶段 0 建表时注释写的值域是 `sino_vietnamese / native / borrowed / mixed / unknown`。

① **加 `compound`**：实测 **9,361 条** entry 只有构词模板（`com`/`af`/`compound`/
   `vi-etym-redup`）而**没有任何来源模板**。给它们写 `NULL` ⇒「源头没说」和
   「源头说了是复合词」长得一样（`[[dont-say-source-lacks-what-we-skipped]]`）。
   越南语词汇学本来就按 *từ thuần Việt / từ Hán-Việt / từ mượn / **từ ghép*** 分，
   `compound` 和另外三个同在一个轴上。
② **`unknown` 有意不用**：源头没给信号就是 `NULL`。留一个没人写的枚举值＝ B7 那种死条目。
   🔴 什么会推翻：若将来有源头**明说**「来源不明」，那时 `unknown` 才有内容。

═══ 🔴 `sino_vietnamese` 优先于 `borrowed`，这**不是**冲突 ═══
实测 1,836 条 entry 同时有 `vi-etym-sino` 与 `bor` —— 汉越词**本来就是从汉语借来的**，
两个模板说的是同一件事，更具体的那个才带信息。判成 `mixed` 是错的。
真冲突只有 `native+borrowed`(63) / `native+sino_vietnamese`(8) / 三者齐全(37) ＝ **108 条（0.6%）**
⇒ 单列 ＋ 一个 `mixed` 值装得下（`SCHEMA` §13.1 的「记录内多值率」判法）。

═══ ❌ 有意**不建** `etymology.origin_lang` 列 ═══
`bor`/`der`/`inh` 的 `args.2` 给出来源语，110 种（zh 1,854 ／ **mkh-vie-pro 原始越语 1,116**
／ fr 1,037 ／ en 505 ／ km 45 …），对中文读者比英文散文有用得多。**但它装不进一列**：

    恰好 1 种来源语  4,687（16.9%）
    0 种            22,293（80.3%）← `vi-etym-sino` 不带 lang 参数，来源隐含是汉语
    ≥2 种              793（ 2.9%）← 那是**词源链**不是单一来源（`neon` ＝ fr ← grc ← la-new）

写成单列 ⇒ 八成是空的、3% 是错的（把链的某一环当成唯一来源）。
🔴 **什么会推翻**：阶段 9 的展示层真要印「借自 X 语」这个徽标 ⇒ 那时它该是一张
  `etymology_origin(etymology_id, seq, lang_code)` 关系表，**不是一列**。
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from criteria import is_ideograph, is_not_a_gloss, norm_vi          # noqa: E402

# ── ① 字段名：**三版不一样，漏一个丢 42%** ────────────────────────────────
# en 版 `etymology_text`（**单数、字符串**）／vi·zh 版 `etymology_texts`（**复数、列表**）。
# 🔴 这是 vi 上第一次栽的那个坑（`paths.py` 文件头记着）：只扫单数 ⇒ 两版都得 0.0%。
ETYM_KEYS = ("etymology_text", "etymology_texts")

# ── ② 哪些版的词源**可出版**（`[[gloss-three-languages]]`：中+英+本语言）────
# 🔴 这是「我们有意不收」，不是「源头没有」。实测第四语言共 **3,622 段**：
#    fr 1,402 ／ ru 1,325 ／ ja 452 ／ ko 282 ／ de 71 ／ pl 36 ／ pt 33 ／ nl 21。
#    🔴 什么会推翻：方针从三语放宽，或决定花钱把它们译成中文。
ETYM_LANG = {
    "en-edition": "en", "vi-edition": "vi",
    "zh-edition-trad": "zh", "zh-edition-simp": "zh",
    "fr-edition": None, "ja-edition": None, "ko-edition": None,
    "pl-edition": None, "ru-edition": None, "nl-edition": None,
    "pt-edition": None, "de-edition": None,
}

# ── ③ 哪些段**压根不是词源**。每一条后面的数字是 2026-10-02 实测段数 ─────────
SKIP_EMPTY = "empty"
SKIP_MAGIC = "mediawiki-magic-word"      #   716  整段就是 `__NOEDITSECTION__`（vi 版）
                                         #        ⚠️ 另有 **5,390 段是内嵌**的，
                                         #        那些**清洗后保留**，不跳过
SKIP_BARE_TABLE = "bare-han-spelling"    # 21,239 `thư viện［書院］`（zh 版，归阶段 2）
SKIP_ALL_HAN = "all-ideographs"          #    11  `𢆥 𣎃` / `金牛的汉越音`
SKIP_SAME_AS_WORD = "same-as-headword"   # 1,247  整段就是该词本身（zh 版）
SKIP_TEMPLATE = "template-residue"       #     3  `{{{1}}}` / `:Template:vi-etym-lai。`
SKIP_TOO_SHORT = "too-short"             #   130  en 版 122 段整串是 `.`

# 🔴🔴 MediaWiki 魔术字**不只是整段出现，更多是内嵌在正文末尾**。
#    实测 vi 版 **5,390 段（它可出版段数的 64.7%）** 形如
#      `Âm Hán-Việt của chữ Hán 云云.\n__NOEDITSECTION__`
#    只判「整段是魔术字」只抓到 716 段（整段型），剩下 5,390 段会**原样印给读者**。
#    ⭐ 逮到它的不是形状检查，是 `dbtool.sample_check` 的抽样反验 ——
#      形状检查问的是「这一段该不该收」，而这一段**该收，只是脏**。
# ⇒ 判据分两步：**先清洗，再判断**。清洗完什么都不剩的才算整段型魔术字。
_MAGIC_ANY = re.compile(r"__[A-Z]+__")


def clean_etym_text(text):
    """出版用的词源正文：剥掉 MediaWiki 魔术字。

    ⚠️ 这是**我们的出版文本**与源头原文第一次不一致的地方，而词源层**没有证据层**
       （不像义项有 `sense_src`）。⇒ 靠 `src_ref` ＋ `src_field` 能从 dump 原地复原，
       别再在正文上做第二种清洗（`[[source-typo-fix-ours-not-quote]]` 的精神：
       改出版文本可以，但得说得出原文在哪、怎么复原）。
    """
    return _MAGIC_ANY.sub("", text or "").strip()
# `词形［漢字］` / `词形[漢字]`
_BRACKET = re.compile(r"^\s*(.+?)\s*[［\[]([^］\]]+)[］\]]\s*[。.]?\s*$")
MIN_LEN = 4


def _all_ideographs(s):
    """整串都是表意文字（**只容许空白，不容许标点**）。

    🔴 容许标点会把 `漢越詞，來自學習。` 这类**用中文写的真词源**判成垃圾（2,032 段）。
       见文件头第一条 —— 这个严格是有意的，不许为了与 `criteria.is_han_headword` 一致改宽。
    """
    t = (s or "").strip()
    return bool(t) and all(is_ideograph(c) or c.isspace() for c in t)


def is_bare_han_spelling(word, text):
    """这一段是不是 `词形［漢字］` 那张**汉字表记表**（归阶段 2，不是词源）。

    ⚠️ 头部与词形的比较走 `norm_vi`（NFC+小写，不去声调）。
       🔴 原来的判据是**大小写敏感**的逐字符比，漏掉 84 段 ——
         `tiếng Việt［㗂越］` 的头部写的是 `tiếng việt`（小写 v）。
    """
    m = _BRACKET.match((text or "").strip())
    return bool(m) and norm_vi(m.group(1)) == norm_vi(word or "") \
        and _all_ideographs(m.group(2))


def etym_skip_why(word, text):
    """→ 跳过原因 或 None（None ＝ 是一段可出版的词源散文）。

    ⚠️ **顺序有意义**：① 先清洗（内嵌魔术字），② 裸表记要在「整段只是汉字」之前判
       （否则 `thư viện［書院］` 会被归到后者而丢掉「它是表记」这个信息）。
    ⚠️ 传进来的是**源头原文**，本函数内部清洗；调用方存库时要存
       `clean_etym_text(原文)`，两边必须是同一次清洗。
    """
    raw = (text or "").strip()
    if not raw:
        return SKIP_EMPTY
    # 🔴 **先清洗再判断**：`__NOEDITSECTION__` 大多是内嵌的，清洗完还剩真词源
    t = clean_etym_text(raw)
    if not t:
        return SKIP_MAGIC            # 整段（剥掉魔术字后）什么都不剩，716 段
    if is_bare_han_spelling(word, t):
        return SKIP_BARE_TABLE
    if _all_ideographs(t):
        return SKIP_ALL_HAN
    if norm_vi(t.rstrip(".。！!？?")) == norm_vi(word or ""):
        return SKIP_SAME_AS_WORD
    if is_not_a_gloss(t):
        return SKIP_TEMPLATE
    if len(t) < MIN_LEN:
        return SKIP_TOO_SHORT
    return None


SKIP_DOMAIN = (SKIP_EMPTY, SKIP_MAGIC, SKIP_BARE_TABLE, SKIP_ALL_HAN,
               SKIP_SAME_AS_WORD, SKIP_TEMPLATE, SKIP_TOO_SHORT)


# ── ④ `etym_type`：**只认 en 版的 `etymology_templates`** ───────────────
# 🔴 vi 版与 zh 版**都没有 `etymology_templates`**（实测 0 条，只有 `etymology_links`）
#    ⇒ 只由 vi/zh 版建 entry 的那批拿不到 `etym_type`，写 NULL。
#    那是「源头没给结构化信号」，不是「来源不明」。
ORIGIN_TEMPLATES = {
    # 汉越词：源头有专门的模板，`args.1` 就是汉字（14,060 条）
    "vi-etym-sino": "sino_vietnamese",
    # 借词。`der`（派生自某语言）比 `bor` 弱，但同样是「来自外语」
    "bor": "borrowed", "bor+": "borrowed", "der": "borrowed", "der+": "borrowed",
    "cal": "borrowed", "calque": "borrowed",
    # ⚠️ 下面这一批是 `unknown_templates()` 报出来之后**逐个读 expansion 定的**，
    #    不是按名字猜的。每条都确认过它的展开文本真的在说「来自某外语」：
    "borrowed": "borrowed", "derived": "borrowed",
    "obor": "borrowed",                 # Orthographic borrowing from English NASA
    "ubor": "borrowed",                 # Unadapted borrowing from English crush
    "lbor": "borrowed",                 # Learned borrowing from Latin Colossae
    "abor": "borrowed",                 # Adapted borrowing of Chinese 社會科學
    "unadapted borrowing": "borrowed", "orthographic borrowing": "borrowed",
    "adapted borrowing": "borrowed",    # `abor` 的全名写法（1 条）
    "zh-etym-short": "borrowed",        # 汉语缩略式（1 条）—— 展开说的是「来自汉语某词的缩略」
    "semantic loan": "borrowed",        # semantic loan from English star
    "pseudo-loan": "borrowed",          # Pseudo-anglicism, derived from snack
    "clq": "borrowed", "pcal": "borrowed", "partial calque": "borrowed",
    "dercat": "borrowed",               # 列的是词源链：cà phê ← fr ← it ← ota ← ar
    # 承自（原始越语 / 原始孟-高棉语）＝ 本族词
    "inh": "native", "inh+": "native",
}
# 构词模板：说的是**怎么构成的**，不是**哪来的**
FORMATION_TEMPLATES = {
    "com", "com+", "compound", "af", "affix", "prefix", "suffix",
    "vi-etym-redup", "blend", "doublet", "Han compound",
    # ⚠️ 三个 vi 专有的**内部构词**模板，也是读 expansion 定的 ——
    #    名字里带 `etym` 很容易被当成来源模板，而它们说的都是越南语自己的构词法：
    "vi-etym-lredup",   # `lẩm bẩm` ＝ l- reduplication of `bẩm`（l- 头叠词）
    "vi-etym-hoi",      # `ảnh` ＝ 给词根 `anh` 加问声构成的远指形（南方方言构词）
    "vi-etym-lai",      # `bật mí` ＝ 由 `bí mật` 经 nói lái（音节互换）生成
}
# 🔴🔴 **`cog`/`ncog` 是「同源词对照」，不是来源声明** —— 4,013+633 条。
#    把它读成「借自那个语言」＝ 把「比较一下」当成「来自」。
#    这里列出来是为了**让它显式地不参与判定**，而不是靠「没写进上面两张表」默默排除。
NOT_ORIGIN_TEMPLATES = {
    "cog", "ncog",                                   # 同源词对照
    "categorize", "etymid", "yesno", "glossary",     # 分类/锚点/开关
    "IPAfont", "m-g", "l", "mention", "vi-l", "zh-l", "ltc-l", "och-l",
    "l/vi/Latn", "liushu",                           # 排版与链接
    "chemical element box",                          # 化学元素框，纯排版（args 只有 `1: vi`）
    # ⚠️ `etymon`（21 条）**有意不解析**：它是个通用壳，真正的关系藏在
    #    `args.2`（实测取值形如 `:bor`）而不是模板名里。为它单开一条解析路径
    #    就是第二套判据，而收益是 21 条。⇒ 这 21 条的 `etym_type` 由同条词源的
    #    其他模板决定，决定不了就 NULL。
    #    🔴 什么会推翻：这个数涨到三位数，或发现 `args.2` 里出现 `:inh` 这类
    #      会把词判成**相反方向**的值（那时「不解析」就不只是少收，而是会判错）。
    "etymon",
}

ETYM_TYPE_DOMAIN = ("sino_vietnamese", "borrowed", "native", "mixed", "compound")
# 真冲突（两个不同轴上的来源同时出现）才算 mixed
_CONFLICT = ({"native", "borrowed"}, {"native", "sino_vietnamese"})


def etym_type_of(template_names):
    """→ `etym_type` 或 None（None ＝ 源头没给结构化信号）。

    判定顺序本身就是判据：
      ① 真冲突（native 同时撞上 borrowed/sino）⇒ `mixed`（实测 108 条，0.6%）
      ② `sino_vietnamese` 优先于 `borrowed` —— 汉越词本来就是从汉语借的，
         1,836 条两者同时出现**不是冲突**，更具体的那个才带信息
      ③ 只有构词模板 ⇒ `compound`（9,361 条）
      ④ 什么都没有 ⇒ None
    """
    names = set(template_names or ())
    org = {ORIGIN_TEMPLATES[n] for n in names if n in ORIGIN_TEMPLATES}
    if any(c <= org for c in _CONFLICT):
        return "mixed"
    if "sino_vietnamese" in org:
        return "sino_vietnamese"
    if "borrowed" in org:
        return "borrowed"
    if "native" in org:
        return "native"
    if names & FORMATION_TEMPLATES:
        return "compound"
    return None


def unknown_templates(template_names):
    """源头有哪些模板名**三张表都没列** —— 调用方据此报红，不许静默忽略。

    🔴 与 `pron_sources.classify()` 的 `unknown-value` 同一条规矩：源头加了新模板，
       我们要当场知道。实测 166 种模板名，这三张表覆盖的是**参与判定的那些**。
    ⚠️ 这里只对**可能表达来源**的模板报警（名字里带 `bor`/`inh`/`der`/`etym`），
       排版类模板源头爱加几个都与我们无关；判据写宽了会天天报假警。
    """
    hint = re.compile(r"(bor|inh|der|etym|cal|clq|loan)", re.I)
    known = set(ORIGIN_TEMPLATES) | FORMATION_TEMPLATES | NOT_ORIGIN_TEMPLATES
    return {n for n in (template_names or ()) if n and n not in known and hint.search(n)}
