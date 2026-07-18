#!/usr/bin/env python3
"""
规则填 IPA：给 synapse-dict-it.sqlite 里 ipa 为空的词（多为 43 万变位形式）补音标。

钥匙：从 kaikki 每个 lemma 的 forms 数组收「带重音的变位形」（pàrlo/parliàmo/pàrlano…），
建 去重音surface → 重音形 映射。填库时优先按此查到重音形喂 G2P（重音位置+e/o 开闭都准，
自证 strict≈83%）；查不到再喂拼写原词（倒二重音默认）。含外文字母 G2P 返回 None → 留空交豆包。

不覆盖已有 ipa（kaikki 优先）。用法：
  python3 b_ipa_fill.py           # 建映射并写库
  python3 b_ipa_fill.py --dry     # 只统计覆盖，不写库
"""
import argparse
import json
import sqlite3
import unicodedata
from pathlib import Path

from b_ipa import word_to_ipa

HERE = Path(__file__).resolve().parent
JSONL_PATH = HERE / "kaikki.org-dictionary-Italian.jsonl"
DB_PATH = HERE / "synapse-dict-it.sqlite"
ACC = set("àèéìíòóù")


def unaccent(s):
    nfd = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def build_accent_map():
    """去重音surface(lower) → 带重音形。覆盖 forms 数组里所有重音变位/派生形。"""
    amap = {}
    n = 0
    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "it":
                continue
            for fm in e.get("forms") or []:
                form = (fm.get("form") or "").strip()
                if not form or not any(c in ACC for c in form):
                    continue
                key = unaccent(form)
                if key not in amap:            # first-seen 胜（同形异重的残差可接受）
                    amap[key] = form
                    n += 1
    print(f"重音形映射：{len(amap)} 条（来自 forms 数组）")
    return amap


def main(dry):
    amap = build_accent_map()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, word, word_norm FROM dict WHERE ipa IS NULL OR ipa=''"
    ).fetchall()
    print(f"待填 ipa 的词 {len(rows)}")

    updates = []
    via_accent = via_plain = none_out = 0
    for r in rows:
        acc = amap.get(r["word_norm"])
        if acc:
            ipa = word_to_ipa(acc)
            if ipa:
                via_accent += 1
        else:
            ipa = None
        if ipa is None:                         # 无重音形或其 G2P 失败 → 退拼写原词
            ipa = word_to_ipa(r["word"])
            if ipa:
                via_plain += 1
        if ipa is None:
            none_out += 1
            continue
        updates.append((ipa, r["id"]))

    filled = len(updates)
    print(f"  可补 {filled}：重音形路径 {via_accent} | 原词路径 {via_plain} | "
          f"G2P 放弃(外文字符→留空交豆包) {none_out}")

    if dry:
        print("[dry] 未写库。样例：")
        for ipa, rid in updates[:12]:
            w = conn.execute("SELECT word FROM dict WHERE id=?", (rid,)).fetchone()["word"]
            print(f"    {w:20} {ipa}")
        conn.close()
        return

    conn.executemany("UPDATE dict SET ipa=? WHERE id=?", updates)
    conn.commit()
    conn.close()
    print(f"写库完成：补 IPA {filled} 条。剩余空 IPA（外文/缩写）交 b_translate.py 豆包兜底。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    main(args.dry)
