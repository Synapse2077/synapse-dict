#!/usr/bin/env python3
"""七月流水线的**防重跑闸**。2026-08-12（阶段 -2）立。

═══ 为什么有这个文件 ═══
`it/` 下有 11 个脚本自己 `sqlite3.connect(DB)` 直接写库 —— 它们是七月建库/补音标/
翻译那一轮的产物，**已经跑完了，当前这个 155 MB 的库就是它们的输出**。
它们不走 `dbtool.session`，没有备份、没有不变量核对。

危险的不是它们存在，是**重跑**。es 上这一类事故一天撞见三次
（`split_case_homographs` 的 4,501 条归属被重建抹掉、`example_gloss` 的 50,289 条
译文被删光、整轮音标修复被新表绕过），全是"重放式脚本静默撤销已完成的修复"，
而且**每次都是隔了一周才偶然发现**。`UNIQUE` 只保证不重复，不保证不倒退。

⇒ 这些脚本从现在起冻结：直接跑会被拦下。确实要跑就显式声明：
      IT_ALLOW_LEGACY=1 python3 pipeline/build.py ...
   声明的意思是"我知道它会覆盖之后所有的修复，且我已经备份"。

被 import 时不拦（`fix_flagged` 会 import `fix_misalign` 复用批处理逻辑）——
只拦"作为主程序直接执行"。

新写的脚本一律走 `dbtool.session`，不进这张名单。
"""
import os
import sys
from pathlib import Path

ENV = "IT_ALLOW_LEGACY"


def frozen(name, file, why="七月流水线，已跑完"):
    """在 `import paths` 之后调用：`legacy_guard.frozen(__name__, __file__)`。"""
    if name != "__main__":
        return                       # 被别的脚本 import：放行
    if os.environ.get(ENV) == "1":
        print("⚠️ %s 是冻结脚本（%s），因 %s=1 放行 —— 重跑会覆盖其后的所有修复。"
              % (Path(file).name, why, ENV), file=sys.stderr)
        return
    print(
        "🔴 %s 已冻结：%s。\n"
        "   它不走 dbtool 闸门（无备份、无不变量核对），重跑会**静默撤销**之后做的修复。\n"
        "   确实要跑：  %s=1 python3 %s ...\n"
        "   新的写库请走 dbtool.session()。"
        % (Path(file).name, why, ENV, Path(file).name), file=sys.stderr)
    raise SystemExit(2)
