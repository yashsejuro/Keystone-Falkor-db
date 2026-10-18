"""All graph queries live here. Every function returns plain Python data.
No synthetic fallbacks. Instrumented, parameterized, and optimized.
"""
from typing import Optional
from datetime import datetime, timedelta, timezone

try:
    from backend.graph_client import (
        execute_graph_query, DEFAULT_REPO, validate_repo
    )
    from backend.cache import METADATA_CACHE
    from backend.centrality import get_precomputed_critical_files
except ImportError:
    from graph_client import (
        execute_graph_query, DEFAULT_REPO, validate_repo
    )
    from cache import METADATA_CACHE
    from centrality import get_precomputed_critical_files


def _rows(query: str, params: Optional[dict] = None, repo: str = DEFAULT_REPO):
    validate_repo(repo)
    res = execute_graph_query(query, params or {}, repo=repo)
    return res.result_set if hasattr(res, "result_set") else []


def get_pr(number: int, repo: str = DEFAULT_REPO) -> dict:
    rows = _rows(
        """
        MATCH (pr:PullRequest {number: $n})
        OPTIONAL MATCH (pr)<-[:AUTHORED]-(a:Person)
        OPTIONAL MATCH (pr)-[touch:TOUCHES]->(f:File)
        RETURN pr.number, pr.title, pr.state, pr.created_at, pr.merged_at,
               pr.additions, pr.deletions, pr.files_changed,
               a.login, collect(DISTINCT f.path) AS files,
               sum(coalesce(touch.additions, 0)), sum(coalesce(touch.deletions, 0)),
               collect(DISTINCT [f.path, coalesce(f.centrality, 0.0)]) AS centrality
        """,
        {"n": int(number)}, repo,
    )
    if not rows or not rows[0][0]:
        return {}
    r = rows[0]
    files = [f for f in (r[9] or []) if f is not None]
    centrality_map = {}
    if r[12]:
        for item in r[12]:
            if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] is not None:
                centrality_map[item[0]] = round(float(item[1] or 0.0), 4)

    return {
        "number": int(r[0]),
        "title": r[1] or f"PR #{number}",
        "state": r[2] or "closed",
        "created_at": r[3],
        "merged_at": r[4],
        "additions": int(r[5] or r[10] or 0),
        "deletions": int(r[6] or r[11] or 0),
        "files_changed": int(r[7] or len(files)),
        "author": r[8] or "contributor",
        "files": files,
        "centrality": centrality_map,
    }


def reviewer_candidates(pr_number: int, cutoff_iso: str, repo: str = DEFAULT_REPO) -> list[dict]:
    rows = _rows(
        """
        MATCH (pr:PullRequest {number: $pr})-[:TOUCHES]->(f:File)
        MATCH (pr)<-[:AUTHORED]-(author:Person)
        MATCH (f)<-[:TOUCHES]-(other:PullRequest)<-[:REVIEWED]-(r:Person)
        WHERE other.merged_at > $cutoff
          AND other.number <> $pr
          AND r.is_bot = false
          AND r.login <> author.login
        RETURN r.login,
               count(DISTINCT f) AS shared_files,
               count(DISTINCT other) AS recent_reviews,
               max(other.merged_at) AS last_review
        ORDER BY shared_files DESC, last_review DESC
        LIMIT 25
        """,
        {"pr": int(pr_number), "cutoff": cutoff_iso}, repo,
    )
    return [
        {
            "login": str(r[0]),
            "shared_files": int(r[1] or 0),
            "recent_reviews": int(r[2] or 0),
            "last_review": r[3],
        }
        for r in rows
    ]


def bus_factor_files(cutoff_iso: str, min_total: int = 5, repo: str = DEFAULT_REPO) -> list[dict]:
    rows = _rows(
        """
        MATCH (f:File)<-[:TOUCHES]-(pr:PullRequest)<-[:REVIEWED]-(r:Person)
        WHERE pr.merged_at > $cutoff AND r.is_bot = false
        WITH f, r, count(DISTINCT pr) AS n
        WITH f, collect({who: r.login, n: n}) AS revs, sum(n) AS total
        WITH f, revs, total,
             [x IN revs WHERE toFloat(x.n)/total >= 0.6] AS dom
        WHERE size(dom) = 1 AND total >= $min_total
        RETURN f.path, dom[0].who AS sole_reviewer, dom[0].n, total
        ORDER BY total DESC
        LIMIT 30
        """,
        {"cutoff": cutoff_iso, "min_total": int(min_total)}, repo,
    )
    return [
        {
            "path": str(r[0]),
            "sole_reviewer": str(r[1]),
            "sole_count": int(r[2] or 0),
            "total": int(r[3] or 0),
        }
        for r in rows
    ]


def critical_files(limit: int = 20, repo: str = DEFAULT_REPO) -> list[dict]:
    """Retrieve top files by reading precomputed File.centrality without running expensive algorithms."""
    data = get_precomputed_critical_files(limit=limit, repo=repo)
    return data.get("files", [])


def graph_affinity(pr_number: int, cutoff_iso: str, repo: str = DEFAULT_REPO) -> list[dict]:
    rows = _rows(
        """
        MATCH (pr:PullRequest {number: $pr})-[:TOUCHES]->(f:File)-[c:CO_CHANGES]->(f2:File)
        MATCH (f2)<-[:TOUCHES]-(other:PullRequest)<-[:REVIEWED]-(r:Person)
        MATCH (pr)<-[:AUTHORED]-(author:Person)
        WHERE other.merged_at > $cutoff AND other.number <> $pr
          AND r.is_bot = false AND r.login <> author.login
        RETURN r.login,
               sum(c.weight) AS affinity,
               count(DISTINCT f2) AS bridge_files,
               count(DISTINCT other) AS bridge_prs,
               sum(c.weight * coalesce(f2.centrality, 0.0)) AS structural
        ORDER BY structural DESC
        LIMIT 25
        """,
        {"pr": int(pr_number), "cutoff": cutoff_iso}, repo,
    )
    return [
        {
            "login": str(r[0]),
            "affinity": float(r[1] or 0.0),
            "bridge_files": int(r[2] or 0),
            "bridge_prs": int(r[3] or 0),
            "structural": float(r[4] or 0.0),
        }
        for r in rows
    ]


def pr_criticality(pr_number: int, repo: str = DEFAULT_REPO) -> dict:
    """Read structural risk from precomputed File.centrality values."""
    rows = _rows(
        """
        MATCH (pr:PullRequest {number: $pr})-[:TOUCHES]->(f:File)
        RETURN count(f), avg(coalesce(f.centrality, 0.0)), max(coalesce(f.centrality, 0.0))
        """,
        {"pr": int(pr_number)}, repo,
    )
    if not rows or rows[0][0] == 0:
        return {"files": 0, "mean_centrality": 0.0, "max_centrality": 0.0}
    n, mean, peak = rows[0]
    return {
        "files": int(n or 0),
        "mean_centrality": round(float(mean or 0.0), 4),
        "max_centrality": round(float(peak or 0.0), 4),
    }


def _node_label(kind: str, value) -> str:
    return f"PR #{value}" if kind == "PullRequest" else str(value)


def explain_path(pr_number: int, reviewer: str, repo: str = DEFAULT_REPO,
                 cutoff_iso: Optional[str] = None, cap: int = 10, max_co_hops: int = 4) -> dict:
    """Shortest evidence path from a PR to a reviewer, plus the bridges behind their score."""
    if not reviewer:
        return {
            "reviewer": "", "hops": 0, "co_change_hops": 0,
            "evidence": "none", "path": [], "path_nodes": [], "path_edges": [],
            "files": [], "via_prs": [], "direct": [], "structural_chain": [], "bridges": [],
        }

    direct = _rows(
        """
        MATCH (pr:PullRequest {number: $pr})-[:TOUCHES]->(f:File)
        MATCH (f)<-[:TOUCHES]-(other:PullRequest)<-[:REVIEWED]-(:Person {login: $rev})
        WHERE other.number <> $pr
        RETURN f.path, other.number, other.merged_at
        ORDER BY other.merged_at DESC, f.path
        LIMIT 20
        """,
        {"pr": int(pr_number), "rev": reviewer}, repo,
    )

    bridges = _rows(
        """
        MATCH (pr:PullRequest {number: $pr})-[:TOUCHES]->(f:File)-[c:CO_CHANGES]->(f2:File)
        MATCH (f2)<-[:TOUCHES]-(other:PullRequest)<-[:REVIEWED]-(:Person {login: $rev})
        WHERE other.number <> $pr AND other.merged_at > $cutoff
        WITH f, f2, c, max(other.number) AS via
        RETURN f.path, f2.path, c.weight, coalesce(f2.centrality, 0.0) AS centrality, via
        ORDER BY c.weight * centrality DESC, f2.path
        LIMIT 5
        """,
        {"pr": int(pr_number), "rev": reviewer, "cutoff": cutoff_iso or ""}, repo,
    )

    chain, co_hops = [], 0
    if direct:
        nodes = [("PullRequest", pr_number), ("File", direct[0][0]),
                 ("PullRequest", direct[0][1]), ("Person", reviewer)]
        edges = [(0, 1, "TOUCHES"), (2, 1, "TOUCHES"), (3, 2, "REVIEWED")]
        evidence = "direct_review_history"
    else:
        # Bounded shortestPath search on CO_CHANGES
        structural = _rows(
            f"""
            MATCH (:Person {{login: $rev}})-[:REVIEWED]->(v:PullRequest)-[:TOUCHES]->(b:File)
            WHERE v.number <> $pr
            WITH b, max(v.merged_at) AS last ORDER BY last DESC, b.path LIMIT $cap
            WITH collect(b) AS dst
            MATCH (:PullRequest {{number: $pr}})-[:TOUCHES]->(a:File)
            WITH dst, a ORDER BY coalesce(a.centrality, 0.0) DESC, a.path LIMIT $cap
            WITH dst, collect(a) AS src
            UNWIND src AS s
            UNWIND dst AS d
            WITH d, shortestPath((s)-[:CO_CHANGES*1..{max_co_hops}]->(d)) AS p
            WHERE p IS NOT NULL
            WITH d, p, length(p) AS hops ORDER BY hops ASC, d.path LIMIT 1
            MATCH (:Person {{login: $rev}})-[:REVIEWED]->(v:PullRequest)-[:TOUCHES]->(d)
            WHERE v.number <> $pr
            RETURN hops, [n IN nodes(p) | n.path], v.number
            ORDER BY v.merged_at DESC LIMIT 1
            """,
            {"pr": int(pr_number), "rev": reviewer, "cap": cap}, repo,
        )
        if not structural:
            return {
                "reviewer": reviewer, "hops": None, "co_change_hops": None,
                "evidence": "none", "path": [], "path_nodes": [], "path_edges": [],
                "files": [], "via_prs": [], "direct": [], "structural_chain": [], "bridges": [],
            }
        co_hops, chain, via = int(structural[0][0]), structural[0][1], structural[0][2]
        k = len(chain)
        nodes = ([("PullRequest", pr_number)] + [("File", p) for p in chain]
                 + [("PullRequest", via), ("Person", reviewer)])
        edges = ([(0, 1, "TOUCHES")] + [(i, i + 1, "CO_CHANGES") for i in range(1, k)]
                 + [(k + 1, k, "TOUCHES"), (k + 2, k + 1, "REVIEWED")])
        evidence = "shortestPath"

    return {
        "reviewer": reviewer,
        "hops": len(edges),
        "co_change_hops": co_hops,
        "evidence": evidence,
        "path": [_node_label(kind, value) for kind, value in nodes],
        "path_nodes": [{"type": kind, "id": value, "label": _node_label(kind, value)}
                       for kind, value in nodes],
        "path_edges": [{"from": a, "to": b, "type": t} for a, b, t in edges],
        "files": list(dict.fromkeys(r[0] for r in direct)),
        "via_prs": list(dict.fromkeys(r[1] for r in direct)),
        "direct": [{"file": f, "via_pr": n} for f, n in dict.fromkeys((r[0], r[1]) for r in direct)],
        "structural_chain": chain,
        "bridges": [{"from": r[0], "to": r[1], "weight": r[2],
                     "centrality": round(float(r[3]), 4), "via_pr": r[4]} for r in bridges],
    }


def graph_stats(repo: str = DEFAULT_REPO) -> dict:
    key = validate_repo(repo)
    cache_key = f"graph_stats:{key}"
    cached = METADATA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rows = _rows(
        """
        MATCH ()-[c:CO_CHANGES]->()
        WITH count(c) AS co, sum(c.weight) AS strength
        OPTIONAL MATCH (f:File) WHERE f.centrality IS NOT NULL AND f.centrality > 0
        RETURN co, strength, count(f)
        """,
        repo=key,
    )
    co_edges, strength, scored = (rows[0] if rows else [0, 0, 0])
    stats = {
        "co_change_edges": int(co_edges or 0),
        "co_change_strength": float(strength or 0.0),
        "centrality_scored_files": int(scored or 0),
    }
    METADATA_CACHE.set(cache_key, stats, ttl=45.0)
    return stats


def sample_pr(repo: str = DEFAULT_REPO) -> Optional[int]:
    key = validate_repo(repo)
    cache_key = f"sample_pr:{key}"
    cached = METADATA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rows = _rows(
        """
        MATCH (pr:PullRequest)<-[:REVIEWED]-(r:Person)
        WHERE r.is_bot = false AND pr.merged_at IS NOT NULL
        OPTIONAL MATCH (pr)-[:TOUCHES]->(f:File)
        WITH pr, count(DISTINCT r) AS reviewers, count(DISTINCT f) AS files
        WHERE reviewers >= 1 AND files >= 1
        RETURN pr.number ORDER BY pr.number DESC LIMIT 1
        """,
        repo=key,
    )
    result = int(rows[0][0]) if rows and rows[0][0] is not None else None
    METADATA_CACHE.set(cache_key, result, ttl=60.0)
    return result


def list_recent_prs(page: int = 1, page_size: int = 25, limit: int = 25,
                    repo: str = DEFAULT_REPO, q: Optional[str] = None,
                    filter_by: str = "all") -> dict:
    """Server-side paginated and filtered PR listing from FalkorDB."""
    key = validate_repo(repo)
    safe_page = max(1, page)
    safe_page_size = max(1, min(page_size or limit, 100))
    skip = (safe_page - 1) * safe_page_size

    # Build filtered query in Cypher
    where_clauses = ["pr.merged_at IS NOT NULL"]
    params: dict = {"skip": skip, "limit": safe_page_size}

    if q:
        clean_q = q.strip().lower()
        if clean_q.isdigit():
            where_clauses.append("pr.number = $pr_num")
            params["pr_num"] = int(clean_q)
        else:
            where_clauses.append("toLower(coalesce(pr.title, '')) CONTAINS $q OR toLower(coalesce(a.login, '')) CONTAINS $q")
            params["q"] = clean_q

    base_match = """
    MATCH (pr:PullRequest)
    OPTIONAL MATCH (pr)<-[:AUTHORED]-(a:Person)
    """

    where_str = " WHERE " + " AND ".join(where_clauses)

    # First aggregate files and reviews
    query = f"""
    {base_match}
    {where_str}
    OPTIONAL MATCH (pr)-[:TOUCHES]->(f:File)
    OPTIONAL MATCH (pr)<-[:REVIEWED]-(r:Person) WHERE r.is_bot = false
    WITH pr, a, count(DISTINCT f) AS file_count, count(DISTINCT r) AS reviewer_count, max(coalesce(f.centrality, 0.0)) AS max_c
    """

    # Post-aggregation review filtering
    post_filter = ""
    if filter_by == "reviewed":
        post_filter = " WHERE reviewer_count > 0"
    elif filter_by == "unreviewed":
        post_filter = " WHERE reviewer_count = 0"
    elif filter_by == "critical":
        post_filter = " WHERE max_c >= 0.08"

    full_query = f"""
    {query}
    {post_filter}
    RETURN pr.number, pr.title, pr.merged_at, a.login, file_count, reviewer_count, max_c
    ORDER BY pr.number DESC
    SKIP $skip
    LIMIT $limit
    """

    rows = _rows(full_query, params, repo=key)

    prs = []
    for r in rows:
        max_c = float(r[6] or 0.0)
        if max_c >= 0.20:
            risk_tier = "Critical Architecture"
            risk_color = "red"
        elif max_c >= 0.08:
            risk_tier = "High Risk"
            risk_color = "amber"
        elif max_c > 0.01:
            risk_tier = "Moderate Risk"
            risk_color = "indigo"
        else:
            risk_tier = "Standard Change"
            risk_color = "slate"

        prs.append({
            "number": int(r[0]),
            "title": str(r[1] or f"PR #{r[0]}"),
            "merged_at": str(r[2]) if r[2] else None,
            "author": str(r[3] or "contributor"),
            "file_count": int(r[4] or 0),
            "reviewer_count": int(r[5] or 0),
            "is_reviewed": int(r[5] or 0) > 0,
            "max_centrality": round(max_c, 4),
            "risk_tier": risk_tier,
            "risk_color": risk_color,
        })

    # Get total count for pagination metadata
    stats = get_repo_pr_stats(key)

    return {
        "repo": key,
        "prs": prs,
        "count": len(prs),
        "page": safe_page,
        "page_size": safe_page_size,
        "stats": stats,
    }


def get_repo_pr_stats(repo: str = DEFAULT_REPO) -> dict:
    key = validate_repo(repo)
    cache_key = f"pr_stats:{key}"
    cached = METADATA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rows = _rows(
        """
        MATCH (pr:PullRequest)
        OPTIONAL MATCH (pr)<-[:REVIEWED]-(r:Person) WHERE r.is_bot = false
        WITH pr, count(DISTINCT r) AS rev_count
        RETURN count(pr) AS total_prs,
               sum(CASE WHEN rev_count > 0 THEN 1 ELSE 0 END) AS reviewed_prs,
               sum(CASE WHEN rev_count = 0 THEN 1 ELSE 0 END) AS unreviewed_prs
        """,
        repo=key
    )
    if not rows:
        stats = {"total": 0, "reviewed": 0, "unreviewed": 0}
    else:
        total, reviewed, unreviewed = rows[0]
        stats = {
            "total": int(total or 0),
            "reviewed": int(reviewed or 0),
            "unreviewed": int(unreviewed or 0),
        }

    METADATA_CACHE.set(cache_key, stats, ttl=30.0)
    return stats


def default_cutoff(days: int = 90) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()