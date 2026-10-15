"""Keystone agent: plan -> tools -> decide -> propose actions.
No LLM in the decision path. Optional LLM narration later."""
from datetime import datetime, timezone
from tools import (
    get_pr, reviewer_candidates, bus_factor_files,
    critical_files, default_cutoff,
)
from scoring import score_reviewers


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


def run_tools(pr_number: int, planned: list[str], repo: str = "pydantic") -> dict:
    cutoff = default_cutoff()
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
    pr_files = set(pr.get("files", []))

    bf = {b["path"]: b for b in obs.get("bus_factor_files", [])}
    flags = []
    for f in pr_files:
        if f in bf:
            flags.append(f"risk:coverage-gap:{f}")
    if top2 and top2[0]["last_review"]:
        try:
            t = datetime.fromisoformat(top2[0]["last_review"].replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - t).days
            if days > 180:
                flags.append("risk:stale-reviewer")
        except Exception:
            pass

    rationale = (
        f"Top candidate {top2[0]['login']} shares "
        f"{top2[0]['shared_files']} files with this PR and reviewed "
        f"{top2[0]['recent_reviews']} PRs recently."
        if top2 else "No candidate above threshold."
    )

    return {
        "reviewers": top2,
        "risk_flags": flags,
        "rationale": rationale,
    }


def propose_actions(pr_number: int, decision: dict) -> list[dict]:
    actions = []
    for r in decision["reviewers"]:
        actions.append({
            "action": "request_review",
            "who": r["login"],
            "on": pr_number,
        })
    labels = set()
    for flag in decision["risk_flags"]:
        parts = flag.split(":")
        label = ":".join(parts[:2]) if len(parts) >= 2 else flag
        labels.add(label)
    for label in labels:
        actions.append({
            "action": "add_label",
            "label": label,
            "on": pr_number,
        })
    return actions


def run_keystone(pr_number: int, question: str = "who should review this?", repo: str = "pydantic") -> dict:
    trace = []
    trace.append(f"START: PR #{pr_number} on {repo}, question='{question}'")

    planned = plan(pr_number, question=question, repo=repo)
    trace.append(f"PLAN: {planned}")

    obs = run_tools(pr_number, planned, repo=repo)
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

    actions = propose_actions(pr_number, decision)
    trace.append(f"ACT: proposed {len(actions)} actions (awaiting approval)")

    return {
        "pr_number": pr_number,
        "repo": repo,
        "question": question,
        "trace": trace,
        "observations": obs,
        "decision": decision,
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