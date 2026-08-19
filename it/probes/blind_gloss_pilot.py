#!/usr/bin/env python3
"""盲测：模型只看词形能不能推出词义？2026-08-17。

═══ 为什么要有这把尺子 ═══
库里有 **3,580 个词头一条释义都没有**（法语版孤儿原形 2,896 + 意语版占位符 684），
而它们**任何源都没有释义** —— 英文版 0、意语版 0、希腊/土耳其/中文版 0。
要补就只能让模型按构词法推。

🔴 问题：没有真值 ⇒ 建不起闸 ⇒ 跑完也不知道对不对。
   这正是 2026-08-15 烧掉 418 万 token 那次的形状（`control-must-cover-every-output-field`）。

⇒ 解法：**拿我们已经有释义的词做盲测**。给模型同样的输入（只有词形+词性），
  把它的答案与库里的真释义比 —— 这就把"能不能做"变成一个可测的数字。

═══ 三组题，混在同一批里，模型分不出来 ═══
    正控 200  C2 生僻动词，库里有中文释义（与目标词同类：低频、构词复杂）
    负控  30  我按意语构词法编的**不存在的词**
              → 模型若给高置信度释义，说明 `c` 这个字段是废的，不能当过滤器
    目标  20  真正要补的 A 组词（不参与打分，只用来看输出长什么样）

⚠️ 负控必须**真的不存在**：逐个对 1.5M 词形的 `dict`、英文版/意语版/法语版 dump 查过。
   `wordfreq-ruler-traps` 记过"词缀被静默剥掉再查"的坑，这里只做精确匹配，不做归一。

⚠️ 打分**我自己逐条读**，不请判官。`llm-as-evaluator-discipline` 第⑤条：
   谁写的不能由谁判；第①条：判官同批数据能报 5.3%–17%。200 条读得完。

用法（在 it/ 目录下）：
    python3 probes/blind_gloss_pilot.py --build       # 出题（含负控查重），不花钱
    python3 probes/blind_gloss_pilot.py --run         # 关思考跑一遍
    python3 probes/blind_gloss_pilot.py --run --think # 开思考再跑一遍
    python3 probes/blind_gloss_pilot.py --grade       # 打印对照表，我逐条读
"""
import argparse
import asyncio
import gzip
import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import ds_batch   # noqa: E402
import paths      # noqa: E402

WORK = paths.DATA / "work" / "it"
QUIZ = WORK / "blind_gloss_quiz.json"
OUT = {False: WORK / "blind_gloss_nothink.jsonl", True: WORK / "blind_gloss_think.jsonl"}
OUT_DOUBAO = WORK / "blind_gloss_doubao_pro.jsonl"

SYS = """你是意大利语词典编纂助手。下面每一行是一个意大利语词条，只给出词形和词性，**没有任何释义来源**。
请根据意大利语构词法与词源推断它的意思，输出简明中文释义。

规则：
1. **宁缺毋错**。推不出来就把 c 设为 0、zh 留空。词典里一条编造的释义比一个空白伤害大得多。
2. zh 写中文释义本身，不写词性说明、不写"意为"之类的话。动词写动作义。
3. m 写你的构词依据（如 `auto- + annullare`）；没有依据就留空字符串。
4. c 是把握度：2 = 构词透明、可确定；1 = 较可能；0 = 不知道。
5. **输入里可能混有并不存在的词**。遇到推不出、也不像真词的，必须 c=0、zh 留空。
6. 严格只返回 JSON 对象：{"标识号": {"zh": "...", "m": "...", "c": 2}, ...}
   标识号是每行的 n，**原样回传，不是序号**。"""

# 负控：按意语构词法编的假词。词根/后缀都合法，组合不存在。--build 会逐个查重。
FAKE = [
    "sgrembolare", "arrufficare", "intamellire", "disbrancolare", "sfrondigliare",
    "abbrusticare", "ritramollire", "scomponellare", "ingarbuzzare", "trasfoltire",
    "sbiaccolare", "rimpastigliare", "annuvolicare", "descrepolare", "infiammellire",
    "sgottolare", "arrampellire", "conturbicare", "spennellicare", "immalvire",
    "strabocciare", "rinvergolare", "dislaccicare", "abbrancolire", "sfiammicare",
    "intorbellire", "raggrinzolare", "svaporicchiare", "commistolare", "prefondellire",
]


def build():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    f = lambda x: format(x, ",")

    # —— 负控查重：必须在库里、在三个 dump 里都查不到 ——
    have = {w for (w,) in con.execute("SELECT word FROM dict")}
    bad = sorted(w for w in FAKE if w in have)
    dumps = ["kaikki.org-dictionary-Italian.jsonl", "itwiktionary.jsonl.gz",
             "kaikki.org-frwiktionary-Italian.jsonl.gz"]
    for fn in dumps:
        p = paths.DATA / "dumps" / fn
        op = gzip.open if fn.endswith(".gz") else open
        with op(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    w = json.loads(line).get("word")
                except Exception:
                    continue
                if w in FAKE:
                    bad.append(w)
    bad = sorted(set(bad))
    print("■ 负控查重：%d 个假词里 %d 个其实存在" % (len(FAKE), len(bad)))
    if bad:
        print("   🔴 %s —— 换掉再跑" % ", ".join(bad))
        return 1
    print("   ✅ 全部确认不存在（对 dict %s 词形 + 3 个 dump 精确匹配）" % f(len(have)))

    # —— 正控：C2 生僻动词，**必须与目标词同形状** ——
    #
    # 🔴 第一版没加形状过滤，抽出来一半是 `abbattendole` `accampandomi` 这类**代词合体形**
    #    —— 拆开就懂，模型 c=2 全中，而目标 A 组是 `accintolare` 这种光杆生僻不定式。
    #    拿容易的题当尺子，量出来的准确率没法外推到要做的活。
    #    （同一个错 2026-08-16 犯过：pilot 1/3 抽到模板产出，读了白读。）
    # ⇒ 两道过滤：① 词形是裸不定式（-are/-ere/-ire 结尾、无空格、无合体尾巴）
    #             ② 它自己不是任何词的变形（`inflection` 里查不到）
    pos_rows = con.execute("""
        SELECT d.id, d.word, g.text FROM dict d
        JOIN sense s ON s.word_id=d.id AND COALESCE(s.hidden,0)=0 AND s.pos='v'
        JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' AND g.seq=0
        WHERE d.is_lemma=1 AND d.pos='v' AND d.level='C2'
          AND trim(COALESCE(g.text,'')) <> ''
          AND d.word NOT LIKE '% %'
          AND (d.word LIKE '%are' OR d.word LIKE '%ere' OR d.word LIKE '%ire')
          AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id = d.id)
    """).fetchall()
    print("■ 正控题库（裸不定式、非变形、有中文）%s 个" % f(len(pos_rows)))
    random.seed(20260817)
    pos_rows = random.sample(pos_rows, 200)

    # —— 目标：真正要补的 A 组词，只看输出形状，不打分 ——
    tgt = con.execute("""
        SELECT d.id, d.word FROM dict d JOIN entry e ON e.word_id=d.id
        WHERE e.src='fr-edition' AND d.pos='v'
          AND NOT EXISTS(SELECT 1 FROM sense_src x WHERE x.word_id=d.id)
        LIMIT 400
    """).fetchall()
    tgt = random.sample(tgt, 20)

    quiz = []
    for wid, w, zh in pos_rows:
        quiz.append({"n": wid, "w": w, "pos": "v", "_kind": "正控", "_truth": zh})
    for i, w in enumerate(FAKE):
        quiz.append({"n": 900000 + i, "w": w, "pos": "v", "_kind": "负控", "_truth": ""})
    for wid, w in tgt:
        quiz.append({"n": wid, "w": w, "pos": "v", "_kind": "目标", "_truth": ""})
    random.shuffle(quiz)          # 🔴 打散：三组必须混在同一批里
    QUIZ.parent.mkdir(parents=True, exist_ok=True)
    QUIZ.write_text(json.dumps(quiz, ensure_ascii=False, indent=1), encoding="utf-8")
    print("■ 出题 %d 条 → %s" % (len(quiz), QUIZ))
    print("   %s" % dict(Counter(q["_kind"] for q in quiz)))
    return 0


def run(think):
    quiz = json.loads(QUIZ.read_text(encoding="utf-8"))
    B = 40
    batches, meta = [], []
    for i in range(0, len(quiz), B):
        chunk = quiz[i:i + B]
        batches.append([{"n": q["n"], "w": q["w"], "pos": q["pos"]} for q in chunk])
        meta.append([(str(q["n"]), q["n"]) for q in chunk])
    print("■ %d 条 / %d 批 / 思考 %s" % (len(quiz), len(batches), "enabled" if think else "disabled"))
    tok = asyncio.run(ds_batch.run(SYS, batches, meta, OUT[think], mode="flash", conc=8,
                                   every=2, thinking="enabled" if think else "disabled"))
    print("■ token %s" % format(tok, ","))
    return 0


def run_doubao():
    """豆包 seed-2.1 pro（online，关思考）跑同一批题。

    🔴 **用户 2026-08-17 主动点名**才跑这一次。豆包在本项目是硬拦截状态
       （`ark_batch.DOUBAO_DISABLED`，起因见那个文件的注释：我烧掉 418 万作废
       token 导致用户欠费）。这里显式传 `allow_doubao=True` 放行，**只此一次**，
       不要把它变成默认路径。

    ⚠️ 必须与 flash 用**同一个 SYS、同一个 payload 形状、同一批题目** ——
       否则比的是我的两套提示，不是两家模型（`prompt-beats-model-choice`）。
    ⇒ 题目从已判读过的 200 条正控里取 100 条（种子固定），加全部 30 条负控。
    """
    import ark_batch
    quiz = json.loads(QUIZ.read_text(encoding="utf-8"))
    pos = [q for q in quiz if q["_kind"] == "正控"]
    neg = [q for q in quiz if q["_kind"] == "负控"]
    random.seed(100)
    sub = random.sample(pos, 100) + neg
    random.shuffle(sub)
    B = 40
    batches, meta = [], []
    for i in range(0, len(sub), B):
        chunk = sub[i:i + B]
        batches.append([{"n": q["n"], "w": q["w"], "pos": q["pos"]} for q in chunk])
        meta.append([(str(q["n"]), q["n"]) for q in chunk])
    print("■ %d 条（正控 100 + 负控 30）/ %d 批 / 豆包 pro online 关思考"
          % (len(sub), len(batches)))
    tok = asyncio.run(ark_batch.run(SYS, batches, meta, OUT_DOUBAO, mode="online",
                                    conc=6, every=1, allow_doubao=True))
    print("■ token %s" % format(tok, ","))
    return 0


def grade():
    quiz = {q["n"]: q for q in json.loads(QUIZ.read_text(encoding="utf-8"))}
    for think in (False, True):
        p = OUT[think]
        if not p.exists():
            print("\n（%s 还没跑）" % ("开思考" if think else "关思考"))
            continue
        ans = {}
        for line in p.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            ans[r["id"]] = r
        print("\n" + "═" * 78)
        print("═══ %s —— 回收 %d / %d 条" % ("开思考" if think else "关思考", len(ans), len(quiz)))
        st = Counter()
        for n, q in quiz.items():
            a = ans.get(n) or {}
            c = a.get("c")
            st[(q["_kind"], "c=%s" % c)] += 1
        for k in sorted(st, key=lambda x: (x[0], str(x[1]))):
            print("   %-6s %-8s %s" % (k[0], k[1], st[k]))
        # 🔴 负控是判据能不能用的关键：假词上给了 c>0 就说明 c 不可信
        fk = [(quiz[n]["w"], a.get("c"), a.get("zh"), a.get("m"))
              for n, a in ans.items() if quiz.get(n, {}).get("_kind") == "负控"]
        wrong = [x for x in fk if x[1] and x[2]]
        print("\n   🔴 负控：%d/%d 个假词被给了释义" % (len(wrong), len(fk)))
        for w, c, zh, m in wrong[:12]:
            print("      %-20s c=%s  %s   [%s]" % (w, c, zh, (m or "")[:32]))
        print("\n   ── 正控对照（我逐条读）──")
        rows = [(quiz[n]["w"], a.get("c"), a.get("zh") or "", quiz[n]["_truth"], a.get("m") or "")
                for n, a in ans.items() if quiz.get(n, {}).get("_kind") == "正控"]
        rows.sort(key=lambda r: (-(r[1] or 0), r[0]))
        for w, c, zh, truth, m in rows:
            print("   %-20s c=%s  模型:%-26s 真值:%-30s %s"
                  % (w[:20], c, zh[:26], truth[:30], m[:26]))
        print("\n   ── 目标组输出长什么样 ──")
        for n, a in list(ans.items()):
            if quiz.get(n, {}).get("_kind") == "目标":
                print("   %-20s c=%s  %-24s [%s]"
                      % (quiz[n]["w"][:20], a.get("c"), (a.get("zh") or "")[:24],
                         (a.get("m") or "")[:30]))
    return 0


def main():
    ap = argparse.ArgumentParser()
    for f in ("build", "run", "grade", "think", "doubao"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    if a.build:
        return build()
    if a.doubao:
        return run_doubao()
    if a.run:
        return run(a.think)
    if a.grade:
        return grade()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
