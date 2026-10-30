#!/usr/bin/env python3
"""读音层 `dialect／hidden／hidden_why` 按 `criteria.pronunciation_status` **原地重算**。ru，2026-10-29。

    python3 -u ru/pipeline/sync_pronunciation_hidden.py            # 干跑
    python3 -u ru/pipeline/sync_pronunciation_hidden.py --apply

判据一条都不在本文件里写 —— 与 `pronunciation_layer.py`、闸 Q5 调的是同一个函数，
所以「判据改了而库里还是旧结果」时，Q5 会红，跑这个就绿。

为什么不直接 `pronunciation_layer.py --rebuild`：重算只动三列，重建要重扫七版 dump、行 id 全换。
第一次用（B10）：`criteria.NOT_IPA` 新增「内容不是 IPA 也藏」，库里 4 行（`сердечный → 5`、`во → v0`）。
"""
import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dbtool                                                   # noqa: E402
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402


def plan(con):
    out = []
    for pid, word, tj, ipa, d, h, w in con.execute(
            "SELECT p.id, x.word, p.tags, p.ipa, p.dialect, p.hidden, p.hidden_why "
            "FROM pronunciation p JOIN dict x ON x.id=p.word_id"):
        t = json.loads(tj) if tj else {"tags": [], "raw_tags": []}
        want = criteria.pronunciation_status(t["tags"], t["raw_tags"], ipa)
        if want != (d, h, w):
            out.append((pid, word, ipa, (d, h, w), want))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = plan(con)
    con.close()
    print("■ 与判据对不上的读音行 %d" % len(todo))
    print("   变化 %s" % dict(collections.Counter("%s → %s" % (o[2], n[2]) for *_x, o, n in todo)))
    for pid, word, ipa, old, new in todo[:20]:
        print("   #%-8d %-20s %-30s %s → %s" % (pid, word, ipa[:30], old, new))
    if not a.apply or not todo:
        print("\n（干跑。加 --apply 才写库）" if todo else "\n（无事可做）")
        return
    why_delta = (sum(1 for *_x, o, n in todo if n[2]) - sum(1 for *_x, o, n in todo if o[2]))
    with dbtool.session("sync-pronunciation-hidden",
                        expect={"pronunciation.hidden_why": why_delta}) as s:
        for pid, _w, _i, _o, (d, h, w) in todo:
            s.execute("UPDATE pronunciation SET dialect=?, hidden=?, hidden_why=? WHERE id=?",
                      (d, h, w, pid))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = len(plan(con))
    con.close()
    print("\n■ 写后回核：仍对不上 %d 行（期望 0）" % left)
    if left:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
