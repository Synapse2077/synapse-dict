#!/usr/bin/env python3
"""
西语拼写→IPA 规则转换器（对齐 kaikki 卡斯蒂利亚约定：ll/y→ʝ(yeísmo)、c/z→θ、
rr→r/单r→ɾ、ch→t͡ʃ、j&ge/gi→x、无音节点、升双元音用滑音j/w、降双元音保元音符）。

用途：给缺 IPA 的变位(59万,纯规则形态,无借词坑)规则补。**先拿14万有kaikki IPA的词
自证准确率**(见 b_ipa_eval.py)，达标才用。借词坑(México/whisky x不规则)全在lemma,交豆包。

token 结构：[phoneme, kind, has_accent, is_weak]；kind V(元音核候选)/G(滑音)/C(辅音)/Vg(降滑元音)
word_to_ipa("hablar") -> "/aˈblaɾ/"；不认识/含外文字母则返回 None（不硬凑）。
"""
import unicodedata

VOWELS = set("aeiouáéíóúü")
ACCENTED = set("áéíóú")
WEAK_UNACC = set("iuü")
DEACC = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u"}
G = "ɡ"                            # U+0261，与 kaikki 一致
ONSET_CLUSTERS = {p + q for p in "pbfkɡ" for q in "lɾ"} | {"tɾ", "dɾ"}
ALLOWED = set("abcdefghijklmnopqrstuvwxyzáéíóúüñ")


def _letters_ok(w):
    return all(ch in ALLOWED for ch in w)


def g2p(w):
    """字母→音位 token 列表。返回 None 表示遇到无法处理的字符。"""
    w = w.lower()
    toks = []
    i, n = 0, len(w)
    while i < n:
        c = w[i]
        nxt = w[i + 1] if i + 1 < n else ""
        nn = w[i + 2] if i + 2 < n else ""
        if c in VOWELS:
            toks.append([DEACC.get(c, c), "V", c in ACCENTED, c in WEAK_UNACC])
            i += 1; continue
        if c == "c":
            if nxt == "h":
                toks.append(["t͡ʃ", "C", False, False]); i += 2; continue
            toks.append(["θ" if nxt in "eiéí" else "k", "C", False, False]); i += 1; continue
        if c == "q":
            if nxt == "u" and nn in "eiéí":
                toks.append(["k", "C", False, False]); i += 2; continue
            toks.append(["k", "C", False, False]); i += 1; continue
        if c == "g":
            if nxt in "eiéí":
                toks.append(["x", "C", False, False]); i += 1; continue
            if nxt == "u" and nn in "eiéí":
                toks.append([G, "C", False, False]); i += 2; continue
            if nxt == "ü" and nn in "eiéí":
                toks.append([G, "C", False, False]); toks.append(["w", "G", False, False]); i += 2; continue
            if nxt == "u" and nn in "aoáó":
                toks.append([G, "C", False, False]); toks.append(["w", "G", False, False]); i += 2; continue
            toks.append([G, "C", False, False]); i += 1; continue
        if c == "l" and nxt == "l":
            toks.append(["ʝ", "C", False, False]); i += 2; continue
        if c == "r" and nxt == "r":
            toks.append(["r", "C", False, False]); i += 2; continue
        if c == "r":
            prev = toks[-1][0] if toks else None
            toks.append(["r" if (prev is None or prev in ("n", "l", "s")) else "ɾ", "C", False, False])
            i += 1; continue
        if c == "y":
            if nxt in VOWELS:
                toks.append(["ʝ", "C", False, False])
            else:
                toks.append(["i", "V", False, True])   # 作元音 i（降双元音/单独 y）
            i += 1; continue
        if c == "h":
            if nxt == "u" and nn in VOWELS:      # hu+元音 → w̝（huevo/huanca）
                toks.append(["w̝", "G", False, False]); i += 2; continue
            i += 1; continue
        simple = {"b": "b", "v": "b", "d": "d", "f": "f", "j": "x", "k": "k",
                  "l": "l", "m": "m", "n": "n", "ñ": "ɲ", "p": "p", "s": "s",
                  "t": "t", "w": "w", "z": "θ", "x": "ks"}
        if c in simple:
            ph = simple[c]
            if ph == "ks":
                toks.append(["k", "C", False, False]); toks.append(["s", "C", False, False])
            else:
                toks.append([ph, "C", False, False])
            i += 1; continue
        return None
    return toks


def _process_vowels(toks):
    """在每个元音串里定音节核(peak)：强元音/带重音=peak；全弱串取最后一个弱为peak。
    非核弱元音：在 peak 前→滑音 G(j/w)；在 peak 后→降滑元音 Vg(保 i/u 符号,不计音节)。"""
    # 找元音串（连续的 V）
    i = 0
    n = len(toks)
    while i < n:
        if toks[i][1] != "V":
            i += 1; continue
        j = i
        while j < n and toks[j][1] == "V":
            j += 1
        run = list(range(i, j))          # 元音串下标
        # peak 判定
        peaks = [k for k in run if not toks[k][3] or toks[k][2]]   # 非弱 或 带重音
        if not peaks:
            peaks = [run[-1]]            # 全弱 → 最后一个弱为核
        peakset = set(peaks)
        for k in run:
            if k in peakset:
                continue
            # 非核弱元音：后面(同串内)是否还有 peak
            after = any(p > k for p in peaks)
            ph = toks[k][0]
            if after:
                toks[k][0] = "j" if ph == "i" else "w"
                toks[k][1] = "G"        # 升→滑音
            else:
                toks[k][1] = "Vg"       # 降→保元音符、非音节核
        i = j
    return toks


def _postprocess(toks):
    """kaikki 音位约定：n→m/在b,p,m前；coda 清塞音 p/t/k 在辅音前→b/d/ɡ。"""
    VOICE = {"p": "b", "t": "d", "k": "ɡ"}
    for k in range(len(toks) - 1):
        ph, kind = toks[k][0], toks[k][1]
        nph, nkind = toks[k + 1][0], toks[k + 1][1]
        if kind != "C" or nkind != "C":
            continue
        if ph == "n" and nph in ("b", "m", "p"):
            toks[k][0] = "m"
        elif ph in VOICE and (ph + nph) not in ONSET_CLUSTERS:
            # 仅 coda 塞音浊化；p/t/k + l/ɾ 是起始丛(同音节)不浊化
            toks[k][0] = VOICE[ph]
    return toks


def _stress_peak(toks, word):
    """返回被重音的音节核 token 下标（kind=='V'）。"""
    vidx = [k for k, t in enumerate(toks) if t[1] == "V"]
    if not vidx:
        return None
    for k in vidx:
        if toks[k][2]:
            return k
    if len(vidx) == 1:
        return vidx[0]
    last = DEACC.get(word[-1].lower(), word[-1].lower())
    return vidx[-2] if (last in "aeiou" or last in "ns") else vidx[-1]


def _render(toks, stress_k):
    nuclei = [k for k, t in enumerate(toks) if t[1] == "V"]
    if not nuclei:
        return "".join(t[0] for t in toks)
    starts = [0]
    for a, b in zip(nuclei, nuclei[1:]):
        mid = list(range(a + 1, b))
        cons = [x for x in mid if toks[x][1] == "C"]
        if len(cons) == 0:
            split = b
        elif len(cons) == 1:
            split = cons[0]
        else:
            pair = toks[cons[-2]][0] + toks[cons[-1]][0]
            split = cons[-2] if pair in ONSET_CLUSTERS else cons[-1]
        j = split - 1
        while j > a and toks[j][1] == "G":     # 前置滑音归后音节
            split = j; j -= 1
        starts.append(split)
    bounds = starts + [len(toks)]
    s_syl = 0
    for si in range(len(nuclei)):
        if bounds[si] <= stress_k < bounds[si + 1]:
            s_syl = si; break
    parts = []
    for si in range(len(nuclei)):
        seg = "".join(toks[x][0] for x in range(bounds[si], bounds[si + 1]))
        parts.append(("ˈ" if si == s_syl else "") + seg)
    return "".join(parts)


def word_to_ipa(word):
    if not word or " " in word or "-" in word:
        return None
    nf = unicodedata.normalize("NFC", word)
    if not _letters_ok(nf):
        return None
    toks = g2p(nf)
    if not toks or not any(t[1] == "V" for t in toks):
        return None
    toks = _process_vowels(toks)       # 先解析双元音（定真音节核）
    stress_k = _stress_peak(toks, nf)  # 再在真核上算重音
    toks = _postprocess(toks)          # 同化/浊化
    return f"/{_render(toks, stress_k)}/"


if __name__ == "__main__":
    tests = {
        "hablar": "/aˈblaɾ/", "cinco": "/ˈθinko/", "perro": "/ˈpero/",
        "caro": "/ˈkaɾo/", "calle": "/ˈkaʝe/", "yo": "/ˈʝo/",
        "guerra": "/ˈɡera/", "queso": "/ˈkeso/", "año": "/ˈaɲo/",
        "rojo": "/ˈroxo/", "jamón": "/xaˈmon/", "país": "/paˈis/",
        "reina": "/ˈreina/", "cuidado": "/kwiˈdado/", "bueno": "/ˈbweno/",
        "ciudad": "/θjuˈdad/", "agua": "/ˈaɡwa/", "construir": "/konsˈtɾwiɾ/",
        "pingüino": "/pinˈɡwino/", "seis": "/ˈseis/", "ley": "/ˈlei/",
        "aire": "/ˈaiɾe/", "muy": "/ˈmwi/",
    }
    ok = 0
    for w, exp in tests.items():
        got = word_to_ipa(w)
        if got == exp:
            ok += 1
        else:
            print(f"  ✗ {w:12} got={got}  exp={exp}")
    print(f"{ok}/{len(tests)} 匹配")
