#!/usr/bin/env python3
"""补建被漏掉的「按音标拆分」entry 行，并把挂错的义项改挂过去。2026-08-13。

═══ 缺陷 ═══
`build_entry_layer.replay()` 原来把 `entries` 按 `(词形,词性,词源号)` 去重（`setdefault`），
于是同键的第二条 JSON **复用了第一条的音标集**；而 `assign_seq()` 恰恰是**按音标集**
把它们拆成 seq 0 / seq 1 的 ⇒ seq=1 那行永远建不出来，它的义项还被挂到 seq 0 上。

全库 2 例：
    kk-en:infrociare:verb:0:1     ← /in.froˈʃa(re)/ 那条，2 个义项
    kk-en:sorti:verb:2:0
是 2026-08-13 语法层的闸①（entry.aux 少一条）逮到的 —— 纸上推不出来，
因为「entry 总数 621,097」这个数**自洽**：漏建的行同时从分子和分母里消失了。

⇒ 教训：`setdefault` 的键必须是**判定用的那个键**。判定用音标分，键就得带音标。
   脚本侧已修（`build_entry_layer.py`），这里补数据。

用法（在 it/ 目录下）：
    python3 fixes/add_split_entry_rows.py            # 只报，不写
    python3 fixes/add_split_entry_rows.py --apply
"""
import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build_entry_layer import SRC, assign_seq   # noqa: E402
from build_grammar_layer import entry_aux_rows, replay_aux   # noqa: E402


def scan(words):
    """→ (每个 (key0, occ) 应该属于的 ref, 全部应有的 ref→(pos,etym,seq,词形))"""
    dup, per_occ = defaultdict(list), {}
    occ_of = defaultdict(int)
    for line in open(paths.KK, encoding="utf-8"):
        e = json.loads(line)
        w0 = e.get("word") or ""
        if w0.strip().lower() not in words:
            continue
        key0 = (w0, e.get("pos") or "", str(e.get("etymology_number") or 0))
        ipas = frozenset(s["ipa"] for s in (e.get("sounds") or []) if s.get("ipa"))
        dup[key0].append((ipas, (e.get("etymology_text") or "")[:200]))
        per_occ[(key0, occ_of[key0])] = ipas
        occ_of[key0] += 1
    seq_of = assign_seq(dup, verbose=False)
    ref_of_occ, all_refs = {}, {}
    for (key0, occ), ipas in per_occ.items():
        seq = seq_of.get((key0, ipas), 0)
        ref = "kk-en:%s:%s:%s:%d" % (key0[0], key0[1], key0[2], seq)
        ref_of_occ[(key0, occ)] = ref
        all_refs[ref] = (key0[1], key0[2], seq, key0[0])
    return ref_of_occ, all_refs, seq_of


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {w.lower() for (w,) in ro.execute("SELECT word FROM dict")}
    ref_of_occ, all_refs, seq_of = scan(words)

    have = {r for (r,) in ro.execute("SELECT src_ref FROM entry")}
    missing = sorted(set(all_refs) - have)
    extra = sorted(have - set(all_refs))
    print("■ 应有 entry %s / 库里 %s / 漏建 %d / 库里多出 %d"
          % (f"{len(all_refs):,}", f"{len(have):,}", len(missing), len(extra)))
    for r in missing:
        print("   缺  %s" % r)
    for r in extra:
        print("   🔴 多  %s" % r)
    if extra:
        print("🔴 库里有 dump 里没有的 entry —— 不是本脚本能修的，停手")
        return 1

    # 挂错的义项：按 sense_src.src_ref 里的 (ref_old, occ) 反推它本该属于哪个 ref
    wrong = []
    for sid, sref in ro.execute("SELECT sense_id, src_ref FROM sense_src"):
        head, _, tail = sref.rpartition("#")
        occ = int(tail.split(".")[0])
        # ⚠️ 词形本身可能含 ':'，只能从右边切固定的三段（词性/词源号/seq）
        rest = head[len("kk-en:"):]
        w0, pos, etym, _seq = rest.rsplit(":", 3)
        want = ref_of_occ.get(((w0, pos, etym), occ))
        if want and want != head:
            wrong.append((sid, sref, "%s#%s" % (want, tail)))
    print("■ 挂错 entry 的义项 %d 条" % len(wrong))
    for x in wrong:
        print("   sense#%-8s %s  →  %s" % x)

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    if not missing and not wrong:
        print("无事可做")
        return 0

    wid_of = {w.lower(): i for i, w in ro.execute("SELECT id, word FROM dict")}
    aux_of, dup2, _ = replay_aux(paths.KK, words)
    ent_aux = entry_aux_rows(aux_of, assign_seq(dup2, verbose=False))
    next_id = ro.execute("SELECT max(id) FROM entry").fetchone()[0] + 1
    new_rows = []
    for n, ref in enumerate(missing):
        pos, etym, seq, w0 = all_refs[ref]
        new_rows.append((next_id + n, wid_of[w0.lower()], pos, etym, seq,
                         ent_aux.get(ref, (None, None))[0], SRC, ref))
    ro.close()

    with dbtool.session("split-entry-rows", expect={"#entry": len(new_rows)}) as s:
        s.executemany("INSERT INTO entry (id,word_id,pos,etym_no,seq,aux,src,src_ref) "
                      "VALUES (?,?,?,?,?,?,?,?)", new_rows)
        id_of = {r: i for i, r in s.conn.execute("SELECT id, src_ref FROM entry")}
        s.executemany("UPDATE sense_src SET src_ref=? WHERE sense_id=?",
                      [(new, sid) for sid, _, new in wrong])
        s.executemany("UPDATE sense SET entry_id=? WHERE id=?",
                      [(id_of[new.rpartition("#")[0]], sid) for sid, _, new in wrong])
    print("\n■ 已补 entry %d 行、改挂义项 %d 条" % (len(new_rows), len(wrong)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
