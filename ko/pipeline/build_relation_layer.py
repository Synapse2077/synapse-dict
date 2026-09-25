#!/usr/bin/env python3
"""阶段 2d：建 `sense_relation` 关系层 —— 五个来源。2026-09-21。

═══ 🔴 为什么这一步是阶段 2 的必做项，不能留到以后 ═══
阶段 2a 收进来的 **5,952 个汉字词形此刻是真空白页**（既无义项、又无变形链、
又无汉字音）。它们的内容**只有一个来源**：`hangeul` form ——
`犬` → `견`、`馬` → `마`。不做这一步，2a 就是"把空白页收进库"。
⚠️ 2a 的文件头当时就写了这句话，本步是兑现它。

═══ 五个来源 ═══
    ① hangeul form          20,134   汉字条目 → 谚文读法      ← 5,952 个空白页靠它
    ② 指针义项              17,777   `犬` → "hanja form of 견"（form_of 15,768 ＋ alt_of 2,009）
    ③ relation 类 form       1,593   异体/方言/量词（判据见 `infl_tags.RELATION`）
    ④ **词级**关系字段      23,809   derived 16,668 / related 4,599 / synonyms 1,397 …
    ⑤ **义项级**关系字段    46,492   derived 19,836 / synonyms 12,877 / related 11,112 …

🔴🔴 **④⑤ 两级都要取。** kaikki 把同一类关系同时放在词级和义项级，
   而 ko 上**义项级（46,492）比词级（23,809）还多一倍** ——
   只取词级会漏掉 46,492 条。es 正是这么漏了 20,193 条，靠外锚闸才发现
   （`PLAYBOOK` 六：「关系字段两级都要取」）。

═══ `kind` 的值：用源头的字段名，不发明 ═══
`synonyms` → `synonym`（去复数），`form_of` → `hanja_form_of`（韩语上它专指汉字表记）。
🔴 不把 `derived`/`related` 合并成"相关词"这种概括 —— 那是展示层的事，
   数据层丢掉区分就再也找不回来（`[[aim-for-perfect-not-cheap]]`）。

跑（在仓库根）：
    python3 -u ko/pipeline/build_relation_layer.py
    python3 -u ko/pipeline/build_relation_layer.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sys
import collections
import json
import re
import sqlite3

import dbtool
import paths
from infl_tags import classify
from coverage import blank_pages, blank_sample

# 🔴 **一个表一个写入方**：关系层的全部来源都在这儿，不另开脚本
#    （`[[replay-scripts-undo-fixes]]`：两个写入方迟早互相撤销）。
#    阶段 4 收词后补进了后三个 —— 那 29,297 个「义项全是指针」的新词形
#    （`一世` → "X 的汉字表记"）靠它们才不是空白页。
SOURCES = [
    ("en-edition", paths.KK),
    ("ko-edition", paths.EDITION),
    ("zh-edition-simp", paths.ZH_SIMP),
    ("zh-edition-trad", paths.ZH_TRAD),
]
SRC = "en-edition"


def _op(p):
    import gzip
    p = str(p)
    return gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") \
        else open(p, encoding="utf-8")

# 源头的关系字段 → 我们的 kind（去复数，不改写含义）
REL_FIELDS = {
    "synonyms": "synonym", "antonyms": "antonym",
    "hypernyms": "hypernym", "hyponyms": "hyponym",
    "holonyms": "holonym", "meronyms": "meronym",
    "derived": "derived", "related": "related",
    "coordinate_terms": "coordinate_term", "descendants": "descendant",
    "troponyms": "troponym", "proverbs": "proverb",
}


# 🔴🔴 **韩文版的指针长得跟英文版完全不一样。**
#    英文版：`form_of: [{"word": "견"}]`  ← 结构化
#    韩文版：`tags: ["form-of"]` ＋ `form_of` **字段是 None**，
#            目标词藏在 `forms` 里那个**空 tag 的条目**（`('일인이역', None)`）
#            —— 而"空 tag 不收"正是阶段 2c 定的判据，于是 23,856 个词形成了空白页。
#
# ⇒ 判据用**两个独立信号必须一致**（pt 的 2d/2e 同一做法）：
#      信号①  gloss 散文：`일인이역의 한자 표기`（X 的汉字表记）→ 抽出 X
#      信号②  forms 里空 tag 的谚文词形
#    实测 **一致 33,275 条 / 不一致 2 条（99.994%）**。
#    不一致的两条是 gloss 不符合模式被正则误匹配（`光度` 的 gloss 是 `강도`）⇒ 跳过。
#    🔴 **只有一个信号时也不收** —— 单信号就是猜。
HANJA_POINTER = re.compile(r'^(.+?)(?:의|익)\s*(?:한자\s*표기|漢字\s*表記)')


def ko_pointer_target(se, o):
    """韩文版的「X 的汉字表记」→ X。两个信号对不上就返回 None。"""
    m = HANJA_POINTER.match((se.get("glosses") or [""])[0])
    if not m:
        return None
    x = m.group(1).strip()
    bare = [f.get("form") for f in (o.get("forms") or [])
            if not (f.get("tags") or []) and f.get("form")
            and any("가" <= c <= "힣" for c in f["form"])]
    return x if x in bare else None


def rel_kind_of_form(tags):
    """relation 类 form 的 kind。**取第一个有意义的 tag**，不把方言/异体揉成一类。"""
    ts = set(tags or [])
    if "counter" in ts:
        return "counter"
    for t in ("alternative", "variant", "dialectal", "nonstandard", "misspelling",
              "abbreviation", "contraction", "clipping", "initialism",
              "archaic", "obsolete", "dated", "rare", "uncommon"):
        if t in ts:
            return t
    # 只剩地域标记（`Gyeongsang` 这种单独出现）⇒ 方言形
    return "dialectal"


def scan(indict, inentry, sense_of):
    """→ (rows, stat)。`sense_of`: (word_id, entry_id, 该 entry 内第几条有 gloss 的义项) → sense_id"""
    seen_entry = collections.Counter()
    rows = []
    seen_key = set()                      # UNIQUE(word_id, sense_id, kind, target)
    stat = collections.Counter()

    def add(wid, sid, kind, target, tags, ref):
        target = (target or "").strip()
        if not target or target in ("-", "—"):
            stat["跳过·空 target"] += 1
            return
        k = (wid, sid, kind, target)
        if k in seen_key:
            stat["跳过·同 (词,义项,kind,目标) 重复"] += 1
            return
        seen_key.add(k)
        rows.append((wid, sid, kind, target,
                     json.dumps(sorted(tags), ensure_ascii=False) if tags else None,
                     ref.split(":")[0] if not ref.startswith("kk-ko") else "en-edition",
                     ref))
        stat["→ " + kind] += 1

    for SRC_NAME, SRC_PATH in SOURCES:
      seen_entry.clear()
      for line in _op(SRC_PATH):
        try:
            o = json.loads(line)
        except Exception:
            continue
        praw = o.get("pos") or "unknown"
        if praw == "romanization":
            continue
        w = o.get("word")
        if not w or not w.strip():
            continue
        wid = indict.get(w)
        if wid is None:
            continue
        en_ = o.get("etymology_number")
        etym = str(en_) if en_ is not None else "0"
        k = (w, praw, etym)
        seq = seen_entry[k]
        seen_entry[k] += 1
        eref = ("kk-ko:%s:%s:%s:%d" % (w, praw, etym, seq)) if SRC_NAME == "en-edition" \
            else ("%s:%s:%s:%s:%d" % (SRC_NAME, w, praw, etym, seq))
        eid = inentry.get(eref)

        # ── ① hangeul form / ③ relation 类 form ──
        for i, f in enumerate(o.get("forms") or []):
            tags = f.get("tags") or []
            try:
                c = classify(tags)
            except Exception:
                # 🔴 别的版可能有英文版没有的 tag。**不默默当成变形/关系收下** ——
                #    跳过并计数，让它显形（`infl_tags.classify` 的契约就是"不认识就抛"）。
                stat["🔴 认不出的 form tag（跳过）·" + SRC_NAME] += 1
                continue
            if c == "script" and "hangeul" in tags:
                add(wid, None, "hangeul", f.get("form"), tags, "%s#form:%d" % (eref, i))
            elif c == "relation":
                add(wid, None, rel_kind_of_form(tags), f.get("form"), tags,
                    "%s#form:%d" % (eref, i))

        # ── ④ 词级关系字段 ──
        for field, kind in REL_FIELDS.items():
            for j, it in enumerate(o.get(field) or []):
                add(wid, None, kind, (it or {}).get("word"), None,
                    "%s#rel:%s:%d" % (eref, field, j))

        # ── ② 指针义项 / ⑤ 义项级关系字段 ──
        gi = 0
        for i, se in enumerate(o.get("senses") or []):
            # 🔴 **无 gloss 的义项也要取它的关系字段。**
            #    第一版在这儿 `continue` 整条跳过 ⇒ 漏掉 **313 条**关系
            #    （derived 295 / related 18，涉及 87 个词形，`변론` 的派生词全没了）。
            #    无 gloss ⇒ 它没有出版义项 ⇒ `sense_id` 记 NULL（挂在词上），
            #    但**关系本身是真的**，不能跟着义项一起丢。
            has_gloss = bool(se.get("glosses") or [])
            sid = sense_of.get((wid, eid, gi)) if has_gloss else None
            if has_gloss:
                gi += 1
            fo = se.get("form_of") or se.get("alt_of")
            if fo:
                kind = "hanja_form_of" if se.get("form_of") else "alt_of"
                for it in fo:
                    add(wid, sid, kind, (it or {}).get("word"), None,
                        "%s#ptr:%d" % (eref, i))
            elif "form-of" in (se.get("tags") or []):
                # 韩文版的指针：结构化字段是空的，目标在散文＋空 tag form 里（见上）
                tgt = ko_pointer_target(se, o)
                if tgt:
                    add(wid, sid, "hanja_form_of", tgt, None,
                        "%s#ptr:%d" % (eref, i))
                else:
                    stat["指针两信号对不上（跳过，不猜）·" + SRC_NAME] += 1
            for field, rkind in REL_FIELDS.items():
                for j, it in enumerate(se.get(field) or []):
                    add(wid, sid, rkind, (it or {}).get("word"), None,
                        "%s#s%d:rel:%s:%d" % (eref, i, field, j))
    return rows, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    # 🔴 本层是**纯派生数据**（全部来自 dump，没有人工/付费内容）⇒ 允许幂等重建。
    #    ja 阶段 2 正是改成"清空重建"才修得动（`[[replay-scripts-undo-fixes]]`：
    #    重建之前要确认这张表**没有别的写入方** —— `sense_relation` 目前只有本脚本写）。
    ap.add_argument("--replace", action="store_true", help="先清空再建")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
    inentry = {r[1]: r[0] for r in con.execute("SELECT id, src_ref FROM entry")}
    have = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    # (word_id, entry_id, 该 entry 内第几条出版义项) → sense_id
    # 🔴 **不按 rank 反推** —— rank 是全词形连续的，而这里要的是「这个 entry 的第几条」。
    #    直接按 (entry_id, id 顺序) 取，与建义项层那个循环同构。
    sense_of = {}
    per = collections.Counter()
    for sid, wid, eid in con.execute(
            "SELECT id, word_id, entry_id FROM sense ORDER BY id"):
        sense_of[(wid, eid, per[(wid, eid)])] = sid
        per[(wid, eid)] += 1
    con.close()
    # 🔴🔴 2026-09-24 加的拦截：**这张表现在有三个写入方**，而 `--replace` 是整表 DELETE。
    #    建库这一支只认得自己那几个 `src`；另两批是
    #      · `fix_meta_gloss.py` 写的 `kind='hanja_spelling'`（51,252 条，**且它不可重跑** ——
    #        它消费的 `sense_gloss` 元描述行已经被删掉了）
    #      · `harvest_relations_from_examples.py` 写的 10,417 条
    #    整表重建会把这两批**静默抹掉**，而本脚本的 expect 只按自己的行数算，**闸不会响**。
    #    ⇒ 撞见就停，要么先想清楚怎么恢复，要么改成定向补写。
    #    （`[[replay-scripts-undo-fixes]]`：A 层搬到 B 层前先问 B 被修过吗）
    if a.replace:
        others = con2 = None
        import sqlite3 as _sq
        con2 = _sq.connect("file:%s?mode=ro" % paths.DB, uri=True)
        others = con2.execute(
            "SELECT kind, COUNT(*) FROM sense_relation "
            "WHERE kind IN ('hanja_spelling','abbreviation','sound_variant','alt_hanja') "
            "GROUP BY 1").fetchall()
        con2.close()
        if others:
            print("🔴 `sense_relation` 里有**别的写入方**的行，整表重建会抹掉它们：",
                  file=sys.stderr)
            for k, n in others:
                print("     %-18s %s 条" % (k, format(n, ",")), file=sys.stderr)
            raise SystemExit(
                "🔴 拒绝 --replace。`fix_meta_gloss.py` 那一批**不可重跑**"
                "（它消费的元描述行已经删掉了）⇒ 要补新词的关系，写定向补写脚本。")

    if have and not a.replace:
        raise SystemExit("🔴 sense_relation 非空（%d 行）—— 本步是首建。"
                         "要重建请加 --replace。" % have)

    rows, stat = scan(indict, inentry, sense_of)
    for k, v in stat.most_common():
        print("   %-40s %9s" % (k, format(v, ",")))
    print("   %-40s %9s" % ("→ sense_relation 合计", format(len(rows), ",")))
    onsense = sum(1 for r in rows if r[1] is not None)
    ptr = sum(1 for r in rows if r[2] in ("hanja_form_of", "alt_of"))
    print("   %-40s %9s" % ("其中挂在具体义项上的", format(onsense, ",")))
    print("   %-40s %9s" % ("  ├ 指针义项（form_of/alt_of）", format(ptr, ",")))
    print("   %-40s %9s" % ("  └ 🔴 义项级关系字段（只取词级就会漏掉这些）",
                            format(onsense - ptr, ",")))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("build-ko-relation",
                        expect={"#sense_relation": len(rows) - have,
                                "sense_relation.target": len(rows) - have},
                        invalidates=[]) as s:
        if have:
            s.execute("DELETE FROM sense_relation")
            s.written += have
        s.executemany(
            "INSERT INTO sense_relation (word_id, sense_id, kind, target, tags, "
            "src, src_ref) VALUES (?,?,?,?,?,?,?)", rows)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("sense_relation 行数", q("SELECT COUNT(*) FROM sense_relation"), len(rows)),
        ("word_id 都指得到",
         q("SELECT COUNT(*) FROM sense_relation r LEFT JOIN dict d ON d.id=r.word_id "
           "WHERE d.id IS NULL"), 0),
        ("sense_id 非空的都指得到",
         q("SELECT COUNT(*) FROM sense_relation r LEFT JOIN sense s ON s.id=r.sense_id "
           "WHERE r.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        ("target 都非空", q("SELECT COUNT(*) FROM sense_relation WHERE target=''"), 0),
        # 🔴🔴 **本步存在的理由**：2a 收的那 5,952 个汉字词形必须不再是空白页
        # 🔴 空白页**不在这儿断言** —— 它有「已接受基线」，而基线只该有一个地方说了算
        #    （回归闸 R1）。脚本里再写一个期望值 0，就是同一判据两个真值，
        #    结果是脚本红、闸绿，两边都对不上（`[[refactor-mindset-code-quality]]`）。
        #    这里只**报数**，判断交给闸。
        # 🔴 义项级关系必须真的拿到了（只取词级是 es 栽过的那个坑，漏 20,193 条）
        # ⚠️ 第一版这条写的是 `onsense > 词级条数`，**当场假红** ——
        #    我把**源头**的比例（义项级 46,492 > 词级 23,809）套到了**落库**数字上，
        #    而落库时"词级"那一堆还含 hangeul 20,089 与 relation form。
        #    `[[measure-landing-not-source]]`：量落点不量源头 —— 我自己又犯了一次。
        #    ⇒ 断言只问"义项级这条路有没有走通"，不假设两级的大小关系。
        ("义项级关系条数（排除指针）> 0",
         q("SELECT COUNT(*) FROM sense_relation WHERE sense_id IS NOT NULL "
           "AND kind NOT IN ('hanja_form_of','alt_of')") > 0, True),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        gs = got if isinstance(got, bool) else format(got, ",")
        ws = want if isinstance(want, bool) else format(want, ",")
        print("   %s %-26s %10s（期望 %s）" % ("✅" if good else "🔴", name, gs, ws))
    print("   ℹ️ 空白页 %s（判断交给回归闸 R1 的已接受基线）"
          % format(blank_pages(con), ","))
    print("\n■ 抽样：`犬`（汉字条目）现在有什么")
    for r in con.execute(
            "SELECT kind, target FROM sense_relation r JOIN dict d ON d.id=r.word_id "
            "WHERE d.word='犬' LIMIT 6"):
        print("     %-16s %s" % r)
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
