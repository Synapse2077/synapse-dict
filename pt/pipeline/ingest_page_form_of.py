#!/usr/bin/env python3
"""阶段 2d：各语言版**页面级** `form_of` 补进变形层 —— 修 5,613 个空白页。2026-08-30。

═══ 外审第二轮的一条意见，顺出来一个两层的洞 ═══
四份报告都点了 `electroencefalograma` 整条空白。全量扫：**19,404 个词形点进去一个字都没有**。
抽样一看全是变形（`junqueiras`/`baguettes`/`jutlandesa`），而回 dump 一查 ——
**源头明明白白给了它们独立页面、结构化 `form_of` 和释义**（`plural de junqueira`）。

🔴🔴 **「归变形层」和「变形层去收」之间有一条缝，东西掉进去了：**

    1.5a 义项层   读页面的 `senses`      → 「指针义项归变形层」⇒ **跳过**
    2b   变形层   读 `form_of`           → **只读英文版**，没读 pt/fr/zh 版
    2c   变形补链  读词元页的 `forms`      → 方向相反（词元→形式），覆盖不到

  三步各自都有道理，**合起来谁也没收**。这类洞不会被任何单步的闸发现 ——
  每一步的不变量都成立，缺的是"步与步之间"。

═══ 判据：不信 `form_of.word`，解析释义 ═══
🔴 **`form_of.word` 不可信**。wiktextract 在 pt 版上经常把**散文释义的片段**塞进去：

    baderna → form_of=[{word:"terceira pessoa"}]   （真实原形是 badernar）
    taxa    → form_of=[{word:"modo indicativo"}]

🔴 **「最后一个 de 之后」也不行** —— 那是形式代理，多词原形上就断：
    `anéis de Einstein` → 取到 `Einstein`，正确原形是 `anel de Einstein`。

⇒ 判据 **import `ingest_prose_inflections.PTR`**（判据只许一份）：
  `<关系词> de <原形>`，关系词只认屈折那几个，原形取**其后的全部**。

═══ 范围：只补当前**完全没有义项**的词形 ═══
⭐ 全量 5,770 条里 157 条的词形**已经有完整词条**，那些**不补**：

    estrela   11 个义项「恒星」  → 印上「estrelo 的阴性」是误导
    coisa      2 个义项「东西」  → 同上
    Filipinas               → 「Filipina 的复数」**根本是错的**（国名不是 Filipina 的复数）

  源头这么写不等于该这么展示。**判据的范围按目的定**：这一步的目的是
  「让空白页有内容」，不是「把源头的每条指针都搬进来」。157 条记账（C37）。

用法（在 pt/ 目录下）：
    python3 -u pipeline/ingest_page_form_of.py
    python3 -u pipeline/ingest_page_form_of.py --apply
"""
import argparse
import collections
import gzip
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "fixes"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from intake_edition_words import EDITIONS, norm_apos      # noqa: E402
from ingest_prose_inflections import PTR, KIND_ZH         # noqa: E402


def scan(con):
    ids = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    have = set(con.execute("SELECT word_id, base FROM inflection"))
    hassense = {r[0] for r in con.execute("SELECT DISTINCT word_id FROM sense")}
    stat, cand = collections.Counter(), {}
    for ed, (path, filt) in EDITIONS.items():
        if not path.exists():
            continue
        op = (gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz"
              else open(path, encoding="utf-8"))
        with op as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if filt and e.get("lang_code") != "pt":
                    continue
                w = norm_apos((e.get("word") or "").strip())
                if w not in ids:
                    continue
                for sn in (e.get("senses") or []):
                    if not (sn.get("form_of") or sn.get("alt_of")):
                        continue
                    g = (sn.get("glosses") or [""])[0].strip()
                    m = PTR.match(g)
                    if not m:
                        stat["释义不是「X de Y」形状"] += 1
                        continue
                    kind, base = m.group(1).lower(), m.group(2).strip()
                    lab = KIND_ZH.get(kind)
                    if not lab:
                        stat["构词（指小/指大，不收）"] += 1
                        continue
                    if base == w or base not in ids:
                        stat["原形不在库 / 自指"] += 1
                        continue
                    if (ids[w], base) in have:
                        stat["变形层已有"] += 1
                        continue
                    if ids[w] in hassense:
                        stat["该词形已有完整词条（不补，见 C37）"] += 1
                        continue
                    stat["✅ 可补（当前是空白页）"] += 1
                    cand.setdefault((ids[w], base, lab), (w, base, lab, ed, ids[w]))
        stat["扫完 " + ed] += 1
    return cand, stat


def blanks(con):
    return con.execute(
        "SELECT COUNT(*) FROM dict d "
        " WHERE NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id AND COALESCE(s.hidden,0)=0)"
        "   AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)").fetchone()[0]


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    before = blanks(con)
    cand, stat = scan(con)
    f = lambda n: format(n, ",")
    for k, v in stat.most_common():
        if not k.startswith("扫完"):
            print("   %9s  %s" % (f(v), k))
    print("\n■ 去重后可补 %s 条；当前空白页 %s" % (f(len(cand)), f(before)))
    random.seed(3)
    for v in random.sample(list(cand.values()), min(12, len(cand))):
        print("     %-26s → %-22s [%s] %s" % (v[0][:26], v[1][:22], v[2], v[3]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    ids = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    rows = [(wid, base, ids[base], lab, "page-form-of:%d:%s" % (wid, base))
            for (wid, base, lab), _v in cand.items()]
    with dbtool.session("ingest-pt-page-form-of", expect={"#inflection": len(rows)}) as s:
        s.executemany(
            "INSERT INTO inflection(word_id, base, base_id, label_zh, src, src_ref) "
            "VALUES(?,?,?,?,'pt-edition-page',?)", rows)
    after = blanks(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))
    print("\n✓ 变形层 +%s ／ 空白页 %s → %s（-%s）"
          % (f(len(rows)), f(before), f(after), f(before - after)))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
