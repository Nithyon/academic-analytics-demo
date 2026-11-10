"""MCP server: exposes the academic analytics system to MCP clients (Claude Desktop, IDEs).

Every tool goes through the same backend as the web app: questions pass the router,
retrieval, the SQL validator and the read-only executor, and they are written to the audit
log. There is deliberately NO tool that runs raw SQL, so an MCP client cannot bypass the
validator.

Privacy note: if the MCP client is a cloud assistant, the question and the aggregate answer
are sent to that service. Student-level records never leave, because the validator only
allows aggregates, but the setup is no longer fully local. The local web app stays the
primary interface.

Run (stdio):  python -m backend.mcp_server
"""
import os
import sqlite3
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import config, data_generator, drive_sync, excel_io, llm, ontology, pipeline, rules

server = MCPServer(
    name="academic-analytics",
    instructions=("Answers descriptive questions about attendance and marks in a synthetic SRM-style "
                  "academic database. Answers are aggregates only; the system declines predictions, "
                  "personal data and anything outside attendance and marks."),
)


def _llm_mode():
    forced = os.getenv("MCP_LLM")  # "offline" or "ollama"
    if forced in ("offline", "ollama"):
        return forced
    ok, _names = llm.ollama_available()
    return "ollama" if ok else "offline"


@server.tool(description="Ask a plain-English question about attendance or marks. Returns the answer, "
                         "the SQL that ran, the metric definition used, or the reason it was declined or blocked.")
def ask_question(question: str) -> dict:
    if not config.DB_PATH.exists():
        data_generator.build(config.DEFAULT_SEED)
    res = pipeline.run_query(question[:500], llm_mode=_llm_mode())
    out = {"status": res["status"], "model": res["model"], "audit_id": res.get("audit_id")}
    if res["status"] == "answered":
        ex = res["explanation"]
        out.update(answer=ex["summary"], columns=res["columns"], rows=res["rows"][:50],
                   sql=res["final_sql"], definitions=ex.get("definitions", []), tables_used=ex["tables_used"])
    else:
        out["reason"] = res["reason"]
        if res["route"] and res["route"].get("options"):
            out["suggested_questions"] = res["route"]["options"]
    return out


@server.tool(description="List the courses offered in a term (default: the current term), with code, "
                         "name, type and department.")
def list_courses(term: str = rules.CURRENT_TERM) -> dict:
    con = sqlite3.connect(f"file:{config.DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute("""SELECT DISTINCT c.course_code, c.course_name, c.course_type, d.dept_code
                              FROM course_results r JOIN dim_course c USING(course_id)
                              JOIN dim_department d ON d.department_id = c.department_id
                              JOIN dim_term t USING(term_id) WHERE t.term_name = ?
                              ORDER BY c.course_code""", (term,)).fetchall()
    finally:
        con.close()
    return {"term": term, "courses": [{"code": a, "name": b, "type": c, "department": d} for a, b, c, d in rows]}


@server.tool(description="Describe the metrics the system can compute and exactly how each one is defined.")
def describe_metrics() -> dict:
    return {"metrics": [{"id": m["id"], "label": m["label"], "definition": m["definition"]} for m in ontology.METRICS]}


@server.tool(description="Import faculty Excel workbooks (.xlsx) from local file paths. Each workbook "
                         "replaces its course, section and term. Returns rows loaded and any problems.")
def import_workbooks(paths: list[str]) -> dict:
    files = [Path(p) for p in paths]
    bad = [str(p) for p in files if p.suffix.lower() != ".xlsx" or not p.is_file()]
    if bad:
        return {"error": "Only existing .xlsx files can be imported.", "rejected": bad}
    return excel_io.import_sheets(files)


@server.tool(description="Import new or changed workbooks from a folder, for example a Google Drive "
                         "folder mirrored by Google Drive for desktop.")
def sync_drive_folder(folder: str) -> dict:
    try:
        return drive_sync.sync_folder(folder)
    except FileNotFoundError as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    server.run("stdio")
