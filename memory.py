"""Agent memory stored in FalkorDB, inside the same graph as the evidence it came from.

(:Investigation)-[:ABOUT]->(:PullRequest)
(:Investigation)-[:RECOMMENDED {rank, score, ...}]->(:Person)
(:Investigation)-[:PROPOSED]->(:Action)-[:TARGETS]->(:Person)

Approval state lives on the Action node, so a proposal made by one client (the web UI or
an MCP agent) can be approved from another, and nothing executes twice.
"""
import uuid
from datetime import datetime, timezone

from graph_client import DEFAULT_REPO, get_graph

_INDEXED: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _graph(repo: str):
    g = get_graph(repo)
    if repo not in _INDEXED:
        for label in ("Investigation", "Action"):
            try:
                g.query(f"CREATE INDEX FOR (n:{label}) ON (n.id)")
            except Exception as exc:
                if "already indexed" not in str(exc):
                    raise
        _INDEXED.add(repo)
    return g


def _clean(props: dict) -> dict:
    return {k: v for k, v in props.items() if v is not None}


def record_investigation(result: dict, repo: str = DEFAULT_REPO, source: str = "ui") -> str | None:
    """Persist an investigation and its proposed actions, assigning ids in place.

    Returns None when the PR is not in the graph, in which case nothing is written.
    """
    pr_number = result["pr_number"]
    decision = result.get("decision", {})
    top = result.get("explain_path") or {}
    inv_id = uuid.uuid4().hex[:12]
    at = _now()
    g = _graph(repo)

    created = g.query(
        """
        MATCH (pr:PullRequest {number: $pr})
        CREATE (i:Investigation)-[:ABOUT]->(pr)
        SET i = $props
        RETURN i.id
        """,
        {"pr": pr_number, "props": _clean({
            "id": inv_id, "pr": pr_number, "question": result.get("question"),
            "asked_at": at, "source": source, "rationale": decision.get("rationale"),
            "flags": decision.get("risk_flags", []), "hops": top.get("hops"),
            "evidence": top.get("evidence"), "path": top.get("path", []),
        })},
    ).result_set
    if not created:
        return None

    recs = [{"login": r["login"], "rank": rank, "score": float(r["score"]),
             "structural": float(r.get("structural", 0)), "shared_files": int(r.get("shared_files", 0))}
            for rank, r in enumerate(decision.get("reviewers", []), start=1)]
    if recs:
        g.query(
            """
            MATCH (i:Investigation {id: $id})
            UNWIND $recs AS rec
            MATCH (p:Person {login: rec.login})
            CREATE (i)-[:RECOMMENDED {rank: rec.rank, score: rec.score,
                                      structural: rec.structural, shared_files: rec.shared_files}]->(p)
            """,
            {"id": inv_id, "recs": recs},
        )

    rows = []
    for action in result.get("proposed_actions", []):
        action["id"] = uuid.uuid4().hex[:12]
        action["status"] = "proposed"
        rows.append(_clean({
            "id": action["id"], "kind": action["action"], "pr": pr_number,
            "who": action.get("who"), "label": action.get("label"), "rank": action.get("rank"),
            "reason": action.get("reason"), "evidence": action.get("evidence"),
            "hops": action.get("hops"), "evidence_path": action.get("evidence_path"),
            "mode": action.get("mode"), "target": action.get("target"),
            "status": "proposed", "proposed_at": at, "source": source,
        }))
    if rows:
        g.query(
            """
            MATCH (i:Investigation {id: $id})
            UNWIND $rows AS row
            CREATE (i)-[:PROPOSED]->(x:Action)
            SET x = row
            """,
            {"id": inv_id, "rows": rows},
        )
        g.query(
            """
            MATCH (x:Action) WHERE x.id IN $ids AND x.who IS NOT NULL
            MATCH (p:Person {login: x.who})
            CREATE (x)-[:TARGETS]->(p)
            """,
            {"ids": [r["id"] for r in rows]},
        )
    return inv_id


def get_action(action_id: str, repo: str = DEFAULT_REPO) -> dict | None:
    rows = _graph(repo).query(
        "MATCH (x:Action {id: $id}) RETURN x", {"id": action_id},
    ).result_set
    return dict(rows[0][0].properties) if rows else None


def claim_action(action_id: str, repo: str = DEFAULT_REPO) -> dict | None:
    """Move a proposed (or previously failed) action to executing.

    A single conditional write, so two concurrent approvals cannot both claim it.
    """
    rows = _graph(repo).query(
        """
        MATCH (x:Action {id: $id}) WHERE x.status IN ['proposed', 'failed']
        SET x.status = 'executing', x.claimed_at = $at, x.attempts = coalesce(x.attempts, 0) + 1
        RETURN x
        """,
        {"id": action_id, "at": _now()},
    ).result_set
    return dict(rows[0][0].properties) if rows else None


def finish_action(action_id: str, outcome: dict, repo: str = DEFAULT_REPO) -> None:
    _graph(repo).query(
        """
        MATCH (x:Action {id: $id})
        SET x += $props, x.error = $error
        """,
        {"id": action_id, "error": None if outcome.get("ok") else outcome.get("error", "failed"),
         "props": _clean({
             "status": "executed" if outcome.get("ok") else "failed",
             "finished_at": _now(), "mode": outcome.get("mode"), "url": outcome.get("url"),
             "target_repo": outcome.get("target_repo"),
             "target_number": outcome.get("target_number"),
         })},
    )


def tracking_issue_number(pr_number: int, target_repo: str, repo: str = DEFAULT_REPO) -> int | None:
    """The sandbox issue that earlier shadow-mode actions for this PR were written to."""
    rows = _graph(repo).query(
        """
        MATCH (x:Action {pr: $pr})
        WHERE x.status = 'executed' AND x.mode = 'shadow' AND x.target_repo = $target
              AND x.target_number IS NOT NULL
        RETURN x.target_number ORDER BY x.finished_at DESC LIMIT 1
        """,
        {"pr": pr_number, "target": target_repo},
    ).result_set
    return rows[0][0] if rows else None
