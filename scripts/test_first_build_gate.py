#!/usr/bin/env python3
"""跨门闸：**开新语种第一天、库还不存在**时，`dbtool` 的三条路径必须走得通。2026-10-27（B6 ／ B22）。

═══ 为什么必须是闸 ═══
这三条路径只在「库不存在」时才走到 —— 十门的库都已建好，所以**它们从没被走过**，
而撞上的那天（开新语种），它们遮住的正是那天最需要看到的消息：
  F1（B6）  `python3 <lang>/dbtool.py` 库不存在时崩（ja `KeyError`，en/es/it/fr/pt/de `OperationalError`）；
  F2（B22①）建库那一步抛异常 ⇒ `bak.unlink()` 的 `AttributeError` **把真正的报错挤成上一条**（ja/ko/vi）；
  F3（B22②）建库那一步闸红 ⇒ `bak.exists()` 第一行就炸 ⇒ **`bad` 清单一条都印不出来**（ja/ko/vi）。
2026-10-27 逐门复现过才修（ru 作对照，它在开门当天就修了）。

═══ 判据 ═══
  · 十门：F1 退出码 0，且**没有顺手建出一个空库文件**。
  · 支持从零建库的门（有 `_ALLOW_EMPTY_PREFIX`）：F2 原样抛出调用方的异常；F3 `SystemExit(1)` 且印出「本步是建库」。
  · 其余六门：`session()` 遇到不存在的库必须**拒绝开工**——调用方的代码一行都没执行、也没建出空库文件。
    ⚠️ 判据问的是这个性质，不是异常类型：我第一版写死 `FileNotFoundError`（猜它在备份那步炸），
       实测是更早的 `snapshot()` 只读打开时 `OperationalError` —— 照样是对的行为。
探针跑在子进程里、`DB` 指向临时目录；真库只**只读**取一次 DDL（F3 要让写后快照走得到）。

用法：
    python3 -u scripts/test_first_build_gate.py            # 红了退出码非 0
    python3 -u scripts/test_first_build_gate.py --mutate   # 把修复在**内存里**改回旧写法，必须打红
"""
import argparse
import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ["en", "es", "it", "fr", "pt", "de", "ja", "ko", "vi", "ru"]

# 变异：把修复改回旧写法（在内存里替换源码，不碰仓库文件 ⇒ 不受 pyc 缓存影响）
INJECT = {
    "B6": ("    if not DB.exists():\n        print(", "    if False:\n        print("),
    "B22a": ("        if bak is None:\n            print(\"\\n🔴 写库异常",
             "        if False:\n            print(\"\\n🔴 写库异常"),
    "B22b": ("            if bak is None:\n                print(\"   ⚠️ 本步是建库",
             "            if False:\n                print(\"   ⚠️ 本步是建库"),
}


def _load(lang_dir, inject, as_main=False):
    src = (lang_dir / "dbtool.py").read_text(encoding="utf-8")
    if inject:
        a, b = INJECT[inject]
        if a not in src:
            raise SystemExit("PRECOND %s 的锚在 %s/dbtool.py 里找不到" % (inject, lang_dir.name))
        src = src.replace(a, b, 1)
    name = "__main__" if as_main else "dbtool"
    spec = importlib.util.spec_from_loader(name, loader=None, origin=str(lang_dir / "dbtool.py"))
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(lang_dir / "dbtool.py")
    return mod, compile(src, mod.__file__, "exec")


def probe(lang, case, inject):
    """子进程里跑。印一行 `RESULT …`。"""
    lang_dir = ROOT / lang
    sys.path.insert(0, str(lang_dir))
    import paths
    real_db = paths.DB
    paths.DB = Path(tempfile.mkdtemp()) / "nope.sqlite"
    out = io.StringIO()
    if case == "main":
        mod, code = _load(lang_dir, inject, as_main=True)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                exec(code, mod.__dict__)
            rc = 0
        except SystemExit as e:
            rc = e.code
        except BaseException as e:            # noqa: BLE001
            print("RESULT crash %s" % type(e).__name__)
            return
        print("RESULT exit=%r created=%s" % (rc, paths.DB.exists()))
        return
    mod, code = _load(lang_dir, inject)
    exec(code, mod.__dict__)
    sys.modules["dbtool"] = mod
    has_build = hasattr(mod, "_ALLOW_EMPTY_PREFIX")
    tag = (mod._ALLOW_EMPTY_PREFIX if has_build else "") + "first-build-probe"
    import sqlite3
    ro = sqlite3.connect("file:%s?mode=ro" % real_db, uri=True)
    ddl = [r[0] for r in ro.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                                    "AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")]
    ro.close()
    ran = []
    kw = {"invalidates": []} if "invalidates" in mod.session.__code__.co_varnames else {}
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            if case == "exc":
                with mod.session(tag, expect={}, **kw):
                    ran.append(1)
                    raise RuntimeError("调用方的真正报错")
            else:
                with mod.session(tag, expect={"__rows__": 5}, **kw) as c:
                    ran.append(1)
                    for d in ddl:
                        c.execute(d)
        print("RESULT no-exception")
    except RuntimeError as e:
        print("RESULT orig" if "调用方的真正报错" in str(e) else "RESULT other-runtime")
    except SystemExit as e:
        hint = "本步是建库" in out.getvalue()
        print("RESULT sysexit=%r hint=%s" % (e.code, hint))
    except BaseException as e:                # noqa: BLE001
        if not ran and not paths.DB.exists():
            print("RESULT refused")              # 拒绝开工：调用方一行没跑、没建出空库
        else:
            print("RESULT crash %s ran=%s created=%s" % (type(e).__name__, bool(ran), paths.DB.exists()))


def run_probe(lang, case, inject=None):
    cmd = [sys.executable, "-B", str(Path(__file__)), "--probe", lang, case] + ([inject] if inject else [])
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    for line in (p.stdout + p.stderr).splitlines():
        if line.startswith("RESULT ") or line.startswith("PRECOND "):
            return line
    return "RESULT nothing（%s）" % (p.stderr.strip().splitlines()[-1:] or ["?"])[0]


def has_build(lang):
    return "_ALLOW_EMPTY_PREFIX" in (ROOT / lang / "dbtool.py").read_text(encoding="utf-8")


def judge(lang, case, got):
    if case == "main":
        return got == "RESULT exit=0 created=False"
    if not has_build(lang):
        return got == "RESULT refused"
    return got == ("RESULT orig" if case == "exc" else "RESULT sysexit=1 hint=True")


CASES = [("main", "F1 dbtool 入口"), ("exc", "F2 建库抛异常"), ("red", "F3 建库闸红")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", nargs="+")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    if a.probe:
        probe(a.probe[0], a.probe[1], a.probe[2] if len(a.probe) > 2 else None)
        return
    print("■ 开新语种第一天：库不存在时 dbtool 的三条路径（B6 ／ B22）")
    red = 0
    for lang in LANGS:
        cells = []
        for case, name in CASES:
            got = run_probe(lang, case)
            ok = judge(lang, case, got)
            red += not ok
            cells.append("%s %s" % ("✅" if ok else "🔴", name) + ("" if ok else "（%s）" % got[7:]))
        print("  %-3s %s  %s" % (lang, "建库门" if has_build(lang) else "老六门", "  ".join(cells)))
    print(("🔴 %d 处红" % red) if red else "✅ 全绿")
    if not a.mutate:
        sys.exit(1 if red else 0)

    print("\n■ 变异（源码在内存里改回旧写法）")
    muts = [("ja", "main", "B6", "ja 入口又直接 snapshot()"),
            ("de", "main", "B6", "de 入口又直接 snapshot()"),
            ("ko", "exc", "B22a", "ko 异常路径判空被拿掉"),
            ("vi", "red", "B22b", "vi 闸红路径判空被拿掉")]
    dead = 0
    for lang, case, inj, name in muts:
        got = run_probe(lang, case, inj)
        if got.startswith("PRECOND"):
            raise SystemExit("🔴 变异前提不成立：" + got)   # 锚漂了当场炸，不报「没逮到」
        hit = not judge(lang, case, got)
        dead += not hit
        print("  %s %-28s → %s" % ("✅" if hit else "🔴 没逮到", name, got[7:]))
    print("  变异 %d/%d" % (len(muts) - dead, len(muts)))
    sys.exit(1 if dead or red else 0)


if __name__ == "__main__":
    main()
