#!/usr/bin/env python3
"""跨语种闸：**写库闸门的追踪清单（`TRACK` / `TRACK_TABLES`）必须与库对得上 —— 两个方向**。B7，2026-10-31。

═══ 为什么需要这道闸 ═══
各门 `dbtool.snapshot()` 有一条「清单里找不到的列/表就跳过」—— 那是给「先写进清单、再建出来」
留的口子，合理，但它让**「名字写错了／早删了／从没建过」与「还没建出来」长得一模一样**，
而被跳过的条目闸门一行都守不住。另一个方向更糟：**库里有、清单里没有的表，行数随便变，没有任何东西会响。**

本闸建成当天实测（十门）：
· 死条目：ja/en/de/pt 列着库里没有的 `pronunciation_entry`；en 列着阶段 0 已改名的 `stardict`；
  de 列着 v3 降列时已删的 7 个 `dict` 列（it 的同一张清单当时就删了，de 漏了）。
· 漏登记：**八门里只有 it 真有 `pronunciation_entry`（282,060 行），而它恰恰不在 it 的清单里**；
  es **一张表都不数**（19 张）；`search_prefix`/`_meta` 漏在 it/fr/pt/de/ja，`field_src` 漏在 de/ja/ko，
  en 漏了 `legacy_gloss`。
🔴 ja/ko/vi/ru 各有一个 `_track_audit()` 查死条目，**没有一个查反方向** —— 而「死条目删掉之后，
   万一建了谁来守」的答案只能是反方向那一半。**同一个洞有两半时，修一半比不修更危险。**

═══ 判据（各门的清单 import，不重写）═══
  T1  `TRACK` 里的列在库里不存在（无前缀＝`TABLE`，`表.列`＝那张表）
  T2  `TRACK_TABLES` 里的表在库里不存在
  T3  库里的表（除主干 `TABLE` 与 `sqlite_*`）不在 `TRACK_TABLES` 里
  T0  十门都在（`*/dbtool.py` 与 `LANGS` 两份独立声明对得上）

各门的清单在**子进程**里读（`cd <lang>; import dbtool`）：各门都有自己的 `paths`/`dbtool`，
同一个解释器里依次 import 会拿到第一门的缓存模块 —— 建这道闸时我自己的测量脚本就栽在这里，
十门全读成了 en 的库。

用法：
    python3 scripts/test_track_gate.py            # 红了退出码 1
    python3 scripts/test_track_gate.py --mutate   # 变异验证：每条判据各注入一次，必须各自变红
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ("en", "es", "it", "fr", "pt", "de", "ja", "ko", "vi", "ru")

_PROBE = ("import json, dbtool; print(json.dumps({'db': str(dbtool.DB), 'table': getattr(dbtool, 'TABLE', 'dict'),"
          " 'track': list(dbtool.TRACK), 'tables': list(getattr(dbtool, 'TRACK_TABLES', []))}))")


def declared(lang):
    r = subprocess.run([sys.executable, "-B", "-c", _PROBE], cwd=ROOT / lang, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("🔴 %s：读不出 dbtool 的清单：%s" % (lang, r.stderr.strip()[-300:]))
    return json.loads(r.stdout.strip().splitlines()[-1])


def actual(db):
    c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        tabs = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols = {t: {r[1] for r in c.execute("PRAGMA table_info(%s)" % t)} for t in tabs}
    finally:
        c.close()
    return cols


def check(decl, cols):
    """→ {判据: [条目]}，空表示绿。"""
    out = {"T1": [], "T2": [], "T3": []}
    for x in decl["track"]:
        t, c = x.split(".", 1) if "." in x else (decl["table"], x)
        if c not in cols.get(t, ()):
            out["T1"].append(x)
    out["T2"] = [t for t in decl["tables"] if t not in cols]
    out["T3"] = sorted(t for t in cols if t != decl["table"] and not t.startswith("sqlite_")
                       and t not in decl["tables"])
    return out


def t0(langs):
    """T0：有 `dbtool.py` 的目录与 `LANGS` 必须是同一组 —— 两份独立声明，任何一边漏一门都红。"""
    found = sorted(p.parent.name for p in ROOT.glob("*/dbtool.py"))
    return [] if found == sorted(langs) else [found, sorted(langs)]


def run(verbose=True):
    bad = 0
    miss = t0(LANGS)
    if miss:
        bad += 1
        print("🔴 T0 门的名单对不上：dbtool.py 在 %s，LANGS 声明 %s" % tuple(miss))
    state = {}
    for lang in LANGS:
        decl = declared(lang)
        if not Path(decl["db"]).exists():
            print("   %s  （库不存在，跳过）" % lang)
            continue
        cols = actual(decl["db"])
        state[lang] = (decl, cols)
        res = check(decl, cols)
        n = sum(len(v) for v in res.values())
        bad += n
        if verbose or n:
            print("%s %s  列 %d／表 %d%s" % ("✅" if not n else "🔴", lang, len(decl["track"]), len(decl["tables"]),
                                          "".join("  %s %s" % (k, v) for k, v in res.items() if v)))
    return bad, state


def mutate(state):
    """每门、每条判据各注入一次 —— 各自必须变红。改的是子进程读出来的声明副本，不碰源文件。"""
    fails = 0
    total = 0

    def expect_red(label, rule, decl, cols, needle):
        nonlocal fails, total
        total += 1
        hit = needle in check(decl, cols)[rule]
        if not hit:
            fails += 1
        print("   %s %s" % ("✅" if hit else "🔴 没逮到：", label))

    for lang, (decl, cols) in state.items():
        d = dict(decl, track=decl["track"] + ["__dead_col__"])
        expect_red("%s M1 清单里加一个库里没有的列 → T1" % lang, "T1", d, cols, "__dead_col__")
        d = dict(decl, track=decl["track"] + ["sense.__dead_col__"])
        expect_red("%s M2 `表.列` 形式的死列 → T1" % lang, "T1", d, cols, "sense.__dead_col__")
        d = dict(decl, tables=decl["tables"] + ["__dead_table__"])
        expect_red("%s M3 清单里加一张库里没有的表 → T2" % lang, "T2", d, cols, "__dead_table__")
        victim = decl["tables"][0]
        d = dict(decl, tables=decl["tables"][1:])
        expect_red("%s M4 清单漏登记一张真表（%s）→ T3" % (lang, victim), "T3", d, cols, victim)
    # T0：名单少一门必须红
    total += 1
    ok = bool(t0(LANGS[:-1]))
    fails += not ok
    print("   %s M5 LANGS 少登记一门 → T0" % ("✅" if ok else "🔴 没逮到："))
    print("\n变异 %d/%d 逮到" % (total - fails, total))
    return fails


def main():
    bad, state = run()
    if "--mutate" in sys.argv:
        if bad:
            raise SystemExit("🔴 基线不绿，变异验证没有意义 —— 先修基线")
        print("\n■ 变异验证")
        if mutate(state):
            raise SystemExit(1)
        return
    print("\n%s 追踪清单与库%s" % ("🔴" if bad else "✅", "对不上 %d 处" % bad if bad else "两个方向都对得上（%d 门）" % len(state)))
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
