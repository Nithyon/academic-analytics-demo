"""FastAPI backend (layer B: orchestrator). Serves the API and the HTML/CSS frontend.

Start it with:   python run.py
or:              uvicorn backend.main:app --reload
then open        http://127.0.0.1:8000
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import audit, config, data_generator, evaluation, excel_io, llm, pipeline
from .schema import schema_metadata



@asynccontextmanager
async def lifespan(_app):
    # Build the synthetic star schema on first start
    if not config.DB_PATH.exists():
        data_generator.build(config.DEFAULT_SEED)
    yield


app = FastAPI(title="Academic Analytics RAG - demo", version="1.0", lifespan=lifespan)


class QueryIn(BaseModel):
    question: str = Field(..., max_length=500)
    llm: str = "offline"            # "offline" or "ollama"
    compromised: bool = False       # simulate a poisoned model
    validator: bool = True          # switch the validator off for the ablation


class RegenIn(BaseModel):
    seed: int = config.DEFAULT_SEED


@app.get("/api/health")
def health():
    ok, models = llm.ollama_available()
    return {"status": "ok", "database": data_generator.stats(),
            "llm": {"offline": True, "ollama": ok, "ollama_model": config.QWEN_MODEL,
                    "ollama_models": models},
            "current_term": config.CURRENT_TERM, "row_limit": config.ROW_LIMIT,
            "timeout_s": config.QUERY_TIMEOUT_S}


@app.post("/api/query")
def query(body: QueryIn):
    return pipeline.run_query(body.question, llm_mode=body.llm, compromised=body.compromised,
                              validator_on=body.validator)


@app.get("/api/schema")
def schema():
    return {"tables": schema_metadata(), "stats": data_generator.stats()}


@app.get("/api/audit")
def audit_log(limit: int = 50):
    return audit.recent(limit)


@app.delete("/api/audit")
def audit_clear():
    audit.clear()
    return {"cleared": True}


@app.post("/api/evaluate")
def evaluate(llm_mode: str = "offline"):
    """Runs the benchmark for the UI (full system vs. no validator) and reshapes the result."""
    out_dir = config.DATA_DIR / "ui_eval"
    for old in out_dir.glob("run_*.json"):
        old.unlink()
    keys = ["C", "C-novalidator"]
    r = evaluation.run(llm_mode, configs=keys, out_dir=out_dir, tag=f"ui_{llm_mode}")
    lam = str(config.WRONG_ANSWER_PENALTY)
    summary = [{"config": s["config"], "execution_accuracy": s["ex_relaxed"], "block_rate": s["block_rate"],
                "abstention_quality": s["abstention_action_accuracy"], "reliability_score": s["reliability"][lam],
                "mean_latency_ms": s["latency_p50_ms"]} for s in r["summary"]]
    items = [{"config": evaluation.CONFIGS[k]["label"],
              "items": [{**row, "points": row["points"][lam]} for row in r["items"][k]]} for k in keys]
    return {"summary": summary, "items": items, "n_items": r["n_items"],
            "penalty": config.WRONG_ANSWER_PENALTY, "llm_mode": llm_mode}


@app.post("/api/regenerate")
def regenerate(body: RegenIn):
    return data_generator.build(body.seed)


@app.post("/api/import")
async def import_excel(files: list[UploadFile] = File(...)):
    """Upload faculty workbooks; each replaces its course, section and term in the database."""
    up = config.DATA_DIR / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in files:
        if not f.filename.lower().endswith(".xlsx"):
            raise HTTPException(400, f"{f.filename}: only .xlsx workbooks are accepted")
        p = up / Path(f.filename).name
        p.write_bytes(await f.read())
        paths.append(p)
    try:
        return excel_io.import_sheets(paths)
    except Exception as exc:  # malformed workbook
        raise HTTPException(400, f"Could not read the workbook: {exc}") from exc


@app.get("/api/import/sample")
def import_sample():
    out = config.DATA_DIR / "sample_sheet"
    paths = excel_io.export_sheets(config.CURRENT_TERM, out, limit=1)
    return FileResponse(paths[0], filename=paths[0].name)


@app.get("/")
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR), name="frontend")
