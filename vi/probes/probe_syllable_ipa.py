#!/usr/bin/env python3
"""§4.2 的裁决：**没有音标的 17,564 个词形，能不能从源头真值拼出来**。只读。2026-09-28。

═══ 为什么不是「写一套 G2P 规则」═══
`PLAYBOOK` 3.3 写着「别用 G2P 重算」，ko 的做法是**先拿源头真值当标尺量准确率，先验后用**。
但在越南语上有个比写规则更好的路子，而且它是**量出来的不是猜的**：

    282,804 条源头音标里，**98.76% 按空格切开后与正字法音节数完全一致**

越南语没有连读、没有变调，**一个音节的读音与它在词里的位置无关**。
⇒ 不写规则，直接从真值里抽 `(音节, 方言) → IPA` 对照表，再拼。
  好处是**用的是真人写的音标，不是我编的规则**（`[[criteria-from-meaning-not-form]]`）。

═══ 🔴 验法：**按词留出，不是按音节留出** ═══
按音节留出会作弊 —— 同一个词的其他方言行会把答案漏给测试集。
这里按**词形**分层留出 20%，训练集里出现过的音节才算「拼得出」。

⚠️ 这个脚本**只量不写库**。写不写、怎么写，看它给出的数字再定。

用法：
    python3 vi/probes/probe_syllable_ipa.py
    python3 vi/probes/probe_syllable_ipa.py --archive
"""
import argparse
import collections
import io
import random
import sqlite3
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import paths                                                      # noqa: E402
from criteria import _SYL_SEP                                     # noqa: E402

HOLDOUT = 0.2
SEED = 20260928


def load():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(
        "SELECT d.word, p.ipa, p.dialect, p.src FROM pronunciation p "
        "JOIN dict d ON d.id = p.word_id").fetchall()
    nopron = [w for (w,) in con.execute(
        "SELECT d.word FROM dict d LEFT JOIN pronunciation p ON p.word_id=d.id "
        "WHERE p.id IS NULL")]
    con.close()
    return rows, nopron


def syl(w):
    return [x for x in _SYL_SEP.split(w.strip()) if x]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", action="store_true")
    a = ap.parse_args()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rows, nopron = load()
        # 🔴🔴 **第一版实验的两个方法错误，都是当场量出来的：**
        #  ① 真值不是单值：同一 (词, 方言) 在源头里有 **19.0%** 给了多个不同 IPA
        #     ⇒「逐字符完全一致」这个指标本身不成立，应该比「与**任何一条**真值相同」
        #  ② 三版的转写约定不一样：词首喉塞音 ʔ 的比例
        #     en 18.7% ／ **vi 0.0%** ／ zh 19.5%
        #     ⇒ 把三版混进一张音节表，拼出来的是**嵌合体**（`[[multi-edition-methodology]]`）
        #  按 (方言, **版**) 切开之后，同一格里仍多值的只剩 3.1%。
        #  ⇒ 实验改成**按版做、按版比**。第一版那个 56.17% 量的是别的东西。
        print("■ 手上的料：%s 条真值音标 ／ %s 个词形没有音标"
              % (format(len(rows), ","), format(len(nopron), ",")))

        # ── 只留下「音节数与 IPA 段数一致」的那批当料
        usable = [(w, i, d, sr) for w, i, d, sr in rows if len(syl(w)) == len(i.split())]
        print("   其中可按音节对齐的 %s（%.2f%%）"
              % (format(len(usable), ","), 100 * len(usable) / len(rows)))

        # ── 🔴 按**词形**分层留出，不按音节
        words = sorted({w for w, _, _, _ in usable})
        rnd = random.Random(SEED)
        rnd.shuffle(words)
        cut = int(len(words) * (1 - HOLDOUT))
        train_w, test_w = set(words[:cut]), set(words[cut:])
        print("   按词形留出：训练 %s ／ 测试 %s"
              % (format(len(train_w), ","), format(len(test_w), ",")))

        # ── 训练：(音节, 方言) → IPA 计数
        tab = collections.defaultdict(collections.Counter)
        for w, i, d, sr in usable:
            if w not in train_w:
                continue
            for s, p in zip(syl(w), i.split()):
                tab[(s.lower(), d, sr)][p] += 1
        print("\n■ 对照表：%s 个 (音节, 方言, **版**) 组合" % format(len(tab), ","))
        amb = [k for k, v in tab.items() if len(v) > 1]
        print("   一个组合对多个 IPA 的 %s（%.1f%%）—— 取最高频那个"
              % (format(len(amb), ","), 100 * len(amb) / len(tab)))
        share = []
        for k in amb:
            v = tab[k]
            share.append(v.most_common(1)[0][1] / sum(v.values()))
        if share:
            share.sort()
            print("   这些歧义组合里，**最高频那个占比**中位数 %.1f%% ／ 最低 %.1f%%"
                  % (100 * share[len(share) // 2], 100 * share[0]))

        best = {k: v.most_common(1)[0][0] for k, v in tab.items()}

        # ── 测试：按词形拼，逐条比对
        # 真值按 (词, 方言, 版) 收成集合 —— **比「与任何一条真值相同」**
        truth = collections.defaultdict(set)
        for w, i, d, sr in usable:
            truth[(w, d, sr)].add(i)
        res = collections.Counter()
        wrong = []
        for key in sorted(truth):
            w, d, sr = key
            if w not in test_w:
                continue
            ss = [s.lower() for s in syl(w)]
            if any((s, d, sr) not in best for s in ss):
                res["拼不出（有音节没见过）"] += 1
                continue
            got = " ".join(best[(s, d, sr)] for s in ss)
            if got in truth[key]:
                res["✅ 与源头某一条真值逐字符相同"] += 1
            else:
                res["🔴 拼出来了但与真值都不同"] += 1
                if len(wrong) < 8:
                    wrong.append((w, d, sr, sorted(truth[key])[0], got))
        tot = sum(res.values())
        print("\n■ 留出集 %s 条的结果" % format(tot, ","))
        for k, v in res.most_common():
            print("   %-24s %8s  %5.1f%%" % (k, format(v, ","), 100 * v / tot))
        cov = tot - res["拼不出（有音节没见过）"]
        if cov:
            print("   ⇒ **在拼得出的那批里，准确率 %.2f%%**"
                  % (100 * res["✅ 与源头某一条真值逐字符相同"] / cov))
        print("\n   拼错的样本（真值 vs 拼出来的）：")
        for w, d, sr, i, g in wrong:
            print("     %-16s %-10s %-16s 真 %s" % (w, d, sr, i))
            print("     %-16s %-10s %-16s 拼 %s" % ("", "", "", g))

        # ── 对无音标那批的实际覆盖：拿**全量**表（不留出）算
        full = collections.defaultdict(collections.Counter)
        for w, i, d, sr in usable:
            for s, p in zip(syl(w), i.split()):
                full[(s.lower(), d, sr)][p] += 1
        fbest = {k: v.most_common(1)[0][0] for k, v in full.items()}
        dial = sorted({(d, sr) for _, d, sr in fbest})
        print("\n■ 拿全量表去够那 %s 个无音标词形" % format(len(nopron), ","))
        hit = collections.Counter()
        for w in nopron:
            ss = [s.lower() for s in syl(w)]
            got = [k for k in dial if all((s,) + k in fbest for s in ss)]
            hit["一个方言都拼不出" if not got else "至少一个方言拼得出"] += 1
        for k, v in hit.most_common():
            print("   %-22s %8s  %5.1f%%" % (k, format(v, ","), 100 * v / len(nopron)))
        gain = hit["至少一个方言拼得出"]
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        ntot = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
        have = con.execute("SELECT COUNT(DISTINCT word_id) FROM pronunciation").fetchone()[0]
        con.close()
        print("   ⇒ 覆盖率会从 **%.1f%%** 变成 **%.1f%%**"
              % (100 * have / ntot, 100 * (have + gain) / ntot))
    out = buf.getvalue()
    print(out, end="")
    if a.archive:
        paths.PROBE.mkdir(parents=True, exist_ok=True)
        f = paths.PROBE / "probe_syllable_ipa.txt"
        f.write_text(out, encoding="utf-8")
        print("■ 已存档 → %s" % f.relative_to(paths.ROOT))


if __name__ == "__main__":
    main()
