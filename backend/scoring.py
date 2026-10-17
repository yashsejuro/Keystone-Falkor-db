"""Deterministic reviewer scoring. No LLM. Pure graph + math.

`use_graph=False` drops the CO_CHANGES/betweenness term and leaves the relational
shared-file baseline, which is what backtest.py ablates to show the graph is doing
real work rather than acting as a store for joins.
"""
import math
from datetime import datetime, timezone
try:
    from backend.tools import reviewer_candidates, graph_affinity, DEFAULT_REPO
except ImportError:
    from tools import reviewer_candidates, graph_affinity, DEFAULT_REPO

WEIGHTS_RELATIONAL = {"shared": 0.60, "recent": 0.20, "recency": 0.20}
WEIGHTS_GRAPH = {"shared": 0.30, "structural": 0.30, "recent": 0.20, "recency": 0.20}


def _days_since(iso: str) -> float:
    if not iso:
        return 999.0
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        secs = (datetime.now(timezone.utc) - t).total_seconds()
        return max(0.0, secs / 86400.0)
    except Exception:
        return 999.0


def score_reviewers(pr_number: int, cutoff_iso: str, repo: str = DEFAULT_REPO,
                    use_graph: bool = True) -> list[dict]:
    candidates = {c["login"]: dict(c) for c in reviewer_candidates(pr_number, cutoff_iso, repo)}
    bridges = {a["login"]: a for a in graph_affinity(pr_number, cutoff_iso, repo)} if use_graph else {}

    logins = set(candidates) | set(bridges)
    if not logins:
        return []

    for login in logins:
        candidates.setdefault(login, {
            "login": login, "shared_files": 0, "recent_reviews": 0, "last_review": None,
        })

    max_shared = max(c["shared_files"] for c in candidates.values()) or 1
    max_recent = max(c["recent_reviews"] for c in candidates.values()) or 1
    max_structural = max((b["structural"] for b in bridges.values()), default=0) or 1

    weights = WEIGHTS_GRAPH if use_graph else WEIGHTS_RELATIONAL
    scored = []
    for login in logins:
        c = candidates[login]
        b = bridges.get(login, {"affinity": 0.0, "bridge_files": 0, "bridge_prs": 0, "structural": 0.0})

        shared_norm = c["shared_files"] / max_shared
        recent_norm = c["recent_reviews"] / max_recent
        structural_norm = b["structural"] / max_structural
        recency = math.exp(-_days_since(c["last_review"]) / 60.0)
        overload = 0.7 if c["recent_reviews"] > 20 else 1.0

        parts = {
            "shared": weights["shared"] * shared_norm,
            "recent": weights["recent"] * recent_norm,
            "recency": weights["recency"] * recency,
        }
        if use_graph:
            parts["structural"] = weights["structural"] * structural_norm

        scored.append({
            **c,
            "affinity": round(b["affinity"], 2),
            "bridge_files": b["bridge_files"],
            "bridge_prs": b["bridge_prs"],
            "structural": round(b["structural"], 3),
            "components": {k: round(v, 4) for k, v in parts.items()},
            "score": round(sum(parts.values()) * overload, 4),
        })

    # Deterministic tie-break. Set iteration order depends on PYTHONHASHSEED, so
    # without this a tied candidate can win top-1 in one run and lose it in the next,
    # which makes the reported benchmark unreproducible.
    scored.sort(key=lambda x: (-x["score"], -x["shared_files"], -x["recent_reviews"],
                               -x["structural"], x["login"]))
    return scored


if __name__ == "__main__":
    from tools import default_cutoff
    for r in score_reviewers(1, default_cutoff()):
        print(f"{r['login']:20s} score={r['score']:.3f} "
              f"shared={r['shared_files']} recent={r['recent_reviews']} "
              f"structural={r['structural']}")
