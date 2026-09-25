#!/usr/bin/env python3
"""定价切片：**据汉字表记生成中文释义**，错误率有多高？ko，2026-09-25。

═══ 为什么必须先做这一步 ═══
K10 量到底之后，剩下能覆盖那 77.8% 无释义词元的路只有一条：**用模型据汉字生成**。
`[[blind-gloss-inference-ceiling]]` 记着：无源可查的词让模型按构词猜释义，
**错误率卡在 24–25% 纹丝不动**。这次不是"盲猜"——有汉字，但**到底降到多少要实测**。
`[[llm-as-evaluator-discipline]]` ⑬：**判官错误率 ≥ 缺陷率就别造，而且这个比较要在花钱之前做。**

═══ 判据：在**源头没错的那批行**上验（`[[validate-criterion-where-source-is-right]]`）═══
对照池 ＝ **已经有真中文释义** ＋ **恰好 1 个汉字表记** 的词，实测 **17,589 个**。
给模型只看「韩语词 ＋ 汉字 ＋ 词性」，**不给真释义**，让它写中文释义；
写完与真释义比。分歧率就是要买的那个数。

🔴🔴 **这个数是乐观的下界，不是真值 —— 必须写在脸上**：
   对照池是「**有**释义的词」，目标池是「**没有**释义的词」。
   前者偏常用（`10월`/`-씨`），后者偏生僻（`가는갈퀴나물`）。
   同一套规则在生僻词上只会更差。`[[llm-as-evaluator-discipline]]` ⑫：
   **取数把哪一类排除在外，判官自己永远不会说。**

═══ 目标池（真要生成的那批）═══
    无释义词元 207,469
      · 恰好 1 个汉字表记  **178,325（86.0%）**  ← 只打算做这批
      · ≥2 个汉字表记       16,093（7.8%）   ← **不做**：一个词形对应多个词
                                            （`사가` 有 12 个），生成一条就是替源头断言
      · 没有汉字            13,051（6.3%）   ← **不做**：那才是真·盲猜

跑（在仓库根）：
    python3 -u ko/pipeline/probe_hanja_gloss.py --n 300
    python3 -u ko/pipeline/probe_hanja_gloss.py --n 300 --judge   # 只重算，不再跑模型
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import hashlib
import json
import re
import sqlite3

import ds_batch
import paths

OUT = paths.WORK / "hanja_gloss_probe"
PER_BATCH = 20

SYS = """你是韩汉词典的释义编辑。根据给定的**汉字表记**写出这个韩语词的中文释义。

输入是一个 JSON 对象：键是编号，值含 w（韩语词头）、h（汉字表记）、p（词性）。
输出**同样的键**，值是 {"zh": "中文释义"}。键一个不许少、不许多、不许改。

规矩：
1. 译成**词典释义**的体例：名词用名词、动词用动词短语，不要写成句子，不要加句号。
2. 汉字表记是这个词的**词源写法**，多数情况下它的现代汉语对应词就是释义
   （`韓國` → 「韩国」）。但**韩语词义可能与现代汉语不同**，
   按**韩语里的实际意思**写，不要照抄汉字。
3. 汉字是日本新字体或异体的，按对应的通行汉字理解（`拠点`＝據點）。
4. **吃不准就写最直白的那个意思，不要编造细节**，不要加例句、不要加用法说明。
5. 只输出释义本身，不要出现韩语词头、罗马字、汉字表记。
6. 实在推不出来（汉字是人名/地名/纯音译用字且无通行义）就输出空字符串 ""。
   🔴 **宁可空着也不要编** —— 词典里错比缺更伤权威。"""

PROBE = {
    "__c1": {"w": "한국", "h": "韓國", "p": "name"},
    "__c2": {"w": "십이월", "h": "十二月", "p": "n"},
}


def pool(con):
    """对照池：有真中文释义 ＋ 恰好 1 个汉字表记。"""
    return con.execute("""
        WITH hj AS (
          SELECT word_id, COUNT(DISTINCT x) c, MIN(x) h FROM
            (SELECT word_id, hanja x FROM entry WHERE hanja IS NOT NULL
             UNION SELECT word_id, target FROM sense_relation
                    WHERE kind IN ('hanja_spelling','alt_hanja'))
          GROUP BY word_id)
        SELECT d.id, d.word, hj.h, COALESCE(e.pos,'unknown'),
               (SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id = s.id
                 WHERE s.word_id = d.id AND s.hidden = 0 AND g.lang='zh'
                 ORDER BY s.rank LIMIT 1)
          FROM dict d JOIN hj ON hj.word_id = d.id
          LEFT JOIN entry e ON e.word_id = d.id
         WHERE d.is_lemma = 1 AND hj.c = 1
           AND EXISTS(SELECT 1 FROM sense s JOIN sense_gloss g ON g.sense_id = s.id
                       WHERE s.word_id = d.id AND s.hidden = 0 AND g.lang='zh')
         GROUP BY d.id
         ORDER BY d.id""").fetchall()


def sample(rows, n):
    """按 id 的稳定哈希抽 —— **不是 `rows[::k]`**（Unicode 把 CJK 排在谚文前面，
    等距抽会抽出一堆生僻汉字，本项目一天内犯过三次）。"""
    rows = sorted(rows, key=lambda r: hashlib.md5(str(r[0]).encode()).hexdigest())
    return rows[:n]


PUNCT = re.compile(r"[，,、。.；;：:（）()「」“”\"'\s\-－—]+")


def norm(t):
    return PUNCT.sub("", t or "")


def compare(gen, truth):
    """→ ('同', '含', '异')。**只做确定性比对，不叫模型当判官**
    （`[[llm-as-evaluator-discipline]]` ⑬：判官错误率 ≥ 缺陷率就别造）。
    分歧的那一堆留给人读 —— 这一步买的是**上界**，不是精确率。"""
    a, b = norm(gen), norm(truth)
    if not a:
        return "空"
    if a == b:
        return "同"
    # 任一方是另一方的子串，或并列项里有交集
    if a in b or b in a:
        return "含"
    sa = {x for x in PUNCT.split(truth or "") if x}
    sb = {x for x in PUNCT.split(gen or "") if x}
    return "含" if sa & sb else "异"


async def run(rows, conc):
    OUT.mkdir(parents=True, exist_ok=True)
    batches, meta = [], []
    for i in range(0, len(rows), PER_BATCH):
        chunk = rows[i:i + PER_BATCH]
        pay = {str(r[0]): {"w": r[1], "h": r[2], "p": r[3]} for r in chunk}
        m = [(str(r[0]), r[0]) for r in chunk]
        ck = list(PROBE)[i // PER_BATCH % len(PROBE)]
        pay[ck] = PROBE[ck]
        m.append((ck, ck))
        batches.append(pay)
        meta.append(m)
    path = OUT / "probe.jsonl"
    ntok = await ds_batch.run(SYS, batches, meta, path,
                              mode="flash", conc=conc, every=5)
    return path, ntok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--conc", type=int, default=30)
    ap.add_argument("--judge", action="store_true", help="只重算，不再跑模型")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = pool(con)
    print("■ 对照池（有真中文释义 ＋ 恰好 1 个汉字表记）：%s 个词"
          % format(len(rows), ","))
    pick = sample(rows, a.n)
    print("   抽 %d 个（按 id 稳定哈希，不按顺序）" % len(pick))

    # 目标池有多大 —— 报价要用
    target = con.execute("""
        WITH hj AS (SELECT word_id, COUNT(DISTINCT x) c FROM
            (SELECT word_id, hanja x FROM entry WHERE hanja IS NOT NULL
             UNION SELECT word_id, target FROM sense_relation
                    WHERE kind IN ('hanja_spelling','alt_hanja')) GROUP BY word_id)
        SELECT COUNT(*) FROM dict d JOIN hj ON hj.word_id = d.id
         WHERE d.is_lemma = 1 AND hj.c = 1
           AND NOT EXISTS(SELECT 1 FROM sense s JOIN sense_gloss g ON g.sense_id=s.id
                           WHERE s.word_id=d.id AND s.hidden=0)""").fetchone()[0]
    print("   目标池（无释义 ＋ 恰好 1 个汉字表记）：%s 个词" % format(target, ","))
    con.close()

    path = OUT / "probe.jsonl"
    ntok = None
    if not a.judge:
        ds_batch.announce_window()
        path, ntok = asyncio.run(run(pick, a.conc))

    got = {}
    for line in path.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        got[d["id"]] = d.get("zh")

    import collections
    stat = collections.Counter()
    diff = []
    for wid, w, h, pos, truth in pick:
        g = got.get(wid)
        if g is None:
            stat["🔴 没回来"] += 1
            continue
        k = compare(g, truth)
        stat[k] += 1
        if k in ("异", "空"):
            diff.append((w, h, truth, g, k))

    n = sum(v for k, v in stat.items() if k != "🔴 没回来")
    print("\n═══ 与真释义比（确定性比对，不用模型当判官）═══")
    for k in ("同", "含", "异", "空", "🔴 没回来"):
        if stat[k]:
            print("   %-8s %4d  (%.1f%%)" % (k, stat[k], 100.0 * stat[k] / max(n, 1)))
    print("   ── 「异」＋「空」＝ **不可用率 %.1f%%**"
          % (100.0 * (stat["异"] + stat["空"]) / max(n, 1)))
    print("      ⚠️ 「同/含」只说明**字面对得上**，不等于释义写得好；"
          "「异」里也混着「换个说法说对了」。这一步买的是**量级**，不是精确率。")

    print("\n■ 分歧样本（逐条人读 —— 这才是真正的判据）")
    for w, h, truth, g, k in diff[:25]:
        print("   [%s] %-10s 汉字=%-8s 真=%-22s 生成=%s"
              % (k, w, h, (truth or "")[:22], (g or "")[:30]))

    if ntok:
        per = ntok / max(n, 1)
        print("\n═══ 单价与报价 ═══")
        print("   本轮 token %s ／ %d 条 ⇒ **每条 %.1f token**"
              % (format(ntok, ","), n, per))
        print("   目标池 %s 条 ⇒ 约 %s token" % (format(target, ","),
                                                format(int(per * target), ",")))
        print("   ⚠️ 折算按**条数**，不按比例 —— 抽样是按哈希抽的，长度分布与全量一致，"
              "但这一点要实测不要假设")
        tp = path.with_suffix(".tokens.json")
        tp.write_text(json.dumps({"tok": ntok, "n": n, "target": target},
                                 ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
