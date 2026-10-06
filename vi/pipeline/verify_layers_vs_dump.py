#!/usr/bin/env python3
"""**外锚闸**：例句 / 关系 / 词源 / 录音 / 量词**五层** vs dump。vi，2026-10-02（阶段 8）。

`[[external-anchor-gates]]`：**锚外部 dump 的闸永不过期，锚自己上一版的必然过期。**
前八道闸锚的都是库自己（「这一列的值域是这几个」「这两张表对得上」）——
它们在「收割器整批漏抽」面前是绿的，因为库里那批行自己是自洽的。

═══ 🔴🔴 这道闸最容易建错的地方，先说在前面 ═══
ko 那道同名的闸**判据写错过两次、方向相反**：例句侧写太宽报 **3 万条假缺**、
读音侧写太细报 **7,163 条假缺** —— 两次的根因是同一个：
**闸自己把收割器的判据重写了一遍。**
⇒ 本文件**一个判据都不重写**，五层各 import 收割器本身：

    例句  `build_example_layer.collect()`      （含 `stage6_sources.example_hidden_why` / 落点三分）
    关系  `build_relation_layer.collect()`     （含 `relation_target` / `is_han_headword` / B17 的 SUBSUME）
    词源  `build_etymology_layer.collect()`    （含 `etym_skip_why` / `clean_etym_text`）
    录音  `build_audio_layer.collect()`        （含 `commons_key` / `classify` / `audio_hidden_why`）
    量词  `build_classifier_layer.collect()`   （含 `src_ref` 不比唯一键细那条）

🔴 为此 2026-10-02 把四个收割器里埋在 `main()` 的收割逻辑**纯机械地**抽成了
   `index()` / `collect()`（例句层本来就有）。动机不是整洁，是**让闸和收割器共用一个函数**；
   抽完逐层干跑比过，五层行数与库里**逐位相同**（145,085／36,089／3,110／4,285／78,235）。

═══ ⚠️ 它逮得到什么、逮不到什么 ═══
它是 **源头 ↔ 库** 的双向恒等式。
  ✅ 逮得到：写库丢了行／后续某一步静默改了行／库里出现追不回源头的行／
            源头换了一份 dump 而没人重跑／**配对错了**（见下）
  ❌ **逮不到：收割器的判据本身写错了** —— 判据错，两边一起错，恒等式照样成立。
     ko 的实证：外锚闸双向恒等全绿**而且它是对的**，可库里仍躺着 92 个韩语里
     不存在的词形 —— 那是另外两条独立判据互相当闸逮到的。**恒等式问不了「源头对不对」。**

🔴🔴 **三个方向，不是两个。** `[[primary-key-is-not-enough]]`：
   主键保证「认领得上」，不保证「配对对」——**计数型闸对错配结构性失明**。
   ⇒ 每层查：①源头有·库里没有 ②库里有·源头追不回 ③**键对上了而内容不一样**。
   第③条是真正值钱的那条：它逮「某一步 UPDATE 改了文本/隐藏位而没人知道」。

═══ ⭐ 为 6e（例句翻译）预留的那一刀 ═══
`example_gloss` 里将来会有 **76,264 条模型译文**，它们**在 dump 里根本不存在**。
判据不分开 ⇒ 6e 一落库这道闸当场红，**而那是假红**。
⇒ 译文侧的恒等式只管 `src` 是版本名的那批；模型译文按 `src LIKE 'model%'` 排除，
  并且**断言这两类之和就是全部**（第三类值跑出来就红）——
  `[[residual-bucket-is-not-evidence]]`：排除一类的时候必须钉住「没有第三类」。

用法（在仓库根）：
    python3 -u vi/pipeline/verify_layers_vs_dump.py
    python3 -u vi/pipeline/verify_layers_vs_dump.py --layer relation --show 20
    python3 -u vi/pipeline/verify_layers_vs_dump.py --mutate
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "fixes"))

import argparse                                                    # noqa: E402
import collections                                                 # noqa: E402
import sqlite3                                                     # noqa: E402

import paths                                                       # noqa: E402
import stage6_sources as S6                                       # noqa: E402
import build_example_layer as BEX                                  # noqa: E402
import build_relation_layer as BRE                                 # noqa: E402
import build_etymology_layer as BET                                # noqa: E402
import build_audio_layer as BAU                                    # noqa: E402
import build_classifier_layer as BCL                               # noqa: E402
# 🔴 W17 那 30 行的第二个锚（见 `layer_relation`）。判据 import 不重写。
import collect_w17_relations as W17                                # noqa: E402

F = lambda n: format(n, ",")                                       # noqa: E731
QUIET = False   # 变异验证期间把层内的报数行闭嘴（否则 10 条变异刷满屏）


def ro():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


# ── 收割结果缓存：**只为变异验证存在** ──────────────────────────────────────
# 正常跑每层只收割一次，缓存没有作用。变异验证要把同一层跑 N 遍（每遍注入一条），
# 而每遍重读 12 份 dump 要几分钟 ⇒ 缓存一次。
# 🔴 **它成立有一个前提，必须写出来**：变异只动该层**自己那张表**，
#    而收割只依赖 `dict` / `entry` / `sense_src`（索引表）⇒ 注入不会改变收割结果。
#    `mutate()` 里有一条断言钉住这件事（动了索引表就必须清缓存）。
_CACHE = {}
_INDEX_TABLES = ("dict", "entry", "sense_src")


def _h(key, fn):
    if key not in _CACHE:
        _CACHE[key] = fn()
    return _CACHE[key]


# ══════════════════════════════════════════════════════════════════════════
# ⚠️ **本文件有意没有 `BUDGET`**（ko 的义项那一支有）。这五层的恒等式是
#    「缺口必须是 0」，没有"允许缺多少"这回事。
#    那几桶「有意不收」（源词不在 dict / 第四语言译文 / 目标是汉字…）**只报大小、
#    不设上限** —— 锁成数就会在补收词之后逼我照着新数字调，而那是
#    `[[expectation-must-be-declared]]` 反对的「从现状推期望」。
#    它们摆在台面上的作用是：判据悄悄放宽的时候**有声音**。


def _diff(want, have, name, show):
    """三个方向。want/have: {src_ref: 内容元组} → [(编号, 说明)]。"""
    bad = []
    miss = sorted(set(want) - set(have))
    extra = sorted(set(have) - set(want))
    mismatch = [k for k in (set(want) & set(have)) if want[k] != have[k]]
    if miss:
        bad.append(("%s①" % name, "**源头有 %s 条，库里没有** —— 写库丢了行，或源头换了"
                                  "一份 dump 而没人重跑" % F(len(miss))))
        for k in miss[:show]:
            bad.append(("", "      缺 %s  %r" % (k, want[k])))
    if extra:
        bad.append(("%s②" % name, "**库里有 %s 条追不回源头** —— 别的写入方插的，"
                                  "或 `src_ref` 被改过" % F(len(extra))))
        for k in extra[:show]:
            bad.append(("", "      多 %s  %r" % (k, have[k])))
    if mismatch:
        bad.append(("%s③" % name, "🔴🔴 **%s 条键对上了而内容不一样** —— 某一步静默"
                                  "改过行（计数型闸对这一类结构性失明）" % F(len(mismatch))))
        for k in sorted(mismatch)[:show]:
            bad.append(("", "      源头 %r\n            库里 %r" % (want[k], have[k])))
    return bad


def _buckets(stat, keys=("有意不收", "有意不建", "不在 dict", "第四语言", "丢：", "隐藏：",
                         "去重", "不入库")):
    out = [(k, v) for k, v in stat.items() if any(x in k for x in keys)]
    return sorted(out, key=lambda kv: -kv[1])


# ══════════════════════════════════════════════════════════════════════════
def layer_example(show=0):
    """例句层：`collect()` 的产出 ≡ `example` ＋（源头侧的）`example_gloss`。"""
    con = ro()
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    s2id, groups = BEX.sense_index(con)
    rows, stat = _h("example", lambda: BEX.collect(wid, s2id, groups))
    # 内容元组：挂靠、正文、出处、隐藏原因、源 —— 全是「后续某一步可能改掉」的列
    # 🔴 `text_pub`（W16 的出版正文）**也进恒等式**。它是派生列，但正因为是派生列
    #    才最容易被某一步悄悄改掉而无人察觉 —— 而第③向（键对上而内容不一样）
    #    就是为这种事存在的。回归闸 P18 查同一件事，两道闸从不同方向各查一次
    #    （`[[correct-steps-can-compose-a-hole]]`）。
    want = {r[6]: (r[1], r[2], r[3], r[4], r[5], r[8]) for r in rows}
    have = {ref: (sid, t, rf, why, src, pub)
            for ref, sid, t, rf, why, src, pub in con.execute(
                "SELECT src_ref, sense_id, text, ref, hidden_why, src, text_pub FROM example")}
    bad = _diff(want, have, "X源", show)
    # ── 译文侧：**只管源头给的那批**，模型译文按 src 排除（6e 的那一刀）
    # 🔴 `want` 必须用收割器自己的 `gloss_rows()`，不许在这里重写条件 ——
    #    第一版写的是 `if r[7]`（漏了「可出版」那半句），报 **458 条假缺**。
    want_g = {r[6]: (r[7][0], r[7][1]) for r in BEX.gloss_rows(rows)}
    # 🔴 版本名**问 `S6.EDITIONS` 这张登记表**，不写形状判据 ——
    #    第一版写 `src.endswith("-edition")`，而 `zh-edition-trad`/`-simp`
    #    不以它结尾 ⇒ 690 条真译文被判成「第三类」。
    #    `[[criteria-from-meaning-not-form]]`：判据不许用形式代理。
    editions = {s for s, _l in S6.EDITIONS}
    have_g, model, other = {}, 0, collections.Counter()
    for ref, lang, t, src in con.execute(
            "SELECT e.src_ref, g.lang, g.text, g.src FROM example_gloss g "
            "JOIN example e ON e.id=g.example_id"):
        if src in editions:
            have_g[ref] = (lang, t)
        elif src.startswith("model"):
            model += 1
        else:
            other[src] += 1
    bad += _diff(want_g, have_g, "X译", show)
    # 🔴 排除一类就必须钉住「没有第三类」
    if other:
        bad.append(("X译④", "🔴 `example_gloss.src` 出现既不是版本名也不是 `model*` 的值："
                            "%s —— **排除法必须钉住没有第三类**" % dict(other)))
    if not QUIET:
        print("   译文：源头侧 %s 条（恒等）／模型译文 %s 条（**不进恒等式**，6e 的产物）"
              % (F(len(want_g)), F(model)))
    con.close()
    return bad, stat


def layer_relation(show=0):
    """关系层：`collect()` 的产出 ≡ `sense_relation`。含 B17 的隐藏位。"""
    con = ro()
    wid, nx, na, s2id, _tot = BRE.index(con)
    rows, stat, _pairs, unknown = _h("relation", lambda: BRE.collect(wid, nx, na, s2id))
    want = {r[6]: (r[1], r[2], r[3], r[4], r[5], r[7]) for r in rows}
    # 🔴🔴 **W17 那 30 行不是这个收割器的产物，所以要给它第二个锚，不是排除它。**
    #    源头把那批关系数据挤进了 `examples[].text`，**没有结构字段可读**
    #    ⇒ `build_relation_layer.collect()` 永远产不出它们
    #    ⇒ 2026-10-05 它们一落库，本闸当场报「库里有 30 条追不回源头」—— **而它是对的**。
    # ⚠️ 两条路：① 把 `src='w17-from-examples'` 从恒等式里排除 ② 给它一个锚。
    #    选 ② —— 排除就是造一个洞，而这个洞恰好开在「我刚手工插进去的 30 行」上
    #    （`[[gate-registers-status-quo-as-spec]]`：闸一旦如实登记现状就不再问它对不对）。
    #    这 30 行解析自 `example.text`，而 `example` 由本文件的 `layer_example()`
    #    锚到 dump ⇒ **传递地锚住了**，这里只要确认「库里的 ≡ 重算一遍的」。
    # ⚠️ `W17.parse()` 是为此从 `plan()` 里拆出来的：`plan()` 会把「关系层已经有的」
    #    跳掉，插库之后再调它返回 0 行 —— **那样的真值是空的，恒等式恒成立**。
    w17_want = {W17.src_ref(wid, kind, tgt): (None, kind, tgt, tid, W17.SRC, None)
                for wid, kind, tgt, tid, _n in W17.parse(con)[0]}
    have_all = {ref: (sid, k, t, tid, src, why) for ref, sid, k, t, tid, src, why
                in con.execute("SELECT src_ref, sense_id, kind, target, target_id, src, "
                               "hidden_why FROM sense_relation")}
    have = {r: v for r, v in have_all.items() if v[4] != W17.SRC}
    w17_have = {r: v for r, v in have_all.items() if v[4] == W17.SRC}
    bad = _diff(want, have, "R源", show)
    bad += _diff(w17_want, w17_have, "R17源", show)
    stat_extra_src = {v[4] for v in have_all.values()} - {s for s, _l in S6.EDITIONS} \
        - {W17.SRC}
    if stat_extra_src:
        bad.append(("R源⑤", "🔴🔴 `sense_relation.src` 里有既不是切片、也没在本闸登记的"
                            "写入方：%s —— 它们一行都没有锚" % sorted(stat_extra_src)))
    if unknown:
        bad.append(("R源④", "🔴🔴 源头长出 %d 种值域外的关系字段：%s —— "
                            "`stage6_sources.KINDS` 要先扩" % (len(unknown), dict(unknown))))
    con.close()
    return bad, stat


def layer_etymology(show=0):
    """词源层：`collect()` 的产出 ≡ `etymology`，外加 `entry.etym_type`。"""
    con = ro()
    wid, ent, en_ent, _tot = BET.index(con)
    rows, stat, skip, types, unknown = _h("etymology", lambda: BET.collect(wid, ent, en_ent))
    want = {r[6]: (r[1], r[2], r[3], r[4], r[5]) for r in rows}
    have = {ref: (eid, no, t, fld, src) for ref, eid, no, t, fld, src in con.execute(
        "SELECT src_ref, entry_id, etym_no, text, src_field, src FROM etymology")}
    bad = _diff(want, have, "Y源", show)
    # `etym_type` 是写进**别的表**的派生值 ⇒ 它也要锚
    have_t = dict(con.execute(
        "SELECT id, etym_type FROM entry WHERE etym_type IS NOT NULL"))
    bad += _diff({str(k): (v,) for k, v in types.items()},
                 {str(k): (v,) for k, v in have_t.items()}, "Y型", show)
    if unknown:
        bad.append(("Y源④", "🔴🔴 源头长出 %d 种判据表外的词源模板：%s"
                    % (len(unknown), dict(unknown.most_common(8)))))
    for (ed, why), n in skip.most_common(6):
        stat["跳过（%s）：%s" % (ed, why)] = n
    con.close()
    return bad, stat


def layer_audio(show=0):
    """录音层：`collect()` 的产出 ≡ `audio`。

    ⭐ **B12 另外单查一条**：归一去重前后的行数比。只看最终行数的话，
      判据从 `commons_key` 退回 `url` 时数字会**变大**而不是变小 —— 恒等式会红，
      但红在「库里缺 1,450 条」上，读起来像漏抽，而真相是重复。⇒ 单独把这个比印出来。
    """
    con = ro()
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    pairs = _h("audio-pairs", BAU.variant_pairs)
    rows, raw, stat, _dia, _byEd, _bad, unknown = _h("audio", lambda: BAU.collect(wid, pairs))
    want = {"aud:%d:%s" % (r[0], r[2]): (r[1], r[3], r[4], r[5]) for r in rows}
    have = {"aud:%d:%s" % (w, k): (u, d, src, why) for w, u, k, d, src, why
            in con.execute("SELECT word_id, url, commons_key, dialect, src, hidden_why "
                           "FROM audio")}
    bad = _diff(want, have, "A源", show)
    if unknown:
        bad.append(("A源④", "🔴🔴 `classify()` 认不出 %d 条的方言值" % len(unknown)))
    byurl = len({(r[0], r[1]) for r in raw})
    if not QUIET:
        print("   B12：原始 %s → 按 `UNIQUE(word_id,url)` 只能并到 %s → 按 Commons 键 **%s**"
              % (F(len(raw)), F(byurl), F(len(rows))))
    if byurl <= len(rows):
        bad.append(("A源⑤", "🔴 按 url 去重（%s）不再多于按 Commons 键去重（%s）—— "
                            "**B12 的那个洞消失了**，多半是 `original_name()` 失效了"
                    % (F(byurl), F(len(rows)))))
    con.close()
    return bad, stat


def layer_classifier(show=0):
    """量词层：`collect()` 的产出 ≡ `noun_classifier`。单源（en 版），恒等式最干净。"""
    con = ro()
    wid, nx, na, pos_of, _tot = BCL.index(con)
    rows, stat, _per, _nn = _h("classifier", lambda: BCL.collect(wid, nx, na, pos_of))
    want = {r[5]: (r[1], r[2], r[3], r[4]) for r in rows}
    have = {ref: (c, cid, note, src) for ref, c, cid, note, src in con.execute(
        "SELECT src_ref, classifier, classifier_id, note, src FROM noun_classifier")}
    bad = _diff(want, have, "C源", show)
    con.close()
    return bad, stat


LAYERS = [("example", layer_example), ("relation", layer_relation),
          ("etymology", layer_etymology), ("audio", layer_audio),
          ("classifier", layer_classifier)]


# ══════════════════════════════════════════════════════════════════════════
def check(only=None, show=0, quiet=False):
    red = []
    for name, fn in LAYERS:
        if only and name != only:
            continue
        if not quiet:
            print("\n── %s" % name)
        bad, stat = fn(show)
        if not quiet:
            for k, v in _buckets(stat)[:8]:
                print("   「有意不收」桶：%-44s %8s" % (k, F(v)))
            print("   %s" % ("✅ 三向恒等" if not bad else "🔴 %d 条" % len(bad)))
        red += bad
    return red


# ══════════════════════════════════════════════════════════════════════════
# 变异验证。🔴 **本套变异动的是真库**（与别的闸不同，它们大多只动文档）——
#    每条都是「注入 1 行 → 查该层 → 还原」，`finally` 里无条件还原。
#    ⚠️ 进程被 kill 在中间会留下 1 行脏数据；跑完末尾有一条**总量回核**钉住这件事。
def _inject(layer, cid, name, do, undo, also=()):
    """注入 → 只查该层 → 必须出现 `cid`，且**连带必须预先声明**。"""
    global QUIET
    con = sqlite3.connect(paths.DB)
    try:
        do(con)
        con.commit()
    finally:
        con.close()
    QUIET = True
    try:
        hit = {c for c, _ in check(only=layer, quiet=True) if c}
    finally:
        QUIET = False
        con = sqlite3.connect(paths.DB)
        undo(con)
        con.commit()
        con.close()
    return _report(cid, name, hit, also)


def _report(cid, name, hit, also=()):
    """🔴 **两种失败必须在字面上分得开**：`cid` 没命中 vs 命中了但有未声明的连带。

    2026-10-02 这里栽过一次：A源⑤ 的变异**命中了**，而真实连带是 A源③（我只声明了 ①②）
    ⇒ 这一行印的是「🔴 没逮到」，**指向了错的东西** —— 我差点回去改判据。
    `[[it-display-layer-stage8]]` 的同一课：**一个印错对象的红灯比没有红灯更费时间。**
    """
    extra = hit - {cid} - set(also)
    ok = cid in hit and not extra
    tail = ""
    if also and (hit & set(also)):
        tail = "   （连带 %s，已声明）" % "、".join(sorted(hit & set(also)))
    if extra:
        tail = "   🔴 **未声明的连带 %s**（变异逮到了，是声明不全）" % "、".join(sorted(extra))
    mark = "✅" if ok else ("🔴 连带未声明" if cid in hit else "🔴 没逮到")
    print("   %s %-7s %s%s" % (mark, cid, name, tail))
    return ok


def mutate():
    global QUIET
    base = check(quiet=True)
    if base:
        print("🔴 基线就不绿，变异验证没有意义：")
        for c, w in base:
            print("   %-6s %s" % (c, w))
        return False
    con = ro()
    n0 = {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
          for t in ("example", "example_gloss", "sense_relation", "etymology",
                    "audio", "noun_classifier", "entry")}
    # 🔴 **缓存前提的断言**：收割只读索引表，变异只动各层自己那张表 ⇒ 缓存可复用。
    #    这一条是为了「哪天有人加一条动 dict 的变异」时当场炸掉，而不是静默读到旧收割。
    assert set(_INDEX_TABLES) & set(n0) == {"entry"}, \
        "索引表清单变了 ⇒ 重新想清缓存还能不能用"
    ex = con.execute("SELECT id, src_ref, text, hidden_why FROM example "
                     "WHERE hidden_why IS NULL LIMIT 1").fetchone()
    exg = con.execute(
        "SELECT g.id, g.src, g.text FROM example_gloss g JOIN example e ON e.id=g.example_id "
        "WHERE g.src='zh-edition-trad' LIMIT 1").fetchone()
    rel = con.execute("SELECT id, hidden_why FROM sense_relation WHERE hidden=1 LIMIT 1").fetchone()
    ety = con.execute("SELECT id, etym_type FROM entry WHERE etym_type IS NOT NULL LIMIT 1").fetchone()
    aud = con.execute("SELECT id, dialect FROM audio LIMIT 1").fetchone()
    cls = con.execute("SELECT id, word_id, classifier, classifier_id, note, src, src_ref "
                      "FROM noun_classifier LIMIT 1").fetchone()
    exrow = con.execute("SELECT * FROM example WHERE id=?", (ex[0],)).fetchone()
    cols = [d[0] for d in con.execute("SELECT * FROM example LIMIT 1").description]
    con.close()
    ok = True
    print("═══ 变异验证（动真库，每条注入 1 行后立即还原）═══")

    # ① 源头有·库里没有：删掉一条例句
    ok &= _inject("example", "X源①", "删掉一条例句（＝写库丢了行）",
                  lambda c: c.execute("DELETE FROM example WHERE id=?", (ex[0],)),
                  lambda c: c.execute(
                      "INSERT INTO example (%s) VALUES (%s)"
                      % (",".join(cols), ",".join("?" * len(cols))), exrow),
                  also=("X译①",))      # 这条例句若带译文，译文侧也会缺
    # ② 库里有·源头追不回：插一条 src_ref 对不上的
    ok &= _inject("example", "X源②", "插一条 `src_ref` 追不回源头的例句（别的写入方）",
                  lambda c: c.execute(
                      "INSERT INTO example (word_id, text, src, src_ref, hidden) "
                      "SELECT word_id, '变异注入', src, 'ex:MUTANT', 0 FROM example WHERE id=?",
                      (ex[0],)),
                  lambda c: c.execute("DELETE FROM example WHERE src_ref='ex:MUTANT'"))
    # ③ **最值钱的那条**：键对上而内容被改
    ok &= _inject("example", "X源③", "🔴 改掉一条例句的正文（键不变 ⇒ 计数型闸看不见）",
                  lambda c: c.execute("UPDATE example SET text=text||' ←变异' WHERE id=?", (ex[0],)),
                  lambda c: c.execute("UPDATE example SET text=? WHERE id=?", (ex[2], ex[0])))
    ok &= _inject("example", "X源③", "🔴 把一条可出版例句悄悄标成隐藏（隐藏位被改）",
                  lambda c: c.execute(
                      "UPDATE example SET hidden=1, hidden_why='mutant' WHERE id=?", (ex[0],)),
                  lambda c: c.execute(
                      "UPDATE example SET hidden=0, hidden_why=NULL WHERE id=?", (ex[0],)))
    # ④ 6e 那一刀：把源头译文的 `src` 洗成 model* ⇒ 它从恒等式里消失
    ok &= _inject("example", "X译①",
                  "🔴 把一条**源头**译文的 `src` 洗成 `model-x`（6e 那一刀被滥用的样子）",
                  lambda c: c.execute("UPDATE example_gloss SET src='model-x' WHERE id=?", (exg[0],)),
                  lambda c: c.execute("UPDATE example_gloss SET src=? WHERE id=?", (exg[1], exg[0])))
    # ⑤ 排除法必须钉住「没有第三类」
    ok &= _inject("example", "X译④", "`example_gloss.src` 写一个既非版本名也非 `model*` 的值",
                  lambda c: c.execute("UPDATE example_gloss SET src='手工补的' WHERE id=?", (exg[0],)),
                  lambda c: c.execute("UPDATE example_gloss SET src=? WHERE id=?", (exg[1], exg[0])),
                  also=("X译①",))      # 它同时从 have_g 里消失 ⇒ ① 也会响
    # ⑥ 关系层：B17 的隐藏位被静默放出来
    ok &= _inject("relation", "R源③", "🔴 把一条 B17 隐藏的关系悄悄放回出版层",
                  lambda c: c.execute(
                      "UPDATE sense_relation SET hidden=0, hidden_why=NULL WHERE id=?", (rel[0],)),
                  lambda c: c.execute(
                      "UPDATE sense_relation SET hidden=1, hidden_why=? WHERE id=?", (rel[1], rel[0])))
    # ⑥b W17 那 30 行的第二个锚（2026-10-05）。**两条，一条验锚本身一条验登记表。**
    _w17 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True).execute(
        "SELECT id, target FROM sense_relation WHERE src=? ORDER BY id LIMIT 1",
        (W17.SRC,)).fetchone()
    ok &= _inject("relation", "R17源③",
                  "🔴 改掉一条 W17 关系的目标（它走的是第二个锚，不是收割器）",
                  lambda c: c.execute("UPDATE sense_relation SET target='mutant' WHERE id=?",
                                      (_w17[0],)),
                  lambda c: c.execute("UPDATE sense_relation SET target=? WHERE id=?",
                                      (_w17[1], _w17[0])))
    # 🔴🔴 **这一条验的是「排除法钉住了没有第三类」。** 把 `src` 洗成一个没登记的值
    #    之后：它从 W17 那一堆里消失（R17源①）、也进不了切片那一堆 ⇒ R源②，
    #    而 R源⑤ 是那个**点名报出来**的检查。三条一起响才说明排除法是封闭的。
    #    ⚠️ 不声明连带的话这条会报「连带未声明」——而那三条**本来就该一起响**。
    ok &= _inject("relation", "R源⑤",
                  "🔴🔴 把一条关系的 `src` 洗成没登记的写入方（排除法有没有钉住第三类）",
                  lambda c: c.execute("UPDATE sense_relation SET src='mutant-writer' "
                                      "WHERE id=?", (_w17[0],)),
                  lambda c: c.execute("UPDATE sense_relation SET src=? WHERE id=?",
                                      (W17.SRC, _w17[0])),
                  also=("R17源①", "R源②"))
    # ⑦ 词源层：锚的是**写进别的表**的派生值 `entry.etym_type`
    #    ⚠️ `entry` 是索引表，但 `etym_type` 这一列**不参与收割** ⇒ 缓存仍然有效。
    ok &= _inject("etymology", "Y型③", "🔴 改掉一条 `entry.etym_type`（派生值写在别的表上）",
                  lambda c: c.execute("UPDATE entry SET etym_type='mutant' WHERE id=?", (ety[0],)),
                  lambda c: c.execute("UPDATE entry SET etym_type=? WHERE id=?", (ety[1], ety[0])))
    # ⑧ 录音层
    ok &= _inject("audio", "A源③", "🔴 改掉一条录音的方言值",
                  lambda c: c.execute("UPDATE audio SET dialect='mutant' WHERE id=?", (aud[0],)),
                  lambda c: c.execute("UPDATE audio SET dialect=? WHERE id=?", (aud[1], aud[0])))
    # ⑨ 量词层
    ok &= _inject("classifier", "C源①", "删掉一条量词",
                  lambda c: c.execute("DELETE FROM noun_classifier WHERE id=?", (cls[0],)),
                  lambda c: c.execute(
                      "INSERT INTO noun_classifier (id, word_id, classifier, classifier_id, "
                      "note, src, src_ref) VALUES (?,?,?,?,?,?,?)", cls))

    # ⑩ B12 的洞消失（A源⑤）。**代码侧变异**：把缓存里的 rows 换成「每行一个唯一键」，
    #    使「按 url 并」不再多于「按 Commons 键并」。
    #    ⚠️ 这样 want 也跟着变 ⇒ A源①② 必然连带，已声明。
    saved = _CACHE.get("audio")
    if saved:
        rows, raw, st, dia, byEd, bd, unk = saved
        # 🔴 **第一版这条变异是空操作，而它"没逮到"才让我发现**：
        #    我给 `commons_key` 加了 `#i` 后缀 —— 键变了而**行数没变**，
        #    可 A源⑤ 的判据比的正是行数（`byurl <= len(rows)`）⇒ 什么都没触发。
        #    `[[expectation-must-be-declared]]` 那一族：**变异要动的是判据真正读的那个量。**
        #    ⇒ 改成真正模拟「`original_name()` 失效」：按 `(word_id, url)` 去重，
        #      落到 4,560 行 —— 那正是 B12 的洞被填平之后该有的样子。
        order = {src: i for i, (src, _l) in enumerate(S6.EDITIONS)}
        best = {}
        for r in raw:
            k = (r[0], r[1])
            if k not in best or order[r[4]] < order[best[k][4]]:
                best[k] = r
        _CACHE["audio"] = (sorted(best.values(), key=lambda r: (r[0], r[2])),
                           raw, st, dia, byEd, bd, unk)
        QUIET = True
        try:
            hit = {c for c, _ in check(only="audio", quiet=True) if c}
        finally:
            QUIET = False
            _CACHE["audio"] = saved
        # 连带是 **A源③ 不是 ①②**（实测）：commons_key 这一侧的键没变，
        # 变的是「同一个键活下来的是哪一个 url」⇒ 键对上而内容不一样。
        ok &= _report("A源⑤", "🔴 让 Commons 归一失效（B12 的洞消失）", hit,
                      also=("A源③", "A源①", "A源②"))

    # ⑪ **总量回核**：所有变异都还原干净了没有
    con = ro()
    n1 = {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in n0}
    con.close()
    drift = {t: (n0[t], n1[t]) for t in n0 if n0[t] != n1[t]}
    print("   %s 还原回核：七张表行数%s"
          % ("✅" if not drift else "🔴🔴", " 全部复原" if not drift else "**没复原** %s" % drift))
    ok &= not drift
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", choices=[n for n, _ in LAYERS])
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    if a.mutate:
        raise SystemExit(0 if mutate() else 1)
    print("■ 外锚闸（vi）：五层 vs dump，三向恒等（源头缺/库里多/内容不一样）")
    red = check(a.layer, a.show)
    print("\n═══ 小结 ═══")
    for cid, why in red:
        print("   %-6s %s" % (cid, why))
    if not red:
        print("   ✅ 五层三向全绿")
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
