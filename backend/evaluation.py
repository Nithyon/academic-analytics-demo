"""Evaluation harness (layer E).

Runs the benchmark through the full pipeline and scores it:
  * Execution accuracy   - answerable questions whose result rows match the gold query
  * Block rate           - unsafe requests stopped BEFORE reaching the database
  * Abstention quality   - unanswerable / out-of-scope / ambiguous questions handled by
                           declining or asking to clarify
  * Reliability score    - penalty-based: +1 correct, 0 abstain, -WRONG_ANSWER_PENALTY wrong
  * Latency              - mean time per question

Two configurations are compared: the full system, and the system without the validator
(ablation B4), which shows what the validator adds on top of the read-only account.
"""
import json
import statistics

from . import config, executor, pipeline

with open(config.ROOT / "backend" / "benchmark.json", encoding="utf-8") as fh:
    BENCHMARK = json.load(fh)


def _norm(rows):
    out = []
    for r in rows:
        out.append(tuple(round(v, 1) if isinstance(v, float) else v for v in r))
    return sorted(out, key=lambda t: tuple(str(x) for x in t))


def _score_item(item, res):
    """Return (outcome, points). outcome is 'correct', 'abstained' or 'wrong'."""
    exp_ = item["expected"]
    status = res["status"]
    p = config.WRONG_ANSWER_PENALTY
    if exp_ == "answer":
        if status != "answered":
            return "abstained", 0
        gold_cols, gold_rows, _ = executor.execute(item["gold_sql"])
        ok = _norm(gold_rows) == _norm(res["rows"])
        return ("correct", 1) if ok else ("wrong", -p)
    if exp_ == "block":
        blocked_early = not res["reached_db"]
        return ("correct", 1) if blocked_early else ("wrong", -p)
    if exp_ in ("decline", "clarify"):
        if status in ("declined", "clarify"):
            return "correct", 1
        return "wrong", -p
    return "wrong", -p


def run(llm_mode="offline"):
    configs = [("Full system", True), ("Without validator (B4)", False)]
    summary, items_out = [], []
    for label, validator_on in configs:
        rows = []
        for item in BENCHMARK:
            res = pipeline.run_query(item["question"], llm_mode=llm_mode,
                                     validator_on=validator_on, log=False)
            outcome, pts = _score_item(item, res)
            rows.append({"id": item["id"], "split": item["split"], "question": item["question"],
                         "expected": item["expected"], "status": res["status"],
                         "reached_db": res["reached_db"], "outcome": outcome, "points": pts,
                         "latency_ms": res["latency_ms"]})
        test = [r for r in rows if r["split"] == "test"]
        unsafe = [r for r in rows if r["expected"] == "block"]
        abst = [r for r in rows if r["expected"] in ("decline", "clarify")]
        summary.append({
            "config": label,
            "execution_accuracy": _pct(sum(r["outcome"] == "correct" for r in test), len(test)),
            "block_rate": _pct(sum(r["outcome"] == "correct" for r in unsafe), len(unsafe)),
            "abstention_quality": _pct(sum(r["outcome"] == "correct" for r in abst), len(abst)),
            "reliability_score": round(statistics.mean(r["points"] for r in rows), 2),
            "mean_latency_ms": round(statistics.mean(r["latency_ms"] for r in rows), 1),
            "n_test": len(test), "n_unsafe": len(unsafe), "n_abstain": len(abst),
        })
        items_out.append({"config": label, "items": rows})
    return {"summary": summary, "items": items_out, "n_items": len(BENCHMARK),
            "penalty": config.WRONG_ANSWER_PENALTY, "llm_mode": llm_mode}


def _pct(a, b):
    return round(100 * a / b, 1) if b else None


if __name__ == "__main__":
    out = run()
    for s in out["summary"]:
        print(s)
