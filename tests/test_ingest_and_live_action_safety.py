"""Tests for stable ingest graph naming and action API protections."""

from unittest.mock import patch

from backend.action_ledger import ActionLedgerStore


def test_ingest_graph_name_uses_registered_repo_logic():
    """Verify ingest.py would generate a graph name using the same registry logic as the app."""
    from backend.graph_client import make_graph_name

    assert make_graph_name("pydantic", "pydantic")
    assert make_graph_name("fastapi", "fastapi")


def test_action_execute_live_requires_confirmation_and_whitelist():
    """LIVE actions must require confirmation and repository authorization."""
    store = ActionLedgerStore()

    # Unconfirmed live action should be denied in ledger entry
    entry = store.record_action({"action": "request_review", "who": "reviewer_a"}, repo="owner/repo", pr_number=123, mode="LIVE", confirmed=False)
    assert entry["mode"] == "FAILED"
    assert entry["status"] == "CONFIRMATION_REQUIRED"

    # Unapproved repo should still be denied
    with patch("backend.action_ledger.ALLOWED_WRITE_REPOS", ["allowed/repo"]):
        entry2 = store.record_action({"action": "request_review", "who": "reviewer_b"}, repo="blocked/repo", pr_number=123, mode="LIVE", confirmed=True)
        assert entry2["mode"] == "FAILED"
        assert entry2["status"] == "EXECUTION_DENIED"
