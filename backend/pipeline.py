"""The request pipeline: question -> router -> retriever -> model -> validator -> (retry once)
-> read-only executor -> explanation -> response, with every decision written to the audit log.

Each step is also recorded in a `trace`, which the frontend uses to light up the matching
box in the architecture diagram, and in `timings` (ms per stage) for the evaluation.
"""
import time
import uuid

from . import audit, executor, explainer, llm, retriever, router, validator


class Trace:
    def __init__(self):
        self.steps = []
        self.t0 = time.perf_counter()

    def add(self, node, label, status="ok", detail=""):
        self.steps.append({"node": node, "label": label, "status": status, "detail": detail,
                           "t_ms": round((time.perf_counter() - self.t0) * 1000, 1)})


def run_query(question, llm_mode="offline", compromised=False, validator_on=True, log=True,
              prompt_mode="rag", model=None, max_attempts=2):
    t0 = time.perf_counter()
    rid = uuid.uuid4().hex[:8]
    tr = Trace()
    timings = {"router": 0.0, "retrieval": 0.0, "generation": 0.0, "validation": 0.0,
               "execution": 0.0, "explanation": 0.0}
    res = {"request_id": rid, "question": question, "status": None, "reason": None,
           "route": None, "attempts": [], "final_sql": None, "columns": [], "rows": [],
           "explanation": None, "model": None, "validator_on": validator_on,
           "prompt_mode": prompt_mode, "reached_db": False, "notes": [], "fallback": False,
           "timings": timings, "tokens": [], "retrieved": None}

    tr.add("user", "Faculty member asks a question", detail=question)
    tr.add("ui", "Web app sends HTTP POST /api/query")
    tr.add("api", f"FastAPI opens request {rid}")

    # ---------------- router
    s = time.perf_counter()
    r = router.route(question)
    timings["router"] = (time.perf_counter() - s) * 1000
    res["route"] = r
    if r["decision"] != "answer":
        status = "declined" if r["decision"] == "decline" else "clarify"
        tr.add("router", "Router: decline" if status == "declined" else "Router: ask to clarify",
               "stop" if status == "declined" else "warn", r["reason"])
        res["status"], res["reason"] = status, r["reason"]
        tr.add("panel", "Reason shown to the user; no SQL generated")
        return _finish(res, tr, t0, log)
    tr.add("router", "Router: answerable, send to SQL generation", detail=r["reason"])

    # ---------------- retrieval
    s = time.perf_counter()
    ret = retriever.retrieve(question, mode=prompt_mode)
    timings["retrieval"] = (time.perf_counter() - s) * 1000
    res["retrieved"] = {"mode": prompt_mode, "cards": ret.get("cards"), "tables": ret.get("tables"),
                        "links": ret.get("links", []), "examples": ret.get("example_ids", []),
                        "context_chars": len(ret["context"])}
    tr.add("metadata", f"Retrieved context ({prompt_mode}): {len(ret.get('tables', []))} tables, "
           f"{len(ret.get('cards') or [])} ontology cards", detail=", ".join(ret.get("cards") or []))

    # ---------------- generate -> validate, with one retry
    error = None
    passed = None
    for attempt in range(1, max_attempts + 1):
        gen = llm.generate(question, ret, attempt=attempt, error=error, mode=llm_mode,
                           compromised=compromised, model=model)
        timings["generation"] += gen["gen_ms"]
        res["model"] = gen["model"]
        res["fallback"] = res["fallback"] or gen["fallback"]
        if gen["tokens"]:
            res["tokens"].append(gen["tokens"])
        if gen["note"]:
            res["notes"].append(gen["note"])
        entry = {"attempt": attempt, "sql": gen["sql"], "validation": None}
        res["attempts"].append(entry)

        if gen["sql"] is None:
            tr.add("llm", f"Model: cannot answer from this schema (attempt {attempt})", "warn")
            res["status"] = "declined"
            res["reason"] = ("The question cannot be answered from the attendance and marks "
                             "data, so the system abstains instead of guessing.")
            tr.add("reject", "Abstain with a clear reason", "stop", res["reason"])
            tr.add("panel", "Reason shown to the user")
            return _finish(res, tr, t0, log)

        tr.add("llm", f"Model proposes candidate SQL (attempt {attempt})", detail=gen["sql"])

        if not validator_on:
            tr.add("validator", "Validator switched OFF (ablation)", "warn",
                   "SQL goes straight to the database.")
            passed = {"final_sql": gen["sql"], "tables": [], "columns": []}
            break

        s = time.perf_counter()
        v = validator.validate(gen["sql"])
        timings["validation"] += (time.perf_counter() - s) * 1000
        entry["validation"] = v
        if v["passed"]:
            tr.add("validator", "Validator: all 5 checks passed", detail=v["checks"][4]["detail"])
            tr.add("gate", "Passes? Yes")
            passed = v
            break
        tr.add("validator", f"Validator: rule {v['failed_rule']} failed", "fail", v["reason"])
        tr.add("gate", "Passes? No", "fail")
        error = v["reason"]
        if attempt < max_attempts:
            tr.add("reject", "Rejected: retry once with the error", "warn", v["reason"])
        else:
            tr.add("reject", "Rejected: abstain with the reason", "stop", v["reason"])

    if passed is None:
        res["status"] = "blocked"
        res["reason"] = f"Blocked by the validator: {error} The query never reached the database."
        tr.add("panel", "Block reason shown to the user")
        return _finish(res, tr, t0, log)

    if len(res["attempts"]) > 1 and validator_on:
        res["notes"].append("The first SQL was rejected; the model's revised query passed.")

    # ---------------- execute (read-only)
    sql = passed["final_sql"]
    res["final_sql"] = sql
    res["reached_db"] = True
    s = time.perf_counter()
    try:
        cols, rows, ms = executor.execute(sql)
    except executor.ExecutionError as exc:
        timings["execution"] = (time.perf_counter() - s) * 1000
        tr.add("executor", "Read-only executor: the database refused", "fail", str(exc))
        tr.add("db", "Star schema unchanged (read-only connection)", "ok")
        res["status"] = "error"
        res["reason"] = str(exc)
        if not validator_on:
            res["reason"] += (" Without the validator the SQL reached the database; only the "
                              "read-only account stopped any change.")
        tr.add("panel", "Error shown to the user", "fail")
        return _finish(res, tr, t0, log)
    timings["execution"] = (time.perf_counter() - s) * 1000
    tr.add("executor", f"Read-only executor ran the query in {ms:.1f} ms",
           detail=f"{len(rows)} rows returned")
    tr.add("db", "Star schema queried (read-only connection)")
    res["columns"], res["rows"] = cols, rows

    # ---------------- explain
    s = time.perf_counter()
    ex = explainer.explain(sql, cols, rows, passed.get("tables") or [], passed.get("columns") or [],
                           ret.get("cards") or [])
    timings["explanation"] = (time.perf_counter() - s) * 1000
    res["explanation"] = ex
    g = ex["grounding"]
    tr.add("explainer", "Explanation generated; grounding check "
           + ("passed" if g["passed"] else "FAILED"), "ok" if g["passed"] else "warn", ex["summary"])
    tr.add("panel", "Answer, SQL and explanation shown")
    res["status"] = "answered"
    if not validator_on and any(c in sql.lower() for c in ("full_name", "email", "roll_no")):
        res["notes"].append("Personal data was returned because the validator was off.")
    return _finish(res, tr, t0, log)


def _finish(res, tr, t0, log):
    res["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if log:
        res["audit_id"] = audit.log(res)
        tr.add("audit", f"Decision logged to the audit log (entry #{res['audit_id']})")
    res["trace"] = tr.steps
    return res
