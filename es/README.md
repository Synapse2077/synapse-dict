# es/ 目录约定（2026-08-01 分层）

**根目录只放可被 `import` 的模块**，子目录放可执行脚本。
分层前 36 个 .py 全平铺在一起，"当前有效的"和"跑完就是历史的"看不出来。

```
es/
├── paths.py         ⭐ 数据路径唯一真相源（数据全在仓库根 data/，见 data/MANIFEST.md）
├── kaikki_util.py   kaikki dump 的唯一读法（定界符/sounds 变体/X-SAMPA 排除）
├── dbtool.py        写库闸门：备份 → 写 → 不变量核对（未声明的列变了就报错）
├── ipa_norm.py      本语种音标约定的唯一实现（记法/擦音/coda 清音）
├── b_ipa.py         拼写→IPA 规则引擎
├── pipeline/        建库主链与落库脚本 —— **要能重跑**
├── probes/          只读度量与探查 —— 可重跑，不写库
├── fixes/           一次性修复 —— **跑完即历史**，保留作证据，不必保证仍可运行
└── tests/           金标准测试：`cd es && python3 -m unittest tests.test_tools`
```

子目录脚本开头有两行 `_sys.path.insert(...)`，用来 import 上一层的根模块。
从语种目录运行：`cd es && python3 probes/xxx.py`。
