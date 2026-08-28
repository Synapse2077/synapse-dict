#!/usr/bin/env python3
"""阶段 6 — 收真人录音的 **URL**（不下载文件）→ `audio` 表。2026-08-28。

═══ 为什么现在补 ═══
阶段 6 当初定的是「本轮不做发音，**只落元数据**」（用户 2026-08-21：与 it 一致，
以后统一做）。但「只落元数据」这半句**也没做** —— `audio` 表 0 行。
收尾单 **B3**；账的闸 P1 现在盯着它（阶段 6 声明 ✅ 就必须交得出这一层）。

═══ 为什么只收 URL，不下载 ═══
`upload.wikimedia.org` 是读者 CDN、**有意限流**（es 实测 8 并发只到 0.6 条/秒、
220 次重试、25 条 429）。fr 的真人录音 244,777 条，落盘约 6 GB / 5–6 天
（`[[fr-dict-pipeline]]`）⇒ URL 白送，下载是**单独的一个决定**，不在本轮。
⚠️ 而且 `SHOW_HUMAN_AUDIO` 全语种关着，**当前展示价值为零** —— 收进来是为了
   将来统一做发音时不用再扫一遍 dump，不是为了这一轮上线。

═══ 三条规矩（判据与 it 同源，不重新设计）═══
① **按语言码过滤**：跨版收割不许按词形匹配（es 曾因此混进 63 条非西语录音）。
   直接用 `build_pronunciation_layer.SOURCES` —— **源清单只许一份**。
② **同一条录音的 mp3/ogg/wav 是一条，不是三条**。行键 `(词形, 文件名)`，
   三种格式落在同一行的三个列上（it 那轮「录音条数虚高 2–3 倍」就是数成三条）。
③ **录音人从文件名认，认不出留空，不猜**。Lingua Libre 命名
   `LL-Q150 (fra)-<录音人>-<词>.wav` —— 只认这一种。

用法（在 fr/ 目录下）：
    python3 -u pipeline/ingest_audio_urls.py            # 干跑
    python3 -u pipeline/ingest_audio_urls.py --apply
    python3 -u pipeline/ingest_audio_urls.py --mutate
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import dbtool                                       # noqa: E402
import paths                                        # noqa: E402
from build_pronunciation_layer import SOURCES, opener, region_of   # noqa: E402
from intake_fr_words import norm_apos               # noqa: E402

f = lambda n: format(n, ",")
URL_KEYS = [("mp3_url", "url_mp3"), ("ogg_url", "url_ogg"), ("wav_url", "url_wav")]
# Lingua Libre：`LL-Q150 (fra)-<录音人>-<词>.wav`
_LL = re.compile(r"^LL-Q\d+\s*\([a-z]{3}\)-([^-]+)-")
# 版本优先级：法文版是录音主源
PRIO = {name: i for i, (name, _p, _lc, _b) in enumerate(SOURCES)}


def speaker_of(filename):
    """从文件名认录音人。**只认 Lingua Libre 那一种命名**，认不出返回 None，不猜。"""
    m = _LL.match(filename or "")
    return m.group(1).strip() if m else None


def collect(con, limit=0):
    ids = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    rows, c = {}, Counter()
    for name, path, lc, _bare in SOURCES:
        if not Path(path).exists():
            print("   （%s 不存在，跳过）" % name)
            continue
        n = 0
        with opener(path) as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if lc and e.get("lang_code") != lc:
                    continue
                w0 = (e.get("word") or "").strip()
                if not w0:
                    continue
                n += 1
                if limit and n > limit:
                    break
                w = norm_apos(w0)
                if w not in ids:
                    c["词形不在库里"] += 1
                    continue
                for s in (e.get("sounds") or []):
                    urls = {col: s.get(k) for k, col in URL_KEYS if s.get(k)}
                    if not urls:
                        continue
                    fn = (s.get("audio") or "").strip()
                    if not fn:
                        # 没有文件名就用 url 最后一段当键 —— **键必须稳定，不能用下标**
                        fn = next(iter(urls.values())).rsplit("/", 1)[-1]
                    key = (w, fn)
                    if key in rows:
                        old = rows[key]
                        for col, u in urls.items():
                            old.setdefault(col, u)     # 补齐缺的格式列
                        if PRIO[name] < PRIO[old["src"]]:
                            old["src"] = name
                        c["同一条录音多版都有"] += 1
                        continue
                    tags = list(s.get("tags") or []) + list(s.get("raw_tags") or [])
                    reg = region_of(tags)
                    row = {"word": w, "file": fn, "ipa": (s.get("ipa") or "").strip() or None,
                           "speaker": speaker_of(fn), "region": reg,
                           "region_src": name if reg else None,
                           "kind": "human", "src": name}
                    row.update(urls)
                    rows[key] = row
                    c["✓ " + name] += 1
        print("   %-12s 扫 %s 条" % (name, f(n)))
    c["落表行数"] = len(rows)
    c["认出录音人的"] = sum(1 for r in rows.values() if r.get("speaker"))
    c["带地区限定的"] = sum(1 for r in rows.values() if r.get("region"))
    c["覆盖词形数"] = len({r["word"] for r in rows.values()})
    return list(rows.values()), c


def gates(con, rows):
    print("\n═══ 闸 ═══")
    ok = True

    def g(name, got, want):
        nonlocal ok
        ok &= got == want
        print("   %s %-50s %s（期望 %s）" % ("✅" if got == want else "🔴", name, f(got), f(want)))

    have = {w for (w,) in con.execute("SELECT word FROM dict")}
    g("① 词形都在 dict 里", sum(1 for r in rows if r["word"] not in have), 0)
    g("② 每行至少有一个 url",
      sum(1 for r in rows if not any(r.get(c) for _k, c in URL_KEYS)), 0)
    g("③ (词形, 文件名) 不重复",
      len(rows) - len({(r["word"], r["file"]) for r in rows}), 0)
    g("④ kind 只有 human（本轮不收合成音）",
      sum(1 for r in rows if r["kind"] != "human"), 0)
    g("⑤ 认不出录音人就留空，不许出现空串",
      sum(1 for r in rows if r.get("speaker") == ""), 0)
    return ok


def mutate():
    print("═══ 变异验证：录音人判据 ═══")
    cases = [
        ("Lingua Libre 标准命名", speaker_of("LL-Q150 (fra)-Lyokoï-chat.wav"), "Lyokoï"),
        ("🔴 别的命名一律不猜", speaker_of("Fr-chat.ogg"), None),
        ("🔴 空文件名", speaker_of(""), None),
        ("🔴 只是长得像", speaker_of("LL-something-else.wav"), None),
        ("录音人名里有空格", speaker_of("LL-Q150 (fra)-Jean Pierre-eau.wav"), "Jean Pierre"),
    ]
    ok = 0
    for name, got, want in cases:
        good = got == want
        ok += good
        print("   %s %-36s → %r" % ("✅" if good else "🔴", name, got))
    print("\n   变异 %d/%d" % (ok, len(cases)))
    return ok == len(cases)


COLS = ["word", "file", "url_mp3", "url_ogg", "url_wav", "url_other",
        "ipa", "speaker", "region", "region_src", "kind", "src"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, c = collect(con, a.limit)
    print("\n■ 可入库 %s 条录音" % f(len(rows)))
    for k, v in c.most_common(14):
        print("   %-30s %s" % (k, f(v)))
    ok = gates(con, rows)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1
    with dbtool.session("keep-v3-fr-audio-urls", expect={"#audio": len(rows)}) as s:
        s.executemany(
            "INSERT INTO audio(%s) VALUES(%s)" % (",".join(COLS), ",".join("?" * len(COLS))),
            [tuple(r.get(k) for k in COLS) for r in rows])
    print("✓ 写入 %s 条" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
