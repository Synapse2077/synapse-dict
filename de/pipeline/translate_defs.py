#!/usr/bin/env python3
"""阶段 1.5b — 德语原文释义译成中文 → `sense_gloss(lang='zh')`。2026-09-03。

    待译义项  125,057  （1.5a 收进来的德语原文，均 61 字符）
    已有中文  135,699  （七月建库 + 阶段 2a 模板 + 中文版白送 10,122，**都不重翻**）
    另有       72 条只有英文没有德语原文 —— 本族够不着，单独记账

═══ 🔴 池子的判据以**库**为准，不以扫描侧为准 ═══
1.5a 的脚本报的付费池是 119,606，比真值少 5,523。它从扫描侧算：
一个词只要拿到过一条免费中文，**整个词**就被踢出付费池，可它别的义项还空着。
⇒ 这里直接问库：「有德语原文、且没有中文」。`[[measure-landing-not-source]]`

═══ 🔴 判据跟着任务走，不是跟着代码复用 ═══
从 pt `translate_defs.py` 移植，但有四条是德语独有、pt 那版没有的：

  ① **习语不许照定义直译**。`'s Maul halten` 的德语释义是一整句解释
     （"keine Laute mehr aus seinem Mund geben"），要的是「闭嘴」，
     不是「不再从嘴里发出声音」。`[[translation-model-has-no-prompt-channel]]`
     里 `lèche-vitrine`→「爱慕虚荣」就是这条没传进去造成的。
  ② **多词动词**：`Dank sagen` / `Halt machen` / `ab sein` 在 `pos=v` 里，
     要给动词短语，不能给名词。
  ③ **数字构词**：`1-achsig`「单轴的」、`0,2-Liter-Flasche`「0.2 升装的瓶子」。
     德语用逗号做小数点 ⇒ 中文要换成点号。
  ④ **地名有通用中文译名**：`'s-Gravenhage` ＝ **海牙**，不是「斯格拉芬哈헤」。
     `[[ask-model-before-building-tool]]`：模型知道惯用译名，点名要求即可，
     不要自己造译写器。没有通用译名的**保留原文**，不生造音译。

═══ payload 带什么 ═══
    id     `sense.id`（**数据库主键**，不是序号）—— `[[model-answer-files-key-by-id]]`
    word   词头（同一条释义挂在不同词下，中文要跟着词走）
    pos    词性（决定给名词说法还是动词说法）
    de     德语释义原文

⚠️ **不传"仅供参考"的上下文** —— `[[context-you-give-leaks-into-output]]`：
   it 那轮把法语原文当参考传进去，母地名直接漏进了 1,583 条音译结果。
   只传必要的四样，每一样都在规则里说明了用途。

═══ 成本纪律 ═══
· 跑批走 DeepSeek，`think=False` 硬默认（`[[batch-never-enables-thinking]]`）。
· `slot_translate.announce_window()` 在发第一个请求前打出北京时间与当前是不是高峰。
  高峰＝工作日 09:00–12:00 与 14:00–18:00；其余（含整个周末）半价。
· **先跑 1% 切片实测单价**，再决定全量 —— 不拿别的语种的单价当报价。

用法（在 de/ 目录下）：
    python3 -u pipeline/translate_defs.py --slice 1200   # 1% 切片，实测单价
    python3 -u pipeline/translate_defs.py --audit
    python3 -u pipeline/translate_defs.py --read 20
    python3 -u pipeline/translate_defs.py                # 全量续跑
    python3 -u pipeline/translate_defs.py --apply
"""
import argparse
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool            # noqa: E402
import paths             # noqa: E402
import slot_translate    # noqa: E402

SRC = "model:def"
OUT = paths.WORK / "defs" / "def_zh.jsonl"
has_han = dbtool.has_han

# 德语释义比葡语长（均 61 vs 43 字符）⇒ 批小一点，免得单批出方向 token 过大
slot_translate.CHUNK = 80
slot_translate.CONC = 60

SYS = """你在把德语词典的释义翻译成中文，用于一部给中文读者的德语词典。

输入是 JSON 数组，每项有：
  `id`    标识号，**不是序号**，原样回传
  `word`  被解释的德语词
  `pos`   词性（n 名词／v 动词／adj 形容词／adv 副词／name 专名／abbrev 缩写／phr 短语／pref 词缀）
  `de`    该词这一条义项的德语释义原文

规则
1. 输出**中文释义**，不是逐字翻译。能用一个常用汉语词对应就给那个词，
   不能对应就给一句简短的解释。
2. 🔴 **词性要对上 `pos`**：`v` 给动词说法（「切开」不是「切口」），
   `n` 给名词说法，`adj` 给形容词说法（带「的」）。
   ⚠️ `pos=v` 里有多词动词（`Dank sagen`、`Halt machen`、`ab sein`），
   同样给动词说法：「道谢」「使停下」「离开、脱落」。
3. 🔴 **习语按中文的说法给，不要照着德语解释直译**。
   德语释义常常是一整句解释，你要给的是中文里对应的说法：
     `'s Maul halten` de=「keine Laute mehr aus seinem Mund geben」→「闭嘴」
     （不是「不再从嘴里发出声音」）
4. 🔴 **不要把词头本身抄回来当释义。** 如果原文只是重复了 `word`，
   说明源头没给真释义，`zh` 给空字符串。
5. 🔴 **不要输出元描述**。像「…的复数」「…的第二分词」「…的属格」「参见…」
   这类说的是语法关系不是词义，`zh` 给空字符串。
6. 专名（`pos=name`）：
   · 有**通用中文译名**的用通用译名 —— `'s-Gravenhage`→「海牙」、`München`→「慕尼黑」。
   · 姓氏、名字：`deutschsprachiger Nachname, Familienname`→「德语姓氏」、
     `männlicher Vorname`→「男性名字」、`weiblicher Vorname`→「女性名字」。
   · 行政区划照实说：`Ortsgemeinde in Rheinland-Pfalz, Deutschland`
     →「德国莱茵兰-普法尔茨州的一个市镇」。
   · **没有通用译名的地名保留原文**，不要音译生造。
7. 缩写（`pos=abbrev`）：给**展开后的意思**，不是把缩写抄回来。
   `1 Kor`→「《哥林多前书》」。原文形如 `Abkürzung für X` 时，译 X 的意思。
8. 数字与构词：德语用逗号作小数点，中文换成点号 ——
   `0,2-Liter-Flasche`→「0.2 升装的瓶子」；`1-achsig`→「单轴的」。
9. 学名、化学式、度量单位、书名缩写原样保留。
10. **不加句末标点**，不写「指」「表示」这类引导语，不加括号解释除非原文就有。
11. 原文残缺或看不出意思，`zh` 给空字符串，不要猜。

输出 JSON 数组：[{"id": <标识号>, "zh": "<中文释义>"}]
只输出 JSON，不要解释。"""

LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{3,}")
# 德语的元描述说法（`Plural von` / `Partizip II` / `Genitiv Singular`…）译过来的样子
META = re.compile(r"的复数|的单数|的属格|的与格|的宾格|的第[一二]分词|的过去分词|"
                  r"的变位|的变格|的比较级|的最高级|参见|同上|见上|这个词|该词|意思是")
TAIL = re.compile(r"[。．.!！?？；;]$")
# 德语小数逗号漏进中文（`0,2 升`）—— 规则 8 的落点
COMMA_NUM = re.compile(r"\d,\d")


def pool(con):
    """→ [{id, word, pos, de}]，只取**有德语原文且还没有中文**的义项。

    🔴 判据写在这一个地方。别处要这个池子的大小，`len(pool(con))`，
       不许另写一条 SQL —— `[[criteria-narrower-than-you-think]]` 那族的成因
       就是同一个判据在两处各写了一版，然后悄悄分叉。
    """
    rows = con.execute(
        "SELECT s.id, d.word, COALESCE(s.pos,''), g.text "
        "  FROM sense s "
        "  JOIN dict d ON d.id=s.word_id "
        "  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='de' "
        " WHERE NOT EXISTS(SELECT 1 FROM sense_gloss z "
        "                   WHERE z.sense_id=s.id AND z.lang='zh') "
        " ORDER BY s.id").fetchall()
    return [{"id": str(i), "word": w, "pos": p, "de": t} for i, w, p, t in rows]


def controls(items, got, title):
    """判据**为德语释义重写**，不从 pt 那套复用。"""
    c, ex = Counter(), {}
    seen = defaultdict(set)          # 中文 → 它对应过的**不同德语原文**

    def hit(k, a, b):
        c[k] += 1
        ex.setdefault(k, (a, b))

    n = 0
    for it in items:
        rec = got.get(it["id"])
        if not rec:
            continue
        n += 1
        z = (rec.get("zh") or "").strip()
        src, w = it["de"], it["word"]
        if not z:
            hit("留空（模型判定给不出）", "%s ← %s" % (w, src[:40]), "")
            continue
        if not has_han(z):
            hit("🔴 一个汉字都没有", w, z)
        if z.strip().lower() == w.strip().lower():
            hit("🔴 把词头原样抄回来了", w, z)
        if META.search(z):
            hit("🔴 元描述当释义（说的是语法关系不是词义）", w, z)
        if TAIL.search(z):
            hit("🔴 带句末标点（释义是短语不是句子）", w, z)
        if COMMA_NUM.search(z):
            hit("🔴 德语小数逗号漏进中文（规则 8）", src[:40], z)
        if len(LATIN.findall(z)) >= 2 and has_han(z):
            hit("残留德语（≥2 个拉丁词，专名保留是允许的）", w, z)
        if len(z) > max(40, len(src)):
            hit("比原文还长", src[:40], z[:40])
        seen[z].add(src)

    # 🔴 泛化判据必须按「**不同的德语原文**」算，不能按「不同的词」算。
    #    pt 那版查的是「一条中文对 >3 个不同词」—— 搬到德语会**整族误报**：
    #    `deutschsprachiger Nachname, Familienname` 这**一句**德语原文就挂着
    #    1,534 个不同的姓，它们本来就该共用「德语姓氏」这一个中文。
    #    真正的泛化是「**不同的**德语原文被压成同一个中文」。
    dup = sum(len(v) for v in seen.values() if len(v) > 3)
    n = max(n, 1)
    print("\n══ %s（%s 条）══" % (title, format(n, ",")))
    for k, v in c.most_common():
        print("  %-40s %7s  %5.2f%%" % (k, format(v, ","), 100.0 * v / n))
        a, b = ex[k]
        print("        %-40s → %s" % (str(a)[:40], str(b)[:40]))
    print("  %-40s %7s  %5.2f%%" % ("一个中文对 >3 条不同德语原文（疑似泛化）",
                                    format(dup, ","), 100.0 * dup / n))
    hard = [k for k in c if k.startswith("🔴") and c[k] > 0.02 * n]
    print("  %s" % ("🔴 硬闸红了（>2%）：" + "；".join(hard) if hard
                    else "✅ 硬闸过（每条 🔴 都 ≤2%）"))
    return not hard


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int, default=0)
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = pool(con)
    con.close()
    got = slot_translate.done_keys(OUT, land="id")
    print("■ 待译义项 %s ｜ 已译 %s ｜ 还差 %s"
          % (format(len(items), ","), format(len(got), ","),
             format(sum(1 for i in items if i["id"] not in got), ",")))

    want = (random.Random(1).sample(items, min(a.slice, len(items)))
            if a.slice else items)
    if not (a.audit or a.apply):
        todo = [i for i in want if i["id"] not in got]
        if todo:
            slot_translate.translate(todo, SYS, OUT,
                                     fields=("id", "word", "pos", "de"),
                                     keep=("id", "word", "de"),
                                     key_field="id", land="id")
            got = slot_translate.done_keys(OUT, land="id")

    ok = controls(want, got, "控制判据（德语释义专用）")
    if a.read:
        xs = [i for i in random.Random(3).sample(want, min(a.read * 3, len(want)))
              if i["id"] in got][:a.read]
        print("\n══ 打样 %d 条 ══" % len(xs))
        for i in xs:
            print("   %-22s [%s] %s" % (i["word"][:22], i["pos"], i["de"][:64]))
            print("   %-22s      → %s\n" % ("", (got[i["id"]].get("zh") or "（留空）")[:56]))
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 硬闸未过，**不写库**")
        return 1

    # 🔴 **写库前挡掉「一个汉字都没有、而且不是专名」的那族** —— 24 条实测：
    #      Bombardierkäfer → bombardier beetle      Frugalismus → frugalism
    #    模型给了**英文**而不是中文。规则 6 允许 `pos=name` 保留原文
    #    （`Abbotsbury` 没有通用中文译名，保留是对的，36 条），但普通名词不在豁免里。
    # ⚠️ 判据故意收得比"我认为它错"更窄：`Chromebook`/`Eth → ð` 落在这条里也被挡掉，
    #    而它们其实说得过去 —— **宁可当成"缺"也不当成"错"**（`FRAMEWORK`：错比缺更伤权威）。
    #    挡掉的行下一轮重跑会重新翻，不丢东西。
    drop = [i for i in items
            if i["id"] in got and (got[i["id"]].get("zh") or "").strip()
            and i["pos"] != "name" and not has_han(got[i["id"]]["zh"])]
    dropped = {i["id"] for i in drop}
    if drop:
        print("\n■ 挡下 %s 行（非专名却没给中文，留空不写）" % format(len(drop), ","))
        for i in drop[:6]:
            print("   %-24s [%s] → %s" % (i["word"][:24], i["pos"], got[i["id"]]["zh"][:32]))

    rows = [(int(i["id"]), got[i["id"]]["zh"].strip())
            for i in items if i["id"] in got and (got[i["id"]].get("zh") or "").strip()
            and i["id"] not in dropped]
    print("\n■ 可落库 %s 行" % format(len(rows), ","))
    if not rows:
        return 0
    with dbtool.session("keep-v3-15b-def-zh",
                        expect={"#sense_gloss": len(rows)}) as s:
        s.executemany("INSERT OR IGNORE INTO sense_gloss "
                      "(sense_id,lang,kind,seq,text,src) VALUES (?,'zh','definition',0,?,?)",
                      [(i, z, SRC) for i, z in rows])
    print("✓ 写入完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
