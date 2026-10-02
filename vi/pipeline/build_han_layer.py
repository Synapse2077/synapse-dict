#!/usr/bin/env python3
"""阶段 2：汉字层 —— `han_spelling`（汉越字）/ `nom_spelling`（喃字）。2026-09-28。

判据全部 import 自 `han_sources.py`，本文件一条都不重写。
源分工、W1 的验证、我自己写错的那两条判据，都写在那个文件的头部。

═══ 🔴 本步**只建 `dict` 里已有的词形** ═══
四源并集涉及 27,334 个越南语词形，而当前 `dict` 只有 30,738 个（全来自英文版）。
交集只有一部分 —— 其余要等**阶段 4 收词**把越南文版/中文版的词形收进来。

⚠️ **这不是「源头没有」，是「我们这一步还没收」**
  （`[[dont-say-source-lacks-what-we-skipped]]`）。
  本脚本会把推迟的那批**数出来并存档**，否则「推迟」就变成了「丢掉」。
  ⇒ 阶段 4 收词之后**必须重跑本脚本**，这条已写进 `invalidates`。
     pt 就是栽在这里：变形层建在收词之前，35.7 万个新收的词形**从此没人给它们连过线**。

═══ `entry_id`：能定到哪个词条就定，定不了留 NULL，**不猜** ═══
同一个拉丁词形可能同时有汉越词源和纯越词源（`đồng thanh` ＝ 銅青「铜绿」／ 同聲「异口同声」，
**两个都对，是两个词**）。所以表记天然挂 entry 而不是 word。
但四个源里只有 S1/S3 能定到具体词条，S2/S4 是词级的 ⇒ 那两个源留 NULL。

跑（在仓库根）：
    python3 -u vi/pipeline/build_han_layer.py
    python3 -u vi/pipeline/build_han_layer.py --apply
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
from criteria import is_han_headword, syllables
import han_sources as HS


def rd(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def harvest():
    """→ {(词, 汉字): {"label":…, "srcs":{src_kind…}, "entry":(pos,etym_no) 或 None}}"""
    got = collections.defaultdict(lambda: {"label": None, "srcs": set(), "entry": None})
    stat = collections.Counter()

    # ── S3 反向源：表意词头的义项自己标 hán/nôm（**唯一带权威标注的**）
    for e in rd(paths.KK):
        w = (e.get("word") or "").strip()
        if not is_han_headword(w):
            continue
        for s in e.get("senses", []) or []:
            for g in s.get("glosses") or []:
                r = HS.s3_label(g)
                if not r:
                    continue
                kind, target = r
                if len(w) != syllables(target):
                    stat["S3 丢弃·字数≠音节数"] += 1
                    continue
                k = (target, w)
                got[k]["label"] = got[k]["label"] or kind
                got[k]["srcs"].add("s3")
                stat["S3"] += 1

    # ── S1 en forms（**混装**，定性只能靠码位）＋ S5 它的反向那一半
    for e in rd(paths.KK):
        w = e["word"]
        syl = syllables(w)
        rev = is_han_headword(w)         # 词头本身就是表意文字 ⇒ 这一条是反向的
        for f in e.get("forms", []) or []:
            if not (HS.S1_TAGS & set(f.get("tags") or [])):
                continue
            form = f.get("form", "")
            if rev:
                r = HS.s5_candidate(w, form, syllables)
                if not r:
                    stat["S5 丢弃"] += 1
                    continue
                k = r
                got[k]["srcs"].add("s5")
                stat["S5"] += 1
                continue
            c = HS.s1_candidate(form, syl)
            if not c:
                stat["S1 丢弃·字数≠音节数"] += 1
                continue
            k = (w, c)
            got[k]["srcs"].add("s1")
            # S1 能定到具体词条（它就挂在某条 entry 的 forms 里）
            got[k]["entry"] = (e.get("pos"), str(e.get("etymology_number", "0") or "0"))
            stat["S1"] += 1

    # ── S4 en 词源散文：源头明说 Sino-Vietnamese
    for e in rd(paths.KK):
        t = e.get("etymology_text")
        if not t:
            continue
        w = e["word"]
        for c in HS.s4_candidates(t, syllables(w)):
            k = (w, c)
            got[k]["srcs"].add("s4")
            stat["S4"] += 1

    # ── S2 zh 版词源栏的括号表（**按空白切**，粘起来就是造假）
    for e in rd(paths.ZH_TRAD):
        w = e["word"]
        syl = syllables(w)
        for t in e.get("etymology_texts") or []:
            for c in HS.s2_candidates(w, t, syl):
                k = (w, c)
                got[k]["srcs"].add("s2")
                stat["S2"] += 1
    return got, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    # 🔴 本层是**纯派生层**（全部从 dump 重算，没有一条付费数据）⇒ 重跑＝清空再建。
    #    第一版没有这个开关，而 `invalidates` 自己写着「阶段 4 收词后必须重跑本脚本」——
    #    于是重跑必然撞 `UNIQUE`，只能手动去清表。**手动清表不留痕、不走闸门**，
    #    那正是 `[[dbtool-and-golden-tests]]` 要堵的口子。
    #    ⚠️ `[[enrich-not-rebuild]]` 说「给已含付费数据的库加字段别重建」——
    #       那条的前提是**付费数据**，本层没有，所以重建是对的；
    #       哪天本层掺进了花钱买的定性结果，这个开关就必须换成原地补列。
    ap.add_argument("--rebuild", action="store_true",
                    help="清空 han_spelling/nom_spelling 再建（纯派生层，可重算）")
    a = ap.parse_args()

    got, stat = harvest()
    print("■ 四源收割（对＝(越南语词, 汉字)）")
    for k in ("S3", "S1", "S4", "S2", "S5", "S3 丢弃·字数≠音节数", "S1 丢弃·字数≠音节数", "S5 丢弃"):
        if stat[k]:
            print("   %-24s %8s" % (k, format(stat[k], ",")))
    print("   %-24s %8s" % ("并集（去重后）", format(len(got), ",")))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    ent = {}
    for eid, wid, pos, en_ in con.execute("SELECT id, word_id, pos, etym_no FROM entry"):
        ent[(wid, pos, en_)] = eid
    con.close()

    rows_han, rows_nom = [], []
    deferred = collections.Counter()
    rulec = collections.Counter()
    for (w, han), v in sorted(got.items()):
        wid = indict.get(w)
        if wid is None:
            # 🔴 不在 dict 里 ＝ **我们这一步还没收**，不是源头没有
            deferred["、".join(sorted(v["srcs"]))] += 1
            continue
        src_kind = None
        if "s2" in v["srcs"]:
            src_kind = "zh-etym"
        elif "s4" in v["srcs"]:
            src_kind = "en-etym"
        kind, rule = HS.classify(han, label=v["label"], src_kind=src_kind)
        rulec[(kind, rule)] += 1
        eid = None
        if v["entry"]:
            eid = ent.get((wid, v["entry"][0], v["entry"][1]))
        src = "+".join(sorted(v["srcs"]))
        src_ref = "han:%s:%s:%s" % (w, han, src)
        (rows_han if kind == "han" else rows_nom).append(
            (wid, eid, han, rule, src, src_ref))

    print("\n■ 落点")
    print("   %-34s %8s" % ("本步能建（词形在 dict 里）", format(len(rows_han) + len(rows_nom), ",")))
    print("   %-34s %8s" % ("  → han_spelling", format(len(rows_han), ",")))
    print("   %-34s %8s" % ("  → nom_spelling", format(len(rows_nom), ",")))
    print("   %-34s %8s  ⇐ **推迟到阶段 4 收词之后重跑**"
          % ("推迟（词形还不在 dict 里）", format(sum(deferred.values()), ",")))
    for k, v in deferred.most_common(5):
        print("        来自 %-12s %8s" % (k, format(v, ",")))

    print("\n■ 定性依据（`rule_ver`）—— 每条的可信度写在 han_sources.RULES 里")
    tot = sum(rulec.values())
    for (kind, rule), n in sorted(rulec.items(), key=lambda x: -x[1]):
        print("   %-4s %-16s %8s  %5.1f%%" % (kind, rule, format(n, ","), 100 * n / tot))
    weak = rulec[("han", "codepoint-v1")]
    print("   🔴 其中 **han + codepoint-v1 是最弱的一档**：%s 条，实测这条判据"
          "只有 70.8%% 对 ⇒ 约 %s 条其实是喃字（W1 的残留，已进 rule_ver 可回溯）"
          % (format(weak, ","), format(round(weak * 0.292), ",")))

    dbtool.sample_check([(r[2], r[3], r[4], "han") for r in rows_han[:0] or rows_han], 6,
                        ("汉字", "判据", "源", "归到"))
    dbtool.sample_check([(r[2], r[3], r[4], "nom") for r in rows_nom], 6,
                        ("喃字", "判据", "源", "归到"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    nh, nn = len(rows_han), len(rows_nom)
    # 重跑时 `expect` 是**净增量**（可以是负数），不是总数 —— 清掉的那批要先减回去
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    oh, on = (con.execute("SELECT COUNT(*) FROM han_spelling").fetchone()[0],
              con.execute("SELECT COUNT(*) FROM nom_spelling").fetchone()[0])
    con.close()
    if (oh or on) and not a.rebuild:
        raise SystemExit(
            "🔴 han_spelling 已有 %s 行、nom_spelling %s 行 —— 本层是纯派生层，"
            "重跑要加 `--rebuild`（清空再建）。\n"
            "   直接插会撞 `UNIQUE`，而手动去清表**不留痕、不走闸门**。"
            % (format(oh, ","), format(on, ",")))
    dh, dn = nh - (oh if a.rebuild else 0), nn - (on if a.rebuild else 0)
    # 🔴 `invalidates` **必须非空**（B3）：收词会让本层的「推迟」那批变成可建的。
    with dbtool.session("build-vi-han-layer",
                        expect={"__rows__": 0, "#han_spelling": dh, "#nom_spelling": dn,
                                "han_spelling.han": dh, "han_spelling.rule_ver": dh,
                                "nom_spelling.nom": dn, "nom_spelling.rule_ver": dn},
                        invalidates=["han-layer：阶段 4 收词后必须重跑本脚本 —— "
                                     "现在有 %s 对因为词形不在 dict 里被推迟了" % format(sum(deferred.values()), ",")]) as s:
        if a.rebuild:
            s.execute("DELETE FROM han_spelling")
            s.execute("DELETE FROM nom_spelling")
        s.executemany(
            "INSERT INTO han_spelling (word_id, entry_id, han, rule_ver, src, src_ref) "
            "VALUES (?,?,?,?,?,?)", rows_han)
        s.executemany(
            "INSERT INTO nom_spelling (word_id, entry_id, nom, rule_ver, src, src_ref) "
            "VALUES (?,?,?,?,?,?)", rows_nom)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("han_spelling 行数", q("SELECT COUNT(*) FROM han_spelling"), nh),
        ("nom_spelling 行数", q("SELECT COUNT(*) FROM nom_spelling"), nn),
        ("han 全是表意文字",
         sum(1 for (h,) in con.execute("SELECT han FROM han_spelling")
             if not HS.all_ideographs(h)), 0),
        ("nom 全是表意文字",
         sum(1 for (h,) in con.execute("SELECT nom FROM nom_spelling")
             if not HS.all_ideographs(h)), 0),
        # 🔴 贯穿四源的硬约束：一个音节一个字
        ("han 字数 ＝ 音节数",
         q("SELECT COUNT(*) FROM han_spelling h JOIN dict d ON d.id=h.word_id "
           "WHERE LENGTH(h.han)<>d.syllables"), 0),
        ("nom 字数 ＝ 音节数",
         q("SELECT COUNT(*) FROM nom_spelling n JOIN dict d ON d.id=n.word_id "
           "WHERE LENGTH(n.nom)<>d.syllables"), 0),
        ("rule_ver 都在值域内",
         q("SELECT COUNT(*) FROM (SELECT rule_ver FROM han_spelling UNION ALL "
           "SELECT rule_ver FROM nom_spelling) WHERE rule_ver NOT IN (%s)"
           % ",".join("'%s'" % r for r in HS.RULES)), 0),
        # 🔴 反向断言：表意词头**没有**进 dict（用户 §4.5），所以汉字层不许指向它们
        ("汉字层没有指向表意词头",
         sum(1 for (w,) in con.execute(
             "SELECT DISTINCT d.word FROM dict d JOIN han_spelling h ON h.word_id=d.id")
             if is_han_headword(w)), 0),
        ("每条都挂得上 dict",
         q("SELECT COUNT(*) FROM han_spelling h LEFT JOIN dict d ON d.id=h.word_id "
           "WHERE d.id IS NULL"), 0),
    ]
    ok = True
    for name, got_, want in checks:
        good = got_ == want
        ok &= good
        print("   %s %-26s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got_, ","), format(want, ",")))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
