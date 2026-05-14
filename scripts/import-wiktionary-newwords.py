"""
从 kaikki.org Wiktionary JSONL 导入新词到 SQLite

功能：
  扫描 Wiktionary 导出的 JSONL 文件，提取 SQLite 词典中不存在的新单词，
  包括英文释义、英美音标、词性、词形变化等字段，批量插入数据库。

数据来源：
  kaikki.org-dictionary-English.jsonl（约 2.7GB，135万条英文词条）
  下载地址：https://kaikki.org/dictionary/English/

提取字段：
  - word        → 单词原文
  - definition  → 英文释义（取前5条 gloss）
  - phonetic_uk → 英式 IPA 音标（从 sounds 中按 Received-Pronunciation/UK 标签提取）
  - phonetic_us → 美式 IPA 音标（从 sounds 中按 General-American/US 标签提取）
  - pos         → 词性（映射为 ECDICT 格式：n/v/j/r/p/u/m/i）
  - exchange    → 词形变化（复数 s:、过去式 p:、过去分词 d:、现在分词 i:、三单 3:、比较级 r:、最高级 t:）

注意：
  - translation（中文释义）留空，后续用 fetch-translation-batch.py 批量补充
  - 同一单词不同词性的条目会合并为一条记录
  - 已存在于 SQLite 中的单词会跳过

用法：python scripts/import-wiktionary-newwords.py
"""

import json
import sqlite3

from paths import DB_PATH, KAIKKI_JSONL_PATH

JSONL_PATH = KAIKKI_JSONL_PATH

UK_TAGS = {"Received-Pronunciation", "UK"}
US_TAGS = {"General-American", "US"}

POS_MAP = {
    "noun": "n",
    "verb": "v",
    "adj": "j",
    "adjective": "j",
    "adverb": "r",
    "pronoun": "p",
    "interjection": "u",
    "numeral": "m",
    "preposition": "i",
    "conjunction": "i",
    "determiner": "i",
    "particle": "i",
    "prefix": "n",
    "suffix": "n",
    "phrase": "n",
    "proper name": "n",
    "contraction": "n",
}


def main():
    print(f"JSONL: {JSONL_PATH}")
    print(f"DB:    {DB_PATH}")

    # 加载现有词表
    print("加载 SQLite 词表...")
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("SELECT word FROM stardict").fetchall()
    existing = {w[0].lower() for w in rows}
    conn.close()
    print(f"现有词表: {len(existing)}")

    # 扫描提取新词
    print("\n扫描 JSONL 提取新词...")
    new_words = {}  # key -> dict
    count = 0

    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if data.get("lang_code") != "en":
                continue
            if data.get("source") == "thesaurus":
                continue

            word = data.get("word", "").strip()
            if not word:
                continue

            key = word.lower()
            if key in existing:
                continue

            # 提取释义
            senses = data.get("senses", [])
            glosses = []
            for s in senses:
                for g in s.get("glosses", []):
                    glosses.append(g)

            definition = "\n".join(glosses[:5]) if glosses else ""

            # 提取音标
            sounds = data.get("sounds", [])
            ph_uk = None
            ph_us = None
            ph_fallback = None

            for s in sounds:
                ipa = s.get("ipa")
                if not ipa:
                    continue
                cleaned = ipa.split(",")[0].strip("/[] ")
                if not cleaned:
                    continue
                tags = set(s.get("tags", []))
                if not ph_uk and tags & UK_TAGS:
                    ph_uk = cleaned
                if not ph_us and tags & US_TAGS:
                    ph_us = cleaned
                if not ph_fallback and not tags:
                    ph_fallback = cleaned

            if not ph_uk and ph_fallback:
                ph_uk = ph_fallback
            if not ph_us and ph_fallback:
                ph_us = ph_fallback

            # 词性
            pos_raw = data.get("pos", "").lower()
            pos = POS_MAP.get(pos_raw, "")

            # 词形变化
            forms = data.get("forms", [])
            exchange_parts = []
            for fm in forms:
                form_word = fm.get("form", "")
                tags = fm.get("tags", [])
                if not form_word or not tags:
                    continue
                if "plural" in tags:
                    exchange_parts.append(f"s:{form_word}")
                elif "past" in tags and "participle" not in tags:
                    exchange_parts.append(f"p:{form_word}")
                elif "past" in tags and "participle" in tags:
                    exchange_parts.append(f"d:{form_word}")
                elif "present" in tags and "participle" in tags:
                    exchange_parts.append(f"i:{form_word}")
                elif "third-person" in tags and "singular" in tags:
                    exchange_parts.append(f"3:{form_word}")
                elif "comparative" in tags:
                    exchange_parts.append(f"r:{form_word}")
                elif "superlative" in tags:
                    exchange_parts.append(f"t:{form_word}")
            exchange = "/".join(exchange_parts) if exchange_parts else ""

            if key not in new_words:
                new_words[key] = {
                    "word": word,
                    "definition": definition,
                    "phonetic_uk": ph_uk,
                    "phonetic_us": ph_us,
                    "pos": f"{pos}:100" if pos else "",
                    "exchange": exchange,
                }
            else:
                # 合并同词不同词性
                entry = new_words[key]
                if definition and not entry["definition"]:
                    entry["definition"] = definition
                if ph_uk and not entry["phonetic_uk"]:
                    entry["phonetic_uk"] = ph_uk
                if ph_us and not entry["phonetic_us"]:
                    entry["phonetic_us"] = ph_us
                if exchange and not entry["exchange"]:
                    entry["exchange"] = exchange

            count += 1
            if count % 100000 == 0:
                print(f"  已扫描 {count} 条...")

    print(f"共扫描 {count} 条新词条，去重后 {len(new_words)} 个")

    has_def = sum(1 for v in new_words.values() if v["definition"])
    has_uk = sum(1 for v in new_words.values() if v["phonetic_uk"])
    has_us = sum(1 for v in new_words.values() if v["phonetic_us"])
    has_exchange = sum(1 for v in new_words.values() if v["exchange"])
    print(f"有释义: {has_def}, 有英式音标: {has_uk}, 有美式音标: {has_us}, 有词形变化: {has_exchange}")

    # 写入 SQLite
    print("\n写入 SQLite...")
    batch = [
        (
            v["word"],
            v["phonetic_uk"],  # phonetic 字段留空，用新字段
            v["definition"],
            None,  # translation 后续用大模型补
            v["pos"],
            v["exchange"],
            v["phonetic_uk"],
            v["phonetic_us"],
        )
        for v in new_words.values()
    ]

    print(f"待插入 {len(batch)} 条")

    conn = sqlite3.connect(str(DB_PATH))
    conn.executemany(
        """INSERT INTO stardict (word, phonetic, definition, translation, pos, exchange, phonetic_uk, phonetic_us)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        batch,
    )
    conn.commit()
    conn.close()
    print("写入完成")

    # 最终统计
    conn = sqlite3.connect(str(DB_PATH))
    r = conn.execute("SELECT COUNT(*) FROM stardict").fetchone()
    conn.close()
    print(f"\n最终词表总数: {r[0]}")


if __name__ == "__main__":
    main()
