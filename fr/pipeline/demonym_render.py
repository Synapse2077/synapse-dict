#!/usr/bin/env python3
"""居民 / 关系形容词族的确定性生成。2026-08-24。

    Habitant de Saint-Denis, commune française située dans le département de l’Yonne.
        → 法国约讷省圣但尼市镇的居民
    Relative à Bannes, commune française située dans le département de la Marne.
        → 法国马恩省巴讷市镇的
    Habitante de Watermael-Boitsfort en Belgique.
        → 比利时 Watermael-Boitsfort 的女居民   ← 非法国的暂无音译表，退回原名

═══ 🔴 我在这里做错过一次判断 ═══
第一版我提议**不翻市镇名**、直接保留法语原名，列了三条理由。用户驳回：
「不要为了省 token 而省，该花花，目的都是质量为本」。

复盘：三条里只有「这个决定可逆」是真的。
**「保留原名对查词的人更有用」是我编的** —— 这是给中文用户的词典，
条目里夹着 `Saint-Cloud` 就是半成品。我真正的理由是「25,682 个音译我核不完」，
那是**我的验收能力问题，不是质量判断**，而我把它包装成了产品决策。
⇒ **当我给一个决定列了三条理由，先挑出哪条是真的。**

现在：市镇名走 `pipeline/place_translate.py`（翻一次、全库复用），
**模型留空的退回法语原名**（比空着强，也比猜强）。
省名（département）复用地名族那轮翻的槽值，覆盖 97.8%。

═══ 三条放弃规则 ═══
  ① 句子匹配不上模式
  ② 省名/国名不在已有的中文表里（`en Moselle` 这种**省当国家用**的一律放弃，
     不硬按国家渲染）
  ③ 市镇名为空或含从句动词

用法（在 fr/ 目录下）：
    python3 pipeline/demonym_render.py --audit
    python3 pipeline/demonym_render.py --apply
"""
import argparse
import io
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool                                   # noqa: E402
import paths                                    # noqa: E402
from pipeline.geo_patterns import DE, alt, dirty   # noqa: E402

SRC = "template:demonym"
GEO_SLOT = paths.WORK / "geo" / "slot_zh.jsonl"
PLACE_SLOT = paths.WORK / "geo" / "place_zh.jsonl"

# 🔴 「Habitant **de/de la/des/du/aux** X」的介词表。这张表把我坑了三次：
#    ① 第一版手抄成 `(?:de|à|au|aux|d’|d')` —— **漏了 `des`/`du`/`de la`**，
#       `Habitant des Bordes` 的地名被切成 `s Bordes`（422 个槽值污染、720 条渲染出错）。
#       教训当时写的是「抽了常量就要复用」，但我**在这里又手抄了一份窄的**。
#    ② 于是这次直接 `from geo_patterns import DE`，**不留第二份**。
#    ③ 还有一个更隐蔽的：`au` 排在 `aux` 前面 ⇒ `aux Essarts` 被 `au` 先吃掉，
#       槽值成了 `x Essarts`（43 条）。⇒ 选择支一律由 `alt()` 按长度降序生成。
A = alt(DE, "à", "au", "aux")
WHO = r"(Habitante|Habitant|Relative|Relatif)"
# 结尾常挂一句 `, en France` / `, en Alsace` —— 不吃掉的话省名槽会带着它，
# 于是 `Seine-Maritime, en France` 查不到中文，整条白丢。
# 🔴 省名槽后面允许挂两种尾巴，**两种都不进槽值**：
#   `, en Belgique`（国家）—— 原来就有
#   `, ou à ses habitants` / `, ou aux Mortuaciens` —— **原来没有，695 条因此整条落到模型那边**，
#      因为 `(.+?)` 非贪婪匹配到 `\.?$` 时把 `Seine-et-Marne, ou à ses habitants` 整段当成了省名。
TAIL = (r"(?:,?\s+en\s+[A-ZÀ-Ý][^,.]*)?"
        # ⚠️ `[àa]ux?` 是错的 —— 它**要求有 `u`**，单独的 `à` 匹配不上，
        #    `, ou à ses habitants`（这一族的绝大多数）全漏。写成显式三选一。
        r"(?:,?\s+ou\s+(?:aux|au|à)\s+[^.]*?)?")

P_DEP = re.compile(
    r"^" + WHO + r" " + A + r"\s*(.+?), (?:une |la |le )?commune française,?\s*"
    r"situ[ée]e?\s+dans le d[ée]partement " + DE + r"\s*(.+?)" + TAIL + r"\.?$")
P_DEP2 = re.compile(
    r"^" + WHO + r" " + A + r"\s*(.+?), (?:une |la |le )?commune " + DE + r"\s*(.+?)"
    + TAIL + r"\.?$")
P_CTY = re.compile(r"^" + WHO + r" " + A + r"\s*(.+?)\s+en\s+(.+?)\.?$")

WHO_ZH = {"Habitant": "居民", "Habitante": "女居民", "Relatif": "", "Relative": ""}

# 🔴 国家/地区是**闭集，手写**。不在表里的一律放弃 —— 那 255 个「国家槽」里混着
#    `est originaire`（句子被切坏）和 `Moselle`（法国的省，不是国家），
#    按国家渲染就错了。
COUNTRY_ZH = {
    "Belgique": "比利时", "France": "法国", "Suisse": "瑞士", "Italie": "意大利",
    "Espagne": "西班牙", "Allemagne": "德国", "Grèce": "希腊", "Inde": "印度",
    "Portugal": "葡萄牙", "Roumanie": "罗马尼亚", "Pologne": "波兰",
    "Russie": "俄罗斯", "Turquie": "土耳其", "Chine": "中国", "Japon": "日本",
    "Autriche": "奥地利", "Hongrie": "匈牙利", "Croatie": "克罗地亚",
    "Serbie": "塞尔维亚", "Slovénie": "斯洛文尼亚", "Bulgarie": "保加利亚",
    "Ukraine": "乌克兰", "Norvège": "挪威", "Suède": "瑞典", "Finlande": "芬兰",
    "Danemark": "丹麦", "Irlande": "爱尔兰", "Écosse": "苏格兰",
    "Angleterre": "英格兰", "Pays de Galles": "威尔士", "Tunisie": "突尼斯",
    "Algérie": "阿尔及利亚", "Maroc": "摩洛哥", "Égypte": "埃及", "Iran": "伊朗",
    "Israël": "以色列", "Liban": "黎巴嫩", "Syrie": "叙利亚", "Brésil": "巴西",
    "Argentine": "阿根廷", "Mexique": "墨西哥", "Colombie": "哥伦比亚",
    "Haïti": "海地", "Sénégal": "塞内加尔", "Mali": "马里", "Bénin": "贝宁",
    "Côte d’Ivoire": "科特迪瓦", "Cameroun": "喀麦隆", "Madagascar": "马达加斯加",
    "Nouvelle-Calédonie": "新喀里多尼亚", "Polynésie française": "法属波利尼西亚",
    "Guadeloupe": "瓜德罗普", "Martinique": "马提尼克", "Guyane": "圭亚那",
    "Corse": "科西嘉", "Sardaigne": "撒丁岛", "Sicile": "西西里",
}


def dep_zh():
    """省名中文 —— **复用地名族那轮翻的槽值**，不重新翻。"""
    t = {}
    for ln in io.open(GEO_SLOT, encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("zh") and not dirty(o["fr"]):
            t.setdefault(o["fr"], o["zh"])
    return t


# 🔴 **望文生义规则**（GB/T 17693.2 正文硬性规定）：
#    「"东""南""西"出现在地名**开头**时，用"栋""楠""锡"译写；
#      "海"出现在**结尾**时，用"亥"译写」。
#    实测模型给的 26,470 个译名里 **252 个违规**（`Siran`→西朗 该锡朗、
#    `Nantes-en-Ratier`→南特… 该楠特），影响 745 次填充。
#    这条是**可全量核、可确定性修**的，不必送模型返工。
_HEAD_FIX = {"东": "栋", "南": "楠", "西": "锡"}
_TAIL_FIX = {"海": "亥"}


def fix_wangwen(z):
    """按标准修掉望文生义用字。"""
    if not z:
        return z
    if z[0] in _HEAD_FIX:
        z = _HEAD_FIX[z[0]] + z[1:]
    if z[-1] in _TAIL_FIX:
        z = z[:-1] + _TAIL_FIX[z[-1]]
    return z


def place_zh():
    """市镇名中文。**留空的不收** —— 渲染时退回法语原名。"""
    t = {}
    if not PLACE_SLOT.exists():
        return t
    for ln in io.open(PLACE_SLOT, encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("zh"):
            t.setdefault(o["fr"], fix_wangwen(o["zh"]))
    return t


def place_ok(x):
    """市镇名的可用性。**保留法语原名**，只挡明显不是名字的东西。"""
    x = x.strip()
    return bool(x) and len(x) <= 60 and not dirty(x) and "(" not in x[:1]


_ART = re.compile(r"^(?:La |Le |Les |L[’'])")


def dep_lookup(dz, dep):
    """省名查中文。⚠️ 海外省在源文里**带定冠词**（`dans le département de La Réunion`），
    而省表里存的是 `Réunion` —— 71 条因此整条落到模型那边。去冠词再查一次。"""
    return dz.get(dep) or dz.get(_ART.sub("", dep))


def render_one(t, dz, pz):
    """→ 中文 或 None。**匹配不上、省名查不到中文，一律放弃。**
    市镇名查不到 ⇒ **退回法语原名**，不放弃整条（有省名就已经能区分同名市镇了）。"""
    m = P_DEP.match(t) or P_DEP2.match(t)
    if m:
        who, place, dep = m.group(1), m.group(2).strip(), m.group(3).strip()
        z = dep_lookup(dz, dep)
        if not z or not place_ok(place):
            return None
        return "法国%s省%s市镇的%s" % (z, pz.get(place, " %s " % place), WHO_ZH[who])
    m = P_CTY.match(t)
    if m:
        who, place, cty = m.group(1), m.group(2).strip(), m.group(3).strip()
        z = COUNTRY_ZH.get(cty)
        if not z or not place_ok(place):
            return None
        return "%s%s的%s" % (z, pz.get(place, " %s " % place), WHO_ZH[who])
    return None


def build(con, rebuild=False):
    """rebuild=True 时把**本模块已写过的行也算进来**（重建用）。

    🔴 不重建的话，修好的规则只作用于剩下没中文的那批 ——
       已落库的 84,994 条会带着旧 bug 留在库里。
    """
    dz, pz = dep_zh(), place_zh()
    cond = ("WHERE z.sense_id IS NULL OR z.src='%s'" % SRC) if rebuild \
        else "WHERE z.sense_id IS NULL"
    rows = con.execute("""
        SELECT s.id, g.text FROM sense s
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
        """ + cond).fetchall()
    out, why = [], Counter()
    for sid, raw in rows:
        t = " ".join(raw.split())
        if not t.startswith(("Habitant", "Relatif", "Relative")):
            why["非本族"] += 1
            continue
        z = render_one(t, dz, pz)
        if not z:
            why["放弃（无模式或槽值无中文）"] += 1
            continue
        out.append((sid, z, t))
    return out, why


def check(out):
    bad = Counter()
    for _s, z, _f in out:
        if not z.strip() or "%" in z:
            bad["空串/模板没填"] += 1
        if len(z) > 90:
            bad["过长"] += 1
    ids = [s for s, _z, _f in out]
    if len(set(ids)) != len(ids):
        bad["sense_id 重复"] = len(ids) - len(set(ids))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--rebuild", action="store_true",
                    help="连同已写过的行一起重建（修了规则之后用）")
    ap.add_argument("--sample", type=int, default=20)
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    out, why = build(con, a.rebuild)
    fam = sum(why.values()) + len(out) - why["非本族"]
    fb = sum(1 for _s, z, _f in out if re.search(r" [A-Za-zÀ-ÿ]", z))
    print("■ 居民/关系族 %s 条 ⇒ 生成 %s（%.1f%%）"
          % (format(fam, ","), format(len(out), ","), 100.0 * len(out) / fam))
    print("   放弃 %s；其中 %s 条市镇名无音译、退回法语原名"
          % (format(why["放弃（无模式或槽值无中文）"], ","), format(fb, ",")))

    bad = check(out)
    if bad:
        print("\n🔴 不变量红了，**不写**：%s" % dict(bad))
        return 1
    print("✓ 不变量全绿")

    if a.audit:
        g = defaultdict(list)
        for _s, z, fr in out:
            key = re.sub(r"[A-ZÀ-Ýa-zà-ÿ][\w’'\-]*", "§", fr)[:60]
            g[key].append((fr, z))
        print("\n── 按法语形状分组（top 12）──")
        for k, rs in sorted(g.items(), key=lambda x: -len(x[1]))[:12]:
            print("\n【%s 条】" % format(len(rs), ","))
            for fr, z in rs[:2]:
                print("      %-70s → %s" % (fr[:70], z))
        return 0

    print("\n── 随机 %d 条 ──" % a.sample)
    for _s, z, fr in random.Random(9).sample(out, a.sample):
        print("   %-72s → %s" % (fr[:72], z))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    old = con.execute("SELECT count(*) FROM sense_gloss WHERE src=?", (SRC,)).fetchone()[0]
    delta = len(out) - (old if a.rebuild else 0)
    with dbtool.session("keep-v3-demonym", expect={"#sense_gloss": delta}) as s:
        if a.rebuild:
            s.execute("DELETE FROM sense_gloss WHERE src=?", (SRC,))
        s.executemany(
            "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
            "VALUES (?,'zh','equivalent',0,?,?)",
            [(sid, z, SRC) for sid, z, _f in out])
    if a.rebuild:
        print("   （重建：删 %s 条旧的，写 %s 条新的，净 %+d）"
              % (format(old, ","), format(len(out), ","), delta))
    print("\n✓ 写入 %s 条 sense_gloss(src='%s')" % (format(len(out), ","), SRC))
    return 0


if __name__ == "__main__":
    sys.exit(main())
