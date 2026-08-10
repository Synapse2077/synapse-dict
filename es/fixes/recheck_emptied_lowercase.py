#!/usr/bin/env python3
"""复核被拆空的小写词条：它们的小写形在西语里到底成不成立。2026-08-07。

`split_case_homographs.py` 把 3,195 条义项搬到新建的专名词条后，
**918 个小写行一条义项都不剩**。逐条看下来分两类：

  · **844 个是真变形**（`argentina` = `argentino` 的阴性、`estonia` 同理），
    有变形指针，空着是对的 —— 本脚本不碰。
  · **70 个有中文却没义项**，是异常。

🔴 **我一度想加「一个词的义项不能全部搬走」这条保底规则 —— 那是错的**：

    chad     Chad（乍得国）+ Lake Chad        两条都是专名，搬空**是对的**
    led      LED 发光二极管                  西语里 `led` 就是小写普通名词（un led, los leds），搬空**是错的**
    tabasco  塔巴斯科酱 + 墨西哥塔巴斯科州       一条该留、一条该走

问题不是「留一条」，而是**「这个词的小写形在西语里成不成立」**。所以这一轮换个问法：
按**词**问（不是按义项问），只有小写形成立时，再问哪些义项属于它。

═══ 可逆 ═══
和上一轮一样，改的只有 `sense.word_id`。

用法：
    python3 -m es.fixes.recheck_emptied_lowercase            # 列出待复核的词
    python3 -m es.fixes.recheck_emptied_lowercase --ask
    python3 -m es.fixes.recheck_emptied_lowercase --ask --apply
"""
import argparse
import asyncio
import collections
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

RAW = paths.WORK / "recheck_lowercase_llm.jsonl"
MODEL = "deepseek-v4-pro"

SYS = """你是西班牙语词典编纂顾问。下面每个词在我们库里被拆成了大小写两个词条，
但**小写那个现在一条释义都没有了**（全被判给了大写专名）。请复核。

输入每条含：lower 小写词形 / upper 大写词形 / senses 该词的全部义项（现都归在大写词条下）

先判 `ok`：**小写形在西语里是否作为普通词存在**（普通名词/形容词/动词…）。
 · `led`     ✅ 存在 —— 西语里 `un led`、`los leds` 是普通名词（发光二极管）
 · `tabasco` ✅ 存在 —— `tabasco` 小写指辣酱（商品名转普通名词）
 · `chad`    ❌ 不存在 —— 只有 Chad（乍得国）和 Lago Chad，没有普通词义
 · `abisinia`❌ 不存在 —— 只有 Abisinia（阿比西尼亚）这个地名

若 `ok` 为 true，再给 `keep`：**哪些义项应该留在小写词条**（填义项 id 的数组）。
 · 判据是这条义项本身是不是普通词义：
     `LED (light-emitting diode)`  → 留（普通名词）
     `Tabasco sauce`               → 留（商品名转普通名词）
     `a state of Mexico`           → 不留（地名）
     `born under the zodiac sign Pisces` → 留（形容词「双鱼座的」在西语里小写）
     `Pisces (constellation)`      → 不留（星座名）
 · 若 `ok` 为 false，`keep` 给空数组。

只输出 JSON：{"结果":[{"lower":小写词形,"ok":true/false,"keep":[义项id,…]},…]}，
条数与输入完全相等。"""


def targets(con):
    """被拆空、且有中文（说明不是纯变形）的小写词条。"""
    rows = con.execute("""
        SELECT d.id, d.word FROM dict d
        WHERE NOT EXISTS (SELECT 1 FROM sense s WHERE s.word_id = d.id)
          AND d.word = lower(d.word)
          AND TRIM(COALESCE(d.translation,'')) <> ''
          AND TRIM(COALESCE(d.infl,'')) = ''
          AND EXISTS (SELECT 1 FROM dict d2
                      WHERE d2.word = d.word COLLATE NOCASE AND d2.id <> d.id)
        """).fetchall()
    out = []
    for did, w in rows:
        up = con.execute(
            "SELECT id, word FROM dict WHERE word = ? COLLATE NOCASE AND id <> ?",
            (w, did)).fetchone()
        if not up:
            continue
        ss = con.execute("""
            SELECT s.id, g.text, (SELECT sr.text FROM sense_src sr
                                  WHERE sr.sense_id = s.id LIMIT 1)
            FROM sense s LEFT JOIN sense_gloss g
              ON g.sense_id = s.id AND g.lang='zh' AND g.seq=0
            WHERE s.word_id = ? ORDER BY s.rank""", (up[0],)).fetchall()
        out.append({"lower": w, "upper": up[1], "_lid": did, "_uid": up[0],
                    "senses": [{"id": i, "zh": (z or "")[:40], "en": (e or "")[:70]}
                               for i, z, e in ss]})
    return out


async def ask(items, env):
    import httpx
    async with httpx.AsyncClient(timeout=900) as cl:
        r = await cl.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": "Bearer " + env["DEEPSEEK_API_KEY"].strip()},
            json={"model": MODEL,
                  "messages": [{"role": "system", "content": SYS},
                               {"role": "user", "content": json.dumps(
                                   [{k: v for k, v in it.items() if not k.startswith("_")}
                                    for it in items], ensure_ascii=False)}],
                  "temperature": 0, "response_format": {"type": "json_object"},
                  "thinking": {"type": "disabled"}, "stream": False})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        d = json.loads(r.text)
        res = next((v for v in json.loads(
            d["choices"][0]["message"]["content"]).values() if isinstance(v, list)), [])
        return res, (d.get("usage") or {})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    items = targets(con)
    con.close()
    print(f"待复核 {len(items)} 个词（被拆空、有中文、非变形）")
    for it in items[:6]:
        print(f"  {it['lower']} / {it['upper']}  {len(it['senses'])} 义项："
              f"{[s['zh'][:12] for s in it['senses'][:3]]}")
    if not args.ask:
        print("\n未加 --ask，不发请求。")
        return

    env = dict(l.split("=", 1) for l in paths.ENV.read_text().splitlines()
               if "=" in l and not l.startswith("#"))
    res, usage = asyncio.run(ask(items, env))
    print(f"\n模型返回 {len(res)} 条，{usage.get('total_tokens', 0):,} tokens")
    by = {it["lower"]: it for it in items}
    plan, stat = [], collections.Counter()
    for r in res:
        it = by.get(r.get("lower"))
        if not it:
            continue
        if not r.get("ok"):
            stat["小写形不成立，维持搬空"] += 1
            continue
        keep = [i for i in (r.get("keep") or [])
                if i in {s["id"] for s in it["senses"]}]
        if not keep:
            stat["ok=true 但没给 keep（当不成立处理）"] += 1
            continue
        stat["小写形成立，搬回义项"] += 1
        for sid in keep:
            plan.append((it["_lid"], sid))
    for k, v in stat.most_common():
        print(f"  {k:<30}{v:>4}")
    print(f"\n待搬回 {len(plan)} 条义项")
    for r in res[:20]:
        it = by.get(r.get("lower"))
        if it and r.get("ok"):
            zh = {s["id"]: s["zh"] for s in it["senses"]}
            print(f"   {r['lower']:<12}留下 {[zh.get(i, '?')[:14] for i in (r.get('keep') or [])]}")

    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    with dbtool.session("recheck-emptied-lowercase", expect={}) as s:
        s.executemany("UPDATE sense SET word_id=? WHERE id=?", plan)

    # rank 重排：两边都动了
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    cur = collections.defaultdict(list)
    for sid, wid, rk in con.execute(
            "SELECT id, word_id, rank FROM sense ORDER BY word_id, rank"):
        cur[wid].append(sid)
    con.close()
    re_rank = [(i, sid) for lst in cur.values() for i, sid in enumerate(lst, 1)]
    with dbtool.session("resequence-after-recheck", expect={}) as s:
        s.executemany("UPDATE sense SET rank=? WHERE id=?", re_rank)

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    left = con.execute("""
        SELECT COUNT(*) FROM dict d WHERE NOT EXISTS
          (SELECT 1 FROM sense s WHERE s.word_id = d.id)
          AND d.word = lower(d.word) AND TRIM(COALESCE(d.translation,'')) <> ''
          AND TRIM(COALESCE(d.infl,'')) = ''
          AND EXISTS (SELECT 1 FROM dict d2
                      WHERE d2.word = d.word COLLATE NOCASE AND d2.id <> d.id)
        """).fetchone()[0]
    bad = sum(1 for wid, n, mx in con.execute(
        "SELECT word_id, COUNT(*), MAX(rank) FROM sense GROUP BY 1") if n != mx)
    con.close()
    print(f"\n落库后：仍被拆空的（判定小写形不成立，正常）{left}；rank 不连续 {bad}")
    assert bad == 0


if __name__ == "__main__":
    main()
