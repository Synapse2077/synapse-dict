from pathlib import Path

# en/paths.py：英语管线路径中枢。所有英语脚本 `from paths import ...`。
# 2026-07-26 整理：英语从 data/ 归拢到 en/，与其他语种目录(es/ it/ …)结构一致。
ROOT = Path(__file__).resolve().parent.parent  # 仓库根（en/ 在根下一层）
EN_DIR = ROOT / "en"

# 兼容旧变量名（原先指向 data/ 与 data/raw、data/intermediate，现全归 en/）
DATA_DIR = EN_DIR
RAW_DIR = EN_DIR
INTERMEDIATE_DIR = EN_DIR

DB_PATH = EN_DIR / "synapse-dict-en.sqlite"
KAIKKI_JSONL_PATH = EN_DIR / "kaikki.org-dictionary-English.jsonl"
ECDICT_PATH = EN_DIR / "ecdict.sqlite"
STARDICT_CSV_PATH = EN_DIR / "stardict.csv"
DOUBAO_TRANSLATION_PATH = EN_DIR / "doubao-translation.jsonl"
MANUAL_TRANSLATION_PATH = EN_DIR / "manual-translation.jsonl"
