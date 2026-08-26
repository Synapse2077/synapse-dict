#!/usr/bin/env python3
"""**证据层 → 出版层**这一步的文本清洗，唯一的一份。2026-08-25。

═══ 为什么必须有这个文件 ═══
🔴 `[[replay-scripts-undo-fixes]]` 的形状，我又撞上了一次：
   `fixes/` 底下那四个清洗脚本（脚注 / 编者残渣 / 标点 / 引文署名）
   **改的全是出版层 `sense_gloss`**，证据层 `sense_src` 一个字没动 ——
   `sense_src` 里现在还躺着 **4,049 条**带 `^([1])` 的行。
   而裁决这一步正是把证据层的文本**搬进**出版层。
   ⇒ 不清洗就等于把已经修好的缺陷原样搬回来，而且四道闸没有一道看得见。

═══ 为什么不去清证据层 ═══
证据层存的是**原文**，`pipeline/verify_vs_dump.py` 那道外锚闸拿它逐条对 dump。
改了它，闸当场红 4,049 条，而数据一点问题都没有。
`ingest_fr_edition.py` 的开头就写着这个约定：
「正则留到**提升到出版层**时再用；正则以后改好了不用重灌数据。
  **这正是两层义项存在的理由。**」
⇒ 清洗属于「提升」这一步，不属于「收录」。放这里是对的。

═══ 判据一个字都不重写 ═══
`[[refactor-mindset-code-quality]]`：四族判据全部 `import` 自它们原来的家。
每一条都是当初逐条读了全库取值才定下的（见各自的 docstring），
在这里重抄一遍 = 两边慢慢漂开，等哪天渲染出来才发现。

用法：
    from pipeline.gloss_clean import clean
    new = clean(text)        # → 洗过的文本；**返回 "" 表示这条不该出版**
    python3 pipeline/gloss_clean.py      # 自测 + 扫一遍证据层看影响面
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import strip_citation_tails as _cit        # noqa: E402
import strip_editorial_residue as _res     # noqa: E402
import strip_footnote_refs as _foot        # noqa: E402
import tidy_gloss_punctuation as _tidy     # noqa: E402


# 🔴 wikitext **模板/链接残渣**，全库 5 条，全在句首，正文本身是好的：
#     `[[légumes|fr}} Laiteron maraîcher (Sonchus oleraceus L.).`
#     `{{vieux|fr]] Relatif à la Haute-Volta et ses habitants.`
#     `}} Relatif à une anatopie ; propre à un monde fictif…`
# `fixes/strip_editorial_residue.py` 当年是**按 sense_gloss 行号写死**修的（那时只有 2 条），
# 所以判据没法复用到证据层 —— 这就是"按行号修"的代价：换一层就得重写。
# ⇒ 这里写成判据：**句首**的一段模板残渣、以 `}}`/`]]`/`}`/`]` 收尾的，剥掉。
#   ⚠️ 只认句首（`^`），句中的花括号不动 —— 没有证据说那也是残渣。
BRACE = re.compile(r"^\s*(?:\{\{|\[\[)?[^\s{}\[\]]*(?:\}\}|\]\]|\}|\])\s*")


def clean(t):
    """证据层原文 → 可出版的法语释义。**空串 = 这条不该出版**。

    顺序不能换：
      ① 引文署名要在脚注之前剥 —— 署名段里也可能带 `^([1])`，先剥署名少做一次功。
      ② 编者残渣（`(Ajouter)` 之类）剥完会留下吊着的标点，所以
      ③ 标点收拾放最后。
    """
    s = " ".join((t or "").split())
    if not s:
        return ""
    if _cit.CIT.search(s) and not _cit.KEEP.search(s):          # ① 引文署名
        s = _cit.CIT.sub("", s).rstrip(" ,;:")
    s = _foot.REF.sub("", s)                                    # ② 引用脚注
    # 🔴 `_res.tidy` **只许跑在真剥掉了残渣的行上**。它那条空格+句点的规则
    #    （`\s+([\.,])(?![\.…])`）比 `tidy_gloss_punctuation` 那条宽 ——
    #    没有"标点后面必须是空白/右括号/行尾"的护栏，会把 `Microsoft .NET`
    #    吃成 `Microsoft.NET`。原脚本只把它用在 117 条剥过的行上，所以没咬人；
    #    我在这里无条件套上去 = 把判据放宽了。自测第 14 例逮到的就是这个。
    if _res.RX.search(s) and not _res.KEEP_RX.search(s):        # ③ 编者残渣
        s = _res.tidy(_res.RX.sub("", s))
    if "{" in s or "}" in s or "]]" in s:                       # ④ 模板残渣（句首）
        s = BRACE.sub("", s, count=1)
    s = _tidy.fix(s)                                            # ⑤ 标点
    if not s or s in _res.STUB or _res.EMPTY.match(s):
        return ""
    return s


# ══════════════════════════════════════════════════════════════════ 自测
CASES = [
    # (原文, 期望)
    ("Voler dans un camp. ^([1])", "Voler dans un camp."),
    ("Qui concerne L’Ascension-de-Patapédia, municipalité québécoise ^([1]).",
     "Qui concerne L’Ascension-de-Patapédia, municipalité québécoise."),
    # 不带方括号的上标是**真内容**，一个字不许动
    ("Le XIX^(ème) siècle.", "Le XIX^(ème) siècle."),
    ("Concentration de 10^(-0.5) mol/L.", "Concentration de 10^(-0.5) mol/L."),
    # 引文署名剥掉，`— (Note …)` 留下
    ("Nom, en Égypte, d’un poids de 45 kg. — (Journal des Débats, 1876)",
     "Nom, en Égypte, d’un poids de 45 kg."),
    ("Sens vieilli. — (Note d’usage : encore courant au Québec)",
     "Sens vieilli. — (Note d’usage : encore courant au Québec)"),
    # 编者残渣
    ("Définition manquante ou à compléter. (Ajouter)", ""),
    ("Étymologie manquante ou incomplète. Si vous la connaissez, merci.", ""),
    ("Sorte de poisson (définition à vérifier)", "Sorte de poisson"),
    # 剥完只剩吊着的介词
    ("Habitant de", ""),
    # 标点
    ("Personne qui pêche , au filet .", "Personne qui pêche, au filet."),
    (". Personne qui pêche.", "Personne qui pêche."),
    # 正常的一律不动
    ("Rapport de cause à effet.", "Rapport de cause à effet."),
    ("Microsoft .NET est une plateforme.", "Microsoft .NET est une plateforme."),
    # wikitext 模板残渣（句首），全库 5 条
    ("[[légumes|fr}} Laiteron maraîcher (Sonchus oleraceus L.).",
     "Laiteron maraîcher (Sonchus oleraceus L.)."),
    ("{{vieux|fr]] Relatif à la Haute-Volta et ses habitants.",
     "Relatif à la Haute-Volta et ses habitants."),
    ("}} Relatif à une anatopie ; propre à un monde fictif.",
     "Relatif à une anatopie ; propre à un monde fictif."),
    ("Pluriel de {{lien|prestolet|fr}.", "Pluriel de {{lien|prestolet|fr}."),  # 🔴 残渣在句中，不动
    # 负控：正常法语里的方括号/花括号不许被误剥
    ("Ensemble {a, b} en mathématiques.", "Ensemble {a, b} en mathématiques."),
]


def selftest():
    bad = 0
    for src, want in CASES:
        got = clean(src)
        if got != want:
            bad += 1
            print("   🔴 %r\n      期望 %r\n      实得 %r" % (src, want, got))
    print("■ 自测 %d 例，红 %d" % (len(CASES), bad))
    return bad


def scan():
    import sqlite3
    from collections import Counter
    import paths
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    c = Counter()
    ex = []
    for t, in con.execute("SELECT text FROM sense_src WHERE src='fr-edition'"):
        n = clean(t)
        c["总数"] += 1
        if n == " ".join(t.split()):
            continue
        c["洗掉整条（不该出版）" if not n else "洗过（内容保留）"] += 1
        if len(ex) < 8:
            ex.append((t, n))
    print("\n■ 扫证据层：%s 条，其中洗过 %s，整条洗没 %s"
          % (format(c["总数"], ","), format(c["洗过（内容保留）"], ","),
             format(c["洗掉整条（不该出版）"], ",")))
    for t, n in ex:
        print("   %-88s\n   → %s" % (" ".join(t.split())[:88], n[:88] or "（不出版）"))
    return 0


if __name__ == "__main__":
    sys.exit(1 if selftest() else scan())
