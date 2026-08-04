#!/usr/bin/env python3
"""记法归一之后的残渣清理：272 行 / 31 族。2026-08-03。

`fixes/normalize_notation.py` 落库后，全列字符普查还剩 272 行带着音位字符表之外的字符。
本轮**只做判据可自证的那部分**，剩下的（外来词送气 h、zh 转写、乱码专名）另列，不硬猜。

═══ 一、确定性修复（判据全部可回核）═══

**ç → θ（34 行）** —— 源头把**拼写字母**写进了音标格：`pereçoso` 的 `phonetic_raw`
就是 `peɾeˈçoso`。`canon_edition` 把 ç 做 NFD 分解、剥掉软音符，只剩下一个裸 `c`。
⭐ 控制组：改完与库里现代拼写的那条**逐字相同** ——
    pereçoso → peɾeˈθoso ＝ 库里 perezoso 的值      fuerça → ˈfweɾθa ＝ fuerza
    quiçá   → kiˈθa      ＝ quizá                  mudança → muˈdanθa ＝ mudanza
（选 θ 不选 s，与本词典 no-seseante 的既有选择一致。）

**ʧ → tʃ（18 行）** —— 同一个音位的预组合字符，库里 5.6 万行写的是分开的 `tʃ`。

**多余连字符（6 行）** —— 判据是**拼写**：拼写里有连字符的位置保留
（`castellano-leonés` `trans-excluyente`、以及 123 个词缀词条 `-io`/`-ingo`），
拼写里没有的删（`desoku-paˈθjon` `ˈmu-tʃos` 是音节切分泄漏）。

**残余的严式记号与乱入字符（14 行）** —— 组合附加符（`peˈlao̯` 的 ̯、`mhm` 的 ̩ ̥）、
声调符（`ˌdi˧ɡa˧me˧ˈlon˥`）、软连字符、逗号、大写字母（`ˈBjena` `ˈDjos`）、
希腊/斯拉夫字母（δ đ ł ζ μ）。都是**同一个音位的别写法或纯噪声**，按位替换或删除。

**替换字符 �（2 行）** —— 判据是拼写：`carcinogénesis` 的 `ka�θino` 对应 `carcino` → `kaɾθino`；
`multiprotocolo` 的 `mult�` → `multi`。

**重音字母（2 行）** —— `podoˈtáktil` 已有 ˈ，á→a 即可；
`postromantiθísmo` 没有 ˈ，那个 í 就是重音本身 → `postromantiˈθismo`。

**西语正字法的哑音 h（15 行）** —— 西语的 h **不发音**，这是正字法事实，不是我的判断：
`hormiga → oɾˈmiɡa`（顺带修重音位置：hor-mi-ga）、`Alcohólicos → alkoˈolikos`、
`hábeas corpus → ˌabeas ˈkoɾpus`。逐条写在 SILENT_H 表里。

═══ 二、本轮不动、另列（约 71 行）═══
| 族 | 行 | 为什么不硬猜 |
|---|---|---|
| 外来词送气 h | 11 | `hard` `hácker` `huf` `Hauschildt` —— 读 /x/ 还是脱落是**惯例**，规则推不出 |
| ʒ（zh 转写与 dj- 词） | 26 | `Guangzhou` `djaina` —— 映射到 tʃ / ʃ / ʝ 是三种不同的产品选择 |
| 乱码专名 | 5 | `Irkutsk → iɾˈkutǀ`（源头把 sk 写成了点击音符号），要重写不是替换 |
| 英语元音 ɜ、ʈʂ、数字与符号 | 15 | `kitesurf` `PDF417` `μm` `Ζenera` —— 与上一轮 444 条同一性质 |

这批的性质与 `pipeline/fill_last_gaps.py` 处理的完全相同（外来词/缩写/符号，
读法约定俗成），要么攒一批走豆包 pro，要么留空。**不在本脚本里瞎填。**

用法（在 es/ 目录）：
    python3 fixes/clean_ipa_residue.py
    python3 fixes/clean_ipa_residue.py --apply
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import re
import sqlite3
import unicodedata as U

import dbtool

# 音位字符表 + 连字符（词缀词条 `-io` 的连字符是内容，见文件头）
INVENTORY = set("aeiou" "bdfklmnprstxɡɲɾθʃʝjw" "ˈˌ" " |-")

# 按位替换：左边这些字符在库里出现，都是"同一音位的别写法"或纯噪声。
CHAR_MAP = {
    "c": "θ",    # ç 的残骸（软音符被 canon_edition 剥掉了），控制组见文件头
    "ʧ": "tʃ",   # 预组合的塞擦音
    "δ": "d", "đ": "d", "ł": "l",   # 希腊 δ、克罗地亚 đ、波兰 ł 乱入
    "B": "b", "D": "d",             # 大写字母
    "á": "a",                       # 该行已有 ˈ，重音不靠字母携带
    "ʀ": "r",                       # 小舌颤音 → 我们的 r
    ",": "", "\xad": "",            # 标点、软连字符
    "˥": "", "˧": "",               # 声调符
}
# 组合附加符（NFD 之后才看得见）：升降符/成音节符/清音符/非成音节符/鼻化符
COMBINING = {"̯", "̩", "̥", "̃", "͡", "̪", "̝", "̞"}

# 判据来自拼写、必须逐条写的（左＝现值，右＝改后）
MANUAL = {
    # 替换字符 �：按拼写补回丢掉的那个音
    "carcinogénesis": "kaɾθinoˈxenesis",
    "multiprotocolo": "multipɾotoˈkolo",
    # 重音字母：这一行没有 ˈ，那个 í 就是重音本身
    "postromanticismo": "postromantiˈθismo",
    # 首字母被写错（goebbeliana 的 ɡ 被写成了 b）+ ø 不是西语音位
    "goebbelianamente": "ɡoebeljanaˈmente",
    # 拟声叹词：剥完严式记号剩 `mˈmm`，重音符落在音节中间不成话
    "mhm": "ˈmm",
}

# 西语正字法的哑音 h：h 不发音。顺带修 `hormiga` 的重音位置（hor-mi-ga）。
SILENT_H = {
    "hormiga": "oɾˈmiɡa",
    "incoherentemente": "inkoeɾenteˈmente",
    "Alcohólicos Anónimos": "alkoˈolikos aˈnonimos",
    "inherentemente": "ineɾenteˈmente",
    "antihomofobia": "antiomoˈfobja",
    "alcoholimetría": "alkoolimeˈtɾia",
    "hábeas corpus": "ˌabeas ˈkoɾpus",
    "hacer el papel": "aˌθeɾ el paˈpel",
    "habés": "aˈbes",
    "halotriquita": "alotɾiˈkita",
    "ahu": "ˈau",
    "mahout": "maˈut",
    "wahabí": "waaˈbi",
    "Weishaupt": "ˈbaisaupt",
    "ohú": "oˈu",
}

# 明确留给下一轮的族（外来词读法/乱码专名），本脚本一个字符都不碰
DEFER = set("hʒǀɜʂʈøʻʼμζ0123456789")


def fix(word, v):
    if word in MANUAL:
        return MANUAL[word]
    if word in SILENT_H:
        return SILENT_H[word]
    if set(v) & DEFER:
        return v
    s = "".join(ch for ch in U.normalize("NFD", v) if ch not in COMBINING)
    s = U.normalize("NFC", s)
    for a, b in CHAR_MAP.items():
        s = s.replace(a, b)
    # 连字符：拼写里没有连字符的词，音标里的连字符是音节切分泄漏
    if "-" in s and "-" not in word:
        s = s.replace("-", "")
    return re.sub(r"\s+", " ", s).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    rows = conn.execute(
        "SELECT id, word, phonetic, COALESCE(phonetic_src,'?') FROM dict "
        "WHERE TRIM(COALESCE(phonetic,''))<>''").fetchall()
    conn.close()

    changes, samples = [], []
    left = collections.Counter()
    left_rows = collections.defaultdict(list)
    for rid, w, v, src in rows:
        c = fix(w, v)
        if c != v:
            changes.append((c, rid))
            samples.append((w, v, c))
        bad = "".join(sorted({ch for ch in c if ch not in INVENTORY}))
        if bad:
            left[bad] += 1
            if len(left_rows[bad]) < 3:
                left_rows[bad].append((w, c))

    print("■ 确定性修复 %d 行" % len(changes))
    dbtool.sample_check(samples, 20, ("词", "改前", "改后"))
    print("\n■ 仍在字符表之外、留给下一轮：%d 行 / %d 族" % (sum(left.values()), len(left)))
    for k, n in left.most_common():
        print("   %-6r %4d  %s" % (k, n, left_rows[k][:2]))

    if not a.apply or not changes:
        print("\n(预览。确认后 --apply)")
        return
    with dbtool.session("ipa-residue", expect={}) as s:
        s.executemany("UPDATE dict SET phonetic=? WHERE id=?", changes)


if __name__ == "__main__":
    main()
