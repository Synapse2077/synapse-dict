#!/usr/bin/env python3
"""探针（收尾单 A6）— **风险面之外**的例句译文有多少是错的？2026-08-28。

═══ 为什么要这一支 ═══
族 A 只判了「多义词 **且** 挂在 rank>1」的 118,879 条（风险面），
另外约 62 万条**从没被判过**。而族 A 收尾时逮到一类我没预料的缺陷：

    nébulosité「云量」
      FR  La nébulosité augmentera sensiblement lundi…
      旧  有好几个理由本可以阻止我追随内心单纯的冲动…（一封漂流瓶的信）

回源确认：那段中文**属于另一句** —— 跑批时模型把 B 句的译文标上了 A 句的 `id`。
这一族与"义项取错"是**两回事**：它不挑义项，它整条搬错了，
而且**没有理由只发生在风险面内**。收尾单 A6：规模未量。

═══ 判官比族 A 多一个取值 ═══
族 A 的判官只回 `ok` / `bad`（`w` 有没有取对义项）。这里要把两件事分开：

    ok     译文就是这句话的意思
    sense  `w` 取错了义项（＝族 A 那一族）
    other  **整条中文说的是别的事** ⇒ A6：答案贴到了别的条目上

⚠️ 本脚本**一个字都不写库**，只出数。判官不是真值 ⇒ `--read` 逐条抽读。

═══ 成本 ═══
每条约 120 token 进 / 8 token 出。n=400 在低谷价下**不到 0.5 元**。

用法（在 fr/ 目录下）：
    python3 -u probes/judge_example_offpool.py --n 400
    python3 -u probes/judge_example_offpool.py --read 20
"""
import argparse
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths                                   # noqa: E402
from pipeline import slot_translate            # noqa: E402

f = lambda n: format(n, ",")
OUT = paths.WORK / "examples" / "offpool_judge.jsonl"
slot_translate.CHUNK = 40
slot_translate.CONC = 32

SYS = """你在检查一部法汉词典里，**例句的中文译文对不对**。

输入是 JSON 数组，每项：
- `id`：标识号，**不是序号**，原样回传。
- `fr`：法语例句原句。
- `w`：这条例句是给哪个词做例句的。
- `sense`：这条例句挂在该词的哪条义项下（中文释义）。**可能是 null** ——
           表示这条例句没有挂到具体义项上，那就只在 `ok` / `other` 之间选。
- `zh`：现有的中文译文。

给出三个取值之一：

- `ok`    ：`zh` 就是 `fr` 这句话的意思（措辞不同、简略、意译，都算 ok）。
- `sense` ：`zh` 确实在翻这句话，但 `w` 那一处取的是**这个词的另一个意思**。
- `other` ：**`zh` 整条说的是别的事** —— 它不是这句法语的译文，
            内容对不上（人物、动作、场景都不是一回事）。

判断纪律
1. `ok` 与 `sense` 的界线只看 `w` 那一处；句子别处译得好不好一律不管。
2. **译文比原文短、省掉修饰、换个说法，都是 `ok`。** 只有内容对不上才是 `other`。
3. `sense` 里写的是「X 的变体/复数/缩写」这类**指针**时，译文指的是 X 就算 `ok`。
4. **拿不准就给 `ok`。** 代价不对称：误判会让一条本来对的译文被重写。

输出 JSON 数组：[{"id": <标识号>, "v": "ok"}]，`v` 只能是 ok / sense / other。
只输出 JSON，不要解释。"""

# 风险面之外 = 不满足族 A 那个条件（多义词且 rank>1）的可见例句
#
# 🔴🔴 2026-08-28 修：这里原本是 `JOIN sense s ON s.id=e.sense_id` —— **内连接**，
#      于是 `sense_id IS NULL` 的 **147,405 条**例句（有中文、页面上就在"例句"块里）
#      **从来没有进过判官的池子**，族 A 和 A6 两轮都没有。
#      我据此宣布「A6 收口，信号在 3% 档耗尽」—— 那条曲线是在**缺了 20% 人口**
#      的池子上量出来的。`[[measure-landing-not-source]]`：量的不是落点，是我的池子。
#
#      怎么发现的：第二轮外审，两家**各自独立**指出 `clair` 的例句块「原文与译文
#      完全错位」。回源一查，8 条错译全在同一批（Spearman r=0.450，**百分位 0.36%**，
#      本来就在我送过判官的最低 1% 档里），而它们 `sense_id` 全是 NULL ⇒ 内连接吃掉了。
#      ⭐ 这就是外审值钱的地方：闸问「有没有」，判官问「对不对」，
#         而**判官池子本身有没有洞**，只有把成品摆到另一双眼睛面前才看得出来。
#
# ⇒ 改成 LEFT JOIN。没有义项的例句 `sense` 给 None：判官只能在 `ok` / `other`
#   之间选（`sense`＝义项取错，无义项时不成立），而 A6 要的正是 `other`。
OFFPOOL = """
  SELECT e.id, e.text, COALESCE(d.word, e.word), s.rank,
    (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' ORDER BY seq LIMIT 1) zs,
    (SELECT text FROM example_gloss WHERE example_id=e.id AND lang='zh') ze
  FROM example e
  LEFT JOIN sense s ON s.id=e.sense_id
  LEFT JOIN dict d ON d.id=s.word_id
  WHERE e.hidden=0 AND NOT (COALESCE(s.rank,0)>1
        AND (SELECT COUNT(*) FROM sense x WHERE x.word_id=s.word_id AND x.hidden=0)>1)
"""
# 🔴 `COALESCE(s.rank,0)` 不能省：LEFT JOIN 之后 `s.rank` 是 NULL，
#    `NULL>1` 是 NULL，`NOT NULL` 还是 NULL ⇒ **整行被 WHERE 丢掉**。
#    改成 LEFT JOIN 却不改这里，等于换了个写法把同一批人再排除一次。


def pool(con):
    """→ [{id, fr, w, sense, zh}]。`sense` 为 None ＝ 这条例句没挂义项。

    ⚠️ 只要求有**例句中文**（`ze`）；第一版还要求有**义项中文**（`zs`），
       那等于把没挂义项的又滤掉一次 —— 同一个洞堵两遍才算堵上。
    """
    out = []
    for eid, text, word, rank, zs, ze in con.execute(OFFPOOL):
        if not ze:
            continue
        out.append({"id": str(eid), "fr": text, "w": word, "sense": zs, "zh": ze,
                    "_rank": rank})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--read", type=int, default=0)
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = pool(con)
    print("■ 风险面之外的可见例句（均有中文）%s 条" % f(len(items)))
    R = random.Random(20260828)
    sample = R.sample(items, min(a.n, len(items))) if a.n else items

    if a.n:
        slot_translate.translate(sample, SYS, OUT,
                                 fields=("id", "fr", "w", "sense", "zh"),
                                 keep=("id", "w"), key_field="id", answer_field="v",
                                 land="id")
    got = slot_translate.done_keys(OUT, "id")
    c, by = Counter(), {"sense": [], "other": []}
    for it in sample:
        r = got.get(it["id"])
        if not r:
            continue
        v = str(r.get("v", "")).strip().lower()
        c[v if v in ("ok", "sense", "other") else "越权值:%r" % v] += 1
        if v in by:
            by[v].append(it)
    n = sum(v for k, v in c.items() if k in ("ok", "sense", "other"))
    if not n:
        print("(还没判过，加 --n 400 跑)")
        return 0
    print("\n══ 判官结果 ══  %s" % dict(c))
    for k, label in (("sense", "义项取错（族 A 那一族）"), ("other", "🔴 整条对不上（A6：答案贴错条目）")):
        print("   %-30s %s / %s = %.2f%%  外推全库 ≈ %s"
              % (label, f(len(by[k])), f(n), 100.0 * len(by[k]) / n,
                 f(int(len(items) * len(by[k]) / n))))
    if a.read:
        print("\n══ 抽读（判官不是真值，我要自己看）══")
        for k in ("other", "sense"):
            for it in by[k][:a.read]:
                print("\n[%s] %s  义项：%s" % (k, it["w"], it["sense"][:24]))
                print("   FR %s" % it["fr"][:130])
                print("   ZH %s" % it["zh"][:110])
    return 0


if __name__ == "__main__":
    sys.exit(main())
