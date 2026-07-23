"""只读枚举：es 跨 etym 双性名词有没有被 enrich.py:197 的 first-wins 锁成单性（同 it/de 的折叠 bug）。
不改库。单进程一遍扫 kaikki + 一次读全库进内存（遵循性能纪律）。
用法：python3 enum_dualgender.py
"""
import json
import sqlite3
import sys
from pathlib import Path

import enrich  # 复用 extract_noun / JSONL_PATH

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-es.sqlite"

# pass: 累积每词性别（原子 m/f）
genders = {}
for line in open(enrich.JSONL_PATH, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    try:
        e = json.loads(line)
    except Exception:
        continue
    if e.get("lang_code") != "es" or e.get("pos") not in ("noun", "name"):
        continue
    word = (e.get("word") or "").strip()
    if not word:
        continue
    g, _pl, _fem = enrich.extract_noun(e, word)
    if not g:
        continue
    s = genders.setdefault(word.lower(), set())
    for x in ("m", "f"):
        if x in g:
            s.add(x)

dual = {k for k, gg in genders.items() if "m" in gg and "f" in gg}
print(f"kaikki 跨词条双性名词（m+f）：{len(dual)} 词", flush=True)

# 读全库 lemma gender 进内存
conn = sqlite3.connect(str(DB))
dbg = {}
for w, g in conn.execute("SELECT word, gender FROM dict WHERE is_lemma=1"):
    dbg.setdefault(w.lower(), g)

locked = []   # kaikki 双性但库里锁成单性 = 折叠 bug 受害者
ok_mf = 0
nolemma = 0
for k in dual:
    cur = dbg.get(k, "__MISSING__")
    if cur == "__MISSING__":
        nolemma += 1
    elif cur == "mf":
        ok_mf += 1
    else:
        locked.append((k, cur))

print(f"  库里已 mf（正确）：{ok_mf}", flush=True)
print(f"  库里锁成单性（折叠 bug 受害者）：{len(locked)}", flush=True)
print(f"  无 lemma 行：{nolemma}", flush=True)
print("  锁死样本（词→当前库性别）：", flush=True)
for k, cur in sorted(locked)[:30]:
    print(f"    {k} → {cur}", flush=True)
conn.close()
