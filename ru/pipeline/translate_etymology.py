#!/usr/bin/env python3
"""阶段 7b：把**词源散文**（en／ru 版）译成中文。ru，2026-10-25。**花钱** —— 用户 2026-10-25 定了范围 A（全译）；
报价与开跑仍分两次拍板。

    python3 -u ru/pipeline/translate_etymology.py --count
    python3 -u ru/pipeline/translate_etymology.py --slice 0.01    # 实测单价，**先跑这个**
    python3 -u ru/pipeline/translate_etymology.py                 # 全量（先看报价、等拍板）
    python3 -u ru/pipeline/translate_etymology.py --audit --tokens N
    python3 -u ru/pipeline/translate_etymology.py --load [--apply]

═══ 范围 A：没有中文词源的词形，它的 en／ru 版**全部**可出版段 ═══
已有 zh 版白送中文词源的词形不译（RU_PLAN §17.4）。只译 `text_pub`（占位/挂件已剥）。

═══ 免费路径（`[[prove-free-path-before-quoting]]`）═══
zh 两版白送的 15,261 段已全收（3.85% 词元）；同一句词源跨版一字不差的借用**不存在**（en 是英文、ru 是俄文、zh 是中文，
三版文字不同）；fr/vi/pl 的词源是第四语言，译它们也要花钱且是二手。⇒ 剩下只能买。

═══ 控制组（`[[control-must-cover-every-output-field]]`：点名点到字段）═══
① 定题（答案确定）② 逐 id ＋ **字段**点名 ③ 形状：空／没有汉字／译文里的俄语串原文没有
④ 行数对齐 ⑤ 🆕 **词源特有：拟构形式（`*voda`）一个都不许丢** —— 词源的骨头就是这些形式，丢一个就是错词源，而形状检查看不见它
"""
import argparse
import asyncio
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import ds_batch                                   # noqa: E402
from pipeline.translate_examples import (_CYR_WORD, _HAN, _stem, already,   # noqa: E402
                                         normalize_zh, pick_slice)

OUT = paths.WORK / "etym_zh"
PER_BATCH = 8           # ru 段 p90 526、p99 1,199 字符 —— 比例句长得多
F = lambda n: format(n, ",")                                    # noqa: E731
SRC_MODEL = "model:deepseek-v4-flash"

SYS = """你是俄汉词典的词源编辑。把给定的俄语词的**词源说明**（英语或俄语写成）译成简体中文。

输入是一个 JSON 对象：键是编号，值含 w（这个俄语词头）、t（词源原文）。
输出**同样的键**，值是 {"zh": "中文译文"}。键一个不许少、不许多、不许改。

规矩：
1. 🔴 **词形一个字母都不许改、不许丢、不许翻译**：俄语/其他语言的词形、拟构形式（带 * 的，如 *voda、*h₁én）、
   转写（括号里的拉丁字母）一律**原样照抄**，包括重音符和特殊字母。译的只是叙述部分。
2. 词形后面的释义（英文 “to go”、俄文 «вестник»）译成中文，用中文引号：“去”、“使者”。
3. 语言名译成中文通行译名。俄语缩写对照（照这张表，不要自己猜）：
   праслав. 原始斯拉夫语｜праиндоевр. 原始印欧语｜ст.-слав. 古教会斯拉夫语｜церк.-слав. 教会斯拉夫语｜
   др.-русск. 古俄语｜русск. 俄语｜укр. 乌克兰语｜белор. 白俄罗斯语｜болг. 保加利亚语｜сербохорв. 塞尔维亚-克罗地亚语｜
   словенск. 斯洛文尼亚语｜чешск./чеш. 捷克语｜словацк. 斯洛伐克语｜польск. 波兰语｜в.-луж. 上索布语｜н.-луж. 下索布语｜
   лит. 立陶宛语｜латышск. 拉脱维亚语｜др.-прусск. 古普鲁士语｜др.-инд. 古印度语｜авест. 阿维斯陀语｜
   греч./др.-греч. 古希腊语｜лат. 拉丁语｜гот. 哥特语｜др.-в.-нем. 古高地德语｜нем. 德语｜франц. 法语｜англ. 英语｜
   ит. 意大利语｜исп. 西班牙语｜араб. 阿拉伯语｜тур. 土耳其语｜тюрк. 突厥语｜ср. 比较｜сущ. 名词｜прил. 形容词｜гл. 动词｜
   м. 阳性｜ж. 阴性｜ср. р. 中性｜мн. 复数｜род. п. 属格。英文里的 Proto-Slavic 原始斯拉夫语、Old East Slavic 古东斯拉夫语、
   Old Church Slavonic 古教会斯拉夫语、Proto-Indo-European 原始印欧语、Proto-Balto-Slavic 原始波罗的-斯拉夫语。
4. 「Inherited from」译「继承自」，「Borrowed from」译「借自」，「Calque of」译「仿译自」，「Cognate with」译「同源词有」，
   「Происходит от」译「源自」，「от которого в числе прочего произошли」译「由此还派生出」。
5. 「Использованы данные словаря М. Фасмера. См. Список литературы.」译「参考了 M. 瓦斯默词典的资料。见参考文献。」
   （Черных 译「切尔内赫」、Шанский 译「尚斯基」）。
6. 🔴 **行数必须与原文一致**，用 \\n 分隔；原文一行的译文也只一行。
7. 只译原文本身，不加解释、不加按语、不补充原文没有的词源信息。吃不准的直译，**不要编造**。"""

PROBE = {
    "__c1": {"w": "вода", "t": "Inherited from Old East Slavic вода (voda), from Proto-Slavic *voda.",
             "want": ("原始斯拉夫语",), "keep": ("*voda", "вода")},
    "__c2": {"w": "беда", "t": "Происходит от праслав. *běda, от которого в числе прочего произошли: укр. біда́.",
             "want": ("原始斯拉夫语", "乌克兰语"), "keep": ("*běda", "біда́")},
    "__c3": {"w": "бюро", "t": "Borrowed from French bureau.", "want": ("法语",), "keep": ("bureau",)},
    "__c4": {"w": "кот", "t": "От праслав. *kotъ.\nИспользованы данные словаря М. Фасмера. См. Список литературы.",
             "want": ("瓦斯默",), "keep": ("*kotъ",), "lines": 2},
}
# 拟构形式与引用的外语词形：`*` 起头的串（到空白/逗号/括号为止）
_STAR = re.compile(r"\*[^\s,;:)(«»\"“”]+")


def gap_rows(con):
    """范围 A：没有中文词源的词形，其 en／ru 版可出版段 → [(etymology_id, 词头, 出版正文)]。"""
    return list(con.execute("""
        SELECT y.id, d.word, COALESCE(y.text_pub, y.text)
        FROM etymology y JOIN dict d ON d.id = y.word_id
        WHERE y.hidden = 0 AND y.src IN ('en-edition', 'ru-edition')
          AND NOT EXISTS (SELECT 1 FROM etymology z WHERE z.word_id = y.word_id AND z.hidden = 0
                          AND z.src LIKE 'zh-%')
          AND NOT EXISTS (SELECT 1 FROM etymology_gloss g WHERE g.etymology_id = y.id AND g.lang = 'zh')
        ORDER BY y.id"""))


def build(rows, per=None):
    per = per or PER_BATCH
    batches, meta = [], []
    for i in range(0, len(rows), per):
        chunk = rows[i:i + per]
        items = [(str(eid), {"w": w, "t": t}) for eid, w, t in chunk]
        ck = list(PROBE)[i // per % len(PROBE)]
        items.insert(len(items) // 2, (ck, {x: PROBE[ck][x] for x in ("w", "t")}))
        batches.append(dict(items))
        meta.append([(k, int(k) if k.isdigit() else k) for k, _v in items])
    return batches, meta


def judge(eid, w, t, zh):
    """一条答案 → None（可以落库）或原因。审计与回收**同一套**，只写这一份。"""
    if zh is None:
        return "没回来（id 或 zh 字段缺）"
    nl = len(t.split("\n"))
    if not zh.strip():
        return "空"
    if not _HAN.search(zh):
        return "没有一个汉字"
    if nl != len(normalize_zh(zh, nl).split("\n")):
        return "行数不对"
    lost = [s for s in _STAR.findall(t) if s not in zh]
    if lost:
        return "丢了拟构形式"
    src_st = {_stem(x) for x in _CYR_WORD.findall(t)} | {_stem(w or "")}
    if any(len(x) > 2 and _stem(x) not in src_st for x in _CYR_WORD.findall(zh)):
        return "译文里的俄语串原文没有（疑似幻觉）"
    return None


def _answers(path):
    got = {}
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:                    # noqa: BLE001
                continue
            got.setdefault(d.get("id"), d.get("zh"))
    return got


def audit(path, rows, ntok, peak):
    got = _answers(path)
    want = {r[0] for r in rows}
    print("\n═══ 控制组 ═══")
    bad_c = []
    for k, v in PROBE.items():
        a = got.get(k)
        if a is None:
            bad_c.append((k, "没回来"))
            continue
        a = normalize_zh(a, len(v["t"].split("\n")))
        if not any(x in a for x in v["want"]):
            bad_c.append((k, "答成 %r（该含 %s）" % (a, "/".join(v["want"]))))
        lost = [x for x in v["keep"] if x not in a]
        if lost:
            bad_c.append((k, "🔴 词形没原样保留：%s" % lost))
        if v.get("lines") and len(a.split("\n")) != v["lines"]:
            bad_c.append((k, "行数 %d ≠ %d" % (len(a.split("\n")), v["lines"])))
    print("   %s 定题对齐        %d/%d" % ("✅" if not bad_c else "🔴", len(PROBE) - len({k for k, _ in bad_c}),
                                       len(PROBE)))
    for k, why in bad_c:
        print("      🔴 %s %s" % (k, why))
    miss = want - set(got)
    nozh = sorted(i for i in want & set(got) if not got[i])
    print("   %s 逐 id 点名       回来 %s / 要 %s（丢 %s）" % ("✅" if not miss else "🔴", F(len(want & set(got))),
                                                       F(len(want)), F(len(miss))))
    print("   %s 字段点名（zh）    缺 %s" % ("✅" if not nozh else "🔴", F(len(nozh))))
    bad, eg = collections.Counter(), collections.defaultdict(list)
    for eid, w, t in rows:
        if eid not in got or not got[eid]:
            continue
        why = judge(eid, w, t, got[eid])
        if why:
            bad[why] += 1
            if len(eg[why]) < 4:
                eg[why].append((w, t[:60].replace("\n", "⏎"), got[eid][:60].replace("\n", "⏎")))
    n = len(want & set(got))
    print("   %s 形状             坏 %d / %s" % ("✅" if not bad else "⚠️", sum(bad.values()), F(n)))
    for k, v in bad.most_common():
        print("      ⚠️ %-30s %d" % (k, v))
        for x in eg[k]:
            print("           %-14s %-60s → %s" % x)
    if ntok:
        print("\n═══ 单价（%s）═══" % ("🔴 高峰全价" if peak else "✅ 空闲半价"))
        print("   总 token %s ／ 成功 %s 条 ／ %s 字符 ⇒ **每条 %.1f token、每字符 %.3f token**" % (
            F(ntok), F(n), F(sum(len(r[2]) for r in rows)), ntok / max(n, 1),
            ntok / max(1, sum(len(r[2]) for r in rows))))
    print("\n■ 抽样（人眼看）")
    import random
    for eid, w, t in random.Random(7).sample([r for r in rows if got.get(r[0])], min(16, n)):
        print("   %-16s %s" % (w, t[:150].replace("\n", " ⏎ ")))
        print("   %-16s → %s" % ("", got[eid][:150].replace("\n", " ⏎ ")))


def run(rows, tag, conc, allow_peak, retry_rounds=3, per=None):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("%s.jsonl" % tag)
    peak = ds_batch.is_peak()
    ds_batch.announce_window()
    if peak and not allow_peak:
        raise SystemExit("🔴 现在是 DeepSeek 高峰（全价）—— 不开跑。真要跑加 --allow-peak")
    ntok, per = 0, per or PER_BATCH
    for rnd in range(retry_rounds + 1):
        done = already(path)
        todo = [r for r in rows if r[0] not in done]
        if not todo:
            break
        if rnd:
            per = max(1, per // 2)
            print("■ 第 %d 轮补跑：丢了 %s 条，批大小对半到 %d" % (rnd, F(len(todo)), per))
        b, m = build(todo, per)
        ntok += asyncio.run(ds_batch.run(SYS, b, m, path, conc=conc))
    done = already(path)                      # 🔴 读一次（6d 那一跤：列表推导里每行重读整个文件）
    left = [r for r in rows if r[0] not in done]
    if left:
        print("🔴🔴 对半切 %d 轮之后仍有 %s 条没回来 —— 大声放弃：%s" % (retry_rounds, F(len(left)), [r[0] for r in left[:20]]))
    (OUT / ("%s.tokens.json" % tag)).write_text(json.dumps({"tokens": ntok, "peak": peak}), encoding="utf-8")
    return path, ntok, peak


def load(tags=("redo", "all"), dry=True):
    import dbtool
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = {r[0]: r for r in gap_rows(con)}
    got = {}
    for tag in tags:
        for k, v in _answers(OUT / ("%s.jsonl" % tag)).items():
            if isinstance(k, int) and v and k not in got:
                got[k] = v
    ins, why, eg = [], collections.Counter(), collections.defaultdict(list)
    for eid, (_i, w, t) in rows.items():
        r = judge(eid, w, t, got.get(eid))
        if r:
            why[r] += 1
            if len(eg[r]) < 6:
                eg[r].append((eid, w, t[:50].replace("\n", "⏎"), (got.get(eid) or "")[:50].replace("\n", "⏎")))
            continue
        ins.append((eid, "zh", normalize_zh(got[eid], len(t.split("\n"))), SRC_MODEL))
    print("■ 待译 %s 段 ／ 可落库 %s ／ 不落库 %s" % (F(len(rows)), F(len(ins)), F(sum(why.values()))))
    for k, v in why.most_common():
        print("   %-30s %8s" % (k, F(v)))
        for x in eg[k]:
            print("        %s %-14s %-50s → %s" % x)
    if dry:
        print("\n(干跑。确认后 --load --apply)")
        return
    con.close()
    with dbtool.session("etymology-zh-load", expect={"#etymology_gloss": len(ins)},
                        invalidates=["etymology_gloss"]) as s:
        s.executemany("INSERT INTO etymology_gloss(etymology_id,lang,text,src) VALUES (?,?,?,?)", ins)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=float)
    ap.add_argument("--conc", type=int, default=100)
    ap.add_argument("--allow-peak", action="store_true")
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--tokens", type=int, default=0)
    ap.add_argument("--redo", action="store_true", help="形状不过／没回来的单条重发一次，进 redo.jsonl")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.load:
        return load(dry=not a.apply)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = gap_rows(con)
    con.close()
    tag = "all"
    if a.slice:
        rows = pick_slice(rows, a.slice)
        tag = "slice%g" % a.slice
    print("■ 待译 %s 段 ／ %s 字符（%s）" % (F(len(rows)), F(sum(len(r[2]) for r in rows)), tag))
    if a.count:
        return
    if a.audit:
        audit(OUT / ("%s.jsonl" % tag), rows, a.tokens, False)
        return
    if a.redo:
        got = _answers(OUT / "all.jsonl")
        redo = [r for r in rows if judge(r[0], r[1], r[2], got.get(r[0])) not in (None, "没有一个汉字")]
        print("■ 单条重发 %s 段" % F(len(redo)))
        path, ntok, peak = run(redo, "redo", a.conc, a.allow_peak, per=1)
        audit(path, redo, ntok, peak)
        return
    path, ntok, peak = run(rows, tag, a.conc, a.allow_peak)
    audit(path, rows, ntok, peak)


if __name__ == "__main__":
    main()
