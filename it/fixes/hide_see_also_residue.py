#!/usr/bin/env python3
"""出版层残渣收尾：「See X.」义项 + 两条假中文。2026-08-18（阶段 7）。

═══ 怎么发现的 ═══
阶段 7 的回归闸报了两条：

    C7  wiktextract 残渣又出现在出版层   22 条
    B1  「中文」整条是拉丁字母             2 条

═══ C7：22 条里只该动 13 条 ═══
`hide_wiktextract_residue.py`（08-13）的判据是「英文 gloss 是 `See X.` 这类交叉引用」，
它们在 kaikki 原文里确实是 senses（所以证据层不删），但不该给用户看。

🔴 但**其中 9 条是该词形唯一的可见义项** —— 藏掉它，用户搜到这个词就是一片空白。
   `unhide_orphan_senses.py`（08-17）立的正是这条规矩：**宁可显示一条弱内容，
   也不要显示空白**。⇒ 只藏「还有别的可见义项」的那 13 条，9 条留着并写进闸的基线。

    藏  mo「See da mo.」          （该词形另有 6 条可见义项）
    留  fieri「See in fieri」     （该词形只有这 1 条）

═══ B1：2 条假中文，删掉而不是编 ═══
    pbsl      中文写着 "pbsl"       ← fr 版原文就是 `pbsl.`，源头没给任何信息
    chaperon  中文写着 "chaperon"   ← 来自盲填那批（`blind-morph`，已知 24-25% 错误率），
                                     而它的意语证据是占位符「definizione mancante」
两条都是**模型没答上来、把原词抄了回来**。按 `blind-gloss-inference-ceiling` 的结论：
**不填，留诚实空白** —— 删掉这两条中文，不编。

用法（在 it/ 目录下）：
    python3 fixes/hide_see_also_residue.py            # 干跑
    python3 fixes/hide_see_also_residue.py --apply
    python3 fixes/hide_see_also_residue.py --verify
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")
# 🔴 判据必须**可验证**，不能只看开头两个字母。
#    第一版写成「英文 gloss 以 see 开头」，会误伤真释义：
#        sede        see (of a bishop)     ← "see" 是名词（主教教区）
#        a più tardi see you later         ← 这就是它的英文释义
#    正确判据：`See X` / `see also X` 里的 **X 确实是我们库里的一个词形** ——
#    交叉引用指向的必然是个词条，而真释义的后半截不是。实测命中 13 条、放行 9 条，
#    放行的那 9 条逐条读过全是真释义。
SEE = "(g.text LIKE 'See %' OR g.text LIKE 'see %')"
REF = re.compile(r"^(?:See|see)\s+(?:also\s+)?(.+?)\.?$")


def scan(con):
    """→ (要藏的义项 id, 保留的义项 id)。**保留的那批是「藏了就没内容了」的。**"""
    words = {w.lower() for (w,) in con.execute("SELECT word FROM dict")}
    rows = con.execute("""
        SELECT s.id, d.word, g.text,
               (SELECT count(*) FROM sense x
                 WHERE x.word_id=s.word_id AND COALESCE(x.hidden,0)=0) AS visible
        FROM sense s JOIN dict d ON d.id=s.word_id
        JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en'
        WHERE COALESCE(s.hidden,0)=0 AND """ + SEE).fetchall()
    hide, keep = [], []
    for sid, w, text, visible in rows:
        m = REF.match((text or "").strip())
        tgt = m.group(1).strip() if m else None
        if not tgt or tgt.lower() not in words:
            continue                      # 真释义（`see you later` / `see (of a bishop)`）
        (hide if visible > 1 else keep).append((sid, w, text))
    return hide, keep


def fake_zh(con):
    """→ [(gloss rowid, 词形, 中文)]：中文与词形逐字相同 = 模型把原词抄了回来。"""
    return con.execute("""
        SELECT g.rowid, d.word, g.text FROM sense s
          JOIN dict d ON d.id=s.word_id
          JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh'
        WHERE COALESCE(s.hidden,0)=0 AND lower(g.text)=lower(d.word)""").fetchall()


def gate(con):
    print("\n═══ 闸 ═══")
    hide, keep = scan(con)
    checks = [
        ("🔴 还有别的可见义项、却仍露着 See X 的", len(hide), 0),
        ("（基线）藏了就没内容、故意留着的", len(keep), 3),
        ("🔴 中文与词形逐字相同的假中文", len(fake_zh(con)), 0),
        # 🔴 不许藏过头：留着的那 9 条必须仍然可见
        ("🔴 那 9 个词形仍然有可见义项",
         sum(1 for sid, w, t in keep
             if con.execute("SELECT count(*) FROM sense WHERE id=? AND COALESCE(hidden,0)=0",
                            (sid,)).fetchone()[0] == 0), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-42s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    hide, keep = scan(ro)
    fz = fake_zh(ro)
    ro.close()
    print("■ See X 义项：藏 %s 条 / 留 %s 条（留＝藏了这个词就空白了）" % (f(len(hide)), f(len(keep))))
    for sid, w, t in hide[:6]:
        print("     藏  %-14s %s" % (w[:14], t[:44]))
    for sid, w, t in keep[:4]:
        print("     留  %-14s %s" % (w[:14], t[:44]))
    print("■ 假中文（与词形逐字相同）：%s 条" % f(len(fz)))
    for rid, w, t in fz:
        print("     删  %-14s 中文写着 %s" % (w[:14], t[:20]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("hide-see-also-residue",
                        expect={"__rows__": 0, "#sense_gloss": -len(fz)}) as s:
        s.execute("UPDATE sense SET hidden=1 WHERE id IN (%s)"
                  % ",".join(str(i) for i, _w, _t in hide))
        s.execute("DELETE FROM sense_gloss WHERE rowid IN (%s)"
                  % ",".join(str(r) for r, _w, _t in fz))
        s.written = len(hide) + len(fz)
    print("\n■ 已藏 %s 条、删假中文 %s 条" % (f(len(hide)), f(len(fz))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
