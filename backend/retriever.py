"""Retriever R(q, M): picks the ontology cards, tables, entity values and worked examples
that a question needs, and builds the prompt context for the three prompt modes.

  * minimal  - table and column names only (configuration A)
  * full     - every table with descriptions, every metric, the full value catalogue and
               fixed examples (configuration B, schema-grounded generation)
  * rag      - retrieved tables, metrics, concepts, linked values and the most similar
               development examples (configuration C, retrieval-augmented)

Lexical BM25 ranking, as the paper specifies; no embeddings. Only development-split
questions enter the example pool.
"""
import json
import math
import re
import time
from collections import Counter

from . import config, ontology
from .schema import TABLES, schema_prompt

STOP = set("a an the of in for to and or by per each is are was were what which how many much "
           "show me give list this that with on at as be do does from all our their there".split())
TOP_METRICS, TOP_CONCEPTS, TOP_EXAMPLES = 3, 2, 3


def tokens(text):
    out = []
    for w in re.findall(r"[a-z0-9+%-]+", text.lower()):
        if w in STOP:
            continue
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        out.append(w)
    return out


class BM25:
    def __init__(self, docs, k1=1.4, b=0.75):
        self.docs = [tokens(d) for d in docs]
        self.k1, self.b = k1, b
        self.avg = sum(map(len, self.docs)) / max(1, len(self.docs))
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def scores(self, query):
        q = tokens(query)
        out = []
        for d, tf in zip(self.docs, self.tf):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
            out.append(s)
        return out


_CARDS = ontology.static_cards()
_METRIC_CARDS = [c for c in _CARDS if c["kind"] == "metric"]
_CONCEPT_CARDS = [c for c in _CARDS if c["kind"] == "concept"]
_TABLE_CARDS = [c for c in _CARDS if c["kind"] == "table"]
_BM_METRIC = BM25([c["text"] for c in _METRIC_CARDS])
_BM_CONCEPT = BM25([c["text"] for c in _CONCEPT_CARDS])
_BM_TABLE = BM25([c["text"] for c in _TABLE_CARDS])

_DEV = None


def dev_examples():
    global _DEV
    if _DEV is None:
        with open(config.ROOT / "backend" / "benchmark.json", encoding="utf-8") as fh:
            items = json.load(fh)
        _DEV = [i for i in items if i["split"] == "dev" and i.get("gold_sql")]
        _DEV_BM[0] = BM25([i["question"] for i in _DEV]) if _DEV else None
    return _DEV


_DEV_BM = [None]


def _top(scores, k, min_score=0.5, ratio=0.6):
    """Top-k items above an absolute floor and within `ratio` of the best score."""
    ranked = sorted(range(len(scores)), key=lambda i: -scores[i])
    if not ranked:
        return []
    best = scores[ranked[0]]
    return [i for i in ranked[:k] if scores[i] >= min_score and scores[i] >= ratio * best]


def retrieve(question, mode="rag", db_path=None):
    """Return {'context': prompt text, 'cards': [...ids], 'tables': [...], 'examples': [...], 'ms'}."""
    t0 = time.perf_counter()
    if mode == "minimal":
        ctx = "Tables (allow-listed columns only):\n" + schema_prompt(with_descriptions=False)
        return {"context": ctx, "cards": [], "tables": list(TABLES), "examples": [],
                "ms": (time.perf_counter() - t0) * 1000}
    examples = dev_examples()
    if mode == "full":
        ctx = ("Schema:\n" + schema_prompt() + "\n\nMetric definitions:\n"
               + "\n".join(ontology.metric_text(m) for m in ontology.METRICS)
               + "\n\nRules:\n" + "\n".join(ontology.concept_text(c) for c in ontology.CONCEPTS)
               + "\n\nValues in the database:\n" + ontology.catalogue_text(db_path))
        ex = examples[:TOP_EXAMPLES]
        return {"context": ctx, "cards": ["all"], "tables": list(TABLES),
                "examples": [(e["question"], e["gold_sql"]) for e in ex], "example_ids": [e["id"] for e in ex],
                "ms": (time.perf_counter() - t0) * 1000}

    # ---- rag
    mi = _top(_BM_METRIC.scores(question), TOP_METRICS)
    ci = _top(_BM_CONCEPT.scores(question), TOP_CONCEPTS)
    ti = _top(_BM_TABLE.scores(question), 2, min_score=1.5)
    metrics = [_METRIC_CARDS[i] for i in mi]
    concepts = [_CONCEPT_CARDS[i] for i in ci]
    links = ontology.link_entities(question, db_path)
    needed = []
    for c in metrics + concepts:
        needed += c.get("tables", [])
    needed += [_TABLE_CARDS[i]["table"] for i in ti]
    kinds = {k for k, _ in links}
    if "course" in kinds or "department" in kinds:
        needed.append("dim_course")
    if "department" in kinds:
        needed += ["dim_department", "dim_section", "dim_program"]
    if "section" in kinds or "batch" in kinds:
        needed.append("dim_section")
    needed.append("dim_term")  # almost every question filters or groups by term
    if not any(t in ("attendance_summary", "component_scores", "course_results", "fact_attendance",
                     "fact_assessment", "dim_student") for t in needed):
        needed += ["attendance_summary", "course_results"]
    tables = list(dict.fromkeys(t for t in needed if t in TABLES))
    ex = []
    if examples and _DEV_BM[0] is not None:
        ex = [examples[i] for i in _top(_DEV_BM[0].scores(question), TOP_EXAMPLES, min_score=0.1)]
    ctx = "Relevant tables:\n" + schema_prompt(tables)
    if metrics:
        ctx += "\n\nMetric definitions:\n" + "\n".join(ontology.metric_text(c["card"]) for c in metrics)
    rules_txt = [ontology.concept_text(c["card"]) for c in concepts]
    privacy = next(c for c in ontology.CONCEPTS if c["id"] == "c.privacy")
    if privacy["id"] not in [c["id"] for c in concepts]:
        rules_txt.append(ontology.concept_text(privacy))
    term_rule = next(c for c in ontology.CONCEPTS if c["id"] == "c.term")
    if term_rule["id"] not in [c["id"] for c in concepts]:
        rules_txt.append(ontology.concept_text(term_rule))
    ctx += "\n\nRules:\n" + "\n".join(rules_txt)
    if links:
        ctx += "\n\nValues mentioned in the question:\n" + "\n".join(f"- {t}" for _k, t in links)
    return {"context": ctx, "cards": [c["id"] for c in metrics + concepts], "tables": tables,
            "links": [t for _k, t in links],
            "examples": [(e["question"], e["gold_sql"]) for e in ex], "example_ids": [e["id"] for e in ex],
            "ms": (time.perf_counter() - t0) * 1000}
