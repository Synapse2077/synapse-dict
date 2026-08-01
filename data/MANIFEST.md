# data/ 清单（MANIFEST）

> 由 `scripts/gen_manifest.py` 生成。事实自动扫，**来历与用途**在该脚本的 `NOTES` 里手工维护。
> 数据有增减时重跑：`python3 scripts/gen_manifest.py > data/MANIFEST.md`

生成时间：2026-08-01 18:21


## 成品库 `data/db/` —— 9 个文件，1.6 GB

| 文件 | 大小 | 修改日 | 是什么 | 来历 |
|---|---|---|---|---|
| `db/synapse-dict-en.sqlite` | 637.1 MB | 2026-07-30 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/ecdict.sqlite` | 322.4 MB | 2026-05-16 | ECDICT 原始库 | en 的基座（译文/词频/考试标签），第三方数据集 |
| `db/synapse-dict-es.sqlite` | 210.4 MB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-it.sqlite` | 137.1 MB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-de.sqlite` | 104.2 MB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-pt.sqlite` | 101.7 MB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-fr.sqlite` | 88.8 MB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-en.sqlite-shm` | 32 KB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `db/synapse-dict-en.sqlite-wal` | 0 B | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |

## 原始 dump `data/dumps/` —— 15 个文件，8.0 GB

| 文件 | 大小 | 修改日 | 是什么 | 来历 |
|---|---|---|---|---|
| `dumps/kaikki.org-dictionary-English.jsonl` | 2.7 GB | 2026-04-24 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-German.jsonl` | 1015.9 MB | 2026-07-19 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-Spanish.jsonl` | 966.4 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-Italian.jsonl` | 725.9 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/frwiktionary.jsonl.gz` | 675.9 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/kaikki.org-dictionary-French.jsonl` | 544.2 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/kaikki.org-dictionary-Portuguese.jsonl` | 529.8 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/dewiktionary.jsonl.gz` | 286.5 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/stardict.csv` | 221.9 MB | 2025-01-02 | ECDICT 原始 CSV | 同上，建库源 |
| `dumps/zhwiktionary.jsonl.gz` | 215.1 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/eswiktionary.jsonl.gz` | 95.8 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/kaikki.org-dictionary-NorwegianBokmål.jsonl` | 74.3 MB | 2026-07-15 | kaikki 英文版 per-language 切片 | https://kaikki.org/dictionary/<Language>/ —— 六个库的**建库基准**；释义为英文 |
| `dumps/itwiktionary.jsonl.gz` | 38.0 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/ptwiktionary.jsonl.gz` | 33.6 MB | 2026-08-01 | kaikki 各语言版**整包** | https://kaikki.org/<xx>wiktionary/ —— ⚠️ 是**多语种**整包（fr 版法语只占 28.4%、zh 版中文占 9.9%），按 lang_code 筛。今后应下 per-language 切片而非整包，见 docs/FRAMEWORK.md §2.4 |
| `dumps/README.md` | 2 KB | 2026-08-01 | — | — |

## 写库备份 `data/backups/` —— 18 个文件，2.8 GB

| 文件 | 大小 | 修改日 | 是什么 | 来历 |
|---|---|---|---|---|
| `backups/synapse-dict-en.pre-usipa-20260730-2258.bak` | 637.1 MB | 2026-07-30 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-ipanorm-20260801-160542.bak` | 200.4 MB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-cqv-20260731-1113.bak` | 188.7 MB | 2026-07-27 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-src-20260801-1308.bak` | 188.7 MB | 2026-08-01 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-es.pre-stress-20260731-2233.bak` | 188.7 MB | 2026-07-31 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-debare-20260727-1421.bak` | 137.1 MB | 2026-07-27 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-reflfix-20260726-2001.bak` | 137.1 MB | 2026-07-26 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-ptrfix-20260726-1539.bak` | 137.1 MB | 2026-07-26 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-it.pre-formnote-20260725-1635.bak` | 136.2 MB | 2026-07-25 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-de.pre-debare-20260727-1421.bak` | 104.2 MB | 2026-07-27 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-de.pre-ptrfix-20260726-1546.bak` | 104.2 MB | 2026-07-26 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-de.pre-fillipa-20260725-1357.bak` | 104.0 MB | 2026-07-25 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-pt.pre-debare-20260727-1421.bak` | 101.7 MB | 2026-07-27 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-pt.pre-ptrfix-20260726-1543.bak` | 101.6 MB | 2026-07-26 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-pt.pre-formnote-20260725-1637.bak` | 101.6 MB | 2026-07-25 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-fr.pre-debare-20260727-1421.bak` | 88.8 MB | 2026-07-27 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-fr.pre-ptrfix-20260726-1542.bak` | 88.8 MB | 2026-07-26 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `backups/synapse-dict-fr.pre-inflfix-20260725-1548.bak` | 88.7 MB | 2026-07-25 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |

## 过程产物 `data/work/` —— 3248 个文件，2.9 GB

| 语种 | 文件数 | 大小 |
|---|---|---|
| _shared | 5 | 1003 KB |
| de | 5 | 36.8 MB |
| en | 135 | 2.8 GB |
| es | 32 | 20.0 MB |
| fr | 6 | 22.8 MB |
| it | 3059 | 46.0 MB |
| pt | 6 | 29.0 MB |

过程产物按语种分放；具体文件类型的来历见下表。

| 文件类型 | 是什么 | 来历 |
|---|---|---|
| `acceptance_de.jsonl` 类 | 跨语种验收抽样 | scripts/acceptance_sample.py |
| `b_out.jsonl` 类 | 豆包批量输出留档 | b_translate.py 的原始返回，可复用不必重花钱 |
| `conflict_residual.tsv` 类 | 冲突残余 | 同上 |
| `conflict_review.tsv` 类 | kaikki↔豆包冲突逐条 | merge 时留痕，归 conflict-deferred-final-pass 统一裁决 |
| `overrides.tsv` 类 | 覆盖记录 | ⚠️ es 的这份原是 gender 裁决产物，2026-07-26 被**译文**覆盖流程重写，gender 那份已不可恢复 —— provenance 列存在的理由 |
| `quality_study.tsv` 类 | 质量研究抽样结果 | quality_study.py |
| `newline_migration.bak.jsonl` 类 | 写库前自动备份 | dbtool.session() 或各 fix 脚本生成；**本地绝不能删** |
| `synapse-dict-en.pre-enrich-20260726-2233.bak` 类 | 六语种成品库 | 各语种 build.py 从 dumps/kaikki.org-dictionary-* 建，后经 enrich/翻译/修复多轮 |
| `b_enrich_out.jsonl` 类 | 豆包富化输出留档 | b_enrich.py 的原始返回 |
| `gender_decisions.tsv` 类 | 裁决表 | adjudicate/b_adjudicate 的逐条判定 |
| `qa_report.tsv` 类 | 质检报告 | quality_pass.py |

---

**合计 15.3 GB**。全部 gitignore，不进版本库：源数据靠下载、产物靠脚本重生成、备份靠本地保管。
