#!/usr/bin/env python3
"""**录音闸** —— 阶段 6c 的不变量。ru，2026-10-24。

    python3 ru/tests/test_audio.py
    python3 ru/tests/test_audio.py --mutate
    python3 ru/tests/test_audio.py --accept

═══ 这一层最容易出的错是**读者点播放听到的不是这个词** ═══
① B12（A3）：同一个文件一个词形只许一行（按 Commons 归一键，不按 URL）。
② 张冠李戴（A4/A5）：藏不藏用收它的那个函数重算；**第二信号来自源头**（同音／异写），
   `form_of` 有意不算（`нога ⇐ ноги` 是错的）。判据写坏两边一致 ⇒ **A8 钉已知答案**。
③ 复数录音（A6）：挂在主格复数词形上、`entry_id` 为空 —— 照音标层 Q4。
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

ROSTER = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9")
ACCEPT = HERE / ".audio_accept.json"
SRC_DOMAIN = frozenset({"en-edition", "ru-edition", "zh-edition-simp", "zh-edition-trad",
                        "fr-edition", "vi-edition", "pl-edition"})
# A8 已知答案（2026-10-24 逐条读过）：(词形, commons_key, 期望 hidden_why 或 None)
KNOWN = (
    ("нога", "Ru-ноги.ogg", criteria.AUDIO_WRONG_WORD),           # 录的是复数（只有 form_of 信号）
    ("интернат", "LL-Q7737 (rus)-Tatiana Kerbush-дом-интернат.wav", criteria.AUDIO_WRONG_WORD),
    ("лесть", "Ru-лезть.ogg", None),                               # 源头声明同音
    ("что", "Ru-што.ogg", None),                                   # 源头 alt_of
    ("эти", "LL-Q7737 (rus)-Kolokol-sa-эти.wav", None),            # 录音者名里有连字符
)


def _open():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def _accept():
    try:
        return json.loads(ACCEPT.read_text("utf-8"))
    except Exception:                            # noqa: BLE001
        return {}


def coverage(con):
    lem = con.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    got = con.execute("SELECT COUNT(DISTINCT a.word_id) FROM audio a JOIN dict d ON d.id=a.word_id "
                      "WHERE a.hidden=0 AND d.is_lemma=1").fetchone()[0]
    pub = con.execute("SELECT COUNT(*) FROM audio WHERE hidden=0").fetchone()[0]
    return dict(pub=pub, lemma=got, lemma_pct=100.0 * got / max(lem, 1))


def checks(con, same=None):
    out = []
    q = lambda s, *a: con.execute(s, a).fetchone()[0]                  # noqa: E731
    n = q("SELECT COUNT(*) FROM audio")
    rows = con.execute("SELECT a.id, a.word_id, a.entry_id, a.url, a.commons_key, a.hidden, a.hidden_why, "
                       "a.src, d.word FROM audio a LEFT JOIN dict d ON d.id=a.word_id").fetchall()
    srcs = {r[7] for r in rows}
    orphan = sum(1 for r in rows if r[8] is None)
    out.append(("A1", n > 0 and srcs == SRC_DOMAIN and orphan == 0,
                "%s 行／版 %d／缺 %s／挂不上 dict %d" % (format(n, ","), len(srcs), sorted(SRC_DOMAIN - srcs), orphan)))
    bad = q("SELECT COUNT(*) FROM audio WHERE (hidden=1) <> (hidden_why IS NOT NULL AND TRIM(hidden_why)<>'') "
            "OR commons_key IS NULL OR TRIM(commons_key)='' OR url NOT LIKE 'http%'")
    out.append(("A2", bad == 0, "hidden/why 不一致、缺归一键或 url 不像 url %d 行" % bad))
    dup = q("SELECT COUNT(*) FROM (SELECT 1 FROM audio GROUP BY word_id, commons_key HAVING COUNT(*)>1)")
    out.append(("A3", dup == 0, "🔴 B12：同一 (词形, Commons 键) 多行 %d 组" % dup))
    # A4 藏不藏 ＝ 判据重算（tags 没落库：源头标错的只有 2 条，按原因放行）
    bad4, eg4 = 0, []
    for r in rows:
        if r[6] and r[6] != criteria.AUDIO_WRONG_WORD:
            continue
        want = criteria.audio_hidden_why(r[8], r[4], same_sound=same or frozenset())
        if want != r[6]:
            bad4 += 1
            if len(eg4) < 3:
                eg4.append("%s ⇐ %s：%s≠%s" % (r[8], r[4][:30], r[6], want))
    out.append(("A4", bad4 == 0, "张冠李戴与判据不一致 %d 行 %s" % (bad4, " ｜ ".join(eg4))))
    # A5 可播的录音，文件名量得了的就必须与词形一致或有源头信号（读者口径，与 A4 独立：不依赖库里的 why）
    bad5 = 0
    for r in rows:
        if r[5]:
            continue
        fw = criteria.audio_filename_word(r[4])
        if fw is not None and not criteria.audio_word_matches(r[8], fw) and \
                frozenset((criteria._audio_fold(r[8]), criteria._audio_fold(fw))) not in (same or ()):
            bad5 += 1
    out.append(("A5", bad5 == 0, "可播而文件名里是另一个词 %d 行" % bad5))
    # A6 entry 归属：有 entry 的必须属于同一个词形；没 entry 的必须是复数录音（不是词元自己的）
    bad6 = q("SELECT COUNT(*) FROM audio a LEFT JOIN entry n ON n.id=a.entry_id "
             "WHERE a.entry_id IS NOT NULL AND (n.id IS NULL OR n.word_id<>a.word_id)")
    null_lemma = q("SELECT COUNT(*) FROM audio a JOIN dict d ON d.id=a.word_id WHERE a.entry_id IS NULL "
                   "AND d.is_lemma=1 AND a.src='en-edition'")
    out.append(("A6", bad6 == 0 and null_lemma == 0,
                "entry 属于别的词形 %d／en 版词元录音丢了 entry %d" % (bad6, null_lemma)))
    # A7 url 与归一键指向**同一个文件**。🔴 第一版 A7 是「(词形, url) 唯一」—— 表结构的 UNIQUE 早就强制了，
    #    变异连注入都注入不进去（IntegrityError），**一条检查结构性地不可能红 ⇒ 信号量为零**。换成这条：
    #    「url 换成了另一个词的文件而归一键没跟着变」是张冠李戴的另一条路，A4/A5 只看归一键看不见它。
    from urllib.parse import unquote
    bad7 = sum(1 for r in rows if r[4].lower() not in unquote(r[3]).replace("_", " ").lower())
    out.append(("A7", bad7 == 0, "url 与 Commons 归一键不是同一个文件 %d 行" % bad7))
    bad8 = []
    for w, key, want in KNOWN:
        hit = con.execute("SELECT a.hidden_why FROM audio a JOIN dict d ON d.id=a.word_id WHERE d.word=? "
                          "AND a.commons_key=?", (w, key)).fetchone()
        if not hit:
            bad8.append("%s ⇐ %s 找不到" % (w, key))
        elif hit[0] != want:
            bad8.append("%s ⇐ %s：%s" % (w, key, hit[0]))
    out.append(("A8", not bad8, " ｜ ".join(bad8) or "%d 个已知答案全对" % len(KNOWN)))
    base = _accept().get("coverage")
    cov = coverage(con)
    if not base:
        out.append(("A9", False, "没有已接受基线（先 --accept）"))
    else:
        low = [k for k in ("pub", "lemma") if cov[k] < base[k]]
        out.append(("A9", not low, "倒退 %s" % low if low else "可播 %s／词元有录音 %s（%.2f%%）" % (
            format(cov["pub"], ","), format(cov["lemma"], ","), cov["lemma_pct"])))
    return out


def _same():
    """第二信号：与收割器同一个函数、同一遍源。"""
    sys.path.insert(0, str(HERE.parent))
    from pipeline.build import SRC, rd
    s = set()
    for _src, p in SRC:
        for e in rd(p):
            if criteria.entry_accept(e)[0]:
                s |= criteria.audio_same_sound_pairs(e)
    return frozenset(s)


def roster_check(rows):
    got = [c for c, _o, _w in rows]
    if sorted(got) != sorted(ROSTER) or len(set(got)) != len(got):
        return ["花名册对不上：多 %s ／ 少 %s" % (sorted(set(got) - set(ROSTER)), sorted(set(ROSTER) - set(got)))]
    return []


def report(same=None):
    if not paths.DB.exists():
        print("🔴 库不存在：%s" % paths.DB)
        return 1
    same = same if same is not None else _same()
    con = _open()
    try:
        rows = checks(con, same)
    finally:
        con.close()
    print("■ 录音闸（ru 阶段 6c）—— 花名册 %d 条" % len(ROSTER))
    for cid, ok, why in rows:
        print("   %s %-4s %s" % ("✅" if ok else "🔴", cid, why))
    rb = roster_check(rows)
    for b in rb:
        print("   🔴🔴 花名册自检：" + b)
    red = [r for r in rows if not r[1]]
    print("■ %s（%d/%d）" % ("全绿 ✓" if not red and not rb else "有红", len(rows) - len(red), len(rows)))
    return len(red) + len(rb)


def accept():
    con = _open()
    try:
        cov = coverage(con)
    finally:
        con.close()
    ACCEPT.write_text(json.dumps({"coverage": cov}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("■ 已接受基线：%s" % cov)
    return 0


def _mutations():
    return [
        ("A1", "删掉 pl 版全部录音（少收一版）",
         {"A9", "A8"},   # 已知答案 `нога ⇐ Ru-ноги.ogg` 那行留下的是 pl 版
         ["DELETE FROM audio WHERE src='pl-edition'"]),
        ("A2", "藏一行却不写为什么", {"A9"},
         ["UPDATE audio SET hidden=1 WHERE id=(SELECT MIN(id) FROM audio WHERE hidden=0)"]),
        ("A3", "B12 复发：同一个文件按 mp3 转码 URL 再插一行", {"A9"},
         ["INSERT INTO audio(id,word_id,entry_id,url,commons_key,hidden,hidden_why,src) SELECT -1,word_id,"
          "entry_id,url||'«变异».mp3',commons_key,hidden,hidden_why,src FROM audio WHERE hidden=0 LIMIT 1"]),
        ("A4", "张冠李戴全部放出来", {"A5", "A8"},
         ["UPDATE audio SET hidden=0, hidden_why=NULL WHERE hidden_why='%s'" % criteria.AUDIO_WRONG_WORD]),
        # A5 与 A4 量的是同一件事的两个口径（A4 对库里的 why、A5 对读者听到什么）⇒ A4 必然连带红。
        #   留着 A5 是因为 A4 跳过「why 是别的原因」的行，A5 不跳。
        ("A5", "放出 5 条张冠李戴（不含已知答案那几条）", {"A4"},
         ["UPDATE audio SET hidden=0, hidden_why=NULL WHERE id IN (SELECT id FROM audio WHERE hidden_why='%s' "
          "AND commons_key NOT IN ('Ru-ноги.ogg','LL-Q7737 (rus)-Tatiana Kerbush-дом-интернат.wav') LIMIT 5)"
          % criteria.AUDIO_WRONG_WORD]),
        ("A6", "把复数录音挂回词元的 entry", set(),
         ["UPDATE audio SET entry_id=(SELECT MIN(id) FROM entry) WHERE entry_id IS NULL"]),
        ("A7", "把一批 url 换成别的词的文件（归一键不动）", set(),
         # OR IGNORE：相邻那行可能是同一个词的另一条录音 ⇒ 撞 UNIQUE(word_id,url)，跳过那几行
         ["UPDATE OR IGNORE audio SET url=(SELECT url FROM audio a2 WHERE a2.id=audio.id+1) WHERE id%500=0 "
          "AND id+1 IN (SELECT id FROM audio)"]),
        ("A8", "`лесть ⇐ лезть` 的同音录音被当成张冠李戴藏掉", {"A4", "A9"},
         ["UPDATE audio SET hidden=1, hidden_why='%s' WHERE commons_key='Ru-лезть.ogg' AND word_id=(SELECT id "
          "FROM dict WHERE word='лесть')" % criteria.AUDIO_WRONG_WORD]),
        ("A9", "删掉一半可播录音", {"A1", "A8"},   # 删掉的那一半里有已知答案的行
         ["DELETE FROM audio WHERE hidden=0 AND id%2=0"]),
    ]


def mutate():
    same = _same()
    if report(same):
        print("\n🔴 基线就不绿，先修基线")
        return 1
    muts = _mutations()
    print("\n■ 变异验证（%d 条，跑在库的副本上）" % len(muts))
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
                    got = {c for c, ok, _ in checks(con, same) if not ok}
                finally:
                    con.close()
                undecl = sorted(got - {cid} - set(also))
                if cid in got and not undecl:
                    print("   ✅ %-4s %s%s" % (cid, why, "（连带红 %s，已逐条声明）" % sorted(got - {cid})
                                             if got - {cid} else ""))
                elif cid in got:
                    print("   🔴 %-4s 逮到了，**但有没声明的连带红 %s** —— %s" % (cid, undecl, why))
                    fails.append(cid)
                else:
                    print("   🔴🔴 %-4s **没逮到**（红的是 %s）—— %s" % (cid, sorted(got), why))
                    fails.append(cid)
            finally:
                paths.DB = real
    if report(same):
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
