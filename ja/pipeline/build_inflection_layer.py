#!/usr/bin/env python3
"""阶段 2：变形层（活用）。2026-09-15。零模型调用。

═══ 🔴 三处和前六门不一样，每处都有实测 ═══
① **源是日语版，不是英文版。**英文版只给 975/13,921 个动词（7.0%）活用表、中位 2 个形；
   日语版 19,564 词 / 中位 19 个形。照「英文版是结构基准」的惯性走，
   会得出「日语动词几乎不活用」这个荒谬结论（`[[multi-edition-methodology]]`：
   英文版是**结构**基准不是**内容**上限）。
② **入口判据不是「forms 有 tags 就收」。**59 万行 forms 里只有 45.3% 是真形态：
       真形态      267,312  45.3%
       罗马字重复   126,849  21.5%   ← 同一个格位的第三份拷贝
       canonical    91,353  15.5%   ← 就是词头本身
       异表记        62,913  10.7%   ← 旧字体/假名写法，**归关系层不归这里**
   照搬会把 20.3 万真活用虚报成 35.7 万。
③ **名词零贡献。**日语名词没有格、没有数、没有性 —— `noun` 的 16.7 万行 forms
   里真形态只有 201 行（0.1%），全是异表记。
   对照 de：名词的属格与复数是变形层的大头。**照搬 de 的判据会收进 16.7 万行异表记。**

═══ 中文语法说明 ═══
`infl_compose.compose()` 确定性组合，**全量 280,340 行只有 1 行拼不出**（已补 `-tari`）。
顺序就是判据，那个模块自带变异验证。

跑（在仓库根）：
    python3 -u ja/pipeline/build_inflection_layer.py
    python3 -u ja/pipeline/build_inflection_layer.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import re
import sqlite3

import dbtool
import paths
from pipeline.build import NOT_A_WORD, norm_ja
from pipeline.infl_compose import compose, has_error
from pipeline.infl_table import consumed as table_consumed
from pipeline.infl_table import mark_ranuki
from pipeline.infl_table import repair as repair_table

MORPH = {"stem", "past", "negative", "formal", "informal", "conditional", "continuative",
         "imperative", "adverbial", "attributive", "terminative", "hypothetical",
         "volitional", "causative", "passive", "potential", "irrealis", "perfective",
         "imperfective", "polite", "realis", "perfect", "desiderative",
         "conjunctive", "contrastive", "-tari"}
JUNK_FORM = {"-", "—", "*", "", "…"}
# 🔴 **罗马字按内容挡，不按标签挡。**英文版有 86,237 行罗马字形**没打 `romanization` 标签**
#    （`尾籠` 的「敬体否定」给成 `birō de wa arimasen`），占收进来的 20.3%。
#    判据不是形式代理：**日语的活用形按定义写成假名或汉字**，纯拉丁串不是日语词形。
JA_SCRIPT = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
# 🔴 英文版把**词形和转写写在同一个单元格**里：`'食べれます [taberemasu]'`。
#    原样收下去，方括号那截就长进 `dict.word` —— 词头印成「食べれます [taberemasu]」、
#    TTS 连着括号一起念、搜裸词形还匹配不上。日语版不带转写，全部 3,721 个受影响词形
#    都来自英文版。2026-09-18 拆开：词形归词形，转写进 `inflection.romaji`。
#    （落库那批由 `ja/fixes/fix_inflection_form_romaji.py` 洗过；这里是生成侧，
#     不改的话下次重跑原样长回来 —— `[[replay-scripts-undo-fixes]]`。）
FORM_ROMAJI = re.compile(r"^(.+?) \[([^\[\]]+)\]$")


def split_romaji(form):
    """`'食べれます [taberemasu]'` → `('食べれます', 'taberemasu')`；没括号原样返回。

    ⚠️ 判据要求**整串结尾是一个方括号组**且括号内不含方括号，括号内还不许有日文
    字符 —— 后者挡的是「词形本身带方括号」那种假阳性（实测 0 条，但判据不能靠"当前没有"）。
    """
    m = FORM_ROMAJI.match(form)
    if not m or JA_SCRIPT.search(m.group(2)):
        return form, None
    return m.group(1), m.group(2)


def _assert_ja():
    assert paths.DB.name == "synapse-dict-ja.sqlite", "🔴 paths 不是 ja 的：%s" % paths.DB
    assert not hasattr(dbtool, "has_han"), "🔴 dbtool 不是 ja 的"


def scan():
    raw = []
    stat = collections.Counter()
    for path, src in ((paths.KK, "en-edition"), (paths.EDITION, "ja-edition")):
        # 🔴 `src_ref` 原来是 `<src>:<词>:<词性>#<下标>`，**不唯一**：dump 里有 5,050 个
        #    (词, 词性) 因词源不同分成多条，成品库里因此有 5,155 组重复 src_ref、
        #    5,829 行多余。2026-09-19 补上「同 (词,词性) 的第几条」这一段
        #    （`[[primary-key-is-not-enough]]`：键声称的唯一性它并不具备）。
        nth = collections.Counter()
        for line in open(path, encoding="utf-8"):
            o = json.loads(line)
            pos = o.get("pos")
            if pos in NOT_A_WORD:
                continue
            base = (o.get("word") or "").strip()
            if not base:
                continue
            k = nth[(base, pos)]
            nth[(base, pos)] += 1
            # 🔴 英文版的活用行**不是平的，是表格** —— wiktextract 在行、列两个方向
            #    都有表头识别失败（整组继承上一组的 tag／丢 past 这一维／认不出的格子
            #    打报错标记被整行丢弃）。扁平遍历看不见表，于是把源头的错原样印上了页面：
            #    `食べましょう` 印「敬体命令形」、`食べます` 与 `食べました` 同印「敬体」、
            #    而 `食べない` 根本不在库里。判据与验证见 `pipeline/infl_table` 文件头。
            #    （日语版没有表结构，`repair_table()` 对它返回空，自然走下面的扁平路径。）
            for j, (fm, tg, rom, tpl) in enumerate(repair_table(o)):
                stat["forms 总行"] += 1
                if fm in JUNK_FORM or fm == base:
                    stat["跳过·空/占位/与词头同形"] += 1
                    continue
                raw.append([fm, base, pos, set(tg), src,
                            "%s:%s:%s:%d:%s#%d" % (src, base, pos, k, tpl, j), rom,
                            "收·%s（活用表）" % src])

            eaten = table_consumed(o)
            for i, f in enumerate(o.get("forms") or []):
                tg = set(f.get("tags") or [])
                stat["forms 总行"] += 1
                # 🔴 只跳过**表修复真的消费掉**的那些行。第一版我跳过了所有
                #    `source=='conjugation'`，把没接的 78 张 `inflection-table-top`
                #    （`COOLじゃない` 那类）整块丢了 —— 1,896 条，干跑的「消失方向」检查逮到的。
                if i in eaten:
                    stat["跳过·活用表（已由表修复路径处理）"] += 1
                    continue
                if "romanization" in tg:
                    stat["跳过·罗马字重复"] += 1
                    continue
                if "canonical" in tg:
                    stat["跳过·canonical（词头本身）"] += 1
                    continue
                if has_error(tg):
                    stat["跳过·源头抽取报错"] += 1
                    continue
                if not (tg & MORPH):
                    stat["跳过·异表记等（归关系层）"] += 1
                    continue
                fm, rom = split_romaji((f.get("form") or "").strip())
                if fm in JUNK_FORM or fm == base:
                    stat["跳过·空/占位/与词头同形"] += 1
                    continue
                if not JA_SCRIPT.search(fm):
                    stat["跳过·罗马字（按内容判，源头没打标签）"] += 1
                    continue
                raw.append([fm, base, pos, set(tg), src,
                            "%s:%s:%s:%d#%d" % (src, base, pos, k, i), rom,
                            "收·%s" % src])

    # 🔴 **第二遍**：ら抜き要看「同一个原形下有没有对照」，一行一行看是判不出来的。
    #    两版都有（日语版给 `得られる`/`得れる` 是两条扁平行，没有表结构），
    #    所以放在这里做一次，而不是在表修复里做一份、扁平路径再做一份。
    stat["标·ら抜き言葉"] = mark_ranuki([(r[0], r[1], r[3]) for r in raw])

    rows = []
    for fm, base, pos, tg, src, ref, rom, hit in raw:
        zh = compose(tg)
        if not zh:
            stat["跳过·拼不出中文说明"] += 1
            continue
        rows.append((fm, base, pos, zh,
                     json.dumps(sorted(tg), ensure_ascii=False), src, ref, rom))
        stat[hit] += 1
    return rows, stat


# 🔴🔴 **这张表不止本阶段一个写入方。**
#    `ja/fixes/recover_pointer_senses.py` 从英文版指针正文里抽出的词形也落在这里（375 行），
#    src_ref 形如 `en-edition:ptr:<n>`。2026-09-19 把本阶段改成「清空重建」时，
#    第一版的 `DELETE FROM inflection` 会把它们一起冲掉 —— **静默撤销另一次修复**
#    （`[[replay-scripts-undo-fixes]]` 的反向：不是我的修被别人撤，是我撤别人的）。
#
#    ⇒ 每个写入方在这里登记自己的 src_ref 形状。下面那条闸要求这些形状对库里的行
#      **既覆盖又互斥**：出现对不上的行就停机。
#      判据只认「哪个写入方」，不认「哪一版格式」—— 本阶段 2026-09-19 给 src_ref
#      加过一段（同 (词,词性) 的第几条），闸不能把格式迁移误报成外来行。
OWNERS = [
    ("本阶段 build_inflection_layer", lambda r: "#" in r),
    ("ja/fixes/recover_pointer_senses.py", lambda r: r.startswith("en-edition:ptr:")),
]
MINE = OWNERS[0][1]


def main():
    _assert_ja()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows, stat = scan()
    for k, v in stat.most_common():
        print("   %-28s %9s" % (k, format(v, ",")))

    # 🔴 `src_ref` 必须唯一 —— 它是这张表和 dump 之间唯一的认领凭据。
    #    原来的格式少了「同 (词,词性) 的第几条」，5,155 组撞在一起
    #    （`[[primary-key-is-not-enough]]`）。这条断言就是不让它再撞回去。
    refs = collections.Counter(r[6] for r in rows)
    dup = [k for k, v in refs.items() if v > 1]
    assert not dup, "🔴 src_ref 不唯一，%d 组重复，例：%s" % (len(dup), dup[:3])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    n_infl, n_rom = con.execute(
        "SELECT COUNT(*), COUNT(romaji) FROM inflection").fetchone()
    # 🔴 重建前对账：库里每一行都必须**恰好**归属一个已登记的写入方。
    #    对不上就停机 —— 少一条登记，清空重建就会静默吃掉别人的修复。
    bad, n_foreign, foreign_base = [], 0, []
    for r, b in con.execute("SELECT src_ref, base FROM inflection"):
        hit = [n for n, f in OWNERS if f(r)]
        if len(hit) != 1:
            bad.append((r, hit))
        elif not MINE(r):
            n_foreign += 1
            foreign_base.append(b)
    n_base_before, n_label_before = con.execute(
        "SELECT COUNT(base_id), COUNT(label_zh) FROM inflection").fetchone()
    con.close()
    assert not bad, (
        "🔴 %d 行的 src_ref 归属不明（没人认领或多人认领），清空重建会吃掉它们。\n"
        "   例：%s\n   ⇒ 查清是谁写的，登记进 OWNERS 再跑。" % (len(bad), bad[:5]))
    assert all(MINE(r[6]) for r in rows), "🔴 本阶段生成了不符合自己 ref 形状的行"
    print("   对账：本阶段拥有 %s 行 ｜别的写入方 %s 行（已登记）"
          % (format(n_infl - n_foreign, ","), format(n_foreign, ",")))
    forms = {r[0] for r in rows}
    new = sorted(forms - set(have))
    print("\n   不同变形词形 %s ｜已在 dict %s ｜**要新插** %s"
          % (format(len(forms), ","), format(len(forms) - len(new), ","), format(len(new), ",")))
    print("   ⇒ dict %s → %s" % (format(len(have), ","), format(len(have) + len(new), ",")))
    final = len(rows) + n_foreign
    print("   ⇒ inflection %s → %s（%+s，其中别的写入方 %s 行原样保留）"
          % (format(n_infl, ","), format(final, ","),
             format(final - n_infl, ","), format(n_foreign, ",")))

    # 🔴 抽样反验：pt 那轮靠这一步挡下 283,136 条假词形（法语版把主语代词写进了变位表单元格）
    dbtool.sample_check([(r[0], r[1], r[3], r[5]) for r in rows[::max(1, len(rows) // 18)]],
                        14, ("变形", "原形", "中文说明", "来源"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    # 🔴 **这一步是幂等的**：先清空再整表重建，而不是往上叠。
    #    2026-09-19 修表结构时需要重跑，原来只 INSERT 的写法重跑一次就翻倍。
    #    `expect` 是**增量**：删 n_infl 再插 len(rows)，净变化是两者之差。
    # 每一行都有中文说明，所以 `label_zh` 的增量就是行数增量；
    # `base_id` 要看原形本身在不在 dict 里（这一轮新插的词形也算）。
    allw = set(have) | set(new)
    exp_base = (sum(1 for r in rows if r[1] in allw)
                + sum(1 for b in foreign_base if b in allw))
    with dbtool.session("ja-inflection-layer", expect={
            "__rows__": len(new), "pos": 0,
            "#inflection": len(rows) - (n_infl - n_foreign),
            "inflection.label_zh": len(rows) + n_foreign - n_label_before,
            "inflection.base_id": exp_base - n_base_before,
            "inflection.romaji": sum(1 for r in rows if r[7]) - n_rom},
            invalidates=[]) as s:
        s.executemany("INSERT INTO dict (word, word_norm, is_lemma) VALUES (?,?,0)",
                      [(w, norm_ja(w)) for w in new])
        wid = {w: i for i, w in s.execute("SELECT id, word FROM dict")}
        s.execute("DELETE FROM inflection WHERE src_ref LIKE '%#%'")   # 只删本阶段的
        s.executemany(
            "INSERT INTO inflection (word_id, kind, base, base_id, label_zh, tags,"
            " src, src_ref, romaji) VALUES (?,'inflection',?,?,?,?,?,?,?)",
            [(wid[fm], base, wid.get(base), zh, tags, src, ref, rom)
             for fm, base, pos, zh, tags, src, ref, rom in rows])
        # 🔴 `base_id` 要在 dict 插完之后再连一遍 —— 同 `intake_edition_words` 那一步，
        #    原形本身可能是这一轮才进 dict 的（pt 栽过的顺序错）。
        s.execute("CREATE TEMP TABLE _b(base TEXT PRIMARY KEY, id INT)")
        s.execute("INSERT INTO _b SELECT word, id FROM dict")
        s.execute("UPDATE inflection SET base_id="
                  "(SELECT b.id FROM _b b WHERE b.base=inflection.base)"
                  " WHERE base_id IS NULL")


if __name__ == "__main__":
    main()
