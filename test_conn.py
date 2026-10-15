import os
from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()

db = FalkorDB(
    host=os.getenv("FALKOR_HOST"),
    port=int(os.getenv("FALKOR_PORT")),
    username=os.getenv("FALKOR_USER"),
    password=os.getenv("FALKOR_PASS"),
    socket_timeout=10,
    socket_connect_timeout=10,
)

g = db.select_graph("test")
g.query("MATCH (n) DETACH DELETE n")
g.query("CREATE (a:Person {login:'me'})-[:REVIEWED]->(b:PullRequest {number:1})")
result = g.query("MATCH (a:Person)-[:REVIEWED]->(b) RETURN a.login, b.number")
print("RESULT:", result.result_set)
g.query("MATCH (n) DETACH DELETE n")
print("OK")