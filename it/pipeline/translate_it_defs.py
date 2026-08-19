#!/usr/bin/env python3
"""阶段 3b 收尾：给新收的意语词条配中文。2026-08-13。

═══ 为什么这一步才花钱 ═══
阶段 1.5 的中文缺口是 **0**（库里 198,047/198,049 条义项早有中文）。
但阶段 3b 收进来的 11,921 个词形是**全新的**，它们只有意语原文释义，一条中文都没有。
⇒ 全项目第一次、也是目前唯一一次真正需要调模型的地方：**13,089 条**。

═══ 判据（全部来自 es 的学费）═══
· 用 flash 关思考（`large-fill-use-turbo-batch` / `prompt-beats-model-choice`）——
  这是常规翻译不是规则判断，开思考纯烧钱
· **块大小按模型给**：flash 输出上限小，一次 25 条；解析失败就把块对半拆重试
· **本地键**：每条带 `id`，不靠模型保持顺序（es 上顺序错位吃过亏）
· **容错 JSON**：模型可能包 ```json 围栏、可能吐 `result` 而不是约定的键名
  （`prompt-beats-model-choice`：解析器只认一个键名，害我误判成"完成率 60%"）
· **四个 payload 坑**（`flash-translation-validated`）：
  ① 交叉引用要喂被引词的中文  ② meta 标签要说明，否则会被写进释义
  ③ 句末不要标点             ④ wiktextract 残渣要提前说明
· **负控**：混入 30 条**已有中文**的义项（不告诉模型），跑完与库里现成的中文比对 ——
  负控不合格就说明这批不能用，不是"再调调 prompt"

用法（在 it/ 目录下）：
    python3 pipeline/translate_it_defs.py --plan      # 只报量和成本估算
    python3 pipeline/translate_it_defs.py --run       # 跑批（断点续传）
    python3 pipeline/translate_it_defs.py --control   # 只跑负控 30 条
    python3 pipeline/translate_it_defs.py --merge     # 结果写回库
    python3 pipeline/translate_it_defs.py --verify
"""
import argparse
import asyncio
import json
import os
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

MODEL = "deepseek-v4-flash"
CHUNK = 25
OUT = paths.WORK / "it_defs_zh.jsonl"
CTRL = paths.WORK / "it_defs_control.jsonl"

SYS = """你是意大利语—中文词典编纂助手。把意语单语释义转成**词典对应词式的中文释义**。

规则：
1. 输出**对应词**，不是把意语句子翻成中文长句。
   例：`erba seccata destinata al nutrimento del bestiame` → `干草`
       `antico gioco da tavola strategico cinese` → `围棋`
2. 有多个对应词用中文逗号分隔，最多 3 个；实在只能解释时，写**尽量短**的解释。
3. **句末不加任何标点**。
4. 释义里**不要**出现"意为""指""表示""该词"这类元话语，也不要出现语法标签
   （如"名词""阳性""复数"），那些字段我们另有来源。
5. 如果原文是"参见 X""同 X"这类指针、或明显是抓取残渣（如以 `See also:` 开头），
   `zh` 输出空字符串 ""，不要编造。
6. 专名（人名/地名/机构名）给通用中译名，后面用中文括号标类别，如 `亚巴科（男名）`。

输入是 JSON 数组，每项有 `id`、`word`（词形）、`it`（意语释义）。
输出**只有** JSON 数组，每项 `{"id": 原样, "zh": "中文"}`，不要围栏、不要解释。"""


def load_env():
    e = dict(l.split("=", 1) for l in (paths.ROOT / ".env").read_text().splitlines()
             if "=" in l and not l.startswith("#"))
    return e


def pending(con):
    """要翻的：有意语定义、没有中文的义项。"""
    return [dict(id=r[0], word=r[1], it=r[2]) for r in con.execute(
        "SELECT s.id, d.word, g.text FROM sense s JOIN dict d ON d.id=s.word_id "
        "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='it' AND g.kind='definition' "
        "WHERE NOT EXISTS(SELECT 1 FROM sense_gloss z WHERE z.sense_id=s.id AND z.lang='zh') "
        "ORDER BY s.id")]


def control_set(con, n=30, seed=11):
    """负控：已有中文的义项，混进去跑，跑完与库里现成的中文比对。"""
    rows = [dict(id=r[0], word=r[1], it=r[2], truth=r[3]) for r in con.execute(
        "SELECT s.id, d.word, g.text, z.text FROM sense s JOIN dict d ON d.id=s.word_id "
        "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='it' AND g.kind='definition' "
        "JOIN sense_gloss z ON z.sense_id=s.id AND z.lang='zh' AND z.seq=0")]
    random.Random(seed).shuffle(rows)
    return rows[:n]


def parse(text):
    """容错解析：允许 ```json 围栏、允许对象包一层、允许键名写成 result/data。"""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t).strip()
    try:
        d = json.loads(t)
    except Exception:
        m = re.search(r"\[.*\]", t, re.S)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except Exception:
            return None
    if isinstance(d, dict):
        for k in ("result", "results", "data", "items", "output"):
            if isinstance(d.get(k), list):
                d = d[k]
                break
    return d if isinstance(d, list) else None


async def call(cl, e, items):
    body = {"model": MODEL, "temperature": 0, "stream": False,
            "thinking": {"type": "disabled"},
            "messages": [{"role": "system", "content": SYS},
                         # 只带**存在的**键：本文件的活儿要 (id, word, it)，
                         # 而 `fix_geo_parent_zh` 复用这个跑批器做纯音译时**故意不给 `it`**
                         # （法语原文正是母地名污染音译的来源）。硬取三个键会 KeyError。
                         {"role": "user", "content": json.dumps(
                             [{k: it[k] for k in ("id", "word", "it") if k in it}
                              for it in items], ensure_ascii=False)}]}
    r = await cl.post("https://api.deepseek.com/chat/completions",
                      headers={"Authorization": "Bearer " + e["DEEPSEEK_API_KEY"].strip()},
                      json=body, timeout=180)
    if r.status_code != 200:
        raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:200]))
    d = r.json()
    return parse(d["choices"][0]["message"]["content"]), d.get("usage") or {}


async def run_batches(items, out_path, conc=6):
    import httpx
    e = load_env()
    done = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
    todo = [x for x in items if x["id"] not in done]
    print("■ 待翻 %s 条（已完成 %s）" % (f"{len(todo):,}", f"{len(done):,}"))
    if not todo:
        return
    chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
    sem = asyncio.Semaphore(conc)
    usage = Counter()
    lock = asyncio.Lock()
    fh = out_path.open("a", encoding="utf-8")

    async def one(cl, ch, depth=0):
        async with sem:
            try:
                got, u = await call(cl, e, ch)
            except Exception as ex:
                if depth < 2:
                    return await one(cl, ch, depth + 1)
                print("   🔴 块失败：%s" % str(ex)[:90])
                return
            usage["in"] += u.get("prompt_tokens", 0)
            usage["out"] += u.get("completion_tokens", 0)
            # 🔴 只比条数不够：模型可能返回**重复 id**，条数对得上但有条目被静默丢掉
            #    （实测真发生了 2 条）。必须比 **id 集合**。
            ok_ids = got is not None and {r.get("id") for r in got} == {x["id"] for x in ch}
            if not ok_ids:
                # 🔴 解析失败或条数对不上：对半拆重试，不猜、不丢
                if len(ch) > 1 and depth < 4:
                    h = len(ch) // 2
                    await asyncio.gather(one(cl, ch[:h], depth + 1), one(cl, ch[h:], depth + 1))
                else:
                    print("   🔴 单条也解析不了 id=%s" % ch[0]["id"])
                return
            by = {x["id"]: x for x in ch}
            async with lock:
                for r in got:
                    if r.get("id") in by:
                        fh.write(json.dumps({"id": r["id"], "zh": (r.get("zh") or "").strip()},
                                            ensure_ascii=False) + "\n")
                fh.flush()

    async with httpx.AsyncClient(timeout=180) as cl:
        for i in range(0, len(chunks), 40):
            await asyncio.gather(*[one(cl, c) for c in chunks[i:i + 40]])
            print("   … %s/%s 块" % (min(i + 40, len(chunks)), len(chunks)))
    fh.close()
    print("■ tokens 入 %s / 出 %s" % (f"{usage['in']:,}", f"{usage['out']:,}"))


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        # ⚠️ 判据本意是"不许**添加**元话语"，不是"永远不能出现"：`Chanzir` 的意语原文
        #    就是 `il nome significa porco`，译成「意为猪」是忠实翻译。⇒ 排除源头自己
        #    就带 significa / vuol dire / indica 的那些。全库因此从 1 条误报降到 0。
        ("🔴 中文里不许**添加**元话语（意为 / 指的是）",
         q("SELECT count(*) FROM sense_gloss z JOIN sense_gloss i ON i.sense_id=z.sense_id "
           "AND i.lang='it' AND i.kind='definition' WHERE z.lang='zh' AND z.src=? AND "
           "(z.text LIKE '%意为%' OR z.text LIKE '%指的是%' OR z.text LIKE '%该词%') AND "
           "i.text NOT LIKE '%significa%' AND i.text NOT LIKE '%vuol dire%' "
           "AND i.text NOT LIKE '%indica%'", MODEL), 0),
        ("🔴 中文句末不许有标点",
         q("SELECT count(*) FROM sense_gloss WHERE lang='zh' AND src=? AND "
           "(text LIKE '%。' OR text LIKE '%.' OR text LIKE '%；')", MODEL), 0),
        ("中文不许是空串",
         q("SELECT count(*) FROM sense_gloss WHERE lang='zh' AND src=? AND trim(text)=''", MODEL), 0),
        ("中文不许含意语原文整句（长度失控）",
         q("SELECT count(*) FROM sense_gloss WHERE lang='zh' AND src=? AND length(text)>60", MODEL), 0),
        ("每条新译文都挂在有意语定义的义项上",
         q("SELECT count(*) FROM sense_gloss z WHERE z.lang='zh' AND z.src=? AND NOT EXISTS("
           "SELECT 1 FROM sense_gloss g WHERE g.sense_id=z.sense_id AND g.lang='it' "
           "AND g.kind='definition')", MODEL), 0),
        ("🔴 没有覆盖任何已有中文（只填空不覆盖）",
         q("SELECT count(*) FROM (SELECT sense_id FROM sense_gloss WHERE lang='zh' "
           "GROUP BY sense_id HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %s (期望 %s)" % ("✅" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("plan", "run", "control", "merge", "verify"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)

    if a.verify:
        return 0 if gate(con) else 1

    if a.control:
        ctrl = control_set(con)
        CTRL.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(run_batches([{k: c[k] for k in ("id", "word", "it")} for c in ctrl], CTRL))
        got = {json.loads(l)["id"]: json.loads(l)["zh"] for l in CTRL.open(encoding="utf-8")}
        print("\n■ 负控比对（模型没见过库里的中文）")
        same = 0
        for c in ctrl:
            g = got.get(c["id"], "")
            hit = bool(g) and (g in c["truth"] or c["truth"] in g
                               or bool(set(g) & set(c["truth"]) and len(set(g) & set(c["truth"])) >= 1))
            same += hit
            print("   %-14s 模型=%-22s 库=%-22s %s" % (c["word"], g[:22], c["truth"][:22],
                                                       "✓" if hit else "✗"))
        print("\n   有字面重叠 %d/%d —— ⚠️ 这只是**可用性下限**，不是准确率" % (same, len(ctrl)))
        return 0

    items = pending(con)
    if a.plan:
        n = len(items)
        avg = sum(len(x["it"]) for x in items) / max(n, 1)
        print("■ 待翻 %s 条，意语原文平均 %.0f 字符" % (f"{n:,}", avg))
        print("   估算 tokens：入 ≈ %s / 出 ≈ %s" % (f"{int(n*(avg/2+40)):,}", f"{int(n*24):,}"))
        return 0
    if a.run:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(run_batches(items, OUT))
        return 0
    if a.merge:
        got = {}
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            if r["zh"]:
                got[r["id"]] = r["zh"]
        have = {r[0] for r in con.execute("SELECT sense_id FROM sense_gloss WHERE lang='zh'")}
        rows = [(sid, "zh", "equivalent", 0, zh, MODEL)
                for sid, zh in got.items() if sid not in have]   # 🔴 只填空，绝不覆盖
        print("■ 结果 %s 条，其中要写入 %s 条（已有中文的一律不覆盖）"
              % (f"{len(got):,}", f"{len(rows):,}"))
        con.close()
        with dbtool.session("translate-it-defs", expect={"#sense_gloss": len(rows)}) as s:
            s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                          "VALUES (?,?,?,?,?,?)", rows)
        print("■ 已写入")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
