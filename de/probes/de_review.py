#!/usr/bin/env python3
"""外审：把**渲染出来的成品**发给模型挑错，我逐条回源裁决。2026-09-04（de 收尾）。

═══ 为什么发渲染成品而不是导库 ═══
用户 2026-08-21 定的：「把点测的结果（也就是我们在前端页面展示给用户的结果）发给…」。
「展示给用户的结果」这句就是判据本身 —— 缺陷**只在渲染之后才存在**：
`TVTB` 那条接口返回完全正确，错只在组件里一行 `entry.isLemma &&`，查库查接口都看不见。
⚠️ de 今天就又验了一次：`die` 的页面印着 `20-Jährige 主格`（冠词被当成名词变格形），
   536 万行变形里按行数/不变量做的闸**全都看不见**，导出的动作本身把它照了出来。

═══ 🔴 这一轮的价值在哪（`[[render-review-with-models]]`）═══
fr 七个评审族里**四个是外审逮到的**，而它逮的是闸永远够不到的东西 ——
**语言学判断**（`treno` 丢了「火车」、`fare` 的「赠送」与意语原文方向相反）。
⭐ 分工是互补不可替代的：**形式残渣是确定性判据的活、模型看不见；模型强在语言学判断。**

═══ 纪律 ═══
· 一问一答，**不是跑批**（`[[large-fill-use-turbo-batch]]`：禁的只是跑批）
· ⑨ **别把结论写进评审材料标题** —— fr 那轮「两家收敛的是我的偏见」
· ⑩ **能确定性回源比对的根本别问模型** ⇒ 材料里不问行数、不问覆盖率
· 结果**逐条回源裁决**，包括我判它说错的那些（模型共识不是证据）

用法（在 de/ 目录下）：
    python3 -u probes/de_review.py --part 1
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import slot_translate                                   # noqa: E402

SRC = Path("/private/tmp/claude-501/-Users-fangyi-demo-synapse-dict/"
           "c00232b0-9c6c-4945-b59a-bb948246b318/scratchpad/de_render.md")

# ⚠️ 不写「我们做得怎么样」「请确认质量很好」这类话 —— ⑨ 那条：
#    评审材料的标题不许携带结论，否则两家收敛的是我的偏见。
SYS = """下面是一部**德汉词典**若干词条页的**最终渲染结果**（用户看到的就是这些文字）。

请你作为德语母语者 + 词典编纂者审阅，**只挑错**，不必夸奖。重点看：

1. **中文释义是否准确**：有没有译错、译反、丢义项、把甲义项的中文安到乙义项上。
2. **德语原文释义与中文是否对得上**：同一条义项下两者应当说的是同一件事。
3. **词形还原 / 词形变化是否正确**：某个形式是不是真的属于那个词元？语法标签对不对？
4. **例句与译文**：有没有译错、译反、张冠李戴。
5. **音标**：明显错的读音。
6. **任何看起来不像词典该有的东西**：占位符、残缺、重复、自相矛盾。

输出 JSON 数组，每条一个问题：
[{"w": "词条", "kind": "释义/变形/例句/音标/其它", "quote": "<原文里出错的那一小段>",
  "why": "<错在哪，一句话>", "fix": "<你认为应该是什么>"}]

⚠️ 只报你**确信**是错的。拿不准就不要写进来。只输出 JSON。"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", type=int, default=1)
    ap.add_argument("--parts", type=int, default=4)
    a = ap.parse_args()

    blocks, cur = [], []
    for ln in SRC.read_text(encoding="utf-8").splitlines(True):
        if ln.startswith("## ") and cur:
            blocks.append("".join(cur)); cur = []
        cur.append(ln)
    if cur:
        blocks.append("".join(cur))
    n = len(blocks)
    lo = (a.part - 1) * n // a.parts
    hi = a.part * n // a.parts
    text = "".join(blocks[lo:hi])
    print("■ 全部 %d 个词条页；本批第 %d/%d 批 = %d 页 / %d 字符"
          % (n, a.part, a.parts, hi - lo, len(text)))

    out = Path(str(SRC) + ".review%d.json" % a.part)
    got = slot_translate.done_keys(out, land="id")
    if got:
        print("（本批已审过，跳过）")
    else:
        slot_translate.translate(
            [{"id": "part%d" % a.part, "md": text}], SYS, out,
            fields=("md",), keep=("id",), key_field="id",
            answer_field="issues", land="id")
        got = slot_translate.done_keys(out, land="id")
    rec = got.get("part%d" % a.part)
    if not rec:
        print("🔴 没有拿到应答")
        return 1
    issues = rec.get("issues") or []
    print("\n■ 模型报了 %d 条问题" % (len(issues) if isinstance(issues, list) else 0))
    for i, x in enumerate(issues if isinstance(issues, list) else []):
        print("\n[%d] %s ｜ %s" % (i + 1, x.get("w"), x.get("kind")))
        print("    原文：%s" % str(x.get("quote"))[:90])
        print("    问题：%s" % str(x.get("why"))[:110])
        print("    建议：%s" % str(x.get("fix"))[:90])
    return 0


if __name__ == "__main__":
    sys.exit(main())
