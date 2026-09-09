#!/usr/bin/env python3
"""书证的**出处**从 `text` 拆进 `ref`。2026-09-08，阶段 5e 落库后。

═══ 怎么发现的 ═══
5e 落库后抽读「没拿到中文的 2,367 条」，里面混着：

    1722, Daniel Defoe, A Journal of the Plague Year, London: E. Nutt et al., p. 86,
    Some Houses were […] entirely（真正的引文在换行之后）

也就是说 `example.text` 里**出处和正文是粘着的**，而 `ref` 列 **99.8% 是空的**。
后果有两层：

  ① **展示**：读者看到的英文带着一整行书目，中文却只有正文 —— 两边对不上。
  ② **翻译**：prompt 规则 5 写着「文献出处不出现在译文里」，模型守住了 94.4%，
     但仍有 **431 条**把书目也译成了中文
     （「1791年，《蜜蜂》杂志，第4卷，…第v页，」）。
     🔴 **根子不在模型，在我们递给它的 payload** —— 规则写得再对，
        结构上把两样东西粘在一起递过去，就是在鼓励它犯这个错
        （`[[criteria-from-meaning-not-form]]`：规则写在 prompt 里、结构却在鼓励相反的事＝等于没写）。

═══ 🔴 判据被自己的"负控"打回一次 ═══
第一版写 `^(年份)[,:]`，命中 8,205 条，我还专门打了一批「以年份开头但后面不是逗号」
当负控，以为那是真句子。**打出来一读，那 2,253 条也全是出处**
（`1973 December, "Books Noted"…`／`1858-1860, George Rawlinson…`／`2015 April 23,…`）。
⇒ 判据**比它要描述的东西窄**：修 8,205 条、留下 2,253 条一模一样的没修。
   放宽成「四位年份开头」后 10,458 条，随机读 15 条全是干净的出处/正文二分。
⚠️ 这次的方向与我惯犯的相反（平时是判据太宽），**两个方向都要查**。

═══ 分两种处理 ═══
  · 有换行 → 首行进 `ref`，正文留在 `text`
  · 无换行 → **整条就是出处，没有正文** ⇒ `hidden=1`（同 `hide_non_examples.py`）

    cd en && python3 -u fixes/split_quote_ref.py
    cd en && python3 -u fixes/split_quote_ref.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import json
import re
import sqlite3

import dbtool
import paths

OUT = paths.WORK / "examples"

# 🔴 `c. 1981,` / `ca. 1928,` / `circa 1850,` 也是出处 —— 2026-09-09 由 D8 的残留
#    逮出来（`c. 1650s, John Cleveland…` 整行躺在 `text` 里当例句）。
#    第一版只认「行首四位年份」，又是**判据比它要描述的东西窄**。
_MON = ("January|February|March|April|May|June|July|August|September|October"
        "|November|December")
# 🔴 三次放宽，每次都是「判据比它要描述的东西窄」被残留逮出来：
#    ① 只认行首四位年份 → 漏 `c. 1650s,`／`circa 1850,`
#    ② 补了 c./ca./circa → 仍漏 `April 14, 1684, John Evelyn, …`（月份开头）
#    ⇒ 允许可选的「月 日,」前缀。**每放宽一次都要回源读样本**，别放成误伤。
YEAR = re.compile(
    r"^(?:c(?:a)?\.\s*|circa\s+)?(?:(?:%s)\s+\d{1,2},?\s*)?(1[4-9]\d\d|20[0-2]\d)\b"
    % _MON)
ANYYEAR = re.compile(r"(1[4-9]\d\d|20[0-2]\d)")


def ref_leaked(txt, ref, zh):
    """出处漏进译文了吗。**判据只写这一份**，回归闸 `import` 它。

    判据：译文里出现了**只在 `ref` 里有**的年份。
    🔴 「只在 ref 里有」必须把**正文的缩写年份**算进来 —— 否则 21 条全是误报：
         正文 `1991-99`   → 中文「1991至1999年」
         正文 `Jan 76`    → 中文「1976年1月」
         正文 `(4/21/99)` → 中文「1999年4月21日」
       模型把缩写展开成四位，是**对的**；判据看不见 `99` 就判它抄了出处。
    ⇒ 四位形式和后两位形式都算「正文里有」。
    ⚠️ 后两位会放宽一点（`90` 这种两位数在正文里不算罕见），
       但**一个每次都误报 21 条的闸没人会看**，宁可略宽（`[[fix-regression-and-gate]]` 坑①）。
    """
    ys = set(ANYYEAR.findall(ref or ""))
    if not ys or not zh:
        return False
    return (any(y in zh for y in ys)
            and not any(y in txt or y[2:] in txt for y in ys))


def collect(con):
    """→ (要拆的, 要藏的, 中文漏了出处的)

    🔴🔴 **`example` 上有 `UNIQUE(word, text)`** —— 削掉出处之后，
       「同一段引文的另一个版本」就会与库里**已经拆好的那份**撞车（实测 2 条：
       `sentence` 下 Chesnutt 那段、`autantonym` 下的词典释义）。
       第一次 `--run` 直接抛 `IntegrityError`，dbtool 回滚干净。
    ⇒ 撞车的那份是**冗余重复**（干净版已在库里），藏掉而不是拆。
      ⚠️ 判据不能是"拆完撞了就跳过" —— 跳过会把一条明知是重复的脏行留在页面上。
    """
    split, hide, leak = [], [], []
    seen = {}
    for eid, w, txt in con.execute("SELECT id, word, text FROM example"):
        seen.setdefault((w, txt), []).append(eid)
    for eid, w, txt, ref, zh in con.execute(
            "SELECT e.id, e.word, e.text, e.ref, g.text FROM example e "
            "LEFT JOIN example_gloss g ON g.example_id = e.id WHERE e.hidden = 0"):
        if not YEAR.match(txt.strip()):
            continue
        if "\n" not in txt:
            hide.append(eid)
            continue
        if ref:                      # 源头已经拆好的，不动
            continue
        head, body = txt.split("\n", 1)
        body = body.strip()
        if not body:                 # 换行后没东西 ＝ 还是纯出处
            hide.append(eid)
            continue
        if seen.get((w, body), [eid]) != [eid]:
            hide.append(eid)          # 干净版已在库里，这份是冗余重复
            continue
        split.append((eid, head.strip(), body))
        # 🔴 中文里出现了**只在出处里有**的年份 ⇒ 模型把书目也译了，这条要重翻
        if ref_leaked(body, head, zh):
            leak.append(eid)
    # 🔴🔴 **同一个判据要覆盖全部带 `ref` 的行，不只是本脚本拆出来的那批。**
    #    第一版只查自己拆的 9,689 条，漏掉源头本来就给了 `ref` 的 63 万条 ——
    #    那是「判据只作用在我经手的那部分」，与缺陷本身无关。
    #    实测漏掉 466 条，形状一模一样（「1791年，《蜜蜂》杂志，第4卷，…第v页，」）。
    got = set(leak)
    for eid, ref, txt, zh in con.execute(
            "SELECT e.id, e.ref, e.text, g.text FROM example e "
            "JOIN example_gloss g ON g.example_id = e.id "
            "WHERE e.hidden = 0 AND e.ref IS NOT NULL AND e.ref <> ''"):
        if eid in got:
            continue
        if ref_leaked(txt, ref, zh):
            leak.append(eid)
    return split, hide, leak


def drop_answers(ids):
    """把这些 id 从答案文件里删掉，让下一次 `--run` **重新问**。

    🔴🔴 **清库不等于清答案文件。**第一轮我只删了 `example_gloss` 的行，
       而 `zh.jsonl` 里那 466 条旧答案还在 ⇒ `slot_translate.done_keys` 判定
       「已翻」直接跳过，`--apply` 又把带书目的旧译文原样写回去 ——
       **闸连着两轮报同一个 466，数字一动不动**，我差点以为是判据误报。
    ⭐ 答案文件既是那 246 元买到的资产、**也是续跑账本**：
       要让某一条重新被问，必须从账本里划掉它。
    ⚠️ 先备份再改（`.bak`），并把删掉的行留一份存档 —— 花过钱的东西不许无痕消失。
    """
    if not ids:
        return 0
    src = OUT / "zh.jsonl"
    if not src.exists():
        return 0
    import shutil
    shutil.copy2(src, src.with_suffix(".jsonl.bak"))
    ids = set(ids)
    keep, drop = [], []
    for ln in src.open(encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            keep.append(ln)
            continue
        (drop if o.get("id") in ids else keep).append(ln)
    with (OUT / "zh.dropped.jsonl").open("a", encoding="utf-8") as f:
        f.writelines(drop)
    tmp = src.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(keep), "utf-8")
    tmp.replace(src)
    return len(drop)


def gates(con, before, n_split, n_hide, n_leak):
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        # 🔴 第一版判据写的是「可见例句里不再有以年份开头的」，报红 16 条。
        #    打出来一读，**16 条全是真内容**：引文本身就是编年条目
        #    （`1417. Henry Rishworth formerly held two oxgangs…`），
        #    而 `ref` 里已经有真正的书目（1909 年那本）。
        #    ⇒ 「以年份开头」≠「出处粘在正文上」，判据比它要描述的东西**宽**。
        #    真正的不变量是「**该拆而没拆**」：以年份开头 + 含换行 + `ref` 还空着。
        ("该拆而没拆的一条不剩",
         len([1 for (t, r) in con.execute(
             "SELECT text, ref FROM example WHERE hidden=0")
             if YEAR.match(t.strip()) and "\n" in t and not r]), 0),
        ("拆出来的 ref 条数对得上",
         q("SELECT COUNT(*) FROM example WHERE ref IS NOT NULL AND ref <> ''"),
         before["ref"] + n_split),
        ("🔴 总行数没变（拆不删）", q("SELECT COUNT(*) FROM example"), before["tot"]),
        ("藏起来的正好是这么多",
         q("SELECT COUNT(*) FROM example WHERE hidden=1"), before["hidden"] + n_hide),
        ("🔴 藏起来的例句没有留下中文",
         q("SELECT COUNT(*) FROM example e JOIN example_gloss g ON g.example_id=e.id "
           "WHERE e.hidden=1"), 0),
        ("漏了出处的译文已清掉，等重翻",
         q("SELECT COUNT(*) FROM example_gloss"),
         before["gloss"] - n_leak - before["gloss_on_hide"]),
        # 🔴 负控：正文一个字都不许丢 —— 拆的是头，不是身
        ("🔴 负控 正文没被削短",
         q("SELECT COUNT(*) FROM example WHERE hidden=0 AND TRIM(text)=''"), 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-32s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    split, hide, leak = collect(con)
    q = con.execute
    before = {
        "tot": q("SELECT COUNT(*) FROM example").fetchone()[0],
        "hidden": q("SELECT COUNT(*) FROM example WHERE hidden=1").fetchone()[0],
        "ref": q("SELECT COUNT(*) FROM example WHERE ref IS NOT NULL "
                 "AND ref <> ''").fetchone()[0],
        "gloss": q("SELECT COUNT(*) FROM example_gloss").fetchone()[0],
    }
    hset = set(hide)
    before["gloss_on_hide"] = sum(
        1 for (i,) in q("SELECT example_id FROM example_gloss") if i in hset)
    print("═══ 书证出处拆分 ═══")
    print("   拆（出处→ref，正文留 text）  %8s" % format(len(split), ","))
    print("   藏（整条就是出处，无正文）    %8s" % format(len(hide), ","))
    print("   🔴 中文漏了出处，清掉重翻     %8s" % format(len(leak), ","))
    print("\n   样本：")
    for eid, head, body in split[:4]:
        print("      出处→ref: %s" % head[:82])
        print("      正文→text: %s" % body[:82])
    con.close()
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0
    with dbtool.session(
            "keep-v3-split-quote-ref",
            expect={"#example_gloss": -(len(leak) + before["gloss_on_hide"])}) as s:
        s.executemany("UPDATE example SET ref=?, text=? WHERE id=?",
                      [(h, b, i) for i, h, b in split])
        s.executemany("UPDATE example SET hidden=1 WHERE id=?", [(i,) for i in hide])
        s.executemany("DELETE FROM example_gloss WHERE example_id=?",
                      [(i,) for i in leak + hide])
    n_drop = drop_answers(leak)   # 见 drop_answers 的注释：不划掉账本就不会重问
    print("   从答案文件划掉 %s 行（存档在 zh.dropped.jsonl，原文件已 .bak）"
          % format(n_drop, ","))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = gates(con, before, len(split), len(hide), len(leak))
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
