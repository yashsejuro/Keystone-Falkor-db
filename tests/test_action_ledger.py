"""Unit tests for the bounded, auditable Action Ledger with mode distinction and idempotency."""
import pytest
from backend.action_ledger import ActionLedgerStore


def test_dry_run_mode():
    ledger = ActionLedgerStore(max_size=50)
    action = {"action": "request_review", "who": "alice", "on": 123}
    res = ledger.record_action(action, repo="test/repo", pr_number=123, mode="DRY_RUN")

    assert res["mode"] == "DRY_RUN"
    assert res["status"] == "DRY_RUN_COMPLETED"
    assert "Simulation" in res["destination"] or "simulation" in res["destination"]
    assert res["target"] == "alice"


def test_shadow_mode():
    ledger = ActionLedgerStore(max_size=50)
    action = {"action": "request_review", "who": "bob", "on": 456}
    res = ledger.record_action(action, repo="test/repo", pr_number=456, mode="SHADOW")

    assert res["mode"] == "SHADOW"
    assert res["status"] == "RECORDED_IN_SHADOW_LEDGER"
    assert "Shadow tracking" in res["destination"] or "shadow" in res["destination"].lower()


def test_live_mode_authorization_and_confirmation():
    ledger = ActionLedgerStore(max_size=50)
    action = {"action": "request_review", "who": "charlie", "on": 789}

    # 1. Disallowed repo should fail
    res_disallowed = ledger.record_action(action, repo="unauthorized/repo", pr_number=789, mode="LIVE", confirmed=True)
    assert res_disallowed["mode"] == "FAILED"
    assert res_disallowed["status"] == "EXECUTION_DENIED"

    # 2. Allowed repo but unconfirmed should fail
    ledger.is_write_allowed = lambda r: True  # mock allow
    res_unconfirmed = ledger.record_action(action, repo="authorized/repo", pr_number=789, mode="LIVE", confirmed=False)
    assert res_unconfirmed["mode"] == "FAILED"
    assert res_unconfirmed["status"] == "CONFIRMATION_REQUIRED"


def test_idempotency_key_prevents_duplicate_actions():
    ledger = ActionLedgerStore(max_size=50)
    action = {"action": "request_review", "who": "dave", "on": 999}
    key = "unique-key-abc-123"

    first = ledger.record_action(action, repo="test/repo", pr_number=999, mode="SHADOW", idempotency_key=key)
    second = ledger.record_action(action, repo="test/repo", pr_number=999, mode="SHADOW", idempotency_key=key)

    assert first["id"] == second["id"]
    # Verify only 1 entry was actually added
    list_res = ledger.list_actions()
    assert list_res["total_count"] == 1


def test_ledger_pagination_and_filtering():
    ledger = ActionLedgerStore(max_size=50)
    for i in range(15):
        mode = "SHADOW" if i % 2 == 0 else "DRY_RUN"
        ledger.record_action({"action": "test", "who": f"user{i}"}, repo="repo_a" if i < 10 else "repo_b",
                             pr_number=i, mode=mode)

    # Filter by mode
    shadow_res = ledger.list_actions(mode="SHADOW")
    assert all(e["mode"] == "SHADOW" for e in shadow_res["ledger"])

    # Filter by repo
    repo_b_res = ledger.list_actions(repo="repo_b")
    assert all(e["repo"] == "repo_b" for e in repo_b_res["ledger"])

    # Pagination
    p1 = ledger.list_actions(page=1, page_size=5)
    p2 = ledger.list_actions(page=2, page_size=5)
    assert len(p1["ledger"]) == 5
    assert len(p2["ledger"]) == 5
    assert p1["ledger"][0]["id"] != p2["ledger"][0]["id"]


def test_bounded_ledger_size():
    capacity = 10
    ledger = ActionLedgerStore(max_size=capacity)
    for i in range(25):
        ledger.record_action({"action": "ping", "who": f"user{i}"}, repo="test/repo", pr_number=i)

    list_res = ledger.list_actions(page_size=50)
    assert list_res["total_count"] == capacity
    assert len(list_res["ledger"]) == capacity
