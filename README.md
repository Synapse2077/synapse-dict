# Synapse Dict

一个把词典数据产线、SQLite 查询能力和网页检索界面放在一起的工程仓库。

## 目标

- 沉淀最终词典文件：`data/synapse-dict.sqlite`
- 提供本地查询 API：给网页或其他服务调用
- 提供浏览器查询页：方便直接人工检索
- 保留数据加工脚本：继续从原始词典和辅助源更新词库

如果其他项目只需要词库，直接使用 `data/synapse-dict.sqlite` 即可。

## 当前结构

```text
apps/
  api/                        Express 查询接口
  web/                        Vite + React 查询页面
packages/
  dict-core/                  SQLite 查询内核
data/
  synapse-dict.sqlite         最终词典文件
  raw/                        原始输入文件
  intermediate/               中间产物
docs/
  pipeline.md                 数据来源和处理说明
scripts/                      数据加工脚本
```

## 数据目录

- `data/synapse-dict.sqlite`
  最终产物，也是 API 和页面默认读取的数据库
- `data/raw/stardict.7z`
  最初的 Stardict 压缩包
- `data/raw/stardict/stardict.csv`
  原始词典展开后的 CSV
- `data/raw/kaikki.org-dictionary-English.jsonl`
  Wiktionary 辅助源
- `data/intermediate/doubao-translation.jsonl`
  豆包翻译中间结果
- `data/intermediate/manual-translation.jsonl`
  手工补充翻译结果

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
  自定义 SQLite 路径，默认 `data/synapse-dict.sqlite`
- `CORS_ORIGIN`
  允许的前端源，默认 `*`
- `ARK_API_KEY`
  翻译脚本所需
- `DOUBAO_MODEL_BATCH_LITE`
  翻译脚本所需

## 数据脚本

- `scripts/import-wiktionary-newwords.py`
  从 Wiktionary 导入新词
- `scripts/import-wiktionary-phonetics.py`
  从 Wiktionary 补充英美音标
- `scripts/fetch-translation-batch.py`
  批量生成缺失中文翻译
- `scripts/merge-translation.ts`
  将中间翻译结果合并回 SQLite
- `scripts/patch-exchange-translation.py`
  根据 `exchange` 追加词形说明

详细处理流程见 `docs/pipeline.md`。
