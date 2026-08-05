#!/usr/bin/env python3
"""录音入库：七个源的真人录音元数据，单独成表。2026-08-04。

═══ 只存元数据，不存字节 ═══
库里只放 文件名 / URL / 录音人 / 地区。音频**内容**不进 SQLite ——
单条 mp3 约 20–60 KB，11,203 条合计 300–600 MB，比整个词典库还大。
后果不是"占地方"，是 `dbtool` 每次写库前要**全文件复制备份**：
现在 360 MB / 0.6 秒，塞进音频后每改一行译文都要复制 1 GB。
⇒ **URL 进库，字节进文件系统。** 真要离线化就在 `data/audio/` 按需缓存，
   库里再加一列记本地路径即可，表结构不用动。

═══ 录音的身份是文件名，不是 URL ═══
🔴 同一条录音在 Commons 上同时有 mp3/ogg/wav/flac 多个 URL（转码产物）。
   第一次按 URL 去重，11,203 条被算成 22,367 —— **整整多了一倍**。
   按 `(word, audio文件名)` 才是一条录音。

═══ 地区靠"录音人"推，不靠逐条标注 ═══
实测 11,203 条里带地区 tag 的只有 1,303 条（11.6%），直接用覆盖太低。
但文件名能解析出**录音人**的有 92.3%，而**录音人只有 73 位**，一个人的口音是固定的。
于是：先用带 tag 的录音给录音人投票定地区，再回填给他所有录音。
    Marreromarco     4,597 条，472 条带 tag，**472/472 全是 Venezuela**
    AdrianAbdulBaha  2,536 条，428 条带 tag，427 Colombia / 1 Venezuela（噪声，取多数）
    Millars / Rodelar → Spain    Rodrigo5260 → Peru    Rubýñ → Costa-Rica
14 位录音人能定地区，他们的录音占 LinguaLibre 族的 **89.8%**。

🔴 **推来的和标来的必须分开记**（`region_src`：tag / speaker / filename）。
   这是项目铁律⑦"写入时记来源，不靠事后考古"——考古会错。

═══ 两族文件名 ═══
    LinguaLibre  `LL-Q1321 (spa)-Rodelar-Japón.wav`  → Q1321=西语, Rodelar=录音人
    早期单条上传 `Es-catalán-bo-La Paz.ogg`          → bo=玻利维亚, La Paz=录制地
剩下 347 条（`Hacer.ogg`、`Gracias (español).ogg`）无结构，录音人和地区都留空，不猜。

═══ 闸门 ═══
建新表不碰 `dict` ⇒ `expect={}`。
⚠️ `dbtool.snapshot()` 只统计 `dict` 的列，新表在它视野外，本脚本自己做去重断言。
"""
import argparse
import collections
import gzip
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dbtool                                                    # noqa: E402
import paths                                                     # noqa: E402

DUMPS = paths.DUMPS
SOURCES = [
    ("es-edition", paths.EDITION, "gz"),
    ("en-edition", paths.KK, "txt"),
    ("fr-edition", DUMPS / "frwiktionary.jsonl.gz", "gz"),
    ("de-edition", DUMPS / "dewiktionary.jsonl.gz", "gz"),
    ("it-edition", DUMPS / "itwiktionary.jsonl.gz", "gz"),
    ("pt-edition", DUMPS / "ptwiktionary.jsonl.gz", "gz"),
    ("zh-edition", DUMPS / "zhwiktionary.jsonl.gz", "gz"),
]
URL_KEYS = ("mp3_url", "ogg_url", "wav_url", "flac_url", "oga_url")
LL = re.compile(r"^LL-Q\d+\s*\([a-z]{3}\)-([^-]+)-")
ES = re.compile(r"^[Ee]s[-_](.+?)[-_]([a-z]{2})[-_](.+)\.\w+$")
# tag 里的地区写法归一（`Colombian`→`Colombia`；`America`/`US` 太糊，不当地区）
REGION_FIX = {"Colombian": "Colombia", "Costa-Rica": "Costa Rica"}
REGION_SKIP = {"America", "US", "Latin-America"}
# 🔴 `region` 一列里绝不能同时出现国家名和国家码。Es- 族文件名给的是两位码
# （`Es-catalán-bo-La Paz.ogg`），tag 给的是国家名（`Spain`/`Colombia`）——
# 混在一起的列，将来任何按地区筛选的查询都会静默漏掉一半。实测只有两个码，写死即可。
CODE2NAME = {"bo": "Bolivia", "mx": "Mexico"}

DDL = """
CREATE TABLE IF NOT EXISTS audio (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  word       TEXT NOT NULL,
  file       TEXT NOT NULL,     -- Commons 文件名 = 录音身份（去重靠它，不是 URL）
  url_mp3    TEXT,
  url_ogg    TEXT,
  url_wav    TEXT,
  url_other  TEXT,              -- flac / oga，罕见
  ipa        TEXT,              -- 这条录音对应哪个读音（同词多读音时配对用）
  speaker    TEXT,              -- 从文件名解析
  region     TEXT,
  region_src TEXT,              -- tag(标注) / speaker(按录音人推) / filename(国家码)
  kind       TEXT NOT NULL,     -- human / tts-tool / browser-tts（方针④三级兜底）
  src        TEXT NOT NULL,     -- 哪个版本给的
  UNIQUE(word, file)
)
"""
IDX = ["CREATE INDEX IF NOT EXISTS idx_audio_word ON audio(word)",
       "CREATE INDEX IF NOT EXISTS idx_audio_speaker ON audio(speaker)"]


def opener(path, kind):
    if kind == "gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def clean_region(tags):
    for t in tags or []:
        t = REGION_FIX.get(t, t)
        if t and t not in REGION_SKIP and re.match(r"^[A-Z]", t):
            return t
    return None


def harvest():
    """→ {(word, file): dict}，按 SOURCES 顺序先到先得。"""
    rec, stat = {}, collections.Counter()
    for src, path, kind in SOURCES:
        if not Path(path).exists():
            print("   ⚠️ 缺文件，跳过：%s" % path)
            continue
        t, got = time.time(), 0
        with opener(path, kind) as fh:
            for ln in fh:
                if '"lang_code": "es"' not in ln:
                    continue
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if e.get("lang_code") != "es":
                    continue
                w = e.get("word")
                if not w:
                    continue
                for s in e.get("sounds") or []:
                    urls = {k: s.get(k) for k in URL_KEYS if s.get(k)}
                    if not urls:
                        continue
                    fn = s.get("audio")
                    if not fn:
                        stat["有URL但无文件名，跳过"] += 1
                        continue
                    key = (w, fn)
                    if key in rec:
                        stat["重复（已有更优先的源）"] += 1
                        continue
                    rec[key] = {
                        "word": w, "file": fn,
                        "mp3": urls.get("mp3_url"), "ogg": urls.get("ogg_url"),
                        "wav": urls.get("wav_url"),
                        "other": urls.get("flac_url") or urls.get("oga_url"),
                        "ipa": (s.get("ipa") or "").strip() or None,
                        "tags": s.get("tags") or [],
                        "src": src,
                    }
                    got += 1
        print("   %-12s +%-6d 条  (%.0fs)" % (src, got, time.time() - t))
        stat["收自 " + src] = got
    return rec, stat


def enrich(rec):
    """解析录音人；再用带 tag 的录音给录音人投票定地区，回填给他全部录音。"""
    for r in rec.values():
        m = LL.match(r["file"])
        if m:
            r["speaker"] = m.group(1).strip()
        else:
            r["speaker"] = None
        r["region"] = clean_region(r["tags"])
        r["region_src"] = "tag" if r["region"] else None
        if not r["region"]:
            m2 = ES.match(r["file"])
            if m2:
                code = m2.group(2)
                r["region"] = CODE2NAME.get(code)   # 认不出的码宁可留空，不写半成品
                r["region_src"] = "filename" if r["region"] else None

    vote = collections.defaultdict(collections.Counter)
    for r in rec.values():
        if r["speaker"] and r["region_src"] == "tag":
            vote[r["speaker"]][r["region"]] += 1
    spk_region = {sp: c.most_common(1)[0][0] for sp, c in vote.items()}

    filled = 0
    for r in rec.values():
        if not r["region"] and r["speaker"] in spk_region:
            r["region"] = spk_region[r["speaker"]]
            r["region_src"] = "speaker"
            filled += 1
    return spk_region, filled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    print("■ 扫七个源")
    rec, stat = harvest()
    print("\n■ 去重后 %d 条录音（重复丢弃 %d；有URL无文件名 %d）"
          % (len(rec), stat["重复（已有更优先的源）"], stat["有URL但无文件名，跳过"]))

    spk_region, filled = enrich(rec)
    nspk = len({r["speaker"] for r in rec.values() if r["speaker"]})
    print("■ 录音人 %d 位；其中 %d 位能从 tag 定地区，回填 %d 条"
          % (nspk, len(spk_region), filled))
    for sp, rg in sorted(spk_region.items(), key=lambda x: -sum(
            1 for r in rec.values() if r["speaker"] == x[0]))[:6]:
        n = sum(1 for r in rec.values() if r["speaker"] == sp)
        print("     %-24s → %-12s (%d 条)" % (sp, rg, n))

    by_src = collections.Counter(r["region_src"] or "(无)" for r in rec.values())
    print("■ 地区来源分布：%s" % dict(by_src))
    print("   有地区的合计 %d / %d = %.1f%%"
          % (len(rec) - by_src["(无)"], len(rec),
             (len(rec) - by_src["(无)"]) / len(rec) * 100))
    print("   有 ipa 的 %d ｜ 有 mp3 的 %d"
          % (sum(1 for r in rec.values() if r["ipa"]),
             sum(1 for r in rec.values() if r["mp3"])))

    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    known = {w for (w,) in conn.execute("SELECT DISTINCT word FROM dict")}
    conn.close()
    words = {r["word"] for r in rec.values()}
    orphan = words - known
    print("   覆盖词形 %d（库里有 %d，库里没有 %d ⇒ 照存不丢）"
          % (len(words), len(words - orphan), len(orphan)))

    samples = [(r["word"], (r["speaker"] or "-")[:16], (r["region"] or "-"),
                r["region_src"] or "-") for r in list(rec.values())[:12]]
    dbtool.sample_check(samples, 12, ("词", "录音人", "地区", "地区来源"))

    if not a.apply:
        print("\n(预览。确认后 --apply)")
        return

    plan = [(r["word"], r["file"], r["mp3"], r["ogg"], r["wav"], r["other"],
             r["ipa"], r["speaker"], r["region"], r["region_src"], "human", r["src"])
            for r in rec.values()]
    with dbtool.session("ingest-audio", expect={}) as s:
        s.execute(DDL)
        for q in IDX:
            s.execute(q)
        s.executemany(
            "INSERT OR IGNORE INTO audio "
            "(word,file,url_mp3,url_ogg,url_wav,url_other,ipa,speaker,region,region_src,kind,src) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", plan)

    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n = conn.execute("SELECT COUNT(*) FROM audio").fetchone()[0]
    d = conn.execute("SELECT COUNT(*) FROM (SELECT 1 FROM audio GROUP BY word,file)").fetchone()[0]
    conn.close()
    print("■ audio 表现有 %d 行（唯一 word+file %d）" % (n, d))
    assert n == d, "去重断言失败"
    print("■ 去重断言通过 ✓")


if __name__ == "__main__":
    main()
