#!/usr/bin/env python3
"""日语译文的**控制组判据**。1.5b 开跑前必须先有这个。2026-09-15。

═══ 为什么单独一个文件 ═══
`[[control-must-cover-every-output-field]]`：那次控制组只量了一个字段，
烧掉 418 万 token 作废重跑、直接导致账户欠费。判据独立成模块，
**闸和跑批 import 同一份**，不手抄（`[[it-regression-gate]]`：判据只许有一份）。

═══ 🔴 日语的控制组不能照抄前六门 ═══
de/pt 那套的头两条在日语上是坏的：

    if not has_han(z):                            # 日语原文本来就全是汉字 → 恒真
    if len(LATIN.findall(z)) >= 2 and has_han(z):  # 日语残留是假名不是拉丁字母 → 抓不到

⇒ 换成**假名残留检测**。这个信号比拉丁词那条更干净：中文专名不会写成假名，
  而模型没翻完的日语必然带假名（除非原文是纯汉字，那种由 `同形回抄` 那条兜）。

⚠️ 一条永远通过的检查等于没有检查（`PLAYBOOK` 7.3）⇒ 本文件自带变异验证：
    python3 ja/pipeline/ctrl.py
"""
import re

KANA = re.compile(r"[ぁ-ゖァ-ヺー]")
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
# 元描述：说的是**语法关系**不是词义。日语这边最常见的是活用形与异表记的说法。
META = re.compile(r"(的(连用形|连体形|未然形|假定形|命令形|过去式|使役形|被动形|敬语|" 
                  r"异体字?|旧字体|新字体|简写|缩写|平假名|片假名|罗马字)|"
                  r"^[^，。；]{0,12}的(一种)?(写法|形式|形态)$)")
TAIL = re.compile(r"[。！？!?]$")
# 「这条词义是不是在说假名本身」—— 看英文原文怎么说的，不看译文长什么样
ABOUT_KANA = re.compile(r"\b(hiragana|katakana|kana|syllable|braille|column of)\b", re.I)
# 功能词：它的「词义」就是它的语法功能
FUNCTION_POS = {"part", "suf", "pref", "aux", "intj", "conj", "postp"}
# 学名：（Genus species）/ Genus species
SCI_NAME = re.compile(r"[（(]?\b[A-Z][a-z]+ [a-z]+(?: [a-z]+)?\b[)）]?")


def check_example(zh, ja_text, en_text=None):
    """例句译文的控制组。→ [(代号, 说明), …]。2026-09-16。

    🔴🔴 **不能复用 `check()`** —— 它是给**释义**写的，两条判据在例句上是反的：

        E5「带句末标点」  释义是短语，有句号是缺陷；
                        **例句译文是句子，有句号是对的**。照搬会把几乎全部
                        正确译文判成失败，然后我会以为模型崩了。
        E4「元描述当释义」 例句译文里根本不该有「表示…的助词」这种话，
                        但也不会有 —— 这条对例句没有意义，去掉。

    ⚠️ 这正是 `[[decision-not-propagated-across-editions]]` 的同族：
       同一套判据换个**被判对象**就失效，而两边都不会报错。

    留下并改写的：
        E0 留空 ／ E1 残留假名 ／ E2 原样抄回 ／ E3 一个汉字都没有
        E6 残留西文（门槛放宽到 ≥4 个词 —— 例句里引人名/品牌是正常的）
        E7 长度失衡（**双向**：日译中通常会**变短**，太长太短都可疑）
    """
    bad = []
    z = (zh or "").strip()
    if not z:
        return [("E0", "留空（模型判定给不出）")]
    src = (ja_text or "").strip()
    # ① 残留假名。例句译文里出现假名，正常只有一种情况：引用日语词本身。
    #    ⇒ 门槛放在「假名占比」上，而不是「有没有假名」——
    #    `「ありがとう」是感谢的话` 这种引用是对的。
    kana = len(KANA.findall(z))
    if kana and kana / max(len(z), 1) > 0.25:
        bad.append(("E1", "🔴 残留假名过多（多半没翻完）"))
    # ② 原样抄回日语原句
    if z == src:
        bad.append(("E2", "🔴 把日语原句原样抄回来了"))
    # ③ 一个汉字都没有 —— 中文句子不可能没有汉字
    if not HAN.search(z):
        bad.append(("E3", "🔴 一个汉字都没有"))
    # ④ 残留西文。例句会引人名/品牌/型号 ⇒ 门槛比释义宽（释义是 ≥2）
    if len(LATIN_WORD.findall(SCI_NAME.sub("", z))) >= 4:
        bad.append(("E6", "残留西文（≥4 个拉丁词）"))
    # ⑤ 长度失衡。日译中一般**变短**（假名不占字），所以两头都要看。
    #    ⚠️ 阈值宽，只逮离谱的 —— 这条是**警告级**的形式判据，不是内容判据。
    if src:
        r = len(z) / len(src)
        if r > 2.0:
            bad.append(("E7", "比日语原句长一倍以上"))
        elif r < 0.2:
            bad.append(("E8", "比日语原句短太多（可能漏译）"))
    return bad


def check(zh, src_text, word, pos=None):
    """→ [(代号, 说明), …]，空列表＝这条译文没被任何判据挑出来。
    代号以 `W` 开头的是**警告不是失败**（数出来看趋势，不当红）。

    `src_text` 是送去翻译的英文原文，`word` 是词头 —— **两者都要**：
    「抄回原文」与「抄回词头」是两种不同的失败。

    🔴 **`pos` 是 2026-09-15 切片实测逼出来的**。第一版把「译文==词头」一律判成回抄，
       1,297 条切片上命中 **13.11%（168 条）** —— 读完发现**一条真错都没有**：
           44% 是 `pos=name`（`信雄`/`亮祐`），SYS 规则 6 明写「没有通用译名的**保留原文汉字**」
                ⇒ 模型照做了，判据判它错
           44% 是名词（`描画`），日语汉字词与汉语大量**同形同义**，那就是正确译文
       ⇒ 日语上「译文与词头同形」**不是失败信号**，除非词头带假名。
       ⚠️ 残余风险：纯汉字的日语词回抄，而它在汉语里**不是同义词**（如 `大根`）——
          这个**形式上分不出来**，只能计成警告 `W1` 报数，不假装能判。
    """
    bad = []
    z = (zh or "").strip()
    if not z:
        return [("E0", "留空（模型判定给不出）")]
    # ① 残留假名 —— 顶替 de/pt 那条「残留拉丁词」。日语的「没翻完」长这样。
    # 🔴 2026-09-15 全量跑完逐条读，收窄一次：**词条讲的就是假名本身时，译文带假名是对的**
    #    （`カ行`→「か行」、盲文条目→「盲文假名ま」、`ら抜き言葉`→「去ら化词」）。
    #    判据问「这条词义是不是在说假名」—— 看词性与英文原文，不看译文长什么样。
    about_kana = (pos == "kana") or bool(ABOUT_KANA.search(src_text or ""))
    if KANA.search(z) and not about_kana:
        bad.append(("E1", "🔴 残留假名（没翻完）"))
    # ② 同形回抄 —— 分三种，只有前两种算错
    w = (word or "").strip()
    st = (src_text or "").strip()
    # 🔴 收窄：`z == src_text` 只有在原文**确实是英文**时才算回抄。
    #    源头的「英文 gloss」里有一批其实就是汉字写法（`しゅうじ` 的 gloss 是 `修辞`），
    #    模型输出 `修辞` 是**正确的汉语词**，不是回抄。
    if z == st and LATIN_WORD.search(st):
        bad.append(("E2", "🔴 把英文原文原样抄回来了"))
    elif z == w and w:
        if KANA.search(w):
            bad.append(("E2", "🔴 把带假名的词头原样抄回来了"))
        elif pos != "name":
            # 纯汉字同形：多数是对的（同形汉语词），少数不是，**形式上分不出** ⇒ 只警告
            bad.append(("W1", "译文与词头同形（纯汉字，多半是同形汉语词，无法用形式判定）"))
    # ③ 一个汉字都没有。⚠️ 这条在日语上**不能反过来用**：有汉字 ≠ 是中文。
    # 🔴 收窄：**原文本身就是拉丁缩略/型号**时，原样保留是 SYS 规则 8 要求的
    #    （`C++`→`C++`、`DJ`→`DJ`、`RISC`→`RISC`）。
    if not HAN.search(z) and not (LATIN_WORD.search(z) and z in (st, w)):
        bad.append(("E3", "🔴 一个汉字都没有"))
    # ④ 元描述当释义
    # 🔴 收窄：**功能词的词义就是它的语法功能**（`て`→「接续助词，接在连用形后」）。
    #    对 part/suf/pref/aux 这几类，「说的是语法关系」恰恰是它该说的。
    if META.search(z) and pos not in FUNCTION_POS:
        bad.append(("E4", "🔴 元描述当释义（说的是语法关系不是词义）"))
    # ⑤ 句末标点 —— 释义是短语不是句子
    # 🔴 收窄：叹词/助词的问号叹号**是中文的一部分**（`か`→「表示提议：…吧？」）。
    #    de 那轮读红时发现的是同一条。
    if TAIL.search(z) and pos not in FUNCTION_POS:
        bad.append(("E5", "带句末标点"))
    # ⑥ 残留西文（专名保留是允许的，所以门槛是 ≥2 个词）
    # 🔴 收窄：**学名**原样保留是 SYS 规则 8 要求的（`梅（Prunus mume）`）。
    #    判据是学名的形状：括号里、首字母大写属名 + 小写种加词。
    if len(LATIN_WORD.findall(SCI_NAME.sub("", z))) >= 2:
        bad.append(("E6", "残留西文（≥2 个拉丁词）"))
    # ⑦ 比原文长太多
    if len(z) > max(40, len(src_text or "") * 2):
        bad.append(("E7", "比原文长太多"))
    return bad


# ══════ 变异验证：每条判据都要有一个「该被它逮住」的例子，和一个「不该」的 ══════
CASES = [
    # (译文,        日语原文,      词头,     该报的代号)
    ("食物；食品",    "食べ物。",     "食べ物",  None),
    ("",            "難しい",      "難しい",  "E0"),
    ("食べる的意思",   "食べること",    "食べる",  "E1"),
    ("日本語",       "the Japanese language", "日本語",  "W1"),   # 纯汉字同形 ⇒ 只警告
    ("食べる",       "to eat",     "食べる",  "E2"),                       # 词头带假名 ⇒ 真回抄
    ("信雄",        "a male given name", "信雄", None),                   # pos=name 照 SYS 规则 6，干净
    ("abc def",     "エービーシー",  "ABC",   "E3"),
    ("走る的连用形",   "走り",       "走り",   "E1"),      # ① 先命中
    ("走的连用形",    "走り",       "走り",   "E4"),      # 纯汉字 ⇒ 靠 ④
    ("吃饭。",       "ご飯を食べる",  "食事",   "E5"),
    ("the quick brown", "速い",    "速い",   "E3"),
]

if __name__ == "__main__":
    ok = True
    for zh, src, w, want in CASES:
        got = [c for c, _ in check(zh, src, w, "name" if w == "信雄" else None)]
        hit = (want is None and not got) or (want is not None and want in got)
        ok &= hit
        print("%s %-18s → %-14s（期望 %s）" % ("✅" if hit else "🔴", zh or "(空)",
                                              ",".join(got) or "干净", want or "干净"))
    # 🔴 再验一遍**旧判据在日语上是瞎的** —— 这是换判据的理由，要能重现
    old = lambda z: bool(HAN.search(z)) and len(LATIN_WORD.findall(z)) < 2
    print("\n对照：前六门的判据「有汉字且没拉丁词就算合格」")
    for z in ("日本語", "食べる", "漢字を書く"):
        print("   %-10s 旧判据判它合格？%s   新判据：%s"
              % (z, "是 🔴" if old(z) else "否", ",".join(c for c, _ in check(z, z, z))))
    raise SystemExit(0 if ok else 1)


# ══════════════════════════════════════════════════════════════════
# 例句控制组的变异自检。⭐ **第一条打的是「照搬释义判据会怎样」**。
EX_MUT = [
    # (译文, 日语原句, 期望代号 或 None)
    ("我头疼。",              "頭が痛い。",        None),   # 🔴 有句号，**必须不红**
    ("请赶快招出租车。",         "早くタクシーを拾って。", None),
    ("",                    "頭が痛い。",        "E0"),
    ("頭が痛い。",             "頭が痛い。",        "E2"),
    ("あたまがいたいです、そうですね", "頭が痛い。",        "E1"),
    ("aaa bbb ccc ddd eee",  "頭が痛い。",        "E3"),
    ("这 Tokyo Osaka Kyoto Nara 四地",
                             "東京大阪京都奈良",    "E6"),
    ("疼",                   "頭がとても痛いのでもう何もしたくない気分です",  "E8"),
]


def _selftest_example():
    ok = 0
    for zh, ja, want in EX_MUT:
        got = [c for c, _ in check_example(zh, ja)]
        hit = (want in got) if want else (not got)
        print("   %s %-26s → %-14s（期望 %s）"
              % ("✅" if hit else "🔴", zh[:24], ",".join(got) or "(干净)", want or "干净"))
        ok += hit
    print("\n   例句控制组变异 %d/%d" % (ok, len(EX_MUT)))
    # 🔴 对照：拿**释义**的判据去判例句，看它错得多离谱
    n = sum(1 for zh, ja, want in EX_MUT
            if want is None and any(c == "E5" for c, _ in check(zh, ja, "")))
    print("   ⚠️ 用释义判据 `check()` 判这些**正确**例句，误判 %d/%d 条为 E5「带句末标点」"
          % (n, sum(1 for _z, _j, w in EX_MUT if w is None)))
    return ok == len(EX_MUT)
