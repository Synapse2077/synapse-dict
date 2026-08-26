#!/usr/bin/env python3
"""阶段 3a：拆开建库时被大小写折叠掉的词形。2026-08-22。

═══ 缺陷 ═══
`build.py:388` 用 `key = word.lower()` 建 `words` 字典 ⇒ dump 里 **388,992** 个法语词形
被压成 **385,216** 行，**吃掉 3,776 个**，而且两边的属性并进了同一行：

    dict `écosse`     pos = 'name/v'   ← **苏格兰**（专名）和 **écosser 的变位**并成一行
    dict `livre`      word_src = Livre / livre
    dict `pie`        word_src = PIE(原始印欧语) / Pie(庇护，教宗名) / pie(喜鹊)
    dict `abbasside`  Abbasside(名词) / abbasside(形容词)

**3,451 族两边词性还不同** ⇒ 属性互相污染。
es 上同一族缺陷已修（`pos` 3,558 行 + `gender` 2,045 行，`[[case-folding-contaminates-columns]]`），
`PLAYBOOK` 第四节把它列为收词第一个必踩的坑：
「大小写折叠去重会吃掉专名词头（es 丢了 573 个）。必须建新行 + 精确大小写作为检索第一排序键。」

═══ 为什么必须排在收词（3b）之前 ═══
3b 要从法文版吃进 166.7 万词形、**保留精确大小写**。
如果先收词：`Écosse` 会作为新行插进来拿到法文版义项，
而英文版给的「苏格兰」义项还留在折叠行 `écosse` 上 —— **同一个词裂成两行、各拿一半**。
⇒ 先拆干净，再收词。

═══ 凭据是 `entry.word_src` ═══
阶段 1 建 `entry` 时特意存了 dump 的真实大小写。实测：
    3,764 个 dict 行挂着多个 word_src（拆 2 路 3,753 / 3 路 10 / 4 路 1）
    `dict.word` **100%** 在它自己的 word_src 集合里（0 例外）⇒ 原行留着自己的拼写，其余拼写建新行

═══ 🔴 一个明说的例外：本步会写 `definition`/`translation`/`meta` ═══
阶段 0 我定过「这五列是**只读的迁移锚点**，任何脚本不许再写」。本步开一个**窄口子**：

    只对本步动到的 3,764 个原行 + 3,776 个新行，**从新表重新生成**这三列。

理由：那条规则是为了防**静默分叉**（`[[fix-regression-and-gate]]` 的"被绕过"）。
而这里是反过来的 —— 义项已经搬到新行去了，不重算的话 `livre` 的 `definition`
里会**继续留着 `Livre` 的释义**，那才是分叉。重算是让旧列跟着新表走，不是绕过它。
⚠️ 迁移锚点本身**不受影响**：它冻在 `pre-keep-v3-entry-20260822-103348.bak` 里，
   已用 `build_v3_schema.py --verify --db <该备份>` 复验通过（四列逐字节一致）。

═══ 新行拿不到的列，本步不猜 ═══
`ipa` / `level` / `aux` / `vgroup` / `pp` / `plural` / `feminine` / `adj_pos` / `government`
这些是建库时按**折叠键**算的，拆不开谁属于谁。**新行一律留 NULL**，记账：
  · `ipa` 归阶段 4（那一步本来就要按 `word_src` 逐条从 dump 重建 `pronunciation`）
  · 其余归阶段 1 的「法语一等字段进 entry」那件事（`entry` 已经建好了列）
**不从原行复制** —— 复制等于把一个可能属于另一个词的值说成是它的（错比缺更伤权威）。

用法（在 fr/ 目录下）：
    python3 pipeline/split_case_folded.py            # 干跑
    python3 pipeline/split_case_folded.py --apply
    python3 pipeline/split_case_folded.py --verify
"""
import argparse
import json
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402


def unaccent(s):
    """与 `build.py:139-142` 逐字一致。改这里就等于改了 `word_norm` 的口径。"""
    nfd = unicodedata.normalize("NFD", s.lower())
    out = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return out.replace("œ", "oe").replace("æ", "ae")


def plan(con):
    """→ [(原 word_id, 原拼写, [要拆出去的拼写…])]，以及每个拼写各自的 entry_id。"""
    sp = defaultdict(lambda: defaultdict(list))     # word_id → word_src → [entry_id]
    for eid, wid, ws in con.execute("SELECT id, word_id, word_src FROM entry"):
        sp[wid][ws].append(eid)
    w_of = dict(con.execute("SELECT id, word FROM dict"))
    out = []
    for wid, by in sp.items():
        if len(by) < 2:
            continue
        keep = w_of[wid]
        assert keep in by, "dict.word %r 不在自己的 word_src 里" % keep
        out.append((wid, keep, {s: e for s, e in by.items() if s != keep}, by[keep]))
    return out, w_of


def pos_of(con, entry_ids):
    """该批 entry 的词性并集，格式与 `build.py:603` 一致：排序后 '/' 连接。"""
    if not entry_ids:
        return None
    q = ",".join("?" * len(entry_ids))
    ps = {r[0] for r in con.execute(
        "SELECT DISTINCT pos FROM entry WHERE id IN (%s)" % q, entry_ids) if r[0]}
    return "/".join(sorted(ps)) if ps else None


def gender_of(con, sense_ids):
    """该批义项的性别并集：只有 m → m，只有 f → f，两者都有 → mf。"""
    if not sense_ids:
        return None
    q = ",".join("?" * len(sense_ids))
    gs = {r[0] for r in con.execute(
        "SELECT DISTINCT gender FROM sense WHERE id IN (%s)" % q, sense_ids) if r[0]}
    if not gs:
        return None
    if gs == {"m"}:
        return "m"
    if gs == {"f"}:
        return "f"
    return "mf" if {"m", "f"} & gs else sorted(gs)[0]


def rebuild_legacy(con, sense_ids):
    """从新表重建 (definition, translation, meta)。规则与 `build_v3_schema.rebuild()` 同源。"""
    if not sense_ids:
        return None, None, None
    q = ",".join("?" * len(sense_ids))
    rows = list(con.execute(
        "SELECT id, rank, pos, gender FROM sense WHERE id IN (%s) ORDER BY rank" % q, sense_ids))
    gl = defaultdict(dict)
    for sid, lang, text in con.execute(
            "SELECT sense_id, lang, text FROM sense_gloss "
            "WHERE kind='equivalent' AND seq=0 AND sense_id IN (%s)" % q, sense_ids):
        gl[sid][lang] = text
    tg = defaultdict(lambda: defaultdict(list))
    for sid, kind, value in con.execute(
            "SELECT sense_id, kind, value FROM sense_tag WHERE sense_id IN (%s)" % q, sense_ids):
        tg[sid][kind].append(value)
    en = [gl[s].get("en") for s, _, _, _ in rows]
    zh = [gl[s].get("zh", "") for s, _, _, _ in rows]
    blank = lambda t: None if (t is None or t.strip() == "") else t
    if not any(x is not None for x in en):
        return None, blank("\n".join(zh)), None    # 只有中文那族（阶段 0 的 58 条）
    meta = []
    for sid, _, pos, g in rows:
        o = {"pos": pos}
        if tg[sid].get("register"):
            o["lex"] = sorted(tg[sid]["register"])
        if tg[sid].get("region"):
            o["reg"] = sorted(tg[sid]["region"])
        if g:
            o["g"] = g
        meta.append(o)
    # 🔴 空串一律写 NULL：`dbtool.snapshot()` 数的是 `TRIM(COALESCE(col,''))<>''`，
    #    ''（或只有换行）在它眼里是"空"，在 `IS NOT NULL` 眼里是"有值" —— 两套口径。
    #    实测踩到 3 行（`mademoiselles` / `Maj` / `À`，正是前面有意留空中文的那几条）。
    return (blank("\n".join(x or "" for x in en)), blank("\n".join(zh)),
            json.dumps(meta, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(con)

    todo, w_of = plan(con)
    st = Counter()
    n_new = sum(len(x[2]) for x in todo)
    print("■ 要拆的 dict 行 %s → 新增 %s 行" % (f"{len(todo):,}", f"{n_new:,}"))
    print("   拆几路：", dict(sorted(Counter(len(x[2]) + 1 for x in todo).items())))

    # 每个 entry 底下的义项与变形
    sense_of = defaultdict(list)
    for sid, eid in con.execute("SELECT id, entry_id FROM sense WHERE entry_id IS NOT NULL"):
        sense_of[eid].append(sid)
    infl_of = defaultdict(list)
    for iid, eid in con.execute("SELECT id, entry_id FROM inflection WHERE entry_id IS NOT NULL"):
        infl_of[eid].append(iid)

    print("\n── 样本 ──")
    for wid, keep, others, keep_eids in todo[:6]:
        ks = sum(len(sense_of[e]) for e in keep_eids)
        line = "   %-12r 留 %-10r(义项%d) " % (w_of[wid], keep, ks)
        for s, eids in sorted(others.items()):
            line += "| 拆出 %r(义项%d) " % (s, sum(len(sense_of[e]) for e in eids))
        print(line)
    for wid, keep, others, keep_eids in todo:
        st["搬走的义项"] += sum(len(sense_of[e]) for s, es in others.items() for e in es)
        st["搬走的变形"] += sum(len(infl_of[e]) for s, es in others.items() for e in es)
        st["搬走的 entry"] += sum(len(es) for es in others.values())
        if not keep_eids or not any(sense_of[e] for e in keep_eids):
            st["🔴 拆完之后原行一条义项都不剩"] += 1
    for k, v in sorted(st.items()):
        print("   %-32s %8s" % (k, f"{v:,}"))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    return apply_(con, todo, w_of, sense_of, infl_of, n_new)


def apply_(con, todo, w_of, sense_of, infl_of, n_new):
    nid = con.execute("SELECT max(id) FROM dict").fetchone()[0]
    new_rows, mv_entry, mv_sense, mv_infl, legacy, ranks, fix_orig = [], [], [], [], [], [], []

    for wid, keep, others, keep_eids in todo:
        for s_, eids in sorted(others.items()):
            nid += 1
            sids = [x for e in eids for x in sense_of[e]]
            iids = [x for e in eids for x in infl_of[e]]
            new_rows.append((nid, s_, unaccent(s_), pos_of(con, eids),
                             1 if sids else 0, gender_of(con, sids)))
            mv_entry += [(nid, e) for e in eids]
            mv_sense += [(nid, x) for x in sids]
            mv_infl += [(nid, x) for x in iids]
            for r, x in enumerate(sorted(sids), 1):
                ranks.append((r, x))
            legacy.append((nid, sids))
        keep_sids = [x for e in keep_eids for x in sense_of[e]]
        # 原行上还有 entry_id 为空的义项（阶段 0 的 58 条中文孤儿），一并留下
        keep_sids += [r[0] for r in con.execute(
            "SELECT id FROM sense WHERE word_id=? AND entry_id IS NULL", (wid,))]
        for r, x in enumerate(sorted(keep_sids), 1):
            ranks.append((r, x))
        legacy.append((wid, keep_sids))
        # 🔴 原行的 pos/gender 也必须重算 —— 这才是"属性互相污染"的修复本身。
        #    不重算的话 `écosse` 拆完仍写着 `name/v`（苏格兰的 name 已经搬走了）。
        fix_orig.append((pos_of(con, keep_eids), gender_of(con, keep_sids), wid))

    # ── 预先把四个受影响列的增量算准，不用 None 逃生 ──────────────────
    old_col = {c: dict(con.execute("SELECT id, %s FROM dict" % c))
               for c in ("pos", "gender", "definition", "translation", "meta")}
    legacy_vals = [(*rebuild_legacy(con, sids), w) for w, sids in legacy]
    newv = {c: {} for c in old_col}
    for nid_, w_, wn_, pos_, il_, g_ in new_rows:
        newv["pos"][nid_], newv["gender"][nid_] = pos_, g_
    for pos_, g_, wid in fix_orig:
        newv["pos"][wid], newv["gender"][wid] = pos_, g_
    for d_, t_, m_, wid in legacy_vals:
        newv["definition"][wid], newv["translation"][wid], newv["meta"][wid] = d_, t_, m_

    expect = {"__rows__": n_new}
    for c in ("pos", "gender", "definition", "translation", "meta"):
        # 🔴 判据必须与闸**逐字一致**：`snapshot()` 用 `TRIM(COALESCE(col,''))<>''`，
        #    不是 `IS NOT NULL`。我第一版用了后者，3 行空串被算成"有值"，闸红 +235 vs +238。
        #    **预测用的口径和被预测的口径不同，那个预测就没有意义。**
        nonempty = lambda x: x is not None and str(x).strip() != ""
        delta = 0
        for k, v in newv[c].items():
            was = old_col[c].get(k)             # 新行在 old_col 里查不到 ⇒ None
            delta += (1 if nonempty(v) else 0) - (1 if nonempty(was) else 0)
        expect[c] = delta
    print("\n■ 预期增量（**先算准再写，不用 None 逃生**）")
    for k, v in expect.items():
        print("   %-14s %+8d" % (k, v))
    print("■ 将写入：新 dict 行 %s | 搬 entry %s | 搬义项 %s | 搬变形 %s | 重排 rank %s | 修原行 %s"
          % (f"{len(new_rows):,}", f"{len(mv_entry):,}", f"{len(mv_sense):,}",
             f"{len(mv_infl):,}", f"{len(ranks):,}", f"{len(fix_orig):,}"))
    con.close()

    with dbtool.session("keep-v3-splitcase", expect=expect) as s:
        s.executemany(
            "INSERT INTO dict (id, word, word_norm, pos, is_lemma, gender) VALUES (?,?,?,?,?,?)",
            new_rows)
        s.executemany("UPDATE entry SET word_id=? WHERE id=?", mv_entry)
        s.executemany("UPDATE sense SET word_id=? WHERE id=?", mv_sense)
        s.executemany("UPDATE inflection SET word_id=? WHERE id=?", mv_infl)
        # ⚠️ UNIQUE(word_id, rank)：先挪负数区再落最终值
        s.executemany("UPDATE sense SET rank=-rank WHERE id=?", [(x,) for _, x in ranks])
        s.executemany("UPDATE sense SET rank=? WHERE id=?", ranks)
        s.executemany("UPDATE dict SET pos=?, gender=? WHERE id=?", fix_orig)
        s.executemany(
            "UPDATE dict SET definition=?, translation=?, meta=? WHERE id=?", legacy_vals)

    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


def verify(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    # 🔴 用 Python 折叠，不用 SQLite 的 lower()（它是 ASCII-only，会给 113 行假红）
    exact = sum(1 for a, b in con.execute(
        "SELECT e.word_src, d.word FROM entry e JOIN dict d ON d.id=e.word_id") if a != b)
    checks = [
        ("🔴 entry.word_src != dict.word（本步的目标：精确相等）", exact, 0),
        ("dict 行数", q("SELECT count(*) FROM dict"), 385216 + 3776),
        ("义项总数不变（只搬不增不减）", q("SELECT count(*) FROM sense"), 124766),
        ("变形总数不变", q("SELECT count(*) FROM inflection"), 331377),
        ("rank 不从 1 连续的词形",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("孤儿 sense", q("SELECT count(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id "
                         "WHERE d.id IS NULL"), 0),
        ("孤儿 inflection", q("SELECT count(*) FROM inflection i LEFT JOIN dict d ON d.id=i.word_id "
                              "WHERE d.id IS NULL"), 0),
        ("word_norm 为空", q("SELECT count(*) FROM dict WHERE word_norm IS NULL OR word_norm=''"), 0),
        ("🔴 仍有 dict 行挂多个 word_src",
         q("SELECT count(*) FROM (SELECT word_id FROM entry GROUP BY word_id "
           "HAVING count(DISTINCT word_src)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %9s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    print("\n%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
