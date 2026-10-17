# peek.py
from backend.graph_client import get_graph
g = get_graph()

print("Sample PR numbers:")
rows = g.query("MATCH (pr:PullRequest) RETURN pr.number ORDER BY pr.number DESC LIMIT 10").result_set
for r in rows:
    print(" ", r[0])

print("\nMerge date range:")
rows = g.query("MATCH (pr:PullRequest) RETURN min(pr.merged_at), max(pr.merged_at)").result_set
print(" ", rows[0][0], "to", rows[0][1])

print("\nTop reviewers in graph:")
rows = g.query("""
  MATCH (r:Person)-[:REVIEWED]->(pr:PullRequest)
  WHERE r.is_bot = false
  RETURN r.login, count(DISTINCT pr) AS n
  ORDER BY n DESC LIMIT 10
""").result_set
for r in rows:
    print(f"  {r[0]:25s} {r[1]}")