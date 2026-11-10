"""FastAPI backend (layer B: orchestrator). Serves the API and the HTML/CSS frontend.

Start it with:   python run.py
or:              uvicorn backend.main:app --reload
then open        http://127.0.0.1:8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import audit, config, data_generator, evaluation, llm, pipeline
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
    return evaluation.run(llm_mode)


@app.post("/api/regenerate")
def regenerate(body: RegenIn):
    return data_generator.build(body.seed)


@app.get("/")
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR), name="frontend")
