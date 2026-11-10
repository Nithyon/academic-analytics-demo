"""Excel import and export in the format faculty already use.

One workbook per course and section and term, with three sheets:
  * Info        - course code, section code, term
  * Attendance  - Roll No, Name, then one column per class session "YYYY-MM-DD P3",
                  cells P / A / OD / ML
  * Marks       - Roll No, Name, then one column per paper item "Component | Item (max)",
                  cells are paper marks, AB (absent) or W (withheld)

export_sheets() writes synthetic sheets from the database (demo and test data).
import_sheets() reads faculty sheets into the star schema, checks them, and rebuilds the
summary tables, so conversions and grades follow backend/rules.py.

  python -m backend.excel_io export --term 2026-ODD --out data/sheets
  python -m backend.excel_io roundtrip --term 2026-ODD
"""
import argparse
import re
import shutil
import sqlite3
from pathlib import Path

from openpyxl import Workbook, load_workbook

from . import config, summaries

HEADER_RE = re.compile(r"^(?P<comp>.+?) \| (?P<item>.+) \((?P<max>[\d.]+)\)$")
SESSION_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2}) P(?P<period>\d)$")


def export_sheets(term, out_dir, db_path=None, limit=None):
    db_path = db_path or config.DB_PATH
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    tid = con.execute("SELECT term_id FROM dim_term WHERE term_name = ?", (term,)).fetchone()[0]
    offers = con.execute("""SELECT DISTINCT a.course_id, c.course_code, a.section_id, s.section_code
                            FROM attendance_summary a JOIN dim_course c USING(course_id)
                            JOIN dim_section s USING(section_id) WHERE a.term_id = ?
                            ORDER BY c.course_code, s.section_code""", (tid,)).fetchall()
    written = []
    for cid, ccode, sid, scode in offers[:limit]:
        wb = Workbook()
        info = wb.active
        info.title = "Info"
        info.append(["course_code", ccode])
        info.append(["section_code", scode])
        info.append(["term", term])
        students = con.execute("""SELECT DISTINCT st.student_id, st.roll_no, st.full_name FROM attendance_summary a
                                  JOIN dim_student st USING(student_id)
                                  WHERE a.course_id = ? AND a.section_id = ? AND a.term_id = ?
                                  ORDER BY st.roll_no""", (cid, sid, tid)).fetchall()
        sessions = con.execute("""SELECT DISTINCT date, period FROM fact_attendance WHERE course_id = ? AND
                                  section_id = ? AND term_id = ? ORDER BY date, period""", (cid, sid, tid)).fetchall()
        att = {(s, d, p): st for s, d, p, st in con.execute(
            "SELECT student_id, date, period, status FROM fact_attendance WHERE course_id = ? AND section_id = ? "
            "AND term_id = ?", (cid, sid, tid))}
        ws = wb.create_sheet("Attendance")
        ws.append(["Roll No", "Name"] + [f"{d} P{p}" for d, p in sessions])
        for s, roll, name in students:
            ws.append([roll, name] + [att.get((s, d, p), "") for d, p in sessions])
        items = con.execute("""SELECT i.item_id, c.component_name, i.item_name, i.paper_max FROM dim_item i
                               JOIN dim_component c USING(component_id) WHERE c.course_id = ? AND c.term_id = ?
                               ORDER BY c.component_id, i.item_id""", (cid, tid)).fetchall()
        marks = {(s, i): (m, st) for s, i, m, st in con.execute(
            "SELECT student_id, item_id, marks_obtained, status FROM fact_assessment WHERE course_id = ? AND "
            "section_id = ? AND term_id = ?", (cid, sid, tid))}
        wm = wb.create_sheet("Marks")
        wm.append(["Roll No", "Name"] + [f"{c} | {n} ({m:g})" for _i, c, n, m in items])
        for s, roll, name in students:
            row = [roll, name]
            for iid, *_ in items:
                m, st = marks.get((s, iid), (None, None))
                row.append("AB" if st == "Absent" else "W" if st == "Withheld" else m)
            wm.append(row)
        path = out_dir / f"{term}_{ccode}_{scode}.xlsx"
        wb.save(path)
        written.append(path)
    con.close()
    return written


def import_sheets(paths, db_path=None):
    """Load faculty workbooks into fact tables; returns a report of rows loaded and problems."""
    db_path = db_path or config.DB_PATH
    con = sqlite3.connect(db_path)
    report = {"files": 0, "attendance_rows": 0, "assessment_rows": 0, "problems": []}
    rolls = dict(con.execute("SELECT roll_no, student_id FROM dim_student"))
    att_id = con.execute("SELECT COALESCE(MAX(attendance_id), 0) FROM fact_attendance").fetchone()[0]
    asm_id = con.execute("SELECT COALESCE(MAX(assessment_id), 0) FROM fact_assessment").fetchone()[0]
    for path in paths:
        wb = load_workbook(path, read_only=True, data_only=True)
        info = {r[0]: r[1] for r in wb["Info"].iter_rows(values_only=True)}
        cid = con.execute("SELECT course_id FROM dim_course WHERE course_code = ?", (info["course_code"],)).fetchone()
        sid = con.execute("SELECT section_id FROM dim_section WHERE section_code = ?", (info["section_code"],)).fetchone()
        tid = con.execute("SELECT term_id FROM dim_term WHERE term_name = ?", (info["term"],)).fetchone()
        if not (cid and sid and tid):
            report["problems"].append(f"{path.name}: unknown course, section or term in Info sheet")
            continue
        cid, sid, tid = cid[0], sid[0], tid[0]
        items = {}
        for iid, cname, iname, pmax, compid in con.execute(
                """SELECT i.item_id, c.component_name, i.item_name, i.paper_max, c.component_id FROM dim_item i
                   JOIN dim_component c USING(component_id) WHERE c.course_id = ? AND c.term_id = ?""", (cid, tid)):
            items[(cname, iname)] = (iid, pmax, compid)
        # ---- attendance
        rows = wb["Attendance"].iter_rows(values_only=True)
        header = next(rows)
        sessions = []
        for h in header[2:]:
            m = SESSION_RE.match(str(h))
            sessions.append((m.group("date"), int(m.group("period"))) if m else None)
            if not m:
                report["problems"].append(f"{path.name}: bad session header {h!r}")
        seen = set()
        for r in rows:
            roll = r[0]
            if roll not in rolls:
                report["problems"].append(f"{path.name}: unknown roll number {roll!r} (row skipped)")
                continue
            if roll in seen:
                report["problems"].append(f"{path.name}: duplicate roll number {roll!r} (row skipped)")
                continue
            seen.add(roll)
            for sess, val in zip(sessions, r[2:]):
                if sess is None or val in (None, ""):
                    continue
                if val not in ("P", "A", "OD", "ML"):
                    report["problems"].append(f"{path.name}: {roll} {sess}: bad status {val!r}")
                    continue
                att_id += 1
                con.execute("INSERT INTO fact_attendance VALUES (?,?,?,?,?,?,?,?)",
                            (att_id, rolls[roll], cid, sid, tid, sess[0], sess[1], val))
                report["attendance_rows"] += 1
        # ---- marks
        rows = wb["Marks"].iter_rows(values_only=True)
        header = next(rows)
        cols = []
        for h in header[2:]:
            m = HEADER_RE.match(str(h))
            key = (m.group("comp"), m.group("item")) if m else None
            if key not in items:
                report["problems"].append(f"{path.name}: column {h!r} does not match a component of the course")
                key = None
            cols.append(key)
        seen = set()
        for r in rows:
            roll = r[0]
            if roll not in rolls:
                report["problems"].append(f"{path.name}: Marks: unknown roll number {roll!r} (row skipped)")
                continue
            if roll in seen:
                report["problems"].append(f"{path.name}: Marks: duplicate roll number {roll!r} (row skipped)")
                continue
            seen.add(roll)
            for key, val in zip(cols, r[2:]):
                if key is None:
                    continue
                iid, pmax, compid = items[key]
                if val in ("AB", "ab", "Ab"):
                    marks, status = None, "Absent"
                elif val in ("W", "w"):
                    marks, status = None, "Withheld"
                elif val in (None, ""):
                    continue
                else:
                    try:
                        marks, status = float(val), "Graded"
                    except (TypeError, ValueError):
                        report["problems"].append(f"{path.name}: {roll} {key}: not a number {val!r}")
                        continue
                    if not 0 <= marks <= pmax:
                        report["problems"].append(f"{path.name}: {roll} {key}: {marks} is outside 0-{pmax:g}")
                        continue
                asm_id += 1
                con.execute("INSERT INTO fact_assessment VALUES (?,?,?,?,?,?,?,?,?)",
                            (asm_id, rolls[roll], iid, compid, cid, sid, tid, marks, status))
                report["assessment_rows"] += 1
        report["files"] += 1
        wb.close()
    summaries.build(con)
    con.commit()
    con.close()
    return report


def roundtrip(term):
    """Export a term to sheets, wipe that term's facts in a copy, import the sheets, compare."""
    tmp = config.DATA_DIR / "sheets_roundtrip"
    if tmp.exists():
        shutil.rmtree(tmp)
    paths = export_sheets(term, tmp / "sheets")
    copy = tmp / "copy.db"
    shutil.copy(config.DB_PATH, copy)
    con = sqlite3.connect(copy)
    tid = con.execute("SELECT term_id FROM dim_term WHERE term_name = ?", (term,)).fetchone()[0]
    con.execute("DELETE FROM fact_attendance WHERE term_id = ?", (tid,))
    con.execute("DELETE FROM fact_assessment WHERE term_id = ?", (tid,))
    con.commit()
    con.close()
    rep = import_sheets(paths, copy)
    q = ("SELECT COUNT(*), ROUND(SUM(attendance_pct), 4) FROM attendance_summary WHERE term_id = {t}",
         "SELECT COUNT(*), ROUND(SUM(total_marks), 4), SUM(result = 'Pass') FROM course_results WHERE term_id = {t}",
         "SELECT COUNT(*), ROUND(SUM(converted_marks), 4) FROM component_scores WHERE term_id = {t}")
    a, b = sqlite3.connect(config.DB_PATH), sqlite3.connect(copy)
    same = all(a.execute(s.format(t=tid)).fetchone() == b.execute(s.format(t=tid)).fetchone() for s in q)
    print({"workbooks": len(paths), **{k: v for k, v in rep.items() if k != "problems"},
           "problems": len(rep["problems"]), "summaries_identical": same})
    return same


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["export", "import", "roundtrip"])
    ap.add_argument("--term", default=config.CURRENT_TERM)
    ap.add_argument("--out", default=str(config.DATA_DIR / "sheets"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("files", nargs="*")
    a = ap.parse_args()
    if a.action == "export":
        print(len(export_sheets(a.term, a.out, limit=a.limit)), "workbooks written to", a.out)
    elif a.action == "import":
        r = import_sheets([Path(f) for f in a.files])
        print({k: v for k, v in r.items() if k != "problems"})
        for p in r["problems"][:50]:
            print(" -", p)
    else:
        raise SystemExit(0 if roundtrip(a.term) else 1)
