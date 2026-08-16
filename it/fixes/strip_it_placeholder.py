#!/usr/bin/env python3
"""清掉意语版的「缺定义」占位符。2026-08-13，阶段 3b。

═══ 是什么 ═══
意语版维基词典允许编者留占位符：

    definizione mancante; se vuoi, aggiungila tu      （"缺定义，欢迎补充"）

wiktextract 把它当成 gloss 抓下来了，我们又把它提升成了出版层的意语释义 ——
**4,031 条**，其中 **1,920 条**所在义项没有任何其它释义，用户看到的整条就是这句话。

═══ 怎么发现的 ═══
翻译负控 30 条里有 2 条模型输出空串，我以为是模型的问题，回查原文才发现
**模型是对的**：它按 prompt 规则五拒绝为占位符编造释义。负控实际 30/30。
⚠️ 教训：负控报错时先回源看输入，别默认是模型的锅。

═══ 两种形态 ═══
① 纯占位符                          → 出版层删掉这条意语释义
② 有真内容 + 占位符尾巴（`(Alisma lanceolatum), alisma, definizione mancante; …`）
                                    → 只截掉尾巴，保留真内容
删完之后**一条释义都不剩**的义项 → `sense.hidden=1`（不删行，证据层永不动）

用法（在 it/ 目录下）：
    python3 fixes/strip_it_placeholder.py            # 干跑
    python3 fixes/strip_it_placeholder.py --apply
    python3 fixes/strip_it_placeholder.py --verify
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 占位符及其常见变体。判据只认这一族固定文本，不做模糊匹配。
PLACEHOLDER = re.compile(
    r"\s*,?\s*definizione\s+mancante\s*;?\s*(se\s+vuoi\s*,?\s*aggiungila\s+tu)?\s*\.?\s*$",
    re.IGNORECASE)
PURE = re.compile(r"^\s*(definizione\s+mancante.*|mancante)\s*$", re.IGNORECASE)
# ⚠️ 占位符也会出现在**句子中间**（全库 1 例：`piante della famiglia delle Labiate;
#    definizione mancante; se vuoi, aggiungila tu; la sua classificazione…`）。
#    只锚句尾的正则漏了它 —— 闸报出来的。
MIDDLE = re.compile(
    r";?\s*definizione\s+mancante\s*;?\s*(se\s+vuoi\s*,?\s*aggiungila\s+tu)?\s*;?",
    re.IGNORECASE)


def bears_placeholder(text):
    """带占位符的文本**整条都不该进出版层**。提升脚本共用这一把尺。

    ⚠️ 2026-08-14：`promote_it_gloss` 重跑时只滤了 `PURE`（整条都是占位符），
       漏掉**夹在句中**的那 5 条，闸报红逮到。清洗后剩下的是 `(di frutto)`
       这种域标签 —— 源头明说"定义缺失"，剩的那点不是定义，留着反而更难看。
       ⇒ 规则从「清洗后保留」收紧成「带占位符就整条不提升」，只影响 5 条，
          而且**一条规则比两条简单**（`PITFALLS` A4：判据别越改越碎）。
    """
    return bool(PURE.match(text) or MIDDLE.search(text) or PLACEHOLDER.search(text))


# `(di animali)` —— 去掉括号内容后什么都不剩 ⇒ 只有域标签，没有定义。
# 和占位符是同一族：源头没写定义，剪掉占位符后剩了个标签。全库实测 14 条。
PAREN = re.compile(r"\([^()]*\)")


def only_label(text):
    return not PAREN.sub("", text).strip(" ,;.·")


def clean(text):
    """剪掉占位符，保留真内容。🔴 全项目**唯一**的清洗函数。

    （`promote_it_gloss.gate1` 里原来抄了一份一模一样的局部 `clean`，已改为引用这里。）
    """
    out = MIDDLE.sub("; ", PLACEHOLDER.sub("", text)).strip()
    return re.sub(r"\s*;\s*;", ";", out).strip().strip(",;").strip()


def not_a_definition(text):
    """🔴 「什么不算释义」的**唯一**判据 = 剪掉占位符后什么实质内容都不剩。

    ⚠️ 走到这一版踩了两次：
      · 第一版只认 `PURE`（整条是占位符）⇒ 漏掉夹在句中的，5 条灌进出版层
      · 第二版改成「带占位符就整条不算」⇒ **矫枉过正**，把 `lanzafina`
        「(Alisma lanceolatum), alisma, definizione mancante…」这种
        **有真内容、只是拖了个占位符尾巴**的也判成非释义（闸报红 2 条逮到）
      ⇒ 正确的是**先剪后判**，也正是 `strip_it_placeholder` 本来的做法。

        (di frutto) definizione mancante…        → 剪后 `(di frutto)`            → 不是释义
        (Alisma lanceolatum), alisma, defini…    → 剪后 `(Alisma…), alisma`      → 是释义
        (urbanistica)                            → 剪后不变                      → 不是释义
    """
    return only_label(clean(text))


def plan(con):
    strip, drop = [], []
    stat = Counter()
    for sid, text in con.execute(
            "SELECT sense_id, text FROM sense_gloss WHERE lang='it' AND kind='definition'"):
        if PURE.match(text):
            drop.append(sid)
            stat["① 纯占位符 → 删这条意语释义"] += 1
            continue
        new = MIDDLE.sub("; ", PLACEHOLDER.sub("", text)).strip()
        new = re.sub(r"\s*;\s*;", ";", new).strip().strip(",;").strip()
        if new != text:
            if not new:
                drop.append(sid)
                stat["① 截完为空 → 删"] += 1
            else:
                strip.append((new, sid))
                stat["② 截掉占位符尾巴，保留真内容"] += 1
    # 删完之后一条释义都不剩的义项
    dropset = set(drop)
    hide = []
    if dropset:
        marks = ",".join("?" * len(dropset))
        for (sid,) in con.execute(
                "SELECT s.id FROM sense s WHERE s.id IN (%s) AND NOT EXISTS("
                "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang<>'it') "
                "AND COALESCE(s.hidden,0)=0" % marks, list(dropset)):
            hide.append(sid)
    stat["③ 删完无任何释义 → sense.hidden=1"] = len(hide)
    return strip, drop, hide, stat


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("🔴 出版层不再有占位符释义",
         q("SELECT count(*) FROM sense_gloss WHERE lang='it' AND kind='definition' "
           "AND (text LIKE '%definizione mancante%' OR text LIKE '%aggiungila tu%')"), 0),
        ("🔴 没有可见义项是「一条释义都没有」的",
         q("SELECT count(*) FROM sense s WHERE COALESCE(s.hidden,0)=0 AND NOT EXISTS("
           "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id)"), 0),
        ("🔴 证据层原样保留（占位符还在，随时可翻案）",
         q("SELECT count(*) FROM sense_src WHERE src='it-edition' "
           "AND text LIKE '%definizione mancante%'"), 9418),
        ("每个词形的 rank 仍连续无空洞",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1

    strip, drop, hide, stat = plan(ro)
    for k, v in stat.most_common():
        print("   %-38s %8s" % (k, f"{v:,}"))
    for new, sid in strip[:4]:
        print("      截后样例 sense#%-8s %s" % (sid, new[:56]))
    ro.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("strip-it-placeholder",
                        expect={"#sense_gloss": -len(drop)}) as s:
        s.executemany("UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='it' "
                      "AND kind='definition'", strip)
        s.executemany("DELETE FROM sense_gloss WHERE sense_id=? AND lang='it' "
                      "AND kind='definition'", [(x,) for x in drop])
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?", [(x,) for x in hide])
        # 🔴 出版层删掉了，证据层的"已裁决"必须一并撤回 —— 否则「已裁决 == 出版层」
        #    这条不变量就永久对不上（阶段 3 复跑旧闸时报出 4,014 条）。
        #    撤回 = `sense_id` 置回 NULL，证据文本一个字节不动，随时可重新裁决。
        s.execute("UPDATE sense_src SET sense_id=NULL WHERE src='it-edition' "
                  "AND sense_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM sense_gloss g "
                  "WHERE g.sense_id=sense_src.sense_id AND g.lang='it' AND g.kind='definition')")
    print("\n■ 截 %s 条 / 删 %s 条 / 隐藏 %s 条义项"
          % (f"{len(strip):,}", f"{len(drop):,}", f"{len(hide):,}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
