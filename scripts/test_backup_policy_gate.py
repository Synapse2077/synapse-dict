#!/usr/bin/env python3
"""跨语种闸：**计划表宣布的「完结」，必须真的作用到备份预算上**。

═══ 为什么需要这道闸 ═══
2026-09-14 查备份占用时翻出来的：`FR_PLAN.md` 里明写着 `✅ fr 完结（2026-08-28）`，
**而 fr 的 `dbtool.py` 根本没有读这个标记的代码** —— 它照着「未完结」的 8 GB 预算跑，
那行 ✅ 等于白写。

🔴 **六门各有一个 `tests/test_prune_backups.py`，当时全是绿的。**
   缺陷不在任何一门内部，而在门与门之间：en 想明白了「完结就把楼梯收干净」并实现了，
   其余五门照旧。每门自己的闸永远不会红。
   ⇒ 这类缺陷只能由**跨语种的闸**逮，这就是本文件存在的唯一理由
   （`decision-not-propagated-across-editions`、`lesson-must-become-mechanism`）。

═══ 判据写「目的」不写「代理」 ═══
不查「有没有 `_language_is_done` 这个函数」（那是形式代理，改个名就失效）。
查的是**落点**：这门语言实际会用哪个预算，和计划表宣布的状态对不对得上。

用法：
    python3 scripts/test_backup_policy_gate.py          # 红了退出码非 0
"""
import importlib
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ("en", "es", "it", "fr", "pt", "de", "ja", "ko", "vi", "ru")


def _discover():
    """仓库里**实际存在**的语种目录（有自己 `dbtool.py` 的就算一门）。

    🔴🔴 **这条自检是给下一门语言准备的。** 2026-09-20 加 ja 时发现：
       ja 做完了整整一轮，而这张 `LANGS` 名单里**根本没有它** ——
       闸打印「六门全部一致 ✅」，而第七门从来没被检查过。
       这与欠账 12 记的是同一个形状（`render-dump` 的 `View` 分支／`css-audit` 的 `VIEWS`／
       `contract-check-layout` 的 `LANGS`，**日语三张登记表一张都没登记**，而三道闸全绿）：
       **闸查的是「登记了的那几门对不对」，没有一条查「是不是所有门都登记了」。**
    ⇒ 名单从磁盘推，对不上就红。加语种时**不需要记得改这里**，忘了它会自己响。
    """
    return {d.name for d in ROOT.iterdir()
            if d.is_dir() and len(d.name) == 2 and (d / "dbtool.py").exists()}
DONE_RX = re.compile(r"^#+\s*✅\s*(\w+)\s*完结", re.M)


def plan_doc_for(lang):
    """计划表的约定位置。es 至今没有（本身就是一条发现）。"""
    p = ROOT / "docs" / f"{lang.upper()}_PLAN.md"
    return p if p.exists() else None


def load_dbtool(lang):
    """按语种 import 它自己的 dbtool。六份是**各自独立**的文件，不能共用一份。"""
    d = ROOT / lang
    if not (d / "dbtool.py").exists():
        return None
    saved = list(sys.path)
    for m in ("dbtool", "paths"):
        sys.modules.pop(m, None)
    sys.path.insert(0, str(d))
    try:
        return importlib.import_module("dbtool")
    finally:
        sys.path[:] = saved


def probe(lang):
    """→ (计划表宣布完结?, dbtool 实际按完结走?, 生效预算, 备注)"""
    doc = plan_doc_for(lang)
    declared = False
    if doc:
        m = DONE_RX.search(doc.read_text("utf-8"))
        if m:
            # 🔴 顺带查语言代码：`_language_is_done` 的正则是硬编码语种的，
            #    复制到别的语种时忘了改，会静默永远匹配不上。
            declared = (m.group(1) == lang)
            if m.group(1) != lang:
                return declared, None, None, f"计划表里写的是「{m.group(1)} 完结」，不是 {lang}"
    mod = load_dbtool(lang)
    if mod is None:
        return declared, None, None, "没有 dbtool.py"
    fn = getattr(mod, "_language_is_done", None)
    if fn is None:
        return declared, False, getattr(mod, "MAX_BACKUP_BYTES", None), "dbtool 没有完结判定机制"
    effective = bool(fn())
    budget = (getattr(mod, "DONE_BACKUP_BYTES", None) if effective
              else getattr(mod, "MAX_BACKUP_BYTES", None))
    return declared, effective, budget, ""


def mechanism_probe(lang, mod):
    """**正反控制**：拿一份临时计划表正着问一遍 `_language_is_done()`。→ 红的原因或 None。

    ═══ 🔴🔴 为什么非加这一条不可（2026-10-02 vi 实证）═══
    `vi/dbtool.py` 是从 ko 拷的，`PLAN_DOC` 改成了 `VI_PLAN.md`、注释也改成了
    「`# ✅ vi 完结`」，**而正则里还写着 `ko`** —— 读 vi 的计划表却找「ko 完结」，
    永远匹配不上。哪天 vi 标完结，预算不会收紧：**fr 那行 ✅ 白写半个月的原形**，
    而这道闸就是为那件事建的。

    ⚠️ 本文件此前**逮不到它**，有两层：
      ① `LANGS` 名单里没有 vi ⇒ 结构性失明（`_discover` 已经在治这一层，它响了）；
      ② **即使登记了也逮不到** —— 计划表没标完结 ⇒ declared=False、
         `_language_is_done()` 也返回 False ⇒ `declared == effective` **判绿**。
         两个 False 相等，不代表机制是通的，只代表**两边都没有信息**
         （`[[expectation-must-be-declared]]`：期望值要独立声明，不能从现状推）。
         这个洞只会在「有人真去标完结」那天现形 —— 而那天正是它最该已经被修好的一天。
    ⇒ 不等那天：**主动给它一份标了完结的临时计划表，看它认不认。**
      正控制（标了 ⇒ 必须 True）＋ 反控制（没标 ⇒ 必须 False，否则它根本没在读文件）。
    ⚠️ 临时文件是 `tempfile`，**真计划表一个字节都不动**。
    """
    fn = getattr(mod, "_language_is_done", None)
    if fn is None:
        return None                      # 没有机制，由 probe() 那边报
    if not hasattr(mod, "PLAN_DOC"):
        # ⚠️ **登记在册的豁免，不是静默跳过**：本门的完结判定不经 `PLAN_DOC`，
        #    探不到。main() 会把它大声印出来（而不是当成通过）。
        return "SKIP:完结判定不经 `PLAN_DOC`，正反控制探不到"
    saved = mod.PLAN_DOC
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / f"{lang.upper()}_PLAN.md"
            mod.PLAN_DOC = p
            p.write_text(f"# ✅ {lang} 完结（正控制，临时文件）\n", "utf-8")
            if not fn():
                return (f"标了 `# ✅ {lang} 完结` 而 `_language_is_done()` 仍是 False —— "
                        "**判定机制对本语种永远不会生效**"
                        "（正则里的语种代码多半是从别门拷过来没改）")
            p.write_text("# 这份没有完结标记（反控制）\n", "utf-8")
            if fn():
                return ("计划表里没有完结标记而 `_language_is_done()` 返回 True —— "
                        "它没在读计划表，那个 ✅ 不是判据")
    finally:
        mod.PLAN_DOC = saved
    return None


def main():
    print("■ 跨语种闸：计划表宣布的完结，是否真的作用到备份预算上\n")
    print(f"  {'语种':<5}{'计划表':>8}{'实际生效':>10}{'生效预算':>10}   备注")
    print("  " + "─" * 62)
    bad = []
    found = _discover()
    missing, stale = sorted(found - set(LANGS)), sorted(set(LANGS) - found)
    if missing or stale:
        print("  🔴 LANGS 名单与磁盘对不上：漏登记 %s ｜名单里有但磁盘没有 %s"
              % (missing or "无", stale or "无"))
        print("     ⇒ 新语种没进名单时，这道闸会对它**结构性失明**（见 `_discover` 的注释）")
        return 1

    skipped = []
    for lang in LANGS:
        declared, effective, budget, note = probe(lang)
        b = f"{budget / 1024 ** 3:.1f}G" if budget else "-"
        e = {True: "完结", False: "未完结", None: "?"}[effective]
        ok = (effective is not None) and (declared == effective)
        # 🔴 **两边都是 False 不算一致** ⇒ 正反控制必须也过（见 `mechanism_probe`）
        if ok:
            why = mechanism_probe(lang, load_dbtool(lang))
            if why and why.startswith("SKIP:"):
                skipped.append((lang, why[5:]))
            elif why:
                ok, note = False, (note + "；" if note else "") + why
        if not ok:
            bad.append((lang, declared, effective, note))
        print(f"  {lang:<5}{'完结' if declared else '未完结':>8}{e:>10}{b:>10}   "
              f"{'✅' if ok else '❌'} {note}")
    print()
    # ⚠️ **登记在册的豁免要大声印**，不许静默跳过（否则它和「通过」长得一样）
    for lang, why in skipped:
        print("  ⚠️ %s：%s" % (lang, why))
    if not bad:
        print("■ ✅ %d 门全部一致（含正反控制：拿临时计划表正着问过 `_language_is_done()`）"
              % len(LANGS))
        return 0
    for lang, declared, effective, note in bad:
        if declared and not effective:
            print(f"■ ❌ {lang}：计划表宣布完结，**但 dbtool 按未完结的宽预算在跑** —— "
                  f"那行 ✅ 不起作用（{note or '缺完结判定机制'}）")
        elif effective and not declared:
            print(f"■ ❌ {lang}：dbtool 判为完结，但计划表没有 ✅ 标记 —— 预算被意外收紧")
        else:
            print(f"■ ❌ {lang}：{note}")
    print("\n   修法：给该语种的 dbtool 补 `_language_is_done()` + `DONE_BACKUP_BYTES`，"
          "\n   正则里的语种代码要跟着改（硬编码的，复制过去不改会静默失效）。"
          "\n   🔴 改完**必须先 `prune_backups(dry=True)` 跑一遍**再真删。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
