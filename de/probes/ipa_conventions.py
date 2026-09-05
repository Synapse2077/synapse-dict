#!/usr/bin/env python3
"""阶段 4 前置 —— **德语版与法语版给同一个词的音标，差在哪里**。2026-09-03。

═══ 为什么先做这一步 ═══
两版都要收（德语版独有 417,539、法语版独有 10,486，谁都不可替代），
于是必然撞上「同一个词两版给的音标不一样」。**在合并之前必须先知道差异是什么性质**：

    是**记法约定**不同（两个都对，选一个就行）
    还是**真的有一边错**（那要判）

🔴 这正是我在 es 上栽过的坑（`[[es-dict-pipeline]]`）：把 `coda 浊化 31,890` 和
   `多词次重音 7,889` 当成两个大缺陷报上去，回源逐字核对后发现**两个都是记法约定**，
   99.9% / 96.8% 逐字一致。而 `[[cross-edition-harvest]]` 已明写
   **fr 版重音符位置约定不同，没归一会误报 92%**。

═══ 判据：一次只抹掉一个特征，看剩下的还等不等 ═══
分类不靠正则猜"看起来像什么"，靠**消去法**：
把两串各抹掉特征 X 之后如果相等，那这对差异**只**关于 X。
一个都消不掉的进「其他」，那一桶才是要拿去问模型的。
⚠️ 顺序固定、且每条只归**第一个**命中的桶 —— 否则同一对会被重复计数。

本脚本**只读**，不写库、不下载、不调模型。
"""
import gzip, json, re, sys, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import paths                                    # noqa: E402
from intake_edition_words import EDITIONS       # noqa: E402

f = lambda n: format(n, ",")


def opener(p):
    p = Path(p)
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def scan(key, keep):
    """→ {词形: set(裸音标)}，只收 `keep` 里的词形。"""
    path, need_filter = EDITIONS[key]
    out = defaultdict(set)
    with opener(path) as fh:
        for line in fh:
            if need_filter and '"lang_code"' in line and '"de"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if need_filter and e.get("lang_code") != "de":
                continue
            w = e.get("word") or ""
            if w not in keep:
                continue
            for s in e.get("sounds") or []:
                # 🔴 **各版的定界符约定不同，必须全剥干净**：
                #    我们/英/德版用 `/…/` 或 `[…]`，**法语维基词典用 `\…\`**。
                #    第一版漏了反斜杠 ⇒ 21,922 条（4.5%）被判成"音段本身不同"，
                #    而实际 `\ʁetʁospɛkˈtiːvm̩\` 与 `ʁetʁospɛkˈtiːvm̩` 逐字相同。
                #    ⇒ **最大的那一桶是我的度量错，不是数据的分歧**
                #      （`[[measure-landing-not-source]]`：新数字先假设我的度量错了）。
                #    逮到它靠的是把**实样**打出来，不是读代码。
                ipa = (s.get("ipa") or "").strip().strip("/[]\\").strip()
                if ipa:
                    out[w].add(ipa)
    return out


# ── 消去器：每个只抹掉一个特征 ──────────────────────────────────────────
STRESS = re.compile(r"[ˈˌ'ˈˌ]")
LONG   = re.compile(r"[ːˑ:]")
SYLL   = re.compile(r"[.·̵‿]")
GLOT   = re.compile(r"[ʔ]")
DIACR  = re.compile(r"[̀-̩̯̞̥ͯ̊͜͡]")
R_ALL  = re.compile(r"[ʁrʀɐɹʶ]")
SPACE  = re.compile(r"[\s​ ]")
HYPH   = re.compile(r"^[-‐‑–]+|[-‐‑–]+$")   # 词缀条目的首尾连字符（法语版带、德语版不带）

# ═══ 🔴🔴 第二批消去器（2026-09-05，做 C41 时补的）═══
# **「⑨ 其他」桶不是证据，它是「我没想到的记法」的容器。** 它是**残差**——
# 定义就是「上面几条都解释不了的」，所以**消去器少一条，这一桶就虚胖一块**。
# 我拿它当过「实质分歧」的度量：账上写着「英文版与德语版 39% 实质分歧、一面倒是英文版错」，
# 于是把 C41 的 29,329 条判成「不能补」。今天把 ⑨ 桶里的**真词**（去掉词缀噪声）打出来看，
# 前 30 条**没有一条是错的**，全是这四种德语转写约定：
#
#     ˈaːbn̩t  / ˈaːbənt      音节化辅音 vs 央元音+辅音（德语版写 n̩，英文版写 ən）
#     ˈapˌmaxʊŋ / ˈapˌmaχʊŋ   ach-Laut 的两种字母（x / χ，同一个音位）
#     ˈaːbm̩tɔɪ̯ɐ / ˈaːbm̩tɔʏ̯ɐ  同一个双元音的两种记法（ɔɪ̯ / ɔʏ̯，aɪ̯ / aɛ̯）
#     ˈapˌz̥aːɡə / ˈapˌsaːɡə   清化附加符 vs 直接写清辅音；英文版还标送气 tʰ
#
# ⇒ `[[criteria-narrower-than-you-think]]` 的**反向形态**：判据窄的时候，
#   受害的不是被判的那一条，而是**兜底桶**——它替所有没写到的判据背了锅。
#
# 🔴 **加消去器有一个显而易见的自伤方向：把它们加到「怎么比都相等」为止。**
#   （`[[proxy-metric-gets-optimized]]`：一致率是代理，不是目的。）
#   ⇒ 每条消去器必须过**过度合并闸**（`overmerge()`）：它不许把两条本来不同的
#     德语音标抹成一样。闸打印新合并的实样，靠眼睛看那是不是真的区别被抹掉了。
#     这是 C22「一条已一致的都不许打坏」的反向版本：**一条本来不同的不许被抹平**。
# 组合竖线（音节化标记）。⚠️ **两个码位都要收**：标准是 U+0329（竖线在下），
# 而法语版大量写成 U+030D（竖线在上，`ˌbɛkŋ̍`）—— 同一个意思的两种写法。
SYLLABIC = "̩̍"
SCHWA_C  = re.compile(r"ə(?=[nmlŋʁr])")   # 央元音 + 成音节辅音位置
ASPIR    = re.compile(r"[ʰʱ]")
RING     = re.compile(r"[̥̊]")  # 下加圈 / 上加圈（清化）
DEVOICED = {"z": "s", "b": "p", "d": "t", "ɡ": "k", "g": "k", "v": "f", "ʒ": "ʃ"}

def _nfc(x):    return unicodedata.normalize("NFC", x)
def d_stress(x): return STRESS.sub("", x)
def d_long(x):   return LONG.sub("", x)
def d_syll(x):   return SYLL.sub("", x)
def d_glot(x):   return GLOT.sub("", x)
def d_diacr(x):  return DIACR.sub("", unicodedata.normalize("NFD", x))
def d_r(x):      return R_ALL.sub("R", x)
def d_space(x):  return SPACE.sub("", x)
def d_hyph(x):   return HYPH.sub("", x)

def d_syllabic(x):
    """n̩ ↔ ən 归一。两侧都收敛到「没有 ə、没有音节化标记」。

    ⚠️ `ə` **只在辅音之前**删。词尾的 `ə`（`Sehne` ˈzeːnə）是独立音位，删了会把
       `Sehne`/`sehn` 抹成一条 —— 那正是过度合并闸要拦的东西。
    """
    x = unicodedata.normalize("NFD", x)
    for ch in SYLLABIC:                   # 两个码位（U+0329 下 / U+030D 上）都要收
        x = x.replace(ch, "")
    return SCHWA_C.sub("", x)

def d_dorsal(x):
    """χ → x。德语只有一个 ach-Laut 音位，两个字母是记法差异不是音位差异。"""
    return x.replace("χ", "x")

def d_diph(x):
    """双元音第二成分的记法归一：ɔʏ→ɔɪ、aɛ→aɪ。**只动这两个二合字母**，
    单独的 ʏ / ɛ 一个都不碰（`Küste` ˈkʏstə ≠ `Kiste` ˈkɪstə）。"""
    return x.replace("ɔʏ", "ɔɪ").replace("aɛ", "aɪ")

# 🔴 第三批（2026-09-05，做 C39 时）：**同音不同码**。法语版 dump 里混着
#    已废弃的连字和同形异码字符 —— 它们不是「另一种读法」，是**另一个码位的同一个符号**：
#      `ǝ` U+01DD（turned e）83 条  ← 与 `ə` U+0259 长得一样，是不同码位
#      `ʦ` 630 条 / `ʧ` / `ʣ` / `ʤ`   ← Unicode 已废弃的塞擦音连字，等价于 `t͡s` 等
#    实测不归一它们，`bitten` 的 `ˈbɪtn̩` / `ˈbɪtǝn` 会被判成「音段本身不同」。
#      `g` U+0067（ASCII）294 条 ← 与 IPA 的 `ɡ` U+0261 长得一样，是不同码位
#    ⚠️ **这一条是聚族分析逼出来的，不是读代码看出来的**：把残差按「最小替换」聚族之后，
#      `ɡ → g` 以 294 条排在第一位 —— 一眼就看得出那不是 294 个读音分歧。
#      ⭐ **残差别只看条目，要先按「差在哪个字符上」聚族**，同音异码会自己浮到最上面。
LEGACY = {"ǝ": "ə", "ʦ": "t͡s", "ʣ": "d͡z", "ʧ": "t͡ʃ", "ʤ": "d͡ʒ", "ʨ": "t͡ɕ",
          "g": "ɡ"}
# 半元音的两种写法：`i̯`/`j`、`u̯`/`w`（`Italien` iˈtaːli̯ən / iˈtaːljən）。
# ⚠️ **只动 `i̯`/`u̯`**：`ɪ̯`/`ʊ̯`/`ɐ̯` 是双元音的第二成分，不是半元音，一个都不碰。
GLIDE = [("i̯", "j"), ("u̯", "w")]

def d_legacy(x):
    x = unicodedata.normalize("NFC", x)
    for k, v in LEGACY.items():
        x = x.replace(k, v)
    return x

def d_glide(x):
    x = unicodedata.normalize("NFC", x)
    for a, b in GLIDE:
        x = x.replace(a, b)
    return x

def d_low_a(x):
    """`ɑ` → `a`。**德语没有 `ɑ` 这个音位**（阶段 4 收割器的注释里已实测记过：
    法语版给 `Aachenerin` 写 `ˈɑː.xə.nə.ʁɪn`，那是法语的后低元音跑进德语转写）。
    ⇒ 它与 `a` 的差别是**记法（而且是有问题的记法）**，不是音位对立。"""
    return x.replace("ɑ", "a")


def d_devoice(x):
    """清化/送气记法归一：`z̥`→`s`、`b̥`→`p`、`tʰ`→`t`。

    🔴 **必须在剥掉圈之前判**，而且**只动带着圈的那个字母**。
       无条件 `z→s` 会把 `reisen`/`reißen`、`Bein`/`Pein` 抹成一条。
    """
    out, n = [], unicodedata.normalize("NFD", x)
    i = 0
    while i < len(n):
        c = n[i]
        if i + 1 < len(n) and RING.match(n[i + 1]) and c in DEVOICED:
            out.append(DEVOICED[c])
            i += 2
            continue
        out.append(c)
        i += 1
    return ASPIR.sub("", RING.sub("", "".join(out)))

# 顺序＝归桶优先级。每对只进第一个命中的桶。
# 🔴🔴 **顺序有意义，不是随手排的。** `d_legacy` / `d_glide` 必须排在 `d_diacr` **前面**：
#    它们会把 `ʦ` 展开成 `t͡s`，而那个连接弧 U+0361 得由后面的 `d_diacr` 收掉。
#    排反了的后果实测：`Abgrenzung` 我们 `ˈapˌɡʁɛnt͡sʊŋ` / 法语版 `ˈapˌɡʀɛnʦʊŋ`
#    明明只差「ʀ/ʁ + 废弃连字」两样，却落进「音段本身不同」的残差桶。
#    ⇒ 展开类的消去器排在收缩类前面。
_COMBO = [d_space, d_hyph, d_syll, d_stress, d_long, d_glot,
          d_legacy, d_glide, d_r, d_diacr,
          d_syllabic, d_dorsal, d_diph, d_devoice, d_low_a]
BUCKETS = [
    ("① 只差空白",                 [d_space]),
    ("①b 只差词缀首尾连字符",       [d_space, d_hyph]),
    ("② 只差音节点 . ·",           [d_space, d_syll]),
    ("③ 只差重音符 ˈ ˌ（位置或有无）", [d_space, d_stress]),
    ("④ 只差长音符 ː",             [d_space, d_long]),
    ("⑤ 只差词首喉塞音 ʔ",          [d_space, d_glot]),
    ("⑥ 只差 r 类记法 ʁ/r/ɐ/ʀ",     [d_space, d_r]),
    ("⑦ 只差附加符（元音下加点等）",   [d_space, d_diacr]),
    ("⑦a 只差 n̩ / ən 记法",        [d_space, d_syllabic]),
    ("⑦b 只差 ach-Laut 字母 x/χ",   [d_space, d_dorsal]),
    ("⑦c 只差双元音记法 ɔɪ/ɔʏ",     [d_space, d_diph]),
    ("⑦d 只差清化/送气记法 z̥/s tʰ/t", [d_space, d_devoice]),
    ("⑦e 只差同音异码/废弃连字 ǝ ʦ",   [d_space, d_legacy]),
    ("⑦f 只差半元音记法 i̯/j u̯/w",     [d_space, d_glide]),
    ("⑦g 只差 ɑ/a（ɑ 不是德语音位）",    [d_space, d_low_a]),
    ("⑧ 上面几样的组合",            _COMBO),
]

# 括号里的成分是**可选**的（`ˈapfalˌ(ʔ)aɪ̯mɐ`＝喉塞音可读可不读）。
# 它不是消去器：正确的处理是**展开成两读**，任一读对上就算一致。
PAREN = re.compile(r"\(([^)]{1,4})\)")

def variants(x):
    """→ {展开可选成分后的所有读法}。最多展开 6 处（2^6=64），超了就只给两端。"""
    hits = PAREN.findall(x)
    if not hits:
        return {x}
    if len(hits) > 6:
        return {PAREN.sub(lambda m: m.group(1), x), PAREN.sub("", x)}
    out = {x}
    for _ in range(len(hits)):
        nxt = set()
        for v in out:
            m = PAREN.search(v)
            if not m:
                nxt.add(v)
                continue
            nxt.add(v[:m.start()] + m.group(1) + v[m.end():])
            nxt.add(v[:m.start()] + v[m.end():])
        out = nxt
    return out


def full_key(v):
    """整条消去阶梯的归一键。"""
    for fn in _COMBO:
        v = fn(v)
    return v


def overmerge(values, extra, keys=None):
    """过度合并闸 → (`extra` 造成的新增合并组数, 实样)。

    `values` 是一批**本来两两不同**的德语音标。跑两次阶梯：一次**不带** `extra`，
    一次带上。带上之后被抹到同一个键、而不带时分属不同键的，就是 `extra` 合并掉的区别。
    **闸只报数和实样，不替我下判断** —— 是不是"真的区别"要眼睛看
    （`ɡlʏk` / `ɡlɪk` 是，`ˈaːbn̩t` / `ˈaːbənt` 不是）。

    `keys` 是 `{值: full_key(值)}` 的预算表，四条消去器共用一份，省掉重复跑阶梯。
    """
    keys = keys or {v: full_key(v) for v in values}
    base, new, where = {}, {}, {}
    for v in values:
        a = v
        for fn in _COMBO:
            if fn is extra:
                continue
            a = fn(a)
        where[v] = a
        base.setdefault(a, set()).add(v)
        new.setdefault(keys[v], set()).add(v)
    grew, ex = 0, []
    for grp in new.values():
        if len(grp) < 2:
            continue
        if len({where[v] for v in grp}) > 1:      # 本来分在不同组，现在并到一起了
            grew += 1
            if len(ex) < 8:
                ex.append(sorted(grp)[:3])
    return grew, ex


# ═══ 🔴🔴 桶③/桶④ 自己也「比它要描述的东西宽」（2026-09-05，做 C39 时发现）═══
# 残差桶虚胖是一种失败（[[residual-bucket-is-not-evidence]]）；**约定桶虚胖是反过来的
# 那一种：它把真错吞进去当成记法差异**，而且不会有任何人再看它一眼。
#
#   ③「只差重音符（位置或有无）」把两件完全不同的事合成了一桶：
#        ˈfraɪ̯ˌtaːk / ˈfraɪ̯taːk     次重音标不标 —— 记法
#        ˈʊnbəˌʃafbaːʁəm / ˌʊnbəˈʃafbaːʁəm   **主重音落在不同音节** —— 真分歧
#      收尾单 C39 自己举的那个例子（`unbeschaffbarem`，法语版对、我们错）**正好落在这一桶**，
#      于是会被当成「记法差异」扫掉。
#   ④「只差长音符 ː」同理：`de:` / `deː` 是 ASCII 冒号冒充长音符（记法），
#      而 `huːɡəˈnɔtə` / `huɡəˈnɔtə` 是**元音长短不同** —— 德语元音长度是音位的
#      （`Staat` ʃtaːt ≠ `Stadt` ʃtat），那是真分歧。
#
# ⇒ 命中 ③/④ 之后**再细分一次**。判据放在这里一份，C39/C41 两个探针都调 `refine()`。
_SEG_SKIP = set("ˈˌ'ˈˌ.·̵‿ ːˑ:​ -‐‑–…()")

# 德语 IPA 的成音节元音。⚠️ 带 U+032F（非音节标记）的是双元音第二成分，不单独算一个元音。
_VOWELS = set("aɑeɛiɪoɔuʊyʏøœəɐæɜʌɒ")
NONSYL = "̯"

def _primary_pos(s):
    """→ 主重音符 `ˈ` 前面有几个**元音**。没标主重音则 None。

    🔴 **第二版：数元音，不数音段。** 第一版数「音段字符」，于是
    `Aquarium` 我们 `aˈkvaːʁiʊm` / 法语版 `akˈvaːʁiʊm` 被判成「主重音落在不同音节」——
    而两边**重读的是同一个 `aː`**，差的只是 `k` 划给前一个音节还是后一个音节，
    那是**音节切分**不是重音位置。⇒ 判据要问「**哪个元音被重读**」，
    这才是「重音落在哪」的含义（`[[criteria-from-meaning-not-form]]`）。
    """
    n = 0
    d = unicodedata.normalize("NFD", s)
    for i, ch in enumerate(d):
        if ch == "ˈ":
            return n
        if ch in _VOWELS and d[i + 1:i + 2] != NONSYL:
            n += 1
    return None


def refine(name, a, b):
    """→ 细分后的桶名（不属于 ③/④ 时原样返回）。**判据只许这一份。**"""
    if name and name.startswith("③"):
        pa, pb = _primary_pos(a), _primary_pos(b)
        if pa is None or pb is None:
            return "③c 一侧没标主重音（另一侧标了）"
        return ("③a 只差次重音符 ˌ（主重音同位置）" if pa == pb
                else "③b 🔴 主重音落在不同音节（真分歧，不是记法）")
    if name and name.startswith("④"):
        norm = lambda s: s.replace(":", "ː").replace("ˑ", "ː")
        return ("④a 只差长音符字符（ASCII : 冒充 ː）" if norm(a) == norm(b)
                else "④b 🔴 元音长短不同（德语元音长度是音位的）")
    return name


def bucket(a, b):
    """→ 桶名。a/b 已 NFC。⚠️ 括号里的可选成分先展开成两读，任一读对上就算这一层解释得了。"""
    A, B = variants(a), variants(b)
    if A & B:
        return None
    for name, fns in BUCKETS:
        X = {x for x in A}
        Y = {y for y in B}
        for fn in fns:
            X = {fn(x) for x in X}
            Y = {fn(y) for y in Y}
        if X & Y:
            return name
    return "⑨ 其他（音段本身不同）← 要拿去问模型的就是这一桶"


def gate():
    """过度合并闸 —— **对阶梯里的每一条消去器都跑**，不只跑新加的那几条。

    🔴 2026-09-05：前八条消去器（空白/连字符/音节点/重音/长音/喉塞/r 类/附加符）
       是 2026-09-03 写的，**从来没过过这道闸** —— 闸是 09-05 做 C41 时才建的，
       当时只拿它验了新加的四条。「新东西要过闸、老东西不用」是没有道理的：
       老的那几条同样可能把两个不同的音抹成一个，而且它们已经在报数了。
    """
    import sqlite3
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    vals = sorted({v for (v,) in con.execute(
        "SELECT DISTINCT ipa FROM pronunciation WHERE COALESCE(ipa,'')<>''")})
    con.close()
    keys = {v: full_key(v) for v in vals}
    print("═══ 过度合并闸：阶梯里的每一条消去器 ═══")
    print("   受检值域：库里 %s 条互不相同的音标\n" % f(len(vals)))
    for fn in _COMBO:
        grew, ex = overmerge(vals, fn, keys)
        print("   %-12s 加上它 → 多合并 %6s 组%s"
              % (fn.__name__, f(grew), "  ✓" if not grew else ""))
        for g in ex[:3]:
            print("        %s" % "  ≡  ".join(g))
    return 0


def main():
    import sqlite3
    if "--gate" in sys.argv:
        return gate()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    keep = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()
    print("■ 库内词形 %s" % f(len(keep)))

    print("■ 扫德语版…"); de = scan("de", keep); print("   带音标词形 %s" % f(len(de)))
    print("■ 扫法语版…"); fr = scan("fr", keep); print("   带音标词形 %s" % f(len(fr)))

    both = set(de) & set(fr)
    print("\n■ 两版都给了音标的词形 %s" % f(len(both)))

    agree, c, ex = 0, Counter(), {}
    for w in both:
        A = {_nfc(x) for x in de[w]}
        B = {_nfc(x) for x in fr[w]}
        if A & B:                       # 有任意一条逐字相同 ⇒ 不算分歧
            agree += 1
            continue
        # 取"最像的一对"来归类：桶序越靠前越像
        best, bname = 99, None
        for a in A:
            for b in B:
                nm = bucket(a, b)
                idx = next((i for i, (n, _) in enumerate(BUCKETS) if n == nm), 98)
                if idx < best:
                    best, bname = idx, nm
                    ex.setdefault(nm, (w, a, b))
        c[bname] += 1

    n = max(len(both), 1)
    print("   逐字有交集（无分歧）    %s  %5.1f%%" % (f(agree), 100.0 * agree / n))
    print("\n■ 分歧归类（每对只进第一个命中的桶）")
    for k, v in sorted(c.items()):
        print("   %-38s %8s  %5.1f%%" % (k, f(v), 100.0 * v / n))
        w, a, b = ex[k]
        print("        %-22s de=%-24s fr=%s" % (w[:22], a[:24], b[:24]))

    print("\n── ⑨ 其他 桶的样本 20 条（这一桶才值得问模型）──")
    shown = 0
    for w in sorted(both):
        if shown >= 20:
            break
        A = {_nfc(x) for x in de[w]}; B = {_nfc(x) for x in fr[w]}
        if A & B:
            continue
        if any(bucket(a, b) and bucket(a, b).startswith("⑨") for a in A for b in B) and \
           not any(bucket(a, b) and not bucket(a, b).startswith("⑨") for a in A for b in B):
            print("   %-24s de=%-26s fr=%s" % (w[:24], sorted(A)[0][:26], sorted(B)[0][:26]))
            shown += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
