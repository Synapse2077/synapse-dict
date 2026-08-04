#!/usr/bin/env python3
"""西语版收词：把 es.wiktionary 里我们没有的词形收进库。2026-08-03。

═══ 为什么有这个脚本 ═══
🔴 **我们的 es 词典是从「英文版」建的，不是「西语版」。**（`build.py` 读 `paths.KK`＝
   kaikki 的 English-edition 西语切片。）西语版整包 8/1 才下，此前只用来给音标背书。
   实测西语版有 85.3 万条西语条目，其中**我们完全没有的**：真 lemma 5.7 万 + 纯变形 31.2 万。
   用户方针①「词汇要全，其他语言版本的词汇尽量收集」→ 全盘收。

═══ 三条判据（都是踩坑之后定的，别凭印象改）═══
① **判变形不能只看 `form_of`。** 西语版大量变形条目没填 `form_of`，只靠
   `pos_title = "Forma verbal"` + 散文 `Gerundio de remilgarse.` 表达。
   只看 `form_of` 会把 **11,979 条变形误判成 lemma**。→ 见 `is_form_entry`。
② **抽原形不能锚定句尾。** `Gerundio de remilgarse, con el pronombre «se» enclítico.`
   句尾是 `enclítico`。→ 取**全部** `de X` 里 X 不是语法词的，见 `GRAM` / `bases_of`。
   这一条把"抽不出原形"从 2,184 压到 105。
③ **中文语法标签复用 `infl_compose.compose`**，不另写一套措辞。
   西语版给的是西语散文，先 `parse_form_gloss` 译成 kaikki tag，再交 compose ——
   这样新收的 31 万变形和库里已有的 66 万**说同一种话**，展示层不用分叉。

═══ 列怎么写（`definition` 那一列的归属问题）═══
`definition` 这一列的性质是「**英文版原值**」—— 2026-08-02 从中文版补义项时，
为了保住这个性质，宁可写空行也没往里塞 `[zh-wiktionary]` 标记。西语版同理：
西语 gloss **不进 `definition`**，进新列 `definition_es`。
两列正交：一列是英文版说的，一列是西语版说的，各自可独立回核。

用法（在 es/ 目录）：
    python3 pipeline/ingest_edition.py --scan     # 全量扫描 → 暂存 jsonl + 普查（不写库）
    python3 pipeline/ingest_edition.py --plan     # 读暂存，出落库计划与指针连通性
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # build.py 里 `import infl_compose` 是同级导入

import argparse
import collections
import json
import random
import re
import sqlite3
import unicodedata as U

import dbtool
import ipa_norm as N
import kaikki_util as K
import paths
from pipeline.apply_edition_confirm import AVOID, WANT, canon_edition
from pipeline.build import POS_MAP, meta_of, unaccent
from pipeline.infl_compose import compose

STAGE = paths.WORK / "edition_intake.jsonl"

# ═══ 变形识别 ═══
# 西语版所有变形条目的 pos_title 都以 "Forma " 开头（Forma verbal / Forma adjetiva /
# Forma sustantiva masculina / Forma de sufijo …）。这是**条目级**信号，比 sense 级可靠。
FORM_TITLE = "Forma "

# ═══ 散文 → kaikki tag ═══
# 骨架普查：36.4 万条变形义项只有 368 种骨架，前 45 种覆盖 95.1%，长尾 258 种共 335 条。
_PERSON = ((r"primera persona", "first-person"), (r"segunda persona", "second-person"),
           (r"tercera persona", "third-person"))
# 时态：**长的先匹配** —— "pretérito perfecto simple" 必须排在 "pretérito perfecto" 前面，
# 否则简单过去时会被吞成完成时。
_TENSE = ((r"pretérito perfecto simple", "preterite"),
          (r"pretérito imperfecto", "imperfect"),
          (r"pretérito perfecto", "preterite"),
          (r"pretérito", "preterite"),
          (r"presente", "present"),
          (r"futuro", "future"))
_MOOD = ((r"imperativo", "imperative"), (r"subjuntivo", "subjunctive"),
         (r"indicativo", "indicative"))
# 不锚定句首：`Haciendo (gerundio de hacer), con los pronombres se y las enclíticos.`
# 的 gerundio 在括号里。
_NONFIN = ((r"\bgerundio\b", "gerund"), (r"\binfinitivo\b", "infinitive"),
           (r"\bparticipio\b", "participle"))

PAREN = re.compile(r"\([^)]*\)|«[^»]*»")
# 语法词：`de X` / `del X` 里的 X 是这些时，X 不是原形而是语法术语/冠词/代词。
GRAM = {
    "subjuntivo", "indicativo", "imperativo", "condicional", "gerundio", "participio",
    "infinitivo", "plural", "singular", "femenino", "masculino", "modo", "forma",
    "manera", "cortesía", "respeto", "persona", "género", "número", "tratamiento",
    "voseo", "tuteo", "presente", "pretérito", "futuro", "perfecto", "imperfecto",
    "simple", "superlativo", "diminutivo", "aumentativo",
    # `del` 也认之后新增的一批：`del verbo requerir` / `del pronombre me`
    "verbo", "sustantivo", "adjetivo", "adverbio", "pronombre", "pronombres",
    "enclítico", "enclíticos", "enclítica", "activo", "pasivo", "afirmativo",
    "negativo", "irregular", "regular", "locución", "sufijo", "prefijo", "grafía",
    "variante", "alternativa", "femenina", "masculina", "verbal", "nominal",
    "la", "el", "los", "las", "un", "una", "lo", "este", "esta", "ese", "esa",
    "aquel", "aquella", "yo", "tú", "vos", "usted", "ustedes", "vosotros",
    "vosotras", "nosotros", "nosotras", "ellos", "ellas", "él", "ella", "se", "sí",
    "me", "te", "nos", "os", "le", "les", "lo", "los", "mí", "ti",
}
# 🔴 必须同时认 `de` 和 `del`：`Participio activo del verbo requerir.` 只有 `del`，
#    早先只认 `de\s` 时这一族全部抽不出原形（2,710 条里的大头）。
#    `del` 后面几乎总跟语法词（del plural / del presente / del verbo），靠 GRAM 挡住。
_DE = re.compile(r"\bde(?:l)?\s+([-\w'’´ˊ́]+)", re.UNICODE)


def is_form_entry(entry):
    """条目是不是变形条目。**别只看 form_of** —— 判据①。"""
    return (entry.get("pos_title") or "").startswith(FORM_TITLE)


# 散文里"这句话在描述一个变形"的关键词。`pos_title` 是条目级信号，会错标：
# `agállara` 的 pos_title 是 "Forma verbal"，两个义项却是货真价实的名词释义
# （"栎树上的圆形瘤突" / "鱼鳃"）—— 源头自己填错了。
# → 条目级信号必须配一道义项级的散文核对，否则真义会被当成变形丢掉。
INFL_PROSE = re.compile(
    r"persona\b|\bplural\b|\bsingular\b|gerundio|participio|infinitivo|imperativo|"
    r"indicativo|subjuntivo|condicional|forma del|forma de |femenino|masculino|"
    r"superlativo|diminutivo|aumentativo|grafía alternativa|enclític|del verbo|"
    r"pretérito|presente de|futuro de", re.I)


def is_form_sense(sense, entry_is_form):
    """义项是不是变形描述。

    结构化 `form_of`/`alt_of` 说了算；没有结构化标记时，条目级 `pos_title` 说是变形
    **还要散文本身看着像变形**（见 INFL_PROSE 上方注释）。
    """
    if sense.get("form_of") or sense.get("alt_of"):
        return True
    if not entry_is_form:
        return False
    return bool(INFL_PROSE.search((sense.get("glosses") or [""])[0]))


def bases_of(sense, gloss):
    """义项指向的全部原形。结构化 `form_of` 优先；没有就从散文抽 —— 判据②。

    抽全部而不是抽一个：`Forma del femenino de amado, participio de amar.`
    两个都是真原形（build.py A⑤ 也是收全部 base）。

    🔴 **`de/del` 后面的第一个词常常是语法词，不能"是语法词就放弃这一处"**，
       要**接着往后走**直到遇见非语法词：
         `Participio activo del verbo requerir.`  → del → verbo(语法词) → requerir ✓
         `... del presente de indicativo de charlear.` → 三处都走到 charlear
       早先在 `del verbo` 那一处直接放弃，这一族全部抽不出原形。
    ⚠️ **不剥括号**：`Dude (de dudar), con el enclítico lo.` 的原形就在括号里。
       括号里的代词列表（tú, vos）由 GRAM 挡住，不需要靠剥括号来防。
    """
    out = []
    for fo in (sense.get("form_of") or []) + (sense.get("alt_of") or []):
        w = (fo.get("word") or "").strip()
        if w and w not in out:
            out.append(w)
    if out:
        return out
    toks = _TOK.findall(gloss.replace("«", " ").replace("»", " "))
    for i, t in enumerate(toks):
        if t.lower() not in ("de", "del"):
            continue
        for nxt in toks[i + 1:]:
            low = nxt.lower()
            if low in ("de", "del"):
                break          # 下一处 de 自己会被扫到，这里不越界
            if low in GRAM or low in _CONN:
                continue
            if nxt not in out:
                out.append(nxt)
            break
    return out


_TOK = re.compile(r"[-\w'’´ˊ́]+", re.UNICODE)
_CONN = {"o", "y", "u", "e", "en", "con", "a", "al", "para", "por", "que", "como"}


def parse_form_gloss(gloss):
    """西语散文变形描述 → kaikki tag 列表（喂给 compose）。认不出返回 []。"""
    g = U.normalize("NFC", gloss.strip().lower())
    body = PAREN.sub(" ", g)
    tags = []

    for rx, tg in _NONFIN:
        if re.search(rx, body):
            tags.append(tg)
            break
    if "superlativo" in body:
        tags.append("superlative")
    if "diminutivo" in body:
        tags.append("diminutive")
    if "aumentativo" in body:
        tags.append("augmentative")

    for rx, tg in _PERSON:
        if re.search(rx, body):
            tags.append(tg)
            break
    if "gerund" not in tags and "participle" not in tags and "infinitive" not in tags:
        # `condicional` 在 kaikki 里是**语气**不是时态
        if "condicional" in body:
            tags.append("conditional")
        else:
            for rx, tg in _MOOD:
                if re.search(rx, body):
                    tags.append(tg)
                    break
            for rx, tg in _TENSE:
                if re.search(rx, body):
                    tags.append(tg)
                    break

    # 性/数：`Forma del femenino plural de X` / `del singular`。
    # ⚠️ 只在**原形之前**的那一段找 —— `Segunda persona del plural … de indicativo de X`
    #    的 plural 说的是主语数，同样是 number，两者在 compose 里是同一维度，不冲突。
    if re.search(r"\bfemenino\b", body):
        tags.append("feminine")
    elif re.search(r"\bmasculino\b", body):
        tags.append("masculine")
    if re.search(r"\bplural\b", body):
        tags.append("plural")
    elif re.search(r"\bsingular\b", body):
        tags.append("singular")

    if "enclítico" in g or "enclítica" in g:
        # 附着代词。«se» 是自复，其它人称代词只标"附着代词"（compose 认 reflexive）
        if "«se»" in g or " se " in g:
            tags.append("reflexive")
    return tags


def label_of(gloss):
    """中文语法标签。compose 组不出时回退 '变位形式'（与 build.py 同一个回退）。"""
    return compose(parse_form_gloss(gloss)) or "变位形式"


def pick_ipa(entry):
    """按源头自己的方言标签选一条读音，归一成本词典的裸音位串。

    与 `apply_edition_confirm.py` 用**完全相同**的表达式 —— 那套归一在 46.6 万个
    落点上与库内值 95.6% 逐字一致，是已验证过的转换，不另写一份。
    """
    v = K.sounds_variants(entry)
    if not v:
        return None, None

    def score(x):
        t = set(x[1])
        return len(t & WANT) * 2 - len(t & AVOID) * 2 + (1 if not t else 0)

    raw = max(v, key=score)[0]
    w = entry.get("word") or ""
    return canon_edition(N.normalize(w, canon_edition(raw))) or None, raw


# ═══ 扫描 ═══

def load_have():
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {w.lower() for (w,) in conn.execute("SELECT word FROM dict")}
    conn.close()
    return have


def new_rec(word):
    return {"word": word, "sp": [], "pos": [], "gl": [], "meta": [], "seen": [],
            "infl": [], "bases": [], "ipa": None, "ipa_raw": None, "audio": [],
            "n_form": 0, "n_real": 0}


def scan():
    have = load_have()
    recs = {}
    ledger = collections.Counter()      # 未归桶的 sense tag
    unparsed = collections.Counter()    # 组不出中文标签的散文骨架
    nobase = []
    n_es = 0

    for w, e in K.iter_edition():
        if e.get("lang_code") != "es":
            continue
        n_es += 1
        w = (w or "").strip()
        if not w or w.lower() in have:
            continue
        key = w.lower()
        r = recs.get(key)
        if r is None:
            r = recs[key] = new_rec(w)
        if w not in r["sp"]:
            r["sp"].append(w)
        pos = e.get("pos") or "unknown"
        p = POS_MAP.get(pos, pos)
        if p not in r["pos"]:
            r["pos"].append(p)
        if r["ipa"] is None:
            r["ipa"], r["ipa_raw"] = pick_ipa(e)
        for u, fn, _t in K.audio_urls(e):
            if u not in [a[0] for a in r["audio"]]:
                r["audio"].append((u, fn))

        ef = is_form_entry(e)
        for s in (e.get("senses") or []):
            g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
            if not g:
                continue
            if is_form_sense(s, ef):
                r["n_form"] += 1
                bs = bases_of(s, g)
                lab = label_of(g)
                if lab == "变位形式":
                    unparsed[re.sub(r"[a-záéíóúüñ'-]{3,}", "X", g)[:60]] += 1
                for b in bs:
                    if b not in r["bases"]:
                        r["bases"].append(b)
                for b in (bs or [None]):
                    line = ("%s 的 %s" % (b, lab)) if b else lab
                    if line not in r["infl"]:
                        r["infl"].append(line)
                if not bs:
                    nobase.append((w, g))
            else:
                r["n_real"] += 1
                if g in r["seen"]:
                    continue
                r["seen"].append(g)
                r["gl"].append(g)
                m = meta_of_edition(s, pos, e.get("tags") or ())
                top = [t for t in (s.get("topics") or [])]
                if top:
                    m["top"] = top[:2]
                m["src"] = "es-wiktionary"
                r["meta"].append(m)
                for tg in (s.get("tags") or []):
                    if tg not in _KNOWN:
                        ledger[tg] += 1

    for r in recs.values():
        r.pop("seen", None)
        # #6 显示拼写：同一个 key 有多种大小写时取小写常规形（与 build.py 同一条规则），
        # 否则 che/CHE/Che 会随扫描顺序显示成 CHE。
        if r["word"].lower() in r["sp"]:
            r["word"] = r["word"].lower()
        # 有真义 → lemma；没真义**也不是变形**（源头 no-gloss 的 2,696 个真动词）
        # → 也当 lemma、释义留空。与 build.py 对孤立真词的处置一致，别把词丢了。
        r["is_lemma"] = 1 if (r["n_real"] or not r["infl"]) else 0
    return recs, ledger, unparsed, nobase, n_es


from pipeline.build import (GENDER_COMMON, IGNORE_TAGS, NUMBER, REGIONS,  # noqa: E402
                            REGISTERS)
from pipeline.infl_compose import COMPOSE_TAGS  # noqa: E402

# ═══ 西语版的标签词汇 ═══
# 西语版用**自己一套**地名/语域命名，与英文版不是同一套字符串。全量普查（不是撞一个补一个）
# 得到 56 个库内白名单没有的 tag。两类处理：
#   · 同一个东西、两种叫法 → `ALIAS` 归一到库内已在用的那个（否则弹窗上
#     `Rioplatense` 和 `Río-de-la-Plata` 会并存，同一个地区显示成两个）；
#   · 库里根本没有的地区/语域 → 直接扩白名单。
ALIAS = {
    "Río-de-la-Plata": "Rioplatense",     # 英文版叫 Rioplatense
    "Canaries": "Canary-Islands",
    "America": "Latin-America",           # 西语 «América» 指美洲/拉美，非 US
    "Basque Country": "Basque-Country",
    "La Rioja": "La-Rioja", "Rioja": "La-Rioja",
    "La Rioja (Argentina)": "La-Rioja-Argentina",
    "outdated": "dated",                  # 英文版语域词是 dated
    "figurative": "figuratively",
    "jocular": "humorous",
    "euphemism": "euphemistic",
}
EXTRA_REGIONS = {
    "Chiloé", "Salamanca", "León", "Cantabria", "Murcia", "Yucatán", "Álava",
    "Hidalgo", "Extremadura", "Castile", "Southern-Chile", "South-Cone", "Navarra",
    "Burgos", "Zamora", "Mexico-City", "Palencia", "Basque-Country", "La-Rioja",
    "La-Rioja-Argentina", "Michoacán", "Grenada", "Cádiz", "Ceuta",
    "Northern-Argentina", "Guadalajara", "Chiapas", "Almería", "Soria",
    "San-Luis-Potosí", "Veracruz", "Oaxaca", "Campeche", "Jalisco", "Nuevo-León",
    "Guanajuato", "Córdoba", "Huelva", "Querétaro", "Central-Mexico",
    "Balearic-Islands", "Antioquia", "Northern-Chile", "Sinaloa", "Portugal",
    "Vizcaya",
}
EXTRA_REGISTERS = {"academic"}
ED_REGIONS = REGIONS | EXTRA_REGIONS
ED_REGISTERS = REGISTERS | EXTRA_REGISTERS

_KNOWN = (ED_REGIONS | ED_REGISTERS | NUMBER | GENDER_COMMON | IGNORE_TAGS
          | {"feminine", "masculine", "adverb"} | set(COMPOSE_TAGS) | set(ALIAS))


def meta_of_edition(sense, pos, entry_tags=()):
    """西语版义项 → meta。先把标签归一到库内词汇，再交 build.meta_of 归桶。

    不复制 build.meta_of 的逻辑，只在它前面加一层标签翻译 —— 性别/数/语域的归桶规则
    只能有一份实现，两份迟早分叉。

    🔴 `entry_tags` 不能省：**西语版的性别标在条目级，不在义项级**
       （`perro` 的 senses 里一个 masculine 都没有，`tags:["masculine"]` 在条目顶层）。
       只读 sense.tags 时，新收的 1.2 万个普通名词性别全空。
    """
    s = dict(sense)
    s["tags"] = [ALIAS.get(t, t)
                 for t in list(sense.get("tags") or []) + list(entry_tags or [])]
    m = meta_of(s, pos)
    # build.meta_of 用的是英文版白名单，西语版新增的地区/语域它认不出来 → 这里补齐
    t = set(s["tags"])
    reg = sorted(t & ED_REGIONS)
    if reg:
        m["reg"] = reg
    lex = sorted(t & ED_REGISTERS)
    if lex:
        m["lex"] = lex
    return m


def bucket(w, havek):
    if " " in w or "-" in w:
        return "④ 多词/连字符"
    if unaccent(w) in havek:
        return "① 仅重音/写法不同"
    if w[:1].isupper():
        return "⑤ 专名"
    return "⑥ 单词条目"


def report(recs, ledger, unparsed, nobase, n_es):
    have = load_have()
    havek = {unaccent(w) for w in have}
    lem = {k: r for k, r in recs.items() if r["is_lemma"]}
    inf = {k: r for k, r in recs.items() if not r["is_lemma"] and r["infl"]}
    shell = {k: r for k, r in lem.items() if not r["gl"]}
    print("■ 西语版西语条目 {:,} → 库里没有的词形 {:,}".format(n_es, len(recs)))
    print("    真 lemma {:,}（义项 {:,}）| 纯变形 {:,} | 空壳（源头 no-gloss）{:,}".format(
        len(lem), sum(len(r["gl"]) for r in lem.values()), len(inf), len(shell)))
    sp = collections.Counter(p for r in shell.values() for p in r["pos"])
    print("    空壳的词性：{}".format(dict(sp.most_common(5))))

    b = collections.Counter()
    for k, r in lem.items():
        b[bucket(r["word"], havek)] += 1
    print("\n■ 真 lemma 的成分")
    for k in sorted(b):
        print("    {:8,}  {}".format(b[k], k))

    nouns = [m for r in lem.values() for m in r["meta"] if m.get("pos") in ("n", "name")]
    print("\n■ 名词/专名义项 {:,}，其中带性别 {:,} ({:.1f}%)".format(
        len(nouns), sum(1 for m in nouns if m.get("g")),
        sum(1 for m in nouns if m.get("g")) * 100 / max(len(nouns), 1)))
    tmpl = collections.Counter()
    for r in lem.values():
        if bucket(r["word"], havek) == "⑤ 专名":
            for g in r["gl"]:
                tmpl[g[:40]] += 1
    nt = sum(tmpl.values())
    print("■ ⑤ 专名的释义模板（共 {:,} 义项，前 8 种覆盖 {:.1f}%）".format(
        nt, sum(c for _, c in tmpl.most_common(8)) * 100 / max(nt, 1)))
    for t, c in tmpl.most_common(8):
        print("    {:7,}  {}".format(c, t))

    ipa = sum(1 for r in recs.values() if r["ipa"])
    aud = sum(1 for r in recs.values() if r["audio"])
    print("\n■ 随词白送：音标 {:,} ({:.2f}%) | 录音 {:,}".format(
        ipa, ipa * 100 / max(len(recs), 1), aud))

    nb = sum(1 for r in inf.values() if not r["bases"])
    print("\n■ 指针：纯变形 {:,} 中抽不出原形 {:,} ({:.2f}%)".format(
        len(inf), nb, nb * 100 / max(len(inf), 1)))
    allw = have | set(recs)
    dang = collections.Counter()
    for r in recs.values():
        for x in r["bases"]:
            dang["在库内" if x.lower() in have
                 else "在本次新收内" if x.lower() in allw else "🔴 悬空"] += 1
    tot = sum(dang.values())
    for k, v in dang.most_common():
        print("    {:8,} ({:5.1f}%)  {}".format(v, v * 100 / max(tot, 1), k))

    if ledger:
        print("\n⚠ 真义义项上未归桶的 tag {} 种（前 20）".format(len(ledger)))
        for t, c in ledger.most_common(20):
            print("    {:7,}  {}".format(c, t))
    else:
        print("\n✓ 真义 tag 全部已归桶")

    if unparsed:
        n = sum(unparsed.values())
        print("\n⚠ 组不出中文语法标签的变形义项 {:,} 条 / {} 种骨架（前 12）".format(
            n, len(unparsed)))
        for t, c in unparsed.most_common(12):
            print("    {:7,}  {}".format(c, t))

    random.seed(3)
    print("\n■ 抽样：新收变形（词 / 中文标签 / 原形）")
    pick = random.sample([r for r in inf.values() if r["infl"]], 10)
    for r in pick:
        print("    {:22} {}".format(r["word"], r["infl"][0][:64]))
    print("\n■ 抽样：新收 lemma（词 / 词性 / 音标 / 西语版释义）")
    for r in random.sample(list(lem.values()), 10):
        print("    {:18} {:6} {:20} {}".format(
            r["word"][:18], "/".join(r["pos"])[:6], (r["ipa"] or "—")[:20],
            r["gl"][0][:58]))
    if nobase:
        print("\n■ 抽样：抽不出原形的变形 {} 条".format(len(nobase)))
        for w, g in random.sample(nobase, min(6, len(nobase))):
            print("    {:20} {}".format(w[:20], g[:70]))


# ═══ 落库 ═══

INSERT_COLS = ("word", "word_norm", "phonetic", "phonetic_raw", "phonetic_src",
               "pos", "is_lemma", "reflexive", "definition_es", "translation",
               "meta", "infl", "exchange")
REFLEX = re.compile(r"(?:ar|er|ir)se$")


def build_rows(recs, have):
    """暂存记录 → 待插入的行。**指针四种情况一条都不扔，但绝不把变形当 lemma。**

        有指针、原形在库内            → exchange = 0:原形
        有指针、原形在本次新收内      → exchange = 0:原形（连原形一起收，86.7%）
        有指针、原形两边都没有        → exchange 不写这一条，`infl` 里的文字仍在（3.6%）
        无指针（6 条）                → is_lemma=0，只留 pos 与音标
    """
    allw = have | set(recs)
    rows, stat = [], collections.Counter()
    for r in recs.values():
        w = r["word"]
        keep = [b for b in r["bases"] if b.lower() in allw]
        stat["悬空指针"] += len(r["bases"]) - len(keep)
        is_lemma = r["is_lemma"]
        gl = "\n".join(r["gl"]) if r["gl"] else None
        meta = json.dumps(r["meta"], ensure_ascii=False) if r["meta"] else None
        infl = "\n".join(r["infl"]) if r["infl"] else None
        # 纯变形行：translation 直接 = infl（沿用 build.py 的约定，展示层不用分叉）
        # lemma 行：translation 留空，交后面的 flash 批次填
        tr = None if is_lemma else infl
        rows.append((
            w, unaccent(w), r["ipa"], r.get("ipa_raw"),
            "es-edition" if r["ipa"] else None,
            "/".join(r["pos"]) if r["pos"] else None, is_lemma,
            1 if ("v" in r["pos"] and REFLEX.search(w)) else None,
            gl, tr, meta, infl,
            "\n".join("0:%s" % b for b in keep) if keep else None,
        ))
        stat["lemma" if is_lemma else "变形"] += 1
        for i, c in enumerate(INSERT_COLS):
            if rows[-1][i] not in (None, ""):
                stat["col:" + c] += 1
    return rows, stat


def apply(dry):
    recs = {}
    for ln in open(STAGE, encoding="utf-8"):
        r = json.loads(ln)
        recs[r["word"].lower()] = r
    have = load_have()
    dup = [w for w in recs if w in have]
    if dup:
        raise SystemExit("🔴 暂存里有 %d 个词形库里已经有了（暂存过期？先重跑 --scan）" % len(dup))
    rows, stat = build_rows(recs, have)

    expect = {"__rows__": len(rows)}
    for c in INSERT_COLS:
        if c in ("word", "word_norm", "is_lemma", "reflexive"):
            continue                     # 不在 TRACK 里
        expect[c] = stat["col:" + c]
    print("■ 待插入 {:,} 行（lemma {:,} / 变形 {:,}），丢弃悬空指针 {:,} 条".format(
        len(rows), stat["lemma"], stat["变形"], stat["悬空指针"]))
    print("■ 各列期望非空增量")
    for c, v in sorted(expect.items()):
        print("    {:16} {:+,}".format(c, v))

    dbtool.sample_check(
        [(r[0], r[5], r[2] or "—", (r[8] or r[11] or "")[:40], (r[12] or "").replace("\n", ","))
         for r in rows], n=12, cols=("词", "词性", "音标", "释义/变形", "指针"))

    if dry:
        print("\n(试算完毕。加 --apply 落库)")
        return
    with dbtool.session("edition-intake", expect=expect) as s:
        s.addcolumn("definition_es")
        s.executemany(
            "INSERT INTO dict (%s) VALUES (%s)" % (
                ",".join(INSERT_COLS), ",".join("?" * len(INSERT_COLS))), rows)
    dbtool.align_check()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--dry", action="store_true", help="试算落库，不写")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if a.dry or a.apply:
        apply(dry=not a.apply)
        return

    if a.scan:
        recs, ledger, unparsed, nobase, n_es = scan()
        STAGE.parent.mkdir(parents=True, exist_ok=True)
        with open(STAGE, "w", encoding="utf-8") as f:
            for r in recs.values():
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        report(recs, ledger, unparsed, nobase, n_es)
        print("\n→ 暂存 {}（{:,} 条，未写库）".format(STAGE, len(recs)))
        return

    if a.plan:
        recs = {}
        for ln in open(STAGE, encoding="utf-8"):
            r = json.loads(ln)
            recs[r["word"].lower()] = r
        report(recs, collections.Counter(), collections.Counter(), [], 853355)
        return

    ap.print_help()


if __name__ == "__main__":
    main()
