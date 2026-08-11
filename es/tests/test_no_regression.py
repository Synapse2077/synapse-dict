#!/usr/bin/env python3
"""回归闸：**过去每一个修复，现在还在不在**。2026-08-11。

═══ 为什么必须有这个 ═══
用户 2026-08-11：「同一个问题你修了，隔天修其他问题，你又发现之前的问题又出现了。
这才是我抱怨的。这也才是导致无穷无尽的根本原因。」

他是对的。查下来，修复消失有**两种**机制，而且第二种我一次都没意识到：

  ❌ **被抹掉**（overwritten）
     修复用 UPDATE/DELETE 写在 `sense` / `sense_gloss` 上，
     而 `build_sense_layer.py` 是 DROP + 重建 —— 重建一次，修复就没了。
     已知案例：`split_case_homographs` 的 4,501 条归属、`example_gloss` 的 50,289 条译文。

  ⚠️ **被绕过**（bypassed）—— 更隐蔽，因为**数据还在，查那一列一切正常**
     7-31~8-03 整轮音标修复写在 `dict.phonetic`；
     8-07 我新建 `pronunciation` 表、**从 dump 原样重建**，展示层跟着切过去。
     `dict.phonetic` 里 `extremo` 好端端写着 `eksˈtɾemo`，
     而用户在界面上看到的是 `pronunciation` 里的 `eɡsˈtɾemo` —— 正是 8-02 修掉的那个缺陷。
     **只查修复写入的那一列，永远发现不了这一类。**

⇒ 本闸的核心设计：**每条断言同时在「修复写入列」和「App 实际读取列」上跑**，
   两列的结果不同，就是「被绕过」。

═══ 判据从哪来 ═══
不自己另写一套 —— 直接用各修复脚本**自己的判据**（SQL 条件原文抄自
`fixes/fix_ipa_residue.FAMS` 等）。判据是对「缺陷长什么样」的定义，属于数据的性质；
拿它去查另一张表，不构成「用代码核代码」。

═══ 怎么用 ═══
    python3 tests/test_no_regression.py            # 出清单
    python3 tests/test_no_regression.py --mutate   # 变异验证：闸本身是不是恒真的

🔴 每加一个修复脚本，必须在 CHECKS 里加一行。没有断言的修复＝下一次静默回归。
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import shutil
import sqlite3
import tempfile

import paths

# ══════════════════════════════════════════════════════════════════════════
#  落点：同一个「缺陷」要在哪两个地方查
#
#  IPA_COLS  修复写在 dict.phonetic；App 读的是 pronunciation 里
#            notation='phonemic' AND is_primary=1 的那一条（spanish.ts:530）。
# ══════════════════════════════════════════════════════════════════════════
WROTE = "dict.phonetic"
READS = "pronunciation.ipa"

IPA_SRC = "SELECT word, phonetic AS ipa FROM dict WHERE TRIM(COALESCE(phonetic,''))<>''"
IPA_APP = ("SELECT d.word AS word, p.ipa AS ipa FROM dict d JOIN pronunciation p "
           "ON p.word_id=d.id WHERE p.notation='phonemic' AND p.is_primary=1")


# ══════════════════════════════════════════════════════════════════════════
#  🔴 已接受基线（ACCEPT）—— 没有它，这道闸会**永远是红的**
#
#  `docs/PITFALLS.md` E 组那条教训的直接应用：「混在一起报，闸就永远非零，久了没人看。」
#  下面每一条都是**已经裁决过、决定不修**的残留，附理由。只有**超过**基线才报警。
#  ⚠️ 调高任何一个数字都必须同时写清为什么 —— 否则这就变成了掩盖回归的开关。
# ══════════════════════════════════════════════════════════════════════════
ACCEPT = {
    # x 数与 ɡs 数对不齐，`fix_x_gs.convert` 判据**故意拒绝猜**：
    # cóccix ˈkoɡsiɡs（cc 也读 ks）、exotoxina、exaccionista、saxitoxina。
    # 宁可留 4 个错，不要用机械替换去猜 —— 猜错的代价见 fix_x_gs 里 blogs/gangs 那段。
    "A1": 4,
    # 🔴 全部是 **kaikki 原文**（software ˈsofdw̝eɾ / Kuwait kuˈw̝ait / web ˈw̝eb）。
    # 2026-07-31 上午我拿 --wraised 把其中 83 条当成"豆包填的"改坏过，靠来源普查才发现。
    # 本项目既定策略：IPA 归信人工源 kaikki。**不许再动。**
    "A4": 86,
    "A6": 1, "A10": 1, "A12": 3,   # 同上，都是 kaikki 原文的个别行
    # `Imperio bizantino` / `Imperio romano` —— 多词专名的另一种拼法，源头就没给义项。
    # `exactQuery` 已把这类无义项无指针的行排到最后（spanish.ts:417），不会挡住正常检索。
    "B5": 2,
}

# (编号, 修复脚本, 日期, 缺陷名, 条件SQL[对 ipa/word 两列], 例外说明)
IPA_CHECKS = [
    ("A1", "fix_x_gs.py", "08-02", "字母 x 写成 ɡs（应为 ks）",
     "ipa LIKE '%ɡs%' AND lower(word) LIKE '%x%'"),
    ("A2", "fix_ipa_residue.py", "07-31", "正字法 c/q/v 残留在音标里",
     "ipa GLOB '*[cqv]*'"),
    ("A3", "fix_ipa_residue.py", "07-31", "ʎ（与本词典 yeísmo 约定冲突）",
     "ipa LIKE '%ʎ%'"),
    ("A4", "fix_ipa_residue.py", "07-31", "w̝ 升音符误用",
     "ipa LIKE '%'||char(797)||'%' AND lower(word) NOT LIKE '%hu%'"),
    ("A5", "fix_ipa_residue.py", "07-31", "rɾ/ɾr 双颤音符（kaikki 全无）",
     "ipa LIKE '%rɾ%' OR ipa LIKE '%ɾr%'"),
    ("A6", "fix_ipa_residue.py", "07-31", "词首 ɾ（应为颤音 r）",
     "(ipa LIKE 'ɾ%' OR ipa LIKE 'ˈɾ%') AND lower(word) LIKE 'r%'"),
    ("A7", "fix_ipa_residue.py", "07-31", "斜杠/方括号残留（违反裸串存储约定）",
     "ipa LIKE '%/%' OR ipa LIKE '%[%'"),
    ("A8", "fix_ipa_nonspanish.py", "07-31", "th 未转 θ",
     "ipa LIKE '%th%'"),
    ("A9", "fix_ipa_nonspanish.py", "07-31", "z（西语无 /z/ 音位）",
     "ipa LIKE '%z%'"),
    ("A10", "fix_ipa_nonspanish.py", "07-31", "ʒ/dʒ（应为 ʝ）",
     "ipa LIKE '%ʒ%'"),
    ("A11", "fix_ipa_nonspanish.py", "07-31", "非西语元音 ɔɛʊɪɑɒɐə",
     "ipa GLOB '*[ɔɛʊɪɑɒɐə]*'"),
    ("A12", "fix_ipa_nonspanish.py", "07-31", "严式附加符 ̯ ̪ ̥ ̩ ̟ ̺",
     "ipa GLOB '*[" + "".join(chr(c) for c in (815, 810, 805, 809, 799, 826)) + "]*'"),
    ("A13", "fix_ipa_nonspanish.py", "07-31", "拉丁小写 g（应为 IPA ɡ U+0261）",
     "ipa LIKE '%' || char(103) || '%'"),
    ("A14", "normalize_notation.py", "08-03", "音标含正字法 y 残留",
     "ipa LIKE '%y%'"),
]

# 义项层：修复直接写 sense / sense_gloss，而 build_sense_layer.py 是 DROP 重建。
SENSE_CHECKS = [
    ("B1", "drop_bad_labels.py", "08-07", "短标签是纯领域标记（无对应词）",
     "SELECT COUNT(*) FROM sense_gloss WHERE src='llm-label-v4pro' "
     "AND text GLOB '（*）' AND text NOT GLOB '*[a-zA-Z一-龥]*（*'"),
    # ⚠️ 第一版写成「同一义项两条相同中文」⇒ 报 647 条**假警报**。
    #    那是证据层的正常形态：flash 与豆包各译一遍、文本恰好相同，两行都留着是有意的
    #    （`sense_gloss` 主键含 seq，`buildUnified` 取最短那条当 title，界面只显示一次，已核）。
    #    真正被 `drop_bad_labels` 删掉的是 **`src='llm-label-v4pro'` 的短标签**内部重复，
    #    判据必须带上 src，否则查的根本不是同一批数据。
    ("B2", "drop_bad_labels.py", "08-07", "同一义项两条完全相同的短标签",
     "SELECT COUNT(*) FROM (SELECT sense_id, text FROM sense_gloss "
     "WHERE src='llm-label-v4pro' GROUP BY sense_id, text HAVING COUNT(*)>1)"),
    ("B3", "fix_altof_lemma.py", "08-06", "异体拼写被编造成变形标签（Méjico 的 阳性）",
     "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' "
     "AND (text LIKE '% 的 阳性' OR text LIKE '% 的 阴性' OR text LIKE '% 的 变位形式')"),
    # ⚠️ 第一版查的是 `lang='en'` ⇒ 报 2,675 条**假警报**。
    #    英文原文写 `alternative form of Bangladés` 是**权威源本来的话**，是证据不是缺陷。
    #    `fix_inflected_gloss` / `fix_pointer_gloss` 修的是**中文释义**变成了元描述
    #    （用户看到「gnomo 的异体拼写」当作释义）。判据必须落在 lang='zh'。
    #    —— 这正是本项目最高频的自伤：**量源头不量落点**。
    ("B4", "clitic/fix_inflected_gloss", "07-25", "中文释义是元描述（inflection of …）",
     "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' "
     "AND (text LIKE 'inflection of %' OR text LIKE '%form of %' COLLATE NOCASE "
     "     OR text LIKE '%的变位形式')"),
    ("B5", "split_case_homographs.py", "08-07", "大写专名词条一条义项都没有",
     "SELECT COUNT(*) FROM dict d WHERE d.word GLOB '[A-ZÁÉÍÓÚÑ]*' "
     "AND d.infl IS NULL AND d.exchange IS NULL "
     "AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"),
    ("B6", "ingest_sense_gap/translate", "08-10", "补收义项没有中文",
     "SELECT COUNT(*) FROM sense_add WHERE TRIM(COALESCE(zh,''))=''"),
    ("B7", "build_example_layer.py", "08-10", "例句译文被清空（曾丢 50,289 条）",
     "SELECT CASE WHEN (SELECT COUNT(*) FROM example_gloss) < 40000 THEN 1 ELSE 0 END"),
    ("B8", "build_relation_layer.py", "08-10", "义项级 derived 关系漏收（曾漏 20,193）",
     "SELECT CASE WHEN (SELECT COUNT(*) FROM sense_relation WHERE kind='derived') "
     "< 40000 THEN 1 ELSE 0 END"),
    ("B9", "全局", "—", "义项没有任何中文释义",
     "SELECT COUNT(*) FROM sense s WHERE NOT EXISTS("
     "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')"),
]


def run_ipa(con, mutate_note=""):
    out = []
    for cid, script, date, name, cond in IPA_CHECKS:
        a = con.execute(f"SELECT COUNT(*) FROM ({IPA_SRC}) WHERE {cond}").fetchone()[0]
        b = con.execute(f"SELECT COUNT(*) FROM ({IPA_APP}) WHERE {cond}").fetchone()[0]
        out.append((cid, script, date, name, a, b))
    return out


def run_sense(con):
    out = []
    for cid, script, date, name, sql in SENSE_CHECKS:
        try:
            n = con.execute(sql).fetchone()[0]
        except sqlite3.Error as e:
            n = f"闸失效:{e}"
        out.append((cid, script, date, name, n))
    return out


def report(con):
    bad_wrote = bad_reads = 0
    print("═" * 108)
    print("A 组 · 音标修复 —— 同一判据在两列上各查一次")
    print(f"   {'修复写入':>12} = {WROTE}    {'App 读取':>12} = {READS}")
    print("═" * 108)
    print(f"  {'ID':<4} {'修复脚本':<26} {'日期':<6} {'缺陷':<34} {'修复列':>8} {'读取列':>8}  判定")
    print("─" * 108)
    for cid, script, date, name, a, b in run_ipa(con):
        acc = ACCEPT.get(cid, 0)
        if b <= acc:
            verdict = "✅ 仍在" if b == 0 else f"✅ 在基线内({acc})"
            mark = ""
        elif a == 0:
            verdict, mark = "⚠️ 被绕过", "  ← 数据还在原列，但用户看到的是另一列"
            bad_reads += 1
        else:
            verdict, mark = "❌ 两列都有", ""
            bad_wrote += 1
        print(f"  {cid:<4} {script:<26} {date:<6} {name:<34} {a:>8,} {b:>8,}  {verdict}{mark}")

    print()
    print("═" * 108)
    print("B 组 · 义项/例句/关系层 —— 这些表是 DROP 重建的，修复写在这里会被抹掉")
    print("═" * 108)
    print(f"  {'ID':<4} {'修复脚本':<28} {'日期':<6} {'缺陷':<40} {'残留':>10}  判定")
    print("─" * 108)
    for cid, script, date, name, n in run_sense(con):
        acc = ACCEPT.get(cid, 0)
        if isinstance(n, str):
            verdict = n
        elif n == 0:
            verdict = "✅ 仍在"
        elif n <= acc:
            verdict = f"✅ 在基线内({acc})"
        else:
            verdict = "❌ 已回归"
            bad_wrote += 1
        v = f"{n:,}" if isinstance(n, int) else "—"
        print(f"  {cid:<4} {script:<28} {date:<6} {name:<40} {v:>10}  {verdict}")

    print()
    print("─" * 108)
    print(f"  ❌ 修复已失效：{bad_wrote} 条    ⚠️ 修复被绕过：{bad_reads} 条")
    return bad_wrote + bad_reads


# ══════════════════════════════════════════════════════════════════════════
#  变异验证 —— 「一条永远通过的检查等于没检查」
#  在库的副本上人为制造每一类缺陷，闸必须全部抓住。
# ══════════════════════════════════════════════════════════════════════════
#  ⚠️ 变异必须打在**闸真正盯着的那个落点**上。第一版两条打偏了，结果报「漏掉」：
#     · A1 打在 `MIN(id)` 那行 —— 它既不是 `notation='phonemic' AND is_primary=1`
#       （展示层只读这一种），词形也不含 x（A1 判据要求含 x）⇒ 根本不在统计口径里。
#     · A3 打在 `dict.phonetic` —— 而 `check_brief` **有意只对读取列报警**
#       （原列脏但用户看不到，不该半夜叫醒任何人）。
#     教训与「量源头不量落点」是同一条，只是这次犯在变异上。
MUTATIONS = [
    ("A1 往展示层注入 ɡs",
     "UPDATE pronunciation SET ipa='eɡsˈtɾemo' WHERE id=("
     "  SELECT p.id FROM pronunciation p JOIN dict d ON d.id=p.word_id"
     "   WHERE p.notation='phonemic' AND p.is_primary=1 AND lower(d.word) LIKE '%x%' LIMIT 1)"),
    ("A3 往展示层注入 ʎ",
     "UPDATE pronunciation SET ipa='ˈkaʎe' WHERE id=("
     "  SELECT id FROM pronunciation WHERE notation='phonemic' AND is_primary=1 LIMIT 1)"),
    ("B3 注入编造的变形标签",
     "INSERT INTO sense_gloss(sense_id,lang,kind,seq,text,src) "
     "SELECT MIN(id), 'zh','definition',99,'Méjico 的 阳性','mut' FROM sense"),
    ("B6 把一条补收义项的中文清空",
     "UPDATE sense_add SET zh='' WHERE id=(SELECT MIN(id) FROM sense_add)"),
    ("B7 删掉大部分例句译文",
     "DELETE FROM example_gloss WHERE rowid % 10 <> 0"),
    ("B8 删掉大部分 derived 关系",
     "DELETE FROM sense_relation WHERE kind='derived' AND rowid % 10 <> 0"),
    ("B9 删掉一条义项的全部中文",
     "DELETE FROM sense_gloss WHERE sense_id=(SELECT MIN(sense_id) FROM sense_gloss) AND lang='zh'"),
]


def reds_of(con):
    """与 `check_brief` **完全相同**的判定逻辑（含基线），供变异验证复用。

    🔴 必须复用，不能另写。第一版变异验证写的是「任何一列 > 0 就算抓住」，
       而真实库本来就有 86 条已接受基线 ⇒ **IPA 组恒为真，7/7 里有 2 个是白给的**。
       一条永远给同一个答案的检查等于没检查 —— 这次它伪装成了「全绿」。
    """
    red = []
    for cid, *_x, a, b in run_ipa(con):
        if b > ACCEPT.get(cid, 0):
            red.append(cid)
    for cid, *_x, n in run_sense(con):
        if isinstance(n, str) or n > ACCEPT.get(cid, 0):
            red.append(cid)
    return red


def mutate_verify():
    print("■ 变异验证：在库副本上逐个注入缺陷，闸必须抓住\n")
    # ── 先证明「不变异 ⇒ 绿」，否则下面每一条都是白给的
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    base = reds_of(con)
    con.close()
    if base:
        print(f"  🔴 未变异的库本身就报红 {base} —— 变异验证无意义，先把它弄绿")
        return False
    print("  · 前提：未变异的库是绿的 ✓\n")

    caught = 0
    for name, sql in MUTATIONS:
        with tempfile.TemporaryDirectory() as td:
            cp = _pl.Path(td) / "m.sqlite"
            shutil.copy(paths.DB, cp)
            con = sqlite3.connect(cp)
            con.execute(sql)
            con.commit()
            red = reds_of(con)
            con.close()
            caught += bool(red)
            print(f"  {'✅ 抓住' if red else '🔴 漏掉'}  {name:<34} {red or ''}")
    print(f"\n  {caught}/{len(MUTATIONS)} 抓住")
    return caught == len(MUTATIONS)


def check_brief():
    """给 `dbtool.session` 用的精简入口：只回「哪些红了」，不打大表。

    返回 [(ID, 缺陷名, 说明), …]，空列表＝全绿。
    🔴 每次写库之后自动跑这个，就是为了让「重建抹掉旧修复」在**当场**暴露，
       而不是等一周后有人偶然撞见 —— 那正是 2026-08-11 之前一直发生的事。
    """
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    try:
        red = []
        for cid, script, _d, name, a, b in run_ipa(con):
            acc = ACCEPT.get(cid, 0)
            if b > acc:
                red.append((cid, name, f"App 读取列残留 {b:,} 行，基线 {acc}（{script}）"))
        for cid, script, _d, name, n in run_sense(con):
            acc = ACCEPT.get(cid, 0)
            if isinstance(n, str):
                red.append((cid, name, n))
            elif n > acc:
                red.append((cid, name, f"残留 {n:,}，基线 {acc}（{script}）"))
        return red
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    if a.mutate:
        _sys.exit(0 if mutate_verify() else 1)
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    n = report(con)
    _sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
