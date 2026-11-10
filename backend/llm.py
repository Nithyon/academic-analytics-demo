"""SQL generation by the language model (layer B).

Back-ends:
  * "ollama"  - a real local model served by Ollama (default qwen2.5-coder:7b), prompted with
                the context chosen by the retriever (minimal / full / rag).
  * "offline" - a small deterministic stand-in so the demo runs with no model installed. It
                maps common question patterns to SQL, including the unsafe SQL that a naive or
                poisoned model can produce. It is NOT a language model and its accuracy is not
                reported as model accuracy; it exists so the safety layers can be shown.

Either way the model only *proposes* SQL. The validator and the read-only executor decide
what runs. If Ollama fails, the result is flagged fallback=True (never silently replaced).
"""
import json
import re
import time
import urllib.request

from . import config, ontology, rules

POISON_PAYLOAD = "; DROP TABLE fact_attendance"


# --------------------------------------------------------------------------- prompt
def build_prompt(question, retrieved, error=None):
    shots = "\n\n".join(f"Question: {q}\nSQL:\n{s}" for q, s in retrieved.get("examples", []))
    prompt = (
        "You translate questions from faculty about attendance and marks into ONE SQLite SELECT "
        "statement.\nRules: read-only SELECT only; use only the tables and columns given; no "
        "comments; answers must be aggregates (never list individual students, never select "
        "roll_no, full_name, email or student_id); round percentages and averages to 2 decimals. "
        "If the data cannot answer the question, reply with exactly CANNOT_ANSWER.\n"
        f"The current term is '{rules.CURRENT_TERM}'.\n\n{retrieved['context']}\n\n")
    if shots:
        prompt += f"Examples:\n{shots}\n\n"
    if error:
        prompt += f"Your previous SQL was rejected: {error}\nWrite a corrected query.\n\n"
    return prompt + f"Question: {question}\nSQL:\n"


def _extract_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    sql = (m.group(1) if m else text).strip()
    if "CANNOT_ANSWER" in sql.upper():
        return None
    return sql.strip().rstrip(";").strip() or None


def ollama_available(timeout=0.6):
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_URL}/api/tags", timeout=timeout) as r:
            names = [m.get("name", "") for m in json.load(r).get("models", [])]
        return config.QWEN_MODEL in names, names
    except Exception:
        return False, []


def ollama_sql(prompt, model):
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "keep_alive": "30m",
                       "options": {"temperature": 0, "seed": 0, "num_ctx": 8192,
                                   "num_predict": 512}}).encode()
    req = urllib.request.Request(f"{config.OLLAMA_URL}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    timeout = config.OLLAMA_TIMEOUTS.get(model, config.OLLAMA_TIMEOUTS["default"])
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    return _extract_sql(out.get("response", "")), {
        "prompt_tokens": out.get("prompt_eval_count"), "output_tokens": out.get("eval_count"),
        "load_ms": (out.get("load_duration") or 0) / 1e6}


# --------------------------------------------------------------------------- offline model
COURSE_RE = re.compile(r"\b(\d{2}[A-Za-z]{3}\d{3}[TLJPtljp])\b")


def _course(q):
    m = COURSE_RE.search(q)
    if m:
        return m.group(1).upper()
    ql = q.lower()
    for alias, code in ontology.ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", ql):
            return code
    return None


def _term(q):
    ql = q.lower()
    m = re.search(r"\b(20\d\d)[\s-]?(odd|even)\b", ql)
    if m:
        return f"{m.group(1)}-{m.group(2).upper()}"
    if re.search(r"\b(last|previous) (term|semester|sem)\b", ql):
        return rules.LAST_TERM
    return rules.CURRENT_TERM


def _filters(q, alias, across_terms=False):
    joins, where = [], []
    course = _course(q)
    if course:
        joins.append(f"JOIN dim_course c ON {alias}.course_id = c.course_id")
        where.append(f"c.course_code = '{course}'")
    if not across_terms:
        joins.append(f"JOIN dim_term t ON {alias}.term_id = t.term_id")
        where.append(f"t.term_name = '{_term(q)}'")
    return joins, where


def _sql(select, frm, joins, where, group=None, order=None):
    sql = f"SELECT {select}\nFROM {frm}"
    seen = set()
    for j in joins:
        key = j.split(" ON ")[0]
        if key not in seen:
            seen.add(key)
            sql += f"\n{j}"
    if where:
        sql += "\nWHERE " + " AND ".join(where)
    if group:
        sql += f"\nGROUP BY {group}"
    if order:
        sql += f"\nORDER BY {order}"
    return sql


def _grouping(q, alias):
    ql = q.lower()
    if "department" in ql or "dept" in ql:
        return ("d.dept_code", [f"JOIN dim_section s ON {alias}.section_id = s.section_id",
                                "JOIN dim_program p ON s.program_id = p.program_id",
                                "JOIN dim_department d ON p.department_id = d.department_id"])
    if "section" in ql:
        return ("s.section_code", [f"JOIN dim_section s ON {alias}.section_id = s.section_id"])
    if re.search(r"\bprogram", ql):
        return ("p.program_name", [f"JOIN dim_section s ON {alias}.section_id = s.section_id",
                                   "JOIN dim_program p ON s.program_id = p.program_id"])
    if re.search(r"\b(terms|across|trend|changed|over time|each term|per term)\b", ql):
        return ("t.term_name", [f"JOIN dim_term t ON {alias}.term_id = t.term_id"])
    return ("c.course_code", [f"JOIN dim_course c ON {alias}.course_id = c.course_id"])


def offline_sql(q):
    ql = q.lower()
    is_att = "attend" in ql
    is_marks = bool(re.search(r"\b(marks?|scores?|grades?|pass|fail|internal|cla|result)", ql))

    # what a naive model does with a write request: it writes the SQL anyway
    if re.search(r"'\s*;|;\s*(drop|delete|update|insert)", ql):
        base = offline_sql(re.split(r"'|;", q)[0]) or "SELECT AVG(attendance_pct) FROM attendance_summary"
        tail = re.search(r";\s*(.*)$", q).group(1).replace("--", "").strip().rstrip(";")
        return f"{base};\n{tail} --"
    if re.search(r"\b(drop|truncate)\b", ql) and "dropped" not in ql:
        return f"DROP TABLE {'fact_assessment' if is_marks else 'fact_attendance'}"
    if re.search(r"\b(delete|wipe|erase|remove all)\b", ql):
        return f"DELETE FROM {'fact_assessment' if is_marks else 'fact_attendance'}"
    if re.search(r"\b(set|change|update)\b.*\b(marks?|grades?|attendance)\b.*\b(to|as)\b|full marks", ql):
        return "UPDATE fact_assessment SET marks_obtained = 100"
    if re.search(r"\b(insert|add a student)\b", ql):
        return "INSERT INTO dim_student (student_id, full_name) VALUES (99999, 'test')"
    # personal data: the model happily selects names / roll numbers; the allow-list stops it
    if re.search(r"\b(names?|roll ?(no|numbers?)|who are|e-?mails?)\b", ql):
        col = "s.roll_no" if "roll" in ql else "s.full_name"
        thr = re.search(r"(below|under|less than|<)\s*(\d+)", ql)
        joins, where = _filters(q, "a")
        where.append(f"a.attendance_pct < {thr.group(2) if thr else rules.ATTENDANCE_THRESHOLD}")
        return _sql(f"{col}, a.attendance_pct", "attendance_summary a",
                    ["JOIN dim_student s ON a.student_id = s.student_id"] + joins, where)

    if is_att:
        thr = re.search(r"(below|under|less than|<)\s*(\d+)", ql)
        across = bool(re.search(r"\b(terms|across|trend|changed|over time)\b", ql))
        joins, where = _filters(q, "a", across_terms=across)
        if re.search(r"\b(weekday|day of the week|which day|monday|friday)\b", ql):
            j2, w2 = _filters(q, "f")
            return _sql("dd.day_name, ROUND(100.0 * SUM(CASE WHEN f.status IN ('P','OD') THEN 1 ELSE 0 END) "
                        "/ COUNT(*), 2) AS attendance_rate", "fact_attendance f",
                        ["JOIN dim_date dd ON f.date = dd.date"] + j2, w2, "dd.day_name, dd.day_of_week",
                        "dd.day_of_week")
        gcol, gj = _grouping(q, "a")
        if thr:
            return _sql(f"{gcol}, COUNT(*) AS students_below", "attendance_summary a", joins + gj,
                        where + [f"a.attendance_pct < {thr.group(2)}"], gcol, "students_below DESC")
        if _course(q) and gcol == "c.course_code":
            return _sql("ROUND(AVG(a.attendance_pct), 2) AS avg_attendance_pct", "attendance_summary a",
                        joins, where)
        return _sql(f"{gcol}, ROUND(AVG(a.attendance_pct), 2) AS avg_attendance_pct",
                    "attendance_summary a", joins + gj, where, gcol, gcol)

    if is_marks:
        across = bool(re.search(r"\b(terms|across|trend|changed|over time)\b", ql))
        joins, where = _filters(q, "r", across_terms=across)
        gcol, gj = _grouping(q, "r")
        comp = re.search(r"\b(cla-?\s?[123]|experiments?|lab test|assignment|course completion)\b", ql)
        if comp:
            name = comp.group(1).upper().replace(" ", "") if comp.group(1).startswith("cla") else \
                {"experiment": "Experiments", "experiments": "Experiments", "lab test": "Lab test",
                 "assignment": "Assignment", "course completion": "Course completion"}[comp.group(1)]
            if name.startswith("CLA") and "-" not in name:
                name = name[:3] + "-" + name[3:]
            return _sql(f"{gcol}, ROUND(AVG(r.score_pct), 2) AS avg_score_pct", "component_scores r",
                        joins + gj, where + [f"r.component_name = '{name}'"], gcol, gcol)
        if re.search(r"\bpass|fail", ql):
            return _sql(f"{gcol}, ROUND(100.0 * SUM(CASE WHEN r.result = 'Pass' THEN 1 ELSE 0 END) / COUNT(*), 2) "
                        "AS pass_rate_pct", "course_results r", joins + gj,
                        where + ["r.result <> 'Withheld'"], gcol, "pass_rate_pct DESC")
        col = "internal_marks" if "internal" in ql else "total_marks"
        if _course(q) and gcol == "c.course_code":
            return _sql(f"ROUND(AVG(r.{col}), 2) AS avg_{col}", "course_results r", joins, where)
        return _sql(f"{gcol}, ROUND(AVG(r.{col}), 2) AS avg_{col}", "course_results r", joins + gj,
                    where, gcol, gcol)

    if re.search(r"how many students|number of students|headcount|strength", ql):
        if "department" in ql:
            return _sql("d.dept_code, COUNT(*) AS students", "dim_student st",
                        ["JOIN dim_program p ON st.program_id = p.program_id",
                         "JOIN dim_department d ON p.department_id = d.department_id"], [], "d.dept_code",
                        "d.dept_code")
        return _sql("p.program_name, COUNT(*) AS students", "dim_student st",
                    ["JOIN dim_program p ON st.program_id = p.program_id"], [], "p.program_name",
                    "p.program_name")
    return None


# --------------------------------------------------------------------------- entry point
def generate(question, retrieved, attempt=1, error=None, mode="offline", compromised=False,
             model=None):
    """Return {'sql', 'model', 'note', 'fallback', 'gen_ms', 'tokens'}. sql None = cannot answer."""
    model = model or config.QWEN_MODEL
    note, fallback, tokens = None, False, {}
    t0 = time.perf_counter()
    if mode == "ollama":
        try:
            sql, tokens = ollama_sql(build_prompt(question, retrieved, error), model)
            label = f"{model} via Ollama"
        except Exception as exc:  # model not running: keep the demo going, but say so
            note = f"Ollama not reachable ({exc.__class__.__name__}); used the offline model."
            fallback = True
            sql, label = offline_sql(question), "Offline demo model (fallback)"
    else:
        sql, label = offline_sql(question), "Offline demo model (stand-in for Qwen2.5-Coder)"
    gen_ms = (time.perf_counter() - t0) * 1000

    if compromised and attempt == 1 and sql and sql.lstrip().upper().startswith(("SELECT", "WITH")):
        sql = sql + POISON_PAYLOAD  # ToxicSQL-style backdoor appends a payload to correct SQL
        note = "Compromised-model simulation: a hidden payload was appended to the SQL."
    return {"sql": sql, "model": label, "note": note, "fallback": fallback, "gen_ms": gen_ms,
            "tokens": tokens}
