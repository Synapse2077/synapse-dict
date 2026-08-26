#!/usr/bin/env python3
"""从**法语句子文本**里回收指针型释义的中文。零模型调用。2026-08-24。

═══ 与 `recover_fr_alt_of.py` 的分工 ═══
那个模块吃的是 kaikki 的**结构化 `alt_of` 字段**（已回收 12,753 条）。
本模块处理的是**kaikki 没给结构化字段、只在散文里写了指针**的那批：

    Variante de licou.                            → licou 的异体形式：（马的）笼头
    Synonyme de poireau.                          → poireau 的同义词：韭葱
    Graphie par contrainte typographique de Bonnœil. → Bonnœil 的排印受限写法：法国卡尔瓦多斯省市镇

**目标词的中文来自我们自己的库，一次模型调用都不发。**

═══ 🔴 判据：封闭前缀白名单，锚在句首，长的优先 ═══
第一版我写的是「扫描找介词，介词后面第一个在 dict 里的词就是目标」。
**它有两个洞，靠打印 14 条样本才看见：**

  ① `de` / `la` / `une` **本身就是库里的词形** ⇒ 「目标必须在 dict 里」拦不住功能词
     `Écriture de État avec omission…` 抽出的目标是 **`de`**
  ② 第一个介词接不上就继续往后扫 ⇒ 扫到句子中段去
     `Écriture non-accentuée d’Égypte, fréquente **en raison** de…` → 目标 `raison`
     `Graphie utilisée due **à une** contrainte typographique de vœu pieux.` → 目标 `une`

⇒ 改成与 `recover_fr_alt_of.TPL` 同构：**整条前缀短语（含介词）进白名单**，
   `^` 锚定，按长度倒序匹配，匹配不上就**放弃这条**。白名单是从数据里穷举出来的，
   不是我凭印象列的（`synonyme de` 7,001 / `variante de` 2,355 / …）。

═══ 🔴 内联词义的边界 ═══
`X 的同义词` 这种**元指针**对查词的人零价值（`[[clitic-compound-gloss-defect]]` 那族缺陷）。
所以能内联就内联目标的中文。但**只在目标恰好只有一条中文时才内联** ——
目标是多义词时取第一条 = 桶① 那个「结构上 1:1 推不出语义上同一条」的坑重演。
多义的只给指针，不猜。

用法（在 fr/ 目录下）：
    python3 fixes/recover_text_pointers.py --audit    # 按前缀分组审查，写库前必看
    python3 fixes/recover_text_pointers.py --apply
"""
import argparse
import random
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SRC = "template:pointer"

# 类别 → 中文标签。**这张表就是最终产物：错一条就是上千条一起错。**
LABEL = {
    "syn":   "%s 的同义词",
    "var":   "%s 的异体形式",
    "orth":  "%s 的异体拼写",
    "typo":  "%s 的排印受限写法",
    "old":   "%s 的旧拼写",
    "oldvar": "%s 的古体异体形式",
    "rare":  "%s 的罕用异体",
    "obs":   "%s 的废弃异体",
    "bad":   "%s 的误拼（非规范写法）",
    "abbr":  "%s 的缩写",
    "sigle": "%s 的首字母缩写",
    "acro":  "%s 的首字母缩略词",
    "dimin": "%s 的指小形式",
    "apoc":  "%s 的省尾形式",
    "ell":   "%s 的省略形式",
    "noacc": "%s 的无变音符写法",
}

# 前缀短语（已归一：小写 / 直撇 / 去变音符 / 单空格）→ 类别。
# 🔴 **从数据穷举**，不是凭印象列的。覆盖率见 --audit。
PREFIX = {
    "synonyme de": "syn", "synonyme d'": "syn", "synonyme du": "syn",
    "synonyme des": "syn", "ou synonyme de": "syn", "synonyme, de": "syn",
    "synonyme desuet de": "obs", "synonyme desuet d'": "obs",
    "synonyme ancien de": "old", "synonyme non-normalise de": "var",
    "synonyme savoyard d'": "syn", "synonyme (au canada) de": "syn",
    "variante de": "var", "variante d'": "var", "variante du": "var",
    "variante des": "var", "ou variante de": "var", "ou variante d'": "var",
    "variante, de": "var",
    "variante orthographique de": "orth", "variante orthographique d'": "orth",
    "variante orthographique du": "orth",
    "variante orthographique ancienne de": "old",
    "variante orthographique desuete de": "obs",
    "variante orthographique, parfois rencontree, de": "orth",
    "variante graphique de": "orth", "variante graphique d'": "orth",
    "variante ancienne de": "oldvar", "variante ancienne d'": "oldvar",
    "variante rare de": "rare", "variante rare d'": "rare",
    "variante (rare) de": "rare",
    "variante desuete de": "obs", "variante desuete d'": "obs",
    "variante non-normalisee de": "var",
    "variante (moins courante) de": "rare",
    "variante (contestee) de": "var", "variante (diminutif) de": "dimin",
    "variante typographique de": "typo", "variante typographique d'": "typo",
    "variante typographique fautive de": "bad",
    "variante par contrainte typographique de": "typo",
    "variante par contrainte typographique d'": "typo",
    "variante, dans l' orthographe traditionnelle, de": "orth",
    "orthographe ancienne de": "old", "orthographe ancienne d'": "old",
    "orthographe alternative de": "orth", "orthographe alternative d'": "orth",
    "orthographe par contrainte typographique de": "typo",
    "orthographe traditionnelle de": "old",
    "mauvaise orthographe de": "bad", "mauvaise orthographe d'": "bad",
    "graphie ancienne de": "old", "graphie ancienne d'": "old",
    "graphie par contrainte typographique de": "typo",
    "graphie par contrainte typographique d'": "typo",
    "graphie utilisee due a une contrainte typographique de": "typo",
    "graphie utilisee due a de la contrainte typographique de": "typo",
    "graphie souvent utilisee pour": "typo",
    "graphie erronee de": "bad", "graphie erronee d'": "bad",
    "graphie erronee du mot": "bad",
    "graphie fautive de": "bad", "graphie alternative de": "orth",
    "ecriture de": "noacc", "ecriture d'": "noacc",
    "ecriture fréquente de": "noacc", "ecriture frequente de": "noacc",
    "ecriture non-accentuee de": "noacc", "ecriture non-accentuee d'": "noacc",
    "ecriture par contrainte typographique de": "typo",
    "abreviation de": "abbr", "abreviation d'": "abbr", "abreviation du": "abbr",
    "abreviation des": "abbr", "abreviation, de": "abbr",
    "sigle de": "sigle", "sigle d'": "sigle", "sigle du": "sigle",
    "acronyme de": "acro", "acronyme d'": "acro",
    "diminutif de": "dimin", "diminutif d'": "dimin", "diminutif du": "dimin",
    "apocope de": "apoc", "apocope d'": "apoc",
    "ellipse de": "ell", "ellipse d'": "ell",
}
# 🔴 **连接短语**：这些跟在类别词后面，本身不是目标。
#    漏了它们 ⇒ 冠词/类别词被当成目标：`Synonyme de la lime.` 抽出 `la`、
#    `Variante du verbe délonger.` 抽出 `verbe`、`Sigle de l’Aide sociale…` 抽出 `l`。
#    做法：把「类别词 + 连接短语」的组合也铺进 PREFIX，长的先匹配自然优先。
_TAIL = ["la", "l'", "le", "les", "un", "une",
         "verbe", "mot", "nom", "adjectif", "adverbe", "expression", "locution",
         "le verbe", "le mot", "le nom", "l' adjectif", "l' expression",
         "la locution", "l' expression"]
for _base, _kind in list(PREFIX.items()):
    for _t in _TAIL:
        PREFIX.setdefault("%s %s" % (_base, _t), _kind)
        # `de` + `la` 写成 `de la`，`d'` + `la` 不合法，靠 setdefault 多铺无害

# 目标不许是这些 —— 它们是库里真实词形，但**永远不会是指针的目标**。
STOP = {"la", "le", "les", "l'", "un", "une", "des", "du", "de", "d'", "au", "aux",
        "on", "qui", "que", "ce", "cela", "ça", "il", "elle", "en", "y", "se", "sa",
        "son", "ses", "et", "ou", "a", "à", "in", "e", "s'", "n'", "verbe", "mot",
        "nom", "adjectif", "adverbe", "expression", "locution", "genre", "espèce"}
ORDER = sorted(PREFIX, key=len, reverse=True)     # 长的先匹配

# 目标之后允许出现的字符：句读、括号、引号。除此之外一律判为**截断**并放弃整条。
DELIM = set(".,;:!?()[]«»\"'’“”（）［］、。，；：")

ELIS = re.compile(r"^(d|l|qu|n|j|c|s|m|t)['’′]", re.I)


def nk(s):
    """归一只用于**匹配**，不影响任何输出。"""
    s = s.replace("’", "'").replace("ʼ", "'").replace("′", "'").lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


def split_elision(t):
    """`d’albite` → [`d'`, `albite`]。不切开的话 `d'albite` 整体不在 dict 里，目标就丢了。"""
    out = []
    for x in t.split():
        m = ELIS.match(x)
        if m:
            out.append(m.group(0).replace("’", "'").replace("′", "'"))
            x = x[m.end():]
        if x:
            out.append(x)
    return out


def find(text, word, words):
    """→ (类别, 目标词) 或 None。**前缀必须锚在句首**，目标必须是库里真实词形。"""
    toks = split_elision(" ".join(text.split()))
    # 🔴 **从长到短**。写成从短到长会让 `synonyme de` 先于 `synonyme de la` 命中，
    #    目标落在 `la` 上被 STOP 挡掉，然后整条放弃 —— `Synonyme de la lime.` 就这么丢的。
    #    （docstring 里我写的是"长的优先"，第一版代码没实现它。）
    for i in range(min(len(toks), 12), 0, -1):
        p = nk(" ".join(toks[:i]))
        kind = PREFIX.get(p)
        if kind is None:
            continue
        # 目标 = 紧随其后**最长**的真实词形（多词条目如 `agaric élevé`）
        for j in range(min(len(toks), i + 6), i, -1):
            cand = " ".join(toks[i:j]).strip(",.;:!?»«’'’")
            if not cand or cand not in words or nk(cand) == nk(word):
                continue
            if nk(cand) in STOP:
                continue                      # 功能词永远不是目标
            # 🔴 目标后面必须是**句读或句尾**。实测「后面紧接实词」那 1,210 条里
            #    抽样 18 条**几乎全是截断**（多词目标不在库里 ⇒ 退回第一个词）：
            #    `Ellipse de nervule cubitale.` → `nervule`、
            #    `Synonyme de prunier d’Inde, …` → `prunier`。**宁可缺不可错，整条放弃。**
            rest = " ".join(toks[j:]).lstrip()
            if rest and rest[0] not in DELIM and not rest.startswith("’"):
                continue
            return kind, cand
        return None          # 前缀对上了但目标坐实不了 ⇒ 放弃，**不往后扫**
    return None


def load(con):
    words = {w for (w,) in con.execute("SELECT word FROM dict")}
    # 目标词的中文：**只收恰好一条**的（多义的不内联，见 docstring）
    zh = defaultdict(list)
    for w, t in con.execute("""SELECT d.word, g.text FROM dict d
            JOIN sense s ON s.word_id = d.id
            JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='zh'"""):
        zh[w].append(t)
    single = {w: v[0] for w, v in zh.items() if len(v) == 1}
    return words, single, {w: len(v) for w, v in zh.items()}


def build(con):
    words, single, nsense = load(con)
    rows = con.execute("""
        SELECT s.id, d.word, g.text FROM sense s
        JOIN dict d ON d.id = s.word_id
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
        WHERE z.sense_id IS NULL""").fetchall()
    out, why = [], Counter()
    for sid, w, raw in rows:
        t = " ".join(raw.split())
        r = find(t, w, words)
        if not r:
            why["无前缀或目标坐实不了"] += 1
            continue
        kind, tgt = r
        label = LABEL[kind] % tgt
        meaning = single.get(tgt)
        if meaning:
            zhs = "%s：%s" % (label, meaning)
            why["内联了目标词义"] += 1
        else:
            zhs = label
            why["目标多义或无中文，只给指针"] += 1
        out.append((sid, zhs, kind, t, tgt, nsense.get(tgt, 0)))
    return out, why


def check(out):
    bad = Counter()
    for _s, z, _k, _f, _t, _n in out:
        if "%s" in z or not z.strip():
            bad["模板没填/空串"] += 1
        if len(z) > 120:
            bad["过长(>120字)"] += 1
    ids = [s for s, *_ in out]
    if len(set(ids)) != len(ids):
        bad["sense_id 重复"] = len(ids) - len(set(ids))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--sample", type=int, default=20)
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    out, why = build(con)
    print("■ 可生成 %s 条（零模型调用）" % format(len(out), ","))
    for k, v in why.most_common():
        print("   %-24s %s" % (k, format(v, ",")))

    bad = check(out)
    if bad:
        print("\n🔴 不变量红了，**不写**：%s" % dict(bad))
        return 1
    print("\n✓ 不变量全绿")

    if a.audit:
        g = defaultdict(list)
        for _s, z, kind, fr, _t, _n in out:
            g[kind].append((fr, z))
        print("\n── 按类别分组（%d 类）──" % len(g))
        for kind, rs in sorted(g.items(), key=lambda x: -len(x[1])):
            print("\n【%s 条】%s" % (format(len(rs), ","), LABEL[kind]))
            for fr, z in rs[:3]:
                print("      %-58s → %s" % (fr[:58], z[:44]))
        return 0

    print("\n── 随机 %d 条 ──" % a.sample)
    for sid, z, _k, fr, _t, _n in random.Random(3).sample(out, a.sample):
        print("   %-56s → %s" % (fr[:56], z[:48]))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    with dbtool.session("keep-v3-text-pointer", expect={"#sense_gloss": len(out)}) as s:
        s.executemany(
            "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
            "VALUES (?,'zh','equivalent',0,?,?)",
            [(sid, z, SRC) for sid, z, _k, _f, _t, _n in out])
    print("\n✓ 写入 %s 条 sense_gloss(src='%s')" % (format(len(out), ","), SRC))
    return 0


if __name__ == "__main__":
    sys.exit(main())
