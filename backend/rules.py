"""Institution rules and every assumption behind the synthetic data (SRM-style).

The team did not confirm all of these values, so each one sits here, in one place, where
it can be corrected without touching the code. docs/data_card.md lists the same
assumptions for readers of the paper.

Values marked ASSUMPTION are placeholders that look like SRM practice but are NOT
official SRM figures.
"""
from datetime import date

INSTITUTION = "SRM-style synthetic institution (not real SRM data)"

# ----------------------------------------------------------------------------- roll numbers
# Format seen on a real SRM roll number: RA + YY + 11 + BBB + CC + NNNN (15 characters).
# Segment meaning is an ASSUMPTION: YY = admission year, 11 = degree (B.Tech),
# BBB = branch code, CC = campus, NNNN = serial.
ROLL_PREFIX = "RA"
ROLL_DEGREE = "11"
ROLL_CAMPUS = "99"          # deliberately NOT a real campus code, so no synthetic roll
ROLL_SERIAL_START = 9001    # number can ever match a real student's roll number

# ----------------------------------------------------------------------------- organisation
# (dept_code, dept_name, branch_code). Branch codes other than 003 are ASSUMPTIONS.
DEPARTMENTS = [
    ("CSE", "Computer Science and Engineering", "003"),
    ("ECE", "Electronics and Communication Engineering", "004"),
    ("EEE", "Electrical and Electronics Engineering", "005"),
    ("MATH", "Mathematics", None),          # service department: teaches, has no program
]
PROGRAMS = [  # (program_name, dept_code)
    ("B.Tech CSE", "CSE"),
    ("B.Tech ECE", "ECE"),
    ("B.Tech EEE", "EEE"),
]
BATCHES = [2023, 2024, 2025]        # admission years
SECTIONS_PER_PROGRAM = 2            # letters A, B for each program and batch
STUDENTS_PER_SECTION = (24, 32)     # uneven section sizes on purpose

# ----------------------------------------------------------------------------- terms
# term_name, academic year, semester type, first teaching day, last teaching day,
# end-semester exam window (no classes). Dates are ASSUMPTIONS.
TERMS = [
    ("2024-EVEN", "2024-25", "Even", date(2025, 1, 6), date(2025, 4, 25), (date(2025, 4, 28), date(2025, 5, 16))),
    ("2025-ODD", "2025-26", "Odd", date(2025, 7, 14), date(2025, 11, 7), (date(2025, 11, 10), date(2025, 11, 28))),
    ("2025-EVEN", "2025-26", "Even", date(2026, 1, 5), date(2026, 4, 24), (date(2026, 4, 27), date(2026, 5, 15))),
    ("2026-ODD", "2026-27", "Odd", date(2026, 7, 13), date(2026, 11, 6), (date(2026, 11, 9), date(2026, 11, 27))),
]
CURRENT_TERM = "2026-ODD"
LAST_TERM = "2025-EVEN"

HOLIDAYS = {  # ASSUMPTION: common Tamil Nadu / national holidays
    date(2025, 1, 14): "Pongal", date(2025, 1, 15): "Thiruvalluvar Day",
    date(2025, 1, 16): "Uzhavar Thirunal", date(2025, 1, 26): "Republic Day",
    date(2025, 3, 31): "Ramzan", date(2025, 4, 14): "Tamil New Year",
    date(2025, 4, 18): "Good Friday", date(2025, 8, 15): "Independence Day",
    date(2025, 8, 27): "Vinayakar Chathurthi", date(2025, 10, 1): "Ayudha Pooja",
    date(2025, 10, 2): "Gandhi Jayanti", date(2025, 10, 20): "Deepavali",
    date(2026, 1, 14): "Pongal", date(2026, 1, 15): "Thiruvalluvar Day",
    date(2026, 1, 16): "Uzhavar Thirunal", date(2026, 1, 26): "Republic Day",
    date(2026, 3, 20): "Ramzan", date(2026, 4, 3): "Good Friday",
    date(2026, 4, 14): "Tamil New Year", date(2026, 8, 15): "Independence Day",
    date(2026, 9, 14): "Vinayakar Chathurthi", date(2026, 10, 2): "Gandhi Jayanti",
    date(2026, 10, 19): "Ayudha Pooja", date(2026, 11, 8): "Deepavali",
}

PERIODS_PER_DAY = 7  # hours 1..7


def semester_no(batch, term_name):
    """Semester a batch is in during a term; 2024 batch is in semester 5 in 2026-ODD."""
    year, kind = term_name.split("-")
    n = (int(year) - batch) * 2 + (1 if kind == "ODD" else 2)
    return n if 1 <= n <= 8 else None


# ----------------------------------------------------------------------------- courses
# SRM-style course codes: 21 + dept letters + level + type letter
# (T theory, L lab, J integrated theory + lab). Catalogue is an ASSUMPTION.
# (code, name, dept_code, type, credits, semester, programs that take it, weekly hours)
COURSES = [
    # Mathematics service courses, shared by all three programs
    ("21MAB101T", "Calculus and Linear Algebra", "MATH", "T", 4, 1, ["CSE", "ECE", "EEE"], 4),
    ("21MAB102T", "Advanced Calculus and Complex Analysis", "MATH", "T", 4, 2, ["CSE", "ECE", "EEE"], 4),
    ("21MAB201T", "Transforms and Boundary Value Problems", "MATH", "T", 4, 3, ["CSE", "ECE", "EEE"], 4),
    ("21MAB204T", "Probability and Queueing Theory", "MATH", "T", 4, 4, ["CSE", "ECE", "EEE"], 4),
    # CSE
    ("21CSS101J", "Programming for Problem Solving", "CSE", "J", 4, 1, ["CSE"], 5),
    ("21CSC101T", "Object Oriented Design and Programming", "CSE", "T", 3, 2, ["CSE"], 3),
    ("21CSC102L", "Object Oriented Programming Lab", "CSE", "L", 2, 2, ["CSE"], 3),
    ("21CSC201J", "Data Structures and Algorithms", "CSE", "J", 4, 3, ["CSE"], 5),
    ("21CSC203L", "Advanced Programming Practice", "CSE", "L", 2, 3, ["CSE"], 3),
    ("21CSC204J", "Design and Analysis of Algorithms", "CSE", "J", 4, 4, ["CSE"], 5),
    ("21CSC205J", "Database Management Systems", "CSE", "J", 4, 4, ["CSE"], 5),
    ("21CSC301T", "Formal Language and Automata", "CSE", "T", 3, 5, ["CSE"], 3),
    ("21CSC302J", "Computer Networks", "CSE", "J", 4, 5, ["CSE"], 5),
    ("21CSC303J", "Software Engineering and Project Management", "CSE", "J", 4, 5, ["CSE"], 4),
    ("21CSC304L", "Machine Learning Lab", "CSE", "L", 2, 5, ["CSE"], 3),
    ("21CSC401T", "Compiler Design", "CSE", "T", 3, 6, ["CSE"], 3),
    ("21CSC402J", "Artificial Intelligence", "CSE", "J", 4, 6, ["CSE"], 5),
    ("21CSE403T", "Cloud Computing", "CSE", "T", 3, 7, ["CSE"], 3),
    ("21CSE404J", "Deep Learning Techniques", "CSE", "J", 4, 7, ["CSE"], 5),
    # ECE
    ("21ECS101J", "Basic Electronics", "ECE", "J", 4, 1, ["ECE"], 5),
    ("21ECC102T", "Electronic Devices", "ECE", "T", 3, 2, ["ECE"], 3),
    ("21ECC103L", "Electronic Devices Lab", "ECE", "L", 2, 2, ["ECE"], 3),
    ("21ECC201J", "Signals and Systems", "ECE", "J", 4, 3, ["ECE"], 5),
    ("21ECC202L", "Analog Circuits Lab", "ECE", "L", 2, 3, ["ECE"], 3),
    ("21ECC203J", "Digital Electronic Principles", "ECE", "J", 4, 4, ["ECE"], 5),
    ("21ECC204T", "Electromagnetic Theory", "ECE", "T", 3, 4, ["ECE"], 3),
    ("21ECC301J", "Digital Signal Processing", "ECE", "J", 4, 5, ["ECE"], 5),
    ("21ECC302T", "Communication Theory", "ECE", "T", 3, 5, ["ECE"], 3),
    ("21ECC303L", "Microprocessors Lab", "ECE", "L", 2, 5, ["ECE"], 3),
    ("21ECC401J", "VLSI Design", "ECE", "J", 4, 6, ["ECE"], 5),
    ("21ECC402T", "Wireless Communication", "ECE", "T", 3, 6, ["ECE"], 3),
    ("21ECE403T", "Embedded Systems", "ECE", "T", 3, 7, ["ECE"], 3),
    ("21ECE404J", "Internet of Things", "ECE", "J", 4, 7, ["ECE"], 5),
    # EEE
    ("21EES101J", "Basic Electrical Engineering", "EEE", "J", 4, 1, ["EEE"], 5),
    ("21EEC102T", "Electric Circuit Analysis", "EEE", "T", 3, 2, ["EEE"], 3),
    ("21EEC103L", "Electric Circuits Lab", "EEE", "L", 2, 2, ["EEE"], 3),
    ("21EEC201J", "Electrical Machines I", "EEE", "J", 4, 3, ["EEE"], 5),
    ("21EEC202T", "Electromagnetic Fields", "EEE", "T", 3, 3, ["EEE"], 3),
    ("21EEC203J", "Electrical Machines II", "EEE", "J", 4, 4, ["EEE"], 5),
    ("21EEC204L", "Control Systems Lab", "EEE", "L", 2, 4, ["EEE"], 3),
    ("21EEC301J", "Power Electronics", "EEE", "J", 4, 5, ["EEE"], 5),
    ("21EEC302T", "Power System Analysis", "EEE", "T", 3, 5, ["EEE"], 3),
    ("21EEC303L", "Power Electronics Lab", "EEE", "L", 2, 5, ["EEE"], 3),
    ("21EEC401J", "Electric Drives and Control", "EEE", "J", 4, 6, ["EEE"], 5),
    ("21EEC402T", "Protection and Switchgear", "EEE", "T", 3, 6, ["EEE"], 3),
    ("21EEE403T", "Renewable Energy Systems", "EEE", "T", 3, 7, ["EEE"], 3),
    ("21EEE404J", "Smart Grid Technology", "EEE", "J", 4, 7, ["EEE"], 5),
]

COURSE_TYPE_NAMES = {"T": "Theory", "L": "Lab", "J": "Integrated"}

# ----------------------------------------------------------------------------- marks
# For each course type: components, each with paper items. converted_max is what the
# component counts for in the 100-mark total. All weights are ASSUMPTIONS, except the
# integrated lab part, which follows what a student reported: a lab test on paper out of
# 25 (with a viva part) converted to 10, and five experiments converted to 15.
# (component_name, group, Internal/External, converted_max, [(item_name, paper_max, week)])
COMPONENTS = {
    "T": [
        ("CLA-1", "Theory", "Internal", 10, [("CLA-1", 50, 5)]),
        ("CLA-2", "Theory", "Internal", 15, [("CLA-2", 50, 10)]),
        ("CLA-3", "Theory", "Internal", 15, [("CLA-3", 50, 14)]),
        ("Assignment", "Assignment", "Internal", 10, [("Assignment 1", 10, 7), ("Assignment 2", 10, 12)]),
        ("Course completion", "Course completion", "Internal", 10, [("Course completion", 100, 15)]),
        ("End semester", "End semester", "External", 40, [("End semester exam", 100, None)]),
    ],
    "J": [
        ("CLA-1", "Theory", "Internal", 10, [("CLA-1", 50, 5)]),
        ("CLA-2", "Theory", "Internal", 10, [("CLA-2", 50, 10)]),
        ("Assignment", "Assignment", "Internal", 5, [("Assignment 1", 10, 8)]),
        ("Experiments", "Lab", "Internal", 15,
         [("Experiment 1", 10, 3), ("Experiment 2", 10, 5), ("Experiment 3", 10, 7),
          ("Experiment 4", 10, 9), ("Experiment 5", 10, 11)]),
        ("Lab test", "Lab", "Internal", 10, [("Lab test written", 20, 13), ("Lab test viva", 5, 13)]),
        ("Course completion", "Course completion", "Internal", 10, [("Course completion", 100, 15)]),
        ("End semester", "End semester", "External", 40, [("End semester exam", 100, None)]),
    ],
    "L": [
        ("Experiments", "Lab", "Internal", 30,
         [(f"Experiment {i}", 10, 2 + i) for i in range(1, 9)]),
        ("Lab test", "Lab", "Internal", 20, [("Lab test written", 20, 13), ("Lab test viva", 5, 13)]),
        ("Course completion", "Course completion", "Internal", 10, [("Course completion", 100, 15)]),
        ("End semester practical", "End semester", "External", 40, [("End semester practical exam", 100, None)]),
    ],
}

PASS_TOTAL = 50            # ASSUMPTION: total out of 100 needed to pass
PASS_EXTERNAL_PCT = 40     # ASSUMPTION: minimum % in the external component
GRADES = [  # (min total, grade, grade point): ASSUMPTION, commonly reported 10-point scale
    (91, "O", 10), (81, "A+", 9), (71, "A", 8), (61, "B+", 7), (56, "B", 6), (50, "C", 5), (0, "F", 0),
]
ATTENDANCE_THRESHOLD = 75   # minimum attendance %
ATTENDANCE_STATUSES = {"P": "Present", "A": "Absent", "OD": "On duty", "ML": "Medical leave"}
# Attendance % counts P and OD as attended; ML and A are not attended (ML is shown separately).
MIN_GROUP_SIZE = 5          # suppression threshold reported in the policy (not yet enforced)

ASSUMPTIONS_NOTE = (
    "Course catalogue, branch codes other than 003, component weights, pass rule, grade "
    "bands, term dates and holidays are assumptions modelled on SRM-style practice. They "
    "are not official SRM regulations."
)
