#!/usr/bin/env python3
"""地名族的**手写模式表**：法语句式 → 中文句式 + 槽位。2026-08-22。

═══ 🔴 为什么不用自动拆分 ═══
第一版想让程序自己把句子拆成「骨架 + 参数」，用一条通用正则找最后一个介词。
**实测 35.7% 的"参数"吞进了整个从句**：

    Commune du canton de Saint-Gall en Suisse.
        ⇒ 参数 = "Saint-Gall en Suisse"        ← 吞了 "en Suisse"
    Village et ancienne commune française, située dans le département de la Sarthe
    intégrée dans la commune de Ballon-Saint Mars en janvier 2016.
        ⇒ 参数 = "Sarthe intégrée dans la commune de … en janvier 2016"

而我基于那份脏数据报的「2,830 骨架 / 5,387 地区名」**全部作废**。
⇒ 改成**手写模式**：每条模式自己声明有几个槽、各是什么。
   槽位干净了，送去翻译的才是真正的地区名。

═══ 这张表就是最终产物 ═══
错一条 = 上万条一起错。所以：
  · 每条都对着**真实原句**写（见 docstring 里的样本）
  · **按顺序匹配，长的具体的在前** —— 否则 `Commune française …` 会被泛化模式抢走
  · 匹配不上的**不生成**，退回模型走正常翻译。**宁可缺不可错。**

═══ 槽位的两类 ═══
  `R` = 地区/省/州名 —— 要翻译，全库复用（送模型一次）
  `P` = 地点名（市镇/村）—— 也要翻译，但长尾
中文里 **`{}` 按声明顺序填**。
"""
import re

# 冠词表。🔴 **只在这一处声明**——之前每条模式手抄一遍，
#    canton 那条漏了 `des`（→ 槽值变成 `s Grisons`，159 条），
#    canton 那条还漏过 `du`（→ 瓦莱/提契诺/汝拉 291 条全未命中）。
#    同一个 bug 犯两次 = 判据不该分散在 30 个地方各写一份。
def alt(*words):
    """→ 正则选择支，**按长度降序**。

    🔴 这个函数存在的唯一理由是：手写选择支的顺序错了三次，每次都坏几百条。
       ① 漏 `du`（291 条）② 漏 `des`（620 条）③ `au` 排在 `aux` 前面 ⇒
       `aux Essarts` 里 `au` 先匹配上，槽值变成 `x Essarts`（43 条）。
       正则的选择支是**从左到右first-match**，不是最长匹配 ⇒ 长的必须排前面。
       ⇒ 一律用这个函数生成，不要再手写 `(?:a|ab|abc)`。
    """
    return "(?:%s)" % "|".join(sorted(words, key=len, reverse=True))


DE = alt("de la", "de l’", "de l'", "des", "du", "de", "d’", "d'")
# 「dans + 冠词」同理。漏 `dans les` ⇒ 槽值变成 `s Asturies`（阿斯图里亚斯等 620 条）。
DANS = alt("dans les", "dans le", "dans la", "dans l’", "dans l'")

# (正则, 中文模板, 槽位类型列表)。**顺序即优先级。**
PATTERNS = [
    # ── 法国 ────────────────────────────────────────────────────────────
    # Village et ancienne commune française, située dans le département de la Sarthe
    #   intégrée dans la commune de Ballon-Saint Mars en janvier 2016.
    (r"^(?:(?:Village|Bourg|Hameau|Ville|Localit[ée]) et ancienne commune|Ancienne commune|Commune)"
     r" française,?\s+situ[ée]e?\s+dans le "
     r"d[ée]partement " + DE + r"\s*(.+?)\s+int[ée]gr[ée]e? "
     r"(?:dans|à) la commune " + DE + r"\s*(.+?)(?:\s+en\s+[^,.]+)?\.?$",
     "法国{}省旧市镇，已并入{}", ["R", "P"]),
    # Commune française, située dans le département de la Charente-Maritime.
    (r"^Commune française,?\s*situ[ée]e?\s+dans le d[ée]partement "
     r"" + DE + r"\s*(.+?)\.?$",
     "法国{}省市镇", ["R"]),
    # Commune française du département des Deux-Sèvres.
    (r"^Commune française du d[ée]partement " + DE + r"\s*(.+?)\.?$",
     "法国{}省市镇", ["R"]),
    # ── 德国 ────────────────────────────────────────────────────────────
    # Commune d’Allemagne située dans le district de Haute-Bavière en Bavière.
    (r"^Commune d[’']Allemagne,?\s*situ[ée]e?\s+dans le district " + DE + r"\s*(.+?)"
     r"\s+en\s+(.+?)\.?$",
     "德国{1}州{0}行政区市镇", ["R", "R"]),
    # Commune d’Allemagne, située dans l’arrondissement de Rhin-Hunsrück en Rhénanie-Palatinat.
    (r"^Commune d[’']Allemagne,?\s*situ[ée]e?\s+dans l[’']arrondissement "
     r"" + DE + r"\s*(.+?)\s+en\s+(.+?)\.?$",
     "德国{1}州{0}县市镇", ["R", "R"]),
    # 🔴 泛化模式必须排在**最后** —— 它的 `dans le` 会把
    #    `dans le district de Basse-Franconie en Bavière` 整段吞成一个槽值，
    #    而模型好心地只翻出「下弗兰肯」⇒ 渲染成「德国下弗兰肯**州**市镇」，
    #    可下弗兰肯是巴伐利亚州下面的**行政区**不是州。794 条中招。
    # Commune d’Allemagne, située dans le Bade-Wurtemberg. / … en Bavière.
    (r"^(?:Ville, commune et arrondissement|Ville et commune|Bourg et commune|Ville|Bourg|Commune) "
     r"d[’']Allemagne,?\s*situ[ée]e?\s+"
     r"(?:dans le Land " + DE + r"|" + DANS + r"|en)\s*(.+?)\.?$",
     "德国{}州市镇", ["R"]),
    # ── 西班牙 ──────────────────────────────────────────────────────────
    # Commune d’Espagne, située dans la province de Teruel et la Communauté autonome d’Aragon.
    (r"^Commune d[’']Espagne,?\s*situ[ée]e?\s+dans la province " + DE + r"\s*(.+?)\s+et "
     r"(?:la|l’|l')\s*Communaut[ée] autonome " + DE + r"\s*(.+?)\.?$",
     "西班牙{1}自治区{0}省市镇", ["R", "R"]),
    # Commune d’Espagne située dans la province de Salamanque, en Castille-et-León.
    #   / Village d’Espagne situé dans la province de Teruel, en Aragon.  ← 通名会变，收进槽位
    (r"^(Commune et ville|Ville et commune|Commune|Ville|Village|Bourg|Hameau) "
     r"d[’']Espagne,?\s*situ[ée]e?\s+dans la province " + DE + r"\s*(.+?),?\s+en\s+(.+?)\.?$",
     "西班牙{2}自治区{1}省{0}", ["TYPE", "R", "R"]),
    # Commune d’Espagne, située dans la province et Communauté autonome de Navarre.
    (r"^Commune d[’']Espagne,?\s*situ[ée]e?\s+dans la province et Communaut[ée] autonome "
     r"" + DE + r"\s*(.+?)\.?$",
     "西班牙{}省（自治区）市镇", ["R"]),
    # Commune d’Espagne, située dans la province de Valence et la Communauté valencienne.
    #   🔴 第一版把 `Communauté (.+?)` 做成槽位 ⇒ 抽出来的是**形容词** `valencienne`，
    #      模型老老实实翻成「巴伦西亚」，渲染出来是「西班牙巴伦西亚阿利坎特省市镇」——
    #      缺了「自治区」，读起来像两个并列地名。而且这个「地区名」只有一个值。
    #      ⇒ **闭集只有一个成员的东西不该是槽位**，直接写进中文里。549 条。
    (r"^Commune d[’']Espagne,?\s*situ[ée]e?\s+dans la province " + DE + r"\s*(.+?),?\s+et "
     r"(?:la|l’|l')\s*Communaut[ée] valencienne\.?$",
     "西班牙巴伦西亚自治区{}省市镇", ["R"]),
    (r"^(Commune et ville|Ville et commune|Commune|Ville|Village|Bourg|Hameau) "
     r"d[’']Espagne,?\s*situ[ée]e?\s+dans la province " + DE + r"\s*(.+?)\.?$",
     "西班牙{1}省{0}", ["TYPE", "R"]),
    # Commune du Pays basque espagnol située dans la province de Biscaye.
    (r"^(Commune|Ville|Village|Hameau|Bourg) du Pays basque espagnol situ[ée]e?\s+"
     r"dans la province " + DE + r"\s*(.+?)\.?$",
     "西班牙巴斯克地区{1}省的{0}", ["TYPE", "P"]),
    # Commune du Pays basque espagnol située en Navarre.   ← 纳瓦拉是自治区不是省，不加「省」
    (r"^(Commune|Ville|Village|Hameau|Bourg) du Pays basque espagnol situ[ée]e?\s+"
     r"en\s+(.+?)\.?$",
     "西班牙巴斯克地区{1}的{0}", ["TYPE", "P"]),
    # ── 意大利 ──────────────────────────────────────────────────────────
    # Commune d’Italie de la province de Verbano-Cusio-Ossola dans la région du Piémont.
    (r"^Commune d[’']Italie de la province " + DE + r"\s*(.+?)\s+dans la r[ée]gion "
     r"" + DE + r"\s*(.+?)\.?$",
     "意大利{1}大区{0}省市镇", ["R", "R"]),
    # Commune d’Italie de la ville métropolitaine de Gênes dans la région de Ligurie.
    (r"^Commune d[’']Italie de la ville m[ée]tropolitaine " + DE + r"\s*(.+?)\s+dans la r[ée]gion "
     r"" + DE + r"\s*(.+?)\.?$",
     "意大利{1}大区{0}广域市市镇", ["R", "R"]),
    # Commune d’Italie de l’organisme régional de décentralisation d’Udine dans la région de
    #   Frioul-Vénétie julienne.   ← 2024 年弗留利大区废省改设 EDR，只此一区，215 条
    (r"^Commune d[’']Italie de l[’']organisme r[ée]gional de d[ée]centralisation "
     r"" + DE + r"\s*(.+?)\s+dans la r[ée]gion "
     r"" + DE + r"\s*(.+?)\.?$",
     "意大利{1}大区{0}地区分权机构市镇", ["R", "R"]),
    # Commune d’Italie du libre consortium municipal de Trapani dans la région de Sicile.
    #   ← 西西里 2015 年废省改设「自由市镇联合体」，134 条
    (r"^(?:Commune et ville|Ville et commune|Commune|Ville) d[’']Italie du libre consortium "
     r"municipal " + DE + r"\s*(.+?)\s+dans la r[ée]gion "
     r"" + DE + r"\s*(.+?)\.?$",
     "意大利{1}大区{0}自由市镇联合体市镇", ["R", "R"]),
    # Commune d’Italie de la province de Caserte, en Campanie.  ← 逗号变体
    (r"^Commune d[’']Italie de la province " + DE + r"\s*(.+?),\s*en\s+(.+?)\.?$",
     "意大利{1}大区{0}省市镇", ["R", "R"]),
    (r"^Commune d[’']Italie de la province " + DE + r"\s*(.+?)\.?$",
     "意大利{}省市镇", ["R"]),
    # ── 比利时 ──────────────────────────────────────────────────────────
    # Commune de la province de Liège de la région wallonne de Belgique.
    (r"^(?:Commune et ville|Ville et commune|Commune|Ville) de la province "
     r"" + DE + r"\s*(.+?)\s+de la r[ée]gion wallonne de Belgique\.?$",
     "比利时瓦隆大区{}省市镇", ["R"]),
    (r"^(?:Commune et ville|Ville et commune|Commune|Ville) de la province "
     r"" + DE + r"\s*(.+?)\s+de la r[ée]gion flamande de Belgique\.?$",
     "比利时弗拉芒大区{}省市镇", ["R"]),
    # ── 荷兰 / 英国 / 威尔士 / 瑞士 / 葡萄牙 / 加拿大 ─────────────────────
    # 🔴 下面这些模式**第 1 组是通名**（Hameau/Village/…），第 2 组才是地名。
    #    第一版把槽位类型写成 ["P","TYPE"]（与组顺序相反），于是 `TYPE` 里
    #    收进了 670 个"不同值"—— 它本来只该有 4 个。
    #    ⇒ **槽位类型必须按正则的组顺序声明**，中文里用 {0}/{1} 显式指定位置。
    # Commune et ville des Pays-Bas située dans la province de Groningue.  ← 384 条
    (r"^(Commune et ville|Ville et commune|Commune|Ville|Village|Bourg) des Pays-Bas "
     r"situ[ée]e?\s+dans la province " + DE + r"\s*(.+?)\.?$",
     "荷兰{1}省{0}", ["TYPE", "R"]),
    # Hameau des Pays-Bas situé dans la commune de Echt-Susteren.
    (r"^(Hameau|Village|Ville|Bourg) des Pays-Bas situ[ée]e?\s+dans la commune "
     r"" + DE + r"\s*(.+?)\.?$",
     "荷兰{1}市镇的{0}", ["TYPE", "P"]),
    # Ville d’Angleterre située dans le district de Fenland.
    (r"^(Ville|Village|Bourg|Hameau) d[’']Angleterre situ[ée]e?\s+dans le district "
     r"" + DE + r"\s*(.+?)\.?$",
     "英格兰{1}区的{0}", ["TYPE", "P"]),
    # Village d’Écosse situé dans le district de North Lanarkshire. / … situé dans le Midlothian.
    (r"^(Ville|Village|Bourg|Hameau) d[’']Écosse situ[ée]e?\s+"
     r"(?:dans le district " + DE + r"|" + DANS + r")\s*(.+?)\.?$",
     "苏格兰{1}的{0}", ["TYPE", "P"]),
    # Village du Pays de Galles situé dans l’autorité unitaire de Gwynedd.
    #   / Village du Pays de Galles situé dans le Carmarthenshire.   ← 同一层级两种写法
    #   / Village et communauté du Pays de Galles situé dans …
    (r"^(Hameau|Village et communaut[ée]|Ville et communaut[ée]|Village|Ville|Bourg) "
     r"du Pays de Galles situ[ée]e?\s+"
     r"(?:dans l[’']autorit[ée] unitaire " + DE + r"|" + DANS + r")"
     r"\s*(.+?)\.?$",
     "威尔士{1}的{0}", ["TYPE", "P"]),
    # Commune du canton de Saint-Gall en Suisse. / Commune du canton du Valais en Suisse.
    #   🔴 第一版只写了 `de|d'`，漏掉 `du` ⇒ 瓦莱/提契诺/汝拉三州 291 条全未命中。
    (r"^(?:Ville et commune|Commune|Ville|Village) du canton "
     r"" + DE + r"\s*(.+?)\s+en Suisse\.?$",
     "瑞士{}州市镇", ["R"]),
    # District du canton du Valais en Suisse.  ← 是「区」不是「市镇」，单列
    (r"^District du canton " + DE + r"\s*(.+?)\s+en Suisse\.?$",
     "瑞士{}州行政区", ["R"]),
    (r"^Commune et ville de Suisse\.?$", "瑞士市镇", []),
    # Municipalité portugaise située dans le district de Guarda.
    (r"^Municipalit[ée] portugaise situ[ée]e?\s+dans le district " + DE + r"\s*(.+?)\.?$",
     "葡萄牙{}区市镇", ["R"]),
    # Municipalité canadienne du Québec située dans la MRC de La Nouvelle-Beauce.
    (r"^(?:Municipalit[ée] de (?:paroisse|village|canton) canadienne|"
     r"Municipalit[ée] canadienne|Village canadien|Ville canadienne) "
     r"du Qu[ée]bec situ[ée]e?\s+dans la MRC " + DE + r"\s*(.+?)\.?$",
     "加拿大魁北克省{}地区县市镇", ["R"]),
    # ── 法国（补） ──────────────────────────────────────────────────────
    # Commune française située dans la métropole de Lyon.
    (r"^Commune française,?\s*situ[ée]e?\s+dans (?:la )?m[ée]tropole "
     r"" + DE + r"\s*(.+?)\.?$",
     "法国{}大都会市镇", ["R"]),
    # Commune française, située en Polynésie française. / … en Nouvelle-Calédonie.
    #   🔴 第一版一条正则通吃 `située en X` ⇒ 把 `située en Saône-et-Loire`（省）
    #      也渲染成「法国索恩-卢瓦尔市镇」，**「省」丢了**。海外领地是**闭集**，列出来；
    #      其余一律按省走下一条。
    (r"^Commune française,?\s*situ[ée]e?\s+en\s+((?:Polyn[ée]sie française|Nouvelle-Cal[ée]donie|"
     r"Guadeloupe|Martinique|Guyane|La R[ée]union|Mayotte|Saint-Pierre-et-Miquelon|"
     r"Wallis-et-Futuna|Saint-Martin|Saint-Barth[ée]lemy))\.?$",
     "法国{}市镇", ["R"]),
    (r"^Commune française,?\s*situ[ée]e?\s+en\s+(.+?)\.?$",
     "法国{}省市镇", ["R"]),
    # ── 布基纳法索 ──────────────────────────────────────────────────────
    # Ville de la province de Boulkiemdé de la région du Centre-Ouest au Burkina Faso.
    (r"^(Ville|Village|Commune|Bourg) de la province " + DE + r"\s*(.+?)\s+de la r[ée]gion "
     + DE + r"\s*(.+?)\s+au Burkina Faso\.?$",
     "布基纳法索{2}大区{1}省的{0}", ["TYPE", "R", "R"]),
    # Commune située dans le département du Gard, en France.  ← 国名后置的变体
    (r"^Commune situ[ée]e?\s+dans le d[ée]partement "
     r"" + DE + r"\s*(.+?),?\s+en France\.?$",
     "法国{}省市镇", ["R"]),
    # ── 兜底：裸的「Hameau de X.」 ───────────────────────────────────────
    # 2,210 条，多为瓦莱达奥斯塔的村落，但**法语原文没说国家，我也不加**。
    # 🔴 必须放在**最后**：`(.+?)\.?$` 极宽，放前面会把
    #    `Hameau des Pays-Bas situé dans …` 整句吞成一个槽值。
    #    `situé`/`dans` 是动词与介词，**永不出现在地名里**，所以排除它们是锚点不是形式代理
    #    （区别于 `de/en/et` —— 那些真的出现在 `Territoire de Belfort` 这类真省名里）。
    (r"^(Hameau|Village|Ville|Bourg|Localit[ée]) " + DE + r"\s*"
     r"((?:(?!\bsitu[ée]|\bdans\b).)+?)\.?$",
     "{1}的{0}", ["TYPE", "P"]),
]

TYPE_ZH = {"Hameau": "村落", "Village": "村庄", "Ville": "镇", "Bourg": "集镇",
           "Commune": "市镇", "Localité": "聚落", "Quartier": "街区",
           "Village et communauté": "村庄", "Ville et communauté": "镇",
           "Commune et ville": "市镇", "Ville et commune": "市镇"}
COMPILED = [(re.compile(p, re.I), zh, slots) for p, zh, slots in PATTERNS]


def match(text):
    """→ (中文模板, [(槽位类型, 法语值), …]) 或 None。**匹配不上就返回 None，不猜。**"""
    t = " ".join(text.split())
    for rx, zh, slots in COMPILED:
        m = rx.match(t)
        if not m:
            continue
        vals = list(m.groups())
        if len(vals) != len(slots):
            continue
        return zh, list(zip(slots, vals))
    return None


# 🔴 **槽位有效性的判据不是"看起来脏不脏"，是"我有没有它的中文"。**
#    第一版写了个正则查槽值里有没有 `de/en/et` 这类功能词来判"吞了从句"——
#    **那又是形式代理**，`Territoire de Belfort`（778 条，真的省名「贝尔福地区」）、
#    `Monza et Brianza`（108，真省名）、`Reggio de Calabre`（87）全被误判成脏。
#    ⇒ 正确做法：槽值必须在**已翻译的地区名表**里才渲染；不在就不渲染、退回模型。
#    吞了从句的槽值自然不会在表里 ⇒ **自动落回安全路径，不需要我判断它脏不脏。**


# 从句标记：**动词与分词**。地名里永不出现这些词。
# 🔴 这与我第一版栽掉的那条判据**不是一回事**：那版查的是 `de/en/et` 这类**功能词**，
#    而真省名里就有 —— `Territoire de Belfort`(778)、`Monza et Brianza`(108)。
#    动词不一样，没有哪个市镇叫「…intégrée…」。判据从**词性**出发，不从长短出发。
CLAUSE = re.compile(
    r"\b(int[ée]gr[ée]e?s?|situ[ée]e?s?|rattach[ée]e?s?|cr[ée][ée]e?s?|devenue?s?|"
    r"regroupement|comprenant|form[ée]e?s?|fusionn[ée]e?s?|appartenant|d[ée]pendant)\b", re.I)


# 行政通名。槽值**以这些词开头** ⇒ 说明模式在**错误的层级**上匹配了：
# 泛化模式的 `dans le` 把 `dans le district de Basse-Franconie en Bavière` 整段吞了，
# 模型好心地只翻出「下弗兰肯」，渲染成「德国下弗兰肯州市镇」—— 可它是行政区不是州。
# 🔴 重排模式解决了已知的这几族；这条是**兜底**，防我以后再写出同样的洞。
# 判据合法性：地名本身不会**以小写行政通名开头**（`Île-de-France` 是专名、大写带连字符）。
ADMIN = re.compile(
    r"^(?:la |le |les |l[’']|du |des |de la )?"
    r"(district|arrondissement|province|canton|r[ée]gion|commune|ville|Land|MRC|"
    r"oblast|ra[ïi]on|comt[ée]|county|vo[ïi]vodie|pr[ée]fecture|"
    r"d[ée]partement|libre consortium|organisme|autorit[ée]|communaut[ée]|"
    r"[îi]le|municipalit[ée]|paroisse)"
    # 🔴 后面必须是**空格或结尾**，不能是连字符/撇号。
    #    原来写的是 `\b`，把 `Ville-sur-Ancre`、`Île-d’Aix`、`L’Île-Bouchard` 全判成了
    #    「匹配在错误层级」而整条放弃 —— 那是 104 条**真市镇名**，只是碰巧以通名开头。
    #    法语里 `Ville de X`（通名短语）用空格，`Ville-sur-Ancre`（专名）用连字符。
    r"(?=\s|$)", re.I)


def dirty(v):  # noqa: C901
    """槽值是否吞了从句、或匹配在了错误层级。⇒ 整条放弃、退回模型。**宁可缺不可错。**

    实测：368 个槽值中招，其中 146 个模型照样给了译名 —— 它把 `Maine-et-Loire
    intégrée à la commune de Noyant-Villages` 老老实实翻成「曼恩-卢瓦尔」，
    **「已并入诺扬-维拉日」整段静默消失**，会坏掉 369 条。
    所以「脏值不在译名表里所以自动退回」这条自我安慰**不成立** —— 模型会替我把它填上。
    """
    v = v.strip()
    # 🔴 **空格分隔**的 ` dans `/` près de ` 是从句标记，永不出现在地名里
    #    （法语复合地名用**连字符**：`Saint-Cloud-en-Dunois`、`Le Puy-en-Velay`）。
    #    漏了这条 ⇒ `Jullouville dans la Manche` 整段被当成地名送去翻译，
    #    模型只翻了「瑞卢维尔」，「dans la Manche」静默消失。
    if re.search(r"\s(dans|pr[èe]s|situ|jusqu)\s", " %s " % v, re.I):
        return True
    # 🔴 **地名里永远不含逗号**。逗号 = 吞了同位语从句，而 CLAUSE 那套动词判据够不着它
    #    （`Valence, capitale de la Communauté valencienne` 一个动词都没有，
    #     渲染出来是「西班牙 Valence, capitale de la Communauté valencienne, 的」）。
    #    这是个**按含义**的判据，不是形式代理：法语行政区名从来不用逗号分段。
    if "," in v:
        return True
    return bool(CLAUSE.search(v)) or bool(ADMIN.match(v))


def type_zh(v):
    """通名（TYPE 槽）→ 中文。**不送翻译**：它是闭集，只有 4 个词的量级。
    查不到返回 None ⇒ 调用方应当放弃这条、退回模型（宁可缺不可错）。"""
    return TYPE_ZH.get(" ".join(str(v).split()).capitalize())


def render(zh, filled):
    """filled = [已翻好的中文, …]，按声明顺序填。"""
    if "{0}" in zh or "{1}" in zh:
        return _tidy(zh.format(*filled))
    out = zh
    for v in filled:
        out = out.replace("{}", v, 1)
    return _tidy(out)


# 通名撞车：模板给的通名与译名自带的通名重了。
# `district de South Gloucestershire` ⇒ 译名「南格洛斯特郡」+ 模板「区」= **「郡区」**（101 条）。
# 判据是**闭集对闭集**（模板里出现的通名 × 译名可能的结尾），不是模糊匹配。
_DUP = [("郡区", "郡"), ("区区", "区"), ("省省", "省"), ("州州", "州"), ("市市", "市"),
        ("大区区", "大区"), ("岛区", "岛"), ("郡的", "郡的")]


def _tidy(s):
    for a, b in _DUP:
        s = s.replace(a, b)
    return s
