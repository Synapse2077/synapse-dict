#!/usr/bin/env python3
"""W8：录音「张冠李戴」7 行人工逐条裁决 —— 3 行是同一个词，放出来。vi，2026-11-05。

裁决写成常量在 `stage6_sources.AUDIO_SAME_WORD_ADJUDICATED`（判据唯一的家：收割器／外锚闸／本脚本都 import 它）。
本脚本只改**已落库**的行：现在被隐藏为 `filename-word-mismatch`、而新判据不再命中的，`hidden=0`、`hidden_why=NULL`。
不走 `build_audio_layer.py` 重建（`audio.id` 会变）。

跑（在仓库根）：
    python3 -u vi/fixes/fix_w8_audio_adjudicated.py            # 干跑
    python3 -u vi/fixes/fix_w8_audio_adjudicated.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import sqlite3

import dbtool
import paths
import stage6_sources as S6


def plan(con):
    """→ [(audio.id, 词, Commons 键)]：隐藏为张冠李戴、而裁决名单说是同一个词的。"""
    return [(i, w, k) for i, w, k in con.execute(
        "SELECT a.id, d.word, a.commons_key FROM audio a JOIN dict d ON d.id = a.word_id "
        "WHERE a.hidden = 1 AND a.hidden_why = ?", (S6.HIDDEN_WRONG_WORD,))
        if (w, S6.filename_word(k)) in S6.AUDIO_SAME_WORD_ADJUDICATED]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = plan(con)
    con.close()
    for i, w, k in todo:
        print("   放出 audio.id=%d  %-14s ← %s" % (i, w, S6.filename_word(k)))
    n = len(S6.AUDIO_SAME_WORD_ADJUDICATED)
    print("■ 要放出 %d 行（裁决名单 %d 对）" % (len(todo), n))
    if len(todo) > n:
        raise SystemExit("🔴 命中比名单多 —— 同一对在别处也出现了，逐条看过再放")
    if not a.apply or not todo:
        return
    with dbtool.session("vi-fix-w8-audio-adjudicated", expect={"__rows__": 0, "audio.hidden_why": -len(todo)},
                        invalidates=[], small=10) as s:
        s.executemany("UPDATE audio SET hidden = 0, hidden_why = NULL WHERE id = ?", [(i,) for i, _w, _k in todo])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = len(plan(con))
    print("■ 写后回核：裁决名单里仍隐藏的 %d 行（期望 0）" % left)
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
