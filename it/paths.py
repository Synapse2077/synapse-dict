#!/usr/bin/env python3
"""意大利语数据路径 —— **本语种数据位置的唯一真相源**。2026-08-01。

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

DB      = DATA / "db" / "synapse-dict-it.sqlite"                    # 成品库
KK      = DATA / "dumps" / "kaikki.org-dictionary-Italian.jsonl"                 # 英文版 per-language 切片（建库源）
EDITION = DATA / "dumps" / "itwiktionary.jsonl.gz"        # 该语种自己的维基版整包（多语种，按 lang_code 筛）
WORK    = DATA / "work" / "it"                  # 过程产物：runs / 冲突表 / 模型输出
BACKUPS = DATA / "backups"                          # 写库前的自动备份
DUMPS   = DATA / "dumps"
ENV     = ROOT / ".env"

# ═══ 合成发音（阶段 6b）═══
# TTS_VOICES 是 Piper 模型目录，**六语种共用**（各语种取自己的那几个文件）。
# TTS_OUT 下按 sha1(词|音色) 前两位分 256 个子目录 —— 单目录放十几万文件时
# macOS 的 `ls` 与 Finder 都会卡。音频字节**不进 SQLite**：`dbtool` 每次写库前
# 要全文件复制备份，塞进音频后每改一行译文都要多复制几 GB。
TTS_VOICES = DATA / "tts" / "voices"
TTS_OUT    = DATA / "tts" / "it"

# ═══ 跨版切片（2026-08-12 阶段 -1 取数）═══
# 取数依据是实测，不是印象：`probe_editions.py --lang it` 的完整输出存档在
# `data/work/it/probe/`，各版本贡献的字段见 `docs/lang/it-CONVENTIONS.md` 的取数表。
# 🔴 最反直觉的一条：**法语版的意语义项 1,309,451 条，是英文版（719,428）的 1.82 倍**。
# ⚠️ 一律下 per-language 切片，不下整包：fr 切片 62 MB vs 整包 676 MB。
KK_FR   = DATA / "dumps" / "kaikki.org-frwiktionary-Italian.jsonl.gz"       # 存量最大
KK_ZH_T = DATA / "dumps" / "kaikki.org-zhwiktionary-Italian-trad.jsonl.gz"  # 中文版「意大利語」
KK_ZH_S = DATA / "dumps" / "kaikki.org-zhwiktionary-Italian-simp.jsonl.gz"  # 中文版「意大利语」——
                                                                            # 同一语言两个本地名是两个独立切片，都得取
KK_EL   = DATA / "dumps" / "kaikki.org-elwiktionary-Italian.jsonl.gz"       # 只用于录音/词形并集
KK_TR   = DATA / "dumps" / "kaikki.org-trwiktionary-Italian.jsonl.gz"       # 同上（探测器原来漏认 İtalyanca）
