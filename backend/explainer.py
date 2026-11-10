"""Explanation generator (layer B): plain-language answer, the tables and columns used,
how the number was computed, and a grounding check that every number in the answer
really appears in the query result.
"""
import re

import sqlglot
from sqlglot import exp

LABELS = {
    "avg_attendance_pct": "average attendance (%)",
    "avg_score_pct": "average score (%)",
    "pass_rate_pct": "pass rate (%)",
    "students_below": "number of students below the threshold",
    "students": "number of students",
    "assessments": "assessments",
    "course_code": "course", "section_name": "section", "term_name": "term",
    "assessment_type": "assessment type", "program": "program",
    "attendance_band": "attendance band", "student_id": "student",
    "section_code": "section", "dept_code": "department", "program_name": "program",
    "day_name": "day", "attendance_rate": "attendance rate (%)", "avg_internal_marks": "average internal marks",
    "avg_total_marks": "average total marks", "component_name": "component", "grade": "grade",
}
PLURAL = {"course": "courses", "section": "sections", "term": "terms", "day": "days",
          "department": "departments", "component": "components", "grade": "grades",
          "assessment type": "assessment types", "program": "programs",
          "attendance band": "attendance bands", "student": "students"}


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def _label(col):
    return LABELS.get(col, col.replace("_", " "))


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def summarise(columns, rows):
    if not rows:
        return "No rows matched this question."
    if len(columns) == 1 and len(rows) == 1:
        return f"The {_label(columns[0])} is {_fmt(rows[0][0])}."
    first_is_label = not _is_num(rows[0][0])
    num_idx = [i for i, v in enumerate(rows[0]) if _is_num(v)]
    if not first_is_label:
        if len(rows) > 1:
            return f"{len(rows)} rows returned."
        parts = [f"the {_label(columns[i])} is {_fmt(rows[0][i])}" for i in num_idx]
        text = "; ".join(parts) + "."
        return text[0].upper() + text[1:]
    metric = num_idx[0] if columns[num_idx[0]].startswith(("avg", "pass")) or len(num_idx) == 1 \
        else num_idx[-1]
    for i in num_idx:
        if columns[i].startswith(("avg", "pass", "students_below")):
            metric = i
            break
    group = _label(columns[0])
    if len(rows) == 1:
        return f"For {group} {rows[0][0]}, the {_label(columns[metric])} is {_fmt(rows[0][metric])}."
    hi = max(rows, key=lambda r: r[metric])
    lo = min(rows, key=lambda r: r[metric])
    return (f"Across {len(rows)} {PLURAL.get(group, group + 's')}, the {_label(columns[metric])} "
            f"is highest for {hi[0]} ({_fmt(hi[metric])}) and lowest for {lo[0]} "
            f"({_fmt(lo[metric])}).")


def how_computed(sql):
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return ""
    aggs = []
    for a in tree.find_all(exp.AggFunc):
        arg = a.this
        target = arg.sql(dialect="sqlite") if arg is not None else "*"
        aggs.append(f"{a.key.upper()}({target})")
    tables = [t.name for t in tree.find_all(exp.Table)]
    parts = []
    if aggs:
        parts.append(", ".join(dict.fromkeys(aggs)))
    if tables:
        parts.append("over " + " joined with ".join(dict.fromkeys(tables)))
    where = tree.args.get("where")
    if where is not None:
        parts.append("where " + where.this.sql(dialect="sqlite"))
    group = tree.args.get("group")
    if group is not None:
        parts.append("grouped by " + ", ".join(g.sql(dialect="sqlite") for g in group.expressions))
    return "; ".join(p for p in parts if p) + "."


def grounding_check(summary, columns, rows):
    allowed = {str(len(rows))}
    for r in rows:
        for v in r:
            allowed.add(_fmt(v))
            allowed.update(re.findall(r"\d+(?:\.\d+)?", str(v)))
    found = re.findall(r"\d+(?:\.\d+)?", summary)
    missing = [n for n in found if n not in allowed]
    return {"passed": not missing, "numbers_checked": len(found), "missing": missing}


def definitions_used(sql, card_ids):
    """Metric definitions from the ontology that this query actually relies on."""
    from .ontology import METRICS
    low = sql.lower()
    out = []
    for m in METRICS:
        if m["id"] not in (card_ids or []):
            continue
        if any(t in low for t in m["tables"]):
            out.append(f"{m['label']}: {m['definition']}")
    return out


def explain(sql, columns, rows, tables, cols_used, card_ids=None):
    summary = summarise(columns, rows)
    return {
        "summary": summary,
        "computed": how_computed(sql),
        "definitions": definitions_used(sql, card_ids),
        "tables_used": tables,
        "columns_used": cols_used,
        "grounding": grounding_check(summary, columns, rows),
    }
