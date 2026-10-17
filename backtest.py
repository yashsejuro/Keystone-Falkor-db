"""Backtest: prove the graph scorer beats baselines at predicting reviewers.

Time-based split, no leakage. All methods only see training-window data.

`relational_ablation` is the identical scorer with the CO_CHANGES and betweenness
term removed. The gap between it and `graph_scorer` is the measured contribution of
graph traversal, which is the question a graph-database sponsor asks.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from backend.graph_client import node_count, edge_count, graph_provenance
from backend.tools import _rows
from backend.scoring import score_reviewers

METHODS = ["baseline_frequent", "baseline_directory", "relational_ablation", "graph_scorer"]


TRAIN_DAYS = 90        # graph data before this is "training"
TEST_SAMPLE = 60       # number of test PRs to evaluate on
LOCK = Path(__file__).with_name("benchmark_lock.json")


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
    results = score_reviewers(pr_number, _iso(cutoff_dt), use_graph=True)
    return [r["login"] for r in results[:topk]]


def relational_ablation(cutoff_dt, pr_number, topk=3):
    """Same scorer, same data, graph term switched off."""
    results = score_reviewers(pr_number, _iso(cutoff_dt), use_graph=False)
    return [r["login"] for r in results[:topk]]


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
    methods = METHODS
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
            "relational_ablation": relational_ablation(cutoff_dt, n, topk=3),
            "graph_scorer": graph_scorer(cutoff_dt, n, topk=3),
        }

        ptype = classify_pr(n, cutoff_dt)
        by_type.setdefault(ptype, {
            "n": 0,
            "top1": {m: 0 for m in methods},
            "top3": {m: 0 for m in methods},
        })
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
    methods = METHODS
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


def _git_rev() -> str:
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10, cwd=str(LOCK.parent)).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def resolve_eval_set(cutoff_dt):
    """Reuse a pinned cutoff and PR set so reported numbers stay reproducible.

    The cutoff is rolling, so an unpinned benchmark silently changes as the training
    window slides and results stop matching the README.
    """
    if LOCK.exists():
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        cutoff_dt = datetime.fromisoformat(lock["cutoff"])
        numbers = lock["test_prs"]
        print(f"Using pinned benchmark: cutoff {lock['cutoff']}, {len(numbers)} test PRs")
        return cutoff_dt, [{"number": n} for n in numbers], False

    test_prs = get_test_prs(cutoff_dt, TEST_SAMPLE)
    LOCK.write_text(json.dumps({
        "cutoff": _iso(cutoff_dt),
        "test_prs": [tp["number"] for tp in test_prs],
        "train_days": TRAIN_DAYS,
        "repo": "pydantic",
        "graph": {
            "nodes": node_count(),
            "edges": edge_count(),
            "provenance": graph_provenance(),
        },
        "git_rev": _git_rev(),
        "pinned_at": _iso(datetime.now(timezone.utc)),
    }, indent=2), encoding="utf-8")
    print(f"Pinned benchmark to {LOCK.name}")
    return cutoff_dt, test_prs, True


if __name__ == "__main__":
    cutoff = split_data()
    cutoff, test_prs, freshly_pinned = resolve_eval_set(cutoff)
    print(f"Test PRs: {len(test_prs)}\n")
    results = evaluate(cutoff, test_prs)
    print_table(results)
    if freshly_pinned:
        print("Re-run to evaluate against the pinned set.")