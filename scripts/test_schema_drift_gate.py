#!/usr/bin/env python3
"""跨门闸：**库里每张表的建表语句，与各门建表脚本声明的一致**（列定义 ＋ 约束/唯一键）。B24，2026-10-31。

═══ 为什么 ═══
`CREATE TABLE IF NOT EXISTS` 对已存在的表是空操作 ⇒ 改了建表脚本老库不变；反过来后来的脚本加列、
整表重建换唯一键，建表脚本也不跟着变。原来八门的结构核对只数对象名和列名，对这些结构性失明。
建成当天实测（九门）：ko/vi/ru 一致；**en `pronunciation`（49.8 万行）唯一键漂了** ——
库里是 `UNIQUE(…, notation, region)`（`build_pronunciation.py` 09-08 重建），建表脚本还是旧的四列，
按脚本重建新库会把英美同音的读音撞掉；另 de/fr/pt/ja/it 共 14 张表有后来加的列没登记。

═══ 判据 ═══ `scripts/schema_drift.py`（与 ru 的 S6 同一份）。各门的声明在**子进程**里读
（各门的 `paths`/`dbtool` 同名，同一解释器里依次 import 会拿到第一门的缓存）。
  D0  每门的建表脚本至少认出 1 条 `CREATE TABLE`（认不出＝判据坏了，不是通过）
  D1  逐表对账一致（声明了而库里没有的表也算不一致）

用法：
    python3 scripts/test_schema_drift_gate.py            # 红了退出码 1
    python3 scripts/test_schema_drift_gate.py --mutate   # ＋变异：每门注入三种漂移各一次，必须各自变红
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from schema_drift import drift  # noqa: E402

SCHEMA = {  # 门 → 建表脚本（独立声明；漏一门 T0 红）
    "en": "build_v3_schema.py", "it": "build_v2_schema.py", "fr": "build_v3_schema.py",
    "pt": "build_v3_schema.py", "de": "build_v3_schema.py", "ja": "build_v3_schema.py",
    "ko": "build_v3_schema.py", "vi": "build_v3_schema.py", "ru": "build_v3_schema.py",
}
NO_SCHEMA = {"es": "es 没有建表脚本（v2 结构由收割器各自建表，B24 原文已注明）"}

_PROBE = r'''
import importlib.util, json, sqlite3, sys
from pathlib import Path
root = Path(sys.argv[1]); lang = sys.argv[2]; f = sys.argv[3]
sys.path[:0] = [str(root / lang / "pipeline"), str(root / lang), str(root / "scripts")]
spec = importlib.util.spec_from_file_location("schema_mod", root / lang / "pipeline" / f)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import paths
from schema_drift import create_statements, added_columns
con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
live = {r[0]: r[1] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")}
print(json.dumps({"stmts": create_statements(m), "added": {k: sorted(v) for k, v in added_columns(m).items()},
                  "live": live}))
'''


def load(lang):
    r = subprocess.run([sys.executable, "-B", "-c", _PROBE, str(ROOT), lang, SCHEMA[lang]],
                       capture_output=True, text=True, cwd=ROOT / lang)
    if r.returncode:
        raise SystemExit("🔴 %s：读不出建表声明：%s" % (lang, r.stderr.strip()[-400:]))
    d = json.loads(r.stdout.strip().splitlines()[-1])
    d["added"] = {k: set(v) for k, v in d["added"].items()}
    return d


def check(d):
    if not d["stmts"]:
        return [("(D0)", "建表脚本里一条 CREATE TABLE 都没认出来 —— 判据坏了，不是通过")]
    return drift(d["live"], d["stmts"], d["added"])


def t0():
    have = {p.parent.parent.name for p in ROOT.glob("*/pipeline/build_v*_schema.py")}
    return sorted(have ^ set(SCHEMA))


def main():
    bad = 0
    miss = t0()
    if miss:
        bad += 1
        print("🔴 T0 建表脚本的名单对不上：%s" % miss)
    state = {}
    for lang in SCHEMA:
        d = load(lang)
        state[lang] = d
        res = check(d)
        bad += len(res)
        print("%s %s  %d 张表%s" % ("🔴" if res else "✅", lang, len(d["stmts"]),
                                  "".join("\n      `%s` %s" % x for x in res)))
    for lang, why in NO_SCHEMA.items():
        print("   %s  （%s）" % (lang, why))
    print("\n%s 建表语句逐表对账%s" % ("🔴" if bad else "✅", "：%d 处不一致" % bad if bad else "一致（%d 门）" % len(SCHEMA)))
    if bad:
        raise SystemExit(1)
    if "--mutate" not in sys.argv:
        return
    print("\n■ 变异（改的是读出来的声明副本，库和源文件都不碰）")
    fails = total = 0
    for lang, d in state.items():
        # 取一张同时有约束的表、一张任意表
        con_tbl = next((t for t, s in d["stmts"].items() if "unique" in s.lower()), None)
        any_tbl = sorted(d["stmts"])[0]
        cases = []
        if con_tbl:
            s = d["stmts"][con_tbl]
            i = s.lower().rindex("unique")
            cases.append(("唯一键少一列（en 那种漂移）",
                          dict(d, stmts=dict(d["stmts"], **{con_tbl: s[:i] + "UNIQUE(zz_only_this)" + s[s.index(")", i) + 1:]}))))
        cases.append(("库里多一列而没登记", dict(d, live=dict(d["live"], **{any_tbl: d["live"][any_tbl].rstrip().rstrip(")") + ", zz_extra TEXT)"}))))
        cases.append(("声明了一张库里没有的表", dict(d, stmts=dict(d["stmts"], zz_t="CREATE TABLE zz_t (a TEXT)"))))
        for label, dd in cases:
            total += 1
            hit = bool(check(dd))
            fails += not hit
            print("   %s %s %s" % ("✅" if hit else "🔴 没逮到：", lang, label))
    total += 1
    ok = bool(check(dict(next(iter(state.values())), stmts={})))
    fails += not ok
    print("   %s D0 一条建表语句都认不出 ⇒ 红（不许当成通过）" % ("✅" if ok else "🔴 没逮到："))
    print("\n变异 %d/%d 逮到" % (total - fails, total))
    if fails:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
