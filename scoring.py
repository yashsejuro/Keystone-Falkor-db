"""Deterministic reviewer scoring. No LLM. Pure graph + math."""
import math
from datetime import datetime, timezone
from tools import reviewer_candidates


def _days_since(iso: str) -> float:
    if not iso:
        return 999.0
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() / 86400.0
    except Exception:
        return 999.0


def score_reviewers(pr_number: int, cutoff_iso: str) -> list[dict]:
    candidates = reviewer_candidates(pr_number, cutoff_iso)
    if not candidates:
        return []

    max_shared = max(c["shared_files"] for c in candidates) or 1
    max_recent = max(c["recent_reviews"] for c in candidates) or 1

    scored = []
    for c in candidates:
        shared_norm = c["shared_files"] / max_shared
        recent_norm = c["recent_reviews"] / max_recent
        recency = math.exp(-_days_since(c["last_review"]) / 60.0)
        overload = 0.7 if c["recent_reviews"] > 20 else 1.0

        score = (
            0.5 * shared_norm
            + 0.2 * recent_norm
            + 0.2 * recency
            + 0.1 * 1.0     # placeholder for hops bonus; filled in later
        ) * overload

        scored.append({
            **c,
            "score": round(score, 4),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


if __name__ == "__main__":
    from tools import default_cutoff
    for r in score_reviewers(1, default_cutoff()):
        print(f"{r['login']:20s} score={r['score']:.3f} "
              f"shared={r['shared_files']} recent={r['recent_reviews']}")