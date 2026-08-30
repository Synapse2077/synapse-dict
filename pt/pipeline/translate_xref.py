#!/usr/bin/env python3
"""C34–C36：1.5b **判定给不出**的那 1,299 条义项，换一套 prompt 重来。2026-08-30。

═══ 为什么不能直接重跑 1.5b ═══
🔴 这 1,299 条**模型早就答过了，答的是空** —— 它老老实实执行了我在
   `translate_defs.py` 里写的两条规则：

     规则4  「…的复数」「参见…」这类元描述 → `zh` 给空字符串
     规则8  原文残缺或看不出意思 → `zh` 给空字符串，不要猜

   **同一套 prompt 重跑一定还是空**（`[[retry-must-converge-or-drop-loud]]`：
   失败模式不变时重试不会收敛）。要么改 prompt，要么这批就是拿不到。

═══ 而那两条规则**对这一批是误伤** ═══
`[[prompt-self-harm-two-patterns]]` ①「自己写的防编造规则误伤了真词」：

    Antárctida  `vide Antártida`        规则4 判它是元描述 ⇒ 空
                                        **但读者要的就是「南极洲」**
    daqueloutros `contração da preposição de com o pronome demonstrativo…`
                                        规则4 判它是元描述 ⇒ 空
                                        **但对一个缩合词，这句话就是它的释义**
    -aram       `indicador de terceira pessoa do plural do pretérito…`
                                        同上，后缀的释义本来就是语法描述

⇒ 本脚本**只处理这一批**，`translate_defs.py` 一个字不改（它对它的 6 万条是对的）。
   `[[criteria-from-meaning-not-form]]`：判据跟着任务走，不跟着代码复用。

═══ 两个子任务，payload 不同 ═══
**A 交叉引用（1,062 条）**：源头说「同某词 / 参见某词」。
    payload: id, word, pos, pt, ref（被引词）, cand（库里被引词的候选中文，可空）
    ⚠️ `cand` **不是"仅供参考"的上下文** —— 它就是答案的来源，规则里写明用途。
       （`[[context-you-give-leaks-into-output]]`：it 那轮把"参考"原文传进去，
         母地名直接漏进 1,583 条结果。这里传的东西有明确职责，不是背景资料。）
    ⭐ 免费路径已经把能确定性解决的 1,107 条做完了（`fixes/fill_xref_zh.py`），
       剩下的两类**只有模型能做**：①被引词有多个义项、词性也分不开（要挑）
       ②被引词根本不在我们库里（要模型自己知道那个词）。
    🔴 ② 那类**我无从核对**（`[[blind-gloss-inference-ceiling]]`：无源可查时错误率
       卡在 24–25%）⇒ 规则里明确「不确定就留空」，并单独统计这一类的留空率。

**B 语法描述 / 真定义（237 条）**：`contração de…` / `indicador de…` / `ramo teológico que…`
    payload: id, word, pos, pt
    规则：**语法描述对这个词就是释义**，照译；只有纯残渣（`:`、`babuge²`、
    只剩地区标签）才留空。

═══ 成本纪律 ═══
· DeepSeek，`think=False`（翻译不是推导型）；`announce_window()` 先报计费时段。
· 编号用 `sense.id`（数据库主键）—— `[[model-answer-files-key-by-id]]`。
· 答案文件与 1.5b **分开**（`xref_zh.jsonl`），prompt 不同的答案不许混进同一个池子。

用法（在 pt/ 目录下）：
    python3 -u pipeline/translate_xref.py --slice 120
    python3 -u pipeline/translate_xref.py
    python3 -u pipeline/translate_xref.py --read 20
    python3 -u pipeline/translate_xref.py --apply
"""
import argparse
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool            # noqa: E402
import paths             # noqa: E402
import slot_translate    # noqa: E402
from fill_xref_zh import referent, pure_pointer   # noqa: E402

SRC = "model:xref"
OUT = paths.WORK / "defs" / "xref_zh.jsonl"
has_han = dbtool.has_han

slot_translate.CHUNK = 40      # payload 比 1.5b 宽（多了 ref/cand），批小一点
slot_translate.CONC = 40

SYS = """你在补一部给中文读者的葡萄牙语词典里缺失的中文释义。

输入是 JSON 数组，每项有：
  `id`    标识号，**不是序号**，原样回传
  `word`  被解释的葡萄牙语词
  `pos`   词性（n 名词／v 动词／adj 形容词／name 专名／phr 短语／contr 缩合形式／suf 后缀…）
  `pt`    源头给这条义项写的葡萄牙语原文
  `ref`   （可能没有）源头说这个词等同于／参见的那个葡萄牙语词
  `cand`  （可能没有）我们库里 `ref` 那个词已有的中文释义，多条用 ‖ 分开

这一批的原文分两种，处理方式不同：

**一、原文是交叉引用**（`vide X`／`o mesmo que X`／`variante de X`／整条就是一个词）
  这时 `ref` 就是被引的那个词。
1. 🔴 输出**被引词的意思**，不要输出「参见X」「同X」「X的异体」这类话 ——
   查 `Antárctida` 的读者要的是「南极洲」，不是「参见 Antártida」。
2. 给了 `cand` 时：`cand` 是我们库里已有的释义，**从中挑最贴合 `word` 这个词性和用法的**，
   可以直接用其中一条，也可以合并两条。挑不出就自己给。
3. 没给 `cand` 时：按你对 `ref` 这个葡萄牙语词的了解给中文。
4. 🔴 **不确定 `ref` 是什么意思就把 `zh` 留空**。宁可空着也不要编 ——
   编出来的错误释义比空白更伤词典。

**二、原文是这个词的语法描述或定义**（`contração da preposição de com…`／
   `indicador de terceira pessoa do plural…`／`ramo teológico que estuda…`）
5. 🔴 对缩合形式（contr）、后缀（suf）、前缀（pref）这类词，**语法描述就是它的释义**，
   照实译成中文（`daqueloutros` → 「de 与阳性复数指示代词 aqueloutros 的缩合形式」）。
6. 普通定义直接译成简明中文。

两种都适用的规则：
7. 原文只是重复词头本身、只剩一个标点、只剩地区/词源标注（`nota: …`、
   `(Regionalismo: …)`）⇒ `zh` 留空。
8. 专名有通用中文译名就用通用译名，没有就保留原文，不要音译生造。
9. 不加句末标点，不写「指」「表示」这类引导语。
10. 输出中文。学名、化学式、度量单位、被引的葡语词形原样保留。

输出 JSON 数组：[{"id": <标识号>, "zh": "<中文释义>"}]
只输出 JSON，不要解释。"""

LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{3,}")
# 🔴 「输出还是纯指针」这条判据 **import `fill_xref_zh.pure_pointer`**，不在这里另写一份。
#    第一版我在这里写了个锚在串尾的 `EXTRA` 正则 ⇒ 把「真释义 + 指针尾巴」也圈了：
#        hamartiologia → 研究罪的…神学分支；更佳形式为 hamartologia…
#        dermatófagas  → 食皮动物的阴性复数
#    而共用那份问的是「整条**只**由拉丁词＋关系标签构成吗」，两者不是一件事。
#    （`[[fix-regression-and-gate]]`：闸与它守的逻辑用两个判据 —— 今天第二次。）
TAIL = re.compile(r"[。．.!！?？；;]$")


def pool(con):
    """→ [{id, word, pos, pt, ref?, cand?}]，只取**可见**、有葡语原文、没有中文的义项。"""
    zh = defaultdict(dict)
    for w, sid, spos, g in con.execute(
            "SELECT d.word, s.id, s.pos, g.text FROM sense s "
            "  JOIN dict d ON d.id=s.word_id "
            "  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' "
            " WHERE COALESCE(s.hidden,0)=0"):
        zh[w].setdefault(sid, (spos, []))[1].append(g)
    out = []
    for sid, w, p, t in con.execute(
            "SELECT s.id, d.word, COALESCE(s.pos,''), g.text FROM sense s "
            "  JOIN dict d ON d.id=s.word_id "
            "  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='pt' "
            " WHERE COALESCE(s.hidden,0)=0 "
            "   AND NOT EXISTS(SELECT 1 FROM sense_gloss z "
            "                   WHERE z.sense_id=s.id AND z.lang='zh') "
            " ORDER BY s.id"):
        it = {"id": str(sid), "word": w, "pos": p, "pt": t}
        r, _label = referent(t)
        if r and r != w:
            it["ref"] = r
            cand = [g for _sp, gs in zh.get(r, {}).values() for g in gs
                    if not pure_pointer(g)]
            if cand:
                it["cand"] = " ‖ ".join(dict.fromkeys(cand))[:400]
        out.append(it)
    return out


def controls(items, got, title):
    """🔴 每一个输出字段都要被量到 —— `[[control-must-cover-every-output-field]]`。
    这里只有 `zh` 一个输出字段，所以每条判据都打在 `zh` 上。"""
    c, ex = Counter(), {}
    seen = defaultdict(list)
    blank_by = Counter()
    ptr_by = Counter()
    tot_by = Counter()

    def hit(k, a, b):
        c[k] += 1
        ex.setdefault(k, (a, b))

    n = 0
    for it in items:
        rec = got.get(it["id"])
        if not rec:
            continue
        n += 1
        kind = ("A2 交叉引用·库里有候选" if it.get("cand") else
                ("A1 交叉引用·库里没有" if it.get("ref") else "B 语法描述/定义"))
        tot_by[kind] += 1
        z = (rec.get("zh") or "").strip()
        w, src = it["word"], it["pt"]
        # 🔴 **纯指针输出等于没答**（`agerato 的替代拼写` 对读者和空白一样）。
        #    ⇒ 与留空同类计入、**同样不落库**。
        #    ⚠️ 这不是在放宽阈值糊弄闸（`[[proxy-metric-gets-optimized]]`）——
        #      闸的目的是「不许把没用的中文写进库」，跳过它们正是达成那个目的；
        #      变的是**写进去的数据**，不是「什么算坏」的定义。数量单独打印，不藏。
        if not z or pure_pointer(z):
            blank_by[kind] += 1
            if z:
                ptr_by[kind] += 1
            continue
        if not has_han(z):
            hit("🔴 一个汉字都没有", w, z)
        if z.strip().lower() == w.strip().lower():
            hit("🔴 把词头原样抄回来了", w, z)
        if TAIL.search(z):
            hit("🔴 带句末标点（释义是短语不是句子）", w, z)
        if it.get("ref") and z.strip().lower() == it["ref"].strip().lower():
            hit("🔴 把被引词原样抄回来了", it["ref"], z)
        if len(LATIN.findall(z)) >= 3 and has_han(z):
            hit("残留葡语（≥3 个拉丁词）", w, z)
        seen[z].append(w)
    dup = sum(len(v) for v in seen.values() if len(v) > 3)
    n = max(n, 1)
    print("\n══ %s（%s 条）══" % (title, format(n, ",")))
    print("  ── 留空率（分桶看，A1 是我无从核对的那一类）──")
    for k in sorted(tot_by):
        t = tot_by[k]
        print("     %-24s %5d 条，给不出 %5d（%.1f%%）＝ 留空 %d ＋ 纯指针 %d"
              % (k, t, blank_by[k], 100.0 * blank_by[k] / max(t, 1),
                 blank_by[k] - ptr_by[k], ptr_by[k]))
    for k, v in c.most_common():
        print("  %-40s %6s  %5.2f%%" % (k, format(v, ","), 100.0 * v / n))
        a, b = ex[k]
        print("        %-40s → %s" % (str(a)[:40], str(b)[:40]))
    print("  %-40s %6s  %5.2f%%" % ("一条中文对 >3 个不同词（疑似泛化）",
                                    format(dup, ","), 100.0 * dup / n))
    hard = [k for k in c if k.startswith("🔴") and c[k] > 0.02 * n]
    print("  %s" % ("🔴 硬闸红了（>2%）：" + "；".join(hard) if hard
                    else "✅ 硬闸过（每条 🔴 都 ≤2%）"))
    return not hard


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int, default=0)
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = pool(con)
    got = slot_translate.done_keys(OUT, land="id")
    bucket = Counter("A2 有候选" if i.get("cand") else
                     ("A1 无候选" if i.get("ref") else "B 语法描述/定义") for i in items)
    print("■ 待补 %s 条 ｜ 已答 %s ｜ 还差 %s"
          % (format(len(items), ","), format(len(got), ","),
             format(sum(1 for i in items if i["id"] not in got), ",")))
    print("   分桶：%s" % dict(bucket))

    want = (random.Random(1).sample(items, min(a.slice, len(items)))
            if a.slice else items)
    if not a.apply:
        todo = [i for i in want if i["id"] not in got]
        if todo:
            slot_translate.translate(todo, SYS, OUT,
                                     fields=("id", "word", "pos", "pt", "ref", "cand"),
                                     keep=("id", "word", "pt"),
                                     key_field="id", land="id")
            got = slot_translate.done_keys(OUT, land="id")

    ok = controls(want, got, "控制判据（交叉引用 / 语法描述专用）")
    if a.read:
        xs = [i for i in random.Random(3).sample(want, min(a.read * 4, len(want)))
              if i["id"] in got][:a.read]
        print("\n══ 打样 %d 条 ══" % len(xs))
        for i in xs:
            print("   %-20s [%s] %s" % (i["word"][:20], i["pos"], i["pt"][:58]))
            if i.get("cand"):
                print("   %-20s 候选: %s" % ("", i["cand"][:58]))
            print("   %-20s    → %s\n" % ("", (got[i["id"]].get("zh") or "（留空）")[:56]))
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 硬闸未过，**不写库**")
        return 1
    rows = [(int(i["id"]), got[i["id"]]["zh"].strip())
            for i in items
            if i["id"] in got and (got[i["id"]].get("zh") or "").strip()
            and not pure_pointer(got[i["id"]]["zh"].strip())]
    print("\n■ 可落库 %s 行" % format(len(rows), ","))
    if not rows:
        return 0
    with dbtool.session("fill-pt-xref-model", expect={"#sense_gloss": len(rows)}) as s:
        s.executemany("INSERT OR IGNORE INTO sense_gloss "
                      "(sense_id,lang,kind,seq,text,src) VALUES (?,'zh','definition',0,?,?)",
                      [(i, z, SRC) for i, z in rows])
    print("✓ 写入完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
