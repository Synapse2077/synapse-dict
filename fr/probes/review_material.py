#!/usr/bin/env python3
"""导**第二轮**外审材料：渲染成品 + 源值附录。2026-08-28。

═══ 为什么要第二轮 ═══
第一轮（2026-08-27，37 个词条）产出 60 余条发现，收敛成族 A–D，是这一整段工作的起点。
之后我改动了不少**展示层**的东西：关系层第一次接线、连诵标签、词头阴阳性判据换成
`frHeadGender`（三条渲染路径）、频次层与录音层落库。
`[[it-display-layer-stage8]]` 的教训是：**三层数据的闸全绿、库里查不出异常，
真渲染出来立刻看见三个缺陷** —— 改完展示层不重新看渲染成品，等于没验收。

═══ 这一轮与上一轮唯一的方法差别：材料带**源值** ═══
上一轮两家**各错 4 次，形状完全一样**：拿标准法语当判据去否定源里记录的方言／俚语／
窄式标音（`[pa.seç]`、`librairie`「烟杂店」、`mari`「大麻」、`cogne` 的 `[kʌnj]`）。
根因不是模型差，是**我给的材料里没有权威源值**（`[[llm-as-evaluator-discipline]]` 第⑧条：
判官 payload 必须带权威源值）—— 它们看不见「这条是 fr-edition 的 narrow 标音」，
只能拿自己脑子里的标准法语去比。
⇒ 本脚本在每个词条后面附一段 `〈源值〉`：读音的 `src`/`notation`/`tags`，
   义项的证据来源版本，关系的来源版本。**判据从「像不像对的」变成「源里有没有」。**

⚠️ 附录只写**来源**，不写「所以这条是对的」—— 那是把结论写进材料
   （`[[llm-as-evaluator-discipline]]` 第⑨条）。源里有的也可能是源自己错了，
   两家仍然可以指出，只是要说明理由，我再回源裁决。

═══ 抽样不许手挑 ═══
按数据分层，层内用 `id` 的确定性伪随机排序取前 n 条 —— 同一个种子重跑结果一样，
而我没有机会挑「好看的词」。层的设计对准两件事：
  ①**这一轮改过的东西**（关系 / 连诵 / 词头性别 / 例句挂载）
  ②**开放发现**（常用多义词 / 专名 / 纯随机）—— 上一轮的族 A–D 全是从这类词里冒出来的。

用法（仓库根目录）：
    python3 fr/probes/review_material.py                 # 抽样 + 渲染 + 出材料
    python3 fr/probes/review_material.py --words a b c   # 指定词（复现某次材料）
然后：
    for f in data/work/fr/review2/part*.md; do python3 scripts/consult.py "$f"; done
"""
import argparse
import json
import pathlib
import re
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import paths  # noqa: E402

OUT = paths.WORK / "review2"
ROOT = paths.ROOT

# 层内确定性伪随机：Knuth 乘数 + 大质数取模。同一库同一层永远同一批词，
# 而 id 与「词好不好看」无关 ⇒ 我挑不动。
SHUF = "((d.id * 2654435761) % 1000003)"

# 🔴 每层都要说清**为什么抽这一层** —— 上一轮的收获全来自「层选对了」，
#    而层选错（比如全抽高频词）就只能看见我已经看过的那部分库。
STRATA = [
    ("关系层（本轮新接线）", 6, """
        SELECT d.word FROM dict d
         WHERE d.id IN (SELECT word_id FROM sense_relation
                         GROUP BY word_id HAVING COUNT(DISTINCT kind) >= 3)
           AND d.freq_zipf IS NOT NULL
         ORDER BY {S} LIMIT ?"""),
    ("连诵读音（本轮新标签）", 3, """
        SELECT d.word FROM dict d
         WHERE d.id IN (SELECT word_id FROM pronunciation WHERE context='liaison')
         ORDER BY {S} LIMIT ?"""),
    ("词形性别被压平（本轮新判据 frHeadGender）", 4, """
        SELECT d.word FROM dict d
         WHERE d.gender='mf'
           AND d.id IN (SELECT word_id FROM sense WHERE hidden=0 AND gender IS NOT NULL)
         ORDER BY {S} LIMIT ?"""),
    ("带领域标签（族 C 面）", 4, """
        SELECT d.word FROM dict d
         WHERE d.id IN (SELECT s.word_id FROM sense s JOIN sense_tag t ON t.sense_id=s.id
                         WHERE t.kind='topic' AND s.hidden=0)
           AND d.freq_zipf IS NOT NULL
         ORDER BY {S} LIMIT ?"""),
    ("多义常用词（开放发现）", 6, """
        SELECT d.word FROM dict d
         WHERE d.freq_zipf >= 3.5
           AND (SELECT COUNT(*) FROM sense s WHERE s.word_id=d.id AND s.hidden=0) >= 5
         ORDER BY {S} LIMIT ?"""),
    ("例句多且跨义项（族 A 面）", 6, """
        SELECT d.word FROM dict d
         WHERE d.id IN (
                SELECT s.word_id FROM example e JOIN sense s ON s.id=e.sense_id
                 WHERE e.hidden=0 GROUP BY s.word_id
                HAVING COUNT(*) >= 4 AND COUNT(DISTINCT e.sense_id) >= 2)
         ORDER BY {S} LIMIT ?"""),
    ("专名", 4, """
        SELECT d.word FROM dict d
         WHERE d.pos='name'
           AND (SELECT COUNT(*) FROM sense s WHERE s.word_id=d.id AND s.hidden=0) >= 1
         ORDER BY {S} LIMIT ?"""),
    ("纯随机（词元，有中文）", 6, """
        SELECT d.word FROM dict d
         WHERE d.is_lemma=1
           AND d.id IN (SELECT s.word_id FROM sense s JOIN sense_gloss g
                          ON g.sense_id=s.id AND g.lang='zh' WHERE s.hidden=0)
         ORDER BY {S} LIMIT ?"""),
]

HEAD = """# 法汉词典词条评审（第二轮）

下面是一部**给中文用户用的法语词典**的词条，内容按用户在网页上看到的样子导出
（`渲染` 段每行的顺序就是屏幕上从上到下的顺序）。
数据来自法语版、英语版等多个维基词典版本，中文释义与例句译文由模型生成。

每个词条后面跟一段 `〈源值〉`，写明这些内容**是从哪一版抄来的**：
读音的来源版本、转写风格（音位式 phonemic `/…/` ／ 音值式 narrow `[…]`）与源标签，
义项的证据来源版本，关系的来源版本。

🔴 **请把源值当作事实来读**：源里记录的方言音、俚语义、窄式标音**不是我们编的**。
   如果你认为源本身错了，仍然可以指出，但要写明理由（哪一版、错在哪），
   不要仅因为「标准法语里没有这个」就判错 —— 上一轮两家在这上面各错了 4 次。

请逐条读，**找出你认为错的地方**。我关心的是内容对不对，尤其是：
- 中文释义是不是这个法语词／这条义项真正的意思（错义、漏掉主要义项、译反方向、过度直译习语）
- 中文释义、法语定义、英文对应词三者说的是不是同一件事（三者打架说明某一条挂错了义项）
- 例句的中文译文对不对，以及这条例句是不是**挂在了正确的义项**下面
- 「相关词」（近义／反义／上下位／整体部分）分组对不对，有没有放错组或放错词
- 页头的语法信息（词性、阴阳性、助动词、变位组、CEFR）是不是这个词的
- 读音：有没有混进**别的词**的读音；标了「连诵」的是不是真的连诵形
- 专名（人名／地名／居民称谓／物种名）的中文处理对不对
- 标签（地区／语域／领域）挂得对不对，有没有把某一版特有的标签安到通用义项上

输出格式：一条问题一行，写清 `词条 → 哪条义项 → 什么问题 → 你的依据/正确说法`。
按严重程度从高到低排。**拿不准的也写出来，但标上「存疑」。**
没问题的词条不要写。不要复述我给你的内容，不要泛泛评价。

---
"""

NOTATION_ZH = {"phonemic": "音位式", "narrow": "音值式 narrow"}


def flat_tags(raw):
    """标签列可能是**数组**（`pronunciation.tags`）也可能是**对象**
    （`sense_src.raw_tags` = `{"tags": [...], "raw_tags": [...], "topics": [...]}`）。

    🔴 第一版对两种都 `"/".join(map(str, t))`，对象那种就把**键名**打了出来 ——
       每条义项后面挂着 `{tags/raw_tags/topics}`，看着像真标签。
       评审材料里的假标签比漏标签更坏：它会引出一整族「这个标签挂错了」的假发现。
    """
    if not raw or raw in ("[]", "null", "{}"):
        return []
    try:
        t = json.loads(raw)
    except ValueError:
        return []
    if isinstance(t, dict):
        t = [x for v in t.values() if isinstance(v, list) for x in v]
    return [str(x) for x in t] if isinstance(t, list) else []


def sample(con, n_over=None):
    words, seen = [], set()
    for name, n, sql in STRATA:
        got = []
        for (w,) in con.execute(sql.format(S=SHUF), (n * 4,)):
            if w in seen:
                continue
            seen.add(w)
            got.append(w)
            if len(got) >= n:
                break
        print("  %-32s %d 词  %s" % (name, len(got), " ".join(got[:6])), file=sys.stderr)
        words += got
    return words


def render(words):
    """走 `render-dump.tsx` —— 与 `contract-check-fr.tsx` 同一条渲染路径。

    🔴 不能改成查库或查接口拼材料：`[[it-display-layer-stage8]]` 三个缺陷全都
       **只在渲染之后才存在**，接口返回是对的。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    wf, rf = OUT / "words.txt", OUT / "rendered.md"
    wf.write_text("\n".join(words) + "\n", encoding="utf-8")
    subprocess.run(
        ["npx", "tsx", "--tsconfig", "apps/web/tsconfig.json",
         "apps/web/src/render-dump.tsx", "--lang", "fr",
         "--file", str(wf), "--out", str(rf)],
        cwd=ROOT, check=True)
    blocks, cur = {}, None
    for line in rf.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (.+)$", line)
        if m:
            cur = m.group(1)
            blocks[cur] = []
        elif cur:
            blocks[cur].append(line)
    return {w: "\n".join(v).strip() for w, v in blocks.items()}


def provenance(con, word):
    """一个词条的源值附录。**只写来源，不写判断。**"""
    row = con.execute(
        "SELECT id FROM dict WHERE word=? ORDER BY is_lemma DESC, id LIMIT 1", (word,)).fetchone()
    if not row:
        return "（库里查无此词）"
    wid = row[0]
    out = []

    prons = con.execute(
        "SELECT ipa, notation, region, tags, src, is_primary, context, pos"
        "  FROM pronunciation WHERE word_id=? ORDER BY is_primary DESC, id", (wid,)).fetchall()
    if prons:
        out.append("读音：")
        for ipa, nota, region, tags, src, prim, ctx, pos in prons:
            bits = [NOTATION_ZH.get(nota, nota or "?"), src]
            if region:
                bits.append(region)
            if pos:
                bits.append("词性 " + pos)
            if ctx:
                bits.append("语境 " + ctx)
            t = flat_tags(tags)
            if t:
                bits.append("源标签 " + "/".join(t))
            out.append("  %s%-16s %s" % ("★" if prim else " ", ipa, "  ".join(bits)))

    senses = con.execute(
        "SELECT id, rank FROM sense WHERE word_id=? AND hidden=0 ORDER BY rank", (wid,)).fetchall()
    if senses:
        out.append("义项证据来源：")
    for sid, rank in senses:
        zh = con.execute(
            "SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' ORDER BY kind, seq LIMIT 1",
            (sid,)).fetchone()
        srcs = con.execute(
            "SELECT src, lang, raw_tags FROM sense_src WHERE sense_id=? ORDER BY id", (sid,)).fetchall()
        # 🔴 同一条出版义项可能合并了多版证据 —— 族 C（`cervelle` 被标成「路易斯安那」）
        #    就是「标签只来自其中一版」。所以这里必须把**每一版**都列出来，不能只列第一条。
        ev = []
        for s, lg, raw in srcs:
            t = flat_tags(raw)
            ev.append("%s(%s)%s" % (s, lg, ("{" + "/".join(t) + "}") if t else ""))
        tags = con.execute(
            "SELECT kind, value FROM sense_tag WHERE sense_id=? ORDER BY kind, value", (sid,)).fetchall()
        tg = ("  标签 " + " ".join("%s=%s" % kv for kv in tags)) if tags else ""
        out.append("  #%-2d %-22s ← %s%s" % (rank, (zh[0] if zh else "（无中文）")[:22],
                                             " + ".join(ev) or "（无证据行）", tg))

    rels = con.execute(
        "SELECT kind, src, COUNT(*) FROM sense_relation WHERE word_id=? GROUP BY kind, src", (wid,)).fetchall()
    if rels:
        out.append("关系来源：" + "  ".join("%s×%d %s" % (k, n, s) for k, s, n in rels))
    return "\n".join(out) or "（无源值）"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--words", nargs="*")
    ap.add_argument("--kb", type=int, default=56, help="每份材料上限（consult.py 的闸是 64KB）")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = a.words or sample(con)
    print("■ 共 %d 词，开始渲染" % len(words), file=sys.stderr)
    rendered = render(words)

    parts, cur, size = [], [], 0
    for w in words:
        body = "## %s\n\n%s\n\n〈源值〉\n\n```\n%s\n```\n" % (
            w, rendered.get(w, "（导出器没给出这个词）"), provenance(con, w))
        b = len(body.encode("utf-8"))
        # 🔴 分份要在**词条边界**上切：切碎一个词条 = 评审在没有上下文的半页上判，
        #    上一轮族 A 的判断全靠「这条例句挂在哪条义项下」这个上下文。
        if cur and size + b > a.kb * 1024 - len(HEAD.encode("utf-8")):
            parts.append(cur)
            cur, size = [], 0
        cur.append(body)
        size += b
    if cur:
        parts.append(cur)
    con.close()

    for i, p in enumerate(parts, 1):
        f = OUT / ("part%d.md" % i)
        f.write_text(HEAD + "\n".join(p), encoding="utf-8")
        print("✓ %s  %d 词  %.0f KB" % (f, len(p), len(f.read_bytes()) / 1024))


if __name__ == "__main__":
    main()
