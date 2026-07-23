"""原地修双性折叠 bug（[[enrich-not-rebuild]]）：现有 synapse-dict-it.sqlite 已含全量豆包付费翻译，
绝不 unlink 重建。radio/fronte/fine/capitale 等双性名词此前 build 的 `if g and not rec["gender"]`
只锁首个 etym 的单性别 → 逐义项性别错。

做法（与 fr/pt 双性修复同款、纯 kaikki 0 豆包）：
  ① gender 列：跨词条累积 m+f → mf；
  ② meta 逐义项加 g（il radio 半径 vs la radio 收音机），供 web 逐义项标冠词。
b_translate 不碰 meta（已验），meta/definition 是 kaikki 确定性，可安全重算。
护栏：重算的 gloss 序列必须与库中 definition 逐字一致才写，否则跳过并报告（绝不错位污染）。

用法：python3 enrich_dual_gender.py            # 修复 + 回填（先自动备份）
      python3 enrich_dual_gender.py --dry-run  # 只算不写
"""

import argparse
import json
import re
import shutil
import sqlite3
import time
from pathlib import Path

import build  # 复用 meta_of_sense / gender_of_senses / POS_MAP / JSONL_PATH

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-it.sqlite"


def _iter_it_entries():
    with open(build.JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "it":
                continue
            word = (e.get("word") or "").strip()
            if not word:
                continue
            yield e, word


def collect_dual_words():
    """Pass 1（便宜）：只碰 noun/name 条累积每词性别，返回双性词 key 集合。"""
    genders = {}
    for e, word in _iter_it_entries():
        if e.get("pos") not in ("noun", "name"):
            continue
        g = build.gender_of_senses(e.get("senses", []))
        if not g:
            continue
        s = genders.setdefault(word.lower(), set())
        for x in ("m", "f"):
            if x in g:
                s.add(x)
    return {k for k, gg in genders.items() if "m" in gg and "f" in gg}


def collect_gloss_meta(keys):
    """Pass 2（只对候选词）：按 build 同款逻辑重建 real_gloss/real_meta。
    返回 {key: {"gloss": [...], "meta": [...]}}。"""
    out = {k: {"gloss": [], "meta": [], "seen": set()} for k in keys}
    for e, word in _iter_it_entries():
        key = word.lower()
        rec = out.get(key)
        if rec is None:
            continue
        pos_raw = e.get("pos", "")
        is_affix = pos_raw in ("suffix", "prefix", "infix", "interfix")
        for s in e.get("senses", []):
            fo = s.get("form_of") or s.get("alt_of")
            if bool(fo) and not is_affix:
                continue   # 变位/变体形，归 infl，不进 real_gloss
            gl = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
            if not gl or gl in rec["seen"]:
                continue
            rec["seen"].add(gl)
            rec["gloss"].append(gl)
            rec["meta"].append(build.meta_of_sense(s, pos_raw))
    return out


def main(dry_run=False):
    if not DB.exists():
        raise SystemExit(f"缺库: {DB}")
    print("Pass 1：扫 kaikki 累积名词性别，找双性候选…")
    dual_keys = collect_dual_words()
    print(f"双性名词（跨词条同见 m+f）：{len(dual_keys)} 词")
    print("Pass 2：只对候选词重建 real_gloss/meta…")
    dual = collect_gloss_meta(dual_keys)

    conn = sqlite3.connect(str(DB))
    # 一次性把所有 lemma 行读进内存（避免 1.5万次 lower(word)=? 全表扫）
    dbmap = {}
    for w, d, mt, g in conn.execute(
            "SELECT word, definition, meta, gender FROM dict WHERE is_lemma=1"):
        dbmap.setdefault(w.lower(), (d, mt, g))
    updates = []      # (key, gender_new, meta_json)
    skip_mismatch = []
    skip_nolemma = []
    flip = []         # 真 bug 受害者：库里当前单性别 → 将变 mf
    already_mf = 0    # 原库已 mf（共性名词 comune）：gender 不变，仅 meta 补逐义项 g
    meta_only = 0     # gender 不变但 meta 有变（补了 g）
    detail = {}       # key -> (status, meta_json)
    for key, r in dual.items():
        row = dbmap.get(key)
        if row is None:
            skip_nolemma.append(key)
            continue
        definition, stored_meta, cur_gender = row
        regened = "\n".join(r["gloss"])
        if (definition or "") != regened:
            skip_mismatch.append(key)
            continue
        meta_json = json.dumps(r["meta"], ensure_ascii=False)
        gender_changed = cur_gender != "mf"
        meta_changed = (stored_meta or "") != meta_json
        if not gender_changed and not meta_changed:
            already_mf += 1
            continue   # 纯共性名词、无单一性别义项：完全 no-op，不动
        if gender_changed:
            flip.append(key)
        else:
            meta_only += 1
            already_mf += 1
        detail[key] = ("修-flip" if gender_changed else "修-meta", meta_json)
        updates.append((key, "mf", meta_json))

    print(f"候选 {len(dual)} | 真 flip(单性别→mf) {len(flip)} | 已 mf 仅补 meta {meta_only} | "
          f"完全 no-op(纯共性) {already_mf - meta_only} | 护栏跳过(gloss不一致) {len(skip_mismatch)} | 无 lemma {len(skip_nolemma)}")
    print(f"实际写库 {len(updates)} 词")
    for w in ("radio", "fronte", "fine", "capitale", "artista", "insegnante"):
        if w in detail:
            print(f"  {w}: {detail[w][0]} | meta={detail[w][1]}")
        elif w in skip_mismatch:
            print(f"  {w}: 跳-mismatch")
        elif w in skip_nolemma:
            print(f"  {w}: 跳-nolemma")
        elif w in dual:
            print(f"  {w}: no-op(已 mf 无单性别义项)")
        else:
            print(f"  {w}: 非双性候选")
    if skip_mismatch:
        print(f"  ⚠ mismatch 样本：{skip_mismatch[:15]}")

    if dry_run:
        print("[dry-run] 未写库")
        conn.close()
        return

    bak = DB.with_suffix(f".sqlite.pre-dualgender-{time.strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(DB, bak)
    print(f"备份 → {bak.name}")

    n = 0
    for key, gender_new, meta_json in updates:
        cur = conn.execute(
            "UPDATE dict SET gender=?, meta=? WHERE word=? COLLATE NOCASE AND is_lemma=1",
            (gender_new, meta_json, key),
        )
        n += cur.rowcount
    conn.commit()
    conn.close()
    print(f"回填 {n} 行（gender=mf + meta 逐义项 g）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    main(dry_run=args.dry_run)
