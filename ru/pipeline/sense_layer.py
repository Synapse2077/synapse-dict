#!/usr/bin/env python3
"""阶段 5a：**义项两层** —— `sense_src`（证据）／`sense`（出版）／`sense_gloss`（文本）／`sense_tag`。
ru，2026-10-23。**不花钱**；5b（中文翻译）是另一个文件、另一次拍板。

    python3 -u ru/pipeline/sense_layer.py --dry
    python3 -u ru/pipeline/sense_layer.py
    python3 -u ru/pipeline/sense_layer.py --rebuild     # 判据改了（本层无付费数据）

判据一条都不在本文件里写 —— `criteria` §⑩（指针／出版文本／标签分桶／藏不藏）＋ §⑨ 之后的
`zh_gloss_tidy`。依据见 RU_PLAN §十二。

═══ 三条约定（照 vi，理由不同的地方写清）═══
① **不跨版合并**：一条源义项 ＝ 一条 `sense`，带它自己的语言（en/ru/zh）。
② **证据层收七份源的全部义项**，出版层只收三语（`[[gloss-three-languages]]`）；
   指针义项（「X 的某格」）只进证据层，目标进 `sense_src.pointer_target`（结构字段，不抠散文）。
③ **挂 entry 靠重算 `src_ref`**（`criteria.SrcRef`，与重音/屈折/音标层同一个函数同一个扫源顺序）。

═══ 🔴 R11 的结清：**两个数一起核，不是只看表非空** ═══
阶段 1 存档的 46.3 万条「落行语法标签」挂在 **entry** 上。实测（RU_PLAN §12.3）：
  · 72,282 个 entry 有可出版义项 ⇒ 它们的标签（`intransitive`/`reflexive`…）是**这个词的语法**，
    挂到这个 entry 的每一条出版义项上（bucket `grammar`，src 记 `entry:<源>`）
  · 343,774 个 entry 只有指针 ⇒ 它们的 `singular`/`plural` 描述的是「**这个词形是哪一格**」
    （`лук` ＝ лука́ 的复数属格），不是这个词的属性；那层信息已在指针原文与屈折层里。**有意不落。**
⇒ 本文件逐个标签核：**落下的 ＋ 有意不落的 ＝ 存档**，差一条就不写库。
"""
import argparse
import collections
import gzip
import json
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dbtool                                                   # noqa: E402
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.build import SRC, rd                              # noqa: E402

R11_ARCHIVE = paths.WORK / "stage1_grammar_rows.json"


def collect(conn, limit=None, verbose=True):
    wid = dict(conn.execute("SELECT word, id FROM dict"))
    eid = dict(conn.execute("SELECT src_ref, id FROM entry"))
    ref = criteria.SrcRef()
    ev, senses, glosses, tags = [], [], [], []
    st = {k: collections.Counter() for k in (
        "ev", "pub", "hidden", "ptr", "nogloss", "lang", "r11_landed", "r11_skipped")}
    st["orphan"] = 0
    sid = 0
    for src, p in SRC:
        t0 = time.time()
        lang = criteria.SENSE_LANG[src]
        n = 0
        for e in rd(p, limit):
            n += 1
            ok, _skip, pos = criteria.entry_accept(e)
            if not ok:
                continue
            w = e["word"]
            no, sub = criteria.etym_no_pair(e)
            sref, _seq = ref.take(src, w, pos, no, sub)
            entry_id = eid.get(sref)
            word_id = wid.get(w) or wid.get(criteria.strip_stress(w))
            if entry_id is None or word_id is None:
                st["orphan"] += 1
                continue
            _isf, ent_via = criteria.is_inflected_form(e)
            _cols, row_tags = criteria.entry_grammar(e)
            pub_ids = []
            for si, s in enumerate(e.get("senses") or []):
                text = criteria.sense_text(s.get("glosses"))
                if not text:
                    st["nogloss"][src] += 1
                    continue
                via = criteria.sense_pointer_via(s, ent_via)
                sref_s = "%s#s%d" % (sref, si)
                if via or lang not in criteria.PUBLISH_LANGS:
                    ev.append((word_id, entry_id, None, lang, text,
                               criteria.sense_pointer_target(s) if via else None, src, sref_s))
                    st["ptr" if via else "ev"][via or ("不出版·" + lang)] += 1
                    continue
                sid += 1
                why = criteria.sense_hidden_why(lang, text)
                senses.append((sid, word_id, entry_id, si, 1 if why else 0, why))
                pub_text = criteria.zh_gloss_tidy(text) if lang == "zh" else text
                glosses.append((sid, lang, pub_text, src))
                ev.append((word_id, entry_id, sid, lang, text, None, src, sref_s))
                seen = {}
                for b, v in criteria.sense_tags(s):
                    if (b, v) not in seen:
                        seen[(b, v)] = len(tags)
                        tags.append((sid, b, v, src))
                for v in row_tags:
                    # 🔴 撞车（义项自己也标了同一个值）⇒ **两个出处都留**：保留那一行、src 记成
                    #    `<源>+entry`。第一版直接跳过 ⇒ 义项闸 E9 按 `entry:` 重数时漏掉这批，
                    #    「entry 级也说过」这条出处就丢了（数据没丢，出处丢了）。
                    k = ("grammar", v)
                    if k in seen:
                        i = seen[k]
                        if not tags[i][3].endswith("+entry"):
                            tags[i] = tags[i][:3] + (tags[i][3] + "+entry",)
                    else:
                        seen[k] = len(tags)
                        tags.append((sid, "grammar", v, "entry:" + src))
                pub_ids.append(sid)
                st["pub"][src] += 1
                st["hidden"][why or "印"] += 1
                st["lang"][lang] += 1
            # R11：entry 级标签按 entry 计数（与存档的口径一致）
            for v in row_tags:
                st["r11_landed" if pub_ids else "r11_skipped"][v] += 1
        if verbose:
            print("  · %-16s %9s 行  %5.1fs" % (src, format(n, ","), time.time() - t0),
                  file=sys.stderr)
    return ev, senses, glosses, tags, st


def r11_check(st):
    """落下的 ＋ 有意不落的 ＝ 存档。→ [不一致的标签]"""
    arch = json.loads(R11_ARCHIVE.read_text("utf-8"))["tags"]
    bad = []
    for t in sorted(set(arch) | set(st["r11_landed"]) | set(st["r11_skipped"])):
        got = st["r11_landed"][t] + st["r11_skipped"][t]
        if got != arch.get(t, 0):
            bad.append("%s：落 %d ＋ 不落 %d ≠ 存档 %d" % (t, st["r11_landed"][t],
                                                     st["r11_skipped"][t], arch.get(t, 0)))
    return bad


def report(ev, senses, glosses, tags, st):
    print("\n■ 阶段 5a 义项层（判据 %s）" % criteria.RULE_VER)
    print("   证据 sense_src %s ／ 出版 sense %s ／ sense_gloss %s ／ sense_tag %s"
          % tuple(format(len(x), ",") for x in (ev, senses, glosses, tags)))
    print("   出版按源 %s" % dict(st["pub"].most_common()))
    print("   出版按语言 %s" % dict(st["lang"]))
    print("   藏不藏 %s" % dict(st["hidden"].most_common()))
    print("   指针（只进证据层）%s" % dict(st["ptr"].most_common()))
    print("   不出版的语言（只进证据层）%s" % dict(st["ev"].most_common()))
    print("   无释义的源义项（不收）%s" % dict(st["nogloss"]))
    print("   挂不上 entry/dict %d（必须是 0）" % st["orphan"])
    bt = collections.Counter(b for _s, b, _v, _src in tags)
    print("   标签按桶 %s" % dict(bt))
    print("   R11：落 %s 条 ／ 有意不落 %s 条（按 entry 计）"
          % (format(sum(st["r11_landed"].values()), ","), format(sum(st["r11_skipped"].values()), ",")))


def write(ev, senses, glosses, tags, conn, rebuild=False):
    have = conn.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
    if have and not rebuild:
        raise SystemExit("🔴 `sense` 已有 %s 行 —— 要重算就加 `--rebuild`" % format(have, ","))
    paid = conn.execute("SELECT COUNT(*) FROM sense_gloss WHERE src NOT LIKE '%-edition%'").fetchone()[0]
    if paid:
        raise SystemExit("🔴🔴 `sense_gloss` 里有 %s 条非源头（模型译文）—— **付费数据，不许 --rebuild**。"
                         "要改判据就写 --sync（vi 6e 之后的做法）" % format(paid, ","))
    q = lambda s: conn.execute(s).fetchone()[0] if rebuild else 0      # noqa: E731
    exp = {
        "#sense": len(senses) - q("SELECT COUNT(*) FROM sense"),
        "#sense_src": len(ev) - q("SELECT COUNT(*) FROM sense_src"),
        "#sense_gloss": len(glosses) - q("SELECT COUNT(*) FROM sense_gloss"),
        "#sense_tag": len(tags) - q("SELECT COUNT(*) FROM sense_tag"),
        "sense_src.pointer_target": sum(1 for r in ev if r[5]) - q(
            "SELECT COUNT(*) FROM sense_src WHERE pointer_target IS NOT NULL AND TRIM(pointer_target)<>''"),
    }
    conn.close()
    with dbtool.session("sense-layer" + ("-rebuild" if rebuild else ""), expect=exp,
                        invalidates=["sense", "sense_src", "sense_gloss", "sense_tag"]) as s:
        if rebuild:
            for t in ("sense_tag", "sense_gloss", "sense_src", "sense"):
                s.execute("DELETE FROM %s" % t)
        s.executemany("INSERT INTO sense(id,word_id,entry_id,rank,hidden,hidden_why) "
                      "VALUES (?,?,?,?,?,?)", senses)
        s.executemany("INSERT INTO sense_src(word_id,entry_id,sense_id,lang,text,pointer_target,"
                      "src,src_ref) VALUES (?,?,?,?,?,?,?,?)", ev)
        s.executemany("INSERT INTO sense_gloss(sense_id,lang,text,src) VALUES (?,?,?,?)", glosses)
        s.executemany("INSERT INTO sense_tag(sense_id,bucket,value,src) VALUES (?,?,?,?)", tags)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("■ 扫七源（义项层）……", file=sys.stderr)
    ev, senses, glosses, tags, st = collect(conn, a.limit or None)
    report(ev, senses, glosses, tags, st)
    bad = r11_check(st) if not a.limit else []
    for b in bad:
        print("   🔴 R11 对不上：" + b)
    if st["orphan"]:
        raise SystemExit("🔴 有义项挂不上 entry/dict —— SrcRef 重放与库不一致，不写库")
    if bad:
        raise SystemExit("🔴 R11 两个数对不上存档，不写库")
    if a.dry:
        print("\n(dry：没写库)")
        return 0
    if a.limit:
        raise SystemExit("🔴 `--limit` 只许和 `--dry` 一起用")
    conn.close()
    write(ev, senses, glosses, tags, sqlite3.connect(paths.DB), rebuild=a.rebuild)
    out = paths.WORK / "stage5a_sense_stats.json"
    out.write_text(json.dumps({
        "sense_src": len(ev), "sense": len(senses), "sense_gloss": len(glosses), "sense_tag": len(tags),
        "pub": dict(st["pub"]), "hidden": dict(st["hidden"]), "ptr": dict(st["ptr"]),
        "ev_only": dict(st["ev"]), "nogloss": dict(st["nogloss"]),
        "r11_landed": dict(st["r11_landed"]), "r11_skipped": dict(st["r11_skipped"]),
        "rule_ver": criteria.RULE_VER,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n■ 统计已存档 → %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
