#!/usr/bin/env python3
"""外审：把**渲染出来的成品**发给模型挑错，我逐条回源裁决。2026-09-09（en 阶段 7）。

═══ 为什么发渲染成品而不是导库 ═══
用户 2026-08-21 定的：「把我们在前端页面展示给用户的结果发给…」。
**缺陷只在渲染之后才存在** —— en 今天又验了两次：
  · `panther[Panthera`（wikitext 残渣）—— 库里查 `target LIKE '%[%'` 才看得见，
    而我是在渲染出来读到的。
  · `oneself` 的中文**修进库了、闸也报 0**，页面上仍然是空的 ——
    展示层的条件问的是「有没有义项」而不是「有没有中文」。

═══ 纪律（照 `[[llm-as-evaluator-discipline]]`）═══
· 一问一答，**不是跑批**（`[[large-fill-use-turbo-batch]]` 禁的是跑批）
· ⑨ **别把结论写进评审材料标题** —— 不写「我们做得怎么样」「请确认质量很好」，
  否则模型收敛的是我的偏见
· ⑩ **能确定性回源比对的根本别问模型** ⇒ 材料里不问行数、不问覆盖率、不问"缺了多少"
· 结果**逐条回源裁决**，包括我判它说错的那些 —— **模型共识不是证据**
  （`[[verify-before-claiming-confirmed]]`）

⚠️ **只有一家模型时要说清楚**，不许把一家的意见说成"外审共识"。

    cd en && python3 -u probes/en_review.py --part 1
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import slot_translate                                   # noqa: E402

SRC = Path("/Users/fangyi/.claude/jobs/c235368c/tmp/en_render.md")

SYS = """下面是一部**英汉词典**若干词条页的**最终渲染结果**（用户看到的就是这些文字）。

请你作为英语母语者 + 词典编纂者审阅，**只挑错**，不必夸奖。重点看：

1. **中文释义是否准确**：有没有译错、译反、丢义项、把甲义项的中文安到乙义项上。
2. **英语原文释义与中文是否对得上**：同一条义项下两者应当说的是同一件事。
3. **例句与译文**：有没有译错、译反、张冠李戴；书证的出处有没有混进译文。
4. **词形还原 / 词形变化**：某个形式是不是真的属于那个词元？语法标签对不对？
5. **音标**：明显错的读音；地区标注与音标是否矛盾。
6. **任何看起来不像词典该有的东西**：占位符、残缺、重复、自相矛盾、维基标记残渣。

🔴 输出格式（**外层必须是这个壳**，`id` 原样回传，否则我这边认领不到）：
[{"id": "<把输入里的 id 原样抄回来>",
  "issues": [{"w": "词条", "kind": "释义/例句/变形/音标/其它",
              "quote": "<原文里出错的那一小段>",
              "why": "<错在哪，一句话>", "fix": "<你认为应该是什么>"}]}]

🔴 **每片最多报 3 条，按严重程度排序。** 判据：

  · **只报你愿意打赌是错的** —— 改了之后读者确实更好，不是"也可以那样说"。
  · **措辞可以更好、但不算错的，不要报。**（"直译虽可理解但…"这类一律不报）
  · **原文（英语释义、书证选取、义项划分）是维基词典给的，不归我们改** ——
    你觉得那条书证不该挂在这个义项下、或那句引文不雅，都不要报；
    只报**中文侧**和**排版侧**的问题。
  · 再给每条加一个 `"sure"` 字段：`"高"`（我确信）／`"中"`（多半是）。

⚠️ 只输出 JSON。"""

# 🔴🔴 **第一版 prompt 的失败不是模型的错，是我把判官造得不可裁决。**
#    第一轮 52 片报回 **599 条**，而我逐条回源裁决的能力是几十条量级 ——
#    关键词只能归类 17%，剩下 499 条要一条条读。
#    **没有裁决的判官产出不是证据**（`[[llm-as-evaluator-discipline]]`）。
#    抽验 25 条的结果：真缺陷 1 族（书证出处的位置，已修）；
#    其余是措辞挑剔（自认"可接受"）／对 kaikki 自身义项挂载的意见（不归我们）／
#    我导出器的假象（"真人发音"那栏被我剥掉了播放按钮的文字）。
#    ⇒ ⑬ 那条「判官错误率 ≥ 缺陷率就别造」有个新形状：
#      **判官的产出规模超过裁决能力，同样等于没有判官。**
#      修法是**给判官设配额并划清边界**，不是我硬读。

# 🔴🔴 上面那个「外层壳」不是可有可无的说明：第一版 prompt 只写了
#    「输出 JSON 数组，每条一个问题」，模型照做输出了扁平数组 ——
#    而 `slot_translate._ask` 认领应答的条件是 `key_field in o`（这里是 `id`）
#    ⇒ 一条都认领不上，重试 5 次后大声放弃，白烧 103,921 token（0.58 元）。
#    **模型「答不出」先怀疑自己的 prompt**（`[[prompt-self-harm-two-patterns]]`）——
#    它答得好好的，是我的 prompt 与调用契约自相矛盾。


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", type=int, default=1)
    # 🔴 **一条词条一发**（`--parts` 默认 = 词条数）。
    #    3 个词条一起发（29,153 字符）连试 5 次全失败、白烧 21.7 万 token ——
    #    不是模型答不出：单发 8,159 字符时格式完全正确、`finish_reason=stop`。
    #    多发时输出要 8K+ token，被截断 ⇒ JSON 解不出 ⇒ 一条都认领不上。
    #    ⚠️ 诊断花了两轮猜测（先怀疑 prompt 契约、再怀疑格式），
    #      **早点把原始返回打出来就一眼看见了** —— 猜比看贵。
    ap.add_argument("--parts", type=int, default=0)
    a = ap.parse_args()
    if not SRC.exists():
        print("🔴 渲染材料不存在：%s\n   先跑 render-dump.tsx --lang en" % SRC)
        return 1
    # 🔴🔴 **按字符切，不按词条切。**
    #    第一版「一条词条一发」仍然烧掉了钱：`the`（8,159 字符）好好的，
    #    `a`（23,532 字符）连试 5 次全失败、每次 8.3 万 token ≈ 0.5 元 ——
    #    因为**失败的原因是输出被截断**，而输出长度跟着输入长度走。
    #    「一条一发」只是把输入变小了一点，没有解决那个不等式。
    #    ⚠️ 这种重试**结构上不可能收敛**（`[[retry-must-converge-or-drop-loud]]`）：
    #      同样的输入必然得到同样长的输出，试 5 次只是把钱乘以 5。
    #      ⇒ 我在它烧完第 5 个词条时手动停了，没让它把 21 条各烧一遍。
    #    ⇒ 切片上限 = 实测能跑通的那个量级（`the` 8.2K 字符 → 2,776 token 输出）。
    CAP = 8000
    blocks, cur = [], []
    for ln in SRC.read_text(encoding="utf-8").splitlines(True):
        if ln.startswith("## ") and cur:
            blocks.append("".join(cur)); cur = []
        cur.append(ln)
    if cur:
        blocks.append("".join(cur))
    # 超过 CAP 的词条页再按行切开；每片都带上它属于哪个词
    chunks = []
    for b in blocks:
        head = b.split("\n", 1)[0]
        if len(b) <= CAP:
            chunks.append(b)
            continue
        lines, buf = b.split("\n"), []
        for ln in lines:
            if sum(len(x) + 1 for x in buf) + len(ln) > CAP and buf:
                chunks.append(head + "（接上页）\n" + "\n".join(buf))
                buf = []
            buf.append(ln)
        if buf:
            chunks.append(head + "（接上页）\n" + "\n".join(buf))
    blocks = chunks
    n = len(blocks)
    parts = a.parts or n
    lo, hi = (a.part - 1) * n // parts, a.part * n // parts
    text = "".join(blocks[lo:hi])
    print("■ 全部 %d 个词条页；本批第 %d/%d = %d 页 / %s 字符"
          % (n, a.part, parts, hi - lo, format(len(text), ",")))
    out = Path(str(SRC) + ".review%d.json" % a.part)
    got = slot_translate.done_keys(out, land="id")
    if not got:
        # 🔴 `key_field` 必须在 `fields` 里（en 版 slot_translate 有硬闸）——
        #    de 那份调用写的是 fields=("md",)+key_field="id"，抄过来会当场抛错。
        slot_translate.translate(
            [{"id": "part%d" % a.part, "md": text}], SYS, out,
            fields=("id", "md"), keep=("id",), key_field="id",
            answer_field="issues", land="id")
        got = slot_translate.done_keys(out, land="id")
    rec = got.get("part%d" % a.part)
    if not rec:
        print("🔴 没有拿到应答")
        return 1
    issues = rec.get("issues") or []
    if not isinstance(issues, list):
        issues = []
    print("\n■ 模型报了 %d 条问题" % len(issues))
    for i, x in enumerate(issues):
        print("\n[%d] %s ｜ %s" % (i + 1, x.get("w"), x.get("kind")))
        print("    原文：%s" % str(x.get("quote"))[:100])
        print("    问题：%s" % str(x.get("why"))[:120])
        print("    建议：%s" % str(x.get("fix"))[:100])
    return 0


if __name__ == "__main__":
    sys.exit(main())
