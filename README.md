# Synapse Dict

一个把词典数据产线、SQLite 查询能力和网页检索界面放在一起的工程仓库。

## 目标

- 沉淀最终词典文件：`en/synapse-dict-en.sqlite`
- 提供本地查询 API：给网页或其他服务调用
- 提供浏览器查询页：方便直接人工检索
- 保留数据加工脚本：继续从原始词典和辅助源更新词库

如果其他项目只需要词库，直接使用 `en/synapse-dict-en.sqlite` 即可。

## 当前结构

```text
apps/
  api/                        Express 查询接口
  web/                        Vite + React 查询页面
packages/
  dict-core/                  SQLite 查询内核
en/                           英语词典（与 es/ it/ fr/ pt/ de/ 同构）
  synapse-dict-en.sqlite      最终词典文件
  ecdict.sqlite               ECDICT 原始源
  stardict.csv                Stardict 展开源
  kaikki.org-dictionary-English.jsonl  Wiktionary 辅助源
  *.py / merge-translation.ts 英语数据加工脚本
es/ it/ fr/ pt/ de/ no/       其他语种词典（各自独立管线）
docs/
  pipeline.md                 数据来源和处理说明
scripts/                      跨语言加工脚本（acceptance/fix_* 等）
```

## 数据目录（英语 `en/`，与其他语种目录同构）

- `en/synapse-dict-en.sqlite`
  最终产物，也是 API 和页面默认读取的数据库
- `en/stardict.csv`
  原始 Stardict/ECDICT 词典展开后的 CSV
- `en/ecdict.sqlite`
  ECDICT 原始 SQLite 源
- `en/kaikki.org-dictionary-English.jsonl`
  Wiktionary 辅助源
- `en/doubao-translation.jsonl`
  豆包翻译中间结果
- `en/manual-translation.jsonl`
  手工补充翻译结果

> 以上大文件均不进 git（见 `.gitignore`：`*.sqlite* / *.jsonl / *.csv`）。

## 本地开发

1. 安装 Node 依赖

```bash
npm install
```

2. 安装 Python 依赖

```bash
python3 -m pip install -r requirements.txt
```

3. 启动 API 和页面

```bash
npm run dev
```

4. 打开页面

- Web: `http://localhost:5180`
- API: `http://localhost:4000`

## API

- `GET /api/health`
- `GET /api/stats`
- `GET /api/search?q=apple&limit=20`
- `GET /api/entries/apple`

## 环境变量

- `PORT`
  API 端口，默认 `4000`
- `DATABASE_PATH`
  自定义 SQLite 路径，默认 `en/synapse-dict-en.sqlite`（原 `data/synapse-dict.sqlite`）
- `CORS_ORIGIN`
  允许的前端源，默认 `*`
- `ARK_API_KEY`
  翻译脚本所需
- `DOUBAO_MODEL_BATCH_LITE`
  翻译脚本所需

## 数据脚本（英语，位于 `en/`）

- `en/import-wiktionary-newwords.py`
  从 Wiktionary 导入新词
- `en/import-wiktionary-phonetics.py`
  从 Wiktionary 补充英美音标
- `en/fetch-translation-batch.py`
  批量生成缺失中文翻译
- `en/merge-translation.ts`
  将中间翻译结果合并回 SQLite
- `en/patch-exchange-translation.py`
  根据 `exchange` 追加词形说明
- `en/paths.py`
  英语管线路径中枢（所有英语脚本 `from paths import`）

跨语言脚本在 `scripts/`（`acceptance_sample.py` 验收抽样、`fix_pointer_gloss.py` / `fix_inflected_gloss.py` / `fix_reflexive_it.py` 缺陷修复、`bucket_conflicts.py` 冲突分档）。

详细处理流程见 `docs/pipeline.md`。
