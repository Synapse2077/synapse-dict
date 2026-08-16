#!/usr/bin/env python3
"""英文明说是姓氏、中文却只有裸音译的，按既定约定补 `（姓氏）`。2026-08-15。

═══ 怎么发现的 ═══
查「同一词形下中文逐字相同」的 622 组重复时，逐条读出来的：

    Polistena  义项1 en=a surname transferred from the place name   zh=波利斯泰纳
               义项2 en=a town and municipality of Reggio Calabria   zh=波利斯泰纳
    Auletta    义项1 en=a village in the province of Salerno         zh=奥莱塔
               义项2 en=a surname transferred from the place name    zh=奥莱塔

用户看到同一个中文两遍，分不出哪条是姓、哪条是镇 —— 这不是"多了一行"，
是**中文翻粗了**。全库量下来比重复那批大一个数量级：

    英文标明是姓氏的义项      11,552
      中文已写「姓」           4,607
      🔴 中文只有裸音译        6,951

═══ 判据与约定 ═══
· 判据：英文释义匹配 `\\bsurname\\b` **且** 中文里没有「姓」字。确定性，不问模型。
· 约定：`X（姓氏）` —— **既定格式**，已写对的 4,607 条里 2,876 条用的正是它。
  不发明第二套（`docs/lang/it-CONVENTIONS.md` A33 那条教训：塞第二份同类东西前
  先搜已有那份）。
· ⚠️ 中文里已带括号的**跳过**（`多里亚（贵族家族）` 再追加就成了两个括号），
  数量记账，不硬修。

═══ 可逆 ═══
只在原中文后追加固定后缀，逆操作是去掉后缀；`src` 从 `unknown` 改成
`unknown+tpl:surname`，改过哪些行一句 SQL 就能查出来。英文原文与证据层不动。

用法（在 it/ 目录下）：
    python3 fixes/mark_surname_zh.py
    python3 fixes/mark_surname_zh.py --apply
    python3 fixes/mark_surname_zh.py --verify
    python3 fixes/mark_surname_zh.py --mutate
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SUFFIX = "（姓氏）"
NEW_SRC_SUFFIX = "+tpl:surname"
SURNAME = re.compile(r"\bsurname\b", re.IGNORECASE)
HAS_PAREN = re.compile(r"[（(].*[）)]")


def plan(con):
    """→ ([(sense_id, old_zh, new_zh, old_src)], 统计)"""
    zh = {}
    for sid, t, src in con.execute(
            "SELECT sense_id, text, src FROM sense_gloss WHERE lang='zh' AND seq=0"):
        zh[sid] = (t, src)
    rows, stat = [], Counter()
    for sid, en in con.execute(
            "SELECT g.sense_id, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
            "WHERE g.lang='en' AND g.seq=0 AND COALESCE(s.hidden,0)=0"):
        if not SURNAME.search(en):
            continue
        stat["英文标明是姓氏"] += 1
        pair = zh.get(sid)
        if not pair:
            stat["  没有中文（不动）"] += 1
            continue
        t, src = pair
        if "姓" in t:
            stat["  中文已体现（不动）"] += 1
            continue
        if HAS_PAREN.search(t):
            stat["  🔴 中文已带括号，跳过并记账"] += 1
            continue
        stat["✅ 追加（姓氏）"] += 1
        rows.append((sid, t, t + SUFFIX, src))
    return rows, stat


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    left, _ = plan(con)
    checks = [
        ("🔴 不再有「英文说姓氏、中文无姓、且无括号」的义项", len(left), 0),
        # 🔴 可逆性回核：去掉后缀必须能变回原文。判据是**结构性**的 ——
        #    改过的行 src 带标记、text 必须以后缀结尾，两者一一对应。
        ("🔴 改过的行都以「（姓氏）」结尾",
         q("SELECT count(*) FROM sense_gloss WHERE src LIKE ? AND text NOT LIKE ?",
           "%" + NEW_SRC_SUFFIX, "%" + SUFFIX), 0),
        # ⚠️ 第一版写成「逐行再查一次英文」，参数传的是裸字符串 ——
        #    sqlite3 把它按字符拆成 13 个绑定直接报错。改成 join，一次查完。
        ("🔴 带该后缀的中文，其英文必须真说了 surname",
         sum(1 for (t,) in con.execute(
             "SELECT COALESCE(e.text,'') FROM sense_gloss z LEFT JOIN sense_gloss e "
             "ON e.sense_id=z.sense_id AND e.lang='en' AND e.seq=0 "
             "WHERE z.lang='zh' AND z.src LIKE ?", ("%" + NEW_SRC_SUFFIX,))
             if not SURNAME.search(t)), 0),
        ("🔴 只改中文行，别的语言一条没碰",
         q("SELECT count(*) FROM sense_gloss WHERE src LIKE ? AND lang<>'zh'",
           "%" + NEW_SRC_SUFFIX), 0),
        ("句末不许有标点",
         q("SELECT count(*) FROM sense_gloss WHERE src LIKE ? AND "
           "(text LIKE '%。' OR text LIKE '%.')", "%" + NEW_SRC_SUFFIX), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1

    if a.mutate:
        import contextlib
        import io
        import shutil
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
        cases = [
            ("把一条改过的行的后缀去掉",
             "UPDATE sense_gloss SET text=replace(text,'%s','') WHERE src LIKE '%%%s' "
             "AND sense_id=(SELECT min(sense_id) FROM sense_gloss WHERE src LIKE '%%%s')"
             % (SUFFIX, NEW_SRC_SUFFIX, NEW_SRC_SUFFIX)),
            ("给一条英文不含 surname 的中文打上后缀与标记",
             "UPDATE sense_gloss SET text=text||'%s', src='unknown%s' WHERE lang='zh' "
             "AND sense_id=(SELECT g.sense_id FROM sense_gloss g WHERE g.lang='en' "
             "AND g.text NOT LIKE '%%surname%%' LIMIT 1)" % (SUFFIX, NEW_SRC_SUFFIX)),
            ("把标记打到英文行上",
             "UPDATE sense_gloss SET src='unknown%s' WHERE lang='en' "
             "AND sense_id=(SELECT min(sense_id) FROM sense_gloss WHERE lang='en')"
             % NEW_SRC_SUFFIX),
        ]
        caught = 0
        for name, sql in cases:
            shutil.copy(paths.DB, tmp)
            c2 = sqlite3.connect(tmp)
            c2.execute(sql)
            c2.commit()
            c2.close()
            r2 = sqlite3.connect("file:%s?mode=ro" % tmp, uri=True)
            with contextlib.redirect_stdout(io.StringIO()):
                red = not gate(r2)
            r2.close()
            caught += red
            print("   %s %-42s %s" % ("✅" if red else "🔴", name,
                                      "闸红了（对）" if red else "闸没红 —— 这条闸是假的"))
        print("\n   变异验证 %d/%d" % (caught, len(cases)))
        return 0 if caught == len(cases) else 1

    rows, stat = plan(ro)
    for k, v in stat.most_common():
        print("   %-34s %7s" % (k, f"{v:,}"))
    print("\n■ 将改写 %s 条中文" % f"{len(rows):,}")
    for sid, old, new, _ in rows[:6]:
        print("     %-22s → %s" % (old[:22], new[:28]))
    ro.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("mark-surname-zh", expect={"#sense_gloss": 0}) as s:
        s.executemany("UPDATE sense_gloss SET text=?, src=? WHERE sense_id=? AND lang='zh' "
                      "AND seq=0", [(new, (src or "unknown") + NEW_SRC_SUFFIX, sid)
                                    for sid, _old, new, src in rows])
    print("\n■ 已改写 %s 条" % f"{len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
