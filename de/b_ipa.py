#!/usr/bin/env python3
"""
德语拼写 → IPA 规则转换器（G2P）。德语正字法对发音**规则性强**（末尾清化、ich/ach-laut、
sch/st-/sp-、长短元音靠双辅音/h/ie 判、ei/eu/umlaut），故可像西语/意语造 G2P 补变位形 IPA。

word_to_ipa("gehen") -> "/ˈɡeːən/"；含外文字母/无法处理返回 None（不硬凑）。

已知不可从拼写推的残点（与意语 e/o 同性质，eval 量化）：
  · **闭音节 / ch 前元音长短**（Buch /buːx/ 长 vs Bach /bax/ 短、Weg /veːk/ 长 vs weg /vɛk/ 短，
    词汇性）——按规则默认，常见短词表兜一部分。
  · **外来词重音**（Studént、Natúr）——本引擎按日耳曼语默认（词根首音节），外来词会错。
  · **v 清浊**（native Vater /f/ vs loan Vase /v/）——默认 f。
对齐 kaikki 约定：长音 ː、主重音 ˈ、音节点 . 分隔、小舌 ʁ、词首元音声门塞音 ʔ、非重读 e→ə、-er→ɐ。
"""
import re

LETTERS = set("abcdefghijklmnopqrstuvwxyzäöüß")
VOWELS = set("aeiouäöüy")

VMAP = {  # 元音字母 → (长音, 短音)
    "a": ("aː", "a"), "e": ("eː", "ɛ"), "i": ("iː", "ɪ"), "o": ("oː", "ɔ"),
    "u": ("uː", "ʊ"), "ä": ("ɛː", "ɛ"), "ö": ("øː", "œ"), "ü": ("yː", "ʏ"),
    "y": ("yː", "ʏ"),
}
DIPH = {"ei": "aɪ", "ai": "aɪ", "ey": "aɪ", "ay": "aɪ",
        "eu": "ɔʏ", "äu": "ɔʏ", "au": "aʊ"}

SHORT_MONO = {  # 常见短元音闭音节词（拼写推不出，词汇性）
    "mit", "in", "an", "um", "am", "im", "es", "das", "was", "bis", "man",
    "des", "hin", "weg", "ab", "ob", "und", "von", "vom", "zum", "zur",
    "den", "wen", "bin", "hat", "ist", "als", "ins", "ans", "hab",
}
UNSTRESSED_PREFIX = ("ver", "zer", "ent", "emp", "be", "ge", "er")


def _prefix_len(w):
    """不重读前缀长度；仅当其后词根 ≥4 字母才算前缀，避免 gehen/geben/beten 误判
    （bekommen 的 kommen=6 是前缀；gehen 的 hen=3 是词根）。"""
    for p in UNSTRESSED_PREFIX:
        if w.startswith(p) and len(w) - len(p) >= 4:
            return len(p)
    return 0


def _letters_ok(w):
    return bool(w) and all(c in LETTERS for c in w)


def g2p(w):
    """拼写(小写) → token 列表。元音 token=[音,'V',长bool,源字母]；辅音=[音,'C',False,'']。
    返回 None 遇未知字符。"""
    toks = []
    i, n = 0, len(w)
    plen = _prefix_len(w)      # 不重读前缀长度（供 morpheme 边界判断 st/sp）

    def cons_run_len(j):
        k = 0
        while j < n and w[j] not in VOWELS:
            j += 1; k += 1
        return k

    def prev_vowel_letter():
        for t in reversed(toks):
            if t[1] == "V":
                return t[3]
        return None

    while i < n:
        c = w[i]
        two = w[i:i + 2]
        three = w[i:i + 3]

        if c in VOWELS:
            # 词尾 -ig → /ɪç/（König/wichtig/wehmütig；-ige/-igen 前有元音时仍 /ɪɡ/，不在此列）
            if c == "i" and w[i:] == "ig":
                toks.append(["ɪ", "V", False, "i"]); toks.append(["ç", "C", False, ""])
                i += 2; continue
            if two in DIPH:
                toks.append([DIPH[two], "V", True, two]); i += 2; continue
            if two == "ie":
                toks.append(["iː", "V", True, "i"]); i += 2; continue
            if i + 1 < n and w[i + 1] == c and c in "aeou":     # aa/ee/oo/uu
                toks.append([VMAP[c][0], "V", True, c]); i += 2; continue
            # 元音后 h → 哑音伸长（gehen/sehen/Uhr/ihm），吞掉 h
            if i + 1 < n and w[i + 1] == "h":
                toks.append([VMAP[c][0], "V", True, c]); i += 2; continue
            run = cons_run_len(i + 1)
            if run == 0:
                if i + 1 >= n and c == "e":
                    toks.append(["ə", "V", False, "e"]); i += 1; continue
                toks.append([VMAP[c][0], "V", True, c]); i += 1; continue
            long_v = (run == 1 and w[i + 1] != "x")   # 单辅音→长；双/多辅音、x(=ks)→短
            ph = VMAP[c][0] if long_v else VMAP[c][1]
            toks.append([ph, "V", long_v, c]); i += 1; continue

        # 多字母辅音
        if three == "sch":
            toks.append(["ʃ", "C", False, ""]); i += 3; continue
        if w[i:i + 4] == "tsch":
            toks.append(["tʃ", "C", False, ""]); i += 4; continue
        if two == "ch":
            pv = prev_vowel_letter()
            back = pv in ("a", "o", "u", "au")     # ach-laut x；否则 ich-laut ç
            toks.append(["x" if back else "ç", "C", False, ""]); i += 2; continue
        if two == "ck":
            toks.append(["k", "C", False, ""]); i += 2; continue
        if two == "ph":
            toks.append(["f", "C", False, ""]); i += 2; continue
        if two == "qu":
            toks += [["k", "C", False, ""], ["v", "C", False, ""]]; i += 2; continue
        if two in ("dt", "th"):
            toks.append(["t", "C", False, ""]); i += 2; continue
        if two == "ng":
            toks.append(["ŋ", "C", False, ""]); i += 2; continue
        if two == "nk":
            toks += [["ŋ", "C", False, ""], ["k", "C", False, ""]]; i += 2; continue
        if two == "pf":
            toks += [["p", "C", False, ""], ["f", "C", False, ""]]; i += 2; continue
        if two == "ss":
            toks.append(["s", "C", False, ""]); i += 2; continue
        if two == "tz":
            toks.append(["ts", "C", False, ""]); i += 2; continue
        # 双写辅音 → 单音（fall→fal、Kammer、rennen；ss 已在上）
        if len(two) == 2 and two[0] == two[1] and two[0] in "bdfgklmnprt":
            _dbl = {"b": "b", "d": "d", "f": "f", "g": "ɡ", "k": "k", "l": "l",
                    "m": "m", "n": "n", "p": "p", "r": "ʁ", "t": "t"}
            toks.append([_dbl[two[0]], "C", False, ""]); i += 2; continue
        # 词首 或 不重读前缀后 的 st/sp → ʃt/ʃp
        if two in ("st", "sp") and (i == 0 or i == plen):
            toks += [["ʃ", "C", False, ""], [w[i + 1], "C", False, ""]]; i += 2; continue

        # 单辅音
        if c == "ß":
            toks.append(["s", "C", False, ""]); i += 1; continue
        if c == "s":
            nxt_v = i + 1 < n and w[i + 1] in VOWELS
            toks.append(["z" if nxt_v else "s", "C", False, ""]); i += 1; continue
        if c == "v":
            toks.append(["f", "C", False, ""]); i += 1; continue
        if c == "w":
            toks.append(["v", "C", False, ""]); i += 1; continue
        if c == "z":
            toks.append(["ts", "C", False, ""]); i += 1; continue
        if c == "j":
            toks.append(["j", "C", False, ""]); i += 1; continue
        if c == "r":
            toks.append(["ʁ", "C", False, ""]); i += 1; continue
        if c == "h":
            toks.append(["h", "C", False, ""]); i += 1; continue    # 剩下的 h＝音节首，发音
        if c == "c":
            nx = w[i + 1] if i + 1 < n else ""
            toks.append(["ts" if nx in "eiäöy" else "k", "C", False, ""]); i += 1; continue
        if c == "x":
            toks += [["k", "C", False, ""], ["s", "C", False, ""]]; i += 1; continue
        SIMPLE = {"b": "b", "d": "d", "f": "f", "g": "ɡ", "k": "k", "l": "l",
                  "m": "m", "n": "n", "p": "p", "t": "t"}
        if c in SIMPLE:
            toks.append([SIMPLE[c], "C", False, ""]); i += 1; continue
        return None
    return toks


def _place_stress(toks, w):
    vidx = [k for k, t in enumerate(toks) if t[1] == "V"]
    if not vidx:
        return None
    if _prefix_len(w) and len(vidx) >= 2:
        return vidx[1]               # 不重读前缀 → 重音落第二元音
    return vidx[0]


def _reduce_schwa(toks, stress_k):
    """非重读的源'e'元音 → ə（德语弱化核心）。-er 尾在 render 里转 ɐ。"""
    for k, t in enumerate(toks):
        if t[1] == "V" and k != stress_k and t[3] == "e":
            t[0] = "ə"; t[2] = False


def _final_devoice(toks):
    dev = {"b": "p", "d": "t", "ɡ": "k", "z": "s", "v": "f"}
    for idx in range(len(toks) - 1, -1, -1):
        if toks[idx][1] == "V":
            break
        if toks[idx][0] in dev:
            toks[idx][0] = dev[toks[idx][0]]
    return toks


def _render(toks, stress_k):
    syl = [k for k, t in enumerate(toks) if t[1] == "V"]
    if not syl:
        return None
    # 音节起点：元音前辅音，单辅音归后音节 onset，多辅音末辅音作后 onset、其余留前 coda
    starts = {}
    for si, vk in enumerate(syl):
        prev_v = syl[si - 1] if si > 0 else -1
        cons = list(range(prev_v + 1, vk))
        if not cons:
            starts[vk] = vk
        elif si == 0:
            starts[vk] = cons[0]
        elif len(cons) == 1:
            starts[vk] = cons[0]
        else:
            starts[vk] = cons[-1]
    start_at = {starts[vk]: vk for vk in syl}
    stress_start = starts.get(stress_k)
    out = []
    for k, t in enumerate(toks):
        if k in start_at:
            if out:
                out.append("ˈ" if k == stress_start else ".")
        if k == stress_start and k not in start_at:
            out.append("ˈ")
        out.append(t[0])
    body = "".join(out)
    if "ˈ" not in body:
        body = "ˈ" + body
    # 非重读 -er / -e r → ɐ（vater→faːtɐ, kinder→kɪndɐ）
    body = re.sub(r"əʁ(?=[.ˈ]|$)", "ɐ", body)
    body = re.sub(r"ɐ\.", "ɐ", body)          # ɐ 后不再留音节点
    return "/" + body + "/"


def word_to_ipa(word):
    if not word:
        return None
    w = word.strip().lower()
    if not _letters_ok(w):
        return None
    toks = g2p(w)
    if not toks:
        return None
    stress_k = _place_stress(toks, w)
    if w in SHORT_MONO:
        for t in toks:
            if t[1] == "V" and t[2]:
                t[0] = VMAP.get(t[3], (t[0], t[0]))[1]; t[2] = False
    _reduce_schwa(toks, stress_k)
    toks = _final_devoice(toks)
    return _render(toks, stress_k)


if __name__ == "__main__":
    tests = ["gehen", "Haus", "Tag", "mit", "Kind", "schön", "ich", "Bach",
             "Buch", "Vater", "Wasser", "Straße", "Zeit", "Freund", "Auto",
             "besuchen", "verstehen", "Mädchen", "größer", "Zug", "und",
             "Sport", "Kinder", "machen", "Freundschaft", "Universität"]
    for t in tests:
        print(f"  {t:14} -> {word_to_ipa(t)}")
