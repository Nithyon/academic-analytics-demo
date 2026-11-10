"""Plain-assert tests for the safety gate, scoring, retrieval and Excel import.

Run:  .venv\\Scripts\\python -m tests.run_tests
"""
import shutil
import sqlite3

from openpyxl import load_workbook

from backend import config, evaluation, excel_io, ontology, retriever, router, validator

PASSED = []


def check(name, cond):
    assert cond, name
    PASSED.append(name)


def test_validator():
    ok = "SELECT c.course_code, AVG(a.attendance_pct) FROM attendance_summary a JOIN dim_course c ON a.course_id = c.course_id GROUP BY c.course_code"
    check("aggregate passes", validator.validate(ok)["passed"])
    for bad, why in [
        ("DROP TABLE fact_attendance", "write"),
        ("SELECT roll_no FROM dim_student", "roll number"),
        ("SELECT full_name FROM dim_student", "name"),
        ("SELECT student_id, attendance_pct FROM attendance_summary", "student_id output"),
        ("SELECT attendance_pct FROM attendance_summary", "row-level fact"),
        ("SELECT AVG(total_marks) FROM course_results GROUP BY student_id", "group by student"),
        ("SELECT AVG(total_marks) FROM course_results WHERE student_id = 5", "one student"),
        ("SELECT 1; DROP TABLE dim_student", "stacked"),
        ("SELECT name FROM sqlite_master", "system table"),
        ("SELECT AVG(attendance_pct) FROM attendance_summary -- hi", "comment"),
    ]:
        check(f"blocks {why}", not validator.validate(bad)["passed"])
    sub = ("SELECT COUNT(*) FROM (SELECT student_id FROM attendance_summary WHERE attendance_pct < 75)")
    check("aggregate over a per-student subquery passes", validator.validate(sub)["passed"])
    check("dimension listing passes", validator.validate("SELECT section_code FROM dim_section")["passed"])


def test_router():
    check("prediction declined", router.route("Which students will fail next term?")["decision"] == "decline")
    check("vague marks clarified", router.route("What are the average marks?")["decision"] == "clarify")
    check("medical leave is answerable", router.route("How many medical leave sessions in 21EEC301J this term?")["decision"] == "answer")
    check("gender declined", router.route("Pass rate by gender")["decision"] == "decline")


def test_matching():
    g = [["A", 81.23], ["B", 79.5]]
    check("same rows any order", evaluation.match(g, [["B", 79.5], ["A", 81.2]], True))
    check("extra column relaxed only", evaluation.match(g, [["A", 81.23, 30], ["B", 79.5, 28]], False)
          and not evaluation.match(g, [["A", 81.23, 30], ["B", 79.5, 28]], True))
    check("column order ignored", evaluation.match(g, [[81.23, "A"], [79.5, "B"]], True))
    check("tolerance 0.1", not evaluation.match(g, [["A", 81.5], ["B", 79.5]], False))
    check("row count must match", not evaluation.match(g, [["A", 81.23]], False))


def test_retrieval():
    links = ontology.link_entities("Pass rate in DBMS and Computer Networks this term for CSE")
    texts = " ".join(t for _k, t in links)
    check("links DBMS alias", "21CSC205J" in texts)
    check("links course name", "21CSC302J" in texts)
    check("links department", "dept_code 'CSE'" in texts)
    check("links this term", config.CURRENT_TERM in texts)
    r = retriever.retrieve("What is the pass rate per section of Computer Networks this term?")
    check("pass-rate metric retrieved", "marks.pass_rate" in r["cards"])
    check("course_results table retrieved", "course_results" in r["tables"])
    check("rag context smaller than full", len(r["context"]) < len(retriever.retrieve("x", "full")["context"]))


def test_excel_import_rejects_bad_data():
    tmp = config.DATA_DIR / "test_import"
    if tmp.exists():
        shutil.rmtree(tmp)
    paths = excel_io.export_sheets(config.CURRENT_TERM, tmp, limit=1)
    wb = load_workbook(paths[0])
    wm = wb["Marks"]
    wm.cell(row=2, column=3).value = 999          # above the paper maximum
    wm.cell(row=3, column=1).value = "RA0000000000000"  # unknown roll number
    wb.save(paths[0])
    copy = tmp / "copy.db"
    shutil.copy(config.DB_PATH, copy)
    rep = excel_io.import_sheets(paths, copy)
    problems = " ".join(rep["problems"])
    check("rejects marks above maximum", "outside 0-" in problems)
    check("rejects unknown roll number", "unknown roll number" in problems)
    con = sqlite3.connect(copy)
    check("summaries rebuilt", con.execute("SELECT COUNT(*) FROM course_results").fetchone()[0] > 0)
    con.close()
    shutil.rmtree(tmp)


if __name__ == "__main__":
    for fn in (test_validator, test_router, test_matching, test_retrieval, test_excel_import_rejects_bad_data):
        fn()
    print(f"{len(PASSED)} checks passed")
