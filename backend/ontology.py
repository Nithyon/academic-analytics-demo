"""Machine-readable ontology: the metadata collection M that the retriever searches.

Cards:
  * table cards   - one per allow-listed table (built from schema.TABLES)
  * metric cards  - one fixed definition per metric, with the SQL pattern that computes it
  * concept cards - vocabulary and rules (this term, internal vs external, paper vs converted)
  * entity values - course codes and names, departments, programs, sections, terms; read from
                    the database so they always match the data
Human-readable version: docs/ontology.md.
"""
import re
import sqlite3

from . import config, rules
from .schema import TABLES

METRICS = [
    {"id": "att.mean_pct", "label": "Average attendance percentage",
     "definition": "Mean of the per-student attendance percentages (each student counts once).",
     "sql": "AVG(attendance_summary.attendance_pct)", "tables": ["attendance_summary"],
     "synonyms": "average attendance mean attendance attendance percentage attendance % class attendance"},
    {"id": "att.rate_pooled", "label": "Attendance rate (pooled)",
     "definition": "Total classes attended divided by total classes held, x 100 (each session counts once).",
     "sql": "100.0 * SUM(attendance_summary.classes_attended) / SUM(attendance_summary.classes_held)",
     "tables": ["attendance_summary"],
     "synonyms": "attendance rate overall rate pooled total classes attended held sessions"},
    {"id": "att.below_threshold", "label": "Students below the attendance threshold",
     "definition": f"Count of students whose attendance_pct is below {rules.ATTENDANCE_THRESHOLD} (use the "
                   "number in the question if one is given). Count per course with COUNT(*), across courses "
                   "with COUNT(DISTINCT student_id).",
     "sql": f"COUNT(*) ... WHERE attendance_pct < {rules.ATTENDANCE_THRESHOLD}", "tables": ["attendance_summary"],
     "synonyms": "below 75 shortage short of attendance detained debarred low attendance under threshold eligible condonation"},
    {"id": "att.session_rate", "label": "Attendance rate by day, period, week or month",
     "definition": "Share of sessions with status P or OD among all sessions, from fact_attendance joined to dim_date.",
     "sql": "100.0 * SUM(CASE WHEN f.status IN ('P','OD') THEN 1 ELSE 0 END) / COUNT(*)",
     "tables": ["fact_attendance", "dim_date"],
     "synonyms": "weekday monday friday day of week period hour first hour week of term weekly month monthly trend over weeks date"},
    {"id": "att.status_counts", "label": "On-duty, medical-leave and absent sessions",
     "definition": "Sum of od_count, ml_count or absent_count in attendance_summary, or count of fact_attendance rows by status.",
     "sql": "SUM(attendance_summary.od_count)", "tables": ["attendance_summary"],
     "synonyms": "on duty od medical leave ml absent sessions leave"},
    {"id": "marks.component_pct", "label": "Average score in a component (%)",
     "definition": "AVG(component_scores.score_pct) for the component (CLA-1, Experiments, Lab test, Assignment, "
                   "Course completion, End semester). The percentage is the same on paper and converted scales. "
                   "Use converted_marks only when the question asks for marks 'out of' the converted maximum, "
                   "and paper_obtained for marks on paper.",
     "sql": "AVG(component_scores.score_pct)", "tables": ["component_scores"],
     "synonyms": "cla cla-1 cla-2 cla-3 cycle test experiments experiment lab test viva assignment course completion component marks score paper converted out of"},
    {"id": "marks.group_pct", "label": "Average score in theory, lab or assignment parts (%)",
     "definition": "Pool the components of one group: 100 * SUM(converted_marks) / SUM(converted_max) per student, "
                   "then average; or simply 100.0 * SUM(converted_marks) / SUM(converted_max) over the group.",
     "sql": "100.0 * SUM(component_scores.converted_marks) / SUM(component_scores.converted_max) WHERE component_group = 'Lab'",
     "tables": ["component_scores"],
     "synonyms": "lab marks theory marks practical marks lab part theory part"},
    {"id": "marks.internal", "label": "Average internal marks",
     "definition": "AVG(course_results.internal_marks), out of 60 (all internal components converted and added).",
     "sql": "AVG(course_results.internal_marks)", "tables": ["course_results"],
     "synonyms": "internal marks internals continuous assessment sessional"},
    {"id": "marks.external", "label": "Average end-semester (external) marks",
     "definition": "AVG(course_results.external_marks), out of 40; for the exam percentage use component_scores.score_pct "
                   "where assessment_kind = 'External'.",
     "sql": "AVG(course_results.external_marks)", "tables": ["course_results"],
     "synonyms": "external end semester end sem final exam semester exam university exam"},
    {"id": "marks.total", "label": "Average total marks",
     "definition": "AVG(course_results.total_marks), out of 100. Exclude result = 'Withheld'.",
     "sql": "AVG(course_results.total_marks)", "tables": ["course_results"],
     "synonyms": "total marks overall marks average marks final marks marks out of 100"},
    {"id": "marks.pass_rate", "label": "Pass rate",
     "definition": f"Share of course results with result = 'Pass' among results that are not 'Withheld', x 100. "
                   f"Pass means total >= {rules.PASS_TOTAL} and at least {rules.PASS_EXTERNAL_PCT}% of the external maximum. "
                   "Do NOT use attendance for pass rate.",
     "sql": "100.0 * SUM(CASE WHEN result = 'Pass' THEN 1 ELSE 0 END) / COUNT(*) ... WHERE result <> 'Withheld'",
     "tables": ["course_results"],
     "synonyms": "pass rate pass percentage passed fail rate failed failures arrears cleared result"},
    {"id": "marks.grades", "label": "Grade distribution and grade points",
     "definition": "COUNT(*) per course_results.grade (O, A+, A, B+, B, C, F, W); AVG(grade_point) for the average grade point.",
     "sql": "COUNT(*) ... GROUP BY course_results.grade", "tables": ["course_results"],
     "synonyms": "grade grades o grade a+ distribution grade point gpa-like how many got"},
    {"id": "marks.absent", "label": "Absent for an assessment",
     "definition": "End-semester absence: SUM(course_results.end_sem_absent). Component absence: component_scores.status = 'Absent'.",
     "sql": "SUM(course_results.end_sem_absent)", "tables": ["course_results"],
     "synonyms": "absent missed exam did not write did not attend exam absentees"},
    {"id": "cnt.students", "label": "Number of students",
     "definition": "COUNT(DISTINCT student_id). Enrolled in a course this term: from attendance_summary or course_results. "
                   "Overall headcount: dim_student.",
     "sql": "COUNT(DISTINCT student_id)", "tables": ["dim_student"],
     "synonyms": "how many students number of students headcount strength enrolled class size"},
]

CONCEPTS = [
    {"id": "c.term", "text": f"'This term', 'this semester' and 'current semester' mean term_name = '{rules.CURRENT_TERM}'. "
                             f"'Last term' means '{rules.LAST_TERM}'. Compare terms by ordering on term_id.",
     "tables": ["dim_term"], "synonyms": "this term current semester this sem last term previous semester across terms trend over terms"},
    {"id": "c.department", "text": "A course belongs to the department that teaches it (dim_course.department_id). "
                                   "A student belongs to a program and section; the program belongs to a department "
                                   "(dim_section.program_id -> dim_program.department_id). For 'students of a department' "
                                   "use the student's program; for 'courses of a department' use dim_course.department_id.",
     "tables": ["dim_department", "dim_program", "dim_section", "dim_course"],
     "synonyms": "department dept cse ece eee maths mathematics branch program programme stream"},
    {"id": "c.section", "text": "A section is one program and one batch, e.g. CSE-2024-A. 'Section A' alone is ambiguous across "
                                "programs and batches unless the course fixes it. batch_year is the admission year; the "
                                "2024 batch is in semester 5 in 2026-ODD.",
     "tables": ["dim_section"], "synonyms": "section class batch year of study second year third year final year division"},
    {"id": "c.components", "text": "Internal components: CLA-1/2/3 (theory tests), Assignment, Experiments and Lab test (lab), "
                                   "Course completion. External: End semester (End semester practical for lab courses). "
                                   "converted_max says what each counts for out of 100; paper_max is the maximum on paper. "
                                   "Example: lab test written 20 + viva 5 = 25 on paper, converted to 10.",
     "tables": ["component_scores", "dim_component", "dim_item"],
     "synonyms": "component cla lab test viva experiment assignment course completion paper marks converted marks out of internal external"},
    {"id": "c.course_type", "text": "dim_course.course_type is Theory (T codes), Lab (L codes) or Integrated (J codes, theory + lab).",
     "tables": ["dim_course"], "synonyms": "theory course lab course integrated practical course type"},
    {"id": "c.calendar", "text": "dim_date has day_name, week_of_term, month_name, is_holiday and is_exam_week. Join fact_attendance.date "
                                 "= dim_date.date. Never compute dates with arithmetic; filter on these columns.",
     "tables": ["dim_date", "fact_attendance"], "synonyms": "day week month date calendar holiday weekday"},
    {"id": "c.privacy", "text": "Answers must be aggregates. Never select roll_no, full_name, email or student_id in the output, "
                                "never list individual students.",
     "tables": [], "synonyms": "names list students roll number who individual"},
]

ALIASES = {  # extra names people use for courses
    "dbms": "21CSC205J", "database": "21CSC205J", "dsa": "21CSC201J", "data structures": "21CSC201J",
    "daa": "21CSC204J", "cn": "21CSC302J", "networks": "21CSC302J", "computer networks": "21CSC302J",
    "oops": "21CSC101T", "flat": "21CSC301T", "automata": "21CSC301T", "se": "21CSC303J",
    "ai": "21CSC402J", "pqt": "21MAB204T", "probability": "21MAB204T", "dsp": "21ECC301J",
    "vlsi": "21ECC401J", "iot": "21ECE404J", "power electronics": "21EEC301J", "psa": "21EEC302T",
    "ml lab": "21CSC304L", "compiler": "21CSC401T", "transforms": "21MAB201T",
}
DEPT_WORDS = {"cse": "CSE", "computer science": "CSE", "ece": "ECE", "electronics": "ECE",
              "eee": "EEE", "electrical": "EEE", "math": "MATH", "maths": "MATH", "mathematics": "MATH"}


def table_cards():
    return [{"id": f"t.{n}", "kind": "table", "table": n, "text": f"{n} {s['description']} " +
             " ".join(f"{c} {d}" for c, (_t, d) in s["columns"].items())} for n, s in TABLES.items()]


def static_cards():
    cards = table_cards()
    cards += [{"id": m["id"], "kind": "metric", "tables": m["tables"],
               "text": f"{m['label']} {m['definition']} {m['synonyms']}", "card": m} for m in METRICS]
    cards += [{"id": c["id"], "kind": "concept", "tables": c["tables"],
               "text": f"{c['text']} {c['synonyms']}", "card": c} for c in CONCEPTS]
    return cards


_ENTITY_CACHE = {}


def entities(db_path=None):
    path = db_path or config.DB_PATH
    if path in _ENTITY_CACHE:
        return _ENTITY_CACHE[path]
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        ent = {
            "courses": con.execute("SELECT c.course_code, c.course_name, c.course_type, d.dept_code, c.semester_no "
                                   "FROM dim_course c JOIN dim_department d USING(department_id)").fetchall(),
            "departments": con.execute("SELECT dept_code, dept_name FROM dim_department").fetchall(),
            "programs": con.execute("SELECT program_name FROM dim_program").fetchall(),
            "sections": con.execute("SELECT section_code FROM dim_section").fetchall(),
            "terms": con.execute("SELECT term_name FROM dim_term ORDER BY term_id").fetchall(),
        }
    finally:
        con.close()
    _ENTITY_CACHE[path] = ent
    return ent


def link_entities(question, db_path=None):
    """Values in the question that map to database values (course codes, departments, ...)."""
    ent = entities(db_path)
    ql = question.lower()
    found = []
    by_code = {c[0]: c for c in ent["courses"]}
    for m in re.findall(r"\b\d{2}[a-z]{3}\d{3}[tljp]\b", ql):
        c = by_code.get(m.upper())
        if c:
            found.append(("course", f"course_code '{c[0]}' = {c[1]} ({c[2]}, {c[3]})"))
    for code, name, ctype, dept, _sem in ent["courses"]:
        if name.lower() in ql and not any(code in f[1] for f in found):
            found.append(("course", f"course_code '{code}' = {name} ({ctype}, {dept})"))
    for alias, code in ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", ql) and not any(code in f[1] for f in found):
            c = by_code[code]
            found.append(("course", f"course_code '{code}' = {c[1]} ({c[2]}, {c[3]})"))
    seen = set()
    for word, dept in DEPT_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", ql) and dept not in seen:
            seen.add(dept)
            name = dict(ent["departments"])[dept]
            found.append(("department", f"dept_code '{dept}' = {name}"))
    for (scode,) in ent["sections"]:
        if scode.lower() in ql:
            found.append(("section", f"section_code '{scode}'"))
    for (tname,) in ent["terms"]:
        if tname.lower() in ql:
            found.append(("term", f"term_name '{tname}'"))
    if re.search(r"\b(this|current) (term|semester|sem)\b", ql):
        found.append(("term", f"this term = term_name '{rules.CURRENT_TERM}'"))
    if re.search(r"\b(last|previous) (term|semester|sem)\b", ql):
        found.append(("term", f"last term = term_name '{rules.LAST_TERM}'"))
    for m in re.findall(r"\b(20\d\d) batch\b", ql):
        found.append(("batch", f"batch_year = {m}"))
    return found


def catalogue_text(db_path=None):
    """All entity values, for the full-context prompt."""
    ent = entities(db_path)
    lines = ["Courses: " + "; ".join(f"{c[0]} {c[1]} ({c[2]}, {c[3]}, sem {c[4]})" for c in ent["courses"]),
             "Departments: " + "; ".join(f"{d[0]} = {d[1]}" for d in ent["departments"]),
             "Programs: " + ", ".join(p[0] for p in ent["programs"]),
             "Sections: " + ", ".join(s[0] for s in ent["sections"]),
             "Terms: " + ", ".join(t[0] for t in ent["terms"]) + f" (current {rules.CURRENT_TERM})"]
    return "\n".join(lines)


def metric_text(m):
    return f"- {m['label']} [{m['id']}]: {m['definition']} SQL: {m['sql']}"


def concept_text(c):
    return f"- {c['text']}"
