# data/ 清单（MANIFEST）

> 由 `scripts/gen_manifest.py` 生成。事实自动扫，**来历与用途**在该脚本的 `NOTES` 里手工维护。
> 数据有增减时重跑：`python3 scripts/gen_manifest.py > data/MANIFEST.md`

生成时间：2026-09-01 10:20


## 成品库 `data/db/` —— 9 个文件，7.1 GB

| 文件 | 大小 | 修改日 | 是什么 | 来历 |
|---|---|---|---|---|
| `db/synapse-dict-fr.sqlite` | 2.9 GB | 2026-08-31 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-it.sqlite` | 1.1 GB | 2026-08-21 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-es.sqlite` | 1009.2 MB | 2026-08-21 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-pt.sqlite` | 979.3 MB | 2026-08-31 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-en.sqlite` | 640.0 MB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/ecdict.sqlite` | 322.4 MB | 2026-05-16 | ECDICT 原始库 | en 的基座（译文/词频/考试标签），第三方数据集 |
| `db/synapse-dict-de.sqlite` | 225.1 MB | 2026-08-31 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-en.sqlite-shm` | 32 KB | 2026-08-31 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-en.sqlite-wal` | 0 B | 2026-08-31 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |

## 原始 dump `data/dumps/` —— 32 个文件，8.0 GB

| 文件 | 大小 | 修改日 | 是什么 | 来历 |
|---|---|---|---|---|
| `dumps/kaikki.org-dictionary-English.jsonl` | 2.7 GB | 2026-04-24 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-German.jsonl` | 1021.5 MB | 2026-08-31 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-Spanish.jsonl` | 966.4 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-Italian.jsonl` | 725.9 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/frwiktionary.jsonl.gz` | 675.9 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/kaikki.org-dictionary-French.jsonl` | 544.2 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-Portuguese.jsonl` | 529.8 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/dewiktionary.jsonl.gz` | 286.5 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/stardict.csv` | 221.9 MB | 2025-01-02 | ECDICT 原始 CSV | 同上，建库源 |
| `dumps/zhwiktionary.jsonl.gz` | 215.1 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/eswiktionary.jsonl.gz` | 95.8 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/kaikki.org-frwiktionary-Italian.jsonl.gz` | 61.7 MB | 2026-08-12 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/itwiktionary.jsonl.gz` | 38.0 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/ptwiktionary.jsonl.gz` | 33.6 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/kaikki.org-zhwiktionary-Italian-trad.jsonl.gz` | 7.6 MB | 2026-08-12 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-trwiktionary-French.jsonl.gz` | 4.7 MB | 2026-08-21 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-nlwiktionary-French.jsonl.gz` | 3.6 MB | 2026-08-21 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-elwiktionary-French.jsonl.gz` | 3.4 MB | 2026-08-21 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-ruwiktionary-French.jsonl.gz` | 3.3 MB | 2026-08-21 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-elwiktionary-Italian.jsonl.gz` | 2.7 MB | 2026-08-12 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-trwiktionary-Italian.jsonl.gz` | 2.4 MB | 2026-08-12 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-jawiktionary-French.jsonl.gz` | 2.1 MB | 2026-08-21 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-ruwiktionary-Portuguese.jsonl.gz` | 1.1 MB | 2026-08-30 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-jawiktionary-Portuguese.jsonl.gz` | 1.0 MB | 2026-08-30 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-plwiktionary-Portuguese.jsonl.gz` | 910 KB | 2026-08-30 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-zhwiktionary-Italian-simp.jsonl.gz` | 233 KB | 2026-08-12 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-elwiktionary-Portuguese.jsonl.gz` | 155 KB | 2026-08-30 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-cswiktionary-Portuguese.jsonl.gz` | 114 KB | 2026-08-30 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-kowiktionary-Portuguese.jsonl.gz` | 93 KB | 2026-08-30 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-trwiktionary-Portuguese.jsonl.gz` | 92 KB | 2026-08-30 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/kaikki.org-nlwiktionary-Portuguese.jsonl.gz` | 88 KB | 2026-08-30 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
| `dumps/README.md` | 3 KB | 2026-08-20 | — | — |

## 写库备份 `data/backups/` —— 24 个文件，13.8 GB

| 文件 | 大小 | 修改日 | 是什么 | 来历 |
|---|---|---|---|---|
| `backups/synapse-dict-fr.pre-hide-fr-ja-cells-20260831-154129.bak` | 2.9 GB | 2026-08-28 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-fr.pre-keep-v3-a5-ab-regressions-20260828-152749.bak` | 2.9 GB | 2026-08-28 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-fix-cross-edition-sense-20260821-135819.bak` | 1.1 GB | 2026-08-21 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-hide-english-relation-notes-20260821-194830.bak` | 1009.2 MB | 2026-08-21 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-pt.pre-keep-v3-15a-pt-senses-20260830-223657.bak` | 979.3 MB | 2026-08-30 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-v3-entry-20260820-140712.bak` | 697.0 MB | 2026-08-11 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-ingest-sense-gap-20260810-154410.bak` | 671.3 MB | 2026-08-07 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-en.pre-ipanorm-20260801-193715.bak` | 637.1 MB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-v2-schema-20260807-105628.bak` | 553.0 MB | 2026-08-06 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-ingest-es-senses-20260805-221648.bak` | 366.4 MB | 2026-08-04 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-keep-v3-inflection-20260813-140018.bak` | 336.2 MB | 2026-08-13 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-edition-intake-20260803-141856.bak` | 220.3 MB | 2026-08-02 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-keep-v3-entry-20260813-103112.bak` | 202.3 MB | 2026-08-13 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-keep-v3-entry-20260813-102957.bak` | 202.3 MB | 2026-08-12 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-keep-v2-dropcols-20260812-222701.bak` | 201.9 MB | 2026-08-12 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-ipanorm-20260801-160542.bak` | 200.4 MB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-keep-v2-schema-20260812-222550.bak` | 148.2 MB | 2026-08-10 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-de.pre-colloc-separator-20260831-211049.bak` | 143.6 MB | 2026-08-31 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-de.pre-keep-v3-entry-20260831-214737.bak` | 143.6 MB | 2026-08-31 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-de.pre-keep-v3-schema-20260831-210922.bak` | 111.1 MB | 2026-08-10 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-pt.pre-keep-v3-schema-20260829-175040.bak` | 109.2 MB | 2026-08-29 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-de.pre-debare-20260727-1421.bak` | 104.2 MB | 2026-07-27 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-en.pre-ipanorm-20260801-193715.bak-shm` | 32 KB | 2026-08-11 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-en.pre-ipanorm-20260801-193715.bak-wal` | 0 B | 2026-08-11 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |

## 过程产物 `data/work/` —— 3649 个文件，1.2 GB

| 语种 | 文件数 | 大小 |
|---|---|---|
| _shared | 7 | 1017 KB |
| de | 12 | 36.8 MB |
| en | 125 | 343.0 MB |
| es | 70 | 315.8 MB |
| fr | 89 | 308.6 MB |
| it | 3320 | 173.6 MB |
| pt | 26 | 43.8 MB |

过程产物按语种分放；具体文件类型的来历见下表。

| 文件类型 | 是什么 | 来历 |
|---|---|---|
| `acceptance_de.jsonl` 类 | 跨语种验收抽样 | scripts/acceptance_sample.py |
| `b_out.jsonl` 类 | 豆包批量输出留档 | b_translate.py 的原始返回，可复用不必重花钱 |
| `conflict_residual.tsv` 类 | 冲突残余 | 同上 |
| `conflict_review.tsv` 类 | kaikki↔豆包冲突逐条 | merge 时留痕，归 conflict-deferred-final-pass 统一裁决 |
| `overrides.tsv` 类 | 覆盖记录 | ⚠️ es 的这份原是 gender 裁决产物，2026-07-26 被**译文**覆盖流程重写，gender 那份已不可恢复 —— provenance 列存在的理由 |
| `quality_study.tsv` 类 | 质量研究抽样结果 | quality_study.py |
| `b_enrich_out.jsonl` 类 | 豆包富化输出留档 | b_enrich.py 的原始返回 |
| `gender_decisions.tsv` 类 | 裁决表 | adjudicate/b_adjudicate 的逐条判定 |
| `qa_report.tsv` 类 | 质检报告 | quality_pass.py |

---

**合计 30.2 GB**。全部 gitignore，不进版本库：源数据靠下载、产物靠脚本重生成、备份靠本地保管。
