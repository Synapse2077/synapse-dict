#!/usr/bin/env python3
"""阶段 6a：**例句层** —— `example`／`example_gloss`。ru，2026-10-23。**不花钱**；
例句的中文翻译（6d）是另一个文件、另一次拍板。

    python3 -u ru/pipeline/example_layer.py --dry
    python3 -u ru/pipeline/example_layer.py
    python3 -u ru/pipeline/example_layer.py --rebuild     # 判据改了（本层尚无付费数据时）
    python3 -u ru/pipeline/example_layer.py --sync [--dry]  # 判据改了而已有付费译文（6d 之后）：原地同步出版列

判据一条都不在本文件里写 —— `criteria` §⑪。依据见 RU_PLAN §十三。

═══ 挂靠：例句挂在义项上，键是 `sense_src.src_ref` ＝ `<entry.src_ref>#s<si>` ═══
四级落点（探针 §A），每一级都是一个独立计数，不是一个「挂不上」：
    ① 该义项可出版           ⇒ `sense_id` ＝ 那条义项
    ② 该义项被藏             ⇒ `sense_id` NULL，挂 entry
    ③ 该义项只在证据层       ⇒ NULL，挂 entry（指针义项／fr·vi·pl 不出版的释义语言）
    ④ 该义项压根没进 sense_src（没有释义）⇒ NULL，挂 entry
🔴 ③ 在 fr/vi/pl 三版上是 94–98%：那三版的**释义**按三语方针不出版，可它们的**例句是俄语**，
   对读者有用 ⇒ 照收、挂 entry。`[[dont-say-source-lacks-what-we-skipped]]`：这是结构上分开的。

═══ 两列：`text`（dump 原文）／`text_pub`（印给读者的）═══
见 criteria §⑪ 开头。**唯一的例外是 zh-s 版**：源头的例句边界切错了（俄₁中₁俄₂中₂ 被切在中文句号后），
`criteria.zh_simp_pairs` 按文字系统交界重切 ⇒ 一行 ＝ 重切出的一对，`text` 存俄语那一段，
`src_ref` 带 `#p<n>`（不是源头的例句序号）。外锚闸要 import 同一个函数，不许自己重写。

═══ 同一格里的重复：藏不删（vi W24）═══
读者口径的格 ＝ (词形, 义项) ；义项为空的 ＝ (词形, entry) 的「例句」区。
同一格里正文相同（去重音/标点/大小写）的留一行，其余 `hidden_why='同一格里重复'`。
留哪一行：有中文译文 ＞ 有英文译文 ＞ 有出处 ＞ 版序（`build.SRC`）＞ src_ref。

═══ ⭐ 白捡的中文：同一个词形下**一字不差**的句子，别的版给了中文译文 ═══
zh-t 版大量照抄 en 版的例句并配了中文（探针 §A：zh-t 版同词跨版重复 9,498）。
en 版那一条挂在 en 义项下，读者在那一格看不到中文 ⇒ 借用，`src` 记 `<出处版>:同句`。
⚠️ 只在**同一个词形**下借（同一句话在别的词条下可能是另一个意思的例子，但译文是句子的译文，
   限定同词形是为了让「借」可审计：一个词页上两条一模一样的句子，一条有中文一条没有）。
"""
import argparse
import collections
import re
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
DUP = "同一格里重复"
ZH_SPLIT_FAIL = "zh-s 纸质词典俄中混排、切不开（R3）"


def dup_key(text):
    """格内去重的正文键：去重音、去标点空白、折大小写、ё→е。"""
    t = criteria.strip_stress(text or "").lower().replace("ё", "е")
    return re.sub(r"[\W_]+", "", t)


def collect(conn, limit=None, verbose=True):
    """→ (rows, glosses, stat)。rows 是元组：
    (id, word_id, entry_id, sense_id, text, text_pub, ref, why, src, src_ref, tags)；
    `tags`（R25，2026-11-05）＝ `criteria.example_tags(x)`，加在**末尾**，前十个位置不变（闸按位置读）；
    glosses：(example_id, lang, text, src)。**只读**。"""
    wid = dict(conn.execute("SELECT word, id FROM dict"))
    eid = dict(conn.execute("SELECT src_ref, id FROM entry"))
    s_hidden = dict(conn.execute("SELECT id, hidden FROM sense"))
    ssrc = dict(conn.execute("SELECT src_ref, sense_id FROM sense_src"))
    ref = criteria.SrcRef()
    rows, gl = [], {}
    st = collections.Counter()
    nid = 0

    def add(word_id, entry_id, sense_id, text, tp, rf, why, src, sref, g, tags=None):
        nonlocal nid
        nid += 1
        rows.append([nid, word_id, entry_id, sense_id, text, tp if tp != text else None,
                     rf, why, src, sref, tags])
        if tags:
            st["带标签（%s）" % src] += 1
        if g:
            gl[nid] = (g[0], g[1], src)

    for src, p in SRC:
        t0 = time.time()
        for e in rd(p, limit):
            ok, _skip, pos = criteria.entry_accept(e)
            if not ok:
                continue
            w = e["word"]
            no, sub = criteria.etym_no_pair(e)
            sref, _seq = ref.take(src, w, pos, no, sub)
            entry_id = eid.get(sref)
            word_id = wid.get(w) or wid.get(criteria.strip_stress(w))
            for si, s in enumerate(e.get("senses") or []):
                exs = s.get("examples") or []
                if not exs:
                    continue
                if entry_id is None or word_id is None:
                    st["🔴 挂不上 entry/dict"] += len(exs)
                    continue
                key = "%s#s%d" % (sref, si)
                if key not in ssrc:
                    land, sense_id = "④ 义项没进 sense_src（无释义）", None
                elif ssrc[key] is None:
                    land, sense_id = "③ 义项只在证据层", None
                elif s_hidden.get(ssrc[key]):
                    land, sense_id = "② 义项被藏", None
                else:
                    land, sense_id = "① 可出版义项", ssrc[key]
                # ── zh-s：整义项重切（criteria §⑪）
                if src == "zh-edition-simp" and not all(
                        criteria.example_gloss(src, x) for x in exs):
                    texts = []
                    for x in exs:
                        texts.append((x.get("text") or "").strip())
                        if x.get("translation"):
                            texts.append(x["translation"].strip())
                    pairs = criteria.zh_simp_pairs(texts)
                    if pairs is not None:
                        for k, (ru, zh) in enumerate(pairs):
                            # v24：`text` 是源头切片；出版正文／译文清私用区字形（criteria §⑪）
                            tp = criteria.example_text_pub(src, ru)
                            why = criteria.example_hidden_why(src, w, tp)
                            add(word_id, entry_id, sense_id, ru, tp, None, why, src,
                                "%s#p%d" % (key, k), None if why else ("zh", criteria.zh_simp_zh_pub(zh)))
                            st["落点 " + land] += 1
                            st["zh-s 重切成对"] += 1
                        st["zh-s 重切的源例句"] += len(exs)
                        continue
                    for xi, x in enumerate(exs):
                        t = (x.get("text") or "").strip()
                        if not t:
                            st["正文空（只有出处）⇒ 不入库"] += 1
                            continue
                        add(word_id, entry_id, sense_id, t, t, (x.get("ref") or "").strip() or None,
                            ZH_SPLIT_FAIL, src, "%s#x%d" % (key, xi), None, criteria.example_tags(x))
                        st["落点 " + land] += 1
                    continue
                for xi, x in enumerate(exs):
                    t = (x.get("text") or "").strip()
                    if not t:
                        st["正文空（只有出处）⇒ 不入库"] += 1
                        continue
                    tp = criteria.example_text_pub(src, t)
                    if tp != t:
                        st["出版正文有清洗（%s）" % src] += 1
                    rf = (x.get("ref") or "").strip() or None
                    # R24：en 版首行是出处 ⇒ 搬进 ref（源头已给 ref 的不覆盖，实测 18 条里 0 条有）
                    tp, head = criteria.example_split_citation(src, tp)
                    if head:
                        st["首行出处搬进 ref（%s）" % src] += 1
                        rf = rf or head
                    why = criteria.example_hidden_why(src, w, tp)
                    g = criteria.example_gloss(src, x)
                    if (x.get("translation") or x.get("english")) and not g:
                        st["译文不收（%s：%s）" % (src, "第四语言/非译文" if not criteria.EX_TR_LANG.get(src)
                                              else "形状不像译文")] += 1
                    add(word_id, entry_id, sense_id, t, tp, rf,
                        why, src, "%s#x%d" % (key, xi), g if not why else None, criteria.example_tags(x))
                    st["落点 " + land] += 1
        if verbose:
            print("   …%s 扫完（%.0fs）" % (src, time.time() - t0), flush=True)

    # ── 同一格里重复：藏不删
    cell = collections.defaultdict(list)
    for r in rows:
        if r[7] is None:
            cell[(r[1], r[3] if r[3] is not None else -r[2], dup_key(r[5] or r[4]))].append(r)
    for grp in cell.values():
        if len(grp) < 2:
            continue
        grp.sort(key=lambda r: (0 if gl.get(r[0], ("",))[0] == "zh" else 1 if r[0] in gl else 2,
                                0 if r[6] else 1, SRC_RANK[r[8]], r[9]))
        keep = grp[0]
        for r in grp[1:]:
            r[7] = DUP
            gl.pop(r[0], None)
            st["隐藏：" + DUP] += 1
            if not keep[6] and r[6]:
                keep[6] = r[6]
                st["重复组：出处并到留下来那行"] += 1
    # ── 白捡的中文：同词形下一字不差的句子
    zh_by = {}
    for r in rows:
        g = gl.get(r[0])
        if r[7] is None and g and g[0] == "zh":
            zh_by.setdefault((r[1], dup_key(r[5] or r[4])), (g[1], r[8]))
    borrowed = []
    for r in rows:
        if r[7] is not None or (r[0] in gl and gl[r[0]][0] == "zh"):
            continue
        hit = zh_by.get((r[1], dup_key(r[5] or r[4])))
        if hit:
            borrowed.append((r[0], "zh", hit[0], hit[1] + ":同句"))
    glosses = [(i, g[0], g[1], g[2]) for i, g in sorted(gl.items())] + borrowed
    st["⭐ 同句借中文"] = len(borrowed)
    for r in rows:
        st[("隐藏：" + r[7]) if r[7] else "✅ 可出版"] += 0 if r[7] == DUP else 1
    # ── id 按 `src_ref` 稳定（2026-11-11，R3 例句那一半）：库里已有的行沿用库里的 id，新行从最大 id 往后排。
    #    🔴 以前 id ＝ 重算顺序号 ⇒ 判据一让某个义项多切出/少切出一行，**它后面 33 万行的 id 全部错位**，
    #    而模型译文按 id 挂着 —— 同步只能拒绝。空库（首次建）时与顺序号完全相同。
    old = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='example'").fetchone():
        old = dict(conn.execute("SELECT src_ref, id FROM example"))
    if old:
        nxt = max(old.values())
        remap = {}
        for r in rows:
            if r[9] in old:
                remap[r[0]] = old[r[9]]
            else:
                nxt += 1
                remap[r[0]] = nxt
                st["新 id（库里没有的 src_ref）"] += 1
        for r in rows:
            r[0] = remap[r[0]]
        glosses = [(remap[g[0]],) + tuple(g[1:]) for g in glosses]
    return [tuple(r) for r in rows], glosses, st


def report(rows, glosses, st):
    print("\n■ 例句 %s 行（可出版 %s）／ 译文 %s 条" % (
        F(len(rows)), F(sum(1 for r in rows if r[7] is None)), F(len(glosses))))
    for k, v in sorted(st.items(), key=lambda kv: kv[0]):
        print("   %-56s %10s" % (k, F(v)))
    by = collections.Counter((r[8], r[7] or "✅") for r in rows)
    print("   ── 按版 × 出版/藏：")
    for k, v in sorted(by.items()):
        print("      %-20s %-40s %9s" % (k[0], k[1][:40], F(v)))
    gb = collections.Counter((g[1], g[3]) for g in glosses)
    print("   ── 译文按语种 × 来源：%s" % dict(gb))
    pub = {r[0] for r in rows if r[7] is None}
    zh = {g[0] for g in glosses if g[1] == "zh"}
    print("   可出版例句有中文 %s（%.2f%%）⇒ **6d 的付费分母 %s**" % (
        F(len(pub & zh)), 100.0 * len(pub & zh) / max(1, len(pub)), F(len(pub - zh))))


def write(rows, glosses, conn, rebuild=False):
    have = conn.execute("SELECT COUNT(*) FROM example").fetchone()[0]
    if have and not rebuild:
        raise SystemExit("🔴 `example` 已有 %s 行 —— 要重算就加 `--rebuild`" % F(have))
    paid = conn.execute("SELECT COUNT(*) FROM example_gloss WHERE src LIKE 'model:%'").fetchone()[0]
    if paid:
        raise SystemExit("🔴🔴 `example_gloss` 里有 %s 条模型译文 —— **付费数据，不许 --rebuild**" % F(paid))
    q = lambda s: conn.execute(s).fetchone()[0] if rebuild else 0      # noqa: E731
    exp = {
        "#example": len(rows) - q("SELECT COUNT(*) FROM example"),
        "#example_gloss": len(glosses) - q("SELECT COUNT(*) FROM example_gloss"),
        "example.text_pub": sum(1 for r in rows if r[5] is not None)
        - q("SELECT COUNT(*) FROM example WHERE text_pub IS NOT NULL AND TRIM(text_pub)<>''"),
        "example.entry_id": sum(1 for r in rows if r[2] is not None)
        - q("SELECT COUNT(*) FROM example WHERE entry_id IS NOT NULL"),
        "example.hidden_why": sum(1 for r in rows if r[7])
        - q("SELECT COUNT(*) FROM example WHERE hidden_why IS NOT NULL AND TRIM(hidden_why)<>''"),
        "example.tags": sum(1 for r in rows if r[10]) - q("SELECT COUNT(*) FROM example WHERE tags IS NOT NULL"),
    }
    conn.close()
    with dbtool.session("example-layer" + ("-rebuild" if rebuild else ""), expect=exp,
                        invalidates=["example", "example_gloss"]) as s:
        if rebuild:
            s.execute("DELETE FROM example_gloss")
            s.execute("DELETE FROM example")
        s.executemany("INSERT INTO example(id,word_id,entry_id,sense_id,text,text_pub,ref,hidden,"
                      "hidden_why,src,src_ref,tags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], 1 if r[7] else 0, r[7], r[8], r[9], r[10])
                       for r in rows])
        s.executemany("INSERT INTO example_gloss(example_id,lang,text,src) VALUES (?,?,?,?)", glosses)


def sync(rows, glosses, conn, dry=False):
    """**原地同步**出版列（`text_pub`／`ref`／`hidden`／`hidden_why`），id 与译文一个不动。2026-10-25（R24）。

    6d 之后 `--rebuild` 被付费数据保险拦住（模型译文按 `example.id` 挂着）⇒ 判据改了只能走这里（vi 6e 的 `--sync`）。
    🔴 只许动上面四列：重算出的 id 与库里按 `src_ref` 对不上、源头译文变了、或要把**挂着模型译文**的例句藏起来，
       一律报错退出（那不是同步能处理的事，要单独设计）。
    """
    # R25（2026-11-05）：`tags` 也归同步管（源头标签，不碰译文）；列还没有 ⇒ 当作全空，写库时先建
    has_tags = "tags" in {c[1] for c in conn.execute("PRAGMA table_info(example)")}
    # R3（2026-11-07）：`sense_id` 也归同步管 —— 它跟着「义项藏不藏」走（文件头 ①②），而义项层判据一改，
    #   藏不藏就变了：R3 放出 4,881 条 zh-s 义项后 612 句例句该挂上去、撤下的破例义项上 3 句该解开。
    #   🔴 以前同步不管这一列 ⇒ 外锚闸 X③ 612 条、例句闸 X5 3 条，是义项层改判据之后**第一次**暴露。
    db = {r[0]: r[1:] for r in conn.execute(
        "SELECT src_ref, id, text_pub, ref, hidden_why, %s, sense_id, text FROM example"
        % ("tags" if has_tags else "NULL"))}
    db_src = dict(conn.execute("SELECT src_ref, src FROM example"))
    row_src = {r[9]: r[8] for r in rows}
    # 2026-11-11（R3 例句那一半）：src_ref 集合**可以变，但只许在 zh-s 重切上变** —— 判据让一个义项从「切不开」
    #   变成「切得开」（`#x` 行换成 `#p` 行）、或多切/少切一对。别的版本行集合变了 ⇒ 不是同步能处理的。
    #   id 由 `collect` 按 src_ref 稳定分配（旧行沿用、新行往后排），所以这里还是逐行核 id。
    want_refs = {r[9] for r in rows}
    add_refs, del_refs = want_refs - set(db), set(db) - want_refs
    bad_ref = [x for x in add_refs if row_src[x] != "zh-edition-simp"] + \
        [x for x in del_refs if db_src[x] != "zh-edition-simp"]
    if bad_ref:
        raise SystemExit("🔴 重算的 src_ref 集合与库里不同（多 %d／少 %d），且有非 zh-s 的（%s）—— 不是同步能处理的"
                         % (len(add_refs), len(del_refs), bad_ref[:3]))
    model = dict(conn.execute("SELECT example_id, id FROM example_gloss WHERE src LIKE 'model:%' AND lang='zh'"))
    model_any = {r[0] for r in conn.execute("SELECT DISTINCT example_id FROM example_gloss WHERE src LIKE 'model:%'")}
    del_ids = [db[x][0] for x in del_refs]
    if model_any & set(del_ids):
        raise SystemExit("🔴 要删的例句挂着模型译文 %d 条 —— 单独设计" % len(model_any & set(del_ids)))
    have_g = {tuple(g) for g in conn.execute(
        "SELECT example_id, lang, text, src FROM example_gloss WHERE src NOT LIKE 'model:%'")}
    # 放行的译文变化只有两种：
    #   ① **新的同句借用**（正文改了之后与同词形下一句带源头中文的一字不差）。落在挂着模型中文的例句上
    #      ⇒ **源头中文替换模型中文**（源头优先）；模型原话仍在答案文件里（`[[answer-file-is-the-ledger]]`）。
    #   ② **zh-s 源头中文本身变了**（v24 重切/清私用区字形；含借过去的 `zh-edition-simp:同句`）。
    #   其余源头译文一变就停。
    zs = lambda g: g[3].startswith("zh-edition-simp")                    # noqa: E731
    new_g, gone_g = set(glosses) - have_g, have_g - set(glosses)
    if any(not zs(g) for g in gone_g) or any(not (zs(g) or g[3].endswith(":同句")) or g[1] != "zh" for g in new_g):
        raise SystemExit("🔴 源头译文会变（库里多 %d／少 %d，且不全是 zh-s 或新的同句借用）—— 同步只动出版列"
                         % (len(gone_g), len(new_g)))
    # 🔴 同一 (例句, 语种) 的源头译文只是**文字变了** ⇒ 原地改 `text`、**id 不动**：B30 的改译按
    #    `example_gloss.id` 挂着（`judge_zh_edition_examples.fixes`），删了再插就把改译冲掉（第一次 apply 实测丢 6 条，回滚）。
    gid = {(r[0], r[1]): r[2] for r in conn.execute(
        "SELECT example_id, lang, id FROM example_gloss WHERE src NOT LIKE 'model:%'")}
    gone_by = {(g[0], g[1]): g for g in gone_g}
    re_g = [(g[2], g[3], gid[(g[0], g[1])]) for g in sorted(new_g) if (g[0], g[1]) in gone_by]
    new_g = {g for g in new_g if (g[0], g[1]) not in gone_by}
    want_keys = {(x[0], x[1]) for x in glosses}
    gone_g = {g for k, g in gone_by.items() if k not in want_keys}
    drop_model = [model[g[0]] for g in new_g if g[0] in model]
    print("   源头译文：新 %s／去 %s／原地改 %s（其中替换模型中文 %d）"
          % (F(len(new_g)), F(len(gone_g)), F(len(re_g)), len(drop_model)))
    up, ins, txt = [], [], []
    for r in rows:
        if r[9] in add_refs:
            ins.append((r[0], r[1], r[2], r[3], r[4], r[5], r[6], 1 if r[7] else 0, r[7], r[8], r[9], r[10]))
            continue
        did, tp, rf, why, tg, sid, text = db[r[9]]
        if did != r[0]:
            raise SystemExit("🔴 %s 的 id 变了（库 %d／重算 %d）—— 模型译文按 id 挂着，不许同步" % (r[9], did, r[0]))
        if text != r[4]:
            if "#p" not in r[9]:
                raise SystemExit("🔴 %s 的原文变了 —— 只有 zh-s 重切的行允许（原文是切片）" % r[9])
            txt.append((r[4], r[0]))
        if (tp, rf, why, tg, sid) != (r[5], r[6], r[7], r[10], r[3]):
            if r[7] and not why and r[0] in model_any:
                raise SystemExit("🔴 要藏的 %s 挂着模型译文 —— 单独设计" % r[9])
            up.append((r[5], r[6], 1 if r[7] else 0, r[7], r[10], r[3], r[0]))
    print("   行：新增 %s／删除 %s／原文切片改 %s" % (F(len(ins)), F(len(del_ids)), F(len(txt))))
    print("\n■ 同步：%s 行出版列要改" % F(len(up)))
    for tp, rf, _h, why, _tg, _sid, i in up[:20]:
        print("   %7d  正文 %-40s ｜ ref %s%s" % (i, (tp or "")[:40].replace("\n", "⏎"), (rf or "")[:40],
                                              "  ｜ 藏：" + why if why else ""))
    if dry or not (up or new_g or gone_g or re_g or ins or del_ids or txt):
        print("(干跑)" if dry else "(没有差异)")
        return
    cnt = lambda sql: conn.execute(sql).fetchone()[0]                   # noqa: E731
    exp = {
        "example.text_pub": sum(1 for r in rows if r[5] is not None)
        - cnt("SELECT COUNT(*) FROM example WHERE text_pub IS NOT NULL AND TRIM(text_pub)<>''"),
        "example.hidden_why": sum(1 for r in rows if r[7])
        - cnt("SELECT COUNT(*) FROM example WHERE hidden_why IS NOT NULL AND TRIM(hidden_why)<>''"),
        "#example": len(ins) - len(del_ids),
        "example.entry_id": len(ins) - len(del_ids),            # 每行都有 entry_id ⇒ 跟行数走
        # 去掉的源头译文若带简体出版文本，跟着没了；新插的等 `zh_pub.py --apply` 补
        "example_gloss.text_pub": -sum(cnt("SELECT COUNT(*) FROM example_gloss WHERE example_id=%d AND lang='%s' "
                                           "AND src='%s' AND text_pub IS NOT NULL" % (g[0], g[1], g[3]))
                                       for g in gone_g)
        - sum(cnt("SELECT COUNT(*) FROM example_gloss WHERE example_id=%d AND text_pub IS NOT NULL" % i)
              for i in set(del_ids) - {g[0] for g in gone_g}),      # 删掉的 #p 行的译文已在 gone_g 里算过
        "#example_gloss": len(new_g) - len(gone_g) - len(drop_model),
        "example_gloss.text": None,               # 原地改（`re_g`）
        "example.text": None,                     # zh-s 重切切片（`txt`）
        "example.tags": sum(1 for r in rows if r[10])
        - (cnt("SELECT COUNT(*) FROM example WHERE tags IS NOT NULL") if has_tags else 0),
        "example.sense_id": None,                 # 允许变（R3 之后挂上/解开），数目由外锚闸逐行核
    }
    conn.close()
    with dbtool.session("example-sync-%s" % criteria.RULE_VER, expect=exp, invalidates=[]) as s:
        if not has_tags:
            s.execute("ALTER TABLE example ADD COLUMN tags TEXT")
        s.executemany("DELETE FROM example_gloss WHERE example_id=? AND lang=? AND text=? AND src=?", sorted(gone_g))
        s.executemany("UPDATE example_gloss SET text=?, src=? WHERE id=?", re_g)
        s.executemany("DELETE FROM example_gloss WHERE example_id=?", [(i,) for i in del_ids])
        s.executemany("DELETE FROM example WHERE id=?", [(i,) for i in del_ids])
        s.executemany("INSERT INTO example(id, word_id, entry_id, sense_id, text, text_pub, ref, hidden, hidden_why,"
                      " src, src_ref, tags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ins)
        s.executemany("UPDATE example SET text=? WHERE id=?", txt)
        s.executemany("UPDATE example SET text_pub=?, ref=?, hidden=?, hidden_why=?, tags=?, sense_id=? WHERE id=?", up)
        s.executemany("DELETE FROM example_gloss WHERE id=?", [(i,) for i in drop_model])
        s.executemany("INSERT INTO example_gloss(example_id,lang,text,src) VALUES (?,?,?,?)", sorted(new_g))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--sync", action="store_true", help="判据改了而已有付费译文：原地同步出版列（id 不动）")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("■ 阶段 6a 例句层  判据 %s" % criteria.RULE_VER, flush=True)
    rows, glosses, st = collect(conn, a.limit)
    report(rows, glosses, st)
    if st.get("🔴 挂不上 entry/dict"):
        raise SystemExit("🔴 有例句挂不上 entry —— 重算 src_ref 的顺序与骨架层不一致？先查")
    dbtool.sample_check([(r[8][:5], (r[5] or r[4])[:50], r[7] or "出版") for r in rows], 10,
                        ("源", "出版正文", "出版/藏"))
    if a.sync:
        if a.limit:
            raise SystemExit("🔴 `--sync` 不许和 `--limit` 一起用")
        return sync(rows, glosses, conn, dry=a.dry)
    if a.dry or a.limit:
        print("\n(干跑。)")
        return
    write(rows, glosses, conn, a.rebuild)
    print("\n■ 写库完成。")


if __name__ == "__main__":
    main()
