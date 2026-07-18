#!/usr/bin/env python3
"""
意大利语拼写 → IPA 规则转换器（对齐 kaikki 约定：音节点 . 分隔、主重音 ˈ、
tie-bar 塞擦音 t͡ʃ d͡ʒ t͡s d͡z、/ɡ/ U+0261、双写辅音 gemination 跨音节切分）。

意语正字法辅音完全规则，难点只有 3 个词汇性不可预测点：重音位置、开/闭 e·o、s/z 清浊。
本模块的钥匙：**吃带重音标注的拼写**（à è é ì ò ó ù，来自 kaikki forms 数组），
一次性解决重音位置 + e/o 开闭；无重音标注时退回「倒二音节重音 + 闭元音」默认。

    word_to_ipa("parlàre")  -> "/parˈla.re/"
    word_to_ipa("pàrlano")  -> "/ˈpar.la.no/"
    word_to_ipa("città")    -> "/t͡ʃitˈta/"
    word_to_ipa("gatto")    -> "/ˈɡat.to/"     # 无重音标注→倒二默认
含无法处理的外文字母则返回 None（交豆包）。

it 独立文件，不 import 其他语种。
"""

G = "ɡ"  # U+0261，与 kaikki 一致

# 元音：拼写 → (音位, 是否带重音, 开闭已定)
VOWEL = {
    "a": ("a", False), "à": ("a", True),
    "e": ("e", False), "è": ("ɛ", True), "é": ("e", True),
    "i": ("i", False), "ì": ("i", True), "í": ("i", True),
    "o": ("o", False), "ò": ("ɔ", True), "ó": ("o", True),
    "u": ("u", False), "ù": ("u", True), "ú": ("u", True),
}
VSET = set(VOWEL)
# 前元音（触发 c/g/sc 软化）
FRONT = set("eièéìí")
# 允许的字母（含外来 j k w x y；纯外文其余字符 → None）
ALLOWED = set("abcdefghijklmnopqrstuvwxyz") | VSET | set(" '-")
VOICED_CONS_START = set("bdɡlmnrvzʒ")  # s 在浊辅音前浊化用（音位判定）


def _tokenize(w):
    """拼写 → 音素 token 列表。每个 token=[phoneme, is_vowel, stressed, is_glide]。
    返回 None 表示遇到无法处理的字符。双写辅音 → 两个相同辅音 token（gemination）。"""
    w = w.lower().replace("'", "").replace(" ", "").replace("-", "")
    if not w or any(ch not in ALLOWED for ch in w):
        return None
    toks = []
    i, n = 0, len(w)

    def prev_vowel():
        for t in reversed(toks):
            if t[1]:
                return True
            return False
        return False

    while i < n:
        c = w[i]
        nxt = w[i + 1] if i + 1 < n else ""
        nn = w[i + 2] if i + 2 < n else ""

        # —— 元音 ——
        if c in VSET:
            ph, stressed = VOWEL[c]
            # 升双元音：非重音 i/u 紧邻其后另有元音 → 滑音 j/w（piano /ˈpja.no/）
            if not stressed and c in "iu" and nxt in VSET:
                toks.append(["j" if c == "i" else "w", False, False, True])
            # 降双元音：非重音 i/u 紧跟另一元音之后 → 滑音（causa /ˈkaw.za/、laudàre /lawˈda.re/）
            elif not stressed and c in "iu" and toks and toks[-1][1]:
                toks.append(["j" if c == "i" else "w", False, False, True])
            else:
                toks.append([ph, True, stressed, False])
            i += 1
            continue

        # —— 辅音 ——
        if c == "c":
            if nxt == "h":                        # ch → k
                toks.append(["k", False, False, False]); i += 2; continue
            # 双写软 c（cce/cci）→ 长塞擦音：先出 t͡ʃ，第二个 c 下轮再出 t͡ʃ
            if nxt == "c" and (nn in FRONT or (nn == "i" and w[i + 3:i + 4] and w[i + 3] in VSET)):
                toks.append(["t͡ʃ", False, False, False]); i += 1; continue
            if nxt == "i" and nn in VSET:         # ci+V
                toks.append(["t͡ʃ", False, False, False]); i += 2
                if nn in "ìí":                    # 重音 ì 是元音（farmacìa），非哑音
                    ph, st = VOWEL[nn]; toks.append([ph, True, st, False]); i += 1
                continue
            if nxt in FRONT:                      # c+e/i → t͡ʃ
                toks.append(["t͡ʃ", False, False, False]); i += 1; continue
            toks.append(["k", False, False, False]); i += 1; continue

        if c == "g":
            if nxt == "h":                        # gh → ɡ
                toks.append([G, False, False, False]); i += 2; continue
            # 双写软 g（gge/ggi）→ 长塞擦音
            if nxt == "g" and (nn in FRONT or (nn == "i" and w[i + 3:i + 4] and w[i + 3] in VSET)):
                toks.append(["d͡ʒ", False, False, False]); i += 1; continue
            if nxt == "l" and nn == "i":          # gli → ʎ（gli / gli+V）
                if i + 3 < n and w[i + 3] in VSET:
                    toks.append(["ʎ", False, False, False]); i += 3; continue
                toks.append(["ʎ", False, False, False]); i += 2; continue  # 留 i 作元音
            if nxt == "n":                        # gn → ɲ
                toks.append(["ɲ", False, False, False]); i += 2; continue
            if nxt == "i" and nn in VSET:         # gi+V
                toks.append(["d͡ʒ", False, False, False]); i += 2
                if nn in "ìí":                    # 重音 ì 是元音（allergìa）
                    ph, st = VOWEL[nn]; toks.append([ph, True, st, False]); i += 1
                continue
            if nxt in FRONT:                      # g+e/i → d͡ʒ
                toks.append(["d͡ʒ", False, False, False]); i += 1; continue
            toks.append([G, False, False, False]); i += 1; continue

        if c == "s":
            if nxt == "c":
                if nn == "h":                     # sch → sk
                    toks.append(["s", False, False, False]); toks.append(["k", False, False, False]); i += 3; continue
                if nn in "iìí" and (i + 3 < n and w[i + 3] in VSET):  # sci+V → ʃ
                    toks.append(["ʃ", False, False, False])
                    if nn in "ìí":               # 重音 ì 是元音（sciìa 类）
                        ph, st = VOWEL[nn]; toks.append([ph, True, st, False])
                    i += 3; continue
                if nn in FRONT:                   # sc+e/i → ʃ
                    toks.append(["ʃ", False, False, False]); i += 2; continue
                # sc+a/o/u/cons → s + k（k 下轮处理 c）
                toks.append(["s", False, False, False]); i += 1; continue
            # s 在浊辅音前 → z（sbaglio /zˈbaʎ.ʎo/）
            if nxt and nxt not in VSET and nxt in "bdglmnrvz":
                toks.append(["z", False, False, False]); i += 1; continue
            # 元音/滑音后单 s + 元音 → z（accusàre /ak.kuˈza.re/、causàre /kawˈza.re/）
            if toks and (toks[-1][1] or toks[-1][3]) and nxt in VSET:
                toks.append(["z", False, False, False]); i += 1; continue
            toks.append(["s", False, False, False]); i += 1; continue

        if c == "z":                              # 清浊词汇性：词首默认浊 d͡z，其余默认清 t͡s
            toks.append(["d͡z" if i == 0 else "t͡s", False, False, False]); i += 1; continue
        if c == "q":                              # qu → k w
            toks.append(["k", False, False, False])
            if nxt == "u":
                toks.append(["w", False, False, True]); i += 2; continue
            i += 1; continue
        if c == "h":                              # 不发音
            i += 1; continue

        # 单辅音直映（含外来 j/k/w/x/y）
        simple = {"b": "b", "d": "d", "f": "f", "l": "l", "m": "m", "n": "n",
                  "p": "p", "r": "r", "t": "t", "v": "v", "k": "k", "j": "j",
                  "w": "w", "x": "ks", "y": "i"}
        if c in simple:
            toks.append([simple[c], False, False, False]); i += 1; continue
        return None  # 兜底：未知字符

    # —— 元音间必长化：ʎ ɲ ʃ 及 t͡s d͡z 在两元音之间恒为双辅音（kaikki 约定）——
    ALWAYS_LONG = {"ʎ", "ɲ", "ʃ", "t͡s", "d͡z"}
    out = []
    for k, t in enumerate(toks):
        out.append(t)
        if t[0] in ALWAYS_LONG:
            prev_v = k > 0 and toks[k - 1][1]
            next_v = k + 1 < len(toks) and toks[k + 1][1]
            if prev_v and next_v:
                out.append([t[0], False, False, False])   # 复制一份 → gemination
    # —— 长塞擦音：相邻两个相同塞擦音 → 前者化为其塞音成分（kaikki /pit.t͡sa/ /fat.t͡ʃa/）——
    AFFR_STOP = {"t͡ʃ": "t", "d͡ʒ": "d", "t͡s": "t", "d͡z": "d"}
    for k in range(len(out) - 1):
        if out[k][0] in AFFR_STOP and out[k + 1][0] == out[k][0]:
            out[k] = [AFFR_STOP[out[k][0]], False, False, False]
    return out


def _place_stress(toks):
    """定位重音元音的 token 下标。有带重音元音→用之；否则倒二音节的元音核。"""
    v_idx = [k for k, t in enumerate(toks) if t[1]]     # 元音核下标
    if not v_idx:
        return None
    for k in v_idx:
        if toks[k][2]:
            return k
    # 无标注：倒二元音核（意语默认 piano 词）；单音节→该元音
    return v_idx[-2] if len(v_idx) >= 2 else v_idx[-1]


def _syllabify(toks, stress_idx):
    """把 token 切成音节列表；每音节=(phoneme列表, 是否重读)。
    规则：以元音核为骨，辅音归属——单辅音→后音节onset；muta+liquida(塞/f+l/r)不拆；
    双写/其余簇→前一个归尾、其余归后。"""
    n = len(toks)
    # 找每个元音核，及其后到下个核之间的辅音簇归属
    nuclei = [k for k, t in enumerate(toks) if t[1]]
    syls = []
    start = 0
    for ni, k in enumerate(nuclei):
        # 本音节 onset 从 start..k（含核）；尾辅音在下面决定
        # 收集核后到下一核前的辅音
        nxt_nuc = nuclei[ni + 1] if ni + 1 < len(nuclei) else n
        # 把 [k+1 .. nxt_nuc-1) 的辅音在本节coda / 下节onset间分配
        cons = list(range(k + 1, nxt_nuc))
        if ni + 1 >= len(nuclei):
            seg = list(range(start, n))              # 末音节吞掉所有剩余
            syls.append(seg); break
        m = len(cons)
        if m == 0:
            split = k + 1
        elif m == 1:
            split = cons[0]                          # 单辅音→下节 onset
        else:
            # 两辅音：muta+liquida 或 含滑音 不拆；否则第一个归本节coda
            c1 = toks[cons[0]][0]
            c2 = toks[cons[1]][0] if m >= 2 else ""
            is_glide2 = toks[cons[1]][3] if m >= 2 else False
            muta_liq = c1 in ("p", "b", "t", "d", "k", G, "f") and c2 in ("l", "r")
            if m == 2 and (muta_liq or is_glide2):
                split = cons[0]                      # 整簇→下节
            else:
                split = cons[0] + 1                  # 第一辅音留本节，其余→下节
        seg = list(range(start, split))
        syls.append(seg)
        start = split
    # 标重读
    out = []
    for seg in syls:
        stressed = stress_idx is not None and stress_idx in seg
        out.append(("".join(toks[j][0] for j in seg), stressed))
    return out


def word_to_ipa(spelled):
    """意语拼写（可带重音标注）→ kaikki 风格 IPA；无法转写返回 None。"""
    toks = _tokenize(spelled)
    if toks is None or not any(t[1] for t in toks):
        return None
    stress_idx = _place_stress(toks)
    syls = _syllabify(toks, stress_idx)
    if not syls:
        return None
    # 组装：重音符 ˈ 替代其前的音节点（kaikki 风格 /parˈla.re/，非 /par.ˈla.re/）
    body = ""
    for idx, (text, stressed) in enumerate(syls):
        if stressed:
            body += "ˈ" + text
        else:
            body += ("." if idx > 0 else "") + text
    return "/" + body + "/"


if __name__ == "__main__":
    import sys
    for w in (sys.argv[1:] or ["parlàre", "pàrlano", "città", "gatto", "essere",
                               "èssere", "figlio", "gnomo", "sciare", "buòno",
                               "chiesa", "quando", "sbaglio", "psicologia"]):
        print(f"{w:14} -> {word_to_ipa(w)}")
