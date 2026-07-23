"""原地补列 noun_variants（[[enrich-not-rebuild]]）：现有 synapse-dict-de.sqlite 已含全量
豆包付费翻译，绝不 unlink 重建。做法 = 复制现库 → ALTER 加列 → 从 kaikki 确定性回填。

多性别名词（Band/See/Steuer…）此前 build 的 `if g and not rec["gender"]` 只存首性别，
非首性别的属格/复数整个丢失。noun_variants JSON [{g,gen,pl},…] 逐性别存回真变格束。
纯 kaikki 事实、零豆包、可逐条对 kaikki 验。

用法：python3 enrich_noun_variants.py            # 原地补列 + 回填（先自动备份）
      python3 enrich_noun_variants.py --dry-run  # 只算不写，打印规模 + 抽样
"""

import argparse
import json
import shutil
import sqlite3
import time
from pathlib import Path

import build  # 复用 extract_noun / compose_noun_variants / JSONL_PATH

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-de.sqlite"


def collect_noun_forms():
    """扫 kaikki，按词累积每性别 (gen, pl)（同 build 主循环的累积逻辑）。
    返回 {word: {gender: [(gen,pl),…]}}。"""
    word_forms = {}
    with open(build.JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            # 仅收 pos=noun（普通名词变格范式）；排除 name 专名（das See 地名之类是噪声）
            if e.get("lang_code") != "de" or e.get("pos") != "noun":
                continue
            word = (e.get("word") or "").strip()
            if not word:
                continue
            g, gen, pl = build.extract_noun(e, word, e.get("senses", []))
            if not g:
                continue
            nf = word_forms.setdefault(word, {})
            for gg in g.split("/"):
                nf.setdefault(gg, []).append((gen, pl))
    return word_forms


def main(dry_run=False):
    if not DB.exists():
        raise SystemExit(f"缺库: {DB}")

    print("扫 kaikki 累积每性别范式束…")
    word_forms = collect_noun_forms()
    # 只有跨词条多性别（compose 返回非 None）才需要 noun_variants
    variants = {}
    for word, nf in word_forms.items():
        jv = build.compose_noun_variants(nf)
        if jv:
            variants[word] = jv
    print(f"多性别名词（需 noun_variants）：{len(variants)} 词")

    for w in ("Band", "See", "Steuer"):
        print(f"  {w}: {variants.get(w, '(无)')}")

    if dry_run:
        print("[dry-run] 未写库")
        return

    # 备份
    bak = DB.with_suffix(f".sqlite.pre-nounvariants-{time.strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(DB, bak)
    print(f"备份 → {bak.name}")

    conn = sqlite3.connect(str(DB))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dict)")}
    if "noun_variants" not in cols:
        conn.execute("ALTER TABLE dict ADD COLUMN noun_variants TEXT")
        print("ALTER: 加列 noun_variants")
    else:
        print("列 noun_variants 已存在，直接回填")

    # 回填：按 word 更新（build 按 word 建键，一词一行；限 lemma 行）
    n = 0
    miss = []
    for word, jv in variants.items():
        cur = conn.execute(
            "UPDATE dict SET noun_variants=? WHERE word=? AND is_lemma=1",
            (jv, word),
        )
        if cur.rowcount:
            n += cur.rowcount
        else:
            miss.append(word)
    conn.commit()
    conn.close()
    print(f"回填 {n} 行 noun_variants（词表 {len(variants)}）")
    if miss:
        print(f"⚠ {len(miss)} 词在库中无 lemma 行未回填（样本）：{miss[:15]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    main(dry_run=args.dry_run)
