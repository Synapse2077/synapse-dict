#!/usr/bin/env python3
"""阶段 -1 补测：法文版收完之后，其余各版**还剩多少词形**（与顺序无关）。

上一版的「边际新增」是**按一个特定顺序**依次求差算的 —— 那个数依赖顺序，
换个顺序 tr 和 el 的数字会互换。这里改问一个**顺序无关**的问题：
    base = 现有库 ∪ 法文版
    对每个 x：residual_x = V_x \ base      （法文版收完之后 x 还能独家给多少）
并额外量三种「假新词」：只差大小写 / 只差重音符 / 只差撇号 —— 这三类在落库归一后会塌掉，
raw 差集会把它们当新词（`[[measure-landing-not-source]]`：量源头不量落点）。
"""
import gzip, json, sqlite3, sys, unicodedata, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import paths

D = paths.DUMPS
DB = str(paths.DB)

SOURCES = [
    ("tr", D / "kaikki.org-trwiktionary-French.jsonl.gz", False),
    ("el", D / "kaikki.org-elwiktionary-French.jsonl.gz", False),
    ("nl", D / "kaikki.org-nlwiktionary-French.jsonl.gz", False),
    ("ru", D / "kaikki.org-ruwiktionary-French.jsonl.gz", False),
    ("ja", D / "kaikki.org-jawiktionary-French.jsonl.gz", False),
    ("zh", D / "zhwiktionary.jsonl.gz", True),
    ("it", D / "itwiktionary.jsonl.gz", True),
    ("de", D / "dewiktionary.jsonl.gz", True),
    ("es", D / "eswiktionary.jsonl.gz", True),
    ("pt", D / "ptwiktionary.jsonl.gz", True),
]


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def words(p, need_filter):
    s = set()
    with opener(p) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if need_filter and e.get("lang_code") != "fr":
                continue
            w = e.get("word")
            if w:
                s.add(w)
    return s


def strip_acc(w):
    return "".join(c for c in unicodedata.normalize("NFD", w) if not unicodedata.combining(c))


def apos(w):
    return w.replace("’", "'").replace("ʼ", "'")


con = sqlite3.connect(DB)
db_words = {r[0] for r in con.execute("SELECT DISTINCT word FROM dict")}
con.close()
print("现有库词形 %s" % f"{len(db_words):,}", flush=True)

fr_words = words(D / "frwiktionary.jsonl.gz", True)
print("法文版词形 %s" % f"{len(fr_words):,}", flush=True)

base = db_words | fr_words
print("base = 库 ∪ 法文版 = %s" % f"{len(base):,}", flush=True)
print()

# 归一化索引：用于判「假新词」
base_fold = {w.casefold() for w in base}
base_acc = {strip_acc(w.casefold()) for w in base}
base_apos = {apos(w).casefold() for w in base}

print("%-4s %11s %11s %10s %10s %10s %11s" %
      ("版本", "该版词形", "residual", "只差大小写", "只差重音符", "只差撇号", "净新词"))
print("-" * 74)

residuals = {}
for key, p, filt in SOURCES:
    if not p.exists():
        print("%-4s 🔴 缺文件 %s" % (key, p.name), flush=True)
        continue
    v = words(p, filt)
    r = v - base
    residuals[key] = r
    n_fold = sum(1 for w in r if w.casefold() in base_fold)
    n_acc = sum(1 for w in r if w.casefold() not in base_fold and strip_acc(w.casefold()) in base_acc)
    n_apos = sum(1 for w in r if w.casefold() not in base_fold and apos(w).casefold() in base_apos)
    net = len(r) - n_fold - n_acc - n_apos
    print("%-4s %11s %11s %10s %10s %10s %11s" % (
        key, f"{len(v):,}", f"{len(r):,}", f"{n_fold:,}", f"{n_acc:,}", f"{n_apos:,}", f"{net:,}"),
        flush=True)

print()
allr = set()
for r in residuals.values():
    allr |= r
print("residual 之和（相加）        %s" % f"{sum(len(r) for r in residuals.values()):,}")
print("residual 并集（去重后真值）  %s" % f"{len(allr):,}")
print("⇒ 十版之间自身重叠           %s" % f"{sum(len(r) for r in residuals.values()) - len(allr):,}")
print("全收总词形 = base + 并集 =   %s" % f"{len(base) + len(allr):,}")
print()
# 十版残差里各版独占（只有这一版有）的量
from collections import Counter
cnt = Counter()
for k, r in residuals.items():
    for w in r:
        cnt[w] += 1
print("十版残差里「只有一版给」的词形 %s（占并集 %.1f%%）"
      % (f"{sum(1 for w in allr if cnt[w] == 1):,}", 100.0 * sum(1 for w in allr if cnt[w] == 1) / max(len(allr), 1)))
for k, r in sorted(residuals.items(), key=lambda kv: -len(kv[1])):
    solo = sum(1 for w in r if cnt[w] == 1)
    print("   %-4s residual %8s  其中独占 %8s" % (k, f"{len(r):,}", f"{solo:,}"))
