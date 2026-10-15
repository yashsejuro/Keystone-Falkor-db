"""All graph queries live here. Every function returns plain Python data."""
from graph_client import get_graph
from datetime import datetime, timedelta, timezone


def _rows(query, params=None):
    g = get_graph()
    return g.query(query, params or {}).result_set


def get_pr(number: int) -> dict:
    rows = _rows(
        """
        MATCH (pr:PullRequest {number: $n})
        OPTIONAL MATCH (pr)<-[:AUTHORED]-(a:Person)
        OPTIONAL MATCH (pr)-[:TOUCHES]->(f:File)
        RETURN pr.number, pr.title, pr.state, pr.created_at, pr.merged_at,
               pr.additions, pr.deletions, pr.files_changed,
               a.login, collect(DISTINCT f.path) AS files
        """,
        {"n": number},
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


def reviewer_candidates(pr_number: int, cutoff_iso: str) -> list[dict]:
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
        {"pr": pr_number, "cutoff": cutoff_iso},
    )
    return [
        {"login": r[0], "shared_files": r[1],
         "recent_reviews": r[2], "last_review": r[3]}
        for r in rows
    ]

def bus_factor_files(cutoff_iso: str, min_total: int = 5) -> list[dict]:
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
        {"cutoff": cutoff_iso, "min_total": min_total},
    )
    return [
        {"path": r[0], "sole_reviewer": r[1], "sole_count": r[2], "total": r[3]}
        for r in rows
    ]


def critical_files(limit: int = 20) -> list[dict]:
    """Betweenness on CO_CHANGES. Falls back to TOUCHES count if graph is empty."""
    try:
        rows = _rows(
            """
            CALL algo.betweenness.stream('File', 'CO_CHANGES')
            YIELD node, score
            RETURN node.path, score
            ORDER BY score DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )
        if rows:
            return [{"path": r[0], "score": r[1]} for r in rows]
    except Exception:
        pass

    rows = _rows(
        """
        MATCH (f:File)<-[:TOUCHES]-()
        RETURN f.path, count(*) AS score
        ORDER BY score DESC
        LIMIT $limit
        """,
        {"limit": limit},
    )
    return [{"path": r[0], "score": r[1]} for r in rows]


def explain_path(pr_number: int, reviewer: str) -> dict:
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
        {"pr": pr_number, "rev": reviewer},
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
    print("PR 1:", get_pr(1))
    print("Candidates:", reviewer_candidates(1, default_cutoff()))
    print("Critical:", critical_files(5))