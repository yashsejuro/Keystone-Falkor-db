"""Auditable, bounded action ledger with live/shadow/dry-run enforcement and idempotency protection."""
import os
import uuid
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Any
import requests

logger = logging.getLogger("keystone.action_ledger")

MAX_LEDGER_ENTRIES = 1000

WRITE_REPOS_CONFIG = os.getenv("KEYSTONE_WRITE_REPOS", "").strip()
ALLOWED_WRITE_REPOS = [r.strip().lower() for r in WRITE_REPOS_CONFIG.split(",") if r.strip()]
SANDBOX_REPO = os.getenv("KEYSTONE_SANDBOX_REPO", "yashsejuro/keystone-sandbox").strip()


class ActionLedgerStore:
    def __init__(self, max_size: int = MAX_LEDGER_ENTRIES):
        self.max_size = max_size
        self._entries: list[dict] = []
        self._idempotency_map: dict[str, dict] = {}
        self._lock = threading.Lock()

    def is_write_allowed(self, repo_slug: str) -> bool:
        clean = repo_slug.strip().lower()
        if not ALLOWED_WRITE_REPOS:
            return False
        return clean in ALLOWED_WRITE_REPOS or any(
            clean.endswith("/" + w) or w.endswith("/" + clean) for w in ALLOWED_WRITE_REPOS
        )

    def record_action(self, action_data: dict, repo: str, pr_number: int,
                      mode: str = "SHADOW", confirmed: bool = False,
                      idempotency_key: Optional[str] = None) -> dict:
        """Process an action with idempotency protection and strict mode distinction."""
        with self._lock:
            if idempotency_key and idempotency_key in self._idempotency_map:
                logger.info(f"Returning cached action for idempotency key {idempotency_key}")
                return self._idempotency_map[idempotency_key]

        action_type = str(action_data.get("action", "UNKNOWN")).upper()
        target = str(action_data.get("who") or action_data.get("label") or "PR")
        reason = str(action_data.get("reason", "Graph-directed decision"))
        timestamp = datetime.now(timezone.utc).isoformat()
        action_id = f"ACT-{uuid.uuid4().hex[:8].upper()}"

        clean_mode = mode.upper().strip()
        if clean_mode not in ("DRY_RUN", "SHADOW", "LIVE"):
            clean_mode = "SHADOW"

        # 1. DRY RUN
        if clean_mode == "DRY_RUN":
            entry = {
                "id": action_id,
                "timestamp": timestamp,
                "repo": repo,
                "pr_number": pr_number,
                "action": action_type,
                "target": target,
                "reason": reason,
                "mode": "DRY_RUN",
                "status": "DRY_RUN_COMPLETED",
                "destination": "Local simulation",
                "safety_notice": "Dry-run only; no external calls or mutations performed.",
                "error": None,
                "idempotency_key": idempotency_key,
            }

        # 2. LIVE EXECUTION
        elif clean_mode == "LIVE":
            if not self.is_write_allowed(repo):
                entry = {
                    "id": action_id,
                    "timestamp": timestamp,
                    "repo": repo,
                    "pr_number": pr_number,
                    "action": action_type,
                    "target": target,
                    "reason": reason,
                    "mode": "FAILED",
                    "status": "EXECUTION_DENIED",
                    "destination": f"{repo} PR #{pr_number}",
                    "safety_notice": f"Repository '{repo}' is not listed in KEYSTONE_WRITE_REPOS.",
                    "error": "Live execution unauthorized for this repository.",
                    "idempotency_key": idempotency_key,
                }
            elif not confirmed:
                entry = {
                    "id": action_id,
                    "timestamp": timestamp,
                    "repo": repo,
                    "pr_number": pr_number,
                    "action": action_type,
                    "target": target,
                    "reason": reason,
                    "mode": "FAILED",
                    "status": "CONFIRMATION_REQUIRED",
                    "destination": f"{repo} PR #{pr_number}",
                    "safety_notice": "Live actions require explicit confirmation.",
                    "error": "Action was not confirmed for live execution.",
                    "idempotency_key": idempotency_key,
                }
            else:
                # Perform real GitHub API call
                token = os.getenv("GITHUB_TOKEN", "").strip()
                if not token:
                    entry = {
                        "id": action_id,
                        "timestamp": timestamp,
                        "repo": repo,
                        "pr_number": pr_number,
                        "action": action_type,
                        "target": target,
                        "reason": reason,
                        "mode": "FAILED",
                        "status": "EXECUTION_FAILED",
                        "destination": f"{repo} PR #{pr_number}",
                        "safety_notice": "GITHUB_TOKEN required for live dispatch.",
                        "error": "Missing GITHUB_TOKEN environment variable.",
                        "idempotency_key": idempotency_key,
                    }
                else:
                    success, err_msg = self._dispatch_live_github_action(token, repo, pr_number, action_type, target)
                    if success:
                        entry = {
                            "id": action_id,
                            "timestamp": timestamp,
                            "repo": repo,
                            "pr_number": pr_number,
                            "action": action_type,
                            "target": target,
                            "reason": reason,
                            "mode": "LIVE",
                            "status": "EXECUTED_ON_GITHUB",
                            "destination": f"GitHub API: {repo} PR #{pr_number}",
                            "safety_notice": "Executed live on GitHub repository.",
                            "error": None,
                            "idempotency_key": idempotency_key,
                        }
                    else:
                        entry = {
                            "id": action_id,
                            "timestamp": timestamp,
                            "repo": repo,
                            "pr_number": pr_number,
                            "action": action_type,
                            "target": target,
                            "reason": reason,
                            "mode": "FAILED",
                            "status": "EXECUTION_FAILED",
                            "destination": f"GitHub API: {repo} PR #{pr_number}",
                            "safety_notice": "GitHub API dispatch failed.",
                            "error": err_msg,
                            "idempotency_key": idempotency_key,
                        }

        # 3. SHADOW MODE
        else:
            entry = {
                "id": action_id,
                "timestamp": timestamp,
                "repo": repo,
                "pr_number": pr_number,
                "action": action_type,
                "target": target,
                "reason": reason,
                "mode": "SHADOW",
                "status": "RECORDED_IN_SHADOW_LEDGER",
                "destination": f"Shadow tracking for {SANDBOX_REPO}",
                "safety_notice": f"Recorded in shadow audit ledger; logins formatted as code to prevent upstream notifications.",
                "error": None,
                "idempotency_key": idempotency_key,
            }

        with self._lock:
            self._entries.insert(0, entry)
            if len(self._entries) > self.max_size:
                removed = self._entries.pop()
                if removed.get("idempotency_key") and removed["idempotency_key"] in self._idempotency_map:
                    del self._idempotency_map[removed["idempotency_key"]]
            if idempotency_key:
                self._idempotency_map[idempotency_key] = entry

        return entry

    def _dispatch_live_github_action(self, token: str, repo: str, pr_number: int,
                                    action_type: str, target: str) -> tuple[bool, Optional[str]]:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Keystone-Action-Dispatcher/2.0",
        }
        try:
            if action_type == "REQUEST_REVIEW":
                url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/requested_reviewers"
                resp = requests.post(url, json={"reviewers": [target]}, headers=headers, timeout=15)
            elif action_type == "ADD_LABEL":
                url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels"
                resp = requests.post(url, json={"labels": [target]}, headers=headers, timeout=15)
            else:
                return False, f"Unsupported live action type: {action_type}"

            if resp.status_code in (200, 201):
                return True, None
            return False, f"GitHub API error {resp.status_code}: {resp.text[:120]}"
        except Exception as e:
            return False, f"Network exception communicating with GitHub: {type(e).__name__}: {e}"

    def list_actions(self, repo: Optional[str] = None, mode: Optional[str] = None,
                     page: int = 1, page_size: int = 20) -> dict:
        with self._lock:
            filtered = self._entries

            if repo and repo != "all":
                repo_clean = repo.strip().lower()
                filtered = [e for e in filtered if e.get("repo", "").lower() == repo_clean]

            if mode and mode != "all":
                mode_clean = mode.strip().upper()
                filtered = [e for e in filtered if e.get("mode") == mode_clean]

            total_count = len(filtered)
            live_count = sum(1 for e in self._entries if e.get("mode") == "LIVE")
            shadow_count = sum(1 for e in self._entries if e.get("mode") == "SHADOW")
            failed_count = sum(1 for e in self._entries if e.get("mode") == "FAILED")
            dry_run_count = sum(1 for e in self._entries if e.get("mode") == "DRY_RUN")

            # Pagination
            safe_page = max(1, page)
            safe_page_size = max(1, min(page_size, 100))
            start_idx = (safe_page - 1) * safe_page_size
            end_idx = start_idx + safe_page_size
            paginated_items = filtered[start_idx:end_idx]

            return {
                "ledger": paginated_items,
                "total_count": total_count,
                "page": safe_page,
                "page_size": safe_page_size,
                "total_pages": max(1, (total_count + safe_page_size - 1) // safe_page_size),
                "counts": {
                    "total": len(self._entries),
                    "live": live_count,
                    "shadow": shadow_count,
                    "dry_run": dry_run_count,
                    "failed": failed_count,
                },
                "sandbox_repo": SANDBOX_REPO,
                "allowed_write_repos": ALLOWED_WRITE_REPOS,
            }

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._idempotency_map.clear()


ACTION_LEDGER_STORE = ActionLedgerStore()
