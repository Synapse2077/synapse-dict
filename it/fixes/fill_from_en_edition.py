#!/usr/bin/env python3
"""把英文版**有真释义、我们却漏收**的那批词补上。2026-08-17。

═══ 是什么 ═══
库里有一批词头一条释义都没有。逐个回英文版 dump 查，绝大多数英文版也没有
（`fill_blind_gloss.py` 处理那批），但有 **12 个英文版写得好好的**，我们漏了：

    cretacico   adj   Cretaceous
    natel       noun  mobile phone, cellphone
    allovino    noun  Halloween
    limosino    adj   Limousin

这批**不需要模型推断**：英文原文是权威源，走的是本项目验证过的翻译通路
（[[flash-translation-validated]]，实测 bad 1–3%），与凭构词猜释义完全不是一回事。

═══ 判据 ═══
① 该词头在库里一条可见义项都没有
② 英文版 dump 里该词形有**非 form_of** 的义项（form_of 的是变形指针，不算释义）
③ 语言必须是 it（`lang_code`），大小写精确匹配

⚠️ 中文由 flash 从**英文原文**译出，`src` 记 `deepseek-v4-flash:from-en`，
   与凭空推断的 `…:blind-morph` 分开标 —— 两者可信度差一个数量级，不能混在一个来源里。

用法（在 it/ 目录下）：
    python3 fixes/fill_from_en_edition.py            # 干跑
    python3 fixes/fill_from_en_edition.py --apply
    python3 fixes/fill_from_en_edition.py --verify
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool     # noqa: E402
import ds_batch   # noqa: E402
import paths      # noqa: E402
from build import POS_MAP   # noqa: E402

WORK = paths.DATA / "work" / "it"
OUT = WORK / "en_edition_fill.jsonl"
SRC_ZH = "deepseek-v4-flash:from-en"
DUMP = paths.DATA / "dumps" / "kaikki.org-dictionary-Italian.jsonl"

SYS = """你是意大利语词典编纂助手。给你一批意大利语词条的**英文释义**，请译成简明中文。

规则：
1. 只翻译给出的英文释义，不要自己补充别的意思。
2. 中文写释义本身，不写词性说明。
3. 英文里的括号说明（如 `(elevated part of a city)`）压缩成中文括号注，可省略冗长例示。
4. 严格只返回 JSON 对象：{"标识号": {"zh": "..."}, ...}，标识号是每行的 n，原样回传。"""


def scan(con):
    """→ [(word_id, 词形, kaikki词性, [英文义项], src_ref前缀)]"""
    need = {}
    for wid, w in con.execute("""
            SELECT d.id, d.word FROM dict d
            WHERE d.is_lemma=1
              AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)
              AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id
                             AND COALESCE(s.hidden,0)=0)"""):
        need[w] = wid
    out = []
    with DUMP.open(encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("lang_code") != "it":
                continue
            w = d.get("word")
            if w not in need:
                continue
            gl = [(i, (s.get("glosses") or [""])[0]) for i, s in enumerate(d.get("senses") or [])
                  if (s.get("glosses") or [""])[0] and not s.get("form_of")]
            if gl:
                out.append((need[w], w, d.get("pos") or "noun", gl))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    left = len(scan(con))
    checks = [
        ("🔴 英文版有真释义却仍没补的", left, 0),
        ("🔴 每条本步义项都有英文原文和中文",
         q("SELECT count(*) FROM sense_gloss g WHERE g.src='%s' AND NOT EXISTS("
           "SELECT 1 FROM sense_gloss h WHERE h.sense_id=g.sense_id AND h.lang='en')"
           % SRC_ZH), 0),
        ("🔴 中文不许为空",
         q("SELECT count(*) FROM sense_gloss WHERE src='%s' "
           "AND trim(COALESCE(text,''))=''" % SRC_ZH), 0),
        # 🔴 本步的证据必须能回源：src_ref 指得回 dump 的具体下标
        ("🔴 本步证据的 src_ref 形状正确",
         q("SELECT count(*) FROM sense_src WHERE src='en-edition' AND id IN "
           "(SELECT x.id FROM sense_src x JOIN sense_gloss g ON g.sense_id=x.sense_id "
           "WHERE g.src='%s') AND src_ref NOT LIKE 'kk-en:%%#%%'" % SRC_ZH), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-42s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = scan(ro)
    print("■ 英文版有真释义、我们没补的 %d 个词，共 %d 条义项"
          % (len(rows), sum(len(g) for _, _, _, g in rows)))
    for wid, w, pos, gl in rows:
        print("   %-24s %-6s %s" % (w[:24], pos, " / ".join(t[:40] for _, t in gl[:2])))
    if not a.apply or not rows:
        ro.close()
        if not a.apply:
            print("\n(未加 --apply，不写库)")
        return 0

    flat = []          # (key, word_id, word, pos, dump下标, 英文)
    for wid, w, pos, gl in rows:
        for i, t in gl:
            flat.append(("%d_%d" % (wid, i), wid, w, pos, i, t))
    batches = [[{"n": k, "en": t} for k, _, _, _, _, t in flat]]
    meta = [[(k, k) for k, *_ in flat]]
    print("\n■ %d 条送 flash 翻译（关思考）" % len(flat))
    tok = asyncio.run(ds_batch.run(SYS, batches, meta, OUT, mode="flash",
                                   conc=2, every=1, thinking="disabled"))
    print("■ token %s" % format(tok, ","))
    zh = {}
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        if (r.get("zh") or "").strip():
            zh[r["id"]] = r["zh"].strip()
    print("■ 译回 %d / %d 条" % (len(zh), len(flat)))
    ent = {}
    for eid, wid, pos in ro.execute("SELECT id, word_id, pos FROM entry"):
        ent.setdefault(wid, eid)
    # 🔴 rank 起点必须是**已有最大 rank + 1**：这些词头没有*可见*义项，
    #    但可能有 hidden=1 的占位符义项占着 rank 1（`sense` 上有 UNIQUE(word_id, rank)）。
    #    第一版从 1 起，写库时 IntegrityError，dbtool 正确回滚。
    rank = {}
    for wid, mx in ro.execute("SELECT word_id, max(rank) FROM sense GROUP BY word_id"):
        rank[wid] = mx
    ro.close()
    todo = [x for x in flat if x[0] in zh]
    with dbtool.session("fill-from-en-edition",
                        expect={"__rows__": 0, "#sense": len(todo),
                                "#sense_src": len(todo),
                                "#sense_gloss": len(todo) * 2}) as s:
        for k, wid, w, pos, i, en in todo:
            rank[wid] = rank.get(wid, 0) + 1
            cur = s.execute("INSERT INTO sense (word_id, rank, pos, entry_id) VALUES (?,?,?,?)",
                            (wid, rank[wid], POS_MAP.get(pos, pos), ent.get(wid)))
            sid = cur.lastrowid
            s.execute("INSERT INTO sense_src (word_id, sense_id, src, src_ref, lang, text) "
                      "VALUES (?,?,'en-edition',?,'en',?)",
                      (wid, sid, "kk-en:%s:%s:0:0#0.%d" % (w, pos, i), en))
            s.execute("INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src) "
                      "VALUES (?,'en','equivalent',0,?,'en-edition')", (sid, en))
            s.execute("INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src) "
                      "VALUES (?,'zh','equivalent',0,?,?)", (sid, zh[k], SRC_ZH))
    print("■ 已补 %d 条义项" % len(todo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
