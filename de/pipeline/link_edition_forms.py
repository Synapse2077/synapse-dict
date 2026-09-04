#!/usr/bin/env python3
"""阶段 2c：收词后的变形层补链 —— 各版的 `form_of` 接进 `inflection`。de 版，2026-09-01。

═══ 这一步为什么在计划表里，而不是等它咬人 ═══
`PLAYBOOK` 四节那条 🔴🔴 是 pt 那轮的账：变形层（2b）建在收词（3）**之前**，
收进来的 35.7 万个词形**从此没人给它们连过线** ⇒ 355,605 个词形（46.2%）
既无义项也无变形链 ＝ 搜得到、点进去空白页，隔了整整两个阶段才发现。

de 把这一步一开始就绑在阶段 3 后面。收词落库当场量：
**空白页 853,164 ＝ 70.9%**（比 pt 同期还高）—— 这不是缺陷，是本步存在的理由。

═══ 🔴 de 的数据形状比 pt 好一个数量级，因此做法不同 ═══
pt 的 2c/2d/2e 补了**四步**，因为源头把 `form_of` 写成散文、而且各版写法不同
（葡语散文、法语散文、页面级、异体指针）。de 不需要：

    德语版指针义项            2,929,145
    其中带结构化 `form_of`    2,927,811  = **100.0%**
    其中带结构化语法 tags      2,916,606  =   99.6%
    `form_of` 目标直接落在库里 2,927,453  =  **99.99%**（只有 358 条落不上）

⇒ **全程确定性，零散文解析、零模型调用。**
⚠️ 这个对比本身是结论：`[[es-v3-structure-backfill]]`「照搬别的语言结构前先量这门语言
   有没有那个病」—— pt 的四步方案照搬到 de 是纯浪费。

═══ 与阶段 2b 的分工 ═══
2b 从**英文版**建了 502,019 行。本步补的是**其余各版**，主力是德语版
（它给每个变格/变位形式都建了独立页面，这正是它 92.4% 义项是指针的原因）。
去重判据：`(word_id, base, label_zh)` 三元组已存在就跳过 ——
pt 收尾单 C8 那条「`tôdas → tôda 复数` 5 行变 1 行」就是没在插入时去重的代价。

═══ 本步顺带补掉 `compose()` 的三条缺口（都是德语版数据逼出来的）═══
    perfect（单独出现）  14,440 条  → 过去分词（Partizip II）
    main-clause        161,751 条  → （主句中分离）   `setzt an` ← ansetzen
    subordinate-clause 135,790 条  → （从句中不分离） `einführen` ← einfahren
⭐ 后两条正好是英文版 `dependent` 的**两面**：德语版把分离与不分离都标了出来，
   而 `setzt an` 这类分离形式正是阶段 3 收进来的 82,650 条多词条目 ——
   不标出来，读者会以为它和 `mitfährst` 是同一种东西。

═══ 闸 ═══
① `dbtool` 的 expect 闸（`#inflection` 增量必须显式声明）。
② 不变量：孤儿 word_id 为 0 ／ `label_zh` 非空 ／ 三元组无重复 ／
   **空白页数必须真的降下来**（本步的目的，不是它的副作用）。
③ 抽样反验：随机打印新链接供人眼核。

用法（在 de/ 目录下）：
    python3 -u pipeline/link_edition_forms.py --edition de           # 干跑
    python3 -u pipeline/link_edition_forms.py --edition de --apply
    python3 -u pipeline/link_edition_forms.py --verify
"""
import argparse
import gzip
import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "probes"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from infl_compose import DERIV, compose                     # noqa: E402
from intake_edition_words import EDITIONS, clean_form, clean_head, opener   # noqa: E402

# 目标串上的尾标点：kaikki 把散文漏进了 `form_of[0].word`（`sehen,` / `hören,`）。
# 实测只有 6 条，**只剥这一种**，不发明更宽的清洗规则。
TAIL_PUNCT = ",.;:"


def clean_base(t):
    """`form_of[0].word` → 原形词形。剥尾标点，其余原样存（`base_id` 认不出就留空）。"""
    t = (t or "").strip()
    while t and t[-1] in TAIL_PUNCT:
        t = t[:-1].strip()
    return t


def scan_forms(edition, words, seen3):
    """**方向二：词元页的 `forms` 变位表 → 形式**（`PLAYBOOK` 四节那条「两条路互补」）。

    🔴 为什么必须有这一条：`scan()` 走的是**形式 → 词元**（读形式自己页面上的 `form_of`），
       而**只在别人变位表里出现、自己没有页面**的词形永远够不着 ——
       实测 2c 第一轮跑完仍有 275,927 个空白页，其中 **125,488 个 `pos='unknown'`**
       正是这一类（它们是从 `forms` 单元格收进来的，源头没给它们建页）。
    ⚠️ 单元格判据仍然 import `clean_form`（内含 `is_single_form`）——
       德语变位表把主语代词写进单元格，不挡就会灌进 `er`/`sie`。
    """
    path, need_filter = EDITIONS[edition]
    rows, stat = [], Counter()
    seq_of = Counter()
    with opener(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if need_filter and e.get("lang_code") != "de":
                continue
            base = clean_head(e.get("word"))
            if not base:
                continue
            # 🔴🔴 **只读真词元页的变位表。**
            #    德语维基给**变形页**也建变位表（列的是兄弟形式），照读会写出
            #    `Epigrammes → Epigramms 变形` —— 两个都是变格形，谁也不是原形。
            #    判据：这一页有没有**至少一条非指针义项**（有 ⇒ 它是真词元页）。
            #    pt 那轮的 2c 判据被同一件事打回过（v3 收窄成「除了指针什么都没有
            #    才算变形页」）——**同一个坑，第二门语言，抽样逮到的**。
            senses = e.get("senses") or []
            if senses and all(x.get("form_of") or "form-of" in (x.get("tags") or [])
                              for x in senses):
                stat["纯指针页（变形页的兄弟形式表，不读）"] += 1
                continue
            pos_raw = e.get("pos") or "unknown"
            k = (base, pos_raw)
            seq = seq_of[k]
            seq_of[k] += 1
            base_id = words.get(base)
            for i, fm in enumerate(e.get("forms") or []):
                x = clean_form(fm.get("form"))
                if not x:
                    continue
                wid = words.get(x)
                if wid is None:
                    stat["形式不在库里（阶段 3 按判据没收，跳过）"] += 1
                    continue
                if x == base:
                    stat["形式就是词元自己（零信息，丢）"] += 1
                    continue
                tags = [t for t in (fm.get("tags") or []) if t not in ("canonical",)]
                label = compose(tags) or "变形"
                if label == "变形":
                    stat["⚠️ 组不出语法说明，回退「变形」"] += 1
                tri = (wid, base, label)
                if tri in seen3:
                    stat["三元组已存在（去重）"] += 1
                    continue
                seen3.add(tri)
                kind = "derivation" if any(k2 in tags for k2, _ in DERIV) else "inflection"
                rows.append((
                    wid, None, kind, base, base_id, label, None,
                    json.dumps(tags, ensure_ascii=False),
                    "kk-%s-forms" % edition,
                    "kk-%s-forms:%s:%s:%d#%d" % (edition, base, pos_raw, seq, i)))
                stat["新变形链接"] += 1
    return rows, stat


def scan(edition, words, seen3):
    """→ (rows, stat)。`seen3` = 已存在的 (word_id, base, label) 三元组，边扫边长。"""
    path, need_filter = EDITIONS[edition]
    rows, stat = [], Counter()
    seq_of = Counter()
    with opener(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                stat["坏行"] += 1
                continue
            if need_filter and e.get("lang_code") != "de":
                continue
            w = clean_head(e.get("word"))
            if not w:
                continue
            wid = words.get(w)
            if wid is None:
                stat["🔴 词形不在库里（阶段 3 应该已收，查这里）"] += 1
                continue
            pos_raw = e.get("pos") or "unknown"
            k = (w, pos_raw)
            seq = seq_of[k]
            seq_of[k] += 1
            for i, s in enumerate(e.get("senses") or []):
                fo = s.get("form_of")
                if not fo:
                    continue
                base = clean_base(fo[0].get("word"))
                if not base:
                    stat["目标为空（丢）"] += 1
                    continue
                if base == w:
                    stat["目标就是自己（零信息，丢）"] += 1
                    continue
                tags = s.get("tags") or []
                label = compose(tags) or "变形"
                if label == "变形":
                    stat["⚠️ 组不出语法说明，回退「变形」"] += 1
                tri = (wid, base, label)
                if tri in seen3:
                    stat["三元组已存在（去重）"] += 1
                    continue
                seen3.add(tri)
                kind = "derivation" if any(k2 in tags for k2, _ in DERIV) else "inflection"
                rows.append((
                    wid, None, kind, base, words.get(base), label,
                    (s.get("glosses") or [""])[0],
                    json.dumps(tags, ensure_ascii=False),
                    "kk-%s" % edition,
                    "kk-%s:%s:%s:%d#%d" % (edition, w, pos_raw, seq, i)))
                stat["新变形链接"] += 1
    return rows, stat


def blank_pages(con):
    return con.execute("""
      SELECT count(*) FROM dict d
       WHERE NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)
         AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)
         AND NOT EXISTS(SELECT 1 FROM sense_relation r WHERE r.word_id=d.id)""").fetchone()[0]


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("inflection 行数 == 期望", q("SELECT count(*) FROM inflection"), expect["n"]),
        ("孤儿 inflection（word_id 不在 dict）",
         q("SELECT count(*) FROM inflection i LEFT JOIN dict d ON d.id=i.word_id "
           "WHERE d.id IS NULL"), 0),
        ("label_zh 为空", q("SELECT count(*) FROM inflection WHERE label_zh=''"), 0),
        ("🔴 (word_id, base, label_zh) 三元组重复（pt 收尾单 C8 那族）",
         q("SELECT count(*) FROM (SELECT word_id, base, label_zh FROM inflection "
           "GROUP BY 1,2,3 HAVING count(*)>1)"), 0),
        ("变形指向自己", q("SELECT count(*) FROM inflection i JOIN dict d ON d.id=i.word_id "
                     "WHERE i.base = d.word"), 0),
        # 🔴 **本步的目的写成断言**，不是靠事后看数字满不满意。
        ("🔴 空白页降到了期望值以下", blank_pages(con) <= expect["blank_max"], True),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        g = f"{got:,}" if isinstance(got, int) else str(got)
        wv = f"{want:,}" if isinstance(want, int) else str(want)
        print("   %s %-48s %10s  期望 %s" % ("✓" if good else "🔴", name, g, wv))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edition", choices=sorted(EDITIONS))
    ap.add_argument("--direction", choices=["form_of", "forms"], default="form_of",
                    help="form_of=形式页指回词元（默认）／forms=词元页的变位表指向形式")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate2(con, {"n": con.execute("SELECT count(*) FROM inflection").fetchone()[0],
                                "blank_max": blank_pages(con)}) else 1
    if not a.edition:
        ap.error("要么 --verify，要么 --edition")

    words = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    seen3 = {(w, b, l) for w, b, l in
             con.execute("SELECT word_id, base, label_zh FROM inflection")}
    before = blank_pages(con)
    n_before = con.execute("SELECT count(*) FROM inflection").fetchone()[0]
    print("■ 库内词形 %s ／ 变形层 %s 行 ／ 空白页 %s"
          % (f"{len(words):,}", f"{n_before:,}", f"{before:,}"))

    fn = scan_forms if a.direction == "forms" else scan
    rows, stat = fn(a.edition, words, seen3)
    for k, v in stat.most_common():
        print("   %-44s %10s" % (k, f"{v:,}"))
    dangling = sum(1 for r in rows if r[4] is None)
    print("\n   → 新变形链接 %s（其中原形不在库里 %s）"
          % (f"{len(rows):,}", f"{dangling:,}"))

    random.seed(11)
    id2w = {i: w for w, i in words.items()}
    print("\n── 抽样反验：随机 14 条新链接（人眼核，这一步没有自动判据）──")
    for r in random.sample(rows, min(14, len(rows))):
        print("   %-26s → %-18s %s" % (id2w[r[0]], r[3], r[5]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    con.close()
    with dbtool.session("keep-v3-2c-%s-%s" % (a.edition, a.direction),
                        expect={"#inflection": len(rows)}) as s:
        s.executemany(
            "INSERT INTO inflection (word_id,entry_id,kind,base,base_id,label_zh,"
            "desc_en,tags,src,src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    after = blank_pages(con)
    print("\n■ 空白页 %s → %s（降 %s，-%.1f%%）"
          % (f"{before:,}", f"{after:,}", f"{before - after:,}",
             100 * (before - after) / max(before, 1)))
    ok = gate2(con, {"n": n_before + len(rows), "blank_max": before})
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
