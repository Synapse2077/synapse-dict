#!/usr/bin/env python3
"""展示层汇总闸的**源码 sha 台账** —— B14「改代码让闸过期，没有任何机制」的触发点。2026-10-27。

═══ 判据 ═══
`npm run gate:display` 跑完，把它**读的那批源码**逐文件的 sha256 记下来（连同绿没绿）。
账的闸（vi/ru 的 V9、ko 的 P12）调 `reasons()`：
    · 从没跑过            ⇒ 红
    · 上次跑是红的        ⇒ 红
    · 有文件改过／新增／删掉 ⇒ 红，并点名是哪几个文件
锚的是**内容**不是时间：改回去 sha 就对上（照搬 vi `gates.MUTLOG` 的形状）。

═══ 为什么挂在账的闸上、不挂在 `gates.self_check()` 上 ═══
`run_gates.py` 在名单自检不过时**整个退出** ⇒ 挂在那里，改一行 CSS 就拦住三门所有数据闸。
这里要的是「欠着就一直有人说话」，不是「欠着就什么都别干」。

═══ 有意偏宽 ═══
SOURCES 取的是 `apps/web/src` ／ `packages/*/src` ／ 闸自己的脚本整片，不按每道闸细分 ——
宽的代价是改了不相干的文件也要多跑一次（两三分钟）；窄的代价是漏跑（`css-audit` 红了一个月）。
⚠️ **它看不见库的变化**：跨门闸（B17 冗余关系、B12 录音重复）读十门的库，而写库那一侧
   只有 ko/vi/ru 有欠账机制。那是另一笔账，别以为这里管了。

用法：
    python3 scripts/display_stamp.py            # 打当前状态，过期退出码 1
    python3 scripts/display_stamp.py --mutate   # 自检 reasons() 的四个分支
"""
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAMP = ROOT / "data" / "db" / ".display-gates-stamp.json"   # 跟库走，不进 git

SOURCES = [
    ("apps/web/src", ("*.ts", "*.tsx", "*.css")),
    ("packages/dict-core/src", ("*.ts",)),
    ("packages/dict-labels", ("*.ts", "*.json")),
    ("scripts/contract", ("*.ts",)),
]
SOURCE_FILES = ["package.json", "scripts/run_display_gates.py", "scripts/display_stamp.py", "scripts/redundant_related.py",
                "scripts/test_redundant_related_gate.py", "scripts/test_audio_dup_gate.py",
                "scripts/commons_filename.py", "scripts/test_first_build_gate.py", "scripts/consult.py", "scripts/test_backlog_gate.py", "scripts/test_backup_policy_gate.py", "scripts/query_plans_probe.py", "scripts/analyze_db.py",
                "docs/BACKLOG.md", "docs/JA_PLAN.md", "docs/KO_PLAN.md", "docs/VI_PLAN.md", "docs/RU_PLAN.md",
                "docs/DE_PLAN.md", "docs/PT_PLAN.md", "docs/FR_PLAN.md", "docs/EN_PLAN.md"]


def current():
    """→ {相对路径: sha16}。"""
    paths = set()
    for d, pats in SOURCES:
        for pat in pats:
            paths |= {p for p in (ROOT / d).rglob(pat)
                      if "node_modules" not in p.parts and "dist" not in p.parts}
    paths |= {ROOT / f for f in SOURCE_FILES if (ROOT / f).exists()}
    paths |= set(ROOT.glob("*/dbtool.py"))      # `gate:first-build` 读的（十门的写库闸门）
    paths |= set(ROOT.glob("*/tests/test_plan_ledger.py"))   # 八门账的闸（也在汇总里跑）
    paths |= {ROOT / "ko/tests/test_dbtool_gate.py", ROOT / "ko/gates.py"}
    paths |= set(ROOT.glob("*/tests/test_prune_backups.py")) | {ROOT / "es/tests/test_backup_prune.py"}   # gate:backup-policy 跑的
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            for p in sorted(paths)}


def load():
    if not STAMP.exists():
        return None
    try:
        return json.loads(STAMP.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit("🔴 展示层台账读不动：%s（%s）—— 别当成「没欠」" % (STAMP, e))


def record(files, ok):
    """`run_display_gates.py` 跑完调。files 要在**开跑之前**取（跑的途中改了文件 ⇒ 下次照样欠）。"""
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.write_text(json.dumps({"ok": bool(ok), "files": files,
                                 "when": datetime.datetime.now().isoformat(timespec="seconds")},
                                ensure_ascii=False, indent=1), encoding="utf-8")


def reasons(stamp, now):
    """纯函数。→ 欠账说明列表（空 ＝ 当前这版源码上跑绿过）。"""
    fix = "⇒ `npm run gate:display`"
    if stamp is None:
        return ["展示层汇总闸从没在这套台账下跑过 %s" % fix]
    if not stamp.get("ok"):
        return ["展示层汇总闸上次跑是**红的**（%s）%s" % (stamp.get("when", "?"), fix)]
    old = stamp.get("files", {})
    changed = sorted(k for k in now if k in old and old[k] != now[k])
    added = sorted(set(now) - set(old))
    gone = sorted(set(old) - set(now))
    if not (changed or added or gone):
        return []
    parts = []
    for tag, xs in (("改过", changed), ("新增", added), ("删掉", gone)):
        if xs:
            parts.append("%s %d 个（%s%s）" % (tag, len(xs), "、".join(xs[:4]),
                                             " …" if len(xs) > 4 else ""))
    return ["展示层汇总闸跑绿之后源码变了：%s（上次 %s）%s"
            % ("；".join(parts), stamp.get("when", "?"), fix)]


def check():
    """账的闸调这个。汇总闸正在跑你时返回空 —— 那时台账必然过期，不拆这个环就永远红。"""
    if os.environ.get("DISPLAY_GATES_RUNNING"):
        return []
    return reasons(load(), current())


if __name__ == "__main__":
    now = current()
    if "--mutate" in sys.argv:
        k = next(iter(now))
        green = {"ok": True, "files": dict(now), "when": "t"}
        cases = [
            ("从没跑过", None, now, True),
            ("上次跑红", dict(green, ok=False), now, True),
            ("改了一个文件", green, dict(now, **{k: "0" * 16}), True),
            ("新增一个文件", green, dict(now, **{"apps/web/src/__new__.tsx": "x"}), True),
            ("删掉一个文件", green, {x: v for x, v in now.items() if x != k}, True),
            ("（反控）没变", green, now, False),
        ]
        dead = 0
        for name, st, cur, want in cases:
            got = bool(reasons(st, cur))
            dead += got != want
            print("  %s %s" % ("✅" if got == want else "🔴 没逮到", name))
        print("  变异 %d/%d" % (len(cases) - dead, len(cases)))
        sys.exit(1 if dead else 0)
    bad = reasons(load(), now)
    print("■ 展示层台账：%d 个源码文件" % len(now))
    for b in bad:
        print("  🔴 " + b)
    print("  ✅ 当前源码上跑绿过" if not bad else "")
    sys.exit(1 if bad else 0)
