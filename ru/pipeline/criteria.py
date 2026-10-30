#!/usr/bin/env python3
"""俄语判据 —— **唯一的家**。2026-10-07（阶段 -1）。

═══ 🔴🔴🔴 为什么这个文件在阶段 -1 就存在 ═══
vi 那门的结论是「**判据一律 import 不重写**」，而它是栽了很多次之后才立的：
  · ko 的 K24：我自写「不全是汉字就算真释义」，zh 版报 **173,887** 条而真值是 **6**；
  · vi 的 R19/S6：闸自己手写一版 SQL 近似判据，**同时更宽又更窄**；
  · vi 的阶段 6：**同一个谓词两份实现只修了一份** ⇒ 155 个汉字词头躺在 dict 里，
    而骨架闸明写这条却报 0（**断言和被断言的用同一个坏判据 ⇒ 双方一致报全绿**）；
  · vi 的阶段 8：⭐「哪些行才真的落库」**也是判据**，条件写成字面量埋在 `main()` 里
    ⇒ 闸重写一遍报 458 条假缺。

⇒ 所以这个文件在**第一个探针写出第二份实现的那一刻**就建了（今天两个探针都在
  各写一份 IPA 定界符判据）。它现在只有三条，但位置是对的。

⚠️ 规矩：
  ① 任何「这条数据算不算 X」的问题，实现只许在这里出现一次；
  ② 探针 / 收割器 / 闸都 `from pipeline import criteria` 取用，**不许各写一版**；
  ③ 判据变了，**连带把它的版本号改掉**（落库时存 `rule_ver`），翻案时才找得到是哪一批。
"""
import re
import unicodedata as ud

RULE_VER = "ru-crit-19"           # 判据版本。改判据必须同时改它（ko 的 W1 教训）
#   v1 → v2（2026-10-07 同日）：`zh_gloss_kind` 从「按整条」改成**按行**判。
#   v2 → v3（同日）：再从「按行」改成**按行内分段**判。
#   🔴 同一条判据一天内三版，而**每一版都是抽样人读推翻的，不是想出来的**：
#        v1 的 meta 桶里 6/16 条粘着真释义（多行，真释义在前几行）
#        v2 的 meta 桶里 1/12 条粘着真释义（**同一行**，真释义在前几个逗号段）
#      ⇒ 我自己写的推翻条件是「meta 桶污染 > 5% 即作废」，v2 的 8% 触发了它。
#      ⚠️ vi 那门同一个位置是「判据三次收窄才对」、另一处「一天内收窄四次」——
#        **这不是失误率，是这类判据的正常形状**：源头把一整条纸质词典抄进了一个字段，
#        而「哪一截是释义」只有人眼能划线。⇒ 预算要按「三版」排，不是按「一版」排。
#   v3 → v4（同日，阶段 1）：加 ④ `pos` 归一与 `entry_type` 分类、屈折形判据、
#        四个落列语法字段的提取、`etym_no` 强转。**值域是实测的 34 种，不是猜的。**
#   v4 → v5（2026-10-08，阶段 2）：加 ⑥「哪些行会落成 entry ＋ `src_ref` 怎么拼」。
#        ⚠️ **这一版没有改任何一条判据的意思，只是把已有的那份搬了家**
#        （原先以字面量写在 `build.py` 的 `collect()` 里）。号照样要进 ——
#        否则「版本号没动」会被读成「这个文件没动过」。
#        🔴 改完必须验「建库结果一个字不差」，见 §九。
#   v5 → v6（同日，阶段 2 的闸逮到两条）：加 ⑦ 重音层判据，并在它的出口上
#        ① 把落库值统一成**组合式**重音符（预组合的 `ѐ` 让 `norm_ru` 剥不掉）；
#        ② **拒掉一点重音信息都没有的**（`с'езд → с’езд` 只差撇号写法）。
#   v8 → v9（2026-10-23，阶段 3 收尾）：`is_inflected_form` 加第四条路 ——
#        **形动词／副动词页**（词级 tags 含 participle/gerund ＋ 每个义项都带变形信号）。
#        62,576 个词形 `is_lemma` 1→0。⚠️ 这一改动**改变一切按词元算的覆盖率的分母**
#        （重音 T10、屈折 I10 的基线都要先解释差额再重锁）。见 RU_PLAN §十。
#   v9 → v10（同日，阶段 4 探针）：`is_inflected_form` 加第五条路 —— **词级 tags 含 form-of**
#        （fr 版姓氏变格形 133,870 条）。132,938 个词形 is_lemma 1→0。见 RU_PLAN §十一。
#   v10 → v11（同日，阶段 4）：加 ⑨ 音标层判据（拆格／归属／能不能印）。
#   v11 → v12（同日）：R6 补完整 —— 撇号不只在开头（fr 498／pl 231 行在词中间）＋ ASCII g/: 。
#   v12 → v13（同日，阶段 5a）：加 ⑩ 义项层判据（指针／出版文本／标签分桶／藏不藏）。
#   v13 → v14（同日，5b 开跑前量待译列）：ru 释义「只有语体/领域标签」⇒ 藏（198 条）。
#   v14 → v15（同日，5b 切片照出来）：`is_inflected_form` 第六条路 —— 副动词页（词级 gerund ＋ 分类）。
#   v17 → v18（2026-10-25，R29）：加 ⑮ 中文出版正文 `zh_simp`（安全的繁→简）。
#   v18 → v19（2026-10-26，5c 回收逮到）：`zh_simp` 否决 `慰藉/狼藉/枕藉`（前一个字决定）；R24 `example_split_citation`。

STRESS = "́"                # COMBINING ACUTE ACCENT


# ══════════════════════════════════════════════════════════════════════════
# ① IPA 的定界符 —— **一个集合，不是一个字符**
# ══════════════════════════════════════════════════════════════════════════
# 🔴🔴 阶段 -1 实测，七份源用了**四种**写法：
#       en  [sɐˈbakə]      方括号  456,669
#       ru  [jɵ]           方括号  442,630
#       fr  \vɐ.ˈda\       **反斜杠** 19,826  ← 第一版判据只认 `[` 和 `/`
#       pl  ˈknʲiɡə        真裸     3,237
#    `RU_PLAN` §0.2④ 写的是「ru 版用方括号不是斜杠，**而别的版剥的是 `/`**」——
#    后半句**是错的**：en 版也用方括号（456,669 / 456,697）。方括号不是 ru 版的
#    特性，是**俄语自己的惯例**（俄语音标按惯例写音素实现 [..] 而不是音位 /../）。
# 🔴 而第一版判据的代价不是「少剥一种」，是**19,826 行被塞进了「裸」这个残差桶**
#    （`[[residual-bucket-is-not-evidence]]`：「其他」桶是残差不是度量）。
#    ⇒ 判据按**枚举**写，并且把**认不出的那种原样返回** `"其他"`，让它自己显形。
_DELIMS = {
    "[": ("]", "[]"),
    "/": ("/", "//"),
    "\\": ("\\", "\\\\"),
    "(": (")", "()"),
}


# 成对定界符的名字集合 —— `strip_ipa_delims` 只许剥这几种（白名单，见那里的注释）
_DELIM_NAMES = frozenset(name for _close, name in _DELIMS.values())


def ipa_delimiter(ip):
    """→ 这条 IPA 用的定界符种类：`[]` / `//` / `\\\\` / `()` / `裸` / `其他`。

    🔴 「裸」和「其他」**分开**：前者是「确实没有定界符」（pl 版的惯例），
       后者是「开头那个字符我不认识」—— 混成一个桶，下一种写法出现时就看不见了。
    """
    t = (ip or "").strip()
    if not t:
        return "空"
    c = t[0]
    if c in _DELIMS:
        close, name = _DELIMS[c]
        return name if t.endswith(close) and len(t) > 1 else "其他"
    # 🔴🔴 **ASCII 撇号当重音符用** —— 判据收窄之后才显形的第三件事（欠账 R6）。
    #    pl 版 91 条 ＋ ru 版 1 条写 `'pulʲə`，而正确的是 IPA 的 `ˈ`（U+02C8）。
    #    ⚠️ **不能把 `'` 并进「裸」** —— 那它就重新沉回一个大桶里看不见了，
    #      而它**是个要修的缺陷**（`[[residual-bucket-is-not-evidence]]`：
    #      桶合并一次，缺陷就隐身一次）。单独一个标签，让它每次都被数到。
    if c in "'\u2018\u2019\u00b4":
        return "裸-ASCII撇号"
    # 开头是音标字符（字母/长度符/重音符）⇒ 真裸。
    # ⭐ **连字符也算**：词缀条目的音标正当地以 `-` 开头（pl 版 `-ка → -kə`）——
    #   这是把「其他」桶追到 0 的最后一条，而**追到 0 才知道它是正当的不是缺陷**
    #   （残差桶留着一条不问，下一种写法混进去就看不见了）。
    return "裸" if (c.isalpha() or c in "ˈˌː̥-\u2010\u2011") else "其他"


# 源头把 ASCII 撇号当 IPA 重音符用（见上）。入库前统一成 `ˈ`。
_STRESS_MARK_FIX = {"'": "ˈ", "\u2018": "ˈ", "\u2019": "ˈ", "\u00b4": "ˈ"}


def normalize_ipa(ip):
    """入库用的音标：剥定界符 ＋ **键盘字符顶替 IPA 字符**的三种（R6，逐个列）。

    🔴 **只换判得清的，逐个列**（与 `norm_ru` 同一条纪律）：
       「顺手把所有看起来像重音的符号都换掉」会动到 `ˌ`（次重音）、`ʼ`（喉塞音，
       在别的语言里是**音位**不是重音）。俄语上用不到喉塞音，但这个函数会被拷走。
    🔴🔴 **R6 第一版只修了一半**（2026-10-23 阶段 4 写库后量出来的）：它只换**开头**的撇号，
       而 fr 498 ／ pl 231 行的撇号在**词中间**（`pɐ.'bʲil`、`gur'man`）—— 那是主重音符，
       只是位置不在开头。⇒ 三条：
       ① 撇号类：一格里**恰好一个**且没有 `ˈ` ⇒ 换成 `ˈ`；多个或与 `ˈ` 并存 ⇒ **原样返回**，
          由 `pronunciation_parts` 拒收（`pərf'ʊm'ɪrəvən:ɨɪ̯'` 判不出哪个是什么）
       ② ASCII `g` ⇒ `ɡ`（U+0261）：IPA 手册承认二者等价，`g` 在 IPA 里没有别的意思（fr 60／pl 159）
       ③ ASCII `:` 后面紧跟非空白 ⇒ `ː`（`ˈto:məs`、`(:)`）；后面是空格的**是标点**
          （谚语 `rɐˈvna: ɪˈɡralʲɪ`）不动
    """
    out = strip_ipa_delims(ip)
    n = sum(out.count(a) for a in _STRESS_MARK_FIX)
    if n == 1 and "ˈ" not in out:
        for a, b in _STRESS_MARK_FIX.items():
            out = out.replace(a, b)
    out = out.replace("g", "ɡ")
    out = re.sub(r":(?=\S)", "ː", out)
    return out


def has_stray_apostrophe(ip):
    """`normalize_ipa` 之后还剩撇号 ⇒ 用法判不出（见上 ①）。"""
    return any(a in (ip or "") for a in _STRESS_MARK_FIX)


def strip_ipa_delims(ip):
    """裸存：剥掉定界符。`[[ipa-bare-storage-convention]]`（六语种统一裸存，展示层加 `/.../`）。

    🔴 认不出定界符时**原样返回**，不猜、不切。错比缺更伤权威 ——
       切错一个音标比留一个带括号的更坏，后者看一眼就发现，前者看不出来。
    """
    t = (ip or "").strip()
    kind = ipa_delimiter(t)
    # 🔴🔴 **白名单，不是黑名单。** 这一行第一版写的是
    #      `if kind in ("裸", "其他", "空"): return t` 然后 `return t[1:-1]`
    #    —— 也就是「**不在这三种里就剥首尾**」。当天给 `ipa_delimiter` 加了第四个
    #    返回值 `裸-ASCII撇号` 之后，它立刻把 `'pulʲə` 剥成了 `pulʲ`（**首尾各吃一个字符**）。
    #    ⚠️ 这与本文件 ② 的 `_STRIP_MARKS` 是**同一条纪律，而我两小时前刚写下它**：
    #      「黑名单会默认删掉下一个没想到的东西，白名单会默认留着它」
    #      （`[[dont-gate-facts-on-my-uncertainty]]`）。⇒ 只对**明确是成对定界符**的那几种动刀。
    if kind in _DELIM_NAMES:
        return t[1:-1].strip()
    return t


# ══════════════════════════════════════════════════════════════════════════
# ② 重音符 —— **它在俄语里是正字，不是装饰**
# ══════════════════════════════════════════════════════════════════════════
# 🔴🔴🔴 这是 ru 与 vi **方向相反**的那一条。归一只许去 U+0301/U+0300，
#    绝不许走「NFD 之后去掉所有组合符」（那会把 й→и、ё→е）。
#    实现与 import 时的自检在 `ru/dbtool.py`（`norm_ru` / `_norm_selfcheck`）。
# ⚠️ **本文件不复制一份 `norm_ru`** —— 那正是上面 ⚠️② 要禁的事。
#    要归一就 `import dbtool`。
def has_stress(s):
    """这串里有没有重音符。原语。"""
    return STRESS in (s or "")


def stress_position(s):
    """重音落在第几个元音上（0 起，没有则 None）。**原语，不是判据。**

    ⚠️ 判据按**含义**写：读者要的是「这个词重音在哪个音节」，而「第几个元音」
       只是它的一个可计算代理。**代理会被优化**（`[[proxy-metric-gets-optimized]]`）——
       这个函数只许用来**比较两个拼写是否同一个重音位置**，不许直接印给读者。
    """
    t = ud.normalize("NFC", s or "")
    n = 0
    for i, c in enumerate(t):
        if c.lower() in "аеёиоуыэюя":
            if i + 1 < len(t) and t[i + 1] == STRESS:
                return n
            n += 1
    return None


# ══════════════════════════════════════════════════════════════════════════
# ③ 中文释义「是不是真释义」—— 🔴 **第一版，已知是下界**
# ══════════════════════════════════════════════════════════════════════════
# ko 的 **K24**：zh 版「白送中文释义 206,091 条」里 **97.2% 是元描述**，
# 中文覆盖率从 74% 掉到 2.11%。而我量它时**第一版判据又太宽**
# （自写「不全是汉字就算真释义」，报 173,887 而真值 6）。
#
# ⭐ **俄语上这件事比 ko/vi 容易，因为元描述有一个强信号：它带西里尔字母。**
#    元描述必须点名那个俄语词元，所以一定含西里尔：
#        авиа         → `авиапо́чта (aviapóčta)的縮寫`      ← 元描述
#        его          → `он (on) 的賓格：他`                ← 元描述**夹着真释义**
#        оно          → `о́ный (ónyj) 的短中性單數`          ← 纯元描述
#        абсолютистский → `〔形〕абсолюти́зм的`              ← 纯元描述（截断的）
#        завод        → `工厂`                              ← 真释义
#        авиасекстант → `航空六分儀`                         ← 真释义
#    ⚠️ **但「带西里尔」不等于「是元描述」**，反例就在上面第二条：
#      `он (on) 的賓格：他` 的冒号后面是真释义。⇒ 判据必须**分三类，不是两类**。
#
# 🔴 **已知的不足，写下来而不是假装没有**：
#   · 本判据只看文本形式，不回源 —— ko 的 K24 真正的判法是**拿另一版的汉字表记去对**；
#     俄语没有汉字表记这一说，所以这条路不存在，只能靠形式 ＋ 抽样人读。
#   · 「纯中文但其实是元描述」的情形（如 `的短中性單數` 前面的词被省略了）本判据看不见。
#   · 阶段 5 必须**抽样人读**一遍再定稿（vi 的教训：抽样反验逮到形状检查看不见的一类）。
#
# 🔴 **`has_cyrillic` 不在这个文件里重新实现** —— 它的家在 `dbtool.py`
#    （那里还挂着 `norm_ru` 的 import 时自检）。见文件头 ⚠️②：
#    「同一个谓词两份实现只修了一份」是 vi 阶段 6 的原形 ——
#    155 个汉字词头躺在 dict 里，而骨架闸明写这条却报 0。
# ⚠️ 在**模块级**导入，不在函数里 —— 函数里 `sys.path.insert` + `import`
#   会在每次调用时重做一遍，20 万次调用就是 20 万次 path 查找。
import sys as _sys                                               # noqa: E402
from pathlib import Path as _Path                                # noqa: E402

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
import dbtool as _dbtool                                         # noqa: E402

has_cyrillic = _dbtool.has_cyrillic
norm_ru = _dbtool.norm_ru
fold_ru = _dbtool.fold_ru          # R30：ё 召回键（不是身份键，见 dbtool）
strip_stress = _dbtool.strip_stress      # 2026-10-07 补：探针要用它，而它的家在 dbtool

_META_TAIL = re.compile(
    # 「X 的 <语法范畴>」：元描述的主干。**列举语法范畴，不写 `的.*`** ——
    # 后者会把 `航空六分儀的一種` 这类真释义也吃掉（判据比它要描述的东西更宽）。
    # ⚠️ `的` 与语法范畴之间**允许夹一小段修饰**（≤6 字）：
    #    `的第三人稱單數現在時直陳式非完整體` —— 范畴在中间，紧跟 `的` 的是 `第三人稱`。
    #    不留这个口子，俄语动词那一大批变位元描述全部漏成 mixed。
    #    ⇒ 上限写 6 而不是不限：不限会让 `的` 和一个远处的范畴词配上对，
    #      把真释义判成元描述（**那一侧的代价是多花翻译钱，仍然比印错给读者轻**）。
    r"的[^。．.\n]{0,6}?(?:縮寫|缩写|簡稱|简称|縮略形式|缩略形式|另一種寫法|另一种写法|"
    r"複數|复数|單數|单数|形容词|形容詞|"
    r"賓格|宾格|主格|屬格|属格|與格|与格|工具格|前置格|呼格|"
    r"陰性|阴性|陽性|阳性|中性|陰性等價詞|阴性等价词|比較級|比较级|最高級|最高级|"
    r"短尾|短形|指小|指小詞|指小词|指小形式|愛稱|爱称|貶義詞|贬义词|屈折|"
    r"現在時|现在时|過去時|过去时|將來時|将来时|命令式|不定式|副動詞|副动词|"
    r"主動形動詞|主动形动词|被動形動詞|被动形动词|形動詞|形动词|分詞|分词|"
    r"被動態|被动态|被动形|被動形|完成體|完成体|未完成體|未完成体|變格|变格|變位|变位|"
    r"異體|异体|舊寫法|旧写法)"
    # ⚠️ 允许后面再跟一小段补充（`的賓格：他` / `的屈折：`），但**不许跟一整句**
    #    —— 跟一整句的是「元描述 ＋ 真释义」，那是 mixed 不是 meta。
    r"[\s　]*[：:，,。．.、]?[^。．.\n]{0,10}$")
# 词典标记：〔形〕〈口〉(单…) ⑴⑵ ～ 之类。**它们不是释义，但它们的存在不说明没有释义。**
_MARKUP = re.compile(r"[〔〈\[(（][^〕〉\])）\n]{0,24}[〕〉\])）]|[⑴-⒇①-⑳~～‖]")
# 整行去掉标记与非汉字之后啥也不剩 ⇒ 这一行没有中文实义
_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]|[\U00020000-\U0003ffff]")


# 🔴🔴 **分段必须按括号深度走，不能直接 `re.split`。** v3 的第一刀就栽在这儿：
#       `автоно́мный (avtonómnyj，“自治的”)的縮寫`
#    括号里**自带一个逗号**，`re.split(r"[，,、；;]")` 把它劈成
#       `автоно́мный (avtonómnyj`  ／  `“自治的”)的縮寫`
#    后半截看起来是「纯中文、没有西里尔」⇒ 判成 real ⇒ **把一条元描述印给读者**。
# ⚠️ 这与 vi 那门「同一天三条判据栽在**正则在空白处停下**」是同一族：
#    **分隔符在结构里有歧义时，正则不够，要带状态扫一遍。**
_OPEN = "〔〈（(「【“《["
_CLOSE = "〕〉）)」】”》]"
_SEP = "，,、；;"


def _split_segments(line):
    """把一行按 `，、；` 切段，**括号/引号内部的分隔符不切**。"""
    out, buf, depth = [], [], 0
    for c in line or "":
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth = max(depth - 1, 0)
        if c in _SEP and depth == 0:
            out.append("".join(buf))
            buf = []
            continue
        buf.append(c)
    out.append("".join(buf))
    return [s for s in out if s.strip()]


def _line_kind(line):
    """**单行**的分类。→ `real` / `mixed` / `meta` / `empty`

    🔴🔴 **第二版（2026-10-07 同日）：判据从「按整条」改成「按行」。**
    第一版把 zh-s 的 34,410 条判成 `meta`，而抽样人读当场看见里面粘着真释义：

        аммиачный  →  氨的 ⏎ 铵的 ⏎ 〔形〕аммиа́к的.
        агрегатный →  附件的 ⏎ 部件的 ⏎ 聚合的 ⏎ … ⏎ 〔形〕агрега́т的.
        античность →  古代 ⏎ 古老 ⏎ … ⏎ 〔阴〕⑴见анти́чный.⑵古希腊、罗马的社会及其文化.

    **前面几行是真释义，只有最后一行是元描述** —— 而中文版把一整条俄汉词典抄进了
    一个 gloss 里（多行、带变位词尾 `-жусь, -жишься`、带〔未〕〈口〉标记、带「见X」交叉引用）。
    判据按整条判 ⇒ 最后一行把前面全判死了。
    ⭐ 这就是 ko 的那一课的原形：**「删除判据」比「分类判据」宽**，
      而宽的那一侧粘着真释义（ko 那次宽的 12 行里也粘着真释义）。
      `[[criteria-narrower-than-you-think]]`：最高频自伤。
    """
    t = (line or "").strip()
    if not t:
        return "empty"
    bare = _MARKUP.sub("", t).strip(" 　,，.。、；;:：-－—")
    if not bare:
        return "meta"                       # 整行只是词典标记
    if not _CJK.search(bare):
        return "meta"                       # 一个汉字都没有（`＝ассимиляти́вный.`）
    if not has_cyrillic(bare):
        return "real"                       # 纯中文（不含俄语词）⇒ 不可能是元描述的主干
    if _META_TAIL.search(bare):
        return "meta"                       # 「X 的 <语法范畴>」把整行吃完了
    # 含俄语词、又不是「X 的某形式」⇒ 中文实义有多少，决定它是混合还是元描述
    return "mixed" if len(_CJK.findall(bare)) >= 2 else "meta"


def zh_gloss_kind(text):
    """中文释义分三类：`real` / `mixed` / `meta`。**不是两类。**

    · `real`  有至少一行是真释义（可直接用）
    · `mixed` 没有纯中文行，但有行里中文实义与俄语词混着（**可用，要先切**）
    · `meta`  整条都只是在说「这是某个俄语词的某个语法形式」—— 读者得不到词义

    🔴 返回**三个值而不是一个布尔**，是有意的：vi 的 W15 教训是
       `coverage.blank_split()` 必须「**返回两个数不是一个**」——
       把「不可用」和「要加工才可用」压成一个数，后面所有覆盖率都说不清自己在说什么。

    🔴 **已知的不足，写下来而不是假装没有**：
      · 本判据只看文本形式，不回源。ko 的 K24 真正的判法是**拿另一版的汉字表记去对**；
        俄语没有汉字表记这一说，这条路不存在，只能靠形式 ＋ 抽样人读。
      · zh-s 那批多行释义**里面混着源头俄汉词典的排版残渣**
        （变位词尾 `-жусь, -жишься` / `见X` 交叉引用 / 丢了圈码的 `?`）——
        本判据判「有没有真释义」，**不负责清洗**。清洗归阶段 5，判据另立。
    🔴 **什么会推翻它**：每一桶抽样 ≥ 14 条人读，`real` 桶污染 > 5%
       或 `meta` 桶里出现真释义 ⇒ 作废重写（v1 就是这么废掉的）。
    """
    kinds = []
    for ln in (text or "").split("\n"):
        # 🔴🔴 **v3：行内还要再分段。** v2 栽在这一条上：
        #      башенка → `小塔，角塔，塔楼，转塔，炮塔，复二-нок〔阴〕ба́шня①解的指小.`
        #    前五个逗号段是**真释义**，尾巴才是元描述，而它们在**同一行**里 ⇒
        #    v2 的 `_META_TAIL` 在行尾命中，把整行判成 meta，真释义跟着没了。
        # ⚠️ **只按 `，、；` 切，不按 `：` 切** —— 按 `：` 切会把
        #    `он (on) 的賓格：他` 的 `他` 切成一个「纯中文段」而判成 real，
        #    于是「这是某词的宾格」会被当成释义印给读者。
        #    `real` 桶脏 = **读者看得见的错**；`meta` 桶脏 = 多花一点翻译钱。
        #    两种代价不对等 ⇒ 这一刀只切到不会弄脏 `real` 的地方为止。
        kinds.append(_line_kind(ln))
        for seg in _split_segments(ln):
            if _line_kind(seg) == "real":
                kinds.append("real")
    if "real" in kinds:
        return "real"
    if "mixed" in kinds:
        return "mixed"
    return "meta"


# ══════════════════════════════════════════════════════════════════════════
# ④ 阶段 1：`pos` 归一 与 `entry_type` 分类
# ══════════════════════════════════════════════════════════════════════════
# 🔴 **值域是实测的 34 种，不是我猜的**（`pos_domain` 全量扫七源，2026-10-07）。
#    K36 的规矩：写映射表之前先把值域全打出来。
#
# 🔴🔴 值域里有**两对「同一件事两个拼法」**，与 `aspect` 的 perfect/perfective 同形：
#        `interj`      27（ru 版）   vs  `intj`          1,362   ← 缩写不同
#        `onomatopeia` 72（ru 版）   vs  `onomatopoeia`     19   ← **ru 版那个拼错了**
#    不归一就是同一列里两个值域，而**展示层的词性徽标会凭空多出两个空标签**
#    （ko 的 K31：词性表按 `pos_raw` 长码写而展示层读 `pos` 短码 ⇒
#      双方一致报全绿而每个徽标都是空的）。
POS_NORM = {
    "interj": "intj",                 # ru 版的写法 → 八门通用的短码
    "onomatopeia": "onomatopoeia",    # 🔴 ru 版拼错了一个字母，归一到正确拼写
}

# `pos` → `entry_type`。**源头 pos 直接映射，一律不猜**。
# ⚠️ `gerund`（ru 版 53 条）**是个形不是词性** —— 副动词是动词的屈折形。
#    归进 `word` 而把「它其实是屈折形」交给 `is_inflected_form()` 判，
#    不在这儿做两件事（`[[criteria-from-meaning-not-form]]`）。
ENTRY_TYPE = {
    # 真词
    "noun": "word", "verb": "word", "adj": "word", "adv": "word", "name": "word",
    "pron": "word", "num": "word", "det": "word", "prep": "word", "postp": "word",
    "conj": "word", "particle": "word", "intj": "word", "onomatopoeia": "word",
    "gerund": "word",
    # 多词单位
    "phrase": "phrase", "adv_phrase": "phrase", "adj_phrase": "phrase",
    "prep_phrase": "phrase",
    "proverb": "proverb",
    # 粘着语素（俄语构词透明度高，这一类对学习者有用，但它不是能独立使用的词）
    "prefix": "affix", "suffix": "affix", "infix": "affix", "interfix": "affix",
    "circumfix": "affix", "root": "affix", "combining_form": "affix",
    # 符号 / 字母
    "character": "letter", "symbol": "letter", "punct": "letter",
    # 缩写
    "abbrev": "abbrev",
    # 🔴 `unknown` 58,634 条（zh-s 版占 57,547）—— 中文版那片**扁平译词表**没给词性。
    #    **不许归进 `word`**：那会让「源头没给」和「源头说是词」长得一样
    #    （`[[dont-say-source-lacks-what-we-skipped]]`）。
    "unknown": "unknown",
}


def pos_norm(pos):
    """源头 pos → 归一后的短码。**认不出就抛**，不静默兜底。

    🔴 兜底会让「源头加了一种新词性」永远看不见 —— 而那正是闸要逮的事
       （`PLAYBOOK` 7.2：闸自证，库里出现的每一种取值必须在值域里）。
    """
    p = (pos or "").strip()
    if not p:
        raise ValueError("pos 是空的 —— 源头每一行都有 pos（实测 7 源 137 万行无空值）")
    p = POS_NORM.get(p, p)
    if p not in ENTRY_TYPE:
        raise ValueError(
            "认不出的 pos %r —— 值域是实测的 34 种（见本文件 ④）。"
            "源头加了新词性 ⇒ **把它登记进 ENTRY_TYPE 并说明归哪一类**，不许静默兜底。" % pos)
    return p


def entry_type_of(pos):
    """源头 pos → `dict.entry_type`。"""
    return ENTRY_TYPE[pos_norm(pos)]


# ── 屈折形的判据 ──────────────────────────────────────────────────────────
# 🔴🔴 **必须读义项级。** 全量实测（RU_PLAN §6.3）：
#        `senses[].form_of`            en 382,715 ／ ru 11,881 ／ zh-t 57,783
#        `word.form_of`                en     28  ／ ru      0 ／ zh-t      0
#        仅 `sense.tags` 含 `form-of`   en      0  ／ ru      0 ／ zh-t      1
#    **只读 `word.form_of` 会漏 99.99%。** 三条路都走 —— `PLAYBOOK` 四那四条补链路
#    的教训是「每一次我都以为补完了，每一次都是换一个源、换一种写法就漏」。
#
# 🔴🔴 **第四条路（ru-crit-9，2026-10-23）：形动词／副动词页。**
#    ru 版**不给形动词 `form_of`**，把「X 的被动过去时形动词」写进释义
#    （`взбулгаченный → страд. прич. прош. вр. от взбулгачить`）⇒ 前三条路全认不出，
#    **62,576 个形动词页被标成了词元**（词元的 9.78%）。上面 `ENTRY_TYPE` 的注释
#    阶段 1 就写着「副动词是动词的屈折形，交给 `is_inflected_form()` 判」——
#    **而这个函数从来没判过**：意图停在注释里，没有一道闸响过。
#    逮到它的是阶段 3 收尾时把「没有变位表的词元」逐个回源（`probe_inflection_gaps.py`）。
#
#    判据是**两个结构信号一致**，不读释义散文（vi 的 W15）：
#      ① 词级 `tags` 含 `participle`/`gerund`
#      ② **每一个**义项都带变形信号（`form_of` ／ `form-of` ／ `participle`/`gerund`）
#    ⚠️ ② 不许放宽成「有一个义项带」：形容词化的形动词（`навороченный` 花哨的、
#       `убитый` 悲痛欲绝的）第二个义项不带标签而有真释义 —— **它们是词元**。
#    实测（ru 版）：过两条的 64,197 个条目，**99.47% 每条释义都只是「…прич. от X」**；
#       0.53%（339）指针后面跟一句解释（`развивающийся … ; находящийся в стадии развития`）
#       —— 语法上仍是形动词，义项行不删、释义不丢，只是不再算进词元分母。
#    ⭐ 零损失的第二个独立信号：61,136/62,576（97.7%）**已经出现在父动词的变位表里**。
#    📋 漏的方向（有意不收）：义项没带标签而释义是「дееприч. от X」的副动词
#       （`бредя`、`содевав`）—— 精度优先，见 RU_PLAN 欠账 R17。
PARTICIPLE_TAGS = frozenset({"participle", "gerund"})


def _sense_is_form(s):
    return bool(s.get("form_of")) or bool(
        set(s.get("tags") or []) & (PARTICIPLE_TAGS | {"form-of"}))


def is_inflected_form(e):
    """这一行是不是某个词元的屈折形。→ (是不是, 认出它的那条路)"""
    if e.get("form_of"):
        return True, "word.form_of"
    for s in e.get("senses") or []:
        if s.get("form_of"):
            return True, "sense.form_of"
    for s in e.get("senses") or []:
        if "form-of" in (s.get("tags") or []):
            return True, "sense.tags:form-of"
    # 🔴🔴 第五条路（ru-crit-10，2026-10-23 阶段 4 的探针逮到）：**词级** `tags` 含 `form-of`。
    #    fr 版把姓氏变格形写成 `{"tags": ["form-of","surename"], "senses":[{"glosses":
    #    ["Datif masculin singulier de Хортов."]}]}` —— 义项上**没有** `form_of` 也没有标签，
    #    前三条路只查义项级 ⇒ **132,938 个姓氏变格形被标成词元**（fr 133,870 条／pl 10 条）。
    #    实测 99.98% 释义是「X 格 … de Y」指针；不是指针形的 32 条要么释义为空（`Ганнибалом`）、
    #    要么那个词在别的源另有词元条目（`нету`/`воскресать`）⇒ 按「任一源说是词元」不翻。
    #    ⚠️ 这正是 §④ 上面那句话的又一次：「每一次我都以为补完了，换一个源、换一种写法就漏」。
    if "form-of" in (e.get("tags") or []):
        return True, "word.tags:form-of"
    # 🔴🔴 第六条路（ru-crit-15，2026-10-23，5b 切片的产物照出来的）：**副动词页**。
    #    ru 版 75,877 个副动词义项（`клянча → дееприч. от клянчить`）**义项本身不带标签**，
    #    ru-crit-9 要求「每个义项都带」⇒ 漏掉；而它们**同时带两个结构信号**：
    #    词级 tags 含 `gerund` ＋ 分类「Русские деепричастия」。R17 当时写「找一个结构信号」——
    #    **这个信号一直在**。⚠️ 副动词是动词的不变化形式；已词汇化的（`благодаря`/`спустя`）
    #    别的源另有介词/副词条目 ⇒ 按「任一源说是词元」不翻（已核）。
    #    🔴 是被**付费切片**照出来的：1% 里 761 条「дееприч.」排在待译标签第一 ——
    #    差一点把两成翻译费花在「X 的副动词」这句元描述上（vi 6e：跑批产物是独立的缺陷探测器）。
    if "gerund" in (e.get("tags") or []) and any(
            isinstance(c, dict) and c.get("name") == "Русские деепричастия"
            for c in e.get("categories") or []):
        return True, "word.tags:gerund+分类·副动词"
    ss = e.get("senses") or []
    if set(e.get("tags") or []) & PARTICIPLE_TAGS and ss and all(
            _sense_is_form(s) for s in ss):
        return True, "word.tags:participle+全部义项"
    return False, ""


def pointer_target(e):
    """屈折形指向的那个词元。**只取源头的结构字段，不从散文里抠。**

    🔴 vi 的 W15：从自由文本里用正则抠目标是**拿形式代理当内容判据**。
    ⚠️ 取不到就返回 None —— 留 NULL 是**如实**，不是缺失。
    """
    for src in ([e.get("form_of")] + [s.get("form_of") for s in e.get("senses") or []]):
        for it in src or []:
            if isinstance(it, dict) and it.get("word"):
                return it["word"]
    return None


# ── 四个落列的语法字段 ────────────────────────────────────────────────────
# 判据与落法的依据在 RU_PLAN §6.1（每个都量过「entry 内是不是单值」）。
# 🔴 `aspect` 要归一：ru 版标 `perfect`、en/zh-t 版标 `perfective` ——
#    同一件事两个词。归一到 `perfective`（`perfect` 在语言学里指完成**时**）。
ASPECT_NORM = {"perfect": "perfective"}
ASPECT_VALUES = ("imperfective", "perfective", "biaspectual")
GENDER_VALUES = ("masculine", "feminine", "neuter", "common")
ANIMACY_VALUES = ("animate", "inanimate")
DECLENSION_VALUES = ("declension-1", "declension-2", "declension-3", "indeclinable")


def _single(tags, values, norm=None):
    """从 tags 里取这一组的值。**多值就返回 None** —— 落列的列不许塞组合值。

    🔴 返回 None 的那些**不是丢掉了**：调用方要把它们落进
       `sense_tag(bucket='grammar')`。两条路都走，列上只放互斥单值。
       （`SCHEMA` §10.4.1：塞进单列就要发明一套编码，而发明的编码既失真、
         又会变成第二份真值。）
    """
    hit = {(norm or {}).get(t, t) for t in tags if (norm or {}).get(t, t) in values}
    return next(iter(hit)) if len(hit) == 1 else None


def entry_grammar(e):
    """→ (dict 四个落列的值, 落行的那些)。

    取值范围是 **词级 `tags` ∪ 各义项 `tags`** ——
    ru 版把它们放词级（131,683 条 gender），en 版放义项级（53,768 条）。
    🔴 只读一边会整版漏掉（与 `form_of` 同一个形状）。
    """
    tags = list(e.get("tags") or [])
    for s in e.get("senses") or []:
        tags += list(s.get("tags") or [])
    cols = {
        "aspect": _single(tags, ASPECT_VALUES, ASPECT_NORM),
        "gender": _single(tags, GENDER_VALUES),
        "animacy": _single(tags, ANIMACY_VALUES),
        "declension": _single(tags, DECLENSION_VALUES),
    }
    # 落行的：① 本来就多值的 transitivity / number；② 上面因多值而落空的那些
    rows = []
    for t in sorted(set(tags)):
        n = ASPECT_NORM.get(t, t)
        if n in ("transitive", "intransitive", "reflexive", "pronominal",
                 "impersonal", "ditransitive",
                 "singular", "plural", "plural-only", "uncountable", "countable",
                 "semelefactive", "iterative"):
            rows.append(n)
        elif n in (ASPECT_VALUES + GENDER_VALUES + ANIMACY_VALUES + DECLENSION_VALUES) \
                and cols.get(_group_of(n)) is None:
            rows.append(n)          # 多值 ⇒ 列上落空，值落行，**一个都不丢**
    return cols, sorted(set(rows))


def _group_of(v):
    for name, vals in (("aspect", ASPECT_VALUES), ("gender", GENDER_VALUES),
                       ("animacy", ANIMACY_VALUES), ("declension", DECLENSION_VALUES)):
        if v in vals:
            return name
    return None


def etym_no_pair(e):
    """`etymology_number` → (主编号 INTEGER, 子编号 INTEGER)。

    🔴🔴 **源头有子编号 `1.1` / `1.2`**（实测 2 行，`лиственник` 的两支词源）。
       两条路都是错的：
         · 存成 TEXT ⇒ **字典序**，「10」排在「2」前面（vi 的 **B18** 就是这个）；
         · 截断成 `1` ⇒ **把两支不同的词源合成一支**。
       ⇒ 拆成两个 INTEGER 列。**不把两件事塞进一列**（`SCHEMA` §10.4.1）。
    ⚠️ 这一条是**判据自己拦下来的**：第一版写 `int(v)` 并在转不动时 `raise`，
       全量跑当场炸在 `'1.1'` 上。如果当时写的是 `except: return 0`，
       这两支词源会**静默合并**而没有任何东西说话。
       ⭐ 顺带暴露了我的探针的一个缺陷：它只印了**排序后的前 8 个值**，
         而 `1.1`/`1.2` 排在后面 ⇒ **「值域全打出来」要真的全打，不许截断**。

    🔴 转不动（出现第三层 `1.1.1` 或非数字）**照旧抛** —— 不许静默兜底。
    """
    v = e.get("etymology_number")
    if v is None or v == "":
        return 0, 0
    s = str(v).strip()
    try:
        if "." in s:
            a, b = s.split(".", 1)
            return int(a), int(b)
        return int(s), 0
    except (TypeError, ValueError):
        raise ValueError(
            "etymology_number 既不是整数也不是 `主.子` 两段：%r（词 %r）—— "
            "**把这种写法登记进 `etym_no_pair` 再往下走**，不许静默当 0"
            % (v, e.get("word")))


# ══════════════════════════════════════════════════════════════════════════
# ⑤ `entry_type` 按**词**唯一 —— 🔴🔴 第一版把一个词形切成了多行
# ══════════════════════════════════════════════════════════════════════════
# 第一版把 `dict` 的身份单位定成 `(word, entry_type)`，于是同一个拼写在不同词性下
# 成了**多个 dict 行**。骨架闸 K10 当场报出来：`word_norm` 一对多 **56,379 组**，
# 其中 **84.2%（47,460 组）是这个** —— 不是数据问题，**是我的设计错**。
#
#     按 (word, entry_type) 唯一   1,023,872 行
#     按 word 唯一                  **976,762** 行   ← 正是阶段 -1 量到的七源并集
#
# ⚠️ 代价是读者可见的：一个词形两个页面，而展示层按 `word_norm` 查会 `.get()` 第一行
#    —— vi 那门正是这样让 **1,291 个页面显示别的词的内容**。
#
# ═══ 判据：**两个独立信号一致才收** ═══
# 源头词性是一个信号，**词头自己的形式**是另一个。实测的组合里，只用前者会出错：
#
#     сердце  [proverb+noun]      ← 源头说它是谚语，而它是「心」。**没有空格 ⇒ 不是谚语**
#     вернее  [suffix+unknown+adv] ← 源头说它是后缀，而它是「更确切地说」。**没有连字符 ⇒ 不是词缀**
#     Ё       [character+name+noun] ← 它既是字母又是词。**不是唯一类别 ⇒ 按词**（vi 的先例：
#                                     「`letter` 必须是唯一词性才算」，324 个里 50 个同时是真词）
#     Абабков [unknown+name]       ← `unknown` 只说明**源头没给**，永远不许赢
#
# 🔴 这里用「含不含空格／带不带连字符」**不是形式代理** ——
#    `[[criteria-from-meaning-not-form]]` 禁的是**拿形式猜内容**；
#    而「这个词头是不是多词单位／是不是粘着语素」**本身就是形式问题**，形式就是答案。
_AFFIX_POS = {"prefix", "suffix", "infix", "interfix", "circumfix", "root",
              "combining_form"}
_LETTER_POS = {"character", "symbol", "punct"}
_PHRASE_POS = {"phrase", "adv_phrase", "adj_phrase", "prep_phrase"}


def entry_type_for_word(word, poss):
    """一个词形的 `entry_type`。**按词唯一** —— 这是 `dict` 的身份单位。

    `poss` ＝ 这个词形在七源里出现过的全部（已归一的）词性。
    判据按「最具体、且与词头形式一致」取，顺序与理由见上面的注释块。
    """
    w = (word or "").strip()
    ps = {pos_norm(p) for p in poss}
    real = ps - {"unknown"}                  # `unknown` 只说明源头没给，永不参与定类
    has_space = " " in w or " " in w
    hyphen = w.startswith("-") or w.endswith("-")

    if "proverb" in real and has_space:
        return "proverb"
    if (real & _PHRASE_POS) and has_space:
        return "phrase"
    if (real & _AFFIX_POS) and hyphen:
        return "affix"
    # 🔴 `letter` **必须是唯一类别**（vi 的先例）：字母的名字往往同时是真词，
    #    判成 letter 会把它从词页上降级。
    if real and real <= _LETTER_POS:
        return "letter"
    if "abbrev" in real:
        return "abbrev"
    if real:
        return "word"
    # 一个真词性都没有 ⇒ 如实说「源头没给」，**不许兜底成 word**
    #（`[[dont-say-source-lacks-what-we-skipped]]`）
    return "unknown"


# ══════════════════════════════════════════════════════════════════════════
# ⑥ **哪些源头行会落成 `entry`，以及 `entry.src_ref` 怎么拼**
# ══════════════════════════════════════════════════════════════════════════
# 🔴🔴 这一节是 2026-10-08（阶段 2）从 `build.py` 的 `collect()` 里搬出来的，
#    搬的理由是 vi 阶段 8 的那一课，**原文照抄**：
#      ⭐「import 判据还不够，**『哪些行才真的落库』也是判据、也必须只有一个家**」
#    —— vi 的收割器把「只给可出版例句存译文」这个条件以字面量写在 `main()` 里，
#    外锚闸自己重写了一遍，**报了 458 条假缺**。
#
# 阶段 2 的重音层要把 `forms[canonical]` 挂到它所属的那个 `entry` 上，
# 而唯一精确的挂法是**重算 `src_ref`**（一行源头 ↔ 一行 entry）。
# 如果重音收割器自己抄一份「跳过哪些行」的逻辑，它与建库差一行，
# 挂上去的重音就会**整体错位一格**（而两边各自的闸都会报绿）。
#
# ⚠️ **`SrcRef` 是有状态的**，这件事本身是判据的一部分：
#    `seq` 是 `(src, word, pos, etym_no, etym_sub)` 之内的出现序号，
#    所以要拼出与建库**同一个**键，必须**按同一个顺序重放同一份源**。
#    ⇒ 它不是纯函数，别当纯函数用；换了扫源顺序，键就全变了。
import collections as _collections                                 # noqa: E402

# `src_ref` 里用的短名。**登记表，不是形状推断** —— vi 那门
# `src.endswith('-edition')` 认不出 `zh-edition-trad`，判据要问登记表。
SRC_SHORT = {
    "en-edition": "en", "ru-edition": "ru",
    "zh-edition-simp": "zhs", "zh-edition-trad": "zht",
    "fr-edition": "fr", "vi-edition": "vi", "pl-edition": "pl",
}


def entry_accept(e):
    """这一行源头数据**会不会落成一个 `entry`**。→ `(ok, (种类, 明细), pos)`。

    三条，顺序就是建库时的顺序（顺序有意义：pos 认不出的行里也有非俄语的）：
      ① 切片应当只含俄语 —— 不是就如实记下，**不许静默收进去**；
      ② 空词头；
      ③ `pos_norm` 认不出 ⇒ **当场记名并跳过**，不兜底（`PLAYBOOK` 7.2 闸自证）。
    """
    if e.get("lang_code") != "ru":
        return False, ("lang", e.get("lang_code")), None
    w = e.get("word") or ""
    if not w.strip():
        return False, ("empty", "«空词头»"), None
    try:
        pos = pos_norm(e.get("pos"))
    except ValueError as ex:
        return False, ("pos", str(ex)[:60]), None
    return True, None, pos


class SrcRef:
    """`entry.src_ref` 的**唯一产地**。见本节 ⚠️：它有状态，必须重放同一个顺序。"""

    FMT = "kk-%s:%s:%s:%d.%d:%d"

    def __init__(self):
        self._seq = _collections.Counter()

    def take(self, src, word, pos, etym_no, etym_sub):
        """消耗一个序号并返回 `src_ref`。**每行源头只许调一次。**"""
        k = (src, word, pos, etym_no, etym_sub)
        seq = self._seq[k]
        self._seq[k] += 1
        return self.FMT % (SRC_SHORT[src], word, pos, etym_no, etym_sub, seq), seq


# ══════════════════════════════════════════════════════════════════════════
# ⑦ **「这是这个词头的带重音正字拼写」** —— 阶段 2 重音层的收词判据
# ══════════════════════════════════════════════════════════════════════════
# 🔴🔴 次重音用的是 **U+0300（grave）**，不是 U+0301。阶段 2 的探针在
#    3,000 行小样本上就逮到 `автолебёдка → а̀втолебёдка`、`Кот-д'Ивуар → Ко̀т-д’Ивуа́р`。
#    而 2026-10-07 写下的两条原语**对「什么算重音符」意见不一致**：
#        strip_stress  剥 U+0301 **和** U+0300   ← 宽的那个（对的）
#        has_stress    只认 U+0301                ← 窄的那个
#    ⇒ `[[criteria-narrower-than-you-think]]`：**最高频自伤**。补 `has_any_stress`，
#      而 `has_stress`（主重音）保留原意并改名说清楚，两个都要，因为
#      「有没有标重音」和「有没有标**主**重音」是两件事。
MARKS = (STRESS, "̀")          # 主重音 U+0301 ／ 次重音 U+0300


def has_any_stress(s):
    """这串里有没有**任何**重音符（主或次）。原语。"""
    return any(m in (s or "") for m in MARKS)


# 源头把印刷用撇号和 ASCII 撇号混着用：`Кот-д'Ивуар` 的词头是 ASCII `'`，
# 而它的带重音拼写写成 `Ко̀т-д’Ивуа́р`（U+2019）。
# ⚠️ **只归一撇号这一类**，不许顺手把「看起来像的」都归一 ——
#    `normalize_ipa` 的文件头写着同一条：那会动到 `ʼ`（在别的语言里是音位）。
_APOS = {"’": "'", "ʼ": "'", "‘": "'", "`": "'"}


def _apos_fold(s):
    return "".join(_APOS.get(c, c) for c in s or "")


# 🔴🔴 **次重音可以是预组合的单码位**，而 `strip_stress` 剥的是组合符，看不见它：
#        индоевропейский → ѝндоевропе́йский     `ѝ` ＝ U+045D（不是 и ＋ U+0300）
#        древнегреческий → дрѐвнегре́ческий     `ѐ` ＝ U+0450
#    这两个字符在残差桶里现身，占 442 条「其他」里相当一部分。
# ⇒ 比对用的键先 NFD 拆开、剥掉重音符、再 NFC 合回来。
# ⚠️⚠️ **这是本门唯一许可用 NFD 的地方，而许可的理由必须说清**：
#    ru 与 vi 方向相反，「NFD 之后去组合符」会毁掉 `й`(и+U+0306) 和 `ё`(е+U+0308)。
#    这里安全是因为两件事同时成立：
#      ① **只剥 U+0301/U+0300 两个**（`MARKS` 白名单），U+0306/U+0308 一个不动；
#      ② 这个键**只用于比较、而且两边都用它** —— 它从不成为落库的值。
#    🔴 谁要把 `_cmp_key` 用在写库那一侧，`norm_ru` 的 import 时自检会当场炸。
def _cmp_key(s):
    t = ud.normalize("NFD", s or "")
    for m in MARKS:
        t = t.replace(m, "")
    return ud.normalize("NFC", t)


# 🔴🔴 **落库的值要统一成「组合式重音符」** —— 这一条是写重音层的闸时逮到的。
#    源头两种编码混着用，而它们在下游的表现**不一样**：
#        组合式   е ＋ U+0300   `strip_stress` 剥得掉 ⇒ `norm_ru` 的检索键干净
#        预组合   ѐ ＝ U+0450   `strip_stress` **剥不掉** ⇒ 重音符活着流进检索键
#    实测落库 736,576 行里有 **165 行**是预组合的（`элѐктро-`／`сѐро-зелёный`），
#    另有 3 行是**拉丁** `ó`（`c-moll → c-móll`，德语调名在俄语词典里的正当条目）。
#    ⇒ `[[aim-for-perfect-not-cheap]]`：**别用展示层补丁代替把事情做进数据里**。
#      把这一个字段统一成一种编码，`norm_ru` 就不用知道有第二种。
# ⚠️ 只拆「底字 ＋ 重音符」这一种组合，`й`(и+U+0306)／`ё`(е+U+0308) 一个不动 ——
#    判据是**分解之后那个组合符是不是重音符**，不是「长得像不像」。
VOWELS = "аеёиоуыэюя"


def stress_not_needed(word):
    """这个词形**本来就不需要重音符**吗 → 原因，不需要则 `None`。

    🔴🔴 这条判据的家必须在这里，而不是在收割器里 —— 它决定的是
    **「源头没给」和「本来就不用给」怎么分成两个数**：
        含 ё      ё 永远重读，俄语词典惯例不另标符 ⇒ 无需标注（实测 2,897 个词形）
        单音节    重音位置无歧义 ⇒ 标不标都不辨义（170 个）
        多音节    没有符就是**源头标坏了** ⇒ 这是缺口（167 个）
    vi 的 `coverage.blank_split()` 是同一课：**返回两个数不是一个**；
    而 `[[dont-say-source-lacks-what-we-skipped]]`：「我们没抽」会慢慢变成「源头没有」。
    """
    low = (word or "").lower()
    if "ё" in low:
        return "含ё（ё 永远重读，源头不另标符）"
    if sum(1 for ch in low if ch in VOWELS) <= 1:
        return "单音节／无元音（重音位置无歧义）"
    return None


def to_combining_stress(s):
    out = []
    for c in s or "":
        d = ud.normalize("NFD", c)
        out.append(d if len(d) == 2 and d[1] in MARKS else c)
    return "".join(out)


# 诊断标签用的形状（**只用来给残渣分类报数，不参与 ok 的判定**）。
_ROMAN_TAIL = re.compile(r"\s+[IVX]{1,4}$")
# 西里尔字母的拉丁同形字。🔴 这一类比散文危险得多：它**看起来是对的**，
# 进了库就是一个搜不到、排不对的词形（vi 的 `word_norm` 事故同形）。
# ⚠️ 判据按**含义**写：不是「含有这些字母」（`со [ with instrumental` 会被误标成
#    同形字，而它是散文），而是「**把同形字换回去之后正好就是这个词头**」。
_LOOKALIKE = {"ë": "ё", "e": "е", "a": "а", "o": "о", "p": "р", "c": "с",
              "x": "х", "y": "у", "é": "е",
              "B": "В", "H": "Н", "K": "К", "M": "М", "T": "Т", "A": "А",
              "E": "Е", "O": "О", "P": "Р", "C": "С", "X": "Х", "Y": "У"}


def _deglyph(s):
    return "".join(_LOOKALIKE.get(c, c) for c in s or "")


# ── 源头残渣的修复 ────────────────────────────────────────────────────────
# ⭐⭐ **这些修复可以写得宽，而不会放进一条垃圾** —— 因为判定始终是
#    「剥掉重音符之后等于词头」那**一个等式**，修完还要再过它一次。
#    等式是修复自己的闸：`со [ with instrumental` 怎么修也等不上 `со`。
#    🔴 `[[source-typo-fix-ours-not-quote]]`：改的是**我们的出版文本**，
#      证据层（`stress.src_ref` 指回的那行源头）一个字不动。
_ORPHAN = re.compile(r"(?:(?<=\s)|^)[̀́]+")       # 游离的组合符：`река ́`
_SP_HYPHEN = re.compile(r"\s*-\s*")                          # `Центра́льно -Африка́нская`
_TAIL_JUNK = re.compile(r"[\s!•*^.,;:]+$")                   # 源头加的尾巴：`шу́тка!`
_ROMAN_IDX = re.compile(r"\s+[IVX]{1,4}$")                   # 同形异义编号：`ча́йка I`
# U+00AD 软连字符冒充连字符：`ноу­ха́у`（看不见，而词头写的是 `ноу-хау`）。
# ⚠️ 单独一条、单独一个名字 —— 不可见字符最该被数到，别混进「空白」里。
_INVISIBLE = {"\u00ad": "-", "\u200b": "", "\u200c": "", "\u2060": ""}


def _repairs(f):
    """逐个产出「修过的候选串 ＋ 这一步叫什么」。**顺序由窄到宽。**"""
    a = re.sub(r"\s+", " ", f).strip()
    if a != f:
        yield a, "ok-修过空白"
    b = _ORPHAN.sub("", a).strip()
    if b != a:
        yield b, "ok-修过游离组合符"
    c = _SP_HYPHEN.sub("-", b)
    if c != b:
        yield c, "ok-修过连字符旁空格"
    d = _TAIL_JUNK.sub("", c)
    if d != c:
        yield d, "ok-修过尾部残渣"
    e = _ROMAN_IDX.sub("", d)
    if e != d:
        # ru 版给同形异义条目的带重音拼写加了 `I`/`II`（`ча́йка I`）。
        # 编号是**条目的**不是拼写的，剥掉；而等式仍然是它自己的闸。
        yield e, "ok-剥同形异义编号"
    g = "".join(_INVISIBLE.get(ch, ch) for ch in e)
    if g != e:
        yield g, "ok-修过不可见字符"


def stressed_spelling(word, form):
    """→ `(ok, kind)`：`form` 是不是 `word` 的带重音正字拼写。

    ═══ 判据只有一条，而它是**两个独立信号一致** ═══
    信号一：源头的 `forms[].tags` 里有 `canonical`／`stressed`（调用方已筛）；
    信号二：**剥掉重音符之后的字母串就是这个词头本身**。

    ⭐ 为什么是这一条：ko 那门反复证明「两个独立信号一致才收」
    （长音符验配对 100%／指针两信号验 99.994%），而重音层这里信号二特别硬 ——
    重音符是**叠加在正字上的记号**，它不许改动任何字母。只要字母串变了，
    那就不是「同一个词的带重音写法」，而是源头往这个字段里塞了别的东西：

        со        → `со [ with instrumental` ／ `accusative]`  源头把一条注释**拆成了两行**
        к         → `к (k)`                                   罗马转写
        чайка     → `ча́йка I`                                 同形异义编号
        алфавит   → `алфа́вит^*`                               源头表格脚注（与 R8 同类）
        бельё     → `бельë`                                   🔴 **拉丁 ë 冒充西里尔 ё**
        после Р. Хр. → `по́сле Р. Хр.`                          ✅ 带缩写点，字母串相同 ⇒ 收

    🔴 **`kind` 是诊断标签，不是判定依据。** 判定只看信号二那一个等式 ——
       把「含拉丁字母就拒」之类的形状条件写进判定，就又是一条
       `[[criteria-narrower-than-you-think]]`：形状列不全的那天它就开始漏。
       形状只用来**给被拒的那批分类报数**，好让我看清源头到底塞了什么。
    """
    f = (form or "").strip()
    if not f:
        return False, "空", ""
    w = (word or "").strip()

    wk = _cmp_key(w)

    def _eq(cand):
        b = strip_stress(cand)
        if b == w:
            return "exact"
        if _apos_fold(b) == _apos_fold(w):
            return "apos"
        # 预组合的次重音字母（`ѝ`/`ѐ`）—— 见 `_cmp_key` 的注释
        if _cmp_key(cand) == wk or _apos_fold(_cmp_key(cand)) == _apos_fold(wk):
            return "precomposed"
        return None

    # 🔴 `_eq` 的每一个返回值都要在这里有一条分支。
    #    第一版漏了 `precomposed`（给 `_eq` 加分支时没回头看调用方），于是
    #    `ѝндоевропе́йский` 明明比对上了却仍落进「其他」残渣桶 ——
    #    `[[fix-regression-and-gate]]`：加了一支而读它的地方没跟上，等于没加。
    _OK = {"exact": "ok",
           "apos": "ok-撇号变体",            # 收，而**存源头原样**（归一只用于比对）
           "precomposed": "ok-预组合次重音"}
    def _publish(val, kind):
        """落库值统一成组合式重音符，并**要求它真的带着重音信息**。

        🔴 第一版只要求「与词头不同」，于是 `с'езд → с’езд`（只差撇号写法）
           被收了进来 —— 它一个比特的重音信息都没有，而「重音写法」那一栏
           印出它就是在撒谎。与 §D 那 6,172 行是**同一个病的第二种形状**：
           判据问的是「不一样吗」，而该问的是「**带信息吗**」。
        """
        v = to_combining_stress(val)
        if not has_any_stress(v):
            # 🔴 **两个数分开**：`стол`／`всё` 这种是「本来不用标」，
            #    `крем для бритья`（源头把重音符写成游离的、被修掉之后什么也不剩）
            #    是「源头标坏了」—— 前者不是缺口，后者是。
            why = stress_not_needed(w)
            return False, ("无需标注·" + why) if why else "🔴 源头标坏了·一点重音信息都没有", v
        return True, kind, v

    hit = _eq(f)
    if hit:
        return _publish(f, _OK[hit])
    for cand, name in _repairs(f):
        if _eq(cand):
            return _publish(cand, name)

    # ── 以下全是被拒的，只分类 ──────────────────────────────────────────
    bare = strip_stress(f)
    # ⚠️ 残渣修复过的串也拿来分类 —— 否则「空白修过之后仍对不上」的那些
    #    会按原串被归到别的桶里，看不出真正的差异在哪。
    rep = [c for c, _n in _repairs(f)]
    deg = [strip_stress(x) for x in [f] + rep]
    if any(_deglyph(b) == w or _deglyph(_apos_fold(b)) == _apos_fold(w) for b in deg):
        return False, "🔴 拉丁同形字冒充西里尔", f
    if "^" in f or "*" in f:
        return False, "源头表格标记（R8 同类）", f
    if any(c in f for c in "[]()"):
        return False, "源头注释（括号）", f
    if _ROMAN_TAIL.search(f):
        return False, "同形异义编号（罗马数字）", f
    if any("a" <= c.lower() <= "z" for c in f):
        return False, "混入拉丁字母/散文", f
    if any(b.lower() == w.lower() for b in deg):
        return False, "只差大小写", f
    if w and any(b and (b in w or w in b) for b in deg):
        # 源头把一条内容**拆成了多行**（谚语按逗号切、`со [...]` 按空格切）。
        # 单独一个标签：它不是脏数据，是**我们这边要重新拼起来**的东西。
        return False, "源头把一条拆成多行（片段）", f
    return False, "其他（残渣，必须看样本）", f


# ══════════════════════════════════════════════════════════════════════════
# ⑧ 屈折层：**哪些 `forms` 行是「这个词元的一个屈折形」**
# ══════════════════════════════════════════════════════════════════════════
# 阶段 3。`forms` 这一个字段同时装着四类东西，而**只有第四类是屈折形**：
#
#   ① 词头自己的带重音拼写      `canonical` / `stressed`     → 阶段 2 已收走
#   ② **拉丁转写**              `romanization` 437,017 ／ `transliteration` 21,093
#                              （`собака → sobáka`。pl 版那 20,776 个「有变位表的词」
#                                **整个是转写**，一条屈折形都没有）
#   ③ **变位表模板的元数据**    `table-tags` 83,091 ／ `inflection-template` 83,089
#                              ／ `class` 91,106（`собака → ru-noun-table` / `velar-stem`
#                                / `accent-a`）—— 它是 `inflection.table_tag` 该装的东西
#   ④ 真正的屈折形
#
# 🔴🔴🔴 **照「有语法标签就收」做，会往 `form` 里灌 45.8 万行拉丁转写。**
#    这个数是「完整 tag 值域、无条件不过滤」那一节逼出来的（138 种 tag 全打）——
#    `[[consult-two-models-on-rules]]`：2026-10-07 我拿一张**猜的**值域表写判据，
#    结果两家外审对一个不存在的现象各给了一套有说服力的归因。
#
# 🔴🔴 **而光按 tag 挡还不够 —— en 版会发出「只带语法标签的拉丁转写行」**：
#        я → jej, nej, jéju, néju
#        tags = ['feminine','instrumental','personal','pronoun','singular','third-person']
#    `romanization` 这个 tag **不在里面**。⇒ 必须**两个独立信号一致**才收：
#      信号一：tag 不在「非词形」登记表里；
#      信号二：**这个串真的是西里尔**。
#    ⚠️ 信号二是形式判据，而这里用形式**是对的** ——
#      `[[criteria-from-meaning-not-form]]` 禁的是拿形式猜内容，
#      而「这串字是不是俄语」本身就是形式问题，形式就是答案（与 `entry_type_for_word` 同理）。

# 非词形行的 tag 登记表。**问名单不写形状**（vi 的 `endswith('-edition')` 那一课）。
NON_FORM_TAGS = frozenset({
    "romanization", "transliteration", "transcription",   # 拉丁转写
    # 源头自己标的错误行：`error-unknown-tag` 592 ／ `error-unrecognized-form` 370。
    # 🔴 它们**不许静默丢**，要单独一个桶数出来 —— 源头的缺陷率是我们该知道的数。
    "error-unknown-tag", "error-unrecognized-form",
})
# 变位表模板的元数据行 —— 它们填 `inflection.table_tag`，不填 `form`。
TABLE_META_TAGS = frozenset({"table-tags", "inflection-template", "class"})
# 阶段 2 收走的
STAGE2_TAGS = frozenset({"canonical", "stressed"})

# 源头表格里的脚注/标记符号。实测 ru 版 `*` 14,415 ／ `^` 1,356 ／ `△` 1,349 ／ `†` 4，
# 还有 en 版 `②`（`b*②`）那一族带圈数字。
# 🔴 **它们是排版记号不是拼写的一部分**，剥掉；而「这一行被源头标过」是信息，
#    落库时进 `tags`，命名空间前缀 `src-mark:`（见 `inflection_rows` 的返回值）。
# ⚠️ 名单是**实测补齐的**，不是想出来的：`⟐`（en 版 266 行）与
#    上标数字（`нея̈ ²`）都是把残差桶追到 0 之后才显形的。
_MARKS_RE = re.compile(r"[\^*†‡△▲▽◊⁂⟐]|[①-⑳]"
                       r"|[¹²³⁰-₟]")


_LAT2CYR_VOWEL = {"a": "а", "e": "е", "o": "о", "y": "у",
                  "i": "и", "u": "у"}


def _fix_latin_accent(s):
    """把「拉丁重音元音」换回「西里尔字母 ＋ U+0301」。换不了的原样留着。

    🔴🔴 阶段 2 在 fr 版逮到过（`бельё → бельë`），而屈折层实测
    **ru 版自己有 929 行**：`Ленин → Лénин / Лénино`（`é` ＝ U+00E9）。
    它们是**真词形**（Ленин 的物主形容词），只是重音符被打成了拉丁字母。
    ⇒ `[[source-typo-fix-ours-not-quote]]`：**改我们的出版文本**，映射一对一；
      而**修完必须整串都是西里尔**才收 —— 那一条就是这次修复自己的闸。
    """
    out = []
    for c in s or "":
        d = ud.normalize("NFD", c)
        if len(d) == 2 and d[1] in MARKS and d[0].lower() in _LAT2CYR_VOWEL:
            cyr = _LAT2CYR_VOWEL[d[0].lower()]
            out.append((cyr.upper() if d[0].isupper() else cyr) + d[1])
        else:
            out.append(c)
    return "".join(out)


def _is_cyrillic_form(s):
    """这个串是不是一个俄语词形（西里尔 ＋ 允许空格/连字符/重音符）。

    判据按含义：**至少有一个西里尔字母，而且没有拉丁字母。**
    ⚠️ 不写「全是西里尔」—— 复合词带连字符、多词形带空格，而
       `2-ой`（序数词）带阿拉伯数字，那些都是正当的俄语写法。
    """
    t = s or ""
    if any("a" <= c.lower() <= "z" for c in t):
        return False
    return any(_dbtool.is_cyrillic(c) for c in t)


# ── 这一层的三条「源头张冠李戴」，每条都带实测证据 ──────────────────────────
# 🔴🔴 ① **一张表印在了别人的页上。** en 版的人称代词表模板名是 `g`
#    （退化的模板名，大概是 Lua 参数漏出来的），而它把**整张代词范式**
#    印在**每一个**代词页上 ⇒ `я → ты / он / она / мы / вы / они`。
#    实测边界很干净：**34 个代词词头 × 约 99 行 ＝ 2,871 行，全是 `pos='pron'`**，
#    而「词形首字母与词头不同」的比例 **85.3%**（全库基线 3.35%）。
#    ✅ **零信息损失已证明**（照 ko 隐藏关系前必须验的那一条）：
#      ru 版给每个代词自己的正确范式（`я → меня/мне/мной/мною`），
#      而删掉 `g` 之后「一条屈折都不剩」的 14 个词**本身就是屈折形**
#      （`меня`/`тобой`/`тебе`…）—— 它们本来就不该有变位表。
BAD_TABLE_TAGS = {
    "g": "en 版代词表模板：把整张人称代词范式印在每个代词页上（2,871 行，零损失已验）",
}

# 🔴 ② **源头把语体标签塞进了词形**：`она → устар. ея`／`деверь → разг. деверьёв`。
# ⚠️ 判据**按枚举写，不按形状写**：以「缩写. 」开头的 62 行里**只有 24 行是污染**，
#    另外 38 行是**正当的带空格缩写**（`т.г. → т. г.`／`л.с. → л. с.`／
#    `санузел → сан. узел`／`ед.ч. → ед. ч.`）。
#    ⇒ 按形状剥会**为了修 24 行而弄坏 38 行**。vi 那门的结论原样适用：
#      「这批东西的本质是**源头的标记词汇表**，所以用枚举」。
#    ⭐ 剥下来的标签不丢，进 `tags` 的 `src-label:` 命名空间。
USAGE_LABELS = ("устар.", "разг.", "прост.", "диал.", "книжн.", "обл.",
                "поэт.", "спец.", "знач.")

# 🔴 ③ **ru 版的代词表也列了兄弟代词**：`она → он / оно`（tags 为空）。
#    与 ① 同一个病在另一版上的小规模复发，实测 **69 行**。
#    ⚠️ 判据要用 `pos` —— 而「tags 为空」本身**不是**判据：全库 8,834 行 tags 为空，
#      其中 `семь → семью`、`восемь → восьми` 都是**正当的**数词屈折，
#      只是 ru/fr 版没给它们打标签。⇒ 必须 `pos='pron'` **且** tags 为空。


def _strip_usage_label(piece):
    """→ (剥掉语体标签之后的串, [剥掉的标签])。按枚举，不按形状。"""
    t = (piece or "").strip()
    got = []
    while True:
        for lab in USAGE_LABELS:
            if t.startswith(lab + " ") or t.startswith(lab + "\u00a0"):
                got.append(lab)
                t = t[len(lab):].strip()
                break
        else:
            return t, got


def _split_cell(form):
    """一格里挤了多个词形时，拆成几个。→ [词形, …]

    实测两种形状，**意思不一样，拆法也不一样**：
      ① 括号在**开头** ＝ 可选前缀 ⇒ 带与不带**都是真词形**
         `(по)бо́льше`  → `бо́льше` ＋ `побо́льше`      （5,952 行）
         `(наи)слабе́йший` → `слабе́йший` ＋ `наислабе́йший`
      ② 括号在**后面** ＝ 主词形 ＋ 括号里的异体清单
         `есть (есь, еси́)` → `есть` ＋ `есь` ＋ `еси́`
    🔴 **按位置分支，不许共用一条规则** —— vi 那门「判据按分支写不共用安全网」
       是同一课：一个安全网对一支是对的、对另一支正好是反的。
    """
    t = (form or "").strip()
    if not t:
        return []
    m = re.match(r"^\(([^)]{1,6})\)(.+)$", t)
    if m:                                        # ① 可选前缀
        pre, rest = m.group(1).strip(), m.group(2).strip()
        return [rest, pre + rest]
    m = re.match(r"^([^(]+)\(([^)]*)\)\s*$", t)
    if m:                                        # ② 主词形 ＋ 异体清单
        out = [m.group(1).strip()]
        out += [x.strip() for x in m.group(2).split(",") if x.strip()]
        return [x for x in out if x]
    if "," in t:                                 # 纯逗号清单
        return [x.strip() for x in t.split(",") if x.strip()]
    return [t]


def inflection_rows(word, form, tags, pos=None, table_tag=None):
    """一行源头 `forms` → 这个词元的屈折形。→ `(kind, [(form, stressed, extra_tags), …])`

    收下来的那一类 `kind == "ok"`；其余每一类都有自己的名字，**一个都不许沉进
    「其他」**（`[[residual-bucket-is-not-evidence]]`：桶合并一次，缺陷隐身一次）。
    """
    ts = set(tags or [])
    # 🔴 **整张表是张冠李戴的** —— 比逐行判都早，因为这一行本身没有任何毛病，
    #    错的是「它属于谁」。见上面 ① 的实测证据。
    if table_tag in BAD_TABLE_TAGS:
        return "🔴 张冠李戴的变位表（%s）" % BAD_TABLE_TAGS[table_tag], []
    if ts & STAGE2_TAGS:
        return "阶段2已收（词头自己的带重音拼写）", []
    # 🔴 **ru 版代词表里的兄弟代词**。见上面 ③：`pos` 与「tags 为空」**两个条件都要**。
    if pos == "pron" and not ts:
        return "🔴 源头的代词表列了兄弟代词（`она → он`，不是它的屈折形）", []
    hit = ts & NON_FORM_TAGS
    if hit:
        return "非词形行·" + "/".join(sorted(hit)), []
    if ts & TABLE_META_TAGS:
        return "变位表模板元数据（填 table_tag）", []
    raw = (form or "").strip()
    if not raw:
        return "空", []
    # 🔴 **压缩范式**：ru 版把整个助动词变位挤进一格 ——
    #    `прыгать → бу́ду/бу́дешь… пры́гать ['future']`（实测 25,414 行带 `…`）。
    #    拆不出干净的单个词形（按 `/` 切会得到 `бу́дешь…` 和 ` пры́гать`），
    #    ⇒ **如实拒掉并单独记数**，别猜。欠账里写清它值多少。
    if "…" in raw or "..." in raw:
        return "源头把整个压缩范式挤进一格（含 …）", []
    # 🔴 **源头说「这一格没有这个词形」** —— 整格就是一个破折号。
    #    `баять → - ['participle','passive','present']`（баять 没有被动现在分词）。
    #    ⚠️ 这是**信息不是垃圾**（缺位动词的空格子），而且第一版我把它错标成
    #      「拉丁转写」—— **标错一个桶比不标更糟**，它会被当成源头的毛病去修。
    #      ⇒ 单独一个名字（`[[residual-bucket-is-not-evidence]]`）。
    if raw in ("-", "—", "–", "‒", "--", "?", "？"):
        return "源头说这一格没有这个词形（缺位）", []
    # 🔴 源头模板没展开。ru 版 108 行 `масленичный → {{{основа1}}}` ——
    #    单独一个桶，它是**源头的缺陷**，与「我们没抽」要在结构上分得开。
    if "{{" in raw or "}}" in raw:
        return "源头模板没展开（`{{{…}}}`）", []
    out = []
    bad = None
    for piece in _split_cell(raw):
        piece, labels = _strip_usage_label(piece)
        cleaned = _MARKS_RE.sub("", piece).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            # 🔴 整格就是一个 `*`（ru 版 6,242 行 `украинский → *`，短尾形那一格）
            #    —— 与 `-` **是同一个意思**：源头说这一格没有这个词形。
            #    ⚠️ 第一版我给它起的名字是「剥掉标记之后什么都不剩」，那描述的是
            #      **机制**不是**含义** —— 于是它看起来像我的 bug 而其实是源头的信息。
            bad = bad or "源头说这一格没有这个词形（缺位）"
            continue
        cleaned = _fix_latin_accent(cleaned)
        # 两个独立信号的第二个：**这串字真的是俄语**
        if not _is_cyrillic_form(cleaned):
            # ⚠️ **两种原因分开印** —— 「混了拉丁字母」是源头在发转写，
            #    「一个西里尔都没有」是剩下的只有数字/符号（`гол → знач. 1`）。
            #    把后者印成前者，就会有人去 fr 版查一个不存在的转写问题。
            #    今天这个「标错桶」已经犯过两次（`*` 与 `-`），**第三次了**。
            bad = bad or ("🔴 拉丁转写而 tag 没说（en/fr 版会这么干）"
                          if any("a" <= ch.lower() <= "z" for ch in cleaned)
                          else "一个西里尔字母都没有（只剩数字/符号）")
            continue
        # 允许的非字母字符。**逐个列，每个都有实测理由**：
        #   空格/连字符  多词与复合词形
        #   U+0301/0300  主/次重音
        #   `/`          **缩写的正当拼法**（ru 版 1,640 行：`б.г. → б/г`＝без года）
        #   `.`          缩写（`январь → янв.`）
        #   撇号两种     `Кòт-д’Ивуа́ра`（阶段 2 的 `_APOS` 同一批）
        #   U+0308       改革前正字法的组合符（`я → ея̈`，en 版 201 行、标着 dated）
        #   数字         序数词（`2-ой → 2-о́го`）
        odd = [c for c in cleaned
               if c not in (" ", "-", "/", ".", "'", "’", STRESS,
                            "̀", "̈")
               and not _dbtool.is_cyrillic(c) and not c.isdigit()]
        if odd:
            bad = bad or ("其他残渣（%s）" % "".join(sorted(set(odd)))[:8])
            continue
        st = to_combining_stress(cleaned)
        extra = ["src-mark:" + c for c in sorted(set(_MARKS_RE.findall(piece)))]
        extra += ["src-label:" + x for x in labels]      # 剥下来的语体标签不丢
        out.append((strip_stress(st), st if has_any_stress(st) else None, extra))
    if not out:
        return bad or "空", []
    return "ok", out


# ── 指针目标怎么解析回一个 `dict` 行 ──────────────────────────────────────
# 🔴🔴 **实测 en 版 91.81% 的 `form_of[].word` 带重音符**（`палочка → па́лка`），
#    拿原样去查 `dict` 只能对上 **7.93%**。
#    ⚠️ 而我第一版的探针就是拿原样去查的，报出「指针目标只有 24.27% 在 dict 里」——
#      **那是我的度量错，不是数据缺陷**（`[[measure-landing-not-source]]`：
#      新数字先假设我的度量错了）。
# 另有 0.27% 怎么都对不上，形状是两种：目标串里带括号转写
# （`пища → пита́ть (pitátʹ)`）、以及带虚词的多词目标（`нетонущий → не тону́ть`）。
# ⇒ 返回**一串按顺序尝试的键**，调用方拿它依次查库；
#   `pointer_target()` 本身仍然返回**源头原样**（那是证据，一个字不动）。
def pointer_lookup_keys(target):
    """→ [(键, 这个键是怎么来的), …]，按「越原样越优先」排。"""
    t = (target or "").strip()
    if not t:
        return []
    keys, seen = [], set()

    def add(k, how):
        if k and k not in seen:
            seen.add(k)
            keys.append((k, how))

    add(t, "原样")
    add(re.sub(r"\s*\([^)]*\)\s*$", "", t).strip(), "去尾部括号转写")
    for k, _how in list(keys):
        add(strip_stress(k), "剥重音符")
    for k, _how in list(keys):
        add(norm_ru(k), "归一（小写＋剥重音）")
    return keys


# ══════════════════════════════════════════════════════════════════════════
# ⑨ 音标层：**一格 `sounds[].ipa` → 几条读音、各属于谁、能不能印**（阶段 4，ru-crit-11）
# ══════════════════════════════════════════════════════════════════════════
# 依据全在 RU_PLAN §十一（探针 `probe_pronunciation_layer.py` §A–§K ＋ 当天三次补量）。
# 🔴 三件事分开判，**谁也不替谁兜底**：
#    ① 拆：一格里可能塞了几条（`~` 783 ／ `;` 91 ／ `,` 64 ／ `/` 5）
#    ② 归属：复数读音属于主格复数那个词形；`~` 后面的属于别的词形或归属不明
#    ③ 能不能印：源头说「错的/不推荐」⇒ 存但 hidden；不是俄语读音 ⇒ 不收
# ⚠️ 本节所有名单都是**从完整值域里逐个挑出来的枚举**，不是关键词：
#    `М` 在 ru 版是「阳性」（`листопад`/`курдский`），**不是莫斯科** —— 凭印象写成
#    关键词就会给三个词凭空加一个莫斯科口音。

# R2：fr 版把**说明文字**填进了 ipa（全量只有这三句，挂在单字母词头上）。
#    🔴 先试过形式判据「词头无空格而音标有空格」⇒ 命中 14,688 行、绝大多数正当
#      （`ДНК → dɛ ɛn ˈka`、`Сан-Диего`）⇒ 为 8 行误伤上万行，放弃，改枚举。
IPA_PROSE = frozenset({"se prononce", "ceux comprenant la séquence", "en russe,", "en russe"})

# 不是俄语读音（整条不收）
NOT_RUSSIAN_TAGS = frozenset({"Mandarin", "Standard-Chinese", "Sinological-IPA"})   # zh-t `且聽下回分解`
# ⚠️ **vi 版 `phonetic respelling` 57 条是正当 IPA，收。** 我第一版把它列成「不是 IPA」——
#    **只看了标签名没看数据**。全量 57 条逐条读过：`цитадель → [t͡sɨtɐˈdɛlʲ]`、`В → [vɐˈstok]`
#    （缩写的读法）—— 标签说的是「这条 IPA 是**按注音拼写生成的**」，不是「这一格是注音拼写」。
#    （与本节头 `М` 同一个教训：**名单要从数据里挑，不从字面意思猜**。）
NOT_IPA_RAW = frozenset()

# 源头说这条读音**错了**／**不推荐** ⇒ 存、但不印（hidden_why 说清是哪一种）。
#   逐个取自完整值域（ru 版 raw_tags／en、zh-t 的 tags），前缀匹配只用在
#   「同一句话后面挂了出处」那种（`неправильно — Аванесов, 1988↓`）。
_HIDE_PREFIX = (
    ("неправильно", "源头标为错误读音"), ("неправ.", "源头标为错误读音"),
    ("грубо неправильно", "源头标为错误读音"),
    ("прост. неправильное произношение", "源头标为错误读音"),
    ("не рекомендуется", "源头标为不推荐"), ("нерекомендуем", "源头标为不推荐"),
    ("не рекомендуемое", "源头标为不推荐"), ("не рек.", "源头标为不推荐"),
)
_HIDE_TAGS = {"proscribed": "源头标为错误读音"}

# B10（2026-10-29）：**内容**不是 IPA ⇒ 存、但不印。IPA 一个都不会合法出现的 ASCII
#   （大写/数字/反引号/反斜杠/下划线，IPA 的小型大写是单独码位）∪ HTML 实体 —— 与另九门同一份判据。
#   实测 4 行：`сердечный → 5`、`во → v0`（fr 版）、两条读音粘成一串中间夹 `0`。
#   ⚠️ 只在源头标签**没说**要藏时才用它：源头的话优先，这条是我们看内容判的。
NOT_IPA = re.compile(r"[A-Z0-9`\\_]|&(#\d+|#x[0-9a-fA-F]+|[a-z]+);")
NOT_IPA_WHY = "不是 IPA（B10）"

# 地域：**只收能确定是「这条读音属于哪里」的**。其余一律 unknown，原词留在 tags。
#   🔴 fr 版的 `Russie (Saint-Pétersbourg)` **不在这里**：99.7% 与录音同对象 ⇒ 录音者所在地。
#   🔴 `М` 不在这里（见本节头）；`圣彼得堡或过时` 这种「A 或 B」不在这里（判不出是哪个）。
DIALECT_MAP = {
    "Moscow": "Moscow", "Saint-Petersburg": "Saint-Petersburg", "Ukraine": "Ukraine",
    "Southern": "Southern", "Northern": "Northern",
    "СПб": "Saint-Petersburg", "Москва": "Moscow", "московская норма": "Moscow", "моск.": "Moscow",
    "聖彼得堡": "Saint-Petersburg", "莫斯科": "Moscow", "烏克蘭": "Ukraine",
    "白俄羅斯": "Belarus", "南部俄語": "Southern",
}

_IPA_SEP_KEEP_ALL = re.compile(r"\s*(?:;|,|//| / )\s*")


def _has_cyrillic(s):
    return any("CYRILLIC" in ud.name(ch, "") for ch in s)


def pronunciation_parts(raw, tags=(), raw_tags=(), word=None):
    """一格 `sounds[].ipa` → `(kind, [(ipa, notation, part_no), …])`。

    kind == "ok" 才有内容；其余每一种拒收都有自己的名字（一个都不沉进「其他」）。
    `part_no` 是这一格里的第几条（`src_ref` 要用它保证唯一）。
    """
    t = (raw or "").strip()
    if not t:
        return "空", []
    if t in IPA_PROSE or t.strip("\\[]/ ") in IPA_PROSE:
        return "🔴 说明文字填进了 ipa（R2）", []
    if set(tags) & NOT_RUSSIAN_TAGS:
        return "不是俄语读音（%s）" % "/".join(sorted(set(tags) & NOT_RUSSIAN_TAGS)), []
    if set(raw_tags) & NOT_IPA_RAW:
        return "不是 IPA（注音式拼写）", []
    # 记音类型看**整格**（`[a ~ b]` 的方括号包着整格；`ˈa] // [b` 的方括号在中间）
    if "[" in t or "]" in t:
        notation = "narrow"
    elif t[0] in "/\\":
        notation = "phonemic"
    else:
        notation = "unmarked"
    if "phoneme" in tags:
        notation = "phonemic"
    # ② `~`：只收第一条（见本节头 ②），后面的计数不收
    dropped = 0
    if "~" in t:
        segs = t.split("~")
        dropped = len(segs) - 1
        t = segs[0]
    # ① 其余分隔符：同一个词的读音变体，**全收**
    t = re.sub(r"\s+/\s+|\s*//\s*", ";", t)
    for ch in "[]\\/":
        t = t.replace(ch, "")
    # 🔴 词头自己带 `,`/`;`（谚语）⇒ 音标里的那个是**标点**，不是「变体分隔」，不拆。
    #    实测现在是 0（七源给谚语注音都省掉了标点）——**现状碰巧安全不等于判据安全**。
    if word and ("," in word or ";" in word):
        parts = [t.strip()]
    else:
        parts = [p.strip() for p in _IPA_SEP_KEEP_ALL.split(t)]
    out, bad = [], []
    for i, p in enumerate(parts):
        if not p:
            continue
        if _has_cyrillic(p):
            bad.append("含西里尔字母")          # `мн. ч. [...]`／`/х/` 那种
            continue
        if p.endswith("-") and not (raw or "").lstrip("[/\\").startswith("-"):
            bad.append("残缺的半截（`[ɔd-]`）")
            continue
        p = normalize_ipa(p)                     # 键盘字符顶替 IPA 字符（R6）
        if has_stray_apostrophe(p):
            bad.append("撇号用法判不出（多个，或与 ˈ 并存）")
            continue
        out.append((p, notation, i))
    if not out:
        return ("🔴 一条可收的都没有（%s）" % "/".join(sorted(set(bad)))) if bad else "空", []
    kind = "ok"
    if dropped:
        kind = "ok·~后丢弃%d条" % dropped
    return kind, out


def pronunciation_status(tags=(), raw_tags=(), ipa=None):
    """→ `(dialect, hidden, hidden_why)`。地域只看源头标签，**一条都不猜**；
    藏不藏先看源头标签，源头没说时再看 `ipa` 的内容是不是 IPA（`NOT_IPA`）。"""
    why = None
    for t in tags:
        if t in _HIDE_TAGS:
            why = _HIDE_TAGS[t]
    for t in raw_tags:
        for pre, w in _HIDE_PREFIX:
            if t.startswith(pre):
                why = why or w
    if why is None and ipa and NOT_IPA.search(ipa):
        why = NOT_IPA_WHY
    ds = {DIALECT_MAP[t] for t in list(tags) + list(raw_tags) if t in DIALECT_MAP}
    dialect = ds.pop() if len(ds) == 1 else "unknown"   # 两个地域并列 ⇒ 判不出，不猜
    return dialect, (1 if why else 0), why


def pronunciation_target(tags):
    """→ `"self"` ／ `"plural"` ／ `None`（归属不明，不收）。

    🔴 ru 版 `tags: plural` 的那条是**主格复数那个词形**的读音（`агат → [ɐˈɡatɨ]`）——
       挂在词元上就是张冠李戴。单复数同标（pl 版 `рак → ˈrakʲɪ ['singular','plural']`）
       判不出属于谁 ⇒ 不收。
    """
    ts = set(tags)
    if {"singular", "plural"} <= ts:
        return None
    return "plural" if "plural" in ts else "self"


def nominative_plural(e):
    """同一 entry 的 `forms` 里**唯一**的主格复数（剥重音、去 `*`）。不唯一或没有 ⇒ None。"""
    got = set()
    for f in e.get("forms") or []:
        ts = set(f.get("tags") or [])
        if {"nominative", "plural"} <= ts and not (ts & NON_FORM_TAGS):
            v = strip_stress((f.get("form") or "").strip().lstrip("*"))
            if v and _has_cyrillic(v):
                got.add(v)
    return got.pop() if len(got) == 1 else None


# ══════════════════════════════════════════════════════════════════════════
# ⑩ 义项层：**哪条源义项出版、出版什么文本、标签进哪个桶**（阶段 5a，ru-crit-13）
# ══════════════════════════════════════════════════════════════════════════
# 依据 RU_PLAN §十二（探针 `probe_sense_layer.py`）。
# 🔴 **不跨版合并义项**（照 vi）：一条源义项 ＝ 一条 `sense`，带它自己的语言。
#    几版之间没有对齐信息，合并就是编；分开可逆、合并不可逆。
# 🔴 **三语方针**（`[[gloss-three-languages]]`）：只有 en/ru/zh 出版；fr/vi/pl 进证据层、不出版。

SENSE_LANG = {"en-edition": "en", "ru-edition": "ru", "zh-edition-simp": "zh",
              "zh-edition-trad": "zh", "fr-edition": "fr", "vi-edition": "vi",
              "pl-edition": "pl"}
PUBLISH_LANGS = frozenset({"en", "ru", "zh"})

# 实体级指针：整个条目就是「X 的某个形式」（ru-crit-9/10 的那两条路 ＋ `word.form_of`）
_ENTITY_POINTER_VIA = frozenset({"word.form_of", "word.tags:form-of",
                                 "word.tags:participle+全部义项",
                                 "word.tags:gerund+分类·副动词"})


def sense_pointer_via(s, entity_via):
    """这条源义项是不是指针（「X 的某格／某形式」，不是释义）。→ 认出它的那条路 或 None。

    `entity_via` ＝ `is_inflected_form(e)[1]`。实体级的路（fr 版姓氏变格、ru 版形动词页）
    让条目里**每一个**义项都是指针；义项级的只管它自己。
    """
    if s.get("form_of"):
        return "sense.form_of"
    if s.get("alt_of"):
        return "sense.alt_of"
    if "form-of" in (s.get("tags") or []):
        return "sense.tags:form-of"
    if entity_via in _ENTITY_POINTER_VIA:
        return "实体级·" + entity_via
    return None


def sense_pointer_target(s):
    """指针的目标。**只取结构字段**（vi 的 W15：不从散文里抠）。取不到就 None。"""
    for k in ("form_of", "alt_of"):
        for it in s.get(k) or []:
            if isinstance(it, dict) and (it.get("word") or "").strip():
                return it["word"].strip()
    return None


def sense_text(glosses):
    """`glosses` 列表 → 出版文本。

    🔴 子义项的列表把父释义放在前面（en `за`：`[with accusative] ⟫ about`）。
       实测 en 版带父层的可出版义项 347 条，**父层每一条都有意义**（`[with dative]`／
       `Places in Russia:`／`a surname, Vitkov`）—— 只留子层，`за → about` 就丢了「接第四格」。
       ⇒ 拼起来：父层是方括号/圆括号标签或以冒号结尾 ⇒ 空格接；否则 ` — ` 接。
    """
    gl = [g.strip() for g in (glosses or []) if g and g.strip()]
    if not gl:
        return ""
    out = gl[0]
    for g in gl[1:]:
        if out.endswith(":") or out.endswith("：") or out[:1] in "[(（":
            out = out + " " + g
        else:
            out = out + " — " + g
    return out


# 义项级 tags 里**语法性**的那些（照 §C 完整值域逐个挑）。其余是语体/地域/语义标签 ⇒ `label`。
# ⚠️ 这张表决定 bucket，不决定收不收 —— 漏挑一个只是把它放进 `label`，**不丢**。
GRAMMAR_TAGS = frozenset({
    # 格／数／人称／时／式／态／体
    "nominative", "genitive", "dative", "accusative", "instrumental", "prepositional",
    "locative", "partitive", "vocative", "singular", "plural", "dual",
    "first-person", "second-person", "third-person", "past", "present", "future",
    "indicative", "imperative", "subjunctive", "conditional", "infinitive",
    "active", "passive", "reflexive", "imperfective", "perfective", "biaspectual",
    # 性／有生
    "masculine", "feminine", "neuter", "common", "animate", "inanimate",
    # 及物与动词类
    "transitive", "intransitive", "ditransitive", "impersonal", "pronominal",
    "semelefactive", "iterative",
    # 形式
    "participle", "adverbial", "short-form", "comparative", "superlative",
    "indeclinable", "uncountable", "countable", "plural-only", "singular-only",
    "plural-normally", "in-plural", "collective", "predicative", "relational",
    "attributive", "no-comparative", "noun-from-verb", "abstract-noun",
    "demonstrative", "interrogative", "indefinite", "possessive",
})
_STRUCTURAL_TAGS = frozenset({"form-of", "alt-of"})   # 指针的结构标记，不是标签


def sense_tags(s):
    """一条源义项 → `[(bucket, value)]`。源头原词，不改写。"""
    out = []
    for t in s.get("tags") or []:
        if t in _STRUCTURAL_TAGS:
            continue
        out.append(("grammar" if t in GRAMMAR_TAGS else "label", t))
    for t in s.get("raw_tags") or []:
        out.append(("raw", t))
    for t in s.get("topics") or []:
        out.append(("topic", t))
    return out


_RU_LABELS_ONLY = re.compile(r"(?:[а-яё\-]{2,10}\.)(?:[,\s]+[а-яё\-]{2,10}\.)*")


def sense_hidden_why(lang, text):
    """出版层的义项要不要藏。→ None（印）或原因。

    zh 版三桶（`zh_gloss_kind`）：`real` 印；`mixed` 先藏（R3：要先切才能用）；`meta` 藏
    （「брело́к 的形容词」这种元描述，读者得不到词义）。
    ⚠️ 藏 ≠ 删：`sense` 行在、`sense_gloss` 在，判据翻案一条 UPDATE 就放出来。
    """
    # 🔴 **先判「没有字母」再判 zh 三桶**：第一版顺序反了，zh-s 约 90 条整串是 `,` 的释义
    #    被 `zh_gloss_kind` 判成 meta，理由记成「元描述」—— **标错原因比不标更坏**，
    #    以后有人按「元描述」去修，查到的是标点残渣。（ru 版 `(?)`/`??` 是「释义待补」。）
    #    ⚠️ 「没有字母」不含数字：`тысяча → 1000` 这种是正确释义（vi W12：按长度清误伤 503 条）——
    #       实测出版候选里全数字的 0 条，这一句是给将来的。
    if not any(ch.isalpha() or ch.isdigit() for ch in text):
        return "没有字母（整串是标点/符号）"
    # 🔴 ru 版**只有语体/领域缩写、没有释义**（198 条，5b 开跑前量这一列时逮到的）：
    #    `прыжок с шестом → спорт.`／`змеёныш → разг., бран. уничиж.`／`Седна → мифол.`
    #    —— 源头漏写了释义。译成「〈体〉」印成释义读者什么都得不到，还白花钱。
    #    判据：每一段都是「2–10 个小写西里尔字母＋句点」，段间只有逗号/空白。
    if lang == "ru" and _RU_LABELS_ONLY.fullmatch(text.strip()):
        return "只有语体/领域标签、没有释义（源头漏写）"
    if lang == "zh":
        k = zh_gloss_kind(text)
        if k == "meta":
            return "zh-元描述（zh_gloss_kind=meta）"
        if k == "mixed":
            return "zh-中俄混排待切（R3）"
    return None


_WIKI_LIST = re.compile(r"^[#*]+[:*]*\s*")


def zh_gloss_tidy(text):
    """zh 出版文本的**最小**清洗：去行首 wiki 列表标记（`#::`）＋ 去完全重复的行。

    2026-10-23 抽读 zh-s real 桶 40 条：40/40 含真释义（污染 0，判据不作废），
    而 ~27% 带纸质词典残渣。**只动两种读者看见就是乱码/重复的**：
      · `#::Сего́дня…` 的 `#::` —— wiki 列表标记，不是内容
      · `计量学 ⏎ … ⏎ 计量学` 一字不差的重复行
    ⚠️ 变位词尾（`-лен, -льна`）、例句、`见X` 交叉引用**不动** —— 它们也是词典内容，
       「哪一截是释义」要人眼划线，那是 R3 的完整清洗。证据层永远留原文。
    """
    out, seen = [], set()
    for ln in (text or "").split("\n"):
        t = _WIKI_LIST.sub("", ln).strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════════════
# ⑪ 例句层：**哪条源例句出版、出版什么正文、译文算哪种语言**（阶段 6a，ru-crit-16）
# ══════════════════════════════════════════════════════════════════════════
# 依据：`ru/probes/probe_stage6.py` §A–§D（存档 `data/work/ru/probe/probe_stage6.txt`），
# 加上三份补量（en 拉丁多数／zh-s 配对／多行组成），2026-10-23。
#
# ═══ 两列：`text` 是证据（与 dump 逐字相等），`text_pub` 是印给读者的 ═══
# 🔴 vi 的 W22：四种清洗**原地改 `text`**、第五种只算出版正文 ⇒「`example.text` 是证据层还是
#    出版层」有两个答案。ru 从第一天分开：`text` 一个字不动（外锚闸拿它与 dump 逐字比），
#    清洗只产出 `text_pub`（NULL ＝ 与 `text` 相同），**付费翻译也只翻 `text_pub`**。
#
# ═══ 译文的语种**按版定，不按字段名定**（vi ②）═══
EX_TR_LANG = {
    "en-edition": "en",          # `english`/`translation`，26,954 条
    "zh-edition-trad": "zh",     # 12,750 条 —— 白送的中文
    "zh-edition-simp": "zh",     # 字段里 508 条；**另有 ~1.1 万条中文挤在正文里**，见 `zh_simp_pairs`
    # 🔴 ru 版 93 条 `translation` **不是译文**：47 条是俄语解说（`опоить → О том, кто находится…`），
    #    45 条是**被译成俄语的原文**（法语/拉丁语/英语，`под ружьё → Après avoir fait…`）。
    "ru-edition": None,
    # 第四语言（`[[gloss-three-languages]]`）：**有意不收，不是源头没有**
    #   fr 8,458 ／ vi 25,724 ／ pl 1,603 都在源头里。推翻：三语方针放宽。
    "fr-edition": None, "vi-edition": None, "pl-edition": None,
}

_EN_PLACEHOLDER = re.compile(r"(?i)please add an English translation")


def example_gloss(src, x):
    """一条源例句 → `(lang, 译文)` 或 None（这一条没有**可出版**的译文）。

    🔴 两条形状检查**只挡读者一看就是错的**：
      · en：要有拉丁字母、且不是 `(please add an English translation of this quotation)` 占位串
        （探针：`куб → 2³`、`Индра → 46`）
      · zh：要有汉字 —— zh-t 版 100 条「译文」是英文（`с небольши́м → slightly more than`），
        **不把它挪成 en**：那是源头放错了格，挪过去就是我替源头做决定。
    """
    lang = EX_TR_LANG.get(src)
    if not lang:
        return None
    tr = (x.get("translation") or x.get("english") or "").strip()
    if not tr:
        return None
    if lang == "en":
        if _EN_PLACEHOLDER.search(tr) or not re.search(r"[A-Za-z]", tr):
            return None
    elif lang == "zh":
        if not _CJK.search(tr):
            return None
    return lang, tr


# ── 出版正文的清洗：每一种都是**读者一看就知道不是例句内容**的东西 ──
# fr 版把法语译文挤在正文里：`беречь деньги : conserver de l’argent.`（探针 §B，~1,000 条）
#   —— 法语不进三语，印出来就是读者读不懂的半句。⚠️ 只切「头有西里尔、尾一个西里尔都没有」的，
#   `мне пришло́сь (+ infinitif) : il m’a fallu…` 这种切了也安全，`X : Y` 两边都是俄语的不切。
_FR_TAIL = re.compile(r"\s+:\s+(?=[^:]*$)")
# 🔴 只剥 `◆`（ru 版例句模板的项目符号）。**`..`／`...` 不剥** —— 那是 НКРЯ 的**删节号**
#    （「此前有省略」），是内容；第一版连它一起剥，`... редкая рыба` 被剥成 `. редкая рыба`
#    （抽读 25 条逮到的，2026-10-23）。
_LEAD_MARK = re.compile(r"^◆\s*")
_WIKI_LINE = re.compile(r"^\s*#")            # 下一个义项的定义行漏进来了（`боязненный`）


def example_text_pub(src, text):
    """`text`（dump 原文）→ 出版正文。与原文相同时返回原文本身。"""
    t = (text or "").strip()
    lines = t.split("\n")
    if len(lines) > 1:
        keep = []
        for ln in lines:
            if _WIKI_LINE.match(ln):
                break                         # 定义行之后全是下一个义项的东西
            # en 版多行里夹着转写行/英译行/出处行（`Russian Synodal Bible, Mark 1.42:`）：
            # 有拉丁字母而一个西里尔都没有 ⇒ 不是俄语正文。**纯标点行（`[…]`）留着**——诗的省略号
            if re.search(r"[A-Za-z]", ln) and not _has_cyrillic(ln):
                continue
            keep.append(ln)
        t = "\n".join(keep).strip() or t
    t = _LEAD_MARK.sub("", t).strip() or t
    if src == "fr-edition":
        m = _FR_TAIL.search(t)
        if m and _has_cyrillic(t[:m.start()]) and not _has_cyrillic(t[m.end():]):
            t = t[:m.start()].rstrip()
    return t


# R24（2026-10-25）：en 版多行引文的**首行是出处**（`1848, Давыдов, Дмитрий Павлович (…), “Думы беглеца…”`／
# `1829 (written), 1830 (published), Alexander Pushkin, …`）。它有西里尔字母，上面「拉丁行」那条剥不掉。
# 形状：年份（可带 `c.`／区间／`(written)` 这类括注，可多个、逗号相连）＋ `, ` ＋ 作者……
#   实测 18 条，全是 en 版；**单行例句里 0 条**（`1340-ку́бовый V-твин` 没有 `, ` 不中）。
# ⚠️ 只认 en 版、只认**多行的首行**（vi 6e 的教训：判据按分支写，不共用安全网）。
_CITE_YEAR = r"(?:c\.\s*)?\d{3,4}s?(?:\s*[-–]\s*\d{2,4})?(?:\s*\([a-z ]+\))?"
_CITE_HEAD = re.compile(r"^" + _CITE_YEAR + r"(?:\s*,\s*" + _CITE_YEAR + r")*\s*,\s+\S")


def example_split_citation(src, text_pub):
    """出版正文 → (正文, 出处或 None)。出处搬进 `example.ref`（源头没给 ref 时）。"""
    lines = (text_pub or "").split("\n")
    if src != "en-edition" or len(lines) < 2 or not _CITE_HEAD.match(lines[0]):
        return text_pub, None
    body = "\n".join(lines[1:]).strip()
    if not _has_cyrillic(body):
        return text_pub, None
    return body, lines[0].strip()


_PLACEHOLDER = re.compile(r"(?i)отсутствует пример употребления")
_TEMPLATE_HOLE = re.compile(r"\{\{|\}\}|\{\{\{|exemple\|lang=")
# en 版词缀页的**构词示意式**：`на- (na-) + идти́ (idtí, “to go”) → найти́ (najtí, “to find”)`
#   1,236 条（探针补量），夹着英文释义，不是句子。
_DERIVATION = re.compile(r"\s\+\s.*→|→.*\s\+\s")
# en 版把关系表写成了例句：`Holonyms: кисть (kistʹ), стопа́ (stopá)`／`Coordinate term: карни́з`
_REL_META = re.compile(r"^(?:Holonyms?|Meronyms?|Coordinate terms?|Hypernyms?|Hyponyms?|"
                       r"Synonyms?|Antonyms?|Troponyms?|Related terms?)\s*:", re.I)


def example_hidden_why(src, word, text_pub):
    """出版正文 → None（印）或原因。**顺序即判据**：第一条命中即定案。

    ⚠️ 判据只认「形式上根本不成例句」的，不判「这条例句好不好」（vi ④ 同一条纪律）。
    超长（>600 字符，~670 条）**不藏**：抽读全是真引文（托尔斯泰、列宁、Брокгауз）。
    「拉丁多于西里尔」**不当判据**：`1.II.2010 г.`（日期写法）、`Финалки Windows 10 Mobile` 都是真例句。
    """
    t = (text_pub or "").strip()
    if not any(ch.isalpha() or ch.isdigit() for ch in t):
        return "没有字母（整串是标点/符号）"
    if _PLACEHOLDER.search(t):
        return "占位串（源头写着「缺例句」）"
    if not _has_cyrillic(t):
        return "一个西里尔字母都没有（外语原文/转写/译文串位）"
    if _TEMPLATE_HOLE.search(t):
        return "模板残渣（正文里有个洞）"
    if src == "en-edition" and _DERIVATION.search(t):
        return "构词示意式（词缀页，不是句子）"
    if src == "en-edition" and _REL_META.match(t):
        return "关系元数据（不是例句）"
    if strip_stress(t).strip(" .!?…").lower() == strip_stress(word).strip().lower():
        return "整条就是词头本身"
    return None


# ── zh-s 版：**纸质俄汉词典整段抄进来、例句边界切错了**（R3 在例句层的那一半）──
# 源头一个义项下的 examples 拼起来是 `俄₁ 中₁ 俄₂ 中₂ …`，而切分点落在中文句号后面：
#     [Воро́на ～ает] [乌鸦哇哇叫。] ／ [花朵把草地点缀得五色缤纷。Все сте́ны ～ли от карти́н]
# ⇒ 按单条读，1,587 条「例句」一个西里尔都没有、7,968 条俄中混排。
# ⭐ **按文字系统的交界重切**：把一个义项的全部正文拼起来，按「西里尔段／汉字段」交替切成对。
#    实测 11,252 条所在的义项整串严格交替（探针补量）。
# 🔴 收的条件写严：**每一对都要过**（俄段有 ≥2 个西里尔字母且括号配平、中段有 ≥2 个汉字且括号配平），
#    任何一对不过 ⇒ **整个义项不收**（宁缺：`Вино́(或хмель)` 会把「或」切成一个中文段，
#    交替照样成立而配对全错一格 —— 配平检查拦的就是它）。
# ⚠️ `‖` 之后是派生词条（`подка́тка〔阴〕(用于①解)`），不是例句 ⇒ 截掉。
# ⚠️ `～` 是纸质词典的「代词头」记号（`～ает` ＝ 词干＋ает）。**不展开** —— 词干在哪儿断
#    源头没给，展开就是猜（R23）。
_ZH_PUNCT = "。，；：？！、（）《》“”〈〉【】…〔〕"


def _zh_cls(ch):
    n = ud.name(ch, "")
    if "CYRILLIC" in n or ch in "～~" or "COMBINING" in n:
        return "C"
    if "CJK" in n or ch in _ZH_PUNCT or "FULLWIDTH" in n or "IDEOGRAPHIC" in n:
        return "H"
    return "L" if ch.isalpha() else "N"


def _balanced(s):
    for a, b in ("()", "（）", "〈〉", "〔〕", "«»", "[]"):
        if s.count(a) != s.count(b):
            return False
    return True


def zh_simp_pairs(texts):
    """一个义项的 zh-s 例句正文（源头顺序）→ `[(俄, 中), …]` 或 None（切不开 ⇒ 整义项不收）。"""
    blob = " ".join(t for t in texts if t)
    blob = blob.split("‖", 1)[0]
    runs = []
    for ch in blob:
        k = _zh_cls(ch)
        if k in "NL":
            if runs:
                runs[-1][1].append(ch)
            else:
                runs.append(["N", [ch]])
            continue
        if runs and runs[-1][0] == k:
            runs[-1][1].append(ch)
        elif runs and runs[-1][0] == "N":
            runs[-1] = [k, runs[-1][1] + [ch]]
        else:
            runs.append([k, [ch]])
    segs = [(k, "".join(c).strip()) for k, c in runs if "".join(c).strip()]
    if not segs or len(segs) % 2 or any(k != "CH"[i % 2] for i, (k, _s) in enumerate(segs)):
        return None
    out = []
    for i in range(0, len(segs), 2):
        ru, zh = segs[i][1], segs[i + 1][1]
        if (sum(1 for ch in ru if "CYRILLIC" in ud.name(ch, "")) < 2
                or len(_CJK.findall(zh)) < 2 or not _balanced(ru) or not _balanced(zh)):
            return None
        out.append((ru, zh))
    return out


# ══════════════════════════════════════════════════════════════════════════
# ⑫ 关系层：**源头字段 → kind、目标清洗、词族分组标签**（阶段 6b，ru-crit-16）
# ══════════════════════════════════════════════════════════════════════════
# 依据：`ru/probes/probe_stage6.py` §E/§F/§F2（存档 `data/work/ru/probe/probe_stage6.txt`）。
#
# ═══ 值域就是这张表，认不出的源头字段一律报红（vi ⑤）═══
REL_KINDS = {
    "synonyms": "synonym", "antonyms": "antonym",
    "hypernyms": "hypernym", "hyponyms": "hyponym",
    "meronyms": "meronym", "holonyms": "holonym", "troponyms": "troponym",
    "coordinate_terms": "coordinate", "derived": "derived", "related": "related",
    "descendants": "descendant", "proverbs": "proverb", "abbreviations": "abbreviation",
    "paronyms": "paronym",        # fr 版 145 条。**语音关系**，不吞 related（vi B17）
}
# 🔴 ru 版的 `related` **不是**「相关词」，是 «Родственные слова» 构词词族（RU_PLAN §5.3，外审两家一致）
WORD_FAMILY_SRC = frozenset({"ru-edition"})
# **有意不收**（每条写推翻条件，`PLAYBOOK` 7.5）：
REL_NOT_COLLECTED = {
    "anagrams": "字母重排（ru 版 61,421／fr 29）—— 文字游戏，不是词汇关系。推翻：做「字谜/词游戏」功能时",
    "metagrams": "换一个字母得到的词（ru 版 4,029）—— 同上",
    "translations": "译文表（ru 版 64.9 万）—— 是「这个词在别的语言里怎么说」，三语之外的不收；"
                    "**其中 zh 那几条可能是白送的中文释义**，阶段 5 没用 ⇒ R26",
}

# B17：兜底 `related` 只被**语义上更具体**的 kind 吞掉。排除 paronym（语音）与 related 自己。
#   ⭐ `word_family` 在吞的一方：同根词族比「相关词」具体。
REL_SUBSUME = frozenset(set(REL_KINDS.values()) | {"word_family", "aspect_pair"}) - {"related", "paronym"}
REL_REDUNDANT = "related 与更具体的关系重复（B17）"
REL_DUP = "同条目同 kind 同目标重复"


def relation_kind(src, field):
    """→ kind；`None` ＝ 有意不收；**认不出抛 KeyError**（不许静默归 related）。"""
    if field in REL_NOT_COLLECTED:
        return None
    k = REL_KINDS[field]
    if k == "related" and src in WORD_FAMILY_SRC:
        return "word_family"
    return k


# ── 目标清洗：每一条都只动**格式**、不动意思，各自计数 ──
_TGT_NUM_PREFIX = re.compile(r"^\d+:\s*")                       # en 数词框 `100: сто`
_TGT_GLOSS_TAIL = re.compile(r"\s+[—–-]\s+[^Ѐ-ӿ]+$")   # `ФСБ — FSB`
_TGT_ROMAN_PAREN = re.compile(r"\s*\(([^()Ѐ-ӿ]*)\)\s*$")   # `Блинолопатия (Blinolopatija)`
_TGT_MARKUP = re.compile(r"\[\[|\]\]|\]>|<|>|\{\{|\}\}|&nbsp;|&[a-z]+;")


def relation_target(item, kind):
    """关系项 → `(目标, 清洗了什么 or None, 丢弃原因 or None)`。

    🔴 目标不是俄语就丢（en 版 `descendants` 是**别的语言**的后代词：`указ → ukase`）。
       判据先看源头的 `lang_code`，再看文字：一个西里尔字母都没有的只在 `abbreviation` 里留
       （`мегабайт → MB`／`ВКонтакте → VK` 是俄语里真用的缩写）。
    ⚠️ `?`／`&nbsp;`／`-`／en 版小标题 `Phrases`/`Proverbs`/`Borrowed` 都是「没有西里尔」挡下的。
    """
    t = (item.get("word") or "").strip()
    if not t:
        return None, None, "目标空"
    lc = item.get("lang_code")
    if lc and lc != "ru":
        return None, None, "目标是别的语言（有 lang_code 且不是 ru）"
    if _TGT_MARKUP.search(t):
        return None, None, "目标带标记残渣"
    fixed = []
    m = _TGT_NUM_PREFIX.match(t)
    if m:
        t, _ = t[m.end():], fixed.append("数字前缀")
    # pl 版 `ze względu na płeć: де́душка`：冒号前是波兰语说明
    if ": " in t and not _has_cyrillic(t.split(": ", 1)[0]):
        t, _ = t.split(": ", 1)[1].strip(), fixed.append("外语说明前缀")
    m = _TGT_GLOSS_TAIL.search(t)
    if m and _has_cyrillic(t[:m.start()]):
        t, _ = t[:m.start()].strip(), fixed.append("外语释义尾巴")
    m = _TGT_ROMAN_PAREN.search(t)
    if m and _has_cyrillic(t[:m.start()]) and re.search(r"[A-Za-z]", m.group(1)):
        t, _ = t[:m.start()].strip(), fixed.append("转写括号")
    if not _has_cyrillic(t):
        if kind == "abbreviation" and any(ch.isalnum() or ch in "₽№µ" for ch in t):
            return t, ("+".join(fixed) or None), None
        return None, None, "目标一个西里尔字母都没有"
    return t, ("+".join(fixed) or None), None


# ── 构词词族（ru 版 «Родственные слова»）的分组标签：**白名单**，认不出的是残渣（R10）──
# 🔴 探针 §F：540 种 raw_tags，其中大量是**上一项的词漏进了标签**（`, полпизды` 116,844／
#    `двупыльник` 22,794）—— 它把真的词性分组（`существительные`）**顶掉了**，而那一项本身
#    仍是词族成员（`полвека → полпирога`）⇒ **关系照收，分组记 NULL**，残渣计数，不猜它原来是哪组。
# ⚠️ 值域统一成一套键（ko K8/K10：一列两套值域 ⇒ 数的是「有值的行」不是「有信息的行」）：
#    源头的俄语分组标签与 wiktextract 已归一的英文 tags 映射到同一套键。展示层查 dict-labels。
FAMILY_POS = {
    "существительные": "noun", "прилагательные": "adjective", "глаголы": "verb",
    "наречия": "adverb", "числительные": "numeral", "частицы": "particle", "союзы": "conjunction",
    "местоимения": "pronoun", "междометия": "interjection", "предлоги": "preposition",
    "вводные слова": "parenthetical", "имена-собственные": "proper-noun",
    # wiktextract 归一过的 tags
    "adverb": "adverb", "participle": "participle", "adverbial": "adverbial",
    "proper-noun": "proper-noun", "interjection": "interjection", "noun": "noun",
    "adjective": "adjective", "verb": "verb", "numeral": "numeral",
    # 第一版漏的四个（干跑后把「残渣」里的 ASCII 标签全打出来才看见，2026-10-23）：
    #   `predicative` 11,791（предикативы：`да → незадача`）／`pronoun` 3,598／
    #   `prepositional` 2,036（предлоги：`в → во`、`среда → посередине`）
    "predicative": "predicative", "pronoun": "pronoun", "prepositional": "preposition",
}
# `superior` 6,512 是**比较级形式的分组**（`красный → краснейший`），不是词性 ⇒ 进构词分组
_FAMILY_FORM = (
    # (前缀, 键) —— 前缀匹配：`Ближайшее родство (кредитно-финансовое учреждение)` 后面的括号是义项提示
    ("Ближайшее родство", "closest"), ("ближайшее родство", "closest"), ("ближнее родство", "closest"),
    ("Непосредственное родство", "closest"), ("непосредственное родство", "closest"),
    ("родство по корню", "closest"), ("Родственные к", "closest"),
    ("уменьш.-ласк. формы", "diminutive"), ("уничиж. формы", "pejorative"),
    ("увелич. формы", "augmentative"), ("усилит. формы", "intensive"),
    ("разговорная форма", "colloquial"), ("фамилии", "surname"),
    ("отчество женщины", "patronymic-f"), ("отчество мужчины", "patronymic-m"),
    ("этнонимы", "ethnonym"), ("квазитопонимы", "quasi-toponym"), ("toponymic", "toponym"),
    ("Избранные примеры", "selected-examples"), ("Производные слова", "derived-words"),
    ("superior", "superlative"),
)


FAMILY_FORM_KEYS = []
for _pre, _k in _FAMILY_FORM:
    if _k not in FAMILY_FORM_KEYS:
        FAMILY_FORM_KEYS.append(_k)


def family_groups(item):
    """→ `(rel_group, form_group, 残渣标签列表, 冲突数)`。

    · `rel_group`：一个词性键。🔴 `adverbial`＋`participle` 是**一个**类（副动词，77,907 条），
      第一版把它算成「两个分组冲突」—— 合成 `adverbial-participle`。
    · `form_group`：构词分组键，**可以多个、按固定顺序用 `+` 连**（`closest+diminutive`）。
      「最近亲属」与「指小形式」是两个正交的维度（源头 7,253 条同时给），不是冲突。
      值域仍是可枚举的（`FAMILY_FORM_KEYS` 的组合）。
    """
    pos, forms, junk = [], [], []
    for t in list(item.get("raw_tags") or []) + list(item.get("tags") or []):
        if t in FAMILY_POS:
            if FAMILY_POS[t] not in pos:
                pos.append(FAMILY_POS[t])
            continue
        for pre, key in _FAMILY_FORM:
            if t.startswith(pre):
                if key not in forms:
                    forms.append(key)
                break
        else:
            junk.append(t)
    if "adverbial" in pos and "participle" in pos:
        pos = ["adverbial-participle"] + [p for p in pos if p not in ("adverbial", "participle")]
    rel = pos[0] if pos else None
    forms.sort(key=FAMILY_FORM_KEYS.index)
    return rel, ("+".join(forms) or None), junk, max(0, len(pos) - 1)


# ── 体对（aspect_pair）：**按字段分支**，不按 tag 名合并（RU_PLAN §5.2 ①）──
# en 版 `forms[]` 带 perfective/imperfective 且**不带** infinitive/canonical 的那一行 ＝ 体对伙伴
#   （`показать → пока́зывать`）；带 infinitive/canonical 的是**这个词自己**（探针 §F2）。
# zh 版 `forms[]` 带体标签 ＝ 体对伙伴（`купить → покупа́ть`）。
# 🔴 其余标签只认这几个；带别的（`error-unknown-tag`+`noun-from-verb`：`принудить → принуди́ловка`）
#    **不是体对**、不收。
ASPECT_TAGS = frozenset({"perfective", "imperfective", "biaspectual"})
ASPECT_SUBKIND = {"semelfactive": "semelfactive", "suppletive": "suppletive", "emphatic": "emphatic"}
_ASPECT_OK_EXTRA = frozenset(ASPECT_SUBKIND) | {"dated", "obsolete", "rare"}
_ASPECT_SELF = frozenset({"infinitive", "canonical"})
ASPECT_PAIR_SRC = frozenset({"en-edition", "zh-edition-trad", "zh-edition-simp"})


def aspect_partner(src, form):
    """动词的一行 `forms[]` → `(目标, subkind)` 或 None（不是体对伙伴）。"""
    if src not in ASPECT_PAIR_SRC:
        return None
    tg = set(form.get("tags") or [])
    if not tg & ASPECT_TAGS or tg & _ASPECT_SELF:
        return None
    if tg - ASPECT_TAGS - _ASPECT_OK_EXTRA:
        return None
    t = (form.get("form") or "").strip()
    if not t or not _has_cyrillic(t):
        return None
    sub = sorted(ASPECT_SUBKIND[x] for x in tg if x in ASPECT_SUBKIND)
    return t, ("+".join(sub) or None)


# ══════════════════════════════════════════════════════════════════════════
# ⑬ 录音层：**挑哪个 URL、归一键、挂谁、能不能播**（阶段 6c，ru-crit-16）
# ══════════════════════════════════════════════════════════════════════════
# 依据：`ru/probes/probe_stage6.py` §G。挂靠照音标层（`pronunciation_target`／`nominative_plural`）：
# ru 版 `tags: plural` 的录音是主格复数那个词形的（6,155 singular／246 plural），挂到词元上就是张冠李戴。
AUDIO_URL_PREF = ("ogg_url", "mp3_url", "wav_url", "oga_url", "flac_url", "opus_url")


def audio_url(sound):
    for k in AUDIO_URL_PREF:
        if sound.get(k):
            return sound[k]
    return None


def commons_key(sound):
    """MediaWiki 标题归一：原文件名、URL 解码、`_`→空格、首字母大写。

    🔴 B12：同一条录音在 `ogg_url`／`mp3_url`（转码）里是两个 URL ⇒ 按 URL 去重并不到一起
       （探针：按 (词,url) 47,822 ／ 按 (词,commons_key) 28,765 ⇒ **39.8% 是重复**）。
       键取 `audio` 字段（源头给的原文件名），没有才从 URL 反推。
    """
    from urllib.parse import unquote
    name = sound.get("audio")
    if not name:
        u = unquote(audio_url(sound) or "")
        m = re.search(r"/([^/]+\.(?:ogg|oga|wav|flac|opus|mp3))/[^/]+$", u, re.I)
        name = m.group(1) if m else u.rsplit("/", 1)[-1]
    name = unquote(name).replace("_", " ").strip()
    if name.lower().startswith("file:"):
        name = name[5:].strip()
    return (name[:1].upper() + name[1:]) if name else None


# ── 张冠李戴：文件名里嵌着被录的那个词，是一把**源头自带的尺子**（vi ⑥）──
# 两种命名，覆盖探针里 ~98% 的录音：
#   `LL-Q7737 (rus)-<录音者>-<词>.wav`（Lingua Libre）  ／  `Ru-<词>.ogg`
# 🔴 录音者名里可能有连字符（`Kolokol-sa`）、甚至西里尔（`Irina (Нейшлотский)`）——
#    第一版探针按「第一个连字符之后」取词，fr 版 195 条「不一致」大半是这个假象。
#    ⇒ 取「去掉括号注释后，**最长的、以西里尔字母开头的西里尔尾段**」当被录的词
#      （`Tatiana Kerbush-дом-интернат` → `дом-интернат`，录的是复合词不是 `интернат`）。
# ⚠️ 括号注释是同形词消歧（`чета (че́та)`／`Стефания (растение)`），先剥掉再比。
_LL_HEAD = re.compile(r"^LL-Q\d+ \([a-z]{3}\)-", re.I)
_RU_HEAD = re.compile(r"^Ru-", re.I)
_EXT = re.compile(r"\.(?:wav|ogg|oga|mp3|flac|opus)$", re.I)
_PAREN = re.compile(r"\s*\([^()]*\)")
# 🔴 第二版（2026-10-24）：第一版干跑报 1,282 条张冠李戴，分堆读完**判据宽了五处**：
#   ① 789 条是**编号录音**（`Ru-сей 2.ogg`／`Ru-мука°2.ogg` ＝ 同一个词的第二条录音）⇒ 剥尾号
#   ② 拉丁转写的文件名（`Ru-Gulag.ogg`／`RU-Belaja gorjachka.ogg`）这把尺子**量不了** ⇒ 返回 None，不是「不一致」
#   ③ 改革前正字法的词头（`міръ`／`Россія`）配现代拼写的录音 ⇒ 是同一个词，折叠时归一
#   ④ 短语文件名里有逗号/破折号（`что посеешь, то и пожнёшь`），尾段在逗号处断了 ⇒ 字符集补上
#   ⑤ 录音者名是西里尔（`Герман Мейстер-Бальзак`）、字母录音命名 `27-буква-Щ`、项目前缀 `wikt-…-Harulover`
#      ⇒ 首尾**没有西里尔**的段先剥；最后一段＝词形且前面的部分像人名（有空格）或是 `буква` ⇒ 一致
# ⚠️ 真不一致的照样藏：`нога ⇐ Ru-ноги.ogg`（录的是复数）、`здравствовать ⇐ Ru-здравствуйте`、
#    `интернат ⇐ …-дом-интернат`（录的是复合词）—— 读者点播放听到的是另一个词。
_CYR_TAIL = re.compile(r"[\u0400-\u04ff][\u0400-\u04ff\u0300-\u036f\d\s'’,;:—–-]*$")
_NUM_SUFFIX = re.compile(r"[\s°_]*\d+$")
_OLD_ORTH = str.maketrans({"і": "и", "ѣ": "е", "ѳ": "ф", "ѵ": "и", "І": "И", "Ѣ": "Е", "Ѳ": "Ф", "Ѵ": "И"})


def _audio_fold(s):
    s = ud.normalize("NFC", s or "").translate(_OLD_ORTH)
    s = strip_stress(s).lower().replace("ё", "е")
    s = re.sub(r"ъ\b", "", s)                     # 改革前的词尾硬音符 `міръ`
    return re.sub(r"[\s\-–—_!?.,;:«»\"'’]+", "", s)


def _trim_segments(s):
    """首尾没有西里尔的 `-` 段剥掉（`wikt-куда-нибудь-Harulover` → `куда-нибудь`；`8-ой` → `ой`）。"""
    seg = s.split("-")
    while seg and not _has_cyrillic(seg[0]):
        seg.pop(0)
    while seg and not _has_cyrillic(seg[-1]):
        seg.pop()
    return "-".join(seg)


def audio_filename_word(key):
    """归一键 → 文件名里被录的词；不是那两种命名、或文件名没有西里尔 ⇒ None（这把尺子量不了）。"""
    if not key:
        return None
    base = _EXT.sub("", key)
    if _RU_HEAD.match(base):
        rest = _RU_HEAD.sub("", base)
    elif _LL_HEAD.match(base):
        m = _CYR_TAIL.search(_PAREN.sub("", _LL_HEAD.sub("", base)).strip())
        rest = m.group(0) if m else ""
    else:
        return None
    rest = _NUM_SUFFIX.sub("", _PAREN.sub("", rest)).strip()
    return rest if _has_cyrillic(rest) else None


def audio_word_matches(word, fw):
    a, b = _audio_fold(_trim_segments(word)), _audio_fold(_trim_segments(fw))
    if a == b:
        return True
    head, sep, last = _trim_segments(fw).rpartition("-")
    if sep and _audio_fold(last) == a and (" " in head.strip() or head.strip().endswith("буква")):
        return True                                # 录音者名 ＋ 词／字母录音
    return False


AUDIO_WRONG_WORD = "录音文件名里的词与这个词形不一致（张冠李戴）"


# ── 第二信号：**源头说这两个词读音一样／是同一个词的异写**（vi：第二信号必须来自源头，不许是我算的）──
# 🔴 第二版干跑剩 235 条，逐条读完分两堆（2026-10-24）：
#    · 编辑**有意**复用同音词的录音：`лесть ⇐ лезть`、`код ⇐ кот`、`что ⇐ што`、`искуство ⇐ искусство`
#      （错拼页挂正确录音）、`4-ый ⇐ четвёртый` —— **录音是对的**，文件名不同是因为读音相同
#    · 真的是另一个词／另一个词形：`нога ⇐ ноги`、`друг ⇐ друзья`、`лисица ⇐ лиса`
#    拼写分不开这两堆；源头分得开：`sounds[].homophones` 41 ／ `senses[].alt_of` 14 ／
#    `forms[alternative]` 4 ／ 几种同时 13 ⇒ **68 条放出来**。
# ⚠️ **`form_of` 有意不算**：它说的是「ноги 是 нога 的一个形式」，而读者在 нога 页上听到 ноги 就是错的
#    （50 条只有 form_of 信号，全是这一类）。
# ⚠️ 剩 115 条无信号的**照藏**：其中有文件名打错字（`Сведрловск`、`анитсептик`）而录音大概是对的，
#    但没有源头信号我判不了 —— 错比缺更伤权威。记 R27。
def audio_same_sound_pairs(e):
    """一个源条目 → 源头声明「读音相同／异写」的无向对（折叠后）。"""
    a = _audio_fold(e.get("word") or "")
    out = set()
    for so in e.get("sounds") or []:
        for k in ("homophones", "homophone"):
            v = so.get(k)
            for h in (v if isinstance(v, list) else [v] if v else []):
                hw = h.get("word") if isinstance(h, dict) else h
                if hw:
                    out.add(frozenset((a, _audio_fold(hw))))
    for sn in e.get("senses") or []:
        for it in sn.get("alt_of") or []:
            if it.get("word"):
                out.add(frozenset((a, _audio_fold(it["word"]))))
    for f in e.get("forms") or []:
        if "alternative" in (f.get("tags") or []) and f.get("form"):
            out.add(frozenset((a, _audio_fold(f["form"]))))
    return out


def audio_hidden_why(word, key, tags=(), raw_tags=(), same_sound=frozenset()):
    """→ None（可播）或原因。先看源头的质量标签（与音标层同一个函数），再看文件名，再看第二信号。"""
    _d, hidden, why = pronunciation_status(tags, raw_tags)
    if hidden:
        return why
    fw = audio_filename_word(key)
    if fw is not None and not audio_word_matches(word, fw):
        if frozenset((_audio_fold(word), _audio_fold(fw))) in same_sound:
            return None
        return AUDIO_WRONG_WORD
    return None


def example_needs_translation(word):
    """这条（可出版的）例句**要不要花钱买中文**。→ bool

    🔴 词缀页（词头以 `-` 开头或结尾：`-тель`、`макро-`）的「例句」是**构词示意**
       （`водить → водитель`）和**词表**（`бойница, варница, звонница`）—— 读者要看的就是俄语本身，
       没有可译的句子。6d 的 1% 切片里 `ком - комь(j)я` 原样退回（模型拒译），回查同类 3,259 条。
    ⚠️ **不藏**：它们照常出版，只是不进付费范围。
    """
    w = (word or "").strip()
    return not (w.startswith("-") or w.endswith("-"))


# ══════════════════════════════════════════════════════════════════════════
# ⑭ 词源层：**字段、清洗、出不出版、来源类型**（阶段 7，ru-crit-17）
# ══════════════════════════════════════════════════════════════════════════
# 依据：`ru/probes/probe_etymology.py`（存档 `data/work/ru/probe/probe_etymology.txt`）＋ 最常见行补量，2026-10-24。
#
# 🔴🔴 **字段名两版不同**：en `etymology_text`（单数），其余 `etymology_texts`（复数）。只认单数 ⇒
#    ru 版报 0 ⇒「只有英文版有词源」（ko K36）。两个都读，**多段全收不设上限**（fr 那轮静默二选一挑错）。
ETYM_FIELDS = ("etymology_text", "etymology_texts")


def etymology_segments(e):
    """一个源条目 → [(段序号, 原文, 字段名)]。"""
    out = []
    if isinstance(e.get("etymology_text"), str) and e["etymology_text"].strip():
        out.append((0, e["etymology_text"], "etymology_text"))
    for i, t in enumerate(e.get("etymology_texts") or []):
        if isinstance(t, str) and t.strip():
            out.append((len(out), t, "etymology_texts"))
    return out


# ── 清洗：每一种都是**读者一看就知道不是词源内容**的东西 ──
# 🔴🔴 ru 版 45.3 万段里 **29.6 万段整段是占位**（`Происходит от ??` 220,230／`От ??` 70,435／`??` 3,122／
#    `Из ??` 1,585／裸 `От` 319…）—— 编辑留空的模板。**这是「源头没给」，不是「我们没收」**：
#    清洗后为空的段不落库，计数单列（读者口径的「有词源」分母不能拿它们充数）。
#    另有 ~7.8 万行是「真内容 ＋ 占位尾巴」（`Происходит от существительного звон, далее от ??`）⇒ 只切尾巴。
_ETYM_PLACEHOLDER_LINE = re.compile(
    r"^(?:(?:Происходит|Образовано|Происхождение|Возможно|Вероятно|Предположительно)\s+)?"
    r"(?:от|из)?\s*(?:\?+)?\s*[.:]?$", re.I)
_ETYM_PLACEHOLDER_TAIL = re.compile(r"[,;]?\s*(?:далее\s+|затем\s+)?(?:от|из)\s+\?\?+\s*\.?\s*$", re.I)
# wiki 维护提示（不是内容）。⚠️ 「Использованы данные словаря М. Фасмера」**不删** —— 那是出处
_ETYM_MAINT = re.compile(r"^(?:Статья нуждается в доработке\.?|Это незаконченная статья\..*|"
                         r"\(См\. Общепринятые правила\)\.?)$")
# 词源树挂件（en `Etymology tree`／zh `詞源樹`／vi `Cây từ nguyên`）：从挂件头一直到**树根那一行**
#   `Russian <词>`／`俄語 <词>`（树根就是词头本身）。🔴 第一版按「节点行不以句号结尾」判，而节点
#   `Proto-Indo-European *h₁énder.` 恰好以句号结尾 ⇒ 挂件只剥了个头。⚠️ **找不到树根就一行都不剥**（宁脏不丢）。
#   另有 `PIE word ⏎  *h₁en` 挂件（en 42 段）。
_ETYM_TREE_HEAD = re.compile(r"^(?:Etymology tree|詞源樹|词源树|Cây từ nguyên)$")
_ETYM_TREE_ROOT = re.compile(r"^(?:Russian|俄語|俄语|tiếng Nga) \S")
# wiki 链接：规整的 `[[X|Y]]`/`[[X]]`，以及源头写坏的 `[[composteur]#Французский|composteur]]]`
_WIKI_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_WIKI_LINK_BROKEN = re.compile(r"\[\[[^|\]]*\]?[^|\]\[]*\|")


def _drop_widgets(lines):
    out, i = [], 0
    while i < len(lines):
        s = lines[i].strip()
        if s in ("PIE word", "原始印歐語詞", "原始印欧语词", "Từ gốc Ấn-Âu nguyên thủy"):   # zh-t 的同一个挂件（抽读逮到）
            i += 2 if i + 1 < len(lines) and lines[i + 1].strip().startswith("*") else 1
            continue
        if _ETYM_TREE_HEAD.match(s):
            j = next((k for k in range(i + 1, len(lines)) if _ETYM_TREE_ROOT.match(lines[k].strip())), None)
            if j is not None:
                i = j + 1
                continue
        out.append(lines[i])
        i += 1
    return out


def etymology_text_pub(text, src=""):
    """dump 原文 → 出版正文（可能为空串 ＝ 整段都是占位/挂件）。

    zh 版的段再过一道 `zh_simp`（⑮，R29）—— **只有 zh 版**：en/ru 版词源里的汉字是**引文**
    （`From Sino-Korean 고려(高麗)`），转了就改了被引用的字形。
    """
    lines = []
    for ln in _drop_widgets((text or "").split("\n")):
        s = ln.strip()
        if not s or s == "{{{1}}}" or re.fullmatch(r"__[A-Z]+__", s) or s.startswith(":Template:") \
                or s.startswith(":Bản mẫu:") or s == "▲":
            continue
        if _ETYM_PLACEHOLDER_LINE.match(s) or _ETYM_MAINT.match(s):
            continue
        s = _ETYM_PLACEHOLDER_TAIL.sub("", s).strip()
        # 剩下的 `??`（1,777 段，`Происходит от сущ. восход ??`／`от ??Kümmel`）是同一个占位模板的残渣，
        # 意思是「再往前没填」—— 不是内容，删掉、并好空白
        # ⚠️ 只动含 `??` 的行：第一版对所有行都并空白、剥首尾标点，en/fr 一个 `??` 都没有却「清洗」了 145 段
        if "??" in s:
            s = re.sub(r"[ \t]{2,}", " ", re.sub(r"\s*\?\?+\s*", " ", s)).strip(" ,;")
        if not s or _ETYM_PLACEHOLDER_LINE.match(s):
            continue
        # 行内的模板洞 `…то же, из лат. coquere «варить». /{{{1}}}`（`кормокухня`，词源闸 Y7 逮到：
        # 第一版只剥整行是 `{{{1}}}` 的）
        s = re.sub(r"\s*/?\s*\{\{\{\d*\}\}\}", "", s).strip()
        if not s:
            continue
        s = _WIKI_LINK.sub(r"\1", s)
        s = _WIKI_LINK_BROKEN.sub("", s).replace("]]]", "").replace("[[", "").replace("]]", "")
        lines.append(s)
    out = "\n".join(lines).strip()
    return zh_simp(out, src) if ETYM_LANG.get(src) == "zh" else out


ETYM_LANG = {"en-edition": "en", "ru-edition": "ru", "zh-edition-simp": "zh", "zh-edition-trad": "zh",
             "fr-edition": "fr", "vi-edition": "vi", "pl-edition": "pl"}
# 指针：「见主词条的词源」—— 不是词源，是告诉读者去别处看（en 116／zh-t 39）
_ETYM_POINTER = re.compile(r"^(?:See the etymology of the corresponding lemma form\.?|"
                           r"請參閲主詞條的词源章節。?|请参阅主词条的词源章节。?)$")
ETYM_NOT_PUBLISHED = "第四语言（三语方针：fr/vi/pl 进证据层不出版）"


def etymology_hidden_why(src, word, text_pub):
    """出版正文 → None（印）或原因。⚠️ 空的出版正文不在这里判 —— 收割器根本不落那一段。"""
    if ETYM_LANG.get(src) not in PUBLISH_LANGS:
        return ETYM_NOT_PUBLISHED
    t = text_pub.strip()
    if _ETYM_POINTER.match(t):
        return "指针（见主词条的词源），不是词源本身"
    if not any(ch.isalpha() for ch in t):
        return "没有字母（整串是标点/符号）"
    if strip_stress(t).strip(" .。").lower() == strip_stress(word).lower():
        return "整段就是词头本身"
    return None


# ── 来源类型 `etym_type`：**只能从 en 版的 `etymology_templates` 来**（其余版 0 条模板）──
# 取模板列表里**第一个**有映射的（源头的叙述顺序：先说「从哪来」，后面才是同源词/注释）。
# `cog`/`ncog`/`m`/`l`/`glossary`/`q`… 不是来源声明（vi：`cog` 是同源词对照），不映射。
ETYM_TYPE_OF_TEMPLATE = {
    "inh": "inherited", "inh+": "inherited",
    "bor": "borrowed", "bor+": "borrowed", "lbor": "borrowed", "slbor": "borrowed", "obor": "borrowed",
    "cal": "calque", "calque": "calque", "clq": "calque", "sl": "calque", "semantic loan": "calque",
    "af": "formation", "affix": "formation", "suf": "formation", "suffix": "formation", "pre": "formation",
    "prefix": "formation", "com": "formation", "compound": "formation", "surf": "formation",
    "surface analysis": "formation", "blend": "formation", "univerbation": "formation",
    "clipcomp": "formation", "back-form": "formation", "deverbal": "formation", "conf": "formation",
    "onomatopoeic": "onomatopoeic", "onom": "onomatopoeic",
    "abbrev": "abbreviation", "initialism": "abbreviation", "acronym": "abbreviation",
    "sylabbr": "abbreviation", "clipping": "abbreviation", "clip": "abbreviation",
    "unk": "unknown", "unc": "unknown",
}
ETYM_TYPE_DOMAIN = frozenset(ETYM_TYPE_OF_TEMPLATE.values())


def etym_type_of(templates):
    for tp in templates or []:
        k = ETYM_TYPE_OF_TEMPLATE.get((tp or {}).get("name"))
        if k:
            return k
    return None


# ══════════════════════════════════════════════════════════════════════════
# ⑮ 中文出版正文：**安全的繁→简**（R29，2026-10-25，ru-crit-18）
# ══════════════════════════════════════════════════════════════════════════
# 页面上繁简混排：zh-t 版源头中文是繁体，zh-s 版的指针说明 99.5% 也是繁体（模板产出），
# 模型中文是简体。⇒ 出版正文转简体，**证据层一个字不动**（`text` 原样，转出来的进 `text_pub`）。
#
# 🔴🔴 **不能整段 `OpenCC t2s`**：它在**本来就是简体**的文本上会改错（6d 回收时就是整段转的，
#    2,941 条与答案不一致里实测到）：
#      · 短语表把简体改错：`头发覆上了一片银白` → `复上`（`反覆→反复` 是对的，同一个字）；
#        `“乾”的意义`（乾卦）／`乾闼婆` → `干`
#      · 字表本身就错：`芸薹`／`薹草` → `苔`（薹是规范简体字）
#      · 生僻字转成**扩展平面**的 2013 规范字形（`麻鳽→麻𫛚`、`刺魟→刺𫚉`、`鮟鱇→𩽾𩾌`），
#        多数字体显示成豆腐块 —— 原字在 BMP、读者看得懂，宁可不转。
# ⇒ 逐个位置决定收不收 OpenCC 的改动（OpenCC 照用它的短语表，只是**否决权在这里**）：
#    ① 目标字不在 BMP ⇒ 不收；
#    ② 原字**不在 GB2312**（＝它不是简体字，方向无歧义，`國→国`）⇒ 收；
#    ③ 原字在 GB2312 而 OpenCC 要改它 —— 这是歧义区，**交给「这行是不是繁体文本」答**：
#       单字表里这样的字全集只有 15 个（`乾吒夥後徵捱摺於榘甯菸薹醣麴麽`，从 OpenCC 自己的字表枚举的，
#       不是手抄），外加短语里的 `覆藉彷俱`。这一行是繁体文本（源头登记为繁体版、或含②那种字）⇒ 收；
#       否则不收 —— 简体文本里出现它们，多数是本该如此（乾卦／芸薹）。
#       例外：`ZH_SIMP_ALWAYS` 在简体文本里也收（`後`/`於`/`麽`… 在规范简体里没有独立用法，
#       模型写出 `主帆和後桅帆` 就是漏转），`ZH_SIMP_NEVER` 永远不收（`薹`：OpenCC 字表错）。
#    ④ 同一行里**繁简对举**（`汉语姓氏 習 /习`、`楊 /杨`）⇒ 那个繁体字是被引用的字形，不收。
ZH_TRAD_SRC = frozenset({"zh-edition-trad"})        # 登记为繁体的源（含 `:同句` 派生）
ZH_SIMP_ALWAYS = frozenset("後於夥摺醣菸麽捱徵藉彷俱")
ZH_SIMP_NEVER = frozenset("薹")
# OpenCC 短语表里有 `覆上→复上`／`覆住→复住`（古义「回复上级」），而我们的数据里这两个**全是「盖」**
# （实测 56 处：`头发覆上了一片银白`、`使覆上`、`手覆住`）⇒ 否决这两条；`反覆/答覆/回覆→复` 照收。
ZH_SIMP_KEEP_PHRASE = ("覆上", "覆住")
# 🔴 2026-10-26（5c 回收时逮到）：`藉` 在 ALWAYS 里（`藉着→借着`、`藉口→借口`、`凭藉→凭借` 都对），
#    而规范简体里 **`慰藉`／`狼藉`／`枕藉` 仍写「藉」**。OpenCC 把 `慰藉手段` 切出 `藉手→借手` ⇒ `慰借手段`。
#    第一版只问了「藉 后面跟什么」（`覆上` 那条），这里是**前一个字**决定的 ⇒ 两个窗口都查。
ZH_SIMP_KEEP_PHRASE_PREV = ("慰藉", "狼藉", "枕藉")


def _gb(ch):
    try:
        ch.encode("gb2312")
        return True
    except UnicodeEncodeError:
        return False


def _t2s():
    global _T2S_FN
    if _T2S_FN is None:
        import opencc
        _T2S_FN = opencc.OpenCC("t2s").convert
    return _T2S_FN


_T2S_FN = None


def zh_simp(text, src="", cap=4):
    """出版正文（简体）。没有要改的 ⇒ 原样返回同一个串（调用方据此存 NULL）。

    🔴 **转到收敛**：OpenCC 的短语切分依赖上下文，转一遍后邻字变了、下一遍会再变（ja/de 的修复脚本早写过
       「t2s 不幂等」；ru 全库实测 1 段：`…派生词，基於` 第二遍才转）。到顶不收敛 ⇒ 大声报错，不静默取某一遍。
    """
    for _ in range(cap):
        out = _zh_simp_once(text, src)
        if out == text:
            return out
        text = out
    raise RuntimeError("zh_simp %d 轮仍不收敛：%r" % (cap, text[:60]))


def _zh_simp_once(text, src):
    if not text:
        return text
    out = _t2s()(text)
    if out == text:
        return text
    if len(out) != len(text):                       # OpenCC t2s 逐字等长；不等长就别信它
        return text
    trad_row = src.split(":")[0] in ZH_TRAD_SRC or any(
        a != b and not _gb(a) for a, b in zip(text, out))
    res = []
    for i, (a, b) in enumerate(zip(text, out)):
        if a == b or ord(b) > 0xFFFF or a in ZH_SIMP_NEVER or text[i:i + 2] in ZH_SIMP_KEEP_PHRASE \
                or (i > 0 and text[i - 1:i + 1] in ZH_SIMP_KEEP_PHRASE_PREV):
            res.append(a)
            continue
        if _gb(a) and not (trad_row or a in ZH_SIMP_ALWAYS):
            res.append(a)
            continue
        # ④ 繁简对举：紧挨着、只隔一个分隔符就是它自己的简体（`習 /习`、`陳（陈）`）
        if re.match(r"\s*[/／（(、]\s*" + re.escape(b), text[i + 1:i + 5]) or \
                re.search(re.escape(b) + r"\s*[/／（(、]\s*$", text[max(0, i - 4):i]):
            res.append(a)
            continue
        res.append(b)
    return "".join(res)
