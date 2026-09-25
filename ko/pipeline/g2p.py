#!/usr/bin/env python3
"""韩语 G2P：谚文拼写 → 发音形谚文 → IPA。**纯函数，不碰库。** 2026-09-21。

═══ 为什么韩语可以走 G2P，而拉丁七门不可以 ═══
`PLAYBOOK` 3.3 的教训「别用 G2P 重算音标」是在**拉丁语言**上得的：
法语/英语的字形—音位是多对多，规则只能覆盖一部分。
谚文是**音素文字**，字形—音位近乎一对一 ⇒ 难点不在"这个字母读什么"，
而在**音变**（연음/자음동화/경음화/격음화/구개음화）。
🔴 所以"韩语能不能走"这个问题，判据**不是类比**，是拿韩文版的
   发音形谚文当标尺实测（§四.1-c 原文：「先验后用」）。

═══ 两级，各有各的标尺 ═══
    A 级  표기형 → 발음형     音变规则全在这一级    标尺＝`pronunciation.hangeul_phonetic`
    B 级  발음형 → IPA        近乎机械的字母映射     标尺＝同一行的 `pronunciation.ipa`
⭐ 分开量，是因为**两级的错误性质完全不同**：A 级错了是发音错（真错误），
   B 级错了多半是记法约定没对上（改映射表就行）。混在一起量，
   A 级的真错误会被 B 级的约定噪声淹掉。

═══ 🔴 三样**规则上算不出来**的东西，不假装能算 ═══
 ① **元音长短 `(ː)`** —— 词汇性的，拼写里没有信息（`눈`雪 vs `눈`眼 同形不同长）。
    ⇒ 生成的 IPA **一律不带长音符**；量准确率时两边都剥掉，并**单独报**标尺里
      有多少行带长音（那部分是我们结构性给不出的）。
 ② **ㄴ 첨가**（`솜이불`→`솜니불`）—— 要知道复合词的词素边界。
 ③ **사잇소리/한자어 경음화**（`갈등`→`갈뜽`）—— 要知道词源是不是汉字词。
 ⇒ 这三样不是 bug，是**判据的边界**。它们贡献的错误要在报告里单列，
   否则会被当成"规则写得不好"而去改规则（`[[residual-bucket-is-not-evidence]]`）。

═══ 验证协议：开发半 / 留出半 ═══
🔴 规则**只在开发半上调**，报出去的数是**留出半**的。
   拿全部标尺调规则再拿全部标尺报准确率，就是拿尺子优化尺子
   （`[[proxy-metric-gets-optimized]]`）。切分按词形的稳定哈希，**不按行号**
   （同一个词形的多行必须落在同一半，否则留出半会泄漏）。

跑（在仓库根）：
    python3 -u ko/pipeline/g2p.py --validate          # 只量，不写库
    python3 -u ko/pipeline/g2p.py --validate --errors 40
"""
import hashlib
import unicodedata

# ══════════════════════════════════════════════════════════════════
# 谚文音节的拆合
# ══════════════════════════════════════════════════════════════════
CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"

SBASE, LCNT, VCNT, TCNT = 0xAC00, 19, 21, 28


def is_syl(c):
    return "가" <= c <= "힣"


def decompose(c):
    """谚文音节 → [초성, 중성, 종성]，종성 为 '' 表示无韵尾。"""
    i = ord(c) - SBASE
    return [CHO[i // (VCNT * TCNT)], JUNG[(i // TCNT) % VCNT], JONG[i % TCNT].strip()]


def compose(cho, jung, jong):
    return chr(SBASE + (CHO.index(cho) * VCNT + JUNG.index(jung)) * TCNT
               + JONG.index(jong if jong else " "))


# ══════════════════════════════════════════════════════════════════
# A 级：표기형 → 발음형
# ══════════════════════════════════════════════════════════════════
# 겹받침：韵尾字母簇 → (前, 后)
CLUSTER = {"ㄳ": ("ㄱ", "ㅅ"), "ㄵ": ("ㄴ", "ㅈ"), "ㄶ": ("ㄴ", "ㅎ"),
           "ㄺ": ("ㄹ", "ㄱ"), "ㄻ": ("ㄹ", "ㅁ"), "ㄼ": ("ㄹ", "ㅂ"),
           "ㄽ": ("ㄹ", "ㅅ"), "ㄾ": ("ㄹ", "ㅌ"), "ㄿ": ("ㄹ", "ㅍ"),
           "ㅀ": ("ㄹ", "ㅎ"), "ㅄ": ("ㅂ", "ㅅ")}

# 자음군 단순화：不连音时哪一个留下来（표준발음법 10·11항）
SIMPLIFY = {"ㄳ": "ㄱ", "ㄵ": "ㄴ", "ㄶ": "ㄴ", "ㄺ": "ㄱ", "ㄻ": "ㅁ",
            "ㄼ": "ㄹ", "ㄽ": "ㄹ", "ㄾ": "ㄹ", "ㄿ": "ㅂ", "ㅀ": "ㄹ",
            "ㅄ": "ㅂ"}

# 음절의 끝소리 규칙（중화）：韵尾位置只剩七个音
NEUTRAL = {"ㄲ": "ㄱ", "ㅋ": "ㄱ", "ㅅ": "ㄷ", "ㅆ": "ㄷ", "ㅈ": "ㄷ",
           "ㅊ": "ㄷ", "ㅌ": "ㄷ", "ㅎ": "ㄷ", "ㅍ": "ㅂ"}

TENSE = {"ㄱ": "ㄲ", "ㄷ": "ㄸ", "ㅂ": "ㅃ", "ㅅ": "ㅆ", "ㅈ": "ㅉ"}
ASPIR = {"ㄱ": "ㅋ", "ㄷ": "ㅌ", "ㅂ": "ㅍ", "ㅈ": "ㅊ", "ㅅ": "ㅆ"}
NASAL = {"ㄱ": "ㅇ", "ㄷ": "ㄴ", "ㅂ": "ㅁ"}
# 韵尾里带 ㅎ 的三种；(留下来的, ) —— 격음화时 ㅎ 消耗掉
H_CODA = {"ㅎ": "", "ㄶ": "ㄴ", "ㅀ": "ㄹ"}
# 韵尾能和后面的 ㅎ 缩合成送气音的
ASPIR_CODA = {"ㄱ": "ㅋ", "ㄺ": "ㅋ", "ㄷ": "ㅌ", "ㅅ": "ㅌ", "ㅆ": "ㅌ",
              "ㅈ": "ㅊ", "ㅊ": "ㅊ", "ㅌ": "ㅌ", "ㅂ": "ㅍ", "ㄼ": "ㅍ",
              "ㅍ": "ㅍ", "ㄵ": "ㅊ", "ㅄ": "ㅍ"}
# 격음화后韵尾位置剩什么（겹받침才有剩）
ASPIR_LEFT = {"ㄺ": "ㄹ", "ㄼ": "ㄹ", "ㄵ": "ㄴ", "ㅄ": ""}

VOICED_CODA = {"ㄴ", "ㅁ", "ㅇ", "ㄹ"}


# ══════════════════════════════════════════════════════════════════
# 候选规则开关 —— 每一条都是两家外审提的，**每一条都在标尺上单独量过**
# ══════════════════════════════════════════════════════════════════
# 🔴 规矩：两家不一致不取多数，回源核对。开关存在就是为了「单独量这一条
#    修好几个、弄坏几个」—— 没有这个数，采纳与否就是听谁说话大声。
ALL_RULES = (
    "rk_verbal",      # ㄺ+ㄱ→ㄹ 只在용언（`읽고`→`일꼬`，但`닭고기`→`닥꼬기`）
    "pl_lex",         # ㄼ→ㅂ 的词汇例外（밟-／넓적-／넓죽-／넓둥-）
    "neutral_h",      # 韵尾 ㅈ/ㅊ ＋ ㅎ 先中和成 ㄷ 再送气（`맞흥정`→`마틍정`）
    "rt_palatal",     # 겹받침 ㄾ ＋ 이 的腭化（`핥이다`→`할치다`）
    "jyeo",           # 非词首 져/쪄/쳐 → 저/쩌/처（5항 다만1）
    "sino_r",         # 26항：汉字词 ㄹ ＋ ㄷ/ㅅ/ㅈ 紧音化（要 sino 信号）
    "verbal_tense",   # 24·25항：용언 어간 ㄴ/ㅁ/ㄼ/ㄾ ＋ ㄱㄷㅅㅈ 紧音化
    "lat_restrict",   # 유음화 只在汉字词/용언上施行（外来语不走，`다운로드`→`다운노드`）
    "ui_mid",         # 非词首零初声 ㅢ → ㅣ
    "real_morph",     # 15항：实质形态素前，韵尾先中和再连音（`웃옷`→`우돋`）
    "pal_final",      # 구개음화 收窄：`이` 必须是词末音节（`곧이어`→`고디어` 不腭化）
    "cluster_tense",  # 겹받침的第二字母是塞音 ⇒ 先触发紧音化再简化（`읽고`→`일꼬`）
)
# 겹받침里第二个字母是**塞音/擦音**的 —— 它在简化中消失，但**消失之前先把后面的平音变紧**
CLUSTER_OBSTRUENT = {"ㄳ", "ㄵ", "ㄺ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅄ"}
# 15항 明文列出的元音：실질 형태소는这几个开头
REAL_MORPH_V = {"ㅏ", "ㅓ", "ㅗ", "ㅜ", "ㅟ"}
# ⭐ 采纳线：**弄坏 ≤ 修好的 5%**，且弄坏的逐条看过。下面四条全部是「零弄坏」。
#    完整的量见 `ablate_g2p.py`；被否掉的四条连同数字记在 `docs/KO_PLAN.md` §四.1-c。
DEFAULT_RULES = frozenset({"rk_verbal", "pl_lex", "jyeo",
                           "cluster_tense", "verbal_tense"})

# ㄼ 读 ㅂ 的词汇例外。**这不是我编的清单，是 표준발음법 10항 但서列出的原词**。
PL_B_PREFIX = ("밟", "넓적", "넓죽", "넓둥")
# 25항 里 `cluster_tense` **管不到的那一个**：ㄻ 的第二字母 ㅁ 是响音，
# 不触发塞音型紧音化，只能靠"这是용언"这个信号（`젊지`→`점찌`、`옮다`→`옴따`）。
# 🔴 **只有 ㄻ。单 ㄴ/ㅁ 不在内。**
#    实测（开发半 20,757 词形）：
#        겹받침 ㄵㄻㄼㄾㄽ   修好 9  弄坏 0   ← 换三种"是不是용언"的信号结论都不变
#        单 ㄴ/ㅁ            修好 3  弄坏 7   ← 即使用库里真 pos 仍然是负的
#    ⚠️ 单 ㄴ/ㅁ 这一支被否，**不是因为规则不存在** —— 표준발음법 24항 明文举了
#       `심다[심ː따]`、`껴안다[껴안따]`。是因为**我们的标尺（韩文版）自己不遵守它**：
#       `검다[검따]` 与 `넘다[넘다]`、`다듬다[다듬따]` 与 `더듬다[더듬다]` 并存。
#       库里已有的 54,211 条人工读音全部来自同一个标尺 ⇒ 施行 24항 会让
#       生成的读音与已落库的读音**互相打架**，那比缺一条规则更糟。
#    🔴 什么会推翻：拿到국립국어원 표준국어대사전的 `발음` 字段（真正的权威源）
#       并确认它站 24항 这边 —— 那时要翻的就不只是这条规则，还有标尺本身的地位。
VERBAL_TENSE_CODA = {"ㄻ"}


def _simplify_ctx(coda, onset, ctx):
    """겹받침 简化，带上下文的例外（표준발음법 10·11항 但서）。"""
    if coda == "ㄺ" and onset == "ㄱ":
        if "rk_verbal" not in ctx["rules"] or ctx["verbal"]:
            return "ㄹ"                  # 읽고 → 일꼬
    if coda == "ㄼ" and "pl_lex" in ctx["rules"] and \
            ctx["word"].startswith(PL_B_PREFIX):
        return "ㅂ"                      # 밟다 → 밥따／넓적다리 → 넙쩍따리
    return SIMPLIFY.get(coda, coda)


def to_phonetic(word, verbal=None, sino=False, rules=DEFAULT_RULES):
    """표기형 → 발음형谚文。非谚文字符原样穿过（空格/连字符/汉字）。

    `verbal` —— 这是不是용언（动词/形容词）。默认按「以 -다 结尾」推断。
                🔴 这是**形式代理**，它的误伤面在标尺上量过（见 KO_PLAN §四.1-c）。
    `sino`   —— 这是不是汉字词。**只有库里 `entry.hanja` 非空才敢说是**，
                推断不出来就传 False ⇒ 26항 整条不施行（宁缺）。
    `rules`  —— 启用哪些候选规则，见 `ALL_RULES`。

    🔴 只处理**谚文音节**之间的相邻关系：碰到非谚文就切断上下文，
       因为跨过一个汉字去做连音是**猜**，而不是规则。
    """
    word = unicodedata.normalize("NFC", word)
    if verbal is None:
        verbal = word.endswith("다")
    ctx = {"word": word, "verbal": verbal, "sino": sino, "rules": rules}
    out, run = [], []

    def flush():
        if run:
            out.append(_phon_run("".join(run), ctx))
            run.clear()

    for ch in word:
        if is_syl(ch):
            run.append(ch)
        else:
            flush()
            out.append(ch)
    flush()
    return "".join(out)


def _phon_run(s, ctx):
    """一段连续谚文的音变。"""
    rules = ctx["rules"]
    syl = [decompose(c) for c in s]
    n = len(syl)
    # 5항 다만1：용언 활용형의 `져/쪄/쳐` 는 `저/쩌/처`。
    # ⚠️ 两家给的施行条件不同（v4pro：要 POS/词表；豆包：非词首即可）——
    #    这里实现成"非词首"，**采不采纳看标尺上的修/坏比**。
    if "jyeo" in rules:
        for k in range(1, n):
            if syl[k][0] in ("ㅈ", "ㅉ", "ㅊ") and syl[k][1] == "ㅕ":
                syl[k][1] = "ㅓ"
    # 표준발음법 5항 다만3：초성이 있는 음절의 `ㅢ` 는 `ㅣ` 로 발음（`희다`→`히다`）
    for k, x in enumerate(syl):
        if x[1] == "ㅢ" and x[0] != "ㅇ":
            x[1] = "ㅣ"
        elif x[1] == "ㅢ" and x[0] == "ㅇ" and k and "ui_mid" in rules:
            x[1] = "ㅣ"
    for i in range(n):
        cur = syl[i]
        coda = cur[2]
        if i + 1 == n:                                     # 词末
            cur[2] = NEUTRAL.get(SIMPLIFY.get(coda, coda),
                                 SIMPLIFY.get(coda, coda))
            continue
        nxt = syl[i + 1]
        onset = nxt[0]

        # ── ① ㅇ 开头：연음（把韵尾挪过去）─────────────────────
        if onset == "ㅇ":
            if coda in ("", "ㅇ"):
                pass
            elif coda == "ㅎ":                             # 좋아 → 조아
                cur[2] = ""
            elif coda in CLUSTER:
                a, b = CLUSTER[coda]
                if b == "ㅎ":                              # 많아→마나 / 싫어→시러
                    # 🔴 ㅎ 脱落**之后剩下的那个辅音仍要连音**。
                    #    第一版只丢了 ㅎ 就收手 ⇒ `많이`→`만이`（错），正确是 `마니`。
                    cur[2] = ""
                    nxt[0] = a
                else:                                      # 닭이→달기 / 넋이→넉씨
                    cur[2] = a
                    nxt[0] = "ㅆ" if b == "ㅅ" else b
            elif (coda in ("ㄷ", "ㅌ") and nxt[1] == "ㅣ"
                  and ("pal_final" not in rules or i + 2 == n)):  # 구개음화 굳이→구지
                cur[2] = ""
                nxt[0] = "ㅈ" if coda == "ㄷ" else "ㅊ"
            elif coda == "ㄾ" and nxt[1] == "ㅣ" and "rt_palatal" in rules:
                cur[2] = "ㄹ"                              # 핥이다 → 할치다
                nxt[0] = "ㅊ"
            elif ("real_morph" in rules and not ctx["verbal"]
                  and nxt[1] in REAL_MORPH_V):
                # 15항：뒤에 실질 형태소가 오면 받침을 **대표음으로 바꾸어** 옮긴다
                #（`웃옷`→`우돋`、`값어치`→`가버치`）。용언 활용의 `-아/-어` 는
                # 형식 형태소이므로 제외（`깎아`→`까까`，不是`깍아`）。
                cur[2] = ""
                nxt[0] = NEUTRAL.get(SIMPLIFY.get(coda, coda),
                                     SIMPLIFY.get(coda, coda))
            else:
                cur[2] = ""
                nxt[0] = coda
            continue

        # ── ② 격음화：韵尾 ㅎ ＋ ㄱ/ㄷ/ㅈ/ㅅ ─────────────────
        if coda in H_CODA and onset in ASPIR:
            left = H_CODA[coda]
            if coda == "ㅀ" and onset == "ㅅ":              # 핥소류，罕见
                pass
            nxt[0] = ASPIR[onset]
            cur[2] = left
            continue
        # ㅎ ＋ ㄴ：놓는→논는 / 많네→만네 / 싫네→실레
        if coda in H_CODA and onset == "ㄴ":
            left = H_CODA[coda]
            if coda == "ㅀ":
                cur[2] = "ㄹ"
                nxt[0] = "ㄹ"                              # 유음화
            else:
                cur[2] = "ㄴ"
            continue

        # ── ③ 격음화（反向）：韵尾 ＋ ㅎ ─────────────────────
        if onset == "ㅎ" and coda in ASPIR_CODA:
            # 닫히다→다치다：격음화 ㅌ 之后再 구개음화
            asp = ASPIR_CODA[coda]
            if "neutral_h" in rules and coda in ("ㅈ", "ㅊ"):
                asp = "ㅌ"                 # 先走끝소리규칙 ㅈ/ㅊ→ㄷ，再 ㄷ＋ㅎ→ㅌ
            if asp == "ㅌ" and nxt[1] == "ㅣ":
                asp = "ㅊ"
            nxt[0] = asp
            cur[2] = ASPIR_LEFT.get(coda, "")
            continue

        # ── ④ 자음군 단순화 ＋ 중화 ──────────────────────────
        # 🔴 顺序：겹받침的塞音成分**先触发紧音化**，然后才被简化掉。
        #    反过来（先简化再紧音化）会得到 `읽고`→`일고`，缺了紧音。
        #    ⭐ 这条比 `verbal_tense` 的 `-다` 代理更本质：它不需要知道是不是용언。
        onset0 = onset          # 🔴 简化要看**原始**初声：紧音化之后 ㄱ 变成 ㄲ，
        if ("cluster_tense" in rules and coda in CLUSTER_OBSTRUENT   # `ㄺ+ㄱ→ㄹ`
                and onset in TENSE):                                 # 那条例外就匹配不上了
            nxt[0] = TENSE[onset]
            onset = nxt[0]
        c = _simplify_ctx(coda, onset0, ctx)
        c = NEUTRAL.get(c, c)

        # ── ⑤ 비음화 / 유음화 / 경음화 ───────────────────────
        lat_ok = "lat_restrict" not in rules or ctx["sino"] or ctx["verbal"]
        if c in NASAL and onset in ("ㄴ", "ㅁ"):           # 국물→궁물
            c = NASAL[c]
        elif c in ("ㅁ", "ㅇ") and onset == "ㄹ":          # 종로→종노
            nxt[0] = "ㄴ"
        elif c in ("ㄱ", "ㅂ") and onset == "ㄹ":          # 백로→뱅노
            nxt[0] = "ㄴ"
            c = NASAL[c]
        elif c == "ㄴ" and onset == "ㄹ":                  # 신라→실라
            if lat_ok:
                c = "ㄹ"
            else:
                nxt[0] = "ㄴ"                              # 다운로드→다운노드
        elif c == "ㄹ" and onset == "ㄴ":                  # 칼날→칼랄
            if lat_ok:
                nxt[0] = "ㄹ"
        elif c in ("ㄱ", "ㄷ", "ㅂ") and onset in TENSE:   # 학교→학꾜
            nxt[0] = TENSE[onset]
        # 26항：汉字词 ㄹ ＋ ㄷ/ㅅ/ㅈ。**没有 sino 信号就整条不施行**
        elif ("sino_r" in rules and ctx["sino"] and c == "ㄹ"
              and onset in ("ㄷ", "ㅅ", "ㅈ")):
            nxt[0] = TENSE[onset]
        # 24·25항：용언 어간 ㄴ/ㅁ/ㄼ/ㄾ ＋ ㄱㄷㅅㅈ。只在**词干与词尾的那个边界**上
        elif ("verbal_tense" in rules and ctx["verbal"] and i + 2 == n
              and coda in VERBAL_TENSE_CODA and onset in ("ㄱ", "ㄷ", "ㅅ", "ㅈ")):
            nxt[0] = TENSE[onset]
        cur[2] = c

    return "".join(compose(*x) for x in syl)


# ══════════════════════════════════════════════════════════════════
# B 级：발음형 → IPA（维基词典韩语窄式记音的约定）
# ══════════════════════════════════════════════════════════════════
# ⭐ 这张表**不是凭语音学知识写的，是回标尺量出来的**（65,926 行里逐条对差异聚合）。
#    凭知识写的第一版在 B 级只有 69.4%，错的全是**记法约定**不是发音：
#    `ㅉ` 写 `t͡ɕ͈` 不是 `t͈͡ɕ͈`、`ㅛ` 写 `jo` 不是 `jo̞`、`ㅚ` 写 `ø̞` 不是 `we̞`。
#    🔴 约定只能从源头量，量不出来的地方**不许按"应该是什么"补"**。
ONSET_IPA = {"ㄱ": ("k", "ɡ"), "ㄲ": ("k͈", "k͈"), "ㄴ": ("n", "n"),
             "ㄷ": ("t", "d"), "ㄸ": ("t͈", "t͈"), "ㄹ": ("ɾ", "ɾ"),
             "ㅁ": ("m", "m"), "ㅂ": ("p", "b"), "ㅃ": ("p͈", "p͈"),
             "ㅅ": ("sʰ", "sʰ"), "ㅆ": ("s͈", "s͈"), "ㅇ": ("", ""),
             "ㅈ": ("t͡ɕ", "d͡ʑ"), "ㅉ": ("t͡ɕ͈", "t͡ɕ͈"), "ㅊ": ("t͡ɕʰ", "t͡ɕʰ"),
             "ㅋ": ("kʰ", "kʰ"), "ㅌ": ("tʰ", "tʰ"), "ㅍ": ("pʰ", "pʰ"),
             "ㅎ": ("h", "ɦ")}

# 中声拆成（介音, 主元音）—— 拆开是因为**腭化的辅音会把 j 吃掉**（`뉴`→`ɲu` 不是 `ɲju`）
VOWEL_IPA = {"ㅏ": ("", "a̠"), "ㅐ": ("", "ɛ"), "ㅑ": ("j", "a̠"),
             "ㅒ": ("j", "ɛ"), "ㅓ": ("", "ʌ̹"), "ㅔ": ("", "e̞"),
             "ㅕ": ("j", "ʌ̹"), "ㅖ": ("j", "e̞"), "ㅗ": ("", "o̞"),
             "ㅘ": ("w", "a̠"), "ㅙ": ("w", "ɛ"), "ㅚ": ("", "ø̞"),
             "ㅛ": ("j", "o"), "ㅜ": ("", "u"), "ㅝ": ("w", "ʌ̹"),
             "ㅞ": ("w", "e̞"), "ㅟ": ("", "y"), "ㅠ": ("j", "u"),
             "ㅡ": ("", "ɯ"), "ㅢ": ("ɰ", "i"), "ㅣ": ("", "i")}

CODA_IPA = {"": "", "ㄱ": "k̚", "ㄴ": "n", "ㄷ": "t̚", "ㄹ": "ɭ",
            "ㅁ": "m", "ㅂ": "p̚", "ㅇ": "ŋ"}

# 实测：只有这五个在 i/j 前腭化。**ㄱ/ㄲ/ㄹ 不腭化**（`기역`→`kijʌ̹k̚`、`소리`→`sʰo̞ɾi`），
# 这与"腭化是普遍音理"的直觉相反 —— 所以判据取自标尺不取自直觉。
PAL_ONSET = {"sʰ": "ɕʰ", "s͈": "ɕ͈", "kʰ": "cç"}
# 🔴 `ㄴ` **只在 j 介音前**腭化（`뉴`→`ɲu`／`뇨`→`ɲo`），在**纯 ㅣ 前不腭化**
#    （`어머니`→`ʌ̹mʌ̹ni`、`아니`→`a̠ni`、`하나님`→`ha̠na̠nim`）。
#    第一版把两者并成「i/j 前」⇒ 判据比它描述的东西宽（`[[criteria-narrower-than-you-think]]`）。
PAL_N_GLIDE_ONLY = True
# 腭化后会把后面的 j 介音吃掉
ABSORB_J = {"ɕʰ", "ɕ͈", "cç", "ɲ", "ç", "ʝ", "ʎ"}


def _h_allophone(glide, nucleus, voiced):
    """ㅎ 的音位变体按**后面的元音**定。实测四组，不是一个 h 走天下。"""
    if glide == "j" or nucleus == "i":
        return "ʝ" if voiced else "ç"
    if nucleus == "ɯ":
        return "ɣ" if voiced else "x"
    if glide == "w":
        return "β" if voiced else "ɸ"
    if nucleus in ("o̞", "o", "u"):
        return "β" if voiced else "ɸʷ"
    return "ɦ" if voiced else "h"


def to_ipa(phonetic):
    """발음형谚文 → IPA（裸串，不带定界符 —— 八语种统一约定）。

    ⚠️ 入参必须是**发音形**，不是拼写形。拿拼写形直接进来会得到
       `읽다`→`iɭk̚ta̠` 这种不存在的读音。
    """
    phonetic = unicodedata.normalize("NFC", phonetic)
    syl = [decompose(c) for c in phonetic if is_syl(c)]
    n = len(syl)
    part = []
    for i, (cho, jung, jong) in enumerate(syl):
        voiced = i > 0 and syl[i - 1][2] in (VOICED_CODA | {""})
        glide, nuc = VOWEL_IPA[jung]
        if cho == "ㅎ":
            s = _h_allophone(glide, nuc, voiced)
        else:
            s = ONSET_IPA[cho][1 if voiced else 0]
            if (glide == "j" or nuc == "i") and s in PAL_ONSET:
                s = PAL_ONSET[s]
            elif s == "kʰ" and nuc == "ɯ":         # `크다`→`kxɯda̠`
                s = "kx"
            elif s == "n" and glide == "j":
                s = "ɲ"
        if s in ABSORB_J and glide == "j":
            glide = ""
        part.append({"on": s, "gl": glide, "nu": nuc, "co": CODA_IPA[jong]})

    # ── 回看下一个音节才能定的三件事 ────────────────────────────
    for i in range(n - 1):
        jong, ncho = syl[i][2], syl[i + 1][0]
        nfront = part[i + 1]["gl"] == "j" or part[i + 1]["nu"] == "i"
        if jong == "ㄹ":
            if ncho == "ㄹ":                       # ㄹㄹ 是长音 [ɭɭ]/[ʎʎ]，不是 [ɭɾ]
                sym = "ʎ" if nfront else "ɭ"
                part[i]["co"] = part[i + 1]["on"] = sym
                if sym == "ʎ" and part[i + 1]["gl"] == "j":
                    part[i + 1]["gl"] = ""
            elif ncho in ("ㅈ", "ㅉ", "ㅊ"):
                part[i]["co"] = "ʎ"
            elif ncho == "ㅎ":                     # `결혼`→`kjʌ̹ɾβo̞n`
                part[i]["co"] = "ɾ"
        elif jong == "ㄴ":
            # 只在**塞擦音**前（`언제`→`ɘɲd͡ʑe̞`）。`문신`→`munɕʰin`、`안녕`→`a̠nɲʌ̹ŋ`
            # 说明擦音 ɕ 和腭化的 ɲ 都**不**触发 —— 又一次「判据比对象宽」。
            if ncho in ("ㅈ", "ㅉ", "ㅊ"):
                part[i]["co"] = "ɲ"
        elif jong in ("ㄱ", "ㄷ", "ㅂ") and ncho == "ㅆ":
            # 实测 ㅆ 前不带不除阻符：ㄱ 665:1／ㅂ 226:0／ㄷ 40:0
            part[i]["co"] = {"ㄱ": "k", "ㄷ": "t", "ㅂ": "p"}[jong]

    return "".join(p["on"] + p["gl"] + p["nu"] + p["co"] for p in part)


def g2p(word):
    """표기형 → (발음형, IPA)。"""
    p = to_phonetic(word)
    return p, to_ipa(p)


# ══════════════════════════════════════════════════════════════════
# 验证：开发半 / 留出半
# ══════════════════════════════════════════════════════════════════
def half_of(word):
    """词形 → 'dev' / 'hold'。**按词形哈希**，同词形的多行必落同一半。"""
    h = hashlib.md5(word.encode("utf-8")).digest()[0]
    return "dev" if h % 2 else "hold"


def strip_len(s):
    """剥掉长音标记。长短是词汇性的，规则上算不出来（见文件头 ①）。"""
    return s.replace("(ː)", "").replace("ː", "")


def strip_stress(s):
    return s.replace("ˈ", "").replace("ˌ", "")


# ══════════════════════════════════════════════════════════════════
# 行为指纹 —— 落库的每一行都带着"它是哪一版规则算的"
# ══════════════════════════════════════════════════════════════════
# 🔴 为什么是**行为**指纹，不是规则名的哈希、也不是文件的哈希：
#     规则名哈希 —— 改 `VOWEL_IPA` 里一个符号不会变 ⇒ **漏报**
#     文件哈希   —— 改一个注释就变 ⇒ **误报**，而误报多了这道闸就被无视了
#   取"在一组固定探针词上的输出"的哈希：**凡是会改变落库内容的改动都会变，
#   不改变内容的改动都不变**。这正是我们要问的那个问题。
# ⚠️ 探针词**不许改**。改了它，指纹会变而落库内容没变 —— 那就成了假红。
#   要加探针只能新开一个列表并同时重算全库（那时本来就该重算）。
PROBE = ("읽다", "읽고", "맑고", "닭고기", "밟다", "넓적다리", "넓다", "많이",
         "좋아", "굳이", "같이", "신라", "칼날", "국물", "백로", "학교",
         "한국어", "짧다", "핥다", "젊지", "가져오다", "희다", "꽃이", "앉다",
         "값어치", "웃옷", "곧이어", "미닫이문", "식용유", "다운로드",
         "발전", "여권", "눈길", "소파", "안녕", "메뉴", "크다", "하키")


def fingerprint(rules=None):
    """→ 8 位十六进制。**规则的行为变了它就变，注释变了它不变。**"""
    import hashlib as _h
    rs = DEFAULT_RULES if rules is None else rules
    out = []
    for w in PROBE:
        for verbal in (False, True):
            p = to_phonetic(w, verbal=verbal, sino=False, rules=rs)
            out.append("%s|%s|%s" % (w, p, to_ipa(p)))
    return _h.sha256("\n".join(out).encode("utf-8")).hexdigest()[:8]
