#!/usr/bin/env python3
"""A1 空壳(69,120)turbo 重译 —— 按锚分层,伪复数剔出不填。见对话 2026-07-29。

A1 空壳 = 整条译文只交代"它是谁的复数/分词",无任何实际词义(用户划到它=白查)。
历轮 `fix_a1a.py` 是**确定性回填**(把库内原形译文原样追加),卡在三个地方:
原形译文是 [网络] 垃圾 / 闸拦下 / 禁止重填名单。本脚本换打法:**交给模型重译**,
把能拿到的锚(kaikki 英文释义 + 库内原形中文)一并喂进去,让它给出 word 本身的词义。

⭐ 分层是关键(pilot 1000 条实测,四层表现完全不同):
    层A 原形有 kaikki 释义 + 库内中文可信  18,056  turbo 重写 93%  pro 判 bad 2.5%
    层B 只有库内中文可信                    5,307  重写 82%       bad 4.9%
    层C 只有 kaikki                          242  重写 86%       bad 6.2%
    层D 无锚(原形中文是[网络]且 kaikki 未收) 45,442  重写 60%       bad 0.7% ← **假象,别信**
🔴 **层D 的 0.7% 是判官放水**:JUDGE_SYS 写着"拿不准就判 ok",而 D 恰恰是判官也不认识的词。
   看词条本身才露馅:`ammianuss` `arctostaphylo­uss` `chamaea fasciatas` `phylum pogonophoras`
   —— ECDICT 给人名/拉丁学名/分类阶元机械加了 s。turbo 译文单看都对(威廉·詹宁斯·布莱恩确实是那人),
   但它在**给不该存在的词条编造合法性**(还编出"指同名的人"这种说法)。
   **这批是删除对象,不是回填对象。**

🔴 **"去掉 s 变正常词"不可行,而且 98.5% 与 1.4% 要反着办**(用户提出,查证后):
   · 19,991 条(98.5%)**原形已经在库里**(且原形译文本身也是 [网络] 垃圾)→ 去 s = 造重复条目;
   · 281 条(1.4%)**根本不是复数**,是 ECDICT 见词尾 s 就机械判定 → 该给真词义,不是去 s。
     kaikki 证实:`Acheloos`=Achelous 的异体 / `Colemanballs`=解说口误(本身是正常名词) /
     `Cheggers`=英国主持人 Keith Chegwin / `Basses-Alpes`=法国某省旧称 /
     `Gagauzes`= plural of **Gagauz**(ECDICT 连原形都拼错成 gagauze)。

模型分工:A/B/C = **翻译题 → turbo batch**(锚在输入里);281 条假复数 = **知识题 → pro**。

用法:
  python3 en/fix_a1_shells_turbo.py                 # 只落分类矩阵,不发 API
  python3 en/fix_a1_shells_turbo.py --run           # 备份后写库,留痕 a1_turbo_fix.tsv
  python3 en/fix_a1_shells_turbo.py --run --limit N # 小批试
"""
import argparse, asyncio, json, re, shutil, sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S
import buckets as B
import rewrite_residue_anchored as R

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"
BASE_GLOSS = HERE / "anchors/a1_base_gloss.json"       # 原形 → kaikki 首个实义(非元描述)
LOG = HERE / "ledgers/a1_turbo_fix.tsv"
WORD_IN_KAIKKI = HERE / "runs/a1_pseudo_kaikki.json"  # 词条本身在 kaikki 有条目 = 该复数形式真实存在
PSEUDO = HERE / "ledgers/a1_pseudoplural_candidates.tsv"   # 伪复数删除候选清单(本脚本只落盘,不删)
CHUNK = 20
MODEL_KEY = "DOUBAO_MODEL_BATCH_LITE"   # ⭐ 同批 1000 条实测 lite vs turbo:bad 只差约 1pt、token 用量相同
HEDGE_AFTER = 1200   # ⚠️ 别用 300:batch 队列一堵就**全部**切 online pro,单价差一个数量级
                     #   (pass2 首次跑 200/200 批全切,被迫中止;第一遍 754 批切 0 次)
MODEL_TAG = "lite"                     #   且两者 bad 高度重合(8 条里 7 条相同)=残留是数据问题,换模型修不掉

# 空壳里的原形。⚠️ ECDICT 的原形可能拼错(Gagauzes 写成 "gagauze 的复数"),仅作线索用。
# ⚠️ 必须容忍 `是`/`为` 系动词:`n. 是lobing的复数形式` 里原形前面不是空格/括号,
#    旧版提取不到原形 → 该条被误算成"层D 无锚"而放弃,实际库内原形俱在。
#    与 buckets.is_shell 同源缺陷,2026-07-29 一并修(440 条误判无锚里绝大多数是这个)。
PAT = re.compile(r"(?:^|[(（\s])(?:[a-z]{1,6}\.\s*)?(?:是|为)?\s*([A-Za-z][\w''\- ]*?)\s*"
                 r"的(?:复数|单数|过去式|过去分词|现在分词|第三人称单数|比较级|最高级|变形|变化形式)")
# 真·伪变形来源:分类阶元/地名限定词开头 —— 这些东西本身没有复数
TAXON = re.compile(r'^(genus|family|order|class|subclass|suborder|superfamily|subfamily|phylum|'
                   r'division|tribe|kingdom|saint|st|lake|mount|cape|fort|port)\b', re.I)
LATIN = re.compile(r'(ss|us|um|ae|is|oides)$', re.I)   # 拉丁双名的种加词形态

SYS = """你是英汉词典编纂专家。给你一批英语**变形词条**(复数/过去式/分词等),每条含:
  word     词条本身
  cur      词典现有内容 —— **只交代了它是谁的变形,没有任何实际词义**,用户查到它等于白查
  base     它的原形(注意:这是原词典机械推出来的,**可能拼错**,以你的判断为准)
  base_en  原形在 Wiktionary 的英文释义(**可信**,有则以它为准)
  base_zh  原形在词典里的中文,可信度见 zh_trust
  zh_trust "可信" 或 "不可信(众包音译垃圾,别照抄)"
任务:给出 **word 本身**的准确中文译文。
- **必须给实际词义**,形态关系写在括注里:`n. 围堰(cofferdam 的复数)`、`v. 发生(happen 的过去式)`;
- **绝不能只写"X 的复数"就交差** —— 那就是现在这条毫无用处的状态;
- 词性要与形态一致:复数→n.;过去式/分词→v./vt./vi.;比较级/最高级→adj./adv.;
- ⚠️ 原形若是**跨词性多义词**,只取与该变形相符的那个义
  (如 apparate 名词=装置、动词=幻影移形,则 apparating 只能取动词义);
- 可带 [医][化][计][法][军][生][地] 学科标签;人名/地名照常音译但要补上它是什么;
- 不要写 `[网络]` 这个标记。
**若没有可信依据、或你判断不出该词真实含义,不要编造** —— 返回 {"fix":"skip","why":"原因"}。
编造的释义比留着"X 的复数"更有害:它看起来可信。
每条返回 {"fix":"rewrite","zh":"译文"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""

SYS_FALSEPL = """你是英汉词典编纂专家。给你一批英语词条,每条含 word 和 cur(词典现有内容)。
这批词条的现有内容都说"它是某某的复数",但**这个判断是错的** —— 原词典只是看到词尾有 s
就机械判定为复数。它们其实是**本身独立的词**:属名、人名、地名、旧称、或有自己含义的名词。
已核实的例子:
  Acheloos     实为 Achelous(希腊河神阿刻罗俄斯)的异体拼写,不是 "acheloo 的复数"
  Colemanballs 实为"(尤指体育解说中的)口误、混乱比喻",本身就是正常名词
  Cheggers     实为英国演员主持人 Keith Chegwin 的昵称
  Basses-Alpes 实为法国 Alpes-de-Haute-Provence 省的旧称
  Arctostaphylos 实为熊果属(杜鹃花科植物的一个属)
请**凭你自身知识**给出该词真正的中文词义:
- 必须给实际词义,不要写"X 的复数"这种形态说明;
- 词性用 n./adj./v. 等;属名/学名用 `n. [植]/[动] 某某属`;人名地名要补上它是谁/在哪;
- 可带 [医][化][计][法][军][生][地] 学科标签;不要写 `[网络]` 这个标记。
**若你确实不认识这个词,不要编造** —— 返回 {"fix":"skip","why":"原因"}。
每条返回 {"fix":"rewrite","zh":"译文"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""


def zh_ok(t):
    return bool(t and "[网络]" not in t and not B.is_shell(t) and re.search(r"[一-鿿]", t))


def classify(conn, only=None):
    """only:id 白名单(set),None=全部 A1 空壳。用于只跑新识别出的那批,
    不去碰 36,293 条老残留(其中 23,727 是伪复数删除候选,明确不该回填)。"""
    kb = json.load(open(BASE_GLOSS, encoding="utf-8"))
    # ⭐ 伪复数否决票:kaikki 若收录了**该复数形式本身**,说明这个复数真实存在,不是 ECDICT 造的。
    #   第一轮只靠词形规则(专名/学名/阶元)判伪复数,**假阳性 27.5%**(7,849/28,540):
    #   A levels / abelian groups / Academy Awards / Abbe condensers 全被误伤。
    real = json.load(open(WORD_IN_KAIKKI, encoding="utf-8")) if WORD_IN_KAIKKI.exists() else {}
    rows = []
    for rid, w, tr, bk in B.load_tail(conn):
        if bk != "A1" or (only is not None and rid not in only):
            continue
        body = (tr or "").strip()
        m = PAT.search(body.replace("\n", " "))
        rows.append((rid, w.strip(), body, m.group(1).strip().lower() if m else ""))
    bases = {r[3] for r in rows if r[3]}
    info = {}
    for w, tr in conn.execute("SELECT word, translation FROM stardict"):
        k = (w or "").strip().lower()
        if k in bases and k not in info:
            info[k] = ((tr or "").strip(), w)
    out = defaultdict(list)
    for rid, w, body, b in rows:
        if not b:
            out["E 提不出原形"].append((rid, w, body, b)); continue
        bt, braw = info.get(b, ("", ""))
        anchored = (b in kb) or zh_ok(bt)
        # 伪复数判定:分类阶元前缀 / 拉丁双名形态 / 原形或词条词头大写(专名)
        pseudo = bool(TAXON.match(b)
                      or (" " in b and LATIN.search(b.split()[-1]))
                      or (braw[:1].isupper() if braw else False)
                      or w[:1].isupper())
        if pseudo and w.lower() in real:
            pseudo = False                      # kaikki 收了这个复数形式 → 不是伪复数
        if pseudo and b in info:
            out["P 伪复数·原形已在库(删除候选)"].append((rid, w, body, b)); continue
        if pseudo and b not in info:
            out["F 假复数·ECDICT 误判(pro 给真义)"].append((rid, w, body, b)); continue
        if not anchored:
            out["D 无锚(待单独 pilot)"].append((rid, w, body, b)); continue
        lay = "A" if (b in kb and zh_ok(bt)) else ("B" if zh_ok(bt) else "C")
        out[f"{lay} 有锚 → turbo"].append((rid, w, body, b))
    return out, kb, info


def item(r, kb, info):
    rid, w, body, b = r
    d = {"word": w, "cur": body.replace("\n", " ")[:80], "base": b}
    if b in kb:
        d["base_en"] = kb[b][:180]
    bt = info.get(b, ("", ""))[0]
    if bt:
        d["base_zh"] = bt.replace("\n", " ")[:120]
        d["zh_trust"] = "可信" if zh_ok(bt) else "不可信(众包音译垃圾,别照抄)"
    return d


def harvest(metas, results, tally, tag):
    """五查:零变动 / 空壳 / 纯指针 / [网络]撞车 / 制表符"""
    fixes = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, r in enumerate(meta, 1):
            v = res.get(str(k))
            act = v.get("fix") if isinstance(v, dict) else None
            zh = (v.get("zh") or "").strip() if isinstance(v, dict) else ""
            if act != "rewrite" or not zh:
                tally[f"{tag} skip"] += 1
            elif zh == r[2]:
                tally[f"{tag} 拦下·零变动"] += 1
            elif B.is_shell(zh):
                tally[f"{tag} 拦下·空壳"] += 1
            elif R.PTRONLY.match(zh.replace("\n", " ")):
                tally[f"{tag} 拦下·纯指针"] += 1
            elif "[网络]" in zh:
                tally[f"{tag} 拦下·[网络]撞车"] += 1
            elif "\t" in zh:
                tally[f"{tag} 拦下·含制表符"] += 1
            else:
                tally[f"{tag} rewrite"] += 1
                fixes.append((r[0], r[1], r[2], zh))
    return fixes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--layer-d", action="store_true", help="只跑层D(无锚,已剔伪变形):同批 500 条实测 turbo 可核实中 bad 1.8%,诚实版 lite 4.2%")
    ap.add_argument("--tag", default="", help="留痕文件后缀;第二遍必须换,否则重跑保护会把上一遍退回空壳")
    ap.add_argument("--turbo", action="store_true", help="改用 turbo(默认 lite:同批实测只差约1pt,单价更低)")
    ap.add_argument("--only-ids", help="JSON 文件,内含 id 列表;只处理这批(配合 --tag 用)")
    a = ap.parse_args()

    only = set(json.load(open(a.only_ids, encoding="utf-8"))) if a.only_ids else None
    if only is not None:
        print(f"[白名单] 只处理 {len(only):,} 个 id({a.only_ids})")

    global MODEL_KEY, MODEL_TAG, LOG, PSEUDO
    if a.tag:
        LOG = HERE / f"ledgers/a1_turbo_fix{a.tag}.tsv"
        # ⚠️ PSEUDO 也必须跟着 tag 走:它是无条件覆盖写。跑子集(--only-ids)时 pseudo 只有
        #    该子集内的伪复数,用默认名会把全量名单(23,728 行)截断成几百行,静默毁掉产物。
        PSEUDO = HERE / f"ledgers/a1_pseudoplural_candidates{a.tag}.tsv"
    MODEL_KEY = "DOUBAO_SEED_2_1_TURBO_BATCH" if (a.turbo or a.layer_d) else "DOUBAO_MODEL_BATCH_LITE"
    MODEL_TAG = "turbo" if (a.turbo or a.layer_d) else "lite"

    conn = sqlite3.connect(DB)
    groups, kb, info = classify(conn, only)
    tot = sum(len(v) for v in groups.values())
    print(f"[A1 空壳分类] 共 {tot:,} 条")
    for k in sorted(groups, key=lambda x: -len(groups[x])):
        print(f"  {k:34} {len(groups[k]):>7,}")

    if a.layer_d:
        # 层D = 无锚知识题:lite 不行(bad 4.2%),必须 turbo/pro;并剔掉已归入删除候选的伪变形族
        ADJ = re.compile(r'(ed|ing|like|proof|free|friendly|ready|specific|sized|shaped|oriented|'
                         r'related|driven|based|style|wheel|level|grade|scale)$', re.I)
        ABS = re.compile(r'(ness|ity|ism|ology|hood|ship)$', re.I)
        turbo_rows = []
        for rid, w, body, b in groups["D 无锚(待单独 pilot)"]:
            wl, bl = w.lower().strip(), b.lower().strip()
            if not bl:
                continue
            parts = bl.replace("-", " ").split(); last = parts[-1] if parts else bl
            if (bl.endswith("s") and wl == bl + "s") or \
               (("-" in bl or " " in bl) and ADJ.search(last)) or ABS.search(last):
                continue                      # 伪变形,不填
            turbo_rows.append((rid, w, body, b))
    else:
        turbo_rows = [r for k in groups if k.endswith("→ turbo") for r in groups[k]]
    pro_rows = [] if a.layer_d else groups["F 假复数·ECDICT 误判(pro 给真义)"]
    pseudo = groups["P 伪复数·原形已在库(删除候选)"]
    if a.limit:
        turbo_rows = turbo_rows[:a.limit]; pro_rows = pro_rows[:max(1, a.limit // 20)]
    print(f"\n→ 重译 {len(turbo_rows):,}   pro 给真义 {len(pro_rows):,}   "
          f"伪复数落盘不填 {len(pseudo):,}")

    if not a.run:
        print("\n(未加 --run,不发 API)")
        return

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        res = []; tot_tok = 0
        for tag, rows, sysp, model, comps, hedge, ck in (
            (MODEL_TAG, turbo_rows, SYS, env[MODEL_KEY], cl.batch.chat.completions,
             (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, HEDGE_AFTER), CHUNK),
            ("pro", pro_rows, SYS_FALSEPL, env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, None, 10),
        ):
            if not rows:
                continue
            metas = [rows[j:j + ck] for j in range(0, len(rows), ck)]
            batches = [{str(k): (item(r, kb, info) if tag == "turbo"
                                 else {"word": r[1], "cur": r[2].replace("\n", " ")[:80]})
                        for k, r in enumerate(m, 1)} for m in metas]
            print(f"  → {tag} {len(rows):,} 条 / {len(batches)} 批")
            rr, tk = await S.run_batches(sysp, batches, model, comps, hedge)
            res.append((tag, metas, rr)); tot_tok += tk
        await cl.close()
        return res, tot_tok

    parts, tok = asyncio.run(go())
    tally = Counter(); fixes = []
    for tag, metas, rr in parts:
        fixes += harvest(metas, rr, tally, tag)

    print(f"\n===== token {tok:,} =====")
    for k, v in tally.most_common():
        print(f"  {k:24} {v:>7,}")
    for rid, w, old, new in fixes[:10]:
        print(f"\n  {w}\n    前: {old.replace(chr(10),' / ')[:56]}\n    后: {new.replace(chr(10),' / ')[:72]}")

    if not fixes:
        print("\n无可写入的改写。")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-a1turbo-{tag}.bak"))
    conn = sqlite3.connect(DB)
    if LOG.exists():   # 重跑保护:先把上一轮写回去,避免 before 失真
        for i, ln in enumerate(open(LOG, encoding="utf-8")):
            if i:
                c = ln.rstrip("\n").split("\t")
                conn.execute("UPDATE stardict SET translation=?, qual='fair' WHERE id=?",
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
    # 伪复数清单落盘(只记录,不删 —— 删不删由产品最后拍板)
    with open(PSEUDO, "w", encoding="utf-8") as f:
        f.write("id\tword\tbase\tcur\n")
        for rid, w, body, b in pseudo:
            f.write("\t".join([str(rid), w, b, body.replace("\t", "\\t").replace("\n", "\\n")]) + "\n")
    print(f"\n已重译 {len(fixes):,} 条(qual 已同步),留痕 → {LOG.name};备份 pre-a1turbo-{tag}.bak")
    print(f"伪复数删除候选 {len(pseudo):,} 条 → {PSEUDO.name}(未删,仅落盘)")


if __name__ == "__main__":
    main()
