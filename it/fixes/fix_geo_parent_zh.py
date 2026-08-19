#!/usr/bin/env python3
"""地名释义里母地名没音译、拉丁字母直接进页面。2026-08-16。

═══ 用户看到的是这个 ═══
    Bode          格雷索内圣让的博德村（Gressoney-Saint-Jean的村庄）
    Bioley        伊西梅的比奥莱（Issime的村庄）
    Africo Nuovo  阿夫里科新村（意大利卡拉布里亚大区，Africo的村庄）

G 层 5,904 条里 **1,583 条（26.8%）**中文里还留着拉丁字母。同一族里另外
4,321 条却是好的（`Guichet` →「吉凯（尚巴夫的村庄）」）—— 一套数据两种样子。

═══ 根因 ═══
`geo_zh.compose()` 的母地名优先取库里已有的中文，取不到就**退化成原文**。
取不到的原因有三个，全是可以确定性解决的：
  ① `parse()` 抠出来的 parent 带着法语从句尾巴 ——
     `Sarre, situé dans la zone Ouest de la ville` / `la commune italienne de Pessina Cremonese`
     判据同今天 `finish_it_defs.subentry`：**逗号后是同位语，不是名字的一部分**。
  ② 查库时大小写不敏感 ⇒ `Africo`（卡拉布里亚市镇）命中了 `africo`「非洲的」。
     🔴 这不是"查不到"，是**查到了错的**，比查不到更危险。
     ⇒ 大小写敏感 + 只认 `pos='name'` 的义项 + 中文里不许再有拉丁字母。
  ③ 法语用自己的地名外来形（`Aoste`/`Agrigente`），库里是意语形 ——
     `geo_zh` 里的 `PROV_ZH`/`REGION_ZH` 两张表本来就是按法语形建的，接上就行。

═══ 顺带修：词头音译被污染 ═══
`fix_geo_zh` 的 prompt 写死了「音译不许带『意大利』『村庄』『省』这类信息」，
但仍有一批把母地名塞进了音译字段：`Bioley` →「**伊西梅的**比奥莱」。
母地名的中文现在已知，可以确定性地把这个前缀剥掉。

═══ 覆盖 ═══
    ✅ 确定性（库内查表 + 两张现成映射表）  132 个母地名 → 1,533 条
    ✅ 逐条判、写在 BY_HAND                9 个母地名 →    50 条
    ⇒ 拉丁字母清零，一个都不靠模型猜。

用法（在 it/ 目录下）：
    python3 fixes/fix_geo_parent_zh.py
    python3 fixes/fix_geo_parent_zh.py --apply
    python3 fixes/fix_geo_parent_zh.py --verify
    python3 fixes/fix_geo_parent_zh.py --mutate
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import ds_batch  # noqa: E402
import paths     # noqa: E402
import translate_it_defs as T   # noqa: E402  复用它的可续传跑批器
from geo_zh import PROV_ZH, REGION_ZH, compose, parse   # noqa: E402

OUT = paths.WORK / "geo_head_retranslit.jsonl"

# 🔴 与 `fix_geo_zh.SYS` 的唯一差别：**不喂法语原文**。
#    那一版把法语句子当「仅供辨别是哪个地方」传进去，母地名就从这儿漏进了音译 ——
#    模型看到 `Hameau de Acri` 就把 `Cantinella` 写成了「阿克里」（19 条），
#    或者写成「阿克里皮耶特拉莫雷拉」「伊西梅的比奥莱」（母地名粘在前面，82+ 条）。
#    音译是**纯语音转写**，除了词形本身不需要任何上下文。给了上下文就是给了污染源。
SYS = """你的唯一任务是把地名转写成中文音译。

规则：
1. 只输出这个名字本身的音译，不加任何说明。`Villa Fiore` → `维拉菲奥雷`
2. 🔴 输入里只有一个名字。**不要**输出任何其它地名，也不要加"村""镇""意大利"这类词。
3. 已有通行中译名的用通行名（`Firenze` → `佛罗伦萨`）
4. 句末不加标点
5. 名字里的 `di` `del` `della` `d'` 按意语习惯音译进去
   （`Acquaviva d'Isernia` → `阿夸维瓦迪塞尔尼亚`）
6. 法语式拼写按其在意大利当地的读法音译（`Rhêmes-Saint-Georges` → `雷姆圣乔治`）

输入是 JSON 数组，每项有 `id`、`word`。
输出**只有** JSON 数组，每项 {"id": 原样, "zh": "音译"}。不要围栏、不要解释。"""

TAG = "+fix:parent-zh"
LAT = re.compile(r"[A-Za-z]")
PAREN = re.compile(r"[（(][^）)]*[）)]")
# 法语描述前缀：`la commune italienne de X` / `l'ancienne commune de X` / `localité italienne de X`
LEAD = re.compile(r"^(?:la\s+|l['’])?(?:commune\s+italienne\s+de\s+|ancienne\s+commune\s+de\s+"
                  r"|localité\s+italienne\s+de\s+|commune\s+de\s+)", re.I)

# 库里和两张表都没有的 9 个母地名，逐个查过写在这里（`geo_zh`：没核过的绝不猜）。
BY_HAND = {
    "Archi": "阿尔基",                    # 基耶蒂省，阿布鲁佐
    "Atri": "阿特里",                     # 泰拉莫省，阿布鲁佐
    "Zone": "佐内",                       # 布雷西亚省，伦巴第
    "Pessina Cremonese": "佩西纳克雷莫内塞",  # 克雷莫纳省，伦巴第
    "Ardea": "阿尔代亚",                   # 罗马首都广域市，拉齐奥
    "Bolognano": "博洛尼亚诺",              # 佩斯卡拉省，阿布鲁佐
    "Marciana": "马尔恰纳",                 # 利沃诺省，厄尔巴岛
    "Agnadel": "阿尼亚德洛",                # 法语形；意语 Agnadello，克雷莫纳省
    "Voerendaal": "福伦达尔",               # 🔴 荷兰林堡省 —— 源头把它当意大利地名收了
    # 这三个词条在库里只有**描述**没有音译（`Arsita`→「意大利阿布鲁佐大区的城镇」），
    # 描述被整串当成了名字塞进括号：「…（意大利阿布鲁佐大区，意大利阿布鲁佐大区的城镇的村庄）」
    "Arsita": "阿尔西塔",                   # 泰拉莫省，阿布鲁佐
    "Arielli": "阿列利",                    # 基耶蒂省，阿布鲁佐
}

# 母地名的中文里出现这些形状 ⇒ 拿到的是**对某地的描述**，不是地名本身。
# `La Salle` 在库里第一条名义项是「圣罗曼德科迪耶尔的地区」（法国那个 La Salle），
# 第二、三条才是「拉萨勒」。⇒ 跳过带「的」的候选，往下取。
DESC_PARENT = re.compile(r"(?:的地区|的城镇|的意大利城镇|大区的城镇)的村庄")


def clean_parent(p):
    """母地名：去法语描述前缀 → 逗号/括号处截断 → 「X et Y」取第一个。"""
    p = LEAD.sub("", (p or "").strip())
    p = re.split(r"\s*[,(（]", p)[0].strip()
    p = re.split(r"\s+et\s+", p)[0].strip()
    return p.rstrip(".;")


def zh_lookup(con):
    """→ 函数 名字 → 中文音译。大小写敏感、只认专名义项、中文里不许有拉丁字母。"""
    cache = {}

    def f(w):
        if w in cache:
            return cache[w]
        out = BY_HAND.get(w)
        if out is None:
            for (t,) in con.execute(
                    "SELECT g.text FROM dict d JOIN sense s ON s.word_id=d.id "
                    "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' AND g.seq=0 "
                    "WHERE d.word=? AND COALESCE(s.hidden,0)=0 "
                    "AND COALESCE(s.pos,'')='name' ORDER BY s.rank", (w,)):
                # ⚠️ 母地名的中文里，描述有两种挂法：括号「阿杰罗拉（…省的城镇）」
                #    和**中文逗号**「阿古利亚诺，意大利马尔凯大区安科纳省市镇」。
                #    第一版只剥括号，逗号那种整串嵌了进去，出来
                #    「…阿古利亚诺，意大利马尔凯大区安科纳省市镇的村庄」。两种都要剥。
                bare = PAREN.sub("", t).strip().strip("，,")
                bare = re.split(r"[，,]", bare)[0].strip()
                # 🔴 地名的中文音译里不会有「的」——「X的地区」是对**另一个**地方的描述。
                if bare and "的" not in bare and not LAT.search(bare):
                    out = bare
                    break
        out = out or PROV_ZH.get(w) or REGION_ZH.get(w)
        cache[w] = out
        return out
    return f


def strip_parent_prefix(head, parent_zh):
    """词头音译被污染：「伊西梅的比奥莱」→「比奥莱」。母地名已知才敢剥。"""
    if not parent_zh:
        return head
    m = re.match(r"^%s(?:村|市|镇)?的(.+)$" % re.escape(parent_zh), head)
    return m.group(1) if m else head


def redo_list(con):
    """要重做音译的词头：中文里带拉丁字母的那 1,583 条所在词形。"""
    out, seen = [], set()
    for w, sid, zh in con.execute(
            "SELECT d.word, g.sense_id, g.text FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "WHERE g.lang='zh' AND g.seq=0 AND COALESCE(s.hidden,0)=0 "
            "AND g.src LIKE '%translit%'"):
        if LAT.search(zh) and w not in seen:
            seen.add(w)
            out.append({"id": sid, "word": w})
    return out


def load_translit():
    """→ {sense_id: 新音译}；只收过闸的。闸在这里而不在事后，是因为
    「模型把母地名写进音译」正是本步要消灭的病，不能靠它自己不犯。"""
    got = {}
    if not OUT.exists():
        return got
    import json
    for line in OUT.open(encoding="utf-8"):     # 每行一个 {"id":…, "zh":…}
        try:
            x = json.loads(line)
            zh = (x.get("zh") or "").strip().rstrip("。.,，;；")
            if zh and not LAT.search(zh) and len(zh) <= 16:
                got[int(x["id"])] = zh
        except Exception:
            continue
    return got


def plan(con):
    zh_of = zh_lookup(con)
    fresh = load_translit()
    # 本轮刚音译出来的名字也能当母地名用 —— `Soleil` 的母地名就叫 Soleil，
    # 库里没有这个专名义项，但我们这一轮正好把它音译成了「索莱伊」。
    by_word = {}
    for it in redo_list(con):
        z = fresh.get(it["id"])
        if z:
            by_word.setdefault(it["word"], z)
    rows, st = [], Counter()
    for w, sid, zh, fr, srcv in con.execute(
            "SELECT d.word, g.sense_id, g.text, "
            "(SELECT text FROM sense_src WHERE sense_id=g.sense_id AND src='fr-edition'), g.src "
            "FROM sense_gloss g JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "WHERE g.lang='zh' AND g.seq=0 AND COALESCE(s.hidden,0)=0 "
            "AND g.src LIKE '%translit%'"):
        # 本步改过的行也要重算 —— 判据自己修过两轮，改过的行必须跟着重算，
        # 否则「第一版判据的产物」会永远留在库里（`replay-scripts-undo-fixes` 的反面）。
        if not (LAT.search(zh) or TAG in (srcv or "") or DESC_PARENT.search(zh)):
            st["中文干净、也不是本步改的"] += 1
            continue
        info = parse(fr or "")
        if not info or info["kind"] != "hameau":
            st["🔴 不是村庄句式，本步不管"] += 1
            continue
        p = clean_parent(info.get("parent"))
        # 🔴 源头有自指的：`Soleil` 的法语释义是 `Hameau de Soleil.`（说它是自己的村庄）。
        #    一个地方不可能是自己的下属村 ⇒ 这个母地名不携带信息，丢掉，
        #    `compose` 会退化成「索莱伊（村庄）」。
        if p and p.lower() == w.lower():
            info = dict(info, parent="")
            p = ""
        pz = (zh_of(p) or by_word.get(p)) if p else ""
        if p and not pz:
            st["🔴 母地名查不到中文（不猜）：%s" % p] += 1
            continue
        head = fresh.get(sid)
        if head:
            # 🔴 重做的音译也要过闸：不许等于母地名、不许以母地名开头
            #    （`Cantinella`→「阿克里」19 条、`Pietramorella`→「阿克里皮耶特拉莫雷拉」
            #      就是上一版把法语原文当上下文喂进去的后果）
            if pz and (head == pz or head.startswith(pz)):
                st["🔴 重做的音译仍等于/以母地名开头，弃用"] += 1
                head = None
        if not head:
            head = strip_parent_prefix((zh.split("（", 1) + [""])[0].strip(), pz)
            st["（沿用旧音译）"] += 1
        if LAT.search(head) or (pz and head == pz):
            st["🔴 词头音译不可用（带拉丁字母或就是母地名）"] += 1
            continue
        new = compose(info, head, pz)
        if new and new != zh:
            rows.append((sid, w, zh, new))
            st["✅ 可修"] += 1
        else:
            st["重算结果与原值相同"] += 1
    return rows, st


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    latin = [(w, t) for w, t in con.execute(
        "SELECT d.word, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
        "JOIN dict d ON d.id=s.word_id WHERE g.lang='zh' AND g.seq=0 "
        "AND COALESCE(s.hidden,0)=0 AND g.src LIKE '%translit%'") if LAT.search(t)]
    rows, _st = plan(con)
    checks = [
        ("🔴 地名中文里不许再有拉丁字母", len(latin), 0),
        ("🔴 没有还能修却没修的", len(rows), 0),
        ("🔴 改过的行必须仍是「音译（…）」形状",
         sum(1 for (t,) in con.execute(
             "SELECT text FROM sense_gloss WHERE src LIKE ?", ("%" + TAG,))
             if not re.match(r"^[^（(]+（[^）)]+）$", t)), 0),
        ("🔴 词头音译里不许再含母地名前缀",
         sum(1 for t, in con.execute(
             "SELECT text FROM sense_gloss WHERE src LIKE ?", ("%" + TAG,))
             if re.match(r"^.+?的.+?（", t) and t.split("（")[0].endswith(("村的", "市的", "镇的"))), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-40s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    for w, t in latin[:6]:
        print("     ⚠️ %-18s %s" % (w[:18], t[:60]))
    return ok


def mutate(con):
    """判据必须真能逮住 —— 尤其是 `Africo` 那个「查到了错的」陷阱。"""
    print("\n═══ 变异验证 ═══")
    zh_of = zh_lookup(con)
    cases = [
        ("大小写敏感：Africo 是市镇不是形容词",
         lambda: zh_of("Africo") not in (None, "非洲的") and "非洲" not in (zh_of("Africo") or "")),
        ("母地名清洗：截断法语从句",
         lambda: clean_parent("Sarre, situé dans la zone Ouest de la ville") == "Sarre"),
        ("母地名清洗：去 `la commune italienne de` 前缀",
         lambda: clean_parent("la commune italienne de Pessina Cremonese") == "Pessina Cremonese"),
        ("母地名清洗：`X et Y` 取第一个",
         lambda: clean_parent("Acqualagna et Cagli") == "Acqualagna"),
        ("词头去污染：伊西梅的比奥莱 → 比奥莱",
         lambda: strip_parent_prefix("伊西梅的比奥莱", "伊西梅") == "比奥莱"),
        ("词头去污染：格雷索内圣让的博德村 → 博德村",
         lambda: strip_parent_prefix("格雷索内圣让的博德村", "格雷索内圣让") == "博德村"),
        ("🔴 不该剥的不剥：母地名对不上时原样返回",
         lambda: strip_parent_prefix("阿尔巴的某村", "都灵") == "阿尔巴的某村"),
        ("🔴 查不到就返回 None，绝不猜",
         lambda: zh_of("Zzzznotaplace") is None),
    ]
    ok = True
    for name, f in cases:
        good = bool(f())
        ok &= good
        print("   %s %s" % ("✅" if good else "🔴", name))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate", "run"):
        ap.add_argument("--" + f, action="store_true")
    ap.add_argument("--slice", type=int, default=0)
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.run:
        import asyncio
        items = redo_list(ro)
        if a.slice:
            items = items[:a.slice]
        print("■ 重做音译 %s 个词头（只喂词形，不喂法语原文）" % f"{len(items):,}")
        T.SYS, T.CHUNK = SYS, 30
        OUT.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(T.run_batches(items, OUT))
        return 0
    if a.verify:
        return 0 if gate(ro) else 1
    if a.mutate:
        return 0 if mutate(ro) else 1
    rows, st = plan(ro)
    for k, v in st.most_common(8):
        print("   %-44s %7s" % (k[:44], f"{v:,}"))
    print("\n■ 将修 %s 条\n" % f"{len(rows):,}")
    for _sid, w, old, new in rows[:14]:
        print("   %-16s %s\n   %16s → %s" % (w[:16], old[:66], "", new[:66]))
    ro.close()
    if not a.apply or not rows:
        print("\n(未加 --apply，不写库)" if not a.apply else "")
        return 0
    with dbtool.session("fix-geo-parent-zh", expect={"#sense_gloss": 0}) as s:
        s.executemany(
            "UPDATE sense_gloss SET text=?, "
            "src=CASE WHEN src LIKE ? THEN src ELSE COALESCE(src,'unknown')||? END "
            "WHERE sense_id=? AND lang='zh' AND seq=0",
            [(new, "%" + TAG, TAG, sid) for sid, _w, _o, new in rows])
    print("\n■ 已修 %s 条" % f"{len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
