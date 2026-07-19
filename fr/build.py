"""
法语词典建库：kaikki.org (Wiktextract) JSONL → synapse-dict-fr.sqlite（骨架层）

fr 独立管线，不 import 其他语种、不复用其他语种 schema。产出法语专属 dict 表：
把法语最本质的特征升为一等字段——
  · 动词：aux(助动词 avoir/être)、vgroup(三组变位)、transitivity、pronominal、pp(过去分词)
  · 名词：gender、plural(不规则复数)、invariable
  · 形容词：feminine(阴性形)、plural、invariable

数据权威分工（一种数据一个权威）：
  · 义项/变位/aux/vgroup/gender/plural/feminine/pp = kaikki（确定性，本脚本负责）
  · 中文/缺口 gender·aux·plural·feminine/搭配/兜底 IPA/难度 = 豆包（b_translate.py，只填不造义项）

IPA 策略（法语不造 G2P）：kaikki lemma sounds 76% 优先；**变位形 IPA 从 lemma 的 forms
数组收割**——每个 form 自带 ipa（覆盖 93%），建库时先建 (拼写)→ipa 映射，回填缺 IPA 的词条，
把变位 IPA 从 17%→90%+；仍缺的交豆包兜底。

变位形式(senses 全 form_of/alt_of)作独立词条收录：
  infl 列存中文语法说明(infl_compose 组合)，exchange 存 "0:原形" 反查 lemma，不送豆包。
  真义 lemma 的 translation 留空，交 b_translate.py 豆包补。

用法：python3 build.py            # 建库
      python3 build.py --dump-infl # 导出真实变位 tag 组合样本（供豆包验证措辞）
产物：synapse-dict-fr.sqlite（与本脚本同目录）
"""

import argparse
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path

from infl_compose import compose, COMPOSE_TAGS

HERE = Path(__file__).resolve().parent
JSONL_PATH = HERE / "kaikki.org-dictionary-French.jsonl"
DB_PATH = HERE / "synapse-dict-fr.sqlite"

POS_MAP = {
    "noun": "n", "verb": "v", "adj": "adj", "adv": "adv",
    "pron": "pron", "prep": "prep", "conj": "conj", "det": "det",
    "num": "num", "intj": "intj", "name": "name",
    "prefix": "pref", "suffix": "suf", "phrase": "phr",
    "prep_phrase": "phr", "proverb": "prov", "article": "art",
    "contraction": "contr", "particle": "part", "character": "char",
    "symbol": "sym", "interfix": "interfix", "punct": "punct",
}

# ---- meta 分桶（法语维度）。全 tag 逐个归桶，桶外建库报警（drop-ledger）----
REGIONS = {
    "France", "Belgium", "Switzerland", "Quebec", "Canada", "Louisiana",
    "Acadia", "Africa", "Algeria", "Morocco", "Tunisia", "Wallonia",
    "Haiti", "Réunion", "Paris", "Marseille", "Lyon", "Normandy",
    "Brittany", "Occitania", "Provence", "Aosta-Valley", "Jersey",
    "Northern", "Southern", "Eastern", "Western", "Central",
    "regional", "dialectal", "Old-French", "Middle-French",
    # 补桶（dump 实测长尾地区/方言）
    "North-America", "Europe", "European", "Canadian", "Canadian-French",
    "Rwanda", "Congo", "Antilles", "Luxembourg", "West", "East", "North", "South",
    "Vietnam", "Egyptian", "Alsace", "Lorraine", "Montreal", "Picardy",
    "Newfoundland", "Savoie", "Ontario", "Valais", "Guyana", "Southern-Africa",
    "Ireland", "New-Zealand", "Bugey", "Languedoc", "Fribourg", "Toulouse",
    "Southeastern", "Northeastern", "New-England", "Ancient-Rome", "Roman",
}
REGISTERS = {
    "literary", "archaic", "obsolete", "dated", "historical", "rare",
    "uncommon", "colloquial", "informal", "formal", "familiar", "vulgar",
    "slang", "derogatory", "offensive", "pejorative", "humorous", "ironic",
    "euphemistic", "poetic", "figuratively", "figurative", "neologism",
    "nonstandard", "proscribed", "childish", "endearing", "emphatic",
    "jargon", "slur", "Internet", "misspelling", "pronunciation-spelling",
    "eye-dialect", "hypercorrect", "excessive", "rhetoric", "bureaucratese",
    "mildly", "taboo", "sarcastic", "solemn", "affected", "verlan",
    "Ancient", "Middle", "Middle-Ages", "World-War-I", "vernacular",
}
NUMBER_NOTE = {
    "uncountable", "plural-only", "invariable", "collective",
    "countable", "in-plural", "plural-normally", "singular-only",
}
GENDER_COMMON = {"by-personal-gender", "gender-neutral", "common"}

# 已审阅、确定不进 meta 展示的标签（语法/句法/派生/领域/占位/错误）。
IGNORE_TAGS = {
    "transitive", "intransitive", "ambitransitive", "ditransitive",
    "reflexive", "pronominal", "impersonal", "personal", "auxiliary",
    "reciprocal", "relational", "possessive", "demonstrative",
    "interrogative", "relative", "cardinal", "ordinal", "numeral",
    "contraction", "article", "particle", "negative", "defective",
    "modal", "copulative", "masculine", "feminine", "neuter",
    "form-of", "alt-of", "combined-form", "compound-of",
    "morpheme", "diminutive", "augmentative", "apocopic", "ellipsis",
    "clipping", "acronym", "initialism", "abbreviation",
    "no-gloss", "empty-gloss", "no-plural",
    "attributive", "predicative", "adjectival", "adverbial", "substantive",
    "indeclinable", "in-compounds", "compound", "onomatopoeic", "demonym",
    "letter", "name", "noun", "verb", "adjective", "suffix", "prefix",
    "phrase", "proper-noun", "place", "character", "standard",
    "alternative", "variant", "also", "usually", "often", "sometimes",
    "especially", "including", "possibly", "general", "specifically",
    "broadly", "literally", "metonymically", "chiefly", "mainly",
    "capitalized", "uppercase", "lowercase", "stressed", "unstressed",
    "singular", "plural", "first-person", "second-person", "third-person",
    "present", "past", "future", "imperfect", "historic", "conditional",
    "subjunctive", "indicative", "imperative", "infinitive", "gerund",
    "participle", "error-lua-exec", "error-lua-timeout", "error-unknown-tag",
    "misconstruction", "obscure", "idiomatic", "unknown",
    "traditional", "pronoun", "subjective", "objective", "dative", "accusative",
    "indefinite", "definite", "with-infinitive", "with-subjunctive",
    "disjunctive", "conjunctive", "ergative", "polite", "focus", "continuative",
    "physical", "vocative", "genitive", "nominative", "prepositional",
    "Greek", "Latin", "Latinism", "Christianity", "Judaism", "Catholicism",
    "Ancient-Greek", "Biblical", "Classical", "Modern", "Early", "medieval",
    "Renaissance", "Germanic", "ethnic", "Australia", "US", "UK",
    # 补桶（dump 实测长尾：领域/词源族/宗教/语法·句法/占位）
    "French", "Anglicism", "Norse", "Chinese", "Japanese", "Arabic", "Romanian",
    "Navajo", "Indo-European-studies", "European-Union",
    "Hinduism", "Marxism", "Mormonism", "Sikhism", "Jainism", "Nazism",
    "direct-object", "indirect-object", "with-definite-article", "intensifier",
    "perfect", "diacritic", "passive", "analytic", "causative", "inanimate",
    "absolute", "absolutive", "in-variation", "catenative", "indirect",
    "noun-from-verb", "ablative", "synecdoche", "symbol", "postpositional",
    "abstract", "nominal", "partitive", "short-form", "phrasal", "inclusive",
    "before-vowel", "animate", "determiner", "anterior", "elative", "person",
    "sublative", "material", "mnemonic", "reduplication", "error-misspelling",
    "adverb", "gnomic", "root",
}

# 法语正字法字母（含重音/连字）
FR_ALPHA = "a-zàâäéèêëîïôöùûüÿçœæ"


def unaccent(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s.lower())
    out = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return out.replace("œ", "oe").replace("æ", "ae")


def pick_ipa(sounds):
    fallback = None
    for s in sounds or []:
        ipa = (s.get("ipa") or "").strip()
        if not ipa:
            continue
        if ipa.startswith("/"):
            return ipa
        if fallback is None:
            fallback = ipa
    return fallback


# ---------- 变位形 IPA 收割：从任意条目的 forms 数组建 (拼写)→ipa 映射 ----------
_FORM_JUNK_TAGS = {"table-tags", "inflection-template", "multiword-construction"}
_WORDLIKE = re.compile(f"^[{FR_ALPHA}][{FR_ALPHA}'’ -]*$", re.I)


def harvest_form_ipa(e, form_ipa_map):
    """把 lemma forms 里带 ipa 的真实词形喂进全局映射（首见优先），供变位行回填 IPA。"""
    for fm in e.get("forms") or []:
        tags = fm.get("tags") or []
        if _FORM_JUNK_TAGS & set(tags):
            continue
        ipa = (fm.get("ipa") or "").strip()
        form = (fm.get("form") or "").strip()
        if not ipa or not form or not _WORDLIKE.match(form):
            continue
        key = form.lower()
        if key not in form_ipa_map:
            form_ipa_map[key] = ipa


# ---------- 法语本质字段抽取 ----------

def extract_aux(e):
    """助动词：lemma forms 里的 'avoir + past participle' / 'être + past participle'
    多词构造行判定。返回 avoir/être/both/None。"""
    got = set()
    for fm in e.get("forms") or []:
        f = (fm.get("form") or "").strip()
        if f.startswith("avoir + "):
            got.add("avoir")
        elif f.startswith("être + "):
            got.add("être")
    if got == {"avoir", "être"}:
        return "both"
    if "avoir" in got:
        return "avoir"
    if "être" in got:
        return "être"
    return None


def _present_participle(e):
    """取现在分词/副动词形（allant / finissant），用于判定动词组（-issant → 第2组）。"""
    for fm in e.get("forms") or []:
        tags = set(fm.get("tags") or [])
        if "multiword-construction" in tags:
            continue
        if "participle" in tags and "present" in tags:
            f = (fm.get("form") or "").strip()
            if f:
                return f
        if tags == {"gerund"}:
            f = (fm.get("form") or "").strip()
            if f:
                return f
    return None


def extract_vgroup(e):
    """动词组：aller→3；现在分词 -issant→2（如 finir）；不定式 -er→1；其余→3。"""
    w = (e.get("word") or "").lower()
    if w == "aller":
        return "3"
    pp = _present_participle(e)
    if pp and pp.lower().endswith("issant"):
        return "2"
    if w.endswith("er"):
        return "1"
    if w.endswith(("ir", "re", "oir")):
        return "3"
    return None


def extract_pp(e):
    """过去分词阳性单数（allé / abhorré / pris），复合时态与 être 一致用。"""
    for fm in e.get("forms") or []:
        tags = set(fm.get("tags") or [])
        if "multiword-construction" in tags:
            continue
        if "participle" in tags and "past" in tags \
                and "feminine" not in tags and "plural" not in tags:
            f = (fm.get("form") or "").strip()
            if f and _WORDLIKE.match(f):
                return f
    return None


def extract_gender(e, senses):
    """名词/名称性别：fr-noun head args['1'] + sense tags。返回 m/f/mf/None。"""
    hf = hm = common = False
    for h in e.get("head_templates") or []:
        args = h.get("args") or {}
        for k in ("1", "2", "g", "g2"):
            v = str(args.get(k, "")).strip().lower()
            if v in ("m", "m-p"):
                hm = True
            elif v in ("f", "f-p"):
                hf = True
            elif v in ("mf", "mfbysense", "?"):
                common = True
    for s in senses:
        t = s.get("tags", [])
        if "feminine" in t:
            hf = True
        if "masculine" in t:
            hm = True
        if any(x in t for x in GENDER_COMMON):
            common = True
    if common or (hf and hm):
        return "mf"
    if hf:
        return "f"
    if hm:
        return "m"
    return None


def _form_by_tags(e, want, without=()):
    """取 forms 中 tags ⊇ want 且不含 without 的首个真实词形。"""
    want = set(want)
    without = set(without)
    for fm in e.get("forms") or []:
        tags = set(fm.get("tags") or [])
        if "multiword-construction" in tags or _FORM_JUNK_TAGS & tags:
            continue
        if want <= tags and not (without & tags):
            f = (fm.get("form") or "").strip()
            if f and _WORDLIKE.match(f):
                return f
    return None


def extract_plural(e, word):
    """名词复数形；仅当不规则（≠ 词+s）才收，规则 +s 留空（省列、省噪声）。"""
    pl = _form_by_tags(e, ["plural"], without=["feminine", "masculine"]) \
        or _form_by_tags(e, ["plural"])
    if not pl:
        return None
    if pl.lower() == (word.lower() + "s"):   # 规则复数(+s)，不收
        return None
    if pl.lower() == word.lower():           # 数不变(词尾 -s/-x/-z)，与原词同形，冗余不收
        return None
    return pl


def extract_feminine(e):
    """形容词阴性形（grand→grande）。规则可推者也收：阴性形常改变发音。"""
    return _form_by_tags(e, ["feminine"], without=["plural"])


def is_invariable(e, senses):
    for h in e.get("head_templates") or []:
        args = h.get("args") or {}
        if str(args.get("inv", "")).strip() in ("1", "yes"):
            return True
        exp = (h.get("expansion") or "").lower()
        if "(invariable)" in exp or "(plural invariable)" in exp:
            return True
    for s in senses:
        if "invariable" in (s.get("tags") or []):
            return True
    return False


# 不规则比较级（数量极少、纯记忆，确定性硬编码；豆包不碰这几个）。
# adj: bon→meilleur / mauvais→pire / petit→moindre；adv: bien→mieux / mal→pis。
COMPARATIVE_IRREGULAR = {
    "bon": "meilleur", "mauvais": "pire", "petit": "moindre",
    "bien": "mieux", "mal": "pis",
}


def new_rec(word):
    return {
        "word": word, "spellings": set(), "ipa": None, "pos": set(),
        "aux": None, "vgroup": None, "transitivity": None, "pronominal": 0,
        "pp": None, "gender": None, "plural": None, "feminine": None,
        "invariable": 0, "adj_pos": None, "government": None, "comparative": None,
        "real_gloss": [], "real_meta": [], "real_seen": set(),
        "infl": [], "infl_seen": set(), "bases": [],
        "_trans": set(),
    }


def meta_of_sense(s, pos):
    t = s.get("tags", [])
    m = {"pos": POS_MAP.get(pos, pos)}
    reg = [x for x in t if x in REGIONS]
    if reg:
        m["reg"] = reg
    lex = [x for x in t if x in REGISTERS]
    if lex:
        m["lex"] = lex
    return m


def main(dump_infl=False):
    if not JSONL_PATH.exists():
        raise SystemExit(f"缺少 dump: {JSONL_PATH}")
    print(f"读取: {JSONL_PATH}")

    words = {}
    form_ipa_map = {}            # 变位形 IPA 收割：拼写.lower() → ipa
    total = bad = 0
    KNOWN = (REGIONS | REGISTERS | NUMBER_NOTE | GENDER_COMMON | IGNORE_TAGS
             | set(COMPOSE_TAGS))
    dropped = Counter()
    infl_combos = Counter()

    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                e = json.loads(line)
            except Exception:
                bad += 1
                continue
            if e.get("lang_code") != "fr":
                continue
            word = (e.get("word") or "").strip()
            if not word:
                continue

            harvest_form_ipa(e, form_ipa_map)   # 无论 lemma/变位，都收割其 forms IPA

            key = word.lower()
            rec = words.get(key)
            if rec is None:
                rec = new_rec(word)
                words[key] = rec
            rec["spellings"].add(word)

            pos_raw = e.get("pos", "")
            pos = POS_MAP.get(pos_raw, pos_raw)
            rec["pos"].add(pos)
            ipa = pick_ipa(e.get("sounds"))
            if ipa and not rec["ipa"]:
                rec["ipa"] = ipa

            senses = e.get("senses", [])
            is_affix = pos_raw in ("suffix", "prefix", "infix", "interfix")

            # —— 法语本质字段（按 pos 分流）——
            if pos_raw == "verb":
                a = extract_aux(e)
                if a and not rec["aux"]:
                    rec["aux"] = a
                vg = extract_vgroup(e)
                if vg and not rec["vgroup"]:
                    rec["vgroup"] = vg
                pp = extract_pp(e)
                if pp and not rec["pp"]:
                    rec["pp"] = pp
                if re.match(r"s['’ ]", word) or word.lower().startswith("se "):
                    rec["pronominal"] = 1
                for s in senses:
                    t = s.get("tags", [])
                    if "reflexive" in t or "pronominal" in t:
                        rec["pronominal"] = 1
                    if "transitive" in t:
                        rec["_trans"].add("t")
                    if "intransitive" in t:
                        rec["_trans"].add("i")
                    if "ambitransitive" in t:
                        rec["_trans"].update(("t", "i"))
            elif pos_raw in ("noun", "name"):
                g = extract_gender(e, senses)
                if g and not rec["gender"]:
                    rec["gender"] = g
                pl = extract_plural(e, word)
                if pl and not rec["plural"]:
                    rec["plural"] = pl
                # 名词阴性对应形（acteur→actrice、ami→amie；生物性别配对）
                fem = extract_feminine(e)
                if fem and not rec["feminine"]:
                    rec["feminine"] = fem
                if is_invariable(e, senses):
                    rec["invariable"] = 1
            elif pos_raw == "adj":
                fem = extract_feminine(e)
                if fem and not rec["feminine"]:
                    rec["feminine"] = fem
                pl = extract_plural(e, word)
                if pl and not rec["plural"]:
                    rec["plural"] = pl
                if is_invariable(e, senses):
                    rec["invariable"] = 1
                # 位置 seed：kaikki 极少标（多数交豆包）。postpositional→后置。
                for s in senses:
                    if "postpositional" in (s.get("tags") or []) and not rec["adj_pos"]:
                        rec["adj_pos"] = "post"

            # 不规则比较级（bon→meilleur 等，按词硬编码，与词性无关）
            if word.lower() in COMPARATIVE_IRREGULAR and not rec["comparative"]:
                rec["comparative"] = COMPARATIVE_IRREGULAR[word.lower()]

            # —— 义项 / 变位分流 ——
            for s in senses:
                tags = s.get("tags", [])
                fo = s.get("form_of") or s.get("alt_of")
                is_infl_sense = bool(fo) and not is_affix
                if is_infl_sense:
                    base = (fo[0].get("word") or "").strip() if fo else ""
                    if not base:
                        continue
                    if dump_infl:
                        combo = tuple(sorted(t for t in tags
                                             if t in COMPOSE_TAGS and t != "form-of"))
                        infl_combos[combo] += 1
                    label = compose(tags) or "变位形式"
                    note = f"{base} 的 {label}"
                    if note not in rec["infl_seen"]:
                        rec["infl_seen"].add(note)
                        rec["infl"].append(note)
                    if base not in rec["bases"]:
                        rec["bases"].append(base)
                else:
                    g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
                    if not g or g in rec["real_seen"]:
                        continue
                    rec["real_seen"].add(g)
                    rec["real_gloss"].append(g)
                    rec["real_meta"].append(meta_of_sense(s, pos_raw))
                    for tg in tags:
                        if tg not in KNOWN:
                            dropped[tg] += 1

    # transitivity 收口
    for rec in words.values():
        tr = rec["_trans"]
        if tr == {"t"}:
            rec["transitivity"] = "t"
        elif tr == {"i"}:
            rec["transitivity"] = "i"
        elif tr:
            rec["transitivity"] = "ti"

    if dump_infl:
        out = HERE / "infl_combos.txt"
        with open(out, "w", encoding="utf-8") as fo:
            for combo, n in infl_combos.most_common():
                fo.write(f"{n:7}  {compose(list(combo))!r:40}  {'+'.join(combo)}\n")
        print(f"变位组合 {len(infl_combos)} 种 → {out}（供豆包验证措辞）")
        return

    # 变位 IPA 收割回填：仍缺 IPA 的词条从 forms 映射补
    n_harvest = 0
    for key, rec in words.items():
        if not rec["ipa"]:
            hit = form_ipa_map.get(key)
            if hit:
                rec["ipa"] = hit
                n_harvest += 1

    # 统计
    n_lemma = sum(1 for r in words.values() if r["real_gloss"])
    n_infl = len(words) - n_lemma
    n_ipa = sum(1 for r in words.values() if r["ipa"])
    n_aux = sum(1 for r in words.values() if r["aux"])
    n_gender = sum(1 for r in words.values() if r["gender"])
    n_fem = sum(1 for r in words.values() if r["feminine"])
    n_pp = sum(1 for r in words.values() if r["pp"])
    print(f"总行数 {total} (解析失败 {bad}) → 去重词条 {len(words)}")
    print(f"  真义 lemma {n_lemma} | 纯变位 {n_infl}")
    print(f"  IPA {n_ipa} ({100*n_ipa//max(len(words),1)}%，其中收割回填 {n_harvest})")
    n_cmp = sum(1 for r in words.values() if r["comparative"])
    print(f"  kaikki 抽取：aux {n_aux} | gender {n_gender} | 阴性形(名+形) {n_fem} | 过去分词 {n_pp} | 不规则比较级 {n_cmp}")
    if dropped:
        print(f"  ⚠ 未归桶 tag {len(dropped)} 种（真义义项上，请归类）：")
        for tg, n in dropped.most_common(30):
            print(f"      {n:6} {tg}")
    else:
        print("  ✓ 全部真义 tag 已归桶，无静默丢弃")

    # 写库
    print(f"写入: {DB_PATH}")
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(
        """
        CREATE TABLE dict (
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          word          TEXT NOT NULL,
          word_norm     TEXT NOT NULL,
          ipa           TEXT,
          pos           TEXT,
          is_lemma      INTEGER NOT NULL,
          aux           TEXT,          -- avoir | être | both（复合时态助动词）
          vgroup        TEXT,          -- 1 | 2 | 3（动词组）
          transitivity  TEXT,          -- t | i | ti
          pronominal    INTEGER,       -- 代词式/反身 se laver
          pp            TEXT,          -- 过去分词 participe passé
          gender        TEXT,          -- m | f | mf
          plural        TEXT,          -- 不规则复数（规则 +s 留空）
          feminine      TEXT,          -- 阴性形（形容词 grand→grande；名词 acteur→actrice）
          invariable    INTEGER,       -- 不变形
          adj_pos       TEXT,          -- 形容词位置 pre | post | both（豆包填，kaikki 几乎无）
          government    TEXT,          -- 动词/形容词固定介词支配 如 "à qch"/"de qch"（豆包填）
          comparative   TEXT,          -- 不规则比较级 bon→meilleur（硬编码/豆包）
          level         TEXT,          -- CEFR 难度 A1-C2（豆包填，kaikki 无）
          definition    TEXT,
          translation   TEXT,
          meta          TEXT,
          infl          TEXT,
          exchange      TEXT,
          collocation   TEXT,
          example       TEXT,
          flag          TEXT
        );
        """
    )
    batch = []
    for rec in words.values():
        is_lemma = 1 if (rec["real_gloss"] or (not rec["infl"] and not rec["bases"])) else 0
        definition = "\n".join(rec["real_gloss"]) if rec["real_gloss"] else None
        meta = (json.dumps(rec["real_meta"], ensure_ascii=False)
                if rec["real_gloss"] else None)
        infl = "\n".join(rec["infl"]) if rec["infl"] else None
        exchange = "\n".join(f"0:{b}" for b in rec["bases"]) if rec["bases"] else None
        translation = None if is_lemma else infl
        disp = rec["word"]
        if disp.lower() in rec["spellings"]:
            disp = disp.lower()
        batch.append((
            disp, unaccent(disp), rec["ipa"],
            "/".join(sorted(rec["pos"])) if rec["pos"] else None,
            is_lemma,
            rec["aux"], rec["vgroup"], rec["transitivity"], rec["pronominal"] or None,
            rec["pp"], rec["gender"], rec["plural"], rec["feminine"],
            rec["invariable"] or None, rec["adj_pos"], rec["government"], rec["comparative"],
            definition, translation, meta, infl, exchange,
        ))
    conn.executemany(
        "INSERT INTO dict (word, word_norm, ipa, pos, is_lemma, aux, vgroup, "
        "transitivity, pronominal, pp, gender, plural, feminine, invariable, "
        "adj_pos, government, comparative, "
        "definition, translation, meta, infl, exchange) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        batch,
    )
    conn.commit()
    conn.execute("CREATE INDEX idx_word ON dict(word COLLATE NOCASE)")
    conn.execute("CREATE INDEX idx_norm ON dict(word_norm)")
    conn.commit()
    conn.close()
    print("完成。下一步：b_translate.py 豆包补 lemma 中文/缺口本质字段/兜底 IPA")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-infl", action="store_true",
                    help="导出真实变位 tag 组合样本（供豆包验证 infl 措辞），不建库")
    args = ap.parse_args()
    main(dump_infl=args.dump_infl)
