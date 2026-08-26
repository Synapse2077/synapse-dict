#!/usr/bin/env python3
"""阶段 4 — **音标层**。把各版 dump 的 IPA 收进 `pronunciation`。2026-08-25。

═══ 上限已实测（`probes/ipa_ceiling.py`），验收线只能定在它以下 ═══
🔴 **fr 明确不造 G2P**（用户七月已定，`fr-DESIGN.md` §1：哑音末辅音/联诵/省音/一音多写）。
   对比 it：那轮 120 万行音标里 **73.4% 是我们自己 G2P 算的**
   （`[[it-pronunciation-layer]]`）⇒ **照搬 it 的覆盖率是不可能的**，
   fr 的天花板完全由源头决定。

    全部词形   2,086,292 ｜ 现状  317,042 (15.2%) → 上限 1,725,139 (82.7%)
    像词头       526,029 ｜ 现状   90,543 (17.2%) → 上限   313,777 (59.7%)
    有可见义项    542,011 ｜ 现状   97,612 (18.0%) → 上限   330,603 (61.0%)

**法文版一家贡献 1,405,701 条新增（99.8%）**，其余各版加起来只有 2,396 条 ——
但那 2,396 条几乎免费（切片已在本地），照收。

═══ 🔴 法文版的 IPA 有三种写法，混着存会出两类硬缺陷 ═══
`[[it-display-layer-stage8]]` 的同一个形状（意语版把**音节切分**当读音，116 条是
`is_primary`）—— 三层数据的闸全绿，真渲染出来才看见。所以判据先在这里写死：

  ① `\\a.kœj\\`            **音位式**，法文版自己的定界符（不是 `/…/`）。**首选**。
                          实测 20 万条目里 **97.3% 有音位式** ⇒ 优先它几乎不丢覆盖。
  ② `^((h aspiré))\\ɔ̃.ɡʁwa\\`  音位式前面挂着 **h 送气/哑音标记**。
                          🔴 不剥就会存成 `^((h aspiré))ɔ̃.ɡʁwa`。
                          ⭐ 而这个标记**本身是有价值的**（它决定联诵与省音：
                          `le hérisson` vs `l'homme`）⇒ 剥下来进 `tags`，不丢。
  ③ `[lə sɔ̃]`            音值式，**多数是给某条录音标的，会把上下文词一起录进去**：
                          `son` → `[lə sɔ̃]`（le son）
                          `encyclopédie` → `[yn ɑ̃.si.klɔ.pe.di]`（une encyclopédie）
                          `accueil` → `[ɛ̃.n‿a.kœj]`（un accueil，还带联诵符）
                          `Neuf` → `œ̃ ʃɑɔ̯ʁ nø`（un chœur neuf，来自别的版的**音位式**）

🔴 **③ 的判据我写错过两版，两版都是形式代理，都被数据打回**
   （`[[criteria-from-meaning-not-form]]`）：
     v1「音值式里有空格」            → `Neuf` 从别的版的音位式漏进来
     v2「单词词形的音标里有空格或 ‿」→ **误杀 8 类真数据**：
        `d’accord \\d‿a.kɔʁ\\`、`c’est \\s‿ɛ\\`、`jusqu’ici \\ʒys.k‿i.si\\`
          —— `‿` 标的是**词内部**的省音，本来就该有
        `RN \\ɛ.ʁ‿ɛn\\`、`VHS \\ve a.ʃ‿ɛs\\`、`CIO \\se i o\\`、`S.A.`、`SN`
          —— 字母逐个念，空格本来就该有
   v3「候选**包含**锚且更长 ⇒ 剔」→ 又误杀 206 条：多出来的东西在**后面**时
        全是真变体 —— `prendre` 锚 `pʁɑ̃dʁ` vs `pʁɑ̃.dʁə`（词尾 schwa）、
        `wombat` `wɔ̃.ba` vs `wɔ̃.bat`（词末辅音读不读）、`ring` `ʁiŋ` vs `ʁiŋɡ`。
   ⇒ **现在这版**（`drop_phrase`，自锚，两条）：
     (a) 候选**以锚结尾**且更长 ⇒ 多出来的在**前面**，那才是别的词。
     (b) 候选**有空格**、且空格后那段就是锚 ⇒ 前面挂了冠词
         （`nord`→`lə nɔʁ`、`chat`→`ɛ̃ ʃä`、`gouvernement`→`œ̃ …`，实测 64 条）。
     `manga` 的 `mɑ̃ŋ.ɡa` 既不以锚结尾也没空格 ⇒ 留。自测含负控。

═══ 两把尺子分开：**存的**和**比的** ═══
`[[it-pronunciation-layer]]`：存进库的是**源头原样（去定界符）**，
去重/比对用的是**归一后的键**。混用一把尺子的后果 ——
`[[cross-edition-harvest]]`「fr 版重音符位置约定不同，没归一会误报 92%」。
归一只做**确定不改变音值**的四件：去定界符 / 去音节点 / 去重音符 / 去首尾空白。
⚠️ **不去鼻化符、不去长音符、不折叠 œ/ø** —— 那些是真的音位区别。

═══ 存法 ═══
`[[ipa-bare-storage-convention]]`：DB **裸存**，不带 `/…/`；展示层统一加。
`notation` = phonemic（①②）/ narrow（③）。
`region` 从 `raw_tags` 归一：France / Canada / Belgique / Suisse / Québec…
`is_primary` 每个词形恰好一条：**音位式 > 音值式；法文版 > 英文版 > 其余版**。

用法（在 fr/ 目录下）：
    python3 -u pipeline/build_pronunciation_layer.py            # 只审计，不写库
    python3 -u pipeline/build_pronunciation_layer.py --sample 30
    python3 -u pipeline/build_pronunciation_layer.py --apply
    python3 -u pipeline/build_pronunciation_layer.py --verify
"""
import argparse
import gzip
import io
import json
import random
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool                              # noqa: E402
import paths                               # noqa: E402
from intake_fr_words import norm_apos      # noqa: E402

# 源的优先级 = 列表顺序。`is_primary` 与去重都按它裁决。
#
# 第四个字段 `bare_ok` = **这一版写不写定界符**，逐版实测出来的，不是猜的：
#     fr  \…\ 为主      裸值 47/60,000，**全是散文**（"On ne prononce pas le"、
#                       "pour l'adjectif, il faut dire \dʁɛ\…"）⇒ 裸值一律不收
#     en  /…/ 32,609 · […] 429                         ⇒ 不收裸值
#     ja  /…/ 10,757 · […] 72                          ⇒ 不收裸值
#     el  **裸 9,977** · \…\ 2                          ⇒ 🔴 必须收裸值，否则整版丢光
#     nl  /…/ 18,683 · 裸 27                            ⇒ 收
#     ru  […] 9,255 · 裸 13                             ⇒ 收
#     tr  /…/ 280 · 裸 26                               ⇒ 收
# 🔴 第一版我写死"无定界符一律不收"，一口气扔掉 10,097 条 —— 其中 el 版
#    **99.98% 都是裸的**。判据必须按版走（`[[criteria-narrower-than-you-think]]`）。
SOURCES = [
    ("fr-edition", paths.EDITION, "fr", False),
    ("en-edition", paths.KK, "fr", False),
    ("el-edition", paths.DUMPS / "kaikki.org-elwiktionary-French.jsonl.gz", None, True),
    ("nl-edition", paths.DUMPS / "kaikki.org-nlwiktionary-French.jsonl.gz", None, True),
    ("ru-edition", paths.DUMPS / "kaikki.org-ruwiktionary-French.jsonl.gz", None, True),
    ("ja-edition", paths.DUMPS / "kaikki.org-jawiktionary-French.jsonl.gz", None, False),
    ("tr-edition", paths.DUMPS / "kaikki.org-trwiktionary-French.jsonl.gz", None, True),
]

# 裸值的护栏：出现这些就不是音标是散文/编者注。
# ⚠️ 这些字符在**带定界符**的值里也偶尔出现（源头自己脏），但那时定界符已经
#    证明了"编者是当音标写的"；裸值没有这个证明，所以这里从严。
BARE_BAD = re.compile(r"[A-Z,;()«»…\\]|\s{2}")
BARE_MAX = 60

# `^((h aspiré))\ɔ̃.ɡʁwa\` 前面那个标记。**剥下来但不丢** —— 它决定联诵与省音。
H_MARK = re.compile(r"^\^?\(\((?P<m>[^)]*)\)\)\s*")
# 三种定界符
DELIM = [("\\", "\\", "phonemic"), ("/", "/", "phonemic"), ("[", "]", "narrow")]
# 归一：只做**确定不改变音值**的四件
# 音节点 / 主次重音（IPA 的 ˈˌ **和各版随手打的 ASCII `'`**，实测
# `plateau cyclique` → `pla.to si.'klik`）/ 空白 / 连结符
NORM_DROP = re.compile(r"[.ˈˌ'ʼ\s‿⁀]")

REGION = [
    (re.compile(r"qu[ée]bec", re.I), "fr-CA"),
    (re.compile(r"canada|acadie|ontario", re.I), "fr-CA"),
    (re.compile(r"belgi|wallon|bruxell", re.I), "fr-BE"),
    (re.compile(r"suisse|helvét|romand", re.I), "fr-CH"),
    (re.compile(r"afrique|s[ée]n[ée]gal|congo|maghreb|alg[ée]rie|maroc|tunisie", re.I), "fr-AF"),
    (re.compile(r"louisiane|ha[ïi]ti|antilles|cr[ée]ole", re.I), "fr-AM"),
    (re.compile(r"france|paris|midi|paris?ien|standard", re.I), "fr-FR"),
]


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if str(p).endswith(".gz") \
        else io.open(p, encoding="utf-8")


def norm_key(ipa):
    """**比**的尺子。存的是另一把（见模块 docstring）。"""
    return NORM_DROP.sub("", ipa)


def loose_key(ipa):
    """比 `norm_key` **更松**的第三把尺子：连附加符和长音符一起抹掉。

    🔴 **只许用在 `drop_phrase` 的 (b) 那一条**（"空格后那段是不是锚"），
       绝不许拿它去重、也绝不许拿它判"是不是同一个音"。
       实测：拿它做包含判断会**删掉真的地区变体** ——
           fin  锚 fɛ̃  → 会去剔 fɛŋ    （南方法语软腭鼻音）
           nom  锚 nɔ̃  → 会去剔 nɔŋ
           an/en 锚 ɑ̃  → 会去剔 ɑŋ
           mon/son/breton 锚 -ɔ̃ → 会去剔 -ɔn（联诵形）
       **鼻化在法语里是音位对立**，本文件 docstring 自己写着"不去鼻化符"，
       我却差点用它做主判据（`[[criteria-narrower-than-you-think]]`）。
    """
    s = unicodedata.normalize("NFD", norm_key(ipa))
    return "".join(c for c in s if not unicodedata.combining(c)).replace(
        "ː", "").replace("ˑ", "")


def region_of(tags):
    for t in tags:
        for rx, code in REGION:
            if rx.search(t):
                return code
    return None


# 🔴 **一格里塞了两条音标**。源头把两个读音写在同一个 `ipa` 字段里：
#     cigare    [si.ɡɑːʁ], [si.ɡɑɔ̯ʁ]
#     aiguisoir [ɛ.ɡi.zwɑʁ], [e.ɡi.zwɑʁ]
# 只剥首尾定界符的话，中间那对就留在字符串里，存成 `si.ɡɑːʁ], [si.ɡɑɔ̯ʁ`。
# 实测 72 条。⇒ 先按"右定界符 + 逗号 + 左定界符"劈开，每段各自解析。
MULTI = re.compile(r"(?<=[\]\\/])\s*[,;]\s*(?=[\[\\/])")
# 尾巴上的省略号（源头写了半句），实测 32 条
TAIL_DOTS = re.compile(r"[\s.·…]*(?:\.\.\.|…)[\s.·…]*$")


def split_multi(raw):
    """一个 `ipa` 字段 → 若干条候选。绝大多数情况就是它自己一条。"""
    v = (raw or "").strip()
    return [x.strip() for x in MULTI.split(v) if x.strip()] if v else []


def parse_ipa(raw, word, st, bare_ok=False):
    """**一条**（已经 `split_multi` 过的）音标串 → (裸音标, notation, 附加 tags) 或 None。"""
    v = (raw or "").strip()
    if not v:
        return None
    extra = []
    m = H_MARK.match(v)
    if m:
        extra.append(m.group("m").strip())
        v = v[m.end():].strip()
        st["② 剥掉 h 送气/哑音标记（留进 tags）"] += 1
    for a, b, notation in DELIM:
        if len(v) >= 2 and v.startswith(a) and v.endswith(b):
            v = v[1:-1].strip()
            break
    else:
        if not bare_ok:
            st["🔴 该版有定界符约定，这条却是裸的 ⇒ 是散文，不收"] += 1
            return None
        # 裸值：先掉落落单的定界符（nl 实测 `sɪˈtʁɔ̃/`），再过护栏
        v = v.strip("\\/[] ").strip()
        if not v or len(v) > BARE_MAX or BARE_BAD.search(v):
            st["🔴 裸值没过护栏（散文/编者注），不收"] += 1
            return None
        notation = "phonemic"
        st["✓ 裸值（该版本来就不写定界符）"] += 1
    if not v:
        return None
    # 🔴🔴 「上下文词」的判据**不在这里**，在 `drop_phrase()`。
    #    我在这里写过两版，两版都是**形式代理**，两版都被数据打回：
    #      v1「音值式里有空格」 → `Neuf` 从别的版的**音位式**漏进来
    #      v2「单词词形的音标里有空格或 ‿」→ **误杀 8 类真数据**：
    #         d’accord `\\d‿a.kɔʁ\\` · c’est `\\s‿ɛ\\` · jusqu’ici `\\ʒys.k‿i.si\\`
    #           —— `‿` 在这里标的是**词内部**的省音，本来就该有
    #         RN `\\ɛ.ʁ‿ɛn\\` · VHS `\\ve a.ʃ‿ɛs\\` · CIO `\\se i o\\` · S.A. · SN
    #           —— 字母逐个念，空格本来就该有
    #    `[[criteria-from-meaning-not-form]]`：判据要按**含义**出发。
    #    真正的区别不是"有没有空格"，是"**前面多挂了一个别的词**"⇒ 见 `drop_phrase`。
    v = TAIL_DOTS.sub("", v).strip()
    if not v:
        return None
    return v, notation, extra


def drop_phrase(cands, st):
    """按**含义**剔除「把上下文词一起录进去」的那种音标。

    判据是**自锚的**，不靠我手写一张冠词表：
      锚 = 这个词形的第一条音位式（源优先级最高的那一版给的）。
      一条候选如果**归一后完整包含锚、而且比锚长**，那多出来的就是别的词。

        son          锚 sɔ̃          候选 ləsɔ̃          ⇒「le son」，剔
        encyclopédie 锚 ɑ̃siklɔpedi   候选 ynɑ̃siklɔpedi   ⇒「une encyclopédie」，剔
        accueil      锚 akœj          候选 ɛ̃nakœj        ⇒「un accueil」，剔
        manga        锚 mɑ̃ɡa         候选 mɑ̃ŋɡa         ⇒ **不含锚**（ŋ 打断了），留
        d’accord     只有它自己                            ⇒ 留

    ⚠️ 只剔**比锚长且含锚**的。短的、与锚无包含关系的，一条都不动 ——
       那些是真的读音变体（地区音、老派音）。
    """
    if len(cands) < 2:
        return cands
    # 锚 = 第一条**音位式**；一条音位式都没有时，退到第一条候选。
    # 🔴 第一版"没有音位式就整组放行"，`lampe économique`（只有音值式）就漏了
    #    `yn lɑ̃.p‿e.kɔ.nɔ.mik`（une lampe…）。而闸拿 `is_primary` 当锚 ——
    #    **两边的锚定义不一样，闸就在报自己的 bug**（同 `verify_vs_dump` 那次）。
    anchor = None
    for ipa, notation, _r, _t, _ref in cands:
        if notation == "phonemic":
            anchor = norm_key(ipa)
            break
    if anchor is None:
        anchor = norm_key(cands[0][0])
    if not anchor:
        return cands
    a_loose = loose_key(anchor)
    out = []
    for c in cands:
        raw, k = c[0], norm_key(c[0])
        # (a) **前缀**式：候选以锚结尾、且前面多出来的**至少 2 个字符** ⇒ 那是别的词。
        # 🔴 «至少 2 个» 不是随手加的阈值，是**含义**：法语冠词/限定词最短也是两个音
        #    （`yn` une · `lə` le · `œ̃` un · `dy` du）。多出来只有一个字符的
        #    一律是读音变体 —— `oh fant` 的 `ˈwoˈfãᵑ` vs `ˈoˈfãᵑ` 差一个 /w/，
        #    没有这条护栏就会被当成"前面挂了词"删掉。
        if k != anchor and len(k) - len(anchor) >= 2 and k.endswith(anchor):
            st["③a 前面多挂了一个词（`son`→`lə sɔ̃`），剔"] += 1
            continue
        # (b) 前缀被读音细节挡住时的兜底：**有空格**、且空格后那段就是锚。
        #     实测 64 条，全是 `un/une/le/la` 起头（`nord`→`lə nɔʁ`、`chat`→`ɛ̃ ʃä`）。
        if " " in raw.strip() and loose_key(raw.strip().rsplit(" ", 1)[-1]) == a_loose:
            st["③b 空格 + 末段等于锚（`chat`→`ɛ̃ ʃä`），剔"] += 1
            continue
        out.append(c)
    return out


def harvest(name, path, lang_code, bare_ok, st, limit=0, raw_seen=None):
    """→ {词形: [(ipa, notation, region, tags, src_ref), …]}，保序、组内已去重。

    `raw_seen`：**源头给过任何一条非空 ipa 的词形**（不管收没收）。
    🔴 这是量「判据到底扔掉了多少词形」用的 ——
       `probes/ipa_ceiling.py` 的上限是**不带护栏**算的（散文和整句读音也算覆盖），
       拿它当分母会以为"我们漏了"，其实是那个上限本来就虚高
       （`[[measure-landing-not-source]]`：量落点不量源头）。
    """
    out = defaultdict(list)
    if not Path(path).exists():
        print("   （%s 不存在，跳过）" % path)
        return out
    seen = set()
    n = 0
    with opener(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if lang_code and e.get("lang_code") != lang_code:
                continue
            w0 = (e.get("word") or "").strip()
            if not w0:
                continue
            n += 1
            if limit and n > limit:
                break
            w = norm_apos(w0)
            pos = e.get("pos") or ""
            for i, s in enumerate(e.get("sounds") or []):
                if raw_seen is not None and (s.get("ipa") or "").strip():
                    raw_seen.add(w)
                parts = split_multi(s.get("ipa"))
                if len(parts) > 1:
                    st["① 一格里塞了两条音标，已劈开"] += len(parts) - 1
                tags = [str(x) for x in (s.get("raw_tags") or []) + (s.get("tags") or [])]
                for q, part in enumerate(parts):
                    got = parse_ipa(part, w0, st, bare_ok)
                    if not got:
                        continue
                    ipa, notation, extra = got
                    k = (w, norm_key(ipa), notation)
                    if k in seen:
                        continue
                    seen.add(k)
                    st["✓ 收 %s" % name] += 1
                    out[w].append((ipa, notation, region_of(tags), tags + extra,
                                   "kk-%s:%s:%s#s%d.%d" % (name[:2], w0, pos, i, q)))
            # 变形层：`forms[].ipa`（法文版实测 0 条新增，英文版有 1,469）
            for j, fm in enumerate(e.get("forms") or []):
                fw0 = (fm.get("form") or "").strip()
                if raw_seen is not None and fw0 and (fm.get("ipa") or "").strip():
                    raw_seen.add(norm_apos(fw0))
                if not fw0:
                    continue
                fw = norm_apos(fw0)
                for q, part in enumerate(split_multi(fm.get("ipa"))):
                    got = parse_ipa(part, fw0, st, bare_ok)
                    if not got:
                        continue
                    ipa, notation, extra = got
                    k = (fw, norm_key(ipa), notation)
                    if k in seen:
                        continue
                    seen.add(k)
                    st["✓ 收 %s（变形层）" % name] += 1
                    out[fw].append((ipa, notation, None, extra,
                                    "kk-%s:%s:%s#f%d.%d" % (name[:2], w0, pos, j, q)))
    return out


# `drop_phrase` 的判据自测。前 3 例是要剔的，后 5 例是**我第二版误杀过的真数据**
# —— 负控比正控重要（`[[llm-as-evaluator-discipline]]` 那条：用前必跑负控）。
PHRASE_CASES = [
    # —— 要剔的（前面多挂了一个词）——
    ("son 剔上下文",        ["sɔ̃", "lə sɔ̃"],                 ["sɔ̃"]),
    ("encyclopédie",       ["ɑ̃.si.klɔ.pe.di", "yn ɑ̃.si.klɔ.pe.di"], ["ɑ̃.si.klɔ.pe.di"]),
    ("accueil 联诵",        ["a.kœj", "ɛ̃.n‿a.kœj"],            ["a.kœj"]),
    ("Neuf 整句读音",        ["nœf", "œ̃ ʃɑɔ̯ʁ nœf"],            ["nœf"]),
    ("chat 走 (b) 空格兜底", ["ʃa", "ɛ̃ ʃä"],                    ["ʃa"]),
    ("gouvernement (b)",   ["ɡu.vɛʁ.nə.mɑ̃", "œ̃ ɡu.vɛʁ.n̪ə.mɑ̃"], ["ɡu.vɛʁ.nə.mɑ̃"]),
    # 只有音值式、没有音位式 ⇒ 退到第一条当锚（不退就整组放行，`yn …` 漏网）
    ("lampe économique 无音位式", ["lɑ̃.p‿e.kɔ.nɔ.mik", "yn lɑ̃.p‿e.kɔ.nɔ.mik"],
     ["lɑ̃.p‿e.kɔ.nɔ.mik"], "narrow"),
    # —— 🔴 负控：以下每一条都是我某一版判据**真的误杀过**的数据 ——
    ("manga 地区变体",       ["mɑ̃.ɡa", "mɑ̃ŋ.ɡa", "maŋ.ɡa"],   ["mɑ̃.ɡa", "mɑ̃ŋ.ɡa", "maŋ.ɡa"]),
    ("mâches 双读音",        ["maʃ", "mɑʃ"],                    ["maʃ", "mɑʃ"]),
    ("d’accord 词内省音",    ["d‿a.kɔʁ"],                       ["d‿a.kɔʁ"]),
    ("VHS 字母逐个念",       ["ve a.ʃ‿ɛs"],                     ["ve a.ʃ‿ɛs"]),
    ("HPGP 字母逐念·两条",   ["aʃ pe ʒe pe", "a.ʃə.pe.ʒe.pe"],  ["aʃ pe ʒe pe", "a.ʃə.pe.ʒe.pe"]),
    ("prendre 词尾 schwa",  ["pʁɑ̃dʁ", "pʁɑ̃.dʁə"],             ["pʁɑ̃dʁ", "pʁɑ̃.dʁə"]),
    ("wombat 词末辅音",      ["wɔ̃.ba", "wɔ̃.bat"],              ["wɔ̃.ba", "wɔ̃.bat"]),
    ("ring 词末 ɡ",          ["ʁiŋ", "ʁiŋɡ"],                   ["ʁiŋ", "ʁiŋɡ"]),
    ("fin 南方软腭鼻音",      ["fɛ̃", "fɛŋ"],                    ["fɛ̃", "fɛŋ"]),
    ("breton 联诵形",        ["bʁə.tɔ̃", "bʁə.tɔn"],            ["bʁə.tɔ̃", "bʁə.tɔn"]),
    # 前面只多一个字符 ⇒ 是读音变体，不是冠词（冠词最短两个音）
    ("oh fant 差一个 /w/",   ["ˈoˈfãᵑ", "ˈwoˈfãᵑ"],             ["ˈoˈfãᵑ", "ˈwoˈfãᵑ"], "narrow"),
]


def selftest():
    bad = 0
    for case in PHRASE_CASES:
        name, inp, want = case[0], case[1], case[2]
        notation = case[3] if len(case) > 3 else "phonemic"
        cands = [(x, notation, None, [], "r%d" % i) for i, x in enumerate(inp)]
        got = [c[0] for c in drop_phrase(cands, Counter())]
        if got != want:
            bad += 1
            print("   🔴 %-22s 期望 %s\n      实得 %s" % (name, want, got))
        else:
            print("   ✓ %-22s → %s" % (name, got))
    print("■ `drop_phrase` 自测 %d 例，红 %d" % (len(PHRASE_CASES), bad))
    return bad


def build(con, limit=0):
    # 🔴 **不许 `.lower()` 当键。** `dict` 有 2,086,292 行词形，`norm_apos` 之后
    #    仍然**一个不重**；再 `.lower()` 一下就折叠掉 **103,549 个**
    #    （`Neuf`/`neuf`、`11 Septembre`/`11 septembre`、`-e`/`-E`…）。
    #    折叠之后一个键只能指向一行，另一行的音标就挂错人 ——
    #    而阶段 3a 花了整整一步**把大小写折叠拆开**
    #    （`[[case-folding-contaminates-columns]]`：大写专名的属性并进小写词形）。
    # ⇒ 主键**保大小写**；大小写不同才走兜底，且**兜底只在唯一命中时才认**。
    exact, ci = {}, defaultdict(list)
    for i, w in con.execute("SELECT id, word FROM dict"):
        k = norm_apos(w)
        exact[k] = i
        ci[k.lower()].append(i)
    print("■ 库内词形 %s（大小写敏感键 %s）"
          % (format(sum(len(v) for v in ci.values()), ","), format(len(exact), ",")))

    def lookup(w0, st):
        k = norm_apos(w0)
        if k in exact:
            return exact[k]
        hit = ci.get(k.lower()) or []
        if len(hit) == 1:
            st["大小写不同，唯一命中 ⇒ 认"] += 1
            return hit[0]
        if hit:
            st["🔴 大小写不同且**多行同名**，不猜，跳过"] += 1
        return None

    st = Counter()
    raw_seen = set()
    rows = []                       # (word_id, ipa, notation, region, tags, src, src_ref)
    taken = defaultdict(set)        # word_id → {(归一键, notation)}
    # 🔴 **`dict.ipa` 本身必须当成一个源。**
    #    探针给的上限 1,725,139 = `dict.ipa` ∪ 各版 dump；只扫 dump 得到 1,714,298，
    #    **差的 10,841 个词形是库里早就有、而各版 dump 里再也扫不出来的**
    #    （原始买入层 + 早期 enrich，来源没记录 ⇒ `src='legacy'`）。
    #    只从 dump 建新表 = 展示层从 `dict.ipa` 切到 `pronunciation` 那天，
    #    这一万多个词的音标**凭空消失** —— `[[fix-regression-and-gate]]` 记的
    #    「第二种机制」原文：换了读取路径、数据一个字节没丢、查原列永远绿，
    #    而用户看到的是错的。
    # ⚠️ 优先级放**最后**：法文版是有据可查的源，`legacy` 连来源都证明不了
    #    （`dict.ipa_src` 317,042 行全是 NULL，`[[ipa-provenance-columns]]` 那条一直没回填）。
    #    所以 legacy 只在"别处没有"时成为首选。
    legacy = [(norm_apos(w), ipa) for w, ipa in con.execute(
        "SELECT word, ipa FROM dict WHERE ipa IS NOT NULL AND TRIM(ipa)<>''")]
    print("\n■ legacy（`dict.ipa`）%s 个词形" % format(len(legacy), ","))

    # 🔴 先**按词形攒齐所有源的候选**，再逐词剔"多挂了一个词"的那种。
    #    不能边扫边写 —— `drop_phrase` 的锚要用**优先级最高那一版**给的音位式，
    #    而 `Neuf` 那条脏数据来自别的版：不攒齐就没有锚可比。
    cand = defaultdict(list)        # word_id → [(ipa, notation, region, tags, ref, src)]
    for name, path, lc, bare_ok in SOURCES:
        print("\n■ %s …" % name, flush=True)
        got = harvest(name, path, lc, bare_ok, st, limit, raw_seen)
        add = 0
        for w, lst in got.items():
            wid = lookup(w, st)
            if wid is None:
                st["🔴 词形不在 dict（阶段 3 应已全收）"] += len(lst)
                continue
            for ipa, notation, region, tags, ref in lst:
                cand[wid].append((ipa, notation, region, tags, ref, name))
                add += 1
        print("   候选 %s 条（累计 %s）" % (format(add, ","), format(
            sum(len(v) for v in cand.values()), ",")))

    # 🔴 legacy 也必须进 `cand`，**不能等 `drop_phrase` 跑完再追加**。
    #    第一版我把它接在后面，结果 206 条 legacy 从没过过滤器 —— 闸一查就露馅。
    #    凡是"新加一路数据"，先问一句：**它绕过了哪几道已有的处理？**
    for w, ipa in legacy:
        wid = exact.get(w)
        if wid is None:
            continue
        raw_seen.add(w)
        for q, part in enumerate(split_multi(ipa)):
            got = parse_ipa(part, w, st, bare_ok=True)
            if got:
                cand[wid].append((got[0], "phonemic", None, got[2],
                                  "dict.ipa:%d.%d" % (wid, q), "legacy"))
    print("   候选合计 %s 条" % format(sum(len(v) for v in cand.values()), ","))

    print("\n■ 逐词剔「多挂了一个词」并跨源去重…", flush=True)
    for wid, lst in cand.items():
        src_of = {c[4]: c[5] for c in lst}
        for ipa, notation, region, tags, ref in drop_phrase(
                [c[:5] for c in lst], st):
            src = src_of[ref]
            k = (norm_key(ipa), notation)
            if k in taken[wid]:            # 高优先级的源已经给过同一个音
                st["跨源重复（保留高优先级那份）"] += 1
                continue
            taken[wid].add(k)
            rows.append((wid, ipa, notation, region,
                         json.dumps(tags, ensure_ascii=False) if tags else None,
                         src, ref))
    print("   落点 %s 行" % format(len(rows), ","))
    return rows, st, raw_seen


def pick_primary(rows):
    """每个词形恰好一条 `is_primary`：**音位式 > 音值式；源按 SOURCES 顺序**。"""
    order = {n: i for i, (n, _p, _l, _b) in enumerate(SOURCES)}
    order["legacy"] = len(SOURCES)      # 证明不了来源 ⇒ 排最后
    best = {}
    for idx, r in enumerate(rows):
        wid, _ipa, notation, region, _tags, src, _ref = r
        # 排序键：音位式优先 / 源优先 / 通用读音优先于地区读音 / 先到先得
        k = (0 if notation == "phonemic" else 1, order.get(src, 99),
             0 if region in (None, "fr-FR") else 1, idx)
        if wid not in best or k < best[wid][0]:
            best[wid] = (k, idx)
    return {i for _k, i in best.values()}


def audit(rows, st, con, sample, raw_seen=None):
    print("\n══ 解析统计 ══")
    for k, v in st.most_common():
        print("   %-52s %10s" % (k, format(v, ",")))

    wids = {r[0] for r in rows}
    n_dict = con.execute("SELECT count(*) FROM dict").fetchone()[0]
    n_lem = con.execute("SELECT count(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    lem = {i for (i,) in con.execute("SELECT id FROM dict WHERE is_lemma=1")}
    sen = {i for (i,) in con.execute("SELECT DISTINCT word_id FROM sense WHERE hidden=0")}
    print("\n══ 覆盖（这一步之后）══")
    for tag, tot, hit in (("全部词形", n_dict, len(wids)),
                          ("像词头", n_lem, len(wids & lem)),
                          ("有可见义项", len(sen), len(wids & sen))):
        print("   %-12s %10s ｜ 有音标 %10s  (%.1f%%)"
              % (tag, format(tot, ","), format(hit, ","), 100.0 * hit / tot))

    per = Counter()
    for r in rows:
        per[r[0]] += 1
    print("\n══ 每个词形几条音标 ══")
    d = Counter(min(v, 5) for v in per.values())
    for k in sorted(d):
        print("   %s 条%-4s %10s" % (k, "+" if k == 5 else "", format(d[k], ",")))
    print("   notation：%s" % Counter(r[2] for r in rows).most_common())
    print("   region  ：%s" % Counter(r[3] for r in rows).most_common(8))

    if raw_seen:
        ids = {norm_apos(w): i for i, w in con.execute("SELECT id, word FROM dict")}
        raw_ids = {ids[w] for w in raw_seen if w in ids}
        lost = raw_ids - wids
        print("\n══ 护栏扔掉了多少**词形**（不是行）══")
        print("   源头给过 ipa 的词形 %s ｜ 落库 %s ｜ **一条都没剩 %s**"
              % (format(len(raw_ids), ","), format(len(wids), ","), format(len(lost), ",")))
        print("   其中像词头 %s ｜ 有可见义项 %s"
              % (format(len(lost & lem), ","), format(len(lost & sen), ",")))
        if lost:
            words = dict(con.execute("SELECT id, word FROM dict"))
            xs = sorted(lost & sen)[:10] or sorted(lost)[:10]
            print("   样本：%s" % " · ".join(words[i] for i in xs))

    if sample:
        words = dict(con.execute("SELECT id, word FROM dict"))
        prim = pick_primary(rows)
        by = defaultdict(list)
        for i, r in enumerate(rows):
            by[r[0]].append((i, r))
        keys = list(by)
        random.Random(4).shuffle(keys)
        print("\n══ 抽样 %d 个词形（★ = is_primary）══" % sample)
        for wid in keys[:sample]:
            print("   %-24s" % words[wid][:24], end="")
            print("  ｜  ".join(
                "%s%s%s%s" % ("★" if i in prim else " ", r[1],
                              "" if r[2] == "phonemic" else "(音值)",
                              "" if not r[3] else "·" + r[3])
                for i, r in by[wid][:4]))


def apply_rows(rows):
    """整张表**重建**。本段是唯一写 `pronunciation` 的脚本，所以重建是幂等的 ——
    判据一改就重跑，不做增量补丁（`[[prefer-reversible-designs]]`：
    可重建 > 可回滚，而且省掉"补丁脚本"这一整类会漂的东西）。"""
    prim = pick_primary(rows)
    payload = [(r[0], r[1], r[2], r[3], r[4], 1 if i in prim else 0, r[5], r[6])
               for i, r in enumerate(rows)]
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    old = con.execute("SELECT count(*) FROM pronunciation").fetchone()[0]
    con.close()
    print("\n■ 写库：%s 行（原有 %s，整表重建），其中 is_primary %s"
          % (format(len(payload), ","), format(old, ","), format(len(prim), ",")))
    with dbtool.session("keep-v3-pron",
                        expect={"#pronunciation": len(payload) - old}) as s:
        s.execute("DELETE FROM pronunciation")
        s.executemany(
            "INSERT OR IGNORE INTO pronunciation "
            "(word_id,ipa,notation,region,tags,is_primary,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?)", payload)
    return 0


def verify():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok = True

    def chk(name, got, want):
        nonlocal ok
        ok &= got == want
        print("   %s %-50s %10s  期望 %s"
              % ("✓" if got == want else "🔴", name, format(got, ","), format(want, ",")))

    n = con.execute("SELECT count(*) FROM pronunciation").fetchone()[0]
    nw = con.execute("SELECT count(DISTINCT word_id) FROM pronunciation").fetchone()[0]
    print("■ pronunciation %s 行 / %s 个词形" % (format(n, ","), format(nw, ",")))
    chk("① 孤儿（word_id 不在 dict）",
        con.execute("SELECT count(*) FROM pronunciation p LEFT JOIN dict d "
                    "ON d.id=p.word_id WHERE d.id IS NULL").fetchone()[0], 0)
    chk("② 每个词形的 is_primary 不是恰好 1 条",
        con.execute("SELECT count(*) FROM (SELECT word_id FROM pronunciation "
                    "GROUP BY word_id HAVING sum(is_primary)<>1)").fetchone()[0], 0)
    chk("③ 音标里还带定界符 / \\ [ ]",
        con.execute("SELECT count(*) FROM pronunciation WHERE ipa GLOB '*[/\\[\\]]*' "
                    "OR ipa LIKE '%\\%' ESCAPE '\\'").fetchone()[0], 0)
    chk("④ 音标里还带 `^((` 标记",
        con.execute("SELECT count(*) FROM pronunciation WHERE ipa LIKE '%^((%'"
                    ).fetchone()[0], 0)
    # 🔴 这里**曾经**是一条形式判据：「单词词形的音标里有空格」。它报 1,085 条红，
    #    我逐条读下来**绝大多数是对的**（`HPGP`→`aʃ pe ʒe pe`、`09`→`ze.ʁo nøf`、
    #    `WWW`→`du.blə.ve ×3`：字母/数字逐个念，空格本来就该有）。
    #    ⇒ 那是**闸过期**，不是数据错（`[[fix-regression-and-gate]]`，同一形状第五次）。
    #    现在这条闸查的是**生成侧真正用的那个判据**（`drop_phrase`），
    #    而且在**读取路径上重查一遍**（`[[it-regression-gate]]`：写入列与读取路径各查一次）。
    # ⚠️ **锚的定义必须和 `drop_phrase` 逐字一致**（第一条音位式，没有就退到第一条），
    #    不能图省事用 `is_primary` —— 那一版报了 2 条红，查下去是**闸和生成侧用了
    #    两个不同的锚**，数据没问题。闸与它守的那段逻辑判据不一致 = 闸在报自己的 bug。
    by = defaultdict(list)
    for wid, ipa, notation in con.execute(
            "SELECT word_id, ipa, notation FROM pronunciation ORDER BY id"):
        by[wid].append((ipa, notation))
    leak = 0
    for wid, lst in by.items():
        if len(lst) < 2:
            continue
        a = next((i for i, n in lst if n == "phonemic"), lst[0][0])
        a_s, a_l = norm_key(a), loose_key(a)
        for ipa, _n in lst:
            k = norm_key(ipa)
            if k == a_s:
                continue
            if (len(k) - len(a_s) >= 2 and k.endswith(a_s)) or (
                    " " in ipa.strip()
                    and loose_key(ipa.strip().rsplit(" ", 1)[-1]) == a_l):
                leak += 1
    chk("⑤ 还有「前面多挂了一个词」的音标（读取路径重查）", leak, 0)
    chk("⑤' 一格里塞了两条音标（`], [`）",
        con.execute(r"SELECT count(*) FROM pronunciation WHERE ipa LIKE '%], [%' "
                    r"OR ipa LIKE '%\, \%' OR ipa LIKE '%/, /%'").fetchone()[0], 0)
    chk("⑤'' 音标尾巴上带省略号",
        con.execute("SELECT count(*) FROM pronunciation "
                    "WHERE ipa LIKE '%...' OR ipa LIKE '%…'").fetchone()[0], 0)
    chk("⑥ notation 取值越界",
        con.execute("SELECT count(*) FROM pronunciation "
                    "WHERE notation NOT IN ('phonemic','narrow')").fetchone()[0], 0)
    # ⑦ 读取路径也查一次（`[[it-regression-gate]]`：写入列与读取路径各查一次）
    bad = con.execute(
        "SELECT count(*) FROM dict d JOIN pronunciation p ON p.word_id=d.id AND p.is_primary=1 "
        "WHERE d.ipa IS NOT NULL AND d.ipa<>'' AND d.ipa<>p.ipa").fetchone()[0]
    print("   📋 `dict.ipa` 与新层首选不一致 %s 行 —— 展示层切到新层之前，"
          "这两列会并存（降列在阶段 8 之后）" % format(bad, ","))
    print("%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="每个源只扫前 N 个条目")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return 1 if selftest() else 0
    if a.verify:
        return verify()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, st, raw_seen = build(con, a.limit)
    audit(rows, st, con, a.sample, raw_seen)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    con.close()
    apply_rows(rows)
    return verify()


if __name__ == "__main__":
    sys.exit(main())
