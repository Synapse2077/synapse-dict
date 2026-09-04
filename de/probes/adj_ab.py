#!/usr/bin/env python3
"""对齐裁决的 A/B：关思考 vs 开思考，同一批 300 个词。2026-09-04。

═══ 为什么要跑这个 ═══
两条记忆在这里**互相冲突**，我不打算靠记忆裁决：
  · `[[batch-never-enables-thinking]]`：跑批一律关思考（用户 2026-08-15 定），
    判据是「任务是不是推导型」——翻译不是。
  · `[[llm-as-evaluator-discipline]]` ⑦：**推导型判官必须开思考**
    （v4-pro 关思考在 es 上 0/2 摆烂）。
对齐裁决**是**推导型 ⇒ 规则本身没说清该怎么办 ⇒ 用数据定。

═══ 🔴 顺带回答一个比准确率更重要的问题 ═══
fr 那轮的教训（`[[llm-as-evaluator-discipline]]`）：正控我量了三版
60.7% → 77.3% → 100%，**前两版全是我的分母错** —— 54.5% 的题根本没有唯一正确答案。

⇒ **两轮独立作答的一致率，是「这题有没有唯一答案」的一个便宜代理**：
  · 两轮一致 ⇒ 题目大概率是良定义的（两次独立推理落到同一处）
  · 两轮不一致 ⇒ 要么题本身有歧义、要么至少一轮错 —— **都是不该盲目全量的信号**
⚠️ 它**只是代理，不是真值**：两轮可能一致地错。所以下面还打样给人读。

用法（在 de/ 目录下）：
    python3 -u probes/adj_ab.py
    python3 -u probes/adj_ab.py --read 12      # 打样：不一致的那些
"""
import argparse
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths                                                   # noqa: E402
import slot_translate                                          # noqa: E402
from adjudicate_de_glosses import OUT_OFF, OUT_ON, pool, inject_negative  # noqa: E402

f = lambda n: format(n, ",")


def mapping(rec):
    """→ {德语释义序号: 义项标识号或 None}。坏行按"没答"处理。"""
    out = {}
    for x in (rec.get("m") or []):
        if isinstance(x, dict) and "i" in x:
            out[x["i"]] = x.get("s")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--read", type=int, default=0)
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = pool(con)
    con.close()
    rng = random.Random(11)
    want = rng.sample(items, min(300, len(items)))
    planted = inject_negative(want, rng)          # 与跑批时同种子、同顺序

    off = slot_translate.done_keys(OUT_OFF, land="id")
    on = slot_translate.done_keys(OUT_ON, land="id")
    both = [it for it in want if it["id"] in off and it["id"] in on]
    print("■ 两轮都答了的词 %s / %s" % (f(len(both)), f(len(want))))

    c = Counter()
    diff = []
    for it in both:
        mo, mn = mapping(off[it["id"]]), mapping(on[it["id"]])
        pl = planted.get(it["id"], set())
        for d in it["de"]:
            i = d["i"]
            k = "负控条" if i in pl else "真题"
            x, y = mo.get(i, "缺"), mn.get(i, "缺")
            if x == y:
                c[k + "·两轮一致"] += 1
                if x is None:
                    c[k + "·两轮都判 null"] += 1
            else:
                c[k + "·🔴 两轮不一致"] += 1
                if k == "真题":
                    diff.append((it, d, x, y))

    tot = sum(v for k, v in c.items() if "两轮" in k and "都判" not in k)
    print("\n══ A/B 结果（按德语释义条计）══")
    for k, v in sorted(c.items()):
        print("   %-28s %7s  %5.1f%%" % (k, f(v), 100.0 * v / max(tot, 1)))
    real = c["真题·两轮一致"] + c["真题·🔴 两轮不一致"]
    if real:
        print("\n⭐ **真题两轮一致率 %.1f%%**（%s / %s）—— 「这题有没有唯一答案」的代理"
              % (100.0 * c["真题·两轮一致"] / real, f(c["真题·两轮一致"]), f(real)))
        print("   其中两轮都判 null 的 %s 条（源头写了我们没有的义项，本来就该留空）"
              % f(c["真题·两轮都判 null"]))
    npl = c["负控条·两轮一致"] + c["负控条·🔴 两轮不一致"]
    if npl:
        print("   负控条两轮一致 %s / %s" % (f(c["负控条·两轮一致"]), f(npl)))

    if a.read and diff:
        print("\n══ 打样：两轮不一致的 %d 条（人眼核，判据在这里不管用）══" % min(a.read, len(diff)))
        zh = {}
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        for sid, t in con.execute("SELECT sense_id, text FROM sense_gloss WHERE lang='zh'"):
            zh[sid] = t
        con.close()
        for it, d, x, y in random.Random(3).sample(diff, min(a.read, len(diff))):
            print("\n── %s ──  de[%d] %s" % (it["w"], d["i"], d["t"][:64]))
            print("     关思考 → %-8s %s" % (x, (zh.get(x) or "（null）")[:26]))
            print("     开思考 → %-8s %s" % (y, (zh.get(y) or "（null）")[:26]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
