#!/usr/bin/env python3
"""B29：出版层中文里漏转的繁体 → 简体。各门共用一份（2026-10-30），零模型调用。

═══ 缺陷 ═══
跑批的模型并不总是写简体（fr 例句译文 `組織` `經濟`），中文版维基白送的释义原样落库（pt `第一人稱單數…`）。
de/ru/ja 早清过；其余几门**没人量过**。同一页上两种字形。

═══ 判据 ═══
一条都不在这里写 —— `scripts/zh_t2s.t2s`（安全版：扩展平面不收、GB2312 歧义字只在繁体行里收、
日文与「讲这个字本身」的不动、逐条裁决表）。闸 import 的也是它。

═══ 改哪儿 ═══
只改**出版层**：表名不以 `_src` 结尾、带 `lang` 列的 `*_gloss`；有 `text_pub` 列的写 `text_pub`（`text` 原文不动），
没有的写 `text`（原文在证据层 `sense_src`／模型答案文件里）。

跑（在仓库根）：
    python3 -u scripts/fix_zh_t2s.py --lang fr            # 干跑
    python3 -u scripts/fix_zh_t2s.py --lang fr --apply
"""
import argparse
import collections
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from zh_t2s import t2s  # noqa: E402

LANGS = ("en", "es", "it", "fr", "pt", "ja", "ko", "vi")


def targets(con):
    """→ [(表, 读的列表达式, 写的列)]"""
    out = []
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%\\_gloss' ESCAPE '\\'"):
        cols = [c[1] for c in con.execute("PRAGMA table_info(%s)" % t)]
        if t.endswith("_src") or "lang" not in cols:
            continue
        out.append((t, "COALESCE(text_pub, text)", "text_pub") if "text_pub" in cols else (t, "text", "text"))
    return out


def plan(con, src_like=None):
    rows = []
    for t, rd, wr in targets(con):
        src = "src" if any(c[1] == "src" for c in con.execute("PRAGMA table_info(%s)" % t)) else "''"
        for rid, txt, s in con.execute("SELECT rowid, %s, %s FROM %s WHERE lang='zh'" % (rd, src, t)):
            if txt and (src_like is None or (s or "").startswith(src_like)) and t2s(txt) != txt:
                rows.append((t, wr, rid, txt, t2s(txt), s))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=LANGS)
    ap.add_argument("--apply", action="store_true")
    # ko/vi：模型写的那几批大半在讲汉字/喃字原形（`운동<運動>` `獨居/독거` 喃字原文），逐行裁决之前不碰 ⇒ 只转中文版白送的
    ap.add_argument("--src", help="只改 src 以此开头的行（如 zh-edition）")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT / a.lang))
    import dbtool                                    # 各门自己的写库闸门
    con = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    tg = targets(con)
    rows = plan(con, a.src)
    con.close()
    print("■ B29 繁→简（%s）：%s 行要改｜表 %s" % (a.lang, format(len(rows), ","), [t[0] for t in tg]))
    for k, v in collections.Counter((r[0], r[5]) for r in rows).most_common():
        print("   %-16s %-26s %6s" % (k[0], k[1], format(v, ",")))
    for r in rows[::max(1, len(rows) // 12)]:
        print("   %s → %s" % (r[3][:40].replace("\n", " "), r[4][:40].replace("\n", " ")))
    if not a.apply or not rows:
        print("\n（干跑。加 --apply 才写库）" if rows else "\n（无事可做）")
        return
    # 写 text_pub 的那批：非空计数涨（原来是 NULL）；写 text 的不变
    grow = collections.Counter(t for t, wr, *_ in rows if wr == "text_pub")
    with dbtool.session("b29-zh-t2s", expect={"text_pub": sum(grow.values())} if grow else {}) as s:
        # executemany：session 只数它（execute 不计数 ⇒ fr/pt 那次屏幕上印的是「写入 0 条」而 914 行都写了）
        by = collections.defaultdict(list)
        for t, wr, rid, _old, new, _s in rows:
            by[(t, wr)].append((new, rid))
        for (t, wr), args in by.items():
            s.executemany("UPDATE %s SET %s=? WHERE rowid=?" % (t, wr), args)
    con = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    left = plan(con, a.src)
    con.close()
    print("\n■ 写后回核：仍可转 %d（期望 0）" % len(left))
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
