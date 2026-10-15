# test_run.py
from tools import get_pr, default_cutoff
from scoring import score_reviewers
from agent import run_keystone

PR = 14000

print("=== PR METADATA ===")
pr = get_pr(PR)
print(f"Title: {pr.get('title')}")
print(f"Author: {pr.get('author')}")
print(f"Merged: {pr.get('merged_at')}")
print(f"Files ({len(pr.get('files', []))}):")
for f in pr.get("files", [])[:10]:
    print(f"  {f}")

print("\n=== RANKED REVIEWERS ===")
results = score_reviewers(PR, default_cutoff())
if not results:
    print("(empty — no candidates share files with this PR)")
else:
    for r in results[:10]:
        print(f"  {r['login']:20s} score={r['score']:.3f} "
              f"shared={r['shared_files']} recent={r['recent_reviews']} "
              f"last={r['last_review']}")

print("\n=== AGENT RUN ===")
res = run_keystone(PR)
for line in res["trace"]:
    print(" ", line)
print("\nFlags:", res["decision"]["risk_flags"])
print("Actions:", len(res["proposed_actions"]))