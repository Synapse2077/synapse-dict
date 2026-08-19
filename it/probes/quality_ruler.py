#!/usr/bin/env python3
"""译文质量的尺子：分层抽样，我逐条读。2026-08-16。

═══ 为什么要有 ═══
全库 41 万条中文，**语义对不对，没有任何测量**。唯一两个数字差 7 倍：
LLM 判官在 92 条上报 bad 1.1%；我自己读 26 条数出约 8%，而且判官把那些全判成 ok
（`assolutivo` 通格被译成"作格"，正好反了）。

肉眼撞见过的错：`falco cuculo`（红脚隼→燕隼）、`areografico`（火星测绘→气溶胶）、
`imenectomia`（切除→切开）、`Orsa maggiore`（大熊座→"查理大车"）——
**全是抽样时看见的，没有任何自动检查抓得到**。

═══ 🔴 分层：改过一次，记下为什么 ═══
第一版按**原文锚**分四层（en+it / 只有en / 只有it / 无锚）。跑 30 条 pilot 之后废掉：
30 条里 9 条是 `Nom de famille.` → 「姓氏」的**模板产出**，读它们等于白读
（模板是逐字节映射表，对不对该用规则核，不该用眼睛抽）。

⇒ 改为按「**这行中文是谁写的**」分层。理由：
   · 模板产出可以 100% 确定性核验，根本不该进抽样池
   · 出了问题的**修法**是按批次重跑，而批次就是按 src 划的 —— 分层与行动对齐
   · 锚（en/it/fr 原文）降为**读的时候的旁证**，每条都打印，但不做分层维度

    T  纯模板         逐字节映射 + 指针文案 —— 不抽读，`--template-check` 全量核
    U  原始买入层     建库时就有的译文，**从没量过，占 48.3%，最大的未知**
    G  模型音译+模板  地名：音译交模型、框架交模板
    F  模型·经法语    法语版释义转中文（含 v2/v3/pro 几轮重做）
    I  模型·从意语    意语原文直译（align_it_multi，两天前刚做）
    E  模型·阶段3b    新收词形的意语原文直译（translate_it_defs）

═══ 评分标准（30 条 pilot 校准后写死）═══
    0  对
    1  可用但不精确：粒度粗、缺区分点、同义词选得不佳
       （典型：`Gombos`→「姓氏」两个字，没音译，等于没告诉读者任何东西）
    2a 源保真错：**源文本是对的**，中文没忠实翻过来
       （典型：`Orsa maggiore` 英文源 `Charles' Wain` 是大熊座的古名，
        我们音译成「查理大车」，中文里毫无意义）
    2b 事实错：**源文本本身就错**，中文忠实地跟着错（`imenectomia` 就是这种）

🔴 2a / 2b 必须分开：修法完全不同。2a 改译文，2b 要回外部权威源。
   我以前一直混着数，所以「错误率」这个词在我嘴里是没有定义的。

═══ 第一轮结果（2026-08-16，190 条我逐条读）═══
                        全层     抽样    0    1   2a   2b   错误率
    G 音译+模板框架      5,904     25   15    9    1    0    4.0%
    I 从意语原文        21,919     40   37    2    1    0    2.5%
    F 经法语           22,420     40   30    8    2    0    5.0%
    E 阶段3b新收词      13,897     35   29    3    3    0    8.6%
    U 原始买入层       197,995     50   44    6    0    0    0.0%
    ─────────────────────────────────────────────────────────
    加权错误率 **1.2%**，覆盖 262,135 条（64%）；T 层 147,716 条走确定性核验

🔴 三个反直觉的结论：
   ① **最大的未知 U 层（48.3%）是最干净的** —— 50 条一条 2 分都没有。
      它是建库时买进来的，我原以为"从没量过＝最可疑"，量了才知道反了。
   ② **风险与「花了多少钱」成正比，不与"有没有锚"成正比**：
      模型翻的四层错误率 2.5–8.6%，人买的那层 0%。
   ③ 抽样只逮到 2a（源保真错），**一条 2b 都没有** ——
      也就是说错在我们这边，不在源头，全部可修。

⚠️ 我自己就是这把尺子。为了不让它变成新的黑箱：
   · 每条都记下**理由**，不只记分数（评分写在 grades/ 下，一层一个文件）
   · 正式读完之后隔一段再盲读其中 30 条，看两次一致率

用法（在 it/ 目录下）：
    python3 probes/quality_ruler.py --strata           # 各层多大 + 与锚的交叉表
    python3 probes/quality_ruler.py --template-check   # T 层：确定性全量核，不抽样
    python3 probes/quality_ruler.py --sample 40 --stratum U
    python3 probes/quality_ruler.py --score            # 汇总我读完写下的评分
"""
import argparse
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths   # noqa: E402

GRADES = Path(__file__).resolve().parent / "grades"

# 层的定义：(键, 中文名, 判据函数 src→bool)。**顺序即匹配优先级**。
STRATA = [
    ("T", "纯模板（不抽读）",   lambda s: s.startswith("template") and "translit" not in s),
    ("G", "模型音译+模板框架", lambda s: "translit" in s),
    ("I", "模型·从意语原文",   lambda s: ":from-it" in s),
    ("F", "模型·经法语",       lambda s: ":via-fr" in s),
    ("E", "模型·阶段3b新收词", lambda s: s.startswith("deepseek")),
    ("U", "原始买入层",        lambda s: True),
]
KEYS = [k for k, _n, _f in STRATA]
NAMES = dict((k, n) for k, n, _f in STRATA)


def stratum(src):
    for k, _n, f in STRATA:
        if f(src or ""):
            return k
    return "U"


def load(con):
    """→ {层: [row]}，row = dict(sid, word, pos, zh, en, it, fr, src)"""
    g = defaultdict(dict)
    for sid, lang, t, src in con.execute(
            "SELECT sense_id, lang, text, src FROM sense_gloss WHERE seq=0"):
        g[sid][lang] = (t, src) if lang == "zh" else t
    ev = defaultdict(dict)
    for sid, src, t in con.execute(
            "SELECT sense_id, src, text FROM sense_src WHERE sense_id IS NOT NULL"):
        ev[sid].setdefault(src, t)
    out = defaultdict(list)
    for sid, w, pos in con.execute(
            "SELECT s.id, d.word, COALESCE(s.pos, e.pos) FROM sense s "
            "JOIN dict d ON d.id=s.word_id LEFT JOIN entry e ON e.id=s.entry_id "
            "WHERE COALESCE(s.hidden,0)=0"):
        row = g.get(sid) or {}
        zh, zsrc = row.get("zh", (None, None))
        if not zh:
            continue
        e = ev.get(sid, {})
        out[stratum(zsrc)].append(dict(
            sid=sid, word=w, pos=pos or "?", zh=zh, src=zsrc or "(NULL)",
            en=row.get("en"), it=row.get("it"),
            fr=e.get("fr-edition"), ev=next(iter(e.values()), None)))
    return out


def anchor(r):
    """读的时候能对着什么原文判 —— 只作旁证打印，不当分层维度。"""
    return ("en+it" if r["en"] and r["it"] else "只有en" if r["en"]
            else "只有it" if r["it"] else "只有fr" if r["fr"] else "无锚")


def cmd_strata(data):
    tot = sum(len(v) for v in data.values())
    print("■ 全库可见义项（有中文）%s 条，按「这行中文是谁写的」分层\n" % f"{tot:,}")
    cols = ["en+it", "只有en", "只有it", "只有fr", "无锚"]
    print("   %-3s %-16s %9s %7s   %s" % ("", "", "条数", "占比",
                                          "".join("%9s" % c for c in cols)))
    for k in KEYS:
        rows = data[k]
        if not rows:
            continue
        c = Counter(anchor(r) for r in rows)
        print("   %-3s %-16s %9s %6.1f%%   %s" % (
            k, NAMES[k], f"{len(rows):,}", 100.0 * len(rows) / tot,
            "".join("%9s" % (f"{c.get(x, 0):,}" if c.get(x) else "·") for x in cols)))
    readable = tot - len(data["T"])
    print("\n   T 层 %s 条走 --template-check 确定性核验，不进抽样池" % f"{len(data['T']):,}")
    print("   ⇒ 需要抽读的面 %s 条（%.1f%%）" % (f"{readable:,}", 100.0 * readable / tot))
    print("   🔴 U 层 %s 条是最大的未知：建库时就在库里，一次都没量过"
          % f"{len(data['U']):,}")


# ═══ T 层：确定性核验，不抽样 ═══════════════════════════════════════════
TPL_VIA_FR = {
    "Nom de famille.": "姓氏",
    "Nom de famille italien.": "意大利语姓氏",
    "Prénom masculin.": "男性名字",
    "Prénom féminin.": "女性名字",
}
# 🔴 指针文案的模板表**直接从产它的脚本引**，不在这里重抄一份 ——
#    重抄就变成"我照着自己的记忆核对自己"，第一版就是这么写的，误报 2,146 条。
#    第二版仍只抄了 `ZH` 一张表，漏掉 `FALLBACK`（"%s 的变体形式"）和"多目标用、连接"，
#    又误报 44 条。⇒ **直接调产它的那个函数**，任何一处改了这里自动跟上。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))
from recover_alt_of import zh_label   # noqa: E402


def cmd_template_check(con, data):
    """T 层不抽样：模板输出必须能从源头逐字节重建。"""
    print("═══ T 层确定性核验（%s 条，非抽样）═══" % f"{len(data['T']):,}")
    bad_map, bad_ptr, unknown = [], [], Counter()
    rel = defaultdict(list)
    # 🔴 `sense_relation.target` 存的是**目标词形原样文本**，不是外键（见建表注释）。
    #    按 id 取，因为多目标是按插入顺序用「、」连起来的，顺序是判据的一部分。
    for sid, tw in con.execute(
            "SELECT sense_id, target FROM sense_relation "
            "WHERE sense_id IS NOT NULL ORDER BY id"):
        rel[sid].append(tw)
    for r in data["T"]:
        if r["src"].endswith(":via-fr"):
            want = TPL_VIA_FR.get(r["fr"] or "")
            if want is None:
                unknown["fr 原文不在模板表里"] += 1
                bad_map.append((r["word"], r["fr"], r["zh"]))
            elif want != r["zh"]:
                bad_map.append((r["word"], r["fr"], r["zh"]))
        elif r["src"].startswith("template:it-ptr"):
            # 意语版的指针文案（`fixes/fill_empty_zh.py` 建的 219 条）走的是另一套模板：
            # 目标词在**意语释义**里，不在 `sense_relation` 里 —— 那张表只记英文版的关系。
            # ⇒ 判据换成「中文里必须点名意语释义里的那个目标词」。
            # ⚠️ `.*?` 非贪婪会停在**第一个** `da`：
            #    `variante da evitare di Cechia` → 目标抠成「evitare di Cechia」。
            #    模板取的是最后一个 `di` 后面那截 ⇒ 这里也必须贪婪。
            m = re.match(r"^(?:plurale|singolare|femminile|maschile|grafia|forma|variante)"
                         r".*\bd[ia]\s+(.+?)\.?$", (r["it"] or "").strip(), re.I)
            tgt = m.group(1).strip().rstrip(".;") if m else (r["it"] or "").strip().rstrip(".;")
            if tgt and tgt not in r["zh"]:
                bad_ptr.append((r["word"], r["zh"], "中文没点名意语目标 " + tgt[:24]))
        else:
            # 逐字节重建：拿英文原文 + sense_relation 的目标，调产它的那个函数重算一遍
            tw = rel.get(r["sid"], [])
            if not tw:
                bad_ptr.append((r["word"], r["zh"], "sense_relation 里没有目标词"))
            # `+tpl:surname` 那步会在末尾确定性地追加「（姓氏）」，重建时要带上
            elif (zh_label(r["en"], tw)[0]
                  + ("（姓氏）" if r["src"].endswith("+tpl:surname") else "")) != r["zh"]:
                bad_ptr.append((r["word"], r["zh"], "重建成 " + zh_label(r["en"], tw)[0]))
    # 🔴 第一版只有上面两条，**全绿** —— 但它们核的是「模板套得对不对」，
    #    不是「套进去的东西对不对」。补这条之后逮到 88 条英文说明直接渲染进了中文。
    #    （`measure-landing-not-source`：别量自己的转换器，要量数据。）
    from trim_pointer_notes import is_note   # noqa: E402
    bad_tgt = [(r["word"], t, "目标位是英文说明") for r in data["T"]
               for t in rel.get(r["sid"], ()) if is_note(t)]
    checks = [
        ("🔴 模板行必须能从法语原文逐字节重建", len(bad_map), 0),
        ("🔴 指针文案必须与 sense_relation 一致", len(bad_ptr), 0),
        ("🔴 指针的目标位必须是词形，不是英文说明", len(bad_tgt), 0),
    ]
    bad_ptr = bad_ptr + bad_tgt
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-42s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    for w, a, b in (bad_map + bad_ptr)[:8]:
        print("     ⚠️ %-22s %-30s %s" % (w[:22], str(a)[:30], str(b)[:30]))
    if unknown:
        for k, v in unknown.items():
            print("     · %s：%d" % (k, v))
    return ok


# ═══ 抽样 ═══════════════════════════════════════════════════════════════
def cmd_sample(data, key, n, seed):
    rows = data[key]
    random.seed(seed + ord(key))
    picked = random.sample(rows, min(n, len(rows)))
    picked.sort(key=lambda r: r["word"].lower())
    print("═" * 78)
    print("■ 层 %s %s —— 全层 %s 条，抽 %d 条" % (key, NAMES[key], f"{len(rows):,}", len(picked)))
    print("  评分：0 对 / 1 可用但不精确 / 2a 源保真错 / 2b 源本身就错")
    for i, r in enumerate(picked, 1):
        print("\n%2d. %-24s [%s]  #%d  锚=%s" % (i, r["word"][:24], r["pos"], r["sid"], anchor(r)))
        print("    中文  %s" % r["zh"])
        for tag in ("en", "it", "fr"):
            if r[tag]:
                print("    %-4s  %s" % (tag.upper(), r[tag][:150]))
        if not (r["en"] or r["it"] or r["fr"]) and r["ev"]:
            print("    证据  %s" % r["ev"][:150])
    ids = [r["sid"] for r in picked]
    GRADES.mkdir(exist_ok=True)
    p = GRADES / ("sample_%s.json" % key)
    p.write_text(json.dumps({"stratum": key, "n_total": len(rows), "seed": seed,
                             "ids": ids}, ensure_ascii=False, indent=1))
    print("\n  （抽样清单已存 %s，评分写进同目录 grade_%s.json）" % (p.name, key))


def cmd_score(data):
    """汇总我读完写下的评分，按层大小加权得全库数。"""
    tot = sum(len(v) for v in data.values())
    print("═══ 译文质量（分层抽样，我逐条读）═══\n")
    print("   %-3s %-16s %9s %6s   %5s %5s %5s %5s   %s" %
          ("", "", "全层", "抽样", "0", "1", "2a", "2b", "错误率(2a+2b)"))
    wsum = wn = 0.0
    for k in KEYS:
        p = GRADES / ("grade_%s.json" % k)
        if not p.exists():
            continue
        g = json.loads(p.read_text())["grades"]
        c = Counter(v["g"] for v in g.values())
        n = len(g)
        err = (c["2a"] + c["2b"]) / n
        size = len(data[k])
        wsum += err * size
        wn += size
        print("   %-3s %-16s %9s %6d   %5d %5d %5d %5d   %.1f%%" % (
            k, NAMES[k], f"{size:,}", n, c["0"], c["1"], c["2a"], c["2b"], 100 * err))
    if wn:
        print("\n   加权（按层大小）错误率 %.1f%%，覆盖 %s 条（%.0f%%）" %
              (100 * wsum / wn, f"{int(wn):,}", 100.0 * wn / tot))
        print("   ⚠️ T 层不在其中：它走确定性核验，不是抽样")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strata", action="store_true")
    ap.add_argument("--template-check", action="store_true")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--stratum", default="")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--seed", type=int, default=20260816)
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    data = load(con)
    if a.template_check:
        return 0 if cmd_template_check(con, data) else 1
    if a.score:
        cmd_score(data)
        return 0
    if a.sample:
        if a.stratum not in KEYS:
            print("🔴 --stratum 要给 %s 之一" % "/".join(KEYS))
            return 2
        cmd_sample(data, a.stratum, a.sample, a.seed)
        return 0
    cmd_strata(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
