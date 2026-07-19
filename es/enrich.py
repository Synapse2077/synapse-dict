"""
西班牙语词典「原地补一等本质字段」——不重建、不搬运，只在现有库上长新列。

背景：es 库是第一代 schema（翻译/释义/音标/搭配齐全但缺本质列）。本脚本：
  ① ALTER TABLE 加新列（gender/plural/feminine/conjugation/stem_change/pp/transitivity/comparative/level）
  ② 读 kaikki 源，按 word 建 essence 映射，UPDATE 回填（确定性、免费）
  · definition/translation/meta 等付费数据**一律不动**（复制副本上操作，原库保留）

西语本质（相对法语模子：删 aux/介词支配/形位；加 stem_change 词干变化）：
  · 名词：gender(el/la m/f/mf)、plural(不规则)、feminine(actor→actriz)  ← 从 es-noun expansion
  · 动词：conjugation(-ar/-er/-ir)、pp(过去分词，不规则)、transitivity(t/i)、
          stem_change(e→ie/o→ue/e→i/u→ue，由 3 单现在时对比词干派生)  ← 西语招牌
  · 形容词：feminine(rojo→roja)、comparative(bueno→mejor 硬编码)
  · CEFR level 交豆包（本脚本不填）；双音 España/América 由 spanish.ts 按 θ→s 规则派生（不入库）

用法（在 es/ 目录）：python3 enrich.py            # 补 es/synapse-dict-es.new.sqlite
                    python3 enrich.py --db 路径   # 指定库
"""

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
JSONL_PATH = HERE / "kaikki.org-dictionary-Spanish.jsonl"
DEFAULT_DB = HERE / "synapse-dict-es.new.sqlite"

ES_ALPHA = "A-Za-záéíóúñüÁÉÍÓÚÑÜ"
WORDRE = f"[{ES_ALPHA}][{ES_ALPHA}\\-]*"

NEW_COLS = [
    ("gender", "TEXT"), ("plural", "TEXT"), ("feminine", "TEXT"),
    ("conjugation", "TEXT"), ("stem_change", "TEXT"), ("pp", "TEXT"),
    ("transitivity", "TEXT"), ("comparative", "TEXT"), ("level", "TEXT"),
]

# 不规则比较级（西语少数，纯记忆，确定性硬编码）。adj + adv。
COMPARATIVE_IRREGULAR = {
    "bueno": "mejor", "malo": "peor", "grande": "mayor", "pequeño": "menor",
    "bien": "mejor", "mal": "peor", "mucho": "más", "poco": "menos",
    "alto": "superior", "bajo": "inferior",
}


def head_exp(e, name):
    for h in e.get("head_templates") or []:
        if h.get("name") == name:
            return h.get("expansion") or ""
    return ""


def _first(pat, s):
    m = re.search(pat, s)
    return m.group(1) if m else None


def extract_noun(e, word):
    """从 es-noun expansion 抽 gender/plural/feminine。
    例：'actor m (plural actores, feminine actriz, feminine plural actrices)'。"""
    exp = head_exp(e, "es-noun")
    gender = plural = feminine = None
    if exp:
        head = exp.split("(")[0]
        after = head[len(word):] if head.startswith(word) else head
        gs = [t for t in re.split(r"[\s,]+", after) if t in ("m", "f", "mf")]
        if gs:
            gender = "mf" if ("m" in gs and "f" in gs) or "mf" in gs else gs[0]
        pl = _first(rf"plural ({WORDRE})", exp)
        # 'plural only'（plurale tantum）/'plural invariable' 非真实复数形，拦掉
        if (pl and pl.lower() not in ("only", "invariable", "none", "singular")
                and pl.lower() != (word.lower() + "s")):
            plural = pl                                   # 只收不规则/非 +s
        # feminine（排除 'feminine plural'）
        fem = _first(rf"feminine ({WORDRE})", exp)
        if fem and not re.search(rf"feminine plural {re.escape(fem)}", exp):
            # 确认捕获的不是 'plural' 这个词本身
            if fem != "plural":
                feminine = fem
    return gender, plural, feminine


def gender_from_meta(meta_json):
    """兜底：从已有 meta 的逐义项 g 聚合出词级性别。"""
    try:
        arr = json.loads(meta_json) if meta_json else []
    except Exception:
        return None
    gs = {m.get("g") for m in arr if isinstance(m, dict) and m.get("g")}
    if not gs:
        return None
    if "mf" in gs or gs == {"m", "f"}:
        return "mf"
    if gs == {"m"}:
        return "m"
    if gs == {"f"}:
        return "f"
    if gs == {"n"}:
        return "n"
    return "mf"


def form_by_tags(e, want, without=()):
    want, without = set(want), set(without)
    for fm in e.get("forms") or []:
        tags = set(fm.get("tags") or [])
        if {"table-tags", "inflection-template"} & tags:
            continue
        if want <= tags and not (without & tags):
            f = (fm.get("form") or "").strip()
            if f and re.fullmatch(WORDRE, f):
                return f
    return None


VOWEL_SUBS = [("e", "ie"), ("o", "ue"), ("u", "ue"), ("e", "i"), ("i", "ie")]


def extract_stem_change(word, e):
    """词干变化：3 单现在时词干 vs 不定式词干比对，识别 e→ie/o→ue/e→i/u→ue。
    3 单形（piensa/duerme/pide/juega）去尾元音得现在词干，与不定式词干比。"""
    m = re.match(r"^(.*?)(ar|er|ir|ír)(se)?$", word)
    if not m:
        return None
    inf_stem = m.group(1)
    p3 = form_by_tags(e, ["present", "indicative", "singular", "third-person"])
    if not p3 or len(p3) < 2:
        return None
    pres_stem = p3[:-1]                      # 去 3 单尾元音 a/e
    if pres_stem == inf_stem:
        return None
    for base, dip in VOWEL_SUBS:
        idx = inf_stem.rfind(base)
        if idx != -1 and inf_stem[:idx] + dip + inf_stem[idx + 1:] == pres_stem:
            return f"{base}→{dip}"
    return None


def extract_pp(word, e):
    """过去分词（阳单）；仅收不规则（≠ 词干+ado/ido）。roto/escrito/visto/hecho…"""
    pp = form_by_tags(e, ["participle", "past"],
                      without=["feminine", "plural"])
    if not pp:
        return None
    m = re.match(r"^(.*?)(ar|er|ir|ír)(se)?$", word)
    if m:
        stem = m.group(1)
        regular = stem + ("ado" if m.group(2) == "ar" else "ido")
        if pp.lower() == regular.lower():
            return None                       # 规则，不收
    return pp


def extract_adj_feminine(e, word):
    """形容词阴性单数（rojo→roja、español→española）。同形/不变则无。"""
    exp = head_exp(e, "es-adj")
    if exp:
        fem = _first(rf"feminine ({WORDRE})", exp)
        if fem and fem != "plural" and not re.search(rf"feminine plural {re.escape(fem)}", exp):
            return fem
    return form_by_tags(e, ["feminine", "singular"], without=["plural"]) \
        or form_by_tags(e, ["feminine"], without=["plural"])


def main(db_path):
    if not JSONL_PATH.exists():
        raise SystemExit(f"缺少 dump: {JSONL_PATH}")
    if not Path(db_path).exists():
        raise SystemExit(f"缺少库: {db_path}（先 cp 现有库成副本）")
    print(f"读取源: {JSONL_PATH}")

    # word.lower() → essence（首见优先，与 build 一致）
    ess = {}
    total = 0
    for line in open(JSONL_PATH, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("lang_code") != "es":
            continue
        word = (e.get("word") or "").strip()
        if not word:
            continue
        total += 1
        key = word.lower()
        rec = ess.setdefault(key, {})
        pos = e.get("pos", "")

        if pos in ("noun", "name"):
            g, pl, fem = extract_noun(e, word)
            if g and not rec.get("gender"):
                rec["gender"] = g
            if pl and not rec.get("plural"):
                rec["plural"] = pl
            if fem and not rec.get("feminine"):
                rec["feminine"] = fem
        elif pos == "verb":
            if not rec.get("conjugation"):
                mm = re.search(r"(ar|er|ir|ír)(se)?$", word)
                if mm:
                    rec["conjugation"] = {"ar": "1", "er": "2", "ir": "3", "ír": "3"}[mm.group(1)]
            sc = extract_stem_change(word, e)
            if sc and not rec.get("stem_change"):
                rec["stem_change"] = sc
            pp = extract_pp(word, e)
            if pp and not rec.get("pp"):
                rec["pp"] = pp
            tr = set()
            for s in e.get("senses", []):
                t = s.get("tags", [])
                if "transitive" in t:
                    tr.add("t")
                if "intransitive" in t:
                    tr.add("i")
                if "ambitransitive" in t:
                    tr.update(("t", "i"))
            if tr and not rec.get("transitivity"):
                rec["transitivity"] = "ti" if tr == {"t", "i"} else next(iter(tr))
        elif pos == "adj":
            fem = extract_adj_feminine(e, word)
            if fem and not rec.get("feminine"):
                rec["feminine"] = fem
        # 不规则比较级（与词性无关，按词）
        if word.lower() in COMPARATIVE_IRREGULAR and not rec.get("comparative"):
            rec["comparative"] = COMPARATIVE_IRREGULAR[word.lower()]

    print(f"  扫描 es 条目 {total}，得 essence 词 {len(ess)}")

    # —— 加列 + 回填 ——
    conn = sqlite3.connect(str(db_path))
    have = {r[1] for r in conn.execute("PRAGMA table_info(dict)")}
    for col, typ in NEW_COLS:
        if col not in have:
            conn.execute(f"ALTER TABLE dict ADD COLUMN {col} {typ}")
    conn.commit()

    rows = conn.execute("SELECT id, word, pos, meta FROM dict").fetchall()
    stat = Counter()
    for rid, word, pos, meta in rows:
        posset = set(pos.split("/")) if pos else set()
        rec = ess.get((word or "").lower(), {})
        sets, vals = [], []

        def put(col, v):
            sets.append(f"{col}=?"); vals.append(v); stat[col] += 1

        # gender：kaikki 优先，兜底用已有 meta 聚合（名词/专名）
        if {"n", "name"} & posset:
            g = rec.get("gender") or gender_from_meta(meta)
            if g:
                put("gender", g)
            if rec.get("plural"):
                put("plural", rec["plural"])
            if rec.get("feminine"):
                put("feminine", rec["feminine"])
        if "v" in posset:
            if rec.get("conjugation"):
                put("conjugation", rec["conjugation"])
            if rec.get("stem_change"):
                put("stem_change", rec["stem_change"])
            if rec.get("pp"):
                put("pp", rec["pp"])
            if rec.get("transitivity"):
                put("transitivity", rec["transitivity"])
        if "adj" in posset and rec.get("feminine"):
            put("feminine", rec["feminine"])
        if rec.get("comparative") and (posset & {"adj", "adv"}):
            put("comparative", rec["comparative"])

        if sets:
            vals.append(rid)
            conn.execute(f"UPDATE dict SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()
    print("回填完成：" + " | ".join(f"{k} {v}" for k, v in stat.most_common()))
    print("下一步：spanish.ts/视图接新列；豆包只补 level(CEFR)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    main(args.db)
