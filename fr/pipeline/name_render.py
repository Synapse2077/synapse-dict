#!/usr/bin/env python3
"""用手写模式 + 已翻形容词，**确定性生成**姓氏/名字族的中文释义。2026-08-23。

═══ 链条（与地名族同构）═══
    name_patterns.py       法语句式 → 中文句式 + 槽位（我手写）
    name_translate_slots   语言/国别形容词 → 中文（flash 翻一次，226 个）
    本步                    组装 → 写 sense_gloss(lang='zh', src='template:name')

**26,067 条 ⇒ 生成 24,9xx 条，由少数句式 + 226 个形容词组装，110 倍压缩。**

═══ 三条放弃规则（宁可缺不可错）═══
  ① 句子匹配不上任何模式（多是带交叉引用的，`Prénom féminin ; variante de Laetitia.`）
  ② 性别不在 `GENDER_ZH` 闭集里
  ③ 形容词没有中文（模型主动留空的 5 个）

用法（在 fr/ 目录下）：
    python3 pipeline/name_render.py --audit    # **按模式分组审查**，写库前必看
    python3 pipeline/name_render.py --apply
"""
import argparse
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool                                             # noqa: E402
import paths                                              # noqa: E402
from pipeline import slot_translate                       # noqa: E402
from pipeline.name_patterns import match, FAM, gender_zh, render   # noqa: E402
from pipeline.name_translate_slots import OUT as SLOT_ZH  # noqa: E402

SRC = "template:name"


def slot_table():
    return {k: v["zh"] for k, v in slot_translate.done_keys(SLOT_ZH).items() if v["zh"]}


def build(con, zh_of):
    rows = con.execute("""
        SELECT s.id, g.text FROM sense s
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
        WHERE z.sense_id IS NULL""").fetchall()
    out, why = [], Counter()
    for sid, raw in rows:
        t = " ".join(raw.split())
        if not FAM.match(t):
            why["非姓名族"] += 1
            continue
        m = match(t)
        if not m:
            why["①无模式匹配"] += 1
            continue
        tpl, slots = m
        filled, drop = [], None
        for kind, val in slots:
            v = val.strip()
            z = gender_zh(v) if kind == "G" else zh_of.get(v)
            if not z:
                drop = "②性别不在闭集" if kind == "G" else "③形容词无中文"
                break
            filled.append(z)
        if drop:
            why[drop] += 1
            continue
        out.append((sid, render(tpl, filled), tpl, t))
    return out, why


def check(out):
    bad = Counter()
    for _s, z, _t, _f in out:
        if "{" in z or "}" in z:
            bad["未填的占位符"] += 1
        if re.search(r"[A-Za-zÀ-ÿ]", z):
            bad["残留拉丁字母"] += 1
        if not z.strip():
            bad["空串"] += 1
    ids = [s for s, _z, _t, _f in out]
    if len(set(ids)) != len(ids):
        bad["sense_id 重复"] = len(ids) - len(set(ids))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--sample", type=int, default=20)
    a = ap.parse_args()

    zh_of = slot_table()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    out, why = build(con, zh_of)
    fam = sum(why.values()) + len(out) - why["非姓名族"]

    print("■ 姓名族 %s 条 ⇒ 生成 %s（%.1f%%）"
          % (format(fam, ","), format(len(out), ","), 100.0 * len(out) / fam))
    print("\n── 放弃原因 ──")
    for k, v in sorted(why.items(), key=lambda x: -x[1]):
        if k != "非姓名族":
            print("   %-16s %s 条" % (k, format(v, ",")))

    bad = check(out)
    if bad:
        print("\n🔴 不变量红了，**不写**：%s" % dict(bad))
        return 1
    print("\n✓ 不变量全绿")

    if a.audit:
        g = defaultdict(list)
        for _s, z, tpl, fr in out:
            g[tpl].append((fr, z))
        print("\n── 按模式分组（%d 条模式）──" % len(g))
        for tpl, rs in sorted(g.items(), key=lambda x: -len(x[1])):
            print("\n【%s 条】%s" % (format(len(rs), ","), tpl))
            for fr, z in rs[:2]:
                print("      %-58s → %s" % (fr[:58], z))
        return 0

    idx = {s: z for s, z, _t, _f in out}
    print("\n── 随机 %d 条 ──" % a.sample)
    for sid, w, fr in con.execute(
            "SELECT s.id, d.word, g.text FROM sense s JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='fr' WHERE s.id IN (%s)"
            % ",".join(str(x) for x in random.Random(5).sample(list(idx), min(a.sample, len(idx))))):
        print("   %-20s %-48s → %s" % (w[:20], " ".join(fr.split())[:48], idx[sid]))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    with dbtool.session("keep-v3-name-template", expect={"#sense_gloss": len(out)}) as s:
        s.executemany(
            "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
            "VALUES (?,'zh','equivalent',0,?,?)",
            [(sid, z, SRC) for sid, z, _t, _f in out])
    print("\n✓ 写入 %s 条 sense_gloss(lang='zh', src='%s')" % (format(len(out), ","), SRC))
    return 0


if __name__ == "__main__":
    sys.exit(main())
