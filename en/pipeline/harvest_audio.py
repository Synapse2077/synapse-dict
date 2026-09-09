#!/usr/bin/env python3
"""阶段 6：录音元数据 → `audio`。**只落 URL，零下载、零成本。**2026-09-08。

🔴 **不下载**：`upload.wikimedia.org` 是读者 CDN、**有意限流**
   （`[[audio-from-commons-not-tts]]`；es 实测 8 并发 0.6 条/秒、220 次重试 25 条 429，
   全量 6–9 小时）⇒ 播放交给浏览器。

═══ 判据（照 de/pt 的教训，但每条都在 en 上重验）═══
① **去重靠 Commons 文件名，不靠 URL** —— 同一条录音在各版 URL 不同
   （有的给 `Special:FilePath`、有的给 transcoded 直链），**文件名才是它的身份**。
   表上 `UNIQUE(word, file)` 就是这么设计的。
② **挡掉别的语言的录音**：英语条目里混进 `De-`/`Fr-`/`Nl-` 前缀的文件是别的语言的读音。
③ **地区判不出就留空，不猜**（`[[ipa-provenance-columns]]`）。判出来的必须记 `region_src`，
   下一轮想推翻某一路能只动那一路。
   ⚠️ de 那轮 **95% 有意留空**：文件名前缀 `De-` 只表示"**德语**录音"，
      不表示"录音人在**德国**"。en 的 `En-us-`/`En-uk-` **确实带地区**，
      但这要**量出来**再用，不能因为 de 那样就假设 en 也一样。
④ `kind='human'` —— Commons 是真人录音，不做 TTS（收录方针④）。

    cd en && python3 -u pipeline/harvest_audio.py          # 干跑：量形状
    cd en && python3 -u pipeline/harvest_audio.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import re
import sqlite3

import dbtool
import paths

SRC = "en-edition"
# 文件名里的语言前缀：不是 En-/en- 的，是别的语言混进来的
OTHER_LANG = re.compile(r"^(de|fr|nl|es|it|pt|ru|pl|cs|sv|da|no|fi|ja|zh|ko|ar|he|tr|hu|ro|el)[-_]",
                        re.I)
# `En-us-cat.ogg` / `en-uk-word.ogg` / `En-au-...` / `En-us-Northeast-...`
FN_REGION = re.compile(r"^en[-_]([a-z]{2})[-_]", re.I)
REGION_MAP = {"us": "en-US", "uk": "en-GB", "gb": "en-GB", "au": "en-AU",
              "ca": "en-CA", "nz": "en-NZ", "ie": "en-IE", "za": "en-ZA", "in": "en-IN"}
TAG_REGION = {"US": "en-US", "General-American": "en-US", "GA": "en-US", "American": "en-US",
              "UK": "en-GB", "RP": "en-GB", "Received-Pronunciation": "en-GB",
              "British": "en-GB", "England": "en-GB",
              "Australia": "en-AU", "Canada": "en-CA", "New-Zealand": "en-NZ",
              "Ireland": "en-IE", "South-Africa": "en-ZA", "India": "en-IN"}
# `LL-Q1860 (eng)-Speaker Name-word.wav`
LL = re.compile(r"^LL-Q\d+\s*\([a-z]{3}\)-(.+?)-", re.I)


def collect(con):
    words = {w for (w,) in con.execute("SELECT word FROM dict")}
    rows, seen = [], set()
    stat = collections.Counter()
    reg_src = collections.Counter()
    spk = collections.Counter()
    for line in paths.KK.open(encoding="utf-8"):
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("source") == "thesaurus":
            continue
        w = o.get("word")
        if w not in words:
            continue
        for s in o.get("sounds") or []:
            f = (s.get("audio") or "").strip()
            if not f:
                continue
            stat["源"] += 1
            if OTHER_LANG.match(f):
                stat["🔴 别的语言的录音（挡掉）"] += 1
                continue
            key = (w, f)
            if key in seen:
                stat["去重"] += 1
                continue
            seen.add(key)
            tags = s.get("tags") or []
            # 地区三级：tag → 文件名 → （speaker 留待量完再定）
            reg = next((TAG_REGION[t] for t in tags if t in TAG_REGION), None)
            rsrc = "tag" if reg else None
            if not reg:
                m = FN_REGION.match(f)
                if m and m.group(1).lower() in REGION_MAP:
                    reg, rsrc = REGION_MAP[m.group(1).lower()], "filename"
            if reg:
                reg_src[rsrc] += 1
            else:
                reg_src["(判不出，留空)"] += 1
            m = LL.match(f)
            speaker = m.group(1).strip() if m else None
            if speaker:
                spk[speaker] += 1
            rows.append((w, f, s.get("mp3_url"), s.get("ogg_url"), s.get("wav_url"),
                         s.get("oga_url") or s.get("flac_url"),
                         s.get("audio-ipa") or s.get("ipa"), speaker, reg, rsrc,
                         "human", SRC))
            stat["入库"] += 1
    return rows, stat, reg_src, spk


def gates(con, n, reg_src):
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("audio 行数", q("SELECT COUNT(*) FROM audio"), n),
        ("word 全在 dict 里",
         q("SELECT COUNT(*) FROM audio a LEFT JOIN dict d ON d.word=a.word "
           "WHERE d.id IS NULL"), 0),
        ("file 非空", q("SELECT COUNT(*) FROM audio WHERE TRIM(file)=''"), 0),
        ("🔴 没有别的语言的录音混进来",
         q("SELECT COUNT(*) FROM audio WHERE file LIKE 'De-%' OR file LIKE 'Fr-%' "
           "OR file LIKE 'Nl-%' OR file LIKE 'Es-%' OR file LIKE 'It-%'"), 0),
        ("kind 只有 human", q("SELECT COUNT(*) FROM audio WHERE kind<>'human'"), 0),
        ("🔴 判出地区的必须都有 region_src",
         q("SELECT COUNT(*) FROM audio WHERE region IS NOT NULL AND region_src IS NULL"), 0),
        ("🔴 没判出地区的必须没有 region_src（不许硬填）",
         q("SELECT COUNT(*) FROM audio WHERE region IS NULL AND region_src IS NOT NULL"), 0),
        ("region 只在白名单内",
         q("SELECT COUNT(*) FROM audio WHERE region IS NOT NULL AND region NOT IN (%s)"
           % ",".join("'%s'" % v for v in sorted(set(REGION_MAP.values())))), 0),
        ("至少有一个播放地址",
         q("SELECT COUNT(*) FROM audio WHERE COALESCE(url_mp3,'')='' "
           "AND COALESCE(url_ogg,'')='' AND COALESCE(url_wav,'')='' "
           "AND COALESCE(url_other,'')=''"), 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-42s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def extrapolate(run=False):
    """⭐ 地区第三级来源：**按录音人外推**（de 那轮验过，en 重验）。

    判据：该录音人 **≥3 条已判出地区 且 100% 一致** 才外推，来源标 `speaker`。
    🔴 **必须是 100%，不是 99%** —— 实测 `I learned some phrases` 是
       en-GB:377 / en-US:1（99.7%）。一条冲突就说明这个人的地区推不实，
       宁可留空（`[[dont-gate-facts-on-my-uncertainty]]` 的反面：这一行是我**推**的，
       推不实就别写）。严格判据当场把它挡在外面。
    实测收益：合格 69 位 ／ 可补 32,049 条 ／ 未判出 32.3% → **1.1%**。
    ⚠️ 记 `region_src='speaker'`，下一轮想推翻这一路能只动这一路。
    """
    import collections
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = con.execute
    byspk = collections.defaultdict(collections.Counter)
    for spk, reg in q("SELECT speaker, region FROM audio "
                      "WHERE speaker IS NOT NULL AND region IS NOT NULL"):
        byspk[spk][reg] += 1
    ok = {s: c.most_common(1)[0][0] for s, c in byspk.items()
          if sum(c.values()) >= 3 and len(c) == 1}
    plan = [(ok[s], i) for i, s in q("SELECT id, speaker FROM audio "
                                     "WHERE region IS NULL AND speaker IS NOT NULL")
            if s in ok]
    unk, = q("SELECT COUNT(*) FROM audio WHERE region IS NULL").fetchone()
    tot, = q("SELECT COUNT(*) FROM audio").fetchone()
    con.close()
    print("═══ 地区第三级：按录音人外推 ═══")
    print("   合格录音人 %s 位（≥3 条已判出且 100%% 一致）" % len(ok))
    print("   可补 %s 条 ｜ 未判出 %s → %s（%.1f%% → %.1f%%）"
          % (format(len(plan), ","), format(unk, ","), format(unk - len(plan), ","),
             100 * unk / tot, 100 * (unk - len(plan)) / tot))
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0
    with dbtool.session("keep-v3-6-audio-speaker", expect={}) as s:
        s.executemany("UPDATE audio SET region=?, region_src='speaker' WHERE id=?", plan)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = con.execute
    checks = [
        ("外推的都标了 region_src='speaker'",
         q("SELECT COUNT(*) FROM audio WHERE region_src='speaker'").fetchone()[0], len(plan)),
        ("🔴 tag/filename 那两路没被改",
         q("SELECT COUNT(*) FROM audio WHERE region_src IN ('tag','filename') "
           "AND region IS NULL").fetchone()[0], 0),
        ("🔴 仍然：没判出的不许有 region_src",
         q("SELECT COUNT(*) FROM audio WHERE region IS NULL "
           "AND region_src IS NOT NULL").fetchone()[0], 0),
        # 负控：有冲突的录音人一条都不许被外推
        ("负控 有地区冲突的录音人未被外推",
         q("SELECT COUNT(*) FROM audio WHERE region_src='speaker' "
           "AND speaker='I learned some phrases'").fetchone()[0], 0),
    ]
    print("\n═══ 闸③ ═══")
    bad = 0
    for name, got, want in checks:
        okk = got == want
        bad += not okk
        print("   %s %-42s %s / %s" % ("✅" if okk else "🔴", name,
                                       format(got, ","), format(want, ",")))
    con.close()
    return 1 if bad else 0


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, stat, reg_src, spk = collect(con)
    now, = con.execute("SELECT COUNT(*) FROM audio").fetchone()
    con.close()
    print("═══ 阶段 6 计划 ═══")
    for k in ("源", "🔴 别的语言的录音（挡掉）", "去重", "入库"):
        print("   %-24s %9s" % (k, format(stat[k], ",")))
    print("   覆盖词形 %s" % format(len({r[0] for r in rows}), ","))
    print("\n   地区来源：")
    for k, v in reg_src.most_common():
        print("      %-16s %9s  %5.1f%%" % (k, format(v, ","), 100 * v / max(stat["入库"], 1)))
    print("\n   录音人 %s 位；前 6：%s"
          % (format(len(spk), ","), "  ".join("%s(%s)" % (k[:18], format(v, ","))
                                              for k, v in spk.most_common(6))))
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0
    with dbtool.session("keep-v3-6-audio", expect={"#audio": len(rows) - now}) as s:
        s.execute("DELETE FROM audio")
        s.executemany("INSERT INTO audio (word,file,url_mp3,url_ogg,url_wav,url_other,"
                      "ipa,speaker,region,region_src,kind,src) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = gates(con, len(rows), reg_src)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    if "--speaker" in _sys.argv:
        _sys.exit(extrapolate(run="--run" in _sys.argv))
    _sys.exit(main(run="--run" in _sys.argv))
