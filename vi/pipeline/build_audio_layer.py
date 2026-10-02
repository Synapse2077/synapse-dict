#!/usr/bin/env python3
"""vi 阶段 6d：**录音层**（`audio`）。2026-10-01。

判据全部 `import stage6_sources` ＋ `scripts/commons_filename`（八门共用的唯一一份）。
裁决见 `vi/probes/probe_stage6.py` §E（可重跑）。

═══ 🔴🔴 第一件事：schema 的 `UNIQUE(word_id, url)` **挡不住 B12** ═══
    原始                                      8,148 行
    按 `UNIQUE(word_id, url)` 去重            4,560 行
    按 Commons 归一键再并                     **3,110 行**
⇒ **光靠唯一键会让 1,450 行重复落进库**，页面上排出两个按钮播同一个文件。
成因：各维基版内嵌的是**转码后**的 mp3 名，Commons 原始名是 `.wav`/`.oga`；
判据不是我们定的，是 MediaWiki 自己的标题归一规则（下划线≡空格、首字母大小写不敏感）。
⇒ 入库前按 `commons_key()` 并，`commons_key` 列从第一天就存（`dbtool.TRACK` 里盯着）。

═══ 🔴 第二件事：录音源是**十版**，不是一版 ═══
`paths.py` 写着「录音只有 en 版有（1,743 : 10）」—— 那是只比 en 与 vi 得出的。
跨版收割后：en 4,122 ／ fr 2,088 ／ **pl 970** ／ zh 457 ／ ja 215 ／ nl 188 ／
vi 186 ／ ko 33 ／ de 12 ／ ru 1。
⭐ `pl` 版整份只有 2,733 行而给了 970 条录音（它自己的 35.6%）——
   `[[cross-edition-harvest]]`「别凭大小判断价值」又一例。

═══ 🔴🔴 第三件事：方言值域在这一层**长出了三个新值**，而音标层四道闸全绿 ═══
这几条 `sounds` 项**只有 `audio` 没有 `ipa`** ⇒ 音标层压根没把它们喂给 `classify()`。
`South Central Coast`（10 条）／`North`（1）／`singular`（1，ru 版把语法数写进了 tags）。
⭐ 逮到它的机制是 `classify()` 的 `unknown-value` **要求调用方报红** ——
   静默归 unknown 的话这三个值会悄悄消失而所有闸照样绿。
   `[[correct-steps-can-compose-a-hole]]`：每步都对、跨步假设失效＝谁都没负责的洞。

═══ ⚠️ 第四件事：张冠李戴只隐藏不删，精确度 ~57%（欠账 W8）═══
见 `stage6_sources` 文件头第三条。**第一版拿 IPA 交集当第二信号，错得很整齐**
（把 `chìa khoá/khóa` 这类正字法异写判成张冠李戴，根因是三版转写约定不同）。
换成「源头有没有说这两个词形是一回事」后：7 行命中，真错 4、假阳 3。

用法：
    python3 vi/pipeline/build_audio_layer.py [--apply]
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
sys.path.insert(0, str(HERE))

import dbtool                                                     # noqa: E402
import paths                                                      # noqa: E402
import stage6_sources as S6                                       # noqa: E402
from pron_sources import classify                                  # noqa: E402

PATH_OF = {
    "en-edition": paths.KK, "vi-edition": paths.EDITION,
    "zh-edition-trad": paths.ZH_TRAD, "zh-edition-simp": paths.ZH_SIMP,
    "fr-edition": paths.FR_EDITION, "ja-edition": paths.JA_EDITION,
    "ko-edition": paths.KO_EDITION, "pl-edition": paths.PL_EDITION,
    "ru-edition": paths.RU_EDITION, "nl-edition": paths.NL_EDITION,
    "pt-edition": paths.PT_EDITION, "de-edition": paths.DE_EDITION,
}
F = lambda n: format(n, ",")                                      # noqa: E731
# 优先级：`.ogg` 最通行，其次 mp3（转码）、wav（原始，大）
URL_PREF = ("ogg_url", "mp3_url", "wav_url", "oga_url")


def rd(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def variant_pairs():
    """源头说「这两个词形是一回事」的无向对 —— 张冠李戴判据的**第二信号**。

    🔴 必须来自源头。第一版自己拿 IPA 集合交集算，而阶段 3b 早已量过
       「三版转写约定不同」⇒ 那个交集量的是哪一版给的音标，不是读音是否相同。
    """
    out = set()
    for src, _lang in S6.EDITIONS:
        for e in rd(PATH_OF[src]):
            w = (e.get("word") or "").strip()
            if not w:
                continue
            for f in e.get("forms") or []:
                if {"alternative", "romanization"} & set(f.get("tags") or []):
                    out.add(S6.variant_pair_key(w, f.get("form") or ""))
            for obj in [e] + list(e.get("senses") or []):
                for fld in ("synonyms", "related"):
                    for it in obj.get(fld) or []:
                        if isinstance(it, dict) and it.get("word"):
                            out.add(S6.variant_pair_key(w, it["word"]))
            for s in e.get("senses") or []:
                for fld in ("alt_of", "form_of"):
                    for it in s.get(fld) or []:
                        if isinstance(it, dict) and it.get("word"):
                            out.add(S6.variant_pair_key(w, it["word"]))
    return out


def collect(wid, pairs):
    """收割 ⇒ (最终行, 原始行, 统计, 方言计数, 按版计数, 疑似张冠李戴, 认不出的方言值)。

    🔴 **抽出来是为了外锚闸能 import 同一个函数**，不是为了整洁 —— 闸若自己重写
       这段判据，它报的就是它自己的 bug（ko 那道外锚闸报过 3 万条假缺）。纯搬移。
    ⭐ 返回 `raw`（归一去重**之前**的行）是有用的：B12 的恒等式要拿它当分母 ——
       只看最终行数，判据从 `commons_key` 退回 `url` 时数字会**变大**而不是变小。
    ⚠️「`classify()` 认不出方言值」那条守卫有意留在 `main()`（它是 `raise SystemExit`）。
    """
    raw, stat, dia = [], collections.Counter(), collections.Counter()
    byEd, bad = collections.Counter(), []
    unknown_dialect = []
    for src, _lang in S6.EDITIONS:
        for e in rd(PATH_OF[src]):
            w = (e.get("word") or "").strip()
            for sd in e.get("sounds") or []:
                url = next((sd[k] for k in URL_PREF if sd.get(k)), None)
                if not url:
                    continue
                if w not in wid:
                    stat["源词不在 dict（汉字词头等，有意不收）"] += 1
                    continue
                stat["源头录音"] += 1
                byEd[src] += 1
                fn = sd.get("audio") or url.rsplit("/", 1)[-1]
                key = S6.commons_key(S6.original_name(fn))
                dl, verdict = classify(sd.get("tags") or [], sd.get("note"))
                if verdict == "drop-not-vietnamese":
                    stat["丢：不是越南语的读音"] += 1
                    continue
                if verdict == "unknown-value":
                    # 🔴 **不许静默归 unknown** —— 源头加了新值要当场知道
                    unknown_dialect.append((w, sd.get("tags"), sd.get("note"), src))
                    continue
                dia[dl] += 1
                why = S6.audio_hidden_why(w, key, pairs)
                if why:
                    bad.append((w, S6.filename_word(key), src))
                raw.append((wid[w], url, key, dl, src, why))


    # ── B12：按 Commons 归一键并。**同一个文件只留一行**
    #    留哪一行：`EDITIONS` 顺序在前的那版（en 优先），同版内 URL_PREF 顺序在前的
    order = {src: i for i, (src, _l) in enumerate(S6.EDITIONS)}
    best = {}
    for r in raw:
        k = (r[0], r[2])
        if k not in best or order[r[4]] < order[best[k][4]]:
            best[k] = r
    rows = sorted(best.values(), key=lambda r: (r[0], r[2]))
    return rows, raw, stat, dia, byEd, bad, unknown_dialect


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    tot = len(wid)
    con.close()

    pairs = variant_pairs()
    print("■ dict %s 词形；源头给出的「彼此异写/同义」无向对 %s（第二信号）"
          % (F(tot), F(len(pairs))))

    rows, raw, stat, dia, byEd, bad, unknown_dialect = collect(wid, pairs)
    if unknown_dialect:
        print("\n🔴🔴 `classify()` 认不出 %d 条的方言值 —— **先把它们加进 "
              "`pron_sources`（方言点 / 非越南语 / 压根不是方言，三类之一）再建库**："
              % len(unknown_dialect))
        for r in unknown_dialect[:12]:
            print("     %s" % (r,))
        raise SystemExit(1)
    pub = [r for r in rows if r[5] is None]

    print("\n■ 录音 %s 行（可出版 %s ／ 隐藏 %s）" % (F(len(rows)), F(len(pub)),
                                              F(len(rows) - len(pub))))
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print("   %-44s %8s" % (k, F(v)))
    # ⚠️ 别用 `src.split("-")[0]` 当显示名 —— 两片中文版会并成两个同名的 `zh`
    print("   ── 按版：%s" % "、".join("%s=%s" % (k, F(v)) for k, v in byEd.most_common()))
    print("   ── 方言：%s" % "、".join("%s=%s" % (k, F(v)) for k, v in dia.most_common()))
    byurl = len({(r[0], r[1]) for r in raw})
    print("\n🔴 **B12**：原始 %s → 按 schema 的 `UNIQUE(word_id,url)` 只能并到 %s"
          " → 按 Commons 归一键并到 **%s**" % (F(len(raw)), F(byurl), F(len(rows))))
    print("   ⇒ 不自己并的话 **%s 行重复会落进库**（两个按钮播同一个文件）"
          % F(byurl - len(rows)))
    print("\n🔴 张冠李戴（文件名里的词≠词形且源头没说它们是一回事）：**%d 行 / %d 组**"
          % (len(bad), len(set(bad))))
    for w, fw, src in sorted(set(bad)):
        print("     %-24s ← 文件名里是 %-16s （%s）" % (w, fw, src))
    print("   ⚠️ 逐条读过：真错 4 组；已知假阳 3 组（欠账 **W8**）⇒ 精确度 ~57%，"
          "**只隐藏不删**；展示层永不播一条读错的音")

    cov = len({r[0] for r in pub})
    print("\n■ 读者口径：有录音的词形 **%s（%.2f%%）**" % (F(cov), 100.0 * cov / tot))

    dbtool.sample_check([(r[2][:44], r[3], r[4].split("-")[0], r[5] or "出版")
                         for r in rows], 8, ("Commons 键", "方言", "源", "出版/隐藏"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session(
            "build-vi-audio-layer",
            expect={"__rows__": 0, "#audio": len(rows), "audio.commons_key": len(rows)},
            invalidates=["录音层落第一行 ⇒ `audio` 从 UNCLAIMED 里拿出来，"
                         "录音层闸必须登记并跑绿（`vi/tests/test_audio_layer.py`）"]) as s:
        # 🔴 判为张冠李戴的 **入库但 hidden=1**，不删 —— 判据精确度只有 57%，
        #    删掉就再也找不回那 3 条假阳（`audio.hidden`/`hidden_why` 是阶段 6 补的列）
        s.executemany(
            "INSERT INTO audio (word_id, url, commons_key, dialect, hidden, hidden_why, src) "
            "VALUES (?,?,?,?,?,?,?)",
            [(r[0], r[1], r[2], r[3], 0 if r[5] is None else 1, r[5], r[4]) for r in rows])

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]                      # noqa: E731
    checks = [
        ("audio 行数", q("SELECT COUNT(*) FROM audio"), len(rows)),
        ("commons_key 都填了",
         q("SELECT COUNT(*) FROM audio WHERE commons_key IS NULL OR TRIM(commons_key)=''"), 0),
        ("🔴 B12：同一 (词, Commons 键) 只有一行",
         q("SELECT COUNT(*) FROM (SELECT word_id, commons_key FROM audio "
           "GROUP BY word_id, commons_key HAVING COUNT(*)>1)"), 0),
        ("每条都挂得上 dict",
         q("SELECT COUNT(*) FROM audio a LEFT JOIN dict d ON d.id=a.word_id "
           "WHERE d.id IS NULL"), 0),
        ("隐藏的都写了为什么",
         q("SELECT COUNT(*) FROM audio WHERE hidden=1 AND "
           "(hidden_why IS NULL OR TRIM(hidden_why)='')"), 0),
        ("张冠李戴那批真的被隐藏了（不是删了）",
         q("SELECT COUNT(*) FROM audio WHERE hidden=1"), len(rows) - len(pub)),
        ("dialect 都在 pron_sources 的值域里",
         q("SELECT COUNT(*) FROM audio WHERE dialect NOT IN (%s)"
           % ",".join("'%s'" % d for d in sorted(
               set(__import__("pron_sources").DIALECTS.values()) | {"unknown"}))), 0),
    ]
    for name, got, want in checks:
        print("   %s %-38s %s（期望 %s）"
              % ("✅" if got == want else "🔴", name, F(got), F(want)))
    con.close()
    if any(g != w for _n, g, w in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
