#!/usr/bin/env python3
"""前置撇号(省音)族 —— 跨桶形态缺陷,一次扫净。见对话 2026-07-29。

词头以 `'` 开头 + 字母 = h 脱落等省音形式:`'aircut`=haircut、`'ammer`=hammer、`'appy`=happy、
`'A' game`="最佳状态"。kaikki 措辞多为 "Pronunciation spelling of X"。
**众包译者没识别撇号,按字面拆词或音译**:
    'aircut → "空气剪;空切削"(当成 air cut)   'ammer → "默河;阿默尔河"
    'appen  → "阿彭;急性盲肠炎"                'A' game → "游戏;一个游戏;一局"
⚠️ 光看 `'aircut→空气剪` **不像错**(库里另有 `air cut→气割` 确实存在) —— 不查撇号很容易放过,判官也会漏判。

🔴 **为什么要单独做**:这是**按形态特征分布的缺陷族,横跨八个桶**。
   全库 1,082 条,其中 **286 条藏在 C2** —— 而 C2 抽样 bad 仅 0.3%、已判定"不用动"。
   **按来源分桶抽样,会整族漏掉这种跨桶缺陷。**

处置:
  有 kaikki 释义的 → lite 依释义重写(翻译题);
  无 kaikki 释义的 → **pro** 依省音规则推断(知识题:要认得 'appen=happen 且知道 happen 的义)。
  两路都要求给**实际词义**,形态关系写括注,不许只写"X 的省音形式"。

用法:
  python3 en/fix_elision_apostrophe.py            # dry-run
  python3 en/fix_elision_apostrophe.py --run      # 备份后写库,留痕 elision_fix.tsv
"""
import argparse, asyncio, json, re, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S
import buckets as B

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"
LOG = HERE / "elision_fix.tsv"
GLOSSES = ["b1_kaikki_gloss.json", "b2_kaikki_gloss.json",
           "c3_kaikki_gloss.json", "c356_kaikki_gloss.json"]

BASE_RULES = """撇号在词头表示**省音**,最常见是 h 脱落(伦敦腔/方言/口语):
  'aircut='haircut  'ammer=hammer  'appy=happy  'appen=happen  'ang=hang  'ome=home  'ead=head
也可能是其他省略:'em=them  'til=until  'bout=about  'cause=because  'n'=and  'A' game=one's A game(最佳状态)。"""

SYS_ANCHORED = """你是英汉词典编纂专家。给你一批**词头带撇号的省音形式**英语词条,每条含:
  word 词条(撇号表示省掉的字母)    zh 当前中文译文(**多为误译:把撇号忽略后按字面拆词或音译,不要信**)
  en   该词在 Wiktionary 的英文释义(可信,以它为准)
""" + BASE_RULES + """
请给出准确的中文译文:
- **必须给实际词义**,形态关系写在括注里:`n. 理发(haircut 的省音拼写)`;
- **绝不能只写"X 的省音形式/非标准拼写"就交差** —— 那等于没解释;
- 词性用 n./v./vt./vi./adj./adv./pron./int.;可用 <口><方><俚> 标记;
- 不要在译文里写 `[网络]` 这个标记。
无法确定则返回 {"fix":"skip","why":"原因"}。
每条返回 {"fix":"rewrite","zh":"译文"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""

SYS_KNOWLEDGE = """你是英汉词典编纂专家。给你一批**词头带撇号的省音形式**英语词条,每条含:
  word 词条(撇号表示省掉的字母)    zh 当前中文译文(**多为误译:把撇号忽略后按字面拆词或音译,不要信**)
Wiktionary 没有收录它们,请**凭你自身英语知识**判断它还原后是哪个词,再给出中文。
""" + BASE_RULES + """
要求:
- **必须给实际词义**,形态关系写括注:`v. 发生(happen 的省音拼写)`;
- **绝不能只写"X 的省音形式"就交差**;
- 词性用 n./v./vt./vi./adj./adv./pron./int.;可用 <口><方><俚> 标记;
- 不要在译文里写 `[网络]` 这个标记。
**若你判断不出它还原后是哪个词,或该拼写并非省音形式(可能是外语词、专名、乱码),不要编造** ——
返回 {"fix":"skip","why":"原因"}。编造的释义比留着原样更有害。
每条返回 {"fix":"rewrite","zh":"译文"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""

PTRONLY = re.compile(r"^\s*(?:[a-z]{1,6}\.\s*)?[A-Za-z][\w'’\- ]*\s*的[^,，;；)）]{0,10}(拼写|变体|形式|写法)\s*[<（(]?[^)）]{0,8}[)）>]?\s*$")


def collect(conn):
    gl = {}
    for f in GLOSSES:
        p = HERE / f
        if p.exists():
            for k, v in json.load(open(p, encoding="utf-8")).items():
                gl.setdefault(k, v[0] if isinstance(v, list) else v)
    anchored, blind = [], []
    for rid, w, t, bk in B.load_tail(conn):
        ws = w.strip()
        if not (ws.startswith("'") and len(ws) > 2 and ws[1].isalpha()):
            continue
        cur = (t or "").strip()
        en = gl.get(ws.lower())
        (anchored if en else blind).append((rid, ws, cur, en or "", bk))
    return anchored, blind


async def run(sysp, rows, model, comps, hedge, chunk):
    batches, metas = [], []
    for j in range(0, len(rows), chunk):
        sub = rows[j:j + chunk]
        batches.append({str(k): ({"word": r[1], "zh": r[2][:120], "en": r[3][:180]} if r[3]
                                 else {"word": r[1], "zh": r[2][:120]})
                        for k, r in enumerate(sub, 1)})
        metas.append(sub)
    res, tok = await S.run_batches(sysp, batches, model, comps, hedge)
    return metas, res, tok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    anchored, blind = collect(conn)
    print(f"[前置撇号族] 共 {len(anchored)+len(blind)} 条")
    print(f"  有 kaikki 释义 → lite  {len(anchored)}")
    print(f"  无 kaikki 释义 → pro   {len(blind)}")
    print("  分桶: " + "  ".join(f"{k}:{v}" for k, v in
          Counter(r[4] for r in anchored + blind).most_common()))

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        out = []
        tot = 0
        if anchored:
            m, r, tk = await run(SYS_ANCHORED, anchored, env["DOUBAO_MODEL_BATCH_LITE"],
                                 cl.batch.chat.completions,
                                 (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 300), 20)
            out.append(("lite", m, r)); tot += tk
        if blind:
            m, r, tk = await run(SYS_KNOWLEDGE, blind, env["DOUBAO_SEED_2_1_PRO"],
                                 cl.chat.completions, None, 10)
            out.append(("pro", m, r)); tot += tk
        await cl.close()
        return out, tot

    parts, tok = asyncio.run(go())
    tally = Counter(); fixes = []
    for who, metas, results in parts:
        for meta, res in zip(metas, results):
            res = res or {}
            for k, r in enumerate(meta, 1):
                v = res.get(str(k))
                act = v.get("fix") if isinstance(v, dict) else None
                zh = v.get("zh", "").strip() if isinstance(v, dict) else ""
                if act == "rewrite" and zh and not PTRONLY.match(zh.replace("\n", " ")) \
                        and not B.is_shell(zh) and "[网络]" not in zh:
                    tally[f"{who} rewrite"] += 1
                    fixes.append((r[0], r[1], r[2], zh))
                else:
                    tally[f"{who} skip/拦下"] += 1

    print(f"\n===== token {tok} =====")
    for k, v in tally.most_common():
        print(f"  {k:18} {v:>5}")
    for rid, w, old, new in fixes[:10]:
        print(f"  {w:14} 前:{old.split(']')[-1].strip()[:20]:22} 后:{new[:44]}")

    if not a.run or not fixes:
        print("\n(dry-run;加 --run 写库)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-elision-{tag}.bak"))
    conn = sqlite3.connect(DB)
    if LOG.exists():
        for i, ln in enumerate(open(LOG, encoding="utf-8")):
            if i:
                c = ln.rstrip("\n").split("\t")
                conn.execute("UPDATE stardict SET translation=? WHERE id=?",
                             (c[2].replace("\\t", "\t").replace("\\n", "\n"), int(c[0])))
        conn.commit()
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("id\tword\tbefore\tafter\n")
        for rid, w, old, new in fixes:
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            conn.execute("UPDATE stardict SET qual='fixed' WHERE id=? AND qual NOT IN ('core','judged')", (rid,))
            f.write("\t".join([str(rid), w,
                               old.replace("\t", "\\t").replace("\n", "\\n"),
                               new.replace("\t", "\\t").replace("\n", "\\n")]) + "\n")
    conn.commit()
    conn.close()
    print(f"\n已修 {len(fixes)} 条(qual 已同步),留痕 → {LOG.name};备份 pre-elision-{tag}.bak")


if __name__ == "__main__":
    main()
