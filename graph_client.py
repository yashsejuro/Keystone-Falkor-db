"""Shared FalkorDB connection. Multi-graph aware."""
import os
from functools import lru_cache
from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()

DEFAULT_REPO = "pydantic"

# repo slug -> graph name in FalkorDB
REPOS = {
    "pydantic": "keystone_pydantic",
    "fastapi":  "keystone_fastapi",
    "redis":    "keystone_redis",
}

# repo slug -> GitHub slug
REPO_SLUGS = {
    "pydantic": "pydantic/pydantic",
    "fastapi":  "fastapi/fastapi",
    "redis":    "redis/redis",
}


@lru_cache(maxsize=1)
def _db():
    port_str = os.getenv("FALKOR_PORT", "6379")
    port = int(port_str) if port_str and port_str.isdigit() else 6379
    return FalkorDB(
        host=os.getenv("FALKOR_HOST"),
        port=port,
        username=os.getenv("FALKOR_USER"),
        password=os.getenv("FALKOR_PASS"),
        socket_timeout=10,
    )


@lru_cache(maxsize=8)
def _graph_for(repo: str):
    graph_name = REPOS.get(repo, REPOS[DEFAULT_REPO])
    return _db().select_graph(graph_name)


def get_graph(repo: str = DEFAULT_REPO):
    return _graph_for(repo)


def get_connection_status():
    host = os.getenv("FALKOR_HOST")
    if not host:
        return {"is_live": False, "message": "FALKOR_HOST not configured"}
    try:
        g = get_graph()
        g.query("MATCH (n) RETURN count(n) LIMIT 1")
        port = os.getenv("FALKOR_PORT", "6379")
        return {"is_live": True, "message": f"Connected to FalkorDB ({host}:{port})"}
    except Exception as e:
        return {"is_live": False, "message": f"FalkorDB connection failed ({type(e).__name__})"}


def list_repos():
    """Return only repos whose graph has data."""
    out = []
    for slug in REPOS:
        try:
            g = _graph_for(slug)
            n = g.query("MATCH (n) RETURN count(n)").result_set[0][0]
            if n > 0:
                out.append(slug)
        except Exception:
            pass
    return out or [DEFAULT_REPO]


def node_count(repo: str = DEFAULT_REPO):
    try:
        g = _graph_for(repo)
        return g.query("MATCH (n) RETURN count(n)").result_set[0][0]
    except Exception:
        return 0


def edge_count(repo: str = DEFAULT_REPO):
    try:
        g = _graph_for(repo)
        return g.query("MATCH ()-[e]->() RETURN count(e)").result_set[0][0]
    except Exception:
        return 0


if __name__ == "__main__":
    for r in list_repos():
        print(f"{r}: {node_count(r)} nodes, {edge_count(r)} edges")