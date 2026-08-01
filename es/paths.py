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
