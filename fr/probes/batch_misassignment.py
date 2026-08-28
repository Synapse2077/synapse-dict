#!/usr/bin/env python3
"""跑批**答案贴错条目**的离线诊断器 —— 不请模型，先把范围缩小 39 倍。2026-08-28。

═══ 这个文件是一次教训的产物 ═══
🔴 我先报了「判 472,100 条例句 ≈ 120 元」，用户顶回来（「你是要承认之前的工作白做了吗」），
   我才回头做**本该先做的调查**。做完之后同一件事花了 **2 元**，找到 1,145 条。
   差 60 倍。差的不是价格，是**我没调查就开口**。
⇒ 规矩：**报价之前必须先写清楚「我试过哪些免费路径、各自为什么不行」**。
   写不出这一段，就是还没调查完，没资格开口要钱。

═══ 缺陷是什么 ═══
`slot_translate` 老版本 `key_field="id"` 而落盘按 `fr`：模型把 B 句的译文标上 A 的 id，
A 就拿到了 B 的中文。`[[model-answer-files-key-by-id]]` 记过这个根因，
2026-08-28 已在 `slot_translate` 做成硬约束（`land="id"` + 落盘键唯一性检查），
**不会再发生**；本文件是清存量的。

═══ 两个离线信号，第二个才管用 ═══

**① 重复型**：A 拿了 B 的译文，而 B 被重排队后又答对了 ⇒ **同一段中文出现两次**。
   查得到，但**随机抽样上召回 0/3** —— 它只覆盖少数模式。
   ⚠️ 光看「同一中文」会误伤：`Espèce d'empafé!`/`Espèce d'abruti!` 都译「你这个蠢货！」
     是对的。要加「组内法语句子词汇重叠 ≤0.15」。

**② 对调型 ⇒ 批内长度相关性**（**这个才是主力**）：
   `pool()` 是 `ORDER BY id` 确定性的、`CHUNK=40` ⇒ **批次可完整重建**。
   批内配对被打乱 ⇒ 长句配到短译文 ⇒ 该批 `len(fr)~len(zh)` 的 Spearman 相关塌掉。

       全库 15,381 批   中位数 **0.950**   10 分位 0.898   1 分位 0.685
       判官随机抽样逮到的 2 条真 A6，**都落在最低 0.1% 的批里**（r=0.274 / 0.196）

   取最低 1% 的批送判官：**other 1,145 / 3,924 = 29.2%**，而全库随机是 0.75%
   ⇒ **富集 39 倍**。50.3 万 token ≈ 2 元。

⚠️ 长度相关性**不是「这条译文对不对」的判据**，是「**这一批的配对乱没乱**」的判据 ——
   信号在**批**这一层，不在条目这一层。用它去判单条就是形式代理
   （`[[criteria-from-meaning-not-form]]`）。它只负责缩小范围，判还是判官判、人还是要抽读。

用法（在 fr/ 目录下）：
    python3 -u probes/batch_misassignment.py                # 只出相关性分布
    python3 -u probes/batch_misassignment.py --pct 1        # 列出最低 1% 批的例句 id
"""
import argparse
import sqlite3
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths                                    # noqa: E402
from pipeline import slot_translate             # noqa: E402

f = lambda n: format(n, ",")
CHUNK = 40          # 必须与当初跑批的 `slot_translate.CHUNK` 一致


def spearman(xs, ys):
    """秩相关。n<8 返回 None —— 批太小时这个统计量没意义。"""
    n = len(xs)
    if n < 8:
        return None
    rank = lambda v: {x: i for i, x in enumerate(sorted(range(n), key=lambda k: v[k]))}
    rx, ry = rank(xs), rank(ys)
    return 1 - 6 * sum((rx[i] - ry[i]) ** 2 for i in range(n)) / (n * (n * n - 1))


def chunks(con, answers):
    """复原当初的批次 → [(相关系数, [example_id…])]。

    🔴 复原依据：`translate_examples.pool()` 是 `SELECT id, text FROM example ORDER BY id`
       + 按文本去重，首跑时没有任何中文 ⇒ 顺序唯一确定。
       **改了 `pool()` 的顺序或 CHUNK，这个诊断就失效** —— 那时要重新对齐。
    """
    seen, items = set(), []
    for eid, t in con.execute("SELECT id, text FROM example ORDER BY id"):
        if t in seen:
            continue
        seen.add(t)
        items.append((eid, t))
    out = []
    for c0 in range(0, len(items), CHUNK):
        xs, ys, ids = [], [], []
        for eid, fr in items[c0:c0 + CHUNK]:
            z = (answers.get(fr) or {}).get("zh", "").strip()
            if not z:
                continue
            xs.append(len(fr))
            ys.append(len(z))
            ids.append(eid)
        r = spearman(xs, ys)
        if r is not None:
            out.append((r, ids))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pct", type=float, default=0,
                    help="列出相关系数最低的百分之几的批")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ans = slot_translate.done_keys(paths.WORK / "examples" / "example_zh.jsonl")
    cs = chunks(con, ans)
    rs = sorted(r for r, _i in cs)
    print("■ %s 批  中位数 %.3f  10分位 %.3f  1分位 %.3f  最低 %.3f"
          % (f(len(cs)), st.median(rs), rs[len(rs) // 10], rs[len(rs) // 100], rs[0]))
    for cut in (0.3, 0.5, 0.7):
        lo = [c for c in cs if c[0] < cut]
        print("   r < %.1f：%s 批（%.2f%%），%s 条例句"
              % (cut, f(len(lo)), 100.0 * len(lo) / len(cs), f(sum(len(i) for _r, i in lo))))
    if a.pct:
        cs.sort(key=lambda x: x[0])
        n = max(1, int(len(cs) * a.pct / 100))
        ids = [e for _r, i in cs[:n] for e in i]
        print("\n■ 最低 %.1f%% = %s 批 / %s 条（该档 r 上限 %.3f）"
              % (a.pct, f(n), f(len(ids)), cs[n - 1][0]))
        print(",".join(str(x) for x in ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
