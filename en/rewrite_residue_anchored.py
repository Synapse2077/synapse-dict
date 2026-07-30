#!/usr/bin/env python3
"""B1/B2/C3 残留中**有 kaikki 锚**的部分:lite 依英文释义重写。见对话 2026-07-29。

前几轮 B1/B2/C3 重写用的是各自的 gloss 文件(b1_/b2_/c3_kaikki_gloss.json),
那几份是**过滤过的残缺版**(按当时的措辞规则筛过)。本轮用 residue_kaikki_gloss.json
—— 对全部残留词形重新全量扫 kaikki 得到的原始首义,不做措辞过滤,锚覆盖显著变高:
    C5 40.3% → 67.4%   B2 0.2% → 14.9%   C6 6.6% → 13.1%

本脚本只吃三段中**最脏且有锚**的 39,947 条(条数少、bad 率最高、又是翻译题=lite 最便宜):
    B1 残留 229,650 中有锚 10,740   (抽样 bad 53.6%,全库最脏)
    B2 残留 178,716 中有锚 26,712   (bad 22.3%)
    C3 残留  29,920 中有锚  2,495   (bad 14.4%)
无锚的 ~40 万条不在本轮范围:没有权威英文释义 = 从"翻译题"变成"知识题",必须上 pro,单价翻几倍。

⭐ 跑完有**免费红利**:现有 35,919 条 A1 空壳卡在"原形译文是 [网络] 众包"上,
   本轮把这些 base 洗干净后,再跑一次 fix_a1a.py 可零 API 成本级联回填一批。

用法:
  python3 en/rewrite_residue_anchored.py --limit 400   # pilot
  python3 en/rewrite_residue_anchored.py --run         # 备份后写库,留痕 residue_anchored_fix.tsv
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
GLOSS = HERE / "anchors/residue_kaikki_gloss.json"
LOG = HERE / "ledgers/residue_anchored_fix.tsv"
CHUNK = 20
SEGS = {"B1": "low", "B2": "low", "C3": "low"}

# B1/B2:众包音译垃圾 → 依英文释义给实义
SYS_WORD = """你是英汉词典编纂专家。给你一批英语词条,每条含:
  word 词条
  zh   当前中文译文(**来自众包,常是纯音译或张冠李戴,不要信它**)
  en   该词在 Wiktionary 的英文释义(可信,以它为准)
  rel  **仅部分词条有**:该词是某个原形的变形时,这里给出原形及原形的词义。
       此时译文要给**原形的实际词义**,再把形态关系写进括注,例:
         word='cats'  rel='本词是 cat 的复数;cat 的意思:A small domesticated feline'
         → `n. 猫(cat 的复数)`
       **绝不能只写 "cat 的复数" 就交差** —— 那等于没解释,用户划到词还是不知道什么意思。
请依据 en/rel 给出准确的中文译文:
- 词性用 n./v./vt./vi./adj./adv./pron./int./prep./conj.;
- 有学科属性可带 [医][化][计][法][军][生][地] 等标签;
- **人名/地名/专名照常音译**,但要补上它是什么:`n. 鲁思(美国棒球运动员贝比·鲁斯)`;
- 若有多个义项,给最主要的 1-3 个,用分号隔开;
- **必须给实际词义**,不能只写"X 的变体/异体/另一种写法"就交差 —— 那等于没解释,
  形态关系写在括注里:`n. 颜色(color 的英式拼写)`;
- 不要在译文里写 `[网络]` 这个标记。
**若 en 无实质信息、或你无法确定其含义,不要编造**,返回 {"fix":"skip","why":"原因"}。
每条返回 {"fix":"rewrite","zh":"译文"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""

# C3:缩写,额外要求给出英文全称
SYS_ABBR = """你是英汉词典编纂专家。给你一批英语**缩写/首字母词**,每条含:
  word 缩写本身
  zh   当前中文译文(**常把缩写展开错、或张冠李戴,不要信它**)
  en   该缩写在 Wiktionary 的英文释义(可信,以它为准;多为 "Initialism of X" / "Abbreviation of X")
  rel  **仅部分词条有**:已替你解出全称及其词义,直接用它组织译文,别只回显 "X 的缩写"。
请依据 en/rel 给出准确的中文译文:
- 格式:`abbr. 中文含义(英文全称)`,例:`abbr. 科学顾问(science advisor)`;
- **必须同时给中文和英文全称** —— 只给中文对缩写没有用;
- 若该缩写有多个常见义,给最主要的 1-2 个,用分号隔开;
- 有学科属性可带 [医][化][计][法][军] 等标签;
- en 里的全称若明显拼错,按你的知识订正后再译;
- 不要在译文里写 `[网络]` 这个标记。
**若 en 无实质信息、或你无法确定其含义,不要编造**,返回 {"fix":"skip","why":"原因"}。
每条返回 {"fix":"rewrite","zh":"译文"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""

# 纯指针输出(只说形态关系不给词义)——历轮反复出现的失败模式,必须拦。
# ⚠️ 原形要允许**撇号开头**:`n. 'cher 的复数` 曾因正则只认字母开头而漏网(pilot 400 条漏 3 条)。
PTRONLY = re.compile(r"^\s*(?:[a-z]{1,6}\.\s*|[前后]缀\s*)?['’\-A-Za-z][\w'’\- ]*\s*的[^,，;；)）]{0,10}"
                     r"(复数|单数|过去式|过去分词|现在分词|第三人称单数|比较级|最高级|"
                     r"拼写|变体|异体|形式|写法|缩写|简称|同义词)\s*[<（(]?[^)）]{0,8}[)）>]?\s*$")

# kaikki 首义**自己就是元描述**时,模型手里没有实义可译,只会原样回显出一个新空壳。
# → 先把原形的实义解出来当锚,解不出就**不发 API**(既保质量又省钱)。
ENMETA = re.compile(r"^(?:plural|singular|simple past(?: tense)?|past participle|present participle|"
                    r"gerund|third[- ]person singular|comparative|superlative|alternative|"
                    r"obsolete|archaic|dated|nonstandard|eye dialect|pronunciation|misspelling|"
                    r"initialism|abbreviation|acronym|clipping|contraction|synonym|"
                    r"short for|abbreviated form)\b[^.]*?\bof\s+(.+?)\s*[.;]?\s*$", re.I)
RELZH = {"plural": "复数", "singular": "单数", "simple past": "过去式", "past participle": "过去分词",
         "present participle": "现在分词", "third": "第三人称单数", "comparative": "比较级",
         "superlative": "最高级", "initialism": "首字母缩写", "abbreviation": "缩写",
         "acronym": "缩略词", "clipping": "截短形式", "contraction": "缩约形式"}


def _rel_zh(g):
    low = g.lower()
    for k, v in RELZH.items():
        if low.startswith(k):
            return v
    return "变体/异体拼写"


def collect(conn):
    gl = json.load(open(GLOSS, encoding="utf-8"))
    q = dict(conn.execute("SELECT id, COALESCE(qual,'?') FROM stardict"))
    # 库内实义索引:给"kaikki 首义是元描述"的词解原形用
    dbt = {}
    for w, t in conn.execute("SELECT word, translation FROM stardict"):
        k = (w or "").strip().lower()
        if k and k not in dbt and t and "[网络]" not in t and not B.is_shell(t) \
                and re.search(r"[一-鿿]", t):
            dbt[k] = t.strip()
    rej = Counter(); out = []
    for rid, w, t, bk in B.load_tail(conn):
        if SEGS.get(bk) != q.get(rid):
            continue
        ws = w.strip()
        en = (gl.get(ws.lower()) or "").strip()
        if not en:
            rej[f"{bk} 无 kaikki 锚"] += 1; continue
        if len(en) < 4:
            rej[f"{bk} 英文释义过短"] += 1; continue
        rel = ""
        m = ENMETA.match(en)
        if m:                                   # 锚自己是元描述 → 换成原形的义
            base = m.group(1).strip().strip('"“”').lower()
            ben = gl.get(base) or ""
            if ENMETA.match(ben or ""):
                ben = ""                        # 原形的锚还是元描述,不再递归
            bzh = dbt.get(base, "")
            if not ben and not bzh:
                rej[f"{bk} 锚是元描述且原形无实义"] += 1; continue
            rel = f"本词是 {base} 的{_rel_zh(en)};{base} 的意思:" + (ben or bzh)[:200]
            en = ben or ""
        out.append((rid, ws, (t or "").strip(), en, bk, rel))
    return out, rej


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    rows, rej = collect(conn)
    if a.limit:
        rows = rows[:a.limit]
    print(f"[B1/B2/C3 有锚残留 · lite 依英文释义重写] {len(rows)} 条")
    print("  分段: " + "  ".join(f"{k}:{v}" for k, v in Counter(r[4] for r in rows).most_common()))
    for k, v in rej.most_common():
        print(f"  剔除 {k:22} {v:>7,}")
    if not rows:
        return

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        out = []; tot = 0
        for tag, sysp in (("word", SYS_WORD), ("abbr", SYS_ABBR)):
            sub = [r for r in rows if (r[4] == "C3") == (tag == "abbr")]
            if not sub:
                continue
            batches, metas = [], []
            for j in range(0, len(sub), CHUNK):
                s = sub[j:j + CHUNK]
                batches.append({str(k): ({"word": r[1], "zh": r[2][:120], "en": r[3][:180],
                                          "rel": r[5][:220]} if r[5] else
                                         {"word": r[1], "zh": r[2][:120], "en": r[3][:180]})
                                for k, r in enumerate(s, 1)})
                metas.append(s)
            print(f"  → {tag} {len(sub)} 条 / {len(batches)} 批")
            res, tk = await S.run_batches(sysp, batches, env["DOUBAO_MODEL_BATCH_LITE"],
                                          cl.batch.chat.completions,
                                          (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 300))
            out.append((tag, metas, res)); tot += tk
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
                flat = zh.replace("\n", " ")
                if act != "rewrite" or not zh:
                    tally[f"{who} skip"] += 1
                elif PTRONLY.match(flat):
                    tally[f"{who} 拦下·纯指针"] += 1
                elif B.is_shell(zh):
                    tally[f"{who} 拦下·空壳"] += 1
                elif "[网络]" in zh:
                    tally[f"{who} 拦下·[网络]撞车"] += 1
                elif zh == r[2]:
                    tally[f"{who} 拦下·零变动"] += 1
                else:
                    tally[f"{who} rewrite"] += 1
                    fixes.append((r[0], r[1], r[2], zh))

    print(f"\n===== {len(rows)} 条 token {tok} =====")
    for k, v in tally.most_common():
        print(f"  {k:22} {v:>6,}")
    for rid, w, old, new in fixes[:10]:
        print(f"\n  {w}\n    前: {old.replace(chr(10),' / ')[:52]}\n    后: {new.replace(chr(10),' / ')[:72]}")

    if not a.run or not fixes:
        print("\n(dry-run;加 --run 写库)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-residue-{tag}.bak"))
    conn = sqlite3.connect(DB)
    if LOG.exists():   # 重跑保护:先把上一轮写回去,避免 before 失真
        for i, ln in enumerate(open(LOG, encoding="utf-8")):
            if i:
                c = ln.rstrip("\n").split("\t")
                conn.execute("UPDATE stardict SET translation=?, qual='low' WHERE id=?",
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
    print(f"\n已重写 {len(fixes)} 条(qual 已同步),留痕 → {LOG.name};备份 pre-residue-{tag}.bak")


if __name__ == "__main__":
    main()
