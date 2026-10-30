#!/usr/bin/env python3
"""B17 跨门闸：读者不该在「相关词」和更具体的类别下看见同一个词。2026-10-27。

判据 import 自 `scripts/redundant_related.py`（唯一的家），不在这里重写。

    python3 -u scripts/test_redundant_related_gate.py            # 红了退出码非 0
    python3 -u scripts/test_redundant_related_gate.py --mutate   # 变异：闸自己的闸

三件事：
  R1 已登记的门（de/ja/es）冗余 `related` 必须是 0。
  R2 未登记的门按**基础名单**量，与 DEBT 逐字相等 —— **涨了红，降了也红**
     （降有两种原因：真修了 / 判据坏了；后者会让闸永远绿。`test_audio_dup_gate` 同一条）。
  K0 已登记的门里出现**没归类的 kind**（既不在 subsume 也不在 not_subsume）⇒ 红：
     新 kind 不会自动算「更具体」，不归类就等于这条判据对它静默失明。
"""
import argparse
import collections
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from redundant_related import REGISTRY, SUBSUME_BASE, redundant  # noqa: E402

DB = ROOT / "data" / "db"
LANGS = ["en", "es", "it", "fr", "pt", "de", "ja", "ko", "vi", "ru"]

# 🔴 未登记门的欠账（2026-10-27 实测，按基础名单量）。
#    en/it/fr/pt 是 0 **因为库里根本没有 `related` 这个 kind**，不是治理过 —— 别拿它们当「已修」的证据。
#    ko：K34 只修了词条级，剩下的是义项内／跨范围那两种形状；判据要按 ko 自己的值域登记后才能动。
#    vi：`SUBSUME` 是建库时定的、只看词级，同上。ru：1 条。
DEBT = {"en": 0, "it": 0, "fr": 0, "pt": 0, "ko": 542, "vi": 124, "ru": 1}


def load(lang):
    db = DB / ("synapse-dict-%s.sqlite" % lang)
    if not db.exists():
        return None
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    cols = [r[1] for r in con.execute("PRAGMA table_info(sense_relation)")]
    if not cols:
        return None
    hid = "COALESCE(hidden,0)=0" if "hidden" in cols else "1"
    sid = "sense_id" if "sense_id" in cols else "NULL"
    rows = con.execute("SELECT id, word_id, %s, kind, target FROM sense_relation WHERE %s"
                       % (sid, hid)).fetchall()
    con.close()
    return rows


def judge(lang, rows):
    """→ (红的理由列表, 冗余条数)"""
    reg = REGISTRY.get(lang)
    if reg:
        n = len(redundant(rows, reg["subsume"], reg["floated"]))
        bad = ["R1 冗余 related %d 条（已登记的门必须 0）" % n] if n else []
        known = reg["subsume"] | reg["not_subsume"] | {"related"}
        new = sorted({r[3] for r in rows} - known)
        if new:
            bad.append("K0 没归类的 kind：%s（写进 redundant_related.REGISTRY）" % "、".join(new))
        return bad, n
    n = len(redundant(rows, SUBSUME_BASE))
    want = DEBT[lang]
    return ([] if n == want else ["R2 冗余 related %d ≠ 登记 %d" % (n, want)]), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    data = {l: load(l) for l in LANGS}
    print("■ B17 跨门闸：兜底 related 撞上更具体的 kind（判据 redundant_related.py）")
    red = 0
    for lang in LANGS:
        rows = data[lang]
        if rows is None:
            print("  %-3s （无库或无 sense_relation）" % lang)
            continue
        bad, n = judge(lang, rows)
        tag = "已登记" if lang in REGISTRY else "欠账 %d" % DEBT[lang]
        print("  %s %-3s 冗余 %-6d（%s）%s" % ("🔴" if bad else "✅", lang, n, tag,
                                           "  " + "；".join(bad) if bad else ""))
        red += bool(bad)
    print(("🔴 %d 门红" % red) if red else "✅ 全绿")
    if not a.mutate:
        sys.exit(1 if red else 0)

    # ── 变异：在**内存里的行**上注入，真库一行不动 ──
    print("\n■ 变异")
    nid = 10 ** 12

    def dup_specific(rows, kind_pick, other_sense=False):
        """找一条可见的更具体 kind，给它配一条同目标的 related。
        other_sense：挂到**另一个**（不存在的）义项上 —— 只有「上浮」那一支（③）逮得到它。"""
        for _i, w, s, k, t in rows:
            if k in kind_pick and (not other_sense or s is not None):
                return rows + [(nid, w, -1 if other_sense else s, "related", t)]
        raise SystemExit("🔴 变异前提不成立：找不到可复制的行")   # 前提不成立当场炸，不报「没逮到」

    cases = [
        ("de 冒出一条与 synonym 同范围同目标的 related", "de",
         lambda r: dup_specific(r, {"synonym"}), "R1"),
        ("ja 义项里的 related 撞上上浮到页尾的 derived", "ja",
         lambda r: dup_specific(r, {"derived"}, other_sense=True), "R1"),
        ("（反控）de 跨义项的 related 不该被判冗余", "de",
         lambda r: dup_specific(r, {"synonym"}, other_sense=True), None),
        ("es 冒出一个没归类的新 kind", "es",
         lambda r: r + [(nid, r[0][1], None, "zzz_new_kind", "x")], "K0"),
        ("ko 欠账涨了一条", "ko", lambda r: dup_specific(r, {"synonym"}), "R2"),
        ("vi 欠账降了（判据坏了的样子）", "vi",
         lambda r: (lambda gone: [x for x in r if x[0] != gone])(redundant(r, SUBSUME_BASE)[0]), "R2"),
    ]
    dead = 0
    for name, lang, f, want in cases:
        bad, _n = judge(lang, f(list(data[lang])))
        ok = (not bad) if want is None else any(b.startswith(want) for b in bad)
        dead += not ok
        print("  %s %-44s → %s" % ("✅" if ok else "🔴 没逮到", name, "；".join(bad) or "（绿）"))
    print("  变异 %d/%d" % (len(cases) - dead, len(cases)))
    sys.exit(1 if dead or red else 0)


if __name__ == "__main__":
    main()
