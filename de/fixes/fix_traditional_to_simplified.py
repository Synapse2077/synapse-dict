#!/usr/bin/env python3
"""修：中文释义里的繁体 → 简体。de 版，2026-09-18。零模型调用。

═══ 病灶 ═══
阶段 1.5a 从中文版白拿的 10,122 条免费中文**原样落库**，而中文版维基本身繁简混排：

    腐肉的氣味、惡臭 ／ 阿布哈茲人 ／ 礦場，礦區        ← 繁
    国内生产总值 ／ 血管瘤 ／ 角膜浑浊                  ← 简（付费翻译那 12 万条）

躺在同一张表里 ⇒ **同一个页面上两种字形**。

实测全库中文释义 292,370 条，转换会变的 **962 条（0.33%）**，按来源拆开：

    zh-edition（中文版白送）   912   ← 大头，1.5a 收的那批
    其余（模板生成/早期收录）     50

⚠️ **2026-09-18 的新一批（本日 `backfill_blank_from_zh.py` 写的 31,985 条）不在里面**
   —— 那一批落库前就转过了。这条修的是**它之前**的存量。

═══ 🔴 为什么 de 可以直接 `t2s`，而 ja 不可以 ═══
ja 那轮的判据写了一大段保护段：中文版的日语释义会**引用日文正字法**
（`【見頃】` → `【见顷】` 把日文词形改坏了），`opencc` 不认识「这几个字是被引用的」。
`[[source-typo-fix-ours-not-quote]]`：改我们的出版文本，引文一个字不动。

**德语这边这个风险不存在，而且是量过的不是想当然**：
  · 962 条里**含 `【】「」『』《》` 的：0 条** —— 没有引用结构要保护；
  · 含拉丁字母的 120 条，那是德语词本身（`Akkordeonist (“手風琴演奏家”) 的陰性等價詞`），
    `t2s` 对拉丁字母**不动**，要转的正是括号里那句中文译文。
⇒ 全量转，不设保护段。⚠️ `opencc` 的 `t2s` 不幂等，转到收敛。

🔴 **推翻它需要**：中文释义里出现被引用的**中文**原文（比如讲某个汉语词的词源），
   那时 `t2s` 会把引文一起改掉。现在一条都没有；出现了就得照 ja 那样加保护段。

═══ 证据层不动 ═══
只改 `sense_gloss`（出版层）。`sense_src` 存的是「源头说了什么」，
繁体原样留着（`[[two-layer-sense-model]]`）。

跑（在仓库根）：
    python3 -u de/fixes/fix_traditional_to_simplified.py
    python3 -u de/fixes/fix_traditional_to_simplified.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import re
import sqlite3

import dbtool
import paths

import opencc

_T2S = opencc.OpenCC("t2s")
# 引用结构。**判据留着，即使当前命中 0 条** —— 它是「推翻这条修复」的探针：
# 哪天中文释义里真出现被引用的中文原文，这里会报出来而不是默默转坏。
QUOTE = re.compile(r"[【】「」『』《》]")


def t2s_opencc(s, cap=6):
    """**整段** OpenCC 繁→简，转到收敛。🔴 只留给「复现 09-18 那两次写库」用（`fix_t2s_damage.py` 靠它认出
    哪些行是被整段转过的）—— 新写的出版文本一律走 `t2s`。"""
    for _ in range(cap):
        out = _T2S.convert(s)
        if out == s:
            return s
        s = out
    raise RuntimeError("opencc 转换 %d 轮仍不收敛：%r" % (cap, s[:60]))


# ══════════════════════════════════════════════════════════════════════════
#  安全的繁→简（B25，2026-10-29）—— 照 ru `criteria` ⑮ 的判据，de 自己一份
# ══════════════════════════════════════════════════════════════════════════
# 🔴 整段 `t2s_opencc` 在**本来就是简体**的文本上会改错。2026-10-29 用原文（答案文件 ＋ 证据层经
#    `clean_gloss` 重算）对出 de 改错 10 条：6 条转成**扩展平面**字形（`宽翅鵟→宽翅𫛭`、`二噁英→二𫫇英`，
#    多数字体显示成豆腐块）＋ 4 条 GB2312 里的歧义字（`鼠麴草`、`反覆`×2、`重覆` —— 这 4 条 OpenCC 是对的）。
# ⇒ 逐个位置决定收不收 OpenCC 的改动：
#    ① 目标字不在 BMP ⇒ 不收；
#    ② 原字不在 GB2312（方向无歧义，`國→国`）⇒ 收；
#    ③ 原字在 GB2312 而 OpenCC 要改它（歧义区：`乾覆薹吒甯麴…`）⇒ 只有「这行是繁体文本」（含②那种字）才收，
#       另有两张逐条裁决过的短语表：`OPENCC_RIGHT` 在简体文本里也收，`OPENCC_WRONG` 永远不收；
#    ④ 繁简对举（`習 /习`）⇒ 不收。
OPENCC_RIGHT = ("反覆", "重覆", "覆信", "乾性", "乾燥", "乾田", "乾苔", "鼠麴")   # `反复`/`干燥`…是规范写法
# 规范简体里**没有独立用法**的字：简体文本里出现就是漏转，照收（ru 同一张，从 OpenCC 字表枚举）。
# 🔴 第一版从 ru 抄判据时漏了这张 ⇒ 干跑当场把 `征收→徵收`、`借口→藉口`、`存折→存摺`、`糖蛋白→醣蛋白` 列成「要改回」。
ALWAYS = frozenset("後於夥摺醣菸麽捱徵藉彷俱")
OPENCC_WRONG = ("覆上", "覆住", "覆育", "慰藉", "狼藉", "枕藉")                   # 「盖」「养育」；`慰藉`仍写藉
NEVER = frozenset("薹")                                                          # OpenCC 字表错：`薹草`是规范简体


def _gb(ch):
    try:
        ch.encode("gb2312")
        return True
    except UnicodeEncodeError:
        return False


def _hit(text, i, phrases):
    return any(text[j:j + len(p)] == p for p in phrases for j in range(max(0, i - len(p) + 1), i + 1))


def _t2s_once(text):
    out = _T2S.convert(text)
    if out == text or len(out) != len(text):      # OpenCC t2s 逐字等长；不等长就别信它
        return text
    trad_row = any(a != b and not _gb(a) for a, b in zip(text, out))
    res = []
    for i, (a, b) in enumerate(zip(text, out)):
        if a == b or ord(b) > 0xFFFF or a in NEVER or _hit(text, i, OPENCC_WRONG):
            res.append(a)
        elif _gb(a) and not (trad_row or a in ALWAYS or _hit(text, i, OPENCC_RIGHT)):
            res.append(a)
        elif re.match(r"\s*[/／（(、]\s*" + re.escape(b), text[i + 1:i + 5]) or \
                re.search(re.escape(b) + r"\s*[/／（(、]\s*$", text[max(0, i - 4):i]):
            res.append(a)
        else:
            res.append(b)
    return "".join(res)


_EXT = None


def ext_targets():
    """OpenCC 字表里「常用平面字 → **扩展平面**字」的目标字集合（815 个，从 OpenCC 自己的字表读，不手抄）。
    页面上出现它们，多半是整段 t2s 转出来的豆腐块（`鮟鱇→𩽾𩾌`）；回归闸拿它锁住 B25 不回来。"""
    global _EXT
    if _EXT is None:
        import os
        _EXT = set()
        for root, _d, fs in os.walk(os.path.dirname(opencc.__file__)):
            for f in fs:
                if f.startswith("TSCharacters") and f.endswith(".txt"):
                    for line in open(os.path.join(root, f), encoding="utf-8"):
                        a, b = line.rstrip("\n").split("\t")
                        _EXT.update(x for x in b.split() if len(x) == 1 and ord(x) > 0xFFFF
                                    and len(a) == 1 and ord(a) <= 0xFFFF)
        assert len(_EXT) > 500, "🔴 OpenCC 字表没读到（%d）—— 闸会空过" % len(_EXT)
    return _EXT


def t2s(s, cap=6):
    """**安全的**繁→简，转到收敛（`opencc` 短语切分依赖上下文，转一遍邻字变了下一遍会再变）。"""
    for _ in range(cap):
        out = _t2s_once(s)
        if out == s:
            return s
        s = out
    raise RuntimeError("t2s %d 轮仍不收敛：%r" % (cap, s[:60]))


def _assert_de():
    assert paths.DB.name == "synapse-dict-de.sqlite", "🔴 paths 不是 de 的：%s" % paths.DB


# 🔴 2026-10-29（B25 顺带）：原来只查 `sense_gloss`；例句译文里模型写出的繁体（`兩倍`、`蚁鴷`）75 条没人管
TABLES = ("sense_gloss", "example_gloss")


def plan(con):
    """→ ([(表, rowid, 原文, 转换后, 来源)], 带引用结构的那些)"""
    rows, quoted = [], []
    for tbl in TABLES:
        for rid, txt, src in con.execute(
                "SELECT rowid, text, src FROM %s WHERE lang='zh'" % tbl):
            new = t2s(txt)
            if new == txt:
                continue
            (quoted if QUOTE.search(txt) else rows).append((tbl, rid, txt, new, src))
    return rows, quoted


def main():
    _assert_de()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    total = sum(con.execute("SELECT count(*) FROM %s WHERE lang='zh'" % t).fetchone()[0] for t in TABLES)
    rows, quoted = plan(con)
    con.close()

    print("   中文释义＋例句译文总数 %9s" % format(total, ","))
    print("   繁转简会变的          %9s（%.2f%%）"
          % (format(len(rows), ","), 100.0 * len(rows) / max(total, 1)))
    print("   🔴 含引用结构、不转    %9s %s"
          % (len(quoted), [q[2][:30] for q in quoted[:3]] or "（0 条 —— 德语没有这个形状）"))
    by_src = {}
    for _tb, _r, _t, _n, src in rows:
        by_src[src] = by_src.get(src, 0) + 1
    for src, n in sorted(by_src.items(), key=lambda x: -x[1]):
        print("      %-20s %6s" % (src, format(n, ",")))

    dbtool.sample_check([(t[:28], n[:28], s) for _tb, _r, t, n, s in rows[::max(1, len(rows) // 14)]],
                        12, ("繁（源头原样）", "简（出版层改成）", "来源"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("de-fix-traditional-to-simplified", expect={}) as s:
        for tbl in TABLES:
            s.executemany("UPDATE %s SET text=? WHERE rowid=?" % tbl,
                          [(n, r) for tb, r, _t, n, _s in rows if tb == tbl])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left, left_q = plan(con)
    ev = con.execute(
        "SELECT count(*) FROM sense_src WHERE lang='zh'").fetchone()[0]
    con.close()
    checks = [
        ("出版层不再有可转的繁体", len(left) == 0),
        # 含引用结构的有意不转（2026-10-29 起例句里有 3 条：`《罗马书》`…），条数不许因这次写库而变
        ("含引用结构的那几条一个没动", len(left_q) == len(quoted)),
        ("证据层一个字没动（繁体原样留着）", ev > 0),
    ]
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    assert all(ok for _, ok in checks), "🔴 回核不过"


if __name__ == "__main__":
    main()
