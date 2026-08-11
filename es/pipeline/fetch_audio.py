#!/usr/bin/env python3
"""真人录音落盘：把 `audio` 表里 11,203 条 Commons URL 的字节抓到本地。2026-08-11。

═══ 为什么现在做 ═══
`ingest_audio.py`（08-04）当时的判断是「URL 进库、字节进文件系统」，并预留了退路：
「真要离线化就在 data/audio/ 按需缓存，库里再加一列记本地路径，表结构不用动。」
今天把它做掉，理由是实测出来的两个数：

  · **体积比估算小**：`ingest_audio` 估 300–600 MB、`spanish.ts:58` 估 260 MB，
    实测 200 条抽样中位 23.7 KB / 均值 25.2 KB ⇒ 全量 ≈ 276 MB，
    只有合成音（2.2 G）的 1/8，放进 18.8 G 的 data/ 里几乎无感。
  · **风险比看上去大**：三级兜底里质量最高的真人录音，是唯一有外网依赖的一级；
    而 `HumanAudioRow` 的死链处理是**静默降级**（chip 变灰 + 立刻换 TTS），
    用户点了「真人发音」听到合成音也不会察觉 ⇒ URL 烂掉多少，界面上量不出来。

⇒ 落盘之后，这一级从「在线依赖 + 静默降级」变成「本地文件 + 可验收」。

═══ 字节仍然不进 SQLite ═══
落盘 ≠ 入库。276 MB 塞进 SQLite 会让 `dbtool` 每次写库前的全文件复制备份从
0.7 G 涨到 1 G —— 而九成九的录音一辈子不会被请求。**库里只加一列本地相对路径。**

═══ 对 Commons 要有礼貌 ═══
🔴 第一次探活我开了 6 并发，立刻吃到大片 **429**，还差点把它当成「死链率 75%」报出去。
   本脚本：并发 3 + 每请求间隔、429 指数退避重试、带可识别的 User-Agent。
   11,203 条按实测速率约 20–30 分钟，这个量对 Commons 的 CDN 是小事，但别再飙并发。

═══ 可续跑 ═══
文件已存在且非空就跳过，所以中断了直接重跑。
🔴 落盘与写库**分两步**（`--commit` 单独跑）：下载是对外网的、会失败会重试，
   写库是事务性的 —— 混在一起会得到一个「跑了一半的库」。
   这也让下载能反复重跑而不碰数据库（见 PITFALLS「重放式脚本」那条）。

    python3 pipeline/fetch_audio.py            # 只下载，产出 manifest.tsv
    python3 pipeline/fetch_audio.py --limit 50 # 先小跑一段看看
    python3 pipeline/fetch_audio.py --commit   # 把 local_path/bytes 写进库
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import hashlib
import random
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import paths

UA = ("synapse-dict/1.0 (offline dictionary build; contact fang1992yi@gmail.com)")

# ═══ 并发定在 8 的理由（实测，别凭感觉调）═══
# 单条请求实测 **2–14 秒**，而文件只有 15–29 KB ⇒ 瓶颈是**延迟不是带宽**，
# 也不是转码：抓原始 ogg/wav 比抓转码 mp3 还慢（20.9s vs 14.2s）。
# 延迟型瓶颈靠并发线性摊薄：3 并发实测 0.35 条/秒（全量要 7 小时以上），8 并发约 70 分钟。
# 🔴 上限不敢再高：第一次探活 6 并发无间隔发 HEAD，吃到大片 429。
#    本脚本用 keep-alive（省掉每条一次 TLS 握手）+ 每请求间隔 + 429 指数退避，
#    并把重试次数显式记出来 —— **被限流而不自知，会被误读成「死链率」**（已经栽过两次）。
WORKERS = 8
GAP = 0.15           # 每个 worker 两次请求之间的最小间隔（秒）
RETRY = 5
MANIFEST = paths.AUDIO_OUT / "manifest.tsv"

_lock = threading.Lock()
_done = {"ok": 0, "skip": 0, "gone": 0, "fail": 0, "bytes": 0, "retry": 0}
_tl = threading.local()


def _session():
    """每个线程一个 requests.Session：连接复用，省掉每条一次 TLS 握手。"""
    s = getattr(_tl, "s", None)
    if s is None:
        import requests
        s = requests.Session()
        s.headers["User-Agent"] = UA
        _tl.s = s
    return s


def shard_path(file_name: str) -> _pl.Path:
    """Commons 文件名 → 本地分片路径。

    🔴 分片键是**文件名**（录音的身份），不是 URL —— 同一条录音有 mp3/ogg/wav
       多个转码 URL，按 URL 分会把同一条录音散到不同分片、并且重复下载。
    后缀统一 .mp3：我们只取 `url_mp3`（`SpanishAudio.url` 就是它，浏览器兼容性最好）。
    """
    h = hashlib.sha1(file_name.encode("utf-8")).hexdigest()
    return paths.AUDIO_OUT / h[:2] / (h + ".mp3")


def encode(url: str) -> str:
    """URL 里有 á/ó/ñ（`LL-Q1321 (spa)-Rubýñ-lama.wav`），urllib 不会自己编码就抛
    UnicodeEncodeError —— 浏览器会自动编码，所以页面正常、探针却全红。
    ⚠️ 已经是 %xx 的部分不能二次编码，所以 `%` 必须在 safe 里。"""
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def fetch(item):
    file_name, url = item
    dst = shard_path(file_name)
    if dst.exists() and dst.stat().st_size > 0:
        with _lock:
            _done["skip"] += 1
            _done["bytes"] += dst.stat().st_size
        return (file_name, "skip", dst.stat().st_size)

    safe = encode(url)
    for attempt in range(RETRY):
        try:
            r = _session().get(safe, timeout=60)
            if r.status_code in (429, 503):     # 限流：退避重试，不算失败
                with _lock:
                    _done["retry"] += 1
                time.sleep((2 ** attempt) + random.random())
                continue
            if r.status_code != 200:
                with _lock:
                    _done["gone" if r.status_code == 404 else "fail"] += 1
                return (file_name, f"http{r.status_code}", 0)
            data = r.content
            if not data:
                raise ValueError("空响应")
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(".part")      # 先写 .part 再改名：中断不会留下半个文件
            tmp.write_bytes(data)
            tmp.rename(dst)
            time.sleep(GAP)
            with _lock:
                _done["ok"] += 1
                _done["bytes"] += len(data)
            return (file_name, "ok", len(data))
        except Exception as e:                  # 超时/连接重置：退避重试
            if attempt == RETRY - 1:
                with _lock:
                    _done["fail"] += 1
                return (file_name, type(e).__name__, 0)
            with _lock:
                _done["retry"] += 1
            time.sleep((2 ** attempt) + random.random())
    with _lock:
        _done["fail"] += 1
    return (file_name, "429-exhausted", 0)


def download(limit=None):
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT file, url_mp3 FROM audio WHERE url_mp3 IS NOT NULL ORDER BY file"
    ).fetchall()
    con.close()
    if limit:
        rows = rows[:limit]

    paths.AUDIO_OUT.mkdir(parents=True, exist_ok=True)
    total = len(rows)
    print(f"■ 待抓 {total:,} 条 → {paths.AUDIO_OUT}")
    print(f"  并发 {WORKERS} / 间隔 {GAP}s / 429 退避重试 {RETRY} 次")

    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, res in enumerate(ex.map(fetch, rows), 1):
            results.append(res)
            if i % 500 == 0 or i == total:
                el = time.time() - t0
                rate = i / el if el else 0
                left = (total - i) / rate if rate else 0
                print(f"  {i:>6,}/{total:,}  "
                      f"新增 {_done['ok']:,} 已有 {_done['skip']:,} "
                      f"404 {_done['gone']:,} 失败 {_done['fail']:,} "
                      f"重试 {_done['retry']:,}  "
                      f"{_done['bytes']/1048576:.0f} MB  "
                      f"{rate:.1f} 条/秒  剩 {left/60:.0f} 分", flush=True)

    with MANIFEST.open("w", encoding="utf-8") as fh:
        fh.write("file\tpath\tbytes\tstatus\n")
        for name, status, n in results:
            rel = shard_path(name).relative_to(paths.AUDIO_OUT) if status in ("ok", "skip") else ""
            fh.write(f"{name}\t{rel}\t{n}\t{status}\n")

    el = time.time() - t0
    print(f"\n■ 完成，用时 {el/60:.1f} 分")
    print(f"  落盘 {_done['ok'] + _done['skip']:,} 条 / {_done['bytes']/1048576:.0f} MB")
    print(f"  404（源头已删）{_done['gone']:,}   其他失败 {_done['fail']:,}")
    print(f"  限流/超时重试 {_done['retry']:,} 次"
          + ("（⚠️ 重试多说明并发偏高，下次调低 WORKERS）" if _done["retry"] > total * 0.1 else ""))
    if _done["fail"]:
        print("  ⚠️ 失败的直接重跑本脚本即可（已存在的会跳过）")
    print(f"  清单 → {MANIFEST}")
    print("\n下一步：python3 pipeline/fetch_audio.py --commit")


def commit():
    """把 manifest 里的落盘结果写进库：`audio.local_path` / `audio.bytes`。

    🔴 只填**这次真的落盘了**的行，不动任何其他列；重跑幂等。
    """
    if not MANIFEST.exists():
        _sys.exit(f"🔴 没有 {MANIFEST}，先跑下载")

    rows = []
    with MANIFEST.open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            name, rel, n, status = line.rstrip("\n").split("\t")
            if status in ("ok", "skip") and rel:
                rows.append((rel, int(n), name))
    print(f"■ manifest 里可入库 {len(rows):,} 条")

    con = sqlite3.connect(paths.DB)
    cols = {r[1] for r in con.execute("PRAGMA table_info(audio)")}
    for col, decl in (("local_path", "TEXT"), ("bytes", "INTEGER")):
        if col not in cols:
            con.execute(f"ALTER TABLE audio ADD COLUMN {col} {decl}")
            print(f"  + audio.{col} {decl}")

    before = con.execute("SELECT COUNT(*) FROM audio WHERE local_path IS NOT NULL").fetchone()[0]
    con.executemany(
        "UPDATE audio SET local_path=?, bytes=? WHERE file=? AND local_path IS NULL", rows)
    con.commit()
    after = con.execute("SELECT COUNT(*) FROM audio WHERE local_path IS NOT NULL").fetchone()[0]
    tot = con.execute("SELECT COUNT(*) FROM audio").fetchone()[0]
    mb = (con.execute("SELECT COALESCE(SUM(bytes),0) FROM audio").fetchone()[0]) / 1048576
    con.close()

    print(f"■ local_path 非空：{before:,} → {after:,} / {tot:,}（{after/tot*100:.1f}%）")
    print(f"  落盘字节合计 {mb:.0f} MB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="只抓前 N 条（试跑）")
    ap.add_argument("--commit", action="store_true", help="把 manifest 写进库")
    a = ap.parse_args()
    if a.commit:
        commit()
    else:
        download(a.limit)


if __name__ == "__main__":
    main()
