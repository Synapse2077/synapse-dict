#!/usr/bin/env python3
"""kaikki 德语 dump 的正确读法 —— de 的唯一入口。2026-08-01。

de 独立文件，不 import 其他语种（见 multilang-decoupling-essence 铁律）。

🔴 **踩过的坑**：用 `re.search(r'"word":\s*"([^"]*)"', line)` 抓词头是**错的**。
   wiktextract 的顶层 key 顺序不固定，`word` 常排在 `forms` / `descendants` / `related`
   这些**内含 "word" 键的嵌套数组之后**，正则会抓到嵌套里的别的词 →
   大量条目漏掉，偶发张冠李戴（把 A 的音标记到 B 头上）。
   → **必须 json.loads 整行再取 d["word"]**。慢一点但正确。
"""
import gzip
import json
import re
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
KK = paths.KK


def iter_entries(words=None):
    """逐条产出英文版 dump 的 (word, entry)。words 给定时只产出这些词（仍先解析再判定）。"""
    with open(KK, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if not ln.strip():
                continue
            if words is not None and '"word"' not in ln:   # 宽松预筛：只敢用来跳过
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            w = d.get("word")
            if not w or (words is not None and w not in words):
                continue
            yield w, d


# ═══════════════════════════════════════════════════════════════════════
# 以下为 2026-08-01 新增：**各版 dump 的解析约定**。
# 立此一节的原因：当天八次翻车里有三次出在解析层，每一次都差点让我们
# 放弃一个真实存在的数据源（西语版、pt 巴葡、fr 版整体）。
# 解析知识必须只有一处实现、且被 test_tools.py 覆盖。
#
# · **德语版用 `[…]`**。
# · **fr 版德语 496,439 词带音标**，能补我们 196,368 行空缺（覆盖 31.4%→87.6%）。
# · fr 版德语 12.3% 多读音，但**是记法差异不是方言**：`ˈfraɪ̯taːk` / `ˈfʁaɪ̯ˌtaːk`（r vs ʁ、次重音）。
#   **取值时要选与本库约定一致的那个（ʁ），别取第一个。**
# · 英文版德语的 `forms` 带 ipa = 0，变形层音标只能从外部源来。
# ═══════════════════════════════════════════════════════════════════════

EDITION = paths.EDITION
# ⚠️ 这个包是**该社区用该语言写的多语种词典整包**，不是「该语言的词典」。
#    es 版 100 万条覆盖 853 种语言、本语言只占 84.5%；fr 版 743 万条里法语只占 28.4%。
#    所以它放在 dumps/ 而不是某个语种目录下 —— 目录结构必须说实话；
#    2026-08-01 之前它叫 `<lang>/<lang>-edition-extract.jsonl.gz`，那个位置本身就在误导。
#    用 iter_edition() 读，务必按 entry["lang_code"] 过滤。

# 三种定界符都要认：it/pt `/…/`、es/de `[…]`、fr `\…\`
_IPA_DELIM = re.compile(r"^\s*[\\/\[]([^\\/\]]+)[\\/\]]")

# 这些 tag 标记的不是本语言的音位式读音，一律排除。
# 🔴 X-SAMPA 是**标签**不是格式 —— 见本节开头。
DROP_TAGS = frozenset({"X-SAMPA", "romanization", "rhymes", "Hyphenation", "hyphenation"})


def parse_ipa(raw):
    """从 `sounds.ipa` 原文取出裸音标串；取不到返回 None。

    只取**第一对定界符之间**的内容 —— 有的条目把音位式与严式拼在一串
    （`/ˈɡɾaθjas/ [ˈɡɾa.θjas]`），`strip("/")` 会把严式段一起带出来。
    """
    if not raw:
        return None
    m = _IPA_DELIM.match(raw.strip())
    return m.group(1) if m else None


def sounds_variants(entry, drop_tags=DROP_TAGS, dedupe=True):
    """返回该条目的**全部**读音变体：[(裸音标, tags元组), ...]。

    🔴 **这是本模块最重要的一个函数，因为 `sounds` 是列表、第一个不代表全部。**
    2026-08-01 两次栽在"只取第一个"上：
      ① 西语版取到 `seseante` → 断言"西语版没用"（实际它两种变体都给）；
      ② fr 版葡语取到欧葡 → 断言"巴葡补不上"（实际 ①欧葡 ②巴葡，双列各能补 17.9 万行）。
    → **任何取值之前，先看这个列表有多长、每个变体的 tags 是什么。**
    """
    out = []
    seen = set()
    for s in (entry.get("sounds") or []):
        tags = tuple(s.get("tags") or [])
        if drop_tags and set(tags) & set(drop_tags):
            continue
        ip = parse_ipa(s.get("ipa"))
        if not ip:
            continue
        if dedupe and ip in seen:
            continue
        seen.add(ip)
        out.append((ip, tags))
    return out


def first_phonemic(entry):
    """便捷取第一个变体。

    ⚠️ **只在已经确认该语种/该版本不存在有意义的多变体时才用。**
    否则用 `sounds_variants` 看全貌 —— 见上面那个函数的注释。
    """
    v = sounds_variants(entry)
    return v[0][0] if v else None


def audio_urls(entry):
    """返回该条目的真人录音直链：[(url, 文件名, tags元组), ...]。

    来源是 Wikimedia Commons（大量出自 Lingua Libre 母语者众包），CC 授权。
    **必须用语言版 dump** —— 英文版几乎没有（西语英文版 36 词 vs 西语版 15,697 词，436 倍）。
    """
    out = []
    for s in (entry.get("sounds") or []):
        u = s.get("mp3_url") or s.get("ogg_url") or s.get("wav_url")
        if u:
            out.append((u, s.get("audio") or "", tuple(s.get("tags") or [])))
    return out


def iter_edition(path=None):
    """逐条产出语言版 dump 的 (word, entry)。

    ⚠️ 语言版 dump 是**该语言社区编写的多语种词典**，里面大量条目不是本语言的
    （法语版 742 万条里法语只占 210 万）。要按 `entry["lang_code"]` 过滤。
    """
    p = Path(path) if path else EDITION
    with gzip.open(p, "rt", encoding="utf-8", errors="replace") as f:
        for ln in f:
            if not ln.strip():
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            w = d.get("word")
            if w:
                yield w, d
