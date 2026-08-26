#!/usr/bin/env python3
"""阶段 5 第二段 — 例句译成中文 → `example_gloss(lang='zh')`。2026-08-25。

用户 2026-08-25：「**全量翻吧，该花的还是要花的**」。

    不同句子 615,214   ← 按**内容键**翻（同一句给多个词当例句只翻一次，省 16.9%）
    已有英文译文 13,181 ← 🔴 **免费的交叉真值**，见下

═══ 🔴 控制判据必须重设，不能套释义那一套 ═══
`fix-regression-and-gate` 的另一面：**判据要跟着任务走，不是跟着代码复用**。
`gloss_translate.py` 那十条里有好几条对例句是**反的**：

    「句末不许带标点」  → 例句译文本来就该有句号
    「压过头（中文太短）」→ 判据方向对，但阈值完全不同（释义是短语，例句是整句）
    「元话语」          → 仍然适用
    「比源还长」        → 对例句无意义

这一族该查的是别的东西：漏译 / 把文献出处也翻进去 / 人名地名生造音译 / 整句没翻。

═══ ⭐ 免费的交叉真值：英文译文 ═══
英文版给了 13,181 条例句的英文译文，已经在出版层。同一句法语，
**我们的中文和源头的英文说的应该是同一件事** —— 这是这一族唯一不花钱的外部锚
（`[[external-anchor-gates]]`：锚外部的闸永不过期）。
⇒ `--cross N` 抽 N 条并排打出来，我逐条读。**不用模型判模型**
（`[[llm-as-evaluator-discipline]]` ⑩：能确定性回源比对的根本别问模型；
 这里做不到确定性，所以由**我**读，不是找第二个模型投票）。

用法（在 fr/ 目录下）：
    python3 -u pipeline/translate_examples.py --slice 2000   # 1% 切片，实测单价
    python3 -u pipeline/translate_examples.py --audit        # 只算控制表
    python3 -u pipeline/translate_examples.py --read 20      # 打样
    python3 -u pipeline/translate_examples.py --cross 25     # 与英文译文并排
    python3 -u pipeline/translate_examples.py                # 全量续跑
    python3 -u pipeline/translate_examples.py --apply        # 落库
"""
import argparse
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool                              # noqa: E402
import paths                               # noqa: E402
from pipeline import slot_translate        # noqa: E402

SRC = "model:example"
OUT = paths.WORK / "examples" / "example_zh.jsonl"

# 例句比短槽值长得多（均 158 字符），批小一点：一批 40 条 ≈ 1 万 token 上下文
slot_translate.CHUNK = 40
# 🔴 DeepSeek flash 的**并发限额是 2,500**（官网），共用件默认的 8 是给小批量定的。
#    这一族 61.5 万句 / 1.5 万批：并发 16 要 6.4 小时，150 只要 40 分钟，
#    而 150 只用掉限额的 6%。**并发只影响墙钟，一分钱不影响 token 成本。**
#    ⚠️ 这活是**网络等待**为主，CPU 只花在 JSON 解析 —— 提并发不会把机器压垮；
#       仍用 `nice` 跑，用户 2026-08-25「别把 cpu 干爆了」。
slot_translate.CONC = 150

SYS = """你在把法语例句翻译成中文，用于一部给中文读者的法语词典。

输入是 JSON 数组，每项有 `id`（标识号，**不是序号**，原样回传）和 `fr`（法语句子）。

规则
1. **完整翻译整句**，不节译、不概括、不加注。
2. 这些句子多是 19–20 世纪文学作品的引文。**保持原文的语体** —— 书面语译成书面语，口语译成口语。
3. 人名、地名、作品名：有通用中文译名的用通用译名；**没有的就保留法语原文**，不要音译生造。
4. 专业术语按该领域的中文说法。
5. **习语、俗语、固定搭配按中文里对应的说法译，不要字面直译。** 例如 `passer cent sept ans sur qch` 是「没完没了地耗在某事上」，不是「耗一百零七年」。
6. 原文残缺、只有半句、或看不出意思，`zh` 给空字符串，不要猜。
7. **只输出译文本身。** 不要输出文献出处、不要加括号解释、不要写「这句话的意思是」这类话。

输出 JSON 数组：[{"id": <标识号>, "zh": "<中文译文>"}]
只输出 JSON，不要解释。"""

LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{4,}")
HAN = re.compile(r"[一-鿿]")
META = re.compile(r"这句话?的意思|原文|译文|此处指|字面意思|注：|译注")


def pool(con):
    """→ [{id, fr}]，按**不同句子**去重；已有中文的不再翻。"""
    done = {t for (t,) in con.execute(
        "SELECT DISTINCT e.text FROM example e "
        "JOIN example_gloss g ON g.example_id=e.id AND g.lang='zh'")}
    seen, items = set(), []
    for eid, t in con.execute("SELECT id, text FROM example ORDER BY id"):
        if t in done or t in seen:
            continue
        seen.add(t)
        items.append({"id": str(eid), "fr": t})
    return items


# ══════════════════════════════════════════════════════════════════ 控制判据
def controls(pairs, title):
    """pairs = [(法语原句, 中文)]。**十条判据全是为整句翻译重写的。**"""
    c = Counter()
    ex = {}

    def hit(k, fr, zh):
        c[k] += 1
        ex.setdefault(k, (fr, zh))

    zh_by = defaultdict(list)
    for fr, zh in pairs:
        z = (zh or "").strip()
        if not z:
            hit("留空（模型判定翻不了）", fr, z)
            continue
        han = len(HAN.findall(z))
        if han == 0:
            hit("🔴 一个汉字都没有", fr, z)
        elif han < len(z) * 0.4:
            hit("🔴 汉字占比 <40%（疑似没翻）", fr, z)
        if LATIN.search(z):
            # 人名地名保留原文是**规则允许的**，所以只在拉丁串很多时才算残留
            if len(LATIN.findall(z)) >= 3:
                hit("🔴 残留法语（≥3 个拉丁词）", fr, z)
        # 漏译：中文字数相对法语字符数过少（整句翻译的经验比是 0.25–0.5）
        if han and han < len(fr) * 0.12:
            hit("🔴 疑似漏译（中文 < 法语字符数的 12%）", fr, z)
        if META.search(z):
            hit("🔴 含元话语/译注", fr, z)
        if "——" in z or "《" in z and "》" in z and "，" not in z:
            hit("疑似把文献出处也翻进来了", fr, z)
        if z.count("（") >= 2:
            hit("括号解释 ≥2 处", fr, z)
        zh_by[z].append(fr)

    dup = sum(len(v) for v in zh_by.values() if len(v) > 1)
    n = max(len(pairs), 1)
    print("\n══ %s（%s 条）══" % (title, format(len(pairs), ",")))
    for k, v in c.most_common():
        print("  %-34s %7s  %5.2f%%" % (k, format(v, ","), 100.0 * v / n))
        f, z = ex[k]
        print("        %-58s → %s" % (f[:58], z[:44]))
    print("  %-34s %7s  %5.2f%%" % ("撞车（不同句→同一中文）", format(dup, ","),
                                    100.0 * dup / n))
    hard = [k for k in c if k.startswith("🔴") and c[k] > 0.02 * n]
    print("  %s" % ("🔴 硬闸红了（>2%）：" + "；".join(hard) if hard
                    else "✅ 硬闸过（每条 🔴 都 ≤2%）"))
    return not hard


def cross(con, got, n):
    """⭐ 与英文版自带的英文译文并排 —— 这一族唯一不花钱的外部锚。"""
    rows = list(con.execute(
        "SELECT e.text, g.text FROM example e "
        "JOIN example_gloss g ON g.example_id=e.id AND g.lang='en'"))
    have = [(fr, en, got[fr]["zh"]) for fr, en in rows if fr in got]
    random.Random(9).shuffle(have)
    print("\n══ 交叉真值：同一句法语，源头英文 vs 我们的中文（%d/%d）══"
          % (min(n, len(have)), len(have)))
    for fr, en, zh in have[:n]:
        print("   FR  %s" % fr[:104])
        print("   EN  %s" % en[:104])
        print("   ZH  %s\n" % (zh or "（留空）")[:104])
    return have


def apply_rows(con, items, got):
    out = []
    txt2ids = defaultdict(list)
    for eid, t in con.execute("SELECT id, text FROM example"):
        txt2ids[t].append(eid)
    done = {(eid) for (eid,) in con.execute(
        "SELECT example_id FROM example_gloss WHERE lang='zh'")}
    for i in items:
        rec = got.get(i["fr"])
        z = (rec or {}).get("zh", "").strip()
        if not z:
            continue
        for eid in txt2ids.get(i["fr"], ()):
            if eid not in done:
                out.append((eid, z))
    print("\n■ 可落库 %s 行（来自 %s 个不同句子）"
          % (format(len(out), ","), format(len({z for _e, z in out}), ",")))
    if not out:
        return 0
    with dbtool.session("keep-v3-example-zh", expect={"#example_gloss": len(out)}) as s:
        s.executemany("INSERT OR IGNORE INTO example_gloss (example_id,lang,text,src) "
                      "VALUES (?,'zh',?,?)", [(e, z, SRC) for e, z in out])
    print("✓ 写入完成")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int, default=0)
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--cross", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = pool(con)
    got = slot_translate.done_keys(OUT)
    print("■ 不同句子 %s ｜ 已翻 %s ｜ 待翻 %s"
          % (format(len(items), ","), format(len(got), ","),
             format(sum(1 for i in items if i["fr"] not in got), ",")))

    want = (random.Random(1).sample(items, min(a.slice, len(items)))
            if a.slice else items)
    if not (a.audit or a.apply):
        todo = [i for i in want if i["fr"] not in got]
        if todo:
            slot_translate.translate(todo, SYS, OUT, fields=("id", "fr"),
                                     keep=("fr",), key_field="id")
            got = slot_translate.done_keys(OUT)

    pairs = [(i["fr"], got[i["fr"]]["zh"]) for i in want if i["fr"] in got]
    ok = controls(pairs, "控制判据（整句翻译专用）")
    if a.read:
        xs = random.Random(3).sample(pairs, min(a.read, len(pairs)))
        print("\n══ 打样 %d 条 ══" % len(xs))
        for f, z in xs:
            print("   FR %s\n   ZH %s\n" % (f[:104], (z or "（留空）")[:104]))
    if a.cross:
        cross(con, got, a.cross)

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 硬闸未过，**不写库**")
        return 1
    return apply_rows(con, items, got)


if __name__ == "__main__":
    sys.exit(main())
