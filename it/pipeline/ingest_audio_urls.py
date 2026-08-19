#!/usr/bin/env python3
"""阶段 6a：收真人录音的 **URL**（不下载文件）→ `audio` 表。2026-08-18。

═══ 为什么先只收 URL ═══
`IT_PLAN` 阶段 6 的原话：**「录音 URL 在语言版 dump 里是白送的，贵的只是下载。」**
`upload.wikimedia.org` 是读者 CDN、**有意限流**（es 实测 8 并发只到 0.6 条/秒、
220 次重试、25 条 429，全量 6–9 小时）⇒ URL 先入库，下不下载是**单独的决定**。

═══ 三条规矩 ═══
① **按语言码过滤**（A14）：跨版收割不许按词形匹配 —— es 曾因此混进 63 条非西语录音。
   本脚本用 `iter_source(..., lang_code)`，与音标/例句同一条通路。
② **同一条录音的 mp3/ogg/wav 是一条，不是三条**（`it-CONVENTIONS` 记账本里那条
   「录音条数原来虚高 2–3 倍」的成因就是把三个 url 字段数成三条）⇒ 行键是
   `(词形, 文件名)`，三种格式落在同一行的三个列上。
③ **录音人从文件名认，认不出就留空**（`audio-from-commons-not-tts`：en 口音靠文件名
   + 145 位录音人，前 5 位覆盖 88.6%）。Lingua Libre 的命名是
   `LL-Q652 (ita)-<录音人>-<词>.wav` —— 只认这一种，别的不猜。

用法（在 it/ 目录下）：
    python3 pipeline/ingest_audio_urls.py            # 干跑
    python3 pipeline/ingest_audio_urls.py --apply
    python3 pipeline/ingest_audio_urls.py --verify
    python3 pipeline/ingest_audio_urls.py --mutate
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool                                       # noqa: E402
import paths                                        # noqa: E402
from build_pronunciation_layer import word_index    # noqa: E402
from ipa_variants import iter_source, norm_ipa, variants_of   # noqa: E402

SOURCES = [("fr-edition", paths.KK_FR, None),      # A13：录音主源（13,343 条，en 的 6.6 倍）
           ("en-edition", paths.KK, None),
           ("it-edition", paths.EDITION, "it")]
PRIO = {"fr-edition": 0, "en-edition": 1, "it-edition": 2}
URL_KEYS = [("mp3_url", "url_mp3"), ("ogg_url", "url_ogg"), ("wav_url", "url_wav")]
# Lingua Libre：LL-Q652 (ita)-<录音人>-<词>.wav
_LL = re.compile(r"^LL-Q\d+\s*\([a-z]{3}\)-([^-]+)-")
f = lambda n: format(n, ",")


def _ipa_of(sound):
    """这条录音自带的音标（有的话）。用与音标层**同一个**解析入口，不另写一份。"""
    vs = variants_of({"word": "x", "sounds": [sound]}, "it-edition")
    return vs[0].ipa if vs else None


def speaker_of(filename):
    """从文件名认录音人。**只认 Lingua Libre 那一种命名**，认不出返回 None，不猜。"""
    m = _LL.match(filename or "")
    return m.group(1).strip() if m else None


def region_of(tags):
    """从 tags/raw_tags 里取地区限定。原样保留源头写法，不映射成地区码。

    ⚠️ 与 `pronunciation.region` 同一个立场（A58）：意语没有 es 那种半岛/拉美两分，
       源头给的是 `Italie (Milan)` / `Monopoli (Italie)` 这类自由文本，
       硬塞成 `it-IT` 之类就是编造。这里只存原文，`region_src` 记它来自哪一版。
    """
    for t in tags:
        if re.search(r"Ital|Milan|Monopoli|Roman|Napol|Sicil|Toscan|Svizzer|Suisse", t, re.I):
            return t
    return None


def collect(con, verbose=True):
    ids, _ = word_index(con)
    id2word = {i: w for i, w in con.execute("SELECT id, word FROM dict")}
    rows, c = {}, Counter()
    for src, path, lc in SOURCES:
        for w, d in iter_source(path, src, lc):
            wid = ids.get(w)
            if wid is None:
                c["词形不在库里"] += 1
                continue
            word = id2word[wid]
            for s in (d.get("sounds") or []):
                urls = {col: s.get(k) for k, col in URL_KEYS if s.get(k)}
                if not urls:
                    continue
                fn = (s.get("audio") or "").strip()
                if not fn:
                    # 没有文件名就用 mp3/ogg 的最后一段当键 —— 键必须稳定，不能用下标
                    any_url = next(iter(urls.values()))
                    fn = any_url.rsplit("/", 1)[-1]
                key = (word, fn)
                if key in rows:
                    # 同一条录音多版都给：补齐缺的格式列，来源记优先级高的那版
                    old = rows[key]
                    for col, u in urls.items():
                        old.setdefault(col, u)
                    if PRIO[src] < PRIO[old["src"]]:
                        old["src"] = src
                    c["同一条录音多版都有"] += 1
                    continue
                tags = list(s.get("tags") or []) + list(s.get("raw_tags") or [])
                row = {"word": word, "file": fn, "ipa": _ipa_of(s),
                       "speaker": speaker_of(fn), "region": region_of(tags),
                       "region_src": src if region_of(tags) else None,
                       "kind": "human", "src": src}
                row.update(urls)
                rows[key] = row
                c[src] += 1
    c["落表行数"] = len(rows)
    c["认出录音人的"] = sum(1 for r in rows.values() if r["speaker"])
    c["带地区限定的"] = sum(1 for r in rows.values() if r["region"])
    c["覆盖词形数"] = len({r["word"] for r in rows.values()})
    return list(rows.values()), c


def gate(con, anchor=None):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("🔴 ② 词形必须在 dict 里",
         q("SELECT count(*) FROM audio a WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.word=a.word)"), 0),
        ("🔴 ② 每行至少有一个 url",
         q("SELECT count(*) FROM audio WHERE COALESCE(url_mp3,'')='' "
           "AND COALESCE(url_ogg,'')='' AND COALESCE(url_wav,'')='' "
           "AND COALESCE(url_other,'')=''"), 0),
        ("🔴 ② (词形,文件名) 不许重复",
         q("SELECT count(*) FROM (SELECT word,file FROM audio GROUP BY word,file "
           "HAVING count(*)>1)"), 0),
        ("🔴 ② url 必须指向 wikimedia",
         q("SELECT count(*) FROM audio WHERE COALESCE(url_mp3,url_ogg,url_wav,'') NOT LIKE "
           "'%wikimedia.org%'"), 0),
        ("🔴 ② src 只有三版",
         q("SELECT count(*) FROM audio WHERE src NOT IN "
           "('en-edition','it-edition','fr-edition')"), 0),
        ("🔴 ③ kind 只有 human（本步不收合成音）",
         q("SELECT count(*) FROM audio WHERE kind <> 'human'"), 0),
    ]
    if anchor is not None:
        have = {(w, fn) for w, fn in con.execute("SELECT word, file FROM audio")}
        checks += [("🔴 ① 表里有、而三版 dump 里查不到的录音", len(have - anchor), 0),
                   ("🔴 ① dump 有、表里没有的录音（漏收）", len(anchor - have), 0)]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-44s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def anchor_set(con):
    ids, _ = word_index(con)
    id2word = {i: w for i, w in con.execute("SELECT id, word FROM dict")}
    out = set()
    for src, path, lc in SOURCES:
        for w, d in iter_source(path, src, lc):
            wid = ids.get(w)
            if wid is None:
                continue
            for s in (d.get("sounds") or []):
                urls = [s.get(k) for k, _ in URL_KEYS if s.get(k)]
                if not urls:
                    continue
                fn = (s.get("audio") or "").strip() or urls[0].rsplit("/", 1)[-1]
                out.add((id2word[wid], fn))
    return out


def mutate():
    print("═══ 变异验证 A：判据本体 ═══")
    cases = [
        ("Lingua Libre 认得出录音人",
         speaker_of("LL-Q652 (ita)-LangPao-mai.wav"), "LangPao"),
        ("🔴 别的命名不猜录音人", speaker_of("It-mai.ogg"), None),
        ("🔴 空文件名不炸", speaker_of(""), None),
        ("地区限定原样留", region_of(["Italie (Milan)"]), "Italie (Milan)"),
        ("🔴 无关 tag 不当地区", region_of(["masculine", "plural"]), None),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-40s → %s" % ("✅" if good else "🔴", name, got))

    print("\n═══ 变异验证 B：闸（备份副本上）═══")
    import contextlib
    import io
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    shutil.copy(paths.DB, tmp)
    muts = [
        ("删 3 条录音", "DELETE FROM audio WHERE id IN (SELECT id FROM audio LIMIT 3)"),
        ("塞一条 url 全空的", "INSERT INTO audio (word,file,kind,src) VALUES "
         "((SELECT word FROM audio LIMIT 1),'x.ogg','human','it-edition')"),
        ("塞一条非 wikimedia 的 url", "INSERT INTO audio (word,file,url_mp3,kind,src) VALUES "
         "((SELECT word FROM audio LIMIT 1),'y.ogg','https://evil.example/y.mp3','human','it-edition')"),
        ("把 1 条改成合成音", "UPDATE audio SET kind='tts' WHERE id=(SELECT min(id) FROM audio)"),
    ]
    anchor = anchor_set(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))
    caught = 0
    for name, sql in muts:
        c2 = sqlite3.connect(tmp)
        try:
            c2.execute(sql)
            c2.commit()
        except sqlite3.IntegrityError:
            c2.close()
            shutil.copy(paths.DB, tmp)
            caught += 1
            print("   ✅ 逮住 %s（UNIQUE 拦下）" % name)
            continue
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            good = gate(c2, anchor)
        c2.close()
        shutil.copy(paths.DB, tmp)
        caught += (not good)
        print("   %s %s" % ("✅ 逮住" if not good else "🔴 没逮住", name))
    ok &= caught == len(muts)
    print("\n   变异验证 %s（%d/%d）" % ("通过" if ok else "🔴 有洞", caught, len(muts)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.mutate:
        ro.close()
        return 0 if mutate() else 1
    if a.verify:
        print("■ 建外锚（重扫三版 dump）", flush=True)
        return 0 if gate(ro, anchor_set(ro)) else 1
    rows, c = collect(ro)
    ro.close()
    print("\n■ 录音 %s 条" % f(len(rows)))
    for k, v in c.most_common():
        print("     %-34s %s" % (k, f(v)))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("ingest-audio-urls", expect={"__rows__": 0, "#audio": len(rows)}) as s:
        s.executemany(
            "INSERT INTO audio (word,file,url_mp3,url_ogg,url_wav,ipa,speaker,region,"
            "region_src,kind,src) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(r["word"], r["file"], r.get("url_mp3"), r.get("url_ogg"), r.get("url_wav"),
              r["ipa"], r["speaker"], r["region"], r["region_src"], r["kind"], r["src"])
             for r in rows])
    print("\n■ 已落表 %s 条" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
