#!/usr/bin/env python3
"""人工补 550 条「六版皆无释义、两个模型也拿不准」的词。2026-08-03。

═══ 这批是什么 ═══
西语版收词带进来的 2,696 个 no-gloss 词头，经 flash（1,588）、v4-pro（558）之后
剩下 550 条：**473 条 v4-pro 明说"连词根都认不出"，77 条它标 low 我拦下没落库。**
用户 2026-08-03："你先人工过一下 570，能弄你就弄。"

═══ 我的标准 ═══
🔴 **只写我能替它辩护的**。这批词绝大多数是 DRAE 罕用词、古语、拉美方言词，
   没有任何权威源在手，我唯一的凭据是自己的西班牙语知识 —— 那就只写有把握的，
   剩下的留空。**留空比编一个更值钱**（错比缺更伤权威）。
🔴 **不给 v4-pro 的 low 档盖章放行**。逐条看下来它那 77 条里至少四条是错的：
     caletear      它译"品尝，尝试" → 实为（船/车）沿途小港小站停靠（智利，caleta）
     huisachear    它译"砍伐金合欢树" → 实为（墨）做讼棍、无照包揽诉讼
     lipidiar      它译"使脂质化" → 实为（中美）纠缠，烦扰（lipidia＝麻烦）
     descerrumarse 它译"崩塌，塌陷" → 实为（牲口）闪伤肩胯
   这四条我按正确义写进下表；它标 low 但答对的（harbar/jitar/lastar 等）我核过后收下。

`translation_src='manual'` 单独标档 —— 这一批是我写的，出了问题查得到、撤得掉。

用法（在 es/ 目录）：
    python3 fixes/manual_nogloss.py
    python3 fixes/manual_nogloss.py --apply
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sqlite3

import dbtool
import paths

SRC = "manual"

# 词 → 中文释义。逐条为我自己的西语知识负责。
GLOSS = {
    # ── 农事、园艺、畜牧 ──
    "arrodrigonar": "给（葡萄藤）立支柱",
    "cachipodar": "修剪（葡萄藤等）枝条",
    "escamujar": "疏剪（橄榄树）枝条",
    "desurcar": "平掉犁沟，抹平垄沟",
    "desucar": "榨出汁液，抽干汁水",
    "esparvar": "把打谷场上的谷物堆成堆",
    "espinochar": "剥去玉米的苞叶",
    "esfoyar": "（阿斯图里亚斯）剥玉米苞叶",
    "desbecerrar": "给小牛断奶",
    "querochar": "（蜂王、昆虫）产卵",
    "bocezar": "（牲畜）翻动嘴唇",
    "calamorrar": "（公羊）以头相顶",
    "chacolotear": "（马掌松动时）咔嗒作响",
    "asobinarse": "（牲口）跌倒蜷缩，翻不起身",
    "ensobinarse": "（牲口）跌倒蜷缩，翻不起身",
    "descerrumarse": "（牲口）闪伤肩胯",
    "socolar": "（美洲）清除林下灌木，砍除杂树",
    "zocolar": "（厄瓜多尔）清除林下灌木",
    "sorrapear": "铲除地面上的杂草与浮土",
    "layar": "用铁锹翻土",
    "arrejacar": "给（庄稼）中耕松土",
    "derrubiar": "（水流）冲刷侵蚀（岸土）",
    "puntisecar": "（树木）梢头枯死",
    "arromadizar": "使伤风，使患鼻黏膜炎",

    # ── 手艺、工具、材料 ──
    "apomazar": "用浮石打磨",
    "apontocar": "用支柱支撑，加撑",
    "ataluzar": "使成斜坡，做出坡面",
    "escantillar": "按样板划线取尺寸",
    "esconzar": "使成斜角，斜切",
    "jabelgar": "刷白灰，粉刷",
    "infurtir": "缩绒，把呢绒踩压紧实",
    "escurar": "洗去（呢绒的）油脂",
    "espolinar": "织入金银线花纹",
    "sopalancar": "用杠杆撬起",
    "enhastillar": "把箭装入箭筒",
    "atortorar": "用绞索绞紧（缆绳）",
    "arrequintar": "用绳索绞紧，勒紧",
    "estirazar": "反复拉扯，拉长",
    "tazar": "磨损，磨破",
    "escomerse": "逐渐磨损，蚀耗",
    "esclafar": "打碎，压破（蛋等）",
    "estozar": "拧断脖子，摔断颈骨",
    "esturar": "烤焦，烧糊",
    "somarrar": "略微烤焦，燎一下",
    "sobrasar": "用余烬加热，煨",
    "rusentar": "把金属烧至通红",
    "encendrar": "提纯（金属），精炼",
    "estipticar": "使收敛，止血",
    "esfacelarse": "发生坏疽，组织坏死",
    "epitimar": "敷药膏",

    # ── 烹饪、饮食 ──
    "escaldufar": "从锅里舀出多余的汤",
    "lamprean": "",           # 占位，见下方 lamprear
    "lamprear": "用蜜与酒烹制（肉）",
    "empapujar": "强行填喂，硬灌食",
    "empapizar": "把（禽鸟）填食噎住",
    "gazmiar": "偷吃零嘴，馋嘴",
    "lambrucear": "贪嘴，馋食，狼吞虎咽",
    "lambucear": "贪嘴，馋食，狼吞虎咽",
    "lamiscar": "匆匆舔一下",
    "churrupear": "小口啜饮",
    "chuperretear": "反复吮吸",
    "rucar": "咬嚼硬东西（发出响声）",
    "rustrir": "烤脆；嚼得咯吱响",
    "liudar": "（面团）发酵",
    "champurrear": "把（几种饮料）混调；说话夹生混杂",

    # ── 言语、性情、举止 ──
    "harbar": "匆忙草率地做（事）",
    "harbullar": "匆忙草率地做（事）",
    "haronear": "偷懒磨蹭，游手好闲",
    "bigardear": "游手好闲，闲荡度日",
    "viltrotear": "（女子）到处闲逛游荡",
    "candonguear": "戏弄，取笑；躲懒推事",
    "chocarrear": "说粗俗玩笑，插科打诨",
    "refitolear": "多管闲事，好插手",
    "zoncear": "说傻话，做蠢事",
    "zaragatear": "吵闹起哄，胡闹",
    "jonjabar": "花言巧语哄骗，奉承",
    "sonsañar": "模仿嘲弄，学样取笑",
    "oprobiar": "侮辱，凌辱",
    "bocabajear": "（古巴、墨西哥）当众训斥，羞辱",
    "fincharse": "自大，摆架子",
    "hespirse": "自负，摆架子",
    "gallearse": "趾高气扬，逞威风",
    "jimplar": "抽泣，啜泣",
    "ayear": "连声叫苦，唉声叹气",
    "rosigar": "啃咬；唠叨不休",
    "escamonearse": "起疑心，变得戒备",
    "trafulcar": "弄混，颠倒，搞乱",
    "engarbullar": "搞乱，弄得纠缠不清",
    "embolatar": "（哥伦比亚）使纠缠不清，拖延；弄丢",
    "emborrullarse": "争吵，口角",
    "cubiletear": "玩杯子戏法；耍手腕，玩花招",
    "enfullar": "（赌博中）作弊出千",
    "mohatrar": "做虚假买卖以放高利贷",
    "paccionar": "订约，缔结协议",
    "lastar": "替人受过，代人偿付",
    "cusir": "粗针大线地缝，缝得马虎",
    "burrajear": "涂鸦，胡乱涂写",
    "chafarrinar": "涂污，弄脏（画面、纸面）",

    # ── 身体、动作 ──
    "espatarrarse": "叉开双腿（坐倒或摔倒）",
    "despaturrar": "摔得四脚朝天；压扁",
    "despaturrarse": "摔得四脚朝天，四肢摊开",
    "taperujarse": "胡乱裹住脸，蒙头掩面",
    "tapirujarse": "胡乱裹住脸，蒙头掩面",
    "regacear": "撩起（衣裙）掖在腰间",
    "solmenar": "猛力摇撼",
    "guachapear": "踏水弄响；胡乱赶工",
    "chapullar": "踏水弄出声响，戏水",
    "chospar": "（羊羔等）欢蹦乱跳",
    "esguilar": "攀爬，爬上",
    "almadearse": "头晕，恶心",
    "encalamocar": "使晕头转向，弄糊涂",
    "estordir": "使昏眩，打晕",
    "esturdir": "使昏眩，打晕",
    "traslumbrarse": "被强光晃花眼",
    "cedacear": "视力变模糊",
    "ciguatarse": "患雪卡毒鱼中毒；面色蜡黄",
    "fizar": "（毒虫）蜇，叮",
    "tarascar": "（狗）猛咬一口",
    "cintarear": "用剑面拍打",
    "espurriar": "噗地喷出（水），喷洒",
    "rujiar": "洒水",
    "apeldar": "溜走，逃跑",
    "zambucar": "迅速藏起，掖藏",
    "escamotar": "变戏法般藏起；侵吞",
    "sopuntar": "在字下加点（作标记）",
    "arrodear": "绕道，兜圈子",
    "amollentar": "使变软，使柔和",
    "atortujar": "压扁，压瘪",
    "atafagar": "（浓味）熏得人发闷；纠缠不休",
    "entrapajar": "用破布包扎",
    "descalandrajar": "撕成破布条",
    "descarcañalar": "把（鞋后跟）踩塌",
    "desembrozar": "清除杂草杂物",
    "arromanzar": "译成西班牙语，用白话转述",
    "dimir": "摇落（树上的果实）",
    "llapar": "添秤，额外多给一点",
    "jitar": "呕吐；赶出去",
    "hornaguear": "挖掘（煤）；掏挖",
    "jamurar": "舀水，排出积水",
    "lampacear": "用拖把擦洗（甲板）",
    "sorrabar": "剪短（牲畜的）尾巴",
    "apolismar": "（美洲）打伤，挫伤；使萎靡",
    "desmorecerse": "（古巴）笑得或哭得喘不过气",
    "cerrajear": "做锁匠活",
    "jaripear": "（墨西哥）参加骑牛驯马表演",
    "jopear": "（美洲）摇尾巴；吆喝驱赶",
    "enyerbarse": "（土地）长满杂草；（墨西哥）中毒、被下蛊",
    "emborujarse": "结成疙瘩，缠作一团",
    "caletear": "（智利，船只、车辆）沿途小港小站逐个停靠",
    "huisachear": "（墨西哥）做讼棍，无照包揽诉讼",
    "lipidiar": "（中美洲）纠缠，烦扰",
}
GLOSS.pop("lamprean", None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = conn.execute(
        "SELECT id, word FROM dict WHERE is_lemma=1 "
        "AND TRIM(COALESCE(translation,''))='' "
        "AND TRIM(COALESCE(definition,''))='' "
        "AND TRIM(COALESCE(definition_es,''))=''").fetchall()
    conn.close()
    byw = {w: rid for rid, w in rows}

    plan, samples, miss = [], [], []
    for w, zh in GLOSS.items():
        rid = byw.get(w)
        if rid is None:
            miss.append(w)          # 已经被别的批次填了，或拼写对不上 → 不动
            continue
        plan.append((zh, SRC, rid))
        samples.append((w, zh))

    print("■ 人工表 {:,} 条；命中待填行 {:,}；不在待填集里 {:,}".format(
        len(GLOSS), len(plan), len(miss)))
    if miss:
        print("   （不在待填集：%s）" % ", ".join(miss[:12]))
    print("■ 落库后仍留空：{:,}".format(len(rows) - len(plan)))
    dbtool.sample_check(samples, n=16, cols=("词", "我写的中文"))

    if not a.apply:
        print("\n(试算完毕。加 --apply 落库)")
        return
    with dbtool.session("manual-nogloss", expect={"translation": len(plan)}) as s:
        s.executemany(
            "UPDATE dict SET translation=?, translation_src=? WHERE id=?", plan)
    dbtool.align_check()


if __name__ == "__main__":
    main()
