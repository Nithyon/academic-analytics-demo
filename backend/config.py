"""Central settings for the demo. Change values here or through environment variables."""
import os
from pathlib import Path

from . import rules

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FRONTEND_DIR = ROOT / "frontend"
RESULTS_DIR = ROOT / "results"

# Star-schema database (SQLite standing in for the MySQL star schema) and the audit log
DB_PATH = Path(os.getenv("DEMO_DB", str(DATA_DIR / "academic.db")))
AUDIT_PATH = DATA_DIR / "audit.db"

DEFAULT_SEED = int(os.getenv("DEMO_SEED", "7"))
FIXTURE_SEEDS = [7, 11, 23]          # databases used to check every answer

# Safety limits applied by the validator and the read-only executor
ROW_LIMIT = 200
QUERY_TIMEOUT_S = 5.0

# The current academic term ("this term" in a question)
CURRENT_TERM = rules.CURRENT_TERM
LAST_TERM = rules.LAST_TERM

# Local models served by Ollama (optional; the demo falls back to the offline model)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen2.5-coder:7b")
OLLAMA_TIMEOUTS = {"default": 180, "gemma4:26b-a4b-it-qat": 600}

# Penalty for a wrong answer in the reliability score (abstaining scores 0)
WRONG_ANSWER_PENALTY = 2
PENALTIES = [1, 2, 5, 10]


def fixture_path(seed):
    return DATA_DIR / ("academic.db" if seed == DEFAULT_SEED else f"academic_seed{seed}.db")
