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
 # 2026-08-12（it 阶段 -1）：非英文版也有 per-language 切片，rawdata 页说只有整包是不全的。
 # 命名 `kaikki.org-<ed>wiktionary-<Language>.jsonl.gz`，与英文版切片、与整包都区分得开。
 "wiktionary-": ("kaikki **非英文版** per-language 切片",
   "https://kaikki.org/<xx>wiktionary/<本地语种名>/ —— 已按语种切好，无需按 lang_code 筛；"
   "取数依据见 data/work/it/probe/ 的探测存档，各版本负责哪些字段见 docs/lang/<xx>-CONVENTIONS.md"),
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
 "jlpt-waller": ("JLPT N5–N1 词表（民间重建）",
   "https://github.com/stephenmk/yomitan-jlpt-vocab 的 original_data/，原作者 Jonathan Waller，**CC BY**。"
   "🔴 JLPT 官方 2010 年后**不再公布词汇表**，此表是 educated guess ⇒ "
   "**只当内部尺子（`dict.core_level`），不作读者可见的难度标签**；署名义务见该目录 README"),
 ".bak": ("写库前自动备份", "dbtool.session() 或各 fix 脚本生成；**本地绝不能删**"),
}

def note(name):
    """⚠️ 传进来的是**相对路径**不是文件名：第三方数据的身份在目录名里
    （`refs/jlpt-waller/n1.csv` 的 `n1.csv` 什么也说明不了）。"""
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
# 🔴 2026-09-19 补 `refs`：`data/refs/jlpt-waller/` 落进来时**这张登记表扫不到它** ——
#    和欠账 12 记的是同一个形状（新东西没进任何登记表，而每张表自己都是绿的）。
#    ⚠️ 以后在 data/ 下新建目录，**这一行要跟着加**，否则它就是一份没有户口的数据。
# 🔴🔴 2026-09-20 补 `tts`：它 **2.8 GB、196,141 个文件，而这张表里一个字都没有** ——
#    上面那句「以后新建目录要跟着加」写下来的第二天就被自己违反了，因为 `tts` 是**更早**
#    建的，而我只回头看了"新建的"。⇒ 判据从「记得加」换成「扫一遍 data/ 下的目录，
#    没登记的当场报出来」，见文件末尾的 `未登记` 自检。**名单从磁盘推，不从记忆推。**
# ⚠️ `tts` 与 `work` 一样走**按语种聚合**：19.6 万行逐条列出来会把这张表毁掉，
#    而登记表的用处是「有没有户口」，不是「每个字节叫什么名字」。
SUBS = (("db", "成品库"), ("dumps", "原始 dump"), ("refs", "第三方参考数据"),
        # ⚠️ 标题里不许带「已搁置 / 待清理」这类状态词：登记表写的是**这是什么**，
        #    状态是别处的事，写在这儿等于替人做判断（本段注释下面记了我连错两版的经过）。
        ("backups", "写库备份"), ("work", "过程产物"), ("tts", "合成发音资产"))
for sub, title in SUBS:
    rs = rows(DATA / sub)
    sz = sum(r[1] for r in rs)
    total += sz
    print(f"\n## {title} `data/{sub}/` —— {len(rs)} 个文件，{human(sz)}\n")
    if sub in ("work", "tts"):
        agg = {}
        for rel, s, _ in rs:
            key = rel.parts[1] if len(rel.parts) > 1 else "(根)"
            a = agg.setdefault(key, [0, 0])
            a[0] += 1; a[1] += s
        print("| 语种 | 文件数 | 大小 |")
        print("|---|---|---|")
        for k in sorted(agg):
            print(f"| {k} | {agg[k][0]} | {human(agg[k][1])} |")
        if sub == "tts":
            # 🔴 这段只写**回源核过的事实**，不写我以为的出处。
            #    第一版我把它记成「it 那轮试听判定质量不够而搁置」—— 文件明明在 `tts/es/`。
            print("\n产出方：`es/pipeline/gen_tts.py`（Piper）；`voices/` 是声音模型"
                  "（es_AR/es_ES/es_MX ＋ it_IT，14 个 `.onnx`）。\n")
            print("🔴 **这是一份珍贵资产，不是过程垃圾，不许当作可清理项。**"
                  "`es/` 下是 **196,123 个西语词的合成发音**（`.m4a`，按 sha1 分 256 个桶），"
                  "自带索引 `manifest.tsv`（词 / 音色 / 路径 / 字节 / 时长，196,126 行）；"
                  "`voices/` 是 Piper 音色模型（es_AR / es_ES / es_MX ＋ it_IT，14 个 `.onnx`）。\n")
            print("⭐ **对照：es 库里的真人录音只有 11,203 条** —— 这批合成音覆盖的词是它的 **17 倍**。"
                  "真人录音天然稀疏（Commons 有什么才有什么），合成音是方针④「三级兜底」里"
                  "**补得上大面积空白的那一级**（`[[dict-scope-four-rules]]`）。\n")
            print("⚠️ **目前 `synapse-dict-es.sqlite` 还没有引用它**（`audio` 表整张是 Commons 真人录音）——"
                  "那是**接线没做**，不是这批文件没用。其余语种没有这一层，是「没跑」或「跑了觉得不够好删掉了」"
                  "（it 即是后者，`IT_PLAN` 6b），**与 es 这批的去留无关**。\n")
            # 🔴🔴 本段前两版都写错了，而且错在同一个方向：**把用户（和我自己）做出来的东西说成无主产物**。
            #    v1：「`docs/ES_PLAN.md` 里一个字都没有 ⇒ 既没记成交付物也没记成有意不做」——
            #        那个文件**根本不存在**（es 的账本是 `docs/lang/es-README.md`，比 PLAN 格式更早），
            #        我 grep 它时用 `2>/dev/null` 吞掉报错，**把「我没查到」当成了「源头没有」**
            #        （`[[dont-say-source-lacks-what-we-skipped]]`）。
            #    v2：改成「实验现场，删不删由用户决定」—— 事实对了，**框架还是错的**：
            #        它默认这东西的默认归宿是删除。用户当场纠正：**这批是珍贵资产**，
            #        其他语种没有只是没跑或跑坏了删了。
            #    ⇒ 判据：**登记表描述一份数据「是什么、多大、谁在用」，不替任何人提议删除。**
            continue
        print("\n过程产物按语种分放；具体文件类型的来历见下表。\n")
        print("| 文件类型 | 是什么 | 来历 |")
        print("|---|---|---|")
        seen = set()
        for rel, s, _ in rs:
            w, h = note(str(rel))
            if w == "—" or w in seen:
                continue
            seen.add(w)
            print(f"| `{rel.name}` 类 | {w} | {h} |")
        continue
    print("| 文件 | 大小 | 修改日 | 是什么 | 来历 |")
    print("|---|---|---|---|---|")
    for rel, s, d in sorted(rs, key=lambda x: -x[1]):
        w, h = note(str(rel))
        print(f"| `{rel}` | {human(s)} | {d} | {w} | {h} |")
print(f"\n---\n\n**合计 {human(total)}**。全部 gitignore，不进版本库：源数据靠下载、产物靠脚本重生成、备份靠本地保管。")

# 🔴🔴 **未登记自检 —— 名单从磁盘推，不从记忆推。**
#    `refs` 漏登记时我补了一行注释说「以后要记得加」，**第二天就发现 `tts` 早就漏着**
#    （2.8 GB／19.6 万文件，而它比那句注释还老）。教训写成文字守不住
#    （`[[lesson-must-become-mechanism]]`）⇒ 改成这段：`data/` 下有目录不在 `SUBS` 里，
#    这张表最后就会多出一节红字，任何人一眼看得见。
known = {s for s, _ in SUBS}
strays = sorted(d.name for d in DATA.iterdir()
                if d.is_dir() and not d.name.startswith(".") and d.name not in known)
if strays:
    print("\n## 🔴 未登记的目录\n")
    print("下面这些目录在 `data/` 下**真实存在**，而 `gen_manifest.py` 的 `SUBS` 名单里没有它们")
    print("⇒ 它们的字节数没算进上面的合计，来历也没人写过。**补进 `SUBS` 再重跑。**\n")
    for s in strays:
        n = sum(1 for _ in (DATA / s).rglob("*"))
        b = sum(p.stat().st_size for p in (DATA / s).rglob("*") if p.is_file())
        print(f"- `data/{s}/` —— {n} 个条目，{human(b)}")
