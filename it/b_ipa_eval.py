#!/usr/bin/env python3
"""
G2P 自证：拿 kaikki 真值 IPA 抽验 b_ipa.word_to_ipa 准确率。达标才敢用规则补变位。

两条输入路径分别评（对应真实补全场景）：
  · plain   ：喂拼写原词（无重音提示）——变位形式最坏情形的下界
  · accent  ：喂带重音标注的 canonical 形（来自 kaikki forms['canonical']）——fill 实际走这条

三档严格度，用来把「辅音/结构正确」与「重音+开闭元音猜测」的贡献拆开：
  strict    ：完全一致（仅归一空格/ɡ/次重音/长音）
  no-stress ：去掉重音符 ˈ 与音节点 . 后一致（看音段序列，含 e/o 开闭）
  segment   ：再把 ɛ→e ɔ→o 归并（纯辅音+元音骨架，剔除开闭与重音变量）

用法：python3 b_ipa_eval.py [--limit N]
"""
import argparse
import json
import re
import unicodedata
from pathlib import Path

from b_ipa import word_to_ipa

HERE = Path(__file__).resolve().parent
JSONL_PATH = HERE / "kaikki.org-dictionary-Italian.jsonl"
ACC = set("àèéìíòóù")


def first_ipa(sounds):
    for s in sounds or []:
        ip = (s.get("ipa") or "").strip()
        if ip.startswith("/"):
            return ip
    return None


def canonical_accented(e):
    """kaikki forms 里带重音的 canonical 形（parlàre）；无则 None。"""
    for fm in e.get("forms") or []:
        if "canonical" in (fm.get("tags") or []):
            f = (fm.get("form") or "").strip()
            if any(c in ACC for c in f):
                return f
    return None


def norm(ip, level):
    if not ip:
        return None
    s = ip.strip().strip("/[]").replace(" ", "")
    s = s.replace("g", "ɡ").replace("ˌ", "").replace("ː", "")  # 次重音/长音
    s = unicodedata.normalize("NFC", s)
    if level == "strict":
        return s
    s = s.replace("ˈ", "").replace(".", "")     # 去主重音+音节点
    if level == "no-stress":
        return s
    return s.replace("ɛ", "e").replace("ɔ", "o")     # 去开闭


def main(limit):
    tot = 0
    hit = {p: {lv: 0 for lv in ("strict", "no-stress", "segment")}
           for p in ("plain", "accent")}
    cnt = {"plain": 0, "accent": 0}
    misses = []
    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "it":
                continue
            truth = first_ipa(e.get("sounds"))
            if not truth:
                continue
            word = (e.get("word") or "").strip()
            if not word:
                continue
            tot += 1
            for path, spelled in (("plain", word), ("accent", canonical_accented(e))):
                if not spelled:
                    continue
                got = word_to_ipa(spelled)
                if got is None:
                    continue
                cnt[path] += 1
                for lv in ("strict", "no-stress", "segment"):
                    if norm(got, lv) == norm(truth, lv):
                        hit[path][lv] += 1
                    elif path == "accent" and lv == "no-stress" and len(misses) < 25:
                        misses.append((spelled, got, truth))
            if limit and tot >= limit:
                break

    print(f"kaikki 真值样本 {tot}\n")
    for path in ("plain", "accent"):
        n = cnt[path]
        if not n:
            continue
        print(f"[{path}] G2P 可转写 {n}（{100*n/tot:.1f}% of 样本）")
        for lv in ("strict", "no-stress", "segment"):
            print(f"    {lv:9} {hit[path][lv]:7} / {n}  = {100*hit[path][lv]/n:.2f}%")
        print()
    print("accent 路径 no-stress 档失配样例（拼写 | G2P | kaikki）：")
    for sp, got, tr in misses[:25]:
        print(f"    {sp:16} {got:20} {tr}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    main(args.limit)
