#!/usr/bin/env python3
"""把法语版/意语版收进来的词条也建进 `entry` 层。2026-08-16。

═══ 缺口 ═══
`entry` 层 621,099 行**全部来自英文版复刻**（`build_entry_layer.py` 是逐条重放
英文 dump 的）。而后来从法语版收的 16.6 万专名、意语版收的 1.1 万词
**从没进过那次复刻**，于是：

    是 lemma 但没有 entry 行的词形   178,558
    其中 dict.pos 也是空的           182,325（两者高度重叠）

后果是 `entry` 层这个"词条＝词×词性×词源"的抽象**只覆盖了库的一半**，
凡是走 `COALESCE(e.pos, s.pos)` 的地方都在拿 fallback 顶着（今天已经有两处
闸因此写错过判据）。`SCHEMA` §10 的模型在这一半上等于没落地。

═══ 做法：不扫 dump，从库里已有的证据推 ═══
每条义项都有 `sense_src.src_ref`，形如：

    kk-fr:Bolotana:name#0.0        法语版
    kk-it:casa:noun#0.1            意语版
    kk-en:gratis:adv:0:0#0.0       英文版（已建过）

**词性就在 src_ref 里**，是 kaikki 原值。⇒ 词性从这里取，不从 `sense.pos` 反推
（`sense.pos` 已归一成展示层短码，反推会碰上 `phrase`/`adv_phrase` 都映射成 `phr`
的多对一，而 `normalize_sense_pos` 的闸盯着「entry.pos 必须仍是 kaikki 原值」）。

═══ 两种去处 ═══
    · 18,528 条义项的 (词形,词性) **已经有 entry**（英文版建的）⇒ 直接挂上去，不新建
    · 186,185 条要新建 ⇒ 去重后 183,094 行 entry
      （其中 5 组同一 (词形,词性) 同时来自法语版和意语版，合并成一行，
       `src` 记先到的那一版）

`src_ref = kk-<版>:<词形>:<词性>:0:0` —— 与英文版同格式、内容派生、可复算。
`etym_no` 记 `0`：这两版的 dump 不带词源号，**不知道就记 0，不编**。

═══ 闸 ═══
① 可复算：把库里本步建的 entry 的 `src_ref` 按同一规则重算，**逐字节**比对
② 反错配：每条义项挂的 entry，其 `word_id` 必须等于义项自己的 `word_id`，
   其 `pos` 必须等于该义项证据 `src_ref` 里的词性 —— 这是本步唯一可能造成的灾难
③ 无孤儿：新建的 entry 每一行都至少挂着一条义项
④ `entry.pos` 仍全是 kaikki 原值（不许混进展示层短码）

用法（在 it/ 目录下）：
    python3 pipeline/extend_entry_layer.py
    python3 pipeline/extend_entry_layer.py --apply
    python3 pipeline/extend_entry_layer.py --verify
    python3 pipeline/extend_entry_layer.py --mutate
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build import POS_MAP   # noqa: E402  只用来做闸④的反向断言

# `kk-<版>:<词形>:<词性>` + 可选的 `:词源:序号` + 可选的 `#位置`
REF = re.compile(r"^kk-(?P<ed>[a-z]+):(?P<word>.*):(?P<pos>[a-z_]+)(?::\d+:\d+)?(?:#.*)?$")


def parse_ref(ref):
    m = REF.match(ref or "")
    return (m.group("ed"), m.group("pos")) if m else (None, None)


def src_ref_of(ed, word, pos):
    """与英文版同格式、内容派生。词形唯一（实测 767,289/767,289），可当主键用。"""
    return "kk-%s:%s:%s:0:0" % (ed, word, pos)


def plan(con):
    """→ (新建 [(word_id, word, pos, ed)], 挂已有 [(sense_id, entry_id)], 统计)"""
    ent = {}
    for eid, wid, pos in con.execute("SELECT id, word_id, pos FROM entry"):
        ent.setdefault((wid, pos), eid)
    word = dict(con.execute("SELECT id, word FROM dict"))
    fresh, link, st = {}, [], Counter()
    seen_sense = set()
    for sid, wid, ref in con.execute(
            "SELECT s.id, s.word_id, x.src_ref FROM sense s "
            "JOIN sense_src x ON x.sense_id=s.id "
            "WHERE s.entry_id IS NULL AND COALESCE(s.hidden,0)=0 ORDER BY s.id, x.id"):
        if sid in seen_sense:          # 一条义项可能挂多条证据，取第一条
            continue
        ed, pos = parse_ref(ref)
        if not pos:
            st["🔴 src_ref 解析不出词性（跳过）"] += 1
            continue
        seen_sense.add(sid)
        eid = ent.get((wid, pos))
        if eid is not None:
            link.append((sid, eid))
            st["挂到已有 entry（英文版建的）"] += 1
        else:
            # 同一 (词形,词性) 来自两版时合并成一行，src 记先到的
            fresh.setdefault((wid, pos), (word[wid], ed))
            link.append((sid, (wid, pos)))     # 占位，写库时换成真 id
            st["新建 entry 并挂上"] += 1
    st["🔴 没有任何证据的义项（无从建 entry）"] = con.execute(
        "SELECT count(*) FROM sense s WHERE s.entry_id IS NULL AND COALESCE(s.hidden,0)=0 "
        "AND NOT EXISTS(SELECT 1 FROM sense_src x WHERE x.sense_id=s.id)").fetchone()[0]
    rows = [(wid, w, pos, ed) for (wid, pos), (w, ed) in fresh.items()]
    return rows, link, st


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    rows, link, st = plan(con)
    # ① 本步建的 entry，src_ref 必须能按同一规则逐字节重算出来
    bad_ref = sum(1 for eid, wid, pos, sr, src in con.execute(
        "SELECT e.id, e.word_id, e.pos, e.src_ref, e.src FROM entry e "
        "WHERE e.src IN ('fr-edition','it-edition')")
        for w in [con.execute("SELECT word FROM dict WHERE id=?", (wid,)).fetchone()[0]]
        if sr != src_ref_of(src.split("-")[0], w, pos))
    # ② 反错配：义项挂的 entry 必须同词形、且词性等于证据里的词性
    cross = q("SELECT count(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
              "WHERE e.word_id <> s.word_id")
    posbad = 0
    for pos, ref in con.execute(
            "SELECT e.pos, x.src_ref FROM sense s JOIN entry e ON e.id=s.entry_id "
            "JOIN sense_src x ON x.sense_id=s.id WHERE e.src IN ('fr-edition','it-edition')"):
        if parse_ref(ref)[1] != pos:
            posbad += 1
    checks = [
        ("🔴 没有还能建 entry 却没建的", len(rows), 0),
        ("🔴 没有还能挂却没挂的义项", len(link), 0),
        ("🔴 本步建的 entry.src_ref 逐字节可复算", bad_ref, 0),
        ("🔴 义项挂的 entry 必须是同一个词形（反错配）", cross, 0),
        ("🔴 entry.pos 必须等于该义项证据里的词性（反错配）", posbad, 0),
        ("🔴 本步建的 entry 不许有孤儿（没有义项挂着）",
         q("SELECT count(*) FROM entry e WHERE e.src IN ('fr-edition','it-edition') "
           "AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.entry_id=e.id)"), 0),
        ("🔴 entry.pos 仍全是 kaikki 原值，没混进展示层短码",
         sum(1 for (p,) in con.execute("SELECT DISTINCT pos FROM entry")
             if p not in POS_MAP), 0),
        # 🔴 已接受基线 27 + 理由：这 27 条义项**一条证据都没有**，
        #    无从判断它属于哪个词条。不编，记账。
        ("没有任何证据的义项（基线 27）", st["🔴 没有任何证据的义项（无从建 entry）"], 27),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-46s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def mutate(con):
    """闸②是本步唯一可能造成灾难的地方（义项挂到别的词条上），必须真能逮住。"""
    import contextlib
    import io
    import os
    import shutil
    tmp = Path(os.environ.get("CLAUDE_JOB_DIR", "/tmp")) / "tmp" / "entry_mut.sqlite"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    n = con.execute("SELECT count(*) FROM entry WHERE src IN ('fr-edition','it-edition')").fetchone()[0]
    if not n:
        print("\n（还没建过，先 --apply 再验）")
        return False
    cases = [
        ("把一条义项挂到别的词形的 entry 上",
         "UPDATE sense SET entry_id=(SELECT id FROM entry WHERE word_id<>sense.word_id LIMIT 1) "
         "WHERE id=(SELECT s.id FROM sense s JOIN entry e ON e.id=s.entry_id "
         "WHERE e.src='fr-edition' LIMIT 1)"),
        ("把一条 entry 的词性改掉",
         "UPDATE entry SET pos='verb' WHERE id=(SELECT id FROM entry WHERE src='fr-edition' "
         "AND pos='name' LIMIT 1)"),
        ("篡改一条 entry 的 src_ref",
         "UPDATE entry SET src_ref='kk-fr:XXX:name:0:0' WHERE id="
         "(SELECT id FROM entry WHERE src='fr-edition' LIMIT 1)"),
        ("解开一条义项的 entry_id（该报「还能挂却没挂」）",
         "UPDATE sense SET entry_id=NULL WHERE id=(SELECT s.id FROM sense s "
         "JOIN entry e ON e.id=s.entry_id WHERE e.src='fr-edition' LIMIT 1)"),
    ]
    print("\n═══ 变异验证 ═══")
    ok = True
    for name, sql in cases:
        shutil.copy(paths.DB, tmp)
        c = sqlite3.connect(tmp)
        c.execute(sql)
        c.commit()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = gate(c)
        c.close()
        red = not res
        ok &= red
        print("   %s %-40s %s" % ("✅" if red else "🔴", name,
                                  "闸红了（对）" if red else "闸没红 —— 这条闸是假的"))
    tmp.exists() and tmp.unlink()
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 有闸是假的"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    if a.mutate:
        return 0 if mutate(ro) else 1
    rows, link, st = plan(ro)
    for k, v in st.most_common():
        print("   %-42s %7s" % (k, f"{v:,}"))
    print("\n■ 将新建 entry %s 行，挂上义项 %s 条" % (f"{len(rows):,}", f"{len(link):,}"))
    pos_c = Counter(p for _w, _wd, p, _e in rows)
    print("   词性分布：%s" % ", ".join("%s=%s" % (p, f"{n:,}") for p, n in pos_c.most_common(8)))
    for wid, w, pos, ed in rows[:8]:
        print("   %-26s %-10s %s" % (w[:26], pos, src_ref_of(ed, w, pos)))
    ro.close()
    if not a.apply or not rows:
        print("\n(未加 --apply，不写库)" if not a.apply else "")
        return 0
    with dbtool.session("extend-entry-layer",
                        expect={"#entry": len(rows), "#sense": 0}) as s:
        eid_of = {}
        for wid, w, pos, ed in rows:
            cur = s.execute(
                "INSERT INTO entry (word_id,pos,etym_no,seq,src,src_ref) VALUES (?,?,'0',0,?,?)",
                (wid, pos, ed + "-edition", src_ref_of(ed, w, pos)))
            eid_of[(wid, pos)] = cur.lastrowid
        s.executemany("UPDATE sense SET entry_id=? WHERE id=?",
                      [(eid_of[t] if isinstance(t, tuple) else t, sid) for sid, t in link])
    print("\n■ 已建 entry %s 行" % f"{len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
