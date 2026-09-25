#!/usr/bin/env python3
"""阶段 6c —— 录音 → `audio`。**只存 URL，一个字节都不下载**。2026-09-24。

═══ 两个入口，都要问 ═══
① **dump 自带的 `mp3_url`**：韩文版 1,017 ／中文繁 124 ／日文版 54 ／英文版 27
   ⇒ 并集 585 个词形 / 1,348 个文件。**ko 与 ja 不同，ja 三版全是 0。**
② **Commons 分类**：`[[dont-say-source-lacks-what-we-skipped]]` ——
   「dump 里没有」≠「拿不到」。ja 那门原本写着「有意不做」，那个结论是错的。

🔴 **只存 URL**：`upload.wikimedia.org` 是读者 CDN、**有意限流**
（es 实测 8 并发 0.6 条/秒、220 次重试 25 条 429）。播放交给浏览器
（`[[audio-from-commons-not-tts]]`）。

═══ 🔴 Commons 上混着 TTS 合成音，必须分档 ═══
`Category:Pronunciation of Korean words` 里躺着
`Korean text to speech pronouncing Hwang Jun-ho from Squid Game.ogg` ——
那是机器合成的。方针④是**三级兜底：真人 > 工具生成 > 浏览器 TTS**
（`[[dict-scope-four-rules]]`），三级要**在数据里分开**，不是展示层临时判断
（`[[aim-for-perfect-not-cheap]]`）。⇒ `audio.kind` 存 `human` / `tts-tool`。
⚠️ 判据按**文件名里的自述**写（`text to speech` / `TTS` / `synthes`），
   并且把命中的逐条打出来 —— 判不准的宁可报出来，不静默归档。

═══ 重试：越等越久，不是越等越短 ═══
`[[retry-must-converge-or-drop-loud]]` 的「对半切」讲的是**切分片大小**，
不是切等待时间。对限流接口，等得越来越短正好把它惹得更凶。⇒ 2→4→8→16→32 封顶。
⚠️ 一次分类查询失败有两种成因：**分类不存在** vs **我的查询写错/瞬时限流**。
   脚本分不出这两种 ⇒ 失败必须**大声报出来并继续**，不许当成"这个分类是空的"
   （ja 的 `probe_editions` NAMES 表栽过同一个坑）。

跑（在仓库根）：
    python3 -u ko/pipeline/harvest_audio.py
    python3 -u ko/pipeline/harvest_audio.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import gzip
import hashlib
import json
import re
import sqlite3
import subprocess
import time
import urllib.parse

import dbtool
import paths

f = lambda n: format(n, ",")
UA = "synapse-dict/1.0 (dictionary research; non-bulk metadata queries)"
BATCH = 20000
HANGUL = re.compile(r"[가-힣]")
AUDIO_EXT = re.compile(r"\.(wav|ogg|oga|mp3|flac|opus)$", re.I)
# LinguaLibre：`LL-Q9176 (kor)-<录音人>-<词>.wav`（Q9176 ＝ 韩语）
LL = re.compile(r"^LL-Q9176 \(kor\)-([^-]+)-(.+)\.(wav|ogg|oga|mp3|flac|opus)$")
KO = re.compile(r"^Ko-(.+)\.(ogg|oga|wav|mp3|flac|opus)$")
TTS = re.compile(r"text[ _-]?to[ _-]?speech|\bTTS\b|synthes", re.I)

CATS = ["Lingua Libre pronunciation-kor", "Korean pronunciation",
        "South Korean pronunciation", "Korean pronunciation of nouns",
        "Korean pronunciation of verbs", "Korean pronunciation of adjectives",
        "Korean pronunciation of adverbs", "Korean pronunciation of numerals",
        "Korean pronunciation of names", "Korean pronunciation of proper nouns",
        "Korean pronunciation of names of cities",
        "Korean pronunciation of names of countries",
        "Pronunciation of Korean words", "Korean language"]

SRC = [("en-edition", paths.KK), ("ko-edition", paths.EDITION),
       ("zh-edition-simp", paths.ZH_SIMP), ("zh-edition-trad", paths.ZH_TRAD),
       ("ja-edition", paths.JA_EDITION)]


def _op(p):
    return (gzip.open(p, "rt", encoding="utf-8") if str(p).endswith(".gz")
            else open(p, "rt", encoding="utf-8"))


def api(**kw):
    kw.update(action="query", format="json")
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(kw)
    wait = 2.0
    for attempt in range(6):
        out = subprocess.run(["curl", "-s", "-m", "90", "-A", UA, url],
                             capture_output=True, text=True).stdout
        try:
            return json.loads(out)
        except Exception:
            if attempt == 5:
                raise RuntimeError("Commons API 连续 6 次拿不到 JSON：%s" % url)
            time.sleep(wait)
            wait = min(wait * 2, 32)


def _page(listname, keyprefix, **a):
    out, cont = [], None
    while True:
        q = dict(a)
        if cont:
            q[keyprefix + "continue"] = cont
        d = api(list=listname, **q)
        out += [x["title"][5:] for x in d.get("query", {}).get(listname, [])]
        cont = d.get("continue", {}).get(keyprefix + "continue")
        if not cont:
            return out
        time.sleep(0.6)


def cat_files(name):
    return _page("categorymembers", "cm", cmtitle="Category:" + name,
                 cmtype="file", cmlimit="500")


def prefix_files(pref):
    return _page("allimages", "ai", aiprefix=pref, ailimit="500")


def urls(fn):
    """→ (Special:FilePath, 转码 mp3)。⚠️ `url_mp3` 是**转码产物**，不是所有格式都有；
    展示层优先用 `Special:FilePath`（它对任何格式都成立）。"""
    u = fn.replace(" ", "_")
    h = hashlib.md5(u.encode("utf-8")).hexdigest()
    direct = ("https://commons.wikimedia.org/wiki/Special:FilePath/"
              + urllib.parse.quote(u))
    mp3 = ("https://upload.wikimedia.org/wikipedia/commons/transcoded/%s/%s/%s/%s.mp3"
           % (h[0], h[:2], urllib.parse.quote(u), urllib.parse.quote(u)))
    return direct, mp3


def from_dumps():
    """dump 自带的音频。→ {(word, file): {...}}"""
    out = {}
    for src, p in SRC:
        for line in _op(p):
            try:
                o = json.loads(line)
            except Exception:
                continue
            w = (o.get("word") or "").strip()
            if not w:
                continue
            for s in o.get("sounds") or []:
                got = {}
                for k, col in (("mp3_url", "url_mp3"), ("ogg_url", "url_ogg"),
                               ("wav_url", "url_wav"), ("oga_url", "url_other")):
                    if s.get(k):
                        got[col] = s[k]
                if not got:
                    continue
                any_url = next(iter(got.values()))
                fn = urllib.parse.unquote(any_url.rsplit("/", 1)[-1])
                rec = out.setdefault((w, fn), {"word": w, "file": fn, "src": src,
                                               "kind": "human", "ipa": None,
                                               "speaker": None, "region": None})
                rec.update(got)
                for t in s.get("tags") or []:
                    if t in ("Seoul", "SK-Standard", "South-Korea", "North-Korea"):
                        rec["region"] = t
    return out


def from_commons():
    """Commons。**失败大声报出来，不当成空分类。**"""
    got, fail = set(), []
    for c in CATS:
        try:
            v = cat_files(c)
        except Exception as e:
            fail.append(("分类 " + c, str(e)[:60]))
            continue
        print("   %-42s %6s" % (c, f(len(v))))
        got |= set(v)
    for pref in ("LL-Q9176 (kor)-", "Ko-"):
        try:
            v = prefix_files(pref)
        except Exception as e:
            fail.append(("前缀 " + pref, str(e)[:60]))
            continue
        print("   %-42s %6s" % ("前缀 " + pref, f(len(v))))
        got |= set(v)
    return got, fail


def word_of(fn):
    """从文件名抽词形。→ (word, speaker) 或 (None, None)。**抽不出就不收**，不猜。"""
    m = LL.match(fn)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    m = KO.match(fn)
    if m:
        w = m.group(1).strip()
        # `Ko-SK-말하다.ogg` / `Ko-NK-…`：南/北标准的前缀，剥掉才是词形。
        # ⚠️ 剥之后把它记成 region，别丢掉这个信息。
        reg = None
        for pref, r in (("SK-", "South-Korea"), ("NK-", "North-Korea")):
            if w.startswith(pref):
                w, reg = w[len(pref):].strip(), r
        return w, reg
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-net", action="store_true", help="只用 dump 那一路")
    a = ap.parse_args()

    print("■ 入口①：dump 自带的音频")
    dmp = from_dumps()
    bysrc = collections.Counter(v["src"] for v in dmp.values())
    for k, v in bysrc.most_common():
        print("   %-42s %6s" % (k, f(v)))
    print("   %-42s %6s 个文件 / %s 个词形"
          % ("── 并集", f(len(dmp)), f(len({w for w, _ in dmp}))))

    com, fail = set(), []
    if not a.no_net:
        print("\n■ 入口②：Commons（只取元数据，一个字节都不下载）")
        com, fail = from_commons()
        if fail:
            print("   🔴 以下查询**失败了，不是空的** —— 分不出「不存在」还是「我写错了」：")
            for what, why in fail:
                print("      %-34s %s" % (what, why))
        com = {x for x in com if AUDIO_EXT.search(x)}
        print("   %-42s %6s" % ("── 并集（只算音频文件）", f(len(com))))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[0] for r in con.execute("SELECT word FROM dict")}
    lemma = {r[0] for r in con.execute("SELECT word FROM dict WHERE is_lemma=1")}

    rows, stat, tts_seen, nomatch = {}, collections.Counter(), [], collections.Counter()
    for (w, fn), rec in dmp.items():
        if w not in indict:
            stat["跳过·词形不在 dict·dump"] += 1
            continue
        rows[(w, fn)] = rec
        stat["✅ 收·dump"] += 1
    for fn in sorted(com):
        w, spk = word_of(fn)
        if not w:
            nomatch[fn.split("-")[0][:24]] += 1
            stat["跳过·文件名抽不出词形"] += 1
            continue
        if not HANGUL.search(w):
            stat["跳过·抽出来的不是谚文"] += 1
            continue
        if w not in indict:
            stat["跳过·词形不在 dict·commons"] += 1
            continue
        region = None
        if not LL.match(fn):        # KO 分支的第二个返回值是地域不是录音人
            spk, region = None, spk
        kind = "tts-tool" if TTS.search(fn) else "human"
        if kind == "tts-tool":
            tts_seen.append(fn)
        if (w, fn) in rows:
            stat["跳过·dump 已有同一文件"] += 1
            continue
        direct, mp3 = urls(fn)
        rows[(w, fn)] = {"word": w, "file": fn, "src": "commons", "kind": kind,
                         "ipa": None, "speaker": spk, "region": region,
                         "url_mp3": mp3, "url_other": direct}
        stat["✅ 收·commons"] += 1

    print("\n■ 汇总")
    for k, v in sorted(stat.items()):
        print("   %-38s %8s" % (k, f(v)))
    words = {r["word"] for r in rows.values()}
    print("   %-38s %8s 条 / %s 个词形" % ("── 要写的", f(len(rows)), f(len(words))))
    if tts_seen:
        print("\n   ⚠️ 判成 TTS 合成音的（**逐条列出**，不静默归档）：%d" % len(tts_seen))
        for x in tts_seen[:8]:
            print("      %s" % x[:92])
    if nomatch:
        print("\n   ⚠️ 文件名抽不出词形的前缀（报出来，不静默）：")
        print("      " + "  ".join("%s=%d" % kv for kv in nomatch.most_common(10)))

    # 🔴 按**核心词覆盖**问值不值得，不按全库覆盖问（ja 那一课）
    print("\n■ 值不值得做：按**核心词**覆盖问")
    for n in (500, 5000, 20000):
        top = [r[0] for r in con.execute(
            "SELECT word FROM dict WHERE is_lemma=1 AND freq_zipf IS NOT NULL "
            "ORDER BY freq_zipf DESC LIMIT ?", (n,))]
        if not top:
            print("   （`freq_zipf` 还没填，频次层是阶段 6 之后的事 —— 这个数现在问不了）")
            break
        hit = sum(1 for w in top if w in words)
        print("   最常用 %6s 个词元里有录音的：%5.1f%%" % (f(n), 100.0 * hit / len(top)))
    # 🔴 频次层还没建 ⇒ 用**英文版那 5.7 万词头**当核心词的代理，并**说明它是代理**：
    #    它是人工编纂、常用词为主，而那 15.7 万只有中文版有的词头是长尾。
    #    ⚠️ 这不是"核心词覆盖"，是它的下位替代；频次层建好之后**必须回来重问**
    #      （`[[dont-say-source-lacks-what-we-skipped]]`：别让临时口径变成永久结论）。
    core = {r[0] for r in con.execute(
        "SELECT d.word FROM dict d JOIN entry e ON e.word_id=d.id "
        "WHERE e.src='en-edition' AND d.is_lemma=1")}
    if core:
        print("   ⚠️ 代理口径 —— 英文版词头 %s 个（人工编纂、常用词为主）里有录音的："
              "%s（%.2f%%）" % (f(len(core)), f(len(words & core)),
                              100.0 * len(words & core) / len(core)))
    print("   全部词元 %s 个里有录音的：%s（%.2f%%）"
          % (f(len(lemma)), f(len(words & lemma)), 100.0 * len(words & lemma) / len(lemma)))
    before = con.execute("SELECT COUNT(*) FROM audio").fetchone()[0]
    con.close()

    if not a.apply:
        print("\n（这是 dry 跑。加 --apply 才写库）")
        return

    ins = [(r["word"], r["file"], r.get("url_mp3"), r.get("url_ogg"),
            r.get("url_wav"), r.get("url_other"), r.get("ipa"), r.get("speaker"),
            r.get("region"), "dump" if r["src"] != "commons" else "commons-filename",
            r["kind"], r["src"]) for r in rows.values()]
    with dbtool.session(
            "ko-harvest-audio",
            expect={"#audio": len(ins)},
            invalidates=[
                "🔴 `audio.kind` 有 `human` / `tts-tool` 两档 —— 展示层**必须分档**，"
                "方针④是三级兜底（真人 > 工具生成 > 浏览器 TTS），"
                "把合成音与真人录音混成一样就是把方针废掉",
                "只存 URL，一个字节没下载：`upload.wikimedia.org` 有意限流，"
                "播放交给浏览器。任何「预下载」的想法都要先回来读这条",
            ]) as s:
        for i in range(0, len(ins), BATCH):
            s.executemany(
                "INSERT OR IGNORE INTO audio (word, file, url_mp3, url_ogg, url_wav,"
                " url_other, ipa, speaker, region, region_src, kind, src)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ins[i:i + BATCH])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda sql: con.execute(sql).fetchone()[0]
    print("\n■ 写后回核（从库里重算）")
    red = 0
    for name, got, want in [
            ("audio 行数", q("SELECT COUNT(*) FROM audio"), before + len(ins)),
            ("有录音的词形", q("SELECT COUNT(DISTINCT word) FROM audio"), len(words)),
            ("🔴 词形不在 dict 的行",
             q("SELECT COUNT(*) FROM audio a WHERE NOT EXISTS"
               "(SELECT 1 FROM dict d WHERE d.word=a.word)"), 0),
            ("🔴 没有任何 URL 的行",
             q("SELECT COUNT(*) FROM audio WHERE COALESCE(url_mp3,url_ogg,url_wav,"
               "url_other) IS NULL"), 0),
            ("tts-tool 行", q("SELECT COUNT(*) FROM audio WHERE kind='tts-tool'"),
             len(tts_seen))]:
        mark = "✅" if got == want else "🔴"
        red += got != want
        print("   %s %-30s %9s  期望 %9s" % (mark, name, f(got), f(want)))
    con.close()
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


if __name__ == "__main__":
    main()
