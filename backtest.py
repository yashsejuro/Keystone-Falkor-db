"""Backtest: prove the graph scorer beats baselines at predicting reviewers.

Time-based split, no leakage. All methods only see training-window data.
"""
from operator import truth
from operator import truth
import statistics
from datetime import datetime, timedelta, timezone
from graph_client import get_graph
from tools import reviewer_candidates, _rows


TRAIN_DAYS = 90        # graph data before this is "training"
TEST_SAMPLE = 60       # number of test PRs to evaluate on


def _iso(dt):
    return dt.isoformat()


def _parse(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


def split_data():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=TRAIN_DAYS)
    print(f"Cutoff: {cutoff.isoformat()}")
    print(f"Training: PRs merged before cutoff")
    print(f"Testing: PRs merged after cutoff\n")
    return cutoff


def get_test_prs(cutoff_dt, limit):
    """Merged PRs after cutoff that have at least one REVIEWED edge."""
    rows = _rows(
        """
        MATCH (pr:PullRequest)<-[:REVIEWED]-(r:Person)
        WHERE pr.merged_at > $cutoff AND r.is_bot = false
        WITH pr, count(DISTINCT r) AS reviewers
        WHERE reviewers >= 1
        RETURN pr.number, pr.merged_at
        ORDER BY pr.merged_at DESC
        LIMIT $limit
        """,
        {"cutoff": _iso(cutoff_dt), "limit": limit},
    )
    return [{"number": r[0], "merged_at": r[1]} for r in rows]


def actual_reviewers(pr_number):
    rows = _rows(
        """
        MATCH (pr:PullRequest {number: $n})<-[:REVIEWED]-(r:Person)
        WHERE r.is_bot = false
        RETURN DISTINCT r.login
        """,
        {"n": pr_number},
    )
    return {r[0] for r in rows}


def pr_files(pr_number):
    rows = _rows(
        "MATCH (pr:PullRequest {number: $n})-[:TOUCHES]->(f:File) RETURN f.path",
        {"n": pr_number},
    )
    return {r[0] for r in rows}


def pr_author(pr_number):
    rows = _rows(
        "MATCH (pr:PullRequest {number: $n})<-[:AUTHORED]-(a:Person) RETURN a.login",
        {"n": pr_number},
    )
    return rows[0][0] if rows else None


# ---------- Baselines ----------

def baseline_frequent(cutoff_dt, topk=3):
    """Most-frequent reviewer overall in training window."""
    rows = _rows(
        """
        MATCH (r:Person)-[:REVIEWED]->(pr:PullRequest)
        WHERE pr.merged_at < $cutoff AND r.is_bot = false
        RETURN r.login, count(DISTINCT pr) AS n
        ORDER BY n DESC LIMIT $k
        """,
        {"cutoff": _iso(cutoff_dt), "k": topk},
    )
    return [r[0] for r in rows]


def baseline_directory(cutoff_dt, pr_number, topk=3):
    """Most-frequent reviewer for this PR's directories in training window."""
    files = pr_files(pr_number)
    if not files:
        return []
    dirs = set()
    for f in files:
        parts = f.split("/")
        if len(parts) > 1:
            dirs.add("/".join(parts[:2]) + "/")
        else:
            dirs.add(parts[0] + "/")

    rows = _rows(
        """
        MATCH (r:Person)-[:REVIEWED]->(pr:PullRequest)-[:TOUCHES]->(f:File)
        WHERE pr.merged_at < $cutoff AND r.is_bot = false
          AND any(d IN $dirs WHERE f.path STARTS WITH d)
        RETURN r.login, count(DISTINCT pr) AS total
        ORDER BY total DESC LIMIT $k
        """,
        {"cutoff": _iso(cutoff_dt), "dirs": list(dirs), "k": topk},
    )
    return [r[0] for r in rows]


# ---------- Graph scorer (uses existing module) ----------

def graph_scorer(cutoff_dt, pr_number, topk=3):
    from scoring import score_reviewers
    results = score_reviewers(pr_number, _iso(cutoff_dt))
    return [r["login"] for r in results[:topk]]


def vector_only(cutoff_dt, pr_number, topk=3):
    """Stub: same as directory baseline for now. Vector search is Day 3."""
    return baseline_directory(cutoff_dt, pr_number, topk)


# ---------- PR classification ----------

def classify_pr(pr_number, cutoff_dt):
    """new_file / cross_module / single_file."""
    files = pr_files(pr_number)
    if len(files) <= 1:
        return "single_file"
    dirs = {"/".join(f.split("/")[:2]) for f in files if "/" in f}
    if len(dirs) > 1:
        return "cross_module"
    return "single_file"


# ---------- Backtest ----------

def evaluate(cutoff_dt, test_prs):
    methods = ["baseline_frequent", "baseline_directory", "vector_only", "graph_scorer"]
    hits_top1 = {m: 0 for m in methods}
    hits_top3 = {m: 0 for m in methods}
    by_type = {}
    valid = 0

    freq = baseline_frequent(cutoff_dt, topk=3)

    for i, tp in enumerate(test_prs):
        n = tp["number"]
        truth = actual_reviewers(n)
        if not truth:
            continue
        author = pr_author(n)
        truth = truth - ({author} if author else set())

        preds = {
            "baseline_frequent": freq,
            "baseline_directory": baseline_directory(cutoff_dt, n, topk=3),
            "vector_only": vector_only(cutoff_dt, n, topk=3),
            "graph_scorer": graph_scorer(cutoff_dt, n, topk=3),
        }

        ptype = classify_pr(n, cutoff_dt)
        if ptype not in by_type:
            by_type[ptype] = {
                "n": 0,
                "top1": {m: 0 for m in methods},
                "top3": {m: 0 for m in methods},
            }
        by_type[ptype]["n"] += 1

        for m in methods:
            p = [x for x in preds[m] if x]
            if p and p[0] in truth:
                hits_top1[m] += 1
                by_type[ptype]["top1"][m] += 1
            if any(x in truth for x in p[:3]):
                hits_top3[m] += 1
                by_type[ptype]["top3"][m] += 1

        valid += 1
        if (i + 1) % 20 == 0:
            print(f"  evaluated {i+1}/{len(test_prs)}")

    results = {
        "n": valid,
        "top1": {m: hits_top1[m] / valid for m in methods},
        "top3": {m: hits_top3[m] / valid for m in methods},
        "by_type": {
            t: {
                "n": by_type[t]["n"],
                "top1": {m: by_type[t]["top1"][m] / by_type[t]["n"] for m in methods},
                "top3": {m: by_type[t]["top3"][m] / by_type[t]["n"] for m in methods},
            }
            for t in by_type
        },
    }
    return results


def print_table(results):
    methods = ["baseline_frequent", "baseline_directory", "vector_only", "graph_scorer"]
    print(f"\nEvaluated on {results['n']} test PRs\n")
    print(f"{'method':<22} {'top1':>8} {'top3':>8}")
    print("-" * 40)
    for m in methods:
        print(f"{m:<22} {results['top1'][m]*100:>7.1f}% {results['top3'][m]*100:>7.1f}%")

    print(f"\nBy PR type:")
    for t, data in results["by_type"].items():
        print(f"\n  {t} (n={data['n']})")
        for m in methods:
            print(f"    {m:<22} top1={data['top1'][m]*100:>5.1f}%  top3={data['top3'][m]*100:>5.1f}%")

    # markdown for README
    md = "| method | top-1 | top-3 |\n|---|---|---|\n"
    for m in methods:
        md += f"| {m} | {results['top1'][m]*100:.1f}% | {results['top3'][m]*100:.1f}% |\n"
    print("\n--- paste into README ---\n")
    print(md)
    return md


if __name__ == "__main__":
    cutoff = split_data()
    test_prs = get_test_prs(cutoff, TEST_SAMPLE)
    print(f"Test PRs: {len(test_prs)}\n")
    results = evaluate(cutoff, test_prs)
    print_table(results)