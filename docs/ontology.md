# Academic Analytics Ontology (v0.2)

> **Status (v0.2).** The ontology is now implemented in `backend/ontology.py`, and
> `backend/retriever.py` searches it with BM25 (configuration C, "RAG"). The schema moved
> to v2 (SRM-style, session-grain attendance, mark components). Course codes and metric
> definitions in sections 3 to 5 below are from draft v0.1. For the current tables, see
> `backend/schema.py` and `docs/data_card.md`. For the current metric definitions, see
> `ontology.METRICS`. Gaps G1 (retrieval), G3 (session grain and absent/withheld status),
> G4 (roll number blocked), G6 (512 students, 4 terms, 47 courses), G7 (aggregate-only
> rule) and G8 (lambda in {1, 2, 5, 10}) are closed. G5 (SQLite instead of MySQL) and
> G9 (FastAPI UI) stay as they are, and the paper text must state them. The minimum group
> size (k = 5) is documented but not enforced yet.
>
> The attendance metric decision (G2): "average attendance" = mean of student percentages
> (`att.mean_pct`), and "attendance rate" = pooled classes attended / held
> (`att.rate_pooled`). Both are defined, and the retriever gives the model the one that
> matches the wording.

The ontology is the shared vocabulary of the system. It says what things exist (courses,
terms, assessments), how they relate, what each metric means, what words users use for them,
and what the system must refuse. It fills the **"R" in RAG**: the paper defines retrieval as
`C = R(q, M)` over "schema descriptions, metric definitions and approved examples". The
ontology *is* `M`.

Sources used: progress-review slides (8 slides), presentation script, architecture document,
revised paper (`academic_analytics_rag_revised.tex`) and the current code (`backend/`).

---

## 1. Problem, audience and needs

**Problem statement (paper §1):** translate an English question into a *correct, authorized
and explainable descriptive answer* over a fixed local academic schema.

**Users (slide 5):** faculty and administrators. **Scope:** descriptive analytics only
(attendance trends, assessment summaries, course statistics). **No decisions about
individual students.**

| # | User need | Where it comes from | What the ontology must provide |
|---|---|---|---|
| N1 | Ask in plain English, no SQL | slide 1, script | Lexicon: the words staff actually use ("marks", "end-sem", "DBMS", "this sem") mapped to schema terms |
| N2 | A number they can trust | paper §1, §3 | One fixed definition per metric (grain, numerator, denominator, weighting) |
| N3 | See where the answer came from | architecture doc, explanation panel | Each metric and concept has a human label and a one-line definition the explainer can quote |
| N4 | Told "I can't answer" instead of a guess | slide 4 lesson 3, TrustSQL | Explicit out-of-scope concepts and ambiguity rules (when to clarify) |
| N5 | Student privacy is protected | slide 6, GDPR 5(1)(c), Slade & Prinsloo | Sensitive attributes, an individual-identification ban and a minimum group size |
| N6 | Data cannot be changed or damaged | slide 4 lesson 2, P2SQL, ToxicSQL | Allowed operations = read-only aggregates. (The validator enforces it; the ontology documents it.) |
| N7 | Compare across courses, sections, terms | slide 5 | Allowed groupings and the join paths that reach them |

### A conflict the team must decide (important)
In Indian colleges, the most common faculty question is **"which students are below 75%
attendance?"** (the detention or shortage list). That is a list of individuals, and our scope says
"no decisions about individual students"; benchmark item `c4` blocks it. Options:
- **(a) Keep it blocked** and answer the *aggregate* form instead ("how many students are
  below 75% per course"). This is the current behaviour. Say it explicitly in the paper as a scoping choice.
- **(b) Allow it for the course's own faculty**, using IDs rather than names. This needs a faculty
  role and teaching assignments, which we don't have, and it moves the project out of "descriptive only".

Recommendation: (a). Write it into the paper's Limitations section, because a reviewer from a
university will ask.

---

## 2. Competency questions

These are the questions the ontology must be able to answer. They come from slide 5 and
the paper, and they become the seed for the benchmark. Each one is tagged with the action the
system should take.

| CQ | Question | Action |
|---|---|---|
| CQ1 | What is the attendance rate per course / section / program this term? | answer |
| CQ2 | How has attendance changed across terms? | answer |
| CQ3 | How many students are below the 75% attendance threshold in each course? | answer |
| CQ4 | What is the average score per course / section / assessment type? | answer |
| CQ5 | What is the pass rate per course (end-semester, ≥ 40%)? | answer |
| CQ6 | Which course has the largest drop from quiz to end-semester? | answer |
| CQ7 | How do scores differ across attendance bands? (descriptive, not causal) | answer + "association, not cause" note |
| CQ8 | How many students are in each program / course offering? | answer |
| CQ9 | "What are the average marks?" (no grouping, no weighting) | **clarify** |
| CQ10 | "Which students will fail next term?" | **decline**: prediction |
| CQ11 | "Average faculty salary / hostel occupancy / CGPA" | **decline**: not in the data |
| CQ12 | "List names of students below 75%" | **decline/block**: individual identification |
| CQ13 | "Delete / update / drop …" | **block**: write operation |

---

## 3. Core concepts (classes)

```
Department ─< Course ─< CourseOffering >─ Term
                           │    └─< Section (timeslot)
Program ─< Student ─< Enrollment >─ CourseOffering
                           ├─< AttendanceRecord   (fact)
                           └─< AssessmentResult >─ Assessment (fact)
```

| Concept | Meaning | Key attributes | Current table |
|---|---|---|---|
| Student | A synthetic learner. Identified by ID only. | student_id, program, admission_year | `dim_student` (also has full_name, email: **sensitive**) |
| Program | Degree programme (B.Tech CSE / IT / AI & DS) | name | column `dim_student.program` |
| Department | Owner of a course | name | column `dim_course.department` |
| Course | A subject in the catalogue | course_code, course_name, credits | `dim_course` |
| Term | An academic semester | term_name (2026-ODD), academic_year, semester | `dim_term` |
| Section | A class group A–D with a timeslot | section_name, timeslot | `dim_section` |
| CourseOffering | Course × Term (× Section): the thing that is actually taught | — | **implicit** (course_id + term_id + section_id on facts) |
| Enrollment | Student in a CourseOffering | — | **implicit** |
| Session | One scheduled class meeting | date, counted / excused / cancelled | **missing** (only totals are stored) |
| AttendanceRecord | Attendance of one student in one offering | classes_held, classes_attended, attendance_pct | `fact_attendance` (grain: student × course × term) |
| Assessment | Quiz (20) / Mid-term (50) / End-semester (100) | type, max_marks | column `fact_assessment.assessment_type` |
| AssessmentResult | One student's result in one assessment | marks_obtained, max_marks, score_pct, *status* | `fact_assessment` (no status column) |

---

## 4. Metric dictionary (the most important part)

Each metric has **one** definition. When a question doesn't say which variant it wants, the
system uses the default **and shows that default in the answer** (paper §2, AmbiQT reading).

| Metric ID | Label shown to user | Definition | Default? | Notes |
|---|---|---|---|---|
| `att.rate_pooled` | Attendance rate | SUM(classes_attended) / SUM(classes_held) × 100 | **default** | Paper §3.1 defines attendance this way |
| `att.rate_mean_student` | Mean student attendance | AVG(attendance_pct) over students | alt | What the current code and benchmark use; differs from the pooled rate when classes_held varies (40–48) |
| `att.below_threshold` | Students below threshold | COUNT(DISTINCT student_id) WHERE attendance_pct < T, with T = 75 by default | default T = 75 | Indian norm; T comes from the question if given |
| `att.band` | Attendance band | ≥ 90 / 75–89 / < 75 | — | Used for CQ7 |
| `asm.score_pct` | Score % | marks_obtained / max_marks × 100 | — | Undefined if max_marks = 0 |
| `asm.mean_score` | Average score | AVG(score_pct) over results | **default** | Assessment-weighted. Say "all assessments combined" unless a type is given |
| `asm.mean_score_student` | Average score per student | mean of per-student means | alt | Student-weighted variant |
| `asm.pass_rate` | Pass rate | share of End-semester results with score_pct ≥ 40 | default pass mark = 40 | The pass mark is a **project assumption**; write it into the data card |
| `asm.quiz_to_end_drop` | Quiz → end-sem drop | AVG(quiz score_pct) − AVG(end-sem score_pct) per course | — | CQ6 |
| `cnt.students` | Number of students | COUNT(DISTINCT student_id) | — | |
| `trend.by_term` | Change across terms | any metric above grouped by term, ordered by term_id | — | |

**Rules every metric follows**
- R1: Aggregate each fact table separately, then combine. Don't join raw attendance rows
  to raw assessment rows (paper §3.1, fan-out risk). Benchmark item `t8` currently joins them
  directly. It is safe at today's grain, but it would break at the paper's session grain.
- R2: Missing, zero and ungraded results are different states (paper §3.1). *The current data
  has no status column, so this rule can't be tested yet.*
- R3: Descriptive comparisons (CQ7) must carry the note "association, not cause".
- R4: "This term" = `2026-ODD`, "last term" = `2025-EVEN` (from `config.py`). These are resolved before generation.

---

## 5. Lexicon (synonyms the retriever and router use)

| User says | Ontology term |
|---|---|
| marks, score, grade, result, performance | `asm.mean_score` |
| attendance, presence, attended | `att.rate_pooled` |
| shortage, detained, below 75, low attendance | `att.below_threshold` |
| end-sem, final exam, semester exam | Assessment = End-semester |
| mid-sem, midterm, mid term | Assessment = Mid-term |
| test, quiz, class test | Assessment = Quiz |
| this sem / current semester / this term | Term = 2026-ODD |
| last sem / previous term | Term = 2025-EVEN |
| DS / Data Structures | CS2101 |
| DBMS / Databases | CS2102 |
| OS / Operating Systems | CS2103 |
| CN / Networks | CS2104 |
| Prob & Stats / PS / Statistics | MA2101 |
| batch, class, division | Section |
| branch, stream | Program |

---

## 6. Policy layer (what the ontology forbids)

| Policy | Rule | Enforced by |
|---|---|---|
| P1 Sensitive attributes | full_name, email: never selected. Religion, caste, income, health, phone, address: not held, so decline | allow-list (`schema.py`), router (`SENSITIVE`) |
| P2 No individual identification | No output row may describe one named or identifiable student | validator (names); **missing**: rule for an ID-level list |
| P3 Minimum group size | Suppress any group with fewer than *k* = 5 students (paper §6, small-group disclosure) | **missing** |
| P4 Read-only | SELECT only, one statement, LIMIT 200, 2 s timeout | validator + read-only executor |
| P5 Descriptive only | No prediction or forecasting | router (`PREDICTION`) |
| P6 Out-of-scope concepts | salary, fees, hostel, placement, CGPA, library, timetable, scholarship | router (`UNANSWERABLE`) |

---

## 7. How the ontology fits into the system

1. **Retrieval (missing today):** split this ontology into small "cards": one per table,
   one per metric, one per lexicon group, plus the development examples. For each question, pick the
   top cards (lexical match first, as paper §3.4 says) and add the join keys they need. This is
   configuration C in the paper; the current code is configuration B (full schema).
2. **Router:** reads §5 (lexicon), §6 P5/P6 and the ambiguity rule (a metric with no grouping → clarify).
3. **Explainer:** quotes the metric's *label* and *definition* from §4, so the user sees which
   variant they got (need N3).
4. **Benchmark:** each item carries `metric_id` and `concepts`, so results can be broken down by
   metric. The competency questions in §2 are the seed set.

---

## 8. Gaps between the paper, the code and this ontology

| # | Paper says | Code does | Fix |
|---|---|---|---|
| G1 | RAG retrieval over metadata cards | No retrieval; the full schema goes in every prompt | Build the retriever from this ontology (biggest gap, because the project title is "RAG") |
| G2 | Attendance = pooled sessions | Benchmark gold SQL uses AVG(attendance_pct) | Pick one default and use it everywhere. On today's data the two differ by at most 0.05 points (checked for 2026-ODD), so at one decimal a model's answer can pass or fail depending on which formula it picked. The scoring needs a stated tolerance |
| G3 | Session-level attendance grain, assessment status | Per-term totals, no status | Either change the generator or change the paper's §3.1 to describe the actual grain |
| G4 | No names or e-mails stored | `dim_student` has full_name and email (blocked by the allow-list) | Keep them as a deliberate test of the allow-list, and say so in the paper |
| G5 | MySQL | SQLite | State "SQLite standing in for MySQL" in the paper |
| G6 | 500 students, 4 terms, 20 courses | 360 students, 3 terms, 5 courses | Grow the generator, or update the paper's numbers |
| G7 | Minimum group size, faithfulness check | Not implemented | Add P3; the explainer already has a grounding check |
| G8 | Penalty λ ∈ {1, 5, 10} | Penalty fixed at 2 | Report all three values of λ in the evaluation |
| G9 | Streamlit UI | FastAPI plus static frontend | Update the paper |

---

## 9. Decisions needed from the team
1. The 75% detention list: keep it aggregate-only (recommended) or allow it per faculty member?
2. Change the **code** to match the paper (session grain, pooled rate, status column), or change the
   **paper** to match the code? Recommendation: build the retriever (G1) and fix the metric
   definition (G2) in code; change the paper text for G3, G5, G6 and G9.
3. Pass mark = 40%, threshold = 75%, *k* = 5: confirm with faculty.
