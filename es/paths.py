#!/usr/bin/env python3
"""西班牙语数据路径 —— **本语种数据位置的唯一真相源**。2026-08-01。

═══ 为什么有这个文件 ═══
2026-08-01 之前，数据（sqlite / dump / bak / tsv / jsonl）和代码混在同一个语种目录下，
127 个脚本各自硬写 `HERE / "synapse-dict-xx.sqlite"` 这类字面量。后果是：
  · 数据没有"户口" —— 哪来的、哪天下的、多少条、谁在用，全靠人记；
  · 想挪动任何一份数据，就得改上百处；
  · 一个目录里既有 1.9 GB 数据又有 35 个脚本，三个月后自己都读不懂。
→ 数据全部迁到仓库根的 `data/`，代码目录下不再存放任何数据字节。
   路径只在本文件声明一次，其余脚本 `import paths` 取用。

清单见 `data/MANIFEST.md`。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # 仓库根
DATA = ROOT / "data"

DB      = DATA / "db" / "synapse-dict-es.sqlite"                    # 成品库
KK      = DATA / "dumps" / "kaikki.org-dictionary-Spanish.jsonl"                 # 英文版 per-language 切片（建库源）
EDITION = DATA / "dumps" / "eswiktionary.jsonl.gz"        # 该语种自己的维基版整包（多语种，按 lang_code 筛）
WORK    = DATA / "work" / "es"                  # 过程产物：runs / 冲突表 / 模型输出
BACKUPS = DATA / "backups"                          # 写库前的自动备份
DUMPS   = DATA / "dumps"
ENV     = ROOT / ".env"

# ═══ 合成发音（2026-08-05）═══
# 音频字节**不进 SQLite**（理由同 ingest_audio.py：dbtool 每次写库前全文件复制备份）。
# TTS_VOICES 是 Piper 模型（跨语种共用一个目录，各语种取自己的那几个）。
# TTS_OUT 下按 sha1(word) 前两位分 256 个子目录 —— 单目录放 16 万文件时
# macOS 上 `ls` 和 Finder 都会卡，分片后每个目录 600 来个文件。
TTS_VOICES = DATA / "tts" / "voices"
TTS_OUT    = DATA / "tts" / "es"                 # 成品音频 + manifest.tsv

# ═══ 真人录音落盘（2026-08-11）═══
# 此前 `audio` 表只存 Commons 的 URL，播放时由浏览器直接向 upload.wikimedia.org 取。
# 代价是**质量最高的那一级发音是唯一有外网依赖的**，而且 `HumanAudioRow` 的死链回落
# 是静默的（chip 变灰 + 换成 TTS），URL 烂掉多少界面上根本看不出来。
# 实测全量 11,203 条 mp3 中位 23.7 KB ⇒ 约 276 MB，只有合成音的 1/8 ⇒ 直接落盘。
# 布局与 TTS 一致：按 sha1(Commons文件名) 前两位分 256 个子目录。
# 🔴 分片键是**文件名**不是 URL —— 同一条录音在 Commons 上有 mp3/ogg/wav 多个 URL，
#    按 URL 去重会把 11,203 条算成 22,367（ingest_audio.py 踩过）。
AUDIO_OUT  = DATA / "audio" / "es"               # 真人录音 + manifest.tsv
