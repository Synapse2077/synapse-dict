#!/usr/bin/env python3
"""用手写模式 + 已翻槽值，**确定性生成**地名族的中文释义。2026-08-22。

═══ 链条 ═══
    geo_patterns.py      法语句式 → 中文句式 + 槽位（我手写，32 条）
    geo_translate_slots  槽值 → 中文（flash 翻一次，2,577 个，全库复用）
    本步                  组装 → 写 sense_gloss(lang='zh', src='template:geo')

**84,632 条法语地名释义里生成 77,116 条（91.1%）—— 由 32 条句式 + 2,577 个译名
组装而成，30 倍压缩。剩下 7,516 条按下面的放弃规则退回模型。**

═══ ⭐ 为什么模板比送模型更好（不只是更便宜）═══
① 同一句式永远渲染成同一句 —— 没有模型的表述漂移
② 同一地名永远同一个中文 —— 模型跑三次能给出三个音译
③ 🔴 **区分性信息被保留下来**。`[[criteria-from-meaning-not-form]]` 那次事故里，
   prompt 写「不是长句翻译」，模型把 `Saint-Léger (Charente).` 压成「圣莱热」，
   **十个同名市镇的中文一模一样**，坏掉 1,528 条。模板天然不会犯这个错。

═══ 四条放弃规则（宁可缺不可错）═══
任一不满足 ⇒ **整条不生成**，退回模型走正常翻译：
  ① 句子匹配不上任何模式
  ② 某个槽值吞了从句（`geo_patterns.dirty`）
  ③ 某个槽值没有中文（不在译名表里，或模型主动留空）
  ④ 通名不在 `TYPE_ZH` 闭集里

用法（在 fr/ 目录下）：
    python3 pipeline/geo_render.py            # 干跑，只报数并抽样打印
    python3 pipeline/geo_render.py --audit    # **按模式分组审查**（写库前必看，理由见 --audit 帮助）
    python3 pipeline/geo_render.py --apply    # 落库（过 dbtool 写库闸）
"""
import argparse
import json
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool                                                    # noqa: E402
import paths                                                     # noqa: E402
from pipeline.geo_patterns import match, dirty, type_zh, render  # noqa: E402

WORK = paths.WORK / "geo"
SLOT_ZH = WORK / "slot_zh.jsonl"
SRC = "template:geo"

FAM = re.compile(r"^(Commune|Ville|Village|Municipalité|Hameau|Localité|Bourg|Quartier)\b", re.I)


def slot_table():
    """法语槽值 → 中文。**留空的不收**（模型说了拿不准），脏的也不收。"""
    t = {}
    for ln in SLOT_ZH.open(encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("zh") and not dirty(o["fr"]):
            t[o["fr"]] = o["zh"]
    return t


def build(con, zh_of):
    """→ (要写的 [(sense_id, 中文)], 放弃原因计数)"""
    rows = con.execute("""
        SELECT s.id, g.text FROM sense s
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
        WHERE z.sense_id IS NULL""").fetchall()
    out, why = [], Counter()
    for sid, raw in rows:
        t = " ".join(raw.split())
        if not FAM.match(t):
            why["非地名族"] += 1
            continue
        m = match(t)
        if not m:
            why["①无模式匹配"] += 1
            continue
        tpl, slots = m
        filled, drop = [], None
        for kind, val in slots:
            v = val.strip()
            if kind == "TYPE":
                z = type_zh(v)
                if not z:
                    drop = "④通名不在闭集"
                    break
            elif dirty(v):
                drop = "②槽值吞了从句"
                break
            else:
                z = zh_of.get(v)
                if not z:
                    drop = "③槽值无中文"
                    break
            filled.append(z)
        if drop:
            why[drop] += 1
            continue
        out.append((sid, render(tpl, filled), tpl, t))
    return out, why


def check(out):
    """写之前的不变量。任一红了就别写。"""
    bad = Counter()
    for _, z, _tpl, _fr in out:
        if "{" in z or "}" in z:
            bad["未填的占位符"] += 1
        if re.search(r"[A-Za-zÀ-ÿ]", z):
            bad["残留拉丁字母"] += 1
        if not z.strip():
            bad["空串"] += 1
    ids = [s for s, _, _t, _f in out]
    if len(set(ids)) != len(ids):
        bad["sense_id 重复"] = len(ids) - len(set(ids))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=25)
    ap.add_argument("--audit", action="store_true",
                    help="按模式分组，每条模式报量并打样本 —— 一条模式错就是上万条一起错，"
                         "随机抽样看不出来（32,879 条都出自同一条模式，抽到的全长一个样）")
    a = ap.parse_args()

    zh_of = slot_table()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    out, why = build(con, zh_of)
    total = sum(why.values()) + len(out)

    print("■ 待翻译 %s 条 ⇒ 模板可生成 %s 条" % (f"{total:,}", f"{len(out):,}"))
    fam = total - why["非地名族"]
    print("   地名族 %s 条，其中生成 %s（%.1f%%）"
          % (f"{fam:,}", f"{len(out):,}", 100.0 * len(out) / fam))
    print("\n── 放弃原因 ──")
    for k, v in sorted(why.items(), key=lambda x: -x[1]):
        if k != "非地名族":
            print("   %-16s %s 条" % (k, f"{v:,}"))

    bad = check(out)
    if bad:
        print("\n🔴 不变量红了，**不写**：%s" % dict(bad))
        return 1
    print("\n✓ 不变量全绿（无未填占位符 / 无残留拉丁字母 / 无空串 / sense_id 不重复）")

    if a.audit:
        from collections import defaultdict
        g = defaultdict(list)
        for _sid, z, tpl, fr in out:
            g[tpl].append((fr, z))
        print("\n── 按模式分组（共 %d 条模式）──" % len(g))
        for tpl, rs in sorted(g.items(), key=lambda x: -len(x[1])):
            print("\n【%s 条】%s" % (f"{len(rs):,}", tpl))
            for fr, z in rs[:2]:
                print("      %-74s → %s" % (fr[:74], z))
        return 0

    print("\n── 随机 %d 条 ──" % a.sample)
    idx = {sid: z for sid, z, _t, _f in out}
    q = con.execute(
        "SELECT s.id, d.word, g.text FROM sense s JOIN dict d ON d.id=s.word_id "
        "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='fr' WHERE s.id IN (%s)"
        % ",".join(str(x) for x in random.Random(11).sample(list(idx), min(a.sample, len(idx)))))
    print("%-22s %-58s %s" % ("词形", "法语原文", "生成的中文"))
    print("-" * 116)
    for sid, w, fr in q:
        print("%-22s %-58s %s" % (w[:22], " ".join(fr.split())[:58], idx[sid]))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    with dbtool.session("keep-v3-geo-template",
                        expect={"#sense_gloss": len(out)}) as s:
        s.executemany(
            "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
            "VALUES (?,'zh','equivalent',0,?,?)",
            [(sid, z, SRC) for sid, z, _t, _f in out])
    print("\n✓ 写入 %s 条 sense_gloss(lang='zh', src='%s')" % (f"{len(out):,}", SRC))
    return 0


if __name__ == "__main__":
    sys.exit(main())
