#!/usr/bin/env python3
"""韩语数据路径 —— **本语种数据位置的唯一真相源**。2026-09-20。

═══ 为什么有这个文件 ═══
数据全部在仓库根的 `data/`，代码目录下不放任何数据字节；路径只在本文件声明一次，
其余脚本 `import paths` 取用。（沿革见 `de/paths.py` 文件头。）

═══ 🔴 韩语的第一个不同：**中文版不是补料，它比英文版大三倍** ═══
前七门的惯例是「英文版 per-language 切片当骨架、别的版本补料」。
`PLAYBOOK` 1.3 跑出来的数（2026-09-20 实测，五份源逐行扫）把这条惯例掀了：

    源                     词头        有释义    真义项    IPA     变形词形   词源文
    英文版 Korean         57,252     51,163    75,263   40,123   359,583   38,796
    韩文版 한국어        104,492     68,222    77,791   71,016    30,982        0
    中文版 朝鲜语(简)    195,332    195,265   199,909      701       718        0
    中文版 朝鮮語(繁)     45,130     43,250    48,750    6,277    16,632        0
    日文版 朝鮮語         29,674     29,671    40,154   15,431       824        0

⇒ **按层各归各家**（判据是上表，不是惯性）：
  · **结构/活用/词源/义项骨架 —— 英文版**。韩语用言活用表在英文版里是**全的**
    （359,583 个变形词形，99.6% 的条目带 forms），敬语阶 × 时制 × 语气三维都在
    （form tags: formal 213,689／informal 209,529／polite 156,902／past 107,444…）。
    🔴 **与日语相反**：ja 的活用只有日语版才有、英文版只给 7.0%。别把 ja 的结论搬过来
    （`[[es-v3-structure-backfill]]`：照搬别的语言结构前先量这门语言有没有那个病）。
  · **词源 —— 只有英文版有**，38,796 条（60.8%）。另外四份**全是 0 条**，不是少，是没有。
  · **读音 —— 韩文版最多**（71,016 条 IPA，比英文版多 30,893），且四套罗马字齐全
    （revised／RR-transliteration／McCune-Reischauer／Yale，roman 字段 338,008 个）
    ＋ **发音形谚文**（`읽다` 的 `tags:[phonetic]` → `익따`，音变后的实际读法）。
  · **中文释义 —— 中文版两片，合计 238,507 个有释义词头**，是 ja（83,234）的 2.9 倍。

═══ 🔴🔴 中文版那 19.5 万词头：**80% 是另外四份源里根本没有的真词** ═══
简体片 195,332 个词头里 **156,966 个（80.4%）不在 英文版∪韩文版** 里，
且 **99.99% 是纯谚文**（hangul 156,950／hanja 8／其他 8）。抽样看全是常用词而非垃圾：
`가다가다`（偶尔）`가득차다`（装满）`간절히`（恳切地）`갈라놓다`（分开）。
⚠️ 但它们**只有释义**：pos 99.5% 是 `unknown`、IPA 701 条、forms 718 条、词源 0。
⇒ 全量收进来会造出十几万个「有中文释义、没词性没读音没活用」的半成品词条，
  也就是 pt 栽过的那个形状（`PLAYBOOK` 四：**355,605 个词形＝搜得到、点进去空白页**）。
  **收不收、怎么收，是 `KO_PLAN` §一要回答的第一个问题**，别顺手全收。

═══ 🔴 已经踩实的两个陷阱（实测，不是印象）═══
① **罗马字转写会长进 `forms` 里冒充词形**：英文版 59,148 个、韩文版 34,396 个 form
   带 `romanization`/`transliteration` tag（`gyoga`、`bakkuda` 这种）。
   不剔掉就会把六位数的拉丁串当韩语词形收进库。判据用 tag，**不用「长得像不像拉丁字母」**
   （`[[criteria-from-meaning-not-form]]`）。
② **中文版把元数据塞进 `examples`**：`가을` 的 examples 里混着
   `近义词：추`／`派生詞：늦가을，올가을…`／`季节：봄 - 여름 - 가을 - 겨울` ——
   它们是关系数据不是例句。送模型之前必须先过滤，顺序反了就会把「近义词：추」当例句翻出来
   （`PLAYBOOK` 5.5 的同一个坑）。

═══ ⭐ 录音：韩文版**在词条里嵌音频**，与日语相反 ═══
韩文版 1,017 个 `mp3_url`（963 个 ogg／68 wav／54 oga），中文繁体 124、日文版 54，
而**英文版只有 27** —— 照「英文版是骨架」的惯性只量英文版，会得出「韩语没有真人录音」。
⚠️ 这仍然只是 **dump 这一个入口**的数。Commons 分类 / LinguaLibre 要另外量，
   别重犯 ja 阶段 6 那个错（`[[dont-say-source-lacks-what-we-skipped]]`：
   「dump 里没有」不等于「拿不到」）。够不够用要按**核心词覆盖**问，不按全库覆盖问。

═══ 关于 `한자` 那份小切片 ═══
韩文版把「汉字」单列成一个**语种**（`lang: 한자`，`lang_code: unknown`），3,917 个字、
5,185 条义项，释义是韩语写的（`言` → `말씀, 말`）。它不在 `한국어` 切片里。
⚠️ 与 ja 的 `kanji_reading` 不是一回事：那是**读音**表，这是**字义**表。
   要不要用、怎么接，等 `KO_PLAN` 阶段 4 再定 —— **别凭「日语有所以韩语也该有」排工**。

═══ ⚠️ 盘上那个容易看错的文件 ═══
`data/dumps/kaikki.org-kowiktionary-Portuguese.jsonl.gz` **不是韩语数据**，
它是韩文版维基词典里的**葡萄牙语**词条，pt 那轮收的（`[[cross-edition-harvest]]`）。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # 仓库根
DATA = ROOT / "data"

DB          = DATA / "db" / "synapse-dict-ko.sqlite"                          # 成品库（尚未建）

# ── 五份源（2026-09-20 下齐，字节数与 kaikki 的 Content-Length 逐份核对过）──
KK          = DATA / "dumps" / "kaikki.org-dictionary-Korean.jsonl"           # 英文版切片 191.6 MB / 63,773 行
EDITION     = DATA / "dumps" / "kaikki.org-kowiktionary-Korean.jsonl"         # 韩文版切片 140.6 MB / 108,909 行
HANJA       = DATA / "dumps" / "kaikki.org-kowiktionary-Hanja.jsonl"          # 韩文版「한자」切片 1.7 MB / 4,023 行
ZH_SIMP     = DATA / "dumps" / "kaikki.org-zhwiktionary-Korean-simp.jsonl.gz" # 中文版「朝鲜语」6.2 MB / 195,435 行
ZH_TRAD     = DATA / "dumps" / "kaikki.org-zhwiktionary-Korean-trad.jsonl.gz" # 中文版「朝鮮語」2.9 MB / 46,471 行
JA_EDITION  = DATA / "dumps" / "kaikki.org-jawiktionary-Korean.jsonl.gz"      # 日文版「朝鮮語」1.9 MB / 31,154 行

# 🔴 中文版取的是**切片不是整包**（`data/dumps/README.md`：下切片别下整包）。
#    盘上那份 `zhwiktionary.jsonl.gz`（215 MB，ja 用的）里按 lang_code=='ko' 能筛出
#    241,659 条，两个切片合计 241,906 行 —— 差 247 条，是切片里 lang_code 非 ko 的边角
#    （繁体片里有 `lang_code:unknown` 的汉字表记条目）。⚠️ 真要拿两条路互相背书时
#    先解释这 247 条，别默认两边等价。
#
# 🔴🔴 中文版是**两个独立切片，不是同一批的简繁两种写法**：
#    简体片 195,332 词头／繁体片 45,130 词头，交集只有一小部分，而且分工完全不同 ——
#    简体片几乎只有「词＋中文释义」（pos 99.5% unknown），
#    繁体片才带结构（noun 38,175 条、hanja/hangeul 对应 form 13,758 个、IPA 6,277）。
#    **两片都要收，谁也替不了谁。**

WORK        = DATA / "work" / "ko"                  # 过程产物：runs / 冲突表 / 模型输出
BACKUPS     = DATA / "backups"                      # 写库前的自动备份
DUMPS       = DATA / "dumps"
ENV         = ROOT / ".env"
