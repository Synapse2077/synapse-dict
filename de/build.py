"""
德语词典建库：kaikki.org (Wiktextract) JSONL → synapse-dict-de.sqlite（骨架层）

de 独立管线，不 import 其他语种、不复用其他语种 schema。产出德语专属 dict 表，
把德语最本质的特征升为一等字段——
  · 名词：gender(三性 der/die/das)、genitive(属格单数)、plural(复数，全收)
  · 动词：aux(haben/sein)、praeteritum+partizip2(三基本形式)、vclass(强/弱/混合[-ablaut类])、
          separable+sep_prefix(可分动词)、reflexive(sich)
  · 形容词：comparative、superlative

数据权威分工（一种数据一个权威）：
  · 义项/变位/gender/genitive/plural/aux/三基本形式/vclass/separable = kaikki（确定性，本脚本）
  · 中文/缺口 gender·genitive·plural·aux/搭配/兜底 IPA/难度 = 豆包（b_translate.py，只填不造义项）

IPA 策略（德语不造 G2P）：kaikki lemma sounds 23% 优先；变位形 IPA 无法从 forms 收割
（德语 forms 含 ipa=0%，与法语 93% 相反），仍缺的交豆包兜底单音。

德语特殊处理：
  · **word 保留原大小写**（名词首字母大写＝德语本质，sie 她 vs Sie 您靠大小写区分），不 lowercase。
  · word_norm：小写 + ä→ae ö→oe ü→ue ß→ss，支持无变音检索。
  · 变位/变格形（senses 全 form_of）作独立词条；infl 存中文语法说明，exchange 存 "0:原形"。

用法：python3 build.py            # 建库
      python3 build.py --dump-infl # 导出真实变位 tag 组合样本（供豆包验证措辞）
产物：synapse-dict-de.sqlite（与本脚本同目录）
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
JSONL_PATH = HERE / "kaikki.org-dictionary-German.jsonl"
DB_PATH = HERE / "synapse-dict-de.sqlite"

POS_MAP = {
    "noun": "n", "verb": "v", "adj": "adj", "adv": "adv",
    "pron": "pron", "prep": "prep", "conj": "conj", "det": "det",
    "num": "num", "intj": "intj", "name": "name",
    "prefix": "pref", "suffix": "suf", "phrase": "phr",
    "prep_phrase": "phr", "proverb": "prov", "article": "art",
    "contraction": "contr", "particle": "part", "character": "char",
    "symbol": "sym", "interfix": "interfix", "punct": "punct",
}

# ---- meta 分桶（德语维度）。全 tag 逐个归桶，桶外建库报警（drop-ledger）----
REGIONS = {
    "Germany", "Austria", "Switzerland", "Liechtenstein", "Luxembourg",
    "Belgium", "Namibia", "South-Tyrol", "Bavaria", "Berlin", "Berlinisch",
    "Saxony", "Swabia", "Swabian", "Franconia", "Rhineland", "Ruhr", "Ruhrdeutsch",
    "Westphalia", "Hesse", "Palatinate", "Alemannic", "Low-German", "High-German",
    "Upper-German", "Central-German", "Northern-German", "Southern-German",
    "Eastern-German", "Western-German", "Middle-West-German", "northern",
    "southern", "eastern", "western", "central", "regional", "dialectal",
    "Austrian", "Swiss", "German", "Viennese", "Vienna", "Tyrol", "Carinthia",
    "Styria", "Vorarlberg", "Cologne", "Hamburg", "Saxon", "Silesia",
    "Old-High-German", "Middle-High-German", "Yiddish", "Pennsylvania",
    "GDR", "DDR", "West-Germany", "East-Germany",
    # 补桶（dump 实测长尾地区/方言）
    "Southern-Germany", "Northern-Germany", "southern-Germany", "East", "West",
    "Eastern", "Northern", "Southern", "Central", "Ruhrgebiet", "Southwestern",
    "Northwestern", "Northeastern", "Southeastern", "South-Africa", "Australia",
    "Texas", "UK", "US", "Bohemia", "Alsace", "Münsterland", "Palatine",
    "Berlin-Brandenburg", "Basel", "Northwest-German", "Iran", "Grenadian",
    "Schleswig-Holstein", "Ireland", "New-Zealand", "Moravia", "Africa",
    "Russia", "Bavarian", "Alsatian", "Europe", "European", "Western",
    "South", "Egyptian",
}
REGISTERS = {
    "literary", "archaic", "obsolete", "dated", "historical", "historic", "rare",
    "uncommon", "colloquial", "informal", "formal", "familiar", "vulgar",
    "slang", "derogatory", "offensive", "pejorative", "humorous", "ironic",
    "euphemistic", "poetic", "figuratively", "figurative", "neologism",
    "nonstandard", "proscribed", "childish", "endearing", "emphatic",
    "jargon", "slur", "Internet", "misspelling", "pronunciation-spelling",
    "eye-dialect", "hypercorrect", "excessive", "rhetoric", "bureaucratese",
    "mildly", "taboo", "sarcastic", "solemn", "affected", "elevated",
    "now", "originally", "chiefly", "especially", "sometimes", "often",
    "standard", "colloquially", "technical", "childish",
    # 补桶（dump 实测长尾语用/语域/年代）
    "strict-sense", "non-scientific", "metaphoric", "exaggerated", "affective",
    "impolite", "term-of-address", "honorific", "polite", "special",
    "World-War-I", "Medieval", "Middle-Ages", "Middle", "modern",
    "Ancient-Rome", "Roman", "Greco-Roman", "retronym", "nonce-word",
    "hard", "natural",
}
NUMBER_NOTE = {
    "uncountable", "plural-only", "invariable", "collective", "singular-only",
    "countable", "in-plural", "plural-normally", "no-plural", "singulare-tantum",
    "plurale-tantum", "usually-uncountable",
}
GENDER_COMMON = {"by-personal-gender", "gender-neutral", "common"}

# 已审阅、确定不进 meta 展示的标签（语法/句法/派生/领域/占位/错误）。
IGNORE_TAGS = {
    "transitive", "intransitive", "ambitransitive", "ditransitive",
    "reflexive", "pronominal", "impersonal", "personal", "auxiliary",
    "reciprocal", "relational", "possessive", "demonstrative",
    "interrogative", "relative", "cardinal", "ordinal", "numeral",
    "contraction", "article", "particle", "negative", "defective",
    "modal", "copulative", "masculine", "feminine", "neuter", "common-gender",
    "form-of", "alt-of", "combined-form", "compound-of",
    "morpheme", "diminutive", "augmentative", "apocopic", "ellipsis",
    "clipping", "acronym", "initialism", "abbreviation",
    "no-gloss", "empty-gloss",
    "attributive", "predicative", "adjectival", "adverbial", "substantive",
    "indeclinable", "in-compounds", "compound", "onomatopoeic", "demonym",
    "letter", "name", "noun", "verb", "adjective", "suffix", "prefix",
    "phrase", "proper-noun", "place", "character", "separable", "inseparable",
    "alternative", "variant", "also", "usually", "including", "possibly",
    "general", "specifically", "broadly", "literally", "metonymically", "mainly",
    "capitalized", "uppercase", "lowercase", "stressed", "unstressed",
    "singular", "plural", "first-person", "second-person", "third-person",
    "present", "past", "future", "future-i", "future-ii", "preterite",
    "imperfect", "perfect", "pluperfect", "conditional",
    "subjunctive", "subjunctive-i", "subjunctive-ii", "indicative",
    "imperative", "infinitive", "infinitive-zu", "gerund", "participle",
    "strong", "weak", "mixed", "class", "irregular", "ablaut",
    "nominative", "genitive", "dative", "accusative", "vocative",
    "definite", "indefinite", "without-article", "includes-article",
    "table-tags", "inflection-template", "multiword-construction",
    "error-lua-exec", "error-lua-timeout", "error-unknown-tag",
    "misconstruction", "obscure", "idiomatic", "unknown", "traditional",
    "pronoun", "subjective", "objective", "with-infinitive", "with-genitive",
    "with-dative", "with-accusative", "with-preposition", "prepositional",
    "Latin", "Latinism", "Greek", "Christianity", "Judaism", "Catholicism",
    "Anglicism", "Gallicism", "biblical", "Biblical", "ethnic",
    "diacritic", "passive", "analytic", "causative", "inanimate", "animate",
    "absolute", "abstract", "nominal", "partitive", "short-form", "long-form",
    "before-vowel", "determiner", "person", "material", "mnemonic",
    "reduplication", "adverb", "root", "postpositional", "intensifier",
    "direct-object", "indirect-object", "predicate", "comparable",
    "comparative", "superlative", "positive", "degree",
    # 补桶（dump 实测长尾：形态/句法/构词/时体/占位）
    "not-comparable", "no-predicative-form", "no-comparative", "uninflected",
    "no-genitive", "no-past", "no-third-person-singular-present",
    "preterite-present", "semelfactive", "subordinating", "coordinating",
    "conjunctive", "disjunctive", "with-definite-article", "with-von",
    "with-negation", "temporal", "physical", "ergative", "absolutive", "stative",
    "egressive", "locative", "without-noun", "repeated", "prospective",
    "inflected", "supine", "dual", "ablative", "continuative", "declinable",
    "potential", "optative", "noun-from-verb", "inchoative", "iterative",
    "durative", "romanization", "surname", "interjection", "specific",
    "counterfactual", "hypothetical",
    "class-1", "class-2", "class-3", "class-4", "class-5", "class-6", "class-7",
    # 领域/宗教/族群/词源
    "Nazism", "Marxism", "Norse", "Germanic", "Hinduism", "Jainism", "Sikhism",
    "Sunni", "Shia", "Christian", "European-Union", "Indo-European-studies",
    "Chinese", "Estonian", "Armenian", "Arabic", "French",
}

# 德语正字法字母（含变音/eszett）。词形匹配须含大写——名词首字母大写，
# 属格/复数等著录形常以大写开头（Hauses、Häuser）。
DE_ALPHA = "A-Za-zÄÖÜäöüßÁÀÂÉÈÊËÍÌÎÓÒÔÚÙÛÑÇáàâéèêëíìîóòôúùûñç"

# 不规则形容词/副词比较级（少数纯记忆，确定性硬编码兜底）。
COMPARATIVE_IRREGULAR = {
    "gut": ("besser", "am besten"),
    "viel": ("mehr", "am meisten"),
    "hoch": ("höher", "am höchsten"),
    "nah": ("näher", "am nächsten"),
    "nahe": ("näher", "am nächsten"),
    "gern": ("lieber", "am liebsten"),
    "gerne": ("lieber", "am liebsten"),
    "groß": ("größer", "am größten"),
    "bald": ("eher", "am ehesten"),
}


def norm_de(s: str) -> str:
    s = s.lower()
    s = (s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
         .replace("ß", "ss"))
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


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


# ---------- 德语本质字段抽取（主要解析 head_templates expansion）----------

def _de_head(e, name):
    """取指定 name 的 head_template expansion（首个）。"""
    for h in e.get("head_templates") or []:
        if h.get("name") == name:
            return h.get("expansion") or ""
    return ""


_WORD_RE = f"[{DE_ALPHA}][{DE_ALPHA}\\-]*"


def extract_noun(e, word, senses):
    """名词：从 de-noun expansion 抽 gender/genitive/plural。返回 (gender, gen, pl)。"""
    exp = _de_head(e, "de-noun")
    gender = gen = pl = None
    if exp and " " in exp:
        # expansion 以 word 开头：word + 性别 tokens + "(" ...
        head = exp.split("(")[0]
        after = head[len(word):] if head.startswith(word) else head
        gs = [tok for tok in re.split(r"[\s,]+", after) if tok in ("m", "f", "n")]
        if gs:
            gender = "/".join(dict.fromkeys(gs))
        elif re.search(r"\bp\b", after):
            gender = None  # 纯复数名词，无单数性别
        mg = re.search(rf"genitive ({_WORD_RE})", exp)
        if mg:
            gen = mg.group(1)
        mp = re.search(rf"plural ({_WORD_RE})", exp)
        if mp:
            pl = mp.group(1)
    # 兜底：expansion 缺性别时看 sense tags
    if not gender:
        hf = hm = hn = False
        for s in senses:
            t = s.get("tags", [])
            if "feminine" in t:
                hf = True
            if "masculine" in t:
                hm = True
            if "neuter" in t:
                hn = True
        gg = "/".join([g for g, ok in (("m", hm), ("f", hf), ("n", hn)) if ok])
        gender = gg or None
    return gender, gen, pl


def extract_verb(e, word, senses):
    """动词：从 de-verb expansion 抽 aux/praeteritum/partizip2/vclass；
    forms 抽 separable+prefix；senses 抽 reflexive。
    返回 (aux, praet, pp2, vclass, sep_prefix, reflexive)."""
    exp = _de_head(e, "de-verb")
    aux = praet = pp2 = vclass = None
    if exp:
        mc = re.search(r"class (\d+)\s+(strong|weak|mixed)", exp)
        if mc:
            vclass = f"{mc.group(2)}-{mc.group(1)}"
        else:
            mk = re.search(r"\b(strong|weak|mixed|irregular)\b", exp)
            if mk:
                vclass = mk.group(1)
        mpt = re.search(rf"past tense ({_WORD_RE})", exp)
        if mpt:
            praet = mpt.group(1)
        mpp = re.search(rf"past participle ({_WORD_RE})", exp)
        if mpp:
            pp2 = mpp.group(1)
        ma = re.search(r"auxiliary ([^)]+)", exp)
        if ma:
            auxs = set(re.findall(r"haben|sein", ma.group(1)))
            if auxs == {"haben", "sein"}:
                aux = "both"
            elif auxs == {"haben"}:
                aux = "haben"
            elif auxs == {"sein"}:
                aux = "sein"

    # 可分动词：现在时限定形含空格（"kommt an"），末词即可分前缀
    sep_prefix = None
    for fm in e.get("forms") or []:
        tags = set(fm.get("tags") or [])
        if "multiword-construction" in tags:
            continue
        if ("present" in tags and "indicative" in tags
                and tags & {"first-person", "second-person", "third-person"}):
            f = (fm.get("form") or "").strip()
            if " " in f:
                sep_prefix = f.split()[-1]
                break

    reflexive = 0
    if word.lower().startswith("sich "):
        reflexive = 1
    else:
        for s in senses:
            if "reflexive" in (s.get("tags") or []):
                reflexive = 1
                break
    return aux, praet, pp2, vclass, sep_prefix, reflexive


def extract_adj(e, word):
    """形容词：从 de-adj expansion 抽 comparative/superlative。返回 (comp, sup)。"""
    if word.lower() in COMPARATIVE_IRREGULAR:
        return COMPARATIVE_IRREGULAR[word.lower()]
    exp = _de_head(e, "de-adj")
    comp = sup = None
    if exp:
        mc = re.search(rf"comparative ({_WORD_RE})", exp)
        if mc:
            comp = mc.group(1)
        ms = re.search(rf"superlative (am {_WORD_RE}|{_WORD_RE})", exp)
        if ms:
            sup = ms.group(1)
    return comp, sup


def new_rec(word):
    return {
        "word": word, "ipa": None, "pos": set(),
        "gender": None, "genitive": None, "plural": None,
        "aux": None, "praeteritum": None, "partizip2": None, "vclass": None,
        "separable": 0, "sep_prefix": None, "reflexive": 0,
        "comparative": None, "superlative": None,
        "real_gloss": [], "real_meta": [], "real_seen": set(),
        "infl": [], "infl_seen": set(), "bases": [],
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
            if e.get("lang_code") != "de":
                continue
            word = (e.get("word") or "").strip()
            if not word:
                continue

            key = word            # 德语按原大小写建键（名词大写＝语义区分）
            rec = words.get(key)
            if rec is None:
                rec = new_rec(word)
                words[key] = rec

            pos_raw = e.get("pos", "")
            pos = POS_MAP.get(pos_raw, pos_raw)
            rec["pos"].add(pos)
            ipa = pick_ipa(e.get("sounds"))
            if ipa and not rec["ipa"]:
                rec["ipa"] = ipa

            senses = e.get("senses", [])
            is_affix = pos_raw in ("suffix", "prefix", "infix", "interfix")

            # —— 德语本质字段（按 pos 分流）——
            if pos_raw in ("noun", "name"):
                g, gen, pl = extract_noun(e, word, senses)
                if g and not rec["gender"]:
                    rec["gender"] = g
                if gen and not rec["genitive"]:
                    rec["genitive"] = gen
                if pl and not rec["plural"]:
                    rec["plural"] = pl
            elif pos_raw == "verb":
                aux, praet, pp2, vclass, sep_prefix, refl = extract_verb(e, word, senses)
                if aux and not rec["aux"]:
                    rec["aux"] = aux
                if praet and not rec["praeteritum"]:
                    rec["praeteritum"] = praet
                if pp2 and not rec["partizip2"]:
                    rec["partizip2"] = pp2
                if vclass and not rec["vclass"]:
                    rec["vclass"] = vclass
                if sep_prefix:
                    rec["separable"] = 1
                    if not rec["sep_prefix"]:
                        rec["sep_prefix"] = sep_prefix
                if refl:
                    rec["reflexive"] = 1
            elif pos_raw == "adj":
                comp, sup = extract_adj(e, word)
                if comp and not rec["comparative"]:
                    rec["comparative"] = comp
                if sup and not rec["superlative"]:
                    rec["superlative"] = sup

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
                    label = compose(tags) or "变形"
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

    if dump_infl:
        out = HERE / "infl_combos.txt"
        with open(out, "w", encoding="utf-8") as fo:
            for combo, n in infl_combos.most_common():
                fo.write(f"{n:7}  {compose(list(combo))!r:40}  {'+'.join(combo)}\n")
        print(f"变位组合 {len(infl_combos)} 种 → {out}（供豆包验证措辞）")
        return

    # 统计
    n_lemma = sum(1 for r in words.values() if r["real_gloss"])
    n_infl = len(words) - n_lemma
    n_ipa = sum(1 for r in words.values() if r["ipa"])
    n_gender = sum(1 for r in words.values() if r["gender"])
    n_gen = sum(1 for r in words.values() if r["genitive"])
    n_pl = sum(1 for r in words.values() if r["plural"])
    n_aux = sum(1 for r in words.values() if r["aux"])
    n_pp = sum(1 for r in words.values() if r["partizip2"])
    n_sep = sum(1 for r in words.values() if r["separable"])
    n_cmp = sum(1 for r in words.values() if r["comparative"])
    print(f"总行数 {total} (解析失败 {bad}) → 去重词条 {len(words)}")
    print(f"  真义 lemma {n_lemma} | 纯变位 {n_infl}")
    print(f"  IPA {n_ipa} ({100*n_ipa//max(len(words),1)}%)")
    print(f"  名词：gender {n_gender} | 属格 {n_gen} | 复数 {n_pl}")
    print(f"  动词：aux {n_aux} | 过去分词 {n_pp} | 可分 {n_sep}")
    print(f"  形容词：比较级 {n_cmp}")
    if dropped:
        print(f"  ⚠ 未归桶 tag {len(dropped)} 种（真义义项上，请归类）：")
        for tg, n in dropped.most_common(200):
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
          gender        TEXT,          -- m | f | n | mf（三性 der/die/das）
          genitive      TEXT,          -- 属格单数（des Hauses）
          plural        TEXT,          -- 复数（die Häuser，不可预测全收）
          aux           TEXT,          -- haben | sein | both（完成时助动词）
          praeteritum   TEXT,          -- 过去式 Präteritum（ging）
          partizip2     TEXT,          -- 过去分词 Partizip II（gegangen）
          vclass        TEXT,          -- weak | strong | mixed（可带 ablaut 类号 strong-7）
          separable     INTEGER,       -- 可分动词 trennbar
          sep_prefix    TEXT,          -- 可分前缀（an/auf/mit…）
          reflexive     INTEGER,       -- 反身 sich
          comparative   TEXT,          -- 比较级（gut→besser）
          superlative   TEXT,          -- 最高级（am besten）
          level         TEXT,          -- CEFR A1-C2（豆包填）
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
        batch.append((
            rec["word"], norm_de(rec["word"]), rec["ipa"],
            "/".join(sorted(rec["pos"])) if rec["pos"] else None,
            is_lemma,
            rec["gender"], rec["genitive"], rec["plural"],
            rec["aux"], rec["praeteritum"], rec["partizip2"], rec["vclass"],
            rec["separable"] or None, rec["sep_prefix"], rec["reflexive"] or None,
            rec["comparative"], rec["superlative"],
            definition, translation, meta, infl, exchange,
        ))
    conn.executemany(
        "INSERT INTO dict (word, word_norm, ipa, pos, is_lemma, gender, genitive, "
        "plural, aux, praeteritum, partizip2, vclass, separable, sep_prefix, "
        "reflexive, comparative, superlative, "
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
