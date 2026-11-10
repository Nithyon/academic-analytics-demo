"""Star-schema definition, the allow-list and the schema metadata given to the model.

Two fact tables (attendance, assessment) and four dimensions (student, course, term,
section). Columns that identify a person (full_name, email) exist in the database but are
NOT on the allow-list, so the validator rejects any query that touches them.
"""

TABLES = {
    "fact_attendance": {
        "kind": "fact",
        "description": "One row per student, course and term: classes held and attended.",
        "columns": {
            "attendance_id": "INTEGER PRIMARY KEY",
            "student_id": "INTEGER",
            "course_id": "INTEGER",
            "term_id": "INTEGER",
            "section_id": "INTEGER",
            "classes_held": "INTEGER",
            "classes_attended": "INTEGER",
            "attendance_pct": "REAL",
        },
        "blocked": [],
    },
    "fact_assessment": {
        "kind": "fact",
        "description": "One row per student, course, term and assessment (Quiz, Mid-term, End-semester).",
        "columns": {
            "assessment_id": "INTEGER PRIMARY KEY",
            "student_id": "INTEGER",
            "course_id": "INTEGER",
            "term_id": "INTEGER",
            "section_id": "INTEGER",
            "assessment_type": "TEXT",
            "max_marks": "REAL",
            "marks_obtained": "REAL",
            "score_pct": "REAL",
        },
        "blocked": [],
    },
    "dim_student": {
        "kind": "dimension",
        "description": "Synthetic students. Names and e-mails are kept off the allow-list.",
        "columns": {
            "student_id": "INTEGER PRIMARY KEY",
            "full_name": "TEXT",
            "email": "TEXT",
            "program": "TEXT",
            "admission_year": "INTEGER",
        },
        "blocked": ["full_name", "email"],
    },
    "dim_course": {
        "kind": "dimension",
        "description": "Courses offered every term.",
        "columns": {
            "course_id": "INTEGER PRIMARY KEY",
            "course_code": "TEXT",
            "course_name": "TEXT",
            "department": "TEXT",
            "credits": "INTEGER",
        },
        "blocked": [],
    },
    "dim_term": {
        "kind": "dimension",
        "description": "Academic terms. 2026-ODD is the current term.",
        "columns": {
            "term_id": "INTEGER PRIMARY KEY",
            "term_name": "TEXT",
            "academic_year": "TEXT",
            "semester": "TEXT",
        },
        "blocked": [],
    },
    "dim_section": {
        "kind": "dimension",
        "description": "Class sections A to D.",
        "columns": {
            "section_id": "INTEGER PRIMARY KEY",
            "section_name": "TEXT",
            "timeslot": "TEXT",
        },
        "blocked": [],
    },
}

ALLOWED = {
    t: {c for c in spec["columns"] if c not in spec["blocked"]} for t, spec in TABLES.items()
}
ALL_COLUMNS = {t: set(spec["columns"]) for t, spec in TABLES.items()}


def ddl_statements():
    """CREATE TABLE statements for the full database (used by the data generator)."""
    out = []
    for name, spec in TABLES.items():
        cols = ",\n  ".join(f"{c} {t}" for c, t in spec["columns"].items())
        out.append(f"CREATE TABLE {name} (\n  {cols}\n);")
    return out


def schema_prompt():
    """Schema text given to the model: allow-listed columns only."""
    lines = []
    for name, spec in TABLES.items():
        cols = ", ".join(f"{c} {spec['columns'][c].split()[0]}" for c in spec["columns"]
                         if c in ALLOWED[name])
        lines.append(f"{name}({cols})  -- {spec['description']}")
    lines.append("Facts join to dimensions on student_id, course_id, term_id and section_id.")
    return "\n".join(lines)


def schema_metadata():
    """Schema description for the frontend."""
    return [
        {
            "name": name,
            "kind": spec["kind"],
            "description": spec["description"],
            "columns": [
                {"name": c, "type": t.split()[0], "allowed": c in ALLOWED[name]}
                for c, t in spec["columns"].items()
            ],
        }
        for name, spec in TABLES.items()
    ]
