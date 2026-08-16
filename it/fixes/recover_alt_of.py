#!/usr/bin/env python3
"""阶段 2a：把被误判成「变形形」的异体/缩写词条移回词条层。2026-08-13。

═══ 缺陷 ═══
建库时 `alt_of` 和 `form_of` 被一起当成变形指针丢掉了。后果是 **7,028 个词形在界面上
一条释义都没有，只显示一句错话**：

    bce    →「Banca Centrale Europea 的变位形式」   实际是**首字母缩写**（欧洲央行）
    abaca  →「abacà 的变位形式」                     实际是**异体写法**
    the    →「tè 的变位形式」                        实际是**误拼**（维基把常见错拼也收了）
    sun    →「su used before a vowel 的变位形式」    模板连英文说明一起吞了

这是 `SCHEMA` §9.1 那条缺陷的 it 版本，es 上是 5,701 个词（`levantarse`/`Méjico`），
it 是 **7,699 个词形 / 8,263 条义项** —— 用同一套解析逻辑，必然复现，实测确实复现。

⚠️ `form_of` 与 `alt_of` 实测**无交集**（0 条同时有），所以判据干净：
   `form_of` = 真变形（`pie` 是 `pio` 的阴性复数）；`alt_of` = 独立词条。

═══ 中文标签用模板确定性生成，不调模型 ═══
下表经两位顾问审过（分歧处按理由取舍，记在 `it-CONVENTIONS` A25）：
  · `apocopic`「省尾」而不是「截尾」—— 否则与 `clipping`「截短」难分
  · `misspelling` 必须带**非规范**警示，不能给它异体的正规地位
  · `acronym`（整体拼读）与 `initialism`（逐字母读）中文要能区分

═══ rank 怎么处理 ═══
新义项按 **dump 顺序**插入，不是追加到末尾。实测 335 个词形的 alt 义项夹在中间 ⇒
现有义项的 `rank` 必须重排。`sense.id` **一律保留**（`sense_gloss`/`sense_tag`/
`sense_src`/`entry_id`/`aux` 都挂在它上面）；`rank` 只是展示序，重排不违反 §2.0.1。
⚠️ `UNIQUE(word_id, rank)` ⇒ 必须先把受影响词形的 rank 挪到负数区再落最终值。

用法（在 it/ 目录下）：
    python3 fixes/recover_alt_of.py            # 干跑
    python3 fixes/recover_alt_of.py --apply
    python3 fixes/recover_alt_of.py --verify
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build_entry_layer import SRC, assign_seq, replay   # noqa: E402

# 关系类型 → 中文模板。键是 gloss 里 "… of" 之前那段（小写）。
# 🔴 这张表就是最终产物：它错了就是 7,699 个词条一起错。
ZH = {
    "alternative form of": "%s 的异体形式",
    "apocopic form of": "%s 的省尾形式",
    "alternative spelling of": "%s 的异体拼写",
    "misspelling of": "%s 的误拼（非规范写法）",
    "abbreviation of": "%s 的缩写",
    "initialism of": "%s 的首字母缩写",
    "ellipsis of": "%s 的省略式",
    "medieval spelling of": "%s 的中世纪拼写",
    "contraction of": "%s 的缩合形式",
    "archaic form of": "%s 的古体形式",
    "obsolete form of": "%s 的废弃形式",
    "alternative letter-case form of": "%s 的大小写变体",
    "clipping of": "%s 的截短形式",
    "obsolete spelling of": "%s 的废弃拼写",
    "acronym of": "%s 的首字母缩略词",
    "obsolete typography of": "%s 的旧式排印形式",
    "honorific alternative letter-case form of": "%s 的敬称大写变体",
    "dated form of": "%s 的旧式形式",
    "pronunciation spelling of": "%s 的读音拼写",
    "dialect of": "%s 的方言异体",
    "eye dialect spelling of": "%s 的方言音写",
    "syncopic form of": "%s 的中略形式",
    "aphetic form of": "%s 的省首形式",
    "elision of": "%s 的省音形式",
    "informal form of": "%s 的口语形式",
    "poetic form of": "%s 的诗体形式",
    "rare form of": "%s 的罕用形式",
    "nonstandard form of": "%s 的非规范形式",
    "superseded spelling of": "%s 的旧拼写",
    "obsolete plural of": "%s 的废弃复数",
}
FALLBACK = "%s 的变体形式"
HEAD = re.compile(r"^(.*?\bof)\b", re.IGNORECASE)


def zh_label(gloss, targets):
    """→ (中文标签, 用到的模板键 或 None 表示走了兜底)"""
    tgt = "、".join(t for t in targets if t) or "?"
    m = HEAD.match(gloss or "")
    key = m.group(1).lower() if m else None
    tpl = ZH.get(key)
    return (tpl or FALLBACK) % tgt, (key if tpl else None)


def plan(con):
    """→ (每个词形的目标义项序列, 统计)。序列元素 = (gloss, alt_targets, tags, ref, occ, idx)"""
    words = {w.lower(): i for i, w in con.execute("SELECT id, word FROM dict")}
    per_word, entries, dup_groups, stat = replay(paths.KK, set(words))
    seq_of = assign_seq(dup_groups, verbose=False)

    have = defaultdict(list)      # word → [(sense_id, rank, en_gloss)]
    for w, sid, rank, g in con.execute(
            "SELECT d.word, s.id, s.rank, gl.text FROM sense s "
            "JOIN dict d ON d.id = s.word_id "
            "LEFT JOIN sense_gloss gl ON gl.sense_id = s.id AND gl.lang='en' "
            "AND gl.kind='equivalent' AND gl.seq=0 ORDER BY s.word_id, s.rank"):
        have[w.lower()].append((sid, rank, g))

    ent_id = {r: i for i, r in con.execute("SELECT id, src_ref FROM entry")}
    out, miss = {}, Counter()
    for w, items in per_word.items():
        want = []
        for g, k, occ, idx, tags, raw, alt in items:
            (w0, pos0, etym0), ipas = k
            ref = "kk-en:%s:%s:%s:%d" % (w0, pos0, etym0, seq_of.get((k[0], ipas), 0))
            want.append((g, alt, sorted(set(tags) | set(raw)), ref, occ, idx))
        cur = {g: sid for sid, _, g in have.get(w, []) if g is not None}
        if len(cur) != len(have.get(w, [])):
            miss["🔴 库里有义项没有英文 gloss，无法按文字匹配"] += 1
        # 复刻序列必须**包含**库里已有的每一条（只增不改）
        wantset = {x[0] for x in want}
        for sid, _, g in have.get(w, []):
            if g is not None and g not in wantset:
                miss["🔴 库里有、复刻序列没有的义项"] += 1
        out[w] = (want, cur, words[w], ent_id)
    return out, stat, miss


def build_rows(con, planned):
    """→ 要写的各批数据"""
    new_sense, new_gloss, new_src, new_rel, rerank = [], [], [], [], []
    nid = con.execute("SELECT max(id) FROM sense").fetchone()[0]
    stat = Counter()
    tpl_use = Counter()
    for w, (want, cur, wid, ent_id) in planned.items():
        touched = False
        rows = []
        for rank, (g, alt, tags, ref, occ, idx) in enumerate(want, start=1):
            sid = cur.get(g)
            if sid is None:
                nid += 1
                sid = nid
                stat["新建义项"] += 1
                touched = True
                new_sense.append((sid, wid, rank, ent_id.get(ref)))
                new_gloss.append((sid, "en", "equivalent", 0, g, SRC))
                if alt:
                    lab, key = zh_label(g, alt)
                    tpl_use[key or "(兜底)"] += 1
                    new_gloss.append((sid, "zh", "equivalent", 0, lab, "template"))
                    for t in alt:
                        if t:
                            new_rel.append((wid, sid, "alt_of", t,
                                            json.dumps(tags, ensure_ascii=False) if tags else None,
                                            SRC, "%s#%d.%d" % (ref, occ, idx)))
                else:
                    stat["🔴 新建但不是 alt（不该出现）"] += 1
                new_src.append((wid, sid, SRC, "%s#%d.%d" % (ref, occ, idx), "en", g,
                                json.dumps(tags, ensure_ascii=False) if tags else None))
            rows.append((sid, rank))
        # 现有义项的 rank 变了才写
        old = {sid: r for sid, r, _ in
               con.execute("SELECT id, rank, 1 FROM sense WHERE word_id=?", (wid,))}
        if any(old.get(sid) not in (None, r) for sid, r in rows):
            touched = True
        if touched:
            rerank.append((wid, rows))
    return new_sense, new_gloss, new_src, new_rel, rerank, stat, tpl_use


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("alt 词条都有中文标签",
         q("SELECT count(*) FROM sense_relation r JOIN sense s ON s.id=r.sense_id "
           "WHERE r.kind='alt_of' AND NOT EXISTS(SELECT 1 FROM sense_gloss g "
           "WHERE g.sense_id=s.id AND g.lang='zh')"), 0),
        ("中文标签的 src 记为 template（可回归、非模型产出）",
         q("SELECT count(*) FROM sense_gloss g JOIN sense_relation r ON r.sense_id=g.sense_id "
           "WHERE r.kind='alt_of' AND g.lang='zh' AND COALESCE(g.src,'')<>'template'"), 0),
        ("🔴 没有词形还停在「一条义项都没有但有 alt 关系」",
         q("SELECT count(*) FROM sense_relation r WHERE r.kind='alt_of' AND NOT EXISTS("
           "SELECT 1 FROM sense s WHERE s.word_id=r.word_id AND COALESCE(s.hidden,0)=0)"), 0),
        ("每个词形的 rank 连续无空洞",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("alt 义项都挂上了 entry",
         q("SELECT count(*) FROM sense_relation r JOIN sense s ON s.id=r.sense_id "
           "WHERE r.kind='alt_of' AND s.entry_id IS NULL"), 0),
        ("新义项都有 sense_src 证据",
         q("SELECT count(*) FROM sense_relation r JOIN sense s ON s.id=r.sense_id "
           "WHERE r.kind='alt_of' AND NOT EXISTS(SELECT 1 FROM sense_src x "
           "WHERE x.sense_id=s.id AND x.src=?)", SRC), 0),
        # 🔴 原来写死 92,385 —— 阶段 3b 收词又灌进 13,089 条就必然红（A28）。
        #    改成结构性口径：本脚本只写 en-edition 的行，绝不给意语证据加 src_ref 前缀之外的东西。
        ("🔴 意语版证据没被本脚本污染（前缀仍是 kk-it:）",
         q("SELECT count(*) FROM sense_src WHERE src='it-edition' "
           "AND src_ref NOT LIKE 'kk-it:%'"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-48s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1

    planned, rstat, miss = plan(ro)
    for k, v in miss.most_common():
        print("   %-40s %8s" % (k, f"{v:,}"))
    ns, ng, nsrc, nrel, rerank, stat, tpl = build_rows(ro, planned)
    print("\n■ 将新建义项 %s 条 / 中文标签 %s 条 / 关系 %s 条 / 需重排 rank 的词形 %s 个"
          % (f"{len(ns):,}", f"{sum(1 for g in ng if g[1]=='zh'):,}",
             f"{len(nrel):,}", f"{len(rerank):,}"))
    print("\n■ 中文模板用量：")
    for k, v in tpl.most_common(12):
        print("   %-42s %6s" % (k, f"{v:,}"))
    if tpl.get("(兜底)"):
        print("   ⚠️ 兜底 %d 条 —— 上界，记账不追" % tpl["(兜底)"])
    for k, v in stat.most_common():
        print("   %-30s %8s" % (k, f"{v:,}"))
    ro.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("recover-alt-of",
                        expect={"#sense": len(ns), "#sense_src": len(nsrc),
                                "#sense_gloss": len(ng), "#sense_relation": len(nrel)}) as s:
        # ⚠️ UNIQUE(word_id, rank)：先把受影响词形的 rank 挪到负数区，再落最终值
        for wid, rows in rerank:
            s.execute("UPDATE sense SET rank = -rank WHERE word_id=?", (wid,))
        s.executemany("INSERT INTO sense (id,word_id,rank,entry_id) VALUES (?,?,?,?)", ns)
        for wid, rows in rerank:
            s.executemany("UPDATE sense SET rank=? WHERE id=?",
                          [(r, sid) for sid, r in rows])
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,?,?,?,?,?)", ng)
        s.executemany("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags) "
                      "VALUES (?,?,?,?,?,?,?)", nsrc)
        s.executemany("INSERT INTO sense_relation (word_id,sense_id,kind,target,tags,src,src_ref) "
                      "VALUES (?,?,?,?,?,?,?)", nrel)
    print("\n■ 已写入")
    return 0


if __name__ == "__main__":
    sys.exit(main())
