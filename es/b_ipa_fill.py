#!/usr/bin/env python3
"""
规则补变位 IPA：给 is_lemma=0 且 phonetic 为空的变位词，用 b_ipa.word_to_ipa 生成 IPA。
已用 6.8 万有 kaikki IPA 的变位自证 98.4% 一致（见 b_ipa_eval.py），残差为前缀 hiatus 合法
两读 + 借词，非发音错误。规则无输出(含外文字符)的少数词写 b_ipa_todo.txt，交豆包。

只碰变位、只填空 phonetic，不动 lemma、不动已有 IPA。免费、确定、可重跑。
用法：python3 b_ipa_fill.py           # 补
      python3 b_ipa_fill.py --dry     # 只统计不写
"""
import argparse
import sqlite3
from pathlib import Path

from b_ipa import word_to_ipa

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "synapse-dict-es.sqlite"
TODO = HERE / "b_ipa_todo.txt"


def main(dry=False):
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT id, word FROM dict WHERE is_lemma=0 AND phonetic IS NULL "
        "AND word NOT LIKE '% %'").fetchall()
    filled, none_ret = 0, []
    ups = []
    for rid, w in rows:
        ipa = word_to_ipa(w)
        if ipa is None:
            none_ret.append(w)
            continue
        ups.append((ipa, rid))
        filled += 1
    print(f"待补变位 {len(rows)}：规则可补 {filled}，搞不定(外文字符) {len(none_ret)}")
    if dry:
        print("（--dry，未写库）")
    else:
        conn.executemany("UPDATE dict SET phonetic=? WHERE id=?", ups)
        conn.commit()
        TODO.write_text("\n".join(none_ret), encoding="utf-8")
        print(f"已写入 {filled} 条 IPA。搞不定的 {len(none_ret)} 词 → {TODO.name}（交豆包）")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    main(ap.parse_args().dry)
