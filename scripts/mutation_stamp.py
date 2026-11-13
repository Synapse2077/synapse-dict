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

═══ B34（2026-11-12）：台账原来只登八门 `tests/` 下的 18 个 ═══
登记表里的闸（`package.json` 的 `gate:*`、`ko/gates.py`）文件里写着 `--mutate`，却**没有任何一本台账逼人跑** ——
22 个（9 道 tsx 契约闸、`scripts/` 下 7 道、ko 外锚闸两道＋查询计划闸）；es 外锚闸连登记表都没进。
发现时：B31 给 ko 外锚闸加了 N10，账上写的跑法 `ko/run_gates.py --mutate` 并不存在，而本台账照报「全绿」。
⇒ ① 变异档改为**从登记表派生**（新闸一登记就进台账，不靠人记得加一行）；
  ② 元检查 `scan()`：全仓带 `--mutate` 的文件逐个归类 —— 在台账里／登记命令自带 `--mutate`（每次都跑）／
     vi·ru 自己的 MUTLOG／按 `EXEMPT` 规则豁免（每条写理由和推翻条件）—— **归不进去就红**；
  ③ 档数独立声明（`EXPECT_SUITES`）：登记表被删一行，派生会静默少一个，只有这个数会响。
"""
import collections
import datetime
import hashlib
import json
import os
import re
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


EXPECT_SUITES = 42    # 独立声明（B34）：tests/ 18 ＋ 登记表派生 22 ＋ es 外锚闸 1 ＋ display_stamp 自检 1

# 登记表之外、单独登的（B34）
DIRECT = [
    # es 外锚闸：自称闸、锚 dump，但 es 没有闸登记表 ⇒ 普通档也没人跑（es 已封版；这里至少让「改了没验」有声音）
    ("es/verify-vs-dump", "es/pipeline/verify_vs_dump.py", ["-m", "es.pipeline.verify_vs_dump", "--mutate"]),
    # display_stamp：vi/ru V9、ko P12 都靠它判「展示层汇总过期没有」，它的 reasons() 自带四分支自检
    ("scripts/display-stamp", "scripts/display_stamp.py", ["scripts/display_stamp.py", "--mutate"]),
]

# 带 `--mutate` 而**有意不进台账**的：(正则, 理由)。每条至少要匹配一个文件（过期规则也红）。
EXEMPT = [
    (r"^(de|en|es|fr|it|pt)/(pipeline|fixes)/",
     "写库脚本内嵌的写后闸：普通档只在脚本重跑写库时跑，变异与之同一生命周期（重跑写库时一起 `--mutate`）。"
     "⚠️ 推翻条件：这几个目录里出现**独立运行的闸**（不写库、只核对，如 es 的 verify_vs_dump）—— 它必须进 DIRECT 或登记表"),
    (r"^it/probes/",
     "it 已完结、没登记为闸的探针：norm/tts 两份契约随合成音搁置（用户试听判定不够），query_plans 已由 "
     "`gate:it-plans`（scripts/query_plans_probe.py）接替。推翻条件：it 合成音复活、或这几个文件被接进任何登记表"),
    (r"^(vi|ru)/(gates|run_gates)\.py$",
     "登记表／跑闸入口本身：文本里写着各闸的 `--mutate` 命令，它们自己不是变异档"),
]


def _vr_gate_files():
    """vi/ru 登记表里**登了 mutate 的**闸文件 —— 由各自的 MUTLOG 管（它们自己查「文件有 --mutate 而登记为 None」）。"""
    out = set()
    for lang in ("vi", "ru"):
        for g in _load_gates(lang):
            if g.get("mutate"):
                out.add(g["file"])
    return out


def _load_gates(lang):
    import importlib.util
    sys.path.insert(0, str(ROOT / lang))
    try:
        spec = importlib.util.spec_from_file_location("_gates_" + lang, ROOT / lang / "gates.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.GATES
    finally:
        sys.path.remove(str(ROOT / lang))


_FILE_RE = re.compile(r"(\S+\.(?:py|tsx|ts))(?![\w.])")   # 🔴 tsx 写在 ts 前面：选择支 first-match


def _has_mutate(f):
    p = ROOT / f
    return p.exists() and "--mutate" in p.read_text(encoding="utf-8", errors="replace")


def registered():
    """→ (派生的档 [(名字, 文件, cwd, argv)], 登记命令自带 --mutate 的文件集合)。纯读登记表。"""
    scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    always, out, seen = set(), [], set()
    vr = _vr_gate_files()
    for gate, cmd in scripts.items():
        if not gate.startswith("gate:"):
            continue
        for part in cmd.split("&&"):
            for m in _FILE_RE.finditer(part):
                f = m.group(1)
                if "--mutate" in part:
                    always.add(f)
    for gate, cmd in scripts.items():
        if not gate.startswith("gate:") or "&&" in cmd:
            continue
        fs = [m.group(1) for m in _FILE_RE.finditer(cmd)]
        if len(fs) != 1:
            continue
        f = fs[0]
        if f in always or f in vr or not _has_mutate(f):
            continue
        out.append(("npm/" + gate[5:], f, ROOT, ["npm", "run", "-s", gate, "--", "--mutate"]))
        seen.add(f)
    for g in _load_gates("ko"):                      # ko 登记表没有 mutate 栏（B34 的起点）
        f = g["file"]
        if f in seen or f in always or not _has_mutate(f):
            continue
        out.append(("ko/" + Path(f).stem.replace("_", "-"), f, ROOT, [sys.executable, "-u", "-B", f, "--mutate"]))
        seen.add(f)
    return out, always


def suites():
    """→ {名字: (cwd, argv, [依赖文件])}。三个来源：tests/ 18 个、登记表派生、DIRECT。"""
    out = {}
    for n, lang, script in SUITES:
        dep = ["%s/%s" % (lang, script)]
        if n.endswith("/ledger") and lang in PLAN:
            dep.append("docs/%s.md" % PLAN[lang])
        out[n] = (ROOT / lang, [sys.executable, "-u", "-B", script, "--mutate"], dep)
    der, _always = registered()
    for n, f, cwd, argv in der:
        out[n] = (cwd, argv, [f])
    for n, f, argv in DIRECT:
        out[n] = (ROOT, [sys.executable, "-u", "-B"] + argv, [f])
    return out


def mutate_files():
    """全仓（git 跟踪＋未忽略）带 `--mutate` 字样的 py/ts/tsx。"""
    r = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "--", "*.py", "*.ts", "*.tsx"],
                       cwd=ROOT, capture_output=True, text=True, check=True)
    fs = [f for f in r.stdout.splitlines() if "node_modules" not in f]
    if len(fs) < 500:
        raise SystemExit("🔴 git ls-files 只列出 %d 个源文件 —— 扫描本身坏了，别当成「没有漏登」" % len(fs))
    return sorted(f for f in fs if _has_mutate(f))


def scan(files, suite, always, vr, exempt=EXEMPT):
    """纯函数。→ (归不进去的文件, 一个都没匹配到的豁免规则, 各类计数)。"""
    covered = {f for _c, _a, dep in suite.values() for f in dep}
    loose, used, kinds = [], set(), collections.Counter()
    for f in files:
        if f in covered:
            kinds["台账"] += 1
        elif f in always:
            kinds["登记命令自带 --mutate"] += 1
        elif f in vr:
            kinds["vi/ru MUTLOG"] += 1
        else:
            hit = next((i for i, (rx, _w) in enumerate(exempt) if re.search(rx, f)), None)
            if hit is None:
                loose.append(f)
            else:
                used.add(hit)
                kinds["豁免"] += 1
    stale = [exempt[i][0] for i in range(len(exempt)) if i not in used]
    return loose, stale, kinds


def deps(name):
    """→ 这个变异档依赖的文件（相对仓库根）。"""
    return suites()[name][2]


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
    cwd, argv, _dep = suites()[name]
    before = shas(name)                    # 开跑前取：跑的途中改了文件 ⇒ 下次照样欠
    # 🔴 B34（11-12）：放在短路径下。默认 TMPDIR（/var/folders/…/T/）＋本档目录＋展示层汇总自己再建一层，
    #    tsx 的 IPC socket 路径超过 macOS 的 104 字节上限 ⇒ `listen EINVAL`，展示层闸一启动就崩、记成红。
    tmp = tempfile.mkdtemp(prefix="mut-", dir="/tmp" if os.path.isdir("/tmp") else None)
    t0 = time.time()
    print("── %s：cd %s && %s" % (name, Path(cwd).relative_to(ROOT) if Path(cwd) != ROOT else ".",
                                  " ".join("python3" if a == sys.executable else a for a in argv)), flush=True)
    try:
        r = subprocess.run(argv, cwd=cwd,
                           # DISPLAY_GATES_RUNNING：账的闸正常跑那一遍里「展示层汇总闸欠一次」与变异无关 ——
                           # 不拆的话 ko 账的闸永远红（汇总闸又在报它欠变异），与 `run_display_gates.py` 同一个环
                           # MUTATION_STAMP_RUNNING（B34）：npm/display 的变异会把整套展示层汇总跑一遍，汇总里有
                           # `gate:mutation-debt` ⇒ 它看见「npm/display 欠着」而红 ⇒ 这一档永远跑不绿。正在跑的这一档不算欠。
                           env=dict(os.environ, TMPDIR=tmp, DISPLAY_GATES_RUNNING="1", MUTATION_STAMP_RUNNING=name))
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
    su = suites()
    now = {n: shas(n) for n in su}
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
    # 名单本身：每个档的文件都在盘上、且真有 --mutate 入口
    for n, (_c, _a, dep) in su.items():
        if not _has_mutate(dep[0]):
            dead += 1
            print("  🔴 名单里的 %s（%s）不存在或没有 --mutate 入口" % (n, dep[0]))
    # B34：scan() 的分支 —— 在**合成**的文件表上测（不寄托于仓库现状）
    _der, always = registered()
    vr = _vr_gate_files()
    fake_ex = [(r"^zz/fixes/", "测试用"), (r"^zz/never/", "过期规则")]
    files = ["zz/fixes/a.py", "zz/tests/new_gate.py", next(iter(su.values()))[2][0]]
    loose, stale, _k = scan(files, su, always, vr, fake_ex)
    for name, hit in (("新闸有 --mutate 而不在任何台账（B34 的形状）", loose == ["zz/tests/new_gate.py"]),
                      ("豁免规则一个文件都没匹配（过期）", stale == [r"^zz/never/"]),
                      ("（反控）台账里的、豁免的都不报", "zz/fixes/a.py" not in loose and len(loose) == 1)):
        dead += not hit
        print("  %s %s" % ("✅" if hit else "🔴 没逮到", name))
    # 真数据上的 B34 形状：ko 登记表里删掉外锚闸那一行 ⇒ 派生少一个档（数对不上）＋全仓扫描把它报成漏登
    global _load_gates
    real_load, target = _load_gates, "ko/pipeline/verify_layers_vs_dump.py"
    _load_gates = lambda lang: [g for g in real_load(lang) if not (lang == "ko" and g["file"] == target)]
    try:
        su2 = suites()
        _d2, al2 = registered()
        loose2, _s2, _k2 = scan(mutate_files(), su2, al2, _vr_gate_files())
    finally:
        _load_gates = real_load
    hit = len(su2) != EXPECT_SUITES and loose2 == [target]
    dead += not hit
    print("  %s %s（档 %d／声明 %d，漏登 %s）" % ("✅" if hit else "🔴 没逮到",
          "ko 登记表少登外锚闸 ⇒ 档数对不上＋扫描报漏登", len(su2), EXPECT_SUITES, loose2))
    print("  变异台账自检 %s" % ("通过" if not dead else "🔴 %d 处失败" % dead))
    return 1 if dead else 0


def main():
    a = sys.argv[1:]
    if "--mutate" in a:
        return selftest()
    su = suites()
    if "--run" in a:
        name = a[a.index("--run") + 1]
        if name not in su:
            raise SystemExit("🔴 没有这个变异档：%r；有：%s" % (name, "、".join(su)))
        return 1 if run(name) else 0
    owed = debt(load(), {n: shas(n) for n in su})
    running = os.environ.get("MUTATION_STAMP_RUNNING")
    if running and "--run-owed" not in a:
        owed = [(n, w) for n, w in owed if n != running]   # 自己正在跑的那一档（见 run() 的注释）
    if "--run-owed" in a:
        return 1 if sum(bool(run(n)) for n, _ in owed) else 0
    _der, always = registered()
    loose, stale, kinds = scan(mutate_files(), su, always, _vr_gate_files())
    bad = len(owed) + len(loose) + len(stale) + (len(su) != EXPECT_SUITES)
    print("■ 变异台账：%d 个变异档（声明 %d；vi/ru 由各自的 MUTLOG 管）" % (len(su), EXPECT_SUITES))
    if len(su) != EXPECT_SUITES:
        print("  🔴 档数 %d ≠ 声明 %d —— 登记表多/少了一道带变异的闸？改完核实再改 EXPECT_SUITES" % (len(su), EXPECT_SUITES))
    print("■ 全仓带 --mutate 的文件：%d 个 —— %s" % (sum(kinds.values()) + len(loose),
                                                 "／".join("%s %d" % kv for kv in sorted(kinds.items()))))
    for f in loose:
        print("  🔴 %s 有 --mutate 而不在任何台账、也没有豁免规则（B34）" % f)
    for rx in stale:
        print("  🔴 豁免规则 %r 一个文件都没匹配 —— 过期了就删" % rx)
    for n, why in owed:
        print("  🔴 %-22s 欠一次变异：%s" % (n, why))
    if owed:
        print("  ⇒ python3 scripts/mutation_stamp.py --run-owed（或 --run <名字>）")
    if not bad:
        print("  ✅ 每个变异档都在当前版本上跑绿过，没有漏登")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
