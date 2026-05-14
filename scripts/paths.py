from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"

DB_PATH = DATA_DIR / "synapse-dict.sqlite"
KAIKKI_JSONL_PATH = RAW_DIR / "kaikki.org-dictionary-English.jsonl"
DOUBAO_TRANSLATION_PATH = INTERMEDIATE_DIR / "doubao-translation.jsonl"
MANUAL_TRANSLATION_PATH = INTERMEDIATE_DIR / "manual-translation.jsonl"
