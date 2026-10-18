import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()

import sys

try:
    from backend.graph_client import make_graph_name, register_repo, REPOS
except ImportError:
    from graph_client import make_graph_name, register_repo, REPOS

REPO = sys.argv[1] if len(sys.argv) > 1 else "pydantic/pydantic"
# LIMIT represents the target batch size for this ingestion job, not the repository's total PR count.
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 500


def get_graph_name(repo_slug: str) -> str:
    repo_slug = repo_slug.strip()
    if "/" not in repo_slug:
        return REPOS.get(repo_slug.lower(), f"keystone_{repo_slug}")

    owner, name = [part.strip() for part in repo_slug.split("/", 1)]
    if not owner or not name:
        return f"keystone_{repo_slug.replace('/', '_')}"

    try:
        canonical_key = register_repo(repo_slug)
        return REPOS.get(canonical_key, make_graph_name(owner, name))
    except Exception:
        return make_graph_name(owner, name)


GRAPH_NAME = get_graph_name(REPO)

H = {
    "Authorization": f"token {os.getenv('GITHUB_TOKEN')}",
    "Accept": "application/vnd.github+json",
}

session = requests.Session()
retry = Retry(
    total=6,
    backoff_factor=2,
    status_forcelist=[500, 502, 503, 504, 429],
    allowed_methods=["GET"],
    raise_on_status=False,
)
session.mount("https://", HTTPAdapter(max_retries=retry))
session.headers.update(H)

db = None
g = None


def get_graph():
    global db, g
    if g is None:
        db = FalkorDB(
            host=os.getenv("FALKOR_HOST"),
            port=int(os.getenv("FALKOR_PORT", "6379")),
            username=os.getenv("FALKOR_USER"),
            password=os.getenv("FALKOR_PASS"),
            socket_timeout=60,
        )
        g = db.select_graph(GRAPH_NAME)
    return g


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
    r = get_graph().query("MATCH (pr:PullRequest {number: $n}) RETURN 1", {"n": number})
    return len(r.result_set) > 0


def ingest_pr(pr):
    number = pr["number"]

    files = gh(f"https://api.github.com/repos/{REPO}/pulls/{number}/files", {"per_page": 100}) or []
    time.sleep(0.3)

    reviews = gh(f"https://api.github.com/repos/{REPO}/pulls/{number}/reviews", {"per_page": 100}) or []
    time.sleep(0.3)

    graph = get_graph()

    author = pr.get("user", {}).get("login")
    if author:
        graph.query(
            "MERGE (p:Person {login: $l}) "
            "ON CREATE SET p.first_seen = $at, p.is_bot = $bot "
            "ON MATCH SET p.last_seen = $at",
            {"l": author, "at": pr["created_at"], "bot": author.endswith("[bot]")},
        )

    graph.query(
        "MERGE (pr:PullRequest {number: $n}) "
        "SET pr.title = $t, pr.state = $s, pr.created_at = $c, pr.merged_at = $m, "
        "pr.additions = $a, pr.deletions = $d, pr.files_changed = $f",
        {"n": number, "t": (pr.get("title") or "")[:200], "s": pr.get("state"),
         "c": pr.get("created_at"), "m": pr.get("merged_at"),
         "a": pr.get("additions", 0), "d": pr.get("deletions", 0),
         "f": pr.get("changed_files", 0)},
    )

    if author:
        graph.query(
            "MATCH (p:Person {login: $l}), (pr:PullRequest {number: $n}) "
            "MERGE (p)-[:AUTHORED {at: $at}]->(pr)",
            {"l": author, "n": number, "at": pr["created_at"]},
        )

    for f in files:
        path = f.get("filename")
        if not path:
            continue
        graph.query(
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
        graph.query(
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
    graph = get_graph()
    print(f"Ingesting {REPO} -> Graph '{GRAPH_NAME}' (Batch size: {LIMIT}; use --limit to change, resumable)\n")
    print(f"Note: Batch size {LIMIT} indicates the maximum PRs fetched per ingestion job, not total repository size.\n")

    for q in [
        "CREATE INDEX FOR (p:Person) ON (p.login)",
        "CREATE INDEX FOR (pr:PullRequest) ON (pr.number)",
        "CREATE INDEX FOR (f:File) ON (f.path)",
    ]:
        try:
            graph.query(q)
        except Exception:
            pass

    start = graph.query("MATCH (pr:PullRequest) RETURN count(pr)").result_set[0][0]
    print(f"Already in graph: {start} PRs\n")

    page, done = 1, 0
    while start + done < LIMIT:
        prs = gh(
            f"https://api.github.com/repos/{REPO}/pulls",
            {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100, "page": page},
        )
        if not prs:
            print(f"  [page {page} empty, stopping]")
            break

        page_processed = False
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
            page_processed = True
            if done % 25 == 0:
                print(f"  +{done} new / {start + done} total / {LIMIT} batch limit")

        if not page_processed:
            break

        page += 1
        time.sleep(1)

    print(f"\nDone. Added {done} new PRs.")
    print(f"Total nodes: {graph.query('MATCH (n) RETURN count(n)').result_set[0][0]}")
    print(f"Total edges: {graph.query('MATCH ()-[e]->() RETURN count(e)').result_set[0][0]}")


if __name__ == "__main__":
    main()
