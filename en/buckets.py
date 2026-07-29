#!/usr/bin/env python3
"""尾巴 387 万的九桶互斥分区(唯一定义处,供采样/验收/修复脚本共用)。见对话 2026-07-27。

全库 3,929,564 = 常用核心 59,137 + 尾巴 3,870,427。
⚠️ CORE 必须用 COALESCE:有 527,000 行(Wiktionary 新词层)五个信号列全 NULL,
   写成 `collins>0 OR …` 时整体求值为 NULL、`NOT NULL` 仍是 NULL,
   → 这批**既不进 CORE 也不进 NOT CORE,从两边静默漏掉**(尾巴会少报 52.7 万)。
   自检铁律:核心 + 尾巴 必须 == 3,929,564。

按优先级归属,每条只落一桶:
  A1 纯元描述空壳 | B1 [网络]纯音译 | B2 [网络]其余 | C1 生物学名 | C2 地名/人名
  C3 缩写 | C4 带领域标记术语 | C5 无标记单词 | C6 无标记多词短语
"""
import re

CORE = ("(COALESCE(collins,0)>0 OR COALESCE(oxford,0)>0 OR COALESCE(frq,0)>0 "
        "OR COALESCE(bnc,0)>0 OR COALESCE(TRIM(tag),'')<>'')")
TOTAL = 3929564

MW = (r"(复数形式|复数|现在分词和动名词形式|现在分词|过去式和过去分词|过去式与过去分词形式|"
      r"过去式|过去分词|第三人称单数|第三人称 ?-s ?形式|最高级|比较级)")
META = re.compile(r"的" + MW)
# ⚠️ 尾部不可贪婪:`…的复数[^\n;；]*` 会把后面的真实义一起吃掉,误判有义条目为空壳(多吞 17%)
CLAUSE = re.compile(r"[（(]?\s*[A-Za-z][\w '\-]*\s*的" + MW + r"\s*[)）]?")
HAN = re.compile(r"[一-鿿·]{1,8}")
# ⚠️ 词性前缀必须先剥:剥掉元描述后残留一个 `n.`,strip 字符集不含字母 → 残留非空 → 误判"有实义"。
#    该 bug 曾让 A1 漏判 137,498 条(散在 C5 96,077 / C6 38,589 / C1 2,808 / C3 24),
#    并在每个桶里制造假 bad(C1 的 78 条 bad 里 45 条、C6 的 103 条里 16 条其实是空壳)。
POSPFX = re.compile(r"^\s*(?:[a-z]{1,5}\.(?:form)?\s*)+", re.M)


def is_shell(body):
    if not META.search(body):
        return False
    return not POSPFX.sub("", CLAUSE.sub("", body)).strip(" \n;；,，/()（）.·-")


def classify(word, translation):
    """返回桶名。word/translation 为库中原值。"""
    ws = (word or "").strip()
    body = (translation or "").strip()
    toks = ws.split()
    is_single = len(toks) == 1 and "-" not in ws
    marks = set(re.findall(r"\[([^\]]{1,8})\]", body))

    if is_shell(body):
        return "A1"
    if "网络" in marks:
        bd = body.split("]", 1)[-1].strip() if "]" in body else body
        return "B1" if "\n" not in body and re.fullmatch(HAN, bd) else "B2"
    if (len(toks) == 2 and toks[0][:1].isupper() and toks[1][:1].islower()
            and all(x.isalpha() for x in toks)):
        return "C1"
    if marks & {"地名", "人名"} or any("姓氏" in m or "名字" in m for m in marks):
        return "C2"
    if (ws.isupper() and ws.isalpha() and len(ws) > 1) or body.startswith("abbr."):
        return "C3"
    if marks:
        return "C4"
    return "C5" if is_single else "C6"


LABELS = {
    "A1": "纯元描述空壳", "B1": "[网络]·纯音译", "B2": "[网络]·其余",
    "C1": "生物学名(属 种)", "C2": "地名/人名(有标记)", "C3": "缩写/首字母词",
    "C4": "带领域标记术语", "C5": "无标记·单词", "C6": "无标记·多词短语",
}


def load_tail(conn):
    """产出 (id, word, translation, bucket)。"""
    for i, w, t in conn.execute(
            f"SELECT id, word, translation FROM stardict WHERE NOT {CORE}"):
        yield i, w, t, classify(w, t)
