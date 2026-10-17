"""All graph queries live here. Every function returns plain Python data.
No synthetic fallbacks. If FalkorDB is unreachable, queries raise."""
try:
    from backend.graph_client import get_graph, DEFAULT_REPO, validate_repo
except ImportError:
    from graph_client import get_graph, DEFAULT_REPO, validate_repo
from datetime import datetime, timedelta, timezone


def _rows(query, params=None, repo: str = DEFAULT_REPO):
    validate_repo(repo)
    g = get_graph(repo)
    return g.query(query, params or {}).result_set


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
             collect(DISTINCT [f.path, coalesce(f.centrality, 0)]) AS centrality
        """,
        {"n": number}, repo,
    )
    if not rows:
        return {}
    r = rows[0]
    files = r[9] or []
    return {
        "number": r[0], "title": r[1], "state": r[2],
        "created_at": r[3], "merged_at": r[4],
        "additions": r[5] or r[10], "deletions": r[6] or r[11],
        "files_changed": r[7] or len(files),
        "author": r[8], "files": files,
        "centrality": {path: round(float(c), 4) for path, c in r[12] if path is not None},
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
        {"pr": pr_number, "cutoff": cutoff_iso}, repo,
    )
    return [
        {"login": r[0], "shared_files": r[1],
         "recent_reviews": r[2], "last_review": r[3]}
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
        {"cutoff": cutoff_iso, "min_total": min_total}, repo,
    )
    return [
        {"path": r[0], "sole_reviewer": r[1], "sole_count": r[2], "total": r[3]}
        for r in rows
    ]


def critical_files(limit: int = 20, repo: str = DEFAULT_REPO) -> list[dict]:
    """Top files by betweenness centrality on the CO_CHANGES subgraph.

    Filters out docs and markdown, which co-change with everything and
    would dominate the ranking without being architecturally meaningful.

    No fallback. If the algorithm errors, the exception propagates.
    """
    rows = _rows(
        """
        CALL algo.betweenness({
            nodeLabels: ['File'],
            relationshipTypes: ['CO_CHANGES']
        }) YIELD node, score
        WHERE NOT node.path STARTS WITH 'docs/'
          AND NOT node.path STARTS WITH 'website/'
          AND NOT node.path ENDS WITH '.md'
        RETURN node.path, score
        ORDER BY score DESC
        LIMIT $limit
        """,
        {"limit": limit}, repo,
    )
    return [{"path": r[0], "score": r[1]} for r in rows]


def graph_affinity(pr_number: int, cutoff_iso: str, repo: str = DEFAULT_REPO) -> list[dict]:
    """Centrality-weighted co-change proximity per candidate reviewer.

    Walks PR -> File -> CO_CHANGES -> File <- PR <- Reviewer, so a candidate is
    credited for reviewing files that change *alongside* this PR's files, not only
    for the files named in it. Each bridge is weighted by the CO_CHANGES count and
    by the bridge file's betweenness centrality, which is stored on the node by
    ingest_service.materialize_file_centrality.
    """
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
               sum(c.weight * coalesce(f2.centrality, 0)) AS structural
        ORDER BY structural DESC
        LIMIT 25
        """,
        {"pr": pr_number, "cutoff": cutoff_iso}, repo,
    )
    return [
        {"login": r[0], "affinity": float(r[1] or 0), "bridge_files": r[2],
         "bridge_prs": r[3], "structural": float(r[4] or 0)}
        for r in rows
    ]


def pr_criticality(pr_number: int, repo: str = DEFAULT_REPO) -> dict:
    """How structurally load-bearing this PR is, from materialised betweenness."""
    rows = _rows(
        """
        MATCH (pr:PullRequest {number: $pr})-[:TOUCHES]->(f:File)
        RETURN count(f), avg(coalesce(f.centrality, 0)), max(coalesce(f.centrality, 0))
        """,
        {"pr": pr_number}, repo,
    )
    if not rows or rows[0][0] == 0:
        return {"files": 0, "mean_centrality": 0.0, "max_centrality": 0.0}
    n, mean, peak = rows[0]
    return {"files": n, "mean_centrality": round(float(mean or 0), 4),
            "max_centrality": round(float(peak or 0), 4)}


def _node_label(kind: str, value) -> str:
    return f"PR #{value}" if kind == "PullRequest" else str(value)


def explain_path(pr_number: int, reviewer: str, repo: str = DEFAULT_REPO,
                 cutoff_iso: str | None = None, cap: int = 10, max_co_hops: int = 4) -> dict:
    """Shortest evidence path from a PR to a reviewer, plus the bridges behind their score.

    The PR's own reviews are excluded, so the shortest possible path is 3 edges:
    PR -TOUCHES-> File <-TOUCHES- PR <-REVIEWED- Person. Without that direct history,
    shortestPath() searches the CO_CHANGES subgraph between the PR's files and the files
    the reviewer has reviewed, and the co-change hops are added to those 3 edges.
    """
    direct = _rows(
        """
        MATCH (pr:PullRequest {number: $pr})-[:TOUCHES]->(f:File)
        MATCH (f)<-[:TOUCHES]-(other:PullRequest)<-[:REVIEWED]-(:Person {login: $rev})
        WHERE other.number <> $pr
        RETURN f.path, other.number, other.merged_at
        ORDER BY other.merged_at DESC, f.path
        LIMIT 20
        """,
        {"pr": pr_number, "rev": reviewer}, repo,
    )
    bridges = _rows(
        """
        MATCH (pr:PullRequest {number: $pr})-[:TOUCHES]->(f:File)-[c:CO_CHANGES]->(f2:File)
        MATCH (f2)<-[:TOUCHES]-(other:PullRequest)<-[:REVIEWED]-(:Person {login: $rev})
        WHERE other.number <> $pr AND other.merged_at > $cutoff
        WITH f, f2, c, max(other.number) AS via
        RETURN f.path, f2.path, c.weight, coalesce(f2.centrality, 0) AS centrality, via
        ORDER BY c.weight * centrality DESC, f2.path
        LIMIT 5
        """,
        {"pr": pr_number, "rev": reviewer, "cutoff": cutoff_iso or ""}, repo,
    )

    chain, co_hops = [], 0
    if direct:
        nodes = [("PullRequest", pr_number), ("File", direct[0][0]),
                 ("PullRequest", direct[0][1]), ("Person", reviewer)]
        edges = [(0, 1, "TOUCHES"), (2, 1, "TOUCHES"), (3, 2, "REVIEWED")]
        evidence = "direct_review_history"
    else:
        # FalkorDB only allows shortestPath in WITH/RETURN and only on directed
        # traversals, which is why CO_CHANGES is written in both directions.
        structural = _rows(
            f"""
            MATCH (:Person {{login: $rev}})-[:REVIEWED]->(v:PullRequest)-[:TOUCHES]->(b:File)
            WHERE v.number <> $pr
            WITH b, max(v.merged_at) AS last ORDER BY last DESC, b.path LIMIT $cap
            WITH collect(b) AS dst
            MATCH (:PullRequest {{number: $pr}})-[:TOUCHES]->(a:File)
            WITH dst, a ORDER BY coalesce(a.centrality, 0) DESC, a.path LIMIT $cap
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
            {"pr": pr_number, "rev": reviewer, "cap": cap}, repo,
        )
        if not structural:
            return {"reviewer": reviewer, "hops": None, "co_change_hops": None,
                    "evidence": "none", "path": [], "path_nodes": [], "path_edges": [],
                    "files": [], "via_prs": [], "structural_chain": [], "bridges": []}
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
    """Substrate the graph algorithms actually have to work with."""
    rows = _rows(
        """
        MATCH ()-[c:CO_CHANGES]->()
        WITH count(c) AS co, sum(c.weight) AS strength
        OPTIONAL MATCH (f:File) WHERE f.centrality IS NOT NULL
        RETURN co, strength, count(f)
        """,
        repo=repo,
    )
    co_edges, strength, scored = (rows[0] if rows else [0, 0, 0])
    return {"co_change_edges": co_edges, "co_change_strength": float(strength or 0),
            "centrality_scored_files": scored}


def sample_pr(repo: str = DEFAULT_REPO) -> int | None:
    """A recent real PR with enough review history to produce an answer.

    Used by the landing page so its example is live rather than a scripted showcase.
    """
    rows = _rows(
        """
        MATCH (pr:PullRequest)<-[:REVIEWED]-(r:Person)
        WHERE r.is_bot = false AND pr.merged_at IS NOT NULL
        OPTIONAL MATCH (pr)-[:TOUCHES]->(f:File)
        WITH pr, count(DISTINCT r) AS reviewers, count(DISTINCT f) AS files
        WHERE reviewers >= 2 AND files >= 3
        RETURN pr.number ORDER BY pr.number DESC LIMIT 1
        """,
        repo=repo,
    )
    return rows[0][0] if rows else None


def list_recent_prs(limit: int = 500, repo: str = DEFAULT_REPO, q: str | None = None, filter_by: str = "all") -> list[dict]:
    """Return real merged pull requests from FalkorDB for the specified repository.
    Supports up to 500 PRs with search and review status filtering.
    """
    rows = _rows(
        """
        MATCH (pr:PullRequest)
        WHERE pr.merged_at IS NOT NULL
        OPTIONAL MATCH (pr)<-[:AUTHORED]-(a:Person)
        OPTIONAL MATCH (pr)-[:TOUCHES]->(f:File)
        OPTIONAL MATCH (pr)<-[:REVIEWED]-(r:Person) WHERE r.is_bot = false
        WITH pr, a, count(DISTINCT f) AS file_count, count(DISTINCT r) AS reviewer_count
        RETURN pr.number, pr.title, pr.merged_at, a.login, file_count, reviewer_count
        ORDER BY pr.number DESC
        LIMIT $limit
        """,
        {"limit": limit or 500}, repo=repo,
    )
    results = [
        {
            "number": int(r[0]),
            "title": str(r[1] or f"PR #{r[0]}"),
            "merged_at": str(r[2]) if r[2] else None,
            "author": str(r[3] or "contributor"),
            "file_count": int(r[4] or 0),
            "reviewer_count": int(r[5] or 0),
            "is_reviewed": int(r[5] or 0) > 0,
        }
        for r in rows
    ]

    if q:
        q_lower = q.lower().strip()
        results = [
            p for p in results
            if q_lower in str(p["number"]) or q_lower in p["title"].lower() or q_lower in p["author"].lower()
        ]

    if filter_by == "reviewed":
        results = [p for p in results if p["reviewer_count"] > 0]
    elif filter_by == "unreviewed":
        results = [p for p in results if p["reviewer_count"] == 0]

    return results


def get_repo_pr_stats(repo: str = DEFAULT_REPO) -> dict:
    """Return statistical summary of all ingested pull requests in the repository."""
    rows = _rows(
        """
        MATCH (pr:PullRequest)
        OPTIONAL MATCH (pr)<-[:REVIEWED]-(r:Person) WHERE r.is_bot = false
        WITH pr, count(DISTINCT r) AS rev_count
        RETURN count(pr) AS total_prs,
               sum(CASE WHEN rev_count > 0 THEN 1 ELSE 0 END) AS reviewed_prs,
               sum(CASE WHEN rev_count = 0 THEN 1 ELSE 0 END) AS unreviewed_prs
        """,
        repo=repo
    )
    if not rows:
        return {"total": 0, "reviewed": 0, "unreviewed": 0}
    total, reviewed, unreviewed = rows[0]
    return {
        "total": int(total or 0),
        "reviewed": int(reviewed or 0),
        "unreviewed": int(unreviewed or 0),
    }


def default_cutoff(days: int = 90) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


if __name__ == "__main__":
    print("PR 14000:", get_pr(14000))
    print("Candidates:", reviewer_candidates(13997, default_cutoff())[:3])