#!/usr/bin/env python3
"""1.5c 切片的**质量分析** —— token 数只是副产品，这才是主要产出。2026-09-07。

用户 2026-09-07：「跑切片的话不着急，把控质量为主，跑全量的话再考虑时段。」

═══ 三个问题，每个都有独立判据 ═══

**① 锚该不该带**（A/B 同一批义项对照）
   · 两轮输出**不同**的比例 —— 全一样说明锚没起作用，全不同说明锚在主导
   · 🔴 **锚泄漏**：锚与该义项语义不吻合时，B 轮有没有把锚的内容抄进去
     判据：B 的输出与 `ref` 的**首个义项片段**高度重合、而 A 的输出与之无关
     （`turtle` 印刷机弯板 配 ref「海龟」就是天生的用例）
   · token 差：带锚多花多少入方向

**② 质量到底如何**（核心层用 ECDICT 人工中文当负控）
   五门里只有 en 有这个条件：核心那 5.9 万条中文是人工审校的（bad≈0.02%）。
   判据**不是**"和人工中文字面一样"（同义表述本来就该不同），
   而是**有没有实质冲突** —— 用词典编纂的三档：
     一致 / 互补（都对，角度不同）/ **冲突（至少一个错）**
   本脚本只做**机械可判的那部分**并把可疑的挑出来给人看，不冒充能判语义。

**③ 空输出与异常**
   规则 6 让模型"看不懂就输出空"。空的比例是**安全指标**：
   过低反而危险（说明它在硬编），过高说明 prompt 或取样有问题。

⚠️ 本脚本**只读、不写库**。
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import random
import re
import sqlite3

import paths

OUT = paths.WORK / "slice"
HAN = re.compile(r"[㐀-䶿一-鿿]")


def load(p):
    d = {}
    if not p.exists():
        return d
    for ln in p.open(encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if "id" in o:
            d[o["id"]] = o
    return d


def frags(ref):
    """把词条级锚拆成片段：`n. 海龟；龟，鳖 / v. 捕龟` → {海龟,龟,鳖,捕龟}"""
    if not ref:
        return set()
    s = re.sub(r"^[a-z]{1,5}\.\s*|\s*/\s*[a-z]{1,5}\.\s*", " ", ref)
    return {x.strip() for x in re.split(r"[；;，,、/\s]+", s) if len(x.strip()) >= 2 and HAN.search(x)}


def main():
    A, B = load(OUT / "slice_noanchor.jsonl"), load(OUT / "slice_anchor.jsonl")
    print("A 轮（不带锚）%s 条 ｜ B 轮（带锚）%s 条" % (format(len(A), ","), format(len(B), ",")))
    if not A:
        print("🔴 还没有 A 轮结果")
        return 1

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    meta = {}
    ids = list(A)
    for chunk in (ids[i:i + 900] for i in range(0, len(ids), 900)):
        qs = ",".join("?" * len(chunk))
        for sid, w, pos, en, lg, frq, tag in con.execute(
                "SELECT s.id, d.word, s.pos, g.text, lg.text, d.freq_rank, d.exam_tag "
                "FROM sense s JOIN dict d ON d.id=s.word_id "
                "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' "
                "LEFT JOIN legacy_gloss lg ON lg.word_id=s.word_id "
                "WHERE s.id IN (%s)" % qs, chunk):
            meta[sid] = dict(word=w, pos=pos, en=en, ref=lg, core=bool(frq or tag))
    con.close()

    # ── ③ 空输出
    empty_a = [i for i, o in A.items() if not (o.get("zh") or "").strip()]
    print("\n═══ ③ 空输出（规则 6：看不懂就留空）═══")
    print("   A 轮空 %s 条 %.2f%%   —— 过低危险（在硬编），过高说明取样/prompt 有问题"
          % (format(len(empty_a), ","), 100 * len(empty_a) / max(len(A), 1)))
    if empty_a:
        print("   样本：")
        for i in empty_a[:5]:
            m = meta.get(i, {})
            print("      %-16s %s" % (str(m.get("word"))[:16], str(m.get("en"))[:56]))

    # ── ① A/B 对照
    both = [i for i in B if i in A]
    print("\n═══ ① 带锚 vs 不带锚（同 %s 条义项）═══" % format(len(both), ","))
    if both:
        diff = [i for i in both if (A[i].get("zh") or "").strip() != (B[i].get("zh") or "").strip()]
        print("   两轮输出不同 %s 条 %.1f%%   —— 全同=锚没起作用；全不同=锚在主导"
              % (format(len(diff), ","), 100 * len(diff) / len(both)))
        # 🔴 锚泄漏：B 的输出片段落在 ref 里、而 A 的没有
        leak = []
        for i in both:
            f = frags(meta.get(i, {}).get("ref"))
            if not f:
                continue
            bz, az = (B[i].get("zh") or ""), (A[i].get("zh") or "")
            hit_b = sum(1 for x in f if x and x in bz)
            hit_a = sum(1 for x in f if x and x in az)
            if hit_b and not hit_a:
                leak.append((i, hit_b))
        print("   🔴 疑似锚泄漏（B 命中锚片段而 A 没有）%s 条 %.1f%%"
              % (format(len(leak), ","), 100 * len(leak) / max(len(both), 1)))
        print("      ⚠️ 这只是**嫌疑**：锚与义项本来就吻合时，B 用了锚的词是**对的**。")
        print("         下面逐条列出来供人眼裁决 —— 机器判不了这个。")
        random.seed(3)
        for i, n in random.sample(leak, min(10, len(leak))):
            m = meta[i]
            print("      ── %s (%s)  %s" % (m["word"], m["pos"], m["en"][:58]))
            print("         A 无锚: %s" % (A[i].get("zh") or "")[:44])
            print("         B 带锚: %s" % (B[i].get("zh") or "")[:44])
            print("         ref   : %s" % (m["ref"] or "").replace("\n", " / ")[:62])

    # ── ② 核心层负控
    core = [i for i in A if meta.get(i, {}).get("core") and meta[i].get("ref")]
    print("\n═══ ② 核心层负控（ECDICT 人工中文，bad≈0.02%%）═══")
    print("   可比对 %s 条" % format(len(core), ","))
    ov = [i for i in core if frags(meta[i]["ref"]) & {x for x in re.split(
        r"[；;，,、\s]+", A[i].get("zh") or "") if len(x) >= 2}]
    print("   A 轮译文与人工中文**有共同词条**的 %s 条 %.1f%%"
          % (format(len(ov), ","), 100 * len(ov) / max(len(core), 1)))
    print("   ⚠️ 无重合**不等于错**（同义表述、义项不同都会无重合）⇒ 下面挑无重合的给人看：")
    no = [i for i in core if i not in ov]
    random.seed(9)
    for i in random.sample(no, min(12, len(no))):
        m = meta[i]
        print("      %-16s %-4s en: %s" % (m["word"][:16], m["pos"], m["en"][:46]))
        print("                       zh: %-30s | 人工: %s"
              % ((A[i].get("zh") or "")[:30], (m["ref"] or "").replace("\n", " / ")[:40]))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
