#!/usr/bin/env python3
"""姓氏 / 名字两族的**手写模式表**。2026-08-23。

承 `geo_patterns.py` 的做法，但这两族**结构简单得多**：没有地名槽位，
唯一要翻的是**语言/国别形容词**（français / néerlandais / anglophone …）。

    Nom de famille.                    → 姓氏                 （14,889 条，一条模式吃掉 84%）
    Nom de famille français.           → 法国姓氏
    Nom de famille d’origine arabe.    → 源自阿拉伯的姓氏
    Prénom féminin.                    → 女子名               （4,017）
    Prénom masculin composé.           → 复合男子名
    Prénom féminin anglais.            → 英国女子名

═══ 槽位只有一类 ═══
  `L` = 语言/国别形容词 —— 要翻译，两族共用（送模型一次）
性别是**闭集**（masculin/féminin/épicène/masculin ou féminin），由 `GENDER_ZH` 解决，不送模型。

🔴 **`L` 必须限定成小写词**。法语里国别形容词一律小写（`français`），
   专名才大写（`France`）—— 这是**词法约定**，不是"看起来像不像"的形式代理。
   不限定的话 `Nom de famille (.+?)\\.` 会把任意长句吞成一个槽值，
   重演 `geo_patterns` 那六次里的第一次。
"""
import re

# 小写起首的形容词，允许连字符与撇号（`nord-américain`、`d’oïl`）
L = r"([a-zà-öø-ÿ][a-zà-öø-ÿ\-’']*)"
DORIG = r"d[’']origine"

GENDER_ZH = {
    "masculin": "男子", "féminin": "女子", "épicène": "男女通用",
    "masculin ou féminin": "男女通用", "féminin ou masculin": "男女通用",
    "mixte": "男女通用",
}
G = r"(masculin ou féminin|féminin ou masculin|masculin|féminin|épicène|mixte)"

# (正则, 中文模板, 槽位类型列表)。**顺序即优先级，长的具体的在前。**
PATTERNS = [
    # ── 姓氏 ────────────────────────────────────────────────────────────
    # Nom de famille français d’origine occitane.
    (r"^Nom de famille " + L + r"\s+" + DORIG + r"\s+" + L + r"\s*\.?$",
     "源自{1}的{0}姓氏", ["L", "L"]),
    # Nom de famille d’origine néerlandaise.
    (r"^Nom de famille " + DORIG + r"\s+" + L + r"\s*\.?$",
     "源自{}的姓氏", ["L"]),
    # Nom de famille croate ou serbe. / … danois ou norvégien.
    (r"^Nom de famille " + L + r"\s+ou\s+" + L + r"\s*\.?$",
     "{0}或{1}姓氏", ["L", "L"]),
    # Nom de famille français attesté en France.
    (r"^Nom de famille " + L + r"\s+attest[ée]\s+en France\s*\.?$",
     "{}姓氏（法国有记录）", ["L"]),
    (r"^Nom de famille attest[ée]\s+en France\s*\.?$",
     "姓氏（法国有记录）", []),
    # Nom de famille composé.
    #   🔴 不加这条也能渲染对（模型把 `composé` 当形容词翻成了「复合」）——**但那是运气**。
    #      `composé` 是构词标记不是国别，让它走 `L` 槽等于把判据交给模型的善意。
    (r"^Nom de famille compos[ée]e?\s*\.?$", "复合姓氏", []),
    # Nom de famille français.
    (r"^Nom de famille " + L + r"\s*\.?$", "{}姓氏", ["L"]),
    # Nom de famille du Nord de la France.
    (r"^Nom de famille du Nord de la France\s*\.?$", "法国北部姓氏", []),
    # Nom de famille. Attesté en France.  /  Nom de famille, attesté en France.
    (r"^Nom de famille\s*[.,]\s*[Aa]ttest[ée]\s+en France\s*\.?$",
     "姓氏（法国有记录）", []),
    # Nom de famille.      ← 14,889 条，占这一族的 84%
    (r"^Nom de famille\s*\.?$", "姓氏", []),
    # ── 名字 ────────────────────────────────────────────────────────────
    # Prénom féminin d’origine anglaise.
    (r"^Pr[ée]nom " + G + r"\s+" + DORIG + r"\s+" + L + r"\s*\.?$",
     "源自{1}的{0}名", ["G", "L"]),
    # Prénom masculin anglais composé.
    (r"^Pr[ée]nom " + G + r"\s+" + L + r"\s+compos[ée]e?\s*\.?$",
     "复合{1}{0}名", ["G", "L"]),
    # Prénom féminin composé.
    (r"^Pr[ée]nom " + G + r"\s+compos[ée]e?\s*\.?$", "复合{}名", ["G"]),
    # Prénom composé masculin.   ← 语序与上面那条相反
    (r"^Pr[ée]nom compos[ée]e?\s+" + G + r"\s*\.?$", "复合{}名", ["G"]),
    # Prénom arabe masculin.     ← 形容词在性别前
    (r"^Pr[ée]nom " + L + r"\s+" + G + r"\s*\.?$", "{0}{1}名", ["L", "G"]),
    # Prénom masculin et féminin.
    (r"^Pr[ée]nom masculin et féminin\s*\.?$", "男女通用名", []),
    # Prénom masculin arabe.
    (r"^Pr[ée]nom " + G + r"\s+" + L + r"\s*\.?$", "{1}{0}名", ["G", "L"]),
    # Prénom féminin.      ← 4,017 条
    (r"^Pr[ée]nom " + G + r"\s*\.?$", "{}名", ["G"]),
    # Prénom.
    (r"^Pr[ée]nom\s*\.?$", "名字", []),
]

COMPILED = [(re.compile(p), zh, slots) for p, zh, slots in PATTERNS]

FAM = re.compile(r"^(Nom de famille|Pr[ée]nom)\b", re.I)


def match(text):
    """→ (中文模板, [(槽位类型, 法语值), …]) 或 None。**匹配不上就返回 None，不猜。**"""
    t = " ".join(text.split())
    # 🔴 只归一**首字母**（`nom de famille français` → `Nom …`），不整体 re.I：
    #    `L` 限定小写正是防止吞长句的锚点，加了 re.I 这个锚点就没了。
    if t[:1].islower():
        t = t[0].upper() + t[1:]
    for rx, zh, slots in COMPILED:
        m = rx.match(t)
        if not m:
            continue
        vals = list(m.groups())
        if len(vals) != len(slots):
            continue
        return zh, list(zip(slots, vals))
    return None


def gender_zh(v):
    """性别是闭集，不送模型。查不到 → 放弃这条。"""
    return GENDER_ZH.get(" ".join(str(v).split()).lower())


def render(zh, filled):
    return zh.format(*filled) if ("{0}" in zh or "{1}" in zh) else _seq(zh, filled)


def _seq(zh, filled):
    out = zh
    for v in filled:
        out = out.replace("{}", v, 1)
    return out
