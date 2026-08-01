#!/usr/bin/env python3
"""es 来源回填 —— 给 phonetic / translation / gender 三个字段各补一列「这个值是谁给的」。
确定性判定，不调模型。2026-08-01。

═══ 为什么要这一列 ═══
目标是词典的**权威性**：库里必须能一句 SQL 答出「有多少行在说自己不知道的事」。
在此之前这个问题只能靠事后重算来源来回答，而重算会错 —— it 的普查第一版就把
112,209 行（19.2%）判错，原因是没能复现当初的生成路径。
→ 来源如果是**写入时记的**，那类错误在结构上不可能发生。这一列就是那个基础设施。

═══ 🔴 回填的铁律：证明不了就写 unknown ═══
现有 76 万行的来源只能靠重算**推定**。所以回填只写**拿得出证据**的结论，
判据一律是「库值与该来源的产物**逐字相同**」。够不上的写 unknown。
假的 provenance 比没有 provenance 更危险 —— 它会让后续所有基于它的筛选都错。

回填值域（**只有能证明的四种**；往后新写入才用全值域 kaikki-es / rule+form /
hybrid-espeak / llm-doubao / fix:<脚本> 等，因为那些是写入当时记的）：
    kaikki-en     库值 == 英文版 kaikki 的产物            → 有人工源背书
    rule          库值 == 本项目规则的输出                → 可确定性复算
    template      库值 == 结构化模板形态（变形层语法译文）  → 形态可证
    overwritten   该来源有值但库值不同                    → 被改写，改写者未记录
    unknown       无任何源可对照                          → 无背书

⚠️ 一处**推定而非证明**（已标注，见 --report 输出）：kaikki 完全没有该词的 gender、
   而库里有值时记 llm-doubao。依据是流水线上只有豆包会写这个字段（enrich.py 只从
   kaikki 取，b_enrich.py 是豆包）。这是**流水线结构证据**，不是数据证据。

用法（在 es/ 目录）：
  python3 backfill_src.py            # 预览分布，不写库
  python3 backfill_src.py --apply    # 写库（自动备份）
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, json, re, shutil, sqlite3, time
from collections import Counter
from pathlib import Path

import kaikki_util
import enrich                      # 🔴 复现原抽取路径，不自己重写一遍正则
from b_ipa import word_to_ipa

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
# 🔴 书面记录只剩这两份，而且都不完整 —— 这正是 provenance 列要解决的问题本身：
#    · overrides.tsv 原本是 gender 裁决产物，2026-07-26 被**译文**覆盖流程重写覆盖了，
#      gender 的那份记录已不可恢复；现在它装的是 305 条译文覆盖。
#    · gender_decisions.tsv 是 turbo 那轮的裁决表；后来 pro 权威重裁的结果没有单独留档。
#    → 能证明的只有「这个词进过 gender 裁决流程」，证不到「最终是哪一轮定的」。
#      对 _src 来说前者就够了。
OVERRIDES = paths.WORK / "overrides.tsv"            # 译文覆盖记录（305 条）
GENDER_DECISIONS = paths.WORK / "gender_decisions.tsv"   # 进过 gender 裁决的词

# 变形层语法译文的模板形态：`pie 的 阳性·复数` / `piar 的 虚拟式·现在时·…`
# 用**半角空格包裹的「的」**作判据 —— lemma 译文（`免费的，免费`）不会长这样。
TEMPLATE = re.compile(r"^\S+ 的 \S")


def is_template(t):
    """多行译文：每一行都是模板形，才算模板生成。"""
    lines = [l for l in (t or "").split("\n") if l.strip()]
    return bool(lines) and all(TEMPLATE.match(l) for l in lines)


def load_tr_overrides():
    """译文覆盖记录 word\ttranslation\told\tnew → {word: new}。库值与 new 一致即可证。"""
    out = {}
    if OVERRIDES.exists():
        for ln in OVERRIDES.read_text(encoding="utf-8").splitlines():
            p = ln.split("\t")
            if len(p) >= 4 and p[1] == "translation":
                out[p[0]] = p[3]
    return out


def load_gender_adjudicated():
    """进过 gender 裁决流程的词（含 keep_kaikki，因为那也是一次裁决）。"""
    out = set()
    if GENDER_DECISIONS.exists():
        for i, ln in enumerate(GENDER_DECISIONS.read_text(encoding="utf-8").splitlines()):
            if i == 0:
                continue
            p = ln.split("\t")
            if p and p[0]:
                out.add(p[0])
    return out


def kaikki_scan(words):
    """一趟扫完：音位式 + es-noun 抽出的 gender。两者都走原路径。"""
    ipa, gen = {}, {}
    for w, d in kaikki_util.iter_entries(words):
        if w not in ipa:
            for s in (d.get("sounds") or []):
                m = re.match(r"\s*/([^/]+)/", s.get("ipa", "") or "")
                if m:
                    ipa[w] = m.group(1)
                    break
        if w not in gen:
            g, _, _ = enrich.extract_noun(d, w)      # 与 enrich.py 同一函数
            if g:
                gen[w] = g
    return ipa, gen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT id, word, phonetic, translation, gender, meta FROM dict").fetchall()
    conn.close()
    print(f"总行 {len(rows):,}，扫 kaikki…", flush=True)

    t0 = time.time()
    kk_ipa, kk_gen = kaikki_scan({r[1] for r in rows})
    tr_ovr = load_tr_overrides()
    gd_adj = load_gender_adjudicated()
    print(f"  kaikki 音位式 {len(kk_ipa):,} 词 / es-noun gender {len(kk_gen):,} 词 "
          f"/ 译文覆盖 {len(tr_ovr):,} 条 / 进过 gender 裁决 {len(gd_adj):,} 词 "
          f"({time.time()-t0:.0f}s)\n", flush=True)

    tal = {c: Counter() for c in ("phonetic", "translation", "gender")}
    plan = []
    for rid, w, ph, tr, gd, meta in rows:
        # ── 音标 ──────────────────────────────────────────────
        if not (ph or "").strip():
            ps = None
        else:
            kv = kk_ipa.get(w)
            rv = word_to_ipa(w)
            rv = rv.strip("/") if rv else None
            if kv is not None and kv == ph:
                ps = "kaikki-en"
            elif rv is not None and rv == ph:
                ps = "rule"
            elif kv is not None:
                ps = "overwritten"
            else:
                ps = "unknown"
            tal["phonetic"][ps] += 1

        # ── 译文 ──────────────────────────────────────────────
        if not (tr or "").strip():
            ts = None
        else:
            if tr_ovr.get(w) == tr:
                ts = "fix:translation-override"
            elif is_template(tr):
                ts = "template"
            else:
                ts = "llm-doubao"
            tal["translation"][ts] += 1

        # ── 性别 ──────────────────────────────────────────────
        if not (gd or "").strip():
            gs = None
        else:
            kg = kk_gen.get(w) or enrich.gender_from_meta(meta)
            if kg is not None and kg == gd:
                gs = "kaikki-en"           # 与 kaikki 一致 —— 裁没裁过都不影响这个结论
            elif w in gd_adj:
                gs = "fix:gender-adjudication"   # 与 kaikki 不同，但进过裁决流程
            elif kg is not None:
                gs = "overwritten"
            else:
                gs = "llm-doubao"          # ⚠️ 流水线结构证据，非数据证据
            tal["gender"][gs] += 1

        if ps or ts or gs:
            plan.append((ps, ts, gs, rid))

    W = 66
    for col in ("phonetic", "translation", "gender"):
        tot = sum(tal[col].values())
        print("=" * W)
        print(f"{col}_src   （有值 {tot:,} 行）")
        print("-" * W)
        for k, v in tal[col].most_common():
            print(f"  {k:28}{v:>12,}{100*v/max(tot,1):>8.2f}%")
        print()

    ph_no = tal["phonetic"]["overwritten"] + tal["phonetic"]["unknown"]
    print(f"⭐ 音标里**无人工源背书且不可复算**的：{ph_no:,} 行 "
          f"（{100*ph_no/max(sum(tal['phonetic'].values()),1):.2f}%）—— 权威性缺口就在这里\n")

    if not a.apply:
        print("(预览。确认后 --apply 写库)")
        return

    bak = DB.with_name(f"synapse-dict-es.pre-src-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy2(DB, bak)
    print(f"已备份 → {bak.name}")
    c = sqlite3.connect(DB)
    c.executemany("UPDATE dict SET phonetic_src=?, translation_src=?, gender_src=? "
                  "WHERE id=?", plan)
    c.commit()
    n = lambda s: c.execute(s).fetchone()[0]
    NE = "SELECT COUNT(*) FROM dict WHERE TRIM(COALESCE({},''))<>''"
    print(f"已写入 {len(plan):,} 行")
    print(f"不变量 → 总行 {n('SELECT COUNT(*) FROM dict'):,} | "
          f"音标 {n(NE.format('phonetic')):,} | 译文 {n(NE.format('translation')):,} | "
          f"性别 {n(NE.format('gender')):,}")
    print(f"新列   → phonetic_src {n(NE.format('phonetic_src')):,} | "
          f"translation_src {n(NE.format('translation_src')):,} | "
          f"gender_src {n(NE.format('gender_src')):,}")
    c.close()


if __name__ == "__main__":
    main()
