#!/usr/bin/env python3
"""阶段 3a/3c：建 `pronunciation` —— IPA ＋ 发音形谚文。四版并取。2026-09-21。

═══ 落点（先量落点，不量源头）═══
    源            带 IPA 词形    落在 dict 里   覆盖率
    英文版           34,742        34,742     100.0%   ← dict 就是从它建的
    韩文版           66,858        18,738      28.0%   ← 其余 48,120 要等阶段 4 收词
    日文版           14,157         9,644      68.1%
    中文繁体          5,263         4,243      80.6%
    ────────────────────────────────────────────
    四版并集         86,690        35,530

🔴 **覆盖率要按「词元」问，不按全库问**：
      词元覆盖 **32,980 / 35,284 = 93.5%**   ← 这个数有决策价值
      全库覆盖 35,530 / 378,811 = 9.4%      ← **这个数没有**，分母里 32 万是变形形
   同 ja 的录音那一课：「够不够用按核心词覆盖问，不按全库覆盖问」。

═══ 🔴 判据 7：不许读 `sounds[].other` ═══
韩文版这个字段 52 条 **100% 是日语假名**（`無料`→`むりょー` 带东京式声调），
那是韩语汉字词顺带标注的日语读音。韩语读音的家是 `ipa` / `hangeul` / `roman` 三个字段。
⚠️ 对照 ja：日语版的 `other` 装的是声调 —— **同一个字段名在不同版本里装不同东西**。

═══ 发音形谚文怎么与 IPA 配对：**靠一个独立信号，不靠位置** ═══
`개` 的 sounds 里有两个 IPA（`[kɛ]` / `[ke̞]`）和两个发音形（`개` / `게`），
按顺序是对应的（ㅐ/ㅔ 合流的两种标法）—— 但"按顺序"本身是**位置推断**，
而位置推断正是 ja 的 `infl_table` 栽过的地方。

⇒ 找了一个独立信号来验：**长音符 `ː` 两边必须一致**。
   `[kɛ(ː)]` 带 (ː)，那么配对的发音形 `개(ː)` 也必须带 —— 这与顺序无关，是内容。
   实测 **99,333 对里一致 99,333 对＝100.00%，零例外**。
   ⇒ 判据成立：**IPA 个数与发音形个数相等时按顺序配对**（68,292 个词形），
     个数不等的 **2,724 个词形留空并落账**（`(2,1)` 1,576／`(4,2)` 387／`(3,2)` 189…）。
   （这正是 pt 的 2d/2e 那条做法：两个独立信号一致才收。）

═══ `notation`：韩语 98.6% 是窄式，这一列**必须真的用起来** ═══
    英文版  narrow 49,285 ／ phonemic 36
    韩文版  narrow 104,311 ／ bare 1,514 ／ phonemic 8
存储**裸串**（八语种统一约定），展示层读 `notation` 决定加 `[ ]` 还是 `/ /`。
🔴 给窄式记音套音位定界符是**记法错误**，不是风格问题。

═══ `src` 存**所有**给出这个读音的版本，`+` 连接 ═══
`PLAYBOOK` 3.1：「用本语种版给库内音标**背书**（不改值，只记谁也这么写）」。
四版对同一个 (词形, IPA) 给出相同值时，不是丢掉三份，而是记成
`en-edition+ko-edition` —— **背书数就是 `src` 里的来源数**，可查询。
🔴 只留一个来源等于把"三版都这么写"和"只有一版这么写"抹成一样，
   而那正是阶段 3.2「修音标的唯一判据是回权威源」要用的证据。

跑（在仓库根）：
    python3 -u ko/pipeline/build_pronunciation.py
    python3 -u ko/pipeline/build_pronunciation.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sys
import collections
import gzip
import json
import sqlite3

import dbtool
import paths

# (来源名, 路径, 是不是建库那一版)。建库版能把读音定到具体 entry，别的版只能定到词形。
SOURCES = [
    ("en-edition", paths.KK, True),
    ("ko-edition", paths.EDITION, False),
    ("ja-edition", paths.JA_EDITION, False),
    ("zh-edition-trad", paths.ZH_TRAD, False),
]


def op(p):
    p = str(p)
    return gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") \
        else open(p, encoding="utf-8")


def norm_ipa(v):
    """→ (裸串, notation)。**裸存**，定界符只用来判 notation，不进值。"""
    v = (v or "").strip()
    if v.startswith("[") and v.endswith("]"):
        return v[1:-1].strip(), "narrow"
    if v.startswith("/") and v.endswith("/"):
        return v[1:-1].strip(), "phonemic"
    # 🔴 **源头写漏了一边的定界符**：`대기안정지수` 的值是 `[tɛː.gi.an.ɟəŋ.ɟi.su`
    #    （有左括号没右括号）。第一版判据要求"两边都有"，于是左括号原样留在了库里，
    #    页面上会显示 `[[tɛː…]`。1 条，闸（R10）逮到的。
    #    ⇒ 单边也认，按有的那一边定 notation。
    #    这是 `[[source-typo-fix-ours-not-quote]]` 的情形：**源头本身写错，
    #    改我们的出版文本**（`pronunciation` 是出版层），证据层一个字不动。
    if v.startswith("[") or v.endswith("]"):
        return v.strip("[]").strip(), "narrow"
    if v.startswith("/") or v.endswith("/"):
        return v.strip("/").strip(), "phonemic"
    # 没有定界符 —— 韩文版有 1,514 条。**不猜**它是哪种记法：
    # 记 `bare`，让展示层知道"源头没说"，而不是替源头做决定。
    return v, "bare"


def pick_notation(ns):
    """几版记法不同时落哪一个。**判据不是偏好，是哪一边带信息**：
    韩语 98.6% 的标注是窄式音值（`[ik̚t͈a̠]`，带音变的实际音值），
    日文版把同一个音值写成 `/…/` 是它的排版习惯，不是它真给了音位式。

    🔴 2026-09-24 抽成函数：外锚闸（`verify_layers_vs_dump.py`）要按同一条规则
       从源头还原期望值。**闸重抄一份判据，报的就是它自己的 bug**
       （那道闸第一版把 `notation` 放进身份键、比这儿细了一档，当场报 7,163 条假缺）。
    """
    return ("narrow" if "narrow" in ns else
            "phonemic" if "phonemic" in ns else "bare")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--replace", action="store_true", help="先清空再建（本层是纯派生数据）")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
    inentry = {r[1]: r[0] for r in con.execute("SELECT id, src_ref FROM entry")}
    lemma = {r[0] for r in con.execute("SELECT id FROM dict WHERE is_lemma=1")}
    have = con.execute("SELECT COUNT(*) FROM pronunciation").fetchone()[0]
    con.close()
    # 🔴 2026-09-24：`--replace` 是**整表 DELETE**，会连 `src='g2p'` 那 18 万行一起删。
    #    那批是 `fill_g2p_pronunciation.py` 写的（本脚本不认识它），而它**可以重跑**
    #    （规则集有行为指纹，重跑得到同样的行）⇒ 不拦，但**必须说出来**并给出下一条命令。
    #    ⚠️ 与关系层不同：那边的 `hanja_spelling` **不可重跑**，所以那边是拦、这边是提醒。
    if a.replace:
        import sqlite3 as _sq
        _c = _sq.connect("file:%s?mode=ro" % paths.DB, uri=True)
        _n = _c.execute("SELECT COUNT(*) FROM pronunciation WHERE src='g2p'").fetchone()[0]
        _c.close()
        if _n:
            print("⚠️ `--replace` 会一并删掉 %s 行 `src='g2p'` 的规则读音。"
                  % format(_n, ","), file=sys.stderr)
            print("   它们可以重跑（规则集有行为指纹）⇒ **本步做完必须接着跑**：",
                  file=sys.stderr)
            print("   python3 -u ko/pipeline/fill_g2p_pronunciation.py --rebuild --apply",
                  file=sys.stderr)

    if have and not a.replace:
        raise SystemExit("🔴 pronunciation 非空（%d 行）—— 本步是首建。"
                         "要重建请加 --replace。" % have)

    # key = (word_id, entry_id, ipa, notation) → {srcs:set, phon:str, tags, ref}
    acc = {}
    stat = collections.Counter()
    unpaired = []
    for src, path, is_base in SOURCES:
        seen_entry = collections.Counter()
        for line in op(path):
            try:
                d = json.loads(line)
            except Exception:
                continue
            w = d.get("word")
            if not w or not w.strip():
                continue
            wid = indict.get(w)
            if wid is None:
                stat["跳过·词形不在 dict 里（等阶段 4 收词）·" + src] += 1
                continue
            praw = d.get("pos")
            eid = None
            if is_base:
                en_ = d.get("etymology_number")
                etym = str(en_) if en_ is not None else "0"
                k = (w, praw, etym)
                seq = seen_entry[k]
                seen_entry[k] += 1
                eid = inentry.get("kk-ko:%s:%s:%s:%d" % (w, praw, etym, seq))
            ss = d.get("sounds") or []
            # 🔴 只读 ipa / hangeul(phonetic)，**不读 `other`**（判据 7）
            ipas = [s for s in ss if s.get("ipa")]
            phons = [s for s in ss if "phonetic" in (s.get("tags") or [])
                     and s.get("hangeul")]
            pairable = len(ipas) == len(phons) and ipas
            if ipas and not pairable and phons:
                unpaired.append((w, src, len(ipas), len(phons)))
                stat["发音形配不上（个数不等）·" + src] += 1
            for i, s in enumerate(ipas):
                ipa, notation = norm_ipa(s["ipa"])
                if not ipa:
                    continue
                phon = phons[i]["hangeul"] if pairable else None
                # 🔴🔴 **背书的判据是 (词形, 读音)，不是 (词形, entry, 读音, 记法)。**
                #    第一版把 `entry_id` 和 `notation` 放进了聚合键，后果是
                #    `읽다` 的同一个读音 `ik̚t͈a̠` **存了 3 遍**：
                #        en-edition  entry_id=4016  narrow     ← 建库版能定到 entry
                #        ko-edition  entry_id=NULL  narrow     ← 跨版定不到 ⇒ 永远碰不到一起
                #        ja-edition  entry_id=NULL  phonemic   ← 日文版用 /…/ 标同一个音值
                #    ⇒ **跨版背书整个失效**（实测只有 ko+zh 这一对发生过，因为它俩都是 NULL），
                #      而背书正是 `PLAYBOOK` 3.1 的核心：「用本语种版给库内音标背书」。
                #    "谁也这么写"问的是**读音**，与它挂在哪个 entry、源头用什么定界符无关。
                key = (wid, ipa)
                cur = acc.get(key)
                if cur is None:
                    acc[key] = {"srcs": {src}, "phon": phon,
                                "eid": eid, "notations": {notation},
                                "tags": sorted(s.get("tags") or []),
                                "pos": praw, "ref": "%s:%s:%d" % (src, w, i)}
                    stat["→ " + src] += 1
                else:
                    cur["srcs"].add(src)          # ⭐ 背书：不丢掉"谁也这么写"
                    cur["notations"].add(notation)
                    stat["背书（另一版给出相同读音）·" + src] += 1
                    if phon and not cur["phon"]:
                        cur["phon"] = phon
                    # entry 归属：**建库版说了算**（只有它的 pos/etym 与我们的 entry 同源）
                    if eid and not cur["eid"]:
                        cur["eid"] = eid

    rows = []
    notation_conflict = 0
    for (wid, ipa), v in acc.items():
        eid = v["eid"]
        # notation：几版记法不同时**取窄式**。判据不是偏好 ——
        # 韩语 98.6% 的标注是窄式音值（`[ik̚t͈a̠]` 这种带音变的实际音值），
        # 日文版把同一个音值写成 `/…/` 是它的排版习惯，不是它真的给了音位式。
        # 🔴 这一步**改了源头的记法标签**，所以要报出来、落账，不能静默。
        ns = v["notations"]
        if len(ns) > 1:
            notation_conflict += 1
        notation = pick_notation(ns)
        rows.append((wid, eid, ipa, notation, v["phon"],
                     ",".join(t for t in v["tags"] if t in
                              ("SK-Standard", "Seoul", "South-Korea",
                               "North-Korea")) or None,
                     json.dumps(v["tags"], ensure_ascii=False) if v["tags"] else None,
                     v["pos"], 0, "+".join(sorted(v["srcs"])), v["ref"]))

    for k, v in sorted(stat.items()):
        print("   %-46s %9s" % (k, format(v, ",")))
    print("   %-46s %9s" % ("→ pronunciation 合计", format(len(rows), ",")))
    nphon = sum(1 for r in rows if r[4])
    print("   %-46s %9s" % ("  └ 带发音形谚文", format(nphon, ",")))
    print("   %-46s %9s" % ("几版记法不同 ⇒ 取窄式", format(notation_conflict, ",")))
    multi = sum(1 for r in rows if "+" in r[9])
    print("   %-46s %9s" % ("  └ **有跨版背书**（≥2 版给出相同读音）", format(multi, ",")))
    covered = len({r[0] for r in rows})
    covlem = len({r[0] for r in rows} & lemma)
    print("   %-46s %9s" % ("覆盖词形", format(covered, ",")))
    print("   🔴 %-44s %8.1f%%" % ("**词元**覆盖（有决策价值的那个数）",
                                   100 * covlem / max(len(lemma), 1)))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    paths.WORK.mkdir(parents=True, exist_ok=True)
    up = paths.WORK / "pron_unpaired_phonetic.tsv"
    with open(up, "w", encoding="utf-8") as f:
        f.write("word\tsrc\tn_ipa\tn_phonetic\n")
        for x in unpaired:
            f.write("\t".join(str(y) for y in x) + "\n")
    print("■ 发音形配不上的 %d 条已落账 → %s（个数不等，**不靠位置硬配**）"
          % (len(unpaired), up))

    with dbtool.session("build-ko-pronunciation",
                        expect={"#pronunciation": len(rows) - have},
                        invalidates=[]) as s:
        if have:
            s.execute("DELETE FROM pronunciation")
            s.written += have
        s.executemany(
            "INSERT INTO pronunciation (word_id, entry_id, ipa, notation, "
            "hangeul_phonetic, region, tags, pos, is_primary, src, src_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    noted = [r[0] for r in con.execute("SELECT DISTINCT notation FROM pronunciation")]
    checks = [
        ("pronunciation 行数", q("SELECT COUNT(*) FROM pronunciation"), len(rows)),
        ("ipa 都非空", q("SELECT COUNT(*) FROM pronunciation WHERE TRIM(ipa)=''"), 0),
        # 🔴 **裸存自证**：库里不许出现定界符，否则展示层套第二层括号
        ("ipa 里没有定界符残留",
         q("SELECT COUNT(*) FROM pronunciation WHERE ipa LIKE '[%' OR ipa LIKE '/%'"), 0),
        ("notation 值域", sorted(noted), sorted(["narrow", "phonemic", "bare"])),
        ("word_id 都指得到",
         q("SELECT COUNT(*) FROM pronunciation p LEFT JOIN dict d ON d.id=p.word_id "
           "WHERE d.id IS NULL"), 0),
        ("entry_id 非空的都指得到",
         q("SELECT COUNT(*) FROM pronunciation p LEFT JOIN entry e ON e.id=p.entry_id "
           "WHERE p.entry_id IS NOT NULL AND e.id IS NULL"), 0),
        # 🔴 **不许读 `other` 字段**：那 52 条是日语假名，库里出现假名就是读错了字段
        ("库里没有假名（`other` 字段的日语读音）",
         q("SELECT COUNT(*) FROM pronunciation WHERE hangeul_phonetic GLOB "
           "'*[ぁ-ゖァ-ヺ]*' OR ipa GLOB '*[ぁ-ゖァ-ヺ]*'"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        gs = got if isinstance(got, list) else format(got, ",")
        ws = want if isinstance(want, list) else format(want, ",")
        print("   %s %-30s %s（期望 %s）" % ("✅" if good else "🔴", name, gs, ws))
    print("\n■ 抽样：`읽다`（连音·紧音化）与 `개`（ㅐ/ㅔ 合流）")
    for r in con.execute(
            "SELECT d.word, p.ipa, p.notation, p.hangeul_phonetic, p.src "
            "FROM pronunciation p JOIN dict d ON d.id=p.word_id "
            "WHERE d.word IN ('읽다','개','한국어') LIMIT 8"):
        print("     %-6s %-16s %-9s %-8s %s" % r)
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
