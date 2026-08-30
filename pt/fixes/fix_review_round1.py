#!/usr/bin/env python3
"""外审第一轮逮到的四族，一次清完。2026-08-30。

═══ 这四族是怎么发现的 ═══
阶段 9 之后跑外审（DeepSeek v4-pro + 豆包，各两版 prompt）。
用户 2026-08-30 问「你的 prompt 有偏袒性吗」⇒ 做了**两版对照**：
一版带 8 条方向提示、一版纯开放式，材料完全相同。
实测：**所有大族两版都出现，差异沿模型分界线而非 prompt 分界线** ——
提示没有实质框定结果。四族里有三族**我全部的闸都没覆盖**。

    族A 非葡语混进语义关系     11 条（德语 3 + 希腊/西里尔/汉字 8）
    族B 同一 target 重复    🔴 **14,386 组** —— 最大的一族
    族C 例句译文用繁体字      🔴 **283 条**
    族D 希腊语版的近义标注行当成了例句   2 条

═══ 逐族的根因（都不是"没注意"，是判据的洞）═══

**族A** 5b 收关系时**没有判据管 target 是不是葡语**。
   `outono` 的反义里躺着 `Frühling`/`Sommer`/`Winter` —— 源头（某版维基）
   在葡语词条下列了德语对应词。⇒ 加「target 必须是拉丁字母且不在外语黑名单」。
   ⚠️ **不能只按字符集判**：葡语本来就全是拉丁字母，德语词也是。
     所以德语季节词只能点名（数量少、可枚举），非拉丁字符才用字符集。

**族B** 我的去重键是 `(word_id, sense_id, kind, target)` —— 而**同一个词的不同义项
   指向同一个近义词**就绕过去了（`bem` 的七条义项都说反义是 `mal`）。
   🔴 这是 `[[criteria-narrower-than-you-think]]` 的又一次：
     去重键比"读者眼里的重复"**窄**。展示层按 `(kind, target)` 去重才对。
   ⇒ **在展示层去重**（数据保留义项级归属，那是有用的），并加闸。

**族C** 1.5b/5d 的控制表**十条判据里没有一条查字形**。
   283 条繁体字混在简体词典里，读者一眼看得出来，而我的闸一条都没响。
   ⇒ 确定性转简 + 加闸。

**族D** 同 fr 收尾单那条「456 行根本不是例句」——
   希腊语版把 `≈ συνώνυμα: …`（近义词标注）写进了 examples。

用法（在 pt/ 目录下）：
    python3 fixes/fix_review_round1.py
    python3 fixes/fix_review_round1.py --apply
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# ── 族A ──
NON_LATIN = re.compile(r"[Ͱ-ϿЀ-ӿ一-鿿぀-ヿ가-힯]")
# 德语词只能点名：葡语和德语都用拉丁字母，字符集判不了。
DE_WORDS = {"Frühling", "Sommer", "Winter", "Herbst"}
# ── 族D ──
NOT_EXAMPLE = re.compile(r"^\s*≈\s*συνών|^\s*(Near-)?synonyms?\s*:", re.I)

# ── 族C：繁体 → 简体 ──
# 🔴 第一版我**自己列了一张 40 字的对照表** —— 干跑当场露馅：
#      `我從沒去過英國。` → `我从沒去過英国。`   （`沒`/`過` 不在我表里）
#    留个半成品比不改更难看。⇒ **判据用现成的权威实现，别自己枚举**
#    （铁律②「先问是不是已经有人做好了」在小尺度上的同一件事）。
from opencc import OpenCC   # noqa: E402

_CC = OpenCC("t2s")


def simp(s):
    return _CC.convert(s)


def is_trad(s):
    """含繁体 = 转换后与原文不同。**不列字表**，由转换器自己判。"""
    return _CC.convert(s) != s


def plan(con):
    # A：非葡语 target
    a = [(i, w, t) for i, w, t in con.execute(
        "SELECT r.id, d.word, r.target FROM sense_relation r JOIN dict d ON d.id=r.word_id "
        "WHERE r.kind<>'alt_of'")
        if NON_LATIN.search(t) or t in DE_WORDS]
    # C：繁体字译文
    cc = [(eid, z) for eid, z in con.execute(
        "SELECT g.example_id, g.text FROM example_gloss g JOIN example e ON e.id=g.example_id "
        "WHERE g.lang='zh' AND COALESCE(e.hidden,0)=0") if is_trad(z)]
    # D：不是例句的标注行
    d = [(i, w, t) for i, w, t in con.execute(
        "SELECT id, word, text FROM example WHERE COALESCE(hidden,0)=0")
        if NOT_EXAMPLE.match(t)]
    # B 只报数（在展示层修，不动数据）
    b = con.execute(
        "SELECT COUNT(*) FROM (SELECT word_id,kind,target FROM sense_relation "
        "WHERE kind<>'alt_of' GROUP BY 1,2,3 HAVING COUNT(*)>1)").fetchone()[0]
    return a, b, cc, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a_, b_, c_, d_ = plan(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))
    f = lambda n: format(n, ",")
    print("■ 族A 非葡语 target（删）        %s" % f(len(a_)))
    for _i, w, t in a_[:6]:
        print("     %-16s → %s" % (w[:16], t[:36]))
    print("■ 族B 同一 target 重复（**展示层去重，不动数据**）%s 组" % f(b_))
    print("■ 族C 繁体字译文（转简）        %s" % f(len(c_)))
    for _e, z in c_[:4]:
        print("     %s\n        → %s" % (z[:46], simp(z)[:46]))
    print("■ 族D 不是例句的标注行（隐掉）   %s" % f(len(d_)))
    for _i, w, t in d_:
        print("     %-16s %s" % (w[:16], t[:50]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("fix-pt-review-r1",
                        expect={"#sense_relation": -len(a_)}) as s:
        s.executemany("DELETE FROM sense_relation WHERE id=?", [(i,) for i, _w, _t in a_])
        s.executemany("UPDATE example_gloss SET text=? WHERE example_id=? AND lang='zh'",
                      [(simp(z), e) for e, z in c_])
        s.executemany("UPDATE example SET hidden=1 WHERE id=?", [(i,) for i, _w, _t in d_])
    print("\n✓ 族A 删 %d ／ 族C 转简 %d ／ 族D 隐 %d（族B 在展示层）"
          % (len(a_), len(c_), len(d_)))
    return 0


if __name__ == "__main__":
    a = None
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    sys.exit(main())
