"""API integration tests using FastAPI TestClient with mocked FalkorDB operations."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from backend.app import app

client = TestClient(app)


def test_api_health_endpoint():
    with patch("backend.app.get_connection_status", return_value={"is_live": True, "message": "Connected"}):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_live"] is True


def test_api_status_endpoint():
    with patch("backend.app.validate_repo", return_value="pydantic"):
        with patch("backend.app.get_connection_status", return_value={"is_live": True, "message": "Connected"}):
            with patch("backend.app.node_count", return_value=1200):
                with patch("backend.app.edge_count", return_value=5000):
                    with patch("backend.app.list_repos", return_value=["pydantic", "fastapi"]):
                        resp = client.get("/api/status?repo=pydantic")
                        assert resp.status_code == 200
                        data = resp.json()
                        assert data["nodes"] == 1200
                        assert data["edges"] == 5000
                        assert data["current_repo"] == "pydantic"
                        assert "centrality" in data


def test_api_repositories_endpoint():
    mock_repos = [
        {"key": "pydantic", "slug": "pydantic/pydantic", "graph_name": "keystone_pydantic",
         "nodes": 1200, "edges": 5000, "status": "ready"}
    ]
    with patch("backend.app.get_registered_repositories", return_value=mock_repos):
        resp = client.get("/api/repositories")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["repositories"]) == 1
        assert data["repositories"][0]["slug"] == "pydantic/pydantic"


def test_api_prs_pagination_and_filtering():
    mock_prs = {
        "repo": "pydantic",
        "prs": [{"number": 100, "title": "Test PR", "is_reviewed": True, "file_count": 2}],
        "count": 1,
        "page": 1,
        "page_size": 25,
        "stats": {"total": 50, "reviewed": 30, "unreviewed": 20}
    }
    with patch("backend.app.validate_repo", return_value="pydantic"):
        with patch("backend.app.list_recent_prs", return_value=mock_prs):
            resp = client.get("/api/prs?repo=pydantic&page=1&limit=25")
            assert resp.status_code == 200
            data = resp.json()
            assert data["page"] == 1
            assert len(data["prs"]) == 1


def test_api_investigate_endpoint():
    mock_keystone_res = {
        "pr_number": 13997,
        "repo": "pydantic",
        "question": "who should review this?",
        "trace": ["START: PR #13997"],
        "observations": {"bus_factor_files": []},
        "decision": {
            "reviewers": [{"login": "alice", "score": 0.9, "shared_files": 2, "recent_reviews": 4, "last_review": "2026-09-01T00:00:00Z"}],
            "risk_flags": [],
            "criticality": {"max_centrality": 0.05},
            "rationale": "Recommended alice"
        },
        "pr_details": {
            "number": 13997,
            "title": "PR Title",
            "files": ["main.py", "types.py"],
            "additions": 10,
            "deletions": 5,
        },
        "reviewer_evidence": {
            "alice": {"files": ["main.py"], "hops": 3, "path": ["PR #13997", "main.py", "alice"]}
        },
        "explain_path": {"hops": 3, "path": ["PR #13997", "main.py", "alice"]},
        "proposed_actions": [{"action": "request_review", "who": "alice", "on": 13997}]
    }

    with patch("backend.app.validate_repo", return_value="pydantic"):
        with patch("backend.app.run_keystone", return_value=mock_keystone_res):
            with patch("backend.app.narrate", return_value="Alice is recommended based on file history."):
                resp = client.post("/api/investigate", json={"pr_number": 13997, "repo": "pydantic"})
                assert resp.status_code == 200
                data = resp.json()
                assert data["pr_number"] == 13997
                assert len(data["decision"]["reviewers"]) == 1
                assert data["decision"]["reviewers"][0]["login"] == "alice"
                assert "latency_ms" in data


def test_api_cypher_security_checks():
    # 1. Reject Write
    resp_write = client.post("/api/cypher", json={"query": "CREATE (n:Test)", "repo": "pydantic"})
    assert resp_write.status_code == 400
    assert "rejected" in resp_write.json()["error"].lower()

    # 2. Reject Algorithm
    resp_algo = client.post("/api/cypher", json={"query": "CALL algo.betweenness()", "repo": "pydantic"})
    assert resp_algo.status_code == 400
    assert "restricted" in resp_algo.json()["error"].lower()

    # 3. Allow Valid Read-Only
    mock_res = MagicMock()
    mock_res.result_set = [["alice"], ["bob"]]
    with patch("backend.app.execute_graph_query", return_value=mock_res):
        resp_read = client.post("/api/cypher", json={"query": "MATCH (n:Person) RETURN n.login", "repo": "pydantic"})
        assert resp_read.status_code == 200
        assert resp_read.json()["count"] == 2


def test_api_action_execute_and_ledger():
    action = {"action": "request_review", "who": "carol", "on": 1234}

    # Dry-run execution
    resp_dry = client.post("/api/action/execute", json={
        "action": action, "repo": "pydantic", "pr_number": 1234, "mode": "DRY_RUN"
    })
    assert resp_dry.status_code == 200
    assert resp_dry.json()["entry"]["status"] == "DRY_RUN_COMPLETED"

    # Shadow execution
    resp_shadow = client.post("/api/action/execute", json={
        "action": action, "repo": "pydantic", "pr_number": 1234, "mode": "SHADOW"
    })
    assert resp_shadow.status_code == 200
    assert resp_shadow.json()["entry"]["status"] == "RECORDED_IN_SHADOW_LEDGER"

    # Ledger listing
    resp_ledger = client.get("/api/action/ledger?page=1&page_size=10")
    assert resp_ledger.status_code == 200
    data = resp_ledger.json()
    assert data["total_count"] >= 2
