#!/usr/bin/env python3
"""ko 词源译文里的**朝鲜古籍书名**写成了日文新字体／繁体 ⇒ 整名换成规范简体。B29，2026-10-31。

═══ 缺陷 ═══
词源层的中文是从**日文版**维基词典译的（`etymology_gloss`，deepseek-v4-flash），模型把书名照抄了日文写法：
    首见于《釈譜詳節》   《月印釈譜》   《竜飛御天歌》   《三綱行実図》   《楞厳経諺解》
648 行里 600 来行就是这个。安全繁简判据（`scripts/zh_t2s.py`）只认繁体、不认日文新字体
（釈 経 竜 図 訳 伝 円 楽 仏 鶏 続 増 厳），机械地转会造出《釈谱详节》《妙法莲华経谚解》这种
简繁日三混的东西 —— 所以 B29 那轮有意没转（R27 锁成名册 904 行）。

═══ 判据：逐个定的对照表，整名替换，其余一个字不动 ═══
`TITLES` 每一项是这部书在中文学界的规范简体写法。书名之外那 59 行里会被转的字**全部保留**：
古韩语汉字转写（`烏（耶鲁式：wo-）`、`薩囉`）、「賈 的汉字音」、「与汉语的「維基百科」比较」——
它们讲的就是那个字形。
⚠️ 替换按**长度从长到短**（`《訳語類解補》` 不许被 `訳語類解` 先吃掉一截；`[[regex-alternation-order]]`）。
⚠️ 只改出版层 `etymology_gloss.text`（我们付费译出的中文）；证据层 `etymology`（日文原文）一字不动。

跑（在仓库根）：
    python3 -u ko/fixes/fix_etym_book_titles.py            # 干跑：印对照表与命中数
    python3 -u ko/fixes/fix_etym_book_titles.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import re
import sqlite3

import dbtool
import paths

TITLES = {
    "釈譜詳節": "释谱详节",
    "月印釈譜": "月印释谱",
    "竜飛御天歌": "龙飞御天歌",
    "龍飛御天歌": "龙飞御天歌",
    "分類杜工部詩諺解": "分类杜工部诗谚解",
    "救急方諺解": "救急方谚解",
    "楞厳経諺解": "楞严经谚解",
    "訓民正音解例": "训民正音解例",
    "訓民正音諺解本": "训民正音谚解本",
    "訓蒙字会": "训蒙字会",
    "救急簡易方諺解": "救急简易方谚解",
    "妙法蓮華経諺解": "妙法莲华经谚解",
    "妙法蓮華經諺解": "妙法莲华经谚解",
    "癸丑日記": "癸丑日记",
    "鶏林類事": "鸡林类事",
    "円覚経諺解": "圆觉经谚解",
    "新増類合": "新增类合",
    "三綱行実図": "三纲行实图",
    "続三綱行実図": "续三纲行实图",
    "訳語類解補": "译语类解补",
    "訳語類解": "译语类解",
    "御製内訓": "御制内训",
    "小学諺解": "小学谚解",
    "南明集諺解": "南明集谚解",
    "禅宗永嘉集諺解": "禅宗永嘉集谚解",
    "朴通事諺解": "朴通事谚解",
    "国韓会話": "国韩会话",
    "国韓会語": "国韩会语",
    "百聯抄解": "百联抄解",
    "翻訳老乞大": "翻译老乞大",
    "翻訳小学": "翻译小学",
    "種徳新編諺解": "种德新编谚解",
    "家礼諺解": "家礼谚解",
    "杜詩諺解": "杜诗谚解",
    "語録解": "语录解",
    "晋書束皙伝": "晋书束皙传",
    "同文類解": "同文类解",
    "女訓諺解": "女训谚解",
    "法語諺解": "法语谚解",
    "新伝煮取焔硝方諺解": "新传煮取焰硝方谚解",
    "新伝煮取焰硝方諺解": "新传煮取焰硝方谚解",
    "諺解胎産集要": "谚解胎产集要",
    "諺解痘瘡集要": "谚解痘疮集要",
    "磨鏡軒集": "磨镜轩集",
    "四十二章経": "四十二章经",
    "詩経諺解": "诗经谚解",
    "正俗諺解李源周教授本": "正俗谚解李源周教授本",
    "痘瘡経験方": "痘疮经验方",
    "楽学軌範": "乐学轨范",
    "韓仏字典": "韩佛字典",
}
PAT = re.compile("|".join(re.escape(k) for k in sorted(TITLES, key=len, reverse=True)))


def fix(t):
    return PAT.sub(lambda m: TITLES[m.group(0)], t)


def plan(con):
    return [(rid, t, fix(t)) for rid, t in con.execute(
        "SELECT rowid, text FROM etymology_gloss WHERE lang='zh'") if t and fix(t) != t]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = plan(con)
    con.close()
    hits = {}
    for _r, t, _n in todo:
        for m in PAT.finditer(t):
            hits[m.group(0)] = hits.get(m.group(0), 0) + 1
    for k in sorted(TITLES, key=lambda k: -hits.get(k, 0)):
        print("   %4d  %s → %s" % (hits.get(k, 0), k, TITLES[k]))
    unused = [k for k in TITLES if not hits.get(k)]
    print("■ 要改 %d 行；对照表 %d 项，没命中的 %d 项%s" % (
        len(todo), len(TITLES), len(unused), "：%s" % unused if unused else ""))
    for _r, t, n in todo[::max(1, len(todo) // 8)]:
        print("     %s\n   → %s" % (t[:90].replace("\n", " "), n[:90].replace("\n", " ")))
    if not a.apply or not todo:
        return
    with dbtool.session("ko-fix-etym-book-titles") as s:
        s.executemany("UPDATE etymology_gloss SET text=? WHERE rowid=?", [(n, r) for r, _t, n in todo])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = len(plan(con))
    print("■ 写后回核：词源译文里仍有对照表里的旧书名 %d 行（期望 0）" % left)
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
