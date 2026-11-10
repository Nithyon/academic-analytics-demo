"""SQL validator (layer C, the safety and policy gate).

Sits outside the model. Every candidate statement must pass all five checks:
  1. Parses as a single statement
  2. SELECT only; no writes or DDL
  3. Tables and columns in the allow-list
  4. No stacked queries or comment tricks
  5. Row LIMIT applied (the timeout is applied by the executor)
"""
import re

import sqlglot
from sqlglot import exp

from . import config
from .schema import ALL_COLUMNS, ALLOWED, FACT_LIKE, PERSON_KEYS

CHECK_NAMES = [
    "Parses as a single statement",
    "SELECT only; no writes or DDL",
    "Tables and columns in the allow-list; aggregates only",
    "No stacked queries or comment tricks",
    "Row LIMIT and timeout applied",
]

WRITE_NODES = tuple(n for n in (
    getattr(exp, name, None) for name in
    ("Insert", "Update", "Delete", "Drop", "Create", "Alter", "AlterTable", "Merge",
     "Command", "Pragma", "Attach", "Detach", "TruncateTable", "Transaction")) if n)
SET_OPS = tuple(n for n in (getattr(exp, name, None) for name in ("Union", "Intersect", "Except")) if n)
DANGEROUS = re.compile(r"\b(sqlite_master|sqlite_schema|pragma|attach|load_extension|"
                       r"randomblob|zeroblob)\b", re.I)


class _Fail(Exception):
    def __init__(self, rule, reason):
        self.rule, self.reason = rule, reason


def _check_allow_list(tree):
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    alias_map = {}
    for t in tree.find_all(exp.Table):
        name = t.name
        if name in ctes:
            continue
        if name not in ALLOWED:
            raise _Fail(3, f"Table '{name}' is not in the allow-list.")
        alias_map[t.alias_or_name] = name
        alias_map[name] = name
    used_tables = set(alias_map.values())
    projection_aliases = {a.alias for a in tree.find_all(exp.Alias)}

    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise _Fail(3, "SELECT * is not allowed; columns must be named so the allow-list "
                           "can be checked.")

    used_columns = set()
    for col in tree.find_all(exp.Column):
        name, qual = col.name, col.table
        if isinstance(col.this, exp.Star):
            raise _Fail(3, "table.* is not allowed; name the columns.")
        if qual:
            table = alias_map.get(qual)
            if table is None:
                if qual in ctes:
                    continue
                raise _Fail(3, f"Unknown table alias '{qual}'.")
            if name not in ALLOWED[table]:
                if name in ALL_COLUMNS[table]:
                    raise _Fail(3, f"Column '{table}.{name}' holds personal data and is not in "
                                   "the allow-list.")
                raise _Fail(3, f"Column '{table}.{name}' does not exist.")
            used_columns.add(f"{table}.{name}")
        else:
            owners = [t for t in used_tables if name in ALL_COLUMNS[t]]
            if not owners:
                if name in projection_aliases or ctes:
                    continue
                raise _Fail(3, f"Column '{name}' does not exist in the tables used.")
            if not any(name in ALLOWED[t] for t in owners):
                raise _Fail(3, f"Column '{name}' holds personal data and is not in the "
                               "allow-list.")
            used_columns.add(f"{owners[0]}.{name}")
    return sorted(used_tables), sorted(used_columns)


def _outer_selects(tree):
    if isinstance(tree, exp.Select):
        return [tree]
    if SET_OPS and isinstance(tree, SET_OPS):
        return _outer_selects(tree.left) + _outer_selects(tree.right)
    return []


def _check_privacy(tree):
    """No individual identification: answers are aggregates, never one row per student."""
    for sel in _outer_selects(tree):
        for proj in sel.expressions:
            inner = proj.this if isinstance(proj, exp.Alias) else proj
            if isinstance(inner, exp.Column) and inner.name in PERSON_KEYS:
                raise _Fail(3, "Selecting student_id returns one row per student; only aggregate "
                               "answers are allowed (no individual identification).")
        group = sel.args.get("group")
        if group is not None and any(isinstance(g, exp.Column) and g.name in PERSON_KEYS
                                     for g in group.expressions):
            raise _Fail(3, "Grouping by student returns per-student records; only aggregates over "
                           "groups of students are allowed.")
        where = sel.args.get("where")
        if where is not None:
            for eq in where.find_all(exp.EQ):
                cols = [c for c in (eq.this, eq.expression) if isinstance(c, exp.Column)]
                lits = [c for c in (eq.this, eq.expression) if isinstance(c, exp.Literal)]
                if cols and lits and cols[0].name in PERSON_KEYS:
                    raise _Fail(3, "Filtering on one student is not allowed (individual records).")
        direct = [t.name for t in sel.find_all(exp.Table) if t.find_ancestor(exp.Select) is sel]
        has_agg = any(True for _ in sel.find_all(exp.AggFunc)) or sel.args.get("group") is not None
        if any(t in FACT_LIKE for t in direct) and not has_agg:
            raise _Fail(3, "Row-level records from a fact or summary table are not allowed; ask "
                           "for an aggregate such as an average, a count or a rate.")


def validate(sql: str) -> dict:
    checks = [{"rule": i + 1, "name": n, "status": "pending", "detail": ""}
              for i, n in enumerate(CHECK_NAMES)]
    result = {"passed": False, "checks": checks, "failed_rule": None, "reason": None,
              "final_sql": None, "tables": [], "columns": []}

    def mark(upto, status="pass"):
        for c in checks[:upto]:
            if c["status"] == "pending":
                c["status"] = status

    try:
        if not sql or not sql.strip():
            raise _Fail(1, "The model returned no SQL.")
        text = sql.strip().rstrip(";").strip()

        # 1. single statement
        try:
            statements = [s for s in sqlglot.parse(text, read="sqlite") if s is not None]
        except Exception as exc:  # sqlglot.errors.ParseError and friends
            raise _Fail(1, f"Does not parse as SQL ({str(exc).splitlines()[0][:120]}).")
        if len(statements) != 1:
            # several statements = stacked query; report it under rule 1 and rule 4
            checks[3]["status"] = "fail"
            checks[3]["detail"] = f"{len(statements)} statements found."
            raise _Fail(1, f"{len(statements)} statements found; only one SELECT may run "
                           "(stacked query).")
        tree = statements[0]
        mark(1)

        # 2. SELECT only
        if not isinstance(tree, (exp.Select,) + SET_OPS):
            raise _Fail(2, f"{tree.key.upper()} statement: write and DDL operations are never "
                           "allowed; only SELECT.")
        bad = tree.find(*WRITE_NODES) if WRITE_NODES else None
        if bad is not None:
            raise _Fail(2, f"Contains a {bad.key.upper()} operation.")
        mark(2)

        # 3. allow-list
        tables, columns = _check_allow_list(tree)
        _check_privacy(tree)
        result["tables"], result["columns"] = tables, columns
        mark(3)

        # 4. stacked queries / comment tricks / dangerous functions
        if "--" in text or "/*" in text or "#" in text:
            raise _Fail(4, "SQL comments are not allowed (they can hide part of a query).")
        if ";" in text:
            raise _Fail(4, "Semicolon inside the statement (possible stacked query).")
        if DANGEROUS.search(text):
            raise _Fail(4, "Uses a system table or function that is not allowed.")
        mark(4)

        # 5. LIMIT (timeout enforced at execution)
        limit = tree.args.get("limit")
        note = f"LIMIT {config.ROW_LIMIT} added; {config.QUERY_TIMEOUT_S:g} s timeout at execution."
        if limit is not None:
            try:
                n = int(limit.expression.name if limit.expression else limit.name)
            except Exception:
                n = config.ROW_LIMIT + 1
            if n > config.ROW_LIMIT:
                tree = tree.limit(config.ROW_LIMIT)
                note = f"LIMIT capped at {config.ROW_LIMIT}."
            else:
                note = f"LIMIT {n} kept; {config.QUERY_TIMEOUT_S:g} s timeout at execution."
        else:
            tree = tree.limit(config.ROW_LIMIT)
        checks[4]["detail"] = note
        mark(5)

        result["passed"] = True
        result["final_sql"] = tree.sql(dialect="sqlite", pretty=True)
    except _Fail as f:
        result["failed_rule"], result["reason"] = f.rule, f.reason
        mark(f.rule - 1)
        checks[f.rule - 1]["status"] = "fail"
        checks[f.rule - 1]["detail"] = checks[f.rule - 1]["detail"] or f.reason
        for c in checks:
            if c["status"] == "pending":
                c["status"] = "skipped"
    return result
