#!/usr/bin/env python3
"""阶段 6 — 录音元数据（**只落 URL，不下载字节**）→ `audio`。2026-08-30。

═══ 🔴 先复核了一条旧结论，它只对一半 ═══
`[[cross-edition-harvest]]` 记着「**pt 为 0**」。2026-08-30 逐版实测：

    pt 版      0 条        ← 旧结论说的是**葡语版自己**，这一半是对的
    fr 版  9,605 条 / 4,391 词形   ← 最多
    en 版  6,203 条 / 3,929 词形
    zh/es/de/it  776 条
    ──────────────────────
    合计  16,584 条

⇒ 结论改成：**葡语版自己没有，但跨版有**。旧结论按"我们的库能拿到多少"读是错的。
  （`[[measure-landing-not-source]]`：量落点不量源头 —— 这次反过来，
   我当初量的是**一个源头**就写下了全局结论。）

═══ 只落 URL，不下载字节 ═══
`[[audio-from-commons-not-tts]]`：`upload.wikimedia.org` 是**读者 CDN、有意限流**
（es 全量仅 276MB 却要 6–9 小时，8 并发只跑到 0.6 条/秒还吃了 220 次重试）。
⇒ 展示层直接引用 Commons URL。这一步**零网络请求、零成本**。

═══ 录音身份是**文件名**不是 URL ═══
同一个录音有 mp3/ogg/wav 多个转码 URL，去重必须按 Commons 文件名。
`UNIQUE(word, file)` 就是这个判据。

═══ 地区从哪里来（pt 是双读音语言，这一列不是装饰）═══
源头 `sounds[].tags` 直接给：`Portugal` / `Brazil` / `Brazil/Caipira` /
`São-Paulo` / `Northern/Portugal` …
⇒ 归一到 `pt-PT` / `pt-BR`，**归一不了的留 NULL 不猜**，并把原串记进 `region_src`。

⚠️ `kind` 一律 `human` —— 这批全是 Commons 上的真人录音（方针④第一级）。
   不做 TTS（`[[it-tts-layer]]`：it 那轮合成音用户试听判定质量不够，产物已删）。

用法（在 pt/ 目录下）：
    python3 -u pipeline/ingest_audio.py            # 干跑
    python3 -u pipeline/ingest_audio.py --apply
    python3 -u pipeline/ingest_audio.py --verify
"""
import argparse
import gzip
import json
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from intake_edition_words import EDITIONS, norm_apos   # noqa: E402

f = lambda n: format(n, ",")

# 地区归一。判据**按含义**：说的是哪一支葡语。
# ⚠️ `Caipira`/`São-Paulo`/`Carioca` 都是**巴西内部**方言 ⇒ pt-BR；
#    `Northern/Portugal` 是葡萄牙内部 ⇒ pt-PT。原串一律留在 `region_src`。
BR = ("brazil", "caipira", "paulista", "são-paulo", "sao-paulo", "carioca",
      "gaúcha", "gaucha", "paranaense", "mineiro", "nordestino")
EU = ("portugal", "lisbon", "lisboa", "porto", "açores", "acores", "madeira",
      "northern", "north")

FILE_RE = re.compile(r"/([^/]+?)(?:\.(?:mp3|ogg|oga|wav|flac|opus))(?:\.[a-z0-9]+)?$", re.I)

# ══════ 第二个地区来源：**文件名** ══════
# 🔴 干跑实测：`sounds[].tags` 只覆盖 37%，10,431 条归一不了。
#    但信息就在文件名里 —— 这正是 `[[audio-from-commons-not-tts]]` 记的做法
#    （en 那轮「口音靠文件名 + 145 位录音人前 5 覆盖 88.6%」）：
#        Pt-br-essa.ogg                    → pt-BR
#        Pt-pt Praia da Vitória.ogg        → pt-PT
#        LL-Q5146_(por)-Santamarcanda-…    → LinguaLibre，中间那段是**录音人**
FNAME_REG = re.compile(r"^pt[-_]?(br|pt)\b", re.I)
# LinguaLibre 命名：`LL-<QID>_(<lang>)-<录音人>-<词>`；录音人是稳定的身份
LL_RE = re.compile(r"^LL-Q\d+[_\s]*\((?:por|pt)\)-([^-]+)-", re.I)


def speaker_of(fn):
    m = LL_RE.match(fn or "")
    return m.group(1).strip() if m else None


# ══════ 第三个地区来源：**录音人** ══════
# 判据按含义：**同一个人的口音不会变** ⇒ 拿他有标记的录音推他没标记的。
#
# 🔴 **先证明前提成立再用它**（2026-08-30 全量实测）：
#       录音人 26 位，**同一人出现两种地区的：0 位** —— 前提零反例
#       6 位有过至少一条带标记的录音，20 位一条都没有
#
# ⚠️ **要证据门槛。** `Adélaïde_Calais_WMFr` 328 条里只有 **1 条**带标记
#    （而这名字看着是法国维基人录葡语，那一条很可能是源头误标）。
#    拿 n=1 外推 327 条正是「判据比它描述的东西宽」的典型 ⇒ 定 **≥3 条一致**。
#
# ⚠️ 两位最大的录音人（`Nelson_Ricardo_2500` 2,948 条 / `Santamarcanda` 2,785 条）
#    **一条带标记的都没有** ⇒ 留 NULL。**不标地区是诚实的，猜错地区是错的。**
#    （已记进收尾单）
SPK_MIN = 3


def speaker_regions(rows):
    """→ {录音人: 地区}，只收**证据 ≥ SPK_MIN 且唯一**的。"""
    from collections import Counter, defaultdict
    seen = defaultdict(Counter)
    for r in rows:
        spk, reg = r[7], r[8]
        if spk and reg:
            seen[spk][reg] += 1
    out = {}
    for spk, c in seen.items():
        (reg, n), = c.most_common(1)
        if len(c) == 1 and n >= SPK_MIN:
            out[spk] = reg
    return out


def region_from_name(fn):
    """→ 'pt-BR'|'pt-PT'|None。判据是**文件名前缀声明的变体**，不是猜。"""
    m = FNAME_REG.match((fn or "").replace("_", "-"))
    if not m:
        return None
    return "pt-BR" if m.group(1).lower() == "br" else "pt-PT"


def region_of(tags):
    """→ ('pt-BR'|'pt-PT'|None, 原串)。归一不了留 None，**不猜**。"""
    raw = "/".join(tags or [])
    low = raw.lower()
    br = any(k in low for k in BR)
    eu = any(k in low for k in EU)
    if br and not eu:
        return "pt-BR", raw or None
    if eu and not br:
        return "pt-PT", raw or None
    return None, raw or None          # 两边都命中（`Brazil/Portugal`）也不猜


def file_of(sd):
    """Commons 文件名 = 录音身份。从任一 URL 里取，取不到就退回 `ogg_url` 全串。"""
    for k in ("ogg_url", "mp3_url", "wav_url", "oga_url", "flac_url", "opus_url"):
        u = sd.get(k)
        if not u:
            continue
        m = FILE_RE.search(u)
        if m:
            return m.group(1)
    for k in ("ogg_url", "mp3_url", "wav_url"):
        if sd.get(k):
            return sd[k]
    return None


def scan(words, editions):
    rows, stat = {}, Counter()
    for ed in editions:
        path, filt = EDITIONS[ed]
        if not path.exists():
            continue
        op = gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" \
            else open(path, encoding="utf-8")
        with op as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if filt and e.get("lang_code") != "pt":
                    continue
                w = norm_apos((e.get("word") or "").strip())
                if not w:
                    continue
                for sd in (e.get("sounds") or []):
                    if not any(sd.get(k) for k in
                               ("mp3_url", "ogg_url", "wav_url", "oga_url",
                                "flac_url", "opus_url")):
                        continue
                    if w not in words:
                        stat["词不在库里（跳过）"] += 1
                        continue
                    fn = file_of(sd)
                    if not fn:
                        stat["🔴 取不到文件名（跳过）"] += 1
                        continue
                    reg, raw = region_of(sd.get("tags"))
                    rsrc = "tag" if reg else None
                    if not reg:                      # ② 退回文件名
                        reg = region_from_name(fn)
                        rsrc = "filename" if reg else None
                    spk = speaker_of(fn)
                    stat["录音·" + ed] += 1
                    stat["地区来源·" + (rsrc or "无(NULL)")] += 1
                    stat["地区·" + (reg or "归一不了(NULL)")] += 1
                    k = (w, fn)
                    if k in rows:
                        # 🔴 **合并不能只留第一条。** 同一个录音在多版里出现，
                        #    有的版给了 `tags`、有的没给 —— 只留第一条就把地区扔了。
                        #    实测：这么写导致「录音人地区表」从 6 位变成 **0 位**，
                        #    而独立探针明明数出 MedK1 有 8 条 pt-BR。
                        #    ⚠️ 两个口径打架就是信号 —— 是这个不一致把 bug 照出来的。
                        #    （同一个坑在 `ingest_examples` 里处理过：合并时补 `sense_id`。）
                        old = rows[k]
                        stat["同一录音多版给出（合并）"] += 1
                        merged = list(old)
                        if merged[8] is None and reg is not None:
                            merged[8], merged[9] = reg, rsrc
                            stat["合并时补上了地区"] += 1
                        if merged[7] is None and spk:
                            merged[7] = spk
                        if merged[6] is None and sd.get("ipa"):
                            merged[6] = sd.get("ipa")
                        for j, key in ((2, "mp3_url"), (3, "ogg_url"), (4, "wav_url")):
                            if merged[j] is None and sd.get(key):
                                merged[j] = sd.get(key)
                        rows[k] = tuple(merged)
                        continue
                    rows[k] = (w, fn, sd.get("mp3_url"), sd.get("ogg_url"),
                               sd.get("wav_url"),
                               sd.get("oga_url") or sd.get("flac_url") or sd.get("opus_url"),
                               sd.get("ipa"), spk, reg,
                               rsrc or (("tag:" + raw) if raw else None),
                               "human", "%s-edition" % ed)
        stat["扫完 " + ed] += 1

    # ── 第三遍：按录音人补地区（判据与门槛见 `speaker_regions`）──
    out = list(rows.values())
    smap = speaker_regions(out)
    stat["录音人地区表（证据≥%d 且唯一）" % SPK_MIN] = len(smap)
    for i, r in enumerate(out):
        if r[8] is None and r[7] in smap:
            out[i] = r[:8] + (smap[r[7]], "speaker") + r[10:]
            stat["地区来源·speaker（补）"] += 1
    return out, stat


def verify(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("audio.word 不在 dict",
         q("SELECT COUNT(*) FROM (SELECT DISTINCT word FROM audio"
           " EXCEPT SELECT word FROM dict)"), 0),
        ("file 为空", q("SELECT COUNT(*) FROM audio WHERE TRIM(COALESCE(file,''))=''"), 0),
        ("(word,file) 重复",
         q("SELECT COUNT(*) FROM (SELECT word,file FROM audio GROUP BY 1,2 HAVING COUNT(*)>1)"), 0),
        ("一个 URL 都没有",
         q("SELECT COUNT(*) FROM audio WHERE COALESCE(url_mp3,url_ogg,url_wav,url_other)"
           " IS NULL"), 0),
        ("🔴 region 不是 pt-BR/pt-PT/NULL",
         q("SELECT COUNT(*) FROM audio WHERE region IS NOT NULL"
           " AND region NOT IN ('pt-BR','pt-PT')"), 0),
        ("🔴 kind 不是 human（本步不做 TTS）",
         q("SELECT COUNT(*) FROM audio WHERE kind<>'human'"), 0),
        # 🔴 判据按**含义**写：「指向 Wikimedia Commons」。
        #    第一版写成单一主机 `upload.wikimedia.org` —— 干跑抽样当场逮到反例：
        #    `commons.wikimedia.org/wiki/Special:FilePath/Pt-pt Praia da Vitória.ogg`
        #    也是 Commons，只是走另一条取文件的路径。判据比它描述的东西窄了。
        ("🔴 URL 不指向 Wikimedia Commons",
         q("SELECT COUNT(*) FROM audio WHERE COALESCE(url_ogg,url_mp3,url_wav,url_other)"
           " NOT LIKE 'https://%.wikimedia.org/%'"), 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-44s %10s  (期望 %s)" % ("✅" if ok else "🔴", name, f(got), f(want)))
    print("\n   录音人可识别 %s" % f(q("SELECT COUNT(*) FROM audio WHERE speaker IS NOT NULL")))
    print("   audio %s ／ 覆盖词形 %s ／ pt-BR %s ／ pt-PT %s ／ 未定 %s"
          % (f(q("SELECT COUNT(*) FROM audio")),
             f(q("SELECT COUNT(DISTINCT word) FROM audio")),
             f(q("SELECT COUNT(*) FROM audio WHERE region='pt-BR'")),
             f(q("SELECT COUNT(*) FROM audio WHERE region='pt-PT'")),
             f(q("SELECT COUNT(*) FROM audio WHERE region IS NULL"))))
    print("\n%s" % ("✅ 全部通过" if not bad else "🔴 %d 条红" % bad))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    # 🔴 **源清单只许一份** —— 从 `EDITIONS` 派生，不手抄。
    #    2026-08-30 实测：补下八个切片后只改了 `EDITIONS`，而这四个文件
    #    （relations/audio/examples/link_table_forms）各自手抄了一份默认值 ⇒
    #    **新源一个都没被扫**，`audio` 跑完行数一条没涨。
    #    `[[refactor-mindset-code-quality]]`：同一张表在两处各存一份，
    #    没分叉纯属运气。
    ap.add_argument("--editions", default=",".join(EDITIONS))
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(ro)
    words = {w for (w,) in ro.execute("SELECT word FROM dict")}
    ro.close()

    rows, stat = scan(words, [x for x in a.editions.split(",") if x])
    for k, v in sorted(stat.items()):
        print("   %-34s %10s" % (k, f(v)))
    print("   %-34s %10s" % ("→ (词, 文件) 去重后", f(len(rows))))
    print("   %-34s %10s" % ("   覆盖词形", f(len({r[0] for r in rows}))))

    print("\n── 抽样反验 15 条 ──")
    random.seed(0)
    for r in random.sample(rows, min(15, len(rows))):
        print("   %-22s %-8s %s" % (r[0][:22], r[8] or "—", (r[3] or r[2] or "")[:74]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    # 🔴 `expect` 比的是**增量**。第一版写成 `len(rows)`（总数），
    #    重跑时 `INSERT OR IGNORE` 一条没插却期望 +11,287 ⇒ 闸红。
    #    **闸是对的，错的是我的声明** —— 同一个错今天第二次（频次层刚犯过）。
    ro3 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    had = {(w, fn) for w, fn in ro3.execute("SELECT word, file FROM audio")}
    ro3.close()
    delta = sum(1 for r in rows if (r[0], r[1]) not in had)
    with dbtool.session("keep-v3-6-audio", expect={"#audio": delta}) as s:
        s.executemany(
            "INSERT OR IGNORE INTO audio "
            "(word,file,url_mp3,url_ogg,url_wav,url_other,ipa,speaker,region,"
            " region_src,kind,src) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


if __name__ == "__main__":
    sys.exit(main())
