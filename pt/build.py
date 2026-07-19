"""
葡萄牙语词典建库：kaikki.org (Wiktextract) JSONL → synapse-dict-pt.sqlite（骨架层）

pt 独立管线，不 import 其他语种、不复用其他语种 schema。产出葡语专属 dict 表：
把葡语最本质的特征升为一等字段——
  · 双读音：ipa_br(巴西 pt-BR) + ipa_pt(欧洲 pt-PT)  ← 葡语灵魂，两列而非单列
  · 动词：vconj(-ar/-er/-ir/pôr 变位类)、transitivity、pronominal、pp(过去分词)
  · 名词/形容词：gender、plural(不规则)、feminine、comparative(不规则少数)
  · 明确不设 aux（葡语无 avoir/être 式逐动词助动词选择）

数据权威分工：
  · 义项/变位/双音/gender/plural/vconj/pp = kaikki（确定性，本脚本）
  · 中文/缺口 gender·plural·feminine/兜底双音/搭配/CEFR = 豆包（b_translate.py，只填不造义项）

IPA：葡语不造 G2P（双方言+鼻化太复杂）。kaikki 双音各覆盖 ~69%；变位形 IPA 无法从 lemma forms
收割（葡语 forms 不带 ipa，与法语相反），只取其自身 sounds 或留空，豆包兜底两套音。

变位形式(senses 全 form_of/alt_of)作独立词条：infl 存中文语法说明(infl_compose，含人称不定式)，
exchange 存 "0:原形" 反查，不送豆包。真义 lemma 的 translation 留空交豆包。

用法：python3 build.py            # 建库
      python3 build.py --dump-infl # 导出真实变位 tag 组合样本
产物：synapse-dict-pt.sqlite（与本脚本同目录）
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
JSONL_PATH = HERE / "kaikki.org-dictionary-Portuguese.jsonl"
DB_PATH = HERE / "synapse-dict-pt.sqlite"

POS_MAP = {
    "noun": "n", "verb": "v", "adj": "adj", "adv": "adv",
    "pron": "pron", "prep": "prep", "conj": "conj", "det": "det",
    "num": "num", "intj": "intj", "name": "name",
    "prefix": "pref", "suffix": "suf", "phrase": "phr",
    "prep_phrase": "phr", "proverb": "prov", "article": "art",
    "contraction": "contr", "particle": "part", "character": "char",
    "symbol": "sym", "interfix": "interfix", "punct": "punct",
}

# ---- meta 分桶（葡语维度）。全 tag 逐个归桶，桶外建库报警（drop-ledger）----
REGIONS = {
    "Brazil", "Portugal", "Southern-Brazil", "Rio-de-Janeiro", "São-Paulo",
    "Caipira", "Northeast-Brazil", "Central-West-Brazil", "Southern", "Northern",
    "Central", "North", "Lisbon", "Porto", "Angola", "Mozambique", "Macau",
    "Cape-Verde", "Guinea-Bissau", "East-Timor", "Galicia", "Alentejo",
    "Azores", "Madeira", "Minho", "Algarve", "regional", "dialectal",
    "Old-Portuguese", "Brazilian", "European",
    # 补桶（dump 实测长尾地区）
    "South-Brazil", "North-Brazil", "Bahia", "Minas-Gerais", "Paraná",
    "Northeastern-Brazil", "Argentina", "Africa", "South-Africa", "India",
    "Canada", "US", "UK", "Australia", "Sri-Lanka", "Indonesia", "Iberian",
    "Northwestern", "Northeastern", "Iranian", "Nordic",
}
REGISTERS = {
    "literary", "archaic", "obsolete", "dated", "historical", "rare",
    "uncommon", "colloquial", "informal", "formal", "familiar", "vulgar",
    "slang", "derogatory", "offensive", "pejorative", "humorous", "ironic",
    "euphemistic", "poetic", "figuratively", "figurative", "neologism",
    "nonstandard", "proscribed", "childish", "endearing", "emphatic",
    "jargon", "slur", "Internet", "misspelling", "pronunciation-spelling",
    "eye-dialect", "hypercorrect", "excessive", "solemn", "affected",
    "chiefly", "reintegrationism", "pre-reform", "obsolete-spelling",
    "rhetoric", "mildly", "sarcastic", "honorific", "impolite",
    "term-of-address", "non-scientific", "nonce-word", "Early",
}
NUMBER_NOTE = {
    "uncountable", "plural-only", "invariable", "collective",
    "countable", "in-plural", "plural-normally", "singular-only",
}
GENDER_COMMON = {"by-personal-gender", "gender-neutral", "common", "epicene"}

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
    "no-gloss", "empty-gloss", "no-plural", "not-comparable", "comparable",
    "attributive", "predicative", "adjectival", "adverbial", "substantive",
    "indeclinable", "in-compounds", "compound", "onomatopoeic", "demonym",
    "letter", "name", "noun", "verb", "adjective", "suffix", "prefix",
    "phrase", "proper-noun", "place", "character", "standard",
    "alternative", "variant", "also", "usually", "often", "sometimes",
    "especially", "including", "possibly", "general", "specifically",
    "broadly", "literally", "metonymically", "mainly",
    "capitalized", "uppercase", "lowercase", "stressed", "unstressed",
    "singular", "plural", "first-person", "second-person", "third-person",
    "present", "past", "future", "imperfect", "preterite", "pluperfect",
    "conditional", "subjunctive", "indicative", "imperative", "infinitive",
    "gerund", "participle", "short-form", "long-form",
    "error-lua-exec", "error-lua-timeout", "error-unknown-tag",
    "misconstruction", "obscure", "idiomatic", "unknown",
    "traditional", "pronoun", "subjective", "objective", "dative", "accusative",
    "indefinite", "definite", "with-infinitive", "with-subjunctive",
    "disjunctive", "conjunctive", "ergative", "polite", "focus", "continuative",
    "physical", "vocative", "genitive", "nominative", "prepositional",
    "Latin", "Latinism", "Christianity", "Ancient-Greek", "Classical",
    "Modern", "medieval", "Renaissance", "Germanic", "ethnic", "Tupi",
    "Greek", "Arabic", "African", "Indo-European-studies",
    # 补桶（dump 实测长尾：宗教/语言族/词源/语法·句法/占位）
    "Roman", "Ancient-Rome", "Hinduism", "Judaism", "Mormonism", "Sikhism",
    "Jainism", "Nazism", "Christian", "Jehovah's-Witnesses", "New-Age",
    "Norse", "Egyptian", "Japanese", "Chinese", "Sanskrit", "Persian",
    "Tibetan", "English", "German", "French", "Provençal", "Greco-Roman",
    "Irish", "Marxism", "European-Union",
    "no-first-person-singular-present", "catenative", "in-variation",
    "intensifier", "diacritic", "retronym", "postpositional", "uninflected",
    "subordinating", "passive", "person", "with-definite-article", "-i",
    "with-negation", "adverb", "sentence-final", "locative", "mnemonic",
    "conjunction", "mixed", "TV", "potential", "sequence", "without-noun",
    "perfective", "elative", "with-numeral", "feminine-usually",
}

# 葡语正字法字母（含鼻化/重音/软音）
PT_ALPHA = "a-zàáâãçéêíóôõú"
BR_FALLBACK = ("Southern-Brazil", "São-Paulo", "Rio-de-Janeiro", "Central-West-Brazil")
PT_FALLBACK = ("Lisbon", "Porto")

# 不规则比较级（葡语少数，纯记忆，硬编码）。adj: bom/mau/grande/pequeno；adv: bem/mal。
COMPARATIVE_IRREGULAR = {
    "bom": "melhor", "mau": "pior", "grande": "maior", "pequeno": "menor",
    "bem": "melhor", "mal": "pior",
}

_WORDLIKE = re.compile(f"^[{PT_ALPHA}][{PT_ALPHA}'’ -]*$", re.I)
PP_RE = re.compile(r"past participle\s+([^\s,()]+)", re.I)


def unaccent(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s.lower())
    out = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return out.replace("ç", "c")


def pick_ipa_region(sounds, primary, fallbacks):
    """取指定方言的音位式 IPA：最一般的 region tag 优先，退回次级 region。"""
    best = None
    for s in sounds or []:
        ip = (s.get("ipa") or "").strip()
        if not ip.startswith("/"):
            continue
        tags = s.get("tags") or []
        if primary in tags:
            return ip
        if best is None and any(f in tags for f in fallbacks):
            best = ip
    return best


def any_ipa(sounds):
    for s in sounds or []:
        ip = (s.get("ipa") or "").strip()
        if ip.startswith("/"):
            return ip
    return None


# ---------- 葡语本质字段抽取 ----------

def extract_vconj(word):
    """变位类：不定式 -ar→1 / -er→2 / -ir→3 / -or(pôr及复合 compor/dispor)→por。"""
    w = (word or "").lower()
    if w.endswith("ar"):
        return "1"
    if w.endswith("er"):
        return "2"
    if w.endswith("ir"):
        return "3"
    if w.endswith("or") or w.endswith("ôr"):
        return "por"
    return None


def extract_pp(e):
    """过去分词：pt-verb head expansion 的 'past participle X'，或 forms participle+past。"""
    for h in e.get("head_templates") or []:
        m = PP_RE.search(h.get("expansion", "") or "")
        if m:
            pp = m.group(1).strip()
            if _WORDLIKE.match(pp):
                return pp
    for fm in e.get("forms") or []:
        tags = set(fm.get("tags") or [])
        if "participle" in tags and "past" in tags \
                and "feminine" not in tags and "plural" not in tags:
            f = (fm.get("form") or "").strip()
            if f and _WORDLIKE.match(f):
                return f
    return None


def extract_gender(e, senses):
    hf = hm = common = False
    for h in e.get("head_templates") or []:
        args = h.get("args") or {}
        for k in ("1", "2", "g", "g2"):
            v = str(args.get(k, "")).strip().lower()
            if v in ("m", "m-p"):
                hm = True
            elif v in ("f", "f-p"):
                hf = True
            elif v in ("mf", "mfbysense", "m or f", "?"):
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
    want = set(want)
    without = set(without)
    for fm in e.get("forms") or []:
        tags = set(fm.get("tags") or [])
        if {"table-tags", "inflection-template"} & tags:
            continue
        if want <= tags and not (without & tags):
            f = (fm.get("form") or "").strip()
            if f and _WORDLIKE.match(f):
                return f
    return None


def extract_plural(e, word):
    """名词/形容词复数；仅不规则（≠词+s 且≠词本身）才收。"""
    pl = _form_by_tags(e, ["plural"], without=["feminine", "masculine"]) \
        or _form_by_tags(e, ["plural"])
    if not pl:
        return None
    lo = pl.lower()
    if lo == (word.lower() + "s"):    # 规则 +s
        return None
    if lo == word.lower():            # 数不变，冗余
        return None
    return pl


def extract_feminine(e):
    return _form_by_tags(e, ["feminine"], without=["plural"])


def new_rec(word):
    return {
        "word": word, "spellings": set(), "ipa_br": None, "ipa_pt": None, "pos": set(),
        "vconj": None, "transitivity": None, "pronominal": 0, "pp": None,
        "gender": None, "plural": None, "feminine": None, "comparative": None,
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
            if e.get("lang_code") != "pt":
                continue
            word = (e.get("word") or "").strip()
            if not word:
                continue
            key = word.lower()
            rec = words.get(key)
            if rec is None:
                rec = new_rec(word)
                words[key] = rec
            rec["spellings"].add(word)

            pos_raw = e.get("pos", "")
            pos = POS_MAP.get(pos_raw, pos_raw)
            rec["pos"].add(pos)

            # 双读音：巴西 / 葡萄牙 各取一，无 region 标注则用通用 IPA 兜到两边
            snd = e.get("sounds")
            br = pick_ipa_region(snd, "Brazil", BR_FALLBACK)
            pt = pick_ipa_region(snd, "Portugal", PT_FALLBACK)
            if not br and not pt:
                generic = any_ipa(snd)
                br = pt = generic
            if br and not rec["ipa_br"]:
                rec["ipa_br"] = br
            if pt and not rec["ipa_pt"]:
                rec["ipa_pt"] = pt

            senses = e.get("senses", [])
            is_affix = pos_raw in ("suffix", "prefix", "infix", "interfix")

            # —— 葡语本质字段 ——
            if pos_raw == "verb":
                vc = extract_vconj(word)
                if vc and not rec["vconj"]:
                    rec["vconj"] = vc
                pp = extract_pp(e)
                if pp and not rec["pp"]:
                    rec["pp"] = pp
                if re.search(r"-se$|\bse$", word):
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
                fem = extract_feminine(e)      # 名词阴性对应形（ator→atriz）
                if fem and not rec["feminine"]:
                    rec["feminine"] = fem
            elif pos_raw == "adj":
                fem = extract_feminine(e)
                if fem and not rec["feminine"]:
                    rec["feminine"] = fem
                pl = extract_plural(e, word)
                if pl and not rec["plural"]:
                    rec["plural"] = pl

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
                        combo = tuple(sorted(x for x in tags
                                             if x in COMPOSE_TAGS and x != "form-of"))
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
        print(f"变位组合 {len(infl_combos)} 种 → {out}")
        return

    # 统计
    n_lemma = sum(1 for r in words.values() if r["real_gloss"])
    n_infl = len(words) - n_lemma
    n_br = sum(1 for r in words.values() if r["ipa_br"])
    n_pt = sum(1 for r in words.values() if r["ipa_pt"])
    n_vc = sum(1 for r in words.values() if r["vconj"])
    n_gender = sum(1 for r in words.values() if r["gender"])
    n_fem = sum(1 for r in words.values() if r["feminine"])
    n_pp = sum(1 for r in words.values() if r["pp"])
    tot = len(words)
    print(f"总行数 {total} (解析失败 {bad}) → 去重词条 {tot}")
    print(f"  真义 lemma {n_lemma} | 纯变位 {n_infl}")
    print(f"  双音：巴西 {n_br}({100*n_br//tot}%) | 葡萄牙 {n_pt}({100*n_pt//tot}%)")
    print(f"  kaikki 抽取：vconj {n_vc} | gender {n_gender} | 阴性形(名+形) {n_fem} | 过去分词 {n_pp}")
    if dropped:
        print(f"  ⚠ 未归桶 tag {len(dropped)} 种：")
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
          ipa_br        TEXT,          -- 巴西标准音 pt-BR
          ipa_pt        TEXT,          -- 欧洲标准音 pt-PT
          pos           TEXT,
          is_lemma      INTEGER NOT NULL,
          vconj         TEXT,          -- 1 | 2 | 3 | por（变位类）
          transitivity  TEXT,          -- t | i | ti
          pronominal    INTEGER,       -- 代词式/反身 -se
          pp            TEXT,          -- 过去分词
          gender        TEXT,          -- m | f | mf
          plural        TEXT,          -- 不规则复数
          feminine      TEXT,          -- 阴性形（形容词 bonito→bonita；名词 ator→atriz）
          comparative   TEXT,          -- 不规则比较级 bom→melhor
          level         TEXT,          -- CEFR A1-C2（豆包）
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
            disp, unaccent(disp), rec["ipa_br"], rec["ipa_pt"],
            "/".join(sorted(rec["pos"])) if rec["pos"] else None,
            is_lemma,
            rec["vconj"], rec["transitivity"], rec["pronominal"] or None, rec["pp"],
            rec["gender"], rec["plural"], rec["feminine"], rec["comparative"],
            definition, translation, meta, infl, exchange,
        ))
    conn.executemany(
        "INSERT INTO dict (word, word_norm, ipa_br, ipa_pt, pos, is_lemma, vconj, "
        "transitivity, pronominal, pp, gender, plural, feminine, comparative, "
        "definition, translation, meta, infl, exchange) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        batch,
    )
    conn.commit()
    conn.execute("CREATE INDEX idx_word ON dict(word COLLATE NOCASE)")
    conn.execute("CREATE INDEX idx_norm ON dict(word_norm)")
    conn.commit()
    conn.close()
    print("完成。下一步：b_translate.py 豆包补 lemma 中文/缺口本质字段/兜底双音")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-infl", action="store_true")
    args = ap.parse_args()
    main(dump_infl=args.dump_infl)
