#!/usr/bin/env python3
"""俄语数据路径 —— **本语种数据位置的唯一真相源**。2026-10-07。

照 `es/paths.py` / `vi/paths.py` 抄（`PLAYBOOK` 1.1）：数据全在仓库根 `data/`，
代码目录下不存放任何数据字节；路径只在本文件声明一次，其余脚本 `import paths` 取用。
清单见 `data/MANIFEST.md`。

═══ 🔴🔴🔴 ru 的头号陷阱：**归一不许用 NFD**（与 vi 方向相反）═══
`й`(U+0439) 和 `ё`(U+0451) 都是 **NFC 单码位**，NFD 会把它们各拆成两个：

    vi:  `norm_vi` 用「NFD 之后去掉所有组合符」**是对的** —— 越南语带调元音要拆开
    ru:  同一行代码会把 **й → и、ё → е**

`й` 是俄语字母表里独立的第 11 个字母（不是 и 的变体）；`ё` **辨义**
（`всё` 一切 ／ `все` 所有人；`совершённый` ／ `совершенный`）。
⇒ 归一只许去 **U+0301 重音符**，白名单逐个列。实现与 **import 时的自检**都在
  `ru/dbtool.py`（`norm_ru` / `_norm_selfcheck`）—— 谁把它改回 NFD 版，import 当场炸。
⚠️ 代价是现成的：vi 那门 `word_norm` 冲突 1,263 组 ⇒
   **1,291 个页面打不开、而且显示的是别的词的内容**。俄语词形更多，同类事故更大。

═══ ✅ 阶段 -1 实测①：**俄语的存量是十门里最大的，而且主源不在英文版** ═══
`scripts/probe_editions.py --lang ru`（2026-10-07，索引页直报义项数，不下载）：

    版本  本地语种名         义项数     切片(gz)
    ru    Русский          586,623   192.9 MB   ← **本语言版最大**
    en    Russian          492,474    86.1 MB
    fr    Russe            363,315    15.8 MB   ← 跨版收割，比 en 的 74% 还多
    zh    俄语(简)          98,188     5.3 MB
    zh    俄語(繁)          94,403     8.3 MB
    vi    Tiếng Nga         48,917     3.4 MB   ← 见下面的陷阱③
    pl    język rosyjski    32,470     2.7 MB
    tr/ko/ja/cs/nl/de/pt/it/el 各 0.1–2.1 万，合计约 8 万

🔴 **源分工必须重量，不许照搬任何一门**（`RU_PLAN` §0.5 最后一行）——
   前七门是「英文版主源」，ko 整个反过来，vi 是第三种。
   ru 版比 en 版多 19%，**但「义项多」不等于「主源」**（ko 那次就是这么判反的：
   源分工要按**每一层**分别量，不按总量）。待量，阶段 -1 §2。

═══ 🔴🔴 阶段 -1 实测②：`probe_editions.py` 的 `NAMES` 补 ru 时栽了两次 ═══
同一张表里 it／pt+tr+cs／ko 两次／vi 已经栽过**五次**，这次是第六、七次，
而**两次的方向相反**：

 ① **宽了会多下**（前五次都是窄了会漏）：`russ`/`ruso`/`ruštin` 这些词干
    **全部是白俄罗斯语名字的后半截** —— de `Weißrussisch`／fr `biélorusse`／
    it `bielorusso`／es `bielorruso`／cs `běloruština`／ru `белорусский`。
    加了词首边界之后仍然多报一条：土耳其语的白俄罗斯语是 **`Beyaz Rusça`**
    （两个词、「白·俄语」），`Rusça` 前面正好是空白 ⇒ 边界判据也挡不住，
    要一条 `(?<!beyaz)`。**是实跑一次、逐行读输出才逮到的，不是想出来的。**
 ② **vi 版把俄语叫 `Tiếng Nga`**（Nga＝俄罗斯），与 ru-/ros-/русск 三个词干
    一个字都不沾 ⇒ 第一版整版漏掉，而它 48,917 条**排第五**，比 pl/tr/ko/ja 都大。
    同一张表里 vi 那行的教训（`Tiếng Việt` 不含 vietnam）换个方向又来一次。

⚠️ ru 版索引里还有一条 **`Русский (дореформенная орфография)` 3,931 条** ——
   **改革前正字法**（1918 年前，带 ѣ/і/ѳ/ъ）。它是另一种正字法、另一个语种条目，
   **本门不收**。🔴 什么会推翻它：如果词源层/历史拼写需要给现代词形挂旧拼写，
   那时再回来取（它的切片 URL 因目录名带括号而 HEAD 取不到大小，取之前先核）。

═══ ⚠️ 阶段 -1 的四件事：**三件只在「ru 版的法语条目」上量过，必须回俄语切片复量** ═══
`RU_PLAN` §0.2 的四条实测，源是本机早就有的 `kaikki.org-ruwiktionary-French.jsonl.gz`
（ru 版里的**法语**条目，32,903 条）。它们是**ru 版抽取器的性质**，大概率对俄语条目也成立，
但「大概率」不是已量 —— `RU_PLAN` §0.1 那张表的规矩是「**右栏不许当成已知**」：

    ① `etymology_texts`（复数），单数出现率 0.0%   ← ko 的 **K36** 原形
    ② `etymology_templates` 出现率 0.0%            ← vi 靠它推 `etym_type` 的路不存在
    ④ IPA 用**方括号** `[apliˈkabl]` 不是斜杠      ← 裸存前剥 `[]`，别门剥的是 `/`
      另有别门都没有的 `hyphenations`（80% 条目有）

⇒ 这三条在 `ru/probes/probe_sources.py` 里**对俄语切片重跑一遍**，结论写回这里。
  （③ ё 的 4.66% 是在释义文本上量的，与目标语言无关，照旧有效。）

═══ 🔴 没有整包，这是**有意的** ═══
`PLAYBOOK` 1.2「下切片别下整包」。ru 版整包未下 —— 俄语切片 192.9 MB 就够，
而 ru 版整包里俄语只占一部分（索引页：ru 版覆盖多种语言）。
盘上原有的 `kaikki.org-ruwiktionary-French.jsonl.gz` / `-Portuguese` / `-Vietnamese`
是**别门**下的 ru 版切片，不是本门的源 —— 但 §0.2 那四条实测就是在第一份上量的。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # 仓库根
DATA = ROOT / "data"

DB = DATA / "db" / "synapse-dict-ru.sqlite"        # 成品库（尚未建）

# ── 主源（2026-10-07 下齐；义项数来自 kaikki 索引页，字节数当天实测）────────────
# 🔴 **谁是主源尚未定**，见文件头。这里只按体量排列，不含分工结论。
KK      = DATA / "dumps" / "kaikki.org-dictionary-Russian.jsonl.gz"        # 英文版  86.1 MB / 492,474 义项
EDITION = DATA / "dumps" / "kaikki.org-ruwiktionary-Russian.jsonl.gz"      # 俄文版 192.9 MB / 586,623 义项
ZH_SIMP = DATA / "dumps" / "kaikki.org-zhwiktionary-Russian-simp.jsonl.gz" # 中文简   5.3 MB /  98,188 义项
ZH_TRAD = DATA / "dumps" / "kaikki.org-zhwiktionary-Russian-trad.jsonl.gz" # 中文繁   8.3 MB /  94,403 义项

# 🔴 中文版简繁的分工**又是一种新形状**：
#    ko 简体片大（195,332 词头）、繁体片才带结构；vi **繁体片大**（trad 40,387 / simp 5,129）；
#    ru 两片**几乎一样大**（98,188 / 94,403，相差 4%）—— 大概率是同一批内容的两种字形。
#    ⇒ 两片都收，但**必须先量重叠**：如果是同一批内容，收两遍就是重复行
#      （vi 的 B12 形状：`UNIQUE(word_id,url)` 挡不住 1,450 行 31.8% 的重复）。

# ── 跨版收割（`[[cross-edition-harvest]]`：语言版 dump 里有大量其他语言的词条且带音标）──
FR_EDITION = DATA / "dumps" / "kaikki.org-frwiktionary-Russian.jsonl.gz"   # 15.8 MB / 363,315 义项
# 🔴 法语版给的俄语义项是 en 版的 **73.8%** —— 这不是长尾，是第三大的一份。
#    （it 那门的教训：法语版里的意语音标是意语版的 17 倍。**别凭"它是法语版"判断价值**。）
VI_EDITION = DATA / "dumps" / "kaikki.org-viwiktionary-Russian.jsonl.gz"   #  3.4 MB /  48,917 义项
PL_EDITION = DATA / "dumps" / "kaikki.org-plwiktionary-Russian.jsonl.gz"   #  2.7 MB /  32,470 义项
# 长尾九份（tr 21,152 ／ ko 18,393 ／ ja 18,129 ／ cs 5,521 ／ nl 4,988 ／ de 4,985 ／
# pt 3,966 ／ it 2,879 ／ el 2,414 ／ es 1,515，合计约 8.4 万义项、< 6 MB）**暂未下**。
# 🔴 什么会推翻「不下」：音标或录音的覆盖缺口要靠并集填的时候（录音可以跨版取并集，
#    音标和释义**不能**取并集、要裁决 —— `PLAYBOOK` 六）。阶段 3/6 再定。

WORK    = DATA / "work" / "ru"                     # 过程产物：probe / runs / 冲突表 / 模型输出
PROBE   = WORK / "probe"                           # 阶段 -1 的探测存档
BACKUPS = DATA / "backups"                         # 写库前的自动备份
DUMPS   = DATA / "dumps"
ENV     = ROOT / ".env"
