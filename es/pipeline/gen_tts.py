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

═══ 用法 ═══
    python -m es.pipeline.gen_tts --level A1,A2,B1              # 核心层，主力音
    python -m es.pipeline.gen_tts --level A1,A2,B1 --peninsular # 再补 θ 词的半岛音
    python -m es.pipeline.gen_tts --lemma                       # 全部 lemma
    python -m es.pipeline.gen_tts --all-forms                   # 全部词形
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
    g.add_argument("--level", help="逗号分隔，如 A1,A2,B1")
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

    if args.only_peninsular:
        args.peninsular = True

    # ── 取词表 ──────────────────────────────────────────────────────────
    con = sqlite3.connect(paths.DB)
    if args.level:
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
