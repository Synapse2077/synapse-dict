#!/usr/bin/env python3
"""kaikki 意语 dump 的正确读法 —— it 的唯一入口。2026-08-01。

it 独立文件，不 import 其他语种（见 multilang-decoupling-essence 铁律）。

🔴 **踩过的坑（es 上两个脚本都中招，这里预先避开）**：用
      re.search(r'"word":\\s*"([^"]*)"', line)
   抓词头是**错的**。wiktextract 的顶层 key 顺序不固定，`word` 常排在
   `forms` / `descendants` / `related` 这些**内含 "word" 键的嵌套数组之后**，
   正则会抓到嵌套里的别的词 → 大量条目漏掉，偶发张冠李戴（把 A 的音标记到 B 头上）。
   → **必须 json.loads 整行再取 d["word"]**。慢一点但正确。

意语 sounds 格式（实测）：干净的音位式 `/ˈɡat.to/`，无 es 那种「音位式+严式拼一起」的情况；
括号可选音 `/bri.koˈla(d)ʒ/` 是 kaikki 原文，不是缺陷。
"""
import gzip
import json
import re
import unicodedata
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
KK = paths.KK


def iter_entries(words=None):
    """逐条产出 (word, entry)。words 给定时只产出这些词（仍然先解析再判定）。"""
    with open(KK, encoding="utf-8") as f:
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


def phonemic_ipa(words):
    """word → 音位式 /.../ 内的内容（裸串）。同词多条时取第一条有音位式的。"""
    out = {}
    for w, d in iter_entries(words):
        if w in out:
            continue
        for s in (d.get("sounds") or []):
            m = re.match(r"\s*/([^/]+)/", s.get("ipa", "") or "")
            if m:
                out[w] = m.group(1)
                break
    return out


ACC = set("àèéìíòóù")


def unaccent(s):
    nfd = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def sounds_and_accent_map(words=None):
    """一趟扫完，同时返回 (音位式 dict, 重音形映射 dict)。

    🔴 **重音形映射是判定「规则生成」的必需品，不是可选项**（2026-08-01 踩到）：
       `b_ipa_fill.py` 喂给 G2P 的是从 kaikki `forms` 取来的**带重音形**（`dìgito`），
       靠它一次性定死重音位置与 e/o 开闭；拿**光杆词形**去调 `word_to_ipa` 会走
       「倒二音节 + 闭元音」默认，结果自然对不上。
       第一版普查就是这么写的 → 把 112,209 行（19.2%）误判成「规则算得出但不同」，
       而它们绝大多数其实是**规则按正确路径生成的、完全正常的行**。
       → **判定某行是不是规则产物，必须复现它当初的生成路径。**
    """
    ipa, amap = {}, {}
    for w, d in iter_entries(words):
        if w not in ipa:
            for s in (d.get("sounds") or []):
                m = re.match(r"\s*/([^/]+)/", s.get("ipa", "") or "")
                if m:
                    ipa[w] = m.group(1)
                    break
        for fm in (d.get("forms") or []):          # 与 b_ipa_fill.build_accent_map 同口径
            form = (fm.get("form") or "").strip()
            if form and any(c in ACC for c in form):
                amap.setdefault(unaccent(form), form)   # first-seen 胜
    return ipa, amap


# ═══════════════════════════════════════════════════════════════════════
# 以下为 2026-08-01 新增：**各版 dump 的解析约定**。
# 立此一节的原因：当天八次翻车里有三次出在解析层，每一次都差点让我们
# 放弃一个真实存在的数据源（西语版、pt 巴葡、fr 版整体）。
# 解析知识必须只有一处实现、且被 test_tools.py 覆盖。
#
# · 意语版格式干净：`/ˈɡat.to/`，无 es 那种「音位式+严式」拼串。
#   括号可选音 `/bri.koˈla(d)ʒ/` 是 kaikki 原文，不是缺陷。
# · **fr 版的意语有 684,212 词带音标，是 it 最大的外部人工音标源**（意语版自己只有 40,090）。
#   2026-08-01 用它复核：有 kaikki 背书的两层与它一致 87%，规则裸路径层仅 57.2% —— 差 30pp。
# · fr 版意语只有 0.1% 多读音，且**有噪声**（`computer` 第二读音是整个短语 `uŋ kɔm.pju.ˈtɛr`）。
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
