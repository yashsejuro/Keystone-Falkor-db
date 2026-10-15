"""Shared FalkorDB connection. Multi-graph aware. No fake fallbacks."""
import os
from functools import lru_cache
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


@lru_cache(maxsize=8)
def _graph_for(repo: str):
    return _db().select_graph(REPOS.get(repo, REPOS[DEFAULT_REPO]))


def get_graph(repo: str = DEFAULT_REPO):
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


if __name__ == "__main__":
    for r in list_repos():
        print(f"{r}: {node_count(r)} nodes, {edge_count(r)} edges")