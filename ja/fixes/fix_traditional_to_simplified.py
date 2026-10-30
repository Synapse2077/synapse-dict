#!/usr/bin/env python3
"""修：中文版收来的释义/例句译文里的繁体 → 简体。2026-09-16（欠账 7）。

═══ 病灶 ═══
阶段 1.5a/3a 从中文版收的 83,234 条免费释义、阶段 5a 收的 8,586 条例句译文
**原样落库**，而中文版维基本身是繁简混排的：

    国内生产总值（简）   和   國際標準書號（繁）   躺在同一张表里

而两批付费翻译（21 万条）是纯简体 ⇒ **同一个页面上两种字形**。
实测繁转简会变的：释义 **11,244 条（13.5%）**、例句译文 **4,656 条（54.2%）**。

═══ 🔴🔴 不能直接 `t2s` 跑一遍 —— 它会改坏引文 ═══
这些释义会**引用日语的正字法**，而 `opencc` 不认识「这几个字是被引用的日文词形」：

    【敢え無くなる】死。          → 敢え无くなる   ← 日文词形被改坏
    【見頃】                    → 【见顷】       ← 同上，而且看着像个词
    「お暑く」、「問いて」变为…     → 「问いて」     ← 同上

`[[source-typo-fix-ours-not-quote]]` 的同一条：**改我们的出版文本，引文一个字不动。**

═══ 判据（量过 177 个 `【】` + 1,257 条含引用结构的释义才定的）═══
① **`【…】` 里的内容一律不转。** 这是中文版标注**日文词形**的约定。
   实测 177 个括号：含假名 103（确定日文）／纯汉字 36（其中 9 个转换会变，
   **逐条读全是日文词形**：鬱蒼・一所懸命・鳩舎・蝦蛄・絨毯・名詞・明視・毛頭・見頃）／
   拉丁数字 38（`【decilitre】`，`t2s` 本来就不动）。
   ⚠️ 我原本担心 `【數學】【化學】` 这类**中文学科标签**会被一起保护 ——
      实测当前数据里一条都没有。**担心要量过才知道是不是真的。**
② **`「」『』（）《》` 里含假名的不转。** 那是日文引用（29 条）。
   ⚠️ 不含假名的括注**要转** —— `（職務）`→`（职务）`、`（化學元素）`→`（化学元素）`
      正是我们要的。第一版我想把所有括号都保护起来，那会漏掉 900 多条该转的。
      **判据比它要描述的东西宽，代价是这次「修了等于没修」。**
③ 其余全部 `t2s`。

═══ ⚠️ 判据管不到的那一类，明说 ═══
**不带任何括号、直接内嵌的纯汉字日文词**，本判据识别不了，会被一起转。
量不出来（纯汉字串字形上分不出中日），所以不假装它不存在。
🔴 **推翻/收紧它需要**：出现一种能标出「这段是日文引用」的结构信号
（比如中文版改用统一的标注约定），或者有人报出实例。

跑（在仓库根）：
    python3 -u ja/fixes/fix_traditional_to_simplified.py
    python3 -u ja/fixes/fix_traditional_to_simplified.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")
KANA = re.compile(r"[ぁ-ゖァ-ヺ]")
# 🔴 `【】` 整段保护；其余括号**只在含假名时**保护。两条规则形状不同，别合并。
BRACKET_JA = re.compile(r"【[^】]*】")
QUOTE_ANY = re.compile(r"[「『（《][^」』）》]*[」』）》]")


def _fix(cv, s, cap=5):
    """把 `cv` 跑到**不动点**。

    🔴 `opencc` 的 `t2s` **不是幂等的**：跑一遍之后还剩 2 条会变
    （`芸薹`→`芸苔`、`惯於`→`惯于` —— 第一遍的产物又命中了第二条规则）。
    30 万条里只剩 2 条，**是闸的「必须为 0」逮到的**；写成「基本转完了」就漏过去了。
    ⚠️ 封顶 + 到顶大声报（`[[retry-must-converge-or-drop-loud]]`）——
       不收敛说明规则表里有环，那是要查的事，不是默默跑下去。
    """
    for _ in range(cap):
        t = cv(s)
        if t == s:
            return s
        s = t
    raise RuntimeError("opencc 转换 %d 轮仍不收敛：%r" % (cap, s[:60]))


# ══════════════════════════════════════════════════════════════════════════
#  安全的繁→简（B25，2026-10-29）—— 照 ru `criteria` ⑮ 的判据，ja 自己一份；`convert` 的 `cv` 传它
# ══════════════════════════════════════════════════════════════════════════
# 🔴 09-16 这里传的是**整段** `opencc t2s`，在本来就是简体的文本上会改错。2026-10-29 用原文（答案文件、
#    证据层、`example.src_translation`）对出改错 152 条：128 条转成**扩展平面**字形（`鮟鱇→𩽾𩾌`、
#    `鰤鱼→𫚕鱼`，多数字体是豆腐块）＋ 24 条 GB2312 里的歧义字（`乾下艮上→干下艮上` 卦名、`市乾鹿文` 人名、
#    `乾云丸` 刀名、`覆上了雪→复上`、`糙叶薹草→苔草`、`甯子→宁子`；其中 `乾燥`/`反覆` 这 7 条 OpenCC 是对的）。
# ⇒ 逐个位置决定收不收：① 目标字不在 BMP 不收；② 原字不在 GB2312（方向无歧义）收；
#    ③ 原字在 GB2312 ⇒ 只有「这段是繁体文本」才收，另有逐条裁决过的 `OPENCC_RIGHT`（照收）／`OPENCC_WRONG`
#       （不收）与 `ALWAYS`（规范简体里没有独立用法的字，照收）；④ 繁简对举不收。
OPENCC_RIGHT = ("反覆", "重覆", "覆信", "乾性", "乾燥", "乾田", "乾苔")
ALWAYS = frozenset("後於夥摺醣菸麽捱徵藉彷俱")
OPENCC_WRONG = ("覆上", "覆住", "覆育", "慰藉", "狼藉", "枕藉")
NEVER = frozenset("薹")
_OPENCC = None


def opencc_t2s(s):
    """**整段** OpenCC t2s 一遍。🔴 只留给复现 09-16 那次写库（`fix_t2s_damage.py`、`backfill_sense_src_id.py`）。"""
    global _OPENCC
    if _OPENCC is None:
        import opencc
        _OPENCC = opencc.OpenCC("t2s").convert
    return _OPENCC(s)


_EXT = None


def ext_targets():
    """OpenCC 字表里「常用平面字 → **扩展平面**字」的目标字集合（从 OpenCC 自己的字表读，不手抄）。
    页面上出现它们，多半是整段 t2s 转出来的豆腐块（`鮟鱇→𩽾𩾌`）；回归闸拿它锁住 B25 不回来。"""
    global _EXT
    if _EXT is None:
        import os
        import opencc
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


def _gb(ch):
    try:
        ch.encode("gb2312")
        return True
    except UnicodeEncodeError:
        return False


def _hit(text, i, phrases):
    return any(text[j:j + len(p)] == p for p in phrases for j in range(max(0, i - len(p) + 1), i + 1))


def safe_t2s(text):
    """安全的繁→简一遍（收敛由 `_fix` 管）。"""
    out = opencc_t2s(text)
    if out == text or len(out) != len(text):
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


def convert(text, cv):
    """→ (新文本, 被保护的片段数)。**保护段一个字节都不动。**"""
    spans = []
    for m in BRACKET_JA.finditer(text):
        spans.append((m.start(), m.end()))
    for m in QUOTE_ANY.finditer(text):
        if KANA.search(m.group(0)):
            spans.append((m.start(), m.end()))
    if not spans:
        return _fix(cv, text), 0
    spans.sort()
    out, pos = [], 0
    for a, b in spans:
        if a < pos:
            continue                      # 嵌套/重叠，外层已保护
        out.append(_fix(cv, text[pos:a]))
        out.append(text[a:b])             # ← 原样
        pos = b
    out.append(_fix(cv, text[pos:]))
    return "".join(out), len(spans)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    cv = safe_t2s          # B25：不再整段 opencc

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    jobs = []      # (表, 主键列, 主键, 新文本)
    stat = {"sense_gloss": [0, 0, 0], "example_gloss": [0, 0, 0]}
    for tbl, key in (("sense_gloss", "rowid"), ("example_gloss", "rowid")):
        for rid, t in con.execute(
                "SELECT %s, text FROM %s WHERE lang='zh'" % (key, tbl)):
            stat[tbl][0] += 1
            new, prot = convert(t or "", cv)
            if prot:
                stat[tbl][2] += 1
            if new != t:
                stat[tbl][1] += 1
                jobs.append((tbl, key, rid, new))
    # 🔴 回核：**保护段真的一个字都没动**（不是"我相信代码对"）
    bad = 0
    for tbl, key, rid, new in jobs:
        old = con.execute("SELECT text FROM %s WHERE %s=?" % (tbl, key),
                          (rid,)).fetchone()[0]
        for m in BRACKET_JA.finditer(old):
            if m.group(0) not in new:
                bad += 1
                if bad <= 5:
                    print("   🔴 保护段被改：%r → %r" % (old[:40], new[:40]))
    con.close()

    for tbl, (tot, chg, prot) in stat.items():
        print("■ %-14s 总 %s ｜ 会变 %s ｜ 含保护段 %s"
              % (tbl, f(tot), f(chg), f(prot)))
    print("■ 待改 %s 条｜保护段回核：%s"
          % (f(len(jobs)), "✅ 一个字都没动" if not bad else "🔴 %d 条被改" % bad))
    if bad:
        _sys.exit(1)
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        for tbl, key, rid, new in jobs[:6]:
            old = con.execute("SELECT text FROM %s WHERE %s=?" % (tbl, key),
                              (rid,)).fetchone()[0]
            print("   %r\n → %r" % (old[:52], new[:52]))
        con.close()
        return

    with dbtool.session("ja-t2s", expect={
            "__rows__": 0, "#sense_gloss": 0, "#example_gloss": 0,
            "#entry": 0, "#sense": 0, "#example": 0}) as con:
        for tbl in ("sense_gloss", "example_gloss"):
            con.executemany(
                "UPDATE %s SET text=? WHERE rowid=?" % tbl,
                [(new, rid) for t, _k, rid, new in jobs if t == tbl])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = {}
    for tbl in ("sense_gloss", "example_gloss"):
        n = sum(1 for (t,) in con.execute(
            "SELECT text FROM %s WHERE lang='zh'" % tbl)
            if convert(t or "", cv)[0] != t)
        left[tbl] = n
    # 保护段里的繁体**应该还在**（那是日文词形，不是我们的出版文本）
    prot_left = sum(1 for (t,) in con.execute(
        "SELECT text FROM sense_gloss WHERE lang='zh'")
        for m in BRACKET_JA.finditer(t or "") if cv(m.group(0)) != m.group(0))
    checks = [
        ("释义里没有可转的繁体了", left["sense_gloss"] == 0),
        ("例句译文里没有可转的繁体了", left["example_gloss"] == 0),
        # 🔴 这一条**期望非零**：日文词形保住了才对。它为 0 说明保护没生效。
        ("日文词形（【】内）的原字保住了", prot_left > 0),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    print("   （【】内保留的日文原字 %s 处 —— **这个数不该是 0**）" % f(prot_left))
    con.close()
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
