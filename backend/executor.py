"""Read-only executor (layer D).

Opens the star schema read-only (the SQLite equivalent of a read-only MySQL user), turns on
query_only, and stops any query that runs longer than the timeout. Even if an unsafe
statement got past the validator, the database itself refuses to change.
"""
import sqlite3
import time

from . import config


class ExecutionError(Exception):
    pass


def execute(sql, limit=config.ROW_LIMIT, timeout=config.QUERY_TIMEOUT_S):
    uri = f"file:{config.DB_PATH.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=1)
    try:
        con.execute("PRAGMA query_only = ON")
        deadline = time.perf_counter() + timeout
        con.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 5000)
        start = time.perf_counter()
        try:
            cur = con.execute(sql)
            rows = cur.fetchmany(limit)
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc):
                raise ExecutionError(f"Query stopped after the {timeout:g} s timeout.") from exc
            raise ExecutionError(f"Database refused the query: {exc}") from exc
        except (sqlite3.ProgrammingError, sqlite3.Warning) as exc:
            raise ExecutionError(f"Database refused the query: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            raise ExecutionError(f"Database refused the query: {exc}") from exc
        ms = (time.perf_counter() - start) * 1000
        columns = [d[0] for d in (cur.description or [])]
        return columns, [list(r) for r in rows], ms
    finally:
        con.close()
