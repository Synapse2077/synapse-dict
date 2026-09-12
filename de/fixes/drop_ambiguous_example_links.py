#!/usr/bin/env python3
"""清掉 21 条挂在**真歧义键**上的例句挂载。2026-09-11。

═══ 来历：改完生成侧「干跑对数」时逮到的 ═══
`pipeline/harvest_examples.py` 换成文本桥之后干跑，挂接数比库里**少 261 条**。
逐个查下来，全部来自 100 个「同一 (词形, 德语原文) 指向多条义项」的歧义键：

    95 个是**真重复义项** —— 德语原文和中文释义**都一字不差**
       （`Erdbeermilch` 两条、`Asterisk` 三条…），读者在页面上分不出来
       ⇒ 生成侧改成**确定性取 `sense_id` 最小的那条**（不是"先到先得"），差额从 261 → 21
     6 个是**德语原文撞车但义项确实不同**（中文不一样）
       ⇒ 生成侧**拒绝挂载**，而库里这 21 条是老桥 `setdefault`「先到先得」**任意挑的**

    met.          现挂「隐喻的」／候选还有「比喻的」
    beidseits     「在两边」／「在…的两边」
    auszugsweise  「摘录地」／「摘录的」
    gradweise     「逐步地」／「逐步的」
    Brigadist     「工作队成员」／「旅成员」   ← 这条是真的两回事

⇒ 清掉，让**库与生成侧相等**。21 / 444,094 = 0.005%，例句仍然可见（掉回词条级例句区）。
   🔴 理由不是"这 21 条一定错"，是**库与生成侧不一致就是漂移**，
     下一次重跑会静默地把它改掉，而那时没人知道发生了什么
     （`[[replay-scripts-undo-fixes]]`）。方向上也是「错换缺」，
     与 `FRAMEWORK §一`「错比缺更伤权威」一致。

用法（在 de/ 目录下）：
    python3 fixes/drop_ambiguous_example_links.py            # 干跑
    python3 fixes/drop_ambiguous_example_links.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")


def plan(con):
    q = con.execute
    zh = {sid: t for sid, t in q("SELECT sense_id, text FROM sense_gloss WHERE lang='zh'")}
    cand = {}
    for w, t, sid in q("""SELECT d.word, g.text, g.sense_id FROM sense_gloss g
            JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id
            WHERE g.lang='de' AND g.text IS NOT NULL AND g.text<>''"""):
        cand.setdefault((w, (t or "").strip()), set()).add(sid)
    # 判据用**含义**：中文分得开才叫歧义；中文也一样的是重复义项，不在此列。
    bad = {k for k, v in cand.items() if len(v) > 1 and len({zh.get(x) for x in v}) > 1}
    ids = [eid for eid, w, sg in q(
        "SELECT id, word, src_gloss FROM example WHERE sense_id IS NOT NULL AND src_gloss IS NOT NULL")
        if (w, (sg or "").strip()) in bad]
    return ids, len(bad), len(cand)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ids, n_bad, n_keys = plan(con)
    before = con.execute("SELECT COUNT(*) FROM example WHERE sense_id IS NOT NULL").fetchone()[0]
    print("═══ 真歧义键上的例句挂载 ═══")
    print("   桥的键总数 %s ／ 真歧义键（中文分得开）%s ／ 要清的挂载 %s"
          % (f(n_keys), f(n_bad), f(len(ids))))
    # 闸：规模必须小（这是"任意挑"的残留，不是一个数据层）；且都还挂着
    checks = [("要清的条数 > 0", int(len(ids) > 0), 1),
              ("🔴 规模必须 < 1000（超了说明判据宽了）", int(len(ids) < 1000), 1)]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-40s %s / %s" % ("✅" if ok else "🔴", name, f(got), f(want)))
    con.close()
    if bad:
        print("\n🔴 闸红，不写。")
        return 1
    if not a.apply:
        print("\n(干跑。--apply 才写库)")
        return 0
    with dbtool.session("de-drop-ambiguous-example-links", expect={}) as s:
        s.executemany("UPDATE example SET sense_id=NULL WHERE id=?", [(i,) for i in ids])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    after = con.execute("SELECT COUNT(*) FROM example WHERE sense_id IS NOT NULL").fetchone()[0]
    con.close()
    ok = before - after == len(ids)
    print("\n%s 挂载 %s → %s（清掉 %s）" % ("✅" if ok else "🔴 数对不上", f(before), f(after), f(len(ids))))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
