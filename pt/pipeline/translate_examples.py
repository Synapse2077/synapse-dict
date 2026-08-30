#!/usr/bin/env python3
"""阶段 5d — 例句译成中文 → `example_gloss(lang='zh')`。2026-08-30。

用户 2026-08-30 批准：先跑 1% 切片实测单价 + 打样，再放全量。

    不同句子      40,065   ← 按**内容键**翻（同一句给多个词当例句只翻一次，省 21%）
    已有中文        803   ← 中文版白送的，不重翻
    已有英文译文  7,495   ← 🔴 **免费的交叉真值**，见下

═══ 🔴 payload 必须带义项上下文 —— fr 那轮最大的一族就栽在这里 ═══
`FR_PLAN` 族 A「例句译文与它所挂的义项不符」，风险面 **22.1 万条**，重跑 41 元：

    taper「发臭」下   `Ça tape ici !`      → 「这儿真热」   ← 取的是另一个义项
    librairie「书店」下 `La librairie du roi.` → 「国王的书店」
    piqué「疯癫」下   `Il est un peu piqué.` → 「它有点酸了」

根因是 `translate_examples.py` 的 payload **只给了句子、没给义项** ——
一词多义时模型只能猜，而它猜的是最常见的那个义。

⇒ pt 从第一批就带 `sense`。**这不是可选项**：实测 pt 的 50,745 条例句
   **100% 都有 `src_gloss`**（源头那条义项的释义原文），代价是每条多约 47 字符。

═══ 🔴 控制判据是为**整句翻译**重写的，不是从释义那套复用 ═══
`gloss_translate` 那十条里有几条对例句是**反的**：

    「句末不许带标点」   → 例句译文本来就该有句号
    「比源还长」         → 对例句无意义
    「压过头」           → 方向对，阈值完全不同（释义是短语，例句是整句）

这一族该查的是：漏译 / 把文献出处也翻进去 / 残留葡语 / 元话语 / 整句没翻。

═══ ⭐ 免费的交叉真值：英文译文 ═══
英文版给了 7,495 条待翻句子的英文译文。同一句葡语，**我们的中文和源头的英文
说的应该是同一件事** —— 这一族唯一不花钱的外部锚（`[[external-anchor-gates]]`）。
⇒ `--cross N` 并排打出来，**我逐条读**。不用模型判模型
（`[[llm-as-evaluator-discipline]]` ⑩）。

═══ 成本纪律 ═══
· 🔴 跑批**一律不用豆包**（用户 2026-08-15）；走 DeepSeek，`DOUBAO_DISABLED` 是硬拦截。
· 🔴 `think=False` 是 `slot_translate._ask` 的**硬默认**，翻译不是推导型任务。
· ⭐ **排低谷跑价格减半**（周一至周五 UTC 01–04 与 06–10 之外），零风险。

用法（在 pt/ 目录下）：
    python3 -u pipeline/translate_examples.py --slice 400   # 1% 切片，实测单价
    python3 -u pipeline/translate_examples.py --audit       # 只算控制表
    python3 -u pipeline/translate_examples.py --read 20     # 打样
    python3 -u pipeline/translate_examples.py --cross 25    # 与英文译文并排
    python3 -u pipeline/translate_examples.py               # 全量续跑
    python3 -u pipeline/translate_examples.py --apply       # 落库
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

# 葡语例句比法语短（均 81 vs 158 字符），但要多带一段义项上下文（均 47）⇒ 批 60
slot_translate.CHUNK = 60
# 🔴 并发只影响墙钟，**一分钱不影响 token 成本**。这活是网络等待为主。
slot_translate.CONC = 60

SYS = """你在把葡萄牙语例句翻译成中文，用于一部给中文读者的葡萄牙语词典。

输入是 JSON 数组，每项有：
  `id`     标识号，**不是序号**，原样回传
  `pt`     葡萄牙语句子
  `sense`  这条例句所属义项的释义（可能是英文或葡萄牙语）

规则
1. **完整翻译整句**，不节译、不概括、不加注。
2. 🔴 **`sense` 决定该取哪个义项。** 一个词有多个意思时，按 `sense` 说的那个意思翻，
   不要按这个词最常见的意思翻。`sense` 本身**不要翻译、不要出现在译文里**。
3. 保持原文语体 —— 书面语译成书面语，口语译成口语。
4. 人名、地名、作品名：有通用中文译名的用通用译名；**没有的就保留葡萄牙语原文**，
   不要音译生造。
5. 专业术语按该领域的中文说法。
6. **习语、俗语、固定搭配按中文里对应的说法译，不要字面直译。**
   例如 `dar uma apitadela` 是「打个电话」，不是「吹一声哨」。
7. 巴西葡语与欧洲葡语的用词差异不必在译文里标注，照意思译即可。
8. 原文残缺、只有半句、或看不出意思，`zh` 给空字符串，不要猜。
9. **只输出译文本身。** 不要输出文献出处、不要加括号解释、不要写「这句话的意思是」。

输出 JSON 数组：[{"id": <标识号>, "zh": "<中文译文>"}]
只输出 JSON，不要解释。"""

LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{4,}")
HAN = re.compile(r"[一-鿿]")
WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}")
# ⚠️ `注：` **不在这里** —— 源头本来就有 `Obs.:`（observação），
#    `Obs.: confira quimbanda → 注：参见金班达` 是**正确**译文，第一版把它判红了。
META = re.compile(r"这句话?的意思|此处指|字面意思|译注")

# ══════ 🔴 词缀词条下的构词式：不是句子，**不送去翻** ══════
# 1% 切片打样当场逮到：给它们付钱翻出来的是**错的** ——
#     alemão（阳性「德国男人」）+ -ã → alemã（阴性「德国女人」）
#         译成「德语 + -ã → 德语」，性别对立整个丢了
#     Holanda + -ês → holandês  →  「荷兰 + -ês → 荷兰语」
#
# 判据**按含义**：词缀词条（`word` 以 `-` 开头或结尾）下的**词素运算式**。
# 🔴 第一版写成「含 `+` 且含 `→`」——**反向查立刻打回**：同一类还有 `=` 写法
#    （`reciclar + -abilidade = reciclabilidade`）和只有箭头的（`orelha → orelhano.`）。
#    符号是形式，「挂在词缀词条下的词素运算」才是含义。
#
# 双向实测（全量 50,745 条）：
#     A 词缀 + 运算符   539   ✅ 抽 10 条全是构词式，一条真句子都没有
#     B 词缀 无运算符   420   ✅ 不判（`paleo-` 下 `Arqueólogos derrubam mito da dieta paleo.` 是真句子）
#     C 非词缀 含运算符  97   ✅ 不判（`A biblioteca 'iostream' é muito útil em C++.` 是真句子）
#
# ⚠️ **数据一个字节不动**，只是不送去翻 —— 照 fr 的先例
#    「规模太小，归阶段 8 展示时过滤」「别在数据里砍」。已记进收尾单 C13。
OPS = re.compile(r"[+→=>]")


def is_formula(word, text):
    return (word.startswith("-") or word.endswith("-")) and bool(OPS.search(text))


def pool(con):
    """→ [{id, pt, sense}]，按**不同句子**去重；已有中文的不再翻。"""
    done = {t for (t,) in con.execute(
        "SELECT DISTINCT e.text FROM example e "
        "JOIN example_gloss g ON g.example_id=e.id AND g.lang='zh'")}
    seen, items, skipped = set(), [], 0
    for eid, w, t, g in con.execute(
            "SELECT id, word, text, COALESCE(src_gloss,'') FROM example ORDER BY id"):
        if t in done or t in seen:
            continue
        if is_formula(w, t):
            skipped += 1
            continue
        seen.add(t)
        items.append({"id": str(eid), "pt": t, "sense": g[:200]})
    if skipped:
        print("■ 跳过词缀构词式 %s 条（不是句子，翻出来是错的；数据未动）"
              % format(skipped, ","))
    return items


def controls(pairs, title):
    """pairs = [(葡语原句, 中文)]。**判据为整句翻译重写，不从释义那套复用。**"""
    c, ex = Counter(), {}

    def hit(k, p, z):
        c[k] += 1
        ex.setdefault(k, (p, z))

    zh_by = defaultdict(list)
    for p, zh in pairs:
        z = (zh or "").strip()
        if not z:
            hit("留空（模型判定翻不了）", p, z)
            continue
        # 🔴 **分母是原文里可翻的词数，不是译文长度。**
        #    第一版拿「汉字占译文字符的比例」当判据 —— 那是**形式代理**，
        #    1% 切片上 10 条红**全是正确译文**被数字和术语撑破的：
        #       `人均收入1900美元，失业率17.9%，通货膨胀率7.65%（2001年）。`  ✓
        #       `10♠,J♠,Q♠,K♠,A♠`（同花大顺，没什么可翻）                    ✓
        #       `使用了两次PCR扩增；TcH2AF/R用于组蛋白H2A/SIRE基因…`            ✓
        #    「没翻」的含义是**原文有实质的葡语词句、而译文里几乎没有中文**，
        #    所以要拿**原文的词数**当尺子（`[[criteria-from-meaning-not-form]]`）。
        han = len(HAN.findall(z))
        nw = len(WORD.findall(p))
        if nw >= 5 and han == 0:
            hit("🔴 一个汉字都没有（而原文有 ≥5 个词）", p, z)
        elif nw >= 5 and han < nw * 0.6:
            hit("🔴 疑似没翻（中文字数 < 原文词数的 60%）", p, z)
        # 残留葡语：只在**原文本身不是专名堆**时才算（专名保留原文是规则 4 要求的）
        if len(LATIN.findall(z)) >= 3 and han >= 4:
            hit("残留拉丁串 ≥3（专名保留是允许的，人工看）", p, z)
        if META.search(z):
            hit("🔴 含元话语/译注", p, z)
        if z.count("（") >= 2:
            hit("括号解释 ≥2 处", p, z)
        zh_by[z].append(p)

    dup = sum(len(v) for v in zh_by.values() if len(v) > 1)
    n = max(len(pairs), 1)
    print("\n══ %s（%s 条）══" % (title, format(len(pairs), ",")))
    for k, v in c.most_common():
        print("  %-34s %7s  %5.2f%%" % (k, format(v, ","), 100.0 * v / n))
        f, z = ex[k]
        print("        %-56s → %s" % (f[:56], z[:44]))
    print("  %-34s %7s  %5.2f%%" % ("撞车（不同句→同一中文）", format(dup, ","),
                                    100.0 * dup / n))
    hard = [k for k in c if k.startswith("🔴") and c[k] > 0.02 * n]
    print("  %s" % ("🔴 硬闸红了（>2%）：" + "；".join(hard) if hard
                    else "✅ 硬闸过（每条 🔴 都 ≤2%）"))
    return not hard


def cross(con, got, n):
    """⭐ 与英文版自带的英文译文并排 —— 这一族唯一不花钱的外部锚。"""
    rows = list(con.execute(
        "SELECT e.text, COALESCE(e.src_gloss,''), g.text FROM example e "
        "JOIN example_gloss g ON g.example_id=e.id AND g.lang='en'"))
    have = [(p, sg, en, got[p]["zh"]) for p, sg, en in rows if p in got]
    random.Random(9).shuffle(have)
    print("\n══ 交叉真值：同一句葡语，源头英文 vs 我们的中文（%d/%d）══"
          % (min(n, len(have)), len(have)))
    for p, sg, en, zh in have[:n]:
        print("   义项 %s" % sg[:96])
        print("   PT  %s" % p[:104])
        print("   EN  %s" % en[:104])
        print("   ZH  %s\n" % ((zh or "（留空）")[:104]))
    return have


def apply_rows(con, got):
    txt2ids = defaultdict(list)
    for eid, t in con.execute("SELECT id, text FROM example"):
        txt2ids[t].append(eid)
    done = {eid for (eid,) in con.execute(
        "SELECT example_id FROM example_gloss WHERE lang='zh'")}
    out = [(eid, rec["zh"].strip())
           for t, rec in got.items() if (rec.get("zh") or "").strip()
           for eid in txt2ids.get(t, ()) if eid not in done]
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
    got = slot_translate.done_keys(OUT, land="pt")
    print("■ 不同句子 %s ｜ 已翻 %s ｜ 待翻 %s"
          % (format(len(items), ","), format(len(got), ","),
             format(sum(1 for i in items if i["pt"] not in got), ",")))

    want = (random.Random(1).sample(items, min(a.slice, len(items)))
            if a.slice else items)
    if not (a.audit or a.apply):
        todo = [i for i in want if i["pt"] not in got]
        if todo:
            slot_translate.translate(todo, SYS, OUT,
                                     fields=("id", "pt", "sense"),
                                     keep=("pt",), key_field="id", land="pt")
            got = slot_translate.done_keys(OUT, land="pt")

    pairs = [(i["pt"], got[i["pt"]]["zh"]) for i in want if i["pt"] in got]
    ok = controls(pairs, "控制判据（整句翻译专用）")
    if a.read:
        xs = random.Random(3).sample(pairs, min(a.read, len(pairs)))
        print("\n══ 打样 %d 条 ══" % len(xs))
        for f, z in xs:
            print("   PT %s\n   ZH %s\n" % (f[:104], (z or "（留空）")[:104]))
    if a.cross:
        cross(con, got, a.cross)

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 硬闸未过，**不写库**")
        return 1
    return apply_rows(con, got)


if __name__ == "__main__":
    sys.exit(main())
