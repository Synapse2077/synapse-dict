#!/usr/bin/env python3
"""合成发音：Piper 生成 TTS 音频，落文件系统。2026-08-05。

方针④三级兜底「真人 > 工具生成 > 浏览器 TTS」里的**中间那级**。
真人录音只覆盖 5.5% 的 lemma（见 `ingest_audio.py`），剩下的靠这里补。

═══ 两个音色，以及为什么只有 16.5% 的词需要第二个 ═══
    es_MX-claude-high      length_scale 1.0    主力，拉美音
    es_ES-sharvard-medium  length_scale 1.13   半岛音，**speaker 0（男声）**
半岛音和拉美音在孤立单词上的差别几乎只有一个：`z` / `ce` / `ci` 读 /θ/ 还是 /s/。
⇒ **音标里没有 θ 的词，两个音色读法相同，只生成一份。** 核心层实测 16.5% 需要两份。

🔴 判据用**音标列**不用拼写。拼写规则 `z|c[ei]` 在核心层给出 15.9%，看着差不多，
   但两边的成员对不上：拼写漏掉逐字母念的缩写（`BBC`→ˌbeˌbeˈθe、`CD`、`PC`），
   又多收了 `pizza`(ˈpitsa)、`mozzarella`(motsaˈɾela)、`center`(ˈsenteɾ) 这些
   /ts/ 和外来词。音标是已经裁决过的数据，拼写是猜。

🔴 sharvard 是**双说话人模型**（`num_speakers: 2`）。不传 `speaker_id` 默认取 0，
   碰巧就是要的男声——但别依赖这个巧合，显式写出来。speaker 1 是女声（198 Hz）。

═══ 三个会让人白跑一遍的坑 ═══
🔴 ① `ESPEAK_DATA_PATH=/usr/local/share` 不设，piper **静默产出 0 字节文件**，
     不报错、不抛异常，跑完才发现一整批是空的。本脚本在启动时自证一次。
🔴 ② **别开多进程。** ONNX 自己就把 4 个物理核吃满了：单进程 28.8 词/秒，
     4 进程 × 1 线程合计反而只有 16.5 词/秒（互相抢核 + 每个进程重新加载模型）。
     并发只用在 afconvert 上——那是外部进程，等的是 I/O。
🔴 ③ 转码用 macOS 自带的 **`afconvert`**，不需要装 ffmpeg。
     WAV 38 KB → AAC 48k 约 10 KB（26%）。WAV 母带不留：重跑一遍只要 9 分钟，
     留着要多占 3.5 倍空间，是笔亏本买卖。

═══ 落盘布局 ═══
    data/tts/es/<sha1[:2]>/<sha1>.m4a        sha1 = sha1(f"{word}|{voice_tag}")
    data/tts/es/manifest.tsv                 word / voice / rel_path / bytes / dur
按 sha1 前两位分 256 片：单目录 16 万文件时 macOS 的 `ls` 和 Finder 都会卡。
词形本身不能直接当文件名——库里有 `a-`、`El Salvador`、`etc.`、`¿qué?` 这类。

音频字节**不进 SQLite**，理由同 `ingest_audio.py`：`dbtool` 每次写库前要全文件复制
备份，360 MB / 0.6 秒；塞进音频后每改一行译文都要复制好几 GB。
⇒ 本脚本**完全不碰数据库**（只读 `dict` 取词表），因此没有 `dbtool` 闸门。

═══ 🔴 取词判据用 `freq_zipf`，不用 `level`（2026-08-10 改）═══
第一轮核心层是按 `--level A1,A2,B1` 挑的 16,236 个词。接上频次层后一比对，**挑错了**：

    没合成、频次却排最前的        合成了、频次却垫底的
    es    7.02   me   6.70       lavaparabrisas  1.01  (B1)
    hay   6.23   está 6.22       escurreplatos   1.01  (B1)
    fue   6.22   son  6.26       decembrino      1.01  (B1)

`es / me / hay / está / fue / son` 这些西语最常用词一个合成音都没有。根因是 `level`
只给内容词打了标，语法词和变形词全是 NULL —— 而 `level` 本来就是全库唯一没有源、
无法回源的字段（见 `build_frequency_layer.py` 开头）。拿它当调度依据必然漏掉高频区。

⇒ **`--freq` 取代 `--level` 成为默认判据。** 分层实测（体积按实测 12.0 KB/个）：

    zipf ≥ 4      7,622 个   占跑动文本 90.0%    0.09 G
    zipf ≥ 3     33,144 个              97.7%    0.38 G
    全部有频次   190,616 个             100%     2.18 G   ← 2026-08-10 用户拍板做到这层

⭐ 「全部有频次」是**自然分界线**，不是拍脑袋的阈值：库里另外 920,663 个单词形
（`Elizathe`、`Basolo` 这类巴斯克地名、`esquizotimia` 这类生僻派生）在 wordfreq 里
根本查不到 = 跑动文本里量不出来，按方针④落到第三级浏览器 TTS。
旧记录「全词形 10.9 G」把它们全算进去了，才显得贵 —— 真正有频次的只占 17%。

═══ 用法 ═══
    python -m es.pipeline.gen_tts --freq                        # 全部有频次的词形（推荐）
    python -m es.pipeline.gen_tts --freq 3                      # 只要 zipf ≥ 3
    python -m es.pipeline.gen_tts --freq --peninsular           # 再补 θ 词的半岛音
    python -m es.pipeline.gen_tts --level A1,A2,B1              # 旧判据，保留仅为复现
    python -m es.pipeline.gen_tts --lemma / --all-forms
    python -m es.pipeline.gen_tts --verify                      # 验收闸：清单↔磁盘↔哈希契约
    python -m es.pipeline.gen_tts --mutate                      # 变异验证：闸抓不抓得住
已存在的文件默认跳过（可中断可续跑），`--force` 重生成。
"""
import argparse
import hashlib
import os
import sqlite3
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# 🔴 必须在 import piper 之前设好，否则 piper 静默产出 0 字节文件
os.environ.setdefault("ESPEAK_DATA_PATH", "/usr/local/share")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import es.paths as paths  # noqa: E402

VOICES = {
    # tag        模型文件                       speaker  length_scale
    "mx": ("es_MX-claude-high.onnx", None, 1.0),
    "es": ("es_ES-sharvard-medium.onnx", 0, 1.13),
}
BITRATE = 48000          # AAC kbps ×1000。32k 也够用，核心层两者只差 30 MB
SILENCE_THR = 0.02       # 切静音的相对峰值阈值，只用于量时长


def digest(word: str, tag: str) -> str:
    return hashlib.sha1(f"{word}|{tag}".encode()).hexdigest()


def speech_text(word: str) -> str:
    """词形 → 送进 TTS 的文本。

    库里有 `a-` / `-able` / `-mente` 这类词缀条目（核心层 40 个）。连字符直接喂给
    espeak 会当成断句符，读出来是残的。剥掉首尾连字符念词干——用户划到 `-able`
    想听的就是 "able" 怎么念。
    """
    return word.strip().strip("-").strip()


def synth_wav(voice, text: str, spk, ls: float, dst: Path) -> float:
    """合成一个词到 WAV，返回时长；一个音频块都没有则返回 0 且不建文件。

    🔴 **不能用 `voice.synthesize_wav()`。** 它把 `setnchannels/setsampwidth/setframerate`
    写在"拿到第一个音频块之后"，所以碰上产不出音频的词时，wave 对象的参数从没被设过，
    退出 `with` 块时炸 `wave.Error: # channels not specified` —— **整批中断**。
    2026-08-05 核心层第一次跑就是这么在第 2,414 个词上死的，前面两千多个白跑（好在可续跑）。
    改成先收齐音频块、确认非空再自己写 WAV 头，产不出音的词就跳过并登记。
    """
    chunks = [c for c in voice.synthesize(text, syn_config=SYN(spk, ls))
              if c.audio_int16_bytes]
    if not chunks:
        return 0.0
    data = b"".join(c.audio_int16_bytes for c in chunks)
    c0 = chunks[0]
    with wave.open(str(dst), "wb") as f:
        f.setnchannels(c0.sample_channels)
        f.setsampwidth(c0.sample_width)
        f.setframerate(c0.sample_rate)
        f.writeframes(data)
    return len(data) / (c0.sample_rate * c0.sample_width * c0.sample_channels)


# ═══════════════════════════ 验收闸（2026-08-10 补）═══════════════════════
# 这一层不写数据库，`dbtool` 那三道闸够不着它，但它有一个别处没有的风险：
# 🔴 **哈希契约在两种语言里各写了一遍** —— 这里的 `digest()` 和
#    `packages/dict-core/src/spanish.ts` 的 `ttsFor()`。两边差一个字节，
#    前端就永远 `existsSync` 失败、**静默**全部降级到浏览器 TTS：不报错、不 404，
#    只是所有词突然都"没有合成音"。闸③专门盯这个。
# ⭐ 一条永远通过的检查等于没检查 ⇒ `--mutate` 造 6 种错，闸全抓住才算数。

MIN_BYTES = 1200          # 实测最短的真音频（`y` 0.20 秒）约 4.6 KB，1.2 KB 是宽松下界
DUR_RANGE = (0.05, 30.0)


def verify(root: Path, manifest_path: Path, quiet: bool = False) -> bool:
    """核对合成层：清单 ↔ 磁盘 ↔ 哈希契约。全量，非抽样。"""
    def say(*a):
        if not quiet:
            print(*a)

    say("\n═══ 合成层验收（全量，非抽样）═══")
    if not manifest_path.exists():
        say("🔴 清单不存在")
        return False

    lines, bad_shape = [], 0
    with manifest_path.open(encoding="utf-8") as f:
        header = next(f, "")
        if header.rstrip("\n").split("\t") != ["word", "voice", "path", "bytes", "dur"]:
            say(f"🔴 清单表头不对：{header!r}")
            return False
        for ln in f:
            p = ln.rstrip("\n").split("\t")
            if len(p) != 5:
                bad_shape += 1
                continue
            lines.append(p)

    missing, size_bad, hash_bad, tiny, dur_bad = [], [], [], [], []
    seen: dict[tuple[str, str], int] = {}
    dup = []
    listed = set()
    for word, tag, rel, nbytes, dur in lines:
        key = (word, tag)
        if key in seen:
            dup.append(key)
        seen[key] = 1
        listed.add(rel)
        # 闸③ 哈希契约：路径必须能从 (词, 音色) 原样重算出来
        if tag in VOICES:
            h = digest(word, tag)
            if rel != f"{h[:2]}/{h}.m4a":
                hash_bad.append((word, tag, rel))
        f = root / rel
        if not f.exists():
            missing.append((word, tag, rel))
            continue
        real = f.stat().st_size
        if real != int(nbytes):
            size_bad.append((word, tag, int(nbytes), real))
        if real < MIN_BYTES:
            tiny.append((word, tag, real))
        if not (DUR_RANGE[0] <= float(dur) <= DUR_RANGE[1]):
            dur_bad.append((word, tag, float(dur)))

    on_disk = {f"{p.parent.name}/{p.name}" for p in root.glob("*/*.m4a")}
    orphans = sorted(on_disk - listed)

    checks = [
        ("清单行格式不对（不是 5 列）", bad_shape, []),
        ("清单里有、磁盘上没有", len(missing), missing),
        ("字节数与磁盘对不上", len(size_bad), size_bad),
        ("🔴 路径 ≠ sha1(词|音色)（与 spanish.ts 的契约）", len(hash_bad), hash_bad),
        (f"文件小于 {MIN_BYTES} 字节（疑似空音频）", len(tiny), tiny),
        (f"时长不在 {DUR_RANGE} 内", len(dur_bad), dur_bad),
        ("同一 (词, 音色) 登记了多次", len(dup), dup),
        ("磁盘上有、清单里没有（孤儿）", len(orphans), orphans),
    ]
    ok = True
    say(f"  清单 {len(lines):,} 行 / 磁盘 {len(on_disk):,} 个文件")
    for name, n, ex in checks:
        say(f"  {'🔴' if n else '  '} {name:<44}{n:>8,}")
        for e in ex[:3]:
            say(f"       {e}")
        ok &= n == 0
    say("  ✅ 全部通过" if ok else "  🔴 有闸没过")
    return ok


def mutate_verify() -> None:
    """⭐ 变异验证。用**硬链接**搭一棵 300 个文件的小树（秒级、不占空间），
    在上面造 6 种错，逐个看闸抓不抓得住。真实音频一个字节都不动。"""
    import shutil
    import tempfile
    root, mf = paths.TTS_OUT, paths.TTS_OUT / "manifest.tsv"
    with mf.open(encoding="utf-8") as f:
        head = next(f)
        rows = [next(f).rstrip("\n").split("\t") for _ in range(300)]

    def build(td: Path, rows_):
        for _, _, rel, _, _ in rows_:
            (td / rel).parent.mkdir(parents=True, exist_ok=True)
            if not (td / rel).exists():
                os.link(root / rel, td / rel)
        p = td / "manifest.tsv"
        p.write_text(head + "".join("\t".join(r) + "\n" for r in rows_), encoding="utf-8")
        return p

    muts = [
        ("① 清单登记的文件其实不在", lambda r, td: (td / r[0][2]).unlink()),
        ("② 字节数与磁盘对不上", lambda r, td: r[0].__setitem__(3, "999999")),
        ("🔴③ 路径不是 sha1(词|音色)（契约破了）",
         lambda r, td: r[0].__setitem__(2, "ff/" + "f" * 40 + ".m4a")),
        ("④ 空音频（0 字节）",
         lambda r, td: (td / r[0][2]).unlink() or (td / r[0][2]).write_bytes(b"")),
        ("⑤ 同一 (词,音色) 登记两次", lambda r, td: r.append(list(r[0]))),
        ("⑥ 磁盘上有、清单里没有（孤儿）", lambda r, td: r.pop(0)),
    ]
    print("\n" + "=" * 62)
    print("⭐ 变异验证：小树上造 6 种错，看闸的反应（真实音频不动）")
    print("=" * 62)
    caught = 0
    for name, apply_mut in muts:
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            rr = [list(r) for r in rows]
            build(td, rr)                 # 先按原样建树（文件按原路径落好）
            apply_mut(rr, td)             # 再破坏
            p = td / "manifest.tsv"
            p.write_text(head + "".join("\t".join(r) + "\n" for r in rr), encoding="utf-8")
            good = verify(td, p, quiet=True)
            caught += not good
            print(f"  {'✅ 抓住' if not good else '🔴 漏过'}  {name}")
    print(f"\n  {caught}/6 被抓住" + ("" if caught == 6 else "  🔴 有闸是摆设，必须修"))


def selftest(voice, out_dir: Path) -> None:
    """坑①的自证：先合成一个词，确认不是 0 字节。"""
    p = out_dir / "_selftest.wav"
    dur = synth_wav(voice, "prueba", None, 1.0, p)
    size = p.stat().st_size if p.exists() else 0
    p.unlink(missing_ok=True)
    if size < 2000 or dur == 0:
        sys.exit(f"✗ 自证失败：合成 'prueba' 只有 {size} 字节。"
                 f"检查 ESPEAK_DATA_PATH（现在是 {os.environ.get('ESPEAK_DATA_PATH')}）")


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--verify", action="store_true", help="只跑验收闸，不合成")
    g.add_argument("--mutate", action="store_true", help="变异验证：闸抓不抓得住")
    g.add_argument("--freq", nargs="?", const=-1.0, type=float, metavar="ZIPF",
                   help="按频次取词（默认判据）：不给数字＝全部有 freq_zipf 的词形；"
                        "给数字则只取 zipf ≥ 该值")
    g.add_argument("--level", help="旧判据，逗号分隔如 A1,A2,B1。见 docstring：会漏掉高频区")
    g.add_argument("--lemma", action="store_true", help="全部 lemma")
    g.add_argument("--all-forms", action="store_true", help="全部词形")
    ap.add_argument("--peninsular", action="store_true",
                    help="给音标含 θ 的词额外生成半岛音（sharvard 男声 ×1.13）")
    ap.add_argument("--only-peninsular", action="store_true",
                    help="只补半岛音，跳过主力音（主力层已经跑完时用）")
    ap.add_argument("--force", action="store_true", help="已存在也重新生成")
    ap.add_argument("--limit", type=int, help="只跑前 N 个，试跑用")
    ap.add_argument("--jobs", type=int, default=4, help="afconvert 并发数（默认 4）")
    args = ap.parse_args()

    if args.verify or args.mutate:
        ok = verify(paths.TTS_OUT, paths.TTS_OUT / "manifest.tsv")
        if args.mutate:
            mutate_verify()
        sys.exit(0 if ok else 1)

    if args.only_peninsular:
        args.peninsular = True

    # ── 取词表 ──────────────────────────────────────────────────────────
    con = sqlite3.connect(paths.DB)
    if args.freq is not None:
        # `dict.word` 全库唯一（1,139,125 行 = 1,139,125 个不同词形），所以这里
        # 取出来不会有同词重复行，不需要去重。换表结构后这条要重新验。
        rows = con.execute(
            "select word, phonetic from dict where freq_zipf is not null "
            "and freq_zipf >= ? order by freq_zipf desc", (args.freq,)).fetchall()
        scope = ("全部有频次的词形" if args.freq < 0 else f"zipf ≥ {args.freq}")
    elif args.level:
        levels = [x.strip() for x in args.level.split(",")]
        sql = (f"select word, phonetic from dict where level in "
               f"({','.join('?' * len(levels))})")
        rows = con.execute(sql, levels).fetchall()
        scope = f"level {args.level}"
    elif args.lemma:
        rows = con.execute("select word, phonetic from dict where is_lemma=1").fetchall()
        scope = "全部 lemma"
    else:
        rows = con.execute("select word, phonetic from dict").fetchall()
        scope = "全部词形"
    con.close()
    if args.limit:
        rows = rows[:args.limit]

    # ── 排任务：每个 (词, 音色) 一个文件 ────────────────────────────────
    jobs, skipped_empty = [], 0
    for word, ph in rows:
        text = speech_text(word)
        if not text:
            skipped_empty += 1
            continue
        if not args.only_peninsular:
            jobs.append((word, text, "mx"))
        if args.peninsular and ph and "θ" in ph:
            jobs.append((word, text, "es"))

    n_mx = sum(1 for j in jobs if j[2] == "mx")
    n_es = len(jobs) - n_mx
    print(f"范围 {scope}：{len(rows):,} 个词形")
    if skipped_empty:
        print(f"  剥完连字符为空、跳过：{skipped_empty}")
    print(f"  主力音 mx  {n_mx:,}")
    print(f"  半岛音 es  {n_es:,}" + (f"（音标含 θ，占 {n_es/len(rows)*100:.1f}%）" if n_es else "（未启用）"))

    out_root = paths.TTS_OUT
    out_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_root / "_tmp"
    tmp_dir.mkdir(exist_ok=True)

    # ── 续跑：以**清单**为准，不以文件存在为准 ──────────────────────────
    # 🔴 2026-08-05 踩过：第一版按"文件存在就跳过"判断。清单是攒批写的，
    #    崩溃时最后一批的行丢了，但音频文件已经落盘 ⇒ 续跑认为它们做完了，
    #    于是 `cuchara` / `puta` 两个词永远补不进清单，成了对不上账的孤儿文件。
    #    正确判据：清单里有登记 **且** 文件真在，才算做完。
    manifest_path = out_root / "manifest.tsv"
    kept: dict[tuple[str, str], str] = {}
    if manifest_path.exists() and not args.force:
        with manifest_path.open(encoding="utf-8") as f:
            next(f, None)
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) == 5 and (out_root / p[2]).exists():
                    kept[(p[0], p[1])] = line
        before = len(jobs)
        jobs = [j for j in jobs if (j[0], j[2]) not in kept]
        orphans = sum(1 for d in out_root.glob("*/*.m4a")) - len(kept)
        if before != len(jobs):
            print(f"  清单已登记、跳过：{before - len(jobs):,}  → 待生成 {len(jobs):,}")
        if orphans > 0:
            print(f"  ⚠️ 有 {orphans} 个文件不在清单里（上次中断留下的），本轮重做并登记")
    if not jobs:
        print("没有要生成的。")
        return

    # ── 加载模型（每个音色只加载一次，坑②）────────────────────────────
    from piper import PiperVoice, SynthesisConfig
    global SYN
    SYN = lambda spk, ls: SynthesisConfig(speaker_id=spk, length_scale=ls)  # noqa: E731

    loaded = {}
    for tag in {j[2] for j in jobs}:
        model, spk, ls = VOICES[tag]
        loaded[tag] = (PiperVoice.load(str(paths.TTS_VOICES / model)), spk, ls)
    selftest(loaded[next(iter(loaded))][0], tmp_dir)

    # ── 合成（单进程）+ 转码（线程池）──────────────────────────────────
    # 清单整份重写：先落"上轮验证过还在的"，再逐批追加新的，每批 flush。
    # 中途再崩，清单里就是「已验证 + 已完成」，正好是下次续跑要的状态。
    mf = manifest_path.open("w", encoding="utf-8")
    mf.write("word\tvoice\tpath\tbytes\tdur\n")
    for line in kept.values():
        mf.write(line)
    mf.flush()

    def transcode(word, tag, wav_path, dur):
        h = digest(word, tag)
        sub = out_root / h[:2]
        sub.mkdir(exist_ok=True)
        dst = sub / f"{h}.m4a"
        rc = os.spawnvp(os.P_WAIT, "afconvert",
                        ["afconvert", "-f", "mp4f", "-d", "aac", "-b", str(BITRATE),
                         str(wav_path), str(dst)])
        wav_path.unlink(missing_ok=True)
        if rc != 0 or not dst.exists():
            return None
        return f"{word}\t{tag}\t{h[:2]}/{h}.m4a\t{dst.stat().st_size}\t{dur:.3f}\n"

    t0 = time.time()
    done = failed = 0
    total_bytes = 0
    voiceless = []          # 合成不出音频的词，逐条留名（不许只报个数）
    pending = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for i, (word, text, tag) in enumerate(jobs):
            voice, spk, ls = loaded[tag]
            wav_path = tmp_dir / f"w{i % (args.jobs * 4)}_{i}.wav"
            dur = synth_wav(voice, text, spk, ls, wav_path)
            if dur == 0.0:
                voiceless.append((word, tag))
                continue
            pending.append(pool.submit(transcode, word, tag, wav_path, dur))

            # 回收，别让 future 无限堆积
            if len(pending) >= args.jobs * 8:
                for fut in pending:
                    line = fut.result()
                    if line:
                        mf.write(line)
                        total_bytes += int(line.split("\t")[3])
                        done += 1
                    else:
                        failed += 1
                pending.clear()
                mf.flush()
                el = time.time() - t0
                print(f"\r  {done + failed:,}/{len(jobs):,}  "
                      f"{(done + failed) / el:.0f} 个/秒  "
                      f"剩 {(len(jobs) - done - failed) / max((done + failed) / el, 1) / 60:.0f} 分钟",
                      end="", flush=True)
        for fut in pending:
            line = fut.result()
            if line:
                mf.write(line)
                total_bytes += int(line.split("\t")[3])
                done += 1
            else:
                failed += 1
    mf.close()

    el = time.time() - t0
    print(f"\r{' ' * 70}\r本轮生成 {done:,} 个，失败 {failed}，"
          f"用时 {el / 60:.1f} 分钟（{done / el:.1f} 个/秒）")
    print(f"本轮体积 {total_bytes / 1024**3:.2f} GB，平均 {total_bytes / max(done,1) / 1024:.1f} KB/个")
    print(f"清单合计 {len(kept) + done:,} 条 → {manifest_path}")
    # 🔴 项目教训：统计里"跳过"那一栏必须逐条看得见，不能只报个数
    if voiceless:
        print(f"\n⚠️ 合成不出音频、已跳过 {len(voiceless)} 个：")
        for word, tag in voiceless[:40]:
            print(f"    {word!r}  ({tag})")
        if len(voiceless) > 40:
            print(f"    …… 另有 {len(voiceless) - 40} 个")
    for p in tmp_dir.glob("*.wav"):
        p.unlink()
    tmp_dir.rmdir()


if __name__ == "__main__":
    main()
