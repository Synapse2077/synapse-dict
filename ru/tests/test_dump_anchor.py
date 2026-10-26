#!/usr/bin/env python3
"""**外锚闸** —— 九层 vs dump，三向恒等。ru，2026-10-24（阶段 8）。

    python3 -u ru/tests/test_dump_anchor.py                    # 全九层（约 20 分钟，七份 dump 各扫九遍）
    python3 -u ru/tests/test_dump_anchor.py --layer example    # 只跑一层
    python3 -u ru/tests/test_dump_anchor.py --mutate           # 变异（源头侧只算一次、缓存）

`[[external-anchor-gates]]`：**锚外部 dump 的闸永不过期，锚自己上一版的必然过期。**
前十一道闸锚的都是库自己 —— 在「收割器整批漏抽」「后来某一步静默 UPDATE 了一批行」面前它们是绿的。

═══ 🔴🔴 一个判据都不重写 ═══
ko 那道同名闸判据写错两次、方向相反（例句太宽报 3 万假缺／读音太细报 7,163 假缺），根因都是**闸自己重写了收割器的判据**。
⇒ 每层 import 收割器的 `collect()` 本身（ru 的收割器从第一天就是 `collect()`/`write()` 分开的，vi 要先重构四个）。

═══ 三个方向（`[[primary-key-is-not-enough]]`：计数型闸对错配结构性失明）═══
  ①源头有·库里没有  ②库里有·追不回源头  ③**键对上而内容不一样**（逮「某一步 UPDATE 改了文本/隐藏位而没人知道」）

═══ 已知的「库里有而源头没有」：**每一类都要钉住，并断言没有第三类** ═══
（`[[residual-bucket-is-not-evidence]]`：排除一类的时候必须钉住「没有第三类」）
  · 5b 的**模型中文释义**（`sense_gloss.src='model:…'`）＋ **破例义项**（fr/vi/pl 证据挂上的新 `sense` 行）
  · 6d 的**模型中文例句**（`example_gloss.src='model:…'`）
  · R13 把 7 个带重音符的词头并进了孪生行（`build.sync_lemma` 同一条折叠规则）

═══ ⚠️ 它逮不到什么 ═══
收割器的**判据本身写错** —— 判据错两边一起错，恒等式照样成立。那是各层闸「已知答案」与「读者口径」的活。
"""
import argparse
import collections
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402

F = lambda n: format(n, ",")                                    # noqa: E731
MODEL = "model:deepseek-v4-flash"
SHOW = 3
_WANT = {}          # 源头侧缓存（变异只动库，不动 dump）


def _open():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def _diff(name, want, have, eg=None):
    """want/have：{键: 内容元组}。→ [(编号, 说明)]。"""
    miss = [k for k in want if k not in have]
    extra = [k for k in have if k not in want]
    mism = [k for k in want if k in have and want[k] != have[k]]
    out = []
    for tag, ks, what in (("①", miss, "源头有 %s 条，库里没有"), ("②", extra, "库里有 %s 条追不回源头"),
                          ("③", mism, "键对上而内容不一样 %s 条")):
        if ks:
            ex = " ｜ ".join("%s %s→%s" % (str(k)[:50], str(want.get(k))[:60], str(have.get(k))[:60])
                            for k in ks[:SHOW])
            out.append((name + tag, (what % F(len(ks))) + "  " + ex))
    return out


# ════════════════════════════════════ 九层 ════════════════════════════════════
def want_skeleton():
    from pipeline import build
    forms, entries, _st = build.collect(verbose=False)
    con = _open()
    live = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()
    # R13：与 `build.sync_lemma` 同一条折叠规则（剥重音后在库里 ⇒ 并进孪生行；词元取或、词性取并）
    fold = {}
    for w in forms:
        if w not in live:
            bare = criteria.strip_stress(w)
            if bare != w and bare in live:
                fold[w] = bare
    d = {}
    for w, v in forms.items():
        t = fold.get(w, w)
        cur = d.setdefault(t, [set(), False])
        cur[0] |= set(v["pos"])
        cur[1] = cur[1] or bool(v["is_lemma"])
    dict_want = {w: (criteria.entry_type_for_word(w, p), 1 if l else 0, "/".join(sorted(p)))
                 for w, (p, l) in d.items()}
    ent_want = {ref: (fold.get(w, w), pos, en, sub, sq, c["aspect"], c["gender"], c["animacy"], c["declension"], src)
                for (w, pos, en, sub, sq, c, src, ref) in entries}
    return dict(dict=dict_want, entry=ent_want, n_fold=len(fold))


def check_skeleton(con, W):
    have_d = {w: (t, l, p) for w, t, l, p in con.execute("SELECT word, entry_type, is_lemma, pos FROM dict")}
    have_e = {r[0]: tuple(r[1:]) for r in con.execute(
        "SELECT e.src_ref, d.word, e.pos, e.etym_no, e.etym_sub, e.seq, e.aspect, e.gender, e.animacy, "
        "e.declension, e.src FROM entry e JOIN dict d ON d.id=e.word_id")}
    return _diff("K·dict", W["dict"], have_d) + _diff("K·entry", W["entry"], have_e)


def want_stress():
    from pipeline import stress_layer
    cand, _st = stress_layer.collect(verbose=False)
    con = _open()
    try:
        # R13 已落库（那 7 行 dict 早删了）⇒ 不再需要 remap；与收割器同一个 `build_rows`
        srows, _estr, _bst = stress_layer.build_rows(cand, con)
    finally:
        con.close()
    return {r[6]: (r[1], r[2], r[3], r[4], r[5]) for r in srows}


def check_stress(con, W):
    have = {r[0]: tuple(r[1:]) for r in con.execute(
        "SELECT src_ref, entry_id, stressed, variant_seq, is_primary, src FROM stress")}
    bad = con.execute("SELECT COUNT(*) FROM stress s JOIN entry e ON e.id=s.entry_id "
                      "WHERE s.word_id<>e.word_id").fetchone()[0]
    out = _diff("T", W, have)
    if bad:
        out.append(("T④", "stress.word_id 与它的 entry 不是同一个词形 %s 行" % F(bad)))
    return out


def want_inflection():
    from pipeline import inflection_layer as IL
    IL.collect(verbose=False)
    con = _open()
    ent = dict(con.execute("SELECT src_ref, id FROM entry"))
    con.close()
    out = {}
    import gzip
    with gzip.open(IL.SPOOL, "rt", encoding="utf-8") as f:
        for line in f:
            sref, bare, stressed, tg, tt, src, sr = line.rstrip("\n").split("\t")
            eid = ent.get(sref)
            if eid is None:
                continue
            out[sr] = hash((eid, bare, stressed or None, tg or None, tt or None, src))
    return out


def check_inflection(con, W):
    have = {}
    for sr, eid, f, s, tg, tt, src in con.execute(
            "SELECT src_ref, entry_id, form, stressed, tags, table_tag, src FROM inflection"):
        have[sr] = hash((eid, f, s, tg, tt, src))
    return _diff("I", W, have)


def want_pronunciation():
    from pipeline import pronunciation_layer as PL
    con = _open()
    rows, _st = PL.collect(con, verbose=False)
    con.close()
    return {r[9]: tuple(r[:9]) for r in rows}


def check_pronunciation(con, W):
    have = {r[0]: tuple(r[1:]) for r in con.execute(
        "SELECT src_ref, word_id, entry_id, ipa, dialect, notation, tags, hidden, hidden_why, src FROM pronunciation")}
    return _diff("Q", W, have)


def want_sense():
    from pipeline import sense_layer as SL
    con = _open()
    ev, senses, glosses, tags, _st = SL.collect(con, verbose=False)
    con.close()
    return dict(
        src={r[7]: tuple(r[:7]) for r in ev},
        sense={r[0]: tuple(r[1:]) for r in senses},
        gloss=collections.Counter((g[0], g[1], g[2], g[3]) for g in glosses),
        tag=collections.Counter(tuple(t) for t in tags))


def check_sense(con, W):
    out = []
    model_only = {s for (s,) in con.execute(
        "SELECT sense_id FROM sense_gloss GROUP BY sense_id HAVING SUM(src<>'%s')=0" % MODEL)}
    have_src, xl = {}, 0
    for r in con.execute("SELECT src_ref, word_id, entry_id, sense_id, lang, text, pointer_target, src "
                         "FROM sense_src"):
        row = tuple(r[1:])
        w = W["src"].get(r[0])
        # 破例（5b，用户拍板）：fr/vi/pl 证据挂上了一条只有模型中文的新义项 —— 第一类「库里多」，钉住
        if w and w[2] is None and row[2] is not None and row[3] in ("fr", "vi", "pl") and row[2] in model_only:
            row = row[:2] + (None,) + row[3:]
            xl += 1
        have_src[r[0]] = row
    out += _diff("E·sense_src", W["src"], have_src)
    have_s = {r[0]: tuple(r[1:]) for r in con.execute(
        "SELECT id, word_id, entry_id, rank, hidden, hidden_why FROM sense")}
    xl_ids = {i for i in have_s if i not in W["sense"]}
    third = xl_ids - model_only
    have_s = {k: v for k, v in have_s.items() if k not in xl_ids}
    out += _diff("E·sense", W["sense"], have_s)
    if third:
        out.append(("E·sense④", "库里多出 %s 条义项，**不是**破例那一类（只有模型中文）—— 第三类" % F(len(third))))
    if len(xl_ids) != xl:
        out.append(("E·sense⑤", "破例义项 %s 条 ≠ 挂上它的 fr/vi/pl 证据 %s 条" % (F(len(xl_ids)), F(xl))))
    have_g = collections.Counter(tuple(r) for r in con.execute(
        "SELECT sense_id, lang, text, src FROM sense_gloss WHERE src<>?", (MODEL,)))
    if have_g != W["gloss"]:
        a, b = W["gloss"] - have_g, have_g - W["gloss"]
        out.append(("E·gloss", "源头释义不一致：源头有库里没有 %s ／ 库里有源头没有 %s  %s" % (
            F(sum(a.values())), F(sum(b.values())), list(a)[:2] + list(b)[:2])))
    third_g = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE src NOT LIKE '%-edition%' AND src<>?",
                          (MODEL,)).fetchone()[0]
    if third_g:
        out.append(("E·gloss④", "释义的 src 既不是源头版也不是 %s：%s 条（第三类）" % (MODEL, F(third_g))))
    have_t = collections.Counter(tuple(r) for r in con.execute("SELECT sense_id, bucket, value, src FROM sense_tag"))
    if have_t != W["tag"]:
        a, b = W["tag"] - have_t, have_t - W["tag"]
        out.append(("E·tag", "标签不一致：源头有库里没有 %s ／ 库里有源头没有 %s" % (F(sum(a.values())), F(sum(b.values())))))
    return out, dict(xl=xl)


def want_example():
    from pipeline import example_layer as XL
    con = _open()
    rows, glosses, _st = XL.collect(con, verbose=False)
    con.close()
    return dict(row={r[9]: (r[0],) + tuple(r[1:9]) for r in rows},
                gloss={(g[0], g[1]): (g[2], g[3]) for g in glosses})


def check_example(con, W):
    have = {r[0]: tuple(r[1:]) for r in con.execute(
        "SELECT src_ref, id, word_id, entry_id, sense_id, text, text_pub, ref, hidden_why, src FROM example")}
    out = _diff("X", W["row"], have)
    have_g, model, third = {}, 0, 0
    for eid, lang, text, src, hid in con.execute(
            "SELECT g.example_id, g.lang, g.text, g.src, e.hidden FROM example_gloss g JOIN example e "
            "ON e.id=g.example_id"):
        if src == MODEL:
            model += 1
            if (eid, lang) in W["gloss"] or hid or lang != "zh":
                third += 1                         # 模型中文盖在源头中文上／挂在藏的例句上／不是中文
            continue
        have_g[(eid, lang)] = (text, src)
    out += _diff("X·gloss", W["gloss"], have_g)
    if third:
        out.append(("X·gloss④", "模型中文 %s 条里 %s 条不在它该在的地方（与源头译文撞键／挂在藏的例句上／不是 zh）"
                    % (F(model), F(third))))
    return out, dict(model=model)


def want_relation():
    from pipeline import relation_layer as RL
    con = _open()
    rows, _st = RL.collect(con, verbose=False)
    con.close()
    return {r[11]: hash(tuple(r[:11])) for r in rows}


def check_relation(con, W):
    have = {}
    for r in con.execute("SELECT src_ref, word_id, entry_id, sense_id, kind, subkind, rel_group, form_group, "
                         "target, target_id, hidden_why, src FROM sense_relation"):
        have[r[0]] = hash(tuple(r[1:]))
    return _diff("R", W, have)


def want_audio():
    from pipeline import audio_layer as AL
    con = _open()
    rows, _raw, _st, _same = AL.collect(con, verbose=False)
    con.close()
    return {(r[0], r[3]): (r[1], r[2], r[4], r[5]) for r in rows}


def check_audio(con, W):
    have = {(r[0], r[1]): tuple(r[2:]) for r in con.execute(
        "SELECT word_id, commons_key, entry_id, url, hidden_why, src FROM audio")}
    return _diff("A", W, have)


def want_etymology():
    from pipeline import etymology_layer as EL
    con = _open()
    rows, _st = EL.collect(con, verbose=False)
    con.close()
    return {r[10]: tuple(r[:10]) for r in rows}


def check_etymology(con, W):
    have = {r[0]: tuple(r[1:]) for r in con.execute(
        "SELECT src_ref, word_id, entry_id, etym_no, etym_sub, text, text_pub, src_field, etym_type, hidden_why, src "
        "FROM etymology")}
    return _diff("Y", W, have)


LAYERS = [("skeleton", want_skeleton, check_skeleton), ("stress", want_stress, check_stress),
          ("inflection", want_inflection, check_inflection),
          ("pronunciation", want_pronunciation, check_pronunciation), ("sense", want_sense, check_sense),
          ("example", want_example, check_example), ("relation", want_relation, check_relation),
          ("audio", want_audio, check_audio), ("etymology", want_etymology, check_etymology)]


def run(only=None, verbose=True):
    """→ {层: [(编号, 说明)]}。"""
    res = {}
    for name, wf, cf in LAYERS:
        if only and name not in only:
            continue
        if name not in _WANT:
            if verbose:
                print("   …%s：重放 dump" % name, flush=True)
            _WANT[name] = wf()
        con = _open()
        try:
            r = cf(con, _WANT[name])
        finally:
            con.close()
        extra = None
        if isinstance(r, tuple):
            r, extra = r
        res[name] = (r, extra)
    return res


def report(only=None):
    res = run(only)
    print("■ 外锚闸（ru 阶段 8）—— %d 层 vs dump，三向恒等" % len(res))
    red = 0
    for name, (bad, extra) in res.items():
        w = _WANT[name]
        n = len(w) if not isinstance(w, dict) or name not in ("skeleton", "sense", "example") else \
            sum(len(v) for v in w.values() if isinstance(v, (dict, collections.Counter)))
        print("   %s %-14s 源头 %s 键%s" % ("✅" if not bad else "🔴", name, F(n),
                                        ("（%s）" % extra) if extra else ""))
        for cid, why in bad:
            print("      🔴 %-12s %s" % (cid, why))
        red += len(bad)
    print("■ %s" % ("全绿 ✓（三个方向都是 0；已知的「库里多」两类已钉住、没有第三类）" if not red else "%d 条红" % red))
    return red


# ══════════════════════════════ 变异：每层一条，动库不动 dump ══════════════════════════════
MUTATIONS = [
    ("skeleton", "K·entry③", "改一条 entry 的词性",
     ["UPDATE entry SET pos='«变异»' WHERE id=(SELECT MIN(id) FROM entry)"]),
    ("stress", "T①", "删一行重音", ["DELETE FROM stress WHERE id=(SELECT MIN(id) FROM stress)"]),
    ("inflection", "I③", "改一行变位形", ["UPDATE inflection SET form=form||'«变异»' WHERE id=(SELECT MIN(id) FROM inflection)"]),
    ("pronunciation", "Q②", "插一行追不回源头的读音",
     ["INSERT INTO pronunciation(word_id,entry_id,ipa,dialect,notation,tags,hidden,hidden_why,src,src_ref) "
      "SELECT word_id,entry_id,ipa,dialect,notation,tags,hidden,hidden_why,src,src_ref||'«变异»' FROM pronunciation LIMIT 1"]),
    ("sense", "E·sense④", "插一条既不是源头也不是破例的义项（第三类）",
     ["INSERT INTO sense(id,word_id,entry_id,rank,hidden,hidden_why) SELECT -1,word_id,entry_id,0,0,NULL FROM sense LIMIT 1"]),
    ("sense", "E·gloss", "改一条源头释义的文本",
     ["UPDATE sense_gloss SET text=text||'«变异»' WHERE id=(SELECT MIN(id) FROM sense_gloss WHERE src<>'%s')" % MODEL]),
    ("example", "X③", "把一条例句的 hidden_why 静默清掉",
     ["UPDATE example SET hidden_why=NULL, hidden=0 WHERE id=(SELECT MIN(id) FROM example WHERE hidden=1)"]),
    ("example", "X·gloss④", "模型中文盖到一条有源头中文的例句上",
     ["UPDATE example_gloss SET src='%s' WHERE id=(SELECT MIN(id) FROM example_gloss WHERE lang='zh' AND src LIKE 'zh-%%')"
      % MODEL]),
    ("relation", "R①", "删一行关系", ["DELETE FROM sense_relation WHERE id=(SELECT MIN(id) FROM sense_relation)"]),
    ("audio", "A③", "把一条录音的 url 换掉", ["UPDATE audio SET url=url||'«变异»' WHERE id=(SELECT MIN(id) FROM audio)"]),
    ("etymology", "Y③", "改一段词源的出版正文",
     ["UPDATE etymology SET text_pub='«变异»' WHERE id=(SELECT MIN(id) FROM etymology)"]),
]
# 每条变异**允许**的连带（先跑看实际、逐条核过才写）
ALSO = {
    "X·gloss④": {"X·gloss②", "X·gloss①"},   # 那条源头中文从「源头侧」消失（①），模型侧多了一条撞键的（④）
    "E·sense④": {"E·sense⑤"},   # 多出来的那条也被算进「库里多的义项」⇒ 与挂上它的 fr/vi/pl 证据数对不上
}


def mutate():
    print("■ 外锚闸变异：先算一次源头侧（缓存），再逐条注入")
    if report():
        print("🔴 基线就不绿，先修基线")
        return 1
    real = paths.DB
    fails = []
    for layer, cid, why, sqls in MUTATIONS:
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / real.name
            shutil.copy2(real, cp)
            paths.DB = cp
            try:
                con = sqlite3.connect(cp)
                for s in sqls:
                    con.execute(s)
                con.commit()
                con.close()
                bad = run([layer], verbose=False)[layer][0]
                got = {c for c, _w in bad}
                also = ALSO.get(cid, set())
                undecl = sorted(got - {cid} - also)
                if cid in got and not undecl:
                    print("   ✅ %-12s %s" % (cid, why))
                elif cid in got:
                    print("   🔴 %-12s 逮到了，**但有没声明的连带红 %s** —— %s" % (cid, undecl, why))
                    fails.append(cid)
                else:
                    print("   🔴🔴 %-12s **没逮到**（红的是 %s）—— %s" % (cid, sorted(got), why))
                    fails.append(cid)
            finally:
                paths.DB = real
    if run(verbose=False) and any(v[0] for v in run(verbose=False).values()):
        print("🔴🔴 反控制失败：真库基线不绿了")
        return 1
    print("\n%s" % ("■ 变异验证全过 ✓，反控制：真库基线仍全绿" if not fails else "🔴 %d 条没过：%s" % (len(fails), fails)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", action="append")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return mutate()
    return 1 if report(a.layer) else 0


if __name__ == "__main__":
    raise SystemExit(main())
