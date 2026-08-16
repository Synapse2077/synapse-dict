#!/usr/bin/env python3
"""阶段 1.5 第一段：把意语版自己写的释义灌进**证据层**。2026-08-13。

═══ 这一段只做一件事 ═══
`itwiktionary` 的意语释义 → `sense_src(src='it-edition', sense_id=NULL)`。
**不判断、不裁决、不花钱、可逆**。`sense_id` 可空、注释写着「NULL = 尚未裁决」——
表结构本来就是为这一步设计的。

🔴 **过滤只做源头自己的结构判定**（`form_of` / `alt_of`），不做我自编的文本判据。
   理由：`plurale di X` 这类指针我写了个正则能认出 2,651 条，但反向核对逮到假阴性 ——
   `ospedali psichiatrici` → "plurale di ospedale psichiatrico"（目标是多词）、
   `acque` → "plurale, vedi acqua"（`vedi` 模板）、`fero` → "…per fiero"（`per` 模板）。
   证据层收全，正则留到**提升到出版层**时再用；正则以后改好了不用重灌数据。
   这正是两层义项存在的理由。

═══ 落不进去的那批 ═══
词形不在 `dict` 里的（≈17,364 条 / 15,282 个词形）**这一步不收** ——
`sense_src.word_id` 是 NOT NULL，没有词条就没有挂载点。那是阶段 3 的收词工作。

用法（在 it/ 目录下）：
    python3 pipeline/ingest_it_edition.py            # 干跑
    python3 pipeline/ingest_it_edition.py --apply
    python3 pipeline/ingest_it_edition.py --verify   # 闸①外锚 + 闸②不变量
    python3 pipeline/ingest_it_edition.py --mutate   # 变异验证
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SRC = "it-edition"
AFFIX_POS = {"prefix", "suffix", "infix", "interfix", "circumfix", "combining_form"}


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def replay(words):
    """扫意语版 → [(word_id, src_ref, text, raw_tags)]，以及统计。

    ⚠️ 意语版**没有 `etymology_number` 字段**（它用 `etymology_texts` 复数），
       所以键里不含词源号 —— 别拿英文版的 `kk-en:<w>:<pos>:<etym>:<seq>` 去套。
       坐标 = `kk-it:<词形>:<词性>#<该键第几条JSON>.<义项下标>`，内容派生、稳定。
    """
    rows, stat = [], Counter()
    occ_of = Counter()
    for line in gzip.open(paths.EDITION, "rt", encoding="utf-8"):
        e = json.loads(line)
        if e.get("lang_code") != "it":
            continue
        stat["意语词条"] += 1
        w0 = (e.get("word") or "").strip()
        pos = e.get("pos") or ""
        key = (w0, pos)
        occ = occ_of[key]
        occ_of[key] += 1
        affix = pos in AFFIX_POS
        # 🔴 阶段 3a/3b 之后同一个小写词形可能有多行（`ZIP` / `zip`、`Angola` / `angola`、
        #    `Aster` / `aster`）⇒ **优先精确大小写**，查不到才回落小写。
        #    只用 `w0.lower()` 查会指到错的那行 —— 闸报出 184 条，且**库是对的、尺子错了**。
        wid = words.get(w0) or words.get(w0.lower())
        for i, s in enumerate(e.get("senses") or []):
            g = norm((s.get("glosses") or [""])[0])
            if not g:
                stat["空 gloss（跳过）"] += 1
                continue
            if (s.get("form_of") or s.get("alt_of")) and not affix:
                stat["变形指针·源头结构判定（跳过）"] += 1
                continue
            if wid is None:
                stat["🔴 词形不在 dict（→ 阶段 3 收词）"] += 1
                continue
            tags = sorted(set(s.get("tags") or []) | set(s.get("raw_tags") or []))
            rows.append((wid, "kk-it:%s:%s#%d.%d" % (w0, pos, occ, i), g,
                         json.dumps(tags, ensure_ascii=False) if tags else None))
            stat["✅ 落证据层"] += 1
    return rows, stat


def gate1(con, words, verbose=True):
    """闸① 外锚回核：库里 it-edition 的证据行 vs 意语版 dump 原文，双向、100%。"""
    print("\n═══ 闸① 外锚回核（vs 意语版 dump 原文，全量双向）═══")
    want = {r[1]: (r[0], r[2], r[3]) for r in replay(words)[0]}
    have = {ref: (wid, text, raw) for ref, wid, text, raw in con.execute(
        "SELECT src_ref, word_id, text, raw_tags FROM sense_src WHERE src=?", (SRC,))}
    bad = []
    for ref, v in want.items():
        if have.get(ref) != v:
            bad.append(("dump 有、库里少或不同", ref, v[1][:40], (have.get(ref) or ("", "", ""))[1][:40]))
    for ref, v in have.items():
        if want.get(ref) != v:
            bad.append(("库里有、dump 没有（凭空捏造）", ref, "", v[1][:40]))
    print("   dump 侧 %s 条 / 库侧 %s 条 / 不符 %d"
          % (f"{len(want):,}", f"{len(have):,}", len(bad)))
    for b in bad[:6]:
        print("     ✗ %s  %s\n        dump=%s\n        库  =%s" % b)
    print("   %s" % ("✅ 零不符" if not bad else "🔴 有不符"))
    return not bad


def gate2(con, n_expect=None):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    n_it = q("SELECT count(*) FROM sense_src WHERE src=?", SRC)
    checks = [
        # ⚠️ 这里原来断言「sense_id 全为 NULL」—— 那是**锚自己上一版**的断言，
        #    下一步 `promote_it_gloss.py` 一裁决它就必然红，红的是断言不是数据
        #    （`external-anchor-gates`：锚外部 dump 的永不过期，锚自己上一版的必然过期）。
        #    改成永不过期的口径：裁决**可以**发生，但只能挂到同一个词的义项上。
        ("it-edition 证据行要么未裁决，要么挂在同一个词的义项上",
         q("SELECT count(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
           "WHERE x.src=? AND x.word_id<>s.word_id", SRC), 0),
        ("it-edition 证据行的 lang 全是 it",
         q("SELECT count(*) FROM sense_src WHERE src=? AND lang<>'it'", SRC), 0),
        ("证据行的 word_id 都在 dict 里",
         q("SELECT count(*) FROM sense_src s LEFT JOIN dict d ON d.id=s.word_id "
           "WHERE s.src=? AND d.id IS NULL", SRC), 0),
        ("text 非空",
         q("SELECT count(*) FROM sense_src WHERE src=? AND (text IS NULL OR text='')", SRC), 0),
        ("src_ref 无重复",
         q("SELECT count(*) FROM (SELECT src_ref FROM sense_src GROUP BY 1 HAVING count(*)>1)"), 0),
        # 🔴 这里原来写死 198,026 / 198,049 ——「锚自己上一版」，阶段 2a 一加义项就必然红。
        #    改成结构性口径：本步只写 it-edition 的行，绝不碰 en-edition 的任何一行。
        ("🔴 en-edition 证据行都还带着它自己的 src_ref 前缀（没被本步污染）",
         q("SELECT count(*) FROM sense_src WHERE src='en-edition' AND src_ref NOT LIKE 'kk-en:%'"), 0),
        ("🔴 it-edition 的行都带 kk-it: 前缀",
         q("SELECT count(*) FROM sense_src WHERE src=? AND src_ref NOT LIKE 'kk-it:%'", SRC), 0),
        # 出版层意语释义的完整性由 `promote_it_gloss.py` 的闸①②守（那里是双向逐字节比对），
        # 这里只守「灌证据这一步自己不写出版层」：出版层的意语释义不能多于已裁决的证据。
        ("出版层意语释义 ≤ 已裁决的证据行（灌证据这步不写出版层）",
         q("SELECT count(*) FROM sense_gloss WHERE lang='it' AND kind='definition'")
         - q("SELECT count(*) FROM sense_src WHERE src=? AND sense_id IS NOT NULL", SRC), 0),
    ]
    if n_expect is not None:
        checks.insert(0, ("it-edition 证据行数 == 期望", n_it, n_expect))
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-52s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def mutate(words):
    import contextlib
    import io
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    cases = [
        ("改掉一条意语释义的一个字符",
         "UPDATE sense_src SET text=text||'x' WHERE src='%s' AND id="
         "(SELECT min(id) FROM sense_src WHERE src='%s')" % (SRC, SRC)),
        ("删掉一条意语释义",
         "DELETE FROM sense_src WHERE src='%s' AND id="
         "(SELECT min(id) FROM sense_src WHERE src='%s')" % (SRC, SRC)),
        ("把一条证据挂到出版义项上（越权裁决）",
         "UPDATE sense_src SET sense_id=1 WHERE src='%s' AND id="
         "(SELECT min(id) FROM sense_src WHERE src='%s')" % (SRC, SRC)),
        ("把一条证据的 word_id 指到别的词",
         "UPDATE sense_src SET word_id=word_id+1 WHERE src='%s' AND id="
         "(SELECT min(id) FROM sense_src WHERE src='%s')" % (SRC, SRC)),
        ("凭空多一条意语释义",
         "INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text) "
         "SELECT word_id,NULL,'%s','kk-it:fake:noun#0.0','it','falso' FROM sense_src "
         "WHERE src='%s' LIMIT 1" % (SRC, SRC)),
    ]
    caught = 0
    for name, sql in cases:
        shutil.copy(paths.DB, tmp)
        c2 = sqlite3.connect(tmp)
        c2.execute(sql)
        c2.commit()
        c2.close()
        ro = sqlite3.connect("file:%s?mode=ro" % tmp, uri=True)
        with contextlib.redirect_stdout(io.StringIO()):
            red = not (gate1(ro, words, verbose=False) and gate2(ro))
        ro.close()
        caught += red
        print("   %s %-40s %s" % ("✅" if red else "🔴", name,
                                  "闸红了（对）" if red else "闸没红 —— 这条闸是假的"))
    print("\n   变异验证 %d/%d" % (caught, len(cases)))
    return caught == len(cases)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {}
    for wid, w in ro.execute("SELECT id, word FROM dict"):
        words[w] = wid                      # 精确大小写
        words.setdefault(w.lower(), wid)    # 回落

    if a.verify:
        return 0 if (gate1(ro, words) & gate2(ro)) else 1
    if a.mutate:
        return 0 if mutate(words) else 1

    rows, stat = replay(words)
    for k, v in stat.most_common():
        print("   %-34s %9s" % (k, f"{v:,}"))
    n_words = len({r[0] for r in rows})
    print("\n■ 将灌入证据层 %s 条，落在 %s 个词形上" % (f"{len(rows):,}", f"{n_words:,}"))
    ro.close()
    if not a.apply:
        print("(未加 --apply，不写库)")
        return 0

    with dbtool.session("ingest-it-edition", expect={"#sense_src": len(rows)}) as s:
        s.executemany("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags) "
                      "VALUES (?,NULL,?,?,'it',?,?)",
                      [(w, SRC, ref, t, r) for w, ref, t, r in rows])
    print("\n■ 已灌入 %s 条意语释义证据（sense_id 全为 NULL = 尚未裁决）" % f"{len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
