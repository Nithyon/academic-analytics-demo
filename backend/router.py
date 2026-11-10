"""Question router (layer B): answer, ask to clarify, or decline with a reason.

Runs before any SQL is generated, so questions outside the descriptive-analytics scope
never reach the model.
"""
import re

PREDICTION = re.compile(
    r"\b(will|predict|predicted|forecast|likely to|going to|expected to)\b|\bnext (term|semester|year)\b",
    re.I)

UNANSWERABLE = {
    "salary": "faculty salaries", "salaries": "faculty salaries", "fee": "fees", "fees": "fees",
    "hostel": "hostel records", "placement": "placements", "placements": "placements",
    "cgpa": "CGPA", "gpa": "GPA", "weather": "the weather", "library": "library usage",
    "scholarship": "scholarships", "timetable": "timetables",
}
SENSITIVE = re.compile(r"\b(religion|caste|income|medical|health|disability|phone|address)\b", re.I)

WRITE_WORDS = re.compile(r"\b(drop|delete|truncate|update|insert|alter|wipe|erase)\b|;", re.I)

SCORE_WORDS = re.compile(r"\b(marks?|scores?|grades?|performance|results?)\b", re.I)
ATTENDANCE_WORD = re.compile(r"\battendance\b", re.I)
GROUPING = re.compile(
    r"\b(per|by|each|every|for|in|across|over|course|courses|section|sections|term|terms|"
    r"semester|type|types|student|students|program|programs|programme|trend|changed|overall|"
    r"quiz|mid-?term|end-?sem\w*|pass|band|below|under|above|top|lowest|highest|names?)\b|"
    r"\b[a-z]{2}\s?\d{4}\b", re.I)


def route(question: str) -> dict:
    q = question.strip()
    if not q:
        return {"decision": "clarify", "reason": "Please type a question.", "options": []}

    if PREDICTION.search(q):
        return {"decision": "decline",
                "reason": "Prediction about individual students is outside the "
                          "descriptive-analytics scope. Ask about what has already happened.",
                "options": []}

    m = SENSITIVE.search(q)
    if m:
        return {"decision": "decline",
                "reason": f"The system does not hold or reveal personal data such as "
                          f"'{m.group(1).lower()}'.",
                "options": []}

    for word in re.findall(r"[a-z]+", q.lower()):
        if word in UNANSWERABLE:
            return {"decision": "decline",
                    "reason": f"The database holds attendance and assessment data only; it has "
                              f"no information on {UNANSWERABLE[word]}.",
                    "options": []}

    if WRITE_WORDS.search(q):
        # The router does not try to judge safety: the request goes on to the model and the
        # validator outside the model decides. This is what the "Blocked" demo shows.
        return {"decision": "answer", "reason": "Routed to SQL generation; safety is enforced by "
                                                "the validator, not the router.", "options": []}

    if SCORE_WORDS.search(q) and not GROUPING.search(q):
        return {"decision": "clarify",
                "reason": "“Average marks” could mean per course, per section, per term or per "
                          "assessment type, and each gives a different answer. Which one?",
                "options": ["What are the average marks per course this term?",
                            "What are the average marks per section this term?",
                            "How have average marks changed across terms?",
                            "What is the average score per assessment type this term?"]}

    if ATTENDANCE_WORD.search(q) and not GROUPING.search(q):
        return {"decision": "clarify",
                "reason": "Attendance for which grouping? Pick one of these.",
                "options": ["Average attendance per course this term?",
                            "Average attendance per section this term?",
                            "How has attendance changed across terms?"]}

    return {"decision": "answer", "reason": "In scope: descriptive question about attendance or "
                                            "assessment.", "options": []}
