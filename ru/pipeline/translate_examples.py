#!/usr/bin/env python3
"""阶段 6d：把**俄语例句**译成中文。ru，2026-10-24。**花钱** —— 报价与开跑分两次拍板。

    python3 -u ru/pipeline/translate_examples.py --slice 0.01     # 实测单价，**先跑这个**
    python3 -u ru/pipeline/translate_examples.py                  # 全量（先看报价、等拍板）
    python3 -u ru/pipeline/translate_examples.py --load           # 干跑回收
    python3 -u ru/pipeline/translate_examples.py --load --apply   # 写库

═══ 免费路径走到底了（`[[prove-free-path-before-quoting]]`）═══
阶段 6a 已经把能白拿的中文全拿了：zh-t/zh-s 源头译文 22,240 ＋ **同词形一字不差的句子借用 11,833**
（例句闸 X9 逐条找出处）＋ zh-s 纸质词典重切 9,063 对。剩下 295,897 条在七版里**没有任何中文**；
其中 17,355 条有英译 —— 译英文也要花同样的钱，而且是二手翻译，**不走**。

═══ 只翻 `text_pub`（出版正文），不翻 `text`（dump 原文）═══
fr 版的法语尾巴、`◆` 项目符号在 `text_pub` 里已经切掉；翻 `text` 就是花钱翻垃圾。

═══ 🔴 控制组：验的是**每一个输出字段**（`[[control-must-cover-every-output-field]]`）═══
输出只有 `zh` 一个字段，四种坏法各对一条：
    ① 错位      —— 定题（答案确定），每批轮流塞一条、键混在中间
    ② 静默丢批  —— 逐 id 点名；丢的对半切重试，封顶、到顶大声放弃
    ③ 答非所问  —— 空／没有一个汉字／译文里的俄语串原文没有（词干级，5 个字母）
    ④ 多行错位  —— 诗、对白是多行的，译文行数必须对得上（vi 6e 的那条）
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
import paths                                                    # noqa: E402
from pipeline import criteria, ds_batch                         # noqa: E402

OUT = paths.WORK / "example_zh"
PER_BATCH = 10          # 俄语例句中位 91 字符（vi 30），批小一点
F = lambda n: format(n, ",")                                    # noqa: E731
SRC_MODEL = "model:deepseek-v4-flash"

SYS = """你是俄汉词典的例句编辑。把给定的俄语例句译成中文。

输入是一个 JSON 对象：键是例句编号，值含 w（这条例句所属的俄语词头）、t（例句原文）。
输出**同样的键**，值是 {"zh": "中文译文"}。键一个不许少、不许多、不许改。

规矩：
1. 译成**自然的简体中文**（不要繁体），不要逐字硬译。例句是给中文读者看怎么用这个词的。
2. 🔴 **行数必须与原文一致。** 原文是多行的（诗、歌词、对白），译文也必须是同样行数的多行，
   用 \\n 分隔，一行对一行；**原文只有一行的，译文也只能一行**。
3. w 是**帮你消歧**的那个词头，译文里要能看出它在这句话里的意思，但**不要**把俄语词头本身写进译文。
4. 只译例句本身。不要加「这句话的意思是」这类引导语，不要加解释、注释、原文、拼音。
5. 原文里的重音符（а́、е́ 这类字母上的撇）只是标重音，不影响意思。
6. 原文里的方括号、省略号原样保留：`[…]`、`⟨…⟩`、`..`、`...` 是源头的删节号，
   `[НКРЯ]` 这类方括号是出处标记 —— 删掉它们等于改了引文。
7. 人名、地名、书名按通行中文译名；没有通行译名的音译要克制，拿不准的保留原文拼写。
8. 吃不准的直译，**不要编造**，不要为了通顺增添原文没有的信息。
9. 粗俗语、俚语照实译出语气，不要净化成书面语，也不要加重。
10. 原文是改革前正字法（带 ѣ、і、ъ 词尾）的，照现代俄语理解，译成现代中文即可。"""

# 定题。答案**确定**，只回答一个问题：这个键上的答案是不是这个键的题目给出来的。
# ⚠️ 5b 的教训：第一版定题 `вода → 水` 答案错了（那是「液体」义项的题）—— 定题的答案要先自己核。
PROBE = {
    "__c1": {"w": "вода", "t": "Я пью воду.", "want": ("水",)},
    "__c2": {"w": "кошка", "t": "У меня есть кошка.", "want": ("猫",)},
    "__c3": {"w": "Москва", "t": "Я живу в Москве.", "want": ("莫斯科",)},
    "__c4": {"w": "врач", "t": "Мама — врач.\nПапа — учитель.", "want": ("医生", "大夫"), "lines": 2},
}


def gap_rows(con):
    """缺中文译文的**可出版**、**需要翻译**的例句 → [(id, 词头, 出版正文)]。口径只写一份。

    词缀页的构词示意不进付费范围（`criteria.example_needs_translation`，1% 切片逼出来的）。
    """
    #   R28：`R28_NO_ZH` 的 6 条（型号／缩写／字母名表）人读裁定**不需要译文**
    return [r for r in _gap_rows_raw(con) if criteria.example_needs_translation(r[1]) and r[0] not in R28_NO_ZH]


def _gap_rows_raw(con):
    return list(con.execute("""
        SELECT e.id, d.word, COALESCE(e.text_pub, e.text)
        FROM example e JOIN dict d ON d.id = e.word_id
        WHERE e.hidden = 0
          AND NOT EXISTS (SELECT 1 FROM example_gloss g WHERE g.example_id = e.id AND g.lang = 'zh')
        ORDER BY e.id"""))


def pick_slice(rows, frac):
    """按 id 的稳定哈希抽（不是 `rows[::n]` —— 按顺序抽会抽出一整片同一版）。"""
    k = int(frac * 0xFFFF)
    return [r for r in rows if int(hashlib.md5(str(r[0]).encode()).hexdigest()[:4], 16) < k]


def already(path):
    out = set()
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:                    # noqa: BLE001
                continue
            if isinstance(d.get("id"), int):
                out.add(d["id"])
    return out


def build(rows, per=None):
    per = per or PER_BATCH
    batches, meta = [], []
    for i in range(0, len(rows), per):
        chunk = rows[i:i + per]
        items = [(str(eid), {"w": w, "t": t}) for eid, w, t in chunk]
        ck = list(PROBE)[i // per % len(PROBE)]
        items.insert(len(items) // 2, (ck, {x: PROBE[ck][x] for x in ("w", "t")}))
        batches.append(dict(items))
        meta.append([(k, int(k) if k.isdigit() else k) for k, _v in items])
    return batches, meta


def normalize_zh(t, src_lines=None):
    """首尾/行尾空白；**原文只有一行时把译文的换行并掉**（vi 6e 切片逼出来的，内容一个字不丢）。

    🔴 1% 切片 3,284 条里 12 条整句是繁体（`媽媽是醫生`，连定题都中了），而且**成片**出现 ——
       整批漂成繁体。prompt 已补「简体」，但格式一致性**在代码里确定性归一，不靠 prompt 保证**（5b 的原则）。
    🔴🔴 2026-10-25（R29）：繁→简**不在这里做了**，搬到出版正文 `example_gloss.text_pub`
       （`criteria.zh_simp`）。这里原先整段 `OpenCC t2s`，在**本来就是简体**的译文上改错了：
       `头发覆上了一片银白→复上`、`藉着→借着`（这条倒是对的）、`“乾”的意义→干`、`薹草→苔草`、
       `麻鳽→麻𫛚`（扩展平面，豆腐块）。⇒ `text` 存模型原话，安全的那道转换只有一个家。
    """
    out = "\n".join(l.rstrip() for l in (t or "").strip().split("\n"))
    if src_lines == 1 and "\n" in out:
        out = "".join(l.strip() for l in out.split("\n"))
    return out


_HAN = re.compile(r"[㐀-鿿]")
_CYR_WORD = re.compile(r"[А-Яа-яЁё][А-Яа-яЁё\-́]+")


def _stem(x):
    return x.replace("́", "").lower().replace("ё", "е")[:5]


def audit(path, rows, ntok, peak):
    got = {}
    for line in path.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:                        # noqa: BLE001
            continue
        got[d["id"]] = d.get("zh")
    want = {eid for eid, *_ in rows}
    print("\n═══ 控制组 ═══")
    ctl_bad = []
    for k, v in PROBE.items():
        ans = got.get(k)
        if ans is None:
            ctl_bad.append((k, "没回来"))
        elif not any(x in ans for x in v["want"]):
            ctl_bad.append((k, "答成了 %r（该含 %s）" % (ans, "/".join(v["want"]))))
        elif v.get("lines") and len(ans.split("\n")) != v["lines"]:
            ctl_bad.append((k, "🔴 多行没对齐：答成 %d 行，该 %d 行" % (len(ans.split("\n")), v["lines"])))
    print("   %s 定题对齐        %d/%d" % ("✅" if not ctl_bad else "🔴", len(PROBE) - len(ctl_bad), len(PROBE)))
    for k, why in ctl_bad:
        print("      🔴 %s %s" % (k, why))
    miss = want - set(got)
    print("   %s 逐 id 点名       回来 %s / 要 %s（丢 %s）"
          % ("✅" if not miss else "🔴", F(len(want & set(got))), F(len(want)), F(len(miss))))
    # 🔴🔴 **字段错位**：id 回来了而 `zh` 字段不在 —— 全量 39 条把译文写进了 `t`（输入字段名）。
    #    第一版点名只认 id，报「丢 0」；形状检查又 `if zh is None: continue` 跳过它们 ⇒ **两条检查一致失明**。
    #    `[[control-must-cover-every-output-field]]` 那一课在本文件里又漏了一次：点名要点到**字段**。
    nozh = sorted(i for i in want & set(got) if not got[i])
    print("   %s 字段点名（zh）    缺 %s" % ("✅" if not nozh else "🔴", F(len(nozh))))
    bad, samples = collections.Counter(), collections.defaultdict(list)
    for eid, w, t in rows:
        zh = got.get(eid)
        if zh is None:
            continue
        nl = len(t.split("\n"))
        why = None
        if not zh.strip():
            why = "空"
        elif not _HAN.search(zh):
            why = "没有一个汉字（多半没翻译／拒译）"
        elif nl != len(normalize_zh(zh, nl).split("\n")):
            why = "🔴 行数不对：原文 %d 行，译文 %d 行" % (nl, len(zh.split("\n")))
        else:
            src_st = {_stem(x) for x in _CYR_WORD.findall(t)} | {_stem(w or "")}
            extra = sorted({x for x in _CYR_WORD.findall(zh) if len(x) > 2 and _stem(x) not in src_st})
            if extra:
                why = "🔴 译文里的俄语串原文没有（疑似幻觉）"
        if why:
            bad[why] += 1
            if len(samples[why]) < 4:
                samples[why].append((w, t[:50].replace("\n", "⏎"), zh[:50].replace("\n", "⏎")))
    n = len(want & set(got))
    print("   %s 形状             坏 %d / %s" % ("✅" if not bad else "⚠️", sum(bad.values()), F(n)))
    for k, v in bad.most_common():
        print("      ⚠️ %-34s %d" % (k, v))
        for w, t, zh in samples[k]:
            print("           %-14s %-50s → %s" % (w, t, zh))
    if ntok:
        print("\n═══ 单价（%s）═══" % ("🔴 高峰全价" if peak else "✅ 空闲半价"))
        print("   总 token %s ／ 成功 %s 条 ⇒ **每条 %.1f token**" % (F(ntok), F(n), ntok / max(n, 1)))
    print("\n■ 抽样（人眼看 —— 形状检查看不出「译错了」）")
    import random
    for eid, w, t in random.Random(7).sample([r for r in rows if r[0] in got], min(20, n)):
        print("   %-16s %s" % (w, t[:90].replace("\n", " ⏎ ")))
        print("   %-16s → %s" % ("", (got[eid] or "")[:90].replace("\n", " ⏎ ")))
    return bad, miss, ctl_bad


def run(rows, tag, conc, allow_peak, retry_rounds=3, per=None):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("%s.jsonl" % tag)
    peak = ds_batch.is_peak()
    ds_batch.announce_window()
    if peak and not allow_peak:
        raise SystemExit("🔴 现在是 DeepSeek 高峰（全价）—— 不开跑。真要跑加 --allow-peak")
    ntok = 0
    per = per or PER_BATCH
    for rnd in range(retry_rounds + 1):
        done = already(path)
        todo = [r for r in rows if r[0] not in done]
        if not todo:
            break
        if rnd:
            per = max(1, per // 2)
            print("■ 第 %d 轮补跑：丢了 %s 条，批大小对半到 %d" % (rnd, F(len(todo)), per))
        batches, meta = build(todo, per)
        ntok += asyncio.run(ds_batch.run(SYS, batches, meta, path, conc=conc))
    # 🔴 `already(path)` 只读一次 —— 第一版写在列表推导里，29 万行 × 每行重读一遍 29 万行的答案文件，
    #    全量跑完卡在这一行 10 分钟 CPU 不出结果（上一次会话 5b 的探针栽过同一跤：`set(flip)` 建在循环里）。
    done = already(path)
    left = [r for r in rows if r[0] not in done]
    if left:
        print("🔴🔴 对半切 %d 轮之后仍有 %s 条没回来 —— **大声放弃**，不静默丢：%s"
              % (retry_rounds, F(len(left)), [r[0] for r in left[:20]]))
    (OUT / ("%s.tokens.json" % tag)).write_text(json.dumps({"tokens": ntok, "peak": peak}), encoding="utf-8")
    return path, ntok, peak


def model_zh_text(src, text, text_pub, answer):
    """答案 → 该落库的模型中文。→ (中文, 答案生成时那份正文的行数)。**一个家**（落库与 R29/R24 同步都问它）。

    R24（2026-10-25）：en 版 18 条例句的首行是出处，后来搬进了 `ref`。答案是按**搬之前**的正文生成的：
      · 模型把出处也译了（行数 ＝ 搬之前）⇒ 去掉译文第一行（那是出处的译文，出处本身已在 ref 里印原文）；
      · 模型跳过了出处（行数 ＝ 搬之后）⇒ 原样（6d 回收时它们因「行数不对」落选，R28 那 9 条里的 6 条）。
    """
    full = criteria.example_text_pub(src, text)
    _body, head = criteria.example_split_citation(src, full)
    nl = len(full.split("\n")) if head else len((text_pub or text).split("\n"))
    a = normalize_zh(answer, nl)
    if head and len(a.split("\n")) == nl:
        a = "\n".join(a.split("\n")[1:]).strip()
    return a, nl


# ═══ R28（2026-11-05）：6d 回收时形状不过的 66 条，**人读逐条裁决** ═══
# 判据「译文里的俄语串原文没有」把**合法引用**（`по-русски зубным врачом` → 「用俄语说就是 зубной врач」、
#   字母名 `фита`、缩写 `БУР`）与**半截音译**（「卡тков先生」「狄фирамб」）挡在一起。53 条里：
#   · 36 条合法 ⇒ `R28_OK` 原样放行（只跳过那一条俄语串检查，其余形状检查照旧）；
#   · 17 条半截音译／译错 ⇒ `R28_FIXED` 人工改译（按原文意思，不只替换专名：`трусиковый`＝兔毛，模型译成「内裤那种毛线」；
#     `цукание`（军校欺压新生）被译成 `цоканье`（方言发音）；`земобилизация`＝强制动员，不是「土地动员」）。
# 10 条「没有汉字」：`аш два о` 给中文（`R28_FIXED`）；型号／缩写／字母名表 6 条 ⇒ `R28_NO_ZH` **不需要译文**（硬塞＝原文再印一遍）；
#   其余 3 条是源头残渣，已由 `criteria.EXAMPLE_JUNK_ADJUDICATED` 隐藏（不再进待译范围）。
# 3 条「行数不对」（诗行／源头断行）⇒ 按原文分行逐行改写，进 `R28_FIXED`。
# `src` 照记模型来源（底稿是模型的；人工改过的 21 条就是 `R28_FIXED`）。
R28_OK = frozenset({36433, 38356, 45741, 78728, 90906, 92005, 96383, 100812, 111393, 113508, 115331, 126731, 129128,
                    148430, 174821, 174882, 175118, 176715, 199356, 201652, 203932, 215840, 220766, 227421, 232454,
                    239474, 242665, 243572, 245835, 248404, 254733, 254788, 255565, 256503, 261478, 270159})
R28_NO_ZH = frozenset({27437, 39459, 217486, 217487, 217488, 217489})
R28_FIXED = {
    4732: "H₂O（水的化学式）",
    54060: "别利亚宁划分出「明亮的」「阴暗的」「忧伤的」「欢快的」「优美的」和「复杂的」文本。每一种类型的基础都是某种人对待世界的态度，"
           "这种态度是具有一定心理构造的人所特有的。更确切地说，就是心理学家所说的性格突显（акцентуация）——某些个性特征的突出，"
           "它不超出常态范围，赋予个性以独特性，只有在患病时才变得具有破坏性。",
    102281: "谈的是地方自治、省长、道路徭役、赎买契约、彼得堡和莫斯科的共同熟人、卡特科夫先生那所刚刚开办的中学、雇工之难、"
            "罚款和牲畜践踏庄稼，还谈到俾斯麦、六六年战争和拿破仑三世——卡洛梅伊采夫称后者为“好小子”。",
    103932: "关注的中心是礼拜颂歌及其各种类型（“派安”——献给阿波罗，“普罗索迪亚”——同样献给阿波罗的游行颂歌，"
            "“帕尔特尼亚”——供少女演唱的颂歌，“狄提兰博斯”（酒神颂）——献给狄俄尼索斯的颂歌，等等）。",
    117201: "为了检查它们表面的缺陷，全俄航空材料研究院（ВИАМ）研制了毛细管荧光法，借助它可以发现裂口宽度小至0.5微米的裂纹。",
    118308: "在亚历山德罗夫之前几年，「цукание」（高年级欺压低年级的风气）差一点就在莫斯科、在兹纳缅卡街上的那座白房子里牢牢扎下根来："
            "当时不知出于什么隐秘的原因，达吉斯坦至圣公爵从尼古拉耶夫骑兵学校调到了那里，他从彼得堡带来了放荡散漫的作风、"
            "时髦的慵懒卷舌音，还有「цукать」低年级同学这种愚蠢的时髦。",
    161650: "不过，结局倒是十分浪漫：国内战争，还有架着“马克沁”机枪的罗斯托夫式机枪马车（тачанки-ростовчанки）。",
    162693: "这是一个你一走进去就得做好一切心理准备的场所：你沿着漆黑狭窄的走廊摸索前行，这里还有用磷涂过的鬼魂现身，"
            "一只无形的手掐住你的脖子，你顺着某个管道滑下去，落到一些软绵绵的袋子上；而最要紧的是，当你满心欢喜地终于走到"
            "那座灯火通明、悬在空中、暴露在下面人群眼前的桥上时——从下面会刮来一阵狂风，如果你是男人，你的大衣会像两只翅膀"
            "一样向上翻到头顶，帽子会疯狂地飞向空中；如果你是女士，那么所有那些心思轻浮的看客不仅会见识到你吊袜带的颜色，"
            "还会见识到许多别的东西——这些东西不该出现在政治小品文里，而该出现在专写此类题材的米哈伊尔·阿尔志跋绥夫笔下"
            "最精彩、最有力、最浓烈的情色篇章里。",
    166216: "顺便说一句，我非常喜欢 ашка，从很多方面来说，对我来说比 ешка 好得多。",
    177552: "航行已经结束，水兵和军官们都为此高兴。“迅捷”号（«Поспешный»）乘着从波罗的海吹来的上桅帆顺风，满帆返航喀琅施塔得。",
    201521: "尽管《历史》一书的文风整体上庄重肃穆，但其中丝毫没有《品级书》（«Степенная книга»）里那种符合传统“编织辞藻”风格的雄辩式造词。",
    218634: "社会院成员呼吁兹维亚金采夫跪下来请求俄罗斯人民原谅。// 对兹维亚金采夫的判决：ахеджакнуть（像阿赫贾科娃那样道歉）！",
    224942: "他们清理过水渠和运河，给玉米除过草，而现在呢——是阿德拉斯潘（адраспан），又臭又有毒。它还有一个完全贴切的别名——坟地草。"
            "不过，采药人倒是很看重它。",
    242826: "起初他送给我一副白棉线织的、镶红边的背带，后来又送给妻子一条柔软的兔毛头巾，我还没来得及对这些古怪的礼物感到惊讶，"
            "他就从衣袋里掏出一双毛袜，递给了正在端茶炊的我们的女工阿克西尼娅。",
    262377: "大约在远征阿卡纳尼亚的前两年，一位名叫阿尔捷蒙的发明家来到伯里克利面前，提出如何借助机械加快被围困要塞陷落的建议。",
    265745: "奥莉姆皮亚达·萨姆索诺夫娜：那你就数数看：一件配缎面衬里的珠光色婚纱，再加三件天鹅绒的——这就是四件；两件纱罗的，"
            "一件绣金的克里普绸的——这是七件；三件缎面的，三件格罗格罗绸的——这是十三件；格罗杰纳普绸的和格罗达弗里克绸的七件——"
            "这是二十件；三件马赛林绸的，两件穆斯林德林的，两件希内罗亚尔的——这算多吗？——三加四等于七，再加二十——二十七；"
            "四件克列普拉舍尔绸的——这就是三十一件。那儿还有薄纱的、布夫穆斯林的、印花布的，差不多有二十件；还有罩衫和长袍——"
            "不是九件就是十件。还有前不久用波斯料子做的那件。",
    266086: "据EADaily报道，已离开该国的乌克兰说唱歌手尤里·利索夫斯基称，TikTok博主纳扎尔切克（НазарЧЕк）失踪，"
            "此人曾批评兵役局工作人员在“强制动员”中的行为。",
    300418: "他们整天从早到晚用攻城器械攻打，在三处放火烧城，而督军扎哈里伊奇扑灭火焰、击退攻城器械，使他们一事无成，只得损兵折将地撤退。",
    # 行数不对：按原文分行
    1631: "就算我们俩\n灾祸接踵而来，\n我与你的友谊\n也只有死亡能夺走",
    21816: "管他呢，没有\n荷马和奥维德笔下\n像我们这样、\n被煤烟熏成麻脸的人。\n我知道——\n太阳若看见，也会黯然失色：\n我们灵魂里那金色的矿藏！",
    266054: "有时游动孢子成对结合，而双鞭毛\n孢子的存在表明，同形配子游动孢子能够融合。",
}


def judge(eid, w, t, zh):
    """一条答案 → None（可以落库）或不落库的原因。**与 `audit` 的形状检查同一套**，在这里只写一份。"""
    if zh is None:
        return "没回来"
    nl = len(t.split("\n"))
    if not zh.strip():
        return "空"
    if not _HAN.search(zh):
        return "没有一个汉字（多半没翻译／拒译）"
    if nl != len(normalize_zh(zh, nl).split("\n")):
        return "行数不对"
    if eid in R28_OK or eid in R28_FIXED:
        return None                       # R28：人读逐条裁决过（只跳过下面这一条俄语串检查）
    src_st = {_stem(x) for x in _CYR_WORD.findall(t)} | {_stem(w or "")}
    if any(len(x) > 2 and _stem(x) not in src_st for x in _CYR_WORD.findall(zh)):
        return "译文里的俄语串原文没有（疑似幻觉）"
    return None


def answer_texts(tags=("redo", "all"), skip_empty=False):
    """{例句 id: 答案中文}：答案文件（按 tags 顺序先到先得）＋ R28 人工改译（优先）。**一个家**：
    `load()` 落库、`zh_pub.plan_model_text`（例句闸 X13 问它）都问这里。
    🔴 2026-11-05：原来两边各读一遍答案文件，R28 只加进了 `load()` ⇒ X13 报「库里的值不是从这份答案算出来的」21 条。"""
    got = {}
    for tag in tags:
        p = OUT / ("%s.jsonl" % tag)
        for line in p.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:                    # noqa: BLE001
                continue
            if isinstance(d.get("id"), int) and d["id"] not in got and (d.get("zh") or not skip_empty):
                got[d["id"]] = d.get("zh")
    got.update(R28_FIXED)
    return got


def load(tags=("redo", "all"), dry=True):
    """答案文件 → `example_gloss(lang='zh', src=model:…)`。幂等：已有中文的例句不动。

    🔴 答案文件**就是账本**（`[[answer-file-is-the-ledger]]`）—— 按例句 id 认领，不按「第几条」。
    🔴 形状不过的**不落库**，原因逐条打出来；它们留在分母里，补跑或人读之后再收。
    """
    import dbtool
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = {r[0]: r for r in gap_rows(con)}
    got = answer_texts(tags)
    ins, why = [], collections.Counter()
    eg = collections.defaultdict(list)
    for eid, (_i, w, t) in rows.items():
        r = judge(eid, w, t, got.get(eid))
        if r:
            why[r] += 1
            if len(eg[r]) < 8:
                eg[r].append((eid, w, t[:50].replace("\n", "⏎"), (got.get(eid) or "")[:50].replace("\n", "⏎")))
            continue
        ins.append((eid, "zh", normalize_zh(got[eid], len(t.split("\n"))), SRC_MODEL))
    print("■ 待译 %s 条 ／ 可落库 %s ／ 不落库 %s" % (F(len(rows)), F(len(ins)), F(sum(why.values()))))
    for k, v in why.most_common():
        print("   %-34s %8s" % (k, F(v)))
        for x in eg[k]:
            print("        %s %-14s %-50s → %s" % x)
    if dry:
        print("\n(干跑。确认后 --load --apply)")
        return
    con.close()
    with dbtool.session("example-zh-load", expect={"#example_gloss": len(ins)},
                        invalidates=["example_gloss"]) as s:
        s.executemany("INSERT INTO example_gloss(example_id,lang,text,src) VALUES (?,?,?,?)", ins)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--slice", type=float)
    ap.add_argument("--conc", type=int, default=100)
    ap.add_argument("--allow-peak", action="store_true")
    ap.add_argument("--count", action="store_true", help="只数分母，不跑")
    ap.add_argument("--audit", action="store_true", help="只审已有答案文件，不调模型")
    ap.add_argument("--redo", action="store_true",
                    help="把 all.jsonl 里形状不过的（幻觉／行数）**单条**重发一次，进 redo.jsonl")
    ap.add_argument("--tokens", type=int, default=0, help="--audit 时报单价用的 token 总数")
    a = ap.parse_args()
    if a.load:
        return load(dry=not a.apply)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = gap_rows(con)
    con.close()
    tag = "all"
    if a.slice:
        rows = pick_slice(rows, a.slice)
        tag = "slice%g" % a.slice
    print("■ 待译 %s 条 ／ %s 字符（%s）" % (F(len(rows)), F(sum(len(r[2]) for r in rows)), tag))
    if a.count:
        return
    if a.redo:
        # 单条重发：换了上下文（批里只有它自己 ＋ 定题），temperature=0 下原样重发是确定性复现（vi 6e）
        got = {}
        for line in (OUT / "all.jsonl").open(encoding="utf-8"):
            d = json.loads(line)
            got.setdefault(d.get("id"), d.get("zh"))
        # 「没回来」＝ id 在而 zh 字段不在（字段错位 39 条）—— 同样单条重发，不去别的字段里捞
        redo = [r for r in rows if (judge(r[0], r[1], r[2], got.get(r[0])) or "").startswith(
            ("行数", "译文里的俄语串", "没回来"))]
        print("■ 单条重发 %s 条" % F(len(redo)))
        path, ntok, peak = run(redo, "redo", a.conc, a.allow_peak, per=1)
        audit(path, redo, ntok, peak)
        return
    if a.audit:
        audit(OUT / ("%s.jsonl" % tag), rows, a.tokens, False)
        return
    path, ntok, peak = run(rows, tag, a.conc, a.allow_peak)
    audit(path, rows, ntok, peak)


if __name__ == "__main__":
    main()
