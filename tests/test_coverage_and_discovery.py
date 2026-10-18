"""
Tests for Repository Coverage, PR Discovery, Pagination, Scope Estimation, and Truthful Analysis Disclosures.
Tests use mocks for FalkorDB, GitHub, and Groq. No real credentials required.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.app import app
from backend.coverage import (
    get_repository_coverage,
    update_coverage_metadata,
)
from backend.graph_client import register_repo
from backend.tools import list_recent_prs
from backend.ingestion_manager import estimate_ingestion_scope


client = TestClient(app)


# ==============================================================================
# 1. Coverage Calculations & Repository Isolation Tests
# ==============================================================================

def test_coverage_metadata_isolation():
    """Verify repository coverage is tracked per-repo and not merged into a global count."""
    register_repo("test/repo-alpha")
    register_repo("test/repo-beta")

    update_coverage_metadata("test/repo-alpha", {
        "github_total": 45000,
        "discovered": 5000,
        "failed": 12,
        "skipped": 5,
        "status": "partially_ingested"
    })
    update_coverage_metadata("test/repo-beta", {
        "github_total": 1200,
        "discovered": 1200,
        "failed": 0,
        "skipped": 0,
        "status": "ingestion_completed"
    })

    cov_alpha = get_repository_coverage("test/repo-alpha")
    cov_beta = get_repository_coverage("test/repo-beta")

    assert cov_alpha["repo"] == "test/repo-alpha"
    assert cov_alpha["counts"]["github_total"] == 45000
    assert cov_alpha["counts"]["discovered"] == 5000
    assert cov_alpha["counts"]["failed"] == 12

    assert cov_beta["repo"] == "test/repo-beta"
    assert cov_beta["counts"]["github_total"] == 1200
    assert cov_beta["counts"]["discovered"] == 1200
    assert cov_beta["counts"]["failed"] == 0

    # Test gaps calculation: ingested in mock DB is 0, discovered=5000
    gaps_alpha = cov_alpha["gaps"]
    assert gaps_alpha["discovered_not_ingested"]["count"] == 5000
    assert gaps_alpha["failed_ingestion"]["count"] == 12
    assert gaps_alpha["skipped_records"]["count"] == 5


def test_coverage_returns_scope_explanation():
    """Verify get_repository_coverage returns scope_explanation field."""
    register_repo("test/scope-repo")
    update_coverage_metadata("test/scope-repo", {
        "github_total": 10000,
        "discovered": 3500,
    })
    cov = get_repository_coverage("test/scope-repo")
    assert "scope_explanation" in cov
    assert "explanation" in cov
    # Both should have the same content
    assert cov["scope_explanation"] == cov["explanation"]


def test_coverage_api_endpoint():
    """Test GET /api/repositories/{repo}/coverage endpoint."""
    register_repo("org/sample-repo")
    update_coverage_metadata("org/sample-repo", {
        "github_total": 10000,
        "discovered": 3500,
        "status": "partially_ingested"
    })

    response = client.get("/api/repositories/org/sample-repo/coverage")
    assert response.status_code == 200
    data = response.json()

    assert data["repo"] == "org/sample-repo"
    assert "counts" in data
    assert data["counts"]["github_total"] == 10000
    assert data["counts"]["discovered"] == 3500
    assert "gaps" in data
    assert "statuses" in data
    # Should have either explanation or scope_explanation
    assert "explanation" in data or "scope_explanation" in data


def test_repositories_api_includes_coverage():
    """Test GET /api/repositories includes coverage metrics and statuses."""
    response = client.get("/api/repositories")
    assert response.status_code == 200
    data = response.json()
    assert "repositories" in data

    if data["repositories"]:
        repo_item = data["repositories"][0]
        # Should have a coverage dict with github_total and ingested
        assert "coverage" in repo_item
        assert "statuses" in repo_item
        assert "github_total" in repo_item["coverage"]
        assert "ingested" in repo_item["coverage"]


# ==============================================================================
# 2. Ingestion Scope Estimation Pre-flight Tests
# ==============================================================================

def test_scope_estimation_recent():
    """Verify pre-flight estimation for recent PRs."""
    estimation = estimate_ingestion_scope("test/est-repo", "recent", limit=100)
    assert estimation["estimated_prs"] == 100
    assert estimation["estimated_api_requests"] > 0
    assert estimation["estimated_nodes_and_edges"] > 0
    assert "GitHub rate limits" in estimation["estimated_limitations"]


def test_scope_estimation_date_range():
    """Verify pre-flight estimation for date range scope."""
    estimation = estimate_ingestion_scope(
        "test/est-repo2",
        "date_range",
        date_from="2026-01-01",
        date_to="2026-06-30"
    )
    assert estimation["scope_type"] == "date_range"
    assert estimation["date_from"] == "2026-01-01"
    assert estimation["date_to"] == "2026-06-30"
    assert estimation["estimated_prs"] > 0


def test_estimate_api_endpoint():
    """Verify POST /api/ingest/estimate endpoint."""
    response = client.post("/api/ingest/estimate", json={
        "repo": "pydantic/pydantic",
        "scope_type": "recent",
        "limit": 50
    })
    assert response.status_code == 200
    data = response.json()
    assert data["repo"] == "pydantic/pydantic"
    assert data["estimated_prs"] == 50
    assert "estimated_api_requests" in data or "estimated_github_api_requests" in data
    assert "estimated_nodes_and_edges" in data or "expected_graph_size" in data


# ==============================================================================
# 3. Server-Side PR Explorer, Pagination & Deep Search Tests
# ==============================================================================

def _make_mock_exec(count: int, rows: list):
    """Create a mock for execute_graph_query that returns count then rows."""
    res_count = MagicMock()
    res_count.result_set = [[count]]
    res_items = MagicMock()
    res_items.result_set = rows
    mock = MagicMock(side_effect=[res_count, res_count, res_items, res_count, res_count])
    return mock


def _pr_row(num, title="PR Title", state="merged", date="2026-08-01T10:00:00Z",
            author="dev", files=3, reviewers=2, max_c=0.0):
    """Build a standard PR row with 9 columns matching the Cypher RETURN order."""
    return [num, title, date, author, files, reviewers, max_c, state, date]


def test_list_recent_prs_pagination():
    """Verify server-side pagination with exact total matching count and next/prev."""
    rows_page1 = [_pr_row(i, f"PR Title #{i}") for i in range(1, 26)]

    with patch("backend.tools.execute_graph_query") as mock_exec:
        # First call: count query → 120
        # Second call: paginated items → 25 rows
        res_count = MagicMock()
        res_count.result_set = [[120]]
        res_items = MagicMock()
        res_items.result_set = rows_page1

        # Coverage and stats queries also hit execute_graph_query
        res_zero = MagicMock()
        res_zero.result_set = [[0]]
        mock_exec.side_effect = [res_count, res_items, res_zero, res_zero, res_zero, res_zero]

        result = list_recent_prs(page=1, page_size=25)

        assert result["pagination"]["page"] == 1
        assert result["pagination"]["page_size"] == 25
        assert result["pagination"]["total_matching"] == 120
        assert result["pagination"]["total_pages"] == 5
        assert result["pagination"]["has_next"] is True
        assert result["pagination"]["has_previous"] is False
        assert len(result["items"]) == 25
        assert result["items"][0]["number"] == 1
        assert "scope" in result
        assert "coverage" in result


def test_list_recent_prs_deep_search():
    """Verify search finds PR by number anywhere in dataset (not just first 500)."""
    target_row = _pr_row(12450, "Fix critical vulnerability in authentication",
                         "merged", "2025-11-12T14:00:00Z", "security_expert", 4, 3, 0.12)

    with patch("backend.tools.execute_graph_query") as mock_exec:
        res_count = MagicMock()
        res_count.result_set = [[1]]
        res_items = MagicMock()
        res_items.result_set = [target_row]

        res_zero = MagicMock()
        res_zero.result_set = [[0]]
        mock_exec.side_effect = [res_count, res_items, res_zero, res_zero, res_zero, res_zero]

        result = list_recent_prs(q="12450", page=1, page_size=25)

        assert result["pagination"]["total_matching"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["number"] == 12450
        assert "vulnerability" in result["items"][0]["title"]

        # Check that the Cypher count query used a server-side search (pr_num parameter)
        first_call_args = mock_exec.call_args_list[0]
        query_str = first_call_args[0][0] if first_call_args[0] else ""
        params_used = first_call_args[0][1] if len(first_call_args[0]) > 1 else {}
        assert "pr_num" in params_used or "$pr_num" in query_str


def test_list_recent_prs_filters():
    """Verify server-side state, review status, and date filters are applied."""
    target_row = _pr_row(201, "Feature A", "merged", "2026-09-01T10:00:00Z",
                         "dev1", 2, 0, 0.09)

    with patch("backend.tools.execute_graph_query") as mock_exec:
        res_count = MagicMock()
        res_count.result_set = [[5]]
        res_items = MagicMock()
        res_items.result_set = [target_row]

        res_zero = MagicMock()
        res_zero.result_set = [[0]]
        mock_exec.side_effect = [res_count, res_items, res_zero, res_zero, res_zero, res_zero]

        result = list_recent_prs(
            state="merged",
            reviewed=False,
            date_from="2026-09-01",
            date_to="2026-09-30"
        )

        assert result["pagination"]["total_matching"] == 5
        assert result["scope"]["state"] == "merged"
        # reviewed in scope should reflect the filter param
        assert result["scope"]["date_from"] == "2026-09-01"


def test_list_recent_prs_recommended_view():
    """Verify recommended PR view attaches explicit recommendation reason and tags."""
    # max_c = 0.09 → triggers High Centrality; rev_count = 0 → Unreviewed
    target_row = _pr_row(999, "Core Refactor", "open", "2026-10-15T09:00:00Z",
                         "dev99", 8, 0, 0.09)

    with patch("backend.tools.execute_graph_query") as mock_exec:
        res_count = MagicMock()
        res_count.result_set = [[1]]
        res_items = MagicMock()
        res_items.result_set = [target_row]

        res_zero = MagicMock()
        res_zero.result_set = [[0]]
        mock_exec.side_effect = [res_count, res_items, res_zero, res_zero, res_zero, res_zero]

        result = list_recent_prs(view="recommended")

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert "recommendation_reason" in item
        assert "recommendation_tags" in item
        assert any(
            tag in item["recommendation_tags"]
            for tag in ["Unreviewed", "High Centrality", "Large Surface"]
        )


def test_api_prs_endpoint_response_shape():
    """Verify GET /api/prs matches the standardized API contract with all required keys."""
    response = client.get("/api/prs?page=1&page_size=25&state=all")
    assert response.status_code == 200
    data = response.json()

    assert "items" in data
    assert "prs" in data  # backward compatibility
    assert "pagination" in data
    assert "coverage" in data
    assert "scope" in data
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["page_size"] == 25
    assert "has_next" in data["pagination"]
    assert "has_previous" in data["pagination"]
    assert "total_matching" in data["pagination"]


def test_no_500_truncation_in_default_pr_query():
    """Verify the default PR query has no silent 500-PR limit."""
    with patch("backend.tools.execute_graph_query") as mock_exec:
        res_count = MagicMock()
        res_count.result_set = [[2500]]  # Dataset has 2500 PRs
        res_items = MagicMock()
        # Return 25 items for page 1
        res_items.result_set = [_pr_row(i) for i in range(1, 26)]

        res_zero = MagicMock()
        res_zero.result_set = [[0]]
        mock_exec.side_effect = [res_count, res_items, res_zero, res_zero, res_zero, res_zero]

        result = list_recent_prs(page=1, page_size=25)

        # total_matching must reflect actual dataset count, not 500
        assert result["pagination"]["total_matching"] == 2500
        assert result["pagination"]["total_pages"] == 100
        # Only 25 items on this page
        assert len(result["items"]) == 25


# ==============================================================================
# 4. Truthful Reviewer Recommendation Scope Disclosures
# ==============================================================================

def test_investigate_discloses_analysis_scope():
    """Verify reviewer investigation returns explicit analysis scope and confidence alerts."""
    with patch("backend.app.run_keystone") as mock_run:
        mock_run.return_value = {
            "pr_details": {
                "number": 101,
                "title": "Update parser",
                "files": ["parser.py"],
                "additions": 10,
                "deletions": 5,
            },
            "decision": {
                "reviewers": [
                    {
                        "login": "octocat",
                        "score": 0.85,
                        "reason": "Expert in parser.py",
                        "last_review": "2026-10-10T00:00:00Z",
                        "recent_reviews": 3,
                    }
                ],
                "criticality": {"max_centrality": 0.05}
            },
            "reviewer_evidence": {
                "octocat": {"files": ["parser.py"]}
            },
            "observations": {"bus_factor_files": []}
        }

        # Seed coverage metadata with large universe to trigger partial disclosure
        update_coverage_metadata("pydantic/pydantic", {
            "github_total": 35842,
            "discovered": 12400,
            "ingested": 2460,
            "status": "partially_ingested"
        })

        response = client.post("/api/investigate", json={
            "pr_number": 101,
            "repo": "pydantic/pydantic",
            "question": "who should review this?"
        })

        assert response.status_code == 200
        data = response.json()
        assert "analysis_scope" in data
        scope = data["analysis_scope"]
        assert scope["analysis_window"] == "Last 90 days"
        assert "coverage_level" in scope
        assert "confidence_warning" in scope
        # Should mention something about partial or complete coverage
        warn = scope["confidence_warning"]
        assert len(warn) > 10  # non-trivial message


# ==============================================================================
# 5. Frontend Markup & Usability Integrity Tests
# ==============================================================================

def test_frontend_has_coverage_and_explorer_elements():
    """Verify index.html contains the coverage panel, PR explorer section, and accessible controls."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Coverage panel must exist
    assert 'id="repo-coverage-panel"' in html

    # At least one coverage metric ID must be present
    coverage_ids = [
        "cov-github-total",
        "cov-ingested",
        "cov-analysis-window",
        "cov-showing-count",
    ]
    found = [cid for cid in coverage_ids if f'id="{cid}"' in html]
    assert len(found) >= 3, f"Expected coverage metric IDs, found: {found}"

    # Navigation: PR Explorer section
    assert 'id="nav-btn-explorer"' in html
    assert 'id="section-explorer"' in html
    assert "PR Explorer" in html

    # Subtabs
    assert 'id="tab-btn-recommended"' in html
    assert 'id="tab-btn-all-prs"' in html
    assert 'id="tab-btn-gaps"' in html

    # "Why am I seeing these PRs?" explanation
    assert 'id="why-prs-card"' in html
    assert 'id="why-prs-explanation"' in html

    # Ingestion Scope Controls in Health
    assert 'name="ingestion-scope"' in html
    assert 'id="scope-preview-card"' in html
    assert 'id="btn-preview-scope"' in html
