"""Builds the three derived summary tables from the two fact tables.

Called by the data generator and by the Excel importer, so both paths compute converted
marks, totals, grades and attendance percentages with exactly the same rules.
"""
from . import rules

GRADE_CASE = "CASE " + " ".join(
    f"WHEN total >= {lo} THEN '{g}'" for lo, g, _ in rules.GRADES[:-1]) + " ELSE 'F' END"
POINT_CASE = "CASE " + " ".join(
    f"WHEN total >= {lo} THEN {p}" for lo, _, p in rules.GRADES[:-1]) + " ELSE 0 END"


def build(con):
    con.execute("DELETE FROM attendance_summary")
    con.execute("DELETE FROM component_scores")
    con.execute("DELETE FROM course_results")
    con.execute("""
        INSERT INTO attendance_summary
        SELECT student_id, course_id, section_id, term_id,
               COUNT(*),
               SUM(CASE WHEN status IN ('P', 'OD') THEN 1 ELSE 0 END),
               SUM(CASE WHEN status = 'OD' THEN 1 ELSE 0 END),
               SUM(CASE WHEN status = 'ML' THEN 1 ELSE 0 END),
               SUM(CASE WHEN status = 'A' THEN 1 ELSE 0 END),
               ROUND(100.0 * SUM(CASE WHEN status IN ('P', 'OD') THEN 1 ELSE 0 END) / COUNT(*), 2)
        FROM fact_attendance
        GROUP BY student_id, course_id, section_id, term_id""")
    con.execute("""
        INSERT INTO component_scores
        SELECT f.student_id, f.course_id, f.section_id, f.term_id, c.component_id,
               c.component_name, c.component_group, c.assessment_kind,
               SUM(COALESCE(f.marks_obtained, 0)), SUM(i.paper_max), c.converted_max,
               ROUND(SUM(COALESCE(f.marks_obtained, 0)) * c.converted_max / SUM(i.paper_max), 2),
               ROUND(100.0 * SUM(COALESCE(f.marks_obtained, 0)) / SUM(i.paper_max), 2),
               CASE WHEN SUM(f.status = 'Withheld') > 0 THEN 'Withheld'
                    WHEN SUM(f.status = 'Absent') = COUNT(*) THEN 'Absent' ELSE 'Graded' END
        FROM fact_assessment f
        JOIN dim_item i ON i.item_id = f.item_id
        JOIN dim_component c ON c.component_id = i.component_id
        GROUP BY f.student_id, f.course_id, f.section_id, f.term_id, c.component_id""")
    con.execute(f"""
        INSERT INTO course_results
        WITH t AS (
            SELECT student_id, course_id, section_id, term_id,
                   SUM(CASE WHEN assessment_kind = 'Internal' THEN converted_marks ELSE 0 END) AS im,
                   SUM(CASE WHEN assessment_kind = 'Internal' THEN converted_max ELSE 0 END) AS imax,
                   SUM(CASE WHEN assessment_kind = 'External' THEN converted_marks ELSE 0 END) AS em,
                   SUM(CASE WHEN assessment_kind = 'External' THEN converted_max ELSE 0 END) AS emax,
                   MAX(status = 'Withheld') AS wh,
                   MAX(assessment_kind = 'External' AND status = 'Absent') AS ab
            FROM component_scores
            GROUP BY student_id, course_id, section_id, term_id),
        u AS (SELECT *, ROUND(im + em, 2) AS total,
                     CASE WHEN wh = 1 THEN 'Withheld'
                          WHEN ab = 1 OR ROUND(im + em, 2) < {rules.PASS_TOTAL}
                               OR em < {rules.PASS_EXTERNAL_PCT / 100} * emax THEN 'Fail'
                          ELSE 'Pass' END AS result
              FROM t)
        SELECT student_id, course_id, section_id, term_id, ROUND(im, 2), imax, ROUND(em, 2), emax,
               total,
               CASE WHEN result = 'Withheld' THEN 'W' WHEN result = 'Fail' THEN 'F' ELSE {GRADE_CASE} END,
               CASE WHEN result = 'Pass' THEN {POINT_CASE} ELSE 0 END,
               result, ab
        FROM u""")
    for stmt in (
        "CREATE INDEX IF NOT EXISTS ix_att ON fact_attendance(course_id, term_id, section_id)",
        "CREATE INDEX IF NOT EXISTS ix_att_date ON fact_attendance(date)",
        "CREATE INDEX IF NOT EXISTS ix_asm ON fact_assessment(course_id, term_id)",
        "CREATE INDEX IF NOT EXISTS ix_as ON attendance_summary(course_id, term_id)",
        "CREATE INDEX IF NOT EXISTS ix_cs ON component_scores(course_id, term_id)",
        "CREATE INDEX IF NOT EXISTS ix_cr ON course_results(course_id, term_id)",
        "CREATE INDEX IF NOT EXISTS ix_as_s ON attendance_summary(student_id, course_id, term_id)",
        "CREATE INDEX IF NOT EXISTS ix_cs_s ON component_scores(student_id, course_id, term_id)",
        "CREATE INDEX IF NOT EXISTS ix_cr_s ON course_results(student_id, course_id, term_id)",
        "CREATE INDEX IF NOT EXISTS ix_att_s ON fact_attendance(student_id, course_id, term_id)",
        "CREATE INDEX IF NOT EXISTS ix_as_sec ON attendance_summary(section_id, term_id)",
        "CREATE INDEX IF NOT EXISTS ix_cr_sec ON course_results(section_id, term_id)",
        "CREATE INDEX IF NOT EXISTS ix_att_term ON fact_attendance(term_id, date)",
    ):
        con.execute(stmt)
