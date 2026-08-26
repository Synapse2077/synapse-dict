#!/usr/bin/env python3
"""剩下几个小族的确定性生成：英格兰教区 / 市镇分区 / 旧名 / 魁北克。2026-08-24。

承地名族、姓名族、指针族、居民族的同一套做法：
**手写句式 + 槽值翻一次全库复用 + `--audit` 按形状审查 + 可逆性回核**。

| 族 | 匹配 | 槽值 | 已有中文覆盖 |
|---|---:|---:|---:|
| 英格兰民政教区 | 9,263 | 241 个区名 | **90.8%**（地名族那轮翻过，直接复用）|
| 市镇的一部分 | 2,584 | 597 个市镇名 | 7.9% |
| 旧名/旧市镇 | 1,074 | 1,074 个市镇名 | 63.0% |
| 魁北克自治体 | 961 | 619 个地名 | 15.1% |

🔴 **槽值一律复用已有的两张表**（`slot_zh.jsonl` 省/区名、`place_zh.jsonl` 市镇名），
   缺的补翻进 `place_zh.jsonl` —— **不新开第三张表**，否则同一个地名会有两个中文。

用法（在 fr/ 目录下）：
    python3 pipeline/misc_render.py --audit
    python3 pipeline/misc_render.py --apply
"""
import argparse
import io
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool                                                        # noqa: E402
import paths                                                         # noqa: E402
from pipeline.demonym_render import (DE, GEO_SLOT, PLACE_SLOT,       # noqa: E402
                                     fix_wangwen, place_ok, COUNTRY_ZH)

SRC = "template:misc"

# (正则, 中文模板, 槽位类型). 槽位类型 R=用地名表 / C=用国名闭集 / TYPE=通名闭集
PATTERNS = [
    # Paroisse civile d’Angleterre située dans le district de Fenland.
    (re.compile(r"^Paroisse civile d[’']Angleterre situ[ée]e?\s+dans le district "
                + DE + r"\s*(.+?)\.?$"),
     "英格兰{}区的民政教区", ["R"]),
    # Paroisse civile du pays de Galles située dans …
    (re.compile(r"^Paroisse civile du [Pp]ays de Galles situ[ée]e?\s+"
                r"(?:dans l[’']autorit[ée] unitaire " + DE + r"|dans le|dans la)\s*(.+?)\.?$"),
     "威尔士{}的民政教区", ["R"]),
    # Section de la commune de Tournai en Belgique.
    (re.compile(r"^Section de la commune " + DE + r"\s*(.+?)\s+(?:en|au|aux)\s+(.+?)\.?$"),
     "{1}{0}市镇的一部分", ["R", "C"]),
    # Ancien nom de la commune française de Bray-sur-Somme.
    (re.compile(r"^Ancien nom de la commune française\s+(?:de\s+|d[’']\s*)?(.+?)\.?$"),
     "法国市镇{}的旧名", ["R"]),
    # Habitant de Granby, ville québécoise.
    (re.compile(r"^(Habitante|Habitant|Relative|Relatif) (?:de|à|d[’']|au|aux)\s*(.+?), "
                r"(?:une |la |le )?(?:municipalit[ée] de village|municipalit[ée] de paroisse|"
                r"municipalit[ée]|ville|village) qu[ée]b[ée]coise\.?$"),
     "加拿大魁北克省{1}的{0}", ["WHO", "R"]),
]

WHO_ZH = {"Habitant": "居民", "Habitante": "女居民", "Relatif": "", "Relative": ""}


def slot_table():
    """两张表合并。**市镇名表优先级低于省/区名表**（同名时省级更可能是对的）。"""
    t = {}
    for p in (PLACE_SLOT, GEO_SLOT):
        if not Path(p).exists():
            continue
        for ln in io.open(p, encoding="utf-8"):
            try:
                o = json.loads(ln)
            except Exception:
                continue
            if o.get("zh"):
                t[o["fr"]] = fix_wangwen(o["zh"])
    return t


def render_one(t, zh_of):
    for rx, tpl, slots in PATTERNS:
        m = rx.match(t)
        if not m:
            continue
        vals = [g.strip() for g in m.groups()]
        if len(vals) != len(slots):
            return None
        filled = []
        for kind, v in zip(slots, vals):
            if kind == "WHO":
                z = WHO_ZH.get(v)
            elif kind == "C":
                z = COUNTRY_ZH.get(v)
            else:
                z = zh_of.get(v) if place_ok(v) else None
            if z is None:
                return None                # 槽值没中文 ⇒ 整条放弃，**不猜**
            filled.append(z)
        return tpl.format(*filled) if ("{0}" in tpl or "{1}" in tpl) else \
            _seqfill(tpl, filled)
    return None


def _seqfill(tpl, filled):
    out = tpl
    for v in filled:
        out = out.replace("{}", v, 1)
    return out


def build(con, rebuild=False):
    zh_of = slot_table()
    cond = ("WHERE z.sense_id IS NULL OR z.src='%s'" % SRC) if rebuild \
        else "WHERE z.sense_id IS NULL"
    rows = con.execute("""
        SELECT s.id, g.text FROM sense s
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
        """ + cond).fetchall()
    out, why = [], Counter()
    for sid, raw in rows:
        t = " ".join(raw.split())
        z = render_one(t, zh_of)
        if z is None:
            why["不匹配或槽值无中文"] += 1
            continue
        out.append((sid, z, t))
    return out, why


def check(out):
    bad = Counter()
    for _s, z, _f in out:
        if not z.strip() or "{" in z:
            bad["空串/模板没填"] += 1
        if len(z) > 90:
            bad["过长"] += 1
    ids = [s for s, _z, _f in out]
    if len(set(ids)) != len(ids):
        bad["sense_id 重复"] = len(ids) - len(set(ids))
    return bad


def missing_slots(con):
    """→ 本模块要用、但两张译名表里还没有的槽值。**补进 `place_zh.jsonl`，不新开表。**"""
    zh_of = slot_table()
    want = Counter()
    ctx = {}
    for (raw,) in con.execute("""
            SELECT g.text FROM sense s
            JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
            LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
            WHERE z.sense_id IS NULL"""):
        t = " ".join(raw.split())
        for rx, _tpl, slots in PATTERNS:
            m = rx.match(t)
            if not m:
                continue
            for kind, v in zip(slots, [g.strip() for g in m.groups()]):
                if kind != "R" or v in zh_of or not place_ok(v):
                    continue
                want[v] += 1
                ctx.setdefault(v, t[:70])
            break
    return [{"fr": v, "kind": "P", "n": c, "ctx": ctx[v]} for v, c in want.most_common()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fill-slots", action="store_true",
                    help="把缺中文的槽值补翻进 place_zh.jsonl（复用同一张表）")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--sample", type=int, default=18)
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)

    if a.fill_slots:
        from pipeline import slot_translate
        from pipeline.place_translate import OUT as PLACE_OUT, SYS as PLACE_SYS
        items = missing_slots(con)
        print("■ 缺中文的槽值 %s 个（补进 %s）" % (format(len(items), ","), PLACE_OUT.name))
        for i in items[:12]:
            print("     n=%-4d %s" % (i["n"], i["fr"][:50]))
        slot_translate.translate(items, PLACE_SYS, PLACE_OUT)
        return 0

    out, why = build(con, a.rebuild)
    print("■ 生成 %s 条（零新增模型调用，槽值全部复用已有译名表）" % format(len(out), ","))

    bad = check(out)
    if bad:
        print("🔴 不变量红了，**不写**：%s" % dict(bad))
        return 1
    print("✓ 不变量全绿")

    if a.audit:
        g = defaultdict(list)
        for _s, z, fr in out:
            g[re.sub(r"[A-ZÀ-Ýa-zà-ÿ][\w’'\-]*", "§", fr)[:56]].append((fr, z))
        print("\n── 按形状分组（top 10）──")
        for k, rs in sorted(g.items(), key=lambda x: -len(x[1]))[:10]:
            print("\n【%s 条】" % format(len(rs), ","))
            for fr, z in rs[:2]:
                print("      %-66s → %s" % (fr[:66], z))
        return 0

    print("\n── 随机 %d 条 ──" % a.sample)
    for _s, z, fr in random.Random(6).sample(out, min(a.sample, len(out))):
        print("   %-68s → %s" % (fr[:68], z))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    old = con.execute("SELECT count(*) FROM sense_gloss WHERE src=?", (SRC,)).fetchone()[0]
    delta = len(out) - (old if a.rebuild else 0)
    with dbtool.session("keep-v3-misc", expect={"#sense_gloss": delta}) as s:
        if a.rebuild:
            s.execute("DELETE FROM sense_gloss WHERE src=?", (SRC,))
        s.executemany(
            "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
            "VALUES (?,'zh','equivalent',0,?,?)",
            [(sid, z, SRC) for sid, z, _f in out])
    print("\n✓ 写入 %s 条 sense_gloss(src='%s')" % (format(len(out), ","), SRC))
    return 0


if __name__ == "__main__":
    sys.exit(main())
