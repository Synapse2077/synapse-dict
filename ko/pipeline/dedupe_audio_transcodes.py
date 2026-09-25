#!/usr/bin/env python3
"""同一条录音被存了两行（转码名 vs 原始名）。ko，2026-09-25（阶段 9b）。

═══ 怎么发现的 ═══
把 `한국` 的词条页真渲染出来读，真人发音那一排是：

    真人发音  [未标注]  [未标注]

两个按钮，标签一模一样 —— **读者分不清点哪个**，而且它们放的是**同一条录音**。

⭐ 这正是 fr 那轮 `chien` 排出「八个按钮全写着法国」的同一个病，
   `App.tsx` 的 `capAudios` 注释里原话记着：「读者要的是不同口音，
   不是同一口音的八个人」。ko 这次更彻底 —— 连口音都不是不同的，是**同一个文件**。

═══ 根子：两个写入方，而去重键看不穿它们的差别 ═══
    Ko-가.ogg.mp3   src=ko-edition    ← 各维基版内嵌的是**转码后**的 mp3 名
    Ko-가.ogg       src=commons       ← Commons 收割拿到的是**原始**文件名

实测 456 组，保留侧 **456/456 全是 `commons`**，转码侧是四个维基版
（ko 423 ／ en 21 ／ zh-trad 11 ／ ja 1）—— 干净的「一个收割器一种写法」。

`audio` 表的注释写着「去重靠 `file` 不靠 URL」——**判据是对的，可两个写入方
把同一个文件写成了两个 `file`**。⇒ 与 K14 同一个签名：
**两个写入方，而身份键分不开它们**（`[[primary-key-is-not-enough]]`）。

═══ 判据（收窄到只认**转码后缀**）═══
    `<名字>.<oga|ogg|wav|flac|opus>.mp3`  ←→  `<名字>.<同一个扩展名>`
只有这一种形状算同一条录音。实测 **456 组 / 每组恰好 2 行 / 四个字段零冲突**。

🔴 **有意不并**另外 3 行（`Ko-한국.oga` vs `Ko-한국.ogg`）：那是两个**不同的
   Commons 文件**，不是转码关系。第一版我用「去掉任意扩展名后同名」去分组，
   多扫出 3 行 —— 判据宽了一点点就会把说不清的东西一起并掉
   （`[[criteria-narrower-than-you-think]]`）。

═══ 并法：合并 URL 列，不是删掉一行了事 ═══
schema 里 `url_mp3` / `url_ogg` / `url_wav` / `url_other` 本来就是为
「同一条录音的多个容器」准备的。⇒ 保留 **Commons 原始文件名**那一行
（`file` 是录音的身份，转码名不是），把另一行的 URL 并进它的空列。

跑（在仓库根）：
    python3 -u ko/pipeline/dedupe_audio_transcodes.py
    python3 -u ko/pipeline/dedupe_audio_transcodes.py --apply
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

# 🔴 只认转码后缀，不认「任意扩展名」（见文件头）
TRANSCODE = re.compile(r"\.(oga|ogg|wav|flac|opus)\.mp3$", re.I)
URLS = ("url_mp3", "url_ogg", "url_wav", "url_other")
COLS = ("id", "word", "file") + URLS + ("ipa", "speaker", "region", "region_src",
                                        "kind", "src")


def original_name(fn):
    """转码名 → 原始 Commons 文件名；本来就是原始名的原样返回。"""
    m = TRANSCODE.search(fn)
    return fn[:m.end() - 4] if m else fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("SELECT %s FROM audio" % ", ".join(COLS)).fetchall()
    n_before = len(rows)
    groups = collections.defaultdict(list)
    for r in rows:
        d = dict(zip(COLS, r))
        groups[(d["word"], original_name(d["file"]).lower())].append(d)
    dups = {k: v for k, v in groups.items() if len(v) > 1}

    # 🔴 判据的自检：每组必须**恰有一行是转码名**，否则分组判据不成立
    bad = [k for k, v in dups.items()
           if sum(1 for x in v if TRANSCODE.search(x["file"])) != 1]
    conflict = collections.Counter()
    for v in dups.values():
        for col in ("ipa", "speaker", "region", "kind"):
            if len({x[col] for x in v if x[col] is not None}) > 1:
                conflict[col] += 1

    print("■ 录音行 %s（词形 %s）" % (f(n_before), f(len({r[1] for r in rows}))))
    print("   同一条录音存了两行的组 %s，可并掉 %s 行 (%.1f%%)"
          % (f(len(dups)), f(sum(len(v) - 1 for v in dups.values())),
             100.0 * sum(len(v) - 1 for v in dups.values()) / n_before))
    print("   %s 每组恰有一行是转码名：%s"
          % ("✅" if not bad else "🔴", "是" if not bad else "%d 组不是" % len(bad)))
    print("   %s 组内字段冲突：%s"
          % ("✅" if not conflict else "🔴", dict(conflict) or "无"))
    if bad:
        raise SystemExit("🔴 分组判据不成立，先弄清楚再并")
    if conflict:
        raise SystemExit("🔴 有字段冲突 —— 并之前要决定留哪个值")

    print("\n■ 样本")
    for k, v in list(dups.items())[:4]:
        print("   %s" % k[0])
        for x in v:
            print("      %-22s src=%-12s %s"
                  % (x["file"], x["src"],
                     " ".join(c for c in URLS if x[c])))

    # 保留原始名那一行，把转码行的 URL 并进它的空列
    keep_upd, drop_ids = [], []
    for v in dups.values():
        keep = next(x for x in v if not TRANSCODE.search(x["file"]))
        other = next(x for x in v if x is not keep)
        merged = {c: keep[c] or other[c] for c in URLS}
        if any(merged[c] != keep[c] for c in URLS):
            keep_upd.append(tuple(merged[c] for c in URLS) + (keep["id"],))
        drop_ids.append((other["id"],))
    # 🔴 期望值**从合并计划直接算出来**，不用「现有 ＋ 增 − 减」那种算式：
    #    第一版就是那么写的，`url_mp3` 报成 2,080 而真值是 1,664 ——
    #    算式里「增」把本来就非空的列也数了一遍。
    #    `[[expectation-must-be-declared]]`：说不清期望值的回核等于没有回核。
    post = collections.Counter()
    for v in groups.values():
        if len(v) == 1:
            for c in URLS:
                if v[0][c]:
                    post[c] += 1
            continue
        keep = next(x for x in v if not TRANSCODE.search(x["file"]))
        other = next(x for x in v if x is not keep)
        for c in URLS:
            if keep[c] or other[c]:
                post[c] += 1
    print("\n■ 将并掉 %s 行；URL 列的合并后真值" % f(len(drop_ids)))
    for c in URLS:
        cur = sum(1 for r in rows if r[COLS.index(c)])
        print("   %-10s 现有 %5s → 合并后 %5s%s"
              % (c, f(cur), f(post[c]),
                 "   ← 删掉的那 456 行各自都有一份，保留行也有，没有丢地址"
                 if c == "url_mp3" else ""))
    # 🔴 反向：合并之后**每一行都还至少有一个可播地址**
    dead = sum(1 for v in groups.values()
               for x in ([v[0]] if len(v) == 1
                         else [next(y for y in v if not TRANSCODE.search(y["file"]))])
               if not any(x[c] for c in URLS))
    print("   %s 合并后没有任何可播地址的行：%s" % ("✅" if not dead else "🔴", f(dead)))
    con.close()

    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-dedupe-audio-transcodes",
            expect={"#audio": -len(drop_ids)},
            invalidates=[]) as s:
        s.executemany(
            "UPDATE audio SET url_mp3=?, url_ogg=?, url_wav=?, url_other=? WHERE id=?",
            keep_upd)
        s.executemany("DELETE FROM audio WHERE id=?", drop_ids)

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    after = con.execute("SELECT word, file FROM audio").fetchall()
    g2 = collections.defaultdict(list)
    for w, fn in after:
        g2[(w, original_name(fn).lower())].append(fn)
    still = sum(len(v) - 1 for v in g2.values() if len(v) > 1)
    checks = [
        ("录音行数", len(after), n_before - len(drop_ids)),
        ("还剩下的转码重复", still, 0),
        # 🔴 反向：**一个词都不能因此失去录音**
        ("失去录音的词形", len({r[COLS.index('word')] for r in rows})
         - len({w for w, _ in after}), 0),
        ("url_mp3 非空", q("SELECT COUNT(*) FROM audio WHERE url_mp3 IS NOT NULL"),
         post["url_mp3"]),
        ("url_other 非空", q("SELECT COUNT(*) FROM audio WHERE url_other IS NOT NULL"),
         post["url_other"]),
        # 🔴 并进来的 URL 没丢：每一行都至少还有一个可播地址
        ("没有任何可播地址的行",
         q("SELECT COUNT(*) FROM audio WHERE COALESCE(url_mp3,url_ogg,url_wav,url_other)"
           " IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-26s %9s（期望 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))
    print("\n■ `한국` 现在的录音")
    for r in con.execute("SELECT file, region, speaker FROM audio WHERE word='한국'"):
        print("   %s" % (r,))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
