"""Real GitHub-to-FalkorDB ingestion used by the web application.

This module only imports data returned by GitHub's public API. It never creates
placeholder PRs, reviewers, or files.
"""
import os
import time
from collections.abc import Callable

import requests
from dotenv import load_dotenv
from falkordb import FalkorDB
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from graph_client import REPOS, register_repo

load_dotenv()

Progress = Callable[[dict], None]


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"Accept": "application/vnd.github+json"})
    token = os.getenv("GITHUB_TOKEN")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def _fetch(session: requests.Session, url: str, params: dict | None = None):
    response = session.get(url, params=params, timeout=30)
    if response.status_code == 403 and "rate limit" in response.text.lower():
        raise RuntimeError("GitHub API rate limit reached. Add GITHUB_TOKEN to .env and retry.")
    if response.status_code == 404:
        raise RuntimeError("GitHub repository or endpoint not found. Check the URL and access permissions.")
    response.raise_for_status()
    return response.json()


def _mark_provenance(graph, repo_slug: str, imported: int):
    graph.query(
        "MERGE (m:KeystoneMetadata {key: 'provenance'}) "
        "SET m.source = 'GitHub API', m.repository = $repo, "
        "m.last_ingested_at = $at, m.last_import_count = $count",
        {"repo": repo_slug, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "count": imported},
    )


def _ensure_indexes(graph):
    for query in (
        "CREATE INDEX FOR (p:Person) ON (p.login)",
        "CREATE INDEX FOR (pr:PullRequest) ON (pr.number)",
        "CREATE INDEX FOR (f:File) ON (f.path)",
    ):
        try:
            graph.query(query)
        except Exception:
            pass


def _already_ingested(graph, number: int) -> bool:
    result = graph.query("MATCH (pr:PullRequest {number: $n}) RETURN 1", {"n": number})
    return bool(result.result_set)


def _ingest_pr(graph, session: requests.Session, repo_slug: str, pr: dict):
    number = pr["number"]
    base = f"https://api.github.com/repos/{repo_slug}"
    pr = _fetch(session, f"{base}/pulls/{number}")
    files = _fetch(session, f"{base}/pulls/{number}/files", {"per_page": 100})
    reviews = _fetch(session, f"{base}/pulls/{number}/reviews", {"per_page": 100})
    author = (pr.get("user") or {}).get("login")

    if author:
        graph.query(
            "MERGE (p:Person {login: $login}) "
            "ON CREATE SET p.first_seen = $at, p.is_bot = $bot "
            "ON MATCH SET p.last_seen = $at",
            {"login": author, "at": pr.get("created_at"), "bot": author.endswith("[bot]")},
        )

    graph.query(
        "MERGE (pr:PullRequest {number: $number}) "
        "SET pr.title = $title, pr.state = $state, pr.created_at = $created, "
        "pr.merged_at = $merged, pr.additions = $additions, pr.deletions = $deletions, "
        "pr.files_changed = $changed, pr.source_repository = $repo",
        {
            "number": number,
            "title": (pr.get("title") or "")[:200],
            "state": pr.get("state"),
            "created": pr.get("created_at"),
            "merged": pr.get("merged_at"),
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "changed": pr.get("changed_files", 0),
            "repo": repo_slug,
        },
    )

    if author:
        graph.query(
            "MATCH (p:Person {login: $login}), (pr:PullRequest {number: $number}) "
            "MERGE (p)-[:AUTHORED {at: $at}]->(pr)",
            {"login": author, "number": number, "at": pr.get("created_at")},
        )

    for file in files:
        path = file.get("filename")
        if not path:
            continue
        graph.query(
            "MERGE (f:File {path: $path}) WITH f "
            "MATCH (pr:PullRequest {number: $number}) "
            "MERGE (pr)-[:TOUCHES {additions: $additions, deletions: $deletions}]->(f)",
            {"path": path, "number": number, "additions": file.get("additions", 0), "deletions": file.get("deletions", 0)},
        )

    for review in reviews:
        reviewer = (review.get("user") or {}).get("login")
        state = review.get("state")
        submitted = review.get("submitted_at")
        if not reviewer or not state or not submitted:
            continue
        graph.query(
            "MERGE (p:Person {login: $login}) "
            "ON CREATE SET p.first_seen = $at, p.is_bot = $bot "
            "ON MATCH SET p.last_seen = $at WITH p "
            "MATCH (pr:PullRequest {number: $number}) "
            "MERGE (p)-[r:REVIEWED {at: $at}]->(pr) SET r.state = $state",
            {"login": reviewer, "number": number, "at": submitted, "state": state, "bot": reviewer.endswith("[bot]")},
        )


def ingest_repository(repo_slug: str, limit: int = 100, progress: Progress | None = None) -> dict:
    """Import up to `limit` real merged PRs, resuming existing graph data."""
    if not os.getenv("FALKOR_HOST"):
        raise RuntimeError("FALKOR_HOST is not configured in .env")
    if limit < 1 or limit > 500:
        raise ValueError("Choose between 1 and 500 pull requests")

    repo_key = register_repo(repo_slug)
    graph = FalkorDB(
        host=os.getenv("FALKOR_HOST"),
        port=int(os.getenv("FALKOR_PORT", "6379")),
        username=os.getenv("FALKOR_USER"),
        password=os.getenv("FALKOR_PASS"),
        socket_timeout=60,
    ).select_graph(REPOS[repo_key])
    session = _session()
    _ensure_indexes(graph)
    existing = graph.query("MATCH (pr:PullRequest) RETURN count(pr)").result_set[0][0]
    imported = 0
    skipped = 0
    page = 1

    def update(stage: str, message: str):
        if progress:
            progress({"stage": stage, "message": message, "imported": imported, "skipped": skipped, "existing": existing, "limit": limit})

    update("connecting", f"Connected to GitHub and FalkorDB for {repo_slug}")
    while imported < limit:
        prs = _fetch(session, f"https://api.github.com/repos/{repo_slug}/pulls", {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100, "page": page})
        if not prs:
            break
        for pr in prs:
            if imported >= limit:
                break
            if not pr.get("merged_at"):
                continue
            if _already_ingested(graph, pr["number"]):
                skipped += 1
                continue
            _ingest_pr(graph, session, repo_slug, pr)
            imported += 1
            update("importing", f"Imported real merged PR #{pr['number']}")
        page += 1

    _mark_provenance(graph, repo_slug, imported)
    total = graph.query("MATCH (pr:PullRequest) RETURN count(pr)").result_set[0][0]
    update("complete", f"Finished. {imported} new PRs added; {total} real PRs are available for analysis.")
    return {"repo": repo_key, "repository": repo_slug, "imported": imported, "skipped": skipped, "total": total}


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "pydantic/pydantic"
    amount = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    print(ingest_repository(target, amount))
