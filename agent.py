"""Keystone agent: plan -> tools -> decide -> propose actions.
No LLM in the decision path. Optional LLM narration later."""
from datetime import datetime, timezone
from tools import (
    get_pr, reviewer_candidates, bus_factor_files,
    critical_files, default_cutoff, pr_criticality, explain_path,
)
from scoring import score_reviewers


# A PR touching a file in the top betweenness tier concentrates risk regardless of
# how well-reviewed it is, so this is checked independently of the bus-factor flags.
CRITICAL_PATH_THRESHOLD = 0.5


def plan(pr_number: int, question: str = "who should review this?", repo: str = "pydantic") -> list[str]:
    """Select tools based on the question. Deterministic keyword routing.

    No LLM. If we add LLM routing later, this stays as the fallback path.
    """
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
              cutoff: str | None = None) -> dict:
    cutoff = cutoff or default_cutoff()
    obs = {}
    if "rank_reviewers" in planned:
        obs["rank_reviewers"] = score_reviewers(pr_number, cutoff, repo=repo)
    if "bus_factor_files" in planned:
        obs["bus_factor_files"] = bus_factor_files(cutoff, repo=repo)
    if "critical_files" in planned:
        obs["critical_files"] = critical_files(repo=repo)
    return obs


def decide(pr_number: int, obs: dict, repo: str = "pydantic") -> dict:
    ranked = obs.get("rank_reviewers", [])
    ranked = [r for r in ranked if r["score"] >= 0.3]
    top2 = ranked[:2]

    pr = get_pr(pr_number, repo=repo)
    pr_files = sorted(set(pr.get("files", [])))

    bf = {b["path"]: b for b in obs.get("bus_factor_files", [])}
    risks = []
    for f in pr_files:
        if f in bf:
            b = bf[f]
            risks.append({"flag": f"risk:coverage-gap:{f}", "label": "risk:coverage-gap",
                          "detail": f"{f}: {b['sole_reviewer']} did {b['sole_count']} of "
                                    f"{b['total']} recent reviews"})
    if top2 and top2[0]["last_review"]:
        try:
            t = datetime.fromisoformat(top2[0]["last_review"].replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - t).days
            if days > 180:
                risks.append({"flag": "risk:stale-reviewer", "label": "risk:stale-reviewer",
                              "detail": f"top reviewer last reviewed {days} days ago"})
        except Exception:
            pass

    # Betweenness output is materialised on File nodes at ingest time, so centrality
    # of the changed files is a graph-derived risk signal in the decision itself.
    criticality = pr_criticality(pr_number, repo=repo)
    if criticality["max_centrality"] >= CRITICAL_PATH_THRESHOLD:
        risks.append({"flag": "risk:critical-path", "label": "risk:critical-path",
                      "detail": f"changed files peak at {criticality['max_centrality']} "
                                f"normalised betweenness (threshold {CRITICAL_PATH_THRESHOLD})"})

    top = top2[0] if top2 else None
    if top:
        rationale = (
            f"Top candidate {top['login']} shares {top['shared_files']} files with this PR "
            f"and reviewed {top['recent_reviews']} PRs recently. Structural affinity "
            f"{top['structural']} comes from {top['bridge_files']} co-changing files; "
            f"changed files peak at {criticality['max_centrality']} betweenness centrality."
        )
    else:
        rationale = "No candidate above threshold."

    return {
        "reviewers": top2,
        "risk_flags": [r["flag"] for r in risks],
        "risks": risks,
        "criticality": criticality,
        "rationale": rationale,
    }


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def propose_actions(pr_number: int, decision: dict, evidence: dict | None = None) -> list[dict]:
    evidence = evidence or {}
    actions = []
    for rank, r in enumerate(decision["reviewers"], start=1):
        path = evidence.get(r["login"]) or {}
        actions.append({
            "action": "request_review",
            "who": r["login"],
            "on": pr_number,
            "rank": rank,
            "reason": (f"rank {rank}, score {r['score']:.2f}: {_count(r['shared_files'], 'shared file')}, "
                       f"{_count(r['bridge_files'], 'co-change bridge file')}, "
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
    trace = []
    trace.append(f"START: PR #{pr_number} on {repo}, question='{question}'")
    cutoff = default_cutoff()

    planned = plan(pr_number, question=question, repo=repo)
    trace.append(f"PLAN: {planned}")

    obs = run_tools(pr_number, planned, repo=repo, cutoff=cutoff)
    counts = ", ".join(
        f"{k} -> {len(v) if isinstance(v, list) else 'ok'}"
        for k, v in obs.items()
    )
    trace.append(f"TOOLS: {counts}")

    decision = decide(pr_number, obs, repo=repo)
    trace.append(
        f"DECIDE: picked "
        f"{[r['login'] for r in decision['reviewers']]}; "
        f"flags={decision['risk_flags']}"
    )

    evidence = {
        r["login"]: explain_path(pr_number, r["login"], repo=repo, cutoff_iso=cutoff)
        for r in decision["reviewers"]
    }
    for login, ep in evidence.items():
        trace.append(
            f"EVIDENCE {login}: {ep['evidence']} over {ep['hops']} hops: {' -> '.join(ep['path'])}"
            if ep["path"] else f"EVIDENCE {login}: no connected path found"
        )
    top_evidence = evidence.get(decision["reviewers"][0]["login"]) if decision["reviewers"] else None

    actions = propose_actions(pr_number, decision, evidence)
    trace.append(f"ACT: proposed {len(actions)} actions (awaiting approval)")

    return {
        "pr_number": pr_number,
        "repo": repo,
        "question": question,
        "trace": trace,
        "observations": obs,
        "decision": decision,
        "explain_path": top_evidence,
        "reviewer_evidence": evidence,
        "proposed_actions": actions,
    }


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 13997
    result = run_keystone(n)
    for line in result["trace"]:
        print(line)
    print()
    for r in result["decision"]["reviewers"]:
        print(f"  reviewer: {r['login']} (score {r['score']})")