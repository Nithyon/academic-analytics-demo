"""SQL generation by the language model (layer B).

Two back-ends:
  * "ollama"  - the real local Qwen2.5-Coder model served by Ollama (or llama.cpp's
                Ollama-compatible server). Prompted with the schema and worked examples.
  * "offline" - a small deterministic stand-in so the demo runs on any laptop with no
                model installed. It maps common question patterns to SQL the way a
                text-to-SQL model would, including the unsafe SQL a naive or poisoned
                model can produce. It is NOT a language model; it exists so the safety
                layers can be demonstrated reliably.

Either way the model only *proposes* SQL. Nothing it returns is trusted: the validator
and the read-only executor decide what runs.
"""
import json
import re
import urllib.request

from . import config
from .schema import schema_prompt

FEW_SHOT = [
    ("Average attendance per course this term?",
     "SELECT c.course_code, ROUND(AVG(a.attendance_pct), 1) AS avg_attendance_pct\n"
     "FROM fact_attendance a\nJOIN dim_course c ON a.course_id = c.course_id\n"
     "JOIN dim_term t ON a.term_id = t.term_id\nWHERE t.term_name = '2026-ODD'\n"
     "GROUP BY c.course_code\nORDER BY c.course_code"),
    ("Average score per assessment type in CS2102 this term",
     "SELECT f.assessment_type, ROUND(AVG(f.score_pct), 1) AS avg_score_pct\n"
     "FROM fact_assessment f\nJOIN dim_course c ON f.course_id = c.course_id\n"
     "JOIN dim_term t ON f.term_id = t.term_id\n"
     "WHERE c.course_code = 'CS2102' AND t.term_name = '2026-ODD'\n"
     "GROUP BY f.assessment_type\nORDER BY avg_score_pct DESC"),
]

POISON_PAYLOAD = "; DROP TABLE fact_attendance"


# --------------------------------------------------------------------------- helpers
def _course(q):
    m = re.search(r"\b([A-Za-z]{2})\s?(\d{4})\b", q)
    return f"{m.group(1).upper()}{m.group(2)}" if m else None


def _term(q):
    ql = q.lower()
    m = re.search(r"\b(20\d\d)[\s-]?(odd|even)\b", ql)
    if m:
        return f"{m.group(1)}-{m.group(2).upper()}"
    if re.search(r"\b(last|previous) (term|semester)\b", ql):
        return config.LAST_TERM
    if re.search(r"\b(this|current) (term|semester)\b", ql):
        return config.CURRENT_TERM
    return None


def _filters(q, fact_alias, default_term=True, across_terms=False):
    """JOIN and WHERE clauses for course / term filters found in the question."""
    joins, where = [], []
    course = _course(q)
    term = None if across_terms else (_term(q) or (config.CURRENT_TERM if default_term else None))
    if course:
        joins.append(f"JOIN dim_course c ON {fact_alias}.course_id = c.course_id")
        where.append(f"c.course_code = '{course}'")
    if term:
        joins.append(f"JOIN dim_term t ON {fact_alias}.term_id = t.term_id")
        where.append(f"t.term_name = '{term}'")
    return joins, where


def _assemble(select, frm, joins, where, group=None, order=None):
    sql = f"SELECT {select}\nFROM {frm}"
    for j in joins:
        sql += f"\n{j}"
    if where:
        sql += "\nWHERE " + " AND ".join(where)
    if group:
        sql += f"\nGROUP BY {group}"
    if order:
        sql += f"\nORDER BY {order}"
    return sql


def _dedupe_join(joins, new):
    return joins if any(new.split(" ON ")[0] == j.split(" ON ")[0] for j in joins) else joins + [new]


# --------------------------------------------------------------------------- offline model
def offline_sql(q):
    """Pattern-based stand-in for the model. Returns SQL text, or None (cannot answer)."""
    ql = q.lower()
    is_att = "attendance" in ql or "attend" in ql
    is_score = bool(re.search(r"\b(marks?|scores?|grades?|performance|results?|pass)\b", ql))

    # ---- what a naive model does with a write request: it writes the SQL anyway
    if re.search(r"'\s*;|;\s*(drop|delete|update|insert)", ql):
        base = offline_sql(re.split(r"'|;", q)[0]) or "SELECT attendance_pct FROM fact_attendance"
        tail = re.search(r";\s*(.*)$", q).group(1).replace("--", "").strip().rstrip(";")
        return f"{base};\n{tail} --"
    if re.search(r"\b(drop|truncate)\b", ql):
        table = "fact_assessment" if is_score else "fact_attendance"
        return f"DROP TABLE {table}"
    if re.search(r"\b(delete|wipe|erase)\b", ql):
        table = "fact_assessment" if (is_score or "assessment" in ql) else "fact_attendance"
        return f"DELETE FROM {table}"
    if re.search(r"\bupdate\b|\bset\b.*\bmarks\b|full marks", ql):
        return "UPDATE fact_assessment SET marks_obtained = max_marks, score_pct = 100"
    if re.search(r"\b(insert|add a student)\b", ql):
        return ("INSERT INTO dim_student (student_id, full_name, program) "
                "VALUES (9999, 'Test Student', 'B.Tech CSE')")

    # ---- personal data: the model happily selects names; the allow-list stops it
    if re.search(r"\b(names?|who are|e-?mails?)\b", ql) and "student" in ql:
        thr = re.search(r"(below|under|less than|<)\s*(\d+)", ql)
        joins, where = _filters(q, "a")
        joins = ["JOIN dim_student s ON a.student_id = s.student_id"] + joins
        group = "s.full_name"
        if thr:
            group += f"\nHAVING AVG(a.attendance_pct) < {thr.group(2)}"
        return _assemble("s.full_name, ROUND(AVG(a.attendance_pct), 1) AS avg_attendance_pct",
                         "fact_attendance a", joins, where, group, "avg_attendance_pct")

    # ---- attendance vs marks
    if re.search(r"relationship|correlat|attendance band|by attendance|attendance and (marks|score)", ql):
        joins, where = _filters(q, "f")
        joins = ["JOIN fact_attendance a ON a.student_id = f.student_id AND a.course_id = "
                 "f.course_id AND a.term_id = f.term_id"] + joins
        band = ("CASE WHEN a.attendance_pct >= 90 THEN '90-100%' WHEN a.attendance_pct >= 75 "
                "THEN '75-89%' ELSE 'below 75%' END")
        return _assemble(f"{band} AS attendance_band, COUNT(*) AS assessments, "
                         "ROUND(AVG(f.score_pct), 1) AS avg_score_pct",
                         "fact_assessment f", joins, where + ["f.assessment_type = 'End-semester'"],
                         "attendance_band", "avg_score_pct DESC")

    if is_att:
        thr = re.search(r"(below|under|less than|<)\s*(\d+)", ql)
        if thr:
            joins, where = _filters(q, "a")
            joins = _dedupe_join(joins, "JOIN dim_course c ON a.course_id = c.course_id")
            return _assemble("c.course_code, COUNT(DISTINCT a.student_id) AS students_below",
                             "fact_attendance a", joins,
                             where + [f"a.attendance_pct < {thr.group(2)}"],
                             "c.course_code", "students_below DESC")
        if re.search(r"\b(top|best|highest|lowest|worst)\b", ql) and "section" in ql:
            joins, where = _filters(q, "a")
            joins.append("JOIN dim_section s ON a.section_id = s.section_id")
            order = "avg_attendance_pct ASC" if re.search(r"lowest|worst", ql) else "avg_attendance_pct DESC"
            return _assemble("s.section_name, ROUND(AVG(a.attendance_pct), 1) AS avg_attendance_pct",
                             "fact_attendance a", joins, where, "s.section_name", order)
        if "section" in ql:
            joins, where = _filters(q, "a")
            joins.append("JOIN dim_section s ON a.section_id = s.section_id")
            return _assemble("s.section_name, ROUND(AVG(a.attendance_pct), 1) AS avg_attendance_pct, "
                             "COUNT(DISTINCT a.student_id) AS students",
                             "fact_attendance a", joins, where, "s.section_name", "s.section_name")
        if re.search(r"\b(terms|trend|changed|over time|across|semesters|each term|per term|by term)\b", ql):
            joins, where = _filters(q, "a", across_terms=True)
            joins.append("JOIN dim_term t ON a.term_id = t.term_id")
            return _assemble("t.term_name, ROUND(AVG(a.attendance_pct), 1) AS avg_attendance_pct",
                             "fact_attendance a", joins, where, "t.term_id, t.term_name", "t.term_id")
        if "program" in ql:
            joins, where = _filters(q, "a")
            joins.append("JOIN dim_student s ON a.student_id = s.student_id")
            return _assemble("s.program, ROUND(AVG(a.attendance_pct), 1) AS avg_attendance_pct",
                             "fact_attendance a", joins, where, "s.program", "s.program")
        if _course(q) and not re.search(r"\b(each|per|by|every) course", ql):
            joins, where = _filters(q, "a")
            return _assemble("ROUND(AVG(a.attendance_pct), 1) AS avg_attendance_pct, "
                             "COUNT(DISTINCT a.student_id) AS students",
                             "fact_attendance a", joins, where)
        joins, where = _filters(q, "a")
        joins = _dedupe_join(joins, "JOIN dim_course c ON a.course_id = c.course_id")
        return _assemble("c.course_code, ROUND(AVG(a.attendance_pct), 1) AS avg_attendance_pct",
                         "fact_attendance a", joins, where, "c.course_code", "c.course_code")

    if is_score:
        if re.search(r"pass", ql):
            joins, where = _filters(q, "f")
            joins = _dedupe_join(joins, "JOIN dim_course c ON f.course_id = c.course_id")
            return _assemble("c.course_code, ROUND(100.0 * SUM(CASE WHEN f.score_pct >= 40 THEN 1 "
                             "ELSE 0 END) / COUNT(*), 1) AS pass_rate_pct",
                             "fact_assessment f", joins,
                             where + ["f.assessment_type = 'End-semester'"],
                             "c.course_code", "pass_rate_pct DESC")
        if re.search(r"\b(type|types|quiz|mid-?term|end-?sem\w*)\b", ql):
            joins, where = _filters(q, "f")
            return _assemble("f.assessment_type, ROUND(AVG(f.score_pct), 1) AS avg_score_pct",
                             "fact_assessment f", joins, where, "f.assessment_type",
                             "avg_score_pct DESC")
        if "section" in ql:
            joins, where = _filters(q, "f")
            joins.append("JOIN dim_section s ON f.section_id = s.section_id")
            return _assemble("s.section_name, ROUND(AVG(f.score_pct), 1) AS avg_score_pct",
                             "fact_assessment f", joins, where, "s.section_name", "s.section_name")
        if re.search(r"\b(terms|trend|changed|over time|across|semesters|each term|per term|by term)\b", ql):
            joins, where = _filters(q, "f", across_terms=True)
            joins.append("JOIN dim_term t ON f.term_id = t.term_id")
            return _assemble("t.term_name, ROUND(AVG(f.score_pct), 1) AS avg_score_pct",
                             "fact_assessment f", joins, where, "t.term_id, t.term_name", "t.term_id")
        if re.search(r"\bper student|each student|by student\b", ql):
            joins, where = _filters(q, "f")
            return _assemble("f.student_id, ROUND(AVG(f.score_pct), 1) AS avg_score_pct",
                             "fact_assessment f", joins, where, "f.student_id",
                             "avg_score_pct DESC")
        if _course(q) and not re.search(r"\b(each|per|by|every) course", ql):
            joins, where = _filters(q, "f")
            return _assemble("ROUND(AVG(f.score_pct), 1) AS avg_score_pct", "fact_assessment f",
                             joins, where)
        joins, where = _filters(q, "f")
        joins = _dedupe_join(joins, "JOIN dim_course c ON f.course_id = c.course_id")
        return _assemble("c.course_code, ROUND(AVG(f.score_pct), 1) AS avg_score_pct",
                         "fact_assessment f", joins, where, "c.course_code", "c.course_code")

    if re.search(r"how many students|number of students|count of students", ql):
        if _course(q) or _term(q):
            joins, where = _filters(q, "a", default_term=False)
            return _assemble("COUNT(DISTINCT a.student_id) AS students", "fact_attendance a",
                             joins, where)
        return _assemble("program, COUNT(*) AS students", "dim_student", [], [], "program",
                         "students DESC")

    return None


# --------------------------------------------------------------------------- Ollama / Qwen
def ollama_available(timeout=0.6):
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_URL}/api/tags", timeout=timeout) as r:
            names = [m.get("name", "") for m in json.load(r).get("models", [])]
        return any(n.split(":")[0] == config.QWEN_MODEL.split(":")[0] for n in names), names
    except Exception:
        return False, []


def build_prompt(question, error=None):
    shots = "\n\n".join(f"Question: {q}\nSQL:\n{s}" for q, s in FEW_SHOT)
    prompt = (
        "You translate questions about university attendance and assessment into ONE SQLite "
        "SELECT statement.\nRules: read-only SELECT only; use only the tables and columns below; "
        "no comments; never select student names or e-mails. If the schema cannot answer the "
        f"question, reply with exactly CANNOT_ANSWER.\nThe current term is '{config.CURRENT_TERM}'."
        f"\n\nSchema:\n{schema_prompt()}\n\nExamples:\n{shots}\n\n"
    )
    if error:
        prompt += f"Your previous SQL was rejected: {error}\nWrite a corrected query.\n\n"
    return prompt + f"Question: {question}\nSQL:\n"


def _extract_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    sql = (m.group(1) if m else text).strip()
    if "CANNOT_ANSWER" in sql.upper():
        return None
    return sql.strip().rstrip(";").strip() or None


def ollama_sql(question, error=None, timeout=60):
    body = json.dumps({"model": config.QWEN_MODEL, "prompt": build_prompt(question, error),
                       "stream": False, "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(f"{config.OLLAMA_URL}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return _extract_sql(json.load(r).get("response", ""))


# --------------------------------------------------------------------------- entry point
def generate(question, attempt=1, error=None, mode="offline", compromised=False):
    """Return {'sql', 'model', 'note'}. sql is None when the model cannot answer."""
    note = None
    model = "Offline demo model (stand-in for Qwen2.5-Coder)"
    sql = None
    if mode == "ollama":
        try:
            sql = ollama_sql(question, error)
            model = f"{config.QWEN_MODEL} via Ollama"
        except Exception as exc:  # model not running: keep the demo going
            note = f"Ollama not reachable ({exc.__class__.__name__}); used the offline model."
            sql = offline_sql(question)
    else:
        sql = offline_sql(question)

    if compromised and attempt == 1 and sql and sql.lstrip().upper().startswith("SELECT"):
        # A backdoored model (ToxicSQL-style) appends a payload to otherwise correct SQL.
        sql = sql + POISON_PAYLOAD
        note = "Compromised-model simulation: a hidden payload was appended to the SQL."
    return {"sql": sql, "model": model, "note": note}
