#!/usr/bin/env python3
"""B12：同一条 Commons 录音被存成两行 —— 并成一行。七门共用一份（en/es/it/fr/pt/de/ja），2026-10-29。

═══ 缺陷 ═══
各维基版内嵌录音时写法不一：`Es-us-Alejandro.ogg`／`es-us-Alejandro.ogg`（首字母）、
`Pt-pt Abrantes FF`／`Pt-pt_Abrantes_FF`（下划线）、`LL-…-&#39;ll.wav`／`…-'ll.wav`（HTML 实体）、
`X.ogg.mp3`／`X.ogg`（转码派生）。`UNIQUE(word_id, url)` 挡不住（vi 实测放进 31.8%）。
页面上排出两个按钮放同一条录音，或标签正好不同而看不出来（ko K23 与本账互相看不见）。

═══ 判据 ═══
「是不是同一个文件」一条都不在这里写 —— `scripts/commons_filename.audio_key`（MediaWiki 自己的标题规则，
闸 `test_audio_dup_gate.py` 与 ko 的合并脚本 import 的也是它）。

═══ 并法（照 ko `dedupe_audio_transcodes.py`：合并 URL 列，不是删一行了事）═══
保留哪一行 —— 按 MediaWiki 的**规范标题**：原始名优先于转码名 → 首字母大写 → 空格而非下划线 →
百分号编码与 HTML 实体已解码 → id 小的。别的行的 URL 并进保留行的**空列**，一个都不丢（写后回核逐组比 URL 集合）。
标注不一致（74 组，2026-10-29 逐组读过）：
    ipa      同一条录音，不同维基版的转写（`ˈpa.dre`／`ˈpadre`）⇒ **本语种维基版给的优先**，否则保留行的
    region   `It-casa`：fr 版 `Italie`／it 版 `italiano settentrionale` ⇒ 本语种维基版优先；
             两行都不是本语种版而又不一致（`Pt doente` fr 版 pt-BR／en 版 pt-PT）⇒ **置空不猜**（连 region_src）
    speaker  只差下划线与空格（`MSa_Eu`／`MSa Eu`）⇒ 取保留行的（规范标题是空格）
`kind` 不一致 ＝ 判据错了（不可能是同一条录音）⇒ 整组不并、大声报。

跑（在仓库根）：
    python3 -u scripts/dedupe_audio_commons.py --lang it            # 干跑
    python3 -u scripts/dedupe_audio_commons.py --lang it --apply
"""
import argparse
import collections
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from commons_filename import TRANSCODE, audio_key, commons_key, url_filename  # noqa: E402

LANGS = ("en", "es", "it", "fr", "pt", "de", "ja")
URLS = ("url_mp3", "url_ogg", "url_wav", "url_other")
COLS = ("id", "word", "file") + URLS + ("ipa", "speaker", "region", "region_src", "kind", "src")
f = lambda n: format(n, ",")


def canon_rank(d):
    fn = d["file"] or ""
    return (bool(TRANSCODE.search(fn)), "%" in fn, not fn[:1].isupper(), "_" in fn, "&#" in fn, d["id"])


def merge(lang, rows):
    """→ (保留行 id, {列: 新值}, [删的 id], 说明)；判据错了返回 None。"""
    if len({r["kind"] for r in rows if r["kind"] is not None}) > 1:
        return None
    rows = sorted(rows, key=canon_rank)
    keep, rest = rows[0], rows[1:]
    new, notes = {}, []
    for c in URLS:
        if keep[c] is None:
            v = next((r[c] for r in rest if r[c] is not None), None)
            if v is not None:
                new[c] = v
    native = [r for r in rows if r["src"] == "%s-edition" % lang]

    def pick(col):
        vals = {r[col] for r in rows if r[col] is not None}
        if len(vals) <= 1:
            return next(iter(vals), None), None
        nat = {r[col] for r in native if r[col] is not None}
        if len(nat) == 1:
            return next(iter(nat)), "本语种版"
        return None, "冲突"

    ipa, why = pick("ipa")
    if why == "冲突":
        ipa, why = keep["ipa"] or next(r["ipa"] for r in rest if r["ipa"]), "保留行"
    if ipa != keep["ipa"]:
        new["ipa"] = ipa
    if why:
        notes.append("ipa:" + why)
    region, why = pick("region")
    if why == "本语种版":
        src = next(r["region_src"] for r in native if r["region"] == region)
    elif why == "冲突":
        region, src = None, None                     # 判不出谁对 ⇒ 不猜
    else:
        src = keep["region_src"] if keep["region"] == region else next(
            (r["region_src"] for r in rows if r["region"] == region), None)
    if (region, src) != (keep["region"], keep["region_src"]):
        new["region"], new["region_src"] = region, src
    if why:
        notes.append("region:" + why)
    if keep["speaker"] is None:
        sp = next((r["speaker"] for r in rest if r["speaker"]), None)
        if sp:
            new["speaker"] = sp
    elif len({r["speaker"] for r in rows if r["speaker"]}) > 1:
        notes.append("speaker:保留行")
    return keep["id"], new, [r["id"] for r in rest], notes


def plan(con, lang):
    g = collections.defaultdict(list)
    for r in con.execute("SELECT %s FROM audio" % ",".join(COLS)):
        d = dict(zip(COLS, r))
        g[(d["word"], audio_key(d["file"], [d[c] for c in URLS if d[c]]))].append(d)
    todo, bad = [], []
    for k, rows in g.items():
        if len(rows) < 2:
            continue
        m = merge(lang, rows)
        (bad if m is None else todo).append((k, rows) if m is None else (k, rows, m))
    return todo, bad


def url_sets(con):
    """按「链接指向的文件＋格式」比，不按字符串比：`Special:FilePath/fr-x.ogg` 与 `…/Fr-x.ogg` 是同一个文件
    （第一版按字符串比，七门报「丢了 5,000 多条链接」，其中只有 2 条是真丢 —— 就是 `Pt-br-eu.ogg` 那条）。"""
    s = collections.defaultdict(set)
    for r in con.execute("SELECT word, file, %s FROM audio" % ",".join(URLS)):
        us = [u for u in r[2:] if u]
        s[(r[0], audio_key(r[1], us))].update(
            (commons_key(url_filename(u) or u), u.rsplit(".", 1)[-1].lower()) for u in us)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=LANGS)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT / a.lang))
    import dbtool                                    # 各门自己的写库闸门
    con = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    todo, bad = plan(con, a.lang)
    before_urls = url_sets(con)
    n_before = con.execute("SELECT COUNT(*) FROM audio").fetchone()[0]
    con.close()
    drop = [i for _k, _r, (_kid, _n, d, _no) in todo for i in d]
    notes = collections.Counter(n for _k, _r, (_kid, _n, _d, no) in todo for n in no)
    print("■ B12 录音去重（%s）：%s 组，删 %s 行，改保留行 %s 组 ｜ 🔴 kind 冲突不并 %s 组"
          % (a.lang, f(len(todo)), f(len(drop)), f(sum(1 for *_x, (_k, n, _d, _no) in todo if n)), len(bad)))
    print("   标注裁决：%s" % (dict(notes) or "（无冲突）"))
    for (w, _k), rows, (kid, new, d, no) in [t for t in todo if t[2][3]][:12]:
        keep = next(r for r in rows if r["id"] == kid)
        print("   %-14s 留 %-34s %s  %s" % (w[:14], keep["file"][-34:], new or "", no))
    if bad:
        for (w, _k), rows in bad[:5]:
            print("   🔴 kind 冲突：%s %s" % (w, [(r["file"], r["kind"]) for r in rows]))
    if not a.apply or not todo:
        print("\n（干跑。加 --apply 才写库）" if todo else "\n（无事可做）")
        return
    expect = {"#audio": -len(drop)} if "audio" in getattr(dbtool, "TRACK_TABLES", ()) else {}
    with dbtool.session("b12-audio-dedupe", expect=expect) as s:
        for _k, _r, (kid, new, d, _no) in todo:
            if new:
                s.execute("UPDATE audio SET %s WHERE id=?" % ",".join("%s=?" % c for c in new),
                          list(new.values()) + [kid])
        s.executemany("DELETE FROM audio WHERE id=?", [(i,) for i in drop])
    con = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    left, _ = plan(con, a.lang)
    after_urls = url_sets(con)
    n_after = con.execute("SELECT COUNT(*) FROM audio").fetchone()[0]
    con.close()
    lost = sum(len(before_urls[k] - after_urls.get(k, set())) for k in before_urls)
    checks = [("仍有重复的组", len(left), 0), ("录音行数", n_after, n_before - len(drop)),
              ("丢掉的 URL（逐组比集合）", lost, 0)]
    red = 0
    print("\n■ 写后回核")
    for name, got, want in checks:
        red += got != want
        print("   %s %-22s %8s  期望 %s" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


if __name__ == "__main__":
    main()
