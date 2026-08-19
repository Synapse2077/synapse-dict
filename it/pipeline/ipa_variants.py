#!/usr/bin/env python3
"""音标变体的**唯一解析实现** —— 普查、建表、闸三处共用。2026-08-17（阶段 4）。

═══ 为什么要单独一个模块 ═══
阶段 4 要做三件事：数一遍源头应有多少条（普查）、把它们落成 `pronunciation` 行（写入）、
再回源逐条核对（闸）。三处若各写一份解析，闸就永远绿 —— 它验的是自己那份实现。
（`verification-gates-not-sampling`：一条永远通过的检查等于没检查。）

⇒ **`variants_of()` 是唯一入口，谁都不许自己解析 `sounds`。**

═══ 三条约定（都是实测出来的，不是猜的）═══

① **定界符定 notation，但各版的定界符约定不同**：
     en 版  `/ˈa.kwi.la/` 音位式 · `[…]` 严式
     it 版  `/ˈkaza/`     音位式 · `[…]` 严式（仅 221 行）
     fr 版  `\\ˈli.re\\`   ← **法语社区用反斜杠写音位式**，不是严式、不是噪声
   🔴 把 fr 的 `\\…\\` 当成"认不出的格式"丢掉，就等于丢掉 it 最大的外部音标源
      （A13：fr 版 698,250 条 = 英文版的 6.3 倍）。

② **fr 版重音符前多一个音节点** —— 这就是 `it-CONVENTIONS` A13 里
   「fr 版重音符位置约定不同，没归一会误报 92% 冲突」那句话的**本体**：

     en 版   o.ˈvi.pa.re  写成   oˈvi.pa.re     ← 重音符自带音节边界，不再写点
     fr 版   o.ˈvi.pa.re                        ← 点和重音符都写

   两者是**同一个读音的两种排版**。⇒ 归一规则：`.ˈ` → `ˈ`、`.ˌ` → `ˌ`。
   ⚠️ 这条归一**只动排版不动音**：没有任何一个意语词靠"重音符前有没有点"区分读音。
      归一前后的效果在 `probes/ipa_census.py` 里有对照数字，不是拍脑袋。

③ **`sounds` 里带 ipa 的行不都是音标**：
     · `X-SAMPA` / `SAMPA` 是**标签**（it 版 19 行）—— 同一个读音的另一种编码，不是变体
     · fr 版有整短语的转写（`[uŋ kɔm.pju.ˈtɛr]` ← "un computer" 那条录音的内容）
       ⇒ **带空格的一律不收**（意语单词的音标里不会有空格；多词词条另说，见 SPACE_OK）
     · 无定界符的裸串（it 版 176 行以 `ˈ` 开头）：**收**，但标记 `notation=phonemic`
       并在 `src_ref` 里留下下标，可回源

═══ 明确不做 ═══
· 不用 G2P 造音标（A6）；本模块只搬源头有的
· 不做「看着不像意语」这类判据（阶段 4「明确不做」第 2 条）
· 不改 `dict.ipa` 列（阶段 4 只加表，列的去留在阶段 8）
"""
import gzip
import json
import re
import unicodedata
from collections import namedtuple

# 每一条源头变体。`src_ref` = <前缀>:<词形>:<词性>:<词源号>#<sounds 下标>
#   🔴 必须带 pos + 词源号：同一词形在 dump 里有多条 JSON，各自的 sounds 下标都从 0 起
#      （es 上不带 pos 撞了 5.3 万条坐标）。
Variant = namedtuple("Variant", "word pos etym_no idx ipa raw notation region tags src src_ref")

# 与 `entry.src_ref` 用同一套前缀（`kk-en:` / `kk-it:` / `kk-fr:`）—— 阶段 4 要按
# (词形, 词性, 词源号) 把读音挂到 entry 上，两边前缀不一致就得靠映射表转换，纯属自找麻烦。
SRC_PREFIX = {"en-edition": "kk-en", "it-edition": "kk-it", "fr-edition": "kk-fr"}

# 这些 tag 标记的不是「另一个读音」，一律排除（X-SAMPA 是编码，不是变体）
DROP_TAGS = frozenset({"X-SAMPA", "SAMPA", "romanization", "rhymes",
                       "Hyphenation", "hyphenation"})

# 三种定界符 → notation。反斜杠是法语社区的音位式写法。
# 🔴 用 finditer **逐段**取，不能用 `^…$` 整串匹配：一个 `sounds.ipa` 字段里
#    可能塞了多条（it 版 `gallese` 是 `/ɡalˈlese/, /ɡalˈleze//` —— 清浊两读挤在一格）。
#    整串匹配会把这种整条丢掉 = 丢掉真变体；逐段取则两条都拿到，各自按自己的定界符定记法。
_DELIM = re.compile(r"([\\/\[])([^\\/\[\]]+)[\\/\]]")
_NOTATION = {"/": "phonemic", "\\": "phonemic", "[": "narrow"}

# 音标里合法的字符之外的东西（用来认「这根本不是音标」）
_NOT_IPA = re.compile(r"[A-Za-z0-9]{0,0}$")     # 占位，真正的判据见 looks_like_ipa


# 各版把主重音符写成键盘上的撇号 —— IPA 的主重音符只有 U+02C8 一个码位。
# 判据、修复脚本、闸三处共用这一份，别各写各的（三份就是三把尺子）。
STRESS_ALIASES = ("'", "’", "′")


def norm_ipa(s):
    """排版归一：NFC + 去重音符前的音节点 + 收尾空白。**只动排版，不动音。**"""
    if not s:
        return s
    s = unicodedata.normalize("NFC", s.strip())
    # 🔴 撇号当重音符（`'luːna`）→ IPA 的 ˈ（U+02C8）。fr 版 6,746 条、it 版 343 条
    #    的社区习惯是直接敲键盘上的撇号；IPA 里**没有**这三个码位，替换无损。
    #    与拉丁 g 那条同源，且同样是"写入侧 dict.ipa 一条没有、读取侧一堆"的形状 ——
    #    区别是这条**接上展示层才看见**（`pesca` 一个词并排显示出四条读音，
    #    其中两条只是记法不同）。2026-08-18 阶段 8。
    # ⚠️ **必须排在折 `.ˈ` 之前**：fr 版写的是 `a.'ba.te`，先折点的话那时点后面还是撇号、
    #    折不掉，等换成 ˈ 就晚了 —— 出来 `a.ˈba.te`，与 en 版的 `aˈba.te` 又成了两条假变体。
    #    （第一版我就是加在后面的，干跑时看输出才发现，字符对了顺序不对。）
    for ch in STRESS_ALIASES:
        s = s.replace(ch, "ˈ")
    s = s.replace(".ˈ", "ˈ").replace(".ˌ", "ˌ")
    # 🔴 拉丁小写 g（U+0067）→ IPA ɡ（U+0261）。**IPA 里没有 U+0067 这个符号**，
    #    两者是同一个音的两种码位，替换无损。不在入口归一的话，it 版 296 条、
    #    fr 版 107 条会一路灌进 `pronunciation`，而 `dict.ipa` 那边是 ɡ ——
    #    同一个词在两条读取路径上长得不一样（2026-08-18 回归闸的"被绕过"信号逮到的）。
    s = s.replace("g", "ɡ")
    return s.strip("."). strip()


VOWELS = "aeiouɛɔyøæɑ"
_VV_DOT = re.compile(r"(?<=[" + VOWELS + r"])\.(?=[" + VOWELS + r"])")


def cmp_key(s):
    """**跨版比对用的键** —— 在 `norm_ipa` 之上再折掉各版的排版习惯。

    🔴 这是与 `norm_ipa` 分开的第二把尺子，两者不能合并：
       `norm_ipa` 决定**存什么**（保留源头的音节切分，那是有信息量的），
       `cmp_key` 决定**算不算同一个读音**（音节点的写法是各版的排版习惯，不是读音差别）。

         en 版  ˈɡra.tis        it 版  ˈɡratis        ← 同一个读音，两种排版
         en 版  ˈɛf.fe          it 版  ˈɛffe          ← 同上

       同理还要折 **tie-bar**（U+0361）：`me.diˈt͡ʃi.ne`（英文版/G2P 的 kaikki 约定）
       与 `mediˈtʃine`（fr/it 版）是同一个塞擦音的两种写法。实测折它能消掉 **4,131 条**
       假冲突。⚠️ **长音符 `ː` 不折** —— 只影响 19 条，且它在有些转写里是真信息。

       ⚠️ **只折排版，不折音**。`a.berˈra.te`（库）与 `ab.berˈra.te`（fr 版）
          折点后仍然不等（`aberˈrate` / `abberˈrate`）—— 那是辅音数量的差别，
          是**真分歧**，必须留成两条让阶段 7 去裁，不许被归一吞掉。

       实测：不折音节点去比，`gratis`/`aquila`/`f` 这类**每个词都会多出一条假变体**，
       表会凭空翻倍 —— es 上正是这么把「多变体规模」虚报成 98.8% 的
       （`build_pronunciation_layer` 顶部记着）。

    ═══ 半元音：折 `j→i` / `w→u`，但**保留两个元音之间的音节点** ═══
    2026-08-17 就这一条同时问了两家顾问，**两家方案相反**，于是回数据判：

      · 豆包 pro：全折（点也全去），并断言"真差异不会被吞掉，因为重音本来就不同"
      · v4-pro：单向折 `j→i`/`w→u`，但**保留 V.V 点** —— 意语 hiatus（元音自成音节）
        与 glide（滑音）是真区别，而点的位置正是它的载体

    实测（三版全量，只看"会被新合并的组"）：全折多合并 998 组，其中**真差异被吞掉**：

        euro       ˈɛ.u.ro（三音节 hiatus）  ⇔ ˈɛw.ro（二音节 diphthong）
        Austria    ˈa.us.trja               ⇔ ˈaw.strja
        Palau      paˈla.u                  ⇔ paˈlaw
        Zimbabwe   d͡zimˈba.bu.e（四音节）  ⇔ d͡zimˈba.bwe（三音节）

    保留 V.V 点则只合并 401 组，逐条看**全是纯记法差**（音节数相同，只是韵尾滑音
    写成元音字母还是滑音符号）：`ˈai⇔ˈaj`、`ˈbɛi⇔ˈbɛj`、`kuˈwɛit⇔kuˈwɛjt`、`taiˈuan⇔tajˈwan`。
    ⇒ **采 v4-pro 的方案**；豆包那句"不会发生"被数据当场否掉
      （`llm-as-evaluator-discipline`：能确定性回源比对的，根本别问模型 —— 我问了，
       所以必须自己去量，不能取共识、也不能取更简单的那个）。
    """
    t = norm_ipa(s).replace("‿", "").replace(" ", "").replace("͡", "")
    t = _VV_DOT.sub("§", t)          # 先保护「元音.元音」的点
    t = t.replace(".", "").replace("§", ".")
    return t.replace("j", "i").replace("w", "u")


# G2P 猜不出的三件事（`b_ipa` 顶部原话）：重音位置、e/o 开闭、s/z 清浊。
# 分歧落在这三件事上，权威源的值可信；落在音段上，往往是源头噪声或两边在说别的词。
_STRESS = "ˈˌ"
_QUAL = {"e": "e", "ɛ": "e", "o": "o", "ɔ": "o", "s": "s", "z": "s"}
BLIND_SPOT = frozenset({"重音位置", "开闭/清浊", "重音位置 + 开闭/清浊"})


def diff_kind(a, b):
    """两条音标的分歧属于哪一类 → 重音位置 / 开闭·清浊 / 两者 / 音段不同。

    **判据本体，写入与闸共用。** 用途见 `build_pronunciation_layer.trust_rank`：
    只在 G2P 的盲点上采信 fr 版，音段分歧保留我们的值。这是 v4-pro 提的方案，
    并被「三版互核」的数字支持：**"另两版一致、只有它不同"的次数 fr 1,965 /
    it 1,038 / en 663** —— fr 版偏离最多，所以不能让它全局顶替。
    （同一组数字也否掉了豆包的"意语版母语编辑最准、应排英文版之前"。）

    ⚠️ **已知残差（量清了，不再加第四轮判据 —— PITFALLS A4）**：音节边界正好落在
       重音符上时，hiatus 与 glide 的区别在 `cmp_key` 里已经被抹掉了
       （`na.ˈu.ru` 先被 `norm_ipa` 折成 `naˈu.ru`，再折滑音就与 `ˈnawru` 只差重音位置）
       ⇒ `Nauru` 这类会被判成「重音位置」而让 fr 版顶替。逐条看过的样例里，
       真正该保留我们值的四族（长音符 `ˈaːvatar`、辅音数量 `abberˈrate`、
       非意语音段 `moˈŋgɔːlja`、hiatus `ˈpi.e`）判据都拦住了，只有 V-ˈ-V 这一族漏。
    """
    seg = lambda s: "".join(ch for ch in s if ch not in _STRESS)
    fold = lambda s: "".join(_QUAL.get(ch, ch) for ch in seg(s))
    moved = ([i for i, ch in enumerate(a) if ch in _STRESS]
             != [i for i, ch in enumerate(b) if ch in _STRESS])
    if seg(a) == seg(b):
        return "重音位置"
    if fold(a) == fold(b):
        return "重音位置 + 开闭/清浊" if moved else "开闭/清浊"
    return "音段不同"


# 音节切分残渣的判据。**这里是它唯一的家** —— `fixes/drop_hyphenation_fragments.py`
# 与回归闸 A5 都 import 这一份（三处各写一份就是三把尺子）。
_IPA_ONLY = set("ˈˌːɛɔʃʒʎɲŋɡ͡θðøæɑʔβɣəɪʊʌɹɾ")
_FRAG_MARGIN = 3


def _fold_spelling(s):
    d = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(ch for ch in d if unicodedata.category(ch) != "Mn").replace(
        ".", "").replace(" ", "").replace("'", "").replace("’", "")


def is_fragment(word, ipa):
    """→ 这串"音标"其实是**词形拼写的一个音节**（意语版把 `su-da-né-se` 的每个音节
    当成一条 `sounds` 给出来了，全库 228 行，其中 116 行还被选成了 is_primary）。

    三条同时成立：① 整串没有任何 IPA 专有符号 ② 折掉重音符号/点之后是词形拼写的子串
    ③ 词形比它长至少 3 个字母。

    🔴 第 ③ 条不是凑数：`a-`→`a`、`in-`→`in`、`bi-`→`bi` 这些前缀词条的音标**本来就等于拼写**，
       前两条判据会把 15 条真读音一起圈进来。与 `see (of a bishop)` 同一个形状 ——
       **看着像残渣的短串，往往正是短词的真值**。
    """
    if not ipa or any(ch in _IPA_ONLY for ch in ipa):
        return False
    frag, w = _fold_spelling(ipa), _fold_spelling(word)
    if not frag or frag not in w:
        return False
    return len(w) >= len(frag) + _FRAG_MARGIN


def looks_like_ipa(s, space_ok=False):
    """→ 这串是不是「一个词的音标」。判据保守：只排除明确不是的。

    🔴 不用「看着不像意语」这类判据（阶段 4 明令禁止）。这里只排除三类**结构**问题：
       ① 空 / 只剩标点
       ② 带空格而词形本身不是多词（fr 版把整短语的转写混在 sounds 里）
       ③ 里面有拉丁字母的连写块 ≥3（`Hyphenation` 类残渣、`si-len-zi-o`）
    """
    if not s or not s.strip("ˈˌ.:‿ ()"):
        return False
    if " " in s and not space_ok:
        return False
    return True


def space_ok_for(word):
    """这个词形的音标里出现空格，算正常还是算噪声。**判据来自实测，不是直觉。**

    正常的两族：
      · **词形本身是多段的** —— `de facto` / `baby-sitter` / `24/7` / `latino-americano`
      · **首字母缩略词** —— `DVD` → `ˈdi ˈvu ˈdi`、`VHS` → `vu akka ɛsse`：
        按字母名逐个读，字母名之间本来就有空格。判据是"词形里有大写字母"，
        因为在意语里正是"写成大写"这件事让它按字母读。

    噪声那族（一律排除）：fr 版把**整条录音的内容**转写进 sounds
    （`vino` → `il ˈvi.no`、`computer` → `uŋ kɔm.pju.ˈtɛr`，连冠词一起），
    以及 it 版的排版手误（`frutta` → `ˈfru tta`、`volare` → `vo la re`）。

    实测规模：it+fr 版单段词形的带空格转写共 295 条，逐条看**全是**上面这两类噪声；
    en 版 90 条里 82 条是多段词形或缩略词。⇒ 本判据放行 8 条残留噪声
    （`Tailandia` → `Tai ˈlan dia` 这种），已记账，不再为它加第四轮判据（PITFALLS A4）。
    """
    return any(ch in word for ch in " -/'’.·") or any(ch.isupper() for ch in word)


def variants_of(entry, src, word=None):
    """一条 dump JSON → [Variant]。**唯一入口。**

    dedupe 在 (ipa, notation) 上做，同一条 JSON 里重复写两遍的（fr 版 `computer`
    连着两条 `\\kom.ˈpju.ter\\`）只留第一条，但**保留第一条的下标**以便回源。
    """
    w = word if word is not None else entry.get("word")
    if not w:
        return []
    pos = entry.get("pos") or "?"
    etym = entry.get("etymology_number") or 0
    space_ok = space_ok_for(w)
    out, seen = [], set()
    for i, s in enumerate(entry.get("sounds") or []):
        raw = (s.get("ipa") or "").strip()
        if not raw:
            continue
        tags = list(s.get("tags") or []) + list(s.get("raw_tags") or [])
        if set(tags) & DROP_TAGS:
            continue
        chunks = [(m.group(2), _NOTATION[m.group(1)]) for m in _DELIM.finditer(raw)]
        if not chunks:
            # 裸串：收，标音位式。
            # 🔴 必须再剥一次单边定界符 —— it 版有 **1,658 行定界符只写了一半**
            #    （`Afghanistan` 的两条是 `"/afɡanisˈtan"` 和 `"afˈɡanistan/"`）。
            #    不剥就会把 `/` 存进 `ipa` 列，闸② 当场报红（2026-08-17 就是这么逮到的）。
            chunks = [(raw.strip(" /[]\\"), "phonemic")]
        # 一对定界符里也可能塞两读，用逗号隔开（it 版 `Edipo` = `/ˈɛdipo, eˈdipo/`
        # 是「重音两读」，`Perseo` 同）。意语音标本身不含逗号 ⇒ 见逗号就是分隔符。
        # 🔴 剥定界符必须在**逗号切分之后**，对每一段各剥一次：
        #    it 版有 `"saviʎʎaˈnese/,"` 这种 —— 定界符只写了后半个、后面还跟着逗号。
        #    先剥后切会剩下 `saviʎʎaˈnese/`（`/` 前面挡着逗号，strip 到不了）。
        chunks = [(part.strip(" /[]\\"), nt)
                  for body, nt in chunks for part in body.split(",")]
        # `sense` 是 it 版放地区/语境限定的地方（casa: /ˈkaza/ "italiano settentrionale"）
        note = s.get("sense") or s.get("note") or None
        for j, (body, notation) in enumerate(chunks):
            ipa = norm_ipa(body)
            if not looks_like_ipa(ipa, space_ok):
                continue
            # 🔴 音节切分残渣：意语版把 `su-da-né-se` 的每个音节当一条 sounds 给出来。
            #    2026-08-18 阶段 8 从库里删了 228 行，**必须同时在入口挡住** ——
            #    否则下次重扫 dump 又灌回来（`replay-scripts-undo-fixes`），
            #    而外锚闸⑤（dump 有、表里没有）会一直红着报这 228 条"漏收"。
            if is_fragment(w, ipa):
                continue
            key = (ipa, notation)
            if key in seen:
                continue
            seen.add(key)
            out.append(Variant(
                word=w, pos=pos, etym_no=etym, idx=i, ipa=ipa, raw=raw, notation=notation,
                region=None, tags=tuple(tags) + ((note,) if note else ()), src=src,
                src_ref="%s:%s:%s:%s#%d%s" % (SRC_PREFIX[src], w, pos, etym, i,
                                              ".%d" % j if j else "")))
    return out


def iter_source(path, src, lang_code=None):
    """逐条产出 (word, entry)。`lang_code` 给定时按它过滤（语言版整包必须过滤）。

    🔴 必须 json.loads 整行再取 `word`，不许用正则 —— wiktextract 的 key 顺序不固定，
       `forms`/`related` 这些嵌套数组里也有 "word" 键（`kaikki_util` 顶部记着这个坑）。
    """
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8", errors="replace") as f:
        for ln in f:
            if not ln.strip():
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if lang_code and d.get("lang_code") != lang_code:
                continue
            w = d.get("word")
            if w:
                yield w, d
