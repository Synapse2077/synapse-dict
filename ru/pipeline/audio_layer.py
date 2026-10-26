#!/usr/bin/env python3
"""阶段 6c：**录音层** —— `audio`。ru，2026-10-24。不花钱。

    python3 -u ru/pipeline/audio_layer.py --dry
    python3 -u ru/pipeline/audio_layer.py
    python3 -u ru/pipeline/audio_layer.py --rebuild

判据一条都不在本文件里写 —— `criteria` §⑬（挑 URL／归一键／张冠李戴）＋ §⑨（`pronunciation_status`／
`pronunciation_target`／`nominative_plural`，与音标层**同一组函数**）。依据见 RU_PLAN §十五。

═══ 三条约定 ═══
① **挂谁照音标层**：`tags: plural` 的录音挂到主格复数那个词形、`entry_id` 留 NULL；
   单复数同标的判不出归属 ⇒ 不收（计数）。
② **B12：同一个文件一个词形只留一行**（按 `commons_key` 并，不按 URL）。
   留哪一行：`build.SRC` 顺序在前的那版；`entry_id` 跟着留下的那行。
③ **藏不删**：源头标错的（`неправильно`）、文件名里的词与词形对不上的 ⇒ `hidden=1` ＋ 原因。
   ⚠️ 判据精度没有 100%（文件名尺子只覆盖两种命名），删掉就找不回假阳。
"""
import argparse
import collections
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dbtool                                                   # noqa: E402
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.build import SRC, rd                              # noqa: E402

F = lambda n: format(n, ",")                                    # noqa: E731
SRC_RANK = {s: i for i, (s, _p) in enumerate(SRC)}


def collect(conn, limit=None, verbose=True):
    """→ (rows, raw, stat)。row ＝ (word_id, entry_id, url, commons_key, why, src)。
    `raw` 是去重之前的行 —— B12 的恒等式要拿它当分母。"""
    wid = dict(conn.execute("SELECT word, id FROM dict"))
    word_of = {i: w for w, i in wid.items()}
    eid = dict(conn.execute("SELECT src_ref, id FROM entry"))
    # 第二信号要先扫一遍全部源（同音/异写可能写在对方的条目里）
    same = set()
    for _src, p in SRC:
        for e in rd(p, limit):
            if criteria.entry_accept(e)[0]:
                same |= criteria.audio_same_sound_pairs(e)
    if verbose:
        print("   源头声明的「读音相同／异写」对 %s" % F(len(same)), flush=True)
    ref = criteria.SrcRef()
    raw, st = [], collections.Counter()
    for src, p in SRC:
        t0 = time.time()
        for e in rd(p, limit):
            ok, _skip, pos = criteria.entry_accept(e)
            if not ok:
                continue
            w = e["word"]
            no, sub = criteria.etym_no_pair(e)
            sref, _seq = ref.take(src, w, pos, no, sub)
            sounds = [s for s in (e.get("sounds") or []) if criteria.audio_url(s)]
            if not sounds:
                continue
            entry_id = eid.get(sref)
            self_wid = wid.get(w) or wid.get(criteria.strip_stress(w))
            if entry_id is None or self_wid is None:
                st["🔴 挂不上 entry/dict"] += len(sounds)
                continue
            plural_wid = None
            for s in sounds:
                tags, raw_tags = s.get("tags") or [], s.get("raw_tags") or []
                target = criteria.pronunciation_target(tags)
                if target is None:
                    st["丢：单复数同标·归属不明"] += 1
                    continue
                if target == "plural":
                    if plural_wid is None:
                        npl = criteria.nominative_plural(e)
                        plural_wid = (wid.get(npl) if npl else None) or False
                    if not plural_wid:
                        st["丢：复数录音·挂不上主格复数词形"] += 1
                        continue
                    w_id, e_id = plural_wid, None
                    st["复数录音挂到复数词形"] += 1
                else:
                    w_id, e_id = self_wid, entry_id
                key = criteria.commons_key(s)
                why = criteria.audio_hidden_why(word_of[w_id], key, tags, raw_tags, same)
                raw.append((w_id, e_id, criteria.audio_url(s), key, why, src))
                st["源头录音"] += 1
        if verbose:
            print("   …%s 扫完（%.0fs）" % (src, time.time() - t0), flush=True)
    best = {}
    for r in raw:
        k = (r[0], r[3])
        if k not in best or SRC_RANK[r[5]] < SRC_RANK[best[k][5]]:
            best[k] = r
    rows = sorted(best.values(), key=lambda r: (r[0], r[3]))
    for r in rows:
        st[("藏：" + r[4]) if r[4] else "✅ 可播"] += 1
    return rows, raw, st, same


def report(rows, raw, st):
    print("\n■ 录音 %s 行（可播 %s）" % (F(len(rows)), F(sum(1 for r in rows if not r[4]))))
    for k, v in sorted(st.items()):
        print("   %-44s %9s" % (k, F(v)))
    byurl = len({(r[0], r[2]) for r in raw})
    print("   🔴 B12：原始 %s → 按 (词,url) %s → 按 (词,commons_key) **%s**" % (F(len(raw)), F(byurl), F(len(rows))))
    print("   ── 按版（留下的）：%s" % dict(collections.Counter(r[5] for r in rows).most_common()))
    bad = [r for r in rows if r[4] == criteria.AUDIO_WRONG_WORD]
    print("   张冠李戴 %d 行，按版：%s" % (len(bad), dict(collections.Counter(r[5] for r in bad))))
    return bad


def write(rows, conn, rebuild=False):
    have = conn.execute("SELECT COUNT(*) FROM audio").fetchone()[0]
    if have and not rebuild:
        raise SystemExit("🔴 `audio` 已有 %s 行 —— 要重算就加 `--rebuild`" % F(have))
    q = lambda s: conn.execute(s).fetchone()[0] if rebuild else 0      # noqa: E731
    exp = {
        "#audio": len(rows) - q("SELECT COUNT(*) FROM audio"),
        "audio.commons_key": sum(1 for r in rows if r[3]) - q(
            "SELECT COUNT(*) FROM audio WHERE commons_key IS NOT NULL AND TRIM(commons_key)<>''"),
        "audio.entry_id": sum(1 for r in rows if r[1] is not None) - q(
            "SELECT COUNT(*) FROM audio WHERE entry_id IS NOT NULL"),
        "audio.hidden_why": sum(1 for r in rows if r[4]) - q(
            "SELECT COUNT(*) FROM audio WHERE hidden_why IS NOT NULL AND TRIM(hidden_why)<>''"),
    }
    conn.close()
    with dbtool.session("audio-layer" + ("-rebuild" if rebuild else ""), expect=exp,
                        invalidates=["audio"]) as s:
        if rebuild:
            s.execute("DELETE FROM audio")
        s.executemany("INSERT INTO audio(word_id,entry_id,url,commons_key,hidden,hidden_why,src) "
                      "VALUES (?,?,?,?,?,?,?)",
                      [(r[0], r[1], r[2], r[3], 1 if r[4] else 0, r[4], r[5]) for r in rows])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("■ 阶段 6c 录音层  判据 %s" % criteria.RULE_VER, flush=True)
    rows, raw, st, _same = collect(conn, a.limit)
    if st.get("🔴 挂不上 entry/dict"):
        raise SystemExit("🔴 有录音挂不上 entry —— 先查")
    bad = report(rows, raw, st)
    wo = dict(conn.execute("SELECT id, word FROM dict"))
    print("   张冠李戴全部（逐条读）：")
    for r in bad:
        print("      %-28s ⇐ %-60s %s" % (wo[r[0]], r[3][:60], r[5]))
    if a.dry or a.limit:
        print("\n(干跑。)")
        return
    write(rows, conn, a.rebuild)
    print("\n■ 写库完成。")


if __name__ == "__main__":
    main()
