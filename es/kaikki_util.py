#!/usr/bin/env python3
"""kaikki dump 的正确读法 —— 唯一入口,别再自己写正则抓 word。见对话 2026-07-31。

🔴 **踩过的坑(2026-07-31,两个脚本都中招)**:用
      re.search(r'"word":\\s*"([^"]*)"', line)
   抓词头是**错的**。wiktextract 的顶层 key 顺序不固定,`word` 常常排在
   `forms` / `descendants` / `related` 这些**内含 "word" 键的嵌套数组之后**。
   实例:`estar` 那一行顶层 key 顺序是
      ['pos','head_templates','forms','inflection_templates','descendants',
       'etymology_text','etymology_templates','sounds', ... 'word' 在更后面]
   正则抓到的第一个 "word" 是 descendants 里的 `istar` —— 于是 `estar` 整条被漏掉/张冠李戴。
   后果有两种:① 大量条目查不到(低估 kaikki 覆盖);② 偶发**错误归属**(把 A 的音标记到 B 头上)。

   → **必须 json.loads 整行再取 d["word"]**。慢一点(全量约 60-90s)但正确。
     想省时间就先用 `if needle not in line` 这种**宽松**预筛(只能用来跳过,不能用来判定)。
"""
import gzip
import json
import re
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
KK = paths.KK


def iter_entries(words=None):
    """逐条产出 (word, entry)。words 给定时只产出这些词(仍然是先解析再判定)。"""
    with open(KK, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            # 宽松预筛:整行连这个词的字面量都没有,才敢跳过(不能拿它当判定)
            if words is not None and '"word"' not in ln:
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            w = d.get("word")
            if not w or (words is not None and w not in words):
                continue
            yield w, d


def phonemic_ipa(words):
    """word → 音位式 /.../ 内容。同词多条时取第一条有音位式的。

    🔴 坑:少数条目的 sounds.ipa 是**音位式与严式拼在一起**的整串,如
       `gracias` → `/ˈɡɾaθjas/ [ˈɡɾa.θjas]`。`strip("/")` 只去首尾斜杠,
       严式段会漏进返回值 → 拿它当真值比对时,那些词永远"不一致"。
       必须**正则取第一对斜杠之间的内容**。
    """
    out = {}
    for w, d in iter_entries(words):
        if w in out:
            continue
        for s in (d.get("sounds") or []):
            m = re.match(r"\s*/([^/]+)/", s.get("ipa", ""))
            if m:
                out[w] = m.group(1)
                break
    return out


def form_of_pointers(words):
    """word → {原形}。顶层 form_of 与各 sense 的 form_of 都收。"""
    out = {}
    for w, d in iter_entries(words):
        acc = out.setdefault(w, set())
        for fo in (d.get("form_of") or []):
            if fo.get("word"):
                acc.add(fo["word"])
        for s in (d.get("senses") or []):
            for fo in (s.get("form_of") or []):
                if fo.get("word"):
                    acc.add(fo["word"])
    return {k: v for k, v in out.items() if v}


# ═══════════════════════════════════════════════════════════════════════
# 以下为 2026-08-01 新增：**各版 dump 的解析约定**。
# 立此一节的原因：当天八次翻车里有三次出在解析层，每一次都差点让我们
# 放弃一个真实存在的数据源（西语版、pt 巴葡、fr 版整体）。
# 解析知识必须只有一处实现、且被 test_tools.py 覆盖。
#
# · **英文版**少数条目的 `sounds.ipa` 是「音位式+严式拼一起」的整串：
#   `gracias` → `/ˈɡɾaθjas/ [ˈɡɾa.θjas]`。必须**只取第一对定界符之间**，`strip("/")` 会漏严式段。
# · **西语版**用 `[…]`，且同一词常同时给 `seseante` / `no seseante` 两种变体 ——
#   2026-08-01 曾**只取第一个拿到 seseante**，据此断言"西语版没用"，是错的。本项目取 `no seseante`（区分 θ/s）。
# · **fr 版的西语 82.4% 是多读音，且是方言变体**（`des`→`ˈdes`/`ˈdeh` s 弱化）——
#   取第一个＝随机选方言。要用必须先定跟哪个方言。
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
