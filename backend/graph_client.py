"""Shared FalkorDB connection. Multi-graph aware. No fake fallbacks."""
import os
import json
import re
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()

DEFAULT_REPO = "pydantic"

REPOS = {
    "pydantic": "keystone_pydantic",
    "fastapi":  "keystone_fastapi",
    "redis":    "keystone_redis",
}

REPO_SLUGS = {
    "pydantic": "pydantic/pydantic",
    "fastapi":  "fastapi/fastapi",
    "redis":    "redis/redis",
}

REGISTRY_PATH = Path(__file__).with_name("repositories.json")


def _load_registered_repos():
    if not REGISTRY_PATH.exists():
        return
    try:
        saved = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        for key, value in saved.items():
            if isinstance(value, dict) and value.get("slug") and value.get("graph"):
                REPOS[key] = value["graph"]
                REPO_SLUGS[key] = value["slug"]
    except (OSError, ValueError):
        pass


_load_registered_repos()


def register_repo(repo_slug: str) -> str:
    """Register an owner/repository slug and return its local graph key."""
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", repo_slug.strip())
    if not match:
        raise ValueError("Use a GitHub repository such as octocat/Hello-World")

    owner, name = match.groups()
    key = f"{owner}/{name}".lower()
    graph_name = f"keystone_{owner}_{name}".replace("-", "_").replace(".", "_")
    REPOS[key] = graph_name
    REPO_SLUGS[key] = f"{owner}/{name}"

    saved = {}
    if REGISTRY_PATH.exists():
        try:
            saved = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
    saved[key] = {"slug": REPO_SLUGS[key], "graph": graph_name}
    REGISTRY_PATH.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
    return key


@lru_cache(maxsize=1)
def _db():
    host = os.getenv("FALKOR_HOST")
    if not host:
        raise RuntimeError("FALKOR_HOST not set")
    return FalkorDB(
        host=host,
        port=int(os.getenv("FALKOR_PORT", "6379")),
        username=os.getenv("FALKOR_USER"),
        password=os.getenv("FALKOR_PASS"),
        socket_timeout=15,
        socket_connect_timeout=10,
    )


def validate_repo(repo: str) -> str:
    """Ensure the selected repository exists in the REPOS dictionary.

    Raises ValueError if the repository is not recognized.
    Returns the matching repository key.
    """
    if not repo or not isinstance(repo, str):
        raise ValueError("Repository name must be a non-empty string.")
    repo_clean = repo.strip()
    if repo_clean in REPOS:
        return repo_clean
    repo_lower = repo_clean.lower()
    if repo_lower in REPOS:
        return repo_lower
    available = ", ".join(sorted(REPOS.keys()))
    raise ValueError(f"Repository '{repo}' not found in REPOS. Available repositories: {available}")


def is_valid_repo(repo: str) -> bool:
    """Return True if the repository exists in the REPOS dictionary, else False."""
    try:
        validate_repo(repo)
        return True
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=8)
def _graph_for(repo: str):
    repo_key = validate_repo(repo)
    return _db().select_graph(REPOS[repo_key])


def get_graph(repo: str = DEFAULT_REPO):
    validate_repo(repo)
    return _graph_for(repo)


def get_connection_status():
    try:
        g = get_graph()
        g.query("MATCH (n) RETURN count(n) LIMIT 1")
        return {"is_live": True, "message": f"Connected to FalkorDB"}
    except Exception as e:
        return {"is_live": False, "message": f"FalkorDB unreachable: {type(e).__name__}"}


def is_live_falkor() -> bool:
    return get_connection_status().get("is_live", False)


def list_repos() -> list[str]:
    """Only repos that actually have data in FalkorDB."""
    out = []
    for slug in REPOS:
        try:
            g = _graph_for(slug)
            n = g.query("MATCH (n) RETURN count(n)").result_set[0][0]
            if n > 0:
                out.append(slug)
        except Exception:
            continue
    return out


def node_count(repo: str = DEFAULT_REPO) -> int:
    """Actual node count. Raises if FalkorDB is unreachable."""
    g = _graph_for(repo)
    return g.query("MATCH (n) RETURN count(n)").result_set[0][0]


def edge_count(repo: str = DEFAULT_REPO) -> int:
    """Actual edge count. Raises if FalkorDB is unreachable."""
    g = _graph_for(repo)
    return g.query("MATCH ()-[e]->() RETURN count(e)").result_set[0][0]


def graph_provenance(repo: str = DEFAULT_REPO) -> dict:
    """Return source metadata without guessing for older unmarked graphs."""
    rows = get_graph(repo).query(
        "MATCH (m:KeystoneMetadata {key: 'provenance'}) "
        "RETURN m.source, m.repository, m.last_ingested_at, m.last_import_count "
        "ORDER BY m.last_ingested_at DESC LIMIT 1",
        {},
    ).result_set
    if not rows:
        return {"status": "unmarked", "message": "Graph data exists but has no recorded ingestion source."}
    source, repository, ingested_at, imported = rows[0]
    return {
        "status": "real",
        "source": source,
        "repository": repository,
        "last_ingested_at": ingested_at,
        "last_import_count": imported,
        "message": "Data was imported from the GitHub API.",
    }


if __name__ == "__main__":
    for r in list_repos():
        print(f"{r}: {node_count(r)} nodes, {edge_count(r)} edges")