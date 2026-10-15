"""Execute approved actions against the sandbox repo via GitHub API.
Only touches yashsejuro/keystone-sandbox. Never any other repo."""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

SANDBOX_REPO = "yashsejuro/keystone-sandbox"
GITHUB_API = "https://api.github.com"


def _headers():
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


def request_reviewer(pr_number: int, reviewer: str) -> dict:
    """Ask `reviewer` to review PR #pr_number on the sandbox repo."""
    r = requests.post(
        f"{GITHUB_API}/repos/{SANDBOX_REPO}/pulls/{pr_number}/requested_reviewers",
        headers=_headers(),
        json={"reviewers": [reviewer]},
        timeout=15,
    )
    if r.status_code not in (200, 201):
        return {"ok": False, "status": r.status_code, "error": r.text[:200]}
    return {"ok": True, "action": "request_review",
            "target": reviewer, "pr": pr_number}


def add_label(pr_number: int, label: str) -> dict:
    """Add a label to PR #pr_number on the sandbox repo."""
    r = requests.post(
        f"{GITHUB_API}/repos/{SANDBOX_REPO}/issues/{pr_number}/labels",
        headers=_headers(),
        json={"labels": [label]},
        timeout=15,
    )
    if r.status_code not in (200, 201):
        return {"ok": False, "status": r.status_code, "error": r.text[:200]}
    return {"ok": True, "action": "add_label",
            "target": label, "pr": pr_number}


def execute(action: dict) -> dict:
    """Dispatch an approved action. action is one dict from proposed_actions."""
    try:
        kind = action.get("action")
        pr = int(action.get("on", 0))
        if kind == "request_review":
            return request_reviewer(pr, action["who"])
        if kind == "add_label":
            return add_label(pr, action["label"])
        return {"ok": False, "error": f"unknown action: {kind}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    # test: try to add a label to sandbox issue #1
    print(add_label(1, "test:keystone"))