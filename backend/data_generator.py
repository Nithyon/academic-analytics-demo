"""Synthetic data generator (offline step, layer D), v2: SRM-style institution.

Builds the star schema and fills it with realistic but entirely synthetic records:
departments, programs, sections, students with SRM-style roll numbers, a course
catalogue, a calendar with holidays and exam weeks, attendance for every class session,
and marks for every paper item (converted to the 100-mark total by summaries.build).

The same seed always gives the same database. Different seeds give different data with
the same catalogue, so gold answers can be checked on several fixtures.

Run on its own:  python -m backend.data_generator --seed 7
All assumptions live in backend/rules.py and docs/data_card.md.
"""
import argparse
import math
import random
import sqlite3
from datetime import timedelta

from . import config, rules, summaries
from .schema import ddl_statements

TELUGU_SURNAMES = ["pokala", "reddy", "naidu", "chowdary", "varma", "rao", "goud", "yadav",
                   "kommineni", "gaddam", "boddu", "pinnamaneni", "konda", "vemula"]
TELUGU_GIVEN = ["sai nithin", "venkata harsha", "sri charan", "lakshmi priya", "naga sai",
                "sai teja", "divya sri", "ravi kiran", "sri vidya", "hemanth", "bhavana",
                "pavan kumar", "keerthi", "manikanta"]
TAMIL_GIVEN = ["karthik", "priya", "arun", "deepika", "vignesh", "kavya", "surya", "nandhini",
               "harish", "swetha", "prakash", "janani", "dinesh", "aishwarya"]
INITIALS = list("rskmvpagdn")
NORTH_GIVEN = ["aarav", "ananya", "rohan", "ishita", "kabir", "meera", "aditya", "riya",
               "arjun", "sneha", "vivaan", "tanvi"]
NORTH_SURNAMES = ["sharma", "gupta", "singh", "verma", "joshi", "mehta", "agarwal", "mishra"]

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

DEPT_ATT = {"CSE": 1.0, "ECE": 0.0, "EEE": -1.5}       # attendance effect by program dept
TERM_ATT = {"2024-EVEN": 0.0, "2025-ODD": 0.5, "2025-EVEN": -3.0, "2026-ODD": 1.0}
DAY_ATT = {0: -2.0, 1: 0.5, 2: 1.0, 3: 0.5, 4: -4.0}  # Monday and Friday lower
PERIOD_ATT = {1: -3.0, 2: 0.0, 3: 1.0, 4: 1.0, 5: -1.0, 6: -1.5, 7: -5.0}
WEAK_SECTIONS = {"EEE-2024-B": -5.0, "CSE-2025-B": -3.0}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _name(rng):
    style = rng.random()
    if style < 0.45:
        return f"{rng.choice(TELUGU_SURNAMES)} {rng.choice(TELUGU_GIVEN)}"
    if style < 0.8:
        return f"{rng.choice(TAMIL_GIVEN)} {rng.choice(INITIALS)}"
    return f"{rng.choice(NORTH_GIVEN)} {rng.choice(NORTH_SURNAMES)}"


def _teaching_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in rules.HOLIDAYS:
            yield d
        d += timedelta(days=1)


def build(seed=config.DEFAULT_SEED, path=config.DB_PATH):
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    for stmt in ddl_statements():
        con.execute(stmt)

    # ---------------- organisation
    dept_id = {}
    for i, (code, name, _branch) in enumerate(rules.DEPARTMENTS, 1):
        dept_id[code] = i
        con.execute("INSERT INTO dim_department VALUES (?,?,?)", (i, code, name))
    branch = {code: b for code, _n, b in rules.DEPARTMENTS}
    prog_id, prog_dept = {}, {}
    for i, (pname, dcode) in enumerate(rules.PROGRAMS, 1):
        prog_id[dcode] = i
        prog_dept[i] = dcode
        con.execute("INSERT INTO dim_program VALUES (?,?,?,?)", (i, pname, dept_id[dcode], branch[dcode]))

    # ---------------- terms and calendar
    term_id = {}
    for i, (tname, ay, kind, start, end, _exam) in enumerate(rules.TERMS, 1):
        term_id[tname] = i
        con.execute("INSERT INTO dim_term VALUES (?,?,?,?,?,?)",
                    (i, tname, ay, kind, start.isoformat(), end.isoformat()))
    first, last = rules.TERMS[0][3], rules.TERMS[-1][5][1]
    d = first
    while d <= last:
        tid = week = None
        exam = 0
        for tname, _ay, _k, start, _end, (ex_s, ex_e) in rules.TERMS:
            if start <= d <= ex_e:
                tid, week = term_id[tname], (d - start).days // 7 + 1
                exam = int(ex_s <= d <= ex_e)
        con.execute("INSERT INTO dim_date VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (d.isoformat(), DAY_NAMES[d.weekday()], d.weekday() + 1, week, d.month,
                     MONTH_NAMES[d.month - 1], d.year, int(d in rules.HOLIDAYS),
                     rules.HOLIDAYS.get(d), exam, tid))
        d += timedelta(days=1)

    # ---------------- courses
    course_id, course_info = {}, {}
    for i, (code, name, dcode, ctype, credits, sem, progs, hours) in enumerate(rules.COURSES, 1):
        course_id[code] = i
        course_info[i] = {"code": code, "type": ctype, "sem": sem, "progs": progs, "hours": hours,
                          "eff": rng.gauss(0, 4) + (-4 if dcode == "MATH" else 0)}
        con.execute("INSERT INTO dim_course VALUES (?,?,?,?,?,?,?)",
                    (i, code, name, dept_id[dcode], rules.COURSE_TYPE_NAMES[ctype], credits, sem))

    # ---------------- sections and students
    sections, students = [], []
    sid_counter = sec_counter = 0
    for batch in rules.BATCHES:
        first_term = next(t for t in rules.TERMS if rules.semester_no(batch, t[0]) == 1) \
            if any(rules.semester_no(batch, t[0]) == 1 for t in rules.TERMS) else None
        for pname, dcode in rules.PROGRAMS:
            serial = rules.ROLL_SERIAL_START
            for li in range(rules.SECTIONS_PER_PROGRAM):
                sec_counter += 1
                letter = "AB"[li]
                scode = f"{dcode}-{batch}-{letter}"
                s_eff = WEAK_SECTIONS.get(scode, rng.gauss(0, 1.5))
                sections.append({"id": sec_counter, "code": scode, "prog": prog_id[dcode],
                                 "batch": batch, "eff": s_eff, "dept": dcode})
                con.execute("INSERT INTO dim_section VALUES (?,?,?,?,?)",
                            (sec_counter, scode, letter, prog_id[dcode], batch))
                for _ in range(rng.randint(*rules.STUDENTS_PER_SECTION)):
                    sid_counter += 1
                    roll = (f"{rules.ROLL_PREFIX}{batch % 100:02d}{rules.ROLL_DEGREE}"
                            f"{branch[dcode]}{rules.ROLL_CAMPUS}{serial:04d}")
                    serial += 1
                    name = _name(rng)
                    joined = None
                    if first_term is not None:
                        joined = first_term[3]
                        if rng.random() < 0.08:  # late joiners
                            joined = joined + timedelta(days=7 * rng.randint(1, 4))
                    dil = rng.gauss(0, 1)
                    students.append({
                        "id": sid_counter, "section": sec_counter, "prog": prog_id[dcode],
                        "batch": batch, "joined": joined, "dil": dil,
                        "abl": 0.6 * dil + 0.8 * rng.gauss(0, 1),
                        "od": rng.random() < 0.15, "ml": rng.random() < 0.08,
                    })
                    con.execute("INSERT INTO dim_student VALUES (?,?,?,?,?,?,?,?)",
                                (sid_counter, roll, name,
                                 f"{name.replace(' ', '.')}{sid_counter}@student.example.edu",
                                 prog_id[dcode], sec_counter, batch,
                                 joined.isoformat() if joined else None))
    by_section = {}
    for s in students:
        by_section.setdefault(s["section"], []).append(s)

    # ---------------- components and items for every course offered in every term
    comp_rows, item_rows = [], []
    offerings = {}  # (course_id, term_id) -> [(component_id, kind, [(item_id, paper_max, item_name)])]
    comp_id = item_id = 0
    for tname, _ay, _k, start, _end, (ex_s, _ex_e) in rules.TERMS:
        tid = term_id[tname]
        sems = {rules.semester_no(b, tname) for b in rules.BATCHES} - {None}
        for cid, info in course_info.items():
            if info["sem"] not in sems:
                continue
            comps = []
            for cname, group, kind, cmax, items in rules.COMPONENTS[info["type"]]:
                comp_id += 1
                comp_rows.append((comp_id, cid, tid, cname, group, kind, cmax))
                its = []
                for iname, pmax, week in items:
                    item_id += 1
                    when = (start + timedelta(days=7 * (week - 1) + 2)) if week else ex_s + \
                        timedelta(days=rng.randint(0, 10))
                    item_rows.append((item_id, comp_id, iname, pmax, when.isoformat()))
                    its.append((item_id, pmax, iname))
                comps.append((comp_id, cname, kind, its))
            offerings[(cid, tid)] = comps
    con.executemany("INSERT INTO dim_component VALUES (?,?,?,?,?,?,?)", comp_rows)
    con.executemany("INSERT INTO dim_item VALUES (?,?,?,?,?)", item_rows)

    # ---------------- attendance and marks
    att_rows, asm_rows = [], []
    aid = xid = 0
    for tname, _ay, _k, start, end, _exam in rules.TERMS:
        tid = term_id[tname]
        days = list(_teaching_days(start, end))
        for sec in sections:
            sem = rules.semester_no(sec["batch"], tname)
            if sem is None:
                continue
            courses = [cid for cid, info in course_info.items()
                       if info["sem"] == sem and sec["dept"] in info["progs"]]
            # weekly timetable for the section: distinct (weekday, period) slots per course
            free = [(wd, p) for wd in range(5) for p in range(1, rules.PERIODS_PER_DAY + 1)]
            rng.shuffle(free)
            slots = {}
            for cid in courses:
                slots[cid] = [free.pop() for _ in range(course_info[cid]["hours"])]
            for cid in courses:
                info = course_info[cid]
                sessions = [(day, p) for day in days for (wd, p) in slots[cid] if day.weekday() == wd]
                for st in by_section[sec["id"]]:
                    base = (84 + 6 * st["dil"] + DEPT_ATT[sec["dept"]] + sec["eff"]
                            + TERM_ATT[tname] + 0.15 * info["eff"])
                    ml_start = rng.randrange(len(days)) if st["ml"] and rng.random() < 0.5 else None
                    ml_days = set(days[ml_start:ml_start + rng.randint(2, 5)]) if ml_start is not None else set()
                    held = attended = 0
                    for day, p in sessions:
                        if st["joined"] and day < st["joined"]:
                            continue
                        week = (day - start).days // 7
                        pr = clamp(base + DAY_ATT[day.weekday()] + PERIOD_ATT[p] - 0.25 * week,
                                   30, 99) / 100
                        if day in ml_days:
                            status = "ML"
                        elif rng.random() < pr:
                            status = "OD" if st["od"] and rng.random() < 0.08 else "P"
                        else:
                            status = "A"
                        held += 1
                        attended += status in ("P", "OD")
                        aid += 1
                        att_rows.append((aid, st["id"], cid, sec["id"], tid, day.isoformat(), p, status))
                    att_pct = 100 * attended / held if held else 0
                    # marks for every paper item
                    for _comp, cname, kind, its in offerings[(cid, tid)]:
                        for iid, pmax, iname in its:
                            xid += 1
                            bonus = 8 if iname.startswith("Experiment") else 5 if "viva" in iname else 0
                            if kind == "External":
                                bonus -= 6
                            if iname == "Course completion":
                                if rng.random() < 0.1:
                                    asm_rows.append((xid, st["id"], iid, _comp, cid, sec["id"], tid, 0.0, "Graded"))
                                    continue
                                bonus += 15
                            pct = clamp(67 + 9 * st["abl"] + 0.3 * (att_pct - 80) + info["eff"]
                                        + bonus + rng.gauss(0, 9), 0, 100)
                            status, marks = "Graded", round(pct * pmax / 100 * 2) / 2
                            r = rng.random()
                            if kind == "External" and att_pct < 65 and r < 0.6:
                                status, marks = "Absent", None
                            elif r < (0.015 if kind == "External" else 0.02):
                                status, marks = "Absent", None
                            elif r > 0.9997:
                                status, marks = "Withheld", None
                            asm_rows.append((xid, st["id"], iid, _comp, cid, sec["id"], tid, marks, status))
    con.executemany("INSERT INTO fact_attendance VALUES (?,?,?,?,?,?,?,?)", att_rows)
    con.executemany("INSERT INTO fact_assessment VALUES (?,?,?,?,?,?,?,?,?)", asm_rows)
    summaries.build(con)
    con.execute("CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO _meta VALUES ('seed', ?)", (str(seed),))
    con.commit()
    con.close()
    return {"seed": seed, "students": len(students), "sections": len(sections),
            "attendance_rows": len(att_rows), "assessment_rows": len(asm_rows)}


STAT_TABLES = ("fact_attendance", "fact_assessment", "dim_student", "dim_course", "dim_term",
               "dim_section", "dim_department", "attendance_summary", "course_results")


def stats(path=config.DB_PATH):
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        out = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in STAT_TABLES}
        out["seed"] = int(con.execute("SELECT value FROM _meta WHERE key='seed'").fetchone()[0])
        return out
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate the synthetic academic star schema")
    ap.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    ap.add_argument("--path", default=None)
    a = ap.parse_args()
    from pathlib import Path
    print(build(a.seed, Path(a.path) if a.path else config.DB_PATH))
