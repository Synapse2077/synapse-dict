#!/usr/bin/env python3
"""**音标闸** —— 阶段 4 的不变量。ru，2026-10-23。

    python3 ru/tests/test_pronunciation.py
    python3 ru/tests/test_pronunciation.py --mutate     # 变异验证：闸的闸
    python3 ru/tests/test_pronunciation.py --accept     # 把覆盖率与交叉复核的现状锁成基线

═══ 这一层最容易出的错**不是脏串，是「这条读音属于谁、能不能印」** ═══
① **归属**（Q3/Q4/Q11）：同形异重音词（`замок` за́мок ˈzamək／замо́к zɐˈmok）靠 `entry_id` 分开；
   复数读音挂在主格复数那个词形上、`entry_id` 留 NULL。**Q11 用重音层做独立复核** ——
   读音里主重音落在第几个元音，要与这个 entry 在重音层的某个候选一致（实测 98.64%）。
② **能不能印**（Q5/Q12）：源头说错的读音存但 hidden。🔴 Q5 用 `criteria.pronunciation_status`
   从 `tags` 列重算 —— **而它对「判据本身写坏了」是瞎的**（断言和被断言的用同一个坏判据
   ⇒ 双方一致报全绿，vi 的 S6）⇒ **Q12 钉已知答案**（常量，不锚现状 —— B20）。
③ **fr 版的地名是录音者所在地，不是方言**（Q8）—— 读者口径的锁。
④ 判据一律 `import criteria`（Q2/Q5），闸不重写。
"""
import argparse
import collections
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402

ROSTER = ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10",
          "Q11", "Q12")
ACCEPT = HERE / ".pronunciation_accept.json"

# `src` 登记表。问名单不写形状（`zh-edition-trad` 那一跤）。
SRC_DOMAIN = frozenset({"en-edition", "ru-edition", "zh-edition-simp", "zh-edition-trad",
                        "fr-edition", "vi-edition", "pl-edition"})
NOTATION_DOMAIN = frozenset({"narrow", "phonemic", "unmarked"})

# Q12 已知答案（全部取自源头原文，2026-10-23 逐条核过）：
#   (词形, ipa, 期望 hidden, 期望 dialect, 期望「有 entry_id」, 说明)
KNOWN = (
    ("агент", "ˈaɡʲɪnt", 1, "unknown", True, "ru 版 raw_tags `неправильно`"),
    ("агент", "ɐˈɡʲent", 0, "unknown", True, "正确读音照印"),
    ("агенты", "ˈaɡʲɪntɨ", 1, "unknown", False, "复数读音挂到复数词形，且仍带 неправильно"),
    ("хорошо", "xɐrɐˈʃɔ", 0, "Ukraine", True, "en 版 tags `Ukraine`"),
    ("диагональ", "dʲɪəɡɐˈnalʲ", 0, "Moscow", True, "ru 版 raw_tags `Москва`"),
)
# 同形异重音：同一个词形、同一个源，两个 entry 各挂各的读音（读者能分清）
HOMOGRAPH = ("замок", "ru-edition", {"за́мок": "ˈzamək", "замо́к": "zɐˈmok"})

_VOW_C = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
_VOW_I = set("aeiouyɐɪʊəɨɵʉɛɔæø")


def _cyr_stress(s):
    """带重音拼写 → 主重音所在的元音序号集合（ё 无重音符时算重音）。"""
    n, pos = 0, set()
    for i, ch in enumerate(s):
        if ch in _VOW_C:
            if s[i + 1:i + 2] == criteria.STRESS:
                pos.add(n)
            n += 1
    if not pos:
        yo = [i for i, ch in enumerate(x for x in s if x in _VOW_C) if ch in "ёЁ"]
        if len(yo) == 1:
            pos = {yo[0]}
    return pos


def _ipa_stress(ip):
    if ip.count("ˈ") != 1:
        return None
    n, pos = 0, None
    for i, ch in enumerate(ip):
        if ch == "ˈ":
            pos = n
        if ch in _VOW_I and ip[i + 1:i + 2] != "̯":
            n += 1
    return pos


def _open():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def _accept():
    try:
        return json.loads(ACCEPT.read_text("utf-8"))
    except Exception:                            # noqa: BLE001
        return {}


def coverage(con):
    """两个口径：词元 ／ 屈折形 —— 有没有一条**可印的**读音。"""
    out = {}
    for lab, v in (("lemma", 1), ("form", 0)):
        tot = con.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=?", (v,)).fetchone()[0]
        got = con.execute(
            "SELECT COUNT(DISTINCT p.word_id) FROM pronunciation p JOIN dict d ON d.id=p.word_id "
            "WHERE d.is_lemma=? AND p.hidden=0", (v,)).fetchone()[0]
        out[lab] = dict(tot=tot, got=got, pct=100.0 * got / max(tot, 1))
    return out


def cross_check(con):
    """Q11：读音的主重音位置 vs 这个 entry 在重音层的全部候选。→ 计数。"""
    var = collections.defaultdict(set)
    for eid, sw in con.execute("SELECT entry_id, stressed FROM stress WHERE entry_id IS NOT NULL"):
        var[eid] |= _cyr_stress(sw)
    c = collections.Counter()
    for ip, eid in con.execute(
            "SELECT p.ipa, p.entry_id FROM pronunciation p JOIN dict d ON d.id=p.word_id "
            "WHERE p.entry_id IS NOT NULL AND instr(d.word,' ')=0 AND instr(d.word,'-')=0"):
        ipp = _ipa_stress(ip)
        if ipp is None or not var.get(eid):
            c["n/a"] += 1
        elif ipp in var[eid]:
            c["match"] += 1
        else:
            c["none"] += 1
    tot = c["match"] + c["none"]
    return dict(match=c["match"], none=c["none"], na=c["n/a"],
                none_pct=100.0 * c["none"] / max(tot, 1))


def checks(con):
    out = []
    acc = _accept()

    def q(sql, *a):
        return con.execute(sql, a).fetchone()[0]

    n = q("SELECT COUNT(*) FROM pronunciation")
    out.append(("Q1", n > 0, "" if n else "`pronunciation` 是空的"))

    # ── Q2 出版值是判据的不动点：再过一遍 `pronunciation_parts` 必须原样返回 ─────
    bad2, eg2 = 0, []
    for pid, ip in con.execute("SELECT id, ipa FROM pronunciation"):
        kind, parts = criteria.pronunciation_parts(ip)
        if kind != "ok" or len(parts) != 1 or parts[0][0] != ip:
            bad2 += 1
            if len(eg2) < 5:
                eg2.append("#%d %s〔%s〕" % (pid, ip, kind))
    out.append(("Q2", bad2 == 0, "" if not bad2 else
                "%s 行出版值不是 `pronunciation_parts` 的不动点（还能再拆/再归一/该拒）：%s"
                % (format(bad2, ","), " ｜ ".join(eg2))))

    # ── Q3 外键 ＋ **归属一致**：entry_id 非空时，那个 entry 必须属于同一个词形 ──
    fk = q("SELECT COUNT(*) FROM pronunciation p LEFT JOIN dict d ON d.id=p.word_id "
           "WHERE d.id IS NULL")
    fe = q("SELECT COUNT(*) FROM pronunciation p LEFT JOIN entry e ON e.id=p.entry_id "
           "WHERE p.entry_id IS NOT NULL AND e.id IS NULL")
    mis = q("SELECT COUNT(*) FROM pronunciation p JOIN entry e ON e.id=p.entry_id "
            "WHERE e.word_id<>p.word_id")
    out.append(("Q3", not (fk or fe or mis), "" if not (fk or fe or mis) else
                "word_id 悬空 %s ／ entry_id 悬空 %s ／ **entry 属于别的词形 %s** —— "
                "后者＝读音挂在了别人的意思上" % (fk, fe, format(mis, ","))))

    # ── Q4 复数读音的锁，**两个方向**：entry_id 为空 ⇔ 源头标了 plural ──────────
    a = b = 0
    for eid, tj in con.execute("SELECT entry_id, tags FROM pronunciation"):
        tg = set(json.loads(tj)["tags"]) if tj else set()
        isp = criteria.pronunciation_target(tg) == "plural"
        if eid is None and not isp:
            a += 1
        elif eid is not None and isp:
            b += 1
    out.append(("Q4", not (a or b), "" if not (a or b) else
                "entry_id 为空而不是复数读音 %s ／ **复数读音挂在了词元的 entry 上 %s**（张冠李戴）"
                % (format(a, ","), format(b, ","))))

    # ── Q5 dialect/hidden/hidden_why 从 tags 重算必须一致（判据 import）───────────
    bad5, eg5 = 0, []
    for pid, tj, d, h, w in con.execute(
            "SELECT id, tags, dialect, hidden, hidden_why FROM pronunciation"):
        t = json.loads(tj) if tj else {"tags": [], "raw_tags": []}
        if criteria.pronunciation_status(t["tags"], t["raw_tags"]) != (d, h, w):
            bad5 += 1
            if len(eg5) < 5:
                eg5.append("#%d %s/%s/%s" % (pid, d, h, w))
    out.append(("Q5", bad5 == 0, "" if not bad5 else
                "%s 行的 dialect/hidden 与从 tags 重算的不一致：%s" % (format(bad5, ","), " ｜ ".join(eg5))))

    # ── Q6 值域 ─────────────────────────────────────────────────────────
    nots = {r[0] for r in con.execute("SELECT DISTINCT notation FROM pronunciation")}
    dias = {r[0] for r in con.execute("SELECT DISTINCT dialect FROM pronunciation")}
    bad_n = sorted(nots - NOTATION_DOMAIN)
    bad_d = sorted(dias - set(criteria.DIALECT_MAP.values()) - {"unknown"})
    out.append(("Q6", not (bad_n or bad_d), "" if not (bad_n or bad_d) else
                "notation 值域外 %s ／ dialect 值域外 %s" % (bad_n, bad_d)))

    # ── Q7 src ⊆ 登记，**且每一个登记的源都有行** ──────────────────────────
    got = {r[0] for r in con.execute("SELECT DISTINCT src FROM pronunciation")}
    uns, miss = sorted(got - SRC_DOMAIN), sorted(SRC_DOMAIN - got)
    out.append(("Q7", not (uns or miss), "" if not (uns or miss) else
                "没登记的源 %s ／ 登记了而一行都没有 %s（少收一整版只查非空查不出）" % (uns, miss)))

    # ── Q8 🔴 fr 版的地名是录音者所在地 —— 不许进 dialect ──────────────────
    fr = q("SELECT COUNT(*) FROM pronunciation WHERE src='fr-edition' AND dialect<>'unknown'")
    out.append(("Q8", fr == 0, "" if not fr else
                "%s 行 fr 版读音被标了方言 —— 那些 `Russie (Saint-Pétersbourg)` 是**录音者所在地**"
                "（99.7%% 与录音同对象），不是这条读音属于哪里" % fr))

    # ── Q9 去重：同一 entry、同一源、同一串只留一行 ───────────────────────
    dup = q("SELECT COUNT(*) FROM (SELECT 1 FROM pronunciation GROUP BY word_id, "
            "COALESCE(entry_id,-1), ipa, src HAVING COUNT(*)>1)")
    out.append(("Q9", dup == 0, "" if not dup else "%s 组重复" % format(dup, ",")))

    # ── Q10 覆盖率两个口径，**只许涨不许跌** ─────────────────────────────
    cov = coverage(con)
    base = acc.get("coverage")
    if base is None:
        ok10, w10 = False, "还没有已接受基线 —— 跑一次 `--accept`"
    else:
        drops = [k for k in ("lemma", "form") if cov[k]["pct"] < base[k] - 0.01]
        ok10 = not drops
        w10 = "" if ok10 else "覆盖率跌了 %s（现 %s ／ 基线 %s）" % (
            drops, {k: round(cov[k]["pct"], 2) for k in cov}, base)
    out.append(("Q10", ok10, w10))

    # ── Q11 重音层独立复核：「与所有候选都对不上」的比例不许涨 ────────────────
    cc = cross_check(con)
    b11 = acc.get("cross_none_pct")
    if b11 is None:
        ok11, w11 = False, "还没有已接受基线 —— 跑一次 `--accept`"
    else:
        ok11 = cc["none_pct"] <= b11 + 0.05
        w11 = "" if ok11 else (
            "读音与重音层所有候选都对不上的比例 %.3f%%（基线 %.3f%%）—— **`entry_id` 挂错了？**"
            % (cc["none_pct"], b11))
    out.append(("Q11", ok11, w11))

    # ── Q12 已知答案（常量）＋ 同形异重音的读者口径 ──────────────────────────
    bad12 = []
    for w, ip, h, d, has_e, why in KNOWN:
        rows = con.execute(
            "SELECT p.hidden, p.dialect, p.entry_id FROM pronunciation p JOIN dict x "
            "ON x.id=p.word_id WHERE x.word=? AND p.ipa=?", (w, ip)).fetchall()
        if not rows:
            bad12.append("%s %s 不在库里〔%s〕" % (w, ip, why))
            continue
        if not any(r[0] == h and r[1] == d and (r[2] is not None) == has_e for r in rows):
            bad12.append("%s %s 期望 hidden=%d dialect=%s 有entry=%s，实为 %s〔%s〕"
                         % (w, ip, h, d, has_e, rows, why))
    hw, hs, want = HOMOGRAPH
    for stressed, ip in want.items():
        r = con.execute(
            "SELECT COUNT(*) FROM pronunciation p JOIN entry e ON e.id=p.entry_id "
            "JOIN dict x ON x.id=p.word_id WHERE x.word=? AND p.src=? AND e.stressed=? AND p.ipa=?",
            (hw, hs, stressed, ip)).fetchone()[0]
        if not r:
            bad12.append("同形异重音：%s 的 entry（%s）上没有挂 %s —— 读者分不清锁与城堡"
                         % (hw, stressed, ip))
    out.append(("Q12", not bad12, " ｜ ".join(bad12)))
    return out


def roster_check(rows):
    got = [c for c, _o, _w in rows]
    bad = []
    if sorted(got) != sorted(ROSTER) or len(set(got)) != len(got):
        bad.append("花名册对不上：多 %s ／ 少 %s" % (sorted(set(got) - set(ROSTER)),
                                               sorted(set(ROSTER) - set(got))))
    return bad


def report():
    if not paths.DB.exists():
        print("🔴 库不存在：%s" % paths.DB)
        return 1
    con = _open()
    try:
        rows = checks(con)
        cov = coverage(con)
        cc = cross_check(con)
    finally:
        con.close()
    print("■ 音标闸（ru 阶段 4）—— 花名册 %d 条" % len(ROSTER))
    for cid, ok, why in rows:
        print("   %s %-4s %s" % ("✅" if ok else "🔴", cid, why))
    rb = roster_check(rows)
    for b in rb:
        print("   🔴🔴 花名册自检：" + b)
    print("   词元有可印读音 %s/%s ＝ **%.2f%%** ／ 屈折形 %.2f%% ／ 重音层复核对不上 %.3f%%"
          % (format(cov["lemma"]["got"], ","), format(cov["lemma"]["tot"], ","),
             cov["lemma"]["pct"], cov["form"]["pct"], cc["none_pct"]))
    red = [r for r in rows if not r[1]]
    print("■ %s（%d/%d）" % ("全绿 ✓" if not red and not rb else "有红", len(rows) - len(red), len(rows)))
    return len(red) + len(rb)


def accept():
    con = _open()
    try:
        cov = coverage(con)
        cc = cross_check(con)
    finally:
        con.close()
    ACCEPT.write_text(json.dumps({
        "coverage": {k: round(v["pct"], 2) for k, v in cov.items()},
        "cross_none_pct": round(cc["none_pct"], 3),
        "cross": cc,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("■ 已接受基线：词元 %.2f%% ／ 屈折形 %.2f%% ／ 复核对不上 %.3f%%"
          % (cov["lemma"]["pct"], cov["form"]["pct"], cc["none_pct"]))
    return 0


def _mutations():
    """(编号, 说明, 允许的连带红, SQL)。合成行一律负 id（B20）。

    🔴 连带红**先跑一遍看实际、逐条确认为什么该红、再写进来**，不许先猜后写
       （2026-10-23 屈折闸那一轮：猜漏了两条 ⇒ 1.5 小时白跑一遍）。
    """
    return [
        ("Q2", "把一行出版值改成还带方括号的串", set(),
         ["UPDATE pronunciation SET ipa='['||ipa||']' WHERE id=(SELECT MIN(id) FROM pronunciation "
          "WHERE entry_id IS NULL)"]),
        ("Q3", "把一批读音的 entry_id 挪到别的词形的 entry 上",
         # Q11：挂到别人的意思上，重音位置自然对不上；Q9：挪过去撞上那个 entry 原有的同串
         {"Q9", "Q11"},["UPDATE pronunciation SET entry_id=entry_id+1 WHERE entry_id IS NOT NULL AND id%50=0"]),
        ("Q4", "把复数读音挂回词元的 entry 上（张冠李戴复发）",
         # Q3：那个 entry 不属于复数词形；Q11：复数读音 vs 词元重音；Q12：`агенты` 有了 entry
         {"Q3", "Q11", "Q12"},["UPDATE pronunciation SET entry_id=(SELECT MIN(id) FROM entry) WHERE entry_id IS NULL"]),
        ("Q5", "把所有 hidden 清零（「源头说错的读音」照印）",
         # Q12：**这正是它存在的理由** —— 判据整个坏掉时 Q5 会与它一致，只有已知答案拦得住
         {"Q12"},
         ["UPDATE pronunciation SET hidden=0, hidden_why=NULL"]),
        ("Q6", "往 notation 塞一个值域外的值", set(),
         ["UPDATE pronunciation SET notation='«变异»' WHERE id=(SELECT MIN(id) FROM pronunciation)"]),
        ("Q7", "删掉 vi 版全部读音（少收一版）",
         # Q10：有些词只有 vi 版给了读音
         {"Q10"},
         ["DELETE FROM pronunciation WHERE src='vi-edition'"]),
        ("Q8", "把 fr 版带 `Russie (Saint-Pétersbourg)` 的读音标成彼得堡方言",
         # Q5：从 tags 重算出来是 unknown
         {"Q5"},
         ["UPDATE pronunciation SET dialect='Saint-Petersburg' WHERE src='fr-edition' "
          "AND tags LIKE '%Saint-Pétersbourg%'"]),
        ("Q9", "造一组重复行", set(),
         ["INSERT INTO pronunciation(id,word_id,entry_id,ipa,dialect,notation,tags,hidden,"
          "hidden_why,src,src_ref) SELECT -1,word_id,entry_id,ipa,dialect,notation,tags,hidden,"
          "hidden_why,src,src_ref||'#mut' FROM pronunciation WHERE tags IS NULL LIMIT 1"]),
        ("Q10", "删掉一半词元的读音",
         # Q11：对不上的集中在词形页（R21），删掉词元的 ⇒ 词形页占比上升；Q12：样例词被删
         {"Q11", "Q12"},["DELETE FROM pronunciation WHERE word_id IN (SELECT id FROM dict WHERE is_lemma=1 "
          "AND id%2=0)"]),
        ("Q11", "把一批单词读音的主重音挪到开头（entry_id 不动）",
         # Q9：有的变体只差重音位置，挪成一样就重复
         {"Q9"},
         ["UPDATE pronunciation SET ipa=REPLACE(ipa,'ˈ','')||'' WHERE id%20=0 AND entry_id IS NOT NULL",
          "UPDATE pronunciation SET ipa='ˈ'||ipa WHERE id%20=0 AND entry_id IS NOT NULL "
          "AND instr(ipa,'ˈ')=0"]),
        ("Q12", "把 `замок` 两个 entry 的读音互换（同形异重音挂反）",
         set(),
         ["UPDATE pronunciation SET ipa=CASE ipa WHEN 'ˈzamək' THEN 'zɐˈmok' ELSE 'ˈzamək' END "
          "WHERE src='ru-edition' AND ipa IN ('ˈzamək','zɐˈmok') AND word_id=(SELECT id FROM dict "
          "WHERE word='замок')"]),
    ]


def mutate():
    if report():
        print("\n🔴 基线就不绿，先修基线")
        return 1
    muts = _mutations()
    print("\n■ 变异验证（%d 条，跑在库的副本上）" % len(muts))
    print("   ⚠️ Q1   无变异档：清空会让 Q4/Q7/Q10/Q12 连带红，分不开")
    real = paths.DB
    fails = []
    for cid, why, also, sqls in muts:
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / real.name
            shutil.copy2(real, cp)
            paths.DB = cp
            try:
                con = sqlite3.connect(cp)
                for s in sqls:
                    con.execute(s)
                con.commit()
                con.close()
                con = _open()
                try:
                    got = {c for c, ok, _ in checks(con) if not ok}
                finally:
                    con.close()
                undecl = sorted(got - {cid} - set(also))
                if cid in got and not undecl:
                    print("   ✅ %-4s %s%s" % (cid, why,
                                             "（连带红 %s，已逐条声明）" % sorted(got - {cid}) if got - {cid} else ""))
                elif cid in got:
                    print("   🔴 %-4s 逮到了，**但有没声明的连带红 %s** —— %s" % (cid, undecl, why))
                    fails.append(cid)
                else:
                    print("   🔴🔴 %-4s **没逮到**（红的是 %s）—— %s" % (cid, sorted(got), why))
                    fails.append(cid)
            finally:
                paths.DB = real
    if report():
        print("\n🔴🔴 反控制失败：真库基线不绿了")
        return 1
    print("\n%s" % ("■ 变异验证全过 ✓，反控制：真库基线仍全绿" if not fails
                    else "🔴 %d 条没过：%s" % (len(fails), fails)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--accept", action="store_true")
    a = ap.parse_args()
    if a.accept:
        return accept()
    return mutate() if a.mutate else (1 if report() else 0)


if __name__ == "__main__":
    raise SystemExit(main())
