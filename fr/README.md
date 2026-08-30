# fr/ 目录约定（2026-08-01 分层）

**根目录只放可被 `import` 的模块**，子目录放可执行脚本。
分层前 12 个 .py 全平铺在一起，"当前有效的"和"跑完就是历史的"看不出来。

```
fr/
├── paths.py         ⭐ 数据路径唯一真相源（数据全在仓库根 data/，见 data/MANIFEST.md）
├── kaikki_util.py   kaikki dump 的唯一读法（定界符/sounds 变体/X-SAMPA 排除）
├── dbtool.py        写库闸门：备份 → 写 → 不变量核对（未声明的列变了就报错）
├── pipeline/        建库主链与落库脚本 —— **要能重跑**
├── probes/          只读度量与探查 —— 可重跑，不写库
├── fixes/           一次性修复 —— **跑完即历史**，保留作证据，不必保证仍可运行
└── tests/           三道闸（`cd fr` 后运行）
                     · test_tools.py         金标准测试 `python3 -m unittest tests.test_tools`
                     · test_no_regression.py 回归闸 28 条：过去每个修复现在还在不在
                     · test_plan_ledger.py   账的闸：计划表/收尾单说的话，库里对不对得上
                     后两道**已挂进 `dbtool.session`**，每次写库自动跑
```

子目录脚本开头有两行 `_sys.path.insert(...)`，用来 import 上一层的根模块。
从语种目录运行：`cd fr && python3 probes/xxx.py`。

## ✅ fr 已完结（2026-08-28）

阶段 -2 → 9 全部完成，收尾见 `docs/FR_PLAN.md` 末尾「fr 完结」一节
（成品清单 / 三道闸 / 成本 / 收尾单 C1–C27）。

⚠️ `fixes/` 里的脚本**跑完即历史**，不保证今天还能跑；它们保留的是**判据与理由**
（每个文件头写着判据收窄了几版、负控是什么、为什么这么修）。要复用请读文件头，别直接跑。

⚠️ `data/work/fr/` 的 310 MB **不要删** —— 那是模型问答的台账
（`examples/example_zh.jsonl` 74 万条例句译文、`senses/wrong_judge.jsonl` 5.45 万条判定…）。
删掉它，任何一次重跑都要把已经花过的钱再花一遍。
