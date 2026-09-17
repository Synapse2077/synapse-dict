#!/usr/bin/env python3
"""阶段 6 —— Commons 真人录音 → `audio`。2026-09-16。

═══ 🔴🔴 这一步原来标着「有意不做」，那个结论是错的 ═══
`JA_PLAN` 和 `ja/paths.py` 都写着：

    三版并集只有 206 个词形有 `mp3_url` …… **别排工**，要发音只能走 Commons 直查

**事实是对的**（我全量重扫过：英文版 4 ／日语版 84 ／中文版 144 个词形），
**结论是错的**。那句话把「dump 里没有」等同于「拿不到」——
正是 `[[dont-say-source-lacks-what-we-skipped]]` 说的那条：
**「源头没写」和「我们没抽」要在结构上分开**。

前六门的录音全部来自**语言版 dump 自带的 `mp3_url`**（de 一百万条就是这么来的），
而日语版维基词典**不在词条里嵌音频**。⇒ 对日语，dump 根本不是录音的来源，
**Commons 的分类才是**。同样零下载、同样只存 URL，只是入口换一个。

═══ Commons 上到底有多少（实测，不是估计）═══
    Lingua Libre pronunciation-jpn      1,043
    Japanese pronunciation（顶层）         248
    其余 9 个子分类 + `Ja-` 前缀            ~690
    ⇒ 去重后约 1,500 个文件

对照 LinguaLibre 各语种：法语 436,115 ／德语 26,112 ／意语 12,637 ／葡语 9,587。
**日语在维基生态里确实被录得极少**，这一点原来的判断没错。

═══ 那还值不值得做？按**核心词覆盖**问，不按全库覆盖问 ═══
    最常用    500 个词元里有录音的：10.4%
    最常用  5,000 个                  5.4%
    最常用 20,000 个                  2.3%

零成本、零下载、一次脚本。方针④本来就是**三级兜底**（真人 > 工具生成 > 浏览器 TTS，
`[[dict-scope-four-rules]]`），从不要求真人录音全覆盖 ——
**793 个常用词上的真人录音严格优于 0 个**。
⚠️ 合成音这一档**不做**：it 那轮用户试听判定质量不够、产物已删（`[[it-tts-layer]]`）。

═══ 🔴 只存 URL，一个字节都不下载 ═══
`[[audio-from-commons-not-tts]]`：`upload.wikimedia.org` 是读者 CDN、**有意限流**
（es 实测 8 并发 0.6 条/秒、220 次重试 25 条 429）。播放交给浏览器。

用法（在仓库根）：
    python3 -u ja/pipeline/harvest_audio.py
    python3 -u ja/pipeline/harvest_audio.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
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
CATS = ["Japanese pronunciation",
        "Japanese vocabulary pronunciation from WaniKani and Tofugu",
        "Japanese pronunciation of names", "Japanese pronunciation of names of cities",
        "Japanese pronunciation of names of countries",
        "Japanese pronunciation of numbers",
        "Pronunciation of names of places in Japan",
        "Pronunciation of Japanese syllables",
        "Japanese audio files from Wikibooks",
        "Lingua Libre pronunciation-jpn"]
# LinguaLibre：`LL-Q5287 (jpn)-<录音人>-<词>.wav`
LL = re.compile(r"^LL-Q5287 \(jpn\)-([^-]+)-(.+)\.(wav|ogg|oga|mp3|flac)$")
JA = re.compile(r"^Ja-(.+)\.(ogg|oga|wav|mp3|flac)$")


def api(**kw):
    """Commons API。🔴 重试**对半切 + 封顶 + 到顶大声放弃**，不静默丢也不无限重试
    （`[[retry-must-converge-or-drop-loud]]`）。"""
    kw.update(action="query", format="json")
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(kw)
    # 🔴 退避是**越等越久**（2→4→8→16→32，封顶 32 秒），不是越等越短。
    #    第一版我写成 `wait /= 2` —— 把 `[[retry-must-converge-or-drop-loud]]` 里
    #    「对半切」照搬了过来，而那条讲的是**切分片大小**（让每次重试的活儿更小、
    #    保证收敛），不是切等待时间。对**限流**的接口，等得越来越短正好把它惹得更凶。
    #    ⚠️ 同一句话在两种场景里指向相反的动作 —— 照抄措辞而不是照抄意图，就会反着做。
    wait = 2.0
    for attempt in range(5):
        out = subprocess.run(["curl", "-s", "-m", "40", "-A", UA, url],
                             capture_output=True, text=True).stdout
        try:
            return json.loads(out)
        except Exception:
            if attempt == 4:
                raise RuntimeError("Commons API 连续 5 次拿不到 JSON：%s" % url)
            time.sleep(wait)
            wait = min(wait * 2, 32)


def cat_files(name):
    out, cont = [], None
    while True:
        a = {"list": "categorymembers", "cmtitle": "Category:" + name,
             "cmtype": "file", "cmlimit": "500"}
        if cont:
            a["cmcontinue"] = cont
        d = api(**a)
        out += [x["title"][5:] for x in d.get("query", {}).get("categorymembers", [])]
        cont = d.get("continue", {}).get("cmcontinue")
        if not cont:
            return out
        time.sleep(1.0)      # 翻页之间歇一口气，别把限流惹起来


def prefix_files(pref):
    out, cont = [], None
    while True:
        a = {"list": "allimages", "aiprefix": pref, "ailimit": "500"}
        if cont:
            a["aicontinue"] = cont
        d = api(**a)
        out += [x["title"][5:] for x in d.get("query", {}).get("allimages", [])]
        cont = d.get("continue", {}).get("aicontinue")
        if not cont:
            return out
        time.sleep(1.0)


def urls(fn):
    """→ (Special:FilePath, 转码 mp3)。与 de 存的形状一致。

    Commons 的物理路径是 md5(下划线文件名) 的前 1 / 前 2 位做目录。
    ⚠️ `url_mp3` 是**转码产物**，不是所有格式都有；拿不准的靠 `url_other` 兜底，
       展示层优先用 `Special:FilePath`（它对任何格式都成立）。
    """
    u = fn.replace(" ", "_")
    h = hashlib.md5(u.encode("utf-8")).hexdigest()
    direct = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(u)
    mp3 = ("https://upload.wikimedia.org/wikipedia/commons/transcoded/%s/%s/%s/%s.mp3"
           % (h[0], h[:2], urllib.parse.quote(u), urllib.parse.quote(u)))
    return direct, mp3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    files = set()
    for c in CATS:
        got = cat_files(c)
        files |= set(got)
        print("   %5s  %s" % (f(len(got)), c), flush=True)
    got = prefix_files("Ja-")
    files |= set(got)
    print("   %5s  前缀 Ja-" % f(len(got)), flush=True)
    print("■ 去重后文件 %s" % f(len(files)), flush=True)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()

    # ── 第四个来源：三版 dump 里嵌着的那 232 个 ──
    # 🔴 它**直接给了「词 ↔ 文件」的对应**，比从文件名反推可靠。
    #    量小不代表不要：`[[cross-edition-harvest]]` 的规矩是各版独有的那部分才是真增量。
    import gzip
    dump_pairs = {}
    for name, op, lc in [("en-edition", lambda: open(paths.KK, encoding="utf-8"), None),
                         ("ja-edition", lambda: open(paths.EDITION, encoding="utf-8"), None),
                         ("zh-edition", lambda: gzip.open(paths.ZH_EDITION, "rt",
                                                          encoding="utf-8"), "ja")]:
        with op() as fh:
            for line in fh:
                if '"sounds"' not in line:
                    continue
                o = json.loads(line)
                if lc and o.get("lang_code") != lc:
                    continue
                for snd in o.get("sounds") or []:
                    fn = snd.get("audio")
                    if fn and o["word"] in have:
                        dump_pairs.setdefault((o["word"], fn.replace("_", " ")), name)
    print("■ dump 内嵌录音 %s 条（词 %s 个）"
          % (f(len(dump_pairs)), f(len({w for w, _ in dump_pairs}))), flush=True)

    rows, st = {}, collections.Counter()
    for fn in sorted(files):
        m = LL.match(fn)
        if m:
            speaker, w = m.group(1), m.group(2)
        else:
            m = JA.match(fn)
            if not m:
                st["⚪ 文件名不认识的形状"] += 1
                continue
            speaker, w = None, m.group(1)
        # `Ja-nippon(日本).ogg` 这种把词写在括号里；括号外是罗马字
        b = re.match(r"^[A-Za-z0-9_'\- ]+\((.+)\)$", w)
        if b:
            w = b.group(1)
        w = w.replace("_", " ").strip()
        if w not in have:
            st["⚪ 词形不在库里（多为罗马字/外语）"] += 1
            continue
        direct, mp3 = urls(fn)
        ext = fn.rsplit(".", 1)[-1].lower()
        rows[(w, fn)] = (
            w, fn,
            mp3,
            direct if ext in ("ogg", "oga") else None,
            direct if ext == "wav" else None,
            direct if ext not in ("ogg", "oga", "wav") else None,
            None, speaker, None, None, "human", "commons")
        st["⭐ 收下（Commons 分类）"] += 1
    for (w, fn), name in dump_pairs.items():
        if (w, fn) in rows:
            st["⚪ dump 的这条分类里已有"] += 1
            continue
        direct, mp3 = urls(fn)
        ext = fn.rsplit(".", 1)[-1].lower()
        rows[(w, fn)] = (w, fn, mp3,
                         direct if ext in ("ogg", "oga") else None,
                         direct if ext == "wav" else None,
                         direct if ext not in ("ogg", "oga", "wav") else None,
                         None, None, None, None, "human", name)
        st["⭐ 收下（dump 独有）"] += 1
    for k in sorted(st):
        print("   %-40s %s" % (k, f(st[k])))
    words = {w for w, _ in rows}
    print("\n■ 录音 %s 条，覆盖词形 %s" % (f(len(rows)), f(len(words))))
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        for (w, fn) in list(rows)[:6]:
            print("   %-12s %s" % (w, fn))
        return

    # 🔴 落库前抽验 URL 真的活着 —— **存死链比不存更坏**（读者点了没反应，
    #    而库里那一列看着是"有录音"）。只发 HEAD，不下载正文。
    print("\n■ 抽 8 条发 HEAD 验活（不下载正文）", flush=True)
    bad = 0
    for (w, fn) in list(rows)[:8]:
        d = rows[(w, fn)]
        u = d[3] or d[4] or d[5] or d[2]
        code = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                               "-I", "-L", "-m", "30", "-A", UA, u],
                              capture_output=True, text=True).stdout.strip()
        ok = code.startswith("2")
        bad += not ok
        print("   %s %s  %s" % ("✅" if ok else "🔴 " + code, w, fn[:52]), flush=True)
    if bad:
        print("\n🔴 有死链，不写库。")
        _sys.exit(1)

    with dbtool.session("ja-harvest-audio", expect={
            "#audio": len(rows), "__rows__": 0, "#entry": 0, "#sense": 0,
            "#example": 0, "#sense_relation": 0}) as con:
        con.executemany(
            "INSERT OR IGNORE INTO audio(word,file,url_mp3,url_ogg,url_wav,url_other,"
            "ipa,speaker,region,region_src,kind,src) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            list(rows.values()))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("每条录音的词形都在库里", q(
            "SELECT COUNT(*) FROM audio a LEFT JOIN dict d ON d.word=a.word "
            "WHERE d.id IS NULL") == 0),
        ("kind 一律 human（本步不产合成音）", q(
            "SELECT COUNT(*) FROM audio WHERE kind<>'human'") == 0),
        ("每条都至少有一个可播的 URL", q(
            "SELECT COUNT(*) FROM audio WHERE COALESCE(url_ogg,url_wav,url_other,"
            "url_mp3) IS NULL") == 0),
        # 🔴 断言的是**目的**：核心词上确实听得到东西，而不是"表里有几行"。
        ("最常用 500 个词元里有录音的 > 30 个", q(
            "SELECT COUNT(*) FROM (SELECT word FROM dict WHERE freq_zipf IS NOT NULL "
            "ORDER BY freq_zipf DESC LIMIT 500) t "
            "WHERE EXISTS(SELECT 1 FROM audio a WHERE a.word=t.word)") > 30),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    for n, lab in [(500, "最常用   500"), (5000, "最常用 5,000")]:
        hit = q("SELECT COUNT(*) FROM (SELECT word FROM dict WHERE freq_zipf IS NOT NULL "
                "ORDER BY freq_zipf DESC LIMIT %d) t "
                "WHERE EXISTS(SELECT 1 FROM audio a WHERE a.word=t.word)" % n)
        print("   %s 个词元有录音：%s = %.1f%%" % (lab, f(hit), 100 * hit / n))
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
