#!/usr/bin/env python3
"""阶段 1.5c 切片：**带 ECDICT 锚 vs 不带锚** 的 A/B 实测。2026-09-07。

用户 2026-09-07 指定模型 `deepseek-v4-flash`、批准跑 2,000 条切片。

═══ 这个切片要回答的问题（不是"能不能翻"，那不用测）═══
**en 独有一份别的语种没有的资产：ECDICT 的人工中文。**
79.6% 的义项所属的词有干净的 ECDICT 中文可当锚。
问题是：**把它写进 prompt 值不值**——省不省 token、质量差多少。
只有 A/B 能回答，所以同一批跑两次。

⚠️ 锚是**词条级**的（整块 `n. 苹果；苹果树`），义项是**义项级**的。
   给锚 ≠ 让它抄 —— prompt 里写死「锚是同一个词的既有中文，可能对应别的义项；
   **只在语义确实吻合时参考，不吻合就无视**」。
   `[[context-you-give-leaks-into-output]]`：it 那轮把法语原文当"仅供参考"传进去，
   母地名直接漏进 1,583 条结果。所以锚的用途必须在规则里说死。

═══ 分层取样，不随机 ═══
翻译事故在长尾（`[[en-dict-pipeline]]`：无源可查的词错误率卡在 24–25%）。
四层各取：核心 600 ／ 有锚 600 ／ 无锚长尾 600 ／ 长释义 200。

═══ 判据 ═══
· 单价：入/出 token **分开记**（flash 入 $0.44/M、出 $1.32/M，差 3 倍）
· 质量：核心那层用 ECDICT 人工中文当**负控**逐条比 —— 五门里只有 en 有这个条件
· 能支撑的决定：全量报价 ／ 要不要带锚 ／ 买到哪条 `freq_rank` 线

跑：
    cd en && python3 -u pipeline/translate_slice.py --plan     # 只看取样，不发请求
    cd en && python3 -u pipeline/translate_slice.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import random
import re
import sqlite3

import paths
import slot_translate as st

OUT = paths.WORK / "slice"
NET = re.compile(r"\[网络\]")

RULES = """你是英汉词典编纂者。把每条英文释义译成简体中文的**词典释义**。

规则：
1. 输出**词典体**，不是句子翻译。名词给名词说法，动词给动词说法。
2. 多个近义中文用「，」分隔；不同义项不要合并。
3. 专业术语用**通行中文术语**；学科可用方括号前缀，如 [化] [医] [计]。
4. 地名人名用**通行译名**；没有通行译名的**保留原文**，不要生造音译。
5. 释义里出现的英文原词不要照抄进中文，除非它本身就是中文里的通行写法。
6. **绝不编造**。释义看不懂或信息不足时，输出空字符串。
7. 只输出 JSON 数组，每项 {"id": <原样回传>, "zh": "<中文>"}。不要解释。"""

ANCHOR_RULE = """
8. 每条可能带 `ref` 字段：**这个词已有的中文**（来自另一部人工审校词典，是**词条级**的，
   可能对应这个词的**别的义项**）。用法：
   · 语义确实吻合 → 可以采用它的用词与术语选择，保持术语一致；
   · **不吻合 → 完全无视它**，按 `en` 的意思译。
   · 绝不把 `ref` 里与本义项无关的部分抄进输出。"""


def pick(con, n_core, n_anchor, n_tail, n_long, seed=20260907):
    q = con.execute
    ptr = {s for (s,) in q("SELECT sense_id FROM sense_src WHERE "
                           "raw_tags LIKE '%\"form-of\"%' OR raw_tags LIKE '%\"alt-of\"%')")} \
        if False else {s for (s,) in q(
            "SELECT sense_id FROM sense_src WHERE raw_tags LIKE '%\"form-of\"%' "
            "OR raw_tags LIKE '%\"alt-of\"%'")}
    rows = []
    for sid, wid, pos, w, en, frq, tag, lgtext, lgqual in q("""
        SELECT s.id, s.word_id, s.pos, d.word, g.text, d.freq_rank, d.exam_tag,
               lg.text, lg.qual
        FROM sense s
        JOIN dict d ON d.id = s.word_id
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='en'
        LEFT JOIN legacy_gloss lg ON lg.word_id = s.word_id"""):
        if sid in ptr:
            continue
        anchor = None
        if lgtext and not NET.search(lgtext):
            anchor = " / ".join(l.strip() for l in lgtext.split("\n") if l.strip())[:180]
        rows.append({"id": sid, "word": w, "pos": pos or "", "en": en,
                     "ref": anchor, "_core": bool(frq or tag), "_len": len(en)})
    rnd = random.Random(seed)
    rnd.shuffle(rows)
    out, seen = [], set()

    def take(pred, k):
        got = 0
        for r in rows:
            if got >= k:
                break
            if r["id"] in seen or not pred(r):
                continue
            seen.add(r["id"])
            out.append(r)
            got += 1
        return got

    got = {"核心": take(lambda r: r["_core"], n_core),
           "有锚": take(lambda r: r["ref"], n_anchor),
           "无锚长尾": take(lambda r: not r["ref"], n_tail),
           "长释义>200": take(lambda r: r["_len"] > 200, n_long)}
    return out, got, len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--core", type=int, default=600)
    ap.add_argument("--anchor", type=int, default=600)
    ap.add_argument("--tail", type=int, default=600)
    ap.add_argument("--long", type=int, default=200)
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items, got, pool = pick(con, a.core, a.anchor, a.tail, a.long)
    con.close()
    print("═══ 1.5c 切片取样 ═══")
    print("   付费池（非指针义项）%s" % format(pool, ","))
    for k, v in got.items():
        print("      %-12s %s" % (k, v))
    print("   合计 %s 条 ；其中带锚 %s"
          % (format(len(items), ","), format(sum(1 for i in items if i["ref"]), ",")))
    print("\n   样本：")
    for r in items[:4]:
        print("      #%-9s %-16s %-5s %s" % (r["id"], r["word"][:16], r["pos"], r["en"][:44]))
        if r["ref"]:
            print("                 ref: %s" % r["ref"][:60])
    if not a.run:
        print("\n(只看取样。加 --run 才发请求)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    st.announce_window()
    # ── A 轮：不带锚
    a_items = [{k: v for k, v in r.items() if k != "ref"} for r in items]
    print("\n══ A 轮：不带锚 ══")
    sa = st.translate(a_items, RULES, OUT / "slice_noanchor.jsonl",
                      fields=("id", "en", "word", "pos"), keep=("id", "word"))
    # ── B 轮：带锚（只发有锚的）
    b_items = [r for r in items if r["ref"]]
    print("\n══ B 轮：带锚（%s 条）══" % format(len(b_items), ","))
    sb = st.translate(b_items, RULES + ANCHOR_RULE, OUT / "slice_anchor.jsonl",
                      fields=("id", "en", "word", "pos", "ref"), keep=("id", "word"))

    print("\n═══ 单价实测 ═══")
    for name, s, n in (("A 不带锚", sa, len(a_items)), ("B 带锚", sb, len(b_items))):
        if not n or not s.get("tok"):
            continue
        print("   %-8s %s 条 ｜ token %s（入 %s ／ 出 %s）｜ **%.1f token/条**"
              % (name, format(n, ","), format(s["tok"], ","),
                 format(s.get("tok_in", 0), ","), format(s.get("tok_out", 0), ","),
                 s["tok"] / n))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
