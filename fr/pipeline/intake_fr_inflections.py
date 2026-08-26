#!/usr/bin/env python3
"""阶段 3b-2：把法文版的变形指针灌进 `inflection`。2026-08-22。

3b-1 收进来的 1,661,965 个词形里 **1,233,952 是纯变形指针** —— 没有这一步，
它们就是搜得到、点开什么也没有的死行。

═══ 🔴 开工前验的那件事：`compose()` 喂不喂得动法文版 ═══
**喂不动。** 法文版的 `form_of` 义项 tags 里**只有 `form-of` 一个**，没有任何语法标签：
实测 1,940,322 条 **100% 退化成「变位形式」四个字**。
不先验就跑，会造出 194 万条写着同一句废话的数据。

语法信息在**法语 gloss 文本**里，而且是模板生成的：
    "Première personne du singulier de l’indicatif présent de encyclopédier."
    "Pluriel de page."   "Participe passé masculin singulier du verbe aimer."
⇒ `fr_infl_parse.parse()` 解析成 kaikki tags，再喂**已有的** `compose()`
   —— 中文措辞复用七月验证过的那套，与库里现有 153 种标签同源。
   实测覆盖 **99.91%**（1,811 条解析不出来，见下）。

═══ 解析不出来的 1,811 条：跳过、记账、不猜 ═══
    "Un des pluriels de larme de sirène."           不规则复数的散文说明
    "Ancienne orthographe de la troisième personne…" 旧拼写 + 变位，双重关系
    "Neutre pluriel de sexisé."                     🔴 **中性**（包容性书写），
                                                     `compose()` 的 GENDER 只有阴/阳
    "Contraction de il y a."                        缩合，不是变形
⇒ 不建 `inflection` 行。`PLAYBOOK`：**错比缺更伤权威**。

═══ 与英文版侧的关系 ═══
`inflection` 里已有 **331,377** 行来自英文版。本步是**另一个来源**，
同一个词形可能两边都给（`src` 列区分）。**不去重、不合并** ——
证据层留全，展示层挑一条是阶段 8 的事（`[[two-layer-sense-model]]` 同一个道理）。

⚠️ `desc_en` 这一列对本步存的是**法语**原文（列名是建 it 时定的，含义是"dump 原文 gloss"）。

═══ 内存 ═══
194 万行不在内存里堆 —— **边扫边分批 flush**（每 20 万条一次 executemany）。

用法（在 fr/ 目录下）：
    python3 pipeline/intake_fr_inflections.py            # 干跑（只统计，不写库）
    python3 pipeline/intake_fr_inflections.py --apply
    python3 pipeline/intake_fr_inflections.py --verify
"""
import argparse
import gzip
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from fr_infl_parse import parse   # noqa: E402
from infl_compose import compose  # noqa: E402
from intake_fr_words import norm_apos   # noqa: E402

SRC = "fr-edition"
BATCH = 200000

SQL = ("INSERT OR IGNORE INTO inflection "
       "(word_id, entry_id, base, base_id, label_zh, desc_en, tags, src, src_ref) "
       "VALUES (?,?,?,?,?,?,?,?,?)")


def run(sess, ids, eids, stat, dry):
    """扫法文版，边解析边 flush。sess=None 时只统计。"""
    buf = []
    occ_of = Counter()
    with gzip.open(paths.EDITION, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "fr":
                continue
            w = norm_apos((e.get("word") or "").strip())
            if not w:
                continue
            pos_raw = e.get("pos") or ""
            key = (w, pos_raw)
            occ = occ_of[key]
            occ_of[key] += 1
            wid = ids.get(w)
            for i, s in enumerate(e.get("senses") or []):
                fo = s.get("form_of")
                if not fo:
                    continue
                stat["form_of 义项"] += 1
                base = norm_apos((fo[0].get("word") or "").strip())
                if not base:
                    stat["🔴 base 为空（跳过）"] += 1
                    continue
                g = (s.get("glosses") or [""])[0]
                tags = parse(g)
                if tags is None:
                    stat["🔴 解析不出来（跳过、记账）"] += 1
                    continue
                lab = compose(tags)
                if not lab:
                    stat["🔴 compose 返回空（跳过）"] += 1
                    continue
                if wid is None:
                    stat["🔴 词形不在 dict（不该发生，3b-1 已全收）"] += 1
                    continue
                stat["→ inflection 行"] += 1
                if dry:
                    continue
                buf.append((wid, eids.get("kk-fr:%s:%s#%d" % (w, pos_raw, occ)),
                            base, ids.get(base), lab, g,
                            json.dumps(tags, ensure_ascii=False), SRC,
                            "kk-fr:%s:%s#%d.%d" % (w, pos_raw, occ, i)))
                if len(buf) >= BATCH:
                    sess.executemany(SQL, buf)
                    buf = []
                    print("   …已写 %s" % f'{stat["→ inflection 行"]:,}', flush=True)
    if buf and not dry:
        sess.executemany(SQL, buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(con)

    print("■ 读词形与词条索引…")
    ids = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    eids = dict(con.execute("SELECT src_ref, id FROM entry WHERE src=?", (SRC,)))
    print("   dict %s / fr-edition entry %s" % (f"{len(ids):,}", f"{len(eids):,}"))
    con.close()

    stat = Counter()
    if not a.apply:
        print("■ 干跑（只统计）…")
        run(None, ids, eids, stat, dry=True)
        for k, v in sorted(stat.items()):
            print("   %-40s %10s" % (k, f"{v:,}"))
        print("\n(未加 --apply，不写库)")
        return 0

    # 🔴 增量事先算不出来（要扫完才知道），但**不能用 None 逃生** ——
    #    先干跑一遍拿到确切数，再用它当 expect。多花一次扫描，换一个真闸。
    print("■ 第一遍：干跑取期望值…")
    run(None, ids, eids, stat, dry=True)
    want = stat["→ inflection 行"]
    for k, v in sorted(stat.items()):
        print("   %-40s %10s" % (k, f"{v:,}"))
    print("■ 第二遍：写库（期望 %s 行）…" % f"{want:,}")

    stat2 = Counter()
    with dbtool.session("keep-v3-intake-fr-infl", expect={"#inflection": want}) as s:
        run(s, ids, eids, stat2, dry=False)

    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


def verify(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("孤儿 inflection（word_id 不在 dict）",
         q("SELECT count(*) FROM inflection i LEFT JOIN dict d ON d.id=i.word_id "
           "WHERE d.id IS NULL"), 0),
        ("挂到不存在 entry 上的 inflection",
         q("SELECT count(*) FROM inflection i LEFT JOIN entry e ON e.id=i.entry_id "
           "WHERE i.entry_id IS NOT NULL AND e.id IS NULL"), 0),
        ("label_zh 为空", q("SELECT count(*) FROM inflection WHERE TRIM(label_zh)=''"), 0),
        ("🔴 label_zh 退化成「变位形式」的（本步要防的就是这个）",
         q("SELECT count(*) FROM inflection WHERE src='fr-edition' AND label_zh='变位形式'"), 0),
        ("src_ref 重复",
         q("SELECT count(*) FROM (SELECT src_ref FROM inflection GROUP BY src_ref "
           "HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %10s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    n_all = q("SELECT count(*) FROM inflection")
    n_en = con.execute("SELECT count(*) FROM inflection WHERE src=?",
                       ("en-edition",)).fetchone()[0]
    n_fr = con.execute("SELECT count(*) FROM inflection WHERE src=?", (SRC,)).fetchone()[0]
    dang = q("SELECT count(*) FROM inflection WHERE base_id IS NULL")
    dead = q("SELECT count(*) FROM dict d LEFT JOIN sense s ON s.word_id=d.id "
             "LEFT JOIN inflection i ON i.word_id=d.id "
             "WHERE s.id IS NULL AND i.id IS NULL")
    print("\n■ 落点：inflection {:,}（en {:,} / fr {:,}）；悬空原形 {:,}".format(
        n_all, n_en, n_fr, dang))
    print("   🔴 既无义项也无变形的 dict 行：{:,}".format(dead))
    print("%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
