# Data card: synthetic SRM-style academic data (v2)

## Purpose

This data lets us build and test the academic analytics system without real student records. Every record is synthetic, and no real student, name or roll number is present.

## How to build it

```
python -m backend.data_generator --seed 7
```

The same seed always produces the same database. The evaluation also uses seeds 11 and 23 as extra fixture databases. Each fixture has the same course catalogue but different records, so a query that is only right by chance on one database fails on another.

## What is in it (seed 7)

| Item | Value |
|---|---|
| Departments | CSE, ECE, EEE, MATH (MATH is a service department with no program) |
| Programs | B.Tech CSE, B.Tech ECE, B.Tech EEE |
| Batches (admission years) | 2023, 2024, 2025 |
| Sections | 18 (2 per program per batch, for example `CSE-2024-A`), 24 to 32 students each |
| Students | 512 |
| Courses | 47, with SRM-style codes (T theory, L lab, J integrated) |
| Terms | 2024-EVEN, 2025-ODD, 2025-EVEN, 2026-ODD (current) |
| Attendance rows | 315,967 (one per student per class session) |
| Assessment rows | 50,674 (one per student per paper item) |

The summary tables `attendance_summary`, `component_scores` and `course_results` are derived from the two fact tables by `backend/summaries.py`.

## Identifiers

Roll numbers follow the 15-character pattern of a real SRM roll number (`RA` + year + `11` + branch + campus + serial). The campus code is set to `99` and the serials start at 9001, so a synthetic roll number cannot match a real student. Names use common Telugu (surname first), Tamil (name and initial) and North Indian patterns, in lowercase. Roll numbers, names and e-mails are kept off the allow-list. The system never shows them.

## Planted patterns

These patterns are known in advance. A correct system must find them.

- The 2025-EVEN term has lower attendance than the other terms.
- The EEE department and the sections `EEE-2024-B` and `CSE-2025-B` have lower attendance.
- Attendance is lower on Mondays and Fridays and in periods 1 and 7. It also falls slowly across the weeks of a term.
- Mathematics courses have lower marks.
- Marks rise with attendance. This is an association only, not a cause.
- About 8 percent of first-semester students join one to four weeks late. Their classes are counted from the day they join.
- Some results are messy on purpose. About 2 percent of items are absent, a small number are withheld, about 10 percent of course-completion items score 0, and students with attendance below 65 percent often miss the end-semester exam.

## Rules and assumptions

Every rule is in `backend/rules.py`, so you can change a rule without changing code. Values marked ASSUMPTION are not official SRM regulations.

| Rule | Value | Status |
|---|---|---|
| Roll-number segment meaning | YY = year, 11 = degree, BBB = branch, CC = campus | Assumption |
| Branch codes | CSE 003 (seen on a real roll number). ECE 004 and EEE 005 are placeholders | Partly assumed |
| Theory course (T) | CLA-1 50 to 10, CLA-2 50 to 15, CLA-3 50 to 15, 2 assignments to 10, course completion to 10, end-semester 100 to 40 | Assumption |
| Integrated course (J) | CLA-1 to 10, CLA-2 to 10, assignment to 5, five experiments to 15, lab test (written 20 + viva 5 = 25) to 10, course completion to 10, end-semester to 40 | The lab part follows a student's report. The rest is assumed |
| Lab course (L) | 8 experiments to 30, lab test to 20, course completion to 10, end-semester practical to 40 | Assumption |
| Conversion | converted = paper obtained / paper maximum x converted maximum. Absent counts as 0 | Assumption |
| Pass | total of at least 50, and at least 40 percent of the external maximum | Assumption |
| Grades | O at least 91, A+ at least 81, A at least 71, B+ at least 61, B at least 56, C at least 50, F below 50 | Commonly reported SRM bands, not verified |
| Attendance | (P + OD) / classes held x 100. ML is shown separately. The threshold is 75 percent | Assumption |
| Calendar | Odd term from mid-July to early November, even term from early January to late April, then a 3-week exam window | Assumption |
| Holidays | Pongal, Deepavali, Ayudha Pooja, national holidays and others (see `rules.HOLIDAYS`) | Approximate dates |

## Limitations

- Every distribution is invented. The results show how the system behaves on data with this shape. They do not show real SRM patterns.
- The course catalogue and the weights are plausible, but they are not the official curriculum.
- Faculty, timetables, fees, CGPA and personal attributes are not modelled. The system declines questions about them.

## Real-data check (planned)

The OULAD dataset (Open University, CC-BY 4.0) is downloaded to `../datasets/oulad/raw/`. We can use it as a second, real but anonymised dataset to check that the results generalise.
