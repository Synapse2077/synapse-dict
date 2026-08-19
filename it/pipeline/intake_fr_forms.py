#!/usr/bin/env python3
"""跨版收词（二）：法语版的意语变形，主体是**代词合体形**。2026-08-16。

═══ 这一轮补的正是 it 与 es 的那道口子 ═══
动词均摊变形 it 13.6 / es 55.6。差的这一族就是代词合体形 ——
es 有 `hablarme` `dámelo` `decírselo`，it 常用词有、**生僻词几乎全缺**。
法语版把意语的变位表穷举生成了，我们缺的 608,636 条里：

    Agglutination（合体形）合计            505,419   83%
      不定式 + 代词        `codificatami`   167,985
      副动词 + 代词        `lontanandogliene` 136,453
      过去分词 + 代词                        177,561
      命令式 + 代词        `recuperalo`      15,683
    常规变形（分词/复数/未完成过去时…）        ~10 万

═══ 🔴 法语版不能照搬英文版那套，两个坑 ═══
① **`form_of` 对合体形指错了**：`codificatami` 的 `form_of` 是 **`mi`**（那个代词），
   不是 `codificare`。照它挂就是把 16.8 万条挂到几个代词底下 —— 灾难。
   真原形只写在法语散文里：「Agglutination du participe présent … **du verbe codificare** avec…」
② **kaikki tags 不带语法信息**：`bee` 的 tags 只有 `['archaic','form-of']`，
   人称/时态全在法语句子里（「Troisième personne du singulier de l'indicatif présent」）。

⇒ 从**法语释义**解析，映射成 kaikki 英文 tag，再交给现成的 `infl_compose.compose()`
  出中文 —— **中文措辞不另写一套**，与库里已有 63 万行保持一致。
  实测 608,636 条里 600,489（98.7%）能干净解析出「原形 + 中文」。

⚠️ `compose()` **会静默丢掉** `archaic`/`obsolete` 这类语域标记，而这批古体很多
   （`bee` 是 `bere` 的古体第三人称单数，标准形是 `beve`）。不补上，读者会以为是现行形式。
   ⇒ 语域标记在本文件里单独追加。

═══ 不收的 8,147 条（记账）═══
    3,014 抠不出原形：`en` `Nord` `Coca-Cola` —— 那是**独立词条**不是变形
    5,133 出不了中文：`SI←Sienne`（省份缩写）`Mai←famille`（姓氏）
                      `krypton←kripton`（异体拼写）—— 归宿是词条层或 `sense_relation`

用法（在 it/ 目录下）：
    python3 pipeline/intake_fr_forms.py
    python3 pipeline/intake_fr_forms.py --apply
    python3 pipeline/intake_fr_forms.py --verify
    python3 pipeline/intake_fr_forms.py --mutate
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool        # noqa: E402
import infl_compose  # noqa: E402
import paths         # noqa: E402
from intake_en_forms import OK, deaccent_inner   # noqa: E402  判据与第一轮共用
from split_case_forms import norm as word_norm   # noqa: E402

DUMP = paths.DATA / "dumps" / "kaikki.org-frwiktionary-Italian.jsonl.gz"
SRC = "fr-edition"

# 法语语法词 → kaikki 英文 tag。顺序无关；命中即累加。
FR2TAG = [
    (r"première personne", "first-person"), (r"deuxième personne", "second-person"),
    (r"troisième personne", "third-person"),
    (r"singulier", "singular"), (r"pluriel", "plural"),
    (r"indicatif présent|présent de l’indicatif", "indicative|present"),
    (r"indicatif imparfait|imparfait de l’indicatif", "indicative|imperfect"),
    (r"passé simple", "indicative|past|historic"),
    (r"futur simple|indicatif futur", "indicative|future"),
    (r"subjonctif présent|présent du subjonctif", "subjunctive|present"),
    (r"subjonctif imparfait|imparfait du subjonctif", "subjunctive|imperfect"),
    (r"conditionnel", "conditional"),
    (r"impératif", "imperative"),
    (r"participe passé", "participle|past"), (r"participe présent", "participle|present"),
    (r"gérondif", "gerund"), (r"infinitif", "infinitive"),
    (r"\bmasculin\b", "masculine"), (r"\bféminin\b", "feminine"),
]
# 语域标记：`compose()` 会丢，这里单独补
REGISTER = [("archaic", "古体"), ("obsolete", "废弃"), ("dated", "旧式"),
            ("rare", "罕用"), ("literary", "文语"), ("poetic", "诗体"),
            ("dialectal", "方言"), ("regional", "方言")]

# ═══ 第二通路：法语版的 `forms[]` ═══
# 词条位要解析法语散文，`forms[]` 却带**正规 kaikki 英文 tags**，可以直接喂 compose()。
# 🔴 但有个方向陷阱：`apiculture` 的 forms[] 里 `apicultura` 标着 `singular` ——
#    `apicultura` 才是原形，`apiculture` 是它的复数。照收就把原形挂成了变形。
#    ⇒ 判据：**词头必须是我们库里的 lemma**（这样 forms[] 才确实是"它的"形式），
#      并排掉裸 `('singular',)`（词元本身通常就是单数，标成单数多半方向反了）。
FORM_EXTRA = {
    ("absolute", "feminine", "superlative"): "绝对最高级阴性",
    ("absolute", "masculine", "superlative"): "绝对最高级阳性",
    ("absolute", "superlative"): "绝对最高级",
    ("feminine",): "阴性形式", ("masculine",): "阳性形式",
}

BASE_VERB = re.compile(r"\bdu verbe\s+([A-Za-zÀ-ÿ'’\-]+)")
BASE_DE = re.compile(r"\bde\s+([A-Za-zÀ-ÿ'’\-]+)\s*\.?\s*$")
AGG = re.compile(r"^Agglutination\b", re.I)

# 🔴 2026-08-17：合体形的法语散文，`avec le pronom` **之后**描述的是**代词**，不是动词形式。
#
#     Agglutination du verbe accintolare avec le pronom personnel masculin singulier lo
#                                                        └──────────────────────────┘
#                                            「阳性单数」说的是代词 lo
#
#    第一版把整句喂进 FR2TAG，于是 `accintolarlo` 标成「**单数**＋代词」（正确是「不定式＋代词」）
#    —— **22,308 条**中招。对照组：`avec le pronom ne`（没有性数词）标对了。
#    ⇒ 取语法 tag 之前先截掉代词那半句。原形仍从全句取（`du verbe X` 在截断点之前）。
#    ⚠️ 同一形状第二次：`context-you-give-leaks-into-output` 记的是"喂给模型的参考上下文
#       漏进了输出"，这里是"喂给解析器的无关文本漏进了标签"。**不给原料才是强约束。**
PRONOUN_HALF = re.compile(r"\s+avec\s+(?:le|la|les|l’|l')\s+pronom.*$", re.I | re.S)


def parse_gloss(gloss, tags):
    """法语释义 + kaikki tags → (原形, 中文语法说明)；解析不出返回 (None, '')。"""
    g = gloss or ""
    m = BASE_VERB.search(g) or BASE_DE.search(g)
    if not m:
        return None, ""
    base = m.group(1)
    g_form = PRONOUN_HALF.sub("", g)          # 只留描述**动词形式**的那半句
    t = sorted({tg for rx, val in FR2TAG if re.search(rx, g_form, re.I) for tg in val.split("|")})
    lab = infl_compose.compose(t)
    if AGG.match(g):
        # 合体形：`compose` 拿不到人称时态时至少是不定式（`codificatami` 那类）
        lab = (lab or "不定式") + "＋代词"
    if not lab:
        return base, ""
    reg = [zh for en, zh in REGISTER if en in (tags or ())]
    return base, lab + ("（%s）" % "、".join(dict.fromkeys(reg)) if reg else "")


def scan(con):
    """→ ({归一词形: (base, pos, 中文说明)}, 统计)。两条通路：词条位 + forms[] 位。"""
    have = {w for (w,) in con.execute("SELECT word FROM dict")}
    have_n = {deaccent_inner(w) for w in have}
    lemma = {w for (w,) in con.execute(
        "SELECT word FROM dict WHERE COALESCE(is_lemma,0)=1")}
    out, st = {}, Counter()
    with gzip.open(DUMP, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("lang_code") != "it":
                continue
            w = d.get("word")
            if not w or not OK.match(w):
                st["形状不是词形"] += 1
                continue
            k = deaccent_inner(w)
            if k in have_n:
                st["库里已有"] += 1
                continue
            if k in out:
                st["本轮已收"] += 1
                continue
            s0 = (d.get("senses") or [{}])[0]
            base, lab = parse_gloss((s0.get("glosses") or [""])[0], s0.get("tags") or [])
            if not base:
                st["🔴 抠不出原形（多半是独立词条，不是变形）"] += 1
                continue
            if not lab:
                st["🔴 出不了中文语法说明（多半是异体/专名）"] += 1
                continue
            if base not in have:
                st["🔴 原形不在库里，挂不上"] += 1
                continue
            out[k] = (base, d.get("pos") or "verb", lab)
            st["✅ 可收（词条位）"] += 1
    # —— 第二遍：forms[] 位 ——
    with gzip.open(DUMP, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("lang_code") != "it":
                continue
            head = d.get("word")
            for fm in (d.get("forms") or []):
                x = fm.get("form")
                if not x or not OK.match(x):
                    continue
                k = deaccent_inner(x)
                if k in have_n or k in out:
                    continue
                tg = tuple(sorted(fm.get("tags") or []))
                if head not in lemma:
                    st["🔴 forms[]：词头不是 lemma（方向存疑，不收）"] += 1
                    continue
                if not tg or {"singular", "plural"} <= set(tg) or tg == ("singular",):
                    st["🔴 forms[]：无 tags / 自相矛盾 / 裸单数，不收"] += 1
                    continue
                lab = infl_compose.compose(list(tg)) or FORM_EXTRA.get(tg, "")
                if not lab:
                    st["🔴 forms[]：标不出中文说明，不收"] += 1
                    continue
                out[k] = (head, d.get("pos") or "noun", lab)
                st["✅ 可收（forms[] 位）"] += 1
    return out, st


def src_ref_of(base, pos, form):
    return "kkform-fr:%s:%s:%s" % (base, pos, form)


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    left, _ = scan(con)
    bad_ref = sum(1 for wid, base, sr in con.execute(
        "SELECT i.word_id, i.base, i.src_ref FROM inflection i WHERE i.src_ref LIKE 'kkform-fr:%'")
        for w in [con.execute("SELECT word FROM dict WHERE id=?", (wid,)).fetchone()[0]]
        if sr.split(":")[1:2] != [base] or sr.split(":")[-1] != w)
    checks = [
        ("🔴 没有还能收却没收的", len(left), 0),
        ("🔴 src_ref 逐字节可复算", bad_ref, 0),
        ("🔴 base_id 指的词形必须等于 base 文本",
         q("SELECT count(*) FROM inflection i JOIN dict d ON d.id=i.base_id "
           "WHERE i.src_ref LIKE 'kkform-fr:%' AND d.word <> i.base"), 0),
        # 🔴 这一条是本步唯一可能造成灾难的：法语版的 `form_of` 对合体形指的是**代词**，
        #    若误用，16.8 万条会挂到 mi/ti/si/lo/la 这几个词底下。
        ("🔴 合体形不许挂到代词底下（法语版 form_of 的坑）",
         q("SELECT count(*) FROM inflection WHERE src_ref LIKE 'kkform-fr:%' "
           "AND label_zh LIKE '%＋代词%' AND base IN "
           "('mi','ti','si','ci','vi','lo','la','li','le','ne','gli')"), 0),
        ("🔴 本步收的词形一律 is_lemma=0",
         q("SELECT count(*) FROM dict d JOIN inflection i ON i.word_id=d.id "
           "WHERE i.src_ref LIKE 'kkform-fr:%' AND COALESCE(d.is_lemma,0)<>0"), 0),
        ("🔴 label_zh 不许为空",
         q("SELECT count(*) FROM inflection WHERE src_ref LIKE 'kkform-fr:%' "
           "AND (label_zh IS NULL OR trim(label_zh)='')"), 0),
        ("词形表里没有重复词形",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-46s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def mutate():
    print("\n═══ 变异验证：法语释义解析 ═══")
    cases = [
        ("合体形的原形取 `du verbe X`，不是 form_of 的代词",
         parse_gloss("Agglutination du participe présent au féminin singulier du verbe "
                     "codificare avec le pronom mi.", []),
         ("codificare", "现在分词阴性单数＋代词")),
        ("普通变形：人称+时态",
         parse_gloss("Troisième personne du singulier de l’indicatif présent de bere.",
                     ["form-of"]),
         ("bere", "陈述式现在时第三人称单数")),
        ("🔴 语域标记不许丢（compose 会静默丢掉）",
         parse_gloss("Troisième personne du singulier de l’indicatif présent de bere.",
                     ["archaic", "form-of"]),
         ("bere", "陈述式现在时第三人称单数（古体）")),
        # 🔴 2026-08-17 逮到的：`avec le pronom` 之后的性数说的是**代词**不是动词形式
        ("🔴 代词的性数不许漏进动词形式的标签",
         parse_gloss("Agglutination du verbe accintolare avec le pronom personnel "
                     "masculin singulier lo (« le »).", []),
         ("accintolare", "不定式＋代词")),
        ("对照组：没有性数词的合体形（第一版就对）",
         parse_gloss("Agglutination du verbe accintolare avec le pronom ne (« en »).", []),
         ("accintolare", "不定式＋代词")),
        ("🔴 截断不许伤到动词自己的性数（在 avec 之前）",
         parse_gloss("Agglutination du participe passé au féminin singulier du verbe "
                     "prendere avec le pronom personnel masculin singulier lo.", []),
         ("prendere", "过去分词阴性单数＋代词")),
        ("复数", parse_gloss("Pluriel de siesta.", []), ("siesta", "复数")),
        ("过去分词阴性复数",
         parse_gloss("Participe passé au féminin pluriel de prendere.", []),
         ("prendere", "过去分词阴性复数")),
        ("🔴 独立词条抠不出原形 ⇒ 不收", parse_gloss("Coca-Cola.", []), (None, "")),
        ("🔴 出不了中文 ⇒ 不收", parse_gloss("Nom de famille.", [])[1], ""),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-44s → %s" % ("✅" if good else "🔴", name, got))
        if not good:
            print("        期望 %s" % (want,))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    got, st = scan(ro)
    for k, v in st.most_common():
        print("   %-42s %11s" % (k, f"{v:,}"))
    lab = Counter(v[2] for v in got.values())
    print("\n■ 可收 %s 个新词形；中文说明分布（前 10）" % f"{len(got):,}")
    for t, n in lab.most_common(10):
        print("   %-30s %s" % (t, f"{n:,}"))
    for k in list(got)[:6]:
        print("   %-26s ← %-16s %s" % (k[:26], got[k][0][:16], got[k][2]))
    if not a.apply or not got:
        ro.close()
        print("\n(未加 --apply，不写库)" if not a.apply else "")
        return 0
    wid_of = dict(ro.execute("SELECT word, id FROM dict"))
    ent_of = {}
    for eid, wid, pos in ro.execute("SELECT id, word_id, pos FROM entry"):
        ent_of.setdefault((wid, pos), eid)
    nxt = ro.execute("SELECT max(id) FROM dict").fetchone()[0] + 1
    ro.close()
    d_rows, i_rows = [], []
    for k in sorted(got):
        base, pos, lab1 = got[k]
        bid = wid_of[base]
        d_rows.append((nxt, k, word_norm(k), 0))
        i_rows.append((nxt, ent_of.get((bid, pos)), base, bid, lab1, None,
                       None, SRC, src_ref_of(base, pos, k)))
        nxt += 1
    with dbtool.session("intake-fr-forms",
                        expect={"__rows__": len(d_rows), "#inflection": len(i_rows)}) as s:
        s.executemany("INSERT INTO dict (id,word,word_norm,is_lemma) VALUES (?,?,?,?)", d_rows)
        s.executemany("INSERT INTO inflection "
                      "(word_id,entry_id,base,base_id,label_zh,desc_en,tags,src,src_ref) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", i_rows)
    print("\n■ 已收 %s 个词形" % f"{len(d_rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
