#!/usr/bin/env python3
"""1.5c 落库前的质量复核。2026-09-08。零 API，只读盘上答案。

用户 2026-09-08「你来判断」⇒ 我判断：**先验再落库**。
`[[verification-gates-not-sampling]]`「别把义项和释义错配了，那才是真灾难」——
落库之后再发现，要重来一整轮。

═══ 机械检查全量做，不抽样 ═══
①-⑥ 覆盖 106 万条全部，判据按**含义**写：

  ① 空输出        规则 6「看不懂就留空」。过低＝在硬编，过高＝取样或 prompt 有问题
  ② 无汉字        译文里一个汉字都没有 ＝ 它没译（回了英文/乱码/纯符号）
  ③ 抄回原文      译文 == 英文释义 ＝ 整条没翻
  ④ 元话语        「该词」「无法翻译」「这个义项」＝ 它在跟我说话而不是在写释义
  ⑤ 长度失控      词典释义不该是一整句话。取分布，不拍阈值
  ⑥ 🔴🔴 **同词形下重复中文** —— **这是本项目重建 en 的原因本身**：
     老库 `crimp` 六条义项共用一坨中文。要是新库还这样，这 207 元就白花了。
     判据：同一个 word_id 下、不同 sense 拿到**逐字相同**的中文。

⚠️ 机械检查判不了「这句中文对不对」——那要人读，见 `--read`。
    cd en && python3 probes/review_defs.py
    cd en && python3 probes/review_defs.py --read 25    # 逐条读无锚那族
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import collections
import json
import random
import re
import sqlite3

import paths
import translate_defs as T

HAN = re.compile(r"[㐀-䶿一-鿿]")
META = re.compile(r"该词|这个词|此词|无法翻译|无法确定|抱歉|作为AI|原文|该义项|这个义项|翻译如下")


def main(read_n=0):
    ans = T.read_answers()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    free, paid = T.pool(con)
    sent = {i["id"]: i for i in paid}
    q = con.execute

    meta = {}
    ids = sorted(ans)
    for k in range(0, len(ids), 900):
        ck = ids[k:k + 900]
        qs = ",".join("?" * len(ck))
        for sid, wid, w, pos, rk, en in q(
                "SELECT s.id, s.word_id, d.word, s.pos, s.rank, g.text FROM sense s "
                "JOIN dict d ON d.id=s.word_id "
                "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' "
                "WHERE s.id IN (%s)" % qs, ck):
            meta[sid] = dict(wid=wid, word=w, pos=pos, rank=rk, en=en)

    n = len(ans)
    empty = [s for s, z in ans.items() if not z]
    nohan = [s for s, z in ans.items() if z and not HAN.search(z)]
    copy = [s for s, z in ans.items() if z and s in meta and z.strip() == meta[s]["en"].strip()]
    metay = [s for s, z in ans.items() if z and META.search(z)]
    alien = sorted(set(ans) - set(sent))

    print("═══ 1.5c 全量机械检查（%s 条，非抽样）═══" % format(n, ","))
    for name, bad, note in [
            ("① 空输出（规则 6）", empty, "过低＝硬编，过高＝取样/prompt 有问题"),
            ("② 译文无汉字", nohan, "🔴 它没译"),
            ("③ 抄回英文原文", copy, "🔴 整条没翻"),
            ("④ 元话语混入", metay, "🔴 在跟我说话，不是在写释义"),
            ("⑤ 答案 id 不在发出去的池子里", alien, "🔴🔴 模型编的 id ⇒ 会贴错义项")]:
        print("   %-28s %9s  %6.3f%%  %s"
              % (name, format(len(bad), ","), 100 * len(bad) / n, note))

    L = sorted(len(z) for z in ans.values() if z)
    print("\n   ⑤ 译文长度分布（字符）：中位 %d ／ p90 %d ／ p99 %d ／ 最长 %d"
          % (L[len(L) // 2], L[int(len(L) * .9)], L[int(len(L) * .99)], L[-1]))
    longs = sorted(((len(z), s) for s, z in ans.items() if z), reverse=True)[:5]
    for ln, s in longs:
        print("      %4d 字  %-14s %s" % (ln, meta.get(s, {}).get("word", "?")[:14], ans[s][:64]))

    # ⑥ 同词形下重复中文 —— 重建 en 的原因本身
    byword = collections.defaultdict(list)
    for s, z in ans.items():
        if z and s in meta:
            byword[meta[s]["wid"]].append((s, z))
    dup_words, dup_rows = 0, 0
    samples = []
    for wid, lst in byword.items():
        if len(lst) < 2:
            continue
        c = collections.Counter(z for _, z in lst)
        d = sum(v - 1 for v in c.values() if v > 1)
        if d:
            dup_words += 1
            dup_rows += d
            if len(samples) < 6:
                t, k = c.most_common(1)[0]
                if k > 1:
                    samples.append((meta[lst[0][0]]["word"], k, len(lst), t))
    print("\n═══ ⑥ 🔴🔴 同词形下重复中文 —— **重建 en 的原因本身** ═══")
    print("   老库 `crimp` 六条义项共用一坨中文；新库要是还这样，这 207 元就白花了。")
    print("   涉及词形 %s ／ 重复行 %s ／ 占全体 %.3f%%"
          % (format(dup_words, ","), format(dup_rows, ","), 100 * dup_rows / n))
    for w, k, tot, t in samples:
        print("      %-18s %d/%d 条义项拿到同一句：%s" % (w[:18], k, tot, t[:44]))

    if read_n:
        print("\n═══ 人眼读：**无锚那族**（历史上错误率最高的一批）═══")
        na = [s for s in ans if s in sent and not sent[s].get("ref") and ans[s]]
        random.seed(5)
        for s in random.sample(na, min(read_n, len(na))):
            m = meta[s]
            print("   ── %s (%s) 第 %d 义" % (m["word"], m["pos"], m["rank"]))
            print("      en: %s" % m["en"][:96])
            print("      zh: %s" % ans[s][:72])
    con.close()
    return 0


if __name__ == "__main__":
    a = _sys.argv
    _sys.exit(main(int(a[a.index("--read") + 1]) if "--read" in a else 0))
