"""Unit tests for the repository ingestion engine and job manager."""
import pytest
from unittest.mock import MagicMock, patch
from backend.ingestion_manager import IngestionJob, IngestionJobManager


def test_ingestion_job_state_transitions():
    job = IngestionJob("test-job-1", "octocat/hello-world", target_limit=50)
    assert job.status == "QUEUED"
    assert job.prs_processed == 0

    job.update_progress(pr_inc=5, file_inc=12, rev_inc=4, page=2)
    assert job.prs_processed == 5
    assert job.files_processed == 12
    assert job.reviews_processed == 4
    assert job.current_page == 2

    job.set_status("IN_PROGRESS")
    assert job.status == "IN_PROGRESS"
    assert job.end_time is None

    job.set_status("COMPLETED")
    assert job.status == "COMPLETED"
    assert job.end_time is not None


def test_ingestion_job_cancellation():
    job = IngestionJob("test-job-cancel", "octocat/hello-world")
    job.cancel()
    assert job.is_cancelled is True
    assert job.status == "CANCELLED"
    assert job.end_time is not None


def test_job_manager_concurrent_job_prevention():
    mgr = IngestionJobManager()
    slug = "owner/concurrent-test-repo"

    # Start a mock job with Thread patched
    with patch("threading.Thread"):
        job1 = mgr.start_job(slug, target_limit=10)
        assert job1.repo_slug == slug

        # Attempting to start second job on same repo raises RuntimeError
        with pytest.raises(RuntimeError, match="already in progress"):
            mgr.start_job(slug, target_limit=10)

        # Once job completes, new job can start
        job1.set_status("COMPLETED")
        with mgr._manager_lock:
            if slug.lower() in mgr._active_repos:
                del mgr._active_repos[slug.lower()]

        job2 = mgr.start_job(slug, target_limit=10)
        assert job2.job_id != job1.job_id
        job2.set_status("COMPLETED")
        with mgr._manager_lock:
            if slug.lower() in mgr._active_repos:
                del mgr._active_repos[slug.lower()]


def test_github_api_404_error_handling():
    mgr = IngestionJobManager()
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_session.get.return_value = mock_resp

    data, code, err = mgr._fetch_github_json(mock_session, "https://api.github.com/repos/missing/repo")
    assert data is None
    assert code == 404
    assert "not found" in err.lower()


def test_github_api_rate_limit_detection():
    mgr = IngestionJobManager()
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "API rate limit exceeded for user"
    mock_resp.headers = {}
    mock_session.get.return_value = mock_resp

    data, code, err = mgr._fetch_github_json(mock_session, "https://api.github.com/repos/test/repo")
    assert data is None
    assert code == 403
    assert "rate limit exceeded" in err.lower()


def test_batched_unwind_query_generation():
    mgr = IngestionJobManager()
    executed_queries = []

    def mock_execute(q, params=None, repo=None):
        executed_queries.append((q, params))
        m = MagicMock()
        m.result_set = []
        return m

    with patch("backend.ingestion_manager.execute_graph_query", mock_execute):
        pr_data = {
            "number": 101,
            "title": "Fix issue",
            "state": "closed",
            "created_at": "2026-01-01T00:00:00Z",
            "merged_at": "2026-01-02T00:00:00Z",
            "user": {"login": "alice"},
            "additions": 10,
            "deletions": 5,
        }
        files = [
            {"filename": "src/core.py", "additions": 8, "deletions": 2},
            {"filename": "tests/test_core.py", "additions": 2, "deletions": 3},
        ]
        reviews = [
            {"user": {"login": "bob"}, "state": "APPROVED", "submitted_at": "2026-01-02T00:00:00Z"}
        ]

        mgr._ingest_single_pr_batch("test_repo", pr_data, files, reviews)

        # Verify UNWIND was used for batch writing files and reviews
        unwind_queries = [q for q, p in executed_queries if "UNWIND" in q]
        assert len(unwind_queries) == 2, "Expected UNWIND queries for batch writing files and reviews"
        assert any("$files AS item" in q for q in unwind_queries)
        assert any("$reviews AS rev" in q for q in unwind_queries)
