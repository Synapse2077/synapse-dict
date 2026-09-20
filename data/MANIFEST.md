# data/ 清单（MANIFEST）

> 由 `scripts/gen_manifest.py` 生成。事实自动扫，**来历与用途**在该脚本的 `NOTES` 里手工维护。
> 数据有增减时重跑：`python3 scripts/gen_manifest.py > data/MANIFEST.md`

生成时间：2026-09-20 12:05


## 成品库 `data/db/` —— 11 个文件，15.0 GB

| 文件 | 大小 | 修改日 | 是什么 | 来历 |
|---|---|---|---|---|
| `db/synapse-dict-en.sqlite` | 4.8 GB | 2026-09-18 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-de.sqlite` | 3.2 GB | 2026-09-18 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-fr.sqlite` | 3.0 GB | 2026-09-14 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-it.sqlite` | 1.1 GB | 2026-09-14 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-es.sqlite` | 1.0 GB | 2026-09-14 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-pt.sqlite` | 985.7 MB | 2026-09-14 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-ja.sqlite` | 470.9 MB | 2026-09-20 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/ecdict.sqlite` | 322.4 MB | 2026-05-16 | ECDICT 原始库 | en 的基座（译文/词频/考试标签），第三方数据集 |
| `db/synapse-dict-en.sqlite-shm` | 32 KB | 2026-09-20 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/en.db` | 0 B | 2026-09-07 | — | — |
| `db/synapse-dict-en.sqlite-wal` | 0 B | 2026-09-18 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |

## 原始 dump `data/dumps/` —— 35 个文件，11.5 GB

| 文件 | 大小 | 修改日 | 是什么 | 来历 |
|---|---|---|---|---|
| `dumps/kaikki.org-dictionary-English-20260828.jsonl` | 3.0 GB | 2026-09-06 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-English-20250424.jsonl` | 2.7 GB | 2026-04-24 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-German.jsonl` | 1021.5 MB | 2026-08-31 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-Spanish.jsonl` | 966.4 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-Italian.jsonl` | 725.9 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/frwiktionary.jsonl.gz` | 675.9 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/kaikki.org-dictionary-French.jsonl` | 544.2 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-Portuguese.jsonl` | 529.8 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-Japanese.jsonl` | 315.4 MB | 2026-09-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/dewiktionary.jsonl.gz` | 286.5 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/stardict.csv` | 221.9 MB | 2025-01-02 | ECDICT 原始 CSV | 同上，建库源 |
| `dumps/zhwiktionary.jsonl.gz` | 215.1 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/kaikki.org-jawiktionary-Japanese.jsonl` | 181.3 MB | 2026-09-15 | kaikki **非英文版** per-language 切片 | https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md |
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

## 第三方参考数据 `data/refs/` —— 6 个文件，424 KB

| 文件 | 大小 | 修改日 | 是什么 | 来历 |
|---|---|---|---|---|
| `refs/jlpt-waller/n1.csv` | 194 KB | 2026-09-19 | JLPT N5–N1 词表（民间重建） | https://github.com/stephenmk/yomitan-jlpt-vocab 的 original_data/，原作者 Jonathan Waller，**CC BY**。🔴 JLPT 官方 2010 年后**不再公布词汇表**，此表是 educated guess ⇒ **只当内部尺子（`dict.core_level`），不作读者可见的难度标签**；署名义务见该目录 README |
| `refs/jlpt-waller/n2.csv` | 93 KB | 2026-09-19 | JLPT N5–N1 词表（民间重建） | https://github.com/stephenmk/yomitan-jlpt-vocab 的 original_data/，原作者 Jonathan Waller，**CC BY**。🔴 JLPT 官方 2010 年后**不再公布词汇表**，此表是 educated guess ⇒ **只当内部尺子（`dict.core_level`），不作读者可见的难度标签**；署名义务见该目录 README |
| `refs/jlpt-waller/n3.csv` | 87 KB | 2026-09-19 | JLPT N5–N1 词表（民间重建） | https://github.com/stephenmk/yomitan-jlpt-vocab 的 original_data/，原作者 Jonathan Waller，**CC BY**。🔴 JLPT 官方 2010 年后**不再公布词汇表**，此表是 educated guess ⇒ **只当内部尺子（`dict.core_level`），不作读者可见的难度标签**；署名义务见该目录 README |
| `refs/jlpt-waller/n4.csv` | 24 KB | 2026-09-19 | JLPT N5–N1 词表（民间重建） | https://github.com/stephenmk/yomitan-jlpt-vocab 的 original_data/，原作者 Jonathan Waller，**CC BY**。🔴 JLPT 官方 2010 年后**不再公布词汇表**，此表是 educated guess ⇒ **只当内部尺子（`dict.core_level`），不作读者可见的难度标签**；署名义务见该目录 README |
| `refs/jlpt-waller/n5.csv` | 23 KB | 2026-09-19 | JLPT N5–N1 词表（民间重建） | https://github.com/stephenmk/yomitan-jlpt-vocab 的 original_data/，原作者 Jonathan Waller，**CC BY**。🔴 JLPT 官方 2010 年后**不再公布词汇表**，此表是 educated guess ⇒ **只当内部尺子（`dict.core_level`），不作读者可见的难度标签**；署名义务见该目录 README |
| `refs/jlpt-waller/README.md` | 2 KB | 2026-09-19 | JLPT N5–N1 词表（民间重建） | https://github.com/stephenmk/yomitan-jlpt-vocab 的 original_data/，原作者 Jonathan Waller，**CC BY**。🔴 JLPT 官方 2010 年后**不再公布词汇表**，此表是 educated guess ⇒ **只当内部尺子（`dict.core_level`），不作读者可见的难度标签**；署名义务见该目录 README |

## 写库备份 `data/backups/` —— 26 个文件，21.5 GB

| 文件 | 大小 | 修改日 | 是什么 | 来历 |
|---|---|---|---|---|
| `backups/synapse-dict-en.pre-keep-v3-publish-legacy-no-zh-20260910-121336.bak` | 4.6 GB | 2026-09-10 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-de.pre-keep-v3-9-search-prefix-20260918-121428.bak` | 3.2 GB | 2026-09-18 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-fr.pre-keep-v3-a5-ab-regressions-20260828-152749.bak` | 2.9 GB | 2026-08-28 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-ingest-etymology-fr-edition-20260914-134720.bak` | 1.1 GB | 2026-09-14 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-ingest-etymology-it-edition-20260914-134428.bak` | 1.1 GB | 2026-09-14 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-fix-salitre-formula-20260913-135421.bak` | 1.0 GB | 2026-09-12 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-ingest-etymology-es-20260914-121001.bak` | 1.0 GB | 2026-09-13 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-pt.pre-keep-v3-15a-pt-senses-20260830-223657.bak` | 979.3 MB | 2026-08-30 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-v3-entry-20260820-140712.bak` | 697.0 MB | 2026-08-11 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-ingest-sense-gap-20260810-154410.bak` | 671.3 MB | 2026-08-07 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-en.pre-keep-v3-schema-revert-20260907-105857.bak` | 640.1 MB | 2026-09-07 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-v2-schema-20260807-105628.bak` | 553.0 MB | 2026-08-06 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-ja.pre-ingest-etymology-ja-20260920-091212.bak` | 470.8 MB | 2026-09-20 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-ja.pre-ja-etymology-wrong-edition-20260920-091028.bak` | 470.8 MB | 2026-09-20 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-ingest-es-senses-20260805-221648.bak` | 366.4 MB | 2026-08-04 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-keep-v3-inflection-20260813-140018.bak` | 336.2 MB | 2026-08-13 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-edition-intake-20260803-141856.bak` | 220.3 MB | 2026-08-02 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-keep-v3-entry-20260813-103112.bak` | 202.3 MB | 2026-08-13 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-keep-v3-entry-20260813-102957.bak` | 202.3 MB | 2026-08-12 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-keep-v2-dropcols-20260812-222701.bak` | 201.9 MB | 2026-08-12 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-keep-ipanorm-20260801-160542.bak` | 200.4 MB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-keep-v2-schema-20260812-222550.bak` | 148.2 MB | 2026-08-10 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-de.pre-keep-v3-schema-20260831-210922.bak` | 111.1 MB | 2026-08-10 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-pt.pre-keep-v3-schema-20260829-175040.bak` | 109.2 MB | 2026-08-29 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-en.pre-ipanorm-20260801-193715.bak-shm` | 32 KB | 2026-08-11 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-en.pre-ipanorm-20260801-193715.bak-wal` | 0 B | 2026-08-11 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |

## 过程产物 `data/work/` —— 3742 个文件，2.7 GB

| 语种 | 文件数 | 大小 |
|---|---|---|
| _shared | 7 | 1017 KB |
| de | 56 | 232.3 MB |
| en | 162 | 1.6 GB |
| es | 70 | 315.8 MB |
| fr | 89 | 308.6 MB |
| it | 3320 | 173.6 MB |
| ja | 12 | 12.3 MB |
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
| `zh.jsonl.bak` 类 | 写库前自动备份 | dbtool.session() 或各 fix 脚本生成；**本地绝不能删** |
| `b_enrich_out.jsonl` 类 | 豆包富化输出留档 | b_enrich.py 的原始返回 |
| `gender_decisions.tsv` 类 | 裁决表 | adjudicate/b_adjudicate 的逐条判定 |
| `qa_report.tsv` 类 | 质检报告 | quality_pass.py |

## 合成发音资产 `data/tts/` —— 196141 个文件，2.3 GB

| 语种 | 文件数 | 大小 |
|---|---|---|
| es | 196127 | 1.8 GB |
| voices | 14 | 532.3 MB |

产出方：`es/pipeline/gen_tts.py`（Piper）；`voices/` 是声音模型（es_AR/es_ES/es_MX ＋ it_IT，14 个 `.onnx`）。

🔴 **这是一份珍贵资产，不是过程垃圾，不许当作可清理项。**`es/` 下是 **196,123 个西语词的合成发音**（`.m4a`，按 sha1 分 256 个桶），自带索引 `manifest.tsv`（词 / 音色 / 路径 / 字节 / 时长，196,126 行）；`voices/` 是 Piper 音色模型（es_AR / es_ES / es_MX ＋ it_IT，14 个 `.onnx`）。

⭐ **对照：es 库里的真人录音只有 11,203 条** —— 这批合成音覆盖的词是它的 **17 倍**。真人录音天然稀疏（Commons 有什么才有什么），合成音是方针④「三级兜底」里**补得上大面积空白的那一级**（`[[dict-scope-four-rules]]`）。

⚠️ **目前 `synapse-dict-es.sqlite` 还没有引用它**（`audio` 表整张是 Commons 真人录音）——那是**接线没做**，不是这批文件没用。其余语种没有这一层，是「没跑」或「跑了觉得不够好删掉了」（it 即是后者，`IT_PLAN` 6b），**与 es 这批的去留无关**。


---

**合计 53.0 GB**。全部 gitignore，不进版本库：源数据靠下载、产物靠脚本重生成、备份靠本地保管。
