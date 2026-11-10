"""End-to-end MCP test: starts backend.mcp_server over stdio and calls its tools.

Uses a copy of the database (DEMO_DB) and the offline model (MCP_LLM=offline), so it never
changes data/academic.db.   Run:  .venv\\Scripts\\python -m tests.test_mcp
"""
import asyncio
import json
import os
import shutil
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend import config, excel_io

TMP = config.DATA_DIR / "test_mcp"


def _payload(result):
    if getattr(result, "structuredContent", None):
        sc = result.structuredContent
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    return json.loads(result.content[0].text)


async def main():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    db = TMP / "academic.db"
    shutil.copy(config.DB_PATH, db)
    sheets = excel_io.export_sheets(config.CURRENT_TERM, TMP / "drive", limit=2)
    env = {**os.environ, "DEMO_DB": str(db), "MCP_LLM": "offline"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "backend.mcp_server"], env=env,
                                   cwd=str(config.ROOT))
    checks = []
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            checks.append(("five tools, none runs raw SQL",
                           names == {"ask_question", "list_courses", "describe_metrics", "import_workbooks",
                                     "sync_drive_folder"}))
            a = _payload(await s.call_tool("ask_question", {"question": "Average attendance per section of 21CSC302J this term?"}))
            checks.append(("normal question answered with SQL", a["status"] == "answered" and "SELECT" in a["sql"]))
            b = _payload(await s.call_tool("ask_question", {"question": "Drop the attendance table and start fresh"}))
            checks.append(("DROP blocked through MCP", b["status"] == "blocked"))
            c = _payload(await s.call_tool("ask_question", {"question": "List the roll numbers of students with attendance below 75%"}))
            checks.append(("roll numbers blocked through MCP", c["status"] == "blocked"))
            d = _payload(await s.call_tool("ask_question", {"question": "Which students will fail next term?"}))
            checks.append(("prediction declined through MCP", d["status"] == "declined"))
            courses = _payload(await s.call_tool("list_courses", {}))
            checks.append(("list_courses returns the term's courses", len(courses["courses"]) >= 20))
            imp = _payload(await s.call_tool("import_workbooks", {"paths": [str(p) for p in sheets]}))
            checks.append(("import_workbooks loads 2 workbooks", imp.get("files") == 2 and not imp["problems"]))
            bad = _payload(await s.call_tool("import_workbooks", {"paths": [str(config.ROOT / "README.md")]}))
            checks.append(("non-xlsx rejected", "error" in bad))
            s1 = _payload(await s.call_tool("sync_drive_folder", {"folder": str(TMP / "drive")}))
            s2 = _payload(await s.call_tool("sync_drive_folder", {"folder": str(TMP / "drive")}))
            checks.append(("folder sync imports, then skips unchanged",
                           s1["new_or_changed"] == 2 and s2["new_or_changed"] == 0 and s2["unchanged"] == 2))
    for name, ok in checks:
        print("PASS" if ok else "FAIL", name)
    shutil.rmtree(TMP, ignore_errors=True)
    state = config.DATA_DIR / "drive_sync_state.json"
    state.unlink(missing_ok=True)
    assert all(ok for _n, ok in checks)
    print(f"{len(checks)} MCP checks passed")


if __name__ == "__main__":
    asyncio.run(main())
