#!/usr/bin/env python3
"""针对 sweep 出的硬伤名单做定向修复(见对话 2026-07-27)。
复用 enrich_core 的补漏 prompt(保留正确义/补漏/纠错/给变形词独立义),但**放开长度闸**——
硬伤主力是"变形词硬塞原形全义+人名",正确修法就是删繁变短,长度闸反而会挡回。
只碰 fixset 名单,写库前备份,写 overrides 留痕。用法(仓库根):
  python3 en/fix_bad.py
"""
import asyncio, json, re, shutil, sqlite3, time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import enrich_core as ec

HERE = Path(__file__).resolve().parent
DB = str(HERE / "synapse-dict-en.sqlite")
FIXSET = HERE / "sweep_core_fixset.jsonl"
CJK = re.compile(r'[一-鿿]')


def main():
    ids = [json.loads(l)["id"] for l in open(FIXSET)]
    conn = sqlite3.connect(DB)
    qm = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, word, pos, definition, translation FROM stardict WHERE id IN ({qm})", ids).fetchall()
    conn.close()
    print(f"[en] 定向修复硬伤: {len(rows)} 条", flush=True)

    bak = Path(DB).with_suffix(f".pre-fixbad-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy(DB, bak); print(f"已备份 {bak.name}")

    env = ec.load_env()
    metas, results, tok = ec.enrich(rows, env, batch=True)

    conn = sqlite3.connect(DB)
    ov = HERE / "overrides.tsv"
    fixed = same = skip = 0
    ov_lines = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, dfn, old) in enumerate(meta, 1):
            v = res.get(str(k))
            new = v.get("zh") if isinstance(v, dict) else None
            # 放开长度闸:只保留 含中文 / 非空 / 新≠旧 三闸
            if not new or not isinstance(new, str) or not CJK.search(new):
                skip += 1; continue
            if new.strip() == old.strip():
                same += 1; continue
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            ov_lines.append(f"{w}\ttranslation\t{old.replace(chr(10),' / ')}\t{new.replace(chr(10),' / ')}")
            fixed += 1
    conn.commit(); conn.close()
    if ov_lines:
        with open(ov, "a", encoding="utf-8") as f:
            f.write("\n".join(ov_lines) + "\n")
    print(f"\n✅ [en] 修复写库 {fixed} | 未变 {same} | 跳过(空/无中文) {skip} | token {tok}", flush=True)


if __name__ == "__main__":
    main()
