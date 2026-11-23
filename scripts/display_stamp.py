#!/usr/bin/env python3
"""展示层汇总闸的**源码 sha 台账** —— B14「改代码让闸过期，没有任何机制」的触发点。2026-10-27。

═══ 判据（2026-11-23 起：累计欠账，到阈值才红）═══
`npm run gate:display` 跑完，把它**读的那批源码**逐文件的 sha256 记下来（连同绿没绿）。
账的闸（vi/ru 的 V9、ko 的 P12）调 `check()`：
    · 从没跑过              ⇒ 红
    · 上次跑是红的          ⇒ 红
    · 新出现的变化累加进 `pending`（`seen` 快照保证同一批只算一次）
        · `pending < LIMIT` ⇒ **只提示、不红**（「已欠 N/50 次改动」）
        · `pending ≥ LIMIT` ⇒ 红，逼你跑
    · 跑绿后 `pending` 归零
阈值默认 **50**，`DISPLAY_STAMP_LIMIT` 可覆盖。
🔴 为什么改：用户 2026-11-23「汇总闸每次跑太费劲，代码改动频繁，可以每改动 100 次跑一次」。
   阈值定为 50（100 太远、30 太近）。**代价**：阈值内不红 ⇒ 回归可能积累一批才发现，定位要二分。
   ⚠️ 这条不是把闸拆掉 —— 到 50 会自己红；`rare-han` 则单独移出汇总（只在库变时需要）。
锚的是**内容**不是时间：改回去 sha 就对上（照搬 vi `gates.MUTLOG` 的形状）。

═══ 为什么挂在账的闸上、不挂在 `gates.self_check()` 上 ═══
`run_gates.py` 在名单自检不过时**整个退出** ⇒ 挂在那里，改一行 CSS 就拦住三门所有数据闸。
这里要的是「欠着就一直有人说话」，不是「欠着就什么都别干」。

═══ 有意偏宽 ═══
SOURCES 取的是 `apps/web/src` ／ `packages/*/src` ／ 闸自己的脚本整片，不按每道闸细分 ——
宽的代价是改了不相干的文件也要多跑一次（两三分钟）；窄的代价是漏跑（`css-audit` 红了一个月）。
═══ 库也进台账（B14②，2026-11-01）═══
汇总闸里一大半读库（各门契约闸按库渲染、罕用字闸扫库、追踪清单闸对库）——原来台账只记源码，
**写库不会让它过期**。现在十门库的主文件记成 `db:<门>` ＝「字节数:修改时间」，与源码同一套比法。
不算 sha：库 0.2–5 GB，每次写库都整份读一遍不值；读库不会改主文件的修改时间（实测汇总闸跑一整轮，
十个主文件的 mtime 一个没动；`-shm` 会动，所以不记它）。
写库那一侧：十门 `dbtool.session` 写完调 `notice()` —— **只报不拦**（与账的闸同一个理由）。

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
                "scripts/commons_filename.py", "scripts/test_first_build_gate.py", "scripts/consult.py", "scripts/zh_t2s.py", "scripts/test_track_gate.py", "scripts/rare_han_font.py", "scripts/schema_drift.py", "scripts/small_undo.py", "scripts/ingest_etymology.py", "scripts/test_small_undo.py", "scripts/test_schema_drift_gate.py", "apps/web/public/fonts/rare-han/manifest.json", "scripts/test_backlog_gate.py", "scripts/mutation_stamp.py", "scripts/batch_audit.py", "scripts/intake_layers.py",
                *["%s/pipeline/ds_batch.py" % l for l in ("it", "ja", "ko", "pt", "ru", "vi")], "scripts/test_backup_policy_gate.py", "scripts/query_plans_probe.py", "scripts/analyze_db.py",
                # B7：追踪清单住在各门 dbtool 里 —— 改了清单，`gate:track` 必须重跑
                *["%s/dbtool.py" % l for l in ("en", "es", "it", "fr", "pt", "de", "ja", "ko", "vi", "ru")],
                # B24：建表声明住在各门建表脚本里 —— 改了声明，`gate:schema-drift` 必须重跑
                *["%s/pipeline/build_v3_schema.py" % l for l in ("en", "fr", "pt", "de", "ja", "ko", "vi", "ru")],
                "it/pipeline/build_v2_schema.py",
                "docs/BACKLOG.md", "docs/JA_PLAN.md", "docs/KO_PLAN.md", "docs/VI_PLAN.md", "docs/RU_PLAN.md",
                "docs/DE_PLAN.md", "docs/PT_PLAN.md", "docs/FR_PLAN.md", "docs/EN_PLAN.md"]


DB_LANGS = ("en", "es", "it", "fr", "pt", "de", "ja", "ko", "vi", "ru")


def db_state():
    """→ {"db:<门>": "字节数:mtime_ns"}。库还没建的门不出现（第一次建好 ⇒ 记成「新增」⇒ 欠一次）。"""
    import importlib.util
    out = {}
    for l in DB_LANGS:
        spec = importlib.util.spec_from_file_location("_paths_" + l, ROOT / l / "paths.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        db = Path(m.DB)
        if db.exists():
            st = db.stat()
            out["db:" + l] = "%d:%d" % (st.st_size, st.st_mtime_ns)
    return out


def current():
    """→ {相对路径: sha16} ∪ {"db:<门>": 字节数:mtime}。"""
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
    files = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()[:16]
             for p in sorted(paths)}
    files.update(db_state())
    return files


def load():
    if not STAMP.exists():
        return None
    try:
        return json.loads(STAMP.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit("🔴 展示层台账读不动：%s（%s）—— 别当成「没欠」" % (STAMP, e))


LIMIT = int(os.environ.get("DISPLAY_STAMP_LIMIT", "50"))


def record(files, ok):
    """`run_display_gates.py` 跑完调。files 要在**开跑之前**取（跑的途中改了文件 ⇒ 下次照样欠）。"""
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.write_text(json.dumps({"ok": bool(ok), "files": files, "seen": files, "pending": 0,
                                 "when": datetime.datetime.now().isoformat(timespec="seconds")},
                                ensure_ascii=False, indent=1), encoding="utf-8")


def _diff(old, now):
    """→ 变化的键列表（改过／新增／删掉）。纯函数，自检直接测它。"""
    return ([k for k in now if k in old and old[k] != now[k]]
            + sorted(set(now) - set(old))
            + sorted(set(old) - set(now)))


def _save(stamp):
    tmp = STAMP.with_name(STAMP.name + ".tmp")
    tmp.write_text(json.dumps(stamp, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STAMP)


def check():
    """账的闸调这个。**只报不拦**：汇总闸正在跑你时返回空。

    ═══ 2026-11-23：从「改了就红」改成「累计欠账，到 `LIMIT` 才红」 ═══
    用户：「汇总闸每次跑太费劲，代码改动频繁，可以每改动 100 次跑一次」。
    ⇒ 每次检查把**新出现的变化数**累加进 `pending`（`seen` 快照保证同一批只算一次）；
    `pending < LIMIT` 时只打一行提示、**不红**；到 `LIMIT` 才红，逼你跑。
    跑绿后 `record()` 把 `pending` 归零。阈值默认 50（`DISPLAY_STAMP_LIMIT` 可覆盖）。
    ⚠️ 代价写清楚：阈值内不红＝回归可能积累一批才发现，定位要二分。
    """
    if os.environ.get("DISPLAY_GATES_RUNNING"):
        return []
    stamp = load()
    now = current()
    if stamp is None:
        return ["展示层汇总闸从没在这套台账下跑过 ⇒ `npm run gate:display`"]
    if not stamp.get("ok"):
        return ["展示层汇总闸上次跑是**红的**（%s）⇒ `npm run gate:display`" % stamp.get("when", "?")]
    seen = stamp.get("seen") or stamp.get("files", {})
    pending = int(stamp.get("pending", 0))
    d = _diff(seen, now)
    if d:
        pending += len(d)
        stamp["pending"] = pending
        stamp["seen"] = now
        _save(stamp)
        if any(k.startswith("db:") for k in d):
            print("⚠️ 库变了 ⇒ 记得单独跑 `npm run gate:rare-han`（罕用字切片可能要重建）")
        if pending < LIMIT:
            print("⚠️ 展示层闸已欠 %d/%d 次改动（到 %d 才红）—— 方便时跑 `npm run gate:display`"
                  % (pending, LIMIT, LIMIT))
    if pending >= LIMIT:
        return ["展示层汇总闸已欠 **%d/%d** 次改动，必须重跑 ⇒ `npm run gate:display`"
                % (pending, LIMIT)]
    return []


def notice():
    """十门 `dbtool.session` 写完调。**只报不拦**：台账读不动也只说一句，不许把写库后的收尾打断。"""
    try:
        bad = check()
    except BaseException as e:            # load() 读不动台账时是 SystemExit
        print("⚠️ 展示层台账查不了（%s）—— 这本身要查" % e)
        return
    for b in bad:
        print("■ 🔴 " + b)


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        # `mutation_stamp` 跑本档时会设 `DISPLAY_GATES_RUNNING=1`（那是给汇总闸内部用的），
        # `check()` 一开头见它就直接返回空 ⇒ 「欠 50/50 红」永远测不到。
        # 自检测的是计数机制本身，先清掉这个短路。
        os.environ.pop("DISPLAY_GATES_RUNNING", None)
        fails = []

        def ck(name, cond):
            if not cond:
                fails.append(name)
            print("  %s %s" % ("✅" if cond else "🔴 没逮到", name))

        # ① 纯函数
        ck("改一个文件", _diff({"a": "1"}, {"a": "2"}) == ["a"])
        ck("新增一个文件", _diff({}, {"a": "1"}) == ["a"])
        ck("删掉一个文件", _diff({"a": "1"}, {}) == ["a"])
        ck("（反控）没变", _diff({"a": "1"}, {"a": "1"}) == [])
        # ② 机制：临时台账 + 伪造 current（不碰真源码/真库）
        real_stamp, real_current = STAMP, current
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            STAMP = Path(td) / "s.json"
            state = {"a": "1"}
            current = lambda: dict(state)                      # noqa: E731
            record(state, True)
            ck("跑绿后不欠", check() == [])
            state["a"] = "2"
            ck("欠 1/%d 不红" % LIMIT, check() == [])
            for i in range(LIMIT - 2):
                state["a"] = str(100 + i)
                check()
            state["a"] = "final"
            ck("欠 %d/%d 红" % (LIMIT, LIMIT), bool(check()))
            record(state, True)
            ck("重新跑绿后归零", check() == [])
        STAMP, current = real_stamp, real_current
        print("  变异 %d/%d" % (9 - len(fails), 9))
        sys.exit(1 if fails else 0)
    now = current()
    bad = check()
    stamp = load()
    pend = int((stamp or {}).get("pending", 0))
    print("■ 展示层台账：%d 个源码文件（欠 %d/%d 次改动）" % (len(now), pend, LIMIT))
    for b in bad:
        print("  🔴 " + b)
    print("  ✅ 当前源码上跑绿过" if not bad else "")
    sys.exit(1 if bad else 0)
