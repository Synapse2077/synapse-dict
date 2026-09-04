#!/usr/bin/env python3
"""阶段 6 —— 收割 Commons 真人录音的 URL → `audio`。2026-09-03。

═══ 只落 URL，零网络请求 ═══
`[[audio-from-commons-not-tts]]`：发音走 Wikimedia Commons 的**真人录音**，不做 TTS；
语言版 dump 直接带 `mp3_url`/`ogg_url`，**一个字节都不用下载**。
🔴 那条记忆同时记着别去下：`upload.wikimedia.org` 是读者 CDN、**有意限流**
   （es 实测 8 并发只涨到 0.6 条/秒、220 次重试 25 条 429，全量要 6–9 小时）。
   ⇒ 本步只存链接，播放交给浏览器。

═══ 三版一起收，去重靠**文件名**不靠 URL ═══
同一条录音会出现在多个语言版里，但 Commons 文件名是它的身份
（表上的 `UNIQUE(word, file)` 就是这么设计的）。
⇒ 德语版 + 英文版 + 法语版一起扫，天然合并；各版独有的部分才是真增量。

═══ 🔴 region：有证据才写，判不出留空 ═══
实测德语版文件名前缀（15 万条目样本）：
    De-      164,211 (95.5%)   ← **只表示"德语"，不表示"德国"**
    De-at-     3,750           ← 奥地利，明确
    LL-Q188    3,123           ← LinguaLibre，文件名里带录音人
    de- / DE-    130           ← 同 `De-`，大小写不同
    Bar- / BY-    30           ← 巴伐利亚
    En- / Fr-     10           ← **别的语言的录音混进了德语条目**

⚠️ **`De-` 一律不写 region。** 它只说明这是德语录音，不说明录音人在德国。
   `[[ipa-provenance-columns]]`：证明不了就别填。95% 留空是**诚实**，
   不是覆盖率低 —— 读者要的是"标准德语发音"，region 只用来标出奥/瑞变体。
⚠️ `region_src` 记下**这个地区是怎么判出来的**（tag / filename），
   下一轮想收紧或推翻某一路时，能只动那一路。

═══ 🔴 kind：本步一律 human ═══
方针④三级兜底（真人 > 工具生成 > 浏览器 TTS，`[[dict-scope-four-rules]]`）。
Commons 上的是真人录音 ⇒ `human`。合成音是另一步的事，**it 那轮实测被用户判定
质量不够、产物已删**（`[[it-tts-layer]]`），de 不主动做。

用法（在 de/ 目录下）：
    python3 -u pipeline/harvest_audio.py           # 干跑
    python3 -u pipeline/harvest_audio.py --apply
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402
from intake_edition_words import EDITIONS         # noqa: E402

f = lambda n: format(n, ",")
EDS = ("de", "en", "fr")            # 计划表实测：录音最富的三版

# ── region：两条路，各自留痕 ────────────────────────────────────────────
TAG_REGION = {
    "Austrian German": "de-AT", "Österreichisch": "de-AT", "Austria": "de-AT",
    "Swiss Standard German": "de-CH", "Switzerland": "de-CH", "Schweiz": "de-CH",
}
FILE_REGION = [
    (re.compile(r"^De-at-", re.I), "de-AT"),
    (re.compile(r"^De-ch-", re.I), "de-CH"),
]
# 🔴 别的语言的录音混进了德语条目（实测 `En-` `Fr-` 各 5 条）——
#    判据按**含义**：文件名前缀声明的语言不是德语。不是按长度/形状猜。
FOREIGN = re.compile(r"^(En|Fr|Es|It|Pt|Nl|Pl|Ru|Cs|Da|Sv|No|Fi|Hu|Tr)-", re.I)
# LinguaLibre：`LL-Q188 (deu)-录音人-词.wav`
LL = re.compile(r"^LL-Q\d+\s*\([a-z]{3}\)-([^-]+)-")


def opener(p):
    p = Path(p)
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def region_of(file, tags):
    """→ (region, region_src)。判不出返回 (None, None)，**不猜**。"""
    for t in tags:
        if t in TAG_REGION:
            return TAG_REGION[t], "tag"
    for rx, r in FILE_REGION:
        if rx.match(file):
            return r, "filename"
    return None, None


def harvest(words):
    rows, stat, seen = [], Counter(), set()
    for ed in EDS:
        path, need_filter = EDITIONS[ed]
        print("   扫 %s 版…" % ed)
        with opener(path) as fh:
            for line in fh:
                if '"audio"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if need_filter and e.get("lang_code") != "de":
                    continue
                w = e.get("word") or ""
                if w not in words:
                    continue
                for s in e.get("sounds") or []:
                    fn = (s.get("audio") or "").strip()
                    if not fn:
                        continue
                    stat["源头录音条数"] += 1
                    if FOREIGN.match(fn):
                        stat["🔴 丢：别的语言的录音混进德语条目"] += 1
                        continue
                    k = (w, fn)
                    if k in seen:
                        stat["重复（同词同文件，多版共享）"] += 1
                        continue
                    seen.add(k)
                    tags = list(s.get("tags") or []) + list(s.get("raw_tags") or [])
                    reg, rsrc = region_of(fn, tags)
                    m = LL.match(fn)
                    other = s.get("oga_url") or s.get("flac_url")
                    rows.append((w, fn, s.get("mp3_url"), s.get("ogg_url"),
                                 s.get("wav_url"), other,
                                 (s.get("ipa") or "").strip().strip("/[]\\") or None,
                                 m.group(1) if m else None,
                                 reg, rsrc, "human", "%s-edition" % ed))
                    stat["收下（%s 版）" % ed] += 1
                    if reg:
                        stat["  判出地区（%s）" % rsrc] += 1
    return rows, stat


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("audio 行数 == 期望", q("SELECT count(*) FROM audio"), expect["rows"]),
        ("🔴 词形不在 dict",
         q("SELECT count(*) FROM audio a LEFT JOIN dict d ON d.word=a.word "
           "WHERE d.id IS NULL"), 0),
        ("🔴 一个 URL 都没有", q("SELECT count(*) FROM audio WHERE "
                            "COALESCE(url_mp3,url_ogg,url_wav,url_other) IS NULL"), 0),
        ("🔴 文件名为空", q("SELECT count(*) FROM audio WHERE TRIM(file)=''"), 0),
        ("region 值域外", q("SELECT count(*) FROM audio WHERE region IS NOT NULL "
                          "AND region NOT IN ('de-AT','de-CH')"), 0),
        # 🔴 有 region 必有 region_src：不许出现"说不清哪来的"的地区值
        ("🔴 有地区却说不出是怎么判的",
         q("SELECT count(*) FROM audio WHERE region IS NOT NULL AND region_src IS NULL"), 0),
        ("kind 值域外", q("SELECT count(*) FROM audio WHERE kind NOT IN "
                        "('human','tts-tool','browser-tts')"), 0),
        ("🔴 同词同文件重复",
         q("SELECT count(*) FROM (SELECT word,file FROM audio GROUP BY 1,2 HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-42s %10s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()
    print("■ 库内词形 %s" % f(len(words)))

    print("\n■ 扫三版…")
    rows, stat = harvest(words)
    for k, v in stat.most_common():
        print("   %-38s %s" % (k, f(v)))

    cov = len({r[0] for r in rows})
    n_reg = sum(1 for r in rows if r[8])
    n_spk = sum(1 for r in rows if r[7])
    print("\n■ 收下 %s 条 ／ 覆盖词形 %s ／ 判出地区 %s ／ 有录音人 %s"
          % (f(len(rows)), f(cov), f(n_reg), f(n_spk)))
    print("   ⚠️ 其余 %s 条 region 留空 —— `De-` 前缀只表示「德语」，不表示「德国」，**不猜**"
          % f(len(rows) - n_reg))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    print("\n■ 将写入 audio %s 行" % f(len(rows)))
    with dbtool.session("keep-v3-6-audio", expect={"#audio": len(rows)}) as s:
        s.executemany(
            "INSERT OR IGNORE INTO audio "
            "(word,file,url_mp3,url_ogg,url_wav,url_other,ipa,speaker,region,region_src,kind,src) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n = con.execute("SELECT count(*) FROM audio").fetchone()[0]
    ok = gate2(con, {"rows": n})
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
