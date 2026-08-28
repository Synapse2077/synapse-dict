#!/usr/bin/env python3
"""收尾单 A5（族 E 的「**错**」子类）—— 中文释义说的不是它自己的法语定义。先判后修。2026-08-28。

═══ 与「窄」子类的分界 ═══
`probes/judge_gloss_coverage.py` 量的是「**窄**」（法语说 A/B/C 三支、中文只剩一支，
外推约 8,355 条，收尾单 C12）。抽读 23 条时冒出另一类，**性质完全不同**：

    passif      FR 性交中的接受方           EN bottom        ZH **底部**
    vedette     FR 提供勤务的**小艇**        EN flagship      ZH **旗舰**（英文源头就错）
    presser     FR 互相挤在一起             EN to hurry up   ZH **赶快**（英文取了另一义项）
    trapézoïde  FR **腕**骨远排的一块小骨     EN trapezoid bone ZH **跗**三角骨

这不是"少一支"，是**整条错**。23 条里真窄 14 / 判官过宽 4 / **直接错 5**，
且 5 条全在高频段 —— 用户查得越多的词，伤害越大。

═══ 两条机制，都是 payload 缺上下文（和族 A 一模一样的形状）═══

**机制①：中文照英文对应词翻，法语定义没参与。**
英文对应词一旦偏/错，中文跟着错。风险面 = 三语俱全的义项。

**机制②：法语定义是一个词的交叉引用，模型无从判断指哪一支。**（第二轮外审逮到）

    allergiser  FR `Sensibiliser.`   ZH **使意识到，提高认识**
                 ↑ `sensibiliser` 的常见义是"提高认识"，医学义才是"致敏"。
                   而 `gloss_translate` 普通道的 payload 是 `("id","gloss","hint")`
                   —— **没有词头**，模型看不到这条定义是给 `allergiser` 用的。

⚠️ 机制②**不能靠改 `gloss_translate` 的落盘键解决**：那条道按法语原串去重
   （`Pénis.` 被 30 个俚语词共用，共用一个中文是**对的**，实测 9,653 种单词定义里
   2,373 种被多词头共用）。⇒ 修复走**逐义项**这条路（`land="id"`），不动去重设计。

═══ 🔴 报价之前先说清楚免费路径试过哪些（`[[prove-free-path-before-quoting]]`）═══

| 免费路径 | 结果 |
|---|---|
| 批内长度相关性（A6 那把尺子，全库 15,381 批上富集 39 倍） | ❌ **对释义无效**。释义窗口中位 r 只有 0.729（例句是 0.950），最低几窗读下来**全是对的**（`Langue bantoue parlée par…` → 「伊兰巴语」）——短串上长度相关本来就弱，是数据性质不是缺陷。**读了才知道，没读就会当成 12% 的富集去烧钱。** |
| 中文来自英文翻译道（`model:gloss-en`） | ❌ 只有 **227** 条，不是主要人口 |
| 长度代理（法语长中文短） | ❌ `[[criteria-from-meaning-not-form]]` 点名的形式代理，`homotopique`/「同伦的」完全正确 |
| **按 `freq_zipf` 做价值加权** | ✅ **可用**。不是缺陷的代理，是**伤害**的代理，而且是量出来的：抽读逮到的 5 条错译**全在高频段** |
| **按「法语定义只有一个词」切** | ✅ **可用**，机制②的结构面，14,756 条 |

⇒ 风险面 = 高频臂 ∪ 单词定义臂，而不是全部 646,748 条。

═══ 四段，每段可续跑 ═══
    ① --control      正控 8 条（已回源确认的错译）／负控（术语 + 模板生成的居民称谓）
    ② --judge        判风险面
    ③ --retranslate  只重翻判 wrong 的，**payload 带上词头与词性**（根因）
    ④ --verify + --apply   **只在「旧的判错、新的判对」时才替换**

用法（在 fr/ 目录下，**排低谷跑**）：
    python3 -u pipeline/fix_gloss_wrong.py --control
    python3 -u pipeline/fix_gloss_wrong.py --judge
    python3 -u pipeline/fix_gloss_wrong.py --read 20
    python3 -u pipeline/fix_gloss_wrong.py --retranslate --verify
    python3 -u pipeline/fix_gloss_wrong.py --apply
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                  # noqa: E402
import paths                                   # noqa: E402
from pipeline import slot_translate            # noqa: E402

f = lambda n: format(n, ",")
DIR = paths.WORK / "senses"
J1 = DIR / "wrong_judge.jsonl"
RT = DIR / "wrong_rt.jsonl"
J2 = DIR / "wrong_judge2.jsonl"
slot_translate.CHUNK = 30
slot_translate.CONC = 48

ONE_WORD = re.compile(r"^[\wÀ-ÿ’'\-]+\.?$")
ZIPF_HI = 3.0

SYS = """你在检查一部法汉词典里，**中文释义说的是不是它自己的法语定义说的那件事**。

输入是 JSON 数组，每项：
- `id`：标识号，**不是序号**，原样回传。
- `w`：词条；`pos`：这条义项的词性。
- `fr`：这条义项的**法语定义**（权威源，一切以它为准）。
- `en`：英文对应词（可能没有）。**它只是参考，它本身就可能是错的。**
- `zh`：这条义项现有的**中文释义**。

给出三个取值之一：

- `ok`    ：中文说的就是法语定义说的那件事。
- `narrow`：方向对，但法语定义说的是几支意思，中文只说了其中一支。
- `wrong` ：**中文说的是另一件事** —— 读者按中文理解会理解成别的东西。
            包括：取错了义（`Se serrer les uns contre les autres.` 译成「赶快」）、
            指错了对象（`Bateau qui assure…` 译成「旗舰」）、
            词性/所指错位（`Celui qui…`＝人，却译成形容词；
            `Qualifie les médicaments qui…`＝形容词，却译成名词「发红药」）、
            单词交叉引用取错义支（`Sensibiliser.` 在 `allergiser` 下是「致敏」不是「提高认识」）。

判断纪律
1. **以 `fr` 为准，不以 `en` 为准。** `en` 与 `fr` 打架时，是 `en` 错。
2. **中文简练不等于错，也不等于窄。** 法语一整句、中文两三个字，只要那两三个字
   就是这个概念本身，就是 `ok`。
3. 法语定义本身是「X 的变体／复数／缩写」这类**指针**时，中文指向 X 就算 `ok`。
4. 括号里的领域限定、语体标注，不影响判断。
5. **`wrong` 只给"读者会被带到别处"的。** 拿不准就往轻里给（`narrow` 或 `ok`）——
   代价不对称：判成 `wrong` 会让一条本来够用的释义被重写。

输出 JSON 数组：[{"id": <标识号>, "v": "ok"|"narrow"|"wrong"}]
只输出 JSON，不要解释。"""

SYS_RT = """你在为一部法汉词典写**中文释义**。

输入是 JSON 数组，每项：
- `id`：标识号，**不是序号**，原样回传。
- `w`：词条；`pos`：词性。
- `fr`：这条义项的法语定义。

规则
1. **中文释义要说的是 `fr` 这条定义说的那件事**，写成中文词典里那种释义
   （几个词到一句话），不是把法语句子逐字翻过来。
2. **词性要对上 `pos`**：`fr` 以 `Qui…` / `Qualifie…` 开头的是形容词性描述，
   中文写成「…的」；`Celui qui…` / `Celle qui…` 指的是**人**，中文写成名词。
3. **`fr` 只有一个词时，那是交叉引用** —— 它指的是那个词在 `w` 这个词条上适用的
   那一支意思，按 `w` 选义（`allergiser` 的 `Sensibiliser.` 是「使致敏」不是「使意识到」）。
4. 专业术语用该领域的中文说法。看不出意思就把 `zh` 给空字符串，不要猜。
5. **只输出释义本身。** 不要输出法语原文、不要加解释、不要写「这句话的意思是」。
6. **句末不加句号。** 这是词典释义不是句子 —— 全库 30 万条中文释义都不带句末标点。
   （🔴 第一版漏了这条，816 条重写里 292 条带了句号，占 36%，而既有语料是 0.0%。
     `fixes/strip_zh_gloss_period.py` 清的存量就是它。）

输出 JSON 数组：[{"id": <标识号>, "zh": "<中文释义>"}]
只输出 JSON，不要解释。"""

# 正控：**已回源确认中文说的是另一件事**。判官应当全判 wrong。
#   43157 passif 底部／7074 vedette 旗舰／18377 presser 赶快（以上抽读 23 条时确认）
#   59901 pédestre 表现行走姿态的（法语是"站立全身像"）／29788 trapézoïde 跗→腕
#   344400 allergiser 使意识到（`Sensibiliser.` 取错义支）
#   156260 rubéfiant 发红药（法语 `Qualifie les médicaments…` 是形容词）
#   21765 conservateur 保守的（法语 `Celui qui…` 指人）
POS_CTRL = [43157, 7074, 18377, 59901, 29788, 344400, 156260, 21765]
# 负控：判官应当全判 ok。
#   前 7 条抄 `judge_gloss_coverage.POS`（单支概念术语，中文本就该简练）
#   ⚠️ 那份清单里 `72045 clayette` 已被移出 —— 判官当时判 narrow 是**对的**，
#      是我的正控错（`[[llm-as-evaluator-discipline]]`：我的真值也不是真值）。
NEG_CTRL = [69594, 87111, 91287, 28582, 78746, 73607, 79395]

ROW = """SELECT s.id, d.word, s.pos, d.freq_zipf,
    (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='fr' ORDER BY seq LIMIT 1) fr,
    (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' ORDER BY seq LIMIT 1) zh,
    (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='en' ORDER BY seq LIMIT 1) en
  FROM sense s JOIN dict d ON d.id=s.word_id
  WHERE s.hidden=0 AND %s"""


def pack(rows):
    out = []
    for sid, w, pos, z, fr, zh, en in rows:
        if not fr or not zh:
            continue
        out.append({"id": str(sid), "w": w, "pos": pos or "", "fr": " ".join(fr.split()),
                    "zh": zh, "en": en or "", "_z": z})
    return out


def risk(con):
    """风险面 = 高频臂 ∪ 单词定义臂。见文件头「免费路径试过哪些」。

    🔴 `freq_zipf` 用**库里那一列**（阶段 5 补做时落的 1,776,527 行），不现算 ——
       现算等于第二把尺子（`[[fix-regression-and-gate]]`）。该列 NULL 的是
       wordfreq 量不了的（多词/词缀），**不当 0**，只是进不了高频臂。
    """
    rows = pack(con.execute(ROW % "1=1").fetchall())
    hi = [r for r in rows if r["_z"] is not None and r["_z"] >= ZIPF_HI]
    one = [r for r in rows if ONE_WORD.match(r["fr"])]
    by = {r["id"]: r for r in hi}
    by.update({r["id"]: r for r in one})
    return rows, hi, one, list(by.values())


def ask(items, out, sys_p, fields, answer):
    slot_translate.translate(items, sys_p, out, fields=fields,
                             keep=("id", "w"), key_field="id", answer_field=answer,
                             land="id")
    return slot_translate.done_keys(out, "id")


def verdicts(items, out):
    got = slot_translate.done_keys(out, "id")
    c, by = Counter(), {"narrow": [], "wrong": []}
    for it in items:
        r = got.get(it["id"])
        if not r:
            c["未判"] += 1
            continue
        v = str(r.get("v", "")).strip().lower()
        c[v if v in ("ok", "narrow", "wrong") else "越权值:%r" % v] += 1
        if v in by:
            by[v].append(it)
    return c, by


def control(con):
    ids = lambda xs: "s.id IN (%s)" % ",".join(str(i) for i in xs)
    pos = pack(con.execute(ROW % ids(POS_CTRL)).fetchall())
    neg = pack(con.execute(ROW % ids(NEG_CTRL)).fetchall())
    ask(pos + neg, J1, SYS, ("id", "w", "pos", "fr", "en", "zh"), "v")
    got = slot_translate.done_keys(J1, "id")
    v = lambda it: str((got.get(it["id"]) or {}).get("v", "")).strip().lower()
    hit = sum(1 for it in pos if v(it) == "wrong")
    print("\n══ 正控（%d 条已回源确认「中文说的是另一件事」，应全判 wrong）══" % len(pos))
    for it in pos:
        print("   %s %-13s %-8s %-46s → %s"
              % ("✅" if v(it) == "wrong" else "🔴 判成 " + (v(it) or "?"),
                 it["w"], it["id"], it["fr"][:46], it["zh"][:22]))
    print("   ⇒ 召回 %d/%d" % (hit, len(pos)))
    bad = [it for it in neg if v(it) == "wrong"]
    print("\n══ 负控（%d 条单支概念术语，中文本就该简练，应全判 ok）══" % len(neg))
    for it in bad:
        print("   🔴 误判 %-14s FR %s\n              ZH %s" % (it["w"], it["fr"][:70], it["zh"][:40]))
    print("   ⇒ 误判 %d/%d = %.1f%%" % (len(bad), len(neg), 100.0 * len(bad) / max(len(neg), 1)))
    return hit, len(pos), len(bad), len(neg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--retranslate", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="只判前 n 条（试跑用）")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)

    if a.control:
        control(con)
        return 0

    allr, hi, one, pool = risk(con)
    print("■ 有法语定义且有中文的可见义项 %s" % f(len(allr)))
    print("   高频臂（freq_zipf ≥ %.1f）        %s" % (ZIPF_HI, f(len(hi))))
    print("   单词定义臂（交叉引用，机制②）      %s" % f(len(one)))
    print("   风险面（并集）                    %s" % f(len(pool)))

    if a.judge:
        todo = pool[:a.limit] if a.limit else pool
        ask(todo, J1, SYS, ("id", "w", "pos", "fr", "en", "zh"), "v")
    c, by = verdicts(pool, J1)
    n = sum(v for k, v in c.items() if k in ("ok", "narrow", "wrong"))
    if n:
        print("\n══ 判官结果 ══  %s" % dict(c))
        for k, label in (("wrong", "🔴 中文说的是另一件事（A5）"),
                         ("narrow", "🟡 窄（族 E 的另一子类，收尾单 C12）")):
            print("   %-34s %s / %s = %.2f%%" % (label, f(len(by[k])), f(n),
                                                 100.0 * len(by[k]) / n))
    con.close()

    if a.read:
        print("\n══ 抽读（判官不是真值，我要自己看）══")
        for it in by["wrong"][:a.read]:
            print("\n[%s] %s #%s  zipf %s"
                  % (it["w"], it["pos"], it["id"], "—" if it["_z"] is None else "%.2f" % it["_z"]))
            print("   FR %s" % it["fr"][:150])
            print("   EN %s" % it["en"][:90])
            print("   ZH %s" % it["zh"][:80])

    if a.retranslate and by["wrong"]:
        ask([{k: i[k] for k in ("id", "w", "pos", "fr")} for i in by["wrong"]],
            RT, SYS_RT, ("id", "w", "pos", "fr"), "zh")
    if a.verify:
        new = slot_translate.done_keys(RT, "id")
        cand = [dict(i, zh=new[i["id"]]["zh"]) for i in by["wrong"]
                if i["id"] in new and (new[i["id"]].get("zh") or "").strip()]
        if cand:
            ask(cand, J2, SYS, ("id", "w", "pos", "fr", "en", "zh"), "v")

    if a.apply:
        new = slot_translate.done_keys(RT, "id")
        v2 = slot_translate.done_keys(J2, "id")
        # 🔴 唯一的替换判据：**旧的判错、新的判对**。缺任何一半都不动。
        rep = [(new[i["id"]]["zh"], int(i["id"])) for i in by["wrong"]
               if i["id"] in new and (new[i["id"]].get("zh") or "").strip()
               and str(v2.get(i["id"], {}).get("v", "")).strip().lower() == "ok"]
        print("\n■ 旧错+新对 ⇒ 可替换 %s 条（新释义仍判不对的 %s 条不动）"
              % (f(len(rep)), f(len(by["wrong"]) - len(rep))))
        for zh, sid in rep[:8]:
            print("   %s → %s" % (sid, zh[:60]))
        if rep:
            # ⚠️ `sense_gloss` 没有 id 列，主键是 (sense_id, lang, kind, seq)
            with dbtool.session("keep-v3-a5-gloss-wrong", expect={}) as s:
                s.executemany(
                    "UPDATE sense_gloss SET text=?, src='model:gloss:a5fix' "
                    "WHERE sense_id=? AND lang='zh' AND seq=("
                    "  SELECT MIN(seq) FROM sense_gloss WHERE sense_id=? AND lang='zh')",
                    [(zh, sid, sid) for zh, sid in rep])
            print("✓ 替换 %s 条" % f(len(rep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
