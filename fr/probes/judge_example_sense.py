#!/usr/bin/env python3
"""探针 — **现有例句译文，取的是不是它所挂义项的那个意思？** 2026-08-27。

═══ 为什么换成"判断"而不是"重翻" ═══
前一个探针 `example_sense_context.py` 拿「带上下文重翻之后文本变不变」当指标，
**指标本身是错的**：这个任务的重跑抖动就有 85%（同一 prompt 跑两次，长文学引文
换个说法而已），2% 的真缺陷完全淹没在噪声里 —— 短句上甚至量出 A−B = +0.0 pp。
（`[[proxy-metric-gets-optimized]]` / `[[measure-landing-not-source]]`：量代理不量落点。）

而拿两家外审挑出的 **6 条已知错案**直接试，带上下文重翻 **6/6 全修对**：

    taper「发臭」    Ça tape ici !          这儿真热     → 这里臭气熏天
    librairie「图书馆」La librairie du roi.  国王的书店   → 国王的图书馆
    piqué「疯癫」    Il est un peu piqué.   它有点酸了   → 他有点疯疯癫癫的

⇒ **机制有效，缺陷稀疏。** 那就不该重跑全部 119,164 条（41 元、churn 掉 85% 的
   好译文、且实测会把对的改错：`squish` 一条带上下文反而更差）。
   正确做法：**先判断、只修被判坏的那些。**
   判断的产物是一个词，约 8 token；重写是 111 token/句 —— 差一个数量级。

═══ 🔴 判官必须先跑正控与负控 ═══
`[[llm-as-evaluator-discipline]]`：判官不是真值，用前必跑负控。

    负控（必须判"坏"）  两家外审挑出、我已回源确认的 6 条
    正控（必须判"好"）  **单义词**的例句 —— 没有歧义可言，判坏就是判官在乱说

⚠️ 本脚本**一个字都不写库**，只出数。

用法（在 fr/ 目录下）：
    python3 -u probes/judge_example_sense.py --control     # 只跑正控+负控
    python3 -u probes/judge_example_sense.py --n 400       # 风险面抽样，估真实缺陷率
"""
import argparse
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths                                  # noqa: E402
from pipeline import slot_translate           # noqa: E402

f = lambda n: format(n, ",")
OUT = paths.WORK / "examples" / "judge_sense.jsonl"
slot_translate.CHUNK = 40
slot_translate.CONC = 32

SYS = """你在检查一部法汉词典里，**例句的中文译文是否取对了义项**。

输入是 JSON 数组，每项：
- `id`：标识号，**不是序号**，原样回传。
- `fr`：法语例句原句。
- `w`：这条例句是给哪个词做例句的。
- `sense`：这条例句挂在该词的哪条义项下（中文释义）。
- `zh`：现有的中文译文。

只判断一件事：**在这句话里，`w` 被译成了 `sense` 说的那个意思吗？**

- `ok`：译文里 `w` 对应的部分，取的就是 `sense` 那个意思。
- `bad`：译文里 `w` 对应的部分，取的是这个词的**另一个**意思（或者干脆没译出来）。

判断纪律
1. **只看 `w` 那一处。** 句子别处译得好不好、措辞漂不漂亮、有没有漏译，**一律不管**。
2. 中文不必逐字对应 `sense`。意思对上就是 `ok`，换个说法、用同义词都算 `ok`。
3. `sense` 本身写的是「X 的变体/复数/缩写」这类**指针**时，只要译文指的是 X 那个东西就算 `ok`。
4. 拿不准就给 `ok`。**这一步的代价是不对称的**：误判成 `bad` 会让一条本来对的译文被重写，
   而重写是有风险的；漏掉一条错的，只是维持现状。

输出 JSON 数组：[{"id": <标识号>, "v": "ok"}] 或 [{"id": <标识号>, "v": "bad"}]
只输出 JSON，不要解释。"""

KNOWN_BAD = ["Ça tape ici !", "La librairie du roi.", "Il est un peu piqué.",
             "Reliure piquée.", "Poulet piqué.",
             "Je vais y passer demain pour mes affaires."]

ROW = """SELECT e.id, e.text, d.word, s.rank,
    (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' ORDER BY seq LIMIT 1),
    (SELECT text FROM example_gloss WHERE example_id=e.id AND lang='zh')
  FROM example e JOIN sense s ON s.id=e.sense_id JOIN dict d ON d.id=s.word_id
  WHERE e.hidden=0 AND %s"""


def pack(rows):
    out = []
    for eid, text, word, rank, zs, ze in rows:
        if not zs or not ze:
            continue
        out.append({"id": str(eid), "fr": text, "w": word, "sense": zs, "zh": ze,
                    "_rank": rank})
    return out


def ask(items, tag):
    out = OUT.with_suffix(".%s.jsonl" % tag)
    slot_translate.translate(items, SYS, out, fields=("id", "fr", "w", "sense", "zh"),
                             keep=("fr",), key_field="id", answer_field="v")
    got = slot_translate.done_keys(out)
    c = Counter()
    bad = []
    for it in items:
        r = got.get(it["fr"])
        if not r:
            c["未答"] += 1
            continue
        v = str(r.get("v", "")).strip().lower()
        c[v if v in ("ok", "bad") else "越权值:%r" % v] += 1
        if v == "bad":
            bad.append(it)
    return c, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--read", type=int, default=12)
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    R = random.Random(20260827)

    if a.control or not a.n:
        neg = pack(con.execute(ROW % ("e.text IN (%s)" % ",".join("?" * len(KNOWN_BAD))),
                               KNOWN_BAD).fetchall())
        pos_all = pack(con.execute(ROW % (
            "(SELECT COUNT(*) FROM sense x WHERE x.word_id=s.word_id AND x.hidden=0)=1 "
            "AND LENGTH(e.text) BETWEEN 20 AND 120 LIMIT 400")).fetchall())
        pos = R.sample(pos_all, min(40, len(pos_all)))
        cn, bn = ask(neg, "neg")
        cp, bp = ask(pos, "pos")
        print("\n══ 负控（6 条已回源确认是错的，判官必须全判 bad）══")
        print("   ", dict(cn), " ⇒ 逮到 %d/%d" % (len(bn), len(neg)))
        for it in neg:
            print("      %-10s %-16s %s" % (it["w"], it["sense"][:16], it["zh"][:40]))
        print("\n══ 正控（40 条**单义词**例句，无歧义可言，判官应几乎全判 ok）══")
        print("   ", dict(cp), " ⇒ 误判率 %.1f%%" % (100.0 * len(bp) / max(len(pos), 1)))
        for it in bp[:6]:
            print("      🔴 误判 %-10s %-16s\n         FR %s\n         ZH %s"
                  % (it["w"], it["sense"][:16], it["fr"][:90], it["zh"][:70]))
        if not a.n:
            return 0

    rows = con.execute(ROW % (
        "s.rank>1 AND (SELECT COUNT(*) FROM sense x "
        "WHERE x.word_id=s.word_id AND x.hidden=0)>1 LIMIT 4000")).fetchall()
    items = R.sample(pack(rows), min(a.n, len(rows)))
    c, bad = ask(items, "risk")
    n = sum(v for k, v in c.items() if k in ("ok", "bad"))
    print("\n══ 风险面抽样（rank>1 的多义词例句）══")
    print("   ", dict(c))
    print("   🔴 判为错配 %s / %s = **%.1f%%**" % (f(len(bad)), f(n),
                                              100.0 * len(bad) / max(n, 1)))
    print("   ⇒ 外推到全库风险面 119,164 条 ≈ **%s 条**"
          % f(int(119164 * len(bad) / max(n, 1))))
    print("\n══ 判为错配的（我要逐条读，判官不是真值）══")
    for it in bad[:a.read]:
        print("\n[%s r%d] 义项：%s" % (it["w"], it["_rank"], it["sense"]))
        print("   FR %s" % it["fr"][:140])
        print("   ZH %s" % it["zh"][:110])
    return 0


if __name__ == "__main__":
    sys.exit(main())
