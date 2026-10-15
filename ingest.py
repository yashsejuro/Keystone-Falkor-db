import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()

import sys

REPO = sys.argv[1] if len(sys.argv) > 1 else "pydantic/pydantic"
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 500
GRAPH_NAME = "keystone_" + REPO.split("/")[1]

H = {
    "Authorization": f"token {os.getenv('GITHUB_TOKEN')}",
    "Accept": "application/vnd.github+json",
}

session = requests.Session()
retry = Retry(
    total=6,
    backoff_factor=2,          # 0s, 2s, 4s, 8s, 16s, 32s
    status_forcelist=[500, 502, 503, 504, 429],
    allowed_methods=["GET"],
    raise_on_status=False,
)
session.mount("https://", HTTPAdapter(max_retries=retry))
session.headers.update(H)

db = FalkorDB(
    host=os.getenv("FALKOR_HOST"),
    port=int(os.getenv("FALKOR_PORT")),
    username=os.getenv("FALKOR_USER"),
    password=os.getenv("FALKOR_PASS"),
    socket_timeout=60,
)
g = db.select_graph(GRAPH_NAME)


def gh(url, params=None):
    """Fetch with manual retry on DNS / connection failures."""
    for attempt in range(6):
        try:
            r = session.get(url, params=params, timeout=30)
            if r.status_code == 403 and "rate limit" in r.text.lower():
                print("  [rate limit, sleeping 60s]")
                time.sleep(60)
                continue
            if r.status_code == 404:
                return None
            if r.status_code >= 400:
                print(f"  [gh {r.status_code}] {url}")
                return None
            return r.json()
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            wait = 3 * (attempt + 1)
            print(f"  [net error, retry in {wait}s] {type(e).__name__}")
            time.sleep(wait)
    print(f"  [give up] {url}")
    return None


def already_ingested(number):
    r = g.query("MATCH (pr:PullRequest {number: $n}) RETURN 1", {"n": number})
    return len(r.result_set) > 0


def ingest_pr(pr):
    number = pr["number"]

    files = gh(f"https://api.github.com/repos/{REPO}/pulls/{number}/files", {"per_page": 100}) or []
    time.sleep(0.3)

    reviews = gh(f"https://api.github.com/repos/{REPO}/pulls/{number}/reviews", {"per_page": 100}) or []
    time.sleep(0.3)

    author = pr.get("user", {}).get("login")
    if author:
        g.query(
            "MERGE (p:Person {login: $l}) "
            "ON CREATE SET p.first_seen = $at, p.is_bot = $bot "
            "ON MATCH SET p.last_seen = $at",
            {"l": author, "at": pr["created_at"], "bot": author.endswith("[bot]")},
        )

    g.query(
        "MERGE (pr:PullRequest {number: $n}) "
        "SET pr.title = $t, pr.state = $s, pr.created_at = $c, pr.merged_at = $m, "
        "pr.additions = $a, pr.deletions = $d, pr.files_changed = $f",
        {"n": number, "t": (pr.get("title") or "")[:200], "s": pr.get("state"),
         "c": pr.get("created_at"), "m": pr.get("merged_at"),
         "a": pr.get("additions", 0), "d": pr.get("deletions", 0),
         "f": pr.get("changed_files", 0)},
    )

    if author:
        g.query(
            "MATCH (p:Person {login: $l}), (pr:PullRequest {number: $n}) "
            "MERGE (p)-[:AUTHORED {at: $at}]->(pr)",
            {"l": author, "n": number, "at": pr["created_at"]},
        )

    for f in files:
        path = f.get("filename")
        if not path:
            continue
        g.query(
            "MERGE (f:File {path: $path}) "
            "WITH f "
            "MATCH (pr:PullRequest {number: $n}) "
            "MERGE (pr)-[:TOUCHES {additions: $a, deletions: $d}]->(f)",
            {"path": path, "n": number,
             "a": f.get("additions", 0), "d": f.get("deletions", 0)},
        )

    for rev in reviews:
        who = rev.get("user", {}).get("login")
        st = rev.get("state")
        at = rev.get("submitted_at")
        if not who or not st:
            continue
        g.query(
            "MERGE (p:Person {login: $l}) "
            "ON CREATE SET p.first_seen = $at, p.is_bot = $bot "
            "ON MATCH SET p.last_seen = $at "
            "WITH p "
            "MATCH (pr:PullRequest {number: $n}) "
            "MERGE (p)-[r:REVIEWED {at: $at}]->(pr) "
            "SET r.state = $state",
            {"l": who, "n": number, "at": at, "state": st, "bot": who.endswith("[bot]")},
        )


def main():
    print(f"Ingesting {REPO} -> '{GRAPH_NAME}' (target {LIMIT}, resumable)\n")

    for q in [
        "CREATE INDEX FOR (p:Person) ON (p.login)",
        "CREATE INDEX FOR (pr:PullRequest) ON (pr.number)",
        "CREATE INDEX FOR (f:File) ON (f.path)",
    ]:
        try:
            g.query(q)
        except Exception:
            pass

    start = g.query("MATCH (pr:PullRequest) RETURN count(pr)").result_set[0][0]
    print(f"Already in graph: {start} PRs\n")

    page, done = 1, 0
    while start + done < LIMIT:
        prs = gh(f"https://api.github.com/repos/{REPO}/pulls",
                 {"state": "closed", "sort": "updated", "direction": "desc",
                  "per_page": 100, "page": page})
        if not prs:
            print(f"  [page {page} empty, stopping]")
            break

        for pr in prs:
            if start + done >= LIMIT:
                break
            if not pr.get("merged_at"):
                continue
            if already_ingested(pr["number"]):
                continue
            try:
                ingest_pr(pr)
            except Exception as e:
                print(f"  [skip #{pr['number']}] {type(e).__name__}: {e}")
                continue
            done += 1
            if done % 25 == 0:
                print(f"  +{done} new / {start + done} total / {LIMIT} target")
        page += 1
        time.sleep(1)   # gentle between pages

    print(f"\nDone. Added {done} new PRs.")
    print(f"Total nodes: {g.query('MATCH (n) RETURN count(n)').result_set[0][0]}")
    print(f"Total edges: {g.query('MATCH ()-[e]->() RETURN count(e)').result_set[0][0]}")


if __name__ == "__main__":
    main()