"""Keystone agent: plan -> tools -> decide -> propose actions.
Deterministic reviewer routing on FalkorDB graphs without LLM in the decision loop.
"""
from datetime import datetime, timezone
from typing import Optional

try:
    from backend.tools import (
        get_pr, reviewer_candidates, bus_factor_files,
        critical_files, default_cutoff, pr_criticality, explain_path,
    )
    from backend.scoring import score_reviewers
except ImportError:
    from tools import (
        get_pr, reviewer_candidates, bus_factor_files,
        critical_files, default_cutoff, pr_criticality, explain_path,
    )
    from scoring import score_reviewers

CRITICAL_PATH_THRESHOLD = 0.5


def plan(pr_number: int, question: str = "who should review this?", repo: str = "pydantic") -> list[str]:
    """Select tools based on the question via deterministic routing."""
    q = (question or "").lower()

    critical_kw = ["critical", "central", "bridge", "betweenness", "architectural"]
    bus_factor_kw = ["bus factor", "bus-factor", "coverage", "risk", "leaves", "leaving", "single point"]
    reviewer_kw = ["review", "reviewer", "who should", "page", "assign"]

    tools = []

    if any(k in q for k in critical_kw):
        tools.append("critical_files")
    if any(k in q for k in bus_factor_kw):
        tools.append("bus_factor_files")
    if any(k in q for k in reviewer_kw) or not tools:
        tools.insert(0, "rank_reviewers")

    if "bus_factor_files" not in tools:
        tools.append("bus_factor_files")
    if "rank_reviewers" not in tools:
        tools.insert(0, "rank_reviewers")

    return tools


def run_tools(pr_number: int, planned: list[str], repo: str = "pydantic",
              cutoff: Optional[str] = None) -> dict:
    cutoff = cutoff or default_cutoff()
    obs = {}
    if "rank_reviewers" in planned:
        obs["rank_reviewers"] = score_reviewers(pr_number, cutoff, repo=repo)
    if "bus_factor_files" in planned:
        obs["bus_factor_files"] = bus_factor_files(cutoff, repo=repo)
    if "critical_files" in planned:
        obs["critical_files"] = critical_files(repo=repo)
    return obs


def decide(pr_number: int, obs: dict, pr_info: Optional[dict] = None, repo: str = "pydantic") -> dict:
    """Evaluate candidate reviewers and graph risk signals without duplicate queries."""
    ranked = obs.get("rank_reviewers", [])
    # Filter candidates with meaningful score
    filtered_candidates = [r for r in ranked if r.get("score", 0) >= 0.15]
    top2 = filtered_candidates[:2]

    pr = pr_info if pr_info is not None else get_pr(pr_number, repo=repo)
    pr_files = sorted(set(pr.get("files", [])))

    bf = {b["path"]: b for b in obs.get("bus_factor_files", [])}
    risks = []
    for f in pr_files:
        if f in bf:
            b = bf[f]
            risks.append({
                "flag": f"risk:coverage-gap:{f}",
                "label": "risk:coverage-gap",
                "detail": f"{f}: {b['sole_reviewer']} did {b['sole_count']} of {b['total']} recent reviews",
            })

    if top2 and top2[0].get("last_review"):
        try:
            t = datetime.fromisoformat(top2[0]["last_review"].replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - t).days
            if days > 180:
                risks.append({
                    "flag": "risk:stale-reviewer",
                    "label": "risk:stale-reviewer",
                    "detail": f"Top reviewer last reviewed {days} days ago",
                })
        except Exception:
            pass

    criticality = pr_criticality(pr_number, repo=repo)
    if criticality.get("max_centrality", 0.0) >= CRITICAL_PATH_THRESHOLD:
        risks.append({
            "flag": "risk:critical-path",
            "label": "risk:critical-path",
            "detail": f"Changed files peak at {criticality['max_centrality']} normalised betweenness",
        })

    top = top2[0] if top2 else None
    if top:
        rationale = (
            f"Recommended primary reviewer @{top['login']} shares {top['shared_files']} files with this PR "
            f"and reviewed {top['recent_reviews']} PRs recently. Connected through {top['bridge_files']} "
            f"co-changing bridge files with structural score {top['structural']}."
        )
    else:
        rationale = "No suitable reviewer was found from the currently ingested review history."

    return {
        "reviewers": top2,
        "risk_flags": [r["flag"] for r in risks],
        "risks": risks,
        "criticality": criticality,
        "rationale": rationale,
    }


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def propose_actions(pr_number: int, decision: dict, evidence: Optional[dict] = None) -> list[dict]:
    evidence = evidence or {}
    actions = []
    for rank, r in enumerate(decision.get("reviewers", []), start=1):
        login = r["login"]
        path = evidence.get(login) or {}
        actions.append({
            "action": "request_review",
            "who": login,
            "on": pr_number,
            "rank": rank,
            "role": "Primary Reviewer" if rank == 1 else "Secondary / Backup Reviewer",
            "reason": (f"Rank {rank}, score {r['score']:.2f}: {_count(r['shared_files'], 'shared file')}, "
                       f"{_count(r['bridge_files'], 'bridge file')}, "
                       f"{_count(r['recent_reviews'], 'recent review')}"),
            "evidence": path.get("evidence", "none"),
            "hops": path.get("hops"),
            "evidence_path": path.get("path", []),
        })

    details_by_label: dict[str, list[str]] = {}
    for risk in decision.get("risks", []):
        details_by_label.setdefault(risk["label"], []).append(risk["detail"])
    for label, details in details_by_label.items():
        actions.append({
            "action": "add_label",
            "label": label,
            "on": pr_number,
            "reason": "; ".join(details),
        })

    return actions


def run_keystone(pr_number: int, question: str = "who should review this?", repo: str = "pydantic") -> dict:
    """End-to-end investigation run avoiding duplicate graph queries."""
    trace = []
    trace.append(f"START: PR #{pr_number} on {repo}, question='{question}'")
    cutoff = default_cutoff()

    # 1. Fetch PR metadata once
    pr_info = get_pr(pr_number, repo=repo)

    # 2. Plan and run tools
    planned = plan(pr_number, question=question, repo=repo)
    trace.append(f"PLAN: {planned}")

    obs = run_tools(pr_number, planned, repo=repo, cutoff=cutoff)
    counts = ", ".join(
        f"{k} -> {len(v) if isinstance(v, list) else 'ok'}"
        for k, v in obs.items()
    )
    trace.append(f"TOOLS: {counts}")

    # 3. Decide using pre-fetched PR info
    decision = decide(pr_number, obs, pr_info=pr_info, repo=repo)
    picked_logins = [r["login"] for r in decision["reviewers"]]
    trace.append(f"DECIDE: picked {picked_logins}; flags={decision['risk_flags']}")

    # 4. Generate evidence paths only for picked reviewers (no duplicate calls)
    evidence = {}
    for r in decision["reviewers"]:
        login = r["login"]
        ep = explain_path(pr_number, login, repo=repo, cutoff_iso=cutoff)
        evidence[login] = ep
        if ep.get("path"):
            trace.append(f"EVIDENCE {login}: {ep['evidence']} over {ep['hops']} hops: {' -> '.join(ep['path'])}")
        else:
            trace.append(f"EVIDENCE {login}: no connected path found")

    top_evidence = evidence.get(picked_logins[0]) if picked_logins else None

    # 5. Propose actions
    actions = propose_actions(pr_number, decision, evidence)
    trace.append(f"ACT: proposed {len(actions)} actions (awaiting approval)")

    return {
        "pr_number": pr_number,
        "repo": repo,
        "question": question,
        "trace": trace,
        "observations": obs,
        "decision": decision,
        "pr_details": pr_info,
        "explain_path": top_evidence,
        "reviewer_evidence": evidence,
        "proposed_actions": actions,
    }