#!/usr/bin/env python3
"""从中文版维基词典抽取西班牙语词条 —— **译文独立核验的第一步**。2026-08-01。

═══ 为什么做这件事 ═══
库里 767,293 行的 `translation` 全部出自豆包，是整个词典**最贵的一层**，
而它至今**只被模型判官间接评过**（同批数据不同判官报 5.3%–17%，判官自噪 45%）。
中文版维基词典是**唯一一个独立于我们流水线的人工中文释义源** —— 第一次有真值可比。

⚠️ 本脚本**只读、不写库、不调模型**。产出的是一份"我们哪里可能不一致"的清单，
   **分歧 ≠ 我们错**：双方可能各自覆盖了不同义项，也可能中文版更粗。裁决是后面的事。

═══ 数据形态（实测，别想当然）═══
中文版是**多语种**词典（2,598 种语言，西语只占一小撮），按 lang_code=='es' 筛。
西语词条的中文释义有三种写法，混在一起：
  · 干净的：   hígado → ["肝脏、肝"]
  · 繁体的：   coche  → ["汽車"]           ← **必须转简，不然全判成分歧**
  · 带词性前缀：comer  → ["vi. 吃饭", "vt. 吃，消耗，使褪色", "vr. 略去"]
顺带白捡的：`sounds`(IPA + Commons 录音 mp3_url)、`etymology_texts`(词源)。

用法（在 es/ 目录）：
    python3 probes/zh_edition_extract.py            # 抽取 → work/zh_es.jsonl
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import gzip
import json
import time

import paths

SRC = paths.DUMPS / "zhwiktionary.jsonl.gz"
OUT = paths.WORK / "zh_es.jsonl"


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    total = kept = 0
    n_gloss = n_ipa = n_audio = n_etym = 0
    with gzip.open(SRC, "rt", encoding="utf-8") as fh, \
         open(OUT, "w", encoding="utf-8") as out:
        for ln in fh:
            total += 1
            e = json.loads(ln)
            if e.get("lang_code") != "es":
                continue
            kept += 1
            senses = []
            for s in e.get("senses") or []:
                g = [x for x in (s.get("glosses") or []) if x and x.strip()]
                if not g:
                    continue
                senses.append({"g": g, "tags": s.get("tags") or [],
                               "topics": s.get("topics") or []})
            ipa = [s["ipa"] for s in (e.get("sounds") or []) if s.get("ipa")]
            audio = [s["mp3_url"] for s in (e.get("sounds") or []) if s.get("mp3_url")]
            etym = e.get("etymology_texts") or []
            if senses:
                n_gloss += 1
            n_ipa += bool(ipa)
            n_audio += bool(audio)
            n_etym += bool(etym)
            out.write(json.dumps({
                "word": e["word"], "pos": e.get("pos"), "pos_title": e.get("pos_title"),
                "senses": senses, "ipa": ipa, "audio": audio, "etym": etym,
                "forms": [{"f": f.get("form"), "t": f.get("tags") or []}
                          for f in (e.get("forms") or []) if f.get("form")],
                "tags": e.get("tags") or [],
            }, ensure_ascii=False) + "\n")
    print(f"■ 扫 {total:,} 行，西语词条 {kept:,}（{time.time()-t0:.0f}s）")
    print(f"    带中文释义 {n_gloss:,} | 带 IPA {n_ipa:,} | 带录音 {n_audio:,} | 带词源 {n_etym:,}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
