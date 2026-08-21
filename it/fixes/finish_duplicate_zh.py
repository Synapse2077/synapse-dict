#!/usr/bin/env python3
"""同词形下重复中文的最后 28 组 —— 逐条读、逐条定。2026-08-19。

`distinguish_duplicate_zh.py` 把 470 组做到 28 组，剩下的全是**接收端闸拒掉的模型回答**
（括注带「的」/ 主名被改写 / 括注就是词性 / 改完仍然重复）。闸拒得对，
所以再跑一轮模型没有意义 —— 28 组 63 条义项，规模小到可以逐条读。

═══ 🔴 第一件事：28 组里有 10 组根本不是重复 ═══
页面按「词条 + 词性」分组（A79）。`beige` 的形容词义和名词义分列在
【形容词】【名词】两个标题下 —— **用户看到的不是两条一样的**。

    poco(adv/det)  nostri(adj/pron)  gemello(adj/n)  colonizzatori(adj/n)
    a vista(adj/adv)  mangiapatate(n/adj)  beige(adj/n)  fashion(adj/n)
    occitanofono(adj/n)  rosa cipria(adj/n)

⇒ 判据本身过宽：它按 `(word_id, 中文)` 分组，而**页面按 `(word_id, 词性)` 分块**。
  这一族已经在 `distinguish_duplicate_zh.check()` 里挡过一次（那条「括注就是词性本身」
  的规则），但当时只挡住了模型的答案，没回头修判据本身。
  ⚠️ 判重的键必须是**用户看到的那个键**，不是我建表时用的那个键。

⇒ 真正挤在同一块里的是 **18 组**。
  （跑完这个脚本之后这一族从 10 变成 13 —— `zulu` 三条藏掉一条、`7`/`8` 四条改写两条，
   剩下的正好都是"词性各不相同"。闸里的基线是**动作之后**那个数，见 `gate()`。）

═══ 第二件事：这 18 组的决定 ═══
    · 10 组 **合并** —— 源头两条说的是同一件事
      （`Gran Carro` 的 Ursa Major / Great Bear / Plough 是同一个星座的三个英文名；
       `latina` 第二条是例句不是义项；`Sopron` 第二条是德语名 Odenburgo）
    · 8 组 **补区分** —— 源头确实是不同的东西，逐条手写

🔴 `La Tour` 是个真错误，不只是重复：现有中文写着「意大利瓦莱达奥斯塔大区市镇」，
   而源头两条分别是 `La Tour (Alpes-Maritimes)` 和 `La Tour (Haute-Savoie)`，
   **都在法国**。补区分的同时把这个错的框架换掉。

⚠️ 地名括注只放能区分的东西、不放类别词（`Chénoz` 两条都是村庄 ⇒ 不写「的村庄」），
   这是 2026-08-19 两家顾问一致、并已在 `Saint-Léger` 十条上落地的约定。

用法（在 it/ 目录下）：
    python3 fixes/finish_duplicate_zh.py            # 干跑
    python3 fixes/finish_duplicate_zh.py --apply
    python3 fixes/finish_duplicate_zh.py --verify
    python3 fixes/finish_duplicate_zh.py --mutate
"""
import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402
from distinguish_duplicate_zh import load_groups  # noqa: E402  判据只有一份

f = lambda n: format(n, ",")

# ═══ 合并：源头两条说的是同一件事，留第一条、其余藏起来 ═══
# 值是「为什么这两条是一回事」—— 写下来，将来谁想翻案不用重查源头。
MERGE = {
    219061: "latina：第二条是例句「Latina è la seconda città del Lazio」，不是独立义项",
    198219: "secreto：en 版一条写 secret, hidden 一条写 secret，同一个异体指针",
    221849: "tiberina：第二条是词源说明（源自 Tiberius），不是独立义项",
    168430: "Gran Carro：Ursa Major / Great Bear / Plough 是同一个星座的三个英文名",
    168436: "Corona australe：Corona Australis / Southern Crown 同一星座",
    168438: "Triangolo Australe：Triangulum Australe / Southern Triangle 同一星座",
    168440: "Croce del Sud：Crux / Southern Cross 同一星座",
    208999: "Sopron：第二条 Odenburgo 是该城的德语名，不是另一个地方",
    212575: "eccocela：一条写「前文提到的人」一条写「eccola 的强调变体」，同一个词",
    219023: "zulu：一条写「班图语部落成员」一条写「南非土著居民」，同一所指",
}

# ═══ 补区分：源头确实是不同的东西 ═══
# 每条后面是源头原文的关键处 —— 括注就是从那里来的，不是我编的。
REWRITE = {
    218666: ("最后通牒（国家间）",       "uno stato comunica ad un altro"),
    218667: ("最后通牒（不容置疑的命令）", "ordine indiscutibile"),

    218949: ("韦伯（马克斯·韦伯）",         "economista, sociologo… Max Weber"),
    218950: ("韦伯（恩斯特·海因里希·韦伯）", "medico tedesco Ernst Heinrich Weber"),
    218951: ("韦伯（威廉·爱德华·韦伯）",     "fisico tedesco Wilhelm Eduard Weber"),

    # 🔴 两条都是村庄 ⇒ 括注不写「的村庄」，只放能区分的地名（Saint-Léger 约定）
    256114: ("凯诺兹（费尼斯）",   "Chénoz, hameau de Fénis"),
    256115: ("凯诺兹（蒙若韦）",   "Montjovet, hameau de Fénis"),

    # 🔴 现有中文「拉图尔（意大利瓦莱达奥斯塔大区市镇）」与源头矛盾：两条都在法国
    297135: ("拉图尔（滨海阿尔卑斯省）", "La Tour (Alpes-Maritimes)"),
    297136: ("拉图尔（上萨瓦省）",       "La Tour (Haute-Savoie)"),

    334911: ("帕基耶（格雷桑）",     "Pâquier, hameau de Gressan"),
    334912: ("帕基耶（瓦尔图南什）", "Valtournenche, hameau de Gressan"),

    342314: ("圣但尼（德塞夫勒省）", "Saint-Denis (Deux-Sèvres)"),
    342315: ("圣但尼（加尔省）",     "Saint-Denis (Gard)"),

    # `il numero sette`（数）vs `la cifra sette`（数字符号）—— 同一 entry、同一词性
    206033: ("七（数）",       "il numero sette"),
    206034: ("七（数字符号）", "la cifra sette"),
    206039: ("八（数）",       "il numero otto"),
    206040: ("八（数字符号）", "la cifra otto"),
}


def page_dupes(con):
    """→ [(词形, 中文, [sense_id])]，**页面上真挤在同一块里**的重复。

    🔴 键是 `(word_id, 词性)` —— 用户看到的分块键，不是 `(word_id, 中文)`。
       `groupItSenses` 按「词条 + 词性」分组，而两个不同 entry 若词性相同，
       页面上会出现两个标题一样、内容一样的块 ⇒ 那也算重复。
       ⇒ 这里按**词性**归并，不按 entry_id。
    """
    out = []
    for g in load_groups(con):
        by = {}
        for i in g["items"]:
            pos = con.execute("SELECT pos FROM sense WHERE id=?", (i["id"],)).fetchone()[0]
            by.setdefault(pos, []).append(i["id"])
        ids = [v for v in by.values() if len(v) > 1]
        if ids:
            out.append((g["word"], g["zh"], [x for v in ids for x in v]))
    return out


def gate(con):
    left = page_dupes(con)
    ok = len(left) == 0
    print("   %s 页面上仍有重复中文的组 %s（应 0）" % ("✅" if ok else "🔴", f(len(left))))
    for w, zh, ids in left[:6]:
        print("        %-22s「%s」%s" % (w, zh, ids))
    # 🔴 已接受基线 13 + 理由：这 13 组两条中文相同但**词性不同**，
    #    页面分列在两个标题下，用户看到的不是重复。判据宽了，不是数据错。
    #    名单：poco(adv/det) nostri(adj/pron) gemello(adj/n) colonizzatori(adj/n)
    #         a vista(adj/adv) mangiapatate(n/adj) 7(num/adj) 8(num/adj)
    #         beige(adj/n) fashion(adj/n) zulu(adj/n) occitanofono(adj/n) rosa cipria(adj/n)
    #    ⚠️ 这个数是**合并之后**的：`zulu` 原本 adj+n+n，藏掉一条 n 之后才落进这一族；
    #       `7`/`8` 原本四条，改写两条之后剩 num+adj。第一版我拿合并前的 10 当基线，
    #       跑完当场红 —— **基线要在动作之后取，不能在之前取**。
    wide = sum(1 for g in load_groups(con)
               if len({con.execute("SELECT pos FROM sense WHERE id=?", (i["id"],)).fetchone()[0]
                       for i in g["items"]}) == len(g["items"]))
    good = wide == 13
    ok &= good
    print("   %s 词性各不相同、页面本就分开的组 %s（基线 13）"
          % ("✅" if good else "🔴", f(wide)))
    # 反向：手写的那 18 条改写必须**逐字**还在（防重放式脚本把它们覆盖回去）
    bad = [sid for sid, (zh, _why) in REWRITE.items()
           if (con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' "
                           "AND kind='equivalent' AND seq=0", (sid,)).fetchone() or [None])[0] != zh]
    ok &= not bad
    print("   %s 手写的 %s 条改写逐字还在（走样 %s）"
          % ("✅" if not bad else "🔴", f(len(REWRITE)), len(bad)))
    return ok


def plan(con):
    """→ (要改写的 [(id, 旧, 新)], 要藏的 [(id, 留下的那条)])"""
    upd = []
    for sid, (zh, _why) in REWRITE.items():
        now = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' "
                          "AND kind='equivalent' AND seq=0", (sid,)).fetchone()
        if now and now[0] != zh:
            upd.append((sid, now[0], zh))
    hide = []
    for keep in MERGE:
        wid, zh = con.execute(
            "SELECT s.word_id, g.text FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
            "AND g.lang='zh' AND g.kind='equivalent' AND g.seq=0 WHERE s.id=?", (keep,)).fetchone()
        pos = con.execute("SELECT pos FROM sense WHERE id=?", (keep,)).fetchone()[0]
        for (sid,) in con.execute(
                "SELECT s.id FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
                "AND g.lang='zh' AND g.kind='equivalent' AND g.seq=0 "
                "WHERE s.word_id=? AND g.text=? AND COALESCE(s.pos,'')=COALESCE(?,'') "
                "AND s.id<>? AND COALESCE(s.hidden,0)=0", (wid, zh, pos, keep)):
            hide.append((sid, keep))
    return upd, hide


def mutate():
    cases = [
        ("把一条手写改写改回原样",
         "UPDATE sense_gloss SET text='最后通牒' WHERE sense_id=218666 AND lang='zh'"),
        ("放出一条已合并的重复义项",
         "UPDATE sense SET hidden=0 WHERE id=(SELECT s.id FROM sense s "
         "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' "
         "WHERE s.hidden=1 AND g.text='大熊座' LIMIT 1)"),
        ("把一条义项的中文改成与同组另一条逐字相同",
         "UPDATE sense_gloss SET text='韦伯（马克斯·韦伯）' WHERE sense_id=218950 AND lang='zh'"),
    ]
    passed = 0
    for name, sql in cases:
        d = Path(tempfile.mkdtemp())
        shutil.copy(paths.DB, d / "m.sqlite")
        con = sqlite3.connect(d / "m.sqlite")
        con.execute(sql)
        con.commit()
        print("\n── 变异：%s" % name)
        red = not gate(con)
        con.close()
        shutil.rmtree(d)
        print("   %s" % ("✅ 闸报红" if red else "🔴 闸没报 —— 这道检查是假的"))
        passed += red
    print("\n■ 变异 %s/%s" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return mutate()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    upd, hide = plan(ro)
    print("■ 页面上真重复的组 %s ／ 手写改写 %s 条 ／ 合并要藏 %s 条"
          % (f(len(page_dupes(ro))), f(len(upd)), f(len(hide))))
    for sid, old, new in upd:
        print("   %-8s「%s」→「%s」" % (sid, old, new))
    for sid, keep in hide:
        print("   藏 %-8s（并入 %s）%s" % (sid, keep, MERGE[keep][:52]))
    if not a.apply:
        ro.close()
        print("\n(未加 --apply，不写库)")
        return 0
    ro.close()
    with dbtool.session("finish-duplicate-zh", expect={"__rows__": 0}) as s:
        for sid, _old, new in upd:
            s.execute("UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='zh' "
                      "AND kind='equivalent' AND seq=0", (new, sid))
        for sid, _keep in hide:
            s.execute("UPDATE sense SET hidden=1 WHERE id=?", (sid,))
    print("■ 已改写 %s 条、藏 %s 条" % (f(len(upd)), f(len(hide))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
