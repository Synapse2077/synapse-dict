"""补 es 冲突文件（纯本地、0 kaikki 扫描、0 模型）：老 es 管线没留痕，这里离线重建。
把 b_out.tar.gz 的豆包值（g 性别 / ipa）与当前库值（gender/phonetic = kaikki 权威）逐条对比，
不一致的写成 es/conflict_review.tsv（同 it/pt/de/fr 格式 word\\tfield\\tkaikki\\tdoubao），
以便进同一分档(scripts/bucket_conflicts.py)/裁决(b_adjudicate.py)流程。

b_out rid == dict.id（已验），直接 id join。只比 lemma 行。原始值比对（记法噪声留给分档器处理）。
gender 冲突：豆包 g ≠ 库 gender（库=kaikki）。ipa 冲突：豆包 ipa ≠ 库 phonetic（库空则豆包填过、不算冲突）。

用法：python3 reconstruct_conflicts.py
"""
import json
import sqlite3
import tarfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-es.sqlite"
BOUT = HERE / "b_out.tar.gz"
OUT = HERE / "conflict_review.tsv"


def load_bout():
    """{rid: {'w':.., 'g':.., 'ipa':..}}"""
    out = {}
    with tarfile.open(BOUT) as tf:
        for mem in tf.getmembers():
            if not mem.name.endswith(".json"):
                continue
            data = json.load(tf.extractfile(mem))
            for rid, o in data.items():
                if not isinstance(o, dict):
                    continue
                ipa = o.get("ipa")
                if not (isinstance(ipa, str) and ipa.startswith("/")):
                    ipa = None
                g = o.get("g") if o.get("g") in ("m", "f", "mf") else None
                out[int(rid)] = {"w": o.get("w"), "g": g, "ipa": ipa}
    return out


def main():
    bout = load_bout()
    print(f"b_out 豆包记录 {len(bout)} 条")
    conn = sqlite3.connect(str(DB))
    rows = []
    field_ct = Counter()
    for rid, o in bout.items():
        r = conn.execute(
            "SELECT word, gender, phonetic, is_lemma FROM dict WHERE id=?", (rid,)).fetchone()
        if not r or r[3] != 1:
            continue
        word, kg, kph, _ = r
        # gender 冲突（两侧都有值且不同）
        if o["g"] and kg and o["g"] != kg:
            rows.append((word, "gender", kg, o["g"]))
            field_ct["gender"] += 1
        # ipa 冲突（两侧都有值且不同；库空=豆包当年填过，不算冲突）
        if o["ipa"] and kph and o["ipa"] != kph:
            rows.append((word, "ipa", kph, o["ipa"]))
            field_ct["ipa"] += 1
    conn.close()

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("word\tfield\tkaikki\tdoubao\n")
        for w, fl, kk, db in rows:
            f.write(f"{w}\t{fl}\t{kk}\t{db}\n")
    print(f"写 {OUT.name}：{len(rows)} 条冲突  {dict(field_ct)}")
    print("样本：")
    for w, fl, kk, db in rows[:15]:
        print(f"  {w}\t{fl}\tkaikki={kk}\tdoubao={db}")


if __name__ == "__main__":
    main()
