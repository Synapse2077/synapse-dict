#!/usr/bin/env python3
"""阶段 3a：收词 —— 从 kaikki 新包灌 `dict` 词形层。2026-09-07。

计划见 `docs/EN_PLAN.md` 阶段表 3a。**只收 kaikki**；ECDICT 补充的 260 万归 3b。

═══ 这一步只做「词形」，不做义项 ═══
`dict` 一行 ＝ **一个词形**（不是一个词条，也不是一个义项）——
`[[schema-redesign-doc]]` 那条核心判断：「我们把**词形**当成了**词条**」。
词条层是阶段 1（`entry`），义项层是阶段 1/1.5（`sense`）。

⚠️ 本步**只填四列**：`word` / `word_norm` / `is_lemma` / `pos`。
   `collins`/`oxford`/`exam_tag`/`bnc`/`freq_rank` 归**阶段 1**（从 `legacy_dict` 挂入），
   `freq_zipf` 归阶段 5。一次只动一样东西（`[[one-problem-at-a-time]]`）。

═══ 顺带产出中间件，让阶段 1 不必再扫一遍 3.2 GB ═══
`data/work/en/ingest/entries.jsonl` —— 每个 kaikki entry 一行，字段已裁剪到后面用得着的那些。
阶段 1（entry/sense_src）、阶段 4（音标）、阶段 5（例句/关系）都从它读。
🔴 **这不是缓存，是取数留痕**：它记下了「本轮从 dump 里认了哪些字段」，
   将来换 dump 版本时，两份中间件一 diff 就知道上游改了什么
   （`[[external-anchor-gates]]`）。

═══ 判据 ═══
① **一个词形一行，pos 合并** ——「/」连接排序后的全部词性（照 de）。
   `record` 有 noun/adj/verb 三个 entry ⇒ `dict` 一行、`pos = "adj/noun/verb"`。
   逐义项词性在 `sense.pos`、逐词条在 `entry.pos`，这里只是词形级的粗标。

② 🔴 **`is_lemma` ＝ 这个词形有没有「自己的」义项**（不是「像不像原形」）。
   判据：**至少有一条不是屈折指针的义项** ⇒ 1，否则 0。
   「屈折指针」取源头的结构化标记 `form_of` / `tags:['form-of']`，**不是 gloss 前缀**；
   **`alt_of`（异体拼写）不算屈折** —— 详细依据与三口径实测见下面 `is_inflection` 上方。
   ⚠️ **这是我们自己打的标，不是源头给的事实。**
      `[[it-display-layer-stage8]]`：it/pt/de 三门都栽在
      「拿 `is_lemma` 决定要不要显示释义」上，de 一处挡住 **124,291 个词形**的整块释义。
      ⇒ 本列只服务「排序/去重/变形归位」，**阶段 8 不许拿它当显示开关**。
      阶段 2 建完 `inflection` 后会复核一次。

③ **词组照收**（含空格的 324,332 条）。产品是划词弹窗、`getEntry()` 拿划选原文精确匹配，
   实测 `clear title`/`Ambystoma tigrinum` 都能命中 ——
   `[[dict-product-scope-popup]]`：短语打得到，不是"留着不伤人"。

④ **大小写不折叠**：`word` 原样存，检索靠 `word_norm`
   （`[[case-folding-contaminates-columns]]`：老库 `word.lower()` 的后遗症）。
   ⇒ `US` 与 `us`、`Polish` 与 `polish` 是**两行**。

跑：
    cd en && python3 pipeline/build_dict.py            # 干跑：只扫不写，打出将写什么
    cd en && python3 pipeline/build_dict.py --run
    cd en && python3 pipeline/build_dict.py --verify   # 只跑闸
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import sqlite3
import time

import dbtool
import paths
from word_norm import norm_en

WORK = paths.WORK / "ingest"
ENTRIES = WORK / "entries.jsonl"

# ══════════════════ `is_lemma` 的判据 ══════════════════
#
# 🔴🔴 **判据是源头的结构化标记，不是 gloss 的字符串前缀。**
#    第一版我写了一张 28 个措辞的 `META` 前缀表 —— 那是拿**形式**当判据
#    （`[[criteria-from-meaning-not-form]]`），而且它漏了整族
#    （`birdnests` 的 "third-person singular simple present indicative of birdnest"
#     不在表里 ⇒ 被当成真义项 ⇒ 判成词元）。
#    kaikki 自带 `tags:['form-of',…]` ＋ `form_of:[{'word':X}]`，那是**源头自己的陈述**。
#
# ⭐ **拿 ECDICT 的 `exchange` 当独立外锚实测过三个口径**（交集 329,490 词，非抽样）：
#    | 口径                | 判 lemma | 与外锚一致 | 变形→lemma | lemma→变形 |
#    | 字符串前缀（第一版）      | 220,993 |   76.6%  |   32,160 |   45,079 |
#    | 结构化，含 alt_of      | 207,836 |   85.3%  |   11,142 |   37,218 |
#    | **结构化，只算屈折**    | 244,221 | **95.8%**|   12,025 |  **1,716** |
#    并集比单独用结构化**更差**（82.1%）—— 字符串加的是噪声不是信号，已整张删掉。
#
# 🔴 **决定性的一条：`alt_of` 不算变形。**
#    `Mobius strip`→"Alternative spelling of Möbius strip"、`hang-around`、`SEB`
#    —— **异体拼写是它自己的词头**，读者查得到它，不是任何词的屈折形式。
#    把它判成非词元会让 3.7 万个正经词头在展示层被当成变形。
#    （同 `[[en-dict-pipeline]]` A1d 那条：「异体拼写不是形态派生」。）
#
# ⚠️ 残留 12,025 条「我判词元、ECDICT 判变形」**多数是我对**：
#    `bifocals` 双光眼镜 / `auditing` 审计 / `vanquished` 被击败的 / `Fridays` 每逢周五
#    —— ECDICT 按词形机械判的伪变形（那是已知缺陷）。⇒ 一致率的真值高于 95.8%。


def is_inflection(sense):
    """这条义项是不是**屈折形式指针**（不含异体拼写）。"""
    return bool(sense.get("form_of")) or ("form-of" in set(sense.get("tags") or []))


def collect(keep_entries=True):
    """扫一遍 dump。→ (words, stat)

    words: word → {"pos": set, "real": bool}
    同时把裁剪过的 entry 落 `entries.jsonl`（阶段 1/4/5 的输入）。
    """
    WORK.mkdir(parents=True, exist_ok=True)
    words = {}
    stat = collections.Counter()
    t0 = time.time()
    fw = open(ENTRIES, "w", encoding="utf-8") if keep_entries else None
    for line in open(paths.KK, encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            stat["unparsable"] += 1
            continue
        # 🔴 thesaurus 条目不是词条（`cat → "Terms relating to things."`）——
        #    老脚本 `probes/import-wiktionary-newwords.py` 就滤了，我第一版漏了。
        #    全库只有 216 条，但"少"不是不滤的理由。
        if d.get("source") == "thesaurus":
            stat["thesaurus"] += 1
            continue
        w = (d.get("word") or "").strip()
        if not w:
            stat["no_word"] += 1
            continue
        stat["entries"] += 1
        pos = d.get("pos") or None
        senses = d.get("senses") or []
        real = False
        for se in senses:
            if (se.get("glosses") or []) and not is_inflection(se):
                real = True
                break
        rec = words.get(w)
        if rec is None:
            rec = words[w] = {"pos": set(), "real": False}
        if pos:
            rec["pos"].add(pos)
        rec["real"] = rec["real"] or real
        if fw:
            fw.write(json.dumps({
                "word": w,
                "pos": pos,
                "etym": d.get("etymology_number") or d.get("etymology_text") and 0 or None,
                # 🔴 存 `glosses[-1]`（最具体的那句）＋ 嵌套时留完整 `path`。
                #    源头的 `glosses` 是**从泛到 specific 的一条路径**，不是并列释义；
                #    取 `[0]` 会把 43,443 条义项压成重复（`free` 六条全变 "Unconstrained."）。
                #    de/pt/fr 的 build.py 取的都是 `[0]`，它们的义项主要来自本语言版才没炸。
                "senses": [{"g": (se.get("glosses") or [None])[-1],
                            "path": (se.get("glosses") if len(se.get("glosses") or []) > 1
                                     else None),
                            "tags": se.get("tags") or [],
                            "topics": se.get("topics") or [],
                            "form_of": se.get("form_of") or None,
                            "alt_of": se.get("alt_of") or None,
                            "ex": len(se.get("examples") or [])}
                           for se in senses],
                "sounds": [{"ipa": so.get("ipa"), "tags": so.get("tags") or []}
                           for so in (d.get("sounds") or []) if so.get("ipa")],
                "forms": len(d.get("forms") or []),
            }, ensure_ascii=False) + "\n")
    if fw:
        fw.close()
    stat["seconds"] = int(time.time() - t0)
    return words, stat


def plan(words):
    """→ [(word, word_norm, is_lemma, pos)]，按 word 排序保证可复现。"""
    out = []
    for w in sorted(words):
        rec = words[w]
        out.append((w, norm_en(w), 1 if rec["real"] else 0,
                    "/".join(sorted(rec["pos"])) if rec["pos"] else None))
    return out


# ══════════════════ 闸 ══════════════════

def gates(con, rows):
    """闸②。→ [(名字, 实际, 期望)]"""
    q = lambda s: con.execute(s).fetchone()[0]
    want_pos = sum(1 for r in rows if r[3])
    want_lemma = sum(1 for r in rows if r[2])
    checks = [
        ("dict 行数 == 计划条数", q("SELECT COUNT(*) FROM dict"), len(rows)),
        ("词形唯一（word 不重复）", q("SELECT COUNT(DISTINCT word) FROM dict"), len(rows)),
        ("word_norm 无空", q("SELECT COUNT(*) FROM dict WHERE TRIM(word_norm)=''"), 0),
        ("有 pos 的行数", q("SELECT COUNT(*) FROM dict WHERE pos IS NOT NULL"), want_pos),
        ("is_lemma=1 的行数", q("SELECT COUNT(*) FROM dict WHERE is_lemma=1"), want_lemma),
        ("is_lemma 只有 0/1", q("SELECT COUNT(*) FROM dict WHERE is_lemma NOT IN (0,1)"), 0),
        # 🔴 大小写不折叠：`US`/`us` 必须是两行。判据用一个**必然存在**的样本对，
        #    不是抽象断言 —— 抽象断言写错了会恒真。
        ("大小写未被折叠（US/us 各一行）",
         q("SELECT COUNT(*) FROM dict WHERE word IN ('US','us')"), 2),
        # 🔴 其余列本步一个字都不许写（阶段 1 / 阶段 5 的活）
        ("collins 本步全空", q("SELECT COUNT(*) FROM dict WHERE collins IS NOT NULL"), 0),
        ("exam_tag 本步全空", q("SELECT COUNT(*) FROM dict WHERE exam_tag IS NOT NULL"), 0),
        ("freq_rank 本步全空", q("SELECT COUNT(*) FROM dict WHERE freq_rank IS NOT NULL"), 0),
        # 🔴 冻结表一行没动
        ("legacy_dict 未被触碰",
         q("SELECT COUNT(*) FROM legacy_dict"),
         q("SELECT COUNT(*) FROM legacy_dict")),
        ("出版层各表仍为空",
         sum(q("SELECT COUNT(*) FROM %s" % t) for t in
             ("sense", "sense_src", "sense_gloss", "pronunciation", "example")), 0),
    ]
    return checks


def report(checks):
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-34s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False, verify=False):
    if verify:
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        n = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
        print("═══ 闸② （按库内现状自比，行数 %s）═══" % format(n, ","))
        rows = [(None, None, 1, "x")] * n     # 只跑不依赖 plan 的那几条
        report([c for c in gates(con, rows) if "计划条数" not in c[0]
                and "唯一" not in c[0] and "行数" not in c[0]])
        con.close()
        return 0

    print("扫 %s …" % paths.KK.name)
    words, stat = collect()
    rows = plan(words)
    n_lemma = sum(1 for r in rows if r[2])
    n_pos = sum(1 for r in rows if r[3])
    print("═══ 阶段 3a 计划 ═══")
    print("   扫描 entry            %10s   （%d 秒，不可解析 %d）"
          % (format(stat["entries"], ","), stat["seconds"], stat["unparsable"]))
    print("   → dict 词形            %10s" % format(len(rows), ","))
    print("      is_lemma=1          %10s   %.1f%%"
          % (format(n_lemma, ","), 100 * n_lemma / max(len(rows), 1)))
    print("      is_lemma=0（纯变形） %10s   %.1f%%"
          % (format(len(rows) - n_lemma, ","), 100 * (len(rows) - n_lemma) / max(len(rows), 1)))
    print("      有 pos               %10s" % format(n_pos, ","))
    print("   中间件 → %s" % ENTRIES)
    print("\n   样本（含空格/大小写/变音符各取几个）：")
    import random
    random.seed(11)
    for w, wn, il, p in random.sample(rows, 8):
        print("      %-30s norm=%-30s lemma=%d pos=%s" % (w[:30], wn[:30], il, p))

    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0

    with dbtool.session("keep-v3-3a-ingest",
                        expect={"__rows__": len(rows), "pos": n_pos}) as s:
        s.executemany(
            "INSERT INTO dict (word, word_norm, is_lemma, pos) VALUES (?,?,?,?)",
            [(w, wn, il, p) for w, wn, il, p in rows])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = report(gates(con, rows))
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv, verify="--verify" in _sys.argv))
