"""Synthetic data generator (offline step, layer D).

Builds the star schema and fills it with realistic but entirely synthetic records.
The same seed always produces the same database, so results can be re-checked on
several generated copies (one database per seed).

Run on its own:  python -m backend.data_generator --seed 7
"""
import argparse
import random
import sqlite3

from . import config
from .schema import ddl_statements

COURSES = [
    (1, "CS2101", "Data Structures", "Computer Science", 4, 0.0, 0.0),
    (2, "CS2102", "Database Management Systems", "Computer Science", 4, 1.5, 2.0),
    (3, "CS2103", "Operating Systems", "Computer Science", 3, -2.0, -4.0),
    (4, "CS2104", "Computer Networks", "Computer Science", 3, -0.5, -1.5),
    (5, "MA2101", "Probability and Statistics", "Mathematics", 4, -3.0, -6.0),
]  # id, code, name, department, credits, attendance effect, score effect

TERMS = [
    (1, "2025-ODD", "2025-26", "Odd", 0.0),
    (2, "2025-EVEN", "2025-26", "Even", -3.5),
    (3, "2026-ODD", "2026-27", "Odd", 1.5),
]  # id, name, academic year, semester, attendance effect

SECTIONS = [
    (1, "A", "Mon/Wed 09:00", 2.0),
    (2, "B", "Mon/Wed 11:00", 0.5),
    (3, "C", "Tue/Thu 14:00", -1.5),
    (4, "D", "Fri 16:00", -4.0),
]  # id, name, timeslot, attendance effect

PROGRAMS = ["B.Tech CSE", "B.Tech IT", "B.Tech AI & DS"]
ASSESSMENTS = [("Quiz", 20), ("Mid-term", 50), ("End-semester", 100)]

FIRST = ["Aarav", "Diya", "Ishaan", "Ananya", "Vihaan", "Meera", "Arjun", "Saanvi", "Kabir",
         "Riya", "Rohan", "Kavya", "Aditya", "Nisha", "Karthik", "Pooja", "Siddharth", "Lakshmi",
         "Varun", "Sneha", "Rahul", "Divya", "Nikhil", "Priya"]
LAST = ["Sharma", "Iyer", "Reddy", "Nair", "Patel", "Gupta", "Menon", "Rao", "Kumar", "Das",
        "Pillai", "Singh", "Joshi", "Bose", "Chopra", "Krishnan"]

STUDENTS_PER_TERM = 120  # each term a new cohort takes the five courses


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def build(seed=config.DEFAULT_SEED, path=config.DB_PATH):
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    for stmt in ddl_statements():
        con.execute(stmt)

    con.executemany("INSERT INTO dim_course VALUES (?,?,?,?,?)", [c[:5] for c in COURSES])
    con.executemany("INSERT INTO dim_term VALUES (?,?,?,?)", [t[:4] for t in TERMS])
    con.executemany("INSERT INTO dim_section VALUES (?,?,?)", [s[:3] for s in SECTIONS])

    students, attendance, assessment = [], [], []
    sid = aid = xid = 0
    for term_id, term_name, _, _, term_eff in TERMS:
        for _ in range(STUDENTS_PER_TERM):
            sid += 1
            first, last = rng.choice(FIRST), rng.choice(LAST)
            program = rng.choices(PROGRAMS, weights=[5, 3, 2])[0]
            admission = 2024 if term_id < 3 else 2025
            students.append((sid, f"{first} {last}", f"{first}.{last}{sid}@example.edu".lower(),
                             program, admission))
            section_id, _, _, sec_eff = rng.choice(SECTIONS)
            diligence = rng.gauss(0, 1)
            ability = 0.6 * diligence + 0.8 * rng.gauss(0, 1)
            for course_id, _, _, _, _, c_att, c_score in COURSES:
                aid += 1
                held = rng.randint(40, 48)
                pct = clamp(82 + 7 * diligence + sec_eff + c_att + term_eff + rng.gauss(0, 4), 30, 100)
                attended = round(pct * held / 100)
                att_pct = round(attended / held * 100, 1)
                attendance.append((aid, sid, course_id, term_id, section_id, held, attended, att_pct))
                for a_type, max_marks in ASSESSMENTS:
                    xid += 1
                    score = clamp(62 + 9 * ability + 0.35 * (att_pct - 82) + c_score
                                  + rng.gauss(0, 8), 5, 100)
                    marks = round(score * max_marks / 100, 1)
                    assessment.append((xid, sid, course_id, term_id, section_id, a_type,
                                       max_marks, marks, round(marks / max_marks * 100, 1)))

    con.executemany("INSERT INTO dim_student VALUES (?,?,?,?,?)", students)
    con.executemany("INSERT INTO fact_attendance VALUES (?,?,?,?,?,?,?,?)", attendance)
    con.executemany("INSERT INTO fact_assessment VALUES (?,?,?,?,?,?,?,?,?)", assessment)
    con.execute("CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO _meta VALUES ('seed', ?)", (str(seed),))
    con.commit()
    con.close()
    return {"seed": seed, "students": len(students), "attendance_rows": len(attendance),
            "assessment_rows": len(assessment)}


def stats(path=config.DB_PATH):
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        out = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
               for t in ("fact_attendance", "fact_assessment", "dim_student", "dim_course",
                         "dim_term", "dim_section")}
        out["seed"] = int(con.execute("SELECT value FROM _meta WHERE key='seed'").fetchone()[0])
        return out
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate the synthetic academic star schema")
    ap.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    print(build(ap.parse_args().seed))
