#!/usr/bin/env python3
"""B29 的返工：化学名里的「噁」被安全繁简判据转成了「恶」。各门共用一份，2026-10-30。

═══ 缺陷 ═══
`噁` 是**规范字**（通用规范汉字表收，化学专用：噁唑、二噁烷、二噁英、噁草酮、噁霉灵），
OpenCC 按台湾用字 `噁心＝恶心` 一律转成「恶」，`scripts/zh_t2s.py` 第一版没拦 ⇒ B29 在
en 511／fr 39／es 4／it 2 处把 `异噁唑` 改成了 `异恶唑`。判据已改（`NEVER` 收「噁」，只有「噁心」照转）。

═══ 改回的判据：只看上下文，不需要原文 ═══
「恶」后面紧跟化学词素（唑 嗪 烷 二唑 草酮 霉灵 唑啉）或「二恶英」—— 这些位置上「恶」不可能是「坏」的意思。
en 的 B29 前备份已被保留策略清掉，按原文逐字还原做不到；按上下文改是确定的（几处原本就写「恶唑」的
也一并规范成「噁唑」，同一页上不再两种写法）。
⚠️ 只跑 B29 转过的四门（en/fr/es/it）。de/ja/ru/pt 的「恶唑」是模型原本就这么写的，不是转坏的，不在这笔账里。

跑（在仓库根）：
    python3 -u scripts/fix_chem_e.py --lang en            # 干跑
    python3 -u scripts/fix_chem_e.py --lang en --apply
"""
import argparse
import pathlib
import re
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fix_zh_t2s import targets  # noqa: E402  —— 哪些表、读哪列写哪列，与 B29 修复脚本同一个函数

LANGS = ("en", "fr", "es", "it")
CHEM = re.compile(r"恶(?=唑|嗪|烷|二唑|草酮|霉灵|唑啉)|(?<=二)恶(?=英)")


def fix(t):
    return CHEM.sub("噁", t)


def plan(con):
    out = []
    for t, rd, wr in targets(con):
        for rid, txt in con.execute("SELECT rowid, %s FROM %s WHERE lang='zh' AND %s LIKE '%%恶%%'" % (rd, t, rd)):
            if txt and fix(txt) != txt:
                out.append((t, wr, rid, txt, fix(txt)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=LANGS)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT / a.lang))
    import dbtool
    con = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    rows = plan(con)
    con.close()
    print("■ 化学名「恶→噁」（%s）：%d 行" % (a.lang, len(rows)))
    for r in rows[::max(1, len(rows) // 10)]:
        print("   %s → %s" % (r[3][:40], r[4][:40]))
    if not a.apply or not rows:
        return
    with dbtool.session("b29-chem-e") as s:
        by = {}
        for t, wr, rid, _o, new in rows:
            by.setdefault((t, wr), []).append((new, rid))
        for (t, wr), args in by.items():
            s.executemany("UPDATE %s SET %s=? WHERE rowid=?" % (t, wr), args)
    con = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    left = len(plan(con))
    print("■ 写后回核：仍有化学名写「恶」%d 行（期望 0）" % left)
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
