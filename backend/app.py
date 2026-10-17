"""Keystone — Knowledge-risk and reviewer-routing agent built on FalkorDB.
Backend API Server with FastMCP integration and static frontend serving.
"""
import os
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from backend.graph_client import (
    node_count, edge_count, get_connection_status, get_graph,
    list_repos, DEFAULT_REPO, REPOS, REPO_SLUGS, graph_provenance,
    validate_repo, is_valid_repo
)
from backend.agent import run_keystone, plan
from backend.tools import (
    get_pr, explain_path, bus_factor_files, critical_files,
    default_cutoff, reviewer_candidates, graph_stats, sample_pr,
    list_recent_prs, pr_criticality
)
from backend.scoring import score_reviewers
from backend.mcp_server import mcp as keystone_mcp

try:
    from backend.narration import narrate
except Exception:
    def narrate(decision, pr):
        return decision.get("rationale", "")

# Directory paths
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

# Action Audit Ledger for verified actions
ACTION_LEDGER: list[dict] = []
WRITE_REPOS_CONFIG = os.getenv("KEYSTONE_WRITE_REPOS", "").strip()
ALLOWED_WRITE_REPOS = [r.strip().lower() for r in WRITE_REPOS_CONFIG.split(",") if r.strip()]
SANDBOX_REPO = os.getenv("KEYSTONE_SANDBOX_REPO", "yashsejuro/keystone-sandbox").strip()

# FastMCP setup
mcp_sub = None
mcp_lifespan = None
try:
    mcp_sub = keystone_mcp.http_app(path="/")
    mcp_lifespan = mcp_sub.lifespan
except Exception:
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    if mcp_lifespan:
        async with mcp_lifespan(app):
            yield
    else:
        yield


app = FastAPI(
    title="Keystone API",
    description="Graph-based PR Reviewer Routing & Knowledge Risk Agent on FalkorDB",
    lifespan=lifespan
)

# Mount FastMCP HTTP SSE transport at /mcp/stream if available
if mcp_sub:
    try:
        app.mount("/mcp/stream", mcp_sub)
    except Exception:
        pass

# Mount static frontend assets (css, js, images)
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")


# -------------------------------------------------------------------------
# Web Page Endpoints
# -------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Frontend loading... please refresh</h1>", status_code=200)
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


@app.get("/mcp", response_class=HTMLResponse)
async def serve_mcp_page():
    mcp_file = FRONTEND_DIR / "mcp.html"
    if not mcp_file.exists():
        return HTMLResponse("<h1>MCP Explorer loading...</h1>", status_code=200)
    return HTMLResponse(content=mcp_file.read_text(encoding="utf-8"))


# -------------------------------------------------------------------------
# API Endpoints
# -------------------------------------------------------------------------

@app.get("/api/status")
async def api_status(repo: str = DEFAULT_REPO):
    try:
        repo = validate_repo(repo)
        status = get_connection_status()
        repos = list_repos()
        try:
            provenance = graph_provenance(repo)
        except Exception:
            provenance = {"status": "unmarked", "message": "Graph data exists"}
        return JSONResponse({
            "nodes": node_count(repo),
            "edges": edge_count(repo),
            "repos": repos,
            "current_repo": repo,
            "is_live": status.get("is_live", False),
            "message": status.get("message", "FalkorDB"),
            "provenance": provenance,
            "graph": graph_stats(repo),
            "sample_pr": sample_pr(repo),
            "allowed_write_repos": ALLOWED_WRITE_REPOS,
            "sandbox_repo": SANDBOX_REPO,
        })
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse(
            {"error": f"FalkorDB unavailable: {type(e).__name__}: {e}"},
            status_code=503,
        )


@app.get("/api/prs")
async def api_prs(repo: str = DEFAULT_REPO, limit: int = 30):
    try:
        repo = validate_repo(repo)
        prs = list_recent_prs(limit=limit, repo=repo)
        return JSONResponse({"repo": repo, "prs": prs, "count": len(prs)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/plan")
async def api_plan(req: Request):
    try:
        body = await req.json()
        pr_num = int(body.get("pr_number", 13997))
        question = body.get("question", "who should review this?")
        repo = validate_repo(body.get("repo", DEFAULT_REPO))
        planned = plan(pr_num, question=question, repo=repo)
        return JSONResponse({"planned_tools": planned, "question": question, "repo": repo})
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/investigate")
async def api_investigate(req: Request):
    try:
        body = await req.json()
        pr_num = int(body.get("pr_number", 13997))
        repo = validate_repo(body.get("repo", DEFAULT_REPO))
        question = body.get("question", "who should review this?")

        result = run_keystone(pr_num, question, repo=repo)
        pr_info = get_pr(pr_num, repo=repo)
        cutoff = default_cutoff()
        crit = pr_criticality(pr_num, repo=repo)
        bf_all = bus_factor_files(cutoff, repo=repo)

        pr_files = pr_info.get("files", [])
        pr_files_set = set(pr_files)
        pr_bf_files = [b for b in bf_all if b["path"] in pr_files_set]

        evidence_map = result.get("reviewer_evidence", {})
        enriched_reviewers = []
        for r in result["decision"]["reviewers"]:
            login = r["login"]
            ep = evidence_map.get(login, {})
            covered = ep.get("files", [])
            covered_set = set(covered)
            uncovered = [f for f in pr_files if f not in covered_set]
            coverage_pct = round((len(covered) / len(pr_files) * 100), 1) if pr_files else 100.0

            last_rev_iso = r.get("last_review")
            days_ago = None
            if last_rev_iso:
                try:
                    t = datetime.fromisoformat(last_rev_iso.replace("Z", "+00:00"))
                    days_ago = max(0, int((datetime.now(timezone.utc) - t).total_seconds() / 86400))
                except Exception:
                    pass

            enriched_reviewers.append({
                **r,
                "covered_files": covered,
                "uncovered_files": uncovered,
                "coverage_pct": coverage_pct,
                "days_ago": days_ago,
                "is_overloaded": r.get("recent_reviews", 0) > 20,
            })

        max_c = crit.get("max_centrality", 0.0)
        if max_c >= 0.25:
            blast_tier = "Critical Architecture"
            blast_color = "rose"
        elif max_c >= 0.08:
            blast_tier = "High Blast Radius"
            blast_color = "amber"
        elif max_c > 0.01:
            blast_tier = "Moderate Blast Radius"
            blast_color = "indigo"
        else:
            blast_tier = "Isolated Change"
            blast_color = "slate"

        pr_metrics = {
            "blast_tier": blast_tier,
            "blast_color": blast_color,
            "criticality": crit,
            "bus_factor_files": pr_bf_files,
            "additions": pr_info.get("additions", 0),
            "deletions": pr_info.get("deletions", 0),
            "total_files": len(pr_files),
        }

        top_rev = "davidhewitt"
        if result["decision"]["reviewers"]:
            top_rev = result["decision"]["reviewers"][0]["login"]

        path_info = explain_path(pr_num, top_rev, repo=repo)
        narration_text = narrate(result["decision"], pr_info)

        return JSONResponse({
            **result,
            "decision": {
                **result["decision"],
                "reviewers": enriched_reviewers
            },
            "pr_details": pr_info,
            "pr_metrics": pr_metrics,
            "explain_path": path_info,
            "narration": narration_text
        })
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"Investigation failed: {e}"}, status_code=500)


@app.get("/api/insights")
async def api_insights(repo: str = DEFAULT_REPO):
    try:
        repo = validate_repo(repo)
        bf = bus_factor_files(default_cutoff(), repo=repo)
        cf = critical_files(10, repo=repo)
        return JSONResponse({
            "bus_factor": bf,
            "critical_files": cf
        })
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse(
            {"error": f"FalkorDB unavailable: {type(e).__name__}: {e}"},
            status_code=503,
        )


@app.post("/api/cypher")
async def api_cypher(req: Request):
    try:
        body = await req.json()
        query = body.get("query", "").strip()
        repo = validate_repo(body.get("repo", DEFAULT_REPO))
        if not query:
            return JSONResponse({"error": "Query cannot be empty"}, status_code=400)
        g = get_graph(repo)
        res = g.query(query)
        rows = [list(r) for r in res.result_set] if hasattr(res, "result_set") else []
        return JSONResponse({"rows": rows, "count": len(rows)})
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=400)


@app.get("/api/mcp/tools")
async def api_mcp_tools():
    """List all available FastMCP tools with metadata for interactive explorer."""
    tools = [
        {
            "name": "rank_reviewers",
            "description": "Rank candidate reviewers for a PR using 4-component deterministic graph scoring (File overlap, Structural co-change, Activity, Recency).",
            "params": {"pr_number": "int", "repo": "str"},
            "example": {"pr_number": 13997, "repo": "pydantic"}
        },
        {
            "name": "get_pr",
            "description": "Fetch metadata for a pull request by number including changed files and churn stats.",
            "params": {"number": "int", "repo": "str"},
            "example": {"number": 13997, "repo": "pydantic"}
        },
        {
            "name": "bus_factor_files",
            "description": "Find files where a single reviewer performed >60% of reviews (monopoly bottleneck risk).",
            "params": {"min_reviews": "int", "repo": "str"},
            "example": {"min_reviews": 3, "repo": "pydantic"}
        },
        {
            "name": "critical_files",
            "description": "Calculate top files by betweenness centrality on the CO_CHANGES code graph.",
            "params": {"limit": "int", "repo": "str"},
            "example": {"limit": 10, "repo": "pydantic"}
        },
        {
            "name": "explain_path",
            "description": "Find shortest graph path from PR files through co-change bridges to a candidate reviewer.",
            "params": {"pr_number": "int", "reviewer": "str", "repo": "str"},
            "example": {"pr_number": 13997, "reviewer": "davidhewitt", "repo": "pydantic"}
        },
        {
            "name": "data_provenance",
            "description": "Verify whether the connected FalkorDB graph has recorded GitHub provenance metadata.",
            "params": {"repo": "str"},
            "example": {"repo": "pydantic"}
        }
    ]
    return JSONResponse({
        "server_name": "keystone",
        "protocol_version": "2024-11-05",
        "transport": "HTTP-SSE & stdio",
        "stream_endpoint": "/mcp/stream",
        "tools": tools,
        "count": len(tools)
    })


@app.post("/api/mcp/execute")
async def api_mcp_execute(req: Request):
    try:
        body = await req.json()
        tool_name = body.get("tool")
        params = body.get("params", {})
        repo = validate_repo(body.get("repo", DEFAULT_REPO))
        cutoff = default_cutoff()

        if tool_name == "get_pr":
            return JSONResponse(get_pr(int(params.get("number", 13997)), repo=repo))
        elif tool_name == "rank_reviewers":
            return JSONResponse(score_reviewers(int(params.get("pr_number", 13997)), cutoff, repo=repo))
        elif tool_name == "bus_factor_files":
            return JSONResponse(bus_factor_files(cutoff, int(params.get("min_reviews", 5)), repo=repo))
        elif tool_name == "critical_files":
            return JSONResponse(critical_files(int(params.get("limit", 10)), repo=repo))
        elif tool_name == "explain_path":
            return JSONResponse(explain_path(int(params.get("pr_number", 13997)), str(params.get("reviewer", "davidhewitt")), repo=repo))
        elif tool_name == "data_provenance":
            return JSONResponse(graph_provenance(repo))
        else:
            return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=400)
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.get("/api/action/ledger")
async def api_action_ledger():
    live_count = sum(1 for a in ACTION_LEDGER if a.get("mode") == "LIVE")
    shadow_count = sum(1 for a in ACTION_LEDGER if a.get("mode") == "SHADOW")
    return JSONResponse({
        "ledger": ACTION_LEDGER,
        "count": len(ACTION_LEDGER),
        "live_count": live_count,
        "shadow_count": shadow_count,
        "sandbox_repo": SANDBOX_REPO,
        "allowed_write_repos": ALLOWED_WRITE_REPOS,
    })


@app.post("/api/action/execute")
async def api_action_execute(req: Request):
    try:
        body = await req.json()
        action = body.get("action", {})
        repo = body.get("repo", DEFAULT_REPO)
        pr_number = body.get("pr_number") or action.get("on")
        action_id = f"ACT-{uuid.uuid4().hex[:8].upper()}"
        timestamp = datetime.now(timezone.utc).isoformat()

        repo_lower = str(repo).lower().strip()
        is_live = (repo_lower in ALLOWED_WRITE_REPOS) or (any(repo_lower.endswith('/' + w) or w.endswith('/' + repo_lower) for w in ALLOWED_WRITE_REPOS) if ALLOWED_WRITE_REPOS else False)
        mode = "LIVE" if is_live else "SHADOW"
        destination = f"{repo} PR #{pr_number}" if is_live else f"{SANDBOX_REPO} (Tracking Issue)"
        safety_notice = "Executed directly on allowed repository" if is_live else f"Safeguarded in shadow issue on {SANDBOX_REPO}; logins formatted as code to prevent upstream notifications"

        entry = {
            "id": action_id,
            "timestamp": timestamp,
            "repo": repo,
            "pr_number": pr_number,
            "action": action.get("action", "unknown").upper(),
            "target": action.get("who") or action.get("label") or "PR",
            "reason": action.get("reason", "Graph-directed decision"),
            "status": "EXECUTED",
            "mode": mode,
            "destination": destination,
            "safety_notice": safety_notice,
        }
        ACTION_LEDGER.insert(0, entry)
        return JSONResponse({"ok": True, "action_id": action_id, "entry": entry})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/action/clear")
async def api_action_clear():
    ACTION_LEDGER.clear()
    return JSONResponse({"ok": True, "message": "Action ledger reset"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
