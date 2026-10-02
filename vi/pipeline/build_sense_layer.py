#!/usr/bin/env python3
"""阶段 5a：义项两层 —— `sense_src`（证据）/ `sense`（出版）/ `sense_gloss`（文本）。2026-09-28。

═══ 🔴 **不跨版合并义项** ═══
三个版各自给一套义项，它们**没有对齐信息**。把 en 的第 2 义和 vi 的第 3 义合成一条，
需要的是判断"这两条说的是不是一个意思"—— 源头没说，我合就是编。
⇒ 一条源义项 ＝ 一条 `sense`，`sense_gloss` 带它自己的语言。
  读者会看到「英文释义 / 越南文释义 / 中文释义」各自成组，**这是诚实的分组**。
⚠️ 代价写在这儿：同一个意思会在三组里各出现一次。合并要等有对齐证据的那天
  （`[[prefer-reversible-designs]]`：分开可逆、合并不可逆）。

═══ 🔴🔴 欠账 W2 结清：中文 gloss 有 **69.2%** 只是汉字表记 ═══
判据住在 `criteria.gloss_is_just_spelling`，读者口径：
页面上方已经印着 `汉字表记 社會`，中文释义栏再印一次 `社會` 对读者是零信息。

    zh 候选释义 31,965 条
      ├ 与该词汉字表记完全相同        22,111（69.2%）  ⇒ `hidden=1`
      ├ 去括号标点后相同                 114（ 0.4%）  ⇒ `hidden=1`
      ├ 该词有表记但 gloss 不同         5,968（18.7%）  ⇒ 出版（`chân → 脚，足`）
      └ 该词没有表记                  3,772（11.8%）  ⇒ 出版（`quần vợt → 網球`）

**为什么这次能收敛**：不是判据更聪明，是**对照表变全了** ——
W2 第③版当时只有 4,810 个词形的表记，现在有 33,104 个。
拿同一条判据跑旧表得 **0.4%**（与 W2 记的 B 桶 0.3% 对上），跑新表得 **69.2%**。
⇒ 72.4% 那个「真释义上界」虚高，是因为**比不上的就被当成了真释义**。

🔴 `hidden` 的行**不删** —— 证据层永不编辑（`[[two-layer-sense-model]]`），
   `hidden_why` 记清原因，哪天判据翻案一条 UPDATE 就能放出来。

跑（在仓库根）：
    python3 -u vi/pipeline/build_sense_layer.py
    python3 -u vi/pipeline/build_sense_layer.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import gzip
import json
import sqlite3

import dbtool
import paths
from criteria import is_pointer_sense, is_not_a_gloss, gloss_is_just_spelling

SRC = [("en-edition", "en", paths.KK),
       ("vi-edition", "vi", paths.EDITION),
       ("zh-edition-trad", "zh", paths.ZH_TRAD),
       ("zh-edition-simp", "zh", paths.ZH_SIMP)]

HIDDEN_SPELLING = "same-as-han-spelling"
HIDDEN_POINTER = "pointer-not-a-definition"
HIDDEN_NOT_GLOSS = "not-a-definition（汉字对照表/模板残渣）"


def rd(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    eid = {r: i for i, r in con.execute("SELECT id, src_ref FROM entry")}
    # 🔴 §4.1 定的第三种分工欠着一条**挂靠规则**：两版都有的词只建了 en 的 entry，
    #    vi/zh 的义项得挂上去。按 (词形, 词性) 索引所有 entry。
    by_pos = collections.defaultdict(list)
    for i, w, p_ in con.execute(
            "SELECT e.id, d.word, e.pos FROM entry e JOIN dict d ON d.id=e.word_id"):
        by_pos[(w, p_)].append(i)
    spell = collections.defaultdict(set)
    for w, h in con.execute("SELECT d.word, h.han FROM han_spelling h "
                            "JOIN dict d ON d.id=h.word_id"):
        spell[w].add(h)
    for w, h in con.execute("SELECT d.word, n.nom FROM nom_spelling n "
                            "JOIN dict d ON d.id=n.word_id"):
        spell[w].add(h)
    con.close()
    print("■ dict %s 词形 ／ entry %s ／ 有汉字表记的 %s"
          % (format(len(wid), ","), format(len(eid), ","), format(len(spell), ",")))

    ev, stat = [], collections.Counter()
    for src, lang, p in SRC:
        ed = src.split("-")[0]
        for e in rd(p):
            w = (e.get("word") or "").strip()
            if w not in wid:
                continue
            pos = e.get("pos")
            etym = str(e.get("etymology_number", "0") or "0")
            # ── 挂靠：三级，**每一级都写清为什么**（`[[dont-gate-facts-on-my-uncertainty]]`）
            #   ① 同版同词性 —— 本版自己建的 entry，最准
            #   ② 跨版同词性 —— §4.1 的挂靠规则：这个词的 entry 是 en 建的，
            #      vi/zh 的义项按词性挂上去。实测**救回 19.9%**（NULL 从 35.9% 降到 12.6%）
            #   ③ 挂不上 ⇒ **NULL，不猜**。词性对不上就是对不上，
            #      硬挂到"第一条 entry"会造出 `Méjico 的阳性` 那种编造关系（es 踩过 3,890 个）
            ent_id = None
            for seq in range(0, 8):
                ref = "kk-%s:%s:%s:%s:%d" % (ed, w, pos, etym, seq)
                if ref in eid:
                    ent_id = eid[ref]
                    stat["挂靠① 同版同词性"] += 1
                    break
            if ent_id is None:
                c = by_pos.get((w, pos)) or []
                if c:
                    ent_id = c[0]
                    stat["挂靠② 跨版同词性（§4.1 的规则）"] += 1
                else:
                    stat["挂靠③ 挂不上 ⇒ NULL"] += 1
            for si, s in enumerate(e.get("senses", []) or []):
                for gi, g in enumerate(s.get("glosses") or []):
                    t = g.strip()
                    if not t:
                        continue
                    why = None
                    if is_pointer_sense(s):
                        why = HIDDEN_POINTER
                    elif is_not_a_gloss(t):
                        why = HIDDEN_NOT_GLOSS
                    elif lang == "zh" and gloss_is_just_spelling(t, spell.get(w, set())):
                        why = HIDDEN_SPELLING
                    stat[(lang, why or "出版")] += 1
                    # 🔴🔴 **主键必须唯一标定源记录**。第一版写的是
                    #    `sense:<版>:<词>:<义序>:<gloss序>` —— 漏了词性与词源号，
                    #    于是同一个词在同一版里的**不同词条**（名词/动词各一套义项）
                    #    键撞在一起，干跑时报「去重 10,106」——
                    #    那不是重复，是**被我悄悄丢掉的一万条真义项**。
                    #    `[[primary-key-is-not-enough]]`：主键保证认领得上，不保证配对对。
                    ev.append((wid[w], ent_id, lang, t, src,
                               "sense:%s:%s:%s:%s:%d:%d" % (ed, w, pos, etym, si, gi), why))

    # src_ref 去重（同一条证据在同一版里出现两次就是重复）
    seen, rows = set(), []
    for r in ev:
        if r[5] in seen:
            stat["同源重复（去重）"] += 1
            continue
        seen.add(r[5])
        rows.append(r)

    print("\n■ 证据层 %s 条（去重 %s）"
          % (format(len(rows), ","), format(stat["同源重复（去重）"], ",")))
    for lang in ("en", "vi", "zh"):
        tot = sum(v for k, v in stat.items() if isinstance(k, tuple) and k[0] == lang)
        if not tot:
            continue
        print("   %s 共 %s" % (lang, format(tot, ",")))
        for k, v in sorted(stat.items(), key=lambda x: -x[1]):
            if isinstance(k, tuple) and k[0] == lang:
                why = k[1]
                print("      %-34s %8s  %5.1f%%" % (why, format(v, ","), 100 * v / tot))

    pub = [r for r in rows if r[6] is None]
    print("\n■ 出版层：%s 条义项" % format(len(pub), ","))
    cov = collections.defaultdict(set)
    for r in pub:
        cov[r[2]].add(r[0])
    U = set().union(*cov.values()) if cov else set()
    for lang in ("en", "vi", "zh"):
        print("   %s 释义覆盖词形 %7s（%5.1f%%）"
              % (lang, format(len(cov[lang]), ","), 100 * len(cov[lang]) / len(wid)))
    print("   ⇒ 三语并集 **%s（%.1f%%）**，一条可出版释义都没有的 **%s**"
          % (format(len(U), ","), 100 * len(U) / len(wid), format(len(wid) - len(U), ",")))
    print("\n■ 义项挂到哪条 entry 上")
    for k in ("挂靠① 同版同词性", "挂靠② 跨版同词性（§4.1 的规则）", "挂靠③ 挂不上 ⇒ NULL"):
        if stat[k]:
            print("   %-32s %8s" % (k, format(stat[k], ",")))
    noentry = sum(1 for r in rows if r[1] is None)
    print("   ⚠️ 挂不到具体 entry 的证据 %s（%.1f%%）—— `entry_id` 留 NULL，**不猜**"
          % (format(noentry, ","), 100 * noentry / len(rows)))

    dbtool.sample_check([(r[3][:40], r[2], r[4], r[6] or "出版") for r in rows], 10,
                        ("释义", "语", "源", "出版/隐藏"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    ns, np_ = len(rows), len(pub)
    with dbtool.session(
            "build-vi-sense-layer",
            expect={"__rows__": 0, "#sense_src": ns, "#sense": np_, "#sense_gloss": np_},
            invalidates=["义项层建好了：阶段 6（例句/关系/量词）与阶段 7（词源桥）都依赖它"]) as s:
        for r in pub:
            s.execute("INSERT INTO sense (word_id, entry_id, rank, hidden) VALUES (?,?,0,0)",
                      (r[0], r[1]))
        sid = {}
        for i, ref in s.execute("SELECT id, word_id FROM sense"):
            pass
        # 出版层与 pub 的顺序一致 ⇒ 按插入序回取 id
        ids = [i for (i,) in s.execute("SELECT id FROM sense ORDER BY id")]
        assert len(ids) == np_, "sense 行数对不上"
        for r, i in zip(pub, ids):
            sid[r[5]] = i
        s.executemany(
            "INSERT INTO sense_gloss (sense_id, lang, text, src) VALUES (?,?,?,?)",
            [(sid[r[5]], r[2], r[3], r[4]) for r in pub])
        s.executemany(
            "INSERT INTO sense_src (word_id, entry_id, sense_id, lang, text, src, src_ref) "
            "VALUES (?,?,?,?,?,?,?)",
            [(r[0], r[1], sid.get(r[5]), r[2], r[3], r[4], r[5]) for r in rows])

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("sense_src 行数", q("SELECT COUNT(*) FROM sense_src"), ns),
        ("sense 行数", q("SELECT COUNT(*) FROM sense"), np_),
        ("sense_gloss 行数", q("SELECT COUNT(*) FROM sense_gloss"), np_),
        ("src_ref 唯一", q("SELECT COUNT(*) FROM (SELECT src_ref FROM sense_src "
                           "GROUP BY src_ref HAVING COUNT(*)>1)"), 0),
        # 🔴 证据层永不编辑：隐藏的那批**必须还在 sense_src 里**，只是 sense_id 为空
        ("隐藏的证据还在（sense_id 为空）",
         q("SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL"), ns - np_),
        ("三语之外的语言", q("SELECT COUNT(*) FROM sense_gloss WHERE lang NOT IN "
                            "('zh','vi','en')"), 0),
        ("每条 sense 都有 gloss",
         q("SELECT COUNT(*) FROM sense s LEFT JOIN sense_gloss g ON g.sense_id=s.id "
           "WHERE g.id IS NULL"), 0),
        ("每条都挂得上 dict",
         q("SELECT COUNT(*) FROM sense_src x LEFT JOIN dict d ON d.id=x.word_id "
           "WHERE d.id IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-28s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
