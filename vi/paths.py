#!/usr/bin/env python3
"""越南语数据路径 —— **本语种数据位置的唯一真相源**。2026-09-28。

照 `es/paths.py` / `ko/paths.py` 抄（`PLAYBOOK` 1.1）：数据全在仓库根 `data/`，
代码目录下不存放任何数据字节；路径只在本文件声明一次，其余脚本 `import paths` 取用。
清单见 `data/MANIFEST.md`。

═══ 🔴🔴 阶段 -1 逮到的第一个陷阱：**词源字段名三个版本不一样** ═══
英文版写 `etymology_text`（**单数**），越南文版与中文版写 `etymology_texts`（**复数**）。
我第一遍只扫单数，两版都得到 **0.0%**，差一点写进账本当成「源头没有词源」。

    只认单数：词源并集 25,321
    两个都认：词源并集 **43,785**      ⇒ 不核这个 0 就丢掉 42%

⚠️ **当天晚些时候这个 43,785 又被自己推翻了一次，方向相反** ——
   中文版那 25,946 条里 **21,155（81.5%）整段只是 `thư viện［書院］`**，那是**汉字表记不是词源**。
   真散文词源：en 25,321 ／ vi 7,457 ／ zh 4,791 ／并集 **27,878（33.1%，不是 51.9%）**。
   ⇒ 同一个字段上，判据**先太窄（漏 42%）后太宽（虚报 15 倍）**。
     两次都不是读错数据，是**没问「这个数量的是哪件事」**。
     判据可重跑：`vi/probes/probe_primary_source.py` §I。

⚠️ 这与 ko 的 **K36** 是同一形状（「只有英文版有词源」是**从错的字段名上读到的一个 0**），
   区别只是 ko 那次做到阶段 7 才被用户问出来，这次在开工第一天。
⇒ **判据：写「某版没有 X」之前，先把该版的顶层字段名全打出来看一眼。**
   （`[[dont-say-source-lacks-what-we-skipped]]`：「源头没写」和「我们没抽」要在结构上分开。）

═══ 🔴 第二个陷阱：`forms` 里装的**不是**屈折 ═══
越南语是分析语，不变位不变格。但英文版 `forms` **有 33,020 行**，tag 分布是：

    CJK 13,361 ／ Hán-Nôm 9,799 ／ alternative 4,647 ／ classifier(量词) 4,344 ／
    romanization 457 ／ reduplication 161

**全是汉字表记、异体、量词，一条屈折都没有。**（越南文版只有 377 行，同理。）
⇒ 照搬别门的 `build_inflection_layer` 会把**汉字表记当成变形形**收进库。
   变形层对 vi 应当是**有意为空**，而「有意为空」要按 `PLAYBOOK` 7.5 写清什么会推翻它。

═══ ✅ 「什么是一个越南语词条」—— kaikki 已经分好词了 ═══
`word` 字段直接存带空格的完整词（`sinh viên` 学生 = 两个音节一个词）。含空格的比例：

    英文版 **47.9%** ／ 越南文版 **81.3%** ／ 中文版 65.8%

⇒ **数据层没有分词问题**，`dict.word` / `word_norm` 可以照搬八门。
⚠️ 分词问题只剩在**搜索与划词**上（用户输 `sinh` 要不要出 `sinh viên`），那是展示层的活。
⚠️ 也因此 `BACKLOG` **B2**（`split_colloc` 的空格判据，de/pt/fr 三门）在 vi 上**必然发作** ——
   搭配层若要做，必须先把那条判据改掉。

═══ ⭐ 汉越词：ko 的汉字层结构可以直接搬 ═══
① 英文版 `forms[tags 含 CJK/Hán-Nôm]` ⇒ **3,759 个词形有汉字表记、6,509 对**
   —— 与 ko 的 `forms[tags=hanja]` 形状一模一样（多候选进 `hanja_spelling`）。
② 英文版**词源正文** 29,098 条里 **14,024（48.2%）** 提到汉越，13,985 条正文真带汉字：
   `y → Sino-Vietnamese word from 伊.`／`in → Non-Sino-Vietnamese reading of Chinese 印`
   —— 结构化程度高，是汉越层的主源。
⚠️ **中文版的 gloss 栏靠不住**：里面自带 `［常］` 这类标注，但只覆盖 **97 个词形 / 161 对**。
🔴🔴 **但别把这句话推广到整个中文版** —— 中文版的**词源栏**里藏着一张汉字表记表，
   形状规整（`thư viện［書院］`），收窄判据后命中 **21,155 个词形**，
   是英文版 `forms` 的 **4.4 倍**（4,806）。两源形状还互补：zh 单候选 / en 多候选。
   ⇒ **汉字层的主源是中文版，不是英文版。** 我差点丢掉它，因为第一版判据只找
     「漢越/汉字/喃/借自」，把这 2.1 万条扔进了「其他」桶
     （`[[residual-bucket-is-not-evidence]]`）。

═══ 🔴🔴 第三件事：中文释义的可用率**量了三次还没收敛** ═══
    ① 我自写的元描述正则          ⇒ 元描述  0.8%
    ② 抽样 20 条人工读            ⇒ **当场打回**：至少 8 条不是释义
    ③ 拿英文版汉字表记去对(ko K24) ⇒ 元描述 22.3%／就是汉字 0.3%／存疑 3.6%／真释义 73.9%

**73.9% 是上界不是真值** —— 第③版的「真释义」桶里仍有污染，已知两类：
  · `la → 儸 囉(啰) 攎 攞 欏(椤) …`（汉字列表，因带括号躲过了「纯汉字」判据）
  · `啊 → a (“發語詞：啊，噢”) 的喃字`（**`的喃字`** 是我漏掉的元描述写法）
⇒ 阶段 5 必须用**写进 pipeline、可 import 的判据**重量，别再各写一版
   （`[[criteria-narrower-than-you-think]]`：判据比它要描述的东西更宽，是最高频自伤）。

═══ 三源互补性极强，谁当主源**尚未定** ═══
    英文版 45,281 词形 ／ 越南文版 41,507 ／ 交集只有 **19,681**
    en 独有 25,600 ／ vi 独有 21,826 ／ **三源并集 84,328**

⇒ 八门的两种分工（前七门「英文版主源」、ko「整个反过来」）**都不适用**，要另定。
   这是待决项之一，见 `docs/VI_PLAN.md` §四。

═══ ⚠️ 音标只有 58.3%，低于方针②「音标全」 ═══
并集 49,130 / 84,328。（对照：it 73.5%。）越南文版反而给得最多（34,047 > 英文版 28,634）。
越南语现代文字是为表音设计的，拼写→读音规则性高，G2P 可能比西语准 ——
但 `PLAYBOOK` 3.3 写着「别用 G2P 重算」，**必须先验后用**（拿本版真值当标尺）。待决项之二。

═══ 这五个版本**确实没有**越南语（核过，不是我的模式没写对）═══
es / it / el / tr / cs 五版：用比 `NAMES` 宽得多的判据
（`viet|wiet|việt|越南|ベトナム|베트남|вьетнам|βιετναμ`）回扫它们的**完整**语种表，
命中都是 **0**。这五版本身收录面就窄（es 60 种、it 42、el 46、tr 72、cs 34）。
⚠️ `probe_editions.py` 那句「没匹配到」有两种成因（源头真没有／我的模式错了），
   它自己分不出来 —— 那条注释已经记了四次栽跤，这次是核完才下的结论。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # 仓库根
DATA = ROOT / "data"

DB = DATA / "db" / "synapse-dict-vi.sqlite"        # 成品库（尚未建）

# ── 三份主源（2026-09-28 下齐；行数与字节数当天实测）──────────────────────
KK      = DATA / "dumps" / "kaikki.org-dictionary-Vietnamese.jsonl.gz"          # 英文版   12.1 MB /  51,896 行
EDITION = DATA / "dumps" / "kaikki.org-viwiktionary-Vietnamese.jsonl.gz"        # 越南文版  7.6 MB /  44,564 行
ZH_TRAD = DATA / "dumps" / "kaikki.org-zhwiktionary-Vietnamese-trad.jsonl.gz"   # 中文版繁  2.4 MB /  40,387 行
ZH_SIMP = DATA / "dumps" / "kaikki.org-zhwiktionary-Vietnamese-simp.jsonl.gz"   # 中文版简  0.1 MB /   5,129 行

# 🔴 中文版简繁的分工与 **ko 正好相反**：
#    ko 是简体片大（195,332 词头）、繁体片才带结构；
#    vi 是**繁体片大**（40,387 行 / 43,908 义项），简体片只有 5,129 行。
#    ⇒ 「照 ko 的经验先读简体片」会拿到小的那一份。两片都要收，但主力是 trad。

# ── 跨版收割（`[[cross-edition-harvest]]`：语言版 dump 里有大量其他语言的词条且带音标）──
FR_EDITION = DATA / "dumps" / "kaikki.org-frwiktionary-Vietnamese.jsonl.gz"     # 2.1 MB / 18,255 行 / 26,533 义项
JA_EDITION = DATA / "dumps" / "kaikki.org-jawiktionary-Vietnamese.jsonl.gz"     # 0.6 MB / 13,223 行 / 15,747 义项
KO_EDITION = DATA / "dumps" / "kaikki.org-kowiktionary-Vietnamese.jsonl.gz"     # 0.5 MB /  5,503 行 /  5,930 义项
# 长尾四份（合计 < 0.5 MB / 7,386 行）。单份都不大，但 it 的教训是**别凭大小判断价值**
# （意语版 38 MB 只有 4 万条意语音标，而法语版里的意语有 68 万条）。收不收等阶段 3 再定。
PL_EDITION = DATA / "dumps" / "kaikki.org-plwiktionary-Vietnamese.jsonl.gz"     # 2,733 行 / 2,893 义项
RU_EDITION = DATA / "dumps" / "kaikki.org-ruwiktionary-Vietnamese.jsonl.gz"     # 1,831 行 / 2,023 义项
NL_EDITION = DATA / "dumps" / "kaikki.org-nlwiktionary-Vietnamese.jsonl.gz"     # 1,711 行 / 2,132 义项
PT_EDITION = DATA / "dumps" / "kaikki.org-ptwiktionary-Vietnamese.jsonl.gz"     # 1,134 行 / 1,269 义项
DE_EDITION = DATA / "dumps" / "kaikki.org-dewiktionary-Vietnamese.jsonl.gz"     # 1,108 行 / 1,210 义项

WORK    = DATA / "work" / "vi"                     # 过程产物：probe / runs / 冲突表 / 模型输出
PROBE   = WORK / "probe"                           # 阶段 -1 的探测存档
BACKUPS = DATA / "backups"                         # 写库前的自动备份
DUMPS   = DATA / "dumps"
ENV     = ROOT / ".env"

# ⚠️ 盘上没有 vi 的**整包**（`viwiktionary.jsonl.gz`），这是**有意的**：
#    `PLAYBOOK` 1.2「下切片别下整包」。越南文版整包里越南语只占 546,240 中的 56,502（10.3%），
#    取切片 7.6 MB 就够。同理中文版整包 215 MB 盘上已有（ja 那轮下的），vi 只取 2.5 MB 切片。
