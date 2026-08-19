#!/usr/bin/env python3
"""阶段 5：收例句（三版 kaikki）→ `example` / `example_gloss`。2026-08-18。

═══ 判据与边界 ═══
· **只认 kaikki**（用户 2026-08-03 方针，A4）：Tatoeba / OPUS 一律不碰。
· 例句挂到**义项**上，不是挂在词上 —— 挂载依据是源头坐标，确定性对上，不猜：
  `sense_src.src_ref` 的格式**三版不一样**（en 带词源号与 seq，it/fr 不带），
  所以键统一解析成 `(版本, 词形, 词性, 词源号, 义项序)`，**不自己拼字符串**。
  实测挂得上：it 9,025 / en 5,835 / fr 735。
· 挂不上的**照收**，`sense_id` 留 NULL —— 挂在词上仍然有用（划词弹窗要的是这个词的例句）。
  挂不上的主因不是解析错，是**我们本来就没收那条义项**：
  fr 版 10,009 条属于「这个词形+词性我们一条义项都没收」（A3：法语释义不收）。

═══ 🔴 fr 版的一个坑：法语译文被塞在意语原文里 ═══
    bei      「Quanti bei regali hai ricevuto! - Tu as reçu beaucoup de beaux cadeaux !」
    attimo   「Aspetta un attimo. — Attends une minute.」
884 条这样的，且它们的 `translation` 字段是**空的**（译文没有单独给出）⇒ 无法确定性切开。
按 A3（释义只留中英意）与「错比缺更伤权威」，**这 884 条整条跳过**，记账。
⚠️ 不用「按破折号切一刀」这种形式判据 —— 意语句子本来就会用破折号，切了会毁掉真例句。

═══ 译文分两层 ═══
· `example_gloss` = **出版层**，只放中英意（A3）。en 版的英文译文进这里。
· `example.src_translation` + `src_lang` = **证据层**，放源头给的、我们不出版的语言
  （fr 版的法文译文 7,707 条）。留着是为了以后能回源核对，不展示。

用法（在 it/ 目录下）：
    python3 pipeline/ingest_examples.py            # 干跑
    python3 pipeline/ingest_examples.py --apply
    python3 pipeline/ingest_examples.py --verify
    python3 pipeline/ingest_examples.py --mutate
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool                                       # noqa: E402
import paths                                        # noqa: E402
from build_pronunciation_layer import word_index    # noqa: E402
from ipa_variants import iter_source                # noqa: E402

SOURCES = [("en-edition", paths.KK, None), ("it-edition", paths.EDITION, "it"),
           ("fr-edition", paths.KK_FR, None)]
PRIO = {"en-edition": 0, "it-edition": 1, "fr-edition": 2}
# 出版层收哪些语言的译文（A3：中 + 英 + 意）；其余语言只进证据层
PUBLISH_LANG = {"en-edition": "en", "it-edition": "it"}
EVIDENCE_LANG = {"fr-edition": "fr"}
f = lambda n: format(n, ",")


def has_foreign_tail(text, translation):
    """判据本体：这条原文里是不是把**外语译文**一起塞进来了。

    🔴 判据不是「有没有破折号」（意语句子本来就用破折号，那是形式代理，A45），
       而是「这一版给的 `translation` 字段是不是空的、而原文里出现了整段外语」。
       我们**不去猜哪一半是外语** —— 猜错就毁掉真例句 ⇒ 只要满足下面两条就整条跳过：
         ① 该版本的译文字段为空（说明译文没被单独抽出来）
         ② 原文里有 ` - ` 或 ` — ` 分隔（wiktextract 抽 fr 版时的固定形态）
       实测 884 条，全部来自 fr 版。en/it 两版一条都不命中。
    """
    if translation:
        return False
    return " - " in text or " — " in text


_META = re.compile(r"see (Citations|Thesaurus|Appendix|Wiktionary):")
_GLOSS_MARK = ("(“", "(«", "(\"")
_CITATION = re.compile(r"^\d{3,4}s?,")
_RELNOTE = re.compile(r"^\s*(\((derived|related|synonym|antonym)\)|"
                     r"(Coordinate\s+terms?|Near-synonyms?|Synonyms?|Antonyms?|"
                     r"Meronyms?|Holonyms?|Hypernyms?|Hyponyms?|Troponyms?)\s*:)", re.I)


def is_not_an_example(text, ref):
    """判据本体：wiktextract 把**不是例句的东西**塞进了 `examples[]`，认出来跳过。

    2026-08-18 翻译试跑时逮到的（模型翻出一堆莫名其妙的东西，回头才发现是原文就不对）：

      ① 元指引     `For quotations using this term, see Citations:gli.`            13 条
      ② 构词公式   `ragazzo (“boy”) + -one → ragazzone (“big boy”)`               ~470 条
                  `dare (“to give”) → darsi (“to give oneself”)`
      ③ 书目当正文 `1320, Dante Alighieri, Divine Comedy, …, page 161`（`ref` 为空） 11 条

    🔴 **判据不能是"含有 →"** —— 那会误删真句子，实测两条：
         epentesi      「Iohannes → Giovanni, ruinam → rovina sono esempi di epentesi」
         causalmente   「L'ordine temporale P→P 1 dei due eventi…」
       构词公式的真正特征是**每个词后面跟着括号里的释义**（`(“…”)` / `(«…»)`），
       那是词典元语言，不是句子 ⇒ 判据 = 有箭头 **且** 有括号释义。
    ⚠️ 代价说清楚：`veloce → velocemente` 这种没带释义的公式（约 10 条）会漏过去，
       记账不追 —— 宁可留几条没用的，也不删一条真句子（PITFALLS A4：三轮就停手）。
    """
    if _META.search(text):
        return True
    if "→" in text and any(m in text for m in _GLOSS_MARK):
        return True
    if _CITATION.match(text) and ", page " in text and not ref:
        return True
    # ④ 关系笔记与元请求 —— 2026-08-18 第二轮：**模型的弃权本身是信号**。
    #    全量翻译跑完有 101 条 `zh` 为空，逐条读发现绝大多数根本不是句子：
    #      `Coordinate term: Brianza f` / `Near-synonyms: pace, va beh` / `(derived) Lunella, …`
    #      `(please add an English translation of this quotation)`
    #    这些是 wiktextract 把「关系小节」和「编辑请求」塞进了 examples[]。
    #    判据是**行首的关系标签**，意语句子不会这么开头。
    if _RELNOTE.match(text):
        return True
    if "please add an English translation" in text:
        return True
    # ⑤ 占位符与模板残渣（it 版的 `<>`、fr 版的 `:Modèle:€xemple`）
    if text.strip() in ("<>", "<...>", "—", "-") or text.strip().startswith(":Modèle:"):
        return True
    return False


def sense_index(con):
    """(版本, 词形, 词性, 词源号, 义项序) → sense_id。**解析库里的 ref，不自己拼。**"""
    out = {}
    for src, ref, sid in con.execute(
            "SELECT src, src_ref, sense_id FROM sense_src WHERE sense_id IS NOT NULL"):
        if "#" not in ref:
            continue
        head, tail = ref.split("#", 1)
        first = tail.split(".")[0]
        if not first.isdigit():
            continue
        p = head.split(":")
        if len(p) >= 5 and p[-1].isdigit() and p[-2].isdigit():
            word, pos, etym = ":".join(p[1:-3]), p[-3], int(p[-2])
        else:
            word, pos, etym = ":".join(p[1:-1]), p[-1], 0
        out.setdefault((src, word, pos, etym, int(first)), sid)
    return out


def collect(con, verbose=True):
    """→ (行列表, 统计)。纯计算，不写库。"""
    smap = sense_index(con)
    ids, _ = word_index(con)
    id2word = {i: w for i, w in con.execute("SELECT id, word FROM dict")}
    # 义项现在挂在哪个词形上 —— 用来拦「例句挂到别的词头的义项上」
    # 🔴 源头坐标指向的义项，可能已经被我们**有意搬走**了：
    #    ① 大小写拆行时有 212 条意语证据留在了大小写不对的行上（记账本已记）
    #    ② `fixes/reroute_subentry_defs.py` 把子条目释义改挂到短语自己的词条上
    #       （`moto` 的某条义项现在属于 `moto d'acqua`）
    #    两种情况下"这条例句到底属于哪条义项"都不再确定 ⇒ **降级成挂在词上**，不硬挂。
    #    实测 9 条。宁可少一个挂载，也不要把例句配到别的词的义项下。
    sense_word = {sid: w for sid, w in con.execute(
        "SELECT s.id, d.word FROM sense s JOIN dict d ON d.id=s.word_id")}
    rows, c = {}, Counter()
    for src, path, lc in SOURCES:
        for w, d in iter_source(path, src, lc):
            wid = ids.get(w)
            if wid is None:
                c["词形不在库里"] += 1
                continue
            word = id2word[wid]          # 撇号空壳 → 合并后那一行的写法
            pos = d.get("pos") or "?"
            etym = d.get("etymology_number") or 0
            for i, s in enumerate(d.get("senses") or []):
                gloss = (s.get("glosses") or [None])[0]
                for e in (s.get("examples") or []):
                    text = (e.get("text") or "").strip()
                    if not text:
                        continue
                    c[src + "·总"] += 1
                    tr = (e.get("translation") or e.get("english") or "").strip()
                    if has_foreign_tail(text, tr):
                        c["🔴 跳过：外语译文混在原文里"] += 1
                        continue
                    if is_not_an_example(text, e.get("ref")):
                        c["🔴 跳过：根本不是例句（构词公式/元指引/书目）"] += 1
                        continue
                    key = (word, text)
                    if key in rows and PRIO[rows[key]["src"]] <= PRIO[src]:
                        c["同一句多版都有，留优先级高的那版"] += 1
                        continue
                    sid = smap.get((src, w, pos, etym, i))
                    if sid is not None and sense_word.get(sid) != word:
                        c["🔴 义项已被搬到别的词头 ⇒ 降级挂在词上"] += 1
                        sid = None
                    c[src + ("·挂得上义项" if sid else "·挂在词上")] += 1
                    rows[key] = {
                        "word": word, "sense_id": sid, "text": text,
                        "bold": json.dumps(e.get("bold_text_offsets"), ensure_ascii=False)
                                if e.get("bold_text_offsets") else None,
                        "ref": e.get("ref"), "src_gloss": gloss,
                        "src_translation": tr if src in EVIDENCE_LANG else None,
                        "src_lang": EVIDENCE_LANG.get(src) if tr else None,
                        "src": src,
                        "pub": (PUBLISH_LANG[src], tr) if (tr and src in PUBLISH_LANG) else None,
                    }
    c["落表行数"] = len(rows)
    c["带出版层译文的"] = sum(1 for r in rows.values() if r["pub"])
    c["挂上义项的"] = sum(1 for r in rows.values() if r["sense_id"])
    return list(rows.values()), c


def gate(con, anchor=None):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        # ② 不变量
        ("🔴 ② 例句的词形必须在 dict 里",
         q("SELECT count(*) FROM example e WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.word=e.word)"), 0),
        ("🔴 ② 挂的义项必须属于同一个词形",
         q("SELECT count(*) FROM example e JOIN sense s ON s.id=e.sense_id "
           "JOIN dict d ON d.id=s.word_id WHERE d.word <> e.word"), 0),
        ("🔴 ② 原文不许为空", q("SELECT count(*) FROM example WHERE trim(text)=''"), 0),
        ("🔴 ② (词形,原文) 不许重复",
         q("SELECT count(*) FROM (SELECT word,text FROM example GROUP BY word,text "
           "HAVING count(*)>1)"), 0),
        ("🔴 ② src 只有三版",
         q("SELECT count(*) FROM example WHERE src NOT IN "
           "('en-edition','it-edition','fr-edition')"), 0),
        # A3：出版层只放中英意
        ("🔴 ③ 出版层译文只有 zh/en/it",
         q("SELECT count(*) FROM example_gloss WHERE lang NOT IN ('zh','en','it')"), 0),
        ("🔴 ③ 法语译文只在证据层，没漏进出版层",
         q("SELECT count(*) FROM example_gloss g JOIN example e ON e.id=g.example_id "
           "WHERE e.src='fr-edition' AND g.lang='fr'"), 0),
        ("🔴 ③ 孤儿译文（example 没了译文还在）",
         q("SELECT count(*) FROM example_gloss g WHERE NOT EXISTS"
           "(SELECT 1 FROM example e WHERE e.id=g.example_id)"), 0),
        # 🔴 外语混入正文：这一族是**跳过**的，库里一条都不许有。
        #    ⚠️ 闸必须用**与写入同一份证据**判：写入时看的是源头的 `translation` 字段，
        #       而它落库后分了两个地方 —— 出版语言进 `example_gloss`、其余进 `src_translation`。
        #       第一版闸只看后者 ⇒ 把 85 条**带英文译文的 en 版引文**（`dovere`
        #       「Grazie! — Dovere.」）误报成"混着外语"。判据不同 = 验的不是同一件事。
        ("🔴 ④ 根本不是例句的（构词公式/元指引/书目，应全被跳过）",
         sum(1 for (tt, rr) in con.execute("SELECT text, ref FROM example")
             if is_not_an_example(tt, rr)), 0),
        ("🔴 ④ 原文里混着外语译文的（应全被跳过）",
         sum(1 for (t, tr) in con.execute(
             "SELECT e.text, COALESCE(e.src_translation,'') || COALESCE("
             "(SELECT g.text FROM example_gloss g WHERE g.example_id=e.id LIMIT 1),'') "
             "FROM example e") if has_foreign_tail(t, tr)), 0),
    ]
    if anchor is not None:
        have = {(w, t) for w, t in con.execute("SELECT word, text FROM example")}
        checks += [("🔴 ① 表里有、而三版 dump 里查不到的例句", len(have - anchor), 0)]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-46s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def anchor_set(con):
    """外锚：三版 dump 里**实际存在**的 (词形, 原文)。永不过期（锚的是外部 dump）。"""
    ids, _ = word_index(con)
    id2word = {i: w for i, w in con.execute("SELECT id, word FROM dict")}
    out = set()
    for src, path, lc in SOURCES:
        for w, d in iter_source(path, src, lc):
            wid = ids.get(w)
            if wid is None:
                continue
            for s in (d.get("senses") or []):
                for e in (s.get("examples") or []):
                    t = (e.get("text") or "").strip()
                    if t:
                        out.add((id2word[wid], t))
    return out


def mutate():
    print("═══ 变异验证 A：判据本体 ═══")
    cases = [
        ("🔴 fr 那族（有破折号且没单独给译文）要跳过",
         has_foreign_tail("Aspetta un attimo. — Attends une minute.", ""), True),
        ("🔴 译文单独给了的，破折号不算问题（可能是真例句）",
         has_foreign_tail("Aspetta un attimo — disse.", "Wait a moment"), False),
        ("普通意语句子不受影响",
         has_foreign_tail("Visto il costo contenuto di un personal computer.", ""), False),
        ("🔴 连字符不是破折号（复合词不许被判成外语）",
         has_foreign_tail("Il lecca-lecca è buono.", ""), False),
        ("构词公式要跳过",
         is_not_an_example('ragazzo (“boy”) + -one → ragazzone (“big boy”)', None), True),
        ("元指引要跳过",
         is_not_an_example("For quotations using this term, see Citations:gli.", None), True),
        ("书目当正文要跳过",
         is_not_an_example("1320, Dante Alighieri, Divine Comedy, page 161", None), True),
        ("🔴 带箭头的**真句子**不许跳过（epentesi）",
         is_not_an_example("Iohannes → Giovanni, ruinam → rovina sono esempi di epentesi", None),
         False),
        ("🔴 带箭头的**真句子**不许跳过（causalmente）",
         is_not_an_example("L’ordine temporale P→P 1 dei due eventi, causalmente connessi…", None),
         False),
        ("关系笔记要跳过", is_not_an_example("Coordinate term: Brianza f", None), True),
        ("Near-synonyms 要跳过", is_not_an_example("Near-synonyms: pace, va beh", None), True),
        ("编辑请求要跳过",
         is_not_an_example("(please add an English translation of this quotation)", None), True),
        ("🔴 括号开头的真例句不许跳过",
         is_not_an_example("(noi) vi amiamo", None), False),
        ("🔴 正常引文（有 ref）不许跳过",
         is_not_an_example("Io fui abate in San Zeno a Verona", "1310s, Dante Alighieri"), False),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-46s → %s" % ("✅" if good else "🔴", name, got))

    print("\n═══ 变异验证 B：闸能不能逮住数据被改坏（在备份副本上）═══")
    import contextlib
    import io
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    shutil.copy(paths.DB, tmp)
    muts = [
        ("把 1 条例句挂到别的词的义项上",
         "UPDATE example SET sense_id=(SELECT s.id FROM sense s JOIN dict d ON d.id=s.word_id "
         "WHERE d.word<>example.word LIMIT 1) WHERE id=(SELECT min(id) FROM example)"),
        ("塞 1 条法语译文进出版层",
         "INSERT INTO example_gloss (example_id,lang,text,src) VALUES "
         "((SELECT min(id) FROM example),'fr','bonjour','x')"),
        ("塞 1 条外语混排的原文",
         "INSERT INTO example (word,text,src) VALUES "
         "((SELECT word FROM example LIMIT 1),'Ciao. — Bonjour.','it-edition')"),
        ("造一条 (词形,原文) 重复",
         "INSERT INTO example (word,text,src) SELECT word,text,src FROM example LIMIT 1"),
        ("留一条孤儿译文",
         "DELETE FROM example WHERE id=(SELECT example_id FROM example_gloss LIMIT 1)"),
    ]
    caught = 0
    for name, sql in muts:
        c2 = sqlite3.connect(tmp)
        try:
            c2.execute(sql)
            c2.commit()
        except sqlite3.IntegrityError:
            # UNIQUE 约束自己就挡住了 = 也算逮住
            c2.close()
            shutil.copy(paths.DB, tmp)
            caught += 1
            print("   ✅ 逮住 %s（被 UNIQUE 约束直接拦下）" % name)
            continue
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            good = gate(c2)
        c2.close()
        shutil.copy(paths.DB, tmp)
        caught += (not good)
        print("   %s %s" % ("✅ 逮住" if not good else "🔴 没逮住", name))
    ok &= caught == len(muts)
    print("\n   变异验证 %s（%d/%d）" % ("通过" if ok else "🔴 有洞", caught, len(muts)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.mutate:
        ro.close()
        return 0 if mutate() else 1
    if a.verify:
        print("■ 建外锚（重扫三版 dump）", flush=True)
        return 0 if gate(ro, anchor_set(ro)) else 1

    rows, c = collect(ro)
    ro.close()
    print("\n■ 例句 %s 条" % f(len(rows)))
    for k, v in c.most_common():
        print("     %-40s %s" % (k, f(v)))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    glosses = [r for r in rows if r["pub"]]
    with dbtool.session("ingest-examples",
                        expect={"__rows__": 0, "#example": len(rows),
                                "#example_gloss": len(glosses)}) as s:
        for r in rows:
            s.execute(
                "INSERT INTO example (word,sense_id,text,bold,ref,src_gloss,"
                "src_translation,src_lang,src) VALUES (?,?,?,?,?,?,?,?,?)",
                (r["word"], r["sense_id"], r["text"], r["bold"], r["ref"], r["src_gloss"],
                 r["src_translation"], r["src_lang"], r["src"]))
            if r["pub"]:
                lang, text = r["pub"]
                s.execute("INSERT INTO example_gloss (example_id,lang,text,src) "
                          "VALUES (?,?,?,?)", (s.conn.execute(
                              "SELECT last_insert_rowid()").fetchone()[0], lang, text, r["src"]))
        s.written = len(rows) + len(glosses)
    print("\n■ 已落表 %s 条例句 / %s 条译文" % (f(len(rows)), f(len(glosses))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
