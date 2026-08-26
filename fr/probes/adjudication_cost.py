#!/usr/bin/env python3
"""裁决（法语释义 → 挂到哪条义项）的**成本实测**，不是估算。2026-08-25。

═══ 为什么单独量 ═══
我此前跟用户说过「对齐裁决那 17.5 万条**我没测过**，粗估 14–17M，**这个数不可信**」。
`[[ship-dont-measure-in-circles]]` 的反面教训是原地打转，但
`[[control-must-cover-every-output-field]]` 的教训是**没测就开跑烧掉 418 万作废**。
⇒ 量一次，量准，然后再决定花不花。

═══ 成本的真实驱动量 ═══
🔴 不是"待裁决的法语释义条数"，是**按 (词形, 词性) 分组后，每组要送进 prompt 的全部文本**：
   一条法语释义必须和它那个词性下**我们的全部候选义项**一起送，
   否则模型没法判断它该挂哪条（`probes/alignability.py` 的原话）。
   ⇒ 一个 5 义项的词，送 1 条法语释义和送 4 条，输入几乎一样贵 —— **按组算，不按条算**。

本探针只读库，输出：组数 / 各桶分布 / 字符量 / 按实测 token 率折算的钱。
跑：python3 -u probes/adjudication_cost.py       （在 fr/ 目录下）
"""
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths   # noqa: E402

# 实测率（`probes/translation_model_bakeoff.py` 那轮，批 160、关思考、全新内容）：
# 法语/中文混合文本约 2.6 字符/token；DeepSeek flash 低谷价（USD/M）。
CHARS_PER_TOKEN = 2.6
DS_OFF_IN, DS_OFF_HIT, DS_OFF_OUT = 0.22, 0.007, 0.66
FX = 7.1


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("■ 读库…")
    # 我们的可见义项：按 (word_id, pos) 分组，带中文与英文
    ours = {}
    for wid, pos, sid, zh, en in con.execute("""
            SELECT s.word_id, s.pos, s.id,
                   (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' LIMIT 1),
                   (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='en' LIMIT 1)
            FROM sense s WHERE s.hidden=0"""):
        ours.setdefault((wid, pos), []).append((sid, zh or "", en or ""))

    by_word = {}
    for (wid, _pos), cs in ours.items():
        by_word.setdefault(wid, []).extend(cs)

    # 待裁决：证据层有、但**这条文本还没上过出版层**的法语释义
    pub = set()
    for wid, t in con.execute("""
            SELECT s.word_id, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id
            WHERE g.lang='fr'"""):
        pub.add((wid, t))
    todo = {}
    for wid, t in con.execute(
            "SELECT word_id, text FROM sense_src WHERE src='fr-edition'"):
        if (wid, t) not in pub:
            todo.setdefault(wid, []).append(t)
    n_rows = sum(len(v) for v in todo.values())
    print("   待裁决的法语释义 %s 条，涉及 %s 个词形"
          % (format(n_rows, ","), format(len(todo), ",")))

    # 组装：一个词形一组（词性在组内，让模型自己按词性配）
    bucket = Counter()
    in_chars = out_chars = 0
    groups = 0
    for wid, frs in todo.items():
        cands = by_word.get(wid, [])
        if not cands:
            bucket["桶0：我们没有可见义项 ⇒ 直接建新义项，**不用裁决**"] += len(frs)
            continue
        groups += 1
        if len(cands) == 1 and len(frs) == 1:
            bucket["桶①：我们1条·法文版1条"] += 1
        elif len(cands) == 1:
            bucket["桶①'：我们1条·法文版多条"] += len(frs)
        else:
            bucket["桶③：我们多条"] += len(frs)
        # 输入 = 我们的候选（中文+英文）+ 法语释义；输出 = 每条法语释义一个 id
        in_chars += sum(len(z) + len(e) for _s, z, e in cands) + sum(len(t) for t in frs)
        out_chars += 18 * len(frs)

    print("\n══ 分桶（按待裁决的法语释义条数）══")
    for k, v in bucket.most_common():
        print("   %-42s %9s" % (k, format(v, ",")))
    print("   %-42s %9s" % ("要送模型的组数（一个词形一组）", format(groups, ",")))

    # prompt 开销：系统提示按 600 token 摊到每批 60 组
    tok_in = in_chars / CHARS_PER_TOKEN + groups / 60 * 600
    tok_out = out_chars / CHARS_PER_TOKEN
    print("\n══ token（按实测 %.1f 字符/token 折算）══" % CHARS_PER_TOKEN)
    print("   输入 %s ｜ 输出 %s ｜ **合计 %s**"
          % (format(int(tok_in), ","), format(int(tok_out), ","),
             format(int(tok_in + tok_out), ",")))
    usd = (tok_in * DS_OFF_IN + tok_out * DS_OFF_OUT) / 1e6
    print("   低谷时段 $%.2f ≈ **%.0f 元**（高峰翻倍）" % (usd, usd * FX))
    print("\n⚠️ 这是**算出来的**，不是估的；真值要等 1% 切片跑完用实测单价重算一次。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
