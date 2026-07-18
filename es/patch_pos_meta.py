#!/usr/bin/env python3
"""
补丁：把逐义项词性(pos)注入 synapse-dict-es.sqlite 的 meta 列。

背景：建库时 pos 只聚合到整词的 pos 列（如 "adj/adv/n/prep"），没下沉到义项。
本脚本按内容匹配从 kaikki dump 还原每条义项的 pos，注入到已有 meta 的每个元素里，
**只加 "pos" 键，其余 meta 值（性别/地区/语域/数）原样不动**，翻译/IPA/搭配也不碰。

定位规则（永不写错 pos）：
  ① 命中 (词,义项原文)→pos 映射     → 用它
  ② 未命中且该词单词性             → 用那唯一 pos（无歧义，如西语补充义项）
  ③ 未命中且多词性                 → pos 留空（宁可不标，绝不误标）

用法（在 es/ 目录）：
  python3 patch_pos_meta.py            # dry-run：只统计，不写库
  python3 patch_pos_meta.py --apply    # 备份后写库
"""
import argparse
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import is_infl_sense, base_of, POS_MAP, ABBR_TAGS

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "synapse-dict-es.sqlite"
JSONL_PATH = HERE / "kaikki.org-dictionary-Spanish.jsonl"
AFFIX = ("suffix", "prefix", "infix", "interfix")


def build_pos_map():
    """(词key, 义项原文) -> pos。与 build.py 取义项/去重语义一致，first-seen 胜。"""
    pos_of = {}
    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
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
            key = word.lower()
            pos = e.get("pos", "")
            is_affix = pos in AFFIX
            short = POS_MAP.get(pos, pos)
            for s in e.get("senses", []):
                tags = s.get("tags", [])
                is_abbr = bool(set(tags) & ABBR_TAGS)
                base = (base_of(s) if (not is_affix and not is_abbr and is_infl_sense(s))
                        else None)
                if base:
                    continue                       # 变位义 → 不进 definition
                g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
                if not g:
                    continue
                pos_of.setdefault((key, g), short)
    return pos_of


def resolve_line_pos(key, line, poscol, pos_of):
    """给一行义项定 pos，遵循 ①②③ 规则；定不了返回 None。"""
    p = pos_of.get((key, line))
    if p:
        return p
    parts = poscol.split("/") if poscol else []
    if len(parts) == 1:                            # 单词性 → 无歧义
        return parts[0]
    return None                                    # 多词性且未命中 → 留空


def main(apply):
    print(f"读取 kaikki 建映射: {JSONL_PATH}")
    pos_of = build_pos_map()
    print(f"  映射条目 {len(pos_of)}")

    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT id, word, pos, definition, meta FROM dict "
        "WHERE is_lemma=1 AND definition IS NOT NULL"
    ).fetchall()

    n_rows = n_updated = n_skip_len = 0
    line_tot = line_pos = line_null = 0
    updates = []
    for rid, word, poscol, definition, meta_json in rows:
        n_rows += 1
        lines = definition.split("\n")
        meta = json.loads(meta_json) if meta_json else None
        # meta 缺失或长度不匹配 → 按行数新建/补齐（值留空，只带 pos）
        if meta is None or len(meta) != len(lines):
            if meta is not None and len(meta) != len(lines):
                n_skip_len += 1
                continue                           # 长度不符：保守跳过，不猜
            meta = [{} for _ in lines]
        key = word.lower()
        changed = False
        for i, line in enumerate(lines):
            line_tot += 1
            p = resolve_line_pos(key, line, poscol, pos_of)
            if p:
                line_pos += 1
                if meta[i].get("pos") != p:
                    # pos 放在每个义项 meta 的首位（新建有序 dict）
                    meta[i] = {"pos": p, **{k: v for k, v in meta[i].items() if k != "pos"}}
                    changed = True
            else:
                line_null += 1
        if changed:
            updates.append((json.dumps(meta, ensure_ascii=False), rid))
            n_updated += 1

    print(f"\nlemma(有释义) {n_rows}")
    print(f"  将更新 meta 的行 {n_updated}")
    print(f"  meta长度与义项数不符、保守跳过 {n_skip_len}")
    print(f"义项行 {line_tot}：定位到pos {line_pos} ({100*line_pos/line_tot:.3f}%)，"
          f"留空 {line_null} ({100*line_null/line_tot:.3f}%)")

    if not apply:
        print("\n[dry-run] 未写库。确认无误后加 --apply 执行。")
        conn.close()
        return

    bak = DB_PATH.with_suffix(".sqlite.bak")
    print(f"\n备份 → {bak}")
    conn.close()
    shutil.copy2(DB_PATH, bak)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executemany("UPDATE dict SET meta=? WHERE id=?", updates)
    conn.commit()
    conn.close()
    print(f"完成：更新 {len(updates)} 行 meta。备份留在 {bak.name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = ap.parse_args()
    main(args.apply)
