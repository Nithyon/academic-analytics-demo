"""Central settings for the demo. Change values here or through environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FRONTEND_DIR = ROOT / "frontend"

# Star-schema database (stands in for the MySQL star schema) and the audit log
DB_PATH = DATA_DIR / "academic.db"
AUDIT_PATH = DATA_DIR / "audit.db"

DEFAULT_SEED = int(os.getenv("DEMO_SEED", "7"))

# Safety limits applied by the validator and the read-only executor
ROW_LIMIT = 200
QUERY_TIMEOUT_S = 2.0

# The current academic term ("this term" in a question)
CURRENT_TERM = "2026-ODD"
LAST_TERM = "2025-EVEN"

# Local Qwen model served by Ollama (optional; the demo falls back to the offline model)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen2.5-coder:7b")

# Penalty for a wrong answer in the reliability score (abstaining scores 0)
WRONG_ANSWER_PENALTY = 2
