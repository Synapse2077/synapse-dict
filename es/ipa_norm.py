#!/usr/bin/env python3
"""es 音标归一化 —— **本词典西语音标约定的唯一实现**。2026-08-01。

es 专用，不 import 其他语种（见 multilang-decoupling-essence 铁律）。

═══ 为什么有这个文件 ═══
在此之前，西语的归一化规则**只存在于 `packages/dict-core/src/spanish.ts` 的
`normalizeSpanishIpa` 里**，也就是：
  · 只对 web 这一个客户端生效——移动端/导出/API 直读都会拿到另一套记法；
  · 每次查询重算一遍；
  · 拿不到词形，所以任何"以拼写为判据"的规则都做不了。
2026-08-01 定：**约定归一在入库时做一次、落进列，不做展示层补丁**（见 docs/FRAMEWORK.md §五之二）。
本文件就是那个唯一实现。`spanish.ts` 的函数保留为幂等兜底，但不再是唯一实现。

═══ 三列各司其职 ═══
    phonetic       本词典的约定值（一套记法、全库一致，任何客户端直接可用）
    phonetic_raw   源值，忠实照搬（可审计、可回滚）
    phonetic_src   来源（见 backfill_src.py）

═══ 🔴 devoice_coda 为什么不能用 b_ipa.py 当判据 ═══
`b_ipa.py` 自己也实现了 coda 浊化（`raptor` → `rabˈtoɾ`、`acto` → `ˈaɡto`），
它复刻的是 kaikki 的约定，不是正字法 —— 拿它当"拼写的代言人"是循环论证。
而且它**过度应用**：`atlas` 规则给 `ˈadlas`，而库里 `ˈatlas` 才是对的。
→ 判据必须直接来自**词形拼写**，见 `devoice_coda` 的算法说明。

用法：
    import ipa_norm
    ipa_norm.normalize("raptor", "rabˈtoɾ")     # → 'rapˈtoɾ'
    python3 -m unittest test_ipa_norm            # 跑归一化的金标准测试
"""
import re
import unicodedata

# ── 音位 ────────────────────────────────────────────────────────────────
# 🔴 判断"某个塞音是不是 coda"要看它后面跟什么。**滑音和流音都不算**：
#    · 塞音 + 滑音（`tj` `kw`）是音节起始，不是 coda —— `septiembre` 的 /tj/；
#    · ⚠️ **流音（l r）曾被一并排除，那是多余的，2026-08-01 已去掉。**
#      当初 `septiembre` 对不齐的真正原因只是滑音 `tj`，我一次改了两处、把不该加的也加了。
#      流音留着无害 —— `libro`/`padre`/`otro` 的塞音本来就与字母清浊一致，替换后原值不变；
#      而排除它会漏掉整个 `tl`/`dl` 族：`atleta` 库内 `adˈleta`，**西语版写 `aˈtleta`**。
#      这条由豆包评审提出、**回西语版 dump 确定性核实后**才采纳：它给的理由（tl 不是合法
#      起始丛、t 属前一音节 coda）其实不对（西语版切成 a.tle.ta，t 是起始），但结论对 ——
#      **字母是 t，音就该是 t，与音节归属无关。**
#      → 本规则的本质是「字母与音位的清浊一致」，音节位置只用来圈定候选。
#    · 🔴 塞音 + ʃ/ʒ 是**塞擦音**（/t͡ʃ/ /d͡ʒ/），更不是 coda。库里存的是带连结弧的 `t͡ʃ`，
#      `basic()` 把弧去掉后变成 `tʃ`，看起来就像"t 后面跟辅音" —— 第一版因此把
#      `derecho` `deˈɾet͡ʃo` 改成了 `deˈɾekʃo`（拼写 `ch` 的 c 被当成 coda）。
#      **这条是全量普查才发现的：测试里一个 ch 词都没有。**
IPA_VOWELS = set("aeiou")
IPA_GLIDES = set("jw")
IPA_LIQUIDS = set("lɾrʎ")
IPA_AFFRICATE_TAIL = set("ʃʒ")
IPA_NONCODA_NEXT = IPA_VOWELS | IPA_GLIDES | IPA_AFFRICATE_TAIL   # 流音已移出，见上
# 记号：重音符、次重音、音节点。判断"下一个音段"时要跳过它们。
MARKS = set("ˈˌ.")

# 西语正字法的元音（含重音字母与 ü）。i/u 作滑音时本来就在这个集合里。
SPELL_VOWELS = set("aeiouáéíóúü")
SPELL_LIQUIDS = set()      # 空集：流音不再排除，见文件头说明（保留常量以便回溯）

# 词形里的塞音字母 → 它在音位式里应有的形态。
# c/k/q → k；b/v → b（西语 b 与 v 同音）；g → ɡ（U+0261，不是 ASCII g）。
LETTER_STOP = {"p": "p", "t": "t", "c": "k", "k": "k", "q": "k",
               "b": "b", "v": "b", "d": "d", "g": "ɡ"}
# 音位式里参与 coda 浊化的塞音（既含清也含浊，因为要按位替换）
IPA_STOPS = set("ptkbdɡ")
# 叠塞音：西语音系不允许，出现即说明撞上了外来词的双写字母
_GEMINATE = re.compile(r"([ptkbdɡ])\1")


def strip_narrow(s):
    """只留音位式，丢严式。

    kaikki 少数条目把两者拼在一串：`/ˈɡɾaθjas/ [ˈɡɾa.θjas]`。
    库内存的是裸串，所以两种形态都要能处理。
    """
    if not s:
        return s
    s = s.strip()
    m = re.search(r"/([^/]*)/", s)          # 有斜杠对 → 只取音位段
    if m:
        return m.group(1).strip()
    return re.sub(r"\s*\[[^\]]*\]\s*", "", s).strip()


def basic(s):
    """记法层归一：去连结弧、音节点、长音符、升符 ̝ / 降符 ̞。

    升降符是严式记号（`w̝`、`β̞`），音位式格子里不该有。
    """
    if not s:
        return s
    s = s.replace("͡", "")
    s = re.sub(r"[.ː]", "", s)
    return s.replace("̝", "").replace("̞", "")


def spirants_to_stops(s):
    """擦音变体 → 音位：ð→d、β→b、ɣ→ɡ、ŋ→n。

    库内约 1.2 万行把这些**同位异音**写进了音位式格子（`ˈliβɾo` / `ˈxuɣo` / `iŋkonfoɾ…`），
    而同类词的另一批写的是塞音 —— 纯属内部不一致。
    RAE 教学式音标写 /b d ɡ n/，不写变体。2026-07-31 决策，当时做在展示层，现搬进数据。
    """
    if not s:
        return s
    return (s.replace("ð", "d").replace("β", "b")
             .replace("ɣ", "ɡ").replace("ŋ", "n"))


def _coda_stops_from_spelling(word):
    """词形里处于 coda（后面紧跟辅音字母）的塞音字母 → 目标音位，按出现顺序。

    例：`septiembre` → ['p'(pt), 'b'(br)]；`acto` → ['k'(ct)]；`abdicar` → ['b'(bd)]。
    """
    w = unicodedata.normalize("NFC", word.lower())
    out = []
    for i, ch in enumerate(w):
        # 🔴 字母 x = /ks/，那个 k 后面永远跟着 s，**永远处于 coda**，必须计入序列。
        #    不计入会导致跨词错位：`óxido de magnesio` 的 want 只剩 magnesio 的 ɡ、
        #    pos 只剩 óxido 的 k，长度"恰好都是 1"→ 把 ˈoksido 改回 ˈoɡsido，
        #    正好**撤销** fixes/fix_x_gs.py 刚修好的东西。2026-08-02 实测到 4 行。
        #    ⚠️ 词首 x 读 /s/ 不是 /ks/（`xerocopia`→seɾoˈkopja），不计。
        if ch == "x":
            if i > 0:
                out.append("k")
            continue
        if ch not in LETTER_STOP:
            continue
        nxt = w[i + 1] if i + 1 < len(w) else ""
        # 🔴 `h` 要跳过两类：`ch` 是二合字母（/t͡ʃ/，那个 c 不是 coda 塞音），
        #    其余位置的 h 在西语里不发音，也不构成 coda 环境。
        if nxt == "h":
            continue
        if (nxt and nxt.isalpha()
                and nxt not in SPELL_VOWELS and nxt not in SPELL_LIQUIDS):
            out.append(LETTER_STOP[ch])
    return out


def _coda_stop_positions(s):
    """音位式里处于 coda（后面紧跟辅音音段）的塞音位置，按出现顺序。"""
    out = []
    for i, ch in enumerate(s):
        if ch not in IPA_STOPS:
            continue
        j = i + 1
        while j < len(s) and (s[j] in MARKS or unicodedata.category(s[j]) == "Mn"):
            j += 1
        if j < len(s) and s[j] not in IPA_NONCODA_NEXT:
            out.append(i)
    return out


def devoice_coda(word, s):
    """把 coda 位置由清音字母派生出的浊塞音还原为清音（跟西语版 / RAE 标准）。

    ═══ 判据 ═══
    英文版维基如实记录口语浊化（`raptor` → `rabˈtoɾ`），西语版写 RAE 标准清音（`rapˈtoɾ`）。
    本词典跟后者：面向学习者要规范音，而且这与 `spirants_to_stops` 是同一件事——
    都是把音位变体从音位式格子里请出去。

    ═══ 算法：按序对齐，长度不等就整条跳过 ═══
    ① 从**词形**取出 coda 塞音字母序列（后跟辅音字母者），映射到目标音位；
    ② 从**音位式**取出 coda 塞音位置序列；
    ③ **两者长度相等才动手**，逐位把音位式的塞音替换成词形给出的目标。
       长度不等说明存在 `x`→/ks/ 这类一对多、或我没想到的情况 —— 一律跳过，不猜。

    这样既能修 `septiembre` 这种**一个词里既有派生浊音又有原生浊音**的情况
    （`sebˈtjembɾe` → `sepˈtjembɾe`：第一个 b 来自 `pt` 的 p，第二个来自 `br` 的 b），
    又不会碰 `abdicar`（两个都是原生，替换后与原值相同）。
    """
    if not s or not word:
        return s
    want = _coda_stops_from_spelling(word)
    pos = _coda_stop_positions(s)
    if not want or len(want) != len(pos):
        return s
    out = list(s)
    for p, target in zip(pos, want):
        out[p] = target
    res = "".join(out)
    # 🔴 第三道保守闸：改完若**产生了原本没有的叠塞音**，整条不动。
    #    西语音系不允许 /pp tt kk bb dd ɡɡ/，出现它一定是外来词的双写字母
    #    （vedette / yuppie / sketches / rockers / tickets，实测 664 行）撞上了本规则。
    #    外来词是本项目反复栽跟头的雷区（见 es-dict-pipeline：别用 G2P 重算外来词），
    #    这里不试图修它们，只保证不把它们改得更糟。
    if _GEMINATE.search(res) and not _GEMINATE.search(s):
        return s
    return res


def normalize(word, s):
    """完整流水线。**顺序是判据，别改**（见 es-dict-pipeline：字符替换表顺序踩过坑）。

    严式 → 记法 → 擦音归音位 → coda 清音。
    `devoice_coda` 放最后，是因为它只认 b/d/ɡ；若在 `spirants_to_stops` 之前跑，
    `β/ð/ɣ` 还没变成塞音，会漏掉一批。
    """
    s = strip_narrow(s)
    s = basic(s)
    s = spirants_to_stops(s)
    s = devoice_coda(word, s)
    return s


if __name__ == "__main__":
    for w, v in (("raptor", "rabˈtoɾ"), ("acto", "ˈaɡto"), ("septiembre", "sebˈtjembɾe"),
                 ("abdicar", "abdiˈkaɾ"), ("ritmo", "ˈridmo"), ("atlas", "ˈatlas"),
                 ("libro", "ˈliβɾo"), ("gracias", "ˈɡɾaθjas [ˈɡɾa.θjas]")):
        print(f"  {w:12} {v:26} → {normalize(w, v)}")
