"""Audit log (layer E): every question, SQL attempt, decision and result is recorded.

Kept in its own database so the star schema can stay strictly read-only.
"""
import json
import sqlite3
from datetime import datetime

from . import config

DDL = """CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT, ts TEXT, question TEXT, route TEXT, status TEXT, reason TEXT,
  attempts TEXT, final_sql TEXT, row_count INTEGER, latency_ms REAL, model TEXT,
  validator_on INTEGER, reached_db INTEGER
)"""


def _con():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.AUDIT_PATH)
    con.execute(DDL)
    return con


def log(result):
    con = _con()
    try:
        attempts = [{"attempt": a["attempt"], "sql": a["sql"],
                     "passed": (a.get("validation") or {}).get("passed"),
                     "failed_rule": (a.get("validation") or {}).get("failed_rule")}
                    for a in result.get("attempts", [])]
        cur = con.execute(
            "INSERT INTO audit_log (request_id, ts, question, route, status, reason, attempts, "
            "final_sql, row_count, latency_ms, model, validator_on, reached_db) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (result["request_id"], datetime.now().isoformat(timespec="seconds"),
             result["question"], result["route"]["decision"], result["status"],
             result.get("reason"), json.dumps(attempts), result.get("final_sql"),
             len(result.get("rows") or []), result.get("latency_ms"), result.get("model"),
             int(result.get("validator_on", True)), int(result.get("reached_db", False))))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def recent(limit=50):
    con = _con()
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["attempts"] = json.loads(d["attempts"] or "[]")
            out.append(d)
        return out
    finally:
        con.close()


def clear():
    con = _con()
    try:
        con.execute("DELETE FROM audit_log")
        con.commit()
    finally:
        con.close()
