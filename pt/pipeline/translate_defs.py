#!/usr/bin/env python3
"""阶段 1.5b — 葡语原文释义译成中文 → `sense_gloss(lang='zh')`。2026-08-30。

    待译义项  60,812   （1.5a 收进来的葡语原文，均 43 字符）
    已有中文  114,912  （七月建库 111,957 + 中文版白送 2,955，**都不重翻**）

═══ 🔴 判据跟着任务走，不是跟着代码复用 ═══
例句族那套（`translate_examples.py`）**不能直接搬**：

    「译文本来就该有句号」        → 释义**不该**有句末标点（它是短语不是句子）
    「中文字数 < 原文词数的 60%」  → 释义就是要压缩，阈值完全不同
    「完整翻译整句」              → 释义要的是**对应词/短定义**，不是逐字翻

这一族该查的是：抄回原词 / 把元描述当释义 / 生造音译 / 一条中文对多个不同葡语词。

═══ payload 带什么 ═══
    id     `sense.id`（**数据库主键**，不是序号）—— `[[model-answer-files-key-by-id]]`
    word   词头（同一条释义在不同词下含义可能不同）
    pos    词性（`n`/`v`/`adj`…，决定中文该给名词还是动词）
    pt     葡语释义原文

⚠️ **不传"仅供参考"的上下文** —— `[[context-you-give-leaks-into-output]]`：
   it 那轮把法语原文当参考传进去，母地名直接漏进了 1,583 条音译结果。
   这里只传**必要**的三样，每一样都在规则里说明了用途。

═══ 成本纪律 ═══
· 跑批走 DeepSeek，`think=False` 硬默认（翻译不是推导型任务）。
· `slot_translate.announce_window()` 会在发第一个请求前打出**北京时间**与当前是不是高峰。

用法（在 pt/ 目录下）：
    python3 -u pipeline/translate_defs.py --slice 600    # 1% 切片，实测单价
    python3 -u pipeline/translate_defs.py --audit
    python3 -u pipeline/translate_defs.py --read 20
    python3 -u pipeline/translate_defs.py               # 全量续跑
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

# 释义比例句短（均 43 vs 81 字符），批可以大一些
slot_translate.CHUNK = 100
slot_translate.CONC = 60

SYS = """你在把葡萄牙语词典的释义翻译成中文，用于一部给中文读者的葡萄牙语词典。

输入是 JSON 数组，每项有：
  `id`    标识号，**不是序号**，原样回传
  `word`  被解释的葡萄牙语词
  `pos`   词性（n 名词／v 动词／adj 形容词／adv 副词／name 专名／phr 短语…）
  `pt`    该词这一条义项的葡萄牙语释义原文

规则
1. 输出**中文释义**，不是逐字翻译。能用一个常用汉语词对应就给那个词，
   不能对应就给一句简短的解释。
2. 🔴 **词性要对上 `pos`**：`v` 给动词说法（「切开」不是「切口」），
   `n` 给名词说法，`adj` 给形容词说法。
3. 🔴 **不要把词头本身抄回来当释义。** 如果原文只是重复了 `word`
   （如 `abdomen` → `Abdomen.`），说明源头没给真释义，`zh` 给空字符串。
4. 🔴 **不要输出元描述**。像「…的复数」「…的阴性形式」「参见…」这类说的是
   语法关系不是词义，`zh` 给空字符串。
5. 专名（`pos=name`）：有通用中文译名的用通用译名（`Sucre` →「苏克雷」）；
   **没有通用译名的保留原文**，不要音译生造。地名可在译名后加括号注国别。
6. 学名、化学式、度量单位原样保留。
7. **不加句末标点**，不写「指」「表示」这类引导语，不加括号解释除非原文就有。
8. 原文残缺或看不出意思，`zh` 给空字符串，不要猜。

输出 JSON 数组：[{"id": <标识号>, "zh": "<中文释义>"}]
只输出 JSON，不要解释。"""

LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{3,}")
META = re.compile(r"的复数|的阴性|的阳性|的变位|参见|同上|见上|这个词|该词|表示「|意思是")
TAIL = re.compile(r"[。．.!！?？；;]$")


def pool(con):
    """→ [{id, word, pos, pt}]，只取**有葡语原文且还没有中文**的义项。"""
    rows = con.execute(
        "SELECT s.id, d.word, COALESCE(s.pos,''), g.text "
        "  FROM sense s "
        "  JOIN dict d ON d.id=s.word_id "
        "  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='pt' "
        " WHERE NOT EXISTS(SELECT 1 FROM sense_gloss z "
        "                   WHERE z.sense_id=s.id AND z.lang='zh') "
        " ORDER BY s.id").fetchall()
    return [{"id": str(i), "word": w, "pos": p, "pt": t} for i, w, p, t in rows]


def controls(items, got, title):
    """判据**为释义重写**，不从例句那套复用。"""
    c, ex = Counter(), {}
    seen = defaultdict(list)

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
        src, w = it["pt"], it["word"]
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
        if len(LATIN.findall(z)) >= 2 and has_han(z):
            hit("残留葡语（≥2 个拉丁词，专名保留是允许的）", w, z)
        if len(z) > max(40, len(src)):
            hit("比原文还长", src[:40], z[:40])
        seen[z].append(w)
    dup = sum(len(v) for v in seen.values() if len(v) > 3)
    n = max(n, 1)
    print("\n══ %s（%s 条）══" % (title, format(n, ",")))
    for k, v in c.most_common():
        print("  %-38s %7s  %5.2f%%" % (k, format(v, ","), 100.0 * v / n))
        a, b = ex[k]
        print("        %-40s → %s" % (str(a)[:40], str(b)[:40]))
    print("  %-38s %7s  %5.2f%%" % ("一条中文对 >3 个不同词（疑似泛化）",
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
                                     fields=("id", "word", "pos", "pt"),
                                     keep=("id", "word", "pt"),
                                     key_field="id", land="id")
            got = slot_translate.done_keys(OUT, land="id")

    ok = controls(want, got, "控制判据（释义专用）")
    if a.read:
        xs = [i for i in random.Random(3).sample(want, min(a.read * 3, len(want)))
              if i["id"] in got][:a.read]
        print("\n══ 打样 %d 条 ══" % len(xs))
        for i in xs:
            print("   %-22s [%s] %s" % (i["word"][:22], i["pos"], i["pt"][:64]))
            print("   %-22s      → %s\n" % ("", (got[i["id"]].get("zh") or "（留空）")[:56]))
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 硬闸未过，**不写库**")
        return 1

    rows = [(int(i["id"]), got[i["id"]]["zh"].strip())
            for i in items if i["id"] in got and (got[i["id"]].get("zh") or "").strip()]
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
