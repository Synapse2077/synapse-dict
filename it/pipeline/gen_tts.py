#!/usr/bin/env python3
"""合成发音：Piper 生成 TTS 音频，落文件系统。it 版，2026-08-18（阶段 6b）。

方针④三级兜底「真人 > 工具生成 > 浏览器 TTS」里的**中间那级**。
意语的真人录音只覆盖 9,404 个词形（全部词形的 0.6%、词头的 5.5%，见 `ingest_audio_urls.py`），
剩下的靠这里补。

⚠️ 本文件是从 `es/pipeline/gen_tts.py` **抄过来改的，不是 import 的** ——
   六语种按语种解耦、互不引用（`multilang-decoupling-essence`）。es 那边的坑注释一并留着，
   因为它们是 Piper/afconvert 的坑，不是西语的坑。

═══ 一个音色就够，不像 es 要两个 ═══
    it_IT-serena-high     length_scale 1.0    单说话人、22 050 Hz
es 需要第二个音色是因为半岛音 θ 与拉美音 s 是**真差别**；意语没有这种全国性的两分
（源头给的地区限定是 `Milan` / `Romanesco` / `Monopoli` 这类零散方言，全库约 600 条，
见 A58）⇒ **一个标准音色覆盖全部**，不做地区分叉。

═══ 取词判据用 `freq_zipf`，不用 `level`（沿用 es 2026-08-10 的结论）═══
`level` 是全库唯一没有源、也无法回源的字段，且**只给内容词打了标、语法词全 NULL**
—— es 上因此漏掉了 `es/me/hay/está/fue/son` 这些最常用词。it 这边分层实测：

    zipf ≥ 4       8,055 个    0.10 GB / 0.2 小时
    zipf ≥ 3      34,057 个    0.41 GB / 0.7 小时
    zipf ≥ 2      92,933 个    1.12 GB / 2.0 小时
    全部有频次   197,445 个    2.37 GB / 4.2 小时   ← 默认做到这层

⭐「全部有频次」是**自然分界线**不是拍脑袋的阈值：另外 130 万个词形在 wordfreq 里
   查不到（`freq_zipf = 0.0` 或 NULL）= 跑动文本里量不出来，按方针④落到第三级浏览器 TTS。

═══ 三个会让人白跑一遍的坑（es 上踩过，原样保留）═══
🔴 ① `ESPEAK_DATA_PATH` 不设，piper **静默产出 0 字节文件**，不报错、不抛异常。
     本脚本启动时自证一次。
🔴 ② **别开多进程。** ONNX 自己就把物理核吃满，多进程反而更慢（es 实测 28.8 → 16.5 词/秒）。
     并发只用在 afconvert 上 —— 那是外部进程，等的是 I/O。
🔴 ③ 转码用 macOS 自带的 **`afconvert`**，不装 ffmpeg。WAV 母带不留。

═══ 落盘布局与哈希契约 ═══
    data/tts/it/<sha1[:2]>/<sha1>.m4a        sha1 = sha1(f"{word}|{voice_tag}")
    data/tts/it/manifest.tsv                 word / voice / rel_path / bytes / dur

🔴 **哈希契约在两种语言里各写了一遍**：这里的 `digest()` 与
   `packages/dict-core/src/italian.ts` 的 `ttsFor()`。差一个字节，前端就永远
   `existsSync` 失败、**静默**全部降级到浏览器 TTS：不报错、不 404，只是所有词
   突然都"没有合成音"。⇒ `probes/tts_contract.ts` 逐条比对两端，`--mutate` 造错验闸。

═══ 用法（在 it/ 目录下）═══
    python3 pipeline/gen_tts.py --freq            # 全部有频次的词形（默认）
    python3 pipeline/gen_tts.py --freq 3          # 只要 zipf ≥ 3
    python3 pipeline/gen_tts.py --lemma / --all-forms
    python3 pipeline/gen_tts.py --verify          # 验收闸：清单 ↔ 磁盘 ↔ 哈希契约
    python3 pipeline/gen_tts.py --mutate          # 变异验证
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths  # noqa: E402

VOICES = {
    # tag        模型文件                     speaker  length_scale
    "it": ("it_IT-paola-medium.onnx", None, 1.0),
}
# 🔴 **为什么是 medium 不是 high**（2026-08-18 实测，不是偏好）：
#    同样 60 个词、同一台机器、各自预热后计时 ——
#        it_IT-serena-high     4.6 词/秒   ⇒ 全量 197,445 个要 **12 小时**
#        it_IT-paola-medium   22.2 词/秒   ⇒ 全量 **2.5 小时**（4.8 倍）
#    产出音频体积两者相当（1.7 vs 1.9 MB / 60 词）。词典里念的是**孤立单词**，
#    high 档的收益主要在长句韵律上 ⇒ 拿 4.8 倍机器时间换它不划算。
#    ⚠️ 两个音色的文件路径**一样**（`sha1(词|it)`，tag 不变）⇒ 换音色必须先清空旧文件，
#      否则库里混着两个人的声音，而且从路径上看不出来。
BITRATE = 48000          # AAC kbps ×1000。32k 也够用，核心层两者只差 30 MB
SILENCE_THR = 0.02       # 切静音的相对峰值阈值，只用于量时长


def digest(word: str, tag: str) -> str:
    return hashlib.sha1(f"{word}|{tag}".encode()).hexdigest()


def speech_text(word: str) -> str:
    """词形 → 送进 TTS 的文本。

    库里有 `a-` / `-mente` / `-issimo` 这类词缀条目。连字符直接喂给
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
#    `packages/dict-core/src/italian.ts` 的 `ttsFor()`。两边差一个字节，
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
        ("🔴 路径 ≠ sha1(词|音色)（与 italian.ts 的契约）", len(hash_bad), hash_bad),
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
    dur = synth_wav(voice, "prova", None, 1.0, p)
    size = p.stat().st_size if p.exists() else 0
    p.unlink(missing_ok=True)
    if size < 2000 or dur == 0:
        sys.exit(f"✗ 自证失败：合成 'prova' 只有 {size} 字节。"
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
    ap.add_argument("--force", action="store_true", help="已存在也重新生成")
    ap.add_argument("--limit", type=int, help="只跑前 N 个，试跑用")
    ap.add_argument("--jobs", type=int, default=4, help="afconvert 并发数（默认 4）")
    args = ap.parse_args()

    if args.verify or args.mutate:
        ok = verify(paths.TTS_OUT, paths.TTS_OUT / "manifest.tsv")
        if args.mutate:
            mutate_verify()
        sys.exit(0 if ok else 1)

    # ── 取词表 ──────────────────────────────────────────────────────────
    con = sqlite3.connect(paths.DB)
    if args.freq is not None:
        # `dict.word` 全库唯一（1,139,125 行 = 1,139,125 个不同词形），所以这里
        # 取出来不会有同词重复行，不需要去重。换表结构后这条要重新验。
        rows = con.execute(
            "select word, ipa from dict where freq_zipf is not null "
            "and freq_zipf > 0 and freq_zipf >= ? order by freq_zipf desc", (args.freq,)).fetchall()
        scope = ("全部有频次的词形" if args.freq < 0 else f"zipf ≥ {args.freq}")
    elif args.level:
        levels = [x.strip() for x in args.level.split(",")]
        sql = (f"select word, ipa from dict where level in "
               f"({','.join('?' * len(levels))})")
        rows = con.execute(sql, levels).fetchall()
        scope = f"level {args.level}"
    elif args.lemma:
        rows = con.execute("select word, ipa from dict where is_lemma=1").fetchall()
        scope = "全部 lemma"
    else:
        rows = con.execute("select word, ipa from dict").fetchall()
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
        jobs.append((word, text, "it"))

    n_mx = len(jobs)
    n_es = 0
    print(f"范围 {scope}：{len(rows):,} 个词形")
    if skipped_empty:
        print(f"  剥完连字符为空、跳过：{skipped_empty}")
    print(f"  主力音 it  {n_mx:,}")

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
