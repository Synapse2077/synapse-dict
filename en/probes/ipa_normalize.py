#!/usr/bin/env python3
"""`packages/dict-core/src/index.ts` 的 normalizePronunciation() 的 Python 移植 + 新规则设计稿。
见对话 2026-07-30。

🔴 **这是一份复制品,不是真源头**。改了 TS 那边必须同步改这里,否则审计出来的
   "用户当前看到的音标"就是假的 —— 审计工具本身失真比不审计更糟。
   自检:`python3 en/ipa_normalize.py --selftest`

⭐ 2026-07-30 重制。依据 = 2000 条真实样本送豆包 pro + v4-pro 双盲评审(两家同码 234 条),
   外加两家对映射代码本身的独立评审。**关键结论:英美必须分列,共用一套规则修不好。**
   A 类「把对的改错了」129 条的归因:ɾ→r 闪音 95 / ɚɝ 27 / ɛ→e 22 / ʔ 16 / ɐ 10 / ɨ 6。

改动要点(每条都有真实词例):
  ① ɾ→**t** 不是 r。ɾ 是美式 /t,d/ 在元音间的闪音变体,不是通音 r。
     citing ˈsaɪɾɪŋ 旧规则出 ˈsaɪrɪŋ「赛润」,应为 ˈsaɪtɪŋ。**单条规则占 A 类的 73%**。
  ② ʔ→**t** 不是删除。ʔ 是英式 /t/ 的喉塞变体。fitty fɪʔi 旧规则出 fɪi(整个音节没了)。
  ③ ɐ→**ʌ** 不是 ə。现代 RP 严式用 ɐ 记 STRUT 元音,映射成 schwa 会把重读读成弱读。
  ④ ɚ/ɝ **分英美**:美式 ɚ→ər、ɝ→ɜr(**不加 ː**,美式无长短对立);
     英式 ɚ→ə、ɝ→ɜː(**不加 r**,非儿化)。abhorrers 英式原文带 ɚ,旧规则给英式加了 r。
  ⑤ ɛ→e **只对英式**。英式 DJ 记法 DRESS 写 /e/(牛津/朗文英式如此),美式词典写 /ɛ/。
  ⑥ 括号**分英美拆掉**,不再透给用户(9,796 条,常用核心 4,676):
     英式 (r)/(ɹ) 整个删、(j) 留 j、(ː) 留长音;美式 (r)→r、(j) 整个删、(ː) 删;
     其余 (ə)(t)(h) 等一律去括号留内容(取全读形式,对学习者最稳)。
  ⑦ 成节符不能光删:dirndl ˈdɜːndl̩ 删掉变 ˈdɜːndl 读不出,应补 schwa → ˈdɜːndəl。
     ⚠️ 但 (ə)C̩ 要合并处理,否则 ˈæb.s(ə)n̩s 会出双 schwa。
  ⑧ 新增裸 a→æ(英式 TRAP):pantry ˈpantri → ˈpæntri。**必须排除 aɪ/aʊ**,否则劈坏双元音。
  ⑨ 新增清理:ːː→ː(ɝ→ɜːr 撞上已有 ː)、腭化符 ʲ 与上标 ⁽ʲ⁾(Kamin-Kashyrskyi 那类)。
  ⑩ rr→r 必须放在**括号拆完之后**。旧版放在前面,number ˈnʌmbɚ(r) 出 ˈnʌmbər(r),
     注释说这条就是为修重复 r 写的,却因为顺序错而失效。
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, re

# ---------- 共用:与口音无关 ----------
DIACRITICS = ["̯", "̟", "̥", "̈", "ʰ", "̚", "̃", "‿", "ʲ"]
TIEBAR = [("t͡ʃ", "tʃ"), ("d͡ʒ", "dʒ"), ("t͡s", "ts"), ("d͡z", "dz"),
          ("t͜ʃ", "tʃ"), ("d͜ʒ", "dʒ")]          # U+035C 下置连弧也要管
COMMON = [("ʔ", "t"), ("ɾ", "t"), ("kç", "k"),
          ("aj", "aɪ"), ("æw", "aʊ"), ("æʊ", "aʊ"), ("ʌɪ", "aɪ"),
          ("ɹ", "r"), ("ɫ", "l"), ("ɐ", "ʌ"), ("ɨ", "ɪ")]

SYL = "̩"       # ̩ 成节符
SUPERSCRIPT = re.compile(r"⁽[^⁾]*⁾")


def _parens(s, accent):
    """按口音拆括号。先处理有口音差异的三类,剩下的一律去括号留内容。"""
    if accent == "uk":
        s = re.sub(r"\([rɹ]\)", "", s)          # 非儿化:连诵 r 单说不读 → 整个删
        s = re.sub(r"\(j\)", "j", s)            # 英式保留 u 前的 yod
        s = re.sub(r"\(ː\)", "ː", s)            # 英式有长短对立 → 留长音
    else:
        s = re.sub(r"\([rɹ]\)", "r", s)         # 儿化:r 必读 → 去括号留 r
        s = re.sub(r"\(j\)", "", s)             # GA 在 t/d/n/l 后丢 yod
        s = re.sub(r"\(ː\)", "", s)             # GA 无长短对立
    s = re.sub(r"\(\s*\)", "", s)
    return re.sub(r"\(\s*(.+?)\s*\)", r"\1", s)  # 其余:去括号留内容


def normalize(ipa, accent="uk"):
    """严式 IPA → 教学式。accent 必须是 'uk' 或 'us' —— 共用一套规则修不好(见模块注释)。"""
    if not ipa:
        return ipa
    s = ipa
    for a, b in TIEBAR:
        s = s.replace(a, b)
    s = SUPERSCRIPT.sub("", s)
    for d in DIACRITICS:
        s = s.replace(d, "")
    for a, b in COMMON:
        s = s.replace(a, b)

    # 成节辅音 → 补 schwa。⚠️ (ə)C̩ 先合并,否则出双 schwa
    s = re.sub(r"\(ə\)([lnmr])" + SYL, r"ə\1", s)
    s = re.sub(r"([lnmr])" + SYL, r"ə\1", s)
    s = s.replace(SYL, "")

    if accent == "uk":
        s = s.replace("ɚ", "ə").replace("ɝ", "ɜː")   # 非儿化:不加 r
        s = s.replace("ɛ", "e")                      # DJ 记法
        s = re.sub(r"a(?![ɪʊ])", "æ", s)             # TRAP;排除 aɪ/aʊ
    else:
        s = s.replace("ɚ", "ər").replace("ɝ", "ɜr")  # 儿化:带 r、不加长音符
        # ⚠️ 不动 uː/iː/ɑː 这些长音符:剑桥/朗文的美式 IPA 本来就写 /uː/,
        #    "美式无长短对立"只适用于**可选长音 (ː)**那一类,推广到全部是我一度想当然。

    s = _parens(s, accent)
    s = s.replace(".", "")
    s = re.sub(r"ː{2,}", "ː", s)                     # ɝ→ɜːr 撞上已有 ː
    s = re.sub(r"[()]", "", s)                       # 兜底:源数据有括号没闭合的(见 TS 侧注释)
    s = re.sub(r"r{2,}", "r", s)                     # ⚠️ 必须在括号拆完之后
    return s.strip()


# ---------- 旧版(线上现行),仅供回归对比 ----------
LEGACY = [("̯", ""), ("̩", ""), ("̟", ""), ("̥", ""), ("̈", ""), ("ʰ", ""),
          ("̚", ""), ("̃", ""), ("‿", ""), ("ʔ", ""), ("kç", "k"),
          ("t͡ʃ", "tʃ"), ("d͡ʒ", "dʒ"), ("t͡s", "ts"), ("d͡z", "dz"),
          ("aj", "aɪ"), ("æw", "aʊ"), ("ɚ", "ər"), ("ɝ", "ɜːr"),
          ("aʊɜːr", "aʊər"), ("ɹ", "r"), ("ɾ", "r"), ("ɫ", "l"),
          ("æʊ", "aʊ"), ("ʌɪ", "aɪ"), ("ɐ", "ə"), ("ɨ", "ɪ"), ("ɛ", "e"),
          (".", ""), ("rr", "r")]


def legacy(ipa):
    if not ipa:
        return ipa
    s = ipa
    for a, b in LEGACY:
        s = s.replace(a, b)
    s = re.sub(r"\(\s*\)", "", s)
    return re.sub(r"\(\s*(.+?)\s*\)", r"(\1)", s)


SELFTEST = [
    # (输入, accent, 期望)  —— 全部来自 2000 条审计里两家同码判错的真实词条
    ("ˈsaɪɾɪŋ", "us", "ˈsaɪtɪŋ"),        # citing 闪音,旧版出 ˈsaɪrɪŋ
    ("fɪʔi", "uk", "fɪti"),               # fitty 喉塞,旧版出 fɪi
    ("ˈpipɐl", "us", "ˈpipʌl"),           # peepul STRUT,旧版出 ˈpipəl
    ("æbˈhɔːɹɚz", "uk", "æbˈhɔːrəz"),    # abhorrers 英式不该加 r,旧版出 …rərz
    ("æbˈhɔɹɚz", "us", "æbˈhɔrərz"),     # 同词美式该有 r
    ("ˈhɛdənɪst", "uk", "ˈhedənɪst"),    # 英式 DRESS → e
    ("ˈhɛdənɪst", "us", "ˈhɛdənɪst"),    # 美式保留 ɛ
    ("ˈpantri", "uk", "ˈpæntri"),         # 裸 a → æ
    ("ˈtraɪ", "uk", "ˈtraɪ"),             # ⚠️ 双元音 aɪ 不能被 a→æ 劈坏
    ("ˈaʊt", "uk", "ˈaʊt"),               # 同上 aʊ
    ("æbˈdʌktə(r)", "uk", "æbˈdʌktə"),   # 英式连诵 r 删掉
    ("æbˈdʌktə(r)", "us", "æbˈdʌktər"),  # 美式留 r
    ("ˈnʌmbɚ(r)", "us", "ˈnʌmbər"),      # 重复 r 合并(旧版出 ˈnʌmbər(r))
    ("ˈæb.s(ə)n̩s", "uk", "ˈæbsəns"),    # (ə)+成节符 合并,不出双 schwa
    ("ˈdɜːndl̩", "uk", "ˈdɜːndəl"),      # dirndl 成节 l 补 schwa
    ("æbˈd(j)uːsɛnz", "uk", "æbˈdjuːsenz"),   # 英式留 yod
    ("æbˈd(j)uːsɛnz", "us", "æbˈduːsɛnz"),     # 美式丢 yod、去长音
    ("t͡ʃiːz", "uk", "tʃiːz"),
    ("ˈkɑm⁽ʲ⁾inʲ", "uk", "ˈkɑmin"),     # 上标括号+腭化符清掉(ɑ 后有 m,不受 a→æ 影响)
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--accent", default="uk", choices=["uk", "us"])
    ap.add_argument("ipa", nargs="*")
    a = ap.parse_args()
    if a.selftest:
        bad = 0
        for src, acc, want in SELFTEST:
            got = normalize(src, acc)
            ok = got == want
            bad += not ok
            old = legacy(src)
            print(f"  {'✓' if ok else '✗'} [{acc}] {src:20} 旧 {old:18} 新 {got:18}"
                  f"{'' if ok else f'  期望 {want}'}")
        print(f"\n{len(SELFTEST)-bad}/{len(SELFTEST)} 通过")
        raise SystemExit(1 if bad else 0)
    for s in a.ipa:
        print(f"{s}  →  旧 {legacy(s)}   新[{a.accent}] {normalize(s, a.accent)}")


if __name__ == "__main__":
    main()
