#!/usr/bin/env python3
"""日语数据路径 —— **本语种数据位置的唯一真相源**。2026-09-15。

═══ 为什么有这个文件 ═══
数据全部在仓库根的 `data/`，代码目录下不放任何数据字节；路径只在本文件声明一次，
其余脚本 `import paths` 取用。（沿革见 `de/paths.py` 文件头。）

═══ 🔴 日语与前六门的第一个不同：**建库源不是一份，是两份，而且分工不能反** ═══
前六门的惯例是「英文版 per-language 切片当骨架、本语种版补料」。日语上这条**部分失效**：

    英文版切片（KK）     词条骨架 / 义项 / 假名读音 / 罗马字 / IPA —— 全在这儿
                         ⚠️ 但**动词活用只给了 975/13,921 个动词（7.0%）**，中位数 2 个形
    日语版切片（EDITION） **活用表在这儿**（19,564 词 / 336,940 行 / 中位 19 个形）
                         ⚠️ 但它的**声调数据在抽取时就毁了**（10,215 条里 10,212 条的
                            `other` 字面是 `"("`，重音位置全丢），且存活的是京阪式不是东京式
    中文版（ZH_EDITION） **声调唯一可用的来源**（东京式 `raw_tags` 占 99.75%）
                         + 免费中文释义（覆盖英文版真词条目约 37%）

⇒ 照「英文版是结构基准」的惯性走，会得出「日语动词几乎不活用」这个荒谬结论。
   `[[multi-edition-methodology]]`：英文版是**结构**基准，不是**内容**上限。

🔴 **录音：dump 不是日语的来源，Commons 分类才是。**
   三版并集只有 232 个词形有内嵌音频 —— 不是 `[[cross-edition-harvest]]` 记的
   「语言版比英文版多 436 倍」，日语版维基词典**根本不在词条里嵌音频**。
   ⚠️ 2026-09-16 更正：本文件原来据此写着「直接跳过、别排工」——
      **事实对、结论错**。那句话把「dump 里没有」等同于「拿不到」
      （`[[dont-say-source-lacks-what-we-skipped]]`：源头没写 ≠ 我们没抽）。
      Commons 的日语发音分类实测约 1,500 个文件，同样零下载只存 URL，
      入口换一个就行 ⇒ 见 `ja/pipeline/harvest_audio.py`。
   ⚠️ 但**量确实少**：LinguaLibre 日语 1,043，对照法语 436,115／德语 26,112。
      按核心词算，最常用 500 个词里 **16.2%** 听得到（5,000 个里 7.0%）—— 靠方针④的三级兜底补
      （`[[dict-scope-four-rules]]`）。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # 仓库根
DATA = ROOT / "data"

DB          = DATA / "db" / "synapse-dict-ja.sqlite"                        # 成品库
KK          = DATA / "dumps" / "kaikki.org-dictionary-Japanese.jsonl"       # 英文版切片 315 MB / 199,484 行
EDITION     = DATA / "dumps" / "kaikki.org-jawiktionary-Japanese.jsonl"     # 日语版切片 181 MB / 148,279 行
ZH_EDITION  = DATA / "dumps" / "zhwiktionary.jsonl.gz"                      # 中文版整包，按 lang_code=='ja' 筛
WORK        = DATA / "work" / "ja"                  # 过程产物：runs / 冲突表 / 模型输出
BACKUPS     = DATA / "backups"                      # 写库前的自动备份
DUMPS       = DATA / "dumps"
# 第三方参考词表（2026-09-19）。⚠️ **不是权威表，是民间重建**：JLPT 官方 2010 年改制后
# 不再公布词汇表 ⇒ 只当内部尺子（挑核心词/算覆盖率），不作读者可见的难度标签。
# 授权、匹配率、尚未履行的署名义务全写在该目录的 README.md 里，用它之前先读。
CORE_LIST   = DATA / "refs" / "jlpt-waller"
ENV         = ROOT / ".env"
