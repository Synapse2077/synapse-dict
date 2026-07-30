#!/usr/bin/env python3
"""判官评测集:人工标签 + 打分器。见对话 2026-07-30。

为什么需要:改 prompt 时用 60 条烟测判精确率,误差条 ±35pp,分不清进步和噪声;
而且我上一轮把测试集里的 reglet/bannerol/缔合分子 写进 prompt 当反例 —— 那是背答案。
→ 把标签固化,以后每改一版自动打分,并把 dev(可以看)和 test(不许看)分开。

标签来源:2026-07-30 对话中逐条人工裁决,依据是英文词义 + 中文标准译法。
  bad    确有缺陷
  ok     没有缺陷(译文可用,即使简短/生僻/格式怪)
  unsure 我也没把握(义项历史争议、罕用词、拉丁学名分类) —— **不计入精确率/召回率**

⚠️ split 字段:dev 允许在调 prompt 时查看和引用;test **不许写进 prompt**,只用于最终验收。
   已被我写进过 prompt 的条目一律标 dev(它们已被污染,不能再当 test)。

用法:
  python3 en/eval_labels.py --build                     # 按 word 匹配库内 id,落 eval_set.json
  python3 en/eval_labels.py --score judge_xxx.jsonl     # 给某次判官输出打分
"""
import argparse, json, sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"
OUT = HERE / "runs/eval_set.json"

# (word, 我的判决, split, 理由)
LABELS = [
    # ---- 确有缺陷 ----
    ("Gell-Mann Amnesia", "bad", "dev", "元描述:'…的同义词',整条无实际词义"),
    ("protozoean", "bad", "dev", "protozoean=原生动物的;原溞幼体是 protozoea,张冠李戴"),
    ("bias-ply tire", "bad", "dev", "标准译法斜交轮胎,'斜网胎'非术语"),
    ("feed processing plant", "bad", "dev", "plant=厂,不是'间'"),
    ("shampooer", "bad", "dev", "洗发员/洗发器,不是[医]按摩师"),
    ("bulldog calf", "bad", "dev", "矮脚犊/斗牛犬样犊牛,不是'斗犬牛病'"),
    ("minimal flight path", "bad", "test", "minimal=最短/最小,不是'最省时'"),
    ("robot psychologist", "bad", "test", "机器人心理学家,译文主宾颠倒"),
    ("hot soarfing", "bad", "test", "词头讹写(scarfing),且'热剥'不对应"),
    ("sodium chloroaurate", "bad", "test", "氯金酸钠,不是'氯化钠金';[机]标签也错"),
    ("optimum final feed temperature", "bad", "test", "漏首字:应为'最佳最终给水温度'"),
    ("bridge washer", "bad", "test", "桥形垫圈;阀桥=valve bridge"),
    ("bottom sloping", "bad", "test", "多一个右括号:'池)底坡度'"),
    ("vastering", "bad", "test", "非英语词,'巨大的'是错译"),
    ("seepproof screen", "bad", "test", "防渗筛/防渗幕,不是止水墙"),
    ("side placement method", "bad", "test", "侧置法;凭空加了'肥料'限定"),
    ("intergatory", "bad", "test", "interrogatory 的讹写"),
    ("streambanks", "bad", "test", "'河岩'是错字"),
    ("single-cycle forced-circulation boiling water", "bad", "test", "single- 整个丢了"),
    ("vertical natural-circulation type shell and tube evaporator", "bad", "test",
     "漏'立'式,且'自然'错成'自燃'"),
    ("kooki", "bad", "test", "川崎和男/故技/神经痛三者互不相关,众包垃圾"),
    ("gintiss", "bad", "dev", "空壳:只说'是谁的复数',无词义"),
    ("geomagnetic interference", "bad", "dev", "译文栏放英文'= geomagnetic noise',无中文"),
    ("merguss", "bad", "dev", "空壳 + 拉丁属名机械加 s"),
    ("upper center", "bad", "test", "上止点=top dead center,张冠李戴"),
    ("cat-foots", "bad", "dev", "空壳:只说是第三人称单数"),
    ("aa. ilic?", "bad", "dev", "词头含问号,坏数据"),
    ("web service architecture", "bad", "test", "web service≠网站服务,应为Web服务架构"),
    ("francoa ramosas", "bad", "dev", "空壳 + 学名伪复数"),
    ("canonical disjunctive form", "bad", "test", "应为析取范式;'逻辑和'是 logical sum 误读"),
    ("disordered scattering", "bad", "dev", "散射是物理现象,[医]标签挂错"),
    ("electrofining precipitator", "bad", "dev", "electrofining=电解精炼,译文不对应"),
    ("graty", "bad", "dev", "'磨磨挤'读不通"),
    ("thylakoid membranes", "bad", "dev", "后半截'层的类囊膜'是残片"),
    ("hatefuller", "bad", "test", "是 hateful 的比较级,只给了原级义"),
    ("schpritzers", "bad", "dev", "空壳:复数形式 + 异写形式,无词义"),
    ("underspeaking", "bad", "dev", "空壳:只说现在分词/动名词形式"),

    # ---- 没有缺陷(重点:简短/生僻/格式怪都算 ok) ----
    ("locally ringed space", "ok", "dev", "局部戴环空间是旧译但可用;mini 提的'环积'是 wreath product"),
    ("Farbenidox", "ok", "dev", "Farbenindex 讹写,血色指数对应正确"),
    ("8-bits", "ok", "dev", "既给了'八位'又说明复数,正常"),
    ("made hay while the sun shone", "ok", "dev", "习语义正确,习语确实有过去式"),
    ("reflets", "ok", "dev", "英语借词 reflet 专指陶瓷虹彩光泽,原译准确"),
    ("Kains Flat", "ok", "dev", "确在新南威尔士州;mini 改成昆士兰是编造"),
    ("mistakeability", "ok", "dev", "释义与异写说明都成立"),
    ("génocidaires", "ok", "dev", "复数 + 异写形式两条陈述都对"),
    ("knocks on the door of", "ok", "dev", "确实是三单形式"),
    ("physical relief", "ok", "test", "地理语境下 relief=地形起伏,译文正确;pro 判错了"),
    ("ncdads", "ok", "test", "缩写全称 + 复数说明,均正确"),
    ("joyo", "ok", "test", "卓越网是该专名的通行译名"),
    ("dies the way one lived", "ok", "test", "是三单形式,且给了习语义"),
    ("reeks", "ok", "test", "名词复数与动词三单义都给全了"),
    ("bellisses", "ok", "dev", "给了'贝利斯'实义,不是空壳"),
    ("clanculus gemmulifer", "ok", "dev", "正规拉丁双名,词头没坏"),
    ("homogenates", "ok", "dev", "有实义'[组织]匀浆';形态说明在前只是格式"),
    ("inkstones", "ok", "dev", "砚正确;水绿矾(melanterite)在矿物学中亦称 inkstone"),
    ("mini-micro software", "ok", "test", "'软体'是台湾用法,可接受"),
    ("reglet", "ok", "dev", "译文完整正确,简短不是缺陷"),
    ("sphinxes", "ok", "dev", "有实义'狮身人面巨象',不是空壳"),
    ("positive displacement pumps", "ok", "dev", "有实义'容积式泵'"),
    ("Mediterranean shearwaters", "ok", "dev", "有实义'地中海鹱'"),
    ("associated molecule", "ok", "dev", "缔合分子确为化学术语,[化]正确"),
    ("bannerol", "ok", "dev", "名词标 n. 无误"),
    ("channel-select signal", "ok", "dev", "通道选择信号完整正确"),
    ("critical section", "ok", "dev", "临界段确为计算机并发术语,[计]正确"),
    ("encrusted", "ok", "dev", "与 infl 一致,且 encrusted 可作形容词"),

    # ---- 我也没把握,不计分 ----
    ("filament purolyzer", "unsure", "dev", "词头讹写(pyrolyzer),但译文对应正确"),
    ("arctic meadow", "unsure", "dev", "北极草甸更标准,'极地湿草原'多了'湿'"),
    ("taxation payment", "unsure", "dev", "纳税/税款之别过细"),
    ("INNERVAITON", "unsure", "test", "词头拼错但译文正确,算不算缺陷取决于口径"),
    ("lynx-stone", "unsure", "test", "史上 lyncurium 曾等同琥珀"),
    ("mousefalls", "unsure", "test", "mousefall 是否有捕鼠器义存疑"),
    ("ctd.", "unsure", "test", "医学俚语义正确,但漏了常见的 continued"),
    ("double-actions", "unsure", "test", "复数与 adj. 混列,程度轻"),
    ("wissed", "unsure", "test", "古语形态存疑"),
    ("matrix number", "unsure", "test", "母盘编号/矩阵编号,语境依赖"),
    ("adokoes", "unsure", "test", "专名伪复数,程度轻"),
    ("ayielded", "unsure", "test", "该词是否存在存疑"),
    ("benswine", "unsure", "dev", "非英语词的无意义音译,算 H 还是 W 不清"),
    ("fullought", "unsure", "dev", "非英语词"),
    ("guilty-conscious", "unsure", "dev", "词义对,[法]标签是否恰当存疑"),
    ("on the hustle", "unsure", "dev", "'靠街头骗钱为生'方向对,程度存疑"),
    ("symbolization or stock number", "unsure", "dev", "'物料之编号'漏了 symbolization"),
    ("us division", "unsure", "dev", "'美国区球队'来源不明"),
]


def build():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    byword = {}
    for rid, w, t in conn.execute("SELECT id, word, translation FROM stardict"):
        k = (w or "").strip().lower()
        if k not in byword:
            byword[k] = (rid, w, t)
    conn.close()
    out = []; miss = []
    for w, v, sp, why in LABELS:
        hit = byword.get(w.strip().lower())
        if not hit:
            miss.append(w); continue
        out.append(dict(id=hit[0], word=hit[1], zh=hit[2], label=v, split=sp, why=why))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    c = Counter((r["label"], r["split"]) for r in out)
    print(f"评测集 {len(out)} 条 → {OUT.name}")
    for sp in ("dev", "test"):
        print(f"  {sp:5} bad {c[('bad',sp)]:>3}  ok {c[('ok',sp)]:>3}  unsure {c[('unsure',sp)]:>3}")
    if miss:
        print(f"  ⚠️ 库内未匹配到 {len(miss)} 条: {miss}")


def score(path, split=None, with_shell=False):
    """with_shell:把 buckets.is_shell() 的确定性判定 OR 进来 —— E 类已交给本地正则,
    只评模型等于低估真实流水线。"""
    gold = {r["id"]: r for r in json.load(open(OUT, encoding="utf-8"))}
    pred = {}
    for ln in open(HERE / path, encoding="utf-8"):
        r = json.loads(ln)
        if not r.get("_meta"):
            pred[r["id"]] = r
    cov = [i for i in gold if i in pred]
    use = [i for i in cov if gold[i]["label"] != "unsure"
           and (split is None or gold[i]["split"] == split)]
    if with_shell:
        import buckets as B
        for i in cov:
            if B.is_shell((gold[i]["zh"] or "").strip()):
                pred[i] = dict(pred[i]); pred[i]["v"] = "bad"
                pred[i]["codes"] = (pred[i].get("codes") or "") + "E*"
    tp = sum(1 for i in use if gold[i]["label"] == "bad" and pred[i]["v"] == "bad")
    fp = sum(1 for i in use if gold[i]["label"] == "ok" and pred[i]["v"] == "bad")
    fn = sum(1 for i in use if gold[i]["label"] == "bad" and pred[i]["v"] != "bad")
    tn = sum(1 for i in use if gold[i]["label"] == "ok" and pred[i]["v"] != "bad")
    uns = sum(1 for i in cov if gold[i]["label"] == "unsure")
    print(f"\n=== {path}  split={split or '全部'} ===")
    print(f"  评测集覆盖 {len(cov)}/{len(gold)};计分 {len(use)} 条(另有 {uns} 条 unsure 不计)")
    print(f"  TP {tp}  FP {fp}  FN {fn}  TN {tn}")
    print(f"  精确率 {100*tp/max(tp+fp,1):5.1f}%   召回率 {100*tp/max(tp+fn,1):5.1f}%")
    if fp:
        print("  误报(标了但其实没问题):")
        for i in use:
            if gold[i]["label"] == "ok" and pred[i]["v"] == "bad":
                print(f"    {gold[i]['word'][:26]:28} 码={pred[i].get('codes','')}  ← {gold[i]['why'][:44]}")
    if fn:
        print("  漏判(有缺陷但没标):")
        for i in use:
            if gold[i]["label"] == "bad" and pred[i]["v"] != "bad":
                print(f"    {gold[i]['word'][:26]:28} ← {gold[i]['why'][:50]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--score")
    ap.add_argument("--split", choices=["dev", "test"])
    ap.add_argument("--with-shell", action="store_true",
                    help="OR 上本地 is_shell() —— 评测真实流水线而非孤立模型")
    a = ap.parse_args()
    if a.build:
        build()
    if a.score:
        score(a.score, a.split, a.with_shell)
