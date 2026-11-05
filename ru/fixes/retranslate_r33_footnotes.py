#!/usr/bin/env python3
"""R33：俄文版释义里的 `[n]` 漏进了机翻中文 ⇒ 剥掉 `[n]` 重译这一批。ru，2026-11-03。

═══ `[n]` 是什么（量过才知道，原先的猜测是错的）═══
不是「见本页第 n 义项」，是 ru.wiktionary 的写法：**紧挨在前面那个词的第 n 个义项**
（`образования козла [4]` ＝ козёл 的第 4 义；`город Лхасу [1]` ＝ Лхаса 第 1 义）—— 64 处的 n 比本页义项数还大，
不可能指本页。⇒ 对中文读者是一个用不上的记号，而机翻已经把它译坏了一部分：
`ботан. плод [1]`（植：果实）→「〈植〉[1]的果实」（模型把 `[1]` 当成了名词）。光删 `[1]` 剩「〈植〉的果实」，照样不通。

═══ 做法 ═══
范围：可出版义项里，俄文释义带 `[n]`、**模型译出的中文也带 `[n]`** 的那批（745 条）。
俄文原文剥掉 `[n]`／`[I]` 后，用 5c 同一份提示（`translate_glosses.SYS`）与同一套定题（`PROBE`）重译；
只改 `sense_gloss.text`（模型那一行），证据层俄文一字不动；`text_pub` 之后由 `zh_pub.py --apply` 同步。
答案文件按义项主键存（`[[model-answer-files-key-by-id]]`），旧译文仍在 5c 的答案文件里（账本不动）。

跑（在仓库根）：
    python3 -u ru/fixes/retranslate_r33_footnotes.py              # 干跑
    python3 -u ru/fixes/retranslate_r33_footnotes.py --run        # 花钱
    python3 -u ru/fixes/retranslate_r33_footnotes.py --load [--apply]
    python3 -u ru/fixes/retranslate_r33_footnotes.py --strip [--apply]   # 第二轮：免费，见下

═══ 第二轮（2026-11-03 晚）：判据窄了两处，漏 42 条 ⇒ **直接剥中文，不花钱** ═══
上面 `MARK` 只认 `[1]`／`[I]`、只认半角：漏了俄文侧 `[1.]`／`[I.1]`／`[1, 2]`／`[III 2]`，
和中文侧模型改成全角的 `［1］`（`завод`「工厂［1］的建筑物」）。判据改住 `criteria.SENSE_REF`（回归闸 P32 同一个）。
这 42 条**先试了免费路径**：在中文上剥掉编号，42 条剥完逐条人读全部通顺（第一轮那种「〈植〉[1]的果实」
——模型把编号当名词——这批里一条没有）⇒ 不重译。只改 `sense_gloss.text`，俄文证据层一字不动。
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import asyncio
import json
import re
import sqlite3

import dbtool
import ds_batch
import paths
import translate_glosses as TG          # 提示与定题：import，不重写（5c 体例一致）

OUT = paths.WORK / "r33_footnote_zh.jsonl"
F = lambda n: format(n, ",")                                      # noqa: E731
_N = r"\[(?:\d+|[IVX]+)\]"
MARK = re.compile(r"\s*" + _N)                                    # 「有没有」用它：`[2]`／`[I]`
# 剥用它：`X [1] или [2]` 说的是「X 的第 1 或第 2 义」，整串就是 X ⇒ 「编号＋或/和＋编号」一起剥。
#   🔴 第一版只剥方括号，留下悬空的「或」：`гриб`「属于真菌的生物，或」、`кошка`「像猫的人，或」（回收抽查逮到）
#   🔴 连词前**必须有空白**：第一版写 `\s*(?:или|и|,)`，把 `России [1]` 的词尾 `и` 当连词吃掉了（`Росси`、`белк`、`лошад`）
STRIP = re.compile(r"(?:\s*%s)?(?:(?:\s+(?:или|и)|\s*,)\s*%s)+|\s*%s" % (_N, _N, _N))
REDO = paths.WORK / "r33_footnote_zh_redo.jsonl"                  # 剥法改了的那几条重译；回收时优先
# 逐条裁决（优先于模型答案）。只有一条：这里的 `[1], [2] и [3]` **恰好指本页自己的义项**（「与第 1、2、3 义相同」），
#   剥掉之后原句残缺、模型译成「与引导从句从属于主句时相同的意义的」⇒ 手工按原文意思译，编号保留成读得懂的写法。
MANUAL = {112924: "与义项 1、2、3 意义相同，用于把从句连接到主句"}   # какой：с теми же знач., что [1], [2] и [3] подчиняет …


def plan(con):
    """→ [(sense_id, 模型中文那一行的 sense_gloss.id, 词头, 词性, 剥过的俄文)]。回归闸 import 它数「还剩几条」。"""
    out = []
    for sid, zid, w, pos, ru, zh in con.execute(
            "SELECT s.id, z.id, d.word, e.pos, g.text, z.text FROM sense s "
            "JOIN entry e ON e.id = s.entry_id JOIN dict d ON d.id = s.word_id "
            "JOIN sense_gloss g ON g.sense_id = s.id AND g.lang = 'ru' "
            "JOIN sense_gloss z ON z.sense_id = s.id AND z.lang = 'zh' AND z.src LIKE 'model:%' "
            "WHERE s.hidden = 0 AND g.text LIKE '%[%]%'"):
        if MARK.search(ru) and MARK.search(zh):
            out.append((sid, zid, w, pos, STRIP.sub("", ru).strip()))
    return out


def answers():
    out = dict(MANUAL)
    for f in (REDO, OUT):                        # REDO 先认领（setdefault）
        if not f.exists():
            continue
        for line in f.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:                                     # noqa: BLE001
                continue
            out.setdefault(d.get("id"), (d.get("zh") or "").strip())
    return out


def redo_rows(rows):
    """剥法改了的行（旧剥法 `MARK.sub` 与新剥法 `STRIP.sub` 结果不同）—— 只重译这几条。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ru = {sid: t for sid, t in con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='ru' AND sense_id IN (%s)" % ",".join(str(r[0]) for r in rows))}
    return [r for r in rows if MARK.sub("", ru[r[0]]).strip() != r[4]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--strip", action="store_true")
    a = ap.parse_args()
    if a.strip:
        return strip_zh(a.apply)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = plan(con)
    con.close()
    print("■ 中文里带 `[n]` 的模型释义 %s 条" % F(len(rows)))
    for r in rows[:5]:
        print("   %s  %s" % (r[2], r[4][:70]))
    if a.run:
        todo = redo_rows(rows) if OUT.exists() else rows
        print("■ 本轮译 %s 条（%s）" % (F(len(todo)), "剥法改了的重译" if OUT.exists() else "全部"))
        batches, meta = TG.build([(sid, w, pos, g) for sid, _z, w, pos, g in todo])
        asyncio.run(ds_batch.run(TG.SYS, batches, meta, REDO if OUT.exists() else OUT, mode="flash", conc=30))
    if not (a.run or a.load):
        print("（干跑。--run 花钱）")
        return
    ans = answers()
    probes = {k: v for k, v in ans.items() if isinstance(k, str) and k.startswith("__c")}
    bad_probe = [k for k, v in probes.items() if not any(w in v for w in TG.PROBE[k.split("#")[0]]["want"])]
    miss = [r for r in rows if not ans.get(r[0])]
    still = [r for r in rows if ans.get(r[0]) and MARK.search(ans[r[0]])]
    nozh = [r for r in rows if ans.get(r[0]) and not re.search(r"[一-鿿]", ans[r[0]])]
    nozh += [r for r in rows if ans.get(r[0]) and re.search(r"(?:或|[、，,])\s*$", ans[r[0]])]   # 悬空的「或」／标点
    #   🔴 第一版是 `[或和与及]$`，把「总和」「普及」判成悬空（以「和」「及」结尾的正常词）⇒ 只认「或」与悬空标点
    print("■ 控制组：定题 %d 道答错 %d ／ 缺答 %d ／ 译文仍带 [n] %d ／ 译文没有汉字 %d"
          % (len(probes), len(bad_probe), len(miss), len(still), len(nozh)))
    for r in still[:5] + nozh[:5]:
        print("   ", r[2], "|", r[4][:50], "|", ans.get(r[0]))
    if not a.load:
        return
    if bad_probe or miss or still or nozh:
        raise SystemExit("🔴 控制组红，不回收")
    upd = [(ans[sid], zid) for sid, zid, *_ in rows]
    if not a.apply:
        print("■ 要改 %s 行（干跑。--apply 写库）" % F(len(upd)))
        return
    with dbtool.session("ru-r33-footnote-retranslate", expect={"__rows__": 0}, invalidates=[]) as s:
        s.executemany("UPDATE sense_gloss SET text=? WHERE id=?", upd)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = len(plan(con))
    print("■ 写后回核：中文仍带 `[n]` 的 %d 条（期望 0）⇒ 接着跑 `python3 -u ru/pipeline/zh_pub.py --apply` 同步 text_pub" % left)
    if left:
        raise SystemExit("🔴 回核红")


def strip_rows(con):
    """第二轮：→ [(sense_gloss.id, 词头, 旧中文, 新中文)]。范围＝可出版义项的模型中文里读者看得到编号的那批。"""
    import criteria as C
    out = []
    for zid, w, t in con.execute(
            "SELECT z.id, d.word, z.text FROM sense s JOIN dict d ON d.id = s.word_id "
            "JOIN sense_gloss z ON z.sense_id = s.id AND z.lang = 'zh' AND z.src LIKE 'model:%' "
            "WHERE s.hidden = 0 AND z.text_pub IS NULL"):
        if C.SENSE_REF.search(t):
            out.append((zid, w, t, C.strip_sense_ref_zh(t)))
    return out


def strip_zh(apply):
    import criteria as C
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = strip_rows(con)
    # text_pub 有值的模型行（简繁转换过，103 条）只改 text 不够、读者看的是 text_pub ⇒ 这里不处理，有就判红
    #   🔴 第一版写「这种行期望 0」—— 错的，有 103 条；该问的是「它们的出版文本里有没有编号」
    pub = sum(1 for (t,) in con.execute(
        "SELECT z.text_pub FROM sense s JOIN sense_gloss z ON z.sense_id = s.id AND z.lang = 'zh' "
        "AND z.src LIKE 'model:%' WHERE s.hidden = 0 AND z.text_pub IS NOT NULL") if C.SENSE_REF.search(t))
    con.close()
    # 收空白那一步只许收「剥编号留下的」：原文去掉编号之前就有的汉字间空白，不许顺带吃掉
    #   判法：编号连同两边空白换成占位符 \x00 之后，还找得到汉字间空白 ⇒ 那是原文自带的
    gap = [r for r in rows if C._SR_CJK_GAP.search(re.sub(r"\s*%s\s*" % C._SR_TOK, "\x00", r[2]))]
    bad = gap + [r for r in rows if C.SENSE_REF.search(r[3]) or not re.search(r"[一-鿿]", r[3])
                 or re.search(r"(?:或|[、，,])\s*$", r[3])]
    print("■ 第二轮：模型中文里仍带义项编号 %d 条（text_pub 有值而出版文本带编号的 %d，期望 0）" % (len(rows), pub))
    for zid, w, old, new in rows:
        print("   %-18s %s\n   %18s → %s" % (w, old[:70], "", new[:70]))
    print("■ 控制组：剥完仍带编号／没有汉字／悬空连词 %d" % len(bad))
    if pub or bad:
        raise SystemExit("🔴 控制组红，不写")
    if not apply:
        print("（干跑。--apply 写库）")
        return
    with dbtool.session("ru-r33-strip-sense-ref", expect={"__rows__": 0}, invalidates=[]) as s:
        s.executemany("UPDATE sense_gloss SET text=? WHERE id=?", [(new, zid) for zid, _w, _o, new in rows])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = len(strip_rows(con))
    print("■ 写后回核：仍带编号 %d 条（期望 0）" % left)
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
