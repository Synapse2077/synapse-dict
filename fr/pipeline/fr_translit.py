#!/usr/bin/env python3
"""法语地名 → 汉字译写，按**国家标准**确定性生成。2026-08-24。

═══ 依据 ═══
**GB/T 17693.2-1999《外语地名汉字译写导则·法语》**（民政部地名研究所，1999）。
表结构：辅音 22 列 × 元音 20 行的音节矩阵 + 固定词尾表 + 若干字母规则。
矩阵按**拼写**索引（`ain/aim/un/um`、`eau/eaux`），不是纯 IPA
⇒ **不需要造完整 G2P**（fr 七月已定不做 G2P）。

表数据落在 `data/work/fr/fr_tbl.json`，由维基「外语译音表/法语」的原始 wikitext 解析而来。

═══ 🔴 它是**校验器**，不是替代品 ═══
标准自己写明：**只适用于尚未被《世界地名译名词典》和新华社历史资料库收录的地名**。
也就是说 `Paris`→巴黎、`Versailles`→凡尔赛、`Marseille`→马赛 这类**约定译名优先于本表**，
机械套表反而会错。

⇒ 用法是：拿它跟模型给的 26,470 个音译**逐个比**。
   · 一致 ⇒ 该条同时满足「标准」与「模型」，可信
   · 不一致 ⇒ **进人工裁决队列**，不自动改
   这把「只能抽样 0.3%」变成「**全量可核**」。

═══ 🔴🔴 当前状态：**还不够格当校验器**（2026-08-24 实测）═══
拿它核 26,470 个模型音译，得「58.6% 不一致」。**这个数不能用来判模型**——
我逐条读了分歧最多的 18 个，**多数是本模块错、模型对**：

    Saint-Hilaire   模型 圣伊莱尔   本模块 圣耶尔     ← 词首 `il` 被当成了 [j] 辅音列
    Saint-Hippolyte 模型 圣伊波利特  本模块 圣伊普波利特 ← 双写 `pp` 该读单音
    Bussières       模型 比西耶尔   本模块 比谢尔     ← `siè` 该是 西+耶
    Saint-Michel    模型 圣米歇尔   本模块 圣米谢尔    ← 约定译名
    Brion           模型 布里翁    本模块 布里永      ← `ion` 在辅音后不读 [jɔ̃]

`tests/test_fr_translit.py` 上报 81%，那是**虚高**：那 16 条真值是我挑的，
正好都是它会做的。⇒ **别拿本模块的输出去改数据**，它现在只够当讨论材料。

已修的 8 个 bug 记在各处 🔴 注释里（削两次词尾 / 对词片段削词尾 / 裸辅音取错行 /
鼻化没取消 / 词尾 e 没走词尾行 / `er` 当通用拼写 / `ch` 在 r 前 / `-ville` 派生形式）。
还差的：词首 `il`、双写辅音、`ion` 的上下文、`Saint-` 后接人名的惯例。

═══ 覆盖不了就说覆盖不了 ═══
`translit()` 遇到拆不出音节的片段返回 `None`。**不猜**。

跑：python3 pipeline/fr_translit.py --demo
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths   # noqa: E402

TBL = json.loads((paths.WORK / "fr_tbl.json").read_text(encoding="utf-8"))

# ── 辅音列 → 该列覆盖的拼写（表头里带条件说明，这里按标准正文摊开）──
# 列序必须与 fr_tbl.json 的 `cons` 一致。
CONS_SPELL = [
    ["b"], ["p"], ["d"], ["th", "t"], ["g"], ["ge"], ["gh"], ["gu"],
    ["qu", "k", "q"], ["cc", "c"], ["w", "v"], ["ph", "f"], ["z"],
    ["ss", "ç", "s"], ["j"], ["ch"], ["mm", "m"], ["nn", "n"], ["gn"],
    ["ll", "l"], ["rr", "r"], ["ill", "il", "y"],
]

# ── 固定词尾 ──
# 🔴 标准正文列了 23 条（-be 布、-de 德、-ne 讷、-re 尔…），但**其中 20 条与矩阵重复**：
#    `e(词尾)` 那一行本来就给出 b→布 d→德 n→讷 r→尔 qu→克。
#    我第一版把它们全做成"先切词尾再分音节"，结果**切掉词尾就把上下文毁了**：
#    `Bannes` → 切出 `-ne`，头部剩 `ban`，双写 n 没了 ⇒ 鼻化没被取消 ⇒ 出「邦讷」（该是巴讷）。
#    ⇒ 只保留**矩阵表达不了**的三条，其余交给 `e(词尾)` 行。
FINAL = [("ille", "耶"), ("illi", "伊"), ("illy", "伊")]

# 🔴 标准点名的习惯译法，压过矩阵。
#    正文原话：「但 ville 发 [vil]，汉字习惯译为"维尔"；**其派生形式也按此译法**」
#    ⇒ 不只整词，`Conteville`/`Francheville` 这种**词尾 -ville** 也要走它。
HABIT = {"ville": "维尔"}
HABIT_SUFFIX = [("ville", "维尔"), ("villers", "维莱"), ("villiers", "维利耶")]

# 🔴 避免望文生义（标准正文）：词首「东南西」→「栋楠锡」，词尾「海」→「亥」
HEAD_FIX = {"东": "栋", "南": "楠", "西": "锡"}
TAIL_FIX = {"海": "亥"}

# 连接成分：法国地名里高频，按标准音节译写（这里固化，省得每次重算）
JOIN = {"saint": "圣", "sainte": "圣", "sur": "叙尔", "sous": "苏", "les": "莱",
        "lès": "莱", "le": "勒", "la": "拉", "en": "昂", "et": "埃", "de": "德",
        "du": "迪", "des": "德", "aux": "欧", "au": "欧", "d": "德", "l": "勒"}


def _rowspell():
    """元音拼写 → 行号。长的优先。"""
    out = {}
    for i, r in enumerate(TBL["rows"]):
        for s in r["spell"]:
            out.setdefault(s, i)          # 先出现的行优先（表内顺序即优先级）
    return out


ROW = _rowspell()
# 🔴 这几个拼写在标准里**只在词尾成立**（`es`单音节词中 / `er`词尾开音节 / `ez`词尾 / `et`结尾）。
#    当成通用拼写会在词中乱切：`Mazerolles` 的 `zer` 被切成 z+er ⇒ 泽，
#    后面的 `o` 就变成裸元音「奧」，出「马泽奧勒」（该是马泽罗勒）。
FINAL_ONLY = {"er", "es", "ez", "et"}
ROW_KEYS = sorted(ROW, key=len, reverse=True)
CONS_KEYS = sorted(({s: i for i, ss in enumerate(CONS_SPELL) for s in ss}).items(),
                   key=lambda kv: -len(kv[0]))
CONS_MAP = dict(CONS_KEYS)
CONS_ORDER = [k for k, _ in CONS_KEYS]

E_FINAL_ROW = 3     # `e(词尾)` 那一行：词尾的 e 不单独发音
SCHWA_ROW = 2       # `e(词首开音节中)` = [ə] 那一行
# 🔴 表里**有一整行专给"辅音单独出现"**（b→布 g→格 l→尔 r→尔 …）。
#    我第一次解析时把它当成表头丢掉了，于是裸辅音全去别的行取字：
#    `Bordeaux` 的 r 取到「勒」出「博勒多」（该是博尔多）、
#    `Grenoble` 的 g 取到 [ə] 行的「热」出「热朗奧布勒」（该是格勒诺布勒）。
BARE = TBL["bare_cons"]
# 鼻化元音那两行的拼写集合（用于"鼻化失效"判定）
NASAL_ROWS = {sp: i for i, r in enumerate(TBL["rows"])
              for sp in r["spell"] if r["ipa"].strip() in ("ɛ̃ œ̃", "ɑ̃", "ɔ̃", "wɛ̃", "jɛ̃", "jɔ̃")}

# 🔴 **词尾哑辅音**。法语词尾辅音多不发音，这是译写里最常错的地方：
#    `Caumont` 若按字面出「科蒙特」就错了（t 不发音 ⇒ 科蒙）。
#    例外是所谓 CaReFuL 一组（c/r/f/l）通常发音，另加 -ct/-ps 等少数组合。
SILENT_FINAL = "stdxzpgn"
SOUNDED_FINAL = "crfl"


# 🔴 `ch` 在 r/l 前读 [k] 不是 [ʃ]（`Christophe` /kʁistɔf/）。
#    一律按 [ʃ] 处理会出「圣什里斯托夫」。这里先改写成 `k`，让矩阵按 k 列取字。
_CH_K = re.compile(r"ch(?=[rl])")


def _strip_h(s):
    """h 不发音。⚠️ `ch`/`ph`/`gh`/`th` 是辅音组合，不能拆 —— 先保护再删。"""
    s = _CH_K.sub("k", s)
    s = re.sub(r"(?<![cpgt])h", "", s)
    return s


def _seg(word):
    """把一个片段切成 [(辅音列 or None, 元音行)]，切不动返回 None。**不猜。**"""
    # 🔴 **这里不削词尾**。削词尾只在 `_piece` 里做一次。
    #    第一版两处都削 ⇒ `Saint-Just` 的 t 和 s 被连削两刀，出「圣瑞」（该是圣瑞斯特）。
    #    而且 `_seg` 还会被喂**词的片段**（切掉 -illy 之后的 `and`），
    #    对片段削"词尾"根本没有意义 ⇒ `Andilly` 出「昂伊」（该是昂迪伊）。
    w = _strip_h(word.lower())
    out, i = [], 0
    while i < len(w):
        c = None
        pos0 = i
        for k in CONS_ORDER:
            if w.startswith(k, i):
                c, i = CONS_MAP[k], i + len(k)
                break
        v = None
        for k in ROW_KEYS:
            if not w.startswith(k, i):
                continue
            if k in FINAL_ONLY and i + len(k) != len(w):
                continue
            # 🔴 鼻化元音失效（标准正文两条例外）：
            #    · 组合中的 -m/-n 后面**再跟元音字母** ⇒ 不再鼻化
            #      （`Grenoble` 的 `en` 后面是 o ⇒ 该读 [ən] 不是 [ɑ̃]）
            #    · 组合中的 -m 后再跟 m、-n 后再跟 n ⇒ 不再鼻化
            #      （`Bannes` 的 `an` 后面是 n ⇒ 巴讷，不是邦内）
            if k[-1] in "nm" and NASAL_ROWS.get(k) is not None:
                nxt = w[i + len(k):i + len(k) + 1]
                if nxt and (nxt in "aeiouyàâéèêëîïôöùûü" or nxt == k[-1]):
                    continue
            v, i = ROW[k], i + len(k)
            # 🔴 `e` 单独出现时开/闭音节取不同行：闭音节(后跟两个辅音或词尾辅音)按「埃」，
            #    开音节(后面一个辅音再跟元音)按「厄」。
            #    第一版一律取「埃」⇒ `Beaurepaire` 的 re 出「雷」（该是「勒」）。
            if k == "e":
                rest = w[i:]
                if not rest:
                    v = E_FINAL_ROW        # **词尾的 e**：走 `e(词尾)` 行
                    #  ⇒ -ne 讷 / -re 尔 / -le 勒 / -que 克，与标准的固定词尾表一致。
                    #  漏了这条时 `Grenoble` 出「格勒诺布莱」、`Bannes` 出「巴内」。
                elif re.match(r"^[^aeiouyàâéèêëîïôöùûü][aeiouyàâéèêëîïôöùûü]", rest):
                    v = SCHWA_ROW
            break
        if c is None and v is None:
            return None                    # 出现表里没有的字母组合 ⇒ 放弃
        if v is None:
            out.append((c, None))          # 裸辅音 ⇒ 走 BARE 行
        else:
            out.append((c, v))
    return out


def _shave(lw):
    """削掉词尾哑辅音。与 `_seg` 里那段同一条规则 —— **抽出来是因为固定词尾表
    也要在削完之后才查**：`Jonquières` 不削掉 s 就匹配不上 `-re`(尔)，出「雷」。"""
    if len(lw) > 1 and lw[-1] in SILENT_FINAL:
        if not (lw[-1] in "nm" and lw[-2] in "aeiouy"):
            return lw[:-1]
    return lw


def _piece(word):
    """单个片段（连字符之间的一段）→ 汉字，或 None。"""
    raw = word.lower()
    # 🔴 习惯译法/连接成分要在**削词尾哑辅音之前**查 ——
    #    削过之后 `saint` 变成 `sain`，查不到 JOIN，出「桑」而不是「圣」。
    if raw in HABIT:
        return HABIT[raw]
    if raw in JOIN:
        return JOIN[raw]
    lw = _shave(raw)
    for suf, zh in HABIT_SUFFIX:           # 习惯译法的词尾，最高优先
        if lw.endswith(suf) and len(lw) > len(suf):
            head = _piece_core(lw[:-len(suf)])
            return None if head is None else head + zh
    for suf, zh in FINAL:                  # 固定词尾优先于矩阵
        if lw.endswith(suf) and len(lw) > len(suf):
            head = _piece_core(lw[:-len(suf)])
            return None if head is None else head + zh
    return _piece_core(lw)


def _piece_core(word):
    segs = _seg(word)
    if not segs:
        return None
    out = []
    for c, v in segs:
        if v is None:                      # 裸辅音
            ch = BARE[c]
        else:
            row = TBL["rows"][v]
            ch = row["bare"] if c is None else row["chars"][c]
        ch = re.sub(r"[（(\[][^）)\]]*[）)\]]", "", ch)   # 去掉 (娜)(莎) 这类女性用字备选
        ch = ch.split("/")[0].strip()                    # 「戈/若」取前者
        if not ch:
            return None
        out.append(ch)
    return "".join(out)


def translit(name):
    """法语地名 → 汉字译写，或 None（拆不出来就**不猜**）。"""
    parts = re.split(r"[-\s’']+", name.strip())
    got = []
    for p in parts:
        if not p:
            continue
        z = _piece(p)
        if z is None:
            return None
        got.append(z)
    if not got:
        return None
    s = "-".join(got) if len(got) > 1 else got[0]
    s = s.replace("-", "")                 # 标准里复合地名汉字连写，不留连字符
    if s and s[0] in HEAD_FIX:
        s = HEAD_FIX[s[0]] + s[1:]
    if s and s[-1] in TAIL_FIX:
        s = s[:-1] + TAIL_FIX[s[-1]]
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--name", nargs="*")
    a = ap.parse_args()
    names = a.name or ["Saint-Denis", "Bannes", "Beaulieu", "Montgaillard", "Bussières",
                       "Caumont", "Saint-Martin-des-Champs", "Elbeuf", "Beaurepaire",
                       "Thil", "Aigues-Vives", "Jonquières", "Paris", "Versailles",
                       "Marseille", "Lyon", "Bordeaux", "Rouen", "Grenoble"]
    print("%-28s %s" % ("法语", "按 GB/T 17693.2 译写"))
    print("-" * 56)
    for n in names:
        print("%-28s %s" % (n, translit(n) or "—（拆不出，不猜）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
