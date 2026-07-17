"""
意大利语词典建库：kaikki.org (Wiktextract) JSONL → synapse-dict-it.sqlite

独立脚本，不与英语管线共用（每语言各自一套）。

策略（基于对西语 kaikki 结构的实测）：
  - 变位形式(senses 全是 form_of，占 ~28%)：作为独立词条收录，
    translation 直接用 tags 生成中文「原形 的 XX 变位」（web 端会把原形渲染成可点链接），
    不送豆包、不做 patch。
  - lemma(有实义 gloss，占 ~71%)：translation 留空，交给 translate.py 用豆包补中文。
  - definition 存英语 gloss（校验锚点 + 外文释义展示）。
  - phonetic 取 sounds 里第一个 /.../ IPA（西语单一 IPA，覆盖 ~83%）。

schema 沿用英语 stardict 表名/列名，让 web 的 api/synapse-dict.ts 零改动兼容。

用法：python3 build.py
产物：synapse-dict-it.sqlite（与本脚本同目录）
"""

import json
import sqlite3
import collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
JSONL_PATH = HERE / "kaikki.org-dictionary-Italian.jsonl"
DB_PATH = HERE / "synapse-dict-it.sqlite"

# kaikki pos → 展示用简写（供内部；实际词性加粗靠 translation 文本开头）
POS_MAP = {
    "noun": "n", "verb": "v", "adj": "adj", "adv": "adv",
    "pron": "pron", "prep": "prep", "conj": "conj", "det": "det",
    "num": "num", "intj": "intj", "name": "name",
    "prefix": "pref", "suffix": "suf", "phrase": "phr",
}

# ---- 变位 tag → 中文（西语语法术语）----
PERSON = {"first-person": "第一人称", "second-person": "第二人称", "third-person": "第三人称"}
NUMBER = {"singular": "单数", "plural": "复数"}
TENSE = {
    "present": "现在时", "preterite": "简单过去时", "imperfect": "未完成过去时",
    "future": "将来时", "conditional": "条件式", "past": "过去时",
}
MOOD = {"indicative": "陈述式", "subjunctive": "虚拟式", "imperative": "命令式"}
NONFINITE = {"infinitive": "不定式", "gerund": "副动词", "participle": "分词"}
GENDER = {"masculine": "阳性", "feminine": "阴性"}
EXTRA = {"with-voseo": "（voseo）", "formal": "（尊称）", "informal": "（非正式）",
         "negative": "否定", "augmentative": "增大式", "diminutive": "指小式"}

# 拼接顺序：人称 → 数 → 时 → 语气 → 非限定 → 性 → 附加
ORDERED = [PERSON, NUMBER, TENSE, MOOD, NONFINITE, GENDER, EXTRA]


def infl_desc_zh(tags):
    """把变位 tags 拼成中文变位描述，如 ['present','second-person','singular','subjunctive'] → 第二人称单数现在时虚拟式"""
    tagset = set(tags)
    parts = []
    for mapping in ORDERED:
        for k, zh in mapping.items():
            if k in tagset:
                parts.append(zh)
    # 过去分词特判：past + participle → 过去分词
    if "participle" in tagset and "past" in tagset:
        return "过去分词" + ("（阴性）" if "feminine" in tagset else "")
    return "".join(parts)


def pick_ipa(sounds):
    """取第一个 /音位/ 形式的 IPA；退回方括号形式。"""
    fallback = None
    for s in sounds or []:
        ipa = s.get("ipa")
        if not ipa:
            continue
        ipa = ipa.strip()
        if ipa.startswith("/"):
            return ipa
        if fallback is None:
            fallback = ipa
    return fallback


def glosses_of(senses):
    gl = []
    for s in senses:
        for g in s.get("glosses", []):
            gl.append(g)
    return gl


def main():
    if not JSONL_PATH.exists():
        raise SystemExit(f"缺少 dump: {JSONL_PATH}")

    print(f"读取: {JSONL_PATH}")
    words = {}  # word.lower() -> record
    total = bad = 0
    n_infl = n_lemma = 0

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

            pos = POS_MAP.get(e.get("pos", ""), e.get("pos", ""))
            senses = e.get("senses", [])
            ipa = pick_ipa(e.get("sounds"))

            is_infl = bool(senses) and all(
                s.get("form_of") or s.get("alt_of") for s in senses
            )

            key = word.lower()
            rec = words.get(key)
            if rec is None:
                rec = {"word": word, "phonetic": None, "definition": [],
                       "infl_desc": [], "pos": set(), "exchange": None, "is_lemma": False}
                words[key] = rec

            if ipa and not rec["phonetic"]:
                rec["phonetic"] = ipa
            if pos:
                rec["pos"].add(pos)

            if is_infl:
                # 变位形式：生成中文「原形 的 XX」，指回 lemma
                for s in senses:
                    fo = s.get("form_of") or s.get("alt_of") or []
                    lemma = fo[0].get("word") if fo else None
                    if not lemma:
                        continue
                    desc = infl_desc_zh(s.get("tags", []))
                    zh = f"{lemma} 的 {desc}" if desc else f"{lemma} 的变位形式"
                    # 只存到 infl_desc；是否用作 translation 由组装阶段按 is_lemma 决定，
                    # 避免污染「既是 lemma 又是他词变位」的词（如 casa=房子/也是 casar 变位）导致漏翻。
                    if zh not in rec["infl_desc"]:
                        rec["infl_desc"].append(zh)
                    if rec["exchange"] is None:
                        rec["exchange"] = f"0:{lemma}"
            else:
                # lemma：definition 存英语释义，translation 待豆包
                rec["is_lemma"] = True
                for g in glosses_of(senses)[:6]:
                    if g not in rec["definition"]:
                        rec["definition"].append(g)

    # 统计
    for rec in words.values():
        if rec["is_lemma"]:
            n_lemma += 1
        else:
            n_infl += 1

    print(f"总行数 {total} (解析失败 {bad}) → 去重词条 {len(words)}")
    print(f"  lemma(送豆包) {n_lemma} | 变位(已填中文) {n_infl}")

    # 写库
    print(f"写入: {DB_PATH}")
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(
        """
        CREATE TABLE stardict (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          word TEXT NOT NULL,
          phonetic TEXT,
          phonetic_uk TEXT,
          phonetic_us TEXT,
          definition TEXT,
          translation TEXT,
          pos TEXT,
          tag TEXT,
          exchange TEXT
        );
        """
    )
    batch = []
    for rec in words.values():
        batch.append((
            rec["word"],
            rec["phonetic"],
            "\n".join(rec["definition"]) if rec["definition"] else None,
            (None if rec["is_lemma"]
             else ("\n".join(rec["infl_desc"]) if rec["infl_desc"] else None)),  # lemma 留空待豆包；纯变位=中文描述
            "/".join(sorted(rec["pos"])) if rec["pos"] else None,
            rec["exchange"],
        ))
    conn.executemany(
        "INSERT INTO stardict (word, phonetic, definition, translation, pos, exchange) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        batch,
    )
    conn.commit()
    conn.execute("CREATE INDEX idx_word ON stardict(word COLLATE NOCASE)")
    conn.commit()
    conn.close()
    print("完成。下一步：python3 translate.py 用豆包补 lemma 中文释义")


if __name__ == "__main__":
    main()
