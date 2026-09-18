#!/usr/bin/env python3
"""把罗马字从**词形字面**里拆出来。2026-09-18。零模型调用。

═══ 症状 ═══
点开 `食べる` 活用表里的「可能敬体」，落到的页面词头印着：

    食べれます [taberemasu]

—— 方括号那截**长在 `dict.word` 里**，不是展示层拼的。于是：
  · 词头、兜底朗读药丸两处都把它当词形原样印出来；
  · 朗读按钮会把 "[taberemasu]" 一起念给 TTS；
  · `word_norm` 里也带着它 ⇒ 搜「食べれます」匹配不上这一行。

═══ 为什么会这样：源头就是这么给的 ═══
英文版维基词典的活用表单元格里，汉字形和转写写在**同一个字符串**里：

    {'form': '食べれます [taberemasu]', 'tags': ['polite', 'potential']}

阶段 2 的 `build_inflection_layer.py` 直接 `f["form"].strip()` 收下了。
⚠️ 这**不是「源头没给」也不是「我们没抽」** —— 是抽到了但没拆开
（`[[dont-say-source-lacks-what-we-skipped]]` 的第三种形态：抽到了，塞错了格子）。

日语版（`ja-edition`）的活用表不带转写 ⇒ 全库 3,721 个词形受影响，**全部来自英文版**：

    en-edition  189,103 行活用 ── 3,866 行的词形带 [罗马字]
    ja-edition  378,989 行活用 ──     0 行

═══ 处置 ═══
① 转写**不丢**，搬到 `inflection.romaji`（源头在那个单元格里给的事实）。
   ⚠️ 不放 `dict` 上：那张表的设计注释明写「读音不在这儿，在 entry」，
      因为一个词形可以有多个读音。活用形的转写是**这一行单元格**的属性，
      放 `inflection` 才对得上它的来处。
② `dict.word` / `word_norm` 洗成裸词形。洗完撞上已有词形的（152 个，多半是
   日语版已经收过的同一个形），把活用行**改挂到已有的那条**，删掉脏行。
③ 生成侧同步改（`build_inflection_layer.py`）——
   `[[replay-scripts-undo-fixes]]`：只修落库的行，下次重跑照样长回来。

    改名 3,279 条 ｜ 合并删除 442 条 ｜ 改挂活用行若干 ｜ 回填 romaji 3,866 行

跑（在仓库根）：
    python3 -u ja/fixes/fix_inflection_form_romaji.py
    python3 -u ja/fixes/fix_inflection_form_romaji.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import re
import sqlite3

import dbtool
import paths
from pipeline.build import norm_ja

# 🔴 判据写形状，不写「含有方括号」：要求**整串结尾是一个方括号组**，
#    且括号里不再有方括号。全库 3,721 条 100% 命中这个形状，0 条例外 ——
#    有例外就必须先看清楚再动，不许用宽判据一把捋（`[[criteria-narrower-than-you-think]]`）。
SHAPE = re.compile(r"^(.+?) \[([^\[\]]+)\]$")
# 转写栏里混进日文字符 ＝ 这一条不是「形 + 转写」，是别的东西。实测 0 条。
JA_SCRIPT = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")


def _assert_ja():
    assert paths.DB.name == "synapse-dict-ja.sqlite", "🔴 paths 不是 ja 的：%s" % paths.DB


def plan():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {w: i for i, w in con.execute("SELECT id, word FROM dict")}

    dirty = []            # (脏 id, 裸词形, 罗马字)
    weird = []
    for i, w in con.execute("SELECT id, word FROM dict WHERE word LIKE '% [%]'"):
        m = SHAPE.match(w)
        if not m or JA_SCRIPT.search(m.group(2)):
            weird.append(w)
            continue
        dirty.append((i, m.group(1), m.group(2)))

    # 裸词形 → 合并后的落点 id（`kept`），脏 id → 落点 id（`target`）
    kept = dict(have)              # 已有的干净词形先占位
    target = {}
    rename, drop = [], []          # rename: (id, 裸词形)；drop: 脏 id
    for _id, bare, _r in dirty:
        if bare in kept:           # 已有同形（库里本来就有 / 前一条脏行刚认领）⇒ 改挂过去
            target[_id] = kept[bare]
            drop.append(_id)
        else:
            rename.append((_id, bare))
            kept[bare] = _id
            target[_id] = _id

    # 受影响的活用行
    ids = tuple(t[0] for t in dirty)
    infl = con.execute(
        "SELECT id, word_id FROM inflection WHERE word_id IN (%s)"
        % ",".join("?" * len(ids)), ids).fetchall()
    romaji = {i: r for i, _b, r in ((d[0], d[1], d[2]) for d in dirty)}
    con.close()

    setrom = [(romaji[wid], rid) for rid, wid in infl]
    repoint = [(target[wid], rid) for rid, wid in infl if target[wid] != wid]
    return dirty, weird, rename, drop, setrom, repoint


def main():
    _assert_ja()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    dirty, weird, rename, drop, setrom, repoint = plan()
    print("   带 [罗马字] 的词形      %9s" % format(len(dirty), ","))
    print("   不合形状（必须为 0）    %9s %s" % (len(weird), weird[:5]))
    print("   改名（洗成裸词形）      %9s" % format(len(rename), ","))
    print("   合并删除（已有同形）    %9s" % format(len(drop), ","))
    print("   回填 romaji 的活用行    %9s" % format(len(setrom), ","))
    print("   改挂到已有词形的活用行  %9s" % format(len(repoint), ","))
    assert not weird, "🔴 有不合形状的行，先看清楚再动"

    dbtool.sample_check([(str(i), b, r) for i, b, r in dirty[::max(1, len(dirty) // 14)]],
                        12, ("dict.id", "洗后词形", "拆出的罗马字"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("ja-fix-inflection-form-romaji", expect={
            "__rows__": -len(drop), "inflection.romaji": len(setrom)}) as s:
        try:
            s.execute("ALTER TABLE inflection ADD COLUMN romaji TEXT")
        except sqlite3.OperationalError:
            pass
        s.executemany("UPDATE inflection SET romaji=? WHERE id=?", setrom)
        s.executemany("UPDATE inflection SET word_id=? WHERE id=?", repoint)
        s.executemany("UPDATE dict SET word=?, word_norm=? WHERE id=?",
                      [(b, norm_ja(b), i) for i, b in rename])
        s.executemany("DELETE FROM dict WHERE id=?", [(i,) for i in drop])

    # ── 回核：读取路径也查一遍（`[[it-regression-gate]]`：写入列与读取路径各查一次）──
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("dict 里不再有带方括号的词形",
         q("SELECT COUNT(*) FROM dict WHERE word LIKE '% [%]'") == 0),
        ("活用行没有指向不存在的词形",
         q("SELECT COUNT(*) FROM inflection i LEFT JOIN dict d ON d.id=i.word_id"
           " WHERE d.id IS NULL") == 0),
        ("word_norm 与 word 同口径",
         all(n == norm_ja(w) for w, n in
             con.execute("SELECT word, word_norm FROM dict WHERE id IN (%s)"
                         % ",".join(str(i) for i, _ in rename[:500])))),
        ("食べれます 能按裸词形查到",
         q("SELECT COUNT(*) FROM dict WHERE word='食べれます'") == 1),
        ("它的罗马字还在（没被丢掉）",
         q("SELECT COUNT(*) FROM inflection i JOIN dict d ON d.id=i.word_id"
           " WHERE d.word='食べれます' AND i.romaji='taberemasu'") >= 1),
    ]
    con.close()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    assert all(ok for _, ok in checks), "🔴 回核不过"


if __name__ == "__main__":
    main()
