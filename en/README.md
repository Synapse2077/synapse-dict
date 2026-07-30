# en/ 目录结构

英语词典管线。产物 `synapse-dict-en.sqlite`（392.9 万行），服务层读它
（`packages/dict-core/src/index.ts` 的 `DEFAULT_DB_PATH`）。

```
en/
├── *.py                    脚本(42 个)。全部用 HERE = Path(__file__).parent 拼路径,
│                           所以**脚本必须留在本层**,移进子目录会让所有数据路径失效。
├── synapse-dict-en.sqlite  当前库
├── ecdict.sqlite           源:ECDICT 原始库
├── kaikki.org-*.jsonl      源:Wiktionary dump(2.7G),锚库靠扫它生成
├── stardict.csv            源:stardict 原始导出
│
├── anchors/    锚库(9 个)   *_kaikki_gloss.json / kaikki_wordset.json / c56_all_senses.json
│                           重建要扫 2.7G dump(约 20 秒),别随手删
├── ledgers/    留痕(28 个)  每次写库的逐行 before/after TSV = **回滚账本**
│                           a1a_fill / b1_ownreal_fill / low_fix / low_keep_promoted …
│                           🔴 这是唯一的精确回滚手段,DB 快照已按轮次清理掉了
├── runs/       跑批产出     判官/验收输出 jsonl、决策记录、pilot、id 清单、人工标注集
│                           verify_* / judge_* / sweep_* / low_pilot_* / eval_set.json
├── logs/       控制台日志   历轮长跑的 stdout
└── backups/    快照(3 个)   pre-enrich-20260726(开工前基线) / 最近两次写库前
```

## 约定

- **脚本路径写法**：`HERE / "ledgers/xxx.tsv"`、`HERE / "runs/xxx.jsonl"`、`HERE / "anchors/xxx.json"`。
  新脚本的输出也要按这个分类落盘，别再往本层丢。
- **命令行传文件时带上子目录**：`python3 en/verify_fixlog.py ledgers/low_fix.tsv --n 300`
  （脚本内部是 `HERE / a.tsv`，相对子路径能正常解析）。
- **`ledgers/` 不要清理**。DB 全量快照只留 3 个，历轮的改动全靠这里的 TSV 才退得回去，
  而且比快照更好用——快照只能整库倒退，会连带撤销后续所有轮次。

## 常用入口

| 目的 | 命令 |
|---|---|
| 按桶抽样测质量 | `python3 en/verify_bucket.py --bucket C6 --n 5000` |
| 对某轮改动做验收 | `python3 en/verify_fixlog.py ledgers/<x>.tsv --n 300 [--judge ds-pro]` |
| 廉价判官摸底 | `python3 en/judge_sample.py --provider deepseek --model deepseek-v4-flash --n 3000 --coded` |
| 判官对人工标注集打分 | `python3 en/eval_labels.py --score runs/judge_xxx.jsonl` |
| low 桶核对式纠错 | `python3 en/rewrite_low_pilot.py --n 20000` → `python3 en/apply_low_fix.py runs/<x>.jsonl --run` |

⚠️ **改写方和判官不能是同一个模型**，否则是自己给自己打分。实测不同判官在同一批数据上
能报出 5.3% / 9.8% / 10.8% / 17% 的 bad 率，两两一致率仅 30%——**任何单一判官的数字都是下界**。
