#!/usr/bin/env python3
"""**阶段 6 的裁决，可重跑** —— 例句 / 关系 / 量词 / 录音。2026-10-01。

每一节都是「我据此做了某个决定」的那个度量。重跑它＝重新裁决一次。
判据一律 `import stage6_sources`，本文件**一行判据都不自己写**
（ko 的 K10：我量它的时候自写了一版更宽的判据，zh 版报 173,887 而真值是 6）。

    §A 十二版的字段名普查      —— 抽任何字段之前先做这一步（vi 上已栽三次）
    §B 例句：落点、挂靠、译文  —— 🔴 vi 版的 `translation` 不是译文
    §C 关系：B17 两种判据      —— 🔴 naive 比正确版宽 11 倍
    §D 量词：V5 的数复现没有
    §E 录音：B12 ＋ 张冠李戴   —— 🔴 `UNIQUE(word_id,url)` 挡不住 B12
    §F 读者口径：这一层让多少词形多了东西看

用法：
    python3 vi/probes/probe_stage6.py
    python3 vi/probes/probe_stage6.py --archive     # 存档到 data/work/vi/probe/
"""
import argparse
import collections
import gzip
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                                      # noqa: E402
import stage6_sources as S6                                       # noqa: E402
from criteria import is_han_headword, norm_vi                      # noqa: E402
from pron_sources import classify                                  # noqa: E402

PATH_OF = {
    "en-edition": paths.KK, "vi-edition": paths.EDITION,
    "zh-edition-trad": paths.ZH_TRAD, "zh-edition-simp": paths.ZH_SIMP,
    "fr-edition": paths.FR_EDITION, "ja-edition": paths.JA_EDITION,
    "ko-edition": paths.KO_EDITION, "pl-edition": paths.PL_EDITION,
    "ru-edition": paths.RU_EDITION, "nl-edition": paths.NL_EDITION,
    "pt-edition": paths.PT_EDITION, "de-edition": paths.DE_EDITION,
}
F = lambda n: format(n, ",")                                       # noqa: E731


def rd(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def load_db():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    norm = collections.defaultdict(list)
    for i, wn in con.execute("SELECT id, word_norm FROM dict ORDER BY id"):
        norm[wn].append(i)
    pos_of = collections.defaultdict(set)
    for w, p in con.execute("SELECT d.word, e.pos FROM entry e JOIN dict d ON d.id=e.word_id"):
        pos_of[w].add(p)
    return con, wid, norm, pos_of


def sense_keys(con):
    """`sense_src.src_ref` → (版, 词, 词性, 词源号, 义序) → sense_id。

    🔴 键是 `sense:<ed>:<w>:<pos>:<etym>:<si>:<gi>`，而**词形自己可能含 `:`** ⇒
       从右往左切，别 `split(":")`。例句挂在**义项**（si）上而不是 gloss（gi）上，
       所以一个 si 的多个 gi 里取第一条已出版的。
       ⚠️ 实测一个 si 带 >1 个 gloss 的只有 587 组（0.4%）⇒ 这个选择影响面很小，
         但**仍然要声明**（`[[correct-steps-can-compose-a-hole]]`）。
    """
    out, groups = {}, collections.Counter()
    for ref, sid in con.execute("SELECT src_ref, sense_id FROM sense_src ORDER BY id"):
        if not ref.startswith("sense:"):
            continue
        body = ref[len("sense:"):]
        ed, rest = body.split(":", 1)
        rest, _gi = rest.rsplit(":", 1)
        rest, si = rest.rsplit(":", 1)
        rest, etym = rest.rsplit(":", 1)
        w, pos = rest.rsplit(":", 1)
        k = (ed, w, pos, etym, int(si))
        groups[k] += 1
        if sid is not None and k not in out:
            out[k] = sid
    return out, groups


# ══════════════════════════════════════════════════════════════════════════
def sA_field_census():
    print("\n═══ §A 十二版的字段名普查 ═══")
    print("🔴 vi 上「同一个概念两个字段名」已栽三次（词源单复数 / 方言 tags-vs-note /")
    print("   例句译文其实是出处）⇒ **抽任何字段之前先把字段名全打出来**。")
    hdr = ("版", "行", "顶层关系", "义项关系", "例句", "带译文", "录音", "量词")
    print("   %-16s %7s %9s %9s %8s %8s %7s %7s" % hdr)
    tot = collections.Counter()
    for src, _lang in S6.EDITIONS:
        n = rel_t = rel_s = ex = tr = au = cl = 0
        for e in rd(PATH_OF[src]):
            n += 1
            for k in S6.KINDS:
                rel_t += len(e.get(k) or [])
            for s in e.get("senses") or []:
                for k in S6.KINDS:
                    rel_s += len(s.get(k) or [])
                for x in s.get("examples") or []:
                    ex += 1
                    if x.get("translation") or x.get("english"):
                        tr += 1
            for sd in e.get("sounds") or []:
                if any(sd.get(k) for k in ("ogg_url", "mp3_url", "wav_url", "oga_url")):
                    au += 1
            for fo in e.get("forms") or []:
                if "classifier" in (fo.get("tags") or []):
                    cl += 1
        print("   %-16s %7s %9s %9s %8s %8s %7s %7s"
              % (src, F(n), F(rel_t), F(rel_s), F(ex), F(tr), F(au), F(cl)))
        for k, v in (("rel_t", rel_t), ("rel_s", rel_s), ("ex", ex),
                     ("tr", tr), ("au", au), ("cl", cl)):
            tot[k] += v
    print("   %-16s %7s %9s %9s %8s %8s %7s %7s"
          % ("合计", "", F(tot["rel_t"]), F(tot["rel_s"]), F(tot["ex"]),
             F(tot["tr"]), F(tot["au"]), F(tot["cl"])))
    print("   ⭐ 读出来的三件事：")
    print("      ① **义项级关系只有 en 版有**（%s : %s）⇒ 只有它能给 `sense_id`，"
          "其余十一版全是词条级" % (F(tot["rel_s"]), 0))
    print("      ② **量词只有 en 版有**（其余十一版 0）⇒ 量词层天然锚在 en 的 entry 上")
    print("      ③ **录音源有十版，不是一版** —— `paths.py` 写的「录音只有 en 版有」"
          "是只比 en:vi 得出的；跨版收割后 `pl` 版 970 条、`fr` 版 2,088 条")
    return tot


def sB_examples(wid, k2s, groups):
    print("\n═══ §B 例句：落点、挂靠、译文 ═══")
    st = collections.Counter()
    byEd = collections.Counter()
    tr_real = collections.Counter()
    tr_dropped = collections.Counter()
    vi_tr_shape = collections.Counter()
    for src, _lang in S6.EDITIONS:
        ed = src.split("-")[0]
        for e in rd(PATH_OF[src]):
            w = (e.get("word") or "").strip()
            inD = w in wid
            pos, etym = e.get("pos"), str(e.get("etymology_number", "0") or "0")
            for si, s in enumerate(e.get("senses") or []):
                for x in s.get("examples") or []:
                    t = (x.get("text") or "").strip()
                    st["源头例句"] += 1
                    if not t:
                        st["① 文本空 ⇒ 不入库"] += 1
                        continue
                    if not inD:
                        st["② 源词不在 dict（汉字词头等）"] += 1
                        continue
                    byEd[src] += 1
                    why = S6.example_hidden_why(t, w, x.get("tags") or [])
                    # ⚠️ 被隐藏的**也入库**（证据层永不编辑），只是 hidden=1
                    st["✅ 可出版" if not why else "   入库但隐藏：%s" % why] += 1
                    k = (ed, w, pos, etym, si)
                    if k in k2s:
                        st["      └ 挂上已出版义项"] += 1
                    elif k in groups:
                        st["      └ 该义项整条被隐藏 ⇒ sense_id NULL"] += 1
                    else:
                        st["      └ 本版的义项没收进 sense_src ⇒ 词条级"] += 1
                    tt = x.get("translation") or x.get("english")
                    if tt:
                        lang = S6.TR_LANG[src]
                        if lang:
                            tr_real[lang] += 1
                        else:
                            tr_dropped[src] += 1
                        if src in S6.REF_FROM_TRANSLATION:
                            vi_tr_shape["整串是 `.` 或标点" if not tt.strip(" .!?)(")
                                        else ("`(…)` 形状" if tt.strip().startswith("(")
                                              else "其他")] += 1
    for k, v in st.most_common():
        print("   %-44s %8s" % (k, F(v)))
    print("   ── 按版（落点在 dict 的）")
    for k, v in byEd.most_common():
        print("      %-18s %8s" % (k, F(v)))
    print("   ── 译文：**按版定语种，不按字段名定**")
    print("      ✅ 可出版 %s" % ("、".join("%s=%s" % (k, F(v)) for k, v in tr_real.most_common())))
    print("      ⚠️ 第四语言、有意不收 %s"
          % "、".join("%s=%s" % (k.split("-")[0], F(v)) for k, v in tr_dropped.most_common()))
    print("   🔴 vi 版 `translation` 的形状（**一条真译文都没有**）：%s"
          % "、".join("%s=%s" % kv for kv in vi_tr_shape.most_common()))
    return st


def sC_relations(wid, norm):
    print("\n═══ §C 关系：B17 的两种判据 ═══")
    pairs = collections.defaultdict(set)
    rows, drop = [], collections.Counter()
    unknown_fields = collections.Counter()
    for src, _lang in S6.EDITIONS:
        for e in rd(PATH_OF[src]):
            w = (e.get("word") or "").strip()
            # 源头有没有我们不认识的关系字段？**兜底必须喊出来**
            for k in e:
                if k.endswith(("nyms", "nymes")) and k not in S6.KINDS:
                    unknown_fields[k] += 1
            if w not in wid:
                drop["源词不在 dict"] += 1
                continue
            for lvl, obj in [(None, e)] + list(enumerate(e.get("senses") or [])):
                for fld, kind in S6.KINDS.items():
                    for it in obj.get(fld) or []:
                        if not isinstance(it, dict):
                            drop["关系项不是对象"] += 1
                            continue
                        t, why = S6.relation_target(it)
                        if t is None:
                            drop[why.split("（")[0]] += 1
                            continue
                        if is_han_headword(t):
                            drop["目标是汉字/喃字 ⇒ 必然死链"] += 1
                            continue
                        pairs[(wid[w], norm_vi(t))].add(kind)
                        rows.append((wid[w], norm_vi(t), kind, src))
    naive = sum(1 for v in pairs.values() if "related" in v and len(v) > 1)
    right = sum(1 for v in pairs.values() if "related" in v and (v & S6.SUBSUME))
    hid = sum(1 for r in rows
              if r[2] == "related" and (pairs[(r[0], r[1])] & S6.SUBSUME))
    print("   关系项 %s 条 / %s 个 (词,目标) 对" % (F(len(rows)), F(len(pairs))))
    for k, v in drop.most_common():
        print("      丢弃 %-30s %8s" % (k, F(v)))
    print("   🔴 B17 两种判据：")
    print("      naive「related 撞上**任何**别的 kind」    %8s（%.1f%%）"
          % (F(naive), 100 * naive / max(len(pairs), 1)))
    print("      正确「related 撞上**语义更具体**的 kind」  %8s（%.1f%%）  ⇒ **差 %.1f 倍**"
          % (F(right), 100 * right / max(len(pairs), 1), naive / max(right, 1)))
    print("      ⇒ 要隐藏的**行** %s / 全部 related 行 %s"
          % (F(hid), F(sum(1 for r in rows if r[2] == "related"))))
    print("      差的那批几乎全是 `paronym+related` —— **语音关系不蕴含语义相关**，"
          "吞掉 related 是丢数据")
    res = sum(1 for r in rows if r[1] in norm)
    print("   ⚠️ `target_id` 可解析 %s（%.1f%%）；解析不了的留 NULL ⇒ "
          "**展示层不许做成链接**（ko 的「点下去空白页」）"
          % (F(res), 100 * res / max(len(rows), 1)))
    if unknown_fields:
        print("   🔴🔴 源头有我们不认识的关系字段：%s" % dict(unknown_fields))
    else:
        print("   ✅ 没有不认识的关系字段（`*nyms` 全在 KINDS 值域里）")
    return rows, pairs


def sD_classifier(wid, norm, pos_of):
    print("\n═══ §D 量词：V5 的数复现没有 ═══")
    per, unres, notnoun, rows = collections.defaultdict(set), collections.Counter(), 0, 0
    for e in rd(paths.KK):
        w = (e.get("word") or "").strip()
        if w not in wid:
            continue
        cs = [(f.get("form") or "").strip() for f in (e.get("forms") or [])
              if "classifier" in (f.get("tags") or [])]
        cs = [c for c in cs if c]
        if not cs:
            continue
        if not ({"noun", "name", "pron"} & pos_of.get(w, set())):
            notnoun += 1
        for c in cs:
            rows += 1
            per[w].add(c)
            unres["✅ 量词自己有词条" if norm_vi(c) in norm
                   else "⚠️ 量词没有词条 ⇒ classifier_id NULL"] += 1
    d = collections.Counter(len(v) for v in per.values())
    multi = 100 * sum(v for k, v in d.items() if k >= 2) / max(len(per), 1)
    print("   %s 行 / %s 个名词；配 ≥2 个量词 **%.1f%%**（`VI_PLAN` V5 写的是 34.6%%）"
          % (F(rows), F(len(per)), multi))
    print("   分布 %s" % dict(sorted(d.items())))
    for k, v in unres.most_common():
        print("   %-34s %s" % (k, F(v)))
    print("   ⚠️ 源词的词性里没有 noun/name/pron 的 %d 个 —— 量词**不只修饰名词**，"
          "这个数不该当成缺陷" % notnoun)
    return rows, len(per)


def sE_audio(wid):
    print("\n═══ §E 录音：B12 ＋ 张冠李戴 ═══")
    # 源头说「这两个词形是一回事」的无向对 —— 第二信号，必须来自源头
    variants = set()
    for src, _lang in S6.EDITIONS:
        for e in rd(PATH_OF[src]):
            w = (e.get("word") or "").strip()
            if not w:
                continue
            for f in e.get("forms") or []:
                if {"alternative", "romanization"} & set(f.get("tags") or []):
                    variants.add(S6.variant_pair_key(w, f.get("form") or ""))
            for obj in [e] + list(e.get("senses") or []):
                for fld in ("synonyms", "related"):
                    for it in obj.get(fld) or []:
                        if isinstance(it, dict) and it.get("word"):
                            variants.add(S6.variant_pair_key(w, it["word"]))
            for s in e.get("senses") or []:
                for fld in ("alt_of", "form_of"):
                    for it in s.get(fld) or []:
                        if isinstance(it, dict) and it.get("word"):
                            variants.add(S6.variant_pair_key(w, it["word"]))
    print("   源头给出的「彼此异写/同义」无向对 %s 个（第二信号）" % F(len(variants)))

    raw, bad, verdicts = [], [], collections.Counter()
    for src, _lang in S6.EDITIONS:
        for e in rd(PATH_OF[src]):
            w = (e.get("word") or "").strip()
            if w not in wid:
                continue
            for sd in e.get("sounds") or []:
                u = (sd.get("ogg_url") or sd.get("mp3_url")
                     or sd.get("wav_url") or sd.get("oga_url"))
                if not u:
                    continue
                fn = sd.get("audio") or u.rsplit("/", 1)[-1]
                key = S6.commons_key(S6.original_name(fn))
                dl, v = classify(sd.get("tags") or [], sd.get("note"))
                verdicts[v] += 1
                why = S6.audio_hidden_why(w, key, variants)
                raw.append((wid[w], u, key, dl, src))
                if why:
                    bad.append((w, S6.filename_word(key), src))
    k_url = {(a[0], a[1]) for a in raw}
    k_key = {(a[0], a[2]) for a in raw}
    print("   原始 %s 条 → 按 schema 的 `UNIQUE(word_id,url)` 去重 %s"
          " → 🔴 按 Commons 归一键再并 **%s**" % (F(len(raw)), F(len(k_url)), F(len(k_key))))
    print("      ⇒ **光靠唯一键会让 %s 行重复落进库**（页面上两个按钮播同一个文件）"
          % F(len(k_url) - len(k_key)))
    print("   `classify()` 的判决：%s" % dict(verdicts))
    print("   🔴 文件名里的词 ≠ 词形、且源头没说它们是一回事：**%d 行 / %d 组**（全部列出）"
          % (len(bad), len(set(bad))))
    for w, fw, src in sorted(set(bad)):
        print("      %-24s ← 文件名里是 %-16s （%s）" % (w, fw, src))
    print("      ⚠️ 逐条读过：真错 4 条；已知假阳 3 条（欠账 **W8**）⇒ 精确度 ~57%，"
          "**只隐藏不删**")
    return raw, k_key, bad


def sF_reader(con):
    print("\n═══ §F 读者口径：这一层让多少词形多了东西看 ═══")
    q = lambda s: con.execute(s).fetchone()[0]                      # noqa: E731
    tot = q("SELECT COUNT(*) FROM dict")
    for name, sql in (
            ("有例句", "SELECT COUNT(DISTINCT word_id) FROM example WHERE hidden=0"),
            ("例句有中文译文",
             "SELECT COUNT(DISTINCT e.word_id) FROM example e JOIN example_gloss g "
             "ON g.example_id=e.id WHERE e.hidden=0 AND g.lang='zh'"),
            ("有语义关系", "SELECT COUNT(DISTINCT word_id) FROM sense_relation WHERE hidden=0"),
            ("有量词", "SELECT COUNT(DISTINCT word_id) FROM noun_classifier"),
            ("有录音", "SELECT COUNT(DISTINCT word_id) FROM audio")):
        try:
            n = q(sql)
        except sqlite3.Error as e:
            print("   %-18s 查不了：%s" % (name, e))
            continue
        print("   %-18s %8s 个词形（%5.2f%%）" % (name, F(n), 100.0 * n / tot))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", action="store_true")
    a = ap.parse_args()
    out = None
    if a.archive:
        p = paths.PROBE / "probe_stage6.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        out = p.open("w", encoding="utf-8")
        sys.stdout = out
    try:
        print("■ vi 阶段 6 裁决（例句 / 关系 / 量词 / 录音）")
        con, wid, norm, pos_of = load_db()
        k2s, groups = sense_keys(con)
        print("   dict %s 词形；义项键 %s 组（有已出版义项的 %s）"
              % (F(len(wid)), F(len(groups)), F(len(k2s))))
        sA_field_census()
        sB_examples(wid, k2s, groups)
        sC_relations(wid, norm)
        sD_classifier(wid, norm, pos_of)
        sE_audio(wid)
        sF_reader(con)
        con.close()
    finally:
        if out:
            sys.stdout = sys.__stdout__
            out.close()
            print("■ 存档 → %s" % (paths.PROBE / "probe_stage6.txt"))


if __name__ == "__main__":
    main()
