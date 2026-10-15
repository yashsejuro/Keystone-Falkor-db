"""Shared FalkorDB connection. Import get_graph() everywhere else."""
import os
from functools import lru_cache
from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()

GRAPH_NAME = "keystone"


@lru_cache(maxsize=1)
def get_graph():
    db = FalkorDB(
        host=os.getenv("FALKOR_HOST"),
        port=int(os.getenv("FALKOR_PORT")),
        username=os.getenv("FALKOR_USER"),
        password=os.getenv("FALKOR_PASS"),
        socket_timeout=60,
    )
    return db.select_graph(GRAPH_NAME)


def node_count():
    g = get_graph()
    return g.query("MATCH (n) RETURN count(n)").result_set[0][0]


def edge_count():
    g = get_graph()
    return g.query("MATCH ()-[e]->() RETURN count(e)").result_set[0][0]


if __name__ == "__main__":
    print("Nodes:", node_count())
    print("Edges:", edge_count())