"""es 双性折叠修复（纯 DB、零 kaikki 扫描、全确定性）。

es 的 meta 逐义项 g 早已正确（bestia 的 brute 义项标 g=mf、ala 的 winger 标 mf），
坏的只有**词级 gender 列**被 enrich.py:197 的 first-wins 锁成首个 etym 的单性别。
修法 = 从已正确的 meta 重算词级性别（含 mf 判定），把「meta 显示双性但 gender 列单性」的改成 mf。
不碰付费翻译、不改 meta，只订正 gender 一列。

判据（同 enrich.gender_from_meta）：某义项 g=='mf'，或义项里同时有 m 和 f → 词级 mf。
天然排除大小写合并假阳性（AVE 缩写 vs ave 鸟——ave 的 meta 没有 mf 义项，不会被误改）。

用法：python3 fix_dualgender.py            # 修复（先备份）
      python3 fix_dualgender.py --dry-run  # 只算不写 + 抽样
"""
import argparse
import json
import shutil
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-es.sqlite"


def meta_is_mf(meta_json):
    """只按普通名词义项(pos=='n')聚合性别；排除 pos=='name' 姓氏义项——
    姓氏天然"m or f by sense"(人有男女)，但普通名词 acero(钢) 恒 m，不能被姓氏 Acero 带成 mf。"""
    try:
        arr = json.loads(meta_json) if meta_json else []
    except Exception:
        return False
    gs = {m.get("g") for m in arr
          if isinstance(m, dict) and m.get("pos") == "n" and m.get("g")}
    return "mf" in gs or ("m" in gs and "f" in gs)


def main(dry_run=False):
    if not DB.exists():
        raise SystemExit(f"缺库: {DB}")
    conn = sqlite3.connect(str(DB))
    victims = []   # (word, cur_gender)
    for word, gender, meta in conn.execute(
            "SELECT word, gender, meta FROM dict WHERE is_lemma=1 AND meta IS NOT NULL"):
        if gender in ("m", "f") and meta_is_mf(meta):
            victims.append((word, gender))

    print(f"meta 显示双性但 gender 列锁成单性（折叠 bug 受害者）：{len(victims)} 词")
    for w, g in sorted(victims)[:25]:
        print(f"  {w}: {g} → mf")

    if dry_run:
        print("[dry-run] 未写库")
        conn.close()
        return

    bak = DB.with_suffix(f".sqlite.pre-esdual-{time.strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(DB, bak)
    print(f"备份 → {bak.name}")

    n = 0
    for word, _g in victims:
        cur = conn.execute(
            "UPDATE dict SET gender='mf' WHERE word=? COLLATE NOCASE AND is_lemma=1 AND gender IN ('m','f')",
            (word,),
        )
        n += cur.rowcount
    conn.commit()
    conn.close()
    print(f"回填 {n} 行 gender=mf")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    main(dry_run=args.dry_run)
