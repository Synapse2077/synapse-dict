#!/usr/bin/env python3
"""阶段 1.5 第一段：把法文版自己写的释义灌进**证据层**。2026-08-22。

═══ 这一段只做一件事 ═══
法文版的法语释义 → `sense_src(src='fr-edition', sense_id=NULL)`。
**不判断、不裁决、不花钱、可逆。**
`sense_id` 可空、注释写着「NULL = 尚未裁决」—— 表结构本来就是为这一步设计的
（`[[two-layer-sense-model]]`：证据层 / 出版层两层）。

裁决（挂到哪一条出版义项上）是第二段的事，分桶已实测：
    桶①  词性唯一 ⇒ 确定性挂，不花钱
    桶②  我们没有这个词性 ⇒ 不挂，记账
    桶③  同词性多条 ⇒ 要语义对齐，**唯一花钱的一桶**

🔴 **过滤只做源头自己的结构判定**（`form_of` / `alt_of`），不做我自编的文本判据。
   理由与 it 那轮一样：正则能认出一部分指针，但反向核对必然逮到假阴性。
   证据层收全，正则留到**提升到出版层**时再用；正则以后改好了不用重灌数据。
   **这正是两层义项存在的理由。**

═══ 与阶段 3 的关系（为什么现在才做）═══
可对齐性实测（`probes/alignability.py`）当时的结论：
**72.7% 的法语释义属于我们还没收的词** ⇒ `sense_src.word_id` 是 NOT NULL，挂不上。
阶段 3 收完 166.7 万词形之后，**这 507,203 条才有落点**。
先做 1.5 就得做两遍 —— 这就是当时把阶段顺序改成 2 → 3 → 1.5 的原因。

═══ 撇号 ═══
词形要过 `norm_apos`（全库唯一约定，直撇）。**释义文本本身不动** ——
那是原文，改了就不是回源坐标能对上的东西了。

═══ 内存 ═══
边扫边分批 flush，不在内存里堆 70 万行。

用法（在 fr/ 目录下）：
    python3 pipeline/ingest_fr_edition.py            # 干跑
    python3 pipeline/ingest_fr_edition.py --apply
    python3 pipeline/ingest_fr_edition.py --verify
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from intake_fr_words import norm_apos   # noqa: E402

SRC = "fr-edition"
BATCH = 100000
SQL = ("INSERT OR IGNORE INTO sense_src "
       "(word_id, sense_id, src, src_ref, lang, text, raw_tags) VALUES (?,?,?,?,?,?,?)")


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def is_pointer(s):
    """这条 sense 是不是**指针**（指向另一个词），而不是释义。

    🔴 判据＝**源头自己的结构化字段**，不猜文本。文本判据（"看着像不像指针"）
       在 es/it 上翻过好几次车，而 `form_of`/`alt_of` 是 wiktextract 解析出来的事实。

    ⚠️ **这是唯一一份**。`pipeline/verify_vs_dump.py` 直接 import 它 ——
       外锚闸和收词器判据必须逐字一致，否则闸永远红而数据没问题
       （2026-08-25 实测：闸从 it 抄来一条"词缀豁免"，当场报 42 条假缺口，
        逐条读下来 **40 条是纯指针**（`Pluriel de -ande.`），收词器跳过是对的）。

    📋 已知代价：`belle-` 有 2 条**真定义**（`De la famille du conjoint.`）
       被源头标成了 `form_of`，一并跳过。这 2 条的**词义并没丢** ——
       英文版那侧已给出并已译成中文；丢的只是法语原文，与另外那 11.1 万条
       "有义项无法语原文"同类，归裁决那一批一起处理。
    """
    return bool(s.get("form_of") or s.get("alt_of"))


def run(sess, ids, stat, dry):
    buf = []
    occ_of = Counter()
    with gzip.open(paths.EDITION, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                stat["坏行"] += 1
                continue
            if e.get("lang_code") != "fr":
                continue
            w = norm_apos((e.get("word") or "").strip())
            if not w:
                continue
            pos_raw = e.get("pos") or ""
            occ = occ_of[(w, pos_raw)]
            occ_of[(w, pos_raw)] += 1
            wid = ids.get(w)
            for i, s in enumerate(e.get("senses") or []):
                if is_pointer(s):
                    stat["指针义项（不是释义）"] += 1
                    continue
                g = norm((s.get("glosses") or [""])[0])
                if not g:
                    stat["空 gloss"] += 1
                    continue
                stat["法语原文释义"] += 1
                if wid is None:
                    stat["🔴 词形不在 dict（阶段 3 应已全收，不该发生）"] += 1
                    continue
                stat["→ sense_src 行"] += 1
                if dry:
                    continue
                buf.append((wid, None, SRC,
                            "kk-fr:%s:%s#%d.%d" % (w, pos_raw, occ, i), "fr", g,
                            json.dumps({"tags": s.get("tags") or [],
                                        "raw_tags": s.get("raw_tags") or [],
                                        "topics": s.get("topics") or []},
                                       ensure_ascii=False)))
                if len(buf) >= BATCH:
                    sess.executemany(SQL, buf)
                    buf = []
                    print("   …已写 %s" % f'{stat["→ sense_src 行"]:,}', flush=True)
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
    ids = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    print("■ 库内词形 %s" % f"{len(ids):,}")
    con.close()

    stat = Counter()
    print("■ 第一遍：干跑取期望值…")
    run(None, ids, stat, dry=True)
    for k, v in sorted(stat.items()):
        print("   %-44s %10s" % (k, f"{v:,}"))
    want = stat["→ sense_src 行"]

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    print("■ 第二遍：写库（期望 %s 行）…" % f"{want:,}")
    with dbtool.session("keep-v3-ingest-fr-defs", expect={"#sense_src": want}) as s:
        run(s, ids, Counter(), dry=False)

    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


def verify(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    n_fr = con.execute("SELECT count(*) FROM sense_src WHERE src=?", (SRC,)).fetchone()[0]
    checks = [
        ("孤儿 sense_src（word_id 不在 dict）",
         q("SELECT count(*) FROM sense_src s LEFT JOIN dict d ON d.id=s.word_id "
           "WHERE d.id IS NULL"), 0),
        ("src_ref 重复",
         q("SELECT count(*) FROM (SELECT src_ref FROM sense_src GROUP BY src_ref "
           "HAVING count(*)>1)"), 0),
        ("🔴 fr-edition 证据的 sense_id 必须全为 NULL（本段不裁决）",
         con.execute("SELECT count(*) FROM sense_src WHERE src=? AND sense_id IS NOT NULL",
                     (SRC,)).fetchone()[0], 0),
        ("lang 不是 fr 的 fr-edition 行",
         con.execute("SELECT count(*) FROM sense_src WHERE src=? AND lang<>'fr'",
                     (SRC,)).fetchone()[0], 0),
        ("text 为空", q("SELECT count(*) FROM sense_src WHERE TRIM(text)=''"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-48s %10s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    print("\n■ sense_src 各来源：")
    for src, n in con.execute("SELECT src, count(*) FROM sense_src GROUP BY src ORDER BY 2 DESC"):
        print("   %-14s %10s" % (src, f"{n:,}"))
    # 空词条还剩多少（阶段 3 留下 434,715 个）
    dead = q("SELECT count(*) FROM dict d "
             "LEFT JOIN sense s ON s.word_id=d.id "
             "LEFT JOIN inflection i ON i.word_id=d.id "
             "LEFT JOIN sense_src x ON x.word_id=d.id "
             "WHERE s.id IS NULL AND i.id IS NULL AND x.id IS NULL")
    print("■ 🔴 既无义项、无变形、也无任何证据的 dict 行：{:,}".format(dead))
    print("%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
