#!/usr/bin/env python3
"""`dict.word_norm` 的判据 —— **英语归一形，只此一份**。2026-09-07。

═══ word_norm 是干什么的 ═══
它不是"更好的词形"，是**检索键**：让 `cafe` 能查到 `café`、`Naive` 能查到 `naïve`。
`word` 列永远保留源头原样（大小写、变音符、撇号全部不动）。

🔴 **为什么必须是两列而不是一列**：`[[case-folding-contaminates-columns]]` ——
   老库当年建库时直接 `word.lower()` 折叠，`Polish`/`polish`、`March`/`march`、`US`/`us`
   被并成一条，后遗症是"拆行只拆了行、没回收属性"。归一形单独一列就没有这个问题。

═══ 判据（英语专用，不照搬 de）═══
de 的 `norm_de` 是 `ä→ae ö→oe ü→ue ß→ss` —— 那是**德语的正字法约定**（变音符可以按这个
拆写），照搬到英语是错的：英语里的变音符全部来自借词，读者输入时是**直接省掉**
（`cafe` / `naive` / `resume`），不是拆成两个字母。
⇒ 英语用 **NFD 分解 + 丢弃组合记号**，即 `é→e`、`ï→i`、`ñ→n`。

**保留**（它们是英语正字法的一部分，不是噪声）：
  · 撇号 `don't` / `o'clock` / `'tis`（`EN_PLAN` 记过一整族前置撇号词）
  · 连字符 `well-known` / `e-mail`
  · 空格（词组是正经词头，全库 32 万条）
**只做**：NFD 去记号 + 小写 + 首尾空白。

⚠️ 不做的：不删标点、不合并连字符与空格、不做词干还原。
   那些都是"看起来更整齐"，但会把不同的词并到一起 —— 错比缺更伤权威。
"""
import unicodedata


def norm_en(s):
    """→ 检索用归一形。`word` 原样保留，这里只产出键。"""
    if not s:
        return ""
    # NFD 把 é 拆成 e + U+0301，再丢掉所有组合记号（Mn 类）
    d = unicodedata.normalize("NFD", s)
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    # 合成回 NFC：拆不掉的（如 ø、đ）保持单字符，避免同一个词出现两种字节表示
    return unicodedata.normalize("NFC", d).lower().strip()


if __name__ == "__main__":
    CASES = [
        ("café", "cafe"), ("naïve", "naive"), ("résumé", "resume"),
        ("Zoë", "zoe"), ("piñata", "pinata"), ("Ångström", "angstrom"),
        ("don't", "don't"), ("o'clock", "o'clock"), ("'tis", "'tis"),
        ("well-known", "well-known"), ("e-mail", "e-mail"),
        ("New York", "new york"), ("US", "us"), ("Polish", "polish"),
        ("  spaced  ", "spaced"), ("", ""), (None, ""),
        # 拆不掉的字符原样保留（不是变音符，是独立字母）
        ("Ø", "ø"), ("Đ", "đ"),
    ]
    bad = 0
    for src, want in CASES:
        got = norm_en(src)
        ok = got == want
        bad += not ok
        print("   %s %-14r → %-14r %s" % ("✅" if ok else "🔴", src, got,
                                          "" if ok else "期望 %r" % want))
    print("\n   %s" % ("✅ %d/%d" % (len(CASES), len(CASES)) if not bad
                       else "🔴 %d 条不符" % bad))
    raise SystemExit(1 if bad else 0)
