"""Shared FalkorDB connection. Multi-graph aware, collision-safe, cached, and instrumented."""
import os
import re
import json
import time
import hashlib
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from falkordb import FalkorDB

try:
    from backend.cache import METADATA_CACHE
    from backend.instrumentation import record_query
except ImportError:
    from cache import METADATA_CACHE
    from instrumentation import record_query

load_dotenv()

DEFAULT_REPO = "pydantic"

REPOS: dict[str, str] = {
    "pydantic": "keystone_pydantic",
    "fastapi": "keystone_fastapi",
    "redis": "keystone_redis",
}

REPO_SLUGS: dict[str, str] = {
    "pydantic": "pydantic/pydantic",
    "fastapi": "fastapi/fastapi",
    "redis": "redis/redis",
}

REGISTRY_PATH = Path(__file__).resolve().parent / "repositories.json"
_REGISTRY_LOCK = threading.Lock()


def _load_registered_repos():
    if not REGISTRY_PATH.exists():
        return
    with _REGISTRY_LOCK:
        try:
            saved = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            for key, value in saved.items():
                if isinstance(value, dict) and value.get("slug") and value.get("graph"):
                    REPOS[key] = value["graph"]
                    REPO_SLUGS[key] = value["slug"]
                    # Also register full slug key
                    slug_key = value["slug"].lower()
                    REPOS[slug_key] = value["graph"]
                    REPO_SLUGS[slug_key] = value["slug"]
        except (OSError, ValueError):
            pass


_load_registered_repos()


def make_graph_name(owner: str, name: str) -> str:
    """Generate a collision-safe FalkorDB graph name for an owner/name repository slug.
    
    Includes a deterministic 8-character SHA-256 slug hash to guarantee that repos
    with different punctuation (e.g. 'foo-bar/baz' vs 'foo_bar/baz') map to distinct graphs.
    """
    slug = f"{owner.strip().lower()}/{name.strip().lower()}"
    slug_hash = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8]
    clean_owner = re.sub(r"[^A-Za-z0-9_]", "_", owner.strip())
    clean_name = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
    return f"keystone_{clean_owner}_{clean_name}_{slug_hash}"


def register_repo(repo_slug: str, graph_name: Optional[str] = None) -> str:
    """Register an owner/repository slug and return its canonical repository key."""
    clean_slug = repo_slug.strip()
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", clean_slug)
    if not match:
        raise ValueError(f"Invalid repository slug '{repo_slug}'. Use owner/name (e.g., 'pydantic/pydantic').")

    owner, name = match.groups()
    key = f"{owner}/{name}".lower()

    # Reuse existing graph name if pre-registered, otherwise compute collision-safe name
    if not graph_name:
        if key in REPOS:
            graph_name = REPOS[key]
        else:
            graph_name = make_graph_name(owner, name)

    with _REGISTRY_LOCK:
        REPOS[key] = graph_name
        REPO_SLUGS[key] = f"{owner}/{name}"

        # If repo short name is not ambiguous, map it too
        short_name = name.lower()
        if short_name not in REPOS or REPOS[short_name] == graph_name:
            REPOS[short_name] = graph_name
            REPO_SLUGS[short_name] = f"{owner}/{name}"

        saved = {}
        if REGISTRY_PATH.exists():
            try:
                saved = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}
        saved[key] = {"slug": f"{owner}/{name}", "graph": graph_name}
        try:
            REGISTRY_PATH.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    _graph_for.cache_clear()
    METADATA_CACHE.invalidate()
    return key


def unregister_repo(repo_slug_or_key: str, drop_graph: bool = False) -> dict:
    """Unregister a repository from the registry and optionally delete its FalkorDB graph."""
    clean = repo_slug_or_key.strip().lower()
    
    # Identify canonical key and graph name
    target_key = None
    target_graph = None
    target_slug = None

    if clean in REPOS:
        target_key = clean
        target_graph = REPOS[clean]
        target_slug = REPO_SLUGS.get(clean, clean)
    else:
        for k, slug in REPO_SLUGS.items():
            if slug.lower() == clean:
                target_key = k
                target_graph = REPOS.get(k)
                target_slug = slug
                break

    if not target_key:
        raise ValueError(f"Repository '{repo_slug_or_key}' is not registered.")

    # Guard against accidental deletion of core sample repositories
    if target_key in ("pydantic", "fastapi"):
        raise ValueError(f"Core demonstration repository '{target_key}' cannot be deleted.")

    with _REGISTRY_LOCK:
        # Remove from in-memory maps
        REPOS.pop(target_key, None)
        REPO_SLUGS.pop(target_key, None)
        if target_slug:
            REPOS.pop(target_slug.lower(), None)
            REPO_SLUGS.pop(target_slug.lower(), None)

        # Remove from repositories.json
        if REGISTRY_PATH.exists():
            try:
                saved = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
                saved.pop(target_key, None)
                if target_slug:
                    saved.pop(target_slug.lower(), None)
                REGISTRY_PATH.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
            except (OSError, ValueError):
                pass

    _graph_for.cache_clear()
    METADATA_CACHE.invalidate()

    graph_dropped = False
    if drop_graph and target_graph:
        try:
            db_conn = _db()
            db_conn.select_graph(target_graph).delete()
            graph_dropped = True
        except Exception:
            pass

    return {
        "ok": True,
        "repo": target_slug or target_key,
        "graph_name": target_graph,
        "graph_dropped": graph_dropped,
        "message": f"Repository '{target_slug or target_key}' unregistered successfully."
    }


@lru_cache(maxsize=1)
def _db():
    host = os.getenv("FALKOR_HOST")
    if not host:
        raise RuntimeError("FALKOR_HOST not configured in environment")
    return FalkorDB(
        host=host,
        port=int(os.getenv("FALKOR_PORT", "6379")),
        username=os.getenv("FALKOR_USER"),
        password=os.getenv("FALKOR_PASS"),
        socket_timeout=15,
        socket_connect_timeout=10,
    )


def reset_db_connection() -> None:
    """Clear cached connection in case of socket resets."""
    _db.cache_clear()
    _graph_for.cache_clear()


def validate_repo(repo: str) -> str:
    """Validate repository name against registered keys and slugs.
    
    Returns the normalized canonical repository key or raises ValueError.
    """
    if not repo or not isinstance(repo, str):
        raise ValueError("Repository identifier must be a non-empty string.")
    
    clean = repo.strip()
    lower = clean.lower()

    # Prefer canonical short key if slug matches a pre-registered slug (e.g. 'pydantic/pydantic' -> 'pydantic')
    for short_key in ("pydantic", "fastapi", "redis"):
        if lower == REPO_SLUGS.get(short_key, "").lower():
            return short_key

    if clean in REPOS:
        return clean
    if lower in REPOS:
        return lower

    # Check by full slug match in REPO_SLUGS
    for k, slug in REPO_SLUGS.items():
        if slug.lower() == lower:
            return k

    available = ", ".join(sorted(set(REPO_SLUGS.values())))
    raise ValueError(f"Repository '{repo}' not found. Available repositories: {available}")


def is_valid_repo(repo: str) -> bool:
    try:
        validate_repo(repo)
        return True
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=16)
def _graph_for(repo_key: str):
    valid_key = validate_repo(repo_key)
    graph_name = REPOS[valid_key]
    return _db().select_graph(graph_name)


def get_graph(repo: str = DEFAULT_REPO):
    key = validate_repo(repo)
    return _graph_for(key)


def execute_graph_query(query: str, params: Optional[dict] = None, repo: str = DEFAULT_REPO):
    """Execute a Cypher query on the designated repository graph with timing instrumentation."""
    key = validate_repo(repo)
    g = _graph_for(key)
    t0 = time.perf_counter()
    try:
        res = g.query(query, params or {})
    except Exception:
        # If connection died, try once to reset and retry
        reset_db_connection()
        g = _graph_for(key)
        res = g.query(query, params or {})
    duration = time.perf_counter() - t0
    record_query(query, duration, key)
    return res


def get_connection_status() -> dict:
    cached = METADATA_CACHE.get("falkor_connection_status")
    if cached is not None:
        return cached

    try:
        g = get_graph()
        g.query("MATCH (n) RETURN 1 LIMIT 1")
        status = {"is_live": True, "message": "Connected to FalkorDB"}
    except Exception as e:
        status = {"is_live": False, "message": f"FalkorDB unreachable: {type(e).__name__}"}

    METADATA_CACHE.set("falkor_connection_status", status, ttl=10.0)
    return status


def is_live_falkor() -> bool:
    return get_connection_status().get("is_live", False)


def list_repos() -> list[str]:
    """Return all repositories that currently have data in FalkorDB, cached for performance."""
    cached = METADATA_CACHE.get("active_repos_list")
    if cached is not None:
        return cached

    out = []
    # Deduplicate graph targets
    seen_graphs = set()
    candidate_keys = []
    for k, gname in sorted(REPOS.items()):
        if gname not in seen_graphs:
            seen_graphs.add(gname)
            candidate_keys.append(k)

    for slug in candidate_keys:
        try:
            g = _graph_for(slug)
            res = g.query("MATCH (n) RETURN count(n) LIMIT 1").result_set
            if res and res[0][0] > 0:
                out.append(slug)
        except Exception:
            continue

    if not out and "pydantic" in REPOS:
        # Fallback to default if offline
        out = ["pydantic"]

    METADATA_CACHE.set("active_repos_list", out, ttl=30.0)
    return out


def node_count(repo: str = DEFAULT_REPO) -> int:
    key = validate_repo(repo)
    cache_key = f"node_count:{key}"
    cached = METADATA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    res = execute_graph_query("MATCH (n) RETURN count(n)", repo=key).result_set
    count = int(res[0][0]) if res else 0
    METADATA_CACHE.set(cache_key, count, ttl=45.0)
    return count


def edge_count(repo: str = DEFAULT_REPO) -> int:
    key = validate_repo(repo)
    cache_key = f"edge_count:{key}"
    cached = METADATA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    res = execute_graph_query("MATCH ()-[e]->() RETURN count(e)", repo=key).result_set
    count = int(res[0][0]) if res else 0
    METADATA_CACHE.set(cache_key, count, ttl=45.0)
    return count


def graph_provenance(repo: str = DEFAULT_REPO) -> dict:
    key = validate_repo(repo)
    cache_key = f"provenance:{key}"
    cached = METADATA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rows = execute_graph_query(
        "MATCH (m:KeystoneMetadata {key: 'provenance'}) "
        "RETURN m.source, m.repository, m.last_ingested_at, m.last_import_count, m.status "
        "ORDER BY m.last_ingested_at DESC LIMIT 1",
        {}, repo=key,
    ).result_set

    if not rows:
        prov = {
            "status": "unmarked",
            "message": "Graph data exists but has no recorded ingestion source.",
            "source": "unmarked",
            "repository": REPO_SLUGS.get(key, key),
            "last_ingested_at": None,
            "last_import_count": 0,
        }
    else:
        source, repository, ingested_at, imported, status = rows[0]
        prov = {
            "status": status or "real",
            "source": source or "github_api",
            "repository": repository or REPO_SLUGS.get(key, key),
            "last_ingested_at": ingested_at,
            "last_import_count": imported or 0,
            "message": "Data was imported from the GitHub API.",
        }

    METADATA_CACHE.set(cache_key, prov, ttl=60.0)
    return prov


def invalidate_repo_cache(repo: Optional[str] = None) -> None:
    """Invalidate cached counts and metadata after ingestion or modification."""
    if repo:
        key = validate_repo(repo)
        METADATA_CACHE.invalidate(f"*:{key}")
        METADATA_CACHE.invalidate(f"*{key}*")
    else:
        METADATA_CACHE.clear()
    METADATA_CACHE.invalidate("active_repos_list")