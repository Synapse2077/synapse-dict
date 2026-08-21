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
# 🔴 判据 import it 那一份：同一个缺陷在两个语种上用两套判据，迟早对不上。
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent.parent / "it" / "fixes"))
from fix_unclosed_paren import classify as paren_class   # noqa: E402
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "fixes"))
from hide_english_relation_notes import is_english_note   # noqa: E402

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
    # 🔴 D3 修在**展示层**（App.tsx 的 esNounBadge/esVerbBadge），SQL 查不到 ⇒
    #    这个数字不会因修复而变。留基线只为「涨了说明数据层来了新的」，
    #    真正守它的是契约闸（先渲染再断言）。
    # ⚠️ 这个数被打回**三次**，每次都是收紧（不是放宽）：
    #    ① 64,393 —— 拿 it 的 NOMINAL={"noun","name","adj"}（**长写法**）去比 es 的
    #       pos（**短写法** n/name/adj），`{n} ⊆ {noun,…}` 恒为假，几乎所有词都命中。
    #       ⇒ 跨语种复用判据，**值域必须先对齐**。
    #    ② 823 —— 判据是「义项词性全是名词性」。**外审逮到误伤**：`banco` 有 6 条名词
    #       义项 + 1 条感叹词义项（`¡banco!`），明确的 `el · 阳` 被藏掉了。
    #    ③ 36 —— 只有**另一种也带性的词类**（art/pron/det/contr）与名词性并存时
    #       才真的说不清归属（`la` ＝ 冠词阴 + 名词阳）。
    "D3": 36,
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
    # C5 —— 🔴 **2026-08-20 修完之后这条断言的含义变了，基线 934 → 111。**
    # 原本它量的是「大小写折叠残留」；`fix_case_fold_residue` 把 904 条义项搬回
    # 各自的拼写行之后，剩下的 111 条**是预期行为**，不是残留：
    # `sense_owner` 的人工裁决把「复活节岛」判给了大写行 `Isla de Pascua`，
    # 而 dump 记的原拼写（`entry.spelling`）是小写 `isla de Pascua` ——
    # 两者本来就该不同。⇒ C5 现在只是「义项行 ≠ entry 行」的计数，
    # **真正管事的是 C10**（是否在权威说的那一行）。
    # ⚠️ 留着 C5 是因为它涨了说明有人新造了折叠；但别再拿它当「残留」读。
    "C5": 111,
    # C7 = `merer` 14 + `ethnographique` 1 —— `build.py:277` 的 JUNK_BASES，
    # 有意不给它们建词头。**实测值**，不是猜的（猜高一条会让「少补词头」这类回归隐形）。
    "C7": 15,
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


# ══════════════════════════════════════════════════════════════════════════
#  C 组 · 词条层 / 变形层（2026-08-20 建）
#
#  这两张表是**从旧列迁出来的**，所以回归的形状与 A/B 组不同：不是「修复被抹掉」，
#  而是「迁移出来的这份与它的来源对不上了」。⇒ 判据一律是**与旧列逐字节比**。
#  🔴 旧列 `dict.infl` / `dict.exchange` **有意不删**，冻结成迁移锚点 ——
#     删了这道闸就永远失去了参照物（同 it 对 `dict.ipa` 的处置）。
#
#  ⚠️ C2 不写成 SQL。第一版用字符串算术在 SQL 里抠「最后一行」，
#     报出 103,095 条假红 —— 是我的 SQL 写错了，不是数据错（A33 先查尺子）。
#     完整的逐字节比对本来就该在 Python 里做，别为了塞进框架去凑 SQL。
# ══════════════════════════════════════════════════════════════════════════
def run_infl(con):
    out = []

    # C1 条数：inflection 行数 vs 旧列拆行后的条数
    n_tab = con.execute("SELECT COUNT(*) FROM inflection").fetchone()[0]
    n_col = con.execute(
        "SELECT COALESCE(SUM(LENGTH(infl)-LENGTH(REPLACE(infl,char(10),''))+1),0) "
        "FROM dict WHERE COALESCE(infl,'')<>''").fetchone()[0]
    out.append(("C1", "build_inflection_layer.py", "08-20",
                "变形层条数与旧 infl 列对不上", abs(n_tab - n_col)))

    # C2 逐字节：从表反向重建每个词形的 infl 字符串，与旧列比。100%，非抽样。
    from collections import defaultdict
    rb = defaultdict(list)
    for wid, seq, base, lab in con.execute(
            "SELECT word_id, seq, base, label_zh FROM inflection"):
        rb[wid].append((seq, ("%s 的 %s" % (base, lab)) if base else lab))
    bad = 0
    for wid, infl in con.execute(
            "SELECT id, infl FROM dict WHERE COALESCE(infl,'')<>''"):
        if "\n".join(t for _, t in sorted(rb.get(wid, []))) != infl:
            bad += 1
    out.append(("C2", "build_inflection_layer.py", "08-20",
                "反向重建 infl 与旧列逐字节不符", bad))

    # C3 挂锚规模：义项挂到 entry 的条数不许缩水（缩水＝有脚本重建了 sense 却没重挂）
    n = con.execute("SELECT COUNT(*) FROM sense WHERE entry_id IS NOT NULL").fetchone()[0]
    out.append(("C3", "build_entry_layer.py", "08-20",
                "义项挂锚数缩水（基线 147,042）", max(0, 147042 - n)))

    # C4 词性轴：sense.pos 与它所属 entry.pos 必须一致。这条是 0 容忍。
    n = con.execute("SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
                    "WHERE s.pos IS NOT NULL AND s.pos<>e.pos").fetchone()[0]
    out.append(("C4", "build_entry_layer.py", "08-20", "义项词性与所属词条词性不符", n))

    # C5 大小写折叠残留：见 build_entry_layer 里的基线说明，934 是已接受存量，只拦涨。
    n = con.execute("SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
                    "WHERE e.word_id<>s.word_id").fetchone()[0]
    out.append(("C5", "build_entry_layer.py", "08-20",
                "义项行≠entry行（裁决判给另一拼写，预期 111）", n))

    # C6 读取路径：展示层拼 inflNotes 的规则与 C2 的重建规则必须是同一条。
    #    🔴 这是「同一判据在写入列和读取列各查一次」里的**读取那一次**。
    #    TS 侧的实测核对见 `probes/infl_read_path.ts`（4,000 个高频词形 4,000/4,000，
    #    三种变异全部报红）。这里查的是它依赖的排序键还在不在 —— seq 一旦有洞或重复，
    #    `ORDER BY i.seq` 拼出来的顺序就不再等于旧列的行序。
    n = con.execute("SELECT COUNT(*) FROM (SELECT word_id FROM inflection "
                    "GROUP BY word_id, seq HAVING COUNT(*)>1)").fetchone()[0]
    out.append(("C6", "spanish.ts:inflectionQuery", "08-20",
                "变形层 (word_id,seq) 有重复（读取路径靠它排序）", n))

    # C7 悬空原形：2026-08-20 从 11,406 降到 15（`merer` 14 + `ethnographique` 1，
    #    都是 build.py:277 有意不收的非标准词）。基线是**实测**的，不是猜的 ——
    #    我第一版猜 16，结果「少补一个词头」这类回归恰好被吞掉、变异该红没红。
    # ⚠️ 判据是「**指不到活着的 dict 行**」，不只是「base_id 为空」。
    #    变异验证当场暴露了这个洞：删掉一个补收词头之后 `base_id` 仍非空、
    #    只是指向了不存在的行，C7 一声不吭（那次是 C8 替它报的红）。
    #    「悬空」的本质是指不到东西，不是某一列恰好为 NULL。
    n = con.execute("""SELECT COUNT(*) FROM inflection i
        LEFT JOIN dict d ON d.id = i.base_id
        WHERE i.base<>'' AND COALESCE(i.hidden,0)=0 AND d.id IS NULL""").fetchone()[0]
    out.append(("C7", "ingest_missing_bases.py", "08-20",
                "变形指不到活着的原形行（基线 15）", n))

    # C8 补收的词头还在不在。判据 = is_lemma + 规则音标 + 无释义无译文 + 有变形指着它。
    #    **基线 8,063 是实测的**，与「本次新增 8,075」对不上，两处已知代价说清楚：
    #      · 少 15：G2P 算不出音标的那批 `phonetic_src` 为空，判据够不到；
    #      · 多 3：`Navidad` / `Nochevieja` / `Pentecostés` 三个**旧行**恰好也满足判据。
    #    🔴 8,063 → 8,062（2026-08-20 晚）：删掉了 `empelotadose` —— 那是 wiktextract
    #       粘出来的伪词，我给它建了词头。**基线降低必须写清为什么**，
    #       否则下次有人会把它当成「又丢了一个词头」。
    #    没有 `src` 标记列可以精确圈出「本次新增」，所以判据只能是近似的 ——
    #    但它拦得住真正要拦的那件事（见下）。
    #    🔴 `build.py` 是 DROP 重建 `dict` 的，这批词头**不在它的输出里** ——
    #    重跑一次建库就全没了。这正是本闸存在的理由（「被抹掉」那一类）。
    n = con.execute("""SELECT COUNT(*) FROM dict d
        WHERE d.is_lemma=1 AND d.phonetic_src='rule' AND d.definition IS NULL
          AND d.translation IS NULL
          AND EXISTS(SELECT 1 FROM inflection i WHERE i.base_id=d.id)""").fetchone()[0]
    out.append(("C8", "ingest_missing_bases.py", "08-20",
                "补收词头缩水（基线 8,062）", max(0, 8062 - n)))

    # C9 被修掉的伪原形不许在**读取路径**上复活。
    #    判据抄 `spanish.ts:inflectionQuery`：COALESCE(base_fixed, base) + hidden 过滤。
    n = con.execute("""SELECT COUNT(*) FROM inflection
        WHERE COALESCE(hidden,0)=0 AND COALESCE(base_fixed, base) IN
              ('desemejadose','tú and vos','él and usted','ellos and ellas',
               'peuco an American hawk','soldado little soldier')""").fetchone()[0]
    out.append(("C9", "fix_glued_reflexive_base.py", "08-20",
                "wiktextract 粘出的伪原形在读取路径上复活", n))

    # C10 大小写折叠残留：2026-08-20 从 934 降到 8。
    #     判据 = 「义项待在 `word` 等于 `entry.spelling` 的那一行」。
    #     🔴 判据必须用 **Python 建的精确映射**：`idx_word` 是 `word COLLATE NOCASE`，
    #        SQL 里写 `d.word = e.spelling` 用不上索引 ⇒ 全表扫（当天踩了两次）。
    #     基线 8 = `OCA`/`ANDA`/`UNA`/`REA`/`ARCA` 这类全大写缩写库里没有独立行，
    #     义项待在 title-case 行上，是合理落点。**实测，不是猜的。**
    # 🔴 判据**直接 import 修复脚本自己的 `target_of`**，不抄一份。
    #    我第一版在这里另写了「义项必须在 entry.spelling 那一行」，
    #    而修复脚本改成「`sense_owner` 裁决优先」之后，两者会互相报红。
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "fixes"))
    from fix_case_fold_residue import load_authority, target_of   # noqa
    exact, owner = load_authority(con)
    off = 0
    for sid, swid, ewid, spell in con.execute(
            "SELECT s.id, s.word_id, e.word_id, e.spelling FROM sense s "
            "JOIN entry e ON e.id=s.entry_id"):
        t, why = target_of(sid, spell, ewid, exact, owner)
        if t is None:
            continue
        if why == "spelling" and t != ewid:
            t = ewid
        if t != swid:
            off += 1
    out.append(("C10", "fix_case_fold_residue.py", "08-20",
                "义项不在权威（sense_owner 裁决 > entry.spelling）说的那一行", off))

    # C11 「参见 vs 变位形式」标题所依赖的信号。`App.tsx` 用
    #     `inflNotes.length > 0 ? '变位形式' : '参见'` 分标题，而 `inflNotes` 来自
    #     `inflection` 表。这 3,881 个词形（`aqui`/`sólo`/`tambien`，全是高频拼写变体）
    #     必须保持「有 exchange、无变形行」，否则标题会静默变回「变位形式」。
    #     ⚠️ **es 没有契约闸**（`contract-check.tsx` 只覆盖意语），
    #        所以渲染层的规则只能在这里从数据侧盯着。这是已知缺口，记在 es-README。
    n = con.execute("""SELECT COUNT(*) FROM dict d
        WHERE COALESCE(d.exchange,'')<>'' AND COALESCE(d.infl,'')=''
          AND EXISTS(SELECT 1 FROM inflection i
                     WHERE i.word_id=d.id AND COALESCE(i.hidden,0)=0)""").fetchone()[0]
    out.append(("C11", "App.tsx:变位形式/参见", "08-20",
                "拼写变体词形冒出了变形行（标题会变回「变位形式」）", n))

    # C12 搜索预计算表的**陈旧性**。这是派生数据，头号风险不是算错，
    #     是「算对了然后 dict 变了没人重算」—— 那时页面上的搜索结果会是旧的，
    #     而查 `search_prefix` 表本身一切正常（[[fix-regression-and-gate]] 的第二种机制）。
    #     ⚠️ 这里只查**指纹**（两个 COUNT，毫秒级）。逐前缀 12,427 条的全量比对
    #        在 `build_search_prefix.py` 自己的闸里，那个要跑十几秒，不适合挂在每次写库后。
    try:
        fp = con.execute("SELECT v FROM search_prefix_meta "
                         "WHERE k='dict_fingerprint'").fetchone()
        now = "%d:%d" % con.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM dict").fetchone()
        stale = 0 if (fp and fp[0] == now) else 1
    except sqlite3.Error:
        stale = 1        # 表不存在 = 没建或被删，同样要报
    out.append(("C12", "build_search_prefix.py", "08-20",
                "搜索预计算表已陈旧（dict 变了没重算）", stale))

    # ── D 组：2026-08-21 拿 it 点测评审的判据来量 es ────────────────────────
    # 🔴 判据 **import it 那一份**，不另写：同一个缺陷在两个语种上用两套判据，
    #    迟早对不上。it 上 808 条，es 只有 11 条 —— es 打磨得更久，但不是 0。
    n = sum(1 for (t,) in con.execute(
        "SELECT target FROM sense_relation WHERE COALESCE(hidden,0)=0") if paren_class(t))
    out.append(("D1", "hide_relation_colloc_residue.py", "08-21",
                "关系目标里的括号残渣（读取路径）", n))

    n = con.execute("""SELECT COALESCE(SUM(k-1),0) FROM (
        SELECT COUNT(*) k FROM collocation WHERE COALESCE(hidden,0)=0
         GROUP BY word_id, text HAVING k>1)""").fetchone()[0]
    out.append(("D2", "hide_relation_colloc_residue.py", "08-21",
                "同一个词的搭配重复出现（读取路径）", n))

    # D3 词头徽标归属不明。**修在展示层**（App.tsx 的 esNounBadge/esVerbBadge），
    #    SQL 查不到 ⇒ 这个数字不会因修复而变，进 ACCEPT 只为「涨了说明数据层来了新的」。
    #    ⚠️ 真正守它的是契约闸（先渲染再断言）。判据与 App.tsx 逐字对应：
    #    名词/专名/形容词共享性数系统，混进没有性数的词类才叫归属不明。
    # ⚠️ 判据第一版是「义项词性全是名词性」，**外审逮到误伤** —— `banco` 有 6 条名词
    #    义项 + 1 条感叹词义项（`¡banco!`），明确的 `el · 阳` 被藏掉了。
    #    会打架的只有**另一种也带性的词类**（冠词/代词/限定词/缩合），
    #    感叹词/介词/动词没有性，不影响名词那一支。与 App.tsx 逐字对应。
    NOMINAL = {"n", "name", "adj"}
    GENDERED = {"art", "pron", "det", "contr"}
    scope = {}
    for wid, pos in con.execute(
            "SELECT word_id, pos FROM sense WHERE pos IS NOT NULL AND pos<>''"):
        scope.setdefault(wid, set()).add(pos)
    n = 0
    for wid, g, pl in con.execute("SELECT id, gender, plural FROM dict"):
        sc = scope.get(wid)
        if sc and (g or pl) and (sc & NOMINAL) and (sc & GENDERED):
            n += 1
    out.append(("D3", "App.tsx 词头徽标守卫", "08-21",
                "词头徽标属性归属不明（展示层已挡，见 ACCEPT）", n))

    # D4 关系区里的英语说明文字。**外审逮到的**（豆包读 `la` 的渲染成品时指出
    #    「相关词模块末尾混入无关的泛语法说明」），我所有确定性判据都没覆盖过这一族。
    # 🔴 判据修了三轮：「全 ASCII」误伤 109 条西语谚语（西语字母本来就是 ASCII）→
    #    双向语言判据（含英语功能词且不含西语功能词）→ 加 8 种精确名单
    #    （`If le` 只有 5 个字符，长度判据够不到；`se3`/`ello5` 是 `se³`/`ello⁵`
    #     的上标被压成了数字）。合计藏 635 条。
    #    ⚠️ 残差记账：`kind='related'` 且目标在 dict 里查不到的仍有约 970 条，
    #       其中含真西语短语（`¿necesitáis ayuda?`），判据够不到 ⇒ 只作上界。
    n = sum(1 for (t,) in con.execute(
        "SELECT target FROM sense_relation WHERE COALESCE(hidden,0)=0") if is_english_note(t))
    out.append(("D4", "hide_english_relation_notes.py", "08-21",
                "关系区里混进英语说明文字（读取路径）", n))
    return out


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
    print("═" * 108)
    print("C 组 · 词条层/变形层 —— 判据是「迁出来的这份与旧列还对不对得上」")
    print("═" * 108)
    print(f"  {'ID':<4} {'来源':<32} {'日期':<6} {'缺陷':<40} {'残留':>10}  判定")
    print("─" * 108)
    for cid, script, date, name, n in run_infl(con):
        acc = ACCEPT.get(cid, 0)
        if n <= acc:
            verdict = "✅ 仍在" if n == 0 else f"✅ 在基线内({acc})"
        else:
            verdict = "❌ 已回归"
            bad_wrote += 1
        print(f"  {cid:<4} {script:<32} {date:<6} {name:<40} {n:>10,}  {verdict}")

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
    # ── D 组（2026-08-21）。⚠️ 变异要挑**目前不在缺陷集里**的行，
    #    否则数字不动 ⇒ 报「漏掉」，而闸其实是好的（it 那轮在 D1 上栽过一次）。
    ("D4 关系区塞一句英语说明",
     "UPDATE sense_relation SET target='Only used in certain circumstances and rarely' "
     "WHERE id=(SELECT id FROM sense_relation WHERE COALESCE(hidden,0)=0"
     "          AND target NOT LIKE '% %' LIMIT 1)"),
    ("D1 关系目标塞一个断括号",
     "UPDATE sense_relation SET target='cuarto (1' WHERE id=("
     "  SELECT id FROM sense_relation WHERE COALESCE(hidden,0)=0"
     "   AND target NOT LIKE '%(%' AND target NOT LIKE '%)%' LIMIT 1)"),
    ("D2 复制一条搭配（rank 另给）",
     "INSERT INTO collocation (word_id,sense_id,text,rank) "
     "SELECT word_id,sense_id,text,9999 FROM collocation c "
     " WHERE NOT EXISTS(SELECT 1 FROM collocation c2 WHERE c2.word_id=c.word_id"
     "                  AND c2.rank=9999) LIMIT 1"),
    # D3 判据读的是 `sense.pos` 集合 ⇒ 变异要打在那儿：挑一个义项**全是名词性**
    # 且词头带 gender 的词，把其中一条义项改成介词，性/复数立刻归属不明。
    ("D3 让一个纯名词词的义项变成介词（性/复数归属立刻不明）",
     "UPDATE sense SET pos='prep' WHERE id=("
     "  SELECT s.id FROM sense s JOIN dict d ON d.id=s.word_id"
     "   WHERE d.gender IS NOT NULL AND d.gender<>'' AND s.pos IS NOT NULL"
     "     AND NOT EXISTS(SELECT 1 FROM sense s2 WHERE s2.word_id=d.id"
     "                    AND s2.pos IS NOT NULL AND s2.pos NOT IN ('n','name','adj'))"
     "   LIMIT 1)"),
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
    # ── C 组：迁出来的这份与旧列对不上 ──────────────────────────────
    # ⚠️ 变异要打在**闸真正比的那一侧**。C 组比的是「新表 vs 旧列」，
    #    所以改新表和改旧列都该报红 —— 下面两个方向各来一个。
    ("C1 删掉一条变形行",
     "DELETE FROM inflection WHERE id=(SELECT MIN(id) FROM inflection)"),
    ("C2 改掉一条变形的中文说明",
     "UPDATE inflection SET label_zh='__篡改__' WHERE id=("
     "  SELECT MIN(i.id) FROM inflection i JOIN dict d ON d.id=i.word_id"
     "   WHERE COALESCE(d.infl,'')<>'')"),
    ("C2b 反过来：改旧列，新表不动",
     "UPDATE dict SET infl=infl||char(10)||'__多出来的一行__' WHERE id=("
     "  SELECT MIN(id) FROM dict WHERE COALESCE(infl,'')<>'')"),
    ("C3 清掉一批义项的挂锚",
     "UPDATE sense SET entry_id=NULL WHERE entry_id IS NOT NULL AND rowid % 7 = 0"),
    ("C4 把一个词条的词性改掉",
     "UPDATE entry SET pos='__x__' WHERE id=("
     "  SELECT MIN(e.id) FROM entry e JOIN sense s ON s.entry_id=e.id WHERE s.pos IS NOT NULL)"),
    ("C5 新造一条大小写折叠残留",
     "UPDATE sense SET entry_id=(SELECT MIN(id) FROM entry WHERE word_id<>1) WHERE id=("
     "  SELECT MIN(id) FROM sense WHERE word_id=1)"),
    ("C7 把一个补收的词头删掉（变形重新悬空）",
     "DELETE FROM dict WHERE id=(SELECT i.base_id FROM inflection i JOIN dict d ON d.id=i.base_id"
     "  WHERE d.phonetic_src='rule' AND d.translation IS NULL AND d.definition IS NULL LIMIT 1)"),
    ("C8 把补收词头的音标来源改掉（模拟被 build.py 重建覆盖）",
     "UPDATE dict SET phonetic_src='kaikki-en' WHERE id IN ("
     "  SELECT d.id FROM dict d WHERE d.phonetic_src='rule' AND d.translation IS NULL"
     "   AND d.definition IS NULL AND d.is_lemma=1 LIMIT 200)"),
    ("C12 往 dict 插一行（预计算表随即陈旧）",
     "INSERT INTO dict(word, word_norm, is_lemma) VALUES ('__mut__','__mut__',1)"),
    ("C10 把一条义项搬回小写行（专名混进常用词）",
     "UPDATE sense SET word_id=(SELECT id FROM dict WHERE word='gracias'), rank=99 "
     "WHERE id=(SELECT s.id FROM sense s JOIN dict d ON d.id=s.word_id"
     "          WHERE d.word='Gracias' LIMIT 1)"),
    ("C9 让一个伪原形在读取路径上复活",
     "UPDATE inflection SET hidden=NULL, base_fixed=NULL WHERE base='tú and vos'"),
    ("C6 造一条重复的 (word_id,seq)",
     "INSERT INTO inflection(word_id,seq,base,base_id,label_zh,src,src_ref)"
     " SELECT word_id,seq,base,base_id,label_zh,src,src_ref||'-mut' FROM inflection LIMIT 1"),
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
    for cid, *_x, n in run_infl(con):
        if n > ACCEPT.get(cid, 0):
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
        for cid, script, _d, name, n in run_infl(con):
            acc = ACCEPT.get(cid, 0)
            if n > acc:
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
