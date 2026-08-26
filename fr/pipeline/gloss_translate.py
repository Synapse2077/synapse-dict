#!/usr/bin/env python3
"""法语释义 → 中文释义。阶段 1.5 第三段：真要送模型的那一批。2026-08-24。

模板生成已经把 511,083 条砍到 296,761 条（`geo`/`name`/`demonym`/`misc`/`pointer` 五族，
231,080 条零语义风险）。剩下这些没有句式可套，只能送模型。

═══ 🔴 上一次大批量我烧掉 418 万 token 作废，根因不是"没注意" ═══
`[[control-must-cover-every-output-field]]`：那次控制组只量了 `i`（对齐下标），
**`zh` 一个字没验**，而 prompt 的缺陷全在 `zh` 那几条规则里 ——
拿一个"对会坏的字段完全瞎"的绿灯批了 2,930 批全量，跑完才第一次读产出。

⇒ 本脚本的 `controls()` **只有一个输出字段 `zh`，就把这个字段拆成十条判据**，
   每条都能在切片上判红绿，且每条都对应一个**我已经知道会发生**的坏法：

   | 判据 | 对应的已知坏法 | 出处 |
   |---|---|---|
   | 缺条 | flash 会**静默丢批里一部分** | it 阶段 5 丢 2,069 条 |
   | 中文字符占比 | 整条原样留法语没翻 | 豆包翻译模型实测 |
   | 句末标点 | 翻译腔，规则第 4 条禁止 | — |
   | 问句/「谁」 | `Qui …` 族被当成疑问句 | 豆包实测 25 抽 12 |
   | 元话语 | 「意为」「指的是」「该词」 | 规则第 5 条 |
   | 比源还长 | 没压缩成释义，整句翻译 | 豆包实测 |
   | 极短 | 压过头，丢掉区分性信息 | `[[criteria-from-meaning-not-form]]` 那次坏 1,528 条 |
   | 撞车率 | 不同源 → 同一中文 = 区分性信息没了 | 同上 |
   | 领域标丢失 | 源 `(Botanique)` 而中文没有 | 规则第 3 条 |
   | 留空率 | 该留空却硬编 / 该翻却摆烂 | `[[blind-gloss-inference-ceiling]]` |

═══ 按**法语原串**存答案，不按 sense_id ═══
`[[model-answer-files-key-by-id]]` 说的是「不许按第几条存」。这里比 id 更强的键是
**法语原串本身**：16,858 种重复串覆盖 46,608 条 ⇒ 按串存
① 少发 29,750 次请求（省 10%）
② **同一句法语在全库永远同一个中文**（按 id 存做不到这点）
③ 续跑/重放天然幂等

用法（在 fr/ 目录下）：
    python3 pipeline/gloss_translate.py --ab 200        # 带不带 word 字段，A/B
    python3 pipeline/gloss_translate.py --slice 3000    # 1% 切片，跑完自动出控制表
    python3 pipeline/gloss_translate.py --audit         # 只看控制表，不发请求
    python3 pipeline/gloss_translate.py --read 40       # 打样给我逐条读
    python3 pipeline/gloss_translate.py                 # 全量续跑
    python3 pipeline/gloss_translate.py --apply         # 落库
"""
import argparse
import io
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool                                  # noqa: E402
import paths                                   # noqa: E402
from pipeline import slot_translate            # noqa: E402

SRC = "model:gloss"
OUT = paths.WORK / "gloss" / "gloss_zh.jsonl"

SYS = """你是法语—中文词典助手。输入是**法语词条在法语维基词典里的释义**（法语原文），
把它转成**中文释义**，供中文用户查词用。

规则：
1. 输出中文释义本身，不是逐字翻译法语句子。`Oiseau de proie diurne.` → `昼行性猛禽`
2. 🔴 **保留区分性信息**。同名的不同事物必须能区分开：
   `Commune française du département de la Charente.` → `法国夏朗德省市镇`
   **不要**压成`法国市镇` —— 那会让十个同名市镇的中文一模一样
3. 专业领域词保留领域限定：`(Botanique) Plante de la famille des rosacées.` → `（植物学）蔷薇科植物`
4. **句末不加标点**；多个对应词用中文顿号分隔，最多 3 个
5. 不要出现「意为」「指」「该词」这类元话语
6. 🔴 法语里以 `Qui …` 开头的是**形容词释义**，不是疑问句。
   `Qui a peur de la nouveauté.` → `恐惧新事物的`，**不是**`谁害怕新鲜事物？`
7. 🔴 `Forme pronominale de X` / `Variante de X` 这类是**指向另一个词的指针**。
   给出**那个词在这个用法下的真实中文意思**，不要翻译"……的代词形式"这句话本身。
   `Forme pronominale de baisser.` → `弯腰，俯身`
8. 🔴 法语释义本身没有信息量、或你无法确定时，`zh` 输出空字符串 ""，**不要猜**。
   留空的会退回显示法语原文，不会出错；瞎编会。
9. 有的项带 `hint`：这是句中某些法语专名在**本词典里已确定的中文译名**。
   · 你的答案里若要出现这个专名，**必须用 hint 给的中文**（全库译名要一致）
   · 🔴 但 hint 是**按拼写**匹配上的，可能匹配错。若该词在本句里**不是**那个地名
     （例如 `Bach` 在句中指作曲家巴赫，而 hint 说的是同名市镇），**忽略 hint**
   · hint 里没提到的专名，照常处理

输入是 JSON 数组，每项有 `id`（标识号，**不是序号**）和 `gloss`（法语释义），
可能有 `hint`。输出**只有** JSON 数组，每项 {"id": 原样回传, "zh": "中文"}，
不要围栏、不要解释。"""

# ══════════ 英文道：只有英文 gloss 的义项 ══════════
#
# 🔴 这批是我自己漏的：翻译池子的判据写成「有法语原文」（`JOIN sense_gloss lang='fr'`），
#    于是 **227 个只有英文 gloss 的义项从没进过池子**（`andorran` / `islam` / `djiboutien`）。
#    ⇒ 判据是「这个义项有没有中文」，不是「它有没有法语原文」。
#
# ⚠️ **不能走"从证据层提升法语原文"这条近路**，虽然 189 个义项所属的词确实有法语证据 ——
#    那是**词级**匹配不是**义项级**：`gland` 的英文 gloss 是 `glans`（龟头），
#    而词级法语证据是 `Fruit du chêne`（橡子），**是同一个词的两个不同义项**。
#    贴过去就是 `[[verification-gates-not-sampling]]` 里用户点名的
#    「把义项和释义错配了，那才是真灾难」。英文 gloss 是**这个义项自己的**内容，义项级对得上。
SYS_EN = """你是英语—中文词典助手。输入是**法语词条在维基词典英文版里的英文释义**，
把它转成**中文释义**，供中文用户查词用。⚠️ 词条本身是**法语词**，英文只是转述语言。

规则：
1. 输出中文释义本身，不是逐字翻译英文句子。`diurnal bird of prey` → `昼行性猛禽`
2. 🔴 **保留区分性信息**，同名的不同事物必须能区分开
3. 领域限定保留：`(botany) plant of the rose family` → `（植物学）蔷薇科植物`
4. **句末不加标点**；多个对应词用中文顿号分隔，最多 3 个
5. 不要出现「意为」「指」「该词」这类元话语
6. 🔴 `alternative form of X` / `plural of X` 这类是**指向另一个词的指针**：
   给出**那个词的真实中文意思**，不要翻译"……的变体形式"这句话本身
7. 🔴 拿不准就输出空字符串 ""，**不要猜**。留空会退回显示原文，瞎编会出错。

输入是 JSON 数组，每项有 `id`（标识号，**不是序号**）、`word`（法语词形）
和 `gloss`（英文释义）。输出**只有** JSON 数组，每项 {"id": 原样回传, "zh": "中文"}，
不要围栏、不要解释。"""

OUT_EN = paths.WORK / "gloss" / "gloss_zh_en.jsonl"


def pool_en(con):
    """→ 只有英文 gloss、**没有中文**的可见义项。键 = `词形\\x1f英文释义`
    （英文 gloss 短、易撞车，必须带词形才唯一决定中文）。"""
    return [{"fr": w + SEP + " ".join(t.split()), "gloss": " ".join(t.split()),
             "word": w, "id": str(sid), "ids": [sid], "n": 1, "ana": False}
            for sid, w, t in con.execute("""
                SELECT s.id, d.word, g.text FROM sense s
                JOIN dict d ON d.id = s.word_id
                JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='en'
                WHERE s.hidden=0
                  AND NOT EXISTS(SELECT 1 FROM sense_gloss f
                                 WHERE f.sense_id=s.id AND f.lang='fr')
                  AND NOT EXISTS(SELECT 1 FROM sense_gloss z
                                 WHERE z.sense_id=s.id AND z.lang='zh')""")]


# 回指族专用：释义里有 `cette ville` / `lui-même` 这类**指向词条本身**的代词，
# 不给 `word` 就只能译成「该城周边省份」，给了才能译成「布雷西亚省」。
SYS_ANA = SYS.replace(
    "输入是 JSON 数组，每项有 `id`（标识号，**不是序号**）和 `gloss`（法语释义）。",
    """🔴 这一批的释义里有**指向词条本身的代词**（`cette ville` / `ce cours d’eau` /
   `lui-même`）。`word` 就是那个词条 —— 把代词**还原成它**：
   `word=Brescia` + `Province autour de cette ville.` → `布雷西亚省`
   （**不要**译成`该城周边省份`）。除还原代词外，`word` 的其他信息一个字都不许写进答案。

输入是 JSON 数组，每项有 `id`（标识号，**不是序号**）、`word`（法语词形）和
`gloss`（法语释义）。""")

# 指示代词 + 它指的那类名词，或 `lui-même` 一族。全库 1,871 个串 / 2,272 条义项（0.8%）。
ANAPHORIC = re.compile(
    r"\b(?:cette?|ces|cet)\s+(?:ville|commune|d[ée]partement|pays|r[ée]gion|province|cours|"
    r"rivi[èe]re|fleuve|montagne|[îi]le|lac|action|mot|terme|verbe|nom|plante|animal|"
    r"esp[èe]ce|genre|famille|personne|lieu|localit[ée]|village|ethnie|peuple|langue|"
    r"instrument|objet|maladie|science|art|sport|jeu)\b"
    r"|lui-m[êe]me|elle-m[êe]me|\bcelui-ci\b|\bcelle-ci\b|\bce dernier\b", re.I)

# ══════════ 撞车修复：只修**真的丢了区分性信息**的那些 ══════════
#
# 🔴 我先试了个更省事的做法，**结果是净回退，已回滚**：往 SYS 加一条
#    「不能确定中文名就必须保留分子式」，然后把 1,064 条带分子式的全部重答。
#    补上分子式 330 条，但代价是模型**整体倒向「类别＋分子式」**：
#      `敌稗（除草剂）` → `除草剂（C₁₅H₁₄Cl₂N₂O₃）`   ← 丢了正确的具体名
#      `杀草强` → `除草剂（C₂H₄N₄）`   `敌草隆` → `除草剂兼杀虫剂（…）`
#      `乙烯利，植物生长调节剂` → `植物生长调节剂（C₂H₆O₃PCl），用于矮化茎秆…`
#    ⇒ `[[criteria-from-meaning-not-form]]` 的原话：**我优化了一个代理指标
#      （有没有分子式），模型就把它优化到了牺牲真正重要的东西**。
#
# ⇒ 正确的判据是**按含义**的：「同一个中文被多个带分子式的不同化合物共用」
#    才是真丢了区分性信息。全量 1,064 条里只有 **85 条 / 29 种中文**中招，
#    其余 979 条本来就是对的，**一个字都不该动**。
FORMULA = re.compile(r"formule (?:chimique|brute)")
FORM_VAL = re.compile(r"formule (?:chimique|brute)\s+((?:[A-Za-z(][A-Za-z0-9₀-₉()_\-]*)+)")

SYS_COLLIDE = """你在给一部法汉词典修一批**撞车**的化学品释义。
这些释义的中文目前**多个不同化合物共用同一个中文**，读者无法区分。

对每一条：
1. 如果你能确定这个**具体化合物**的中文名（如 `敌稗`、`杀草强`、`敌草隆`），就给这个名，
   后面加分子式：`敌稗（C₉H₉Cl₂NO）`
2. 🔴 如果你**不能确定**具体名，给`<用途类别>（<分子式>）`，如 `除草剂（C₈H₁₄ClNS₂）`。
   **绝对不要给一个你不确定的具体名** —— 现在的错误正是同一个名被安到了五个不同化合物上。
3. 分子式**照抄源文**，不要改写、不要自己推。
4. 句末不加标点。

输入 JSON 数组，每项有 `id`（原样回传）和 `gloss`（法语原文）、`now`（当前撞车的中文）。
输出**只有** JSON 数组，每项 {"id": 原样, "zh": "中文"}，不要围栏、不要解释。"""

META = re.compile(r"意为|指的是|该词|这个词|这个字|字面意思|翻译为")
CJK = re.compile(r"[一-鿿]")
LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{4,}")


def pool(con, hidden=False):
    """→ [{id, fr, word}]，只取**可见**且尚无中文的义项。"""
    return [{"id": sid, "fr": " ".join(t.split()), "word": w}
            for sid, w, t in con.execute("""
                SELECT s.id, d.word, g.text FROM sense s
                JOIN dict d ON d.id = s.word_id
                JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
                LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
                WHERE z.sense_id IS NULL AND s.hidden=%d""" % (1 if hidden else 0))]


SEP = "\x1f"
# 已有译名表：地名族那轮翻的 28,332 个市镇/省区名。整句翻译要**复用**它，
# 否则同一个 `Wincrange` 在模板族里是「温克朗日」、在这里是原样法语。
PLACE_ZH = paths.WORK / "geo" / "place_zh.jsonl"
_TOK = re.compile(r"[A-ZÀ-Ý][\w’'\-]*(?:-[A-ZÀ-Ýa-zà-ÿ][\w’'\-]*)*")


def place_table():
    t = {}
    if PLACE_ZH.exists():
        for ln in io.open(PLACE_ZH, encoding="utf-8"):
            try:
                o = json.loads(ln)
            except Exception:
                continue
            if o.get("zh"):
                t[o["fr"]] = o["zh"]
    return t


def hint_of(gloss, tbl):
    """→ {法语专名: 中文} 或 None。**只按拼写匹配，必然有误报**
    （`Mars` 火星 / `Cellule` 细胞 / `Bach` 作曲家 都同时是法国市镇名），
    所以 prompt 里把它写成"建议"并明确授权模型忽略 —— 判断留给模型，不由我硬替换。
    实测切片：157/2,700 命中，其中真该用的 62 条、误报约 95 条。"""
    h = {n: tbl[n] for n in {m.group(0) for m in _TOK.finditer(gloss)} if n in tbl}
    return h or None


def key_of(r):
    """落盘键 = **能唯一决定这条中文的全部输入**。

    普通释义：法语原串本身就够（`Manger.` 不管挂在哪个词下都是「吃」）。
    回指释义：`cette ville` 指的是词条自己 ⇒ 词形也是输入的一部分，进键。
    ⇒ 这样"同样的输入永远同一个中文"在两条道上都成立，去重和续跑都不用特判。
    """
    return (r["word"] + SEP + r["fr"]) if ANAPHORIC.search(r["fr"]) else r["fr"]


def uniq(rows):
    """按 `key_of` 去重 → [{fr(=键), gloss, word, ana, n, ids}]，按出现次数降序。"""
    by = defaultdict(list)
    meta = {}
    for r in rows:
        k = key_of(r)
        by[k].append(r["id"])
        meta.setdefault(k, r)
    tbl = place_table()
    out = []
    for k, ids in sorted(by.items(), key=lambda x: -len(x[1])):
        r = meta[k]
        it = {"fr": k, "gloss": r["fr"], "word": r["word"],
              "ana": SEP in k, "n": len(ids), "ids": ids}
        h = hint_of(r["fr"], tbl)
        if h:
            it["hint"] = h
        out.append(it)
    return out


# ══════════ 控制判据：唯一的输出字段 `zh`，拆成十条 ══════════

def controls(pairs):
    """pairs = [(fr, zh)]。→ (统计 dict, 各判据的样本)。**红线由调用方判**，这里只报数。"""
    n = len(pairs)
    if not n:
        return {}, {}
    ex = defaultdict(list)
    c = Counter()
    seen = defaultdict(set)
    for fr, zh in pairs:
        z = (zh or "").strip()
        if not z:
            c["留空"] += 1
            ex["留空"].append((fr, z))
            continue
        cjk = len(CJK.findall(z))
        if cjk == 0 or cjk / max(len(z), 1) < 0.3:
            c["中文占比过低（疑似没翻）"] += 1
            ex["中文占比过低（疑似没翻）"].append((fr, z))
        if re.search(r"[。．\.！!]$", z):
            c["句末带标点"] += 1
            ex["句末带标点"].append((fr, z))
        if "？" in z or "?" in z or z.startswith("谁"):
            c["问句/以「谁」开头"] += 1
            ex["问句/以「谁」开头"].append((fr, z))
        if META.search(z):
            c["含元话语"] += 1
            ex["含元话语"].append((fr, z))
        if len(z) > max(12, len(fr) * 0.75):
            c["比源还长（没压缩）"] += 1
            ex["比源还长（没压缩）"].append((fr, z))
        if len(fr) > 40 and len(z) <= 4:
            c["压过头（源长中文极短）"] += 1
            ex["压过头（源长中文极短）"].append((fr, z))
        if fr.lstrip().startswith("(") and not z.lstrip().startswith(("（", "(")):
            c["领域标丢失"] += 1
            ex["领域标丢失"].append((fr, z))
        m = LATIN.findall(re.sub(r"[（(][^）)]*[）)]", "", z))
        if m:
            c["残留法语词"] += 1
            ex["残留法语词"].append((fr, z))
        seen[z].add(fr)
    dup = {z: frs for z, frs in seen.items() if len(frs) > 1}
    c["撞车（不同源→同一中文）"] = sum(len(f) for f in dup.values())
    for z, frs in sorted(dup.items(), key=lambda x: -len(x[1]))[:6]:
        ex["撞车（不同源→同一中文）"].append((" ／ ".join(sorted(frs)[:3]), z))
    return dict(c), ex


def show_controls(pairs, title="控制判据"):
    c, ex = controls(pairs)
    n = len(pairs)
    print("\n══ %s（%s 条）══" % (title, format(n, ",")))
    order = ["留空", "中文占比过低（疑似没翻）", "残留法语词", "句末带标点",
             "问句/以「谁」开头", "含元话语", "比源还长（没压缩）", "压过头（源长中文极短）",
             "领域标丢失", "撞车（不同源→同一中文）"]
    for k in order:
        v = c.get(k, 0)
        print("  %-26s %6s  %5.2f%%" % (k, format(v, ","), v * 100 / n))
        for fr, z in ex.get(k, [])[:2]:
            print("        %-62s → %s" % (fr[:62], z[:40]))
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int, default=0, help="只跑前 N 个**去重后**的串")
    ap.add_argument("--ab", type=int, default=0, help="带不带 word 字段，A/B 各跑 N 条")
    ap.add_argument("--audit", action="store_true", help="只看已落盘答案的控制表")
    ap.add_argument("--read", type=int, default=0, help="打样 N 条给我逐条读")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--fix-collide", action="store_true",
                    help="重答**中文撞车**的化学品条目（只动撞车的）")
    ap.add_argument("--en", action="store_true",
                    help="英文道：翻**只有英文 gloss**的义项（我原来的判据漏掉的那批）")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if a.fix_collide:
        return fix_collide(a.apply)
    if a.en:
        return en_lane(a.apply)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = pool(con)
    items = uniq(rows)
    cover = sum(i["n"] for i in items)
    ana = [i for i in items if i["ana"]]
    print("■ 待翻义项 %s 条 → 去重后 **%s 个待翻单元**（重复串省下 %s 次请求）"
          % (format(cover, ","), format(len(items), ","), format(cover - len(items), ",")))
    print("   其中回指族 %s 个（走带 `word` 那条道，代词还原成词条本身）"
          % format(len(ana), ","))

    got = slot_translate.done_keys(OUT)
    done = lambda xs: [(i["gloss"], got[i["fr"]]["zh"]) for i in xs if i["fr"] in got]  # noqa

    if a.stats or a.audit or a.read or a.apply:
        pairs = done(items)
        print("■ 已翻 %s 单元 / 覆盖 %s 条义项"
              % (format(len(pairs), ","),
                 format(sum(i["n"] for i in items if i["fr"] in got), ",")))
        if a.stats:
            return 0
        if a.read:
            print("\n── 随机 %d 条，逐条读 ──" % a.read)
            for fr, zh in random.Random(7).sample(pairs, min(a.read, len(pairs))):
                print("   %-76s → %s" % (fr[:76], zh or "（留空）"))
            return 0
        if a.audit:
            show_controls(pairs)
            return 0

    if a.ab:
        return ab_test(items[:a.ab])

    if not a.apply:
        # 🔴 切片必须**随机抽**。`items` 是按重复次数降序的，取头部会全是
        #    `Manger.` `Île de Grèce.` 这类高频短串 —— 那是**最容易翻的一撮**，
        #    拿它当 1% 试跑等于自己骗自己（`[[llm-as-evaluator-discipline]]` 的负控精神）。
        want = random.Random(1).sample(items, a.slice) if a.slice else items
        for tag, sys_p, flds, xs in (
                ("普通", SYS, ("id", "gloss", "hint"), [i for i in want if not i["ana"]]),
                ("回指", SYS_ANA, ("id", "word", "gloss", "hint"), [i for i in want if i["ana"]])):
            todo = [dict(i, id=str(i["ids"][0])) for i in xs if i["fr"] not in got]
            if not todo:
                continue
            print("\n── %s 道 ──" % tag)
            slot_translate.translate(todo, sys_p, OUT, fields=flds,
                                     keep=("fr", "n"), key_field="id")
        got = slot_translate.done_keys(OUT)
        done = lambda xs: [(i["gloss"], got[i["fr"]]["zh"])       # noqa: E731
                           for i in xs if i["fr"] in got]
        show_controls(done(want), "控制判据（本次切片，全部）")
        if any(i["ana"] for i in want):
            show_controls(done([i for i in want if i["ana"]]), "控制判据（回指族单独看）")
        print("\n(未加 --apply，未写库)")
        return 0

    return apply(con, items, got)


def ab_test(items):
    """带 `word` 与不带，同一批。`[[context-you-give-leaks-into-output]]`：
    多喂的上下文会漏进输出，多喂之前先证明它有用。"""
    import asyncio
    import httpx

    SYS_W = SYS.replace(
        "输入是 JSON 数组，每项有 `id`（标识号，**不是序号**）和 `gloss`（法语释义）。",
        "输入是 JSON 数组，每项有 `id`（标识号，**不是序号**）、`word`（法语词形，"
        "**只用来帮你判断，一个字都不许写进答案**）和 `gloss`（法语释义）。")

    async def run():
        key = slot_translate.env()["DEEPSEEK_API_KEY"].strip()
        payload = [{"id": str(i["ids"][0]), "gloss": i["gloss"], "word": i["word"]}
                   for i in items]
        async with httpx.AsyncClient() as cl:
            out = {}
            for tag, sys_p, flds in (("不带 word", SYS, ["id", "gloss"]),
                                     ("带 word", SYS_W, ["id", "word", "gloss"])):
                g, tok = await slot_translate._ask(cl, key, sys_p, payload, flds,
                                                   key_field="id")
                out[tag] = {i["gloss"]: g.get(str(i["ids"][0]), "") for i in items}
                print("── %-10s token %s（%.1f/条）"
                      % (tag, format(tok, ","), tok / len(items)))
            return out

    out = asyncio.run(run())
    for tag in out:
        show_controls([(f, z) for f, z in out[tag].items()], "控制判据 · " + tag)
    diff = [(f, out["不带 word"][f], out["带 word"][f])
            for f in out["不带 word"] if out["不带 word"][f] != out["带 word"][f]]
    print("\n══ 两版不一致 %d/%d ══" % (len(diff), len(items)))
    for f, a_, b_ in diff[:25]:
        print("   %-58s\n     不带 → %-26s 带 → %s" % (f[:58], a_[:26], b_[:26]))
    return 0


def en_lane(apply_it):
    """英文道。走**同一套**共用件：按内容键落盘、逐条核对、关思考、可续跑。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = pool_en(con)
    got = slot_translate.done_keys(OUT_EN)
    todo = [i for i in items if i["fr"] not in got]
    print("■ 只有英文 gloss 且无中文的义项 %s ｜ 已翻 %s ｜ 待翻 %s"
          % (format(len(items), ","), format(len(got), ","), format(len(todo), ",")))
    if todo:
        slot_translate.translate(todo, SYS_EN, OUT_EN, fields=("id", "word", "gloss"),
                                 keep=("fr", "n"), key_field="id")
        got = slot_translate.done_keys(OUT_EN)

    pairs = [(i["gloss"], got[i["fr"]]["zh"]) for i in items if i["fr"] in got]
    show_controls(pairs, "控制判据（英文道）")
    print("\n── 全部 %d 条，逐条读 ──" % len(pairs))
    for i in items:
        if i["fr"] in got:
            print("   %-20s %-50s → %s"
                  % (i["word"][:20], i["gloss"][:50], got[i["fr"]]["zh"] or "（留空）"))
    if not apply_it:
        print("\n(未加 --apply，未写库)")
        return 0

    out = [(i["ids"][0], got[i["fr"]]["zh"].strip()) for i in items
           if i["fr"] in got and (got[i["fr"]]["zh"] or "").strip()]
    if not out:
        return 0
    with dbtool.session("keep-v3-gloss-en", expect={"#sense_gloss": len(out)}) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,'zh','equivalent',0,?,?)",
                      [(sid, z, "model:gloss-en") for sid, z in out])
    print("\n✓ 写入 %s 条 sense_gloss(src='model:gloss-en')" % format(len(out), ","))
    return 0


def collide_formula(recs):
    """→ 真撞车的记录列表：同一个中文被 ≥2 个**带分子式的不同源**共用。"""
    by = defaultdict(list)
    for r in recs:
        g = r["fr"].split(SEP)[-1]
        z = (r["zh"] or "").strip()
        if z and FORMULA.search(g):
            by[z].append(r)
    return [r for v in by.values() if len(v) > 1 for r in v]


def fix_collide(apply_it):
    """重答撞车的化学品条目。**只动撞车的那些**，其余一个字不碰。"""
    import asyncio
    import httpx
    recs = [json.loads(ln) for ln in io.open(OUT, encoding="utf-8") if ln.strip()]
    hit = collide_formula(recs)
    print("■ 带分子式 %s 条，其中**中文撞车** %s 条"
          % (format(sum(1 for r in recs if FORMULA.search(r["fr"].split(SEP)[-1])), ","),
             format(len(hit), ",")))
    if not hit or not apply_it:
        for r in hit[:6]:
            print("   %-84s → %s" % (r["fr"].split(SEP)[-1][:84], r["zh"]))
        if not apply_it:
            print("\n(未加 --apply，未重答)")
        return 0

    items = [{"id": str(i), "gloss": r["fr"].split(SEP)[-1], "now": r["zh"]}
             for i, r in enumerate(hit)]

    async def run():
        key = slot_translate.env()["DEEPSEEK_API_KEY"].strip()
        async with httpx.AsyncClient() as cl:
            got, tok = {}, 0
            for k in range(0, len(items), 60):
                g, t = await slot_translate._ask(cl, key, SYS_COLLIDE, items[k:k + 60],
                                                 ["id", "gloss", "now"], key_field="id")
                got.update(g)
                tok += t
            return got, tok
    got, tok = asyncio.run(run())
    print("   重答 %d 条 / token %s" % (len(got), format(tok, ",")))

    new = {}
    for i, r in enumerate(hit):
        z = (got.get(str(i)) or "").strip()
        if z:
            new[r["fr"]] = z
    print("\n── 全部 %d 条，前后并排 ──" % len(new))
    for r in hit:
        if r["fr"] in new:
            print("   %-70s\n     旧: %-26s 新: %s"
                  % (r["fr"].split(SEP)[-1][:70], r["zh"][:26], new[r["fr"]][:44]))
    out = [dict(r, zh=new.get(r["fr"], r["zh"])) for r in recs]
    io.open(OUT, "w", encoding="utf-8").write(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    left = collide_formula(out)
    print("\n■ 改完仍撞车：%s 条（改前 %s）" % (format(len(left), ","), format(len(hit), ",")))
    return 0


def apply(con, items, got):
    out = []
    for i in items:
        rec = got.get(i["fr"])
        if not rec or not (rec.get("zh") or "").strip():
            continue
        for sid in i["ids"]:
            out.append((sid, rec["zh"].strip()))
    print("\n■ 可落库 %s 条义项（来自 %s 个串）"
          % (format(len(out), ","), format(len({i for i, _z in out}), ",")))
    if not out:
        return 0
    ids = [i for i, _z in out]
    if len(set(ids)) != len(ids):
        print("🔴 sense_id 重复 %d，**不写**" % (len(ids) - len(set(ids))))
        return 1
    dup = con.execute("SELECT count(*) FROM sense_gloss WHERE lang='zh' AND sense_id IN (%s)"
                      % ",".join("?" * min(len(ids), 900)), ids[:900]).fetchone()[0]
    if dup:
        print("🔴 抽查前 900 个 sense_id，已有中文 %d 条，**不写**" % dup)
        return 1
    with dbtool.session("keep-v3-gloss-zh", expect={"#sense_gloss": len(out)}) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,'zh','equivalent',0,?,?)",
                      [(sid, z, SRC) for sid, z in out])
    print("✓ 写入 %s 条 sense_gloss(src='%s')" % (format(len(out), ","), SRC))
    return 0


if __name__ == "__main__":
    sys.exit(main())
