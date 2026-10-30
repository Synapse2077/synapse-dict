#!/usr/bin/env python3
"""展示层闸的**汇总入口**（B14 ／ B15）。2026-10-27。

═══ 为什么要有它 ═══
展示层闸比的是「源码 vs 库」或「源码 vs 源码」，**改代码才让它过期，而改代码不经过 `dbtool.session`**
⇒ 写库自动跑的那套机制标不脏它们。实证两次：
  · `css-audit` 自 09-25 起红着，没人看见（B14 原文）；
  · `gate:etym-display`／`gate:layout` 自 vi 上线（10-06）起红在登记表自检上，**三周**没人看见（2026-10-27 做 B18 时）。
另有六道契约闸（colloc/de/en/es/fr/pt）连 npm 入口都没有（B15）—— 2026-10-27 逐道跑过：
**五道绿、en 红的就是账上的 B13**，没有藏着的新红。

═══ 判据 ═══
  · 名册 G0：`apps/web/src/contract-check-*.tsx` 每个文件都必须在 GATES 里（新闸有文件没入口＝没有闸，B15 的病）；
    GATES 里每个 npm 入口都必须在 package.json 里。
  · 每道闸退出码 0 ⇒ 绿。
  · 退出码非 0 ⇒ 只有当红的**恰好是** DEBT 登记的那几条、且条数逐字相等，才算「欠账照旧」；
    多一条、少一条、数字变了 —— 都红。🔴 **一条永远红的闸信号量是零，而且会掩盖真红**
    （`[[permanently-red-gate-masks-real-reds]]`），所以欠账锁**数字**不锁名字（`[[fix-regression-and-gate]]`）。
  · 登记了欠账的闸跑绿了也红 —— 提醒把欠账划掉，别让账虚高。

用法：
    npm run gate:display              # 全跑（并发），红了退出码非 0
    npm run gate:display -- --mutate  # 变异：在**捕获的输出**上注入，不重跑闸

跑完把源码 sha 记进 `display_stamp`；vi/ru 的 V9、ko 的 P12 查它 ⇒ 改了代码没重跑，账的闸一直红（B14）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import display_stamp

ROOT = Path(__file__).resolve().parent.parent

# npm 入口 ／ 对应文件（名册自检用）
GATES = {
    "gate:ja-display": "apps/web/src/contract-check-ja.tsx",
    "gate:ko-display": "apps/web/src/contract-check-ko.tsx",
    "gate:vi-display": "apps/web/src/contract-check-vi.tsx",
    "gate:ru-display": "apps/web/src/contract-check-ru.tsx",
    "gate:de-display": "apps/web/src/contract-check-de.tsx",
    "gate:en-display": "apps/web/src/contract-check-en.tsx",
    "gate:es-display": "apps/web/src/contract-check-es.tsx",
    "gate:fr-display": "apps/web/src/contract-check-fr.tsx",
    "gate:pt-display": "apps/web/src/contract-check-pt.tsx",
    "gate:colloc-display": "apps/web/src/contract-check-colloc.tsx",
    "gate:audio-labels": "apps/web/src/contract-check-audio.tsx",
    "gate:etym-display": "apps/web/src/contract-check-etym.tsx",
    "gate:layout": "apps/web/src/contract-check-layout.tsx",
    "gate:css-audit": "apps/web/src/css-audit.ts",
    "gate:dispatch-audit": "apps/web/src/dispatch-audit.ts",
    "gate:redundant-related": "scripts/test_redundant_related_gate.py",
    "gate:audio-dup": "scripts/test_audio_dup_gate.py",
    "gate:fr-tags": "scripts/contract/fr_tag_tables.ts",
    "gate:tags": "scripts/contract/tag_coverage_all.ts",
    "gate:en-chips": "scripts/contract/en_sense_chips.ts",
    "gate:service-api": "scripts/contract/service_api.ts",
    "gate:first-build": "scripts/test_first_build_gate.py",   # B6/B22：库不存在时 dbtool 的三条路径
    "gate:consult": "scripts/consult.py",                       # B8/B9：咨询工具的离线自检
    "gate:backlog": "scripts/test_backlog_gate.py",             # B5：顶层账本与各门计划表对得上
    "gate:backup-policy": "scripts/test_backup_policy_gate.py",  # 完结预算生效＋十门删除行为测试（2026-10-28 前没人跑）
    # B11：es/fr/it 没有各自的 `gates.py`，查询计划闸与页面计时闸挂在这里（ko/vi/ru 的在各门名单里）
    "gate:es-plans": "scripts/query_plans_probe.py",
    "gate:fr-plans": "scripts/query_plans_probe.py",
    "gate:it-plans": "scripts/query_plans_probe.py",
    "gate:page-timing": "scripts/contract/page_timing.ts",
    "gate:overflow": "apps/web/src/contract-check-overflow.tsx",   # B26：手机宽度下整页不许横向溢出（真用 Chrome 排版）
    # 🔴 八门「账的闸」（2026-10-27）。封版／做完的门**没有任何东西再跑它们**，当天撞见两次：
    #    pt 的 C56 锚在一个 09-26 就改名的变量上、红了一个月；pt 的 `--mutate` 入口写死 `== 6`
    #    而变异是 8 条 ⇒ 全过也永远退 1。挂进这里 ⇒ 改了代码或计划表，台账一过期它们就得重跑。
    #    不是 npm 入口，直接跑文件（名册只查 `gate:*`）。
    **{"ledger:%s" % l: "%s/tests/test_plan_ledger.py" % l
       for l in ("de", "ja", "en", "fr", "pt", "ko", "vi", "ru")},
    # ko 写库闸门自己的变异闸：只登记在账的闸的交付物里、不在 `ko/gates.py`，
    # M7 因此自 09-28 红到 10-27 没人看见（K36 那一条）。
    "selftest:ko-dbtool": "ko/tests/test_dbtool_gate.py",
}

# 有意不进汇总的 `gate:*`：各门自己的闸，由 `<lang>/gates.py` 跑（查询计划闸要先有本门 ANALYZE）。
# 🔴 package.json 新加的 `gate:*` 两边都不在 ⇒ G0 红（新闸没归类＝没人跑，B15 的病）。
OWN_LANG = frozenset({"gate:ko-labels", "gate:ko-plans", "gate:vi-plans", "gate:ru-plans", "gate:display"})

# 已登记、仍开着的红：闸 → {断言编号: 条数}。🔴 锚在常量上，不从现状推。
DEBT = {
    # （2026-10-29 清空）原有 `"gate:en-display": {"F4": 43}` —— B13 查明那 43 条是**闸自己看不见**学科标签的假红，
    #  判据修好后 F4 转绿，本闸当场报「登记了欠账而它跑绿了」⇒ 划掉。
}

RED_LINE = re.compile(r"^\s*🔴\s+(?:🔴\s+)?([A-Z]+\d+[a-z]?)\b.*?([\d,]+)\s*条\s*$")


def roster():
    bad = []
    have = {str(p.relative_to(ROOT)) for p in (ROOT / "apps/web/src").glob("contract-check-*.tsx")}
    scripts = json.loads((ROOT / "package.json").read_text())["scripts"]
    # 🔴 B23 那一类（2026-10-30）：下面三条比较，任何一边为空都恒真 —— 目录挪了 glob 一个都扫不到、
    #    入口前缀改了一个 `gate:` 都没有 ⇒ 「有文件不在名单里」「有入口不在名单里」永远报不出来，汇总闸照样全绿。
    #    另：名单里登记的文件自己存不存在，原来没人查（改名之后 `npm run` 才报错，而那只在真跑到它时）。
    if not have:
        bad.append("G0 判据坏了：apps/web/src 下一个 contract-check-*.tsx 都没扫到")
    if not any(k.startswith("gate:") for k in scripts):
        bad.append("G0 判据坏了：package.json 里一个 gate: 入口都没有")
    for g, f in GATES.items():
        if not (ROOT / f).exists():
            bad.append("G0 汇总名单里的 %s 指向不存在的文件 %s" % (g, f))
    for f in sorted(have - set(GATES.values())):
        bad.append("G0 %s 有文件而不在汇总名单里" % f)
    for g in GATES:
        if g.startswith("gate:") and g not in scripts:
            bad.append("G0 package.json 没有入口 %s" % g)
    for g in sorted(k for k in scripts if k.startswith("gate:")):
        if g not in GATES and g not in OWN_LANG:
            bad.append("G0 %s 既不在汇总名单也不在 OWN_LANG" % g)
    return bad


def run(g):
    import time
    t0 = time.time()
    code, out = _run(g)
    return code, out, time.time() - t0


def _run(g):
    if not g.startswith("gate:"):
        # ko/vi/ru 的账的闸自己会查展示层台账，而本闸跑的途中台账必然是过期的
        # ⇒ 不拆这个环它们永远红、台账永远记红。用环境变量告诉它们「是汇总闸在跑你」。
        env = dict(os.environ, DISPLAY_GATES_RUNNING="1")
        p = subprocess.run([sys.executable, "-u", GATES[g]], cwd=ROOT, capture_output=True,
                           text=True, env=env)
        return p.returncode, p.stdout + p.stderr
    p = subprocess.run(["npm", "run", "-s", g], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def judge(g, code, out):
    """→ (绿不绿, 说明)。"""
    debt = DEBT.get(g)
    if code == 0:
        return (False, "登记了欠账 %s 而它跑绿了 —— 划掉 DEBT" % debt) if debt else (True, "")
    if not debt:
        return False, "退出码 %d" % code
    got = {}
    for line in out.splitlines():
        m = RED_LINE.match(line)
        if m:
            got[m.group(1)] = int(m.group(2).replace(",", ""))
    summary = re.search(r"🔴\s*(\d+)\s*条红", out)
    if got == debt and summary and int(summary.group(1)) == len(debt):
        return True, "欠账照旧 %s" % debt
    return False, "红的是 %s，登记的是 %s" % (got or "（认不出）", debt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    print("■ 跨门展示层／契约闸汇总（%d 道）" % len(GATES))
    files = display_stamp.current()        # 🔴 开跑之前取：跑的途中改了文件 ⇒ 下次照样欠
    ros = roster()
    for b in ros:
        print("  🔴 " + b)
    # 🔴 带**计时判据**的闸最后单独跑（2026-10-27）：de 的账的闸 P3 要求单条判据不超过 10 个全列扫，
    #    和 30 道闸一起并发时 I/O 互相抢，C38 从单跑的 2.0 秒涨到 30.4 秒、判红 ——
    #    判据没病，是测量环境坏了。⚠️ 不去调宽 de 的预算（它的注释写明「不要靠调高倍数让它变绿」）。
    #    清单靠 grep 计时判据得来（2026-10-27 只有 de 一处）；再有别的就加进来。
    TIMED = {"ledger:de", "gate:page-timing"}   # 页面计时闸：fr 那页并发下 17→29 ms 的抖动实测过
    rest = [g for g in GATES if g not in TIMED]
    with ThreadPoolExecutor(8) as ex:
        res = dict(zip(rest, ex.map(run, rest)))
    for g in GATES:
        if g in TIMED:
            res[g] = run(g)
    res = {g: res[g] for g in GATES}
    red = len(ros)
    for g, (code, out, dt) in res.items():
        ok, why = judge(g, code, out)
        red += not ok
        print("  %s %-24s %4.0fs  %s" % ("✅" if ok else "🔴", g, dt, why))
        if not ok:
            for line in out.strip().splitlines()[-12:]:
                print("       │ " + line)
    print(("🔴 %d 道红" % red) if red else "✅ 全绿")
    display_stamp.record(files, red == 0)  # 红了也记：账的闸要说「上次跑是红的」，不是「没跑过」
    if not a.mutate:
        sys.exit(1 if red else 0)

    print("\n■ 变异（在捕获的输出上注入）")
    # 🔴 2026-10-29 改：原来拿 **en 那条真欠账**当前提（`en 闸不是 F4 欠账就 raise`）—— 欠账一结清，
    #    整套欠账判定的变异就跑不起来（B20 那个形状：变异把前提寄托在现状上，现状一推进就失效）。
    #    ⇒ 前提**自带**：临时登记一笔假欠账、手造它的输出，只测 `judge` 的判定逻辑。
    FAKE = "gate:__debt_probe__"
    DEBT[FAKE] = {"F4": 43}
    fake_out = "   🔴 🔴 F4 假欠账  43 条\n🔴 1 条红"
    cases = [
        ("一道没登记欠账的闸红了", "gate:fr-display", 1, "🔴 1 条红", False),
        ("欠账涨了一条", FAKE, 1, fake_out.replace(" 43 条", " 44 条"), False),
        ("欠账旁边冒出第二条红", FAKE, 1,
         fake_out.replace("🔴 1 条红", "   🔴 F9 新的缺陷  3 条\n🔴 2 条红"), False),
        ("登记了欠账的闸跑绿了", FAKE, 0, "✅ 全部通过", False),
        ("（反控）欠账照旧", FAKE, 1, fake_out, True),
    ]
    dead = 0
    for name, g, code, out, want in cases:
        ok, why = judge(g, code, out)
        hit = ok == want
        dead += not hit
        print("  %s %-24s → %s" % ("✅" if hit else "🔴 没逮到", name, why or "（绿）"))
    # 名册：假装多了一个没进名单的闸文件
    GATES_BAK = dict(GATES)
    GATES.pop("gate:colloc-display")
    hit = any("contract-check-colloc" in b for b in roster())
    GATES.clear(); GATES.update(GATES_BAK)
    dead += not hit
    print("  %s %-24s" % ("✅" if hit else "🔴 没逮到", "有文件而不在名单里"))
    GATES.pop("gate:fr-tags")
    hit2 = any("gate:fr-tags" in b and "OWN_LANG" in b for b in roster())
    GATES.clear(); GATES.update(GATES_BAK)
    dead += not hit2
    print("  %s %-24s" % ("✅" if hit2 else "🔴 没逮到", "npm 入口没归类"))
    GATES["gate:__ghost__"] = "apps/web/src/contract-check-__ghost__.tsx"
    hit3 = any("指向不存在的文件" in b for b in roster())
    GATES.clear(); GATES.update(GATES_BAK)
    dead += not hit3
    print("  %s %-24s" % ("✅" if hit3 else "🔴 没逮到", "名单登记的文件不存在"))
    DEBT.pop(FAKE)
    print("  变异 %d/%d" % (len(cases) + 3 - dead, len(cases) + 3))
    sys.exit(1 if dead or red else 0)


if __name__ == "__main__":
    main()
