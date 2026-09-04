#!/usr/bin/env python3
"""阶段 5b — 德语例句译成中文 → `example_gloss(lang='zh')`。2026-09-03。

    待译例句 444,094（阶段 5a 收的德语版例句，句长中位 114 字符）
    用户 2026-09-03 明确：**池子选全部**，不按义项封顶

═══ 消歧上下文走 `src_gloss`，不走 `sense_id` ═══
    `src_gloss`（源里这条例句挂在哪条德语释义下）  443,228 = **99.8%**
    `sense_id`（挂回我们出版层的义项）              227,896 = 51.3%
⇒ 传 `src_gloss`。挂不挂得回我们的义项层是**我们这边的**问题，
  而模型要的只是「这句里这个词取哪个意思」。

🔴 fr 那轮的族 A 就是**例句译文取错义项**（`FR_PLAN` 族 A）——
   不给消歧上下文，模型按这个词最常见的意思翻。
⚠️ 但给了上下文就有 `[[context-you-give-leaks-into-output]]` 的风险
   （it 那轮把法语原文当参考传进去，母地名漏进 1,583 条音译）。
   ⇒ 规则里写死「`sense` 不要翻译、不要出现在译文里」，**并且控制判据专门查这一条**。

═══ 🔴 判据跟着任务走：pt 那套有两条搬不过来 ═══
① **pt 的「词缀词条下的构词式不送翻」在 de 上不成立。**
   pt 逮到 `alemão + -ã → alemã` 这种词素运算式（付钱翻出来是错的）。
   de 的词缀词条下 1,422 条**全是真句子**：
     `-abel` → `Was akzeptabel ist, kann man akzeptieren.`
     `-age`  → `Eine Blamage ist es, wenn man sich blamiert hat.`
   照搬会白白扔掉 1,422 条好例句。**判据要按数据重新验，不按代码复用。**
② **pt 的 `Obs.:` 豁免不适用**（那是葡语源头的编辑标记）。

═══ 德语独有的三条 ═══
① **可分动词在句子里是拆开的**：`Er fährt am Montag mit.` 的动词是 `mitfahren`，
   不是 `fahren`。译文要按合起来的那个词的意思翻。
② **框型结构**：从句里动词跑到句末（`…, weil er mitfährt`），
   语序不能照搬进中文。
③ **德语引号是 „…“**，中文用「」或“”，不照抄原符号。

═══ payload ═══
    id     `example.id`（**数据库主键**）—— `[[model-answer-files-key-by-id]]`
    word   词头（这条例句是为哪个词收的）
    de     德语句子
    sense  该词在这条例句里取的义项（德语原文，**只用于消歧**）
⚠️ **不传 `ref`（文献出处）** —— 它不是句子的一部分，传进去会被当正文翻。

═══ 成本纪律 ═══
· `think=False` 硬默认（`[[batch-never-enables-thinking]]`）。
· 高峰＝工作日北京时间 09–12 与 14–18，其余（含周末）半价。
· **先跑切片实测单价**，不拿 1.5b 或别的语种的单价当报价
  （`[[prove-free-path-before-quoting]]`）。

用法（在 de/ 目录下）：
    python3 -u pipeline/translate_examples.py --slice 1600 --read 20
    python3 -u pipeline/translate_examples.py --audit
    python3 -u pipeline/translate_examples.py                # 全量续跑
    python3 -u pipeline/translate_examples.py --apply
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

SRC = "model:example"
OUT = paths.WORK / "examples" / "example_zh.jsonl"
has_han = dbtool.has_han

# 德语例句比释义长得多（中位 114 vs 61 字符）⇒ 批要小，免得单批出方向 token 过大
slot_translate.CHUNK = 40
slot_translate.CONC = 60

SYS = """你在把德语例句翻译成中文，用于一部给中文读者的德语词典。

输入是 JSON 数组，每项有：
  `id`     标识号，**不是序号**，原样回传
  `word`   这条例句是为哪个德语词收的
  `de`     德语句子
  `sense`  该词在这句里取的那个义项的德语释义

规则
1. **完整翻译整句**，不节译、不概括、不加注。
2. 🔴 **`sense` 决定该取哪个义项。** 一个词有多个意思时按 `sense` 说的那个翻，
   不要按这个词最常见的意思翻。
   🔴 **`sense` 本身不要翻译、不要出现在译文里** —— 它是给你消歧用的，不是要翻的内容。
3. 🔴 **德语可分动词在句子里是拆开的。** `Er fährt am Montag mit.` 的动词是
   `mitfahren`（一同前往），不是 `fahren`（行驶）。要按合起来那个词的意思翻。
4. 🔴 **德语从句把动词放句末**（`…, weil er mitfährt`），中文按中文语序写，
   不要照搬德语语序。
5. 保持原文语体 —— 书面语译成书面语，口语译成口语。
6. **习语、俗语、固定搭配按中文里对应的说法译，不要字面直译。**
   `jemandem einen Bären aufbinden` 是「骗某人」，不是「给某人绑只熊」。
7. 人名、地名、作品名：有通用中文译名的用通用译名；**没有的保留德语原文**，
   不要音译生造。
8. 专业术语按该领域的中文说法。复合词按中文里对应的说法译。
9. 德语引号是 „…“，中文用“…”，不照抄德语符号。
10. 原文残缺、只有半句、或看不出意思，`zh` 给空字符串，不要猜。
11. **只输出译文本身。** 不要输出文献出处、不要加括号解释、
    不要写「这句话的意思是」这类引导语。

输出 JSON 数组：[{"id": <标识号>, "zh": "<中文译文>"}]
只输出 JSON，不要解释。"""

LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{4,}")
WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}")
META = re.compile(r"这句话?的意思|此处指|字面意思|译注|原文是|德语中")

# 🔴 **空壳**：把引号/括号/标点/空白剥掉之后什么都不剩（实测最常见的是一对 `“”`）。
#    判据**按含义写**（`[[criteria-from-meaning-not-form]]`）：不是"太短"、不是"没汉字"
#    —— 公式 `y = cosh x`、代号 `SN 1987A` 没有汉字但**原样保留是对的**；
#    空壳的含义是「模型没给出译文，只吐了个标点外壳」。
#    ⚠️ 它和规则 10 的**留空不是一回事**：留空是模型诚实地说"给不出"，
#      空壳是它假装翻了，而 `.strip()` 判它非空 ⇒ **会原样落进库**。
#      `docs/FRAMEWORK.md §一`：错比缺更伤权威。⇒ 既拦落库，也当一条硬闸。
SHELL = re.compile(r"^[\s“”\"'‘’«»()（）\[\]—–\-·.,。，；;:：!！?？]*$")


def is_shell(z):
    """→ 这条译文是不是空壳。生成侧与闸**共用这一份**（`[[fix-regression-and-gate]]`）。"""
    return bool(SHELL.match(z))


# 🔴 **一条显式例外，不是判据。** 全量那轮"抄回原句"32 条我一条不落地读完了：
#    31 条是公式/代号/人名，原样保留就是正确答案；只有 `example.id=43395`
#    （`Unze`：„Väsele Li behielt davon nur einhundertachtzig Unzen…"）是真句子被抄回。
#    **重问两次都抄回**——失败模式没变就不会自己好（`[[retry-must-converge-or-drop-loud]]`），
#    所以不再循环，改成大声放弃：不落库、在这里留名。
#    ⚠️ 之所以写成 id 而不是判据：我试过把"真句子"和"人名串/公式"分开，**分不开**
#      （那条人名串同样是多词多实词）。与其编第三版形式代理，不如承认
#      「读完全部 32 条」这个事实本身就是最准的判据（`[[record-the-negative-decision]]`）。
KNOWN_BAD = {43395}


def pool(con):
    """→ [{id, word, de, sense}]，只取**还没有中文**的例句。判据只写这一份。"""
    rows = con.execute(
        "SELECT e.id, e.word, e.text, COALESCE(e.src_gloss,'') "
        "  FROM example e "
        " WHERE NOT EXISTS(SELECT 1 FROM example_gloss g "
        "                   WHERE g.example_id=e.id AND g.lang='zh') "
        " ORDER BY e.id").fetchall()
    return [{"id": str(i), "word": w, "de": t, "sense": g} for i, w, t, g in rows]


def controls(items, got, title):
    """判据**为德语例句重写**，不从释义那套复用。

    🔴 释义那套的阈值在这里全不适用：释义**要**压缩、例句**不许**节译；
       释义不该有句末标点、例句是完整句子**本来就该有**。
    """
    c, ex = Counter(), {}
    seen = defaultdict(set)

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
        src, w, sense = it["de"], it["word"], it["sense"]
        if not z:
            hit("留空（模型判定给不出）", "%s ← %s" % (w, src[:40]), "")
            continue
        if is_shell(z):
            hit("🔴 空壳（只剩标点，模型没给出译文）", "%s ← %s" % (w, src[:30]), repr(z))
        elif not has_han(z):
            # 公式/代号原样保留是对的（`y = cosh x`、`SN 1987A`），只做记账不算红。
            hit("无汉字（公式/代号，原样保留）", w, z[:40])
        if z.strip() == src.strip():
            # ⚠️ **不是硬闸**：全量那轮把这 32 条**一条不漏地读完了**，
            #    31 条是公式/代号/人名（`y = cosh x`、`SN 1987A`、`Bäcker + -ei -> Bäckerei`、
            #    `P[ater] Prov. …SJ`），**原样保留就是正确答案**；只有 1 条是真缺陷
            #    （`Unze` 那句真句子被抄回）。真缺陷率 ≈ 3%。
            # 🔴 我试过用"是不是一个句子"把两者分开，**分不开** —— 那条人名串同样是
            #    多词多实词。与其编第三版形式代理（`[[criteria-narrower-than-you-think]]`：
            #    修判据三轮就停手），不如**记账 + 把残差当上界报**：
            #    这一栏数字要人读，不自动判红。
            hit("抄回原句（读完 32 条：31 条公式/代号正确，1 条真缺陷）", w, z[:40])
        if META.search(z):
            hit("🔴 加了元描述/引导语（规则 11）", w, z[:40])
        # 🔴 `[[context-you-give-leaks-into-output]]` 的专用闸：
        #    消歧上下文被抄进了译文。判据＝`sense` 里**独有**的实词出现在译文里，
        #    而原句里根本没有那个词。
        if sense:
            s_words = set(WORD.findall(sense.lower())) - set(WORD.findall(src.lower()))
            if any(x in z.lower() for x in s_words if len(x) >= 6):
                hit("🔴 消歧上下文漏进译文（sense 被抄了进去）", sense[:34], z[:34])
        rem = [x for x in LATIN.findall(z) if x.lower() in src.lower()]
        if len(rem) >= 3:
            hit("残留德语（≥3 个原句里的拉丁词，专名保留是允许的）", src[:34], z[:34])
        if len(z) > 2 * len(src):
            hit("译文超过原文两倍长", src[:34], z[:34])
        seen[z].add(src)
    dup = sum(len(v) for v in seen.values() if len(v) > 3)
    n = max(n, 1)
    print("\n══ %s（%s 条）══" % (title, format(n, ",")))
    for k, v in c.most_common():
        print("  %-42s %7s  %5.2f%%" % (k, format(v, ","), 100.0 * v / n))
        a, b = ex[k]
        print("        %-40s → %s" % (str(a)[:40], str(b)[:40]))
    print("  %-42s %7s  %5.2f%%" % ("一个中文对 >3 条不同德语原句（疑似泛化）",
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
    print("■ 待译例句 %s ｜ 已译 %s ｜ 还差 %s"
          % (format(len(items), ","), format(len(got), ","),
             format(sum(1 for i in items if i["id"] not in got), ",")))

    want = (random.Random(1).sample(items, min(a.slice, len(items)))
            if a.slice else items)
    if not (a.audit or a.apply):
        todo = [i for i in want if i["id"] not in got]
        if todo:
            slot_translate.translate(todo, SYS, OUT,
                                     fields=("id", "word", "de", "sense"),
                                     keep=("id", "word", "de"),
                                     key_field="id", land="id")
            got = slot_translate.done_keys(OUT, land="id")

    ok = controls(want, got, "控制判据（德语例句专用）")
    if a.read:
        xs = [i for i in random.Random(3).sample(want, min(a.read * 3, len(want)))
              if i["id"] in got][:a.read]
        print("\n══ 打样 %d 条 ══" % len(xs))
        for i in xs:
            print("   [%s] %s" % (i["word"][:20], i["de"][:88]))
            print("        → %s\n" % (got[i["id"]].get("zh") or "（留空）")[:80])
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 硬闸未过，**不写库**")
        return 1

    # 🔴 空壳不落库：`.strip()` 判 `“”` 非空，不拦就会把一对空引号当译文写进去。
    #    判据 import 上面那一份，闸与落库用的是**同一个** `is_shell`。
    rows = [(int(i["id"]), got[i["id"]]["zh"].strip())
            for i in items if i["id"] in got and (got[i["id"]].get("zh") or "").strip()
            and not is_shell(got[i["id"]]["zh"].strip())
            and int(i["id"]) not in KNOWN_BAD]
    print("\n■ 可落库 %s 行" % format(len(rows), ","))
    if not rows:
        return 0
    with dbtool.session("keep-v3-5b-example-zh",
                        expect={"#example_gloss": len(rows)}) as s:
        s.executemany("INSERT OR IGNORE INTO example_gloss (example_id,lang,text,src) "
                      "VALUES (?,'zh',?,?)", [(i, z, SRC) for i, z in rows])
    print("✓ 写入完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
