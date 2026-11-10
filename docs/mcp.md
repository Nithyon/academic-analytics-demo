# MCP interface (optional)

`backend/mcp_server.py` exposes the system to MCP clients such as Claude Desktop and IDE assistants. It is built with the official MCP Python SDK (`mcp` 2.x) and runs over stdio.

## Tools

| Tool | What it does |
|---|---|
| `ask_question(question)` | Runs the full pipeline: router, retrieval, SQL generation, validator, read-only executor and explanation. Writes the question to the audit log. Returns the answer, the SQL that ran, the metric definition used and the tables used, or the reason the question was declined or blocked. |
| `list_courses(term)` | Lists the courses offered in a term. |
| `describe_metrics()` | Returns the metric definitions from the ontology. |
| `import_workbooks(paths)` | Imports faculty `.xlsx` workbooks. Each workbook replaces its course, section and term. |
| `sync_drive_folder(folder)` | Imports new or changed workbooks from a folder, for example a Google Drive folder that Google Drive for desktop mirrors on this computer. |

There is no tool that runs raw SQL. Every question passes the validator, so an MCP client cannot bypass the safety gate. `tests/test_mcp.py` checks this end to end: DROP is blocked, a request for roll numbers is blocked and a prediction is declined.

## Connect it to Claude Desktop

Add this entry to `claude_desktop_config.json`, and change the paths to your clone:

```json
{
  "mcpServers": {
    "academic-analytics": {
      "command": "C:\\path\\to\\academic-analytics-demo\\.venv\\Scripts\\python.exe",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "C:\\path\\to\\academic-analytics-demo"
    }
  }
}
```

The server uses the local Qwen model through Ollama when Ollama is running. If Ollama is not running, it uses the offline demo model. To choose the model yourself, set `MCP_LLM=offline` or `MCP_LLM=ollama`.

## Google Drive

- **Recommended:** install Google Drive for desktop, then point `sync_drive_folder`, or `python -m backend.drive_sync folder "G:/My Drive/..."`, at the mirrored folder. This app needs no credentials, and only changed files are re-imported.
- **Optional:** use `python -m backend.drive_sync api FOLDER_ID --key service-account.json` to download through the Drive v3 API. It needs `pip install google-api-python-client google-auth`. This path has not been tested yet, because no credentials were available.

## Privacy trade-off (for the paper)

The web app keeps everything local. An MCP client can be a cloud assistant. In that case the question and the aggregate answer go to that service. Student-level records do not leave, because the validator allows only aggregates. However, the deployment is then no longer fully local.

The MCP interface is therefore an optional convenience layer. The local web app stays the primary interface. A fully local setup is possible with a local MCP client that uses a local model.

Suggested paragraph for the Discussion or Future Work section:

> We also exposed the pipeline as a Model Context Protocol (MCP) server, so faculty can query it from general-purpose assistants. The server offers question answering, metric descriptions and workbook import, but no raw-SQL tool. Every request therefore passes the same router, validator and read-only executor. When the MCP client is a cloud assistant, questions and aggregate results leave the institution, although student-level records do not. We therefore treat MCP as an optional interface and keep the local web application as the default deployment.
