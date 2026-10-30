#!/usr/bin/env python3
"""**ru 回归闸** —— 过去每一个修复，现在还在不在。2026-10-25（阶段 8）。

    python3 ru/tests/test_no_regression.py
    python3 ru/tests/test_no_regression.py --mutate

`dbtool._regression_check()` **每次写库之后自动调用** `check_brief()`（只报不拦：写库已经 commit）。
它让回归在**产生它的那次写库**上报出来，而不是十天后偶然撞见（用户 2026-08-11：「同一个问题你修了，
隔天修其他问题，你又发现之前的问题又出现了」）。

═══ 与层闸的分工 ═══
层闸查不变量（多半是「= 0」）、要手动跑；回归闸查**修复**、每次写库自动跑、锁**非零的已接受基线**。
⚠️ 只用 SQL 计数（每次写库都跑，必须快）；判据重算是层闸和外锚闸的活。

═══ 🔴 基线规矩：每条非零都在这里带理由，「锁数字不锁名字」（`[[fix-regression-and-gate]]`）═══
数字变了就红，哪怕变好。调任何一个基线都要在 `why` 里写清为什么 —— 否则这就成了掩盖回归的开关。
⭐ **付费数据两条（P5/P8）是这道闸最值钱的**：5b 的 331,639 条、6d 的 292,566 条模型中文，
   一次 `--rebuild` 误操作就能静默清掉（层闸只看比例，比例会跟着分母一起掉）。

═══ ⚠️ 读取路径那一半现在是空的 —— **带锁的豁免**（R0）═══
`[[it-regression-gate]]`：在写入列与读取路径各查一次。ru 的展示层（`packages/dict-core/src/russian.ts`）
**还不存在** ⇒ R0：那个文件一出现而 `READ_PATH` 还空着，当场判红。
"""
import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402

F = lambda n: format(n, ",")                                    # noqa: E731
DISPLAY = paths.ROOT / "packages" / "dict-core" / "src" / "russian.ts"
# ══ 读取路径那一半（阶段 9a 补；R0 在 `russian.ts` 出现的那次写库上当场判红、逼出来的）══
# 每条锁**两个数的差额**：写入列总量 − 展示层 WHERE 之后的量。差额是一笔笔有名字的账，变了必须有人解释。
# ⚠️ 只锁展示层那一个数的话，「把 hidden 判据整个关掉」会让它**变大**而不是变小 —— 只有两个数一起看才逮得到。
# 🔴 读取路径 SQL 的 WHERE **抠自 russian.ts 的条件**（hidden = 0／指针的两个条件），不是这里另发明的口径。
# (编号, 名称, 写入列 SQL, 读取路径 SQL, 期望差额, 差额是什么)
READ_PATH = [
    ("RP1", "义项：写入 vs 展示", "SELECT COUNT(*) FROM sense", "SELECT COUNT(*) FROM sense WHERE hidden = 0",
     12779, "藏的义项：zh 元描述／中俄混排待切（R3）／只有语体标签／没有字母"),
    ("RP2", "例句：写入 vs 展示", "SELECT COUNT(*) FROM example", "SELECT COUNT(*) FROM example WHERE hidden = 0",
     2483, "构词示意式 1,280／R3 切不开 615／关系元数据 169／同格重复 151／整条是词头 126／其余"),
    ("RP3", "关系：写入 vs 展示", "SELECT COUNT(*) FROM sense_relation",
     "SELECT COUNT(*) FROM sense_relation WHERE hidden = 0", 244130, "B17 108,451 ＋ 同条目重复 135,679"),
    ("RP4", "录音：写入 vs 展示", "SELECT COUNT(*) FROM audio", "SELECT COUNT(*) FROM audio WHERE hidden = 0",
     167, "张冠李戴 165 ＋ 源头标错/不推荐 2"),
    ("RP5", "词源：写入 vs 展示", "SELECT COUNT(*) FROM etymology", "SELECT COUNT(*) FROM etymology WHERE hidden = 0",
     32113, "fr/vi/pl 第四语言 31,953 ＋ 指针段 157 ＋ 没有字母 3"),
    ("RP6", "读音：写入 vs 展示", "SELECT COUNT(*) FROM pronunciation",
     "SELECT COUNT(*) FROM pronunciation WHERE hidden = 0", 249,
     "源头标错/不推荐 245（P3）＋ 内容不是 IPA 4（P24，B10，2026-10-29）"),
    ("RP7", "指针：证据层 vs 展示的指针", "SELECT COUNT(*) FROM sense_src",
     "SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL AND pointer_target IS NOT NULL", 1168141,
     "已出版的义项（sense_id 有值）＋ 不出版语言的普通释义证据 ＋ 没有结构目标的指针（R22 形动词页）"),
]

# (编号, 名称, SQL, 期望, 当初怎么坏的／为什么是这个数)
CHECKS = [
    ("P1", "词元数", "SELECT COUNT(*) FROM dict WHERE is_lemma=1", 368849,
     "三次修 is_lemma（ru-crit-9 形动词 62,576／crit-10 姓氏变格 132,938／crit-15 副动词 75,782），"
     "分母虚胖过 42%。**锁数**：判据再动一次它就变，变了必须有人解释"),
    ("P2", "带重音符的词头", "SELECT COUNT(*) FROM dict WHERE instr(word, char(769))>0 OR instr(word, char(768))>0",
     1, "R13 并掉 7 个；剩的 1 个是 `◌́`（维基词典给重音符本身建的条目，重音闸 T11 白名单）"),
    # 🔴 2026-10-29 收窄到「源头标的」：B10 起另有一种藏法（内容不是 IPA，P24），混着数 245 就变 249、两件事分不开
    ("P3", "源头标错的读音藏而不删",
     "SELECT COUNT(*) FROM pronunciation WHERE hidden=1 AND hidden_why IN ('源头标为错误读音','源头标为不推荐')", 245,
     "源头 `неправильно`/proscribed 等；删掉就找不回，清零 hidden 就印给读者"),
    ("P4", "可出版义项", "SELECT COUNT(*) FROM sense WHERE hidden=0", 625800,
     "5a 落库 ＋ 5b 破例 11,496。`--rebuild` 改判据会动它"),
    ("P5", "🔴 付费：5b+5c 模型中文释义", "SELECT COUNT(*) FROM sense_gloss WHERE src='model:deepseek-v4-flash'", 515689,
     "5b 331,639（≈106 元）＋ 5c 184,050（2026-10-26，≈59 元，答案 `ru-C1`/`en-C1`）。**少一条都是付费数据丢了**"
     "（答案文件在 `data/work/ru/gloss_zh/`，可按 id 回收）"),
    ("P6", "破例义项", "SELECT COUNT(*) FROM sense s WHERE EXISTS (SELECT 1 FROM sense_src x WHERE x.sense_id=s.id "
     "AND x.lang IN ('fr','vi','pl'))", 11496, "用户 2026-10-23 拍板：fr/vi/pl 证据只在空白页词元上出版、只挂模型中文"),
    ("P7", "破例义项挂在没有字母的证据上", "SELECT COUNT(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
     "WHERE x.lang IN ('fr','vi','pl') AND x.text NOT GLOB '*[A-Za-zА-яЁё0-9]*'", 0,
     "5b 那一跤：破例盘子漏过判据，55 条 `:` 证据被模型照词头盲推，义项闸 E4 拦下、已撤"),
    ("P8", "🔴 付费：6d 模型中文例句", "SELECT COUNT(*) FROM example_gloss WHERE src='model:deepseek-v4-flash'", 292571,
     "≈108 元。答案文件 `data/work/ru/example_zh/{all,redo}.jsonl`。2026-10-25 R24：292,566 −1（3806 出处搬走后与 zh-t "
     "一句一字不差 ⇒ 源头中文替换模型中文）＋6（出处搬走后行数对上、从答案文件免费落库，R28 的 6 条）"),
    ("P9", "同句借中文", "SELECT COUNT(*) FROM example_gloss WHERE src LIKE '%:同句'", 11834,
     "6a：同词形一字不差的句子借 zh 版的中文（例句闸 X9 逐条找出处）；R24 +1（3806）"),
    ("P10", "删节号被剥成句点", "SELECT COUNT(*) FROM example WHERE text LIKE '...%' AND text_pub LIKE '. %'", 0,
     "6a 第一版判据把 НКРЯ 的 `...` 当垃圾剥成 `.`（抽读逮到）"),
    ("P11", "zh-s 纸质词典重切成对", "SELECT COUNT(*) FROM example WHERE src_ref LIKE '%#p%'", 9063,
     "R3 的例句那一半：按文字交界重切（抽读 60/60）。数变了 ⇒ 重切判据被动过"),
    ("P12", "构词示意式不当例句印", "SELECT COUNT(*) FROM example WHERE hidden_why='构词示意式（词缀页，不是句子）'", 1280,
     "en 版词缀页 `на- + идти → найти`"),
    ("P13", "张冠李戴录音藏", "SELECT COUNT(*) FROM audio WHERE hidden_why LIKE '录音文件名里的词%'", 165,
     "判据三版（1,282→235→165）；第三版的源头第二信号放出 70 条同音/异写，`form_of` 有意不算"),
    ("P14", "B12：同一文件一个词形多行", "SELECT COUNT(*) FROM (SELECT 1 FROM audio GROUP BY word_id, commons_key "
     "HAVING COUNT(*)>1)", 0, "按 url 去重会让 40% 的重复落库（两个按钮播同一个文件）"),
    ("P15", "出版词源里有 `??`", "SELECT COUNT(*) FROM etymology WHERE hidden=0 AND COALESCE(text_pub,text) LIKE '%??%'",
     0, "ru 版 29.6 万段 `От ??` 占位 ＋ 1,777 段行内残留"),
    ("P16", "ru 版可出版词源", "SELECT COUNT(*) FROM etymology WHERE hidden=0 AND src='ru-edition'", 158114,
     "清洗后为空的不落库（源头没给）；数变了 ⇒ 占位判据被动过"),
    ("P17", "ru 版的 related 仍是 related", "SELECT COUNT(*) FROM sense_relation WHERE kind='related' "
     "AND src='ru-edition'", 0, "R1：ru 版 `related` 是构词词族，落 `word_family`"),
    ("P18", "可出版构词词族", "SELECT COUNT(*) FROM sense_relation WHERE kind='word_family' AND hidden=0", 4152020,
     "R1 结清时的数"),
    ("P19", "fr/vi/pl 词源出版了", "SELECT COUNT(*) FROM etymology WHERE hidden=0 AND src IN "
     "('fr-edition','vi-edition','pl-edition')", 0, "三语方针"),
    ("P20", "体对", "SELECT COUNT(*) FROM sense_relation WHERE kind='aspect_pair' AND hidden=0", 16483,
     "按字段分支（en/zh 的 forms）；`noun-from-verb` 不收"),
    ("P21", "屈折层行数", "SELECT COUNT(*) FROM inflection", 6387251, "阶段 3；数变了 ⇒ 屈折判据或词元判据被动过"),
    ("P22", "R29：中文简体出版正文", "SELECT (SELECT COUNT(*) FROM sense_gloss WHERE text_pub IS NOT NULL)"
     "+(SELECT COUNT(*) FROM example_gloss WHERE text_pub IS NOT NULL)"
     "+(SELECT COUNT(*) FROM sense_src WHERE text_pub IS NOT NULL)", 138188,
     "2026-10-25 `zh_pub.py`：释义 25,920（5c 新译文里模型漏转的繁体 ＋52）＋ 例句译文 16,883（R24 借来的 3806 ＋1）＋ 指针说明 95,385；掉了 ⇒ 页面回到繁简混排"),
    ("P23", "R29：「覆上」没被改成「复上」", "SELECT (SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND "
     "COALESCE(text_pub,text) LIKE '%覆上%')+(SELECT COUNT(*) FROM example_gloss WHERE lang='zh' AND "
     "COALESCE(text_pub,text) LIKE '%覆上%')", 92,
     "6d 回收时整段 OpenCC t2s 把 23 条「覆上（盖）」改成「复上」（OpenCC 短语表的古义），已从答案文件改回；5c 新译文里又有 23 处正确的「覆上」（69→92）；"
     "少了 ⇒ 有人又整段 t2s 了"),
    ("P24", "内容不是 IPA 的读音藏而不印（B10）",
     "SELECT COUNT(*) FROM pronunciation WHERE hidden=1 AND hidden_why='不是 IPA（B10）'", 4,
     "`criteria.NOT_IPA`（十门同一份判据）：`сердечный → 5`、`во → v0` ×2、两条读音粘成一串夹 `0`。"
     "少了 ⇒ 判据被放松或有人清零 hidden；多了 ⇒ 源头新来了，逐条看过再改数"),
]
# R0c：中文的读取路径必须读 `text_pub`（R29）—— 这几段在 russian.ts 里抠不到 ⇒ 展示层回到繁体原文
ZH_READ = ("COALESCE(g.text_pub, g.text) FROM sense s JOIN sense_gloss g",
           "COALESCE(g.text_pub, g.text) AS text, g.src FROM sense_gloss g",
           "COALESCE(text_pub, text) FROM example_gloss WHERE example_id = x.id AND lang = 'zh'",
           "COALESCE(x.text_pub, x.text) AS text, x.src, x.pointer_target")
# 🔴🔴 2026-10-30（B23 那一类）：原来是 `["R0"] + [c[0] for c in CHECKS] + …` —— **从检查列表推出来的**，
#    于是从 CHECKS 里删掉一条，花名册跟着少一条，`roster_check` 照样对得上：它只逮得到「列表里有而没跑」，
#    逮不到「整条被删了」（vi 栽过的正是后者：P12/P13 被整段替换切走，正常跑报全绿）。
#    ⇒ 独立写死。加一条检查 ⇒ 这里也要加，不加就红 —— 那正是它存在的理由（`[[expectation-must-be-declared]]`）。
ROSTER = ["R0",
          "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11", "P12",
          "P13", "P14", "P15", "P16", "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24",
          "RP1", "RP2", "RP3", "RP4", "RP5", "RP6", "RP7",
          "R0b", "R0c"]


def run_all(con):
    """→ [(编号, 名称, 实测, 期望, 理由)]"""
    out = []
    # R0：读取路径那一半的带锁豁免
    out.append(("R0", "展示层出现而读取路径没补", 1 if (DISPLAY.exists() and not READ_PATH) else 0, 0,
                "`%s` 一出现就必须补 READ_PATH（写入列 vs 展示层 WHERE 的差额）" % DISPLAY.name))
    for cid, name, sql, want, why in CHECKS:
        out.append((cid, name, con.execute(sql).fetchone()[0], want, why))
    for cid, name, wsql, rsql, want, why in READ_PATH:
        out.append((cid, name, con.execute(wsql).fetchone()[0] - con.execute(rsql).fetchone()[0], want, why))
    # R0b：READ_PATH 的读取路径条件必须**真的出现在 russian.ts 里**（抠不到 ⇒ 展示层换了口径而这里没跟）
    if DISPLAY.exists():
        ts = DISPLAY.read_text(encoding="utf-8")
        miss = [c for c, _n, _w, r, _e, _y in READ_PATH
                if r.split("WHERE", 1)[1].strip().split(" AND ")[0] not in ts]
        out.append(("R0b", "读取路径条件在 russian.ts 里找不到", len(miss), 0, "找不到的：%s" % miss))
        zmiss = [z for z in ZH_READ if z not in ts]
        out.append(("R0c", "中文读取路径不读简体 text_pub", len(zmiss), 0, "找不到的：%s" % zmiss))
    return out


def check_brief():
    """给 `dbtool` 用：→ **[(编号, 名称, 说明)]**，空列表＝全绿。🔴 元数必须是 3（vi 的第一版写成 2，报警时自己炸了）。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        return [(cid, name[:36], "实测 %s，期望 %s" % (F(got), F(want)))
                for cid, name, got, want, _why in run_all(con) if got != want]
    finally:
        con.close()


def roster_check(rows):
    got = [r[0] for r in rows]
    if got != ROSTER:
        return ["花名册对不上：多 %s ／ 少 %s" % (sorted(set(got) - set(ROSTER)), sorted(set(ROSTER) - set(got)))]
    return []


def report():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        rows = run_all(con)
    finally:
        con.close()
    print("■ 回归闸（ru 阶段 8）—— 花名册 %d 条" % len(ROSTER))
    red = 0
    for cid, name, got, want, why in rows:
        ok = got == want
        red += not ok
        print("   %s %-4s %-30s 实测 %12s ／ 期望 %12s%s" % ("✅" if ok else "🔴", cid, name, F(got), F(want),
                                                       "" if ok else "  —— " + why))
    rb = roster_check(rows)
    for b in rb:
        print("   🔴🔴 花名册自检：" + b)
    print("■ %s" % ("全绿 ✓（过去的修复都还在）" if not red and not rb else "%d 条红" % (red + len(rb))))
    return red + len(rb)


def _mutations():
    """每条一个注入，只许它自己红（回归闸的检查彼此独立：都是单表计数）。"""
    return [
        ("R0", "展示层文件出现而 READ_PATH 为空", None),
        ("P1", "一个屈折形被标回词元", "UPDATE dict SET is_lemma=1 WHERE id=(SELECT MIN(id) FROM dict WHERE is_lemma=0)"),
        ("P2", "一个词头带上重音符", "UPDATE dict SET word=word||char(769) WHERE id=(SELECT MIN(id) FROM dict "
         "WHERE is_lemma=0)"),
        ("P3", "藏的读音被放出来", "UPDATE pronunciation SET hidden=0 WHERE id=(SELECT MIN(id) FROM pronunciation "
         "WHERE hidden=1 AND hidden_why IN ('源头标为错误读音','源头标为不推荐'))"),
        ("P24", "一条「不是 IPA」的读音被放出来", "UPDATE pronunciation SET hidden=0 WHERE id=(SELECT MIN(id) "
         "FROM pronunciation WHERE hidden_why='不是 IPA（B10）')"),
        ("P4", "一条可出版义项被藏", "UPDATE sense SET hidden=1 WHERE id=(SELECT MIN(id) FROM sense WHERE hidden=0)"),
        ("P5", "删一条付费中文释义", "DELETE FROM sense_gloss WHERE id=(SELECT MIN(id) FROM sense_gloss WHERE "
         "src='model:deepseek-v4-flash')"),
        ("P6", "一条破例义项的证据脱钩", "UPDATE sense_src SET sense_id=NULL WHERE id=(SELECT MIN(id) FROM sense_src "
         "WHERE lang='fr' AND sense_id IS NOT NULL)"),
        ("P7", "一条破例证据的文本变成标点", "UPDATE sense_src SET text=':' WHERE id=(SELECT MIN(id) FROM sense_src "
         "WHERE lang='fr' AND sense_id IS NOT NULL)"),
        ("P8", "删一条付费中文例句", "DELETE FROM example_gloss WHERE id=(SELECT MIN(id) FROM example_gloss WHERE "
         "src='model:deepseek-v4-flash')"),
        ("P9", "删一条借来的中文", "DELETE FROM example_gloss WHERE id=(SELECT MIN(id) FROM example_gloss WHERE "
         "src LIKE '%:同句')"),
        ("P10", "删节号被剥成句点", "UPDATE example SET text_pub='. '||substr(text,5) WHERE id=(SELECT MIN(id) FROM "
         "example WHERE text LIKE '...%')"),
        ("P11", "一对 zh-s 重切行被删", "DELETE FROM example WHERE id=(SELECT MIN(id) FROM example WHERE src_ref LIKE '%#p%') "
         "AND id NOT IN (SELECT example_id FROM example_gloss WHERE src LIKE '%:同句' OR src LIKE 'model:%')"),
        ("P12", "构词示意式被放出来", "UPDATE example SET hidden=0, hidden_why=NULL WHERE id=(SELECT MIN(id) FROM "
         "example WHERE hidden_why='构词示意式（词缀页，不是句子）')"),
        ("P13", "一条张冠李戴录音被放出来", "UPDATE audio SET hidden=0, hidden_why=NULL WHERE id=(SELECT MIN(id) FROM "
         "audio WHERE hidden_why LIKE '录音文件名里的词%')"),
        ("P14", "B12 复发", "INSERT INTO audio(word_id,entry_id,url,commons_key,hidden,hidden_why,src) SELECT word_id,"
         "entry_id,url||'«变异»',commons_key,1,'«变异»',src FROM audio LIMIT 1"),
        ("P15", "占位回到出版词源", "UPDATE etymology SET text_pub=COALESCE(text_pub,text)||' ??' WHERE id=(SELECT MIN(id) "
         "FROM etymology WHERE hidden=0 AND src='en-edition')"),
        ("P16", "一段 ru 版词源被藏", "UPDATE etymology SET hidden=1, hidden_why='«变异»' WHERE id=(SELECT MIN(id) FROM "
         "etymology WHERE hidden=0 AND src='ru-edition')"),
        ("P17", "一条词族退回 related", "UPDATE sense_relation SET kind='related' WHERE id=(SELECT MIN(id) FROM "
         "sense_relation WHERE kind='word_family' AND hidden=1)"),
        ("P18", "一条可出版词族被藏", "UPDATE sense_relation SET hidden=1, hidden_why='«变异»' WHERE id=(SELECT MIN(id) "
         "FROM sense_relation WHERE kind='word_family' AND hidden=0)"),
        ("P19", "fr 版词源被放出来", "UPDATE etymology SET hidden=0, hidden_why=NULL WHERE id=(SELECT MIN(id) FROM "
         "etymology WHERE src='fr-edition')"),
        ("P20", "一条体对被删", "DELETE FROM sense_relation WHERE id=(SELECT MIN(id) FROM sense_relation WHERE "
         "kind='aspect_pair' AND hidden=0)"),
        ("P21", "删一行屈折", "DELETE FROM inflection WHERE id=(SELECT MIN(id) FROM inflection)"),
        # 读取路径：插一行**藏着的**合成行 ⇒ 写入总量 +1、展示量不变 ⇒ 只有差额那条红
        ("RP1", "插一条藏着的义项", "INSERT INTO sense(id,word_id,entry_id,rank,hidden,hidden_why) "
         "SELECT -1,word_id,entry_id,0,1,'«变异»' FROM sense LIMIT 1"),
        ("RP2", "插一条藏着的例句", "INSERT INTO example(id,word_id,entry_id,sense_id,text,text_pub,ref,hidden,hidden_why,"
         "src,src_ref) SELECT -1,word_id,entry_id,NULL,'«变异»',NULL,NULL,1,'«变异»',src,'«变异»' FROM example LIMIT 1"),
        ("RP3", "插一条藏着的关系", "INSERT INTO sense_relation(id,word_id,entry_id,sense_id,kind,target,hidden,hidden_why,"
         "src,src_ref) SELECT -1,word_id,entry_id,NULL,'«变异»','«变异»',1,'«变异»',src,'«变异»' FROM sense_relation LIMIT 1"),
        ("RP4", "插一条藏着的录音", "INSERT INTO audio(id,word_id,entry_id,url,commons_key,hidden,hidden_why,src) "
         "SELECT -1,word_id,entry_id,url||'«变异»','«变异»',1,'«变异»',src FROM audio LIMIT 1"),
        ("RP5", "插一段藏着的词源", "INSERT INTO etymology(id,word_id,entry_id,etym_no,etym_sub,text,src_field,hidden,"
         "hidden_why,src,src_ref) SELECT -1,word_id,entry_id,etym_no,etym_sub,'«变异»',src_field,1,'«变异»',src,'«变异»' "
         "FROM etymology WHERE src='fr-edition' LIMIT 1"),
        ("RP6", "插一条藏着的读音", "INSERT INTO pronunciation(id,word_id,entry_id,ipa,dialect,notation,tags,hidden,"
         "hidden_why,src,src_ref) SELECT -1,word_id,entry_id,'«变异»',dialect,notation,NULL,1,'«变异»',src,'«变异»' "
         "FROM pronunciation WHERE hidden=1 LIMIT 1"),
        ("RP7", "插一条已出版义项的证据", "INSERT INTO sense_src(id,word_id,entry_id,sense_id,lang,text,pointer_target,src,"
         "src_ref) SELECT -1,word_id,entry_id,sense_id,lang,'«变异»',NULL,src,'«变异»' FROM sense_src "
         "WHERE sense_id IS NOT NULL LIMIT 1"),
        ("P22", "一条指针说明的简体出版正文被清空", "UPDATE sense_src SET text_pub=NULL WHERE id=(SELECT MIN(id) "
         "FROM sense_src WHERE text_pub IS NOT NULL)"),
        ("P23", "一条「覆上」又被改成「复上」", "UPDATE example_gloss SET text=replace(text,'覆上','复上') WHERE id=("
         "SELECT MIN(id) FROM example_gloss WHERE text_pub IS NULL AND text LIKE '%覆上%')"),
        ("R0b", "展示层换了口径（russian.ts 里没有 hidden = 0 了）", "DISPLAY"),
        ("R0c", "展示层的中文回到读 text（不读 text_pub）", "DISPLAY_ZH"),
    ]


# 变异的**已声明连带红**（先跑看实际、逐条核过再写）。🔴 补了读取路径 RP1–RP7 之后，「每条只许它自己红」不再成立 ——
#    RP 锁的就是「写入 − 展示」的差额，任何「藏/放出一行」的变异都**必然**同时动它，这正是两个数一起锁的意义。
ALSO = {
    "P3": {"RP6"}, "RP6": {"P3"},          # 藏着的读音：P3 数 hidden=1、RP6 数差额 —— 同一批行
    "P24": {"RP6"},                        # B10 那 4 条也在 RP6 的差额里
    "P4": {"RP1"},                         # 藏一条义项 ⇒ 差额 +1
    "P12": {"RP2"},                        # 放出构词示意式 ⇒ 差额 −1
    "P13": {"RP4"}, "P14": {"RP4"},        # 录音放出/多插一行藏着的
    "P16": {"RP5"}, "P19": {"RP5"},        # 词源藏/放
    "P18": {"RP3"},                        # 藏一条词族
    # 假的 russian.ts 一行源码都没有 ⇒ 中文读取路径（R0c）必然一起找不到
    "R0": {"R0c"}, "R0b": {"R0c"},
}


def mutate():
    global DISPLAY
    if report():
        print("\n🔴 基线就不绿，先修基线")
        return 1
    real = paths.DB
    fails = []
    muts = _mutations()
    print("\n■ 变异验证（%d 条，跑在库的副本上；连带红必须逐条声明）" % len(muts))
    with tempfile.TemporaryDirectory() as td:
        cp = Path(td) / real.name
        for cid, why, sql in muts:
            shutil.copy2(real, cp)
            paths.DB = cp
            saved = DISPLAY
            try:
                if sql == "DISPLAY_ZH":         # R0c：真文件，只把中文读取路径换回读 text
                    fake = Path(td) / "russian.ts"
                    fake.write_text(saved.read_text(encoding="utf-8").replace("text_pub, g.text", "text, g.text")
                                    .replace("COALESCE(text_pub, text) FROM example_gloss", "text FROM example_gloss")
                                    .replace("x.text_pub, x.text) AS text, x.src, x.pointer", "x.text, x.text) AS text"
                                             ", x.src, x.pointer"), encoding="utf-8")
                    DISPLAY = fake
                elif sql is None or sql == "DISPLAY":
                    fake = Path(td) / "russian.ts"
                    fake.write_text("// «变异»", encoding="utf-8")
                    DISPLAY = fake
                    if sql == "DISPLAY":       # R0b：文件在、READ_PATH 不空，但条件在源码里找不到
                        pass
                    else:                      # R0：文件在而 READ_PATH 为空
                        globals()["READ_PATH"], saved_rp = [], READ_PATH
                else:
                    con = sqlite3.connect(cp)
                    con.execute(sql)
                    con.commit()
                    con.close()
                got = {c for c, _n, _w in check_brief()}
                if cid in got and not (got - {cid} - ALSO.get(cid, set())):
                    print("   ✅ %-4s %s" % (cid, why))
                elif cid in got:
                    print("   🔴 %-4s 逮到了，**但还有别的红 %s** —— %s" % (cid, sorted(got - {cid}), why))
                    fails.append(cid)
                else:
                    print("   🔴🔴 %-4s **没逮到**（红的是 %s）—— %s" % (cid, sorted(got), why))
                    fails.append(cid)
            finally:
                DISPLAY = saved
                if sql is None:
                    globals()["READ_PATH"] = saved_rp
                paths.DB = real
    # 花名册自检自己的变异（B23 那一类，2026-10-30）：一条检查**整条被删**，花名册必须报「少了它」。
    #    原来 ROSTER 从 CHECKS 推出来，这条变异会空过 —— 这里每次都证明一遍它没有退回去。
    con = sqlite3.connect("file:%s?mode=ro" % real, uri=True)
    try:
        rows = run_all(con)
    finally:
        con.close()
    gone = rows[len(rows) // 2][0]
    caught = bool(roster_check([r for r in rows if r[0] != gone]))
    print("   %s 花名册  删掉一整条检查（%s）%s" % ("✅" if caught else "🔴🔴", gone, " → 判红" if caught else " —— **没逮到**"))
    if not caught:
        fails.append("ROSTER")
    if report():
        print("\n🔴🔴 反控制失败：真库基线不绿了")
        return 1
    print("\n%s" % ("■ 变异验证全过 ✓，反控制：真库基线仍全绿" if not fails else "🔴 %d 条没过：%s" % (len(fails), fails)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    return mutate() if a.mutate else (1 if report() else 0)


if __name__ == "__main__":
    raise SystemExit(main())
