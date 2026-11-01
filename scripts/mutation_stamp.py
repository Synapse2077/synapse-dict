#!/usr/bin/env python3
"""各门变异档的**台账**：闸的代码或它读的计划表变了 ⇒ 欠一次变异，汇总闸点名。2026-11-01（B20 ＋ B14①）。

═══ 为什么要它 ═══
变异验证是「闸的闸」，而它**不跑就不会坏给你看**：
  · B20 六次「变异静默失效」，都是**前提变了**（计划表里的阶段状态推进、豁免兑现）而没人重跑变异；
  · vi/ru 有 `gates.MUTLOG`（锚闸文件 sha），其余八门 18 个带 `--mutate` 的脚本**没有任何台账**。
⇒ 照 vi 的形状推广：记下每个脚本**上次跑绿变异时**它依赖的文件的 sha；对不上就欠。

═══ 依赖算哪些（`deps`）═══
  · 脚本自己 —— 改断言、改基线、整段替换（vi 那次把 P12/P13 切掉而正常跑报「全绿」）
  · 账的闸另加**它读的计划表** —— B20 的 V4/V2/V11 都是计划表状态推进让变异空转
⚠️ **库不算**：回归闸的变异在库副本上跑，一轮 16 分钟到 1 小时 49 分钟（fr）；
   每写一次库就欠一次 = 永远欠着 = 没人看（`[[permanently-red-gate-masks-real-reds]]`）。
   变异若依赖「库里恰好还有缺陷」，应当改成自带前提（en 回归闸在内存库里注入的写法），不是让台账追库。

═══ 2026-11-01 首轮实测（建台账之前把 18 个全跑了一遍）═══
变异全部逮到、无一崩溃；最慢 fr 回归闸 6,523s、de 2,932s、it 1,878s、es 1,313s、ja 962s、pt 640s，其余 ≤ 137s。
顺带逮到 5 处临时目录不清理（de 账的闸每轮漏 7 GB 库副本、it 回归闸 1.2 GB），已改；
本入口另外**每次给子进程一个专属 TMPDIR、跑完整个删掉** ⇒ 脚本自己忘了清也漏不出来。

用法（仓库根）：
    python3 scripts/mutation_stamp.py                # 打台账；欠着就退出码 1（gate:mutation-debt）
    python3 scripts/mutation_stamp.py --run NAME     # 跑一个（NAME 如 ja/regression）
    python3 scripts/mutation_stamp.py --run-owed     # 把欠着的依次跑完
    python3 scripts/mutation_stamp.py --mutate       # 自检 debt() 的分支
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAMP = ROOT / "data" / "db" / ".mutation-stamp.json"   # 跟库走，不进 git

PLAN = {"de": "DE_PLAN", "en": "EN_PLAN", "fr": "FR_PLAN", "ja": "JA_PLAN", "ko": "KO_PLAN", "pt": "PT_PLAN"}
# (名字, 门, 脚本) —— vi/ru 不在这里：它们的 `gates.MUTLOG` 由各自账的闸管
SUITES = [(lang + "/" + kind, lang, "tests/%s.py" % script) for lang, kind, script in (
    ("de", "literal", "test_no_literal_counts"), ("de", "regression", "test_no_regression"), ("de", "ledger", "test_plan_ledger"),
    ("en", "literal", "test_no_literal_counts"), ("en", "regression", "test_no_regression"), ("en", "ledger", "test_plan_ledger"),
    ("es", "regression", "test_no_regression"),
    ("fr", "regression", "test_no_regression"), ("fr", "ledger", "test_plan_ledger"), ("fr", "template", "test_template_roundtrip"),
    ("it", "regression", "test_no_regression"),
    ("ja", "literal", "test_no_literal_counts"), ("ja", "regression", "test_no_regression"), ("ja", "ledger", "test_plan_ledger"),
    ("ko", "ledger", "test_plan_ledger"),
    ("pt", "literal", "test_no_literal_counts"), ("pt", "regression", "test_no_regression"), ("pt", "ledger", "test_plan_ledger"),
)]


def deps(name):
    """→ 这个变异档依赖的文件（相对仓库根）。"""
    lang, kind = name.split("/")
    script = next(s for n, _l, s in SUITES if n == name)
    out = ["%s/%s" % (lang, script)]
    if kind == "ledger" and lang in PLAN:
        out.append("docs/%s.md" % PLAN[lang])
    return out


def shas(name):
    """→ {文件: sha16}；文件不在记 None（被删也算变了）。"""
    out = {}
    for f in deps(name):
        p = ROOT / f
        out[f] = hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else None
    return out


def load():
    if not STAMP.exists():
        return {}
    try:
        return json.loads(STAMP.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit("🔴 变异台账读不动：%s（%s）—— 别当成「没欠」" % (STAMP, e))


def debt(log, now):
    """纯函数。log：台账；now：{名字: shas}。→ [(名字, 原因)]，空 ＝ 每个变异档都在当前版本上跑绿过。"""
    out = []
    for name in now:
        rec = log.get(name)
        if rec is None:
            out.append((name, "从没在这套台账下跑过变异"))
        elif not rec.get("ok"):
            out.append((name, "上次跑变异退出码 %s（%s）" % (rec.get("code"), rec.get("when", "?"))))
        else:
            changed = sorted(f for f, s in now[name].items() if rec.get("shas", {}).get(f) != s)
            if changed:
                out.append((name, "改过：%s（上次 %s，约 %ss）" % ("、".join(changed), rec.get("when", "?"), rec.get("secs", "?"))))
    return out


def run(name):
    """跑一个变异档并记台账。子进程一个专属 TMPDIR，跑完整个删掉。→ 退出码。"""
    lang = name.split("/")[0]
    script = next(s for n, _l, s in SUITES if n == name)
    before = shas(name)                    # 开跑前取：跑的途中改了文件 ⇒ 下次照样欠
    tmp = tempfile.mkdtemp(prefix="mutation-%s-" % name.replace("/", "-"))
    t0 = time.time()
    print("── %s：cd %s && python3 %s --mutate" % (name, lang, script), flush=True)
    try:
        r = subprocess.run([sys.executable, "-u", "-B", script, "--mutate"], cwd=ROOT / lang,
                           # DISPLAY_GATES_RUNNING：账的闸正常跑那一遍里「展示层汇总闸欠一次」与变异无关 ——
                           # 不拆的话 ko 账的闸永远红（汇总闸又在报它欠变异），与 `run_display_gates.py` 同一个环
                           env=dict(os.environ, TMPDIR=tmp, DISPLAY_GATES_RUNNING="1"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    secs = int(time.time() - t0)
    log = load()
    log[name] = {"ok": r.returncode == 0, "code": r.returncode, "shas": before, "secs": secs,
                 "when": datetime.datetime.now().isoformat(timespec="seconds")}
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("   %s %s（退出码 %d，%ds）" % ("✅" if r.returncode == 0 else "🔴", name, r.returncode, secs), flush=True)
    return r.returncode


def selftest():
    now = {n: shas(n) for n, _l, _s in SUITES}
    k = SUITES[0][0]
    green = {n: {"ok": True, "code": 0, "shas": dict(s), "when": "t", "secs": 1} for n, s in now.items()}
    led = next(n for n, _l, _s in SUITES if n.endswith("/ledger"))
    plan = next(f for f in now[led] if f.startswith("docs/"))
    cases = [
        ("从没跑过", {}, now, True),
        ("上次跑红", dict(green, **{k: dict(green[k], ok=False, code=1)}), now, True),
        ("脚本改过", green, dict(now, **{k: {f: "0" * 16 for f in now[k]}}), True),
        ("账的闸读的计划表改过（B20 的 V4 形状）", green, dict(now, **{led: dict(now[led], **{plan: "0" * 16})}), True),
        ("脚本被删", green, dict(now, **{k: {f: None for f in now[k]}}), True),
        ("（反控）都没变", green, now, False),
    ]
    dead = 0
    for name, log, cur, want in cases:
        got = bool(debt(log, cur))
        dead += got != want
        print("  %s %s" % ("✅" if got == want else "🔴 没逮到", name))
    # 名单本身：每个脚本都在盘上、且真有 --mutate 入口
    for n, lang, s in SUITES:
        p = ROOT / lang / s
        if not p.exists() or "--mutate" not in p.read_text(encoding="utf-8"):
            dead += 1
            print("  🔴 名单里的 %s 不存在或没有 --mutate 入口" % n)
    print("  变异台账自检 %s" % ("通过" if not dead else "🔴 %d 处失败" % dead))
    return 1 if dead else 0


def main():
    a = sys.argv[1:]
    if "--mutate" in a:
        return selftest()
    if "--run" in a:
        name = a[a.index("--run") + 1]
        if name not in {n for n, _l, _s in SUITES}:
            raise SystemExit("🔴 没有这个变异档：%r；有：%s" % (name, "、".join(n for n, _l, _s in SUITES)))
        return 1 if run(name) else 0
    owed = debt(load(), {n: shas(n) for n, _l, _s in SUITES})
    if "--run-owed" in a:
        return 1 if sum(bool(run(n)) for n, _ in owed) else 0
    print("■ 变异台账：%d 个变异档（vi/ru 由各自的 MUTLOG 管）" % len(SUITES))
    for n, why in owed:
        print("  🔴 %-16s 欠一次变异：%s" % (n, why))
    if owed:
        print("  ⇒ python3 scripts/mutation_stamp.py --run-owed（或 --run <名字>）")
    else:
        print("  ✅ 每个变异档都在当前版本上跑绿过")
    return 1 if owed else 0


if __name__ == "__main__":
    sys.exit(main())
