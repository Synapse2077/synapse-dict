#!/usr/bin/env python3
"""阶段 3b：收意语版独有的词形，连同它们的意语释义。2026-08-13。

═══ 收哪些 ═══
`verify_vs_dump.py` 报出的 it 版缺口：**11,921 个词形 / 13,089 条真意语释义**。
它们在英文版里根本没有词条，所以阶段 1 建库时不可能收到。

🔴 **fr 版的 170,968 个独有词形本轮不收**：实测 94.1%（160,874 个）既无音标也无录音，
   而它们在 fr 版里的释义是**法语**写的（按 A3 不收）⇒ 收进来就是搜得到、点开什么都没有
   的空壳。产品是划词弹窗，空壳比未收录更伤。已记账，判据和数字见 `it-CONVENTIONS`。

═══ 为什么这批可以直接提升到出版层 ═══
阶段 1.5 只提升了「意语 1 条 / 我们 1 条」，因为怕两版说的不是同一个义项。
这批词形我们**一条义项都没有** ⇒ 没有可错配的对象，**风险为零**，
每条意语释义各自成为一条 `sense`。这是最安全的一档，不是最危险的。

═══ 中文 ═══
本步只落**意语原文**，中文由 `translate_it_defs.py` 单独一步做（要花钱、要单独的闸）。

用法（在 it/ 目录下）：
    python3 pipeline/intake_it_words.py            # 干跑
    python3 pipeline/intake_it_words.py --apply
    python3 pipeline/intake_it_words.py --verify
    python3 pipeline/intake_it_words.py --mutate
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from split_case_forms import norm as wnorm   # noqa: E402  同一套 word_norm 规则

SRC = "it-edition"
AFFIX_POS = {"prefix", "suffix", "infix", "interfix", "circumfix", "combining_form"}
norm = lambda s: re.sub(r"\s+", " ", s or "").strip()


def replay(words):
    """扫意语版，取**库里没有**的词形及其真释义。→ {词形: [(src_ref, text, tags)]}"""
    out = defaultdict(list)
    occ_of = Counter()
    stat = Counter()
    with gzip.open(paths.EDITION, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e.get("lang_code") != "it":
                continue
            w0 = (e.get("word") or "").strip()
            pos = e.get("pos") or ""
            key = (w0, pos)
            occ = occ_of[key]
            occ_of[key] += 1
            if w0.lower() in words:
                continue
            affix = pos in AFFIX_POS
            for i, s in enumerate(e.get("senses") or []):
                g = norm((s.get("glosses") or [""])[0])
                if not g:
                    stat["空 gloss"] += 1
                    continue
                if (s.get("form_of") or s.get("alt_of")) and not affix:
                    stat["变形指针（不收）"] += 1
                    continue
                tags = sorted(set(s.get("tags") or []) | set(s.get("raw_tags") or []))
                out[w0].append(("kk-it:%s:%s#%d.%d" % (w0, pos, occ, i), g,
                                json.dumps(tags, ensure_ascii=False) if tags else None))
                stat["✅ 要收的释义"] += 1
    return out, stat


def gate(con, n_words=None, n_senses=None):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("🔴 新收的词形都有出版义项（不许是空壳）",
         q("SELECT count(*) FROM dict d WHERE d.id IN (SELECT word_id FROM sense_src "
           "WHERE src=? AND src_ref LIKE 'kk-it:%') AND NOT EXISTS("
           "SELECT 1 FROM sense s WHERE s.word_id=d.id)", SRC), 0),
        ("每条意语证据都有对应的出版释义（新收这批全裁决）",
         q("SELECT count(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
           "WHERE x.src=? AND NOT EXISTS(SELECT 1 FROM sense_gloss g "
           "WHERE g.sense_id=s.id AND g.lang='it' AND g.kind='definition')", SRC), 0),
        ("出版层意语释义 == 已裁决的意语证据",
         q("SELECT count(*) FROM sense_gloss WHERE lang='it' AND kind='definition'")
         - q("SELECT count(*) FROM sense_src WHERE src=? AND sense_id IS NOT NULL", SRC), 0),
        ("每个词形的 rank 连续无空洞",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("不存在两行 word 完全相同",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
        ("证据行的 word_id 与它的义项一致",
         q("SELECT count(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
           "WHERE x.word_id<>s.word_id"), 0),
        ("🔴 英文版侧的义项一条没动",
         q("SELECT count(*) FROM sense_src WHERE src='en-edition'"), 205928),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-48s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def mutate():
    import contextlib
    import io
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    cases = [
        ("新收一个空壳词形（无义项）",
         "INSERT INTO dict (word,word_norm,is_lemma) VALUES ('zzfake','zzfake',1); "
         "INSERT INTO sense_src (word_id,src,src_ref,lang,text) SELECT id,'it-edition',"
         "'kk-it:zzfake:noun#0.0','it','x' FROM dict WHERE word='zzfake'"),
        ("删掉一条出版层意语释义",
         "DELETE FROM sense_gloss WHERE lang='it' AND kind='definition' AND sense_id="
         "(SELECT max(sense_id) FROM sense_gloss WHERE lang='it' AND kind='definition')"),
        ("把一条证据挂到别的词的义项上",
         "UPDATE sense_src SET word_id=word_id+1 WHERE id=(SELECT max(id) FROM sense_src "
         "WHERE src='it-edition' AND sense_id IS NOT NULL)"),
        ("制造 rank 空洞",
         "UPDATE sense SET rank=rank+5 WHERE id=(SELECT max(id) FROM sense)"),
    ]
    caught = 0
    for name, sql in cases:
        shutil.copy(paths.DB, tmp)
        c2 = sqlite3.connect(tmp)
        try:
            c2.executescript(sql)
            c2.commit()
        except Exception as e:
            print("   ⚠️ %-34s 变异本身失败：%s" % (name, e))
            c2.close()
            continue
        c2.close()
        ro = sqlite3.connect("file:%s?mode=ro" % tmp, uri=True)
        with contextlib.redirect_stdout(io.StringIO()):
            red = not gate(ro)
        ro.close()
        caught += red
        print("   %s %-34s %s" % ("✅" if red else "🔴", name,
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
    if a.verify:
        return 0 if gate(ro) else 1
    if a.mutate:
        return 0 if mutate() else 1

    words = {w.lower() for (w,) in ro.execute("SELECT word FROM dict")}
    new, stat = replay(words)
    n_sense = sum(len(v) for v in new.values())
    for k, v in stat.most_common():
        print("   %-30s %9s" % (k, f"{v:,}"))
    print("\n■ 将新收词形 %s 个 / 意语释义 %s 条" % (f"{len(new):,}", f"{n_sense:,}"))
    print("   ⚠️ 这批**暂时没有中文**，由下一步 translate_it_defs.py 单独处理")
    if not a.apply:
        print("(未加 --apply，不写库)")
        return 0

    nid = ro.execute("SELECT max(id) FROM dict").fetchone()[0]
    sid = ro.execute("SELECT max(id) FROM sense").fetchone()[0]
    ro.close()
    d_rows, s_rows, g_rows, x_rows = [], [], [], []
    for w0 in sorted(new):
        nid += 1
        d_rows.append((nid, w0, wnorm(w0), 1))
        for rank, (ref, text, tags) in enumerate(new[w0], start=1):
            sid += 1
            s_rows.append((sid, nid, rank))
            g_rows.append((sid, "it", "definition", 0, text, SRC))
            x_rows.append((nid, sid, SRC, ref, "it", text, tags))

    with dbtool.session("intake-it-words",
                        expect={"__rows__": len(d_rows), "#sense": len(s_rows),
                                "#sense_gloss": len(g_rows), "#sense_src": len(x_rows)}) as s:
        s.executemany("INSERT INTO dict (id,word,word_norm,is_lemma) VALUES (?,?,?,?)", d_rows)
        s.executemany("INSERT INTO sense (id,word_id,rank) VALUES (?,?,?)", s_rows)
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,?,?,?,?,?)", g_rows)
        s.executemany("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags) "
                      "VALUES (?,?,?,?,?,?,?)", x_rows)
    print("\n■ 已收 %s 个词形 / %s 条义项" % (f"{len(d_rows):,}", f"{len(s_rows):,}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
