# test_flag.py
from backend.tools import bus_factor_files, default_cutoff, get_pr
from backend.scoring import score_reviewers
from backend.agent import run_keystone
from backend.graph_client import get_graph

cutoff = default_cutoff()
print("=== BUS FACTOR FILES ===")
bf = bus_factor_files(cutoff)
for b in bf:
    print(f"  {b['path']:60s} sole={b['sole_reviewer']} ({b['sole_count']}/{b['total']})")

if not bf:
    print("(none)")
    raise SystemExit

# find a merged PR that touches one of these flagged files
flagged_paths = [b["path"] for b in bf]
g = get_graph()
rows = g.query("""
    MATCH (pr:PullRequest)-[:TOUCHES]->(f:File)
    WHERE f.path IN $paths
    RETURN DISTINCT pr.number
    ORDER BY pr.number DESC
    LIMIT 10
""", {"paths": flagged_paths}).result_set

print("\n=== CANDIDATE PRs TOUCHING FLAGGED FILES ===")
for r in rows:
    print(f"  PR #{r[0]}")

if not rows:
    print("(none — flagged files have no recent PRs)")
    raise SystemExit

# test the top one
pr_num = rows[0][0]
print(f"\n=== RUNNING AGENT ON PR #{pr_num} ===")
res = run_keystone(pr_num)
for line in res["trace"]:
    print(" ", line)

print("\nPR files:")
for f in get_pr(pr_num).get("files", []):
    print(f"  {f}")

print("\nFlags:", res["decision"]["risk_flags"])
print("Reviewers:", [r["login"] for r in res["decision"]["reviewers"]])
print("Actions:", len(res["proposed_actions"]))