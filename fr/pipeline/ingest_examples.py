#!/usr/bin/env python3
"""阶段 5 — 收例句（七版 kaikki）→ `example` / `example_gloss`。2026-08-25。

═══ 判据与边界 ═══
· **只认 kaikki**（用户 2026-08-03 方针 A3）：Tatoeba / OPUS 一律不碰。
· **文本一个字节都不许动。** `bold_text_offsets` 是弹窗高亮词形用的坐标，
  改一个字符偏移量就全错位。⇒ 法语释义那套清洗（`gloss_clean`）**不适用于例句**；
  有引文残渣只能记账，不能剥。
· 例句挂到**义项**上，挂载依据是**源头坐标**，确定性对上，不猜：
      法文版  `kk-fr:<词>:<pos_raw>#<occ>.<义项序>`   ← 与 `ingest_fr_edition` 同一套 occ 计数
      英文版  `kk-en:<词>:<pos_raw>:<词源号>:<seq>#<义项序>`
  法文版占 96%，坐标逐字复算得到；其余版**挂不上照收**、`sense_id` 留 NULL ——
  挂在词上仍然有用（划词弹窗要的是「这个词」的例句）。

═══ 规模（实测，2026-08-25）═══
    七版原始         742,248
    (词,句) 去重      740,363   ← 入库行数（`UNIQUE(word, text)`）
    **不同句子**      615,033   ← 翻译成本的真分母（同一句可给几个词当例句，省 16.9%）
    句长中位 152 字符 / 均 158；法文版一家占 96%

⚠️ 这批例句**几乎全是文学引文**（带 `ref` 文献出处、大量简单过去时），
   不是教学例句。权威性强、实用性存疑 —— 用户 2026-08-25 明确「全量翻吧，该花的还是要花的」。

═══ 译文分两层（照 it）═══
· `example_gloss` = **出版层**，只放中英（A3：释义只留三语，例句原文本身就是法语）。
  英文版自带的英文译文 13,803 条直接进这里。
· `example.src_translation` + `src_lang` = **证据层**，放源头给的、我们不出版的语言
  （nl/ru/ja/el/tr 版给的本国语译文）。留着能回源核对，不展示。

用法（在 fr/ 目录下）：
    python3 -u pipeline/ingest_examples.py            # 干跑
    python3 -u pipeline/ingest_examples.py --sample 12
    python3 -u pipeline/ingest_examples.py --apply
    python3 -u pipeline/ingest_examples.py --verify
    python3 -u pipeline/ingest_examples.py --undo
"""
import argparse
import gzip
import io
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool                              # noqa: E402
import paths                               # noqa: E402
from intake_fr_words import norm_apos      # noqa: E402

# (键, 路径, lang_code 过滤, 源头译文是什么语言)
SOURCES = [
    ("fr-edition", paths.EDITION, "fr", None),
    ("en-edition", paths.KK, "fr", "en"),
    ("el-edition", paths.DUMPS / "kaikki.org-elwiktionary-French.jsonl.gz", None, "el"),
    ("nl-edition", paths.DUMPS / "kaikki.org-nlwiktionary-French.jsonl.gz", None, "nl"),
    ("ru-edition", paths.DUMPS / "kaikki.org-ruwiktionary-French.jsonl.gz", None, "ru"),
    ("ja-edition", paths.DUMPS / "kaikki.org-jawiktionary-French.jsonl.gz", None, "ja"),
    ("tr-edition", paths.DUMPS / "kaikki.org-trwiktionary-French.jsonl.gz", None, "tr"),
]
# 出版层收哪些语言的源头译文（A3：中 + 英 + 本语言；例句原文本身就是法语）
PUBLISH = {"en"}


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if str(p).endswith(".gz") \
        else io.open(p, encoding="utf-8")


def norm(s):
    return " ".join((s or "").split())


def valid_bold(off, text, st):
    """高亮坐标 → JSON，**坐标本身也要过闸**。

    🔴 源头会吐退化坐标：`[[0,0],[1,1],[2,2],…]` 每个字符位一个**零宽**区间 ——
       实测 59 条，全出在句子里带 `'''` wiki 标记的那些（wiktextract 被它干扰）。
       这种 `bold` 拿去高亮只会画错位置。**该丢的是坐标，不是句子。**
    ⚠️ 文本一个字节不动，所以能丢的只有坐标 —— 反过来做（改文本迁就坐标）是灾难。
    """
    if not off:
        return None
    good = [[a, z] for a, z in off if isinstance(a, int) and isinstance(z, int)
            and 0 <= a < z <= len(text)]
    if len(good) != len(off):
        st["🔴 源头高亮坐标非法，已丢弃（句子照收）"] += 1
    return json.dumps(good) if good else None


def harvest(con, limit=0):
    """→ (rows, stat)。rows 元素 = dict，键与 `example` 表同名。"""
    st = Counter()
    # 法文版的义项坐标 → sense_id（裁决之后 91.4% 已挂上）
    ref2sense = {}
    for ref, sid in con.execute(
            "SELECT src_ref, sense_id FROM sense_src WHERE src='fr-edition'"):
        if sid is not None:
            ref2sense[ref] = sid

    seen = set()
    rows = []
    for name, path, lc, tlang in SOURCES:
        if not Path(path).exists():
            print("   （%s 不存在，跳过）" % name)
            continue
        n = 0
        add = 0
        with opener(path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if lc and e.get("lang_code") != lc:
                    continue
                w0 = (e.get("word") or "").strip()
                if not w0:
                    continue
                w = norm_apos(w0)
                n += 1
                if limit and n > limit:
                    break
                pos_raw = e.get("pos") or ""
                # 🔴 `occ` 必须与 `ingest_fr_edition.run()` 同一套计数，否则坐标对不上
                if name == "fr-edition":
                    key = (norm_apos(w0), pos_raw)
                    occ = st[("occ", key)]
                    st[("occ", key)] += 1
                for i, s in enumerate(e.get("senses") or []):
                    gl = norm((s.get("glosses") or [""])[0])
                    sid = None
                    if name == "fr-edition":
                        sid = ref2sense.get("kk-fr:%s:%s#%d.%d"
                                            % (norm_apos(w0), pos_raw, occ, i))
                    for x in s.get("examples") or []:
                        # 🔴🔴 **文本原样存，一个字节都不许动。**
                        #    我第一版写了 `norm()`（空白归一），闸当场逮到 168 条
                        #    「高亮坐标越界」—— `bold_text_offsets` 是相对**原始文本**
                        #    的字符区间，归一一次就全错位，而这个错**在数据里看不出来，
                        #    只有渲染出来才发现**（`[[it-display-layer-stage8]]` 的形状）。
                        #    ⇒ 连 `.strip()` 都不做（去掉行首空白同样会平移偏移量）。
                        t = x.get("text") or ""
                        if not t.strip():
                            st["空 text"] += 1
                            continue
                        k = (w, t)
                        if k in seen:
                            st["(词,句) 重复（跨源或跨义项）"] += 1
                            continue
                        seen.add(k)
                        tr = norm(x.get("translation"))
                        rows.append({
                            # 🔴 `word` 必须过 `norm_apos` —— 全库唯一约定（直撇）。
                            #    第一版存 dump 原样（`l’eau`），15,577 行连不上 `dict`。
                            "word": w, "sense_id": sid, "text": t,
                            "bold": valid_bold(x.get("bold_text_offsets"), t, st),
                            "ref": norm(x.get("ref")) or None,
                            "src_gloss": gl or None,
                            "src_translation": tr or None,
                            "src_lang": tlang if tr else None,
                            "src": name,
                        })
                        add += 1
                        if sid:
                            st["✓ 确定性挂上义项"] += 1
                        else:
                            st["📋 挂不上义项（照收，sense_id=NULL）"] += 1
                        if tr and tlang in PUBLISH:
                            st["源头译文可直接进出版层（%s）" % tlang] += 1
        print("   %-12s 收 %s 条" % (name, format(add, ",")))
    st["合计入库行"] = len(rows)
    st["不同句子"] = len({r["text"] for r in rows})
    return rows, st


def apply_rows(rows):
    pub = [(r, r["src_translation"]) for r in rows
           if r["src_translation"] and r["src_lang"] in PUBLISH]
    print("\n■ 落库：`example` %s 行 ｜ 出版层英文译文 %s 条"
          % (format(len(rows), ","), format(len(pub), ",")))
    con = sqlite3.connect(paths.DB)
    with dbtool.session("keep-v3-examples",
                        expect={"#example": len(rows), "#example_gloss": len(pub)}) as s:
        s.executemany(
            "INSERT OR IGNORE INTO example "
            "(word,sense_id,text,bold,ref,src_gloss,src_translation,src_lang,hidden,src) "
            "VALUES (:word,:sense_id,:text,:bold,:ref,:src_gloss,:src_translation,"
            ":src_lang,0,:src)", rows)
        # 英文译文按 (word,text) 回查 id
        s.execute("CREATE TEMP TABLE _en (word TEXT, text TEXT, tr TEXT)")
        s.executemany("INSERT INTO _en VALUES (?,?,?)",
                      [(r["word"], r["text"], tr) for r, tr in pub])
        s.execute("INSERT OR IGNORE INTO example_gloss (example_id,lang,text,src) "
                  "SELECT e.id,'en',t.tr,'en-edition' FROM _en t "
                  "JOIN example e ON e.word=t.word AND e.text=t.text")
    con.close()
    print("✓ 写入完成（撤回：--undo）")
    return 0


def verify():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok = True

    def chk(name, got, want):
        nonlocal ok
        ok &= got == want
        print("   %s %-50s %10s  期望 %s"
              % ("✓" if got == want else "🔴", name, format(got, ","), format(want, ",")))

    n = con.execute("SELECT count(*) FROM example").fetchone()[0]
    att = con.execute("SELECT count(*) FROM example WHERE sense_id IS NOT NULL").fetchone()[0]
    print("■ example %s 行 ｜ 挂上义项 %s (%.1f%%) ｜ 不同句子 %s"
          % (format(n, ","), format(att, ","), 100.0 * att / max(n, 1),
             format(con.execute("SELECT count(DISTINCT text) FROM example").fetchone()[0], ",")))
    chk("① 孤儿：sense_id 指向不存在的义项",
        con.execute("SELECT count(*) FROM example e LEFT JOIN sense s ON s.id=e.sense_id "
                    "WHERE e.sense_id IS NOT NULL AND s.id IS NULL").fetchone()[0], 0)
    chk("② 词形不在 dict",
        con.execute("SELECT count(*) FROM example e LEFT JOIN dict d "
                    "ON d.word=e.word WHERE d.id IS NULL").fetchone()[0], 0)
    chk("③ text 为空", con.execute("SELECT count(*) FROM example "
                                   "WHERE TRIM(text)=''").fetchone()[0], 0)
    # ④ 🔴 高亮坐标必须落在句子范围内 —— 这是"文本没被动过"的可判定证明
    bad = 0
    for t, b in con.execute("SELECT text, bold FROM example WHERE bold IS NOT NULL"):
        try:
            for a, z in json.loads(b):
                if not (0 <= a < z <= len(t)):
                    bad += 1
                    break
        except Exception:
            bad += 1
    chk("④ 高亮坐标越界（= 文本被动过）", bad, 0)
    chk("⑤ 出版层出现了中英之外的语言",
        con.execute("SELECT count(*) FROM example_gloss "
                    "WHERE lang NOT IN ('zh','en')").fetchone()[0], 0)
    print("■ 出版层：%s" % dict(con.execute(
        "SELECT lang, count(*) FROM example_gloss GROUP BY lang")))
    print("%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


def undo():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ne = con.execute("SELECT count(*) FROM example").fetchone()[0]
    ng = con.execute("SELECT count(*) FROM example_gloss").fetchone()[0]
    print("■ 撤回：example %s 行、example_gloss %s 行"
          % (format(ne, ","), format(ng, ",")))
    with dbtool.session("keep-v3-examples-undo",
                        expect={"#example": -ne, "#example_gloss": -ng}) as s:
        s.execute("DELETE FROM example_gloss")
        s.execute("DELETE FROM example")
    print("✓ 已撤回")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--undo", action="store_true")
    a = ap.parse_args()
    if a.verify:
        return verify()
    if a.undo:
        return undo()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, st = harvest(con, a.limit)
    print("\n══ 统计 ══")
    for k, v in st.most_common():
        if isinstance(k, tuple):
            continue
        print("   %-46s %10s" % (k, format(v, ",")))
    if a.sample:
        xs = random.Random(7).sample(rows, min(a.sample, len(rows)))
        print("\n══ 抽样 %d 条 ══" % len(xs))
        for r in xs:
            print("   %-18s [%s] %s"
                  % (r["word"][:18], "挂上" if r["sense_id"] else "未挂", r["text"][:96]))
            if r["ref"]:
                print("        —— %s" % r["ref"][:78])
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    con.close()
    apply_rows(rows)
    return verify()


if __name__ == "__main__":
    sys.exit(main())
