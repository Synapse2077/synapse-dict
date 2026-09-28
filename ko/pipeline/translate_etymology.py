#!/usr/bin/env python3
"""K36：把 38,796 条词源正文译成中文。2026-09-27。

═══ 盘子 ═══
    `etymology` **38,796** 条，落在 33,161 个词形上，**100% 是英文**（`edition` 全是
    `en-edition`）。释义译了、例句译了（中文覆盖 100.00%），**偏偏词源一条没译**。

🔴 **用户 2026-09-27 在 `아름답다` 页面上看见它**：
    「EN First attested in the Seokbo sangjeol (釋譜詳節 / 석보상절), 1447, as
      Middle Korean 아ᄅᆞᆷ〮답다〮 (Yale: àlóm-tàptá), perhaps from …」
    原话是「这是什么啊，我有点看不懂」。⇒ 阶段 7 的验收只问了「到不到得了读者」，
    **没问「读者读不读得懂」** —— 与 **K10** 同一个签名：
    数的是「有值的行」不是「有信息的行」。

═══ 🔴 三条免费路径，全部实测过（`[[prove-free-path-before-quoting]]`）═══
① **另外四个版本有没有词源正文** —— 逐行扫过四份 dump（不是引旧结论）：
     英文版 38,796 ／ 韩文版 **0** ／ 日文版 **0** ／ 中文简 **0** ／ 中文繁 **0**
   ⇒ 不是「少」，是**一条都没有**。没有白送的中文词源。
② **模板替换** —— 遮掉变量位之后 30 个结构覆盖 **58.6%**
   （最大的 `Sino-Korean word from 漢.` 7,257 条 ＝ 18.7%）。**有意不做**：
   42.5% 的行里嵌着英文释义（引号里的 `“privateness; non-publicness”`），
   模板替换救不了那一部分；而一半模板一半模型会造出读起来不齐的两种文风。
   省下的约 4 元，代价是建一套判据 ＋ 验它 —— 今天我自己写宽/写偏判据已经四次。
③ 🔴 **拿我们自己的中文释义替掉嵌入的英文释义** —— **实测会错，当场否掉**。
   `词 (罗马字, “英文释义”)` 单元 21,094 个，其中那个词我们有中文释义的 8,743（41.4%），
   但它是**按词形认**的：
       源头 `란 (ran, “that/what is called”)`   我们的 `란` ＝「蛋」（卵）
       源头 `하다 (hada, “to do, to be”)`        我们的 ＝「做；泛指几乎任何动作，尤指」（被截断）
   ⇒ 忽略了词源说的是**哪个义项**，正是 **K20**（谚文那一页是一个「词形」不是一个「词」）
     的签名。`[[criteria-from-meaning-not-form]]`。

═══ 报价（用户 2026-09-27「现在是低谷期，随便花」）═══
词源正文 2,470,298 字，算上译文估 3.83 M 字。
按**阶段 6d 的真实账单**折算（1,360,311 字 → 2,589,486 token → 6.9 元，即 0.051 元/万字）：
    ≈ **19.4 元**（半价窗口；北京时间周日 ⇒ `announce_window()` 实测确认空闲）

═══ 🔴 这不是「译例句」那个任务，prompt 不能照抄 ═══
阶段 6d 译的是**例句**（要自然的中文句子）；这一步译的是**词源考据**，
里面有大量**被引用的语言形式**（中世韩语、古谚文、汉字、罗马字），
它们是**证据不是内容** —— 译掉或规范化掉就等于毁掉这条词源。
⚠️ 尤其是古谚文：`아ᄅᆞᆷ〮` 里有结合型字母（U+1105/119E/11B7）和**声点**（U+302E）。
   模型很容易「顺手」把它规范成 `아름` —— 那是**篡改 15 世纪的文献形式**。
   ⇒ 控制组专门有一条逐字节验它。

═══ 控制组对着五种坏法（`[[control-must-cover-every-output-field]]`）═══
  · 错位／静默丢批 —— 每批注入定题 ＋ 回收时逐 id 点名
  · 🔴 **引用形式被规范化** —— 定题里放 `아ᄅᆞᆷ〮`，答案里必须逐字节还在
  · 🔴 **对冲语被抹掉** —— `perhaps … but this is uncertain` 译完必须还带对冲词
        （抹掉它就把一个假说变成了断言）
  · 🔴 **嵌入的英文释义没译** —— 引号里的 `“big”` 必须变成中文
  · 🔴 **上下文泄漏** —— 给词头当消歧材料，而定题的词头与正文无关

跑（在仓库根）：
    python3 -u ko/pipeline/translate_etymology.py --create      # 建 etymology_gloss 表
    python3 -u ko/pipeline/translate_etymology.py --slice 0.01  # 1% 切片，实测单价
    python3 -u ko/pipeline/translate_etymology.py --conc 60     # 正式跑
    python3 -u ko/pipeline/translate_etymology.py --load --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import asyncio
import collections
import hashlib
import json
import re
import sqlite3

import dbtool
import ds_batch
import paths

f = lambda n: format(n, ",")
OUT = paths.WORK / "etymology_zh"
SRC_MODEL = "model:deepseek-v4-flash"
CHAR_BUDGET = 2600          # 每批的源文字符预算（行长差 70 倍，按条数切会切出巨批）
MAX_PER_BATCH = 24

# 引用形式：韩语（含古谚文结合型字母与声点）、汉字
KO_RUN = re.compile(r"[가-힣ᄀ-ᇿꥠ-꥿ힰ-퟿][가-힣ᄀ-ᇿꥠ-꥿ힰ-퟿〮〯]*")
HAN_RUN = re.compile(r"[一-鿿㐀-䶿]+")
LATIN = re.compile(r"[A-Za-z]{3,}")
HEDGE_EN = re.compile(r"\b(perhaps|possibly|probably|may be|might|uncertain|unclear|"
                      r"apparently|presumably|likely|disputed|unknown origin)\b", re.I)
HEDGE_ZH = ("可能", "或许", "也许", "大概", "推测", "不确定", "不明", "存疑", "未定",
            "有争议", "似", "疑", "据说", "或作")

SYS = """你是韩汉词典的词源编辑。把给定的英文词源考据译成中文。

输入是一个 JSON 对象：键是词源编号，值含 t（英文词源正文），可能还有 w（这条词源所属的词头）。
输出**同样的键**，值是 {"zh": "中文译文"}。键一个不许少、不许多、不许改。

🔴 最要紧的一条：**被引用的语言形式一个字符都不许改。**
   词源里的韩语词形、中世韩语、古谚文、汉字、罗马字转写，都是**证据**，
   必须原样抄进译文，包括：
   - 古谚文的字母与**声点**（例如 아ᄅᆞᆷ〮 里的 ᄅ ᆞ ᆷ 和那个小点），
     **不许规范成现代写法**（不许把 아ᄅᆞᆷ〮 写成 아름）
   - 罗马字上的声调符号（àlóm 不许写成 alom）
   - 汉字的字形（釋 不许改成 释，靑 不许改成 青）

其余规矩：
1. 引号里的**英文释义**要译成中文：`물 (mul, “water”)` → `물（mul，「水」）`。
   引号用中文引号「」，括号用中文括号（）。
2. **对冲语必须保留**：perhaps／possibly／uncertain／disputed 这类词，
   译成「可能」「或许」「尚不确定」「有争议」。
   🔴 抹掉对冲语就是把一个假说说成了定论 —— 这比漏译严重。
3. 术语按这一套译，不要自创：
   Middle Korean＝中世韩语｜Early Modern Korean＝近代韩语｜Old Korean＝古韩语
   Middle Chinese＝中古汉语｜Old Chinese＝上古汉语｜Proto-Koreanic＝原始韩语族
   Sino-Korean word＝汉字词｜native Korean＝固有词｜onomatopoeic＝拟声词
   nativisation＝韩化｜orthographic borrowing＝借形｜calque＝仿译
   attested＝见于（文献）｜reading＝读法｜suffix＝后缀｜prefix＝前缀
4. 文献名：原文给了汉字的用《》括汉字形，谚文与罗马字原样保留。
   例：`the Seokbo sangjeol (釋譜詳節 / 석보상절), 1447` → `1447 年《釋譜詳節》（석보상절）`
5. **只输出译文**。不要加「译：」「意思是」这类引导语，不要解释，不要补充原文没有的考据。
6. 原文用 `+` 连接构词成分的，译文也用 `+`，不要改成「加」。
7. w 只是帮你消歧的参考，**不许出现在输出里**（除非它本来就在 t 里）。
8. 吃不准的直译，**不要编造**。原文说「来源不明」就写「来源不明」。"""

# 🔴 控制组。五条各对着一种坏法，`want`/`bad` 都是**常量**（锚在会变的行文上过不了夜）。
PROBE = {
    # ① 最常见的模板 ＋ 术语
    "__c1": {"t": "Sino-Korean word from 水 (su, “water”).",
             "want": ("汉字词",), "want2": ("水",), "bad": ()},
    # ② 🔴 古谚文与声点必须逐字节还在；罗马字的声调符号也不许掉
    "__c2": {"t": "First attested as Middle Korean 아ᄅᆞᆷ〮 (Yale: àlóm) in 1447.",
             "want": ("아ᄅᆞᆷ〮",), "want2": ("àlóm",), "bad": ("아름",)},
    # ③ 🔴 对冲语不许抹掉
    "__c3": {"t": "Perhaps from 물 (mul, “water”), but this is uncertain.",
             "want": HEDGE_ZH, "want2": ("水",), "bad": ()},
    # ④ 🔴 引号里的英文释义必须变成中文
    "__c4": {"t": "From 큰 (keun, “big”) + 집 (jip, “house”).",
             "want": ("大",), "want2": ("房", "屋", "家"), "bad": ("big", "house")},
    # ⑤ 🔴 上下文（w）不许漏进输出：w 是「自行车」而正文讲的是水
    "__c5": {"t": "From 물 (mul, “water”).", "w": "자전거",
             "want": ("水",), "want2": ("물",), "bad": ("自行车", "自行車", "자전거")},
}


def gap_rows(con):
    """缺中文的词源行。**口径只写一份。**"""
    return con.execute("""
        SELECT e.id, d.word, e.text
          FROM etymology e JOIN dict d ON d.id = e.word_id
         WHERE NOT EXISTS (SELECT 1 FROM etymology_gloss g
                            WHERE g.etymology_id = e.id AND g.lang = 'zh')
         ORDER BY e.id
    """).fetchall()


def pick_slice(rows, frac):
    """按主键的稳定哈希抽 —— **不是 `rows[::n]`**（那是先截断再抽）。"""
    k = int(frac * 0xFFFF)
    return [r for r in rows
            if int(hashlib.md5(str(r[0]).encode()).hexdigest()[:4], 16) < k]


def build(rows):
    """按**字符预算**切批，不按条数。

    🔴 词源行长差 70 倍（中位 44 字、最长 3,247 字、>400 字的 344 条）。
       按固定条数切会切出 2 万字的巨批 —— 那种批最容易整批答歪或超时，
       而 `[[retry-must-converge-or-drop-loud]]` 说重试要收敛，巨批收敛不了。
    """
    batches, meta = [], []
    cur, m, size = {}, [], 0
    order = list(PROBE)

    def flush():
        if not cur:
            return
        ck = order[len(batches) % len(order)]
        cur[ck] = {x: PROBE[ck][x] for x in ("t", "w") if x in PROBE[ck]}
        m.append((ck, ck))
        batches.append(dict(cur))
        meta.append(list(m))
        cur.clear()
        m.clear()

    for eid, word, text in rows:
        if cur and (size + len(text) > CHAR_BUDGET or len(cur) >= MAX_PER_BATCH):
            flush()
            size = 0
        d = {"t": text}
        if word:
            d["w"] = word
        cur[str(eid)] = d
        m.append((str(eid), eid))
        size += len(text)
    flush()
    return batches, meta


def _quoted_en(t):
    """原文引号里的英文释义片段（用来查「译完还是英文」）。"""
    return [x for x in re.findall(r"[“\"]([^”\"]{2,})[”\"]", t) if LATIN.search(x)]


def audit(path, rows, ntok, peak):
    got = {}
    for line in path.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        got[str(d["id"])] = d.get("zh")

    print("\n═══ 控制组（五条，各对着一种坏法）═══")
    bad = []
    for k, v in PROBE.items():
        ans = got.get(k)
        if ans is None:
            bad.append((k, "没回来"))
            continue
        for key in ("want", "want2"):
            need = v.get(key) or ()
            if need and not any(x in ans for x in need):
                bad.append((k, "答成 %r —— 该含 %s" % (ans[:70], "/".join(need[:4]))))
        for x in v.get("bad", ()):
            if x in ans:
                bad.append((k, "🔴 不该出现的东西出现了：%r（答 %r）" % (x, ans[:60])))
    print("   %s 定题 %d/%d" % ("✅" if not bad else "🔴", len(PROBE) - len(bad), len(PROBE)))
    for k, why in bad:
        print("      🔴 %s %s" % (k, why))

    want = {str(r[0]) for r in rows}
    back = {k for k in got if not k.startswith("__")}
    lost = want - back
    print("   %s 逐 id 点名   回来 %s / 要 %s（丢 %s）"
          % ("✅" if not lost else "🔴", f(len(back & want)), f(len(want)), f(len(lost))))

    shape = collections.Counter()
    examples = collections.defaultdict(list)

    def note(k, eid, src, ans):
        shape[k] += 1
        if len(examples[k]) < 3:
            examples[k].append((eid, src[:60], (ans or "")[:60]))

    for eid, word, text in rows:
        a = got.get(str(eid))
        if a is None:
            continue
        if not a.strip():
            note("空", eid, text, a)
            continue
        # 🔴 引用形式：原文出现过的韩语/古谚文 token 必须原样还在译文里
        for tok in set(KO_RUN.findall(text)):
            if len(tok) >= 1 and tok not in a:
                note("🔴 韩语/古谚文形式丢了或被改了", eid, text, a)
                break
        for tok in set(HAN_RUN.findall(text)):
            if tok not in a:
                note("⚠️ 汉字形式丢了（可能是简繁被改）", eid, text, a)
                break
        # 🔴 引号里的英文释义译完还是英文
        for q in _quoted_en(text):
            if q in a:
                note("🔴 引号里的英文释义原样留着", eid, text, a)
                break
        # 🔴 对冲语被抹掉
        if HEDGE_EN.search(text) and not any(h in a for h in HEDGE_ZH):
            note("🔴 对冲语被抹掉（假说变成了断言）", eid, text, a)
        # 残留英文散文（罗马字是允许的，所以只看**长串**且原文里没有的）
        for w2 in set(LATIN.findall(a)):
            if w2 not in text and len(w2) >= 5:
                note("⚠️ 混进原文没有的英文词", eid, text, a)
                break
        if len(a) < 0.25 * len(text):
            note("⚠️ 译文过短（不足原文 1/4）", eid, text, a)
        if len(a) > 2.5 * len(text) + 20:
            note("⚠️ 译文过长（超原文 2.5 倍）", eid, text, a)

    n = len(rows)
    print("   %s 形状  坏 %s / %s" % ("✅" if not shape else "⚠️", f(sum(shape.values())), f(n)))
    for k, v in shape.most_common():
        print("      %-40s %s" % (k, f(v)))
        for eid, s, a in examples[k]:
            print("          [%s] %s\n               → %s" % (eid, s, a))

    print("\n═══ 单价（%s）═══" % ("🔴 高峰全价" if peak else "✅ 空闲半价"))
    ok = len(back & want)
    print("   总 token %s ／ 成功 %s 条 ⇒ **每条 %.1f token**"
          % (f(ntok), f(ok), ntok / max(ok, 1)))
    print("   ⚠️ 折算到全量乘的是**条数**，不是切片比例")

    print("\n■ 抽样（人眼看 —— 形状检查看不出「译错了」）")
    for eid, word, text in rows[:10]:
        a = got.get(str(eid)) or ""
        print("   %-8s %s\n            → %s" % (word[:8], text[:88], a[:88]))


def create_table():
    """建 `etymology_gloss`。schema 声明已同步进 `build_v3_schema.py`（R21 盯着）。"""
    con = sqlite3.connect(paths.DB)
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "etymology_gloss" in have:
        print("■ `etymology_gloss` 已存在，不重建")
    else:
        con.execute("""CREATE TABLE etymology_gloss (
             etymology_id INTEGER NOT NULL,
             lang         TEXT NOT NULL,
             text         TEXT NOT NULL,
             src          TEXT,
             PRIMARY KEY(etymology_id, lang))""")
        con.commit()
        print("■ 已建 `etymology_gloss`")
    print("   行数 %d" % con.execute("SELECT COUNT(*) FROM etymology_gloss").fetchone()[0])
    con.close()


def load(dry=True):
    got = {}
    for p in sorted(OUT.glob("*.jsonl")):
        for line in p.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            k, zh = d.get("id"), (d.get("zh") or "").strip()
            if not k or str(k).startswith("__"):
                continue
            try:
                k = int(k)
            except (TypeError, ValueError):
                continue
            if zh:
                got[k] = zh
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    need = {r[0] for r in gap_rows(con)}
    con.close()
    rows = [(k, v) for k, v in got.items() if k in need]
    print("■ 答案文件里 %s 条；其中仍在缺口里的 %s 条" % (f(len(got)), f(len(rows))))
    if len(got) - len(rows):
        print("   （%s 条已经不在缺口里 —— 上一轮已落库，不重复写）" % f(len(got) - len(rows)))
    if dry:
        print("\n（干跑。确认后 --load --apply）")
        return
    with dbtool.session(
            "ko-load-etymology-zh",
            expect={"#etymology_gloss": len(rows)},
            invalidates=[
                "🔴 展示层要改成**优先印中文词源**、英文原文降为可展开的证据 —— "
                "不改的话这 %s 条译文一个读者都看不到（K26 那条的形状）" % f(len(rows)),
                "阶段 8 的闸：词源中文覆盖率的下限要在**确认落点之后**再设",
            ]) as s:
        for i in range(0, len(rows), 20000):
            s.executemany(
                "INSERT OR IGNORE INTO etymology_gloss (etymology_id, lang, text, src)"
                " VALUES (?,'zh',?,?)",
                [(k, v, SRC_MODEL) for k, v in rows[i:i + 20000]])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n■ 写后回核（从库里重算）")
    print("   模型译文行        %9s" % f(q(
        "SELECT COUNT(*) FROM etymology_gloss WHERE lang='zh' AND src='%s'" % SRC_MODEL)))
    print("   仍缺中文的词源行  %9s" % f(q(
        "SELECT COUNT(*) FROM etymology e WHERE NOT EXISTS("
        "SELECT 1 FROM etymology_gloss g WHERE g.etymology_id=e.id AND g.lang='zh')")))
    print("   词源中文覆盖率    %8.2f%%" % q(
        "SELECT 100.0*SUM(CASE WHEN EXISTS(SELECT 1 FROM etymology_gloss g "
        "WHERE g.etymology_id=e.id AND g.lang='zh') THEN 1 ELSE 0 END)/COUNT(*) "
        "FROM etymology e"))
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--slice", type=float, default=0.0)
    ap.add_argument("--conc", type=int, default=60)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    if a.create:
        create_table()
        return
    if a.load:
        load(dry=not a.apply)
        return
    peak = ds_batch.announce_window()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = gap_rows(con)
    con.close()
    if a.slice:
        rows = pick_slice(rows, a.slice)
    OUT.mkdir(parents=True, exist_ok=True)
    tag = a.tag or ("slice" if a.slice else "all")
    path = OUT / ("%s.jsonl" % tag)
    batches, meta = build(rows)
    chars = sum(len(r[2]) for r in rows)
    print("\n■ 词源 → zh：%s 条 / %s 字，%s 批（字符预算 %d，每批另加 1 条定题）"
          % (f(len(rows)), f(chars), f(len(batches)), CHAR_BUDGET))
    if not rows:
        return
    ntok = asyncio.run(ds_batch.run(SYS, batches, meta, path,
                                    mode="flash", conc=a.conc, every=5))
    tp = path.with_suffix(".tokens.json")
    prev = json.loads(tp.read_text()) if tp.exists() else {"tok": 0, "runs": []}
    prev["tok"] += ntok
    prev["runs"].append({"tok": ntok, "n": len(rows), "peak": peak})
    tp.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
    audit(path, rows, prev["tok"], peak)


if __name__ == "__main__":
    main()
