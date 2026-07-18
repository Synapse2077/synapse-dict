"""
意大利语词典建库：kaikki.org (Wiktextract) JSONL → synapse-dict-it.sqlite（骨架层）

it 独立管线，不 import 其他语种、不复用其他语种 schema。产出意语专属 dict 表：
把意语最本质的特征升为一等字段——
  · 动词：aux(助动词 essere/avere)、conj(变位类)、transitivity、pronominal
  · 名词：gender、plural(不规则复数)、plural_gender(异性复数)、number_note

数据权威分工（一种数据一个权威）：
  · 义项/变位/aux/conj/gender/plural = kaikki（确定性，本脚本负责，能抽多少抽多少）
  · 中文/缺口 aux·gender·plural/搭配/兜底 IPA = 豆包（b_translate.py，只填不造义项）

变位形式(senses 全 form_of/alt_of，占 ~74%)作独立词条收录：
  infl 列存中文语法说明(infl_compose 组合)，exchange 存 "0:原形" 反查 lemma，不送豆包。
真义 lemma 的 translation 留空，交 b_translate.py 豆包补。

用法：python3 build.py            # 建库
      python3 build.py --dump-infl # 导出真实变位 tag 组合样本（供豆包验证措辞）
产物：synapse-dict-it.sqlite（与本脚本同目录）
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
JSONL_PATH = HERE / "kaikki.org-dictionary-Italian.jsonl"
DB_PATH = HERE / "synapse-dict-it.sqlite"

POS_MAP = {
    "noun": "n", "verb": "v", "adj": "adj", "adv": "adv",
    "pron": "pron", "prep": "prep", "conj": "conj", "det": "det",
    "num": "num", "intj": "intj", "name": "name",
    "prefix": "pref", "suffix": "suf", "phrase": "phr",
    "prep_phrase": "phr", "proverb": "prov", "article": "art",
    "contraction": "contr", "particle": "part", "character": "char",
    "symbol": "sym", "interfix": "interfix", "punct": "punct",
}

# ---- meta 分桶（意语维度）。全 tag 逐个归桶，桶外建库报警（drop-ledger）----
REGIONS = {
    "Italy", "Tuscany", "Switzerland", "Sardinia", "Sicily", "Naples", "Rome",
    "Florence", "Milan", "Venice", "Turin", "Genoa", "Bologna", "Lombardy",
    "Piedmont", "Veneto", "Campania", "Calabria", "Apulia", "Abruzzo",
    "Lazio", "Liguria", "Emilia-Romagna", "Umbria", "Marche", "Molise",
    "Basilicata", "Friuli", "Trentino", "Aosta-Valley", "Corsica",
    "Northern", "Southern", "Eastern", "Western", "Central",
    "Northern-Italy", "Southern-Italy", "Central-Italy",
    "regional", "dialectal", "Ancient-Rome", "Roman",
}
REGISTERS = {
    "literary", "archaic", "obsolete", "dated", "historical", "rare",
    "uncommon", "colloquial", "informal", "formal", "familiar", "vulgar",
    "slang", "derogatory", "offensive", "pejorative", "humorous", "ironic",
    "euphemistic", "poetic", "figuratively", "figurative", "neologism",
    "nonstandard", "proscribed", "childish", "endearing", "emphatic",
    "jargon", "slur", "Internet", "misspelling", "pronunciation-spelling",
    "eye-dialect", "hypercorrect", "excessive", "rhetoric", "bureaucratese",
    "mildly", "taboo", "sarcastic", "Middle-Ages", "solemn", "affected",
}
NUMBER_NOTE = {
    "uncountable", "plural-only", "invariable", "collective",
    "countable", "in-plural", "plural-normally", "singular-only",
}
GENDER_COMMON = {"by-personal-gender", "gender-neutral", "common"}

# 已审阅、确定不进 meta 展示的标签（语法/句法/派生/领域/占位/错误）。
IGNORE_TAGS = {
    # 语法·句法（属 compose、essence 列，或不展示）
    "transitive", "intransitive", "ambitransitive", "ditransitive",
    "reflexive", "pronominal", "impersonal", "personal", "auxiliary",
    "reciprocal", "relational", "possessive", "demonstrative",
    "interrogative", "relative", "cardinal", "ordinal", "numeral",
    "contraction", "article", "particle", "negative", "defective",
    "modal", "copulative", "masculine", "feminine", "neuter",
    "form-of", "alt-of", "combined-form", "compound-of",
    "morpheme", "diminutive", "augmentative", "apocopic", "ellipsis",
    "clipping", "acronym", "initialism", "abbreviation",
    "no-gloss", "empty-gloss", "no-plural", "no-past-participle",
    "attributive", "predicative", "adjectival", "adverbial", "substantive",
    "indeclinable", "in-compounds", "compound", "onomatopoeic", "demonym",
    "letter", "name", "noun", "verb", "adjective", "suffix", "prefix",
    "phrase", "proper-noun", "place", "character", "standard",
    "alternative", "variant", "also", "usually", "often", "sometimes",
    "especially", "including", "possibly", "general", "specifically",
    "broadly", "literally", "metonymically", "chiefly", "mainly",
    "capitalized", "uppercase", "lowercase", "stressed", "unstressed",
    "with-euphonic", "second-person-semantically", "singular", "plural",
    "first-person", "second-person", "third-person", "present", "past",
    "future", "imperfect", "historic", "conditional", "subjunctive",
    "indicative", "imperative", "infinitive", "gerund", "participle",
    "error-lua-exec", "error-lua-timeout", "error-unknown-tag",
    "misconstruction", "obscure", "idiomatic", "unknown",
    "traditional", "pronoun", "subjective", "objective", "dative", "accusative",
    "indefinite", "definite", "with-infinitive", "with-subjunctive",
    "with-definite-article", "with-indefinite-article", "no-auxiliary",
    "disjunctive", "conjunctive", "ergative", "polite", "focus", "continuative",
    "physical", "no-first-person-singular-present", "no-third-person",
    "vocative", "genitive", "nominative", "prepositional",
    # 领域·文化·族群
    "Greek", "Latin", "Latinism", "Christianity", "Judaism", "Catholicism",
    "Roman-Catholicism", "Ancient-Greek", "Biblical", "Classical", "Modern",
    "Early", "medieval", "Renaissance", "Egyptian", "Germanic", "ethnic",
    "Australia", "US", "UK",
}

DEACC = str.maketrans("àèéìíòóù", "aeeiioou")
AUX_RE = re.compile(r"auxiliary\s+(av[eé]re|[eè]ssere)(?:\s+or\s+(av[eé]re|[eè]ssere))?", re.I)


def unaccent(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s.lower())
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


# ---------- 意语本质字段抽取 ----------

def extract_aux(e, cats):
    """助动词：expansion 'auxiliary avére/èssere' + categories 双源。返回 avere/essere/both/None。"""
    got = set()
    for h in e.get("head_templates") or []:
        for m in AUX_RE.finditer(h.get("expansion", "") or ""):
            for g in m.groups():
                if g:
                    got.add(g.translate(DEACC).lower())
    if "taking avere as auxiliary" in cats:
        got.add("avere")
    if "taking essere as auxiliary" in cats:
        got.add("essere")
    if got == {"avere", "essere"}:
        return "both"
    if "avere" in got:
        return "avere"
    if "essere" in got:
        return "essere"
    return None


def extract_conj(e):
    """变位类：不定式词尾 -are→1 / -ire→3 / 其余(-ere,-rre)→2；含 -isc- 记 3isc。"""
    w = e.get("word", "")
    isc = False
    for h in e.get("head_templates") or []:
        if "isc" in str(h.get("args", {}).get("1", "")):
            isc = True
    if w.endswith("are"):
        return "1"
    if w.endswith("ire"):
        return "3isc" if isc else "3"
    if w.endswith("ere") or w.endswith("rre"):
        return "2"
    return None


PLURAL_ARG_RE = re.compile(r"([^\s,<]+?)(?:<g:([mf]+)>)?(?:<[^>]*>)*(?:,|$)")


def _plural_from_head(e):
    """从 it-noun head_template args 抽复数形+性别（braccia<g:f> 这类，forms 数组常缺）。
    返回 [(form, gender_or_None), ...]。"""
    out = []
    for h in e.get("head_templates") or []:
        if h.get("name") != "it-noun":
            continue
        args = h.get("args") or {}
        for k in sorted(k for k in args if k.isdigit() and int(k) >= 2):
            spec = str(args[k]).strip()
            if not spec or spec in ("#", "~", "-", "!", "+", "s"):  # 占位/规则标记
                continue
            for m in PLURAL_ARG_RE.finditer(spec):
                form = (m.group(1) or "").strip()
                if not form or "<" in form:
                    continue
                g = m.group(2)
                out.append((form, "f" if g == "f" else ("m" if g == "m" else None)))
    return out


# 合法复数形：意语字母（含重音）+ 允许多词（le Marche / esseri umani）与撇号，长度≥2。
# 拦掉 kaikki/豆包的词典惯例占位符：# ~ + - ? ! * #s 之类。
_PLURAL_OK = re.compile(r"[A-Za-zàèéìíòóù][A-Za-zàèéìíòóù'’ ]*[A-Za-zàèéìíòóù]")


def _valid_plural(form):
    form = (form or "").strip()
    return bool(form) and bool(_PLURAL_OK.fullmatch(form))


def extract_plural(e, gender):
    """复数形与其性别。head_template args 优先（带 <g:> 标注，异性复数可靠），forms 数组兜底。
    返回 (plural, plural_gender)；异性复数(metaplasmic)时 plural_gender 非空。占位符标记一律丢。"""
    plural = None
    pl_gender = None
    # ① head_template args（braccia<g:f>,bracci<g:m>）
    for form, fg in _plural_from_head(e):
        if not _valid_plural(form):
            continue
        if plural is None:
            plural = form
        if fg and gender and fg != gender:
            pl_gender = fg
            plural = form              # 异性复数形优先展示
            break
    # ② forms 数组兜底
    if plural is None or pl_gender is None:
        for fm in e.get("forms") or []:
            tags = fm.get("tags") or []
            if "plural" in tags and "singular" not in tags:
                form = (fm.get("form") or "").strip()
                if not _valid_plural(form):
                    continue
                if plural is None:
                    plural = form
                fg = "f" if "feminine" in tags else ("m" if "masculine" in tags else None)
                if fg and gender and fg != gender and pl_gender is None:
                    pl_gender = fg     # 异性复数：braccio(m)→braccia(f)
    return plural, pl_gender


def new_rec(word):
    return {
        "word": word, "spellings": set(), "ipa": None, "pos": set(),
        "aux": None, "conj": None, "transitivity": None, "pronominal": 0,
        "gender": None, "plural": None, "plural_gender": None, "number_note": None,
        "real_gloss": [], "real_meta": [], "real_seen": set(),
        "infl": [], "infl_seen": set(), "bases": [],
        "_trans": set(),   # transitive/intransitive 累积
    }


def gender_of_senses(senses):
    hf = hm = common = False
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
    dropped = Counter()          # 真义义项上、未归桶的 tag（应为空）
    infl_combos = Counter()      # --dump-infl：真实变位 tag 组合

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
            if e.get("lang_code") != "it":
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
            ipa = pick_ipa(e.get("sounds"))
            if ipa and not rec["ipa"]:
                rec["ipa"] = ipa

            cats = set()
            for s in e.get("senses", []):
                for c in s.get("categories") or []:
                    cats.add(c.get("name", ""))

            senses = e.get("senses", [])
            is_affix = pos_raw in ("suffix", "prefix", "infix", "interfix")

            # —— 意语本质字段（按 pos 分流）——
            if pos_raw == "verb":
                a = extract_aux(e, cats)
                if a and not rec["aux"]:
                    rec["aux"] = a
                c = extract_conj(e)
                if c and not rec["conj"]:
                    rec["conj"] = c
                if re.search(r"[ai]rsi$|ersi$", word):
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
                g = gender_of_senses(senses)
                if g and not rec["gender"]:
                    rec["gender"] = g
                pl, plg = extract_plural(e, rec["gender"] or g)
                if pl and not rec["plural"]:
                    rec["plural"] = pl
                if plg and not rec["plural_gender"]:
                    rec["plural_gender"] = plg
                for s in senses:
                    nn = [x for x in s.get("tags", []) if x in NUMBER_NOTE
                          and x not in ("countable",)]
                    if nn and not rec["number_note"]:
                        rec["number_note"] = nn[0]

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

    # 统计
    n_lemma = sum(1 for r in words.values() if r["real_gloss"])
    n_infl = len(words) - n_lemma
    n_aux = sum(1 for r in words.values() if r["aux"])
    n_gender = sum(1 for r in words.values() if r["gender"])
    n_plural = sum(1 for r in words.values() if r["plural"])
    print(f"总行数 {total} (解析失败 {bad}) → 去重词条 {len(words)}")
    print(f"  真义 lemma {n_lemma} | 纯变位 {n_infl}")
    print(f"  kaikki 抽取：aux {n_aux} | gender {n_gender} | 不规则复数 {n_plural}")
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
          aux           TEXT,
          conj          TEXT,
          transitivity  TEXT,
          pronominal    INTEGER,
          gender        TEXT,
          plural        TEXT,
          plural_gender TEXT,
          number_note   TEXT,
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
            rec["aux"], rec["conj"], rec["transitivity"], rec["pronominal"] or None,
            rec["gender"], rec["plural"], rec["plural_gender"], rec["number_note"],
            definition, translation, meta, infl, exchange,
        ))
    conn.executemany(
        "INSERT INTO dict (word, word_norm, ipa, pos, is_lemma, aux, conj, "
        "transitivity, pronominal, gender, plural, plural_gender, number_note, "
        "definition, translation, meta, infl, exchange) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        batch,
    )
    conn.commit()
    conn.execute("CREATE INDEX idx_word ON dict(word COLLATE NOCASE)")
    conn.execute("CREATE INDEX idx_norm ON dict(word_norm)")
    conn.commit()
    conn.close()
    print("完成。下一步：b_ipa_fill.py 补变位 IPA，b_translate.py 豆包补 lemma 中文/缺口本质字段")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-infl", action="store_true",
                    help="导出真实变位 tag 组合样本（供豆包验证 infl 措辞），不建库")
    args = ap.parse_args()
    main(dump_infl=args.dump_infl)
