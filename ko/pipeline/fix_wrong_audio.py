#!/usr/bin/env python3
"""删掉**不是这个词的录音**的录音行。ko，2026-09-25（阶段 9 验收）。

═══ 怎么发现的 ═══
用户看 `사가` 的页面说「有很多没有释义」，顺着查录音层时打出文件名，撞见：

    그리고  Y.mp3        가다  Y.mp3        학교  Y.mp3   …… **45 个词共用一个文件**

一个 Commons 文件不可能同时是 45 个不同韩语词的录音。回源头看，
**中文版（简繁两片）自己就这么写**：

    {"audio": "y", "mp3_url": ".../transcoded/5/57/Y/Y.mp3"}

⭐ 又一次是**渲染出来读**才看见的：所有形式判据都满足（有 URL、有词形、
  `kind='human'`），只有内容是错的（`[[it-display-layer-stage8]]`）。
🔴 这一条比"缺"严重得多：读者点 `가다` 听到的是别的声音。
  `[[dict-framework-doc]]`：**错比缺更伤权威。**

═══ 🔴 判据写了三版，前两版都太宽 ═══
① 「文件名里不含词形且很短」⇒ 形式代理，会误伤 `여자.ogg.mp3` 这种正常命名。
② 「文件名不是 `Ko-` 前缀」⇒ **误伤 969 行**（`LL-Q9176_(kor)-…` 是
   Lingua Libre 的韩语录音，占全库 58%，最大的一族）。
③ **按含义写**（下面两条），实测只命中 58 行，且两个方向都验过。

    (a) **文件名声明了别的语言**（`Zh-` / `Ja-` 前缀）
        —— 挂在汉字条目上的**汉语/日语**读音。读者点 `士` 听到的是普通话 `shì`，
        而它的韩语音是 `사`。13 行。
    (b) **一个文件挂在多个词形上，而这些词的韩语读音没有交集**
        —— 它不可能同时是它们每一个的录音。45 行（全是 `Y.mp3`）。

🔴 **(b) 必须写成「读音没有交集」，不能写成「挂在多个词形上」** ——
   后者会误伤三族**正确**的共用：

    Ko-가.ogg.mp3    → 假 價 加 可 歌 街 駕   七个汉字**韩语都读 가** ✅
    Ko-안따.ogg.mp3   → 안다 안다/앉다          两个词**都读 안따**（同音词）✅
    Ko-있다.ogg.mp3   → 잇다 잊다              **都读 읻따** ✅

   汉字条目挂它的**韩语音**的录音是对的；同音词共用一条录音也是对的。
   `[[criteria-narrower-than-you-think]]`：收窄之后才逮到真的。

═══ ⚠️ 删完有 13 个汉字条目会一条录音都没有 ═══
全是 (a) 那批（仕 侍 勢 士 耆 誓 …）—— 它们**只有**那条汉语录音。
**有意删掉**：留着＝对读者说「韩语的 士 念 shì」。宁可没有。

跑（在仓库根）：
    python3 -u ko/pipeline/fix_wrong_audio.py
    python3 -u ko/pipeline/fix_wrong_audio.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")

# (a) 文件名声明了别的语言。**只列真见过的**，不预先想象
#     （`LL-Q9176_(kor)-…` 是 Lingua Libre 的韩语录音，占全库 58%，绝不能进这张表）。
FOREIGN = re.compile(r"^(Zh|Ja|En|Vi|Th|Yue|Cmn)-", re.I)
# 读音比对时忽略长音符与分隔符
NOISE = re.compile(r"[()ː·\s]")


def korean_readings(con, word):
    """这个词形在韩语里怎么读。谚文词用发音形；汉字条目用汉字音层的音节。"""
    r = {x[0] for x in con.execute(
        "SELECT p.hangeul_phonetic FROM pronunciation p JOIN dict d ON d.id = p.word_id"
        " WHERE d.word_norm = ? AND p.hangeul_phonetic IS NOT NULL", (word,))}
    r |= {x[0] for x in con.execute(
        "SELECT d.word FROM hanja_reading h JOIN dict d ON d.id = h.word_id"
        " WHERE h.hanja = ?", (word,))}
    return {NOISE.sub("", x) for x in r if x}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("SELECT id, word, file, src FROM audio").fetchall()
    n_before = len(rows)

    # (a) 别的语言的录音
    foreign = [r for r in rows if FOREIGN.match(r[2])]
    # (b) 一个文件挂在多个词形上而读音无交集
    by_file = collections.defaultdict(list)
    for r in rows:
        by_file[r[2]].append(r)
    shared, kept_shared = [], []
    for fn, rs in by_file.items():
        ws = {r[1] for r in rs}
        if len(ws) < 2:
            continue
        sets = [korean_readings(con, w) for w in ws]
        common = set.intersection(*sets) if all(sets) else set()
        (kept_shared if common else shared).append((fn, sorted(ws), sorted(common)[:3]))
    shared_ids = {r[0] for fn, ws, _ in shared for r in by_file[fn]}

    drop = {r[0] for r in foreign} | shared_ids
    print("■ 录音行 %s" % f(n_before))
    print("   (a) 文件名声明了别的语言           %3d 行" % len(foreign))
    for r in foreign[:8]:
        print("        %-8s %s" % (r[1], r[2]))
    print("   (b) 一文件多词形且韩语读音无交集     %3d 行" % len(shared_ids))
    for fn, ws, _ in shared:
        print("        %-24s %d 个词形：%s…" % (fn, len(ws), "、".join(ws[:6])))
    print("   ── 合计要删 %s 行 (%.1f%%)" % (f(len(drop)), 100.0 * len(drop) / n_before))

    print("\n■ 判据收窄的证据（这三族**共用同一条录音是对的**，不许被带走）")
    for fn, ws, common in kept_shared:
        print("   ✅ %-22s %d 个词形，韩语读音交集 %s：%s"
              % (fn, len(ws), common, "、".join(ws[:7])))
    if not kept_shared:
        raise SystemExit("🔴 一条「正确的共用」都没留下 —— 判据多半又写宽了，停")

    # 🔴 反向：谁会因此一条录音都没有
    left = collections.Counter(r[1] for r in rows if r[0] not in drop)
    orphan = sorted({r[1] for r in rows if r[0] in drop} - set(left))
    print("\n■ 删完会一条录音都没有的词形：%d" % len(orphan))
    print("   %s" % "、".join(orphan))
    print("   ⚠️ 有意如此：它们**只有**那条别的语言的录音。"
          "留着＝对读者说「韩语的 士 念 shì」。宁可没有（错比缺更伤权威）")
    con.close()

    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-drop-wrong-audio",
            expect={"#audio": -len(drop)},
            invalidates=[]) as s:
        s.executemany("DELETE FROM audio WHERE id=?", [(i,) for i in sorted(drop)])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    after = con.execute("SELECT word, file FROM audio").fetchall()
    g = collections.defaultdict(set)
    for w, fn in after:
        g[fn].add(w)
    still = [fn for fn, ws in g.items()
             if len(ws) > 1 and not set.intersection(
                 *[korean_readings(con, w) for w in ws])]
    checks = [
        ("录音行数", len(after), n_before - len(drop)),
        ("还剩别的语言的录音", sum(1 for _w, fn in after if FOREIGN.match(fn)), 0),
        ("还剩「一文件多词形且读音无交集」", len(still), 0),
        # 🔴 反向：那三族**对的**共用一条没少
        ("`Ko-가.ogg.mp3` 还挂着几个汉字",
         q("SELECT COUNT(*) FROM audio WHERE file='Ko-가.ogg.mp3'"), 7),
        ("Lingua Libre 那 969 行一条没动",
         q("SELECT COUNT(*) FROM audio WHERE file GLOB 'LL-*'"), 969),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-34s %7s（期望 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
