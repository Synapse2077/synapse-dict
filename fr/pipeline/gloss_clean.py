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
# 🔴 2026-08-27：BRACE 判据太宽，`Commune]] d’Espagne…` 被它整段吃掉 `Commune]]`，
#    而 `Commune` 是**正文第一个词**（`Puebla de Obando` 的释义就此丢掉主语）。
#    ⇒ 加一道护栏，分界线是**花括号 vs 方括号**：
#      · 以 `}` / `}}` 收尾 —— **花括号在法语正文里根本不出现**，一律是模板残渣，
#        前面是什么都剥（`Lorraine}` 是 `{{Lorraine|fr}}` 丢了左半边）。
#      · 以 `]` / `]]` 收尾 —— 方括号是**会出现在正文里的**（`crochet`/`érasure`
#        整条释义讲的就是方括号）⇒ 只有前面为空、或带着 `{` `[` `|` 才算残渣。
#        `Commune]] d’Espagne` 里的 `Commune` 是正文第一个词，不许剥。
#   🔴 第一版护栏没分这两种，`Lorraine} Lieu où se déroulait la veillée.` 当场被挡住。
TPL = re.compile(r"^\s*(?:\{\{|\[\[)?([^\s{}\[\]]*)(?:\}\}|\]\]|\}|\])")


def _is_template(s):
    m = TPL.match(s)
    if not m:
        return False
    body = m.group(0)
    if body.rstrip().endswith("}"):
        return True
    return not m.group(1) or any(ch in body for ch in "{[|")

# ══════════════════════════════════════════════════════════════════ wiki 链接残渣
# 🔴 上面 BRACE 那条只认**句首**，注释里写着「句中的花括号不动 —— 没有证据说那也是残渣」。
#    2026-08-27 有证据了：全库 23 条证据行带 `[[`/`]]`，我逐条读完，20 条是断掉的
#    wiki 链接（`chose]]s`、`Commune]] d’Espagne`、`[[w:…|planète mineure]]`）。
#    它们卡住了裁决那步的可逆性闸 —— 出版层那两行早被行级脚本修好了，证据层没有，
#    于是「证据 + clean」重建不出出版层的值。
#
# ⚠️ **不许写成「见到 [[ 就剥」**。全库有一族真内容长得一模一样：
#       rouge de méthyle: `acide 2-[[4-(dimethylamino)phenyl]diazenyl]benzoique`
#       érasure:          定义正文讲的就是方括号本身
#    （这两条 `fixes/fix_gate_reds.py` 的 B6_PLAN 已经点名保过一次。）
# ⭐ 判据卡在含义上：
#    ① `[[目标|标签]]` —— **竖线**是 wikitext 独有的，化学命名法里永远没有 `|`。
#       只剥掉 `[[目标|` 这个开头，标签本身是正文要留（`crochet` 的标签就是 `[…]`）。
#    ② 剥完之后**整串不含 `[[` 却还有 `]]`** = 孤立的右半边，删。
#       化学式那条 `[[` 还在 ⇒ ② 够不着它。
#
# 🔴 **写过第三条 `[[目标]]` → 目标，撤掉了**：`érasure` 的正文是
#       「…用两个方括号标在被抹掉文本的两边：`[[abc]]`」
#    那对方括号**就是它要讲的东西**，形式上和 wiki 链接一个字都不差 ——
#    没有任何形式判据分得开。而全库 23 条里**没有一条**需要这个规则。
#    ⇒ 为零收益冒毁掉一条真释义的风险，不做。判据宁可窄。
WIKI_PIPE = re.compile(r"\[\[[^\[\]|]*\|")


def strip_wiki(s):
    if "[[" not in s and "]]" not in s:
        return s
    s = WIKI_PIPE.sub("", s)
    if "[[" not in s:
        s = s.replace("]]", "")
    return s

# ══════════════════════════════════════════════════════════════════ 词条头泄漏
# 🔴 法文版有 43 条把**整段词条头**（音标＋性数＋词性＋变位提示）灌进了 definition 字段：
#       `\sa.mo\`                                    ← 整条就是音标，没有定义
#       `métriques\me.tʁik\féminin`
#       `\tɛ̃.da.li.ze\transitif1ᵉʳ groupe (voir la conjugaison)* Mode de stérilisation…`
#   渲染出来就是「法语定义：\sa.mo\」。阶段 8 接上展示层才看见（`[[it-display-layer-stage8]]`）。
#
# ⭐ 判据卡在**含义**上，不是"看起来像音标"（`[[criteria-from-meaning-not-form]]`）：
#      法文版用 `\…\` 括音标。**词条头里的音标，前面只可能是词头本身或什么都没有**；
#      而真内容里的 `\…\` 前面是一句法语 ——
#         `Variante de achement le \h\ est non étymologique.`   ← 真内容
#         `Changement d’un son \k\ indo-européen en…`            ← 真内容
#         `Utilisé pour représenter \si\ ou \sis\…`              ← 真内容
#   ⇒ 「`\…\` 之前那段归一后 ≈ 词头（或为空）」才算泄漏。
#   🔴 第一版判据是「`\…\` 出现在前 40 字符内且前面没句子标点」，全库 49 命中里
#      **6 条是真内容**（上面三条 + `alphacisme`/`zamuco`/`6`）。位置是形式，词头是含义。
PRON = r"\\[^\\]{1,60}\\"
LEAD_PRON = re.compile(r"^(?P<pre>[^\\]{0,40}?)(?P<pron>%s(?:\s*ou\s*%s)*)" % (PRON, PRON))
# 音标之后黏着的语法标记，**闭集**（全部取自这 43 条的实际取值，加一个都要先回源看）。
# 🔴 `\s*` 必须写在重复组**里面**。第一版写成 `^\s*(?:…)+`，
#    于是只有第一个标记前面允许空格，`pluriel invariable` 剥完剩下 `invariable`、
#    `transitif1ᵉʳ groupe (voir la conjugaison)` 剩下 `(voir la conjugaison)`。
#    ⚠️ 这些标记全是小写，而剥完之后的真定义一律以大写字母或 `(` 开头（43 条实测），
#       所以往后多吃一个标记不会啃进正文。
GRAM = re.compile(
    r"^(?:\s*(?:masculin|f[ée]minin|pluriel|singulier|invariable|identiques|"
    r"transitif|intransitif|pronominal|et|ou|[0-9]\s*[ᵉʳ]*\s*groupe|"
    r"\(voir la conjugaison\)|\(Sigle\)|[,:;]))+")
_ACC = str.maketrans("àâäáãçéèêëíìîïñóòôöõúùûüýÿ", "aaaaacéèêëiiiinooooouuuuyy")


def _nkey(s):
    """归一到「同一个词头」的判重键：大小写、重音符、撇号、空白、连字符都不算差别。"""
    s = (s or "").strip().lower().translate(_ACC)
    s = s.replace("’", "'").replace("é", "e").replace("è", "e").replace("ê", "e") \
         .replace("ë", "e")
    return re.sub(r"[\s\-]", "", s)


def strip_header(s, word):
    """剥掉句首的词条头泄漏。不是泄漏就原样返回。"""
    m = LEAD_PRON.match(s)
    if not m:
        return s
    pre, key = m.group("pre"), _nkey(m.group("pre"))
    if pre.strip():
        if word is None:
            return s
        w = _nkey(word)
        # `surges` 的定义泄漏的是单数 `surge` 的头 ⇒ 允许一头是另一头的前缀（差 ≤3 字符）。
        if not (key and w and (key.startswith(w) or w.startswith(key))
                and abs(len(key) - len(w)) <= 3):
            return s
    s = s[m.end():]
    s = GRAM.sub("", s)
    return s.lstrip("*: ,").strip()


def clean(t, word=None):
    """证据层原文 → 可出版的法语释义。**空串 = 这条不该出版**。

    `word` = 这条释义属于哪个词形。只有词条头泄漏那一条判据用得上它；
    不传就只处理「整条以 `\\音标\\` 开头」那半边（前面为空，不需要词头就能判定）。

    顺序不能换：
      ① 引文署名要在脚注之前剥 —— 署名段里也可能带 `^([1])`，先剥署名少做一次功。
      ② 编者残渣（`(Ajouter)` 之类）剥完会留下吊着的标点，所以
      ③ 标点收拾放最后。
    """
    s = " ".join((t or "").split())
    if not s:
        return ""
    if "\\" in s:                                               # ⓪ 词条头泄漏
        s = strip_header(s, word)
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
    # 🔴 ④ 必须在 ⑤ **前面**。反过来写，`strip_wiki` 会先把 `{{vieux|fr]]` 的 `]]` 删掉，
    #    BRACE 靠的就是那个收尾符号，于是句首整段模板反而留下半截 `{{vieux|fr Relatif…`。
    if ("{" in s or "}" in s or "]]" in s) and _is_template(s):  # ④ 模板残渣（句首）
        s = BRACE.sub("", s, count=1)
    s = strip_wiki(s)                                           # ⑤ wiki 链接残渣（句中）
    s = _tidy.fix(s)                                            # ⑤ 标点
    # 🔴 `_res.STUB`（`Habitant de` / `Geste consistant à`）是**吊着介词的半句**，
    #    剥完残渣后 ⑤ 会给它补一个句点 ⇒ `Geste consistant à.` 就躲过了这条判断。
    #    比之前先去掉句末标点再比。STUB 是闭集两条，不存在真释义等于它们。
    if not s or s.rstrip(" .…") in _res.STUB or _res.EMPTY.match(s):
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
    # 吊着介词的半句，⑤ 补了句点也要认出来
    ("Geste consistant à Définition manquante ou à compléter. (Ajouter).", ""),
    ("Habitant de… Définition manquante ou à compléter. (Ajouter)", ""),
    # 负控：`Habitant de` 后面**有内容**的是真释义，一个字不许动
    ("Habitant de Barcelone.", "Habitant de Barcelone."),
    # ── wiki 链接残渣（句中）。全库 23 条证据行，下面覆盖全部四种形状 ──
    ("Classe dans laquelle on range plusieurs chose]]s qui sont d’espèce différente.",
     "Classe dans laquelle on range plusieurs choses qui sont d’espèce différente."),
    ("Nom donné à la [[w:https://fr.wikipedia.org/wiki/Liste_des_planètes_mineures_(1-1000)|"
     "planète mineure]] nᵒ 495.", "Nom donné à la planète mineure nᵒ 495."),
    # 标签本身是正文（`crochet` 的标签就是 `[…]`），只剥 `[[目标|` 和收尾的 `]]`
    ("Des points de suspension placés entre crochets : "
     "[[Titres_non_pris_en_charge/Trois_points_entre_crochets|[…]]], dans une citation.",
     "Des points de suspension placés entre crochets : […], dans une citation."),
    # 句首模板要在 wiki 规则**之前**剥掉（顺序 ④→⑤ 的证据）
    ("{{vieux|fr]] Relatif à la Haute-Volta et ses habitants.",
     "Relatif à la Haute-Volta et ses habitants."),
    ("{{lien|wagon|fr|nom|Wagon]] ou voiture destiné au transport du courrier.",
     "ou voiture destiné au transport du courrier."),
    # 🔴 负控：化学命名法里的 `[[` 是**真内容**（这两条 fix_gate_reds 的 B6_PLAN 保过一次）
    ("Colorant rouge, sa formule brute est C₁₅H₁₅N₃O₂ "
     "(acide 2-[[4-(dimethylamino)phenyl]diazenyl]benzoique).",
     "Colorant rouge, sa formule brute est C₁₅H₁₅N₃O₂ "
     "(acide 2-[[4-(dimethylamino)phenyl]diazenyl]benzoique)."),
    # 🔴 `[[abc]]` 在这条释义里**就是正文**（讲的正是"用两个方括号标在两边"）。
    #    形式上和 wiki 链接完全一样 ⇒ 只能靠"不做 `[[a]]` 这条规则"保住它。
    ("Elle est symbolisée par deux crochets de part et d’autre : [[abc]].",
     "Elle est symbolisée par deux crochets de part et d’autre : [[abc]]."),
    # 负控：普通法语词后面挂孤立 `]]`，不许被句首模板规则整段吃掉
    ("Commune]] d’Espagne, située dans la province de Badajoz.",
     "Commune d’Espagne, située dans la province de Badajoz."),
    # 正控：同一个位置换成**花括号**就是模板残渣（`{{Lorraine|fr}}` 丢了左半边）
    ("Lorraine} Lieu où se déroulait la veillée.", "Lieu où se déroulait la veillée."),
]

# ══ 词条头泄漏（要带 word 才判得了）。43 条全库取值 + 6 条负控 ══
# ⭐ 负控用的就是**上一版判据误杀过的那 6 条**（`[[criteria-from-meaning-not-form]]`）。
WORD_CASES = [
    # (词形, 原文, 期望)
    ("Samot", "\\sa.mo\\", ""),                                   # 整条就是音标
    ("Sacco", "\\sa.kɔ\\", ""),
    ("Durban", "\\dyʁ.bɑ̃\\ ou \\dœʁ.ban\\", ""),                 # 两个音标用 ou 连
    ("Fabricio", "\\faˈbɾi.sio\\masculin", ""),
    ("barrels twist", "\\ba.ʁɛlz twist\\pluriel invariable", ""),
    ("métriques", "métriques\\me.tʁik\\féminin", ""),             # 词头 + 音标 + 性
    ("pommeaux", "pommeaux\\pɔ.mo\\masculin", ""),
    ("pianistes", "pianistes\\pja.nist\\masculin et féminin identiques", ""),
    ("pyj", "pyj \\piʒ\\ masculin, singulier et pluriel identiques", ""),
    ("surges", "surge\\syʁʒ\\féminin", ""),                       # 泄漏的是单数的头
    ("PVTiste", "Pvtiste\\pe.ve.tist\\masculin et féminin identiques", ""),  # 大小写不同
    ("algéco", "Algeco\\al.ʒe.ko\\masculin", ""),                 # 重音符不同
    ("Collina d'Oro", "Collina d’Oro\\Prononciation ?\\", ""),    # 撇号不同
    ("Wexham Civil parish", "Wexham Civil parish\\Prononciation ?\\", ""),
    ("filer en quenouille", "filer en quenouille \\Prononciation ?\\ intransitif", ""),
    # 头剥掉之后**还有真定义**的，定义一个字不许动
    ("contre-latte", "\\kɔ̃.tʁə.lat\\ Latte qu’on pose perpendiculairement entre deux chevrons.",
     "Latte qu’on pose perpendiculairement entre deux chevrons."),
    ("omnivision", "\\ˈɔm.ni.vi.zjɔ̃\\ Qui voit tout.", "Qui voit tout."),
    ("RNA", "\\Prononciation ?\\masculin* (Couche physique) Raccordement numérique asymétrique.",
     "(Couche physique) Raccordement numérique asymétrique."),
    ("tyndalliser", "\\tɛ̃.da.li.ze\\transitif1ᵉʳ groupe (voir la conjugaison)* Mode de stérilisation.",
     "Mode de stérilisation."),
    ("Paranda", "\\pa.ʁɑ̃.da\\fémininpluriel Genre musical traditionnel des Garifunas.",
     "Genre musical traditionnel des Garifunas."),
    ("pinasse", "pinasse\\pi.nas\\féminin* (Textile) (Désuet) Biambonnée.",
     "(Textile) (Désuet) Biambonnée."),
    ("crabier malgache", "crabier malgache\\kʁa.bje.mal.gaʃ\\masculin Synonyme de crabier blanc",
     "Synonyme de crabier blanc"),
    ("-arde", "\\aʁd\\* Sert à former des mots féminins à valeur péjorative.",
     "Sert à former des mots féminins à valeur péjorative."),
    # 🔴 负控：`\…\` 是**真内容**（讲某个音），前面是一句法语不是词头 —— 一个字不许动
    ("hachement", "Variante de achement le \\h\\ est non étymologique.",
     "Variante de achement le \\h\\ est non étymologique."),
    ("satemisation", "Changement d’un son \\k\\ indo-européen en une affriquée.",
     "Changement d’un son \\k\\ indo-européen en une affriquée."),
    ("alphacisme", "Substitution d’un son vocalique par \\a\\.",
     "Substitution d’un son vocalique par \\a\\."),
    ("6", "Utilisé pour représenter \\si\\ ou \\sis\\ ou \\siz\\.",
     "Utilisé pour représenter \\si\\ ou \\sis\\ ou \\siz\\."),
    ("2", "Utilisé pour représenter les sons \\də\\, \\dœ\\ et \\dø\\.",
     "Utilisé pour représenter les sons \\də\\, \\dœ\\ et \\dø\\."),
    ("zamuco", "Langue amérindienne des Ayorés\\Ayoreo\\Zamuco. Elle est parlée en Bolivie.",
     "Langue amérindienne des Ayorés\\Ayoreo\\Zamuco. Elle est parlée en Bolivie."),
    # 🔴 负控：不传 word 时，**前面非空**的一律不许剥（判不了就别动）
    ("", "métriques\\me.tʁik\\féminin", "métriques\\me.tʁik\\féminin"),
]


def selftest():
    bad = 0
    for src, want in CASES:
        got = clean(src)
        if got != want:
            bad += 1
            print("   🔴 %r\n      期望 %r\n      实得 %r" % (src, want, got))
    for w, src, want in WORD_CASES:
        got = clean(src, w or None)
        if got != want:
            bad += 1
            print("   🔴 [%s] %r\n      期望 %r\n      实得 %r" % (w, src, want, got))
    print("■ 自测 %d 例（其中词条头 %d），红 %d"
          % (len(CASES) + len(WORD_CASES), len(WORD_CASES), bad))
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
