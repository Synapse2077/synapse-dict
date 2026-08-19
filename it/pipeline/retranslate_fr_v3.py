#!/usr/bin/env python3
"""法语侧模型翻的 20,987 条：用按含义写的 prompt 重做。2026-08-16。

═══ 为什么重做 ═══
用户 2026-08-16 指出：「法语的翻译和英语的翻译和意语本身的义项翻译，都是义项翻译，
如果模型能力稳定，正确率应该差不多对吧？」—— **他是对的**。

我一直说「43.3% 二手法语是弱点」，但按同样逻辑英文那 53% 也是二手（英文版的意语词条
同样是英语编者写的对应词，不是意大利人写的原文）。真正的分界是
**第一手 it→zh 只有 22,231 条，其余全是二手**，法语并不特别差。

我单挑法语出来说，没有测量支持。可测的差别只有一个，而且是**我的锅**：

    来源                        带括号   总长中位
    flash:from-it（新 prompt）  72.1%      13
    flash:via-fr（旧 prompt）    0.9%       4
    flash:via-fr-v2（旧+词性）   0.3%       4

同一个模型、同一件事，只因为换了 prompt，带区分信息的比例差 **80 倍**。
旧版那句「输出对应词，不是长句翻译」是形式代理（`A45`），把括号里的区分点一起删了。

═══ A/B 实测（同 40 条输入，两版各跑一次，逐条人读）═══
    新版明显更好 18 · 打平 7 · 🔴旧版更好 1 · 两版都错 1 · 完全相同 13

  · 最硬的证据：**旧版给出 5 条空白（12.5%），新版 0 条** —— 旧 prompt 让模型
    在专名上直接放弃（`Lamhadi` / `Filippovskij` / `Les Fosses` 都是空）。
  · 区分点回来了，且正是设计要的：`Les Fosses` 同词已有「莱福塞（尚巴夫的村庄）」，
    新版写「莱福塞（法国德塞夫勒省市镇）」。
  · 🔴 代价：偶尔为了凑区分信息把词本身改偏 ——
    `musica cosmica`（Musique planante 氛围/太空音乐）被写成「太空摇滚」，那是另一个流派。
  · ⚠️ 换 prompt 救不了的：`airone fischiatore`（Héron flûte-du-soleil＝日鳽）两版都错，
    因为**法语源头用的是法语自己的俗名** —— 这是二手的固有损耗。

═══ 范围 ═══
只重做**模型翻的** 20,987 条（`deepseek%:via-fr%`）。
`template:via-fr` 那 139,815 条是确定性模板产出，不动。
连带解决记账里的 **1,534 条地名裸音译**（`Aisne (rivière française)` 与
`Aisne (rivière belge)` 都译成「埃纳河」），它们全在这批里。

🔴 只用 DeepSeek flash（豆包已在 `ark_batch` 硬拦截）。

用法（在 it/ 目录下）：
    python3 pipeline/retranslate_fr_v3.py --plan
    python3 pipeline/retranslate_fr_v3.py --run
    python3 pipeline/retranslate_fr_v3.py --diff    # 新旧分歧率 + 抽样
    python3 pipeline/retranslate_fr_v3.py --apply
    python3 pipeline/retranslate_fr_v3.py --verify
"""
import argparse
import asyncio
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool     # noqa: E402
import ds_batch   # noqa: E402
import paths      # noqa: E402
from align_it_defs import batched   # noqa: E402

OUT = paths.WORK / "fr_zh_v3.jsonl"
NEW_SRC = "deepseek-v4-flash:via-fr-v3"
CHUNK = 10

SYS = """你是意大利语—中文词典编纂员。每条给你：
`w` 意大利语词形、`pos` 词性、`fr` 它在**法语**维基词典里的释义（参考）、
`other` 该词条已有的其它中文义项（可能为空）。

写出这条义项**指的那个东西**在中文里的说法 —— 读者拿它去替换句子里的这个词，
意思应当成立。不要写"关于这个词"的话（"用于构成…""参见…""该词表示…"）。

🔴 以你对**意大利语**的了解为准。`fr` 只是参考：法语编者有时换成法语自己的说法、
   有时丢掉语体色彩、有时比原词更窄或更宽。不一致时**以意语为准**。
🔴 `pos` 必须用上：同一个拼写在不同词性下意思不同。
🔴 你写的这条会**和 `other` 里的义项并排显示给用户**。它必须让读者一眼看出
   跟那些不是同一个意思。**区分点是什么就写什么**，写在括号里，括号内**不限长度**：
       Aisne  已有「埃纳河（法国河流）」 → 这条写「埃纳河（比利时河流）」
       Saint-Léger (Charente).         → 「圣莱热（法国夏朗德省市镇）」
   若不写括号就会跟已有的某条**字面相同**，那括号是必须的。
🔴 括号是用来**补限定信息**的，不是用来改词本身。
   `Musique planante` 是氛围/太空音乐，写成「太空摇滚」就把流派改错了 ——
   拿不准词本身时，宁可只给稳的那个说法、括号里说明限定。
· 括号外只放对应词本身。意思确实有几个不同说法时用中文逗号并列，
  **只列真正不同的**；同义重复的不要。
· 句末不加任何标点。
· 学名、`:*` 之类的抓取残渣不要带进中文。
· 带语体色彩的（粗俗、俚语、文语、古语）要在中文里体现出来。
· 你确实读不懂这条法语释义时，`zh` 给空字符串 ""，**不要猜**。

输入是一个 JSON 对象，键是编号。输出**只有**一个 JSON 对象，键与输入相同，
值形如 {"zh": "中文"}。不要围栏、不要解释、不要输出数组。"""


def load(con):
    sib = defaultdict(list)
    for wid, t in con.execute(
            "SELECT s.word_id, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
            "WHERE g.lang='zh' AND g.seq=0 AND COALESCE(s.hidden,0)=0"):
        sib[wid].append(t)
    rows = []
    for sid, wid, w, pos, fr, zh in con.execute(
            "SELECT s.id, s.word_id, d.word, COALESCE(s.pos, e.pos), x.text, g.text "
            "FROM sense_src x JOIN sense s ON s.id=x.sense_id JOIN dict d ON d.id=s.word_id "
            "LEFT JOIN entry e ON e.id=s.entry_id "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' AND g.seq=0 "
            "WHERE x.src='fr-edition' AND g.src LIKE 'deepseek%:via-fr%' "
            "AND COALESCE(s.hidden,0)=0"):
        rows.append(dict(sid=sid, w=w, pos=pos or "?", fr=fr, cur=zh,
                         other="；".join(t for t in sib[wid] if t != zh)[:90]))
    return rows


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("🔴 来源标明仍是经法语中转（二手记在明处）",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND src NOT LIKE '%via-fr%'",
           NEW_SRC), 0),
        ("🔴 只改中文行", q("SELECT count(*) FROM sense_gloss WHERE src=? AND lang<>'zh'",
                        NEW_SRC), 0),
        ("🔴 中文不许为空", q("SELECT count(*) FROM sense_gloss WHERE src=? AND trim(text)=''",
                        NEW_SRC), 0),
        ("句末不许有标点",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND "
           "(text LIKE '%。' OR text LIKE '%.' OR text LIKE '%；')", NEW_SRC), 0),
        # ⚠️ 判据收窄两处，都是第一版写过头（报红 5 条，全是假红）：
        #    ① 「有意为之」是正常成语，被 `LIKE '%意为%'` 的子串撞上（`fare apposta`）
        #    ② 括号里解释**源头名字**的含义是词源信息，不是在讲我们这个词
        #       （`Pobeda`「波别达（俄语地名，意为"胜利"）」）
        #    ⇒ 元话语只在**括号外**算，且排除「有意为之」。
        ("不许含元话语（括号外）",
         sum(1 for (t,) in con.execute(
             "SELECT text FROM sense_gloss WHERE src=?", (NEW_SRC,))
             if any(k in re.split(r"[（(]", t)[0].replace("有意为之", "")
                    for k in ("意为", "指的是", "该词", "本词"))), 0),
        ("🔴 一条 sense 只有一条中文",
         q("SELECT count(*) FROM (SELECT sense_id FROM sense_gloss WHERE lang='zh' "
           "GROUP BY sense_id HAVING count(*)>1)"), 0),
        ("🔴 法语原文仍只在证据层（三语规矩）",
         q("SELECT count(*) FROM sense_gloss WHERE lang='fr'"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-44s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("plan", "run", "diff", "apply", "verify"):
        ap.add_argument("--" + f, action="store_true")
    ap.add_argument("--conc", type=int, default=24)
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = load(ro)

    if a.plan:
        print("■ 待重做 %s 条" % f"{len(rows):,}")
        print("   词性分布 %s" % Counter(r["pos"] for r in rows).most_common(6))
        print("   现有中文为空的 %s" % f"{sum(1 for r in rows if not r['cur']):,}")
        return 0

    if a.run:
        items = [({k: r[k] for k in ("w", "pos", "fr", "other")}, r["sid"]) for r in rows]
        ro.close()
        asyncio.run(ds_batch.run(SYS, *batched(items, CHUNK), OUT,
                                 mode="flash", conc=a.conc, every=25))
        return 0

    got = {}
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            got[r["id"]] = (r.get("zh") or "").strip()

    if a.diff:
        same = diff = empty = 0
        ex = []
        for r in rows:
            b = got.get(r["sid"])
            if b is None:
                continue
            if not b:
                empty += 1
            elif b == r["cur"]:
                same += 1
            else:
                diff += 1
                ex.append(r | {"new": b})
        n = same + diff + empty
        print("■ 新旧比对（%s 条）" % f"{n:,}")
        print("   完全相同 %7s (%.1f%%)" % (f"{same:,}", 100.0 * same / max(n, 1)))
        print("   不同     %7s (%.1f%%)" % (f"{diff:,}", 100.0 * diff / max(n, 1)))
        print("   新版空   %7s (%.1f%%)" % (f"{empty:,}", 100.0 * empty / max(n, 1)))
        random.seed(11)
        print("\n■ 抽 16 条")
        for r in random.sample(ex, min(16, len(ex))):
            print("   %-20s [%s] fr: %s" % (r["w"][:20], r["pos"], r["fr"][:50]))
            print("   %-20s 旧: %-26s 新: %s" % ("", r["cur"][:26], r["new"][:34]))
        return 0

    if a.apply:
        # 🔴 **不整批采用**。12,867 条分歧逐类读过，新版的错有固定形状：
        #    错全出在「括号外的词本身被改了」的时候（`falco cuculo` 红脚隼→燕隼、
        #    `areografico` 火星测绘→气溶胶），而价值全在「括号里加限定」。
        #    ⇒ 只采用能确定性判定为**信息只增不减**的三类，其余留旧值记账。
        P = re.compile(r"[（(]")
        head = lambda t: P.split(t)[0].strip(" ，,")
        upd, stat = [], Counter()
        for r in rows:
            b = got.get(r["sid"])
            if b is None:
                stat["模型没回答（留旧值）"] += 1
                continue
            if not b:
                stat["模型判读不懂（留旧值）"] += 1
                continue
            if b == r["cur"]:
                stat["与旧值相同（不写）"] += 1
                continue
            ho, hn = head(r["cur"]), head(b)
            po, pn = P.search(r["cur"]) is not None, P.search(b) is not None
            if ho == hn and not po and pn:
                stat["✅ 括号外不变、新增括号"] += 1
            elif ho == hn and po and pn:
                stat["✅ 括号外不变、括号更精确"] += 1
            elif ho != hn and ho and ho in b:
                stat["✅ 旧词完整保留在新文本里（重组）"] += 1
            elif ho == hn and po and not pn:
                stat["🔴 括号被删，丢信息（留旧值）"] += 1
                continue
            elif ho != hn and hn and hn in r["cur"]:
                stat["🔴 新版更短，丢同义说法（留旧值）"] += 1
                continue
            else:
                stat["🔴 两词各不相干，风险最高（留旧值）"] += 1
                continue
            upd.append((b, NEW_SRC, r["sid"]))
        for k, v in stat.most_common():
            print("   %-30s %7s" % (k, f"{v:,}"))
        ro.close()
        if not upd:
            return 0
        with dbtool.session("retranslate-fr-v3", expect={"#sense_gloss": 0}) as s:
            s.executemany("UPDATE sense_gloss SET text=?, src=? WHERE sense_id=? "
                          "AND lang='zh' AND seq=0", upd)
        print("\n■ 已改写 %s 条" % f"{len(upd):,}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
