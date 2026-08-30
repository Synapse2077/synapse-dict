#!/usr/bin/env python3
"""外审取样：**规则写死、可复算、可被质疑**。2026-08-30。只读。

🔴 用户 2026-08-30 提的问题：「我怕你的 prompt 会存在给自己开脱的嫌疑，
   导致外审的结果偏向已有结果，你的 prompt 有偏袒性吗」——
   `[[llm-as-evaluator-discipline]]` ⑨ 记着这已经发生过一次：
   **把结论写进评审材料标题，两家收敛的是我的偏见**。

⇒ 取样必须**不由我挑**。本文件的规则：
   ① 固定种子，同样的库跑出同样的词表，**你可以自己重跑核对**
   ② **按已知风险类别配额**，而不是"我认为有代表性的词" ——
      配额本身覆盖的是**我最可能出错的地方**，不是我最有把握的地方
   ③ 每一类都取满，**包括我明知有问题的那几类**（隐藏义项、无中文、
      判据够不着的残渣）—— 不许只送干净样本

用法：python3 probes/review_sample.py [每类条数]
"""
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths   # noqa: E402

# 每一类都对应「我可能错在哪」，不对应「我做得好的地方」。
BUCKETS = [
    ("多义项高频词（译文错了最伤）",
     """SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
         WHERE COALESCE(s.hidden,0)=0 AND d.freq_zipf>=4
         GROUP BY d.id HAVING COUNT(*)>=4"""),
    ("阶段 1.5b 新翻的释义（本轮最大一笔支出）",
     """SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
         JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' AND g.src='model:def'
         GROUP BY d.id"""),
    ("例句中文（第二笔支出）",
     """SELECT e.word FROM example e JOIN example_gloss g
         ON g.example_id=e.id AND g.lang='zh' AND g.src='model:example'
         WHERE COALESCE(e.hidden,0)=0 GROUP BY e.word"""),
    ("巴葡欧葡读音不同（pt 独有，我判据改过四版）",
     """SELECT d.word FROM dict d JOIN pronunciation p ON p.word_id=d.id
         WHERE p.region='pt-BR' AND EXISTS(SELECT 1 FROM pronunciation q
           WHERE q.word_id=d.id AND q.region='pt-PT' AND q.ipa<>p.ipa) GROUP BY d.id"""),
    ("阶段 2c 补链的变形（476,580 条，判据打回四次）",
     """SELECT d.word FROM dict d JOIN inflection i ON i.word_id=d.id
         WHERE i.src LIKE '%-edition-forms' GROUP BY d.id"""),
    ("语义关系多的词（源头噪声可能混进来）",
     """SELECT d.word FROM dict d JOIN sense_relation r ON r.word_id=d.id
         WHERE r.kind<>'alt_of' GROUP BY d.id HAVING COUNT(*)>=8"""),
    ("🔴 有义项却没有中文（我知道有 2,939 条）",
     """SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
         WHERE COALESCE(s.hidden,0)=0 AND NOT EXISTS(
           SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')
         GROUP BY d.id"""),
    ("🔴 我隐掉了义项的词（判断可能是错的）",
     "SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id WHERE s.hidden=1 GROUP BY d.id"),
    ("专名 / 地名（音译最容易出错）",
     """SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
         WHERE s.pos='name' AND COALESCE(s.hidden,0)=0 GROUP BY d.id"""),
    ("多词词条（否定命令式、固定短语）",
     "SELECT word FROM dict WHERE word LIKE '% %' AND is_lemma=1"),
]


def main():
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    seen, out = set(), []
    for name, sql in BUCKETS:
        pool = [r[0] for r in con.execute(sql)]
        rnd = random.Random(20260830)          # 固定种子：同库同结果，可复算
        rnd.shuffle(pool)
        got = [w for w in pool if w not in seen][:per]
        seen.update(got)
        out.append((name, len(pool), got))
    con.close()
    print("# 外审取样（种子 20260830，规则见 probes/review_sample.py）\n")
    for name, n, got in out:
        print("## %s\n   池 %s ／ 取 %d：%s" % (name, f"{n:,}", len(got), " ".join(got)))
    print("\n合计 %d 个词" % len(seen))
    Path("/tmp/pt_review_words.txt").write_text("\n".join(sorted(seen)), encoding="utf-8")
    print("词表已写 /tmp/pt_review_words.txt")


if __name__ == "__main__":
    sys.exit(main())
