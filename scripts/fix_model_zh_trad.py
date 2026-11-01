#!/usr/bin/env python3
"""B29 最后一块：ko/vi **模型写的中文**里的繁体 —— 按逐行裁决清单改，不机械地转。2026-10-31。

═══ 为什么不能机械地转 ═══
ko 904 行／vi 82 行，`scripts/zh_t2s.py` 转一遍都会变，但读下来大半**该保留**：
· 汉字词表 `過去/과거`、括号里注的韩文汉字 `总统夫人（大統領令夫人）` —— 韩文汉字本来就是繁体
· 汉文／喃字原文 `又棄之路中　牛馬避之 又把它丢弃…`、`𧐖𥐇麻吱䖳𨱽`（转了喃字原文就坏了）
· 讲字本身 `鍔的异体`、`學(학)的简化字是学(학)`、`法语写作“法語”`（转了句子就没意义了）
· 人名 `李熙昇`、`胡季犛`；五音 `徵`；和合本的 `藉着`（规范用法）
ko 的词源 646 行另有专门的书名对照表（`ko/fixes/fix_etym_book_titles.py`：日文新字体 `《釈譜詳節》`）。

═══ 判据：逐行裁决清单 `<lang>/fixes/b29_model_zh.json` ═══
每条：表、rowid、`action`（convert 整行按安全判据转／edit 只改指定部分／dedupe 简繁各写一遍删掉繁体那一半）、
`orig`（裁决时读到的原文）、`new`、`why`。**没列进清单的行＝有意保留**（ko R27 锁住剩下的数）。
⚠️ `orig` 与库里当前原文逐字相同才生效；原文变了 ⇒ 红（裁决的是那一句，不是那个 rowid）。

· ko：出版文本就是 `text`（与 R26 同）⇒ 本脚本直接写库。
· vi：`text` 是源头原文（外锚闸逐字比），出版正文在 `text_pub`、由 `vi/pipeline/zh_pub.py` 统一生成 ⇒
  `zh_pub` 调本文件的 `overrides()` 拿裁决，本脚本对 vi 只做核对、不写库（写了也会被下一次同步盖掉）。

跑（在仓库根）：
    python3 -u scripts/fix_model_zh_trad.py --lang ko            # 干跑：逐条印
    python3 -u scripts/fix_model_zh_trad.py --lang ko --apply
    python3 -u scripts/fix_model_zh_trad.py --lang vi            # 只核对；写库走 vi/pipeline/zh_pub.py --apply
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ("ko", "vi")
SRC_COL = {"ko": "text", "vi": "text"}          # 裁决时读的那一列（原文）
PUB_COL = {"ko": "text", "vi": "text_pub"}      # 出版正文所在列


def decisions(lang):
    return json.loads((ROOT / lang / "fixes/b29_model_zh.json").read_text())["rows"]


def status(con, lang):
    """→ [(决定, 状态)]，状态：pending 待改／done 已生效／drift 原文变了（红）／gone 行不在了（红）。"""
    out = []
    for d in decisions(lang):
        r = con.execute("SELECT %s, %s FROM %s WHERE rowid=?" % (SRC_COL[lang], PUB_COL[lang], d["table"]),
                        (d["rowid"],)).fetchone()
        if r is None:
            out.append((d, "gone"))
            continue
        src, pub = r
        if lang == "ko" and src == d["new"]:
            out.append((d, "done"))                 # ko 原地改：改完原文就是新文
        elif src != d["orig"]:
            out.append((d, "drift"))
        else:
            out.append((d, "done" if pub == d["new"] else "pending"))
    return out


def overrides(con, lang="vi"):
    """vi `zh_pub` 用：{(表, rowid): 出版正文}。原文漂了就炸 —— 不许静默退回照抄。"""
    bad = [d for d, s in status(con, lang) if s in ("drift", "gone")]
    if bad:
        raise SystemExit("🔴 B29 裁决清单与库对不上 %d 条（原文变了或行不在了）：%s"
                         % (len(bad), [(d["table"], d["rowid"]) for d in bad[:5]]))
    return {(d["table"], d["rowid"]): d["new"] for d in decisions(lang)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=LANGS)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT / a.lang))
    import dbtool
    con = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    st = status(con, a.lang)
    con.close()
    for d, s in st:
        print("   [%s] %-7s %s:%d  %s\n                        → %s" % (
            s, d["action"], d["table"], d["rowid"], d["orig"][:70].replace("\n", " / "),
            d["new"][:70].replace("\n", " / ")))
    cnt = {k: sum(1 for _d, s in st if s == k) for k in ("pending", "done", "drift", "gone")}
    print("■ %s 裁决 %d 条：%s" % (a.lang, len(st), cnt))
    if cnt["drift"] or cnt["gone"]:
        raise SystemExit("🔴 原文变了／行不在了 —— 重新裁决那几条")
    if a.lang == "vi":
        print("（vi 的出版正文由 `python3 -u vi/pipeline/zh_pub.py --apply` 写）")
        return
    todo = [d for d, s in st if s == "pending"]
    if not a.apply or not todo:
        return
    with dbtool.session("b29-model-zh-%s" % a.lang) as s:
        for t in sorted({d["table"] for d in todo}):
            s.executemany("UPDATE %s SET %s=? WHERE rowid=?" % (t, PUB_COL[a.lang]),
                          [(d["new"], d["rowid"]) for d in todo if d["table"] == t])
    con = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    left = [d for d, s in status(con, a.lang) if s != "done"]
    print("■ 写后回核：未生效 %d 条（期望 0）" % len(left))
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
