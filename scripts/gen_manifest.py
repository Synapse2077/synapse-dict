#!/usr/bin/env python3
"""生成 `data/MANIFEST.md` —— 每份数据的**户口**。2026-08-01。

═══ 为什么 ═══
2026-08-01 之前，14 GB 数据散在各语种目录里，**哪来的、哪天下的、多少条、谁在用，全靠人记**。
后果实例：`overrides.tsv` 被后来的流程覆盖过，我查了半天才发现它装的已经不是 gender 裁决；
下载的 5 个语言版整包连个说明都没有，导致「西语版 = 西语词典」这个误解持续了很久。
→ 事实（大小/时间/行数）由本脚本自动扫，**来历与用途**由下方 NOTES 手工维护。
   数据有增减时重跑一次。

用法：python3 scripts/gen_manifest.py > data/MANIFEST.md
"""
import gzip, os, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# 来历与用途 —— 手工维护。键是文件名或前缀。
NOTES = {
 "synapse-dict-": ("六语种成品库", "各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮"),
 "ecdict.sqlite": ("ECDICT 原始库", "en 的基座（译文/词频/考试标签），第三方数据集"),
 "stardict.csv": ("ECDICT 原始 CSV", "同上，建库源"),
 "kaikki.org-dictionary-": ("kaikki 英文版 per-language 切片",
   "https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文"),
 "wiktionary.jsonl.gz": ("kaikki 各语言版**整包**",
   "https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），"
   "按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4"),
 "b_out": ("豆包批量输出留档", "b_translate.py 的原始返回，可复用不必重花钱"),
 "b_enrich_out": ("豆包富化输出留档", "b_enrich.py 的原始返回"),
 "conflict_review": ("kaikki↔豆包冲突逐条", "merge 时留痕，归 conflict-deferred-final-pass 统一裁决"),
 "conflict_residual": ("冲突残余", "同上"),
 "overrides.tsv": ("覆盖记录", "⚠️ es 的这份原是 gender 裁决产物，2026-07-26 被**译文**覆盖流程重写，"
                              "gender 那份已不可恢复 —— provenance 列存在的理由"),
 "decisions.tsv": ("裁决表", "adjudicate/b_adjudicate 的逐条判定"),
 "gender_decisions": ("gender 裁决表", "turbo 那轮；后续 pro 重裁未单独留档"),
 "quality_study": ("质量研究抽样结果", "quality_study.py"),
 "qa_report": ("质检报告", "quality_pass.py"),
 "acceptance_": ("跨语种验收抽样", "scripts/acceptance_sample.py"),
 ".bak": ("写库前自动备份", "dbtool.session() 或各 fix 脚本生成；**本地绝不能删**"),
}

def note(name):
    for k, v in NOTES.items():
        if k in name:
            return v
    return ("—", "—")

def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u in ("B", "KB") else f"{n:.1f} {u}"
        n /= 1024

def rows(d):
    out = []
    if not d.exists():
        return out
    for p in sorted(d.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            st = p.stat()
            out.append((p.relative_to(DATA), st.st_size,
                        time.strftime("%Y-%m-%d", time.localtime(st.st_mtime))))
    return out

print("# data/ 清单（MANIFEST）\n")
print("> 由 `scripts/gen_manifest.py` 生成。事实自动扫，**来历与用途**在该脚本的 `NOTES` 里手工维护。")
print("> 数据有增减时重跑：`python3 scripts/gen_manifest.py > data/MANIFEST.md`\n")
print(f"生成时间：{time.strftime('%Y-%m-%d %H:%M')}\n")
total = 0
for sub, title in (("db", "成品库"), ("dumps", "原始 dump"),
                   ("backups", "写库备份"), ("work", "过程产物")):
    rs = rows(DATA / sub)
    sz = sum(r[1] for r in rs)
    total += sz
    print(f"\n## {title} `data/{sub}/` —— {len(rs)} 个文件，{human(sz)}\n")
    if sub == "work":
        agg = {}
        for rel, s, _ in rs:
            key = rel.parts[1] if len(rel.parts) > 1 else "(根)"
            a = agg.setdefault(key, [0, 0])
            a[0] += 1; a[1] += s
        print("| 语种 | 文件数 | 大小 |")
        print("|---|---|---|")
        for k in sorted(agg):
            print(f"| {k} | {agg[k][0]} | {human(agg[k][1])} |")
        print("\n过程产物按语种分放；具体文件类型的来历见下表。\n")
        print("| 文件类型 | 是什么 | 来历 |")
        print("|---|---|---|")
        seen = set()
        for rel, s, _ in rs:
            w, h = note(rel.name)
            if w == "—" or w in seen:
                continue
            seen.add(w)
            print(f"| `{rel.name}` 类 | {w} | {h} |")
        continue
    print("| 文件 | 大小 | 修改日 | 是什么 | 来历 |")
    print("|---|---|---|---|---|")
    for rel, s, d in sorted(rs, key=lambda x: -x[1]):
        w, h = note(rel.name)
        print(f"| `{rel}` | {human(s)} | {d} | {w} | {h} |")
print(f"\n---\n\n**合计 {human(total)}**。全部 gitignore，不进版本库：源数据靠下载、产物靠脚本重生成、备份靠本地保管。")
