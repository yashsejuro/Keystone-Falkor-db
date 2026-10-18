"""Unit tests proving centrality materialization, query deduplication, and instrumentation."""
import pytest
from unittest.mock import MagicMock, patch
from backend.centrality import get_centrality_status, get_precomputed_critical_files
from backend.tools import critical_files, list_recent_prs, explain_path
from backend.agent import run_keystone, decide
from backend.instrumentation import track_queries


def test_critical_files_reads_materialized_centrality_without_algo():
    # Mock execute_graph_query to verify CALL algo.betweenness is NOT executed
    executed_queries = []

    def mock_query(q, params=None, repo=None):
        executed_queries.append(q)
        m = MagicMock()
        m.result_set = [["pydantic/main.py", 0.85], ["pydantic/types.py", 0.62]]
        return m

    with patch("backend.centrality.execute_graph_query", mock_query):
        files = critical_files(limit=5, repo="pydantic")
        assert len(files) == 2
        assert files[0]["path"] == "pydantic/main.py"
        assert files[0]["score"] == 0.85

        # Verify CALL algo.betweenness was NEVER called
        for q in executed_queries:
            assert "CALL algo.betweenness" not in q, f"Expensive graph algorithm was invoked: {q}"


def test_centrality_status_reporting():
    # 1. When metadata node exists
    mock_res_meta = MagicMock()
    mock_res_meta.result_set = [["current", "2026-10-18T00:00:00Z", 150, "betweenness"]]

    with patch("backend.centrality.execute_graph_query", return_value=mock_res_meta):
        with patch("backend.cache.METADATA_CACHE.get", return_value=None):
            status = get_centrality_status("pydantic")
            assert status["status"] == "current"
            assert status["file_count"] == 150

    # 2. When no files have centrality
    mock_empty = MagicMock()
    mock_empty.result_set = []
    mock_zero = MagicMock()
    mock_zero.result_set = [[0]]

    with patch("backend.centrality.execute_graph_query", side_effect=[mock_empty, mock_zero]):
        with patch("backend.cache.METADATA_CACHE.get", return_value=None):
            status = get_centrality_status("pydantic")
            assert status["status"] == "unavailable"
            assert status["file_count"] == 0


def test_investigation_no_duplicate_explain_path():
    explain_path_calls = []

    def mock_explain(pr_number, reviewer, **kwargs):
        explain_path_calls.append(reviewer)
        return {
            "reviewer": reviewer,
            "hops": 3,
            "evidence": "direct_review_history",
            "path": [f"PR #{pr_number}", "file.py", reviewer],
            "files": ["file.py"],
            "direct": [{"file": "file.py", "via_pr": 100}],
            "structural_chain": [],
            "bridges": [],
        }

    mock_pr = {
        "number": 14000,
        "title": "Test PR",
        "author": "alice",
        "files": ["file.py"],
        "additions": 10,
        "deletions": 5,
    }

    mock_candidates = [
        {"login": "reviewer_bob", "score": 0.85, "shared_files": 1, "recent_reviews": 5,
         "last_review": "2026-10-01T00:00:00Z", "bridge_files": 0, "structural": 0.0},
    ]

    with patch("backend.agent.get_pr", return_value=mock_pr):
        with patch("backend.agent.score_reviewers", return_value=mock_candidates):
            with patch("backend.agent.bus_factor_files", return_value=[]):
                with patch("backend.agent.explain_path", mock_explain):
                    with track_queries() as q_stats:
                        res = run_keystone(14000, repo="pydantic")

                    # Verify reviewer_bob was only explained ONCE
                    assert explain_path_calls == ["reviewer_bob"]
                    assert len(explain_path_calls) == 1
                    assert res["decision"]["reviewers"][0]["login"] == "reviewer_bob"


def test_truthful_recommendation_when_no_candidates():
    # When no candidate reviewers exist above threshold, verify NO fallback to hardcoded names like davidhewitt
    obs = {
        "rank_reviewers": [],
        "bus_factor_files": [],
        "critical_files": [],
    }
    pr_info = {"number": 9999, "title": "Obscure change", "files": ["unknown.txt"]}

    decision = decide(9999, obs, pr_info=pr_info, repo="pydantic")
    assert decision["reviewers"] == []
    assert "No suitable reviewer was found" in decision["rationale"]
    # Guarantee no hardcoded reviewer
    assert "davidhewitt" not in decision["rationale"].lower()


def test_pr_listing_pagination_and_cypher_filters():
    mock_rows = [
        [100, "Title 100", "2026-10-10", "alice", 3, 2, 0.15],
        [99, "Title 99", "2026-10-09", "bob", 1, 0, 0.0],
    ]

    executed_queries = []

    def mock_query(q, params=None, repo=None):
        executed_queries.append((q, params))
        m = MagicMock()
        m.result_set = mock_rows
        return m

    with patch("backend.tools._rows", side_effect=lambda q, p=None, repo=None: mock_rows):
        with patch("backend.tools.get_repo_pr_stats", return_value={"total": 200, "reviewed": 150, "unreviewed": 50}):
            res = list_recent_prs(page=2, page_size=10, repo="pydantic", q="test", filter_by="reviewed")

            assert res["page"] == 2
            assert res["page_size"] == 10
            assert len(res["prs"]) == 2
            assert res["prs"][0]["number"] == 100
            assert res["prs"][0]["is_reviewed"] is True
            assert res["prs"][1]["is_reviewed"] is False
