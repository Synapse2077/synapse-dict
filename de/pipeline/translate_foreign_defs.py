#!/usr/bin/env python3
"""把 fr/it/es/pt 版给德语词的释义译成中文 → 补 10,578 个**空白页**。de 版，2026-09-18。

═══ 这一批是什么 ═══
2026-09-18 的 C44 用中文版白送的中文补掉了 31,852 个空白页，剩 17,505 个。
其中 **10,578 个词形 / 11,017 条义项**在 fr/it/es/pt 版里有释义 ——
但那些释义是**法语/意语/西语/葡语**，`[[gloss-three-languages]]`（中＋英＋本语言）
不让它们上页 ⇒ 只能翻。

    fr 版  8,717 词形   ← 大头
    it 版  1,207
    es 版    465
    pt 版    189
    原文 319,296 字符，均 29 字符/条（对照 1.5b 的德语原文均 61）

═══ 🔴 必须先说清楚这一批比 1.5b 差在哪 ═══
**它是「译文的译文」，而且没有德语原文可以对照。**
这些词形**德语版根本没有条目**（那正是它们空白的原因），英文版也没收到 ——
所以：
  · 控制组少掉最有力的一条判据（拿德语原文核中文）；
  · 页面上会是「中文有、德语原文永远空」，缺三语里的「本语言」那一栏，而**这一栏补不了**；
  · 译错了我们查不出来，唯一的上游就是法语版那一句。
⇒ 出版时 `sense_gloss.src='model:foreign-def'`，证据层留**源语言原文 + 哪一版**，
  将来要翻案能逐条回源（`[[two-layer-sense-model]]`）。
⚠️ 用户 2026-09-18 看过量与这段顾虑之后说「花」，先跑控制切片再放全量。

═══ 🔴 应答按什么认领 ═══
这批义项**在库里还不存在**（要等翻译落地才建 `sense`），所以没有 `sense.id` 可用。
⇒ 用**源头锚定**的稳定键 `<词形>\\x1f<版>\\x1f<源里第几条义项>`。
它不是「这一批里的第几条」（`[[model-answer-files-key-by-id]]` 骂的正是那个），
而是**在源 dump 里唯一确定一条义项**的坐标：重跑、换切片、换顺序都不变。
落盘前断言它在本批内唯一。

═══ 判据为这一族重写，不从 1.5b 复用 ═══
① 🔴 源语言**有意不发给模型**。第一版发了 `lang`，切片实测 **4/200＝2.0%** 把它
   写进了答案（`Hebert [法语] → 法语姓氏`，而 `Apellido`/`Nom de famille` 只是「姓氏」
   的意思、说的不是这个姓属于哪种语言）。`[[context-you-give-leaks-into-output]]`
   的教训不是「在 prompt 里请它忽略」，是**把通道拆掉** —— 模型自己认得出法语还是西语。
② 源头自己就有指针（`forme fléchie de X`／`pluriel de X`）⇒ 要求 `zh` 给空字符串。
③ 🔴 **不许照抄德语词头**：源头释义里常常原样出现那个德语词
   （`Flachheit → Platitude, banalité.` 是好的；`Urbanisation → Urbanisation.` 是把词抄了一遍）。
④ 🔴🔴 **专名不生造音译** —— 这一批最危险的一条，因为法语版收了大量德国小市镇，
   而它们的条目**只有词头没有释义**（`src` 就是 `word` 本身）。第一版切片实测
   **11/200＝5.5%** 被模型按读音编出了中文（`Staudach-Egerndach → 施陶达赫-埃根达赫`）。
   ⇒ 规则 3/6 改写成「`src` 只重复词头就给空串」，并做成一条**控制判据**盯着。
   ⚠️ 例外只有「本身有公认中文名」那种（`Poinsettia → 一品红`），所以判据是**测量**不是硬零。

═══ 成本 ═══
🔴 **我报给用户的 1.9 元是低估的。** 那是拿 1.5b 的 70.1 token/条折算的，
而切片**实测 91.3 token/条**（200 条 18,254 token，入 12,494／出 5,760）——
原文虽短，SYS 提示词的固定开销按条摊下来更重。
⇒ 全量 11,017 条 ≈ **1.0M token ≈ 2.4 元**（空闲半价）。
`[[prove-free-path-before-quoting]]`：折算来的数只能当估算，实测出来要回头改口。

用法（在 de/ 目录下）：
    python3 -u pipeline/translate_foreign_defs.py --build-pool      # 扫四版，落盘池子
    python3 -u pipeline/translate_foreign_defs.py --slice 200       # 控制切片
    python3 -u pipeline/translate_foreign_defs.py --read 20
    python3 -u pipeline/translate_foreign_defs.py                   # 全量续跑
    python3 -u pipeline/translate_foreign_defs.py --apply           # 写库
"""
import argparse
import gzip
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool            # noqa: E402
import paths             # noqa: E402
import slot_translate    # noqa: E402
from ingest_de_senses import is_real_sense   # noqa: E402  判据只许一份
from build import POS_MAP                    # noqa: E402

SRC = "model:foreign-def"
POOL = paths.WORK / "foreign" / "pool.json"
OUT = paths.WORK / "foreign" / "zh.jsonl"
has_han = dbtool.has_han

# 源头优先级：同一个词形几版都有时只翻一版。fr 条目最全、释义最规整。
EDITIONS = [("frwiktionary", "法语"), ("itwiktionary", "意大利语"),
            ("eswiktionary", "西班牙语"), ("ptwiktionary", "葡萄牙语")]
SEP = "\x1f"

# 原文比 1.5b 短一半 ⇒ 批可以大一点
slot_translate.CHUNK = 120
slot_translate.CONC = 60

SYS = """你在把一部德语词典的释义翻译成中文，给中文读者用。

⚠️ 被解释的词是**德语词**，但释义原文是用**别的语言**写的（法语/意大利语/西班牙语/葡萄牙语）——
因为这些词条只有那几版维基词典收了。你要给的是**这个德语词的中文释义**。

输入是 JSON 数组，每项有：
  `id`    标识号，**不是序号**，原样回传
  `word`  被解释的**德语**词
  `pos`   词性（n 名词／v 动词／adj 形容词／adv 副词／name 专名／phr 短语／unknown 未标注）
  `src`   释义原文（语言你自己认，不会告诉你是哪种）

规则
1. 输出**中文释义**，不是逐字翻译。能用一个常用汉语词对应就给那个词，
   不能对应就给一句简短的解释。
2. 🔴 **词性要对上 `pos`**：`v` 给动词说法（「切开」不是「切口」），
   `n` 给名词说法，`adj` 给形容词说法（带「的」）。
   `pos=unknown` 时按 `src` 读出来的词性给。
3. 🔴🔴 **`src` 只是把 `word` 重复了一遍时，`zh` 必须给空字符串。**
   那说明源头压根没写释义，只建了个词条壳子。**这时绝对不许你根据读音编一个中文出来**：
     `Staudach-Egerndach` src=「Staudach-Egerndach.」→ `zh` 给 ""（**不是**「施陶达赫-埃根达赫」）
     `Rheinbreitbach`     src=「Rheinbreitbach.」    → `zh` 给 ""（**不是**「莱茵布赖特巴赫」）
     `Urbanisation`       src=「Urbanisation.」      → `zh` 给 ""
   例外只有一种：这个词**本身就有公认的中文名**，你不是在音译而是在叫出它的名字
   （`Poinsettia` src=「poinsettia」→「一品红」）。**拿不准就给空字符串。**
   `Flachheit` src=「Platitude, banalité.」→「平庸，陈腐」—— 这条源头真给了释义，是好的。
4. 🔴 **源头自己是指针的，`zh` 给空字符串**。像
   `forme fléchie de X`／`pluriel de X`／`féminin de X`／`participe passé de X`
   说的是语法关系不是词义。
5. 🔴 **不要输出元描述**。「…的复数」「…的分词」「参见…」同样给空字符串。
6. 专名（`pos=name`，以及 `src` 里说是地名/姓名的）：
   · 有**通用中文译名**的用通用译名 —— `München`→「慕尼黑」。
   · 姓氏、名字：给「德语姓氏」「男性名字」「女性名字」。
   · 行政区划照实说：「德国巴伐利亚州的一个市镇」。
   · 🔴🔴 **没有通用译名的地名：`zh` 给空字符串。**
     德国、奥地利、瑞士的小市镇绝大多数**没有**中文译名。
     按读音拼一个出来看着像数据、其实是你编的，而这一批没有德语原文可以对照，
     编出来的没人查得出来。**慕尼黑、科隆、汉堡这种才叫通用译名；
     Kutenholz、Temnitztal、Hattgenstein 这种一律给空字符串。**
7. 学名、化学式、度量单位原样保留。
8. **不加句末标点**，不写「指」「表示」这类引导语，不加括号解释除非原文就有。
9. 🔴 原文残缺、看不出意思、或你不确定，`zh` 给空字符串，**不要猜**。
   这一批没有德语原文可以对照，猜错了没人查得出来。
10. 🔴 **不要在中文里提释义原文是什么语言。** `Nom de famille`／`Apellido`
   都只是「姓氏」的意思，说的**不是**这个姓属于哪种语言 ——
   被解释的词是德语词。给「德语姓氏」或就给「姓氏」，
   **绝不要给「法语姓氏」「西班牙语姓氏」**。

输出 JSON 数组：[{"id": "<标识号>", "zh": "<中文释义>"}]
只输出 JSON，不要解释。"""

LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{3,}")
# 源语言名漏进中文答案的样子
LEAK = re.compile(r"(法语|法文|意大利语|意语|西班牙语|西语|葡萄牙语|葡语)")


def _bare(s):
    """去掉标点空白再比 —— `Staudach-Egerndach.` 与词头只差一个句点。"""
    return re.sub(r"[\s.,;:!?()（）。，、]+", "", s or "").lower()


META = re.compile(r"的复数|的单数|的属格|的与格|的宾格|的第[一二]分词|的过去分词|"
                  r"的变位|的变格|的比较级|的最高级|参见|同上|见上|这个词|该词|阴性形式|阳性形式")
TAIL = re.compile(r"[。．.!！?？；;]$")
# 源语言的指针说法（模型该给空串却照译了的样子）
PTR_SRC = re.compile(r"(forme fléchie|pluriel de|féminin de|masculin de|participe|"
                     r"plurale di|femminile di|plural de|femenino de|particípio)", re.I)


def _assert_de():
    assert paths.DB.name == "synapse-dict-de.sqlite", "🔴 paths 不是 de 的：%s" % paths.DB


def build_pool():
    """扫四版 → 池子落盘。判据：**当前空白页** ∩ 该版有真释义。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    blank = {w: i for i, w in con.execute(
        "SELECT id, word FROM dict d"
        " WHERE NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
        "   AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)"
        "   AND COALESCE(d.exchange,'')=''")}
    pos_of = dict(con.execute("SELECT word, COALESCE(pos,'unknown') FROM dict"))
    con.close()
    print("■ 当前空白页 %s" % format(len(blank), ","))

    items, taken = [], set()
    for ed, langname in EDITIONS:
        n = 0
        with gzip.open(paths.DUMPS / ("%s.jsonl.gz" % ed), "rt", encoding="utf-8") as fh:
            for line in fh:
                if '"de"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("lang_code") != "de":
                    continue
                w = (o.get("word") or "").strip()
                # 🔴 一个词形只翻一版：几版都有时按 fr>it>es>pt 取第一版。
                #    不这么做就会给同一个空白页写进两套互相矛盾的中文。
                if w not in blank or w in taken:
                    continue
                gl = [(s.get("glosses") or [""])[0].strip()
                      for s in (o.get("senses") or []) if is_real_sense(s)]
                gl = [g for g in gl if g]
                if not gl:
                    continue
                taken.add(w)
                for k, g in enumerate(gl):
                    items.append({
                        "id": SEP.join((w, ed, str(k))),
                        "word": w, "pos": POS_MAP.get(pos_of.get(w, "unknown"),
                                                      pos_of.get(w, "unknown")),
                        "lang": langname, "src": g, "ed": ed, "k": k,
                    })
                n += 1
        print("   %-16s 覆盖空白词形 %s" % (ed, format(n, ",")))

    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids)), "🔴 锚定键在本批内不唯一"
    POOL.parent.mkdir(parents=True, exist_ok=True)
    POOL.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    chars = sum(len(i["src"]) for i in items)
    print("\n⇒ 词形 %s ｜义项 %s ｜原文 %s 字符（均 %.0f）→ %s"
          % (format(len(taken), ","), format(len(items), ","),
             format(chars, ","), chars / max(len(items), 1), POOL))


def pool():
    assert POOL.exists(), "🔴 池子还没建：先跑 --build-pool"
    return json.loads(POOL.read_text(encoding="utf-8"))


def controls(items, got, title):
    """判据**为这一族重写**。与 1.5b 的差别写在每一条上。"""
    c, ex = Counter(), {}
    seen = defaultdict(set)

    def hit(k, a, b):
        c[k] += 1
        ex.setdefault(k, (a, b))

    n = 0
    for it in items:
        rec = got.get(it["id"])
        if not rec:
            continue
        n += 1
        z = (rec.get("zh") or "").strip()
        src, w = it["src"], it["word"]
        if not z:
            hit("留空（模型判定给不出）", "%s ← %s" % (w, src[:36]), "")
            continue
        if not has_han(z):
            hit("🔴 一个汉字都没有", w, z)
        if z.strip().lower() == w.strip().lower():
            hit("🔴 把德语词头原样抄回来了（规则 3）", w, z)
        if META.search(z):
            hit("🔴 元描述当释义（规则 5）", w, z)
        if TAIL.search(z):
            hit("🔴 带句末标点（规则 8）", w, z)
        # 🔴 这一条是本族**独有**的：源头自己是指针，模型该给空串却照译了。
        if PTR_SRC.search(src):
            hit("🔴 源头是指针却给了释义（规则 4）", src[:36], z)
        # 🔴 本族独有其一：源头只把词头重复一遍，模型却给了释义 ——
        #    切片第一轮 11/200＝5.5%，全是德国小市镇的**生造音译**。
        if _bare(src) == _bare(w):
            hit("🔴 源头只重复词头却给了释义（规则 3，多半是生造音译）", src[:36], z)
        # 🔴 本族独有其二：源语言漏进输出（`Hebert [法语] → 法语姓氏`）。
        #    第一轮 4/200＝2.0%，起因是 payload 里发了 `lang` ⇒ 已把那个字段拆掉。
        if LEAK.search(z):
            hit("🔴 源语言漏进输出（规则 10）", "%s ← %s" % (w, src[:28]), z)
        if len(LATIN.findall(z)) >= 2 and has_han(z):
            hit("残留外文（≥2 个拉丁词，专名保留是允许的）", w, z)
        if len(z) > max(40, len(src) * 2):
            hit("比原文长一倍以上", src[:36], z[:36])
        seen[z].add(src)

    dup = sum(len(v) for v in seen.values() if len(v) > 3)
    n = max(n, 1)
    print("\n══ %s（%s 条）══" % (title, format(n, ",")))
    for k, v in c.most_common():
        print("  %-42s %7s  %5.2f%%" % (k, format(v, ","), 100.0 * v / n))
        a, b = ex[k]
        print("        %-40s → %s" % (str(a)[:40], str(b)[:40]))
    print("  %-42s %7s  %5.2f%%" % ("一个中文对 >3 条不同原文（疑似泛化）",
                                    format(dup, ","), 100.0 * dup / n))
    hard = [k for k in c if k.startswith("🔴") and c[k] > 0.02 * n]
    print("  %s" % ("🔴 硬闸红了（>2%）：" + "；".join(hard) if hard
                    else "✅ 硬闸过（每条 🔴 都 ≤2%）"))
    return not hard


def apply_db(items, got):
    """把译好的写库：新建 `sense` + `sense_gloss(zh)` + `sense_src`（源语言原文）。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = dict(con.execute("SELECT word, id FROM dict"))
    sid = con.execute("SELECT max(id) FROM sense").fetchone()[0]
    con.close()

    senses, glosses, srcs = [], [], []
    rank_of = Counter()
    seen_zh = defaultdict(set)
    empty = 0
    for it in items:
        rec = got.get(it["id"])
        z = (rec or {}).get("zh", "").strip()
        if not z:
            empty += 1
            continue
        w = it["word"]
        if w not in wid:
            continue
        if z in seen_zh[w]:          # 同一个词形译出两条一样的中文 ⇒ 只留一条
            continue
        seen_zh[w].add(z)
        rank_of[w] += 1
        sid += 1
        senses.append((sid, wid[w], rank_of[w], it["pos"] or None, None))
        glosses.append((sid, "zh", "equivalent", 0, z, SRC))
        srcs.append((wid[w], sid, it["ed"], "kk-%s:%s#%d" % (it["ed"][:2], w, it["k"]),
                     it["ed"][:2], it["src"], None))

    refs = [r[3] for r in srcs]
    assert len(refs) == len(set(refs)), "🔴 src_ref 有重复"
    print("■ 将写入 sense %s ／ sense_gloss %s ／ sense_src %s ｜模型留空丢掉 %s"
          % (format(len(senses), ","), format(len(glosses), ","),
             format(len(srcs), ","), format(empty, ",")))
    if not senses:
        print("   没有可写的。")
        return
    with dbtool.session("de-foreign-defs", expect={
            "#sense": len(senses), "#sense_gloss": len(glosses),
            "#sense_src": len(srcs)}) as s:
        s.executemany("INSERT INTO sense (id,word_id,rank,pos,gender) VALUES (?,?,?,?,?)",
                      senses)
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src)"
                      " VALUES (?,?,?,?,?,?)", glosses)
        s.executemany("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags)"
                      " VALUES (?,?,?,?,?,?,?)", srcs)


def main():
    _assert_de()
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-pool", action="store_true", dest="build_pool")
    ap.add_argument("--slice", type=int, default=0)
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if a.build_pool:
        return build_pool()

    items = pool()
    got = slot_translate.done_keys(OUT, land="id")
    print("■ 待译义项 %s ｜已译 %s ｜还差 %s"
          % (format(len(items), ","), format(len(got), ","),
             format(sum(1 for i in items if i["id"] not in got), ",")))

    want = (random.Random(1).sample(items, min(a.slice, len(items)))
            if a.slice else items)
    if not a.apply:
        todo = [i for i in want if i["id"] not in got]
        if todo:
            slot_translate.translate(todo, SYS, OUT,
                                     # 🔴 **`lang` 有意不发**（结构性拆掉泄漏通道）：
                                     # 切片实测 4/200＝2.0% 把源语言写进了答案
                                     # （`Hebert [法语] → 法语姓氏`），而模型自己认得出
                                     # 法语还是西班牙语。`[[context-you-give-leaks-into-output]]`：
                                     # 不是在 prompt 里请它忽略，是根本不给。
                                     fields=("id", "word", "pos", "src"),
                                     keep=("id", "word", "src", "ed", "k", "pos"),
                                     key_field="id", land="id")
            got = slot_translate.done_keys(OUT, land="id")

    ok = controls(want, got, "控制判据（外语释义专用）")
    if a.read:
        xs = [i for i in random.Random(3).sample(want, min(a.read * 3, len(want)))
              if i["id"] in got][:a.read]
        print("\n══ 打样 %d 条（原文与译文并排）══" % len(xs))
        for i in xs:
            print("   %-22s [%s] %-40s → %s"
                  % (i["word"][:22], i["lang"][:3], i["src"][:40],
                     got[i["id"]].get("zh", "")[:30]))
    if a.apply:
        assert ok, "🔴 控制判据没过，不写库"
        apply_db(want, got)


if __name__ == "__main__":
    main()
