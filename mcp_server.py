"""Keystone MCP server. Exposes graph tools over stdio for Claude Desktop,
Cursor, or any MCP client."""
from fastmcp import FastMCP
from tools import (
    get_pr as _get_pr,
    reviewer_candidates as _candidates,
    bus_factor_files as _bf,
    critical_files as _critical,
    explain_path as _explain,
    default_cutoff,
)
from scoring import score_reviewers

mcp = FastMCP("keystone")


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def get_pr(number: int) -> dict:
    """Fetch metadata for a pull request by number."""
    return _safe(_get_pr, number)


@mcp.tool()
def rank_reviewers(pr_number: int) -> list[dict]:
    """Rank candidate reviewers for a PR using deterministic graph scoring."""
    return _safe(score_reviewers, pr_number, default_cutoff())


@mcp.tool()
def bus_factor_files(min_reviews: int = 5) -> list[dict]:
    """Files where a single reviewer did more than 60% of reviews since cutoff."""
    return _safe(_bf, default_cutoff(), min_reviews)


@mcp.tool()
def critical_files(limit: int = 20) -> list[dict]:
    """Top files by betweenness centrality on the CO_CHANGES subgraph."""
    return _safe(_critical, limit)


@mcp.tool()
def explain_path(pr_number: int, reviewer: str) -> dict:
    """Shortest graph path from a PR's files to a candidate reviewer."""
    return _safe(_explain, pr_number, reviewer)


if __name__ == "__main__":
    mcp.run()