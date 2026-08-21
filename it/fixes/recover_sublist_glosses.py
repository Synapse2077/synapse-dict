#!/usr/bin/env python3
"""意语版「总述 + 子列表」的子列表 —— 一直都在，是我们读错了下标。2026-08-19。

═══ 用户看得到 ═══
    Springfield  六条义项，中文全是「斯普林菲尔德（地名）」，意语原文也全是
                 「nome di varie località nei paesi anglofoni, tra cui:」（"英语国家的多个地名，其中："）
                 —— 冒号后面那一句到底是哪个 Springfield，页面上一个字都没有

═══ 🔴 记账本这条记错了两件事 ═══
原记：「wiktextract 把总述复制了 N 遍、具体是哪些没收。全库 362 条证据行 / 235 个词形」。

① **子列表没丢**。wiktextract 把它放在 `glosses[1]`，我们的收词器只取了 `glosses[0]`：

       "glosses": ["nome di varie località nei paesi anglofoni, tra cui:",
                   "la capitale dell'Illinois, uno dei cinquanta stati federati…"]

② **362 / 235 量的是别的东西** —— 那是「`sense_src.text` 以冒号结尾」的行数。
   意语版拿冒号引出例句是常规写法（`esperanto` 的「relativo all'esperanto:」冒号后
   本来就没东西）。回 dump 逐条核，**真有子列表的只有 23 条义项 / 11 个词形**。
   ⚠️ 又一次「量源头不量落点」的近亲：我拿一个**形式特征**（结尾是冒号）当了
      「丢了内容」的判据，而真判据是 `len(glosses) > 1`，回 dump 一查就有。

═══ 映射是确定性的 ═══
`ingest_it_edition.py:84` 写的是 `kk-it:<词>:<词性>#<occ>.<i>`，**`i` 就是 dump 里
`enumerate(senses)` 的下标**。所以 dump 的第 i 条义项 ↔ 库里 `#occ.i` 那一行，
不需要文本匹配、不需要模型。

═══ 改哪一层 ═══
    · `sense_src.text` **不动** —— 外锚闸 `verify_vs_dump.py:93` 拿它跟 `glosses[0]`
      逐条比。证据层记的就是"源头第一行写了什么"，改了闸当场红，而且改错了地方。
    · `sense_gloss(lang='it', kind='definition')` → 换成**子列表那一句**（页面显示的意语原文）
    · `sense_gloss(lang='zh')` → 手写（23 条，不送模型）

═══ 两族，只做一族 ═══
    · 17 条 证据已提升成出版义项 → 本脚本处理
    ·  6 条 证据**没提升**（`farfalla` 的 diurna/notturna、`gufo` 的 comune/reale、
      `retroterra`、`cenci`）→ 那是"少了义项"不是"义项错了"，要新建行，记账不做

用法（在 it/ 目录下）：
    python3 fixes/recover_sublist_glosses.py            # 干跑
    python3 fixes/recover_sublist_glosses.py --apply
    python3 fixes/recover_sublist_glosses.py --verify
    python3 fixes/recover_sublist_glosses.py --mutate
"""
import argparse
import gzip
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

# ═══ 手写中文，键是 `src_ref`（源头的稳定标识）═══
# 🔴 不用 sense_id 也不用「第几条」当键：`model-answer-files-key-by-id` 记的那个坑
#    是「按第几条存，重放时贴到别的义项上」。`src_ref` 由源头的词+词性+下标派生，
#    源头不变它就不变，比库里的自增主键更适合当这份手写表的键。
ZH = {
    # Springfield —— 五个具体的 Springfield（#0.0 是总述，保持原样）
    "kk-it:Springfield:name#0.1": "斯普林菲尔德（伊利诺伊州首府）",
    "kk-it:Springfield:name#0.2": "斯普林菲尔德（马萨诸塞州）",
    "kk-it:Springfield:name#0.3": "斯普林菲尔德（密苏里州）",
    "kk-it:Springfield:name#0.4": "斯普林菲尔德（俄勒冈州）",
    "kk-it:Springfield:name#0.5": "斯普林菲尔德（俄亥俄州）",
    # Lansing
    "kk-it:Lansing:name#0.1": "兰辛（密歇根州首府）",
    "kk-it:Lansing:name#0.2": "兰辛（纽约州市镇，密歇根州那座城以此得名）",
    # Jackson
    "kk-it:Jackson:name#0.2": "杰克逊（密西西比州首府）",
    # Concord
    "kk-it:Concord:name#0.1": "康科德（加利福尼亚州）",
    "kk-it:Concord:name#0.2": "康科德（北卡罗来纳州）",
    "kk-it:Concord:name#0.3": "康科德（新罕布什尔州首府）",
    # epiclesi
    "kk-it:epiclesi:noun#0.1": "呼名祈求（古罗马祭司呼唤朱庇特之名时行之）",
    "kk-it:epiclesi:noun#0.2": "呼求圣灵（天主教感恩祭中对圣灵的祈求）",
    # dispositivo
    "kk-it:dispositivo:noun#0.2": "（法律）判决主文（民事或刑事判决中载明裁判结论的部分）",
    "kk-it:dispositivo:noun#0.3": "（法律）合同处分条款（前言之后载明各项约定的部分）",
    # acciocché —— 🔴 现有中文与源头**错位一格**：#0.0 是总述，目的义在 #0.1
    "kk-it:acciocché:conj#0.0": "从属连词（可表下列意义）",
    "kk-it:acciocché:conj#0.1": "以便，为了（引导目的从句，动词用虚拟式）",
    "kk-it:acciocché:conj#0.2": "因为（引导原因从句，动词用陈述式）",
}


def dump_sublists():
    """→ {src_ref: 子列表那一句}。只扫一次 dump。

    🔴 `occ` 不能写死成 0。`ingest_it_edition.py:84` 的 `#<occ>.<i>` 里 `occ` 是
       **同一个 (词, 词性) 在 dump 里第几次出现**（不同词源会各出现一次）。
       第一版写死 0，`cenci` 当场对不上 —— 它的证据行是 `kk-it:cenci:noun#1.0`。
       ⇒ 这里按收词器同样的方式数出现次数。
    """
    out, occ = {}, {}
    for line in gzip.open(paths.EDITION, "rt", encoding="utf-8"):
        d = json.loads(line)
        if d.get("lang_code") != "it":
            continue
        w, pos = d.get("word"), d.get("pos")
        k = occ[(w, pos)] = occ.get((w, pos), -1) + 1
        for i, s in enumerate(d.get("senses") or []):
            g = s.get("glosses") or []
            if len(g) > 1:
                out["kk-it:%s:%s#%d.%d" % (w, pos, k, i)] = g[-1]
    return out


def plan(con, sub=None):
    """→ (要改的 [(sense_id, src_ref, 新意语 或 None, 新中文)], 没提升的, 对不上的)

    新意语为 `None` = **只改中文**。这一族是「总述行的中文被写成了子义项的中文」：
    `acciocché#0.0` 的源头只有一层 gloss（「congiunzione subordinativa; può avere valore:」），
    库里的中文却写着「以便（引导目的从句）」—— 那是 `#0.1` 的意思，**整组错位一格**。
    只改中文不动意语原文（源头那一行本来就没错）。
    """
    sub = sub if sub is not None else dump_sublists()
    todo, unpromoted, orphan = [], [], []
    for ref in sorted(set(sub) | set(ZH)):
        it_text = sub.get(ref)          # 不在 sub 里 ⇒ 只改中文
        row = con.execute(
            "SELECT sense_id FROM sense_src WHERE src='it-edition' AND src_ref=?",
            (ref,)).fetchone()
        if row is None:
            orphan.append(ref)
        elif row[0] is None:
            unpromoted.append((ref, it_text or "(只改中文)"))
        else:
            todo.append((row[0], ref, it_text, ZH.get(ref)))
    return todo, unpromoted, orphan


def gate(con, sub=None):
    todo, unpromoted, orphan = plan(con, sub)
    ok = True

    def chk(name, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print("   %s %-42s %s（应 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))

    # 🔴 已接受基线 1 + 理由：`kk-it:cenci:noun#0.1`。源头**自己**给这条打了
    #    `form_of: galani` + `form-of` 标签 ⇒ 收词器按 A23「只做源头自己的结构判定」
    #    把它路由到变形层，不进证据层。这是对的，不是漏收。
    #    （顺手回源核过一遍：整个 occ 块没进证据层的 485,669 个里，
    #      真义项被漏 **0 条** —— 全是变形指针 485,002 + 空 gloss 667。）
    chk("dump 里有子列表、库里对不上的（基线 1）", len(orphan), 1)
    # 🔴 已接受基线 5 + 理由：这 5 条证据从没提升成出版义项（`farfalla` 的日行蝶/夜行蝶、
    #    `gufo` 的长耳鸮/雕鸮、`retroterra` 的"城市周边地带"）。补它们要**新建义项行**，
    #    是"少了义项"不是"义项错了"，记账不做。
    #    ⚠️ 是 5 不是 6 —— `cenci` 归到上面那条基线里去了（源头标了 form-of）。
    #       两条基线是**互斥分区**，加起来才是 dump 里带子列表的全部 24 条。
    chk("证据没提升成义项的（基线 5）", len(unpromoted), 5)
    chk("要改的义项", len(todo), 18)
    # 每一条都必须有手写中文，且库里的意语原文已经是子列表那一句
    nozh = [r for r in todo if not r[3]]
    chk("🔴 没写中文的", len(nozh), 0)
    bad = 0
    for sid, _ref, it_text, zh in todo:
        cur_it = con.execute(
            "SELECT text FROM sense_gloss WHERE sense_id=? AND lang='it' AND kind='definition' "
            "AND seq=0", (sid,)).fetchone()
        cur_zh = con.execute(
            "SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' AND kind='equivalent' "
            "AND seq=0", (sid,)).fetchone()
        if it_text is not None and (cur_it or [None])[0] != it_text:
            bad += 1
        elif (cur_zh or [None])[0] != zh:
            bad += 1
    chk("🔴 意语原文与中文都已就位", bad, 0)
    return ok


def mutate():
    sub = dump_sublists()
    ref0 = "kk-it:Springfield:name#0.1"
    cases = [
        ("把一条意语原文改回总述",
         "UPDATE sense_gloss SET text='nome di varie località nei paesi anglofoni, tra cui:' "
         "WHERE sense_id=(SELECT sense_id FROM sense_src WHERE src_ref='%s') "
         "AND lang='it'" % ref0),
        ("把一条中文改回泛称",
         "UPDATE sense_gloss SET text='斯普林菲尔德（地名）' "
         "WHERE sense_id=(SELECT sense_id FROM sense_src WHERE src_ref='%s') "
         "AND lang='zh'" % ref0),
        ("把一条已提升的证据解开（该落进「没提升」那一族）",
         "UPDATE sense_src SET sense_id=NULL WHERE src_ref='%s'" % ref0),
    ]
    passed = 0
    for name, sql in cases:
        d = Path(tempfile.mkdtemp())
        shutil.copy(paths.DB, d / "m.sqlite")
        con = sqlite3.connect(d / "m.sqlite")
        con.execute(sql)
        con.commit()
        print("\n── 变异：%s" % name)
        red = not gate(con, sub)
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
    todo, unpromoted, orphan = plan(ro)
    print("■ dump 里带子列表的义项 %s ｜ 已提升可改 %s ｜ 没提升（记账）%s ｜ 对不上 %s"
          % (f(len(todo) + len(unpromoted) + len(orphan)), f(len(todo)),
             f(len(unpromoted)), f(len(orphan))))
    for sid, ref, it_text, zh in todo:
        old = ro.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' "
                         "AND kind='equivalent' AND seq=0", (sid,)).fetchone()
        print("   %-34s「%s」→「%s」" % (ref[6:40], (old or [""])[0], zh))
        print("        意语 %s" % (it_text[:88] if it_text else "（不动，只改中文）"))
    print("\n■ 没提升的（记账，不做）")
    for ref, t in unpromoted:
        print("   %-34s %s" % (ref[6:40], t[:70]))
    if orphan:
        print("\n🔴 对不上的 %s" % orphan)
    if not a.apply:
        ro.close()
        print("\n(未加 --apply，不写库)")
        return 0
    # `orphan` 的已接受基线见 gate()：源头自己标了 form-of 的那一条不算漏收。
    if any(not zh for _s, _r, _t, zh in todo) or len(orphan) > 1:
        print("🔴 有没写中文的、或出现了基线之外的对不上，先查清再写库")
        return 1
    ro.close()
    with dbtool.session("recover-sublist-glosses", expect={"__rows__": 0}) as s:
        for sid, _ref, it_text, zh in todo:
            if it_text is not None:
                s.execute("UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='it' "
                          "AND kind='definition' AND seq=0", (it_text, sid))
            s.execute("UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='zh' "
                      "AND kind='equivalent' AND seq=0", (zh, sid))
    print("■ 已恢复 %s 条" % f(len(todo)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
