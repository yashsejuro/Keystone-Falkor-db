"""All graph queries live here. Every function returns plain Python data.
No synthetic fallbacks. If FalkorDB is unreachable, queries raise."""
from graph_client import get_graph, DEFAULT_REPO
from datetime import datetime, timedelta, timezone


def _rows(query, params=None, repo: str = DEFAULT_REPO):
    g = get_graph(repo)
    return g.query(query, params or {}).result_set


def get_pr(number: int, repo: str = DEFAULT_REPO) -> dict:
    rows = _rows(
        """
        MATCH (pr:PullRequest {number: $n})
        OPTIONAL MATCH (pr)<-[:AUTHORED]-(a:Person)
        OPTIONAL MATCH (pr)-[:TOUCHES]->(f:File)
        RETURN pr.number, pr.title, pr.state, pr.created_at, pr.merged_at,
               pr.additions, pr.deletions, pr.files_changed,
               a.login, collect(DISTINCT f.path) AS files
        """,
        {"n": number}, repo,
    )
    if not rows:
        return {}
    r = rows[0]
    return {
        "number": r[0], "title": r[1], "state": r[2],
        "created_at": r[3], "merged_at": r[4],
        "additions": r[5], "deletions": r[6], "files_changed": r[7],
        "author": r[8], "files": r[9],
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


def explain_path(pr_number: int, reviewer: str, repo: str = DEFAULT_REPO) -> dict:
    rows = _rows(
        """
        MATCH (pr:PullRequest {number: $pr})-[:TOUCHES]->(f:File)
        MATCH (f)<-[:TOUCHES]-(other:PullRequest)<-[:REVIEWED]-(r:Person {login: $rev})
        WHERE other.number <> $pr
        RETURN f.path AS file,
               other.number AS via_pr,
               other.merged_at AS merged_at
        ORDER BY other.merged_at DESC
        LIMIT 20
        """,
        {"pr": pr_number, "rev": reviewer}, repo,
    )
    if not rows:
        return {"reviewer": reviewer, "hops": None, "path": [], "files": [], "via_prs": []}
    files, seen = [], set()
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0])
            files.append(r[0])
    return {
        "reviewer": reviewer,
        "hops": 2,
        "path": [f"PR #{pr_number}"] + files + [reviewer],
        "files": files,
        "via_prs": [r[1] for r in rows],
    }


def default_cutoff(days: int = 90) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


if __name__ == "__main__":
    print("PR 14000:", get_pr(14000))
    print("Candidates:", reviewer_candidates(13997, default_cutoff())[:3])