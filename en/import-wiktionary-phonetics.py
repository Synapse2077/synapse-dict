"""
从 kaikki.org Wiktionary JSONL 提取英美音标，更新到 SQLite

功能：
  扫描 Wiktionary 导出的 JSONL 文件，提取 SQLite 词典中已有单词的
  英式（Received-Pronunciation/UK）和美式（General-American/US）IPA 音标，
  批量更新到 phonetic_uk 和 phonetic_us 字段。

实现方式：
  使用 SQLite 临时表 + JOIN UPDATE 进行批量更新，避免逐条 UPDATE 的性能问题。

数据来源：
  kaikki.org-dictionary-English.jsonl（约 2.7GB）

注意：
  - 只更新 SQLite 中已存在的单词，不会新增记录
  - 如果 Wiktionary 中只有无标签的 IPA，会作为兜底同时填入英式和美式
  - 原有 phonetic 字段不受影响

用法：python scripts/import-wiktionary-phonetics.py
"""

import json
import sqlite3

from paths import DB_PATH, KAIKKI_JSONL_PATH

JSONL_PATH = KAIKKI_JSONL_PATH

UK_TAGS = {"Received-Pronunciation", "UK"}
US_TAGS = {"General-American", "US"}


def main():
    print(f"JSONL: {JSONL_PATH}")
    print(f"DB:    {DB_PATH}")

    if not JSONL_PATH.exists():
        print(f"文件不存在: {JSONL_PATH}")
        return

    # 先加载 SQLite 词表用于匹配
    print("加载 SQLite 词表...")
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("SELECT word FROM stardict").fetchall()
    # lower -> 原始 word 的映射
    word_map = {}
    for (w,) in rows:
        word_map[w.lower()] = w
    conn.close()
    print(f"SQLite 词表共 {len(word_map)} 个词（去重后）")

    # 一遍扫描提取音标（只处理 SQLite 中有的词）
    print("\n扫描 JSONL 提取音标...")
    phonetics = {}
    count = 0

    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if data.get("lang_code") != "en":
                continue

            word = data.get("word", "").strip()
            if not word:
                continue

            key = word.lower()
            if key not in word_map:
                continue

            sounds = data.get("sounds", [])
            if not sounds:
                continue

            if key not in phonetics:
                phonetics[key] = {"uk": None, "us": None, "fallback": None}

            entry = phonetics[key]

            for s in sounds:
                ipa = s.get("ipa")
                if not ipa:
                    continue
                cleaned = ipa.split(",")[0].strip("/[] ")
                if not cleaned:
                    continue

                tags = set(s.get("tags", []))

                if not entry["uk"] and tags & UK_TAGS:
                    entry["uk"] = cleaned
                if not entry["us"] and tags & US_TAGS:
                    entry["us"] = cleaned
                if not entry["fallback"] and not tags:
                    entry["fallback"] = cleaned

            count += 1
            if count % 100000 == 0:
                print(f"  已扫描 {count} 条...")

    print(f"共扫描 {count} 条，匹配到 {len(phonetics)} 个词")

    # 用 fallback 填充
    filled = 0
    for entry in phonetics.values():
        if not entry["uk"] and not entry["us"] and entry["fallback"]:
            entry["uk"] = entry["fallback"]
            entry["us"] = entry["fallback"]
            filled += 1
        elif not entry["uk"] and entry["fallback"]:
            entry["uk"] = entry["fallback"]
            filled += 1
        elif not entry["us"] and entry["fallback"]:
            entry["us"] = entry["fallback"]
            filled += 1

    has_uk = sum(1 for v in phonetics.values() if v["uk"])
    has_us = sum(1 for v in phonetics.values() if v["us"])
    has_both = sum(1 for v in phonetics.values() if v["uk"] and v["us"])
    print(f"兜底填充了 {filled} 个词")
    print(f"有英式: {has_uk}, 有美式: {has_us}, 两者都有: {has_both}")

    # 临时表 + JOIN 批量更新
    print("\n写入 SQLite...")
    batch = []
    for key, entry in phonetics.items():
        uk = entry["uk"]
        us = entry["us"]
        if uk or us:
            batch.append((word_map[key], uk, us))

    print(f"待写入 {len(batch)} 条")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("CREATE TEMP TABLE _ph_import (word TEXT, uk TEXT, us TEXT)")
    conn.execute("CREATE INDEX _ph_import_idx ON _ph_import(word COLLATE NOCASE)")

    # 快速插入临时表
    conn.executemany("INSERT INTO _ph_import VALUES (?, ?, ?)", batch)
    print("  临时表写入完成，开始更新主表...")

    # 一条语句批量更新
    conn.execute("""
        UPDATE stardict SET
            phonetic_uk = (SELECT uk FROM _ph_import WHERE _ph_import.word = stardict.word COLLATE NOCASE),
            phonetic_us = (SELECT us FROM _ph_import WHERE _ph_import.word = stardict.word COLLATE NOCASE)
        WHERE word IN (SELECT word FROM _ph_import)
    """)
    conn.commit()
    conn.execute("DROP TABLE _ph_import")
    conn.close()
    print(f"写入完成")

    # 最终统计
    conn = sqlite3.connect(str(DB_PATH))
    r = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN phonetic_uk IS NOT NULL AND phonetic_uk != '' THEN 1 ELSE 0 END) as has_uk,
            SUM(CASE WHEN phonetic_us IS NOT NULL AND phonetic_us != '' THEN 1 ELSE 0 END) as has_us
        FROM stardict
    """).fetchone()
    conn.close()
    print(f"\n最终结果: 总词数 {r[0]}, 有英式音标 {r[1]}, 有美式音标 {r[2]}")


if __name__ == "__main__":
    main()
