"""Keystone — Knowledge-risk and reviewer-routing agent built on FalkorDB.
Backend API Server with FastMCP integration, non-blocking execution, and static frontend serving.
"""
import os
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
import uvicorn

from backend.graph_client import (
    node_count, edge_count, get_connection_status, get_graph,
    list_repos, DEFAULT_REPO, REPOS, REPO_SLUGS, graph_provenance,
    validate_repo, is_valid_repo, execute_graph_query, unregister_repo
)
from backend.agent import run_keystone, plan
from backend.tools import (
    get_pr, explain_path, bus_factor_files, critical_files,
    default_cutoff, reviewer_candidates, graph_stats, sample_pr,
    list_recent_prs, pr_criticality, get_repo_pr_stats
)
from backend.scoring import score_reviewers
from backend.mcp_server import mcp as keystone_mcp
from backend.cypher_guard import sanitize_and_bound_query, CypherSecurityError
from backend.centrality import get_centrality_status, materialize_centrality, get_precomputed_critical_files
from backend.ingestion_manager import INGESTION_MANAGER, get_registered_repositories, estimate_ingestion_scope
from backend.action_ledger import ACTION_LEDGER_STORE, ALLOWED_WRITE_REPOS, SANDBOX_REPO
from backend.coverage import get_repository_coverage, update_coverage_metadata

try:
    from backend.narration import narrate
except Exception:
    def narrate(decision, pr):
        return decision.get("rationale", "")

logger = logging.getLogger("keystone.api")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Directory paths
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

# FastMCP setup
mcp_sub = None
mcp_lifespan = None
try:
    mcp_sub = keystone_mcp.http_app(path="/")
    mcp_lifespan = mcp_sub.lifespan
except Exception as e:
    logger.warning(f"FastMCP setup deferred: {e}")


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
    except Exception as e:
        logger.warning(f"FastMCP stream mount skipped: {e}")

# Mount static frontend assets
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
# Health & Status Endpoints
# -------------------------------------------------------------------------

@app.get("/api/health")
async def api_health():
    """Cheap, lightweight health check separating ping from heavy graph metadata."""
    status = await run_in_threadpool(get_connection_status)
    http_code = 200 if status.get("is_live") else 503
    return JSONResponse(status, status_code=http_code)


@app.get("/api/status")
async def api_status(repo: str = DEFAULT_REPO):
    t0 = time.perf_counter()
    try:
        repo_clean = await run_in_threadpool(validate_repo, repo)
        status = await run_in_threadpool(get_connection_status)
        repos = await run_in_threadpool(list_repos)
        provenance = await run_in_threadpool(graph_provenance, repo_clean)
        nodes = await run_in_threadpool(node_count, repo_clean)
        edges = await run_in_threadpool(edge_count, repo_clean)
        g_stats = await run_in_threadpool(graph_stats, repo_clean)
        s_pr = await run_in_threadpool(sample_pr, repo_clean)
        cent_status = await run_in_threadpool(get_centrality_status, repo_clean)

        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        logger.info(f"[/api/status] {repo_clean} processed in {duration_ms}ms")

        return JSONResponse({
            "nodes": nodes,
            "edges": edges,
            "repos": repos,
            "current_repo": repo_clean,
            "repo_slug": REPO_SLUGS.get(repo_clean, repo_clean),
            "is_live": status.get("is_live", False),
            "message": status.get("message", "FalkorDB"),
            "provenance": provenance,
            "graph": g_stats,
            "centrality": cent_status,
            "sample_pr": s_pr,
            "allowed_write_repos": ALLOWED_WRITE_REPOS,
            "sandbox_repo": SANDBOX_REPO,
            "latency_ms": duration_ms,
        })
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        logger.error(f"Status check failed: {e}", exc_info=True)
        return JSONResponse(
            {"error": f"FalkorDB unavailable: {type(e).__name__}: {e}"},
            status_code=503,
        )


@app.get("/api/repositories")
async def api_repositories():
    """List registered repositories with their graph names, coverage counts, and live freshness."""
    try:
        repos = await run_in_threadpool(get_registered_repositories)
        return JSONResponse({"repositories": repos, "count": len(repos)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/repositories/{repo:path}")
async def api_delete_repository(repo: str, drop_graph: bool = True):
    """Unregister a repository and permanently delete its FalkorDB graph."""
    try:
        res = await run_in_threadpool(unregister_repo, repo, drop_graph)
        return JSONResponse(res)
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except RuntimeError as re:
        # Graph was removed from registry but FalkorDB deletion failed
        logger.error(f"Graph deletion failed for {repo}: {re}", exc_info=True)
        return JSONResponse({"error": str(re), "graph_dropped": False}, status_code=500)
    except Exception as e:
        logger.error(f"Failed to unregister repository {repo}: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/repositories/{repo:path}/coverage")
async def api_repository_coverage(repo: str, window_days: int = 90):
    """Return full repository coverage metrics: GitHub universe, discovered, ingested, active window, and gaps."""
    try:
        repo_clean = await run_in_threadpool(validate_repo, repo)
        cov = await run_in_threadpool(get_repository_coverage, repo_clean, window_days)
        return JSONResponse(cov)
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        logger.error(f"Failed to fetch coverage for {repo}: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


# -------------------------------------------------------------------------
# Repository Ingestion Endpoints
# -------------------------------------------------------------------------

@app.post("/api/ingest/estimate")
async def api_ingest_estimate(req: Request):
    """Pre-flight scope estimation before initiating ingestion."""
    try:
        body = await req.json()
        repo_slug = body.get("repo", "").strip()
        scope_type = body.get("scope_type", "recent")
        limit = int(body.get("limit", 100))
        date_from = body.get("date_from")
        date_to = body.get("date_to")

        if not repo_slug:
            return JSONResponse({"error": "Repository slug is required in owner/name format."}, status_code=400)

        est = await run_in_threadpool(
            estimate_ingestion_scope,
            repo_slug=repo_slug,
            scope_type=scope_type,
            limit=limit,
            date_from=date_from,
            date_to=date_to,
        )
        return JSONResponse(est)
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/ingest")
async def api_ingest(req: Request):
    """Start an asynchronous, resumable, and idempotent repository ingestion job."""
    try:
        body = await req.json()
        repo_slug = body.get("repo", "").strip()
        limit = int(body.get("limit", 100))
        materialize = bool(body.get("materialize_centrality", True))
        scope_type = body.get("scope_type", "recent")
        date_from = body.get("date_from")
        date_to = body.get("date_to")

        if not repo_slug:
            return JSONResponse({"error": "Repository slug is required in owner/name format."}, status_code=400)

        job = await run_in_threadpool(
            INGESTION_MANAGER.start_job,
            repo_slug=repo_slug,
            target_limit=limit,
            materialize_centrality_flag=materialize,
            scope_type=scope_type,
            date_from=date_from,
            date_to=date_to,
        )

        return JSONResponse({
            "ok": True,
            "job_id": job.job_id,
            "job": job.to_dict(),
            "message": f"Ingestion job queued for {repo_slug}."
        })
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except RuntimeError as re:
        return JSONResponse({"error": str(re)}, status_code=409)
    except Exception as e:
        logger.error(f"Ingestion start failed: {e}", exc_info=True)
        return JSONResponse({"error": f"Failed to start ingestion: {type(e).__name__}: {e}"}, status_code=500)


@app.get("/api/ingest/{job_id}")
async def api_ingest_status(job_id: str):
    """Query current status and progress of an ingestion job."""
    job = INGESTION_MANAGER.get_job(job_id)
    if not job:
        return JSONResponse({"error": f"Ingestion job '{job_id}' not found."}, status_code=404)
    return JSONResponse({"job": job.to_dict()})


@app.post("/api/ingest/{job_id}/cancel")
async def api_ingest_cancel(job_id: str):
    """Request safe cancellation of an active ingestion job."""
    success = INGESTION_MANAGER.cancel_job(job_id)
    if not success:
        return JSONResponse({"error": f"Ingestion job '{job_id}' not found."}, status_code=404)
    return JSONResponse({"ok": True, "message": f"Cancellation requested for job '{job_id}'."})


# -------------------------------------------------------------------------
# Centrality Materialization Refresh Endpoint
# -------------------------------------------------------------------------

@app.post("/api/centrality/refresh")
async def api_centrality_refresh(req: Request):
    """Admin/authorized command to calculate and materialize File.centrality."""
    try:
        body = await req.json() if (await req.body()) else {}
        repo = body.get("repo", DEFAULT_REPO)
        repo_clean = await run_in_threadpool(validate_repo, repo)
        res = await run_in_threadpool(materialize_centrality, repo_clean)
        status_code = 200 if res.get("ok") else 500
        return JSONResponse(res, status_code=status_code)
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# -------------------------------------------------------------------------
# PR Browser Endpoints (Server-side Paginated & Deep Filtered)
# -------------------------------------------------------------------------

@app.get("/api/prs")
async def api_prs(repo: str = DEFAULT_REPO, page: int = 1, page_size: int = 25,
                  limit: int = 25, q: Optional[str] = None, filter_by: str = "all",
                  state: Optional[str] = None, merged: Optional[str] = None,
                  reviewed: Optional[str] = None, risk: Optional[str] = None,
                  author: Optional[str] = None, reviewer: Optional[str] = None,
                  date_from: Optional[str] = None, date_to: Optional[str] = None,
                  min_files: Optional[int] = None, max_files: Optional[int] = None,
                  sort: str = "number", sort_direction: str = "desc",
                  view: str = "all"):
    t0 = time.perf_counter()
    try:
        repo_clean = await run_in_threadpool(validate_repo, repo)
        effective_page_size = page_size or limit
        data = await run_in_threadpool(
            list_recent_prs,
            page=page,
            page_size=effective_page_size,
            limit=effective_page_size,
            repo=repo_clean,
            q=q,
            filter_by=filter_by,
            state=state,
            merged=merged,
            reviewed=reviewed,
            risk=risk,
            author=author,
            reviewer=reviewer,
            date_from=date_from,
            date_to=date_to,
            min_files=min_files,
            max_files=max_files,
            sort=sort,
            sort_direction=sort_direction,
            view=view,
        )
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        logger.info(f"[/api/prs] {repo_clean} page {page} returned {data['count']} items in {duration_ms}ms")
        return JSONResponse(data)
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        logger.error(f"PR listing error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/prs/stats")
async def api_prs_stats(repo: str = DEFAULT_REPO):
    try:
        repo_clean = await run_in_threadpool(validate_repo, repo)
        stats = await run_in_threadpool(get_repo_pr_stats, repo_clean)
        return JSONResponse({"repo": repo_clean, "stats": stats})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# -------------------------------------------------------------------------
# Investigation & Reasoning Endpoints (Deduplicated & Non-Blocking)
# -------------------------------------------------------------------------

@app.post("/api/plan")
async def api_plan(req: Request):
    try:
        body = await req.json()
        pr_num = int(body.get("pr_number", 13997))
        question = body.get("question", "who should review this?")
        repo = await run_in_threadpool(validate_repo, body.get("repo", DEFAULT_REPO))
        planned = await run_in_threadpool(plan, pr_num, question=question, repo=repo)
        return JSONResponse({"planned_tools": planned, "question": question, "repo": repo})
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/investigate")
async def api_investigate(req: Request):
    """End-to-end investigation with zero duplicate queries and non-blocking execution."""
    t0 = time.perf_counter()
    try:
        body = await req.json()
        pr_num = int(body.get("pr_number", 13997))
        repo = await run_in_threadpool(validate_repo, body.get("repo", DEFAULT_REPO))
        question = body.get("question", "who should review this?")

        # Run single keystone pipeline pass
        result = await run_in_threadpool(run_keystone, pr_num, question, repo=repo)

        # Reuse pre-fetched PR info and decision without re-querying FalkorDB!
        pr_info = result["pr_details"]
        decision = result["decision"]
        crit = decision.get("criticality", {"max_centrality": 0.0})
        pr_files = pr_info.get("files", [])
        evidence_map = result.get("reviewer_evidence", {})

        # Compute enriched reviewer metrics in-memory
        enriched_reviewers = []
        for r in decision.get("reviewers", []):
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

        max_c = float(crit.get("max_centrality", 0.0))
        if max_c >= 0.25:
            blast_tier = "Critical Architecture"
            blast_color = "red"
        elif max_c >= 0.08:
            blast_tier = "High Risk"
            blast_color = "amber"
        elif max_c > 0.01:
            blast_tier = "Moderate Risk"
            blast_color = "indigo"
        else:
            blast_tier = "Standard Change"
            blast_color = "slate"

        # Filter bus factor files from observations
        obs_bf = result.get("observations", {}).get("bus_factor_files", [])
        pr_files_set = set(pr_files)
        pr_bf_files = [b for b in obs_bf if b.get("path") in pr_files_set]

        pr_metrics = {
            "blast_tier": blast_tier,
            "blast_color": blast_color,
            "criticality": crit,
            "bus_factor_files": pr_bf_files,
            "additions": pr_info.get("additions", 0),
            "deletions": pr_info.get("deletions", 0),
            "total_files": len(pr_files),
        }

        # Compute analysis training scope and coverage transparency
        cov = await run_in_threadpool(get_repository_coverage, repo)
        cov_counts = cov.get("counts", {})
        cov_pct = cov.get("percentages", {})
        is_partial = cov.get("is_partial", True)
        ingested_pct = cov_pct.get("ingested_pct")

        if is_partial and ingested_pct is not None:
            confidence_notice = (
                f"Recommendation confidence is limited because only {ingested_pct}% "
                f"of the repository's discovered PR history has been ingested."
            )
        else:
            confidence_notice = "Recommendation based on complete ingested dataset within the active analysis window."

        training_summary = (
            f"Reviewer recommendation based on: {cov_counts.get('analysis_ready', 0):,} analysis-ready PRs · "
            f"{cov_counts.get('review_relationships', 0):,} review relationships · "
            f"{cov.get('analysis_window', {}).get('label', 'Last 90 days')} · "
            f"Graph updated {cov.get('statuses', {}).get('freshness', 'recently')} · "
            f"Coverage: {'partial' if is_partial else 'complete'}"
        )

        analysis_scope = {
            "analysis_window": cov.get("analysis_window", {}).get("label", "Last 90 days"),
            "window_start": cov.get("analysis_window", {}).get("start"),
            "window_end": cov.get("analysis_window", {}).get("end"),
            "historical_prs_used": cov_counts.get("in_active_window", 0),
            "analysis_ready_prs": cov_counts.get("analysis_ready", 0),
            "review_relationships_used": cov_counts.get("review_relationships", 0),
            "files_in_graph": cov_counts.get("files_in_graph", 0),
            "graph_freshness": cov.get("statuses", {}).get("freshness", "Fresh"),
            "last_synced_at": cov.get("last_synced_at"),
            "coverage_quality": "partial" if is_partial else "complete",
            "coverage_level": "partial" if is_partial else "complete",
            "confidence_notice": confidence_notice,
            "confidence_warning": confidence_notice,
            "training_summary": training_summary,
            "coverage_percentage": ingested_pct,
        }

        # Optional LLM narration (non-blocking)
        narration_text = await run_in_threadpool(narrate, decision, pr_info)

        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        logger.info(f"[/api/investigate] PR #{pr_num} on {repo} completed in {duration_ms}ms")

        return JSONResponse({
            **result,
            "decision": {
                **decision,
                "reviewers": enriched_reviewers,
            },
            "pr_details": pr_info,
            "pr_metrics": pr_metrics,
            "analysis_scope": analysis_scope,
            "explain_path": result.get("explain_path"),
            "narration": narration_text,
            "latency_ms": duration_ms,
        })
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        logger.error(f"Investigation failed: {e}", exc_info=True)
        return JSONResponse({"error": f"Investigation failed: {type(e).__name__}: {e}"}, status_code=500)


@app.get("/api/insights")
async def api_insights(repo: str = DEFAULT_REPO):
    try:
        repo_clean = await run_in_threadpool(validate_repo, repo)
        bf = await run_in_threadpool(bus_factor_files, default_cutoff(), 5, repo_clean)
        cf_data = await run_in_threadpool(get_precomputed_critical_files, 10, repo_clean)
        return JSONResponse({
            "bus_factor": bf,
            "critical_files": cf_data.get("files", []),
            "centrality_status": cf_data.get("status"),
        })
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse(
            {"error": f"FalkorDB unavailable: {type(e).__name__}: {e}"},
            status_code=503,
        )


@app.get("/api/benchmark")
async def api_benchmark():
    """Return locked backtest results. If results do not exist, return explicit unavailable state."""
    results_path = BASE_DIR / "benchmark_results.json"
    if results_path.exists():
        try:
            data = json.loads(results_path.read_text(encoding="utf-8"))
            return JSONResponse(data)
        except Exception as e:
            return JSONResponse({"error": f"Unable to parse benchmark results: {e}"}, status_code=500)

    # Do not invent fake fallback data! Report honestly that benchmark has not been run.
    return JSONResponse({
        "status": "unavailable",
        "message": "Benchmark results not generated yet. Run backtest.py to generate results."
    }, status_code=404)


# -------------------------------------------------------------------------
# Secure Cypher Execution Endpoint
# -------------------------------------------------------------------------

@app.post("/api/cypher")
async def api_cypher(req: Request):
    """Secure, bounded read-only Cypher query execution."""
    t0 = time.perf_counter()
    try:
        body = await req.json()
        query = str(body.get("query", "")).strip()
        repo = await run_in_threadpool(validate_repo, body.get("repo", DEFAULT_REPO))

        if not query:
            return JSONResponse({"error": "Query cannot be empty."}, status_code=400)

        # Enforce read-only, bounds, and max rows
        safe_query = sanitize_and_bound_query(query, max_rows=100)

        res = await run_in_threadpool(execute_graph_query, safe_query, repo=repo)
        rows = [list(r) for r in res.result_set] if hasattr(res, "result_set") else []

        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        logger.info(f"[/api/cypher] {repo} executed in {duration_ms}ms, rows: {len(rows)}")

        return JSONResponse({
            "rows": rows,
            "count": len(rows),
            "executed_query": safe_query,
            "latency_ms": duration_ms
        })
    except CypherSecurityError as cse:
        return JSONResponse({"error": f"Query rejected: {cse}"}, status_code=400)
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        logger.error(f"Cypher error: {e}")
        return JSONResponse({"error": f"Cypher execution error: {type(e).__name__}: {e}"}, status_code=400)


# -------------------------------------------------------------------------
# MCP Interactive Tools Endpoints
# -------------------------------------------------------------------------

@app.get("/api/mcp/tools")
async def api_mcp_tools():
    tools = [
        {
            "name": "rank_reviewers",
            "description": "Rank candidate reviewers using deterministic 4-component graph scoring.",
            "params": {"pr_number": "int", "repo": "str"},
            "example": {"pr_number": 13997, "repo": "pydantic"}
        },
        {
            "name": "get_pr",
            "description": "Fetch PR metadata, changed files, and churn statistics.",
            "params": {"number": "int", "repo": "str"},
            "example": {"number": 13997, "repo": "pydantic"}
        },
        {
            "name": "bus_factor_files",
            "description": "Find files where a single reviewer performed >60% of reviews (monopoly bottleneck risk).",
            "params": {"min_reviews": "int", "repo": "str"},
            "example": {"min_reviews": 5, "repo": "pydantic"}
        },
        {
            "name": "critical_files",
            "description": "Retrieve top structural files from precomputed File.centrality.",
            "params": {"limit": "int", "repo": "str"},
            "example": {"limit": 10, "repo": "pydantic"}
        },
        {
            "name": "explain_path",
            "description": "Find shortest evidence graph path from PR files to a candidate reviewer.",
            "params": {"pr_number": "int", "reviewer": "str", "repo": "str"},
            "example": {"pr_number": 13997, "reviewer": "example_reviewer", "repo": "pydantic"}
        },
        {
            "name": "data_provenance",
            "description": "Verify whether the connected FalkorDB graph has recorded GitHub provenance.",
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
        repo = await run_in_threadpool(validate_repo, body.get("repo", DEFAULT_REPO))
        cutoff = default_cutoff()

        if tool_name == "get_pr":
            res = await run_in_threadpool(get_pr, int(params.get("number", 13997)), repo=repo)
        elif tool_name == "rank_reviewers":
            res = await run_in_threadpool(score_reviewers, int(params.get("pr_number", 13997)), cutoff, repo=repo)
        elif tool_name == "bus_factor_files":
            res = await run_in_threadpool(bus_factor_files, cutoff, int(params.get("min_reviews", 5)), repo=repo)
        elif tool_name == "critical_files":
            res = await run_in_threadpool(critical_files, int(params.get("limit", 10)), repo=repo)
        elif tool_name == "explain_path":
            rev = str(params.get("reviewer", ""))
            res = await run_in_threadpool(explain_path, int(params.get("pr_number", 13997)), rev, repo=repo)
        elif tool_name == "data_provenance":
            res = await run_in_threadpool(graph_provenance, repo)
        else:
            return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=400)

        return JSONResponse(res)
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


# -------------------------------------------------------------------------
# Action Ledger Endpoints (Audit, Modes, Idempotency)
# -------------------------------------------------------------------------

@app.get("/api/action/ledger")
async def api_action_ledger(page: int = 1, page_size: int = 20,
                            repo: Optional[str] = None, mode: Optional[str] = None):
    data = ACTION_LEDGER_STORE.list_actions(repo=repo, mode=mode, page=page, page_size=page_size)
    return JSONResponse(data)


@app.post("/api/action/execute")
async def api_action_execute(req: Request):
    """Execute or record an action with strict DRY_RUN / SHADOW / LIVE mode distinction."""
    try:
        body = await req.json()
        action = body.get("action", {})
        repo = body.get("repo", DEFAULT_REPO)
        pr_number = body.get("pr_number") or action.get("on")
        mode = str(body.get("mode", "SHADOW")).upper()
        confirmed = bool(body.get("confirmed", False))
        idempotency_key = body.get("idempotency_key")

        if mode == "LIVE":
            repo_norm = repo.strip().lower()
            allowed_repos = [r.strip().lower() for r in ALLOWED_WRITE_REPOS]
            if not allowed_repos:
                return JSONResponse(
                    {"error": "LIVE actions are disabled because KEYSTONE_WRITE_REPOS is empty."},
                    status_code=403,
                )
            if not confirmed:
                return JSONResponse(
                    {"error": "Live action requires explicit confirmation before execution."},
                    status_code=400,
                )
            if repo_norm not in allowed_repos:
                return JSONResponse(
                    {"error": f"Repository '{repo}' is not authorized for live actions."},
                    status_code=403,
                )

        entry = await run_in_threadpool(
            ACTION_LEDGER_STORE.record_action,
            action_data=action,
            repo=repo,
            pr_number=int(pr_number) if pr_number else 0,
            mode=mode,
            confirmed=confirmed,
            idempotency_key=idempotency_key
        )

        return JSONResponse({"ok": True, "action_id": entry["id"], "entry": entry})
    except Exception as e:
        logger.error(f"Action execution error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/action/clear")
async def api_action_clear():
    ACTION_LEDGER_STORE.clear()
    return JSONResponse({"ok": True, "message": "Action ledger reset"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
