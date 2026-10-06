#!/usr/bin/env python3
"""阶段 6e：把**越南语例句**译成中文。vi，2026-10-03。

═══ 🔴🔴 这个阶段整个曾经不存在 ═══
2026-10-02 用户问「计划里为什么没有例句翻译」—— 阶段表无行、欠账表无编号、
账的闸 `COVERAGE` 还注释着「有意不进这张表」。
而**排除它的局部理由是对的**：中文例句覆盖率的下限只能写 0（实测 0.90%）。
⭐ 正因为那个理由是对的，这件事**再没被质疑过，闸一次都没响**。
⇒ 补了阶段 6e ＋ 欠账 W14 ＋ 账的闸 **V11「带锁的豁免」**（`COVERAGE_PENDING`，锁双向）。

═══ 🔴🔴 开跑前先把 `example.text` 自己量了一遍 ═══
这个阶段买的就是「把 `text` 译成中文」⇒ 开跑前必须问「这一列里装的真是越南语例句吗」。
量出来 **188 条不是**（外语原文 111 ／ 近义词元数据 53 ／ 整条只有出处 24），
另有 202 条出处串在正文首行、359 行英译夹在正文里、55 条 wiki 标记残渣。
已在 `stage6_sources.py` §⑤ 写成判据、在 `build_example_layer.collect()` 施用、
由回归闸 P11/P12/P13 锁住。⭐ **要花钱加工某一列之前，先把那一列本身量一遍。**
（ko 的 1% 定价切片逮到 K15 是**花钱之后**才逮到的，这次是花钱之前。）

═══ 免费路径走到底了：690 条封顶 ═══
🔴 `[[prove-free-path-before-quoting]]`：报价必须带「试过哪些免费路径、各自为什么不行」。
全 **12 个版本**扫过，「例句译文含汉字」共 **761 条**，逐条读完：
    中文版繁/简 719 条  ⇒ 库里已收 690（差额 29：4 条正文是喃字、
                          `Coi chừng!` 是 `same-as-headword`，都有现成理由）
    `KK` 27 条         ⇒ **英译里引了汉字**（`鰓 Tai = fish gills`，1895 Génibrel 词典）
    `EDITION` 10 条    ⇒ 🔴 **越南语音译对应的汉文原文**（`(經年不沐浴, 塵垢滿肌膚)`）——
                          它不是译文是**原文**，正是「有相似形状而意思相反」那一类
    `JA` 4 ／ `KO` 1   ⇒ 日语／韩语
⇒ 免费的中文**一条不剩**，剩下只能买。

═══ 🔴 控制组：验的是**每一个输出字段** ═══
`[[control-must-cover-every-output-field]]`：控制组漏验一个字段就烧掉 418 万 token 作废重跑。
输出只有 `zh` 一个字段，它有四种坏法，控制组各对一条：
    ① 错位      —— 答案贴到别的键上（定题，答案确定）
    ② 静默丢批  —— 逐 id 点名（flash 会丢；temperature=0 下**确定性地**丢同一个键）
    ③ 答非所问  —— 形状（空／没有一个汉字／译文里的越南语串原文没有）
    ④ **多行错位** —— 🔴 例句特有：诗文是多行的，译文的行数必须与原文**对得上**，
                    否则读者看到的是「四行越南语配两行中文」而没人知道哪行对哪行。
                    5b 的释义是单行，**这条检查在 5b 里不存在**。

用法：
    python3 -u vi/pipeline/translate_examples.py --slice 0.01    # 实测单价，**先跑这个**
    python3 -u vi/pipeline/translate_examples.py                 # 全量（先看报价）
    python3 -u vi/pipeline/translate_examples.py --load --apply   # 写库
"""
import argparse
import asyncio
import collections
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import paths                                                      # noqa: E402
import ds_batch                                                   # noqa: E402
import stage6_sources as S6                                       # noqa: E402

OUT = paths.WORK / "example_zh"
PER_BATCH = 12          # 🔴 例句比释义长（平均 30 字符 vs 释义 ~25），批小一点
F = lambda n: format(n, ",")                                      # noqa: E731

SYS = """你是越汉词典的例句编辑。把给定的越南语例句译成中文。

输入是一个 JSON 对象：键是例句编号，值含 w（这条例句所属的越南语词头）、t（例句原文）。
输出**同样的键**，值是 {"zh": "中文译文"}。键一个不许少、不许多、不许改。

规矩：
1. 译成**自然的中文**，不要逐字硬译。例句是给中文读者看怎么用这个词的。
2. 🔴 **行数必须与原文一致。** 原文是多行的（诗、歌词、对白、法条），译文也必须是
   同样行数的多行，用 \\n 分隔，一行对一行；**原文只有一行的，译文也只能一行** ——
   哪怕原文把一副对句或一整段挤在了一行里，也不要为了好看加换行。
3. w 是**帮你消歧**的那个词头，译文里要能看出它的意思，但**不要**把词头本身
   或它的拼写、音标、汉字写进译文。
4. 只译例句本身。不要加「这句话的意思是」这类引导语，不要加解释、注释、原文。
5. 原文里的方括号补充（`[...]`、`[…]`、`[sic]`、`[sic – meaning X]`）**原样保留**：
   `[…]` 是源头的省略号，`[sic]` 是「原文如此」的编辑标记 —— 删掉它等于把引文改成没错过。
6. 人名、地名、书名按通行中文译名；没有通行译名的**原样保留拉丁拼写**，不要音译生造。
7. 专有名词里的汉越词如果有确定的汉字写法，用汉字（Hà Nội → 河内，Nguyễn Trãi → 阮廌）。
8. 吃不准的直译，**不要编造**，不要为了通顺增添原文没有的信息。
9. 原文是法律、公文条款的，译成中文公文体；是口语对白的，译成口语。

越南语里的称谓/语气词，按语境译，**不要一律译成「你我他」**：
   anh / chị / em / ông / bà / cô / chú / bác —— 兄/姐/弟妹/先生/女士/姑/叔/伯，
   作第二人称时按中文习惯处理（多数情况下译成「你」或省略最自然）。
   ơi（呼唤）／nhé ／nhỉ ／à ／ạ（敬语尾）—— 用中文语气词对应，不要漏掉敬意层级。"""

# 🔴 控制组的定题。答案是**确定**的，用来验 id 对齐没坏。
#    ⚠️ 它们不是"考模型翻得好不好"——那要靠抽样人读。这几条只回答一个问题：
#      **这个键上的答案，是不是这个键的题目给出来的。**
#    ⭐ `__c4` 是**多行**的 —— 它验的是规矩 2（行数对齐），而 5b 没有这条。
PROBE = {
    "__c1": {"w": "nước", "t": "Tôi uống nước.", "want": ("水",)},
    "__c2": {"w": "một", "t": "Tôi có một con mèo.", "want": ("一只", "一头", "1")},
    "__c3": {"w": "Hà Nội", "t": "Tôi sống ở Hà Nội.", "want": ("河内",)},
    "__c4": {"w": "mẹ", "t": "Mẹ tôi là bác sĩ.\nBố tôi là giáo viên.",
             "want": ("医生",), "lines": 2},
}


def gap_rows(con):
    """缺中文译文的**可出版**例句。口径只写一份。

    🔴 `hidden = 0` 不是可选的：隐藏的例句不出版，给它买译文就是白花钱
       —— 例句层闸 **X8** 守着这件事，而收割器的 `gloss_rows()` 是同一条规矩的另一面。
    ⚠️ 判据写在 SQL 里而不是先全取再过滤：76,031 条的 `text` 有 230 万字符，
       全取一遍只为了丢掉其中一部分是白搬。
    """
    return list(con.execute("""
        SELECT e.id, d.word, e.text
        FROM example e JOIN dict d ON d.id = e.word_id
        WHERE e.hidden = 0
          AND NOT EXISTS (SELECT 1 FROM example_gloss g
                          WHERE g.example_id = e.id AND g.lang = 'zh')
        ORDER BY e.id"""))


def pick_slice(rows, frac):
    """按例句 id 的稳定哈希抽 —— **不是 `rows[::n]`**。

    🔴 按顺序抽会抽出一整片同类（`ORDER BY e.id` 把同一版、同一个词的例句排在一起，
       而十二版是**依次**收割的 ⇒ 前 1% 全是英文版的）。
       按哈希抽与顺序无关，长度分布才与全量可比。
    """
    k = int(frac * 0xFFFF)
    return [r for r in rows
            if int(hashlib.md5(str(r[0]).encode()).hexdigest()[:4], 16) < k]


def already(path):
    """答案文件里已经有答案的例句 id。"""
    out = set()
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if isinstance(d.get("id"), int):
                out.add(d["id"])
    return out


def build(rows, per=None):
    per = per or PER_BATCH
    batches, meta = [], []
    for i in range(0, len(rows), per):
        chunk = rows[i:i + per]
        pay = {str(eid): {"w": w, "t": t} for eid, w, t in chunk}
        m = [(str(eid), eid) for eid, *_ in chunk]
        # 每批注入一条定题（轮着来），键**混在中间不放开头**
        ck = list(PROBE)[i // per % len(PROBE)]
        pay[ck] = {x: PROBE[ck][x] for x in ("w", "t")}
        m.append((ck, ck))
        batches.append(pay)
        meta.append(m)
    return batches, meta


SRC_MODEL = "model:deepseek-v4-flash"


def normalize_zh(t, src_lines=None):
    """去掉首尾空白、行尾空白；**原文只有一行时把译文的换行并掉**。

    ⚠️ 不做引号归一（5b 的 `normalize_zh` 做了）：例句译文里的引号是**对白**，
       把 `“这样不行”` 换成 `「这样不行」` 是改行文风格，不是归一词形引用。
       5b 那条判据的前提是「引号里裹的是一个越南语词形」，例句里不成立。

    🔴🔴 **`src_lines` 这一半是 1% 切片实测逼出来的。** 755 条里坏 3 条，
       三条全是「原文 1 行、译文多行」—— 源头把《翘传》的对句、《歌谣》的上下句、
       一整段散文**挤在一行**，模型为了好读加了换行，而内容是对的：
           原 `"Lại càng ủ dột nét hoa, Sầu tuôn đứt nối, châu sa vắn dài." (TKiều)`
           译 `"更添花容憔悴，⏎ 愁绪断断续续，泪珠长短不齐。"（《翘传》）`
    ⚠️ 我的检查**比它的目的宽**：目的是「原文有几行就对应几行，别让读者不知道
       哪行对哪行」，而我写成「行数必须相等」—— 原文只有一行时**没有对应关系可丢**。
    ⇒ 按 5b 那条原则办：**在代码里确定性归一，不靠 prompt 保证**
      （prompt 管不住格式一致性）。中文标点自带分隔，直接接起来即可，
      一个内容字符都不丢：`…憔悴，` ＋ `愁绪…` → `…憔悴，愁绪…`。
    """
    out = "\n".join(l.rstrip() for l in (t or "").strip().split("\n"))
    if src_lines == 1 and "\n" in out:
        out = "".join(l.strip() for l in out.split("\n"))
    return out


_VI_TOKEN = re.compile(
    "[A-Za-zÀ-ỹ]*["
    "ăâêôơưđĂÂÊÔƠƯĐ"
    "àáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩị"
    "òóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ"
    "][A-Za-zÀ-ỹ]*")
_HAN = re.compile(r"[㐀-鿿]")


def audit(path, rows, ntok, peak):
    """回收侧的四条控制。**每一条对着一种坏法**，见文件头。"""
    got = {}
    for line in path.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        got[d["id"]] = d.get("zh")
    want = {eid for eid, *_ in rows}

    print("\n═══ 控制组 ═══")
    # ① 错位：定题的答案必须含它该含的字
    ctl_bad = []
    for k, v in PROBE.items():
        ans = got.get(k)
        if ans is None:
            ctl_bad.append((k, "没回来"))
        elif not any(x in ans for x in v["want"]):
            ctl_bad.append((k, "答成了 %r（该含 %s）" % (ans, "/".join(v["want"]))))
        elif v.get("lines") and len(ans.split("\n")) != v["lines"]:
            ctl_bad.append((k, "🔴 多行没对齐：答成 %d 行，该 %d 行"
                            % (len(ans.split("\n")), v["lines"])))
    print("   %s 定题对齐        %d/%d"
          % ("✅" if not ctl_bad else "🔴", len(PROBE) - len(ctl_bad), len(PROBE)))
    for k, why in ctl_bad:
        print("      🔴 %s %s" % (k, why))

    # ② 静默丢批：逐 id 点名
    miss = want - set(got)
    print("   %s 逐 id 点名       回来 %s / 要 %s（丢 %s）"
          % ("✅" if not miss else "🔴", F(len(want & set(got))), F(len(want)), F(len(miss))))

    # ③④ 答非所问 ＋ 多行错位。**每条判据都对比原文 `t`**
    bad = collections.Counter()
    samples = collections.defaultdict(list)
    for eid, w, t in rows:
        zh = got.get(eid)
        if zh is None:
            continue
        why = None
        if not zh.strip():
            why = "空"
        elif not _HAN.search(zh):
            why = "没有一个汉字（多半没翻译）"
        elif len(t.split("\n")) != len(normalize_zh(zh, len(t.split("\n"))).split("\n")):
            # 🔴 **例句特有的那条，5b 里不存在。** 诗文多行，行数不对读者就不知道
            #    哪行对哪行。⚠️ 判的是 `normalize_zh` **归一之后**的行数 ——
            #    「原文 1 行而译文多行」那一类已在代码里确定性并掉，不该再报红
            #    （1% 切片的 3 条坏全是那一类）。这里剩下的是真的对不上。
            why = ("🔴 行数不对：原文 %d 行，译文 %d 行"
                   % (len(t.split("\n")), len(zh.split("\n"))))
        else:
            # 判据**词一级**：译文里出现的越南语串，原文里（或词头里）也得有。
            # ⚠️ 这条在 5b 被收窄过一次（第一版「译文里有越南语特征拼写」太宽，
            #    1% 切片实测 9 条命中全是合法输出 —— 中文释义本来就要引用那个词形）。
            #    例句译文引用原文词形的理由更少，但**判据沿用收窄后的那一版**，
            #    不因为"这里应该更少"就放宽。
            vi_z = {x.lower() for x in _VI_TOKEN.findall(zh) if len(x) > 2}
            vi_t = {x.lower() for x in _VI_TOKEN.findall(t)} | {(w or "").lower()}
            extra = sorted(x for x in vi_z if not any(x in y for y in vi_t))
            if extra:
                why = "🔴 译文里的越南语串原文没有（疑似幻觉）：%s" % extra[:3]
        if why:
            bad[why] += 1
            if len(samples[why]) < 3:
                samples[why].append((w, t[:40].replace("\n", "⏎"),
                                     zh[:40].replace("\n", "⏎")))
    n = len(want & set(got))
    print("   %s 形状             坏 %d / %s"
          % ("✅" if not bad else "⚠️", sum(bad.values()), F(n)))
    for k, v in bad.most_common():
        print("      ⚠️ %-34s %d" % (k, v))
        for w, t, zh in samples[k]:
            print("           %-14s %-40s → %s" % (w, t, zh))

    # ⑤ 单价：**这是本次切片要买的数**
    if ntok:
        per = ntok / max(n, 1)
        print("\n═══ 单价（%s）═══" % ("🔴 高峰全价" if peak else "✅ 空闲半价"))
        print("   总 token %s ／ 成功 %s 条 ⇒ **每条 %.1f token**" % (F(ntok), F(n), per))
        print("   ⚠️ 折算到全量要乘的是**条数**，不是切片比例 —— "
              "切片按哈希抽，长度分布应与全量一致，但**这一点要实测不要假设**")

    print("\n■ 抽样（人眼看 —— 形状检查看不出「译错了」）")
    idx = list(range(0, min(5, len(rows)))) + list(
        range(len(rows) // 2, min(len(rows) // 2 + 5, len(rows))))
    for i in idx:
        eid, w, t = rows[i]
        if eid in got:
            print("   %-14s %s" % (w, t[:62].replace("\n", " ⏎ ")))
            print("   %-14s → %s" % ("", (got[eid] or "")[:62].replace("\n", " ⏎ ")))


def load(tags, dry=True, replace=None):
    """把 `OUT/<tag>.jsonl` 写进 `example_gloss`。**幂等**：已有中文的例句跳过。

    🔴🔴 **`tags` 的顺序是判据的一部分：先列的赢。**
       本函数幂等的做法是「这个 id 已经有中文了就跳过」，所以
       **一旦 `all.jsonl` 里的旧译文先落地，`redo` 那一批就永远进不来**。
    ⚠️ 这不是假想：6e 全量跑完之后我又把两条清洗判据收宽了一轮
       （`Coordinate term:` 那 49 条元数据、年份开头的 35 条出处），
       于是 **35 条的 `text` 变了 ⇒ 它们在 `all.jsonl` 里的译文是旧正文的译文**
       （有几条把出处也译进去了：`秀昌，《鹤先生…》，陈济昌诗作；1998年由文化信息出版`）。
       ⇒ 调用方必须写成 `load(["redo-redo_ids", "all"])`，redo 在前。
    ⭐ `[[answer-file-is-the-ledger]]`：答案文件是账本 —— 而账本有**版次**，
      新的那一版必须压住旧的，不能靠「谁先被读到」碰运气。
    """
    import dbtool
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {r[0] for r in con.execute(
        "SELECT example_id FROM example_gloss WHERE lang='zh'")}
    # 🔴 只认**可出版**的例句 —— 隐藏的不许收（例句层闸 X8）
    valid = {r[0] for r in con.execute("SELECT id FROM example WHERE hidden=0")}
    con.close()

    # 🔴 `normalize_zh` 要知道**原文有几行** ⇒ 入库前必须把原文取回来。
    #    不取的话归一那一半静默失效，而库里会存着多行译文、页面上与原文对不上。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    src_lines = {i: len(t.split("\n")) for i, t in
                 con.execute("SELECT id, text FROM example WHERE hidden=0")}
    con.close()

    rows, stat, seen = [], collections.Counter(), set()
    if isinstance(tags, str):
        tags = [tags]
    lines = []
    for tag in tags:
        p = OUT / ("%s.jsonl" % tag)
        if not p.exists():
            raise SystemExit("⚠️ %s 不存在（还没跑批？）" % p)
        got = p.read_text(encoding="utf-8").splitlines()
        print("   读 %-22s %6s 行" % (p.name, F(len(got))))
        lines += got
    for line in lines:
        try:
            d = json.loads(line)
        except Exception:
            stat["答案行解析不了"] += 1
            continue
        eid = d.get("id")
        zh = normalize_zh(d.get("zh"), src_lines.get(eid) if isinstance(eid, int) else None)
        if not isinstance(eid, int):
            stat["定题/非整数键（控制组，不入库）"] += 1
            continue
        if eid not in valid:
            stat["🔴 例句 id 不在出版层里"] += 1
            continue
        if eid in have and not (replace and eid in replace):
            # 🔴 `replace` 是**显式的白名单**，不是「新的总是赢」 ——
            #    后者会让任何一次误操作悄悄盖掉已经买到的译文。
            stat["已有中文，跳过"] += 1
            continue
        if eid in seen:
            stat["答案文件里重复（旧版本，已被压住）"] += 1
            continue
        # ⚠️ 计数**放在去重之后** —— 放在前面会把同一个 id 在两份答案文件里
        #    各数一次（实测报 130 而实际替换 65）。**一个报错的数就是一个会被引用的错数。**
        if eid in have:
            stat["替换掉失效的旧译文"] += 1
        if not zh or not _HAN.search(zh):
            # 🔴 判据与 `audit` ③ 同一条：没有一个汉字 ⇒ 不是译文，不入库。
            #    ko 的 R15 那一跤：跑批报「失败 0、定题全绿」而 18 条内容是 `[[]]`。
            stat["🔴 没有一个汉字 ⇒ 不入库"] += 1
            continue
        seen.add(eid)
        rows.append((eid, "zh", zh, SRC_MODEL))
    print("■ 可入库 %s 条" % F(len(rows)))
    for k, v in stat.most_common():
        print("   %-34s %6s" % (k, F(v)))
    if dry:
        print("\n(干跑。确认后 --apply)")
        return
    n_rep = sum(1 for r in rows if replace and r[0] in replace)
    with dbtool.session("vi-6e-example-zh",
                        expect={"__rows__": 0, "#example_gloss": len(rows) - n_rep},
                        invalidates=[]) as s:
        if n_rep:
            # 先删后插，**只删白名单里的**（`lang='zh'` 且付费来源 —— 不碰源头译文）
            s.executemany("DELETE FROM example_gloss WHERE example_id=? AND lang='zh' "
                          "AND src LIKE 'model%'",
                          [(r[0],) for r in rows if r[0] in replace])
        s.executemany("INSERT INTO example_gloss(example_id, lang, text, src) "
                      "VALUES (?,?,?,?)", rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true", help="把答案文件写进库")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--slice", type=float, default=0.0, help="只跑这个比例（实测单价用）")
    ap.add_argument("--conc", type=int, default=60,
                    help="🔴 从 60 起不从 16 起 —— `[[batch-concurrency-dont-be-timid]]`："
                         "实测快一个数量级且失败都是 0，**并发选低了直接换算成钱**"
                         "（跑慢了会跨出半价窗口）")
    ap.add_argument("--tag", default="", help="答案文件另起名，别覆盖已买到的")
    ap.add_argument("--redo", default="",
                    help="只跑 `OUT/<file>.json` 里列的 id，答案写进 `--tag`。"
                         "🔴 两种情形都走它：① 跑批**真丢**的（temperature=0 下模型"
                         "确定性地漏同一个键，原样重发永不收敛 ⇒ 单独成批）"
                         "② **正文改过**所以旧译文失效的（判据再收窄一轮之后）")
    ap.add_argument("--quote", action="store_true", help="只报价，不发一个请求")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = gap_rows(con)
    tot_pub = con.execute("SELECT COUNT(*) FROM example WHERE hidden=0").fetchone()[0]
    con.close()
    have_zh = tot_pub - len(rows)
    print("■ 可出版例句 %s ／ 已有中文 %s（%.2f%%）／ **待译 %s**"
          % (F(tot_pub), F(have_zh), 100.0 * have_zh / tot_pub, F(len(rows))))

    if a.load:
        # 🔴 顺序＝优先级，**redo 必须在 all 前面**（见 `load` 的文档）
        rep = None
        if a.redo:
            rep = set(json.loads((OUT / ("%s.json" % a.redo)).read_text()))
        # 🔴 **顺序即优先级，新的一版压住旧的。** 每收窄一轮判据就多一份 redo，
        #    而 `all.jsonl` 永远排最后 —— 它是第一版，里面有已经失效的译文。
        #    ⚠️ 名字写死在这里而不是扫目录：扫目录的顺序不可控，
        #      而这张表的**顺序就是语义**（`[[answer-file-is-the-ledger]]`：账本有版次）。
        load([a.tag] if a.tag else ["redo2", "redo-redo_ids", "all"],
             dry=not a.apply, replace=rep)
        return

    if a.redo:
        # 🔴 **批长缩到 4**：这批是「模型确定性漏掉的」和「正文改过的」，
        #    原样重发永不收敛（`[[retry-must-converge-or-drop-loud]]`）⇒ 把批切小，
        #    让每个键被单独注意到；几十条切成十来批的代价是零。
        #
        # 🔴🔴 **口径是「重译」不是「补缺」。** 第一版我让它从 `gap_rows()`（缺中文的）
        #    里挑，于是 65 条正文改过的**一条都挑不出来** —— 它们已经有一条
        #    **失效的**中文（旧正文的译文）。清单 65 条、本轮 0 条。
        #    ⭐ 救场的是我写的「大声放弃不静默丢」那一句：它把 65 个 id 打了出来，
        #      否则「本轮 0 条」看起来就像「没什么要补的」。
        #      `[[retry-must-converge-or-drop-loud]]` 的价值在这里是**可观测性**。
        # ⇒ `--redo` 从**全部可出版例句**里挑，不管它有没有中文；
        #   回收那头用 `--replace` 把旧的那条换掉（见 `load`）。
        want = set(json.loads((OUT / ("%s.json" % a.redo)).read_text()))
        con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        rows = list(con2.execute(
            "SELECT e.id, d.word, e.text FROM example e JOIN dict d ON d.id = e.word_id "
            "WHERE e.hidden = 0 AND e.id IN (%s) ORDER BY e.id"
            % ",".join("?" * len(want)), tuple(sorted(want))))
        con2.close()
        missing = want - {r[0] for r in rows}
        if missing:
            # 🔴 **大声放弃，不静默丢**：清单里有而库里取不到的（已隐藏），当场打出来。
            print("   ⚠️ 清单里 %d 条取不到（已隐藏 ⇒ 不该再译）：%s"
                  % (len(missing), sorted(missing)[:10]))
        global PER_BATCH
        PER_BATCH = 4
    if a.slice:
        rows = pick_slice(rows, a.slice)
    tag = a.tag or (a.redo and ("redo-%s" % a.redo)) or ("slice" if a.slice else "all")
    nch = sum(len(t) for _i, _w, t in rows)
    nml = sum(1 for _i, _w, t in rows if "\n" in t)
    print("■ 本轮 %s 条 ／ %s 字符（平均 %.0f）／ 多行 %s 条"
          % (F(len(rows)), F(nch), nch / max(len(rows), 1), F(nml)))
    peak = ds_batch.announce_window()      # 🔴 无条件播报，不是可选项
    if a.quote:
        print("   （只报价，没发请求。实测单价要跑 `--slice 0.01`。）")
        return

    done = already(OUT / ("%s.jsonl" % tag))
    if done:
        print("■ 答案文件里已有 %s 条，跳过" % F(len(done)))
        rows = [r for r in rows if r[0] not in done]
    if not rows:
        print("■ 这一轮没有要跑的了。")
        return
    batches, meta = build(rows)
    print("■ %s 批 × %d 条/批，并发 %d" % (F(len(batches)), PER_BATCH, a.conc))
    # 进度打印频率随规模缩 —— 6,337 批按默认每 10 批打一行会刷出 634 行，
    # 而**真正要读的是末尾那四条控制**，被刷走就等于没有。
    ntok = asyncio.run(ds_batch.run(SYS, batches, meta, OUT / ("%s.jsonl" % tag),
                                    mode="flash", conc=a.conc,
                                    every=max(10, len(batches) // 25)))
    audit(OUT / ("%s.jsonl" % tag), rows, ntok, peak)


if __name__ == "__main__":
    main()
