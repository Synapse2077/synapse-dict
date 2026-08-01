#!/usr/bin/env python3
"""B1×kaikki 改写结果里"可疑"那批的重写(turbo batch)。见对话 2026-07-28。

fix_b1_kaikki.py 把 39,161 条 [网络] 音译换成了原形词义,抽 500 验 ok 93.0%/bad 7.0%。
35 条 bad 有共同形态:**kaikki 说是动词变形,但库里原形只有名词义**,于是抄来的是名词释义:
    posteth      → post的第三人称单数 + n. 柱, 杆, 邮件…
    secretarying → secretary的现在分词 + n. 秘书
    booping      → boop的现在分词 + abbr. 细支气管炎…(原形是缩写)
确定性可标出这批 4,164 条(动词变形但原形无 v./vt./vi. 3,946 + 原形是缩写 218)。

⚠️ **这批不能撤回,只能重写**:撤回=退回 [网络] 音译,而 [网络] 本身 bad 53.6%;
   实测这 4,164 条当前约 67% 是对的 —— 退回去反而更差(49 条标注:现 33ok/16bad,
   退回按 46% 可用率约 22ok/27bad)。
   **A1 那套"宁可多撤"的逻辑在 B1 不成立,因为 B1 的"原状"本身就是坏的,不是无害的。**
   → 故 skip 分支 = **保持现状**(已回填的版本),而不是回退。

用法:
  python3 en/rewrite_b1_suspect.py            # dry-run
  python3 en/rewrite_b1_suspect.py --run      # 备份后写库,留痕 b1_rewrite.tsv
"""
import argparse, asyncio, re, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
FILL = paths.WORK / "ledgers/b1_kaikki_fill.tsv"
LOG = paths.WORK / "ledgers/b1_rewrite.tsv"
CHUNK = 10

VERB = ("的现在分词", "的动名词", "的过去分词", "的过去式", "的第三人称单数")
HASV = re.compile(r"(^|\n)\s*(v|vt|vi)\s*\.")
ABBR = re.compile(r"(^|\n)\s*(abbr\.|\[?=)")

SYS = """你是英汉词典编纂专家。给你一批英语词条,每条含:
  word 英语词(是某个标准词的变形或异体拼写)
  rel  形态关系(如"post的第三人称单数")
  zh   当前中文译文(有问题:它抄的是原形的**名词**释义,或原形是个缩写,与该变形词对不上)

请你**重写**该词条的中文译文。要求:
- 首行保留 rel 这句形态说明,换行后给出**该词本身**的准确中文释义;
- 动词变形要给**动词义**(如 posteth 是 post 作动词"邮寄、张贴"的古体第三人称单数,不是名词"柱子");
- 词义给最常用的 1–3 个,简洁;动词用 v./vt./vi.,名词 n.,形容词 adj.;有学科属性可带 [医][化] 标签。

**如果该词条本身不成立就不要硬编**,返回 {"fix":"skip","why":"…"}:
- 原形是纯名词/形容词,不存在该动词变形(candidate 无 candidated、metric 无 metricked);
- 原形其实是缩写,该变形无意义;
- 该拼写不是一个真实英语词。

每条返回 {"fix":"rewrite","zh":"完整译文(可含换行\\n)"} 或 {"fix":"skip","why":"原因"}。
严格输出 JSON {"1":{...},"2":{...}},键与输入一致,无多余文字。"""


def load_suspect(conn):
    trans = {}
    for w, t in conn.execute("SELECT word, translation FROM stardict"):
        trans.setdefault(w.strip().lower(), (t or "").strip())
    out = []
    for i, ln in enumerate(open(FILL, encoding="utf-8")):
        if not i:
            continue
        c = ln.rstrip("\n").split("\t")
        rid, word, base = int(c[0]), c[1], c[2]
        after = c[4].replace("\\n", "\n")
        rel = after.split("\n")[0]
        bt = trans.get(base.lower(), "")
        why = None
        if any(k in rel for k in VERB) and not HASV.search(bt):
            why = "动词变形但原形无动词义"
        elif ABBR.search(bt):
            why = "原形是缩写"
        if why:
            out.append((rid, word, rel, after, why))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    rows = load_suspect(conn)
    if a.limit:
        rows = rows[:a.limit]
    print(f"[B1 可疑重写] {len(rows)} 条", flush=True)
    print("  " + "  ".join(f"{k}:{v}" for k, v in Counter(r[4] for r in rows).items()))

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "rel": r[2], "zh": r[3]}
                            for k, r in enumerate(sub, 1)})
            metas.append(sub)
        res, tok = await S.run_batches(SYS, batches, env["DOUBAO_SEED_2_1_TURBO_BATCH"],
                                       cl.batch.chat.completions,
                                       (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 180))
        await cl.close()
        return metas, res, tok

    metas, results, tok = asyncio.run(go())
    tally = Counter(); rewrites = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, rel, after, why) in enumerate(meta, 1):
            v = res.get(str(k))
            act = v.get("fix") if isinstance(v, dict) else None
            if act == "rewrite" and isinstance(v.get("zh"), str) and v["zh"].strip():
                tally["rewrite"] += 1
                rewrites.append((rid, w, after, v["zh"].strip()))
            else:
                tally["skip/novote(保持现状,不退回[网络])"] += 1

    print(f"\n===== {sum(tally.values())} 条 token {tok} =====")
    for k, v in tally.most_common():
        print(f"  {k:34} {v:>6}")
    for rid, w, old, new in rewrites[:8]:
        print(f"\n  {w}\n    前: {old.replace(chr(10),' ⏎ ')[:58]}\n    后: {new.replace(chr(10),' ⏎ ')[:70]}")

    if not a.run or not rewrites:
        print("\n(dry-run;加 --run 写库)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-b1rw-{tag}.bak"))
    conn = sqlite3.connect(DB)
    # 重跑保护:先把上一轮重写退回到"回填版"(不是 [网络] 原文)
    if LOG.exists():
        for i, ln in enumerate(open(LOG, encoding="utf-8")):
            if i:
                c = ln.rstrip("\n").split("\t")
                conn.execute("UPDATE stardict SET translation=? WHERE id=?",
                             (c[2].replace("\\n", "\n"), int(c[0])))
        conn.commit()
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("id\tword\tbefore_filled\tafter\n")
        for rid, w, old, new in rewrites:
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            f.write("\t".join([str(rid), w, old.replace("\n", "\\n"), new.replace("\n", "\\n")]) + "\n")
    conn.commit()
    conn.close()
    print(f"\n已重写 {len(rewrites)} 条,留痕 → {LOG.name};备份 pre-b1rw-{tag}.bak")


if __name__ == "__main__":
    main()
