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
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
KK = HERE / "kaikki.org-dictionary-Spanish.jsonl"


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
