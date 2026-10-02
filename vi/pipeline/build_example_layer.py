#!/usr/bin/env python3
"""vi 阶段 6a：**例句层**（`example` / `example_gloss`）。2026-10-01。

判据全部 `import stage6_sources`，本文件一行判据都不写。
裁决过程见 `vi/probes/probe_stage6.py` §B（可重跑）。

═══ 挂靠：例句挂在**义项**上，而义项的键是 `sense_src.src_ref` ═══
例句在源头躺在 `senses[si].examples[]` 里 ⇒ 键是 `(版, 词, 词性, 词源号, si)`，
比义项层的键少最后一节（`gi`，gloss 序号）。一个 si 有多个 gloss 时取**第一条已出版的**。
⚠️ 实测一个 si 带 >1 个 gloss 的只有 587 组（0.4%）⇒ 影响面很小，**但仍然声明**。

三级落点，每一级都写清为什么（`[[dont-gate-facts-on-my-uncertainty]]`）：

    ① 键对得上且该义项已出版  ⇒ `sense_id` ＝ 那条义项     56,419 条（72.0%）
    ② 键对得上而该义项被隐藏  ⇒ `sense_id` NULL，词条级      1,838 条（ 2.3%）
    ③ **本版的义项压根没进 `sense_src`** ⇒ NULL，词条级     20,097 条（25.6%）

🔴 ③ 不是 bug，也不是「键算错了」—— 是**我们有意只收了三版的义项**
   （en/vi/zh，`[[gloss-three-languages]]`）。跨版收割的 fr/ko/de/nl… 九版
   没有义项行，它们的例句自然挂不到义项上。
   `[[dont-say-source-lacks-what-we-skipped]]`：这两件事必须在结构上分得开 ——
   所以 ② 和 ③ 是两个计数，不是一个「挂不上」。

═══ 🔴🔴 译文的语种**按版定，不按字段名定** ═══
vi 版 709 条 `translation` 里**一条真译文都没有**（214 条整串是 `.`，290 条是
`(tục ngữ)` 这种出处标注）。照字段名收 ⇒ 读者看见「译文：.」。
那批进 `example.ref`（它确实是出处），不进 `example_gloss`。

用法：
    python3 vi/pipeline/build_example_layer.py            # 干跑
    python3 vi/pipeline/build_example_layer.py --apply
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

PATH_OF = {
    "en-edition": paths.KK, "vi-edition": paths.EDITION,
    "zh-edition-trad": paths.ZH_TRAD, "zh-edition-simp": paths.ZH_SIMP,
    "fr-edition": paths.FR_EDITION, "ja-edition": paths.JA_EDITION,
    "ko-edition": paths.KO_EDITION, "pl-edition": paths.PL_EDITION,
    "ru-edition": paths.RU_EDITION, "nl-edition": paths.NL_EDITION,
    "pt-edition": paths.PT_EDITION, "de-edition": paths.DE_EDITION,
}
F = lambda n: format(n, ",")                                      # noqa: E731


def rd(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def sense_index(con):
    """→ ({(版,词,词性,词源号,si): sense_id}, {同键: 这个键在 sense_src 里有几行})

    🔴 `src_ref` 是 `sense:<ed>:<w>:<pos>:<etym>:<si>:<gi>`，而**词形本身可能含 `:`**
       ⇒ 从右往左切。`split(":")` 会把带冒号的词形切烂而不报错。
    """
    sid, groups = {}, collections.Counter()
    for ref, s in con.execute("SELECT src_ref, sense_id FROM sense_src ORDER BY id"):
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
        if s is not None and k not in sid:
            sid[k] = s
    return sid, groups


def collect(wid, s2id, groups):
    rows, stat = [], collections.Counter()
    for src, _lang in S6.EDITIONS:
        ed = src.split("-")[0]
        tr_lang = S6.TR_LANG[src]
        ref_from_tr = src in S6.REF_FROM_TRANSLATION
        for e in rd(PATH_OF[src]):
            w = (e.get("word") or "").strip()
            if w not in wid:
                stat["源词不在 dict（汉字词头等，有意不收）"] += 1
                continue
            pos = e.get("pos")
            etym = str(e.get("etymology_number", "0") or "0")
            for si, s in enumerate(e.get("senses") or []):
                for xi, x in enumerate(s.get("examples") or []):
                    t = (x.get("text") or "").strip()
                    if not t:
                        stat["文本空 ⇒ 不入库"] += 1
                        continue
                    k = (ed, w, pos, etym, si)
                    sense_id = s2id.get(k)
                    if sense_id is not None:
                        stat["落点① 挂上已出版义项"] += 1
                    elif k in groups:
                        stat["落点② 该义项被隐藏 ⇒ 词条级"] += 1
                    else:
                        stat["落点③ 本版义项没收（三语方针）⇒ 词条级"] += 1
                    why = S6.example_hidden_why(t, w, x.get("tags") or [])
                    stat[("隐藏：" + why) if why else "✅ 可出版"] += 1
                    # 出处：`ref` 字段，以及**那些版里其实装着出处的 `translation`**
                    ref = (x.get("ref") or "").strip() or None
                    tr = (x.get("translation") or x.get("english") or "").strip()
                    if ref_from_tr and tr and not ref:
                        ref = tr
                    gloss = None
                    if tr_lang and tr:
                        gloss = (tr_lang, tr)
                        stat["译文 %s" % tr_lang] += 1
                    elif tr:
                        stat["译文是第四语言（%s）⇒ 有意不收" % ed] += 1
                    # 🔴 主键必须唯一标定源记录：版+词+词性+词源号+义序+例序。
                    #    漏掉词性/词源号 ⇒ 同一个词的名词条与动词条的例句键撞在一起
                    #    （义项层上这个 bug 差点悄悄丢掉一万条真义项）。
                    rows.append((wid[w], sense_id, t, ref, why, src,
                                 "ex:%s:%s:%s:%s:%d:%d" % (ed, w, pos, etym, si, xi),
                                 gloss))
    # 同一条证据在同一版里出现两次就是重复（`src_ref` 唯一）
    seen, out = set(), []
    for r in rows:
        if r[6] in seen:
            stat["同源重复（去重）"] += 1
            continue
        seen.add(r[6])
        out.append(r)
    return out, stat


def gloss_rows(rows):
    """`collect()` 的行里，**哪些真的会在 `example_gloss` 里落一行**。

    🔴🔴 **2026-10-02 抽出来的，而且是外锚闸第一次跑就逼出来的。**
       原先这个条件以字面量写在 `main()` 里（`[r for r in rows if r[7] and r[4] is None]`），
       外锚闸照着"有译文"自己写了一遍 ⇒ 漏掉 `r[4] is None`，报 **458 条假缺**。
    ⚠️ 教训比「少写一个条件」大：**import 收割器的判据还不够** ——
       「哪些行才真的落库」这一步也是判据，它也必须只有一个家。
       ko 那道外锚闸记的是「闸自己重写收割器的判据」，这里是**同一个病的更细一层**：
       判据共用了，**落库口径没共用**。
    ⭐ 条件本身的理由：隐藏的例句不存译文（闸 **X8**）—— 否则 6e 按「有没有译文」
       挑行时，钱会花在不出版的行上（ko 的 6d 正是这个口径）。
    """
    return [r for r in rows if r[7] and r[4] is None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    s2id, groups = sense_index(con)
    tot = len(wid)
    con.close()
    print("■ dict %s 词形；义项键 %s 组（有已出版义项的 %s）"
          % (F(tot), F(len(groups)), F(len(s2id))))

    rows, stat = collect(wid, s2id, groups)
    pub = [r for r in rows if r[4] is None]
    gl = gloss_rows(rows)
    print("\n■ 例句 %s 条（可出版 %s ／ 隐藏 %s），译文 %s 条"
          % (F(len(rows)), F(len(pub)), F(len(rows) - len(pub)), F(len(gl))))
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print("   %-44s %8s" % (k, F(v)))

    cov = len({r[0] for r in pub})
    covzh = len({r[0] for r in gl if r[7][0] == "zh"})
    print("\n■ 读者口径：有可出版例句的词形 **%s（%.1f%%）**；其中有中文译文的 %s（%.2f%%）"
          % (F(cov), 100.0 * cov / tot, F(covzh), 100.0 * covzh / tot))
    print("   ⚠️ 中文译文覆盖这么低不是漏抽 —— 源头只有 zh 版给（698 条），"
          "其余九版的译文是第四语言。把越南语例句本身译成中文是**要花钱的那条路**。")

    dbtool.sample_check([(r[2][:46], (r[5] or "")[:14],
                          "挂义项" if r[1] else "词条级", r[4] or "出版") for r in rows],
                        10, ("例句", "源", "落点", "出版/隐藏"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session(
            "build-vi-example-layer",
            expect={"__rows__": 0, "#example": len(rows), "#example_gloss": len(gl)},
            invalidates=["例句层落第一行 ⇒ `example`/`example_gloss` 从 UNCLAIMED 里拿出来，"
                         "例句层闸必须登记并跑绿（`vi/tests/test_example_layer.py`）"]) as s:
        s.executemany(
            "INSERT INTO example (word_id, sense_id, text, ref, hidden, hidden_why, "
            "src, src_ref) VALUES (?,?,?,?,?,?,?,?)",
            [(r[0], r[1], r[2], r[3], 0 if r[4] is None else 1, r[4], r[5], r[6])
             for r in rows])
        eid = {ref: i for i, ref in s.execute("SELECT id, src_ref FROM example")}
        s.executemany(
            "INSERT INTO example_gloss (example_id, lang, text, src) VALUES (?,?,?,?)",
            [(eid[r[6]], r[7][0], r[7][1], r[5]) for r in gl])

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]                     # noqa: E731
    checks = [
        ("example 行数", q("SELECT COUNT(*) FROM example"), len(rows)),
        ("example_gloss 行数", q("SELECT COUNT(*) FROM example_gloss"), len(gl)),
        ("src_ref 唯一", q("SELECT COUNT(*) FROM (SELECT src_ref FROM example "
                          "GROUP BY src_ref HAVING COUNT(*)>1)"), 0),
        ("每条都挂得上 dict",
         q("SELECT COUNT(*) FROM example e LEFT JOIN dict d ON d.id=e.word_id "
           "WHERE d.id IS NULL"), 0),
        ("sense_id 要么空要么真指向一条 sense",
         q("SELECT COUNT(*) FROM example e LEFT JOIN sense s ON s.id=e.sense_id "
           "WHERE e.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        # 🔴 译文只挂在可出版的例句上 —— 隐藏的例句带译文＝白译
        ("隐藏的例句不带译文",
         q("SELECT COUNT(*) FROM example_gloss g JOIN example e ON e.id=g.example_id "
           "WHERE e.hidden=1"), 0),
        ("译文只有三语",
         q("SELECT COUNT(*) FROM example_gloss WHERE lang NOT IN ('zh','en','vi')"), 0),
    ]
    for name, got, want in checks:
        print("   %s %-38s %s（期望 %s）"
              % ("✅" if got == want else "🔴", name, F(got), F(want)))
    con.close()
    if any(g != w for _n, g, w in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
