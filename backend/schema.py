"""Star-schema definition (v2, SRM-style), the allow-list and schema text for the model.

Two fact tables at event grain:
  * fact_attendance  - one row per student per class session (date + period)
  * fact_assessment  - one row per student per marked paper item (CLA-1, Experiment 3, viva...)
Dimensions: department, program, section, student, course, term, date, component, item.
Three summary tables are derived from the facts (built by summaries.build):
  * attendance_summary - one row per student, course, term: classes held / attended / %
  * component_scores   - one row per student, course, term, component: paper and converted marks
  * course_results     - one row per student, course, term: internal, external, total, grade

Columns that identify a person (roll_no, full_name, email) exist but are NOT on the
allow-list, so the validator rejects any query that touches them.
"""

# name -> {kind, description, columns: {col: (type, description)}, blocked: [...]}
TABLES = {
    "dim_department": {
        "kind": "dimension",
        "description": "Academic departments. MATH is a service department that teaches other programs.",
        "columns": {
            "department_id": ("INTEGER PRIMARY KEY", "surrogate key"),
            "dept_code": ("TEXT", "short code: CSE, ECE, EEE, MATH"),
            "dept_name": ("TEXT", "full department name"),
        },
        "blocked": [],
    },
    "dim_program": {
        "kind": "dimension",
        "description": "Degree programs (branches), each owned by a department.",
        "columns": {
            "program_id": ("INTEGER PRIMARY KEY", "surrogate key"),
            "program_name": ("TEXT", "B.Tech CSE, B.Tech ECE, B.Tech EEE"),
            "department_id": ("INTEGER", "owning department"),
            "branch_code": ("TEXT", "three-digit branch code used in roll numbers"),
        },
        "blocked": [],
    },
    "dim_section": {
        "kind": "dimension",
        "description": "Class sections. A section is one program and one batch, e.g. CSE-2024-A.",
        "columns": {
            "section_id": ("INTEGER PRIMARY KEY", "surrogate key"),
            "section_code": ("TEXT", "program-batch-letter, e.g. CSE-2024-A"),
            "section_letter": ("TEXT", "A or B"),
            "program_id": ("INTEGER", "program of the section"),
            "batch_year": ("INTEGER", "admission year of the students in the section"),
        },
        "blocked": [],
    },
    "dim_student": {
        "kind": "dimension",
        "description": "Synthetic students. Roll number, name and e-mail are kept off the allow-list.",
        "columns": {
            "student_id": ("INTEGER PRIMARY KEY", "surrogate key"),
            "roll_no": ("TEXT", "SRM-style roll number (personal identifier)"),
            "full_name": ("TEXT", "student name (personal data)"),
            "email": ("TEXT", "student e-mail (personal data)"),
            "program_id": ("INTEGER", "program the student is enrolled in"),
            "section_id": ("INTEGER", "section the student belongs to"),
            "batch_year": ("INTEGER", "admission year (batch)"),
            "joined_date": ("TEXT", "first day the student attended (late joiners start later)"),
        },
        "blocked": ["roll_no", "full_name", "email"],
    },
    "dim_course": {
        "kind": "dimension",
        "description": "Course catalogue with SRM-style codes (T theory, L lab, J integrated theory + lab).",
        "columns": {
            "course_id": ("INTEGER PRIMARY KEY", "surrogate key"),
            "course_code": ("TEXT", "e.g. 21CSC205J"),
            "course_name": ("TEXT", "e.g. Database Management Systems"),
            "department_id": ("INTEGER", "department that teaches the course"),
            "course_type": ("TEXT", "Theory, Lab or Integrated"),
            "credits": ("INTEGER", "credits"),
            "semester_no": ("INTEGER", "semester in which the course is taken (1-8)"),
        },
        "blocked": [],
    },
    "dim_term": {
        "kind": "dimension",
        "description": "Academic terms (semesters). 2026-ODD is the current term.",
        "columns": {
            "term_id": ("INTEGER PRIMARY KEY", "surrogate key, increases with time"),
            "term_name": ("TEXT", "2024-EVEN, 2025-ODD, 2025-EVEN, 2026-ODD"),
            "academic_year": ("TEXT", "e.g. 2026-27"),
            "semester_type": ("TEXT", "Odd or Even"),
            "start_date": ("TEXT", "first teaching day, YYYY-MM-DD"),
            "end_date": ("TEXT", "last teaching day, YYYY-MM-DD"),
        },
        "blocked": [],
    },
    "dim_date": {
        "kind": "dimension",
        "description": "Calendar: one row per day, with week of term, holidays and exam weeks.",
        "columns": {
            "date": ("TEXT PRIMARY KEY", "YYYY-MM-DD"),
            "day_name": ("TEXT", "Mon, Tue, Wed, Thu, Fri, Sat, Sun"),
            "day_of_week": ("INTEGER", "1 = Monday ... 7 = Sunday"),
            "week_of_term": ("INTEGER", "teaching week number from 1; NULL outside a term"),
            "month": ("INTEGER", "1-12"),
            "month_name": ("TEXT", "Jan ... Dec"),
            "year": ("INTEGER", "calendar year"),
            "is_holiday": ("INTEGER", "1 if a declared holiday"),
            "holiday_name": ("TEXT", "name of the holiday, if any"),
            "is_exam_week": ("INTEGER", "1 during the end-semester exam window"),
            "term_id": ("INTEGER", "term the date belongs to, if any"),
        },
        "blocked": [],
    },
    "dim_component": {
        "kind": "dimension",
        "description": ("Mark components of a course in a term (CLA-1, Experiments, Lab test, Assignment, "
                        "Course completion, End semester) and what each is converted to out of 100."),
        "columns": {
            "component_id": ("INTEGER PRIMARY KEY", "surrogate key"),
            "course_id": ("INTEGER", "course"),
            "term_id": ("INTEGER", "term"),
            "component_name": ("TEXT", "CLA-1, CLA-2, CLA-3, Assignment, Experiments, Lab test, Course completion, End semester, End semester practical"),
            "component_group": ("TEXT", "Theory, Lab, Assignment, Course completion, End semester"),
            "assessment_kind": ("TEXT", "Internal or External"),
            "converted_max": ("REAL", "marks the component counts for in the 100-mark total"),
        },
        "blocked": [],
    },
    "dim_item": {
        "kind": "dimension",
        "description": "Paper items inside a component, with the maximum marks on paper (before conversion).",
        "columns": {
            "item_id": ("INTEGER PRIMARY KEY", "surrogate key"),
            "component_id": ("INTEGER", "component the item belongs to"),
            "item_name": ("TEXT", "e.g. Experiment 3, Lab test viva, CLA-2"),
            "paper_max": ("REAL", "maximum marks on paper"),
            "item_date": ("TEXT", "date the item was assessed, YYYY-MM-DD"),
        },
        "blocked": [],
    },
    "fact_attendance": {
        "kind": "fact",
        "description": "One row per student per class session (date and period). Event grain.",
        "columns": {
            "attendance_id": ("INTEGER PRIMARY KEY", "surrogate key"),
            "student_id": ("INTEGER", "student"),
            "course_id": ("INTEGER", "course"),
            "section_id": ("INTEGER", "section"),
            "term_id": ("INTEGER", "term"),
            "date": ("TEXT", "session date, joins dim_date.date"),
            "period": ("INTEGER", "hour of the day, 1-7"),
            "status": ("TEXT", "P present, A absent, OD on duty, ML medical leave"),
        },
        "blocked": [],
    },
    "fact_assessment": {
        "kind": "fact",
        "description": "One row per student per paper item. Marks are as written on paper (before conversion).",
        "columns": {
            "assessment_id": ("INTEGER PRIMARY KEY", "surrogate key"),
            "student_id": ("INTEGER", "student"),
            "item_id": ("INTEGER", "paper item"),
            "component_id": ("INTEGER", "component"),
            "course_id": ("INTEGER", "course"),
            "section_id": ("INTEGER", "section"),
            "term_id": ("INTEGER", "term"),
            "marks_obtained": ("REAL", "paper marks; NULL when absent or withheld"),
            "status": ("TEXT", "Graded, Absent or Withheld"),
        },
        "blocked": [],
    },
    "attendance_summary": {
        "kind": "summary",
        "description": ("Derived: one row per student, course and term. attendance_pct = (P + OD) / classes held x 100. "
                        "Use this for attendance percentages and the 75% rule."),
        "columns": {
            "student_id": ("INTEGER", "student"),
            "course_id": ("INTEGER", "course"),
            "section_id": ("INTEGER", "section"),
            "term_id": ("INTEGER", "term"),
            "classes_held": ("INTEGER", "sessions held since the student joined"),
            "classes_attended": ("INTEGER", "sessions with status P or OD"),
            "od_count": ("INTEGER", "sessions on duty"),
            "ml_count": ("INTEGER", "sessions on medical leave"),
            "absent_count": ("INTEGER", "sessions absent"),
            "attendance_pct": ("REAL", "classes_attended / classes_held x 100"),
        },
        "blocked": [],
    },
    "component_scores": {
        "kind": "summary",
        "description": ("Derived: one row per student, course, term and component. converted_marks = "
                        "paper_obtained / paper_max x converted_max. score_pct is the same on paper and converted scales."),
        "columns": {
            "student_id": ("INTEGER", "student"),
            "course_id": ("INTEGER", "course"),
            "section_id": ("INTEGER", "section"),
            "term_id": ("INTEGER", "term"),
            "component_id": ("INTEGER", "component"),
            "component_name": ("TEXT", "CLA-1, Experiments, Lab test, ..."),
            "component_group": ("TEXT", "Theory, Lab, Assignment, Course completion, End semester"),
            "assessment_kind": ("TEXT", "Internal or External"),
            "paper_obtained": ("REAL", "sum of paper marks (absent counts as 0)"),
            "paper_max": ("REAL", "sum of paper maxima"),
            "converted_max": ("REAL", "converted maximum"),
            "converted_marks": ("REAL", "marks after conversion"),
            "score_pct": ("REAL", "paper_obtained / paper_max x 100"),
            "status": ("TEXT", "Graded, Absent (all items absent) or Withheld"),
        },
        "blocked": [],
    },
    "course_results": {
        "kind": "summary",
        "description": ("Derived: one row per student, course and term. total_marks (out of 100) = internal_marks + external_marks. "
                        "Pass needs total >= 50 and at least 40% of the external maximum; grade on the 10-point scale."),
        "columns": {
            "student_id": ("INTEGER", "student"),
            "course_id": ("INTEGER", "course"),
            "section_id": ("INTEGER", "section"),
            "term_id": ("INTEGER", "term"),
            "internal_marks": ("REAL", "sum of converted internal components (out of internal_max)"),
            "internal_max": ("REAL", "60"),
            "external_marks": ("REAL", "converted end-semester marks (out of external_max)"),
            "external_max": ("REAL", "40"),
            "total_marks": ("REAL", "internal + external, out of 100"),
            "grade": ("TEXT", "O, A+, A, B+, B, C, F or W (withheld)"),
            "grade_point": ("INTEGER", "10, 9, 8, 7, 6, 5, 0"),
            "result": ("TEXT", "Pass, Fail or Withheld"),
            "end_sem_absent": ("INTEGER", "1 if absent for the end-semester exam"),
        },
        "blocked": [],
    },
}

FACT_LIKE = {t for t, s in TABLES.items() if s["kind"] in ("fact", "summary")}
PERSON_KEYS = {"student_id"}
ALLOWED = {t: {c for c in s["columns"] if c not in s["blocked"]} for t, s in TABLES.items()}
ALL_COLUMNS = {t: set(s["columns"]) for t, s in TABLES.items()}

JOIN_KEYS = [
    "fact/summary.student_id = dim_student.student_id",
    "fact/summary.course_id = dim_course.course_id",
    "fact/summary.section_id = dim_section.section_id",
    "fact/summary.term_id = dim_term.term_id",
    "fact_attendance.date = dim_date.date",
    "fact_assessment.item_id = dim_item.item_id; dim_item.component_id = dim_component.component_id",
    "component_scores.component_id = dim_component.component_id",
    "dim_course.department_id = dim_department.department_id",
    "dim_section.program_id = dim_program.program_id; dim_program.department_id = dim_department.department_id",
]


def ddl_statements():
    out = []
    for name, spec in TABLES.items():
        cols = ",\n  ".join(f"{c} {t}" for c, (t, _d) in spec["columns"].items())
        out.append(f"CREATE TABLE {name} (\n  {cols}\n);")
    return out


def table_text(name, with_descriptions=True):
    spec = TABLES[name]
    if with_descriptions:
        cols = "\n".join(f"    {c} {spec['columns'][c][0].split()[0]} -- {spec['columns'][c][1]}"
                         for c in spec["columns"] if c in ALLOWED[name])
        return f"{name}  -- {spec['description']}\n{cols}"
    cols = ", ".join(c for c in spec["columns"] if c in ALLOWED[name])
    return f"{name}({cols})"


def schema_prompt(tables=None, with_descriptions=True):
    """Schema text given to the model: allow-listed columns only."""
    names = tables or list(TABLES)
    body = "\n".join(table_text(n, with_descriptions) for n in names)
    if with_descriptions:
        body += "\nJoin keys:\n" + "\n".join(f"  {j}" for j in JOIN_KEYS)
    return body


def schema_metadata():
    return [
        {"name": name, "kind": spec["kind"], "description": spec["description"],
         "columns": [{"name": c, "type": t.split()[0], "allowed": c in ALLOWED[name]}
                     for c, (t, _d) in spec["columns"].items()]}
        for name, spec in TABLES.items()
    ]
