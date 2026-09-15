#!/usr/bin/env python3
"""搭配层佐证率：拿 kaikki dump **全文**做确定性比对。2026-09-14。

═══ 为什么先做这一步 ═══
`[[llm-as-evaluator-discipline]]` ⑩：能确定性回源比对的，根本不要问模型。
此前报的「74.2% 无佐证」用的是**我们自己那张 `example` 表**（es 仅 2.9 万条），
语料太小 ⇒ 那个数**不是错误率**，是"我们的小语料里查不到"。
dump 是 1 GB 级的：词条名 + 全部例句 + 全部释义 + derived/related，语料大两个数量级。

🔴 **佐证 ≠ 正确，无佐证 ≠ 错误。** 这一步只做一件事：把 98,968 条切成
「有外部出处的」与「没有的」，后者才值得花钱送判官。别把这里的数字当错误率报出去。
   · 无佐证≠错：`uñas postizas 假指甲` 是正常西语词组，只是没人给它写过例句。
   · 有佐证≠对：`color primária` 那种，词真、能撞上，错在搭配本身不地道。

═══ 已跑出来的（2026-09-14，跑到 fr 被叫停）═══
    es  llm:doubao        28,960 条   佐证 24.3%
    it  llm:doubao        23,196 条   佐证 27.5%
    it  kaikki:subentry      303 条   佐证 **100.0%**   ← 现成的正控
    it  kaikki:pseudo-sense  376 条   佐证 **100.0%**   ← 同上
⭐ kaikki 来源那 679 条本来就是从 dump 搬出来的，100% 先**证明匹配器没问题**
   （归一化/分词没把真的漏掉）。有这个对照，豆包那 24–27% 才读得出意思。
⏳ 未跑：fr / pt / de。中间结果 `colloc_<lang>.json`（命中的 collocation.id）。

⚠️ 匹配按**词序列**不按裸子串：`dar` 不该因为 `dar cuenta` 里有 `dar` 就算佐证。
   短语按空白切成词，在语料的词序列里找连续匹配（大小写与重音归一后比）。
"""
import gzip
import json
import re
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DUMPS = Path('data/dumps')
KK = {'es': 'kaikki.org-dictionary-Spanish.jsonl',
      'it': 'kaikki.org-dictionary-Italian.jsonl',
      'fr': 'kaikki.org-dictionary-French.jsonl',
      'pt': 'kaikki.org-dictionary-Portuguese.jsonl',
      'de': 'kaikki.org-dictionary-German.jsonl'}
EDITION = {'es': 'eswiktionary.jsonl.gz', 'it': 'itwiktionary.jsonl.gz',
           'fr': 'frwiktionary.jsonl.gz', 'pt': 'ptwiktionary.jsonl.gz',
           'de': 'dewiktionary.jsonl.gz'}

WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)


def norm(s):
    """归一：小写 + 去重音 + 弯撇号统一。判据要吃掉排版差异，不吃掉词。"""
    s = s.replace('’', "'")
    s = unicodedata.normalize('NFD', s.lower())
    return ''.join(c for c in s if not unicodedata.combining(c))


def toks(s):
    return [norm(m.group(0)) for m in WORD.finditer(s)]


def texts_of(o):
    """一条 dump 记录里所有值得当语料的文本。"""
    yield o.get('word') or ''
    for s in o.get('senses') or []:
        for g in s.get('glosses') or []:
            yield g
        for e in s.get('examples') or []:
            yield e.get('text') or ''
            yield e.get('english') or ''
    for k in ('derived', 'related', 'synonyms', 'antonyms', 'proverbs',
              'hypernyms', 'hyponyms', 'coordinate_terms'):
        for r in o.get(k) or []:
            if isinstance(r, dict):
                yield r.get('word') or ''
    for t in o.get('etymology_texts') or []:
        yield t
    yield o.get('etymology_text') or ''


def main(lang):
    con = sqlite3.connect('file:data/db/synapse-dict-%s.sqlite?mode=ro' % lang, uri=True)
    rows = con.execute("SELECT id, text, src FROM collocation").fetchall()
    con.close()
    # 短语 → 词序列；按首词建索引，扫语料时只比首词相同的那几条
    byfirst = defaultdict(list)
    seq = {}
    for cid, text, src in rows:
        t = toks(text)
        if not t:
            continue
        seq[cid] = (t, src)
        byfirst[t[0]].append(cid)
    print('■ %s：搭配 %s 条，首词索引 %s 个'
          % (lang, format(len(seq), ','), format(len(byfirst), ',')), flush=True)

    hit = set()
    t0 = time.time()
    for path, opener in ((DUMPS / KK[lang], open),
                         (DUMPS / EDITION[lang], gzip.open)):
        if not path.exists():
            print('   (跳过，不在盘上：%s)' % path.name)
            continue
        with opener(path, 'rt', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if i % 500000 == 0 and i:
                    print('   %s %s 行 / %ds / 已佐证 %s'
                          % (path.name[:22], format(i, ','), time.time() - t0,
                             format(len(hit), ',')), flush=True)
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                for txt in texts_of(o):
                    if not txt:
                        continue
                    tk = toks(txt)
                    for p, w in enumerate(tk):
                        for cid in byfirst.get(w, ()):
                            if cid in hit:
                                continue
                            s, _ = seq[cid]
                            if tk[p:p + len(s)] == s:
                                hit.add(cid)
    n = len(seq)
    by_src = defaultdict(lambda: [0, 0])
    for cid, (_, src) in seq.items():
        by_src[src or '(NULL)'][0] += 1
        if cid in hit:
            by_src[src or '(NULL)'][1] += 1
    print('\n■ %s 佐证率：%s / %s = %.1f%%'
          % (lang, format(len(hit), ','), format(n, ','), 100 * len(hit) / n))
    for src, (tot, ok) in sorted(by_src.items(), key=lambda x: -x[1][0]):
        print('     %-22s %7s 条   佐证 %6s (%.1f%%)'
              % (src, format(tot, ','), format(ok, ','), 100 * ok / tot))
    out = Path('/Users/fangyi/.claude/jobs/c235368c/tmp/colloc_%s.json' % lang)
    out.write_text(json.dumps({'hit': sorted(hit), 'total': n}), encoding='utf-8')
    print('   → %s' % out)


if __name__ == '__main__':
    for lg in (sys.argv[1:] or ['es']):
        main(lg)
