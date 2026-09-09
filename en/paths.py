#!/usr/bin/env python3
"""英语数据路径 —— **本语种数据位置的唯一真相源**。2026-08-01。

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

DB      = DATA / "db" / "synapse-dict-en.sqlite"                    # 成品库

# ═══ 🔴 en 是六门里唯一盘上同时留着两个版本主源的 ═══
# 另五门的建库源都是不带日期的规范名、只有一份；en 有意留两份并**都带日期**，
# 理由是这门语言的版本漂移已经骗过我一次（2026-09-06，见 docs/EN_PLAN.md §1.4）：
# 我拿「kaikki 只比库里多 93 个词」下过「换基底收词收益为零」的结论，
# 而那 93 是**同源自比** —— 库里那 52.7 万 Wiktionary 层就是 KK_2025 灌进去的。
# ⇒ 不留一个不带日期的名字，任何一处引用都必须说清楚它读的是哪一版。
KK      = DATA / "dumps" / "kaikki.org-dictionary-English-20260828.jsonl"   # 建库源（v3 主干）3.21 GB
KK_2025 = DATA / "dumps" / "kaikki.org-dictionary-English-20250424.jsonl"   # 存证：现库 52.7 万新词层的来源
#         ⚠️ KK_2025 一个字节都不许删（[[external-anchor-gates]]：锚外部 dump 的闸永不过期）。
#         de 那轮七月的包被保留策略清掉，直接导致 16,483 个词形的读音**说不清是哪来的、也补不回来**。
WORK    = DATA / "work" / "en"                  # 过程产物：runs / 冲突表 / 模型输出
BACKUPS = DATA / "backups"                          # 写库前的自动备份
DUMPS   = DATA / "dumps"
ENV     = ROOT / ".env"
