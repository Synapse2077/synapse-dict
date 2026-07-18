"""
西班牙语词典建库：kaikki.org (Wiktextract) JSONL → synapse-dict-es.sqlite（骨架层）

集成 A①–⑥（见 memory project_multilang_dict）：
  A① 变位语法标签用确定性组合器 infl_compose.compose（豆包一次性验证措辞、规则组合）
  A② lemma definition 过滤变位描述义（结构化 form_of + prose 模式），不污染
  A③ 抽 base 去 "combined with…" 后缀（双代词/反身不定式 exchange 不再被污染）
  A④ 逐义项 meta（性别/地区/语域，存 kaikki 原始数据，显示层再转换）+ reflexive 列
  A⑤ 一个词形多原形时收全部 base 进 exchange（hablas→habla+hablar）
  A⑥ 原生扁平 schema（一个拼写一行），删英语死列，不被英语词典束缚

真义中文(translation)留空，交 B 组豆包填。本脚本只出确定性骨架。
用法：python3 build.py     产物：synapse-dict-es.sqlite
"""

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from infl_compose import compose, COMPOSE_TAGS

HERE = Path(__file__).resolve().parent
JSONL_PATH = HERE / "kaikki.org-dictionary-Spanish.jsonl"
DB_PATH = HERE / "synapse-dict-es.sqlite"

DROP_TAGS = {"form-of", "alt-of", "combined-form"}
# 缩写/首字母词：不是变位，是独立词条，全称即其义 → 当真义留着(交B组翻)，不进 exchange
ABBR_TAGS = {"abbreviation", "initialism", "acronym"}
STRIP_COMBINED = re.compile(r"\s+combined with.*$", re.I)
PROSE_INFL = re.compile(
    r"(only used in|inflection of|syntactic variant|combined with|"
    r"\b(singular|plural|first[- ]person|second[- ]person|third[- ]person|"
    r"participle|gerund|infinitive|imperative|indicative|subjunctive|"
    r"preterite|imperfect|conditional|dative|accusative)\b.{0,30}\bof\b)",
    re.I,
)
BASE_FROM_PROSE = re.compile(r"\bof\s+([a-záéíóúñü]+)\s*$", re.I)

# A④ 原始标签集合（存 kaikki 原名，不转码）。全库 312 个 tag 逐个归桶，
# 桶外的建库时打印（见 main 末尾 drop-ledger），杜绝"白名单漏一个=静默丢"。
REGIONS = {  # 地理使用区（国家/西班牙各大区/拉美各国/泛方位）
    "Spain", "Canary-Islands", "Andalusia", "Latin-America", "Mexico", "Chile",
    "Colombia", "Peru", "Venezuela", "Cuba", "Bolivia", "Ecuador", "Guatemala",
    "Honduras", "Nicaragua", "Costa-Rica", "Paraguay", "Uruguay",
    "Dominican-Republic", "Puerto-Rico", "Caribbean", "Rioplatense",
    "Argentina", "Panama", "El-Salvador",
    # —— 补全（原白名单漏，静默丢过 1157 义项）——
    "Central-America", "South-America", "North-America", "Philippines", "US", "UK",
    "Canada", "Australia", "Louisiana", "Texas", "California", "New-York-City",
    "Aragon", "Asturias", "Galicia", "Navarre", "Tenerife", "Seville", "Valencia",
    "Catalonia", "Mallorca", "Belize", "Antilles", "Guerrero", "Puebla", "Bogota",
    "Manila", "Llanos", "Morocco", "Angola", "Equatorial-Guinea", "Iberian",
    "European", "European-Union", "EU", "Lunfardo", "Southern-Spain",
    "Northern", "Southern", "Eastern", "Western", "Northeastern", "Northwestern",
    "Southeastern", "Southwestern", "Central",
}
REGISTERS = {  # 语域/时代/语气
    "colloquial", "vulgar", "slang", "derogatory", "offensive", "humorous",
    "literary", "dated", "euphemistic", "informal", "formal", "pejorative",
    "childish", "poetic", "familiar", "proscribed", "nonstandard",
    # —— 补全（静默丢过 6026 义项）——
    "obsolete", "historical", "archaic", "rare", "uncommon", "neologism",
    "Internet", "misspelling", "pronunciation-spelling", "dialectal", "regional",
    "jargon", "slur", "ironic", "sarcastic", "endearing", "emphatic", "rhetoric",
    "bureaucratese", "Leet", "figuratively",
}
NUMBER = {  # #4 词汇性数属性（仅名词有意义）
    "uncountable", "plural-only", "invariable", "collective",
}
GENDER_COMMON = {"by-personal-gender", "gender-neutral", "common"}  # → mf 共性

# 已审阅、确定不进 meta 展示的标签（语法/句法/词素/领域/错误）。
# 与上面各桶合起来覆盖全部 312 个 tag；都不在=新标签，建库时报警。
IGNORE_TAGS = {
    # 语法/句法（属 compose 或不展示）
    "past", "transitive", "intransitive", "ambitransitive", "ditransitive",
    "impersonal", "personal", "auxiliary", "catenative", "copulative",
    "reciprocal", "relational", "possessive", "demonstrative", "interrogative",
    "relative", "pronoun", "cardinal", "ordinal", "numeral", "letter",
    "contraction", "article", "particle", "negative", "defective", "ergative",
    "stative", "modal", "imperfective", "perfect", "pluperfect", "jussive",
    "potential", "contemplative", "essive", "instructive", "locative", "ablative",
    "genitive", "nominative", "objective", "subjective", "disjunctive",
    "conjunctive", "vocative", "prepositional", "postpositional", "attributive",
    "predicative", "adjectival", "adverbial", "copula", "substantive",
    "no-plural", "no-superlative", "no-feminine", "feminine-usually",
    "no-first-person-singular-present", "no-first-person-singular-preterite",
    "addressee-singular", "addressee-plural", "with-definite-article",
    "with-personal-pronoun", "with-por", "with-a", "with-infinitive",
    "with-subjunctive", "with-comparative", "indeclinable", "in-plural",
    "plural-normally", "countable", "in-compounds", "compound-of",
    "noun-from-verb", "retronym", "onomatopoeic", "demonym", "apocopic",
    "ellipsis", "clipping", "acronym", "initialism", "abbreviation", "morpheme",
    "name", "noun", "verb", "adjective", "suffix", "phrase", "proper-noun",
    "place", "character", "standard", "traditional", "variant", "alternative",
    "also", "usually", "often", "sometimes", "especially", "including",
    "possibly", "general", "physical", "specifically", "broadly", "literally",
    "metonymically", "diacritic", "stressed", "capitalized", "uppercase",
    "lowercase", "mixedcase", "dependent", "inclusive", "excessive",
    "term-of-address", "polite", "deliberate", "mildly", "ethnic", "neuter",
    "gender-neutral", "pronominal", "definite", "indefinite", "person",
    "irregular", "intensifier",
    # 领域/文化
    "idiomatic", "Judaism", "Marxism", "Hinduism", "Jainism", "Sikhism",
    "Mormonism", "Roman", "Ancient-Rome", "Norse", "Greek", "Egyptian",
    "Japanese", "Chinese", "German", "Dutch", "Irish", "Basque", "Catalan",
    "Biblical", "Classical", "Modern", "Early", "Jewish", "Brazilian", "Spanish",
    # 错误/占位
    "error-lua-timeout", "error-unknown-tag", "error-lua-exec", "no-gloss",
    "empty-gloss", "misconstruction",
}

POS_MAP = {
    "noun": "n", "verb": "v", "adj": "adj", "adv": "adv", "pron": "pron",
    "prep": "prep", "conj": "conj", "det": "det", "num": "num", "intj": "intj",
    "name": "name", "prefix": "pref", "suffix": "suf", "phrase": "phr",
    "contraction": "contr", "article": "art", "proverb": "prov",
}


def unaccent(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower()


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


def is_infl_sense(s) -> bool:
    if s.get("form_of") or s.get("alt_of"):
        return True
    g = (s.get("glosses") or [""])[0]
    return bool(PROSE_INFL.search(g))


def base_of(s):
    fo = s.get("form_of") or s.get("alt_of")
    if fo and fo[0].get("word"):
        return STRIP_COMBINED.sub("", fo[0]["word"]).strip()
    g = (s.get("glosses") or [""])[0].strip()
    m = BASE_FROM_PROSE.search(g)
    return m.group(1) if m else None


def meta_of(s, pos):
    t = s.get("tags", [])
    m = {"pos": POS_MAP.get(pos, pos)}   # 逐义项词性（kaikki 一条=一个 pos）
    # 性别：只对名词/专名有意义。形容词的阴+阳双标是"一致关系"非固有性别→丢。
    if pos in ("noun", "name", "proper noun"):
        hf = "feminine" in t
        hm = "masculine" in t
        common = any(x in t for x in GENDER_COMMON)
        if common or (hf and hm):
            m["g"] = "mf"          # 共性 el/la（#5 by-personal-gender 并入）
        elif hf:
            m["g"] = "f"
        elif hm:
            m["g"] = "m"
        elif "neuter" in t:
            m["g"] = "n"
        num = [x for x in t if x in NUMBER]     # #4 数属性（仅名词）
        if num:
            m["num"] = num
    reg = [x for x in t if x in REGIONS]
    if reg:
        m["reg"] = reg
    lex = [x for x in t if x in REGISTERS]
    if lex:
        m["lex"] = lex
    return m


def new_rec(word):
    return {
        "word": word, "spellings": set(), "phonetic": None, "pos": set(),
        "reflexive": 0,
        "real_gloss": [], "real_meta": [], "real_seen": set(),
        "infl": [], "infl_seen": set(), "bases": [],
    }


def main():
    if not JSONL_PATH.exists():
        raise SystemExit(f"缺少 dump: {JSONL_PATH}")
    print(f"读取: {JSONL_PATH}")
    words = {}
    total = bad = 0
    KNOWN_ALL = (REGIONS | REGISTERS | NUMBER | GENDER_COMMON | IGNORE_TAGS
                 | {"feminine", "masculine"} | set(COMPOSE_TAGS))
    dropped = {}  # 出现在真义义项上、却不在任何已知桶里的 tag → 潜在新漏网

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
            if e.get("lang_code") != "es":
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
            pos = e.get("pos", "")
            rec["pos"].add(POS_MAP.get(pos, pos))
            ipa = pick_ipa(e.get("sounds"))
            if ipa and not rec["phonetic"]:
                rec["phonetic"] = ipa
            # A④ reflexive：-arse/-erse/-irse 词尾 或 reflexive/pronominal 标签
            if pos == "verb" and re.search(r"(ar|er|ir)se$", word):
                rec["reflexive"] = 1

            # 后缀/前缀是词素，不是某词的变位——永不判变位
            is_affix = pos in ("suffix", "prefix", "infix", "interfix")
            for s in e.get("senses", []):
                tags = s.get("tags", [])
                if "reflexive" in tags or "pronominal" in tags:
                    rec["reflexive"] = 1
                # ① 缩写不是变位：全称当真义留着，不指 exchange（否则全称词组=悬空孤儿）
                is_abbr = bool(set(tags) & ABBR_TAGS)
                # A①/A③/A⑤ 变位义：非词素、非缩写、判定为变位、且能抽出真 base
                base = (base_of(s) if (not is_affix and not is_abbr and is_infl_sense(s))
                        else None)
                if base:
                    label = compose(tags) or "变位形式"
                    line = f"{base} 的 {label}"
                    if line not in rec["infl_seen"]:
                        rec["infl_seen"].add(line)
                        rec["infl"].append(line)
                    if base not in rec["bases"]:
                        rec["bases"].append(base)
                else:
                    # A②/A④ 真义（含 prose 抽不出 base 的"only used in X"，当真义留着）
                    g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
                    if not g or g in rec["real_seen"]:
                        continue
                    rec["real_seen"].add(g)
                    rec["real_gloss"].append(g)
                    rec["real_meta"].append(meta_of(s, pos))
                    for tg in tags:                     # drop-ledger：真义上的未归桶 tag
                        if tg not in KNOWN_ALL:
                            dropped[tg] = dropped.get(tg, 0) + 1

    # —— 孤儿指针收口（单词原形，用西语知识裁决）——
    # 变位的 "0:原形" 若在库里查不到就是悬空孤儿。三种处置：
    #   ① 重音变体（fertil↔fértil）→ 重指到库中规范拼写
    #   ② 真缺真词（cimblar/aggiornar/averar 等 kaikki 漏收词头）→ 补空壳 lemma 交 B 组翻
    #   ③ 明确 junk（merer 非标准词、ethnographique 法语）→ 删指针，删因此变空的 junk 变位
    JUNK_BASES = {"merer", "ethnographique"}
    # 多词原形逐条裁决（33个，见对话记录）：剥英文泄漏 / 补短语 stub / 删残渣
    MW_REPOINT = {                            # ① 英文释义泄漏在真词上 → 剥回真词
        "azud m": "azud", "peuco an American hawk": "peuco",
        "primogénito firstborn daughter": "primogénito",
        "soldado little soldier": "soldado", "vaquera Cowgirls": "vaquera",
        "o when between numerals": "o", "de often found on signs": "de",
        "es que in the Madrid dialect": "es que",
    }
    MW_STUB = {                               # ② 真实短语 → 补 stub 词头交豆包
        "a través", "aloe vera", "paso doble", "con base en", "salir mal",
        "nueva tecnología", "el pan de cada día", "en hora mala", "día sí",
        "galane de noche",
    }
    MW_DROP = {                               # ③ 纯英文/代词描述/谚语碎片 → 删指针
        "execution of a crimen or delito in that",
        "an eccentric or superficial genius", "tú and vos", "él and usted",
        "ellos and ellas", "voy a", "al mal tiempo buena cara",
        "allá donde fueres", "quien se pica", "quien tiene boca",
        "en casa de herrero", "lo que se aprende en la cuna", "quien más",
        "lo bueno",
    }
    norm_index = {}                       # word_norm → 一个真实拼写
    for r in words.values():
        norm_index.setdefault(unaccent(r["word"]), r["word"])
    missing_bases = set()
    drop_word_keys = []
    for key, r in words.items():
        if not r["bases"]:
            continue
        nb, dropped_junk = [], False
        for b in r["bases"]:
            bl = b.lower()
            if bl in words:                   # 已存在
                nb.append(b)
            elif " " in b:                    # 多词：查裁决表
                if b in MW_REPOINT:
                    tgt = MW_REPOINT[b]
                    nb.append(tgt)
                    if tgt.lower() not in words:   # 目标本身缺 → 也补 stub
                        missing_bases.add(tgt)
                elif b in MW_STUB:
                    nb.append(b)
                    missing_bases.add(b)
                elif b in MW_DROP:
                    dropped_junk = True
                else:
                    nb.append(b)              # 未列多词（合法词组基，保留）
            elif bl in JUNK_BASES:
                dropped_junk = True           # ③ 删指针
            elif unaccent(b) in norm_index:
                nb.append(norm_index[unaccent(b)])   # ① 重指规范拼写
            else:
                nb.append(b)                  # ② 真缺 → 保留并补 stub
                missing_bases.add(b)
        r["bases"] = nb
        if dropped_junk and not nb and not r["real_gloss"] and not r["infl"]:
            drop_word_keys.append(key)        # 变位变空 → 整词删
    for key in drop_word_keys:
        del words[key]
    for b in missing_bases:                   # ② 补空壳真词头（def 空，交 B 组豆包）
        k = b.lower()
        if k not in words:
            rec = new_rec(b)
            rec["spellings"].add(b)
            words[k] = rec
    print(f"  孤儿收口：补 stub 真词头 {len(missing_bases)}，删 junk 变位 {len(drop_word_keys)}")

    # 统计
    n_lemma = sum(1 for r in words.values() if r["real_gloss"])
    n_infl_only = len(words) - n_lemma
    print(f"总行数 {total} (解析失败 {bad}) → 去重词条 {len(words)}")
    print(f"  有真义 lemma {n_lemma} | 纯变位 {n_infl_only}")
    # drop-ledger：真义义项上出现、却没归进任何桶的 tag（应为空；非空=有新漏网待归类）
    if dropped:
        print(f"  ⚠ 未归桶 tag {len(dropped)} 种（真义义项上，请归类）：")
        for tg, n in sorted(dropped.items(), key=lambda x: -x[1])[:30]:
            print(f"      {n:6} {tg}")
    else:
        print("  ✓ 全部真义 tag 已归桶，无静默丢弃")

    # 写库（A⑥ 原生 schema）
    print(f"写入: {DB_PATH}")
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(
        """
        CREATE TABLE dict (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          word        TEXT NOT NULL,
          word_norm   TEXT NOT NULL,
          phonetic    TEXT,
          pos         TEXT,
          is_lemma    INTEGER NOT NULL,
          reflexive   INTEGER,
          definition  TEXT,
          translation TEXT,
          meta        TEXT,
          infl        TEXT,
          exchange    TEXT,
          collocation TEXT,
          example     TEXT,
          flag        TEXT
        );
        """
    )
    batch = []
    for rec in words.values():
        # 有真义 → lemma；无真义但也不是变位(kaikki 无 gloss 的孤立真词，如 paralelar)
        # → 也当 lemma、definition 留空，交 B 组豆包凭西语知识补中文（别丢）
        is_lemma = 1 if (rec["real_gloss"] or (not rec["infl"] and not rec["bases"])) else 0
        definition = "\n".join(rec["real_gloss"]) if rec["real_gloss"] else None
        meta = (json.dumps(rec["real_meta"], ensure_ascii=False)
                if rec["real_gloss"] else None)
        infl = "\n".join(rec["infl"]) if rec["infl"] else None
        exchange = "\n".join(f"0:{b}" for b in rec["bases"]) if rec["bases"] else None
        # 纯变位词：translation 直接 = infl（无真义待豆包）；有真义：translation 留空待 B
        translation = None if is_lemma else infl
        # #6 显示拼写：同 key 多拼写(che/CHE/Che)优先取小写常规形，避免显示成 XD/DIA
        disp = rec["word"]
        if disp.lower() in rec["spellings"]:
            disp = disp.lower()
        batch.append((
            disp, unaccent(disp), rec["phonetic"],
            "/".join(sorted(rec["pos"])) if rec["pos"] else None,
            is_lemma, rec["reflexive"] or None,
            definition, translation, meta, infl, exchange, None,
        ))
    conn.executemany(
        "INSERT INTO dict (word, word_norm, phonetic, pos, is_lemma, reflexive, "
        "definition, translation, meta, infl, exchange, example) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        batch,
    )
    conn.commit()
    conn.execute("CREATE INDEX idx_word ON dict(word COLLATE NOCASE)")
    conn.execute("CREATE INDEX idx_norm ON dict(word_norm)")
    conn.commit()
    conn.close()
    print("完成。下一步：B 组豆包填 translation（is_lemma=1 且 translation 为空的词）")


if __name__ == "__main__":
    main()
