#!/usr/bin/env python3
"""en：删掉 ECDICT 方括号解析出来的**非中文残片**（它们被当成学科标记入了库）。2026-09-15。

═══ 怎么发现的 ═══
准备把 kaikki 的英文 topic 解开展示时，逐条看落点里没有中文名的 slug，
尾巴上蹲着一批根本不是学科的东西：

    [2,3-f]   benzfuro「苯并呋喃并[2,3-f]喹啉」 —— 化学名的一部分
    [inf！]   to get laid「[inf！]性交」        —— 源头自己的排版残渣
    [WIN,NT]  stack dump「[WIN,NT]堆栈转储」    —— 平台标注
    [P-] [m-] [s-] [a-] [pl. ] …

`build_legacy_sense.py` 的 `MARK_RE` 抠 `[…]`（≤6 字符），`bucket()` 查不到就落 `topic`
—— 于是这些残片全成了「学科标记」。

═══ 🔴 判据：ECDICT 的学科标记**全是中文短码** ═══
库里量过：ecdict 来源的 topic 取值 3,239 种中文 / 65.3 万条，
外加 58 种拉丁字母 / 174 条 —— 后者**无一例外**是残片。
⚠️ 第一版我写的判据是「长得像不像 slug」，把 kaikki 的 `pesäpallo`（芬兰棒球）
   当噪声误伤了。改成「这条 tag 是不是 ecdict 来源 + 有没有汉字」，
   两个条件缺一不可（`[[criteria-narrower-than-you-think]]`）。

生成侧的守卫已经补在 `build_legacy_sense.py::bucket()`；这里删已经落库的。
（`[[it-backlog-cleared]]`：修生成侧没修已落库的行 —— 同一个坑。）

跑：
    python3 scripts/fix_en_ecdict_mark_junk.py            # 预览
    python3 scripts/fix_en_ecdict_mark_junk.py --apply
"""
import argparse
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "en"))
import dbtool                                                        # noqa: E402

SEL = """SELECT st.sense_id, st.value FROM sense_tag st
         JOIN sense_src ss ON ss.sense_id = st.sense_id AND ss.src = 'ecdict'
         WHERE st.kind = 'topic'"""


def ro():
    return sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = ro()
    rows = [(sid, v) for sid, v in con.execute(SEL) if not dbtool.has_han(v)]
    con.close()
    vals = sorted({v for _, v in rows})
    print(f"■ 要删的：{len(rows)} 条 / {len(vals)} 种")
    dbtool.sample_check([(v, sum(1 for _, x in rows if x == v)) for v in vals[:20]],
                        20, ("残片", "条数"))
    if not a.apply:
        print("\n(预览。确认后 --apply)")
        return

    with dbtool.session("fix-en-ecdict-mark-junk", expect={"#sense_tag": -len(rows)}) as s:
        s.executemany("DELETE FROM sense_tag WHERE sense_id=? AND kind='topic' AND value=?",
                      rows)

    con = ro()
    left = [v for sid, v in con.execute(SEL) if not dbtool.has_han(v)]
    con.close()
    print(f"\n═══ 写后回核 ═══\n   剩余非中文 ecdict topic：{len(left)}（期望 0）")
    if left:
        sys.exit("🔴 回核对不上：%r" % left[:10])
    print("   ✅")


if __name__ == "__main__":
    main()
