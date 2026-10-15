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


SANDBOX_TARGET_ISSUE = 1   # all approved actions target this sandbox issue for the demo


def execute(action: dict) -> dict:
    """Dispatch an approved action. All actions target the sandbox repo.
    For the demo, every pydantic PR maps to SANDBOX_TARGET_ISSUE."""
    try:
        kind = action.get("action")
        if kind == "request_review":
            who = action["who"]
            # PR doesn't exist on sandbox, so post a comment as the "review request"
            return post_comment(
                SANDBOX_TARGET_ISSUE,
                f"🤖 Keystone requests review from **@{who}** for this change.",
            )
        if kind == "add_label":
            return add_label(SANDBOX_TARGET_ISSUE, action["label"])
        if kind == "post_comment":
            return post_comment(SANDBOX_TARGET_ISSUE, action.get("body", ""))
        return {"ok": False, "error": f"unknown action: {kind}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    
def post_comment(pr_number: int, body: str) -> dict:
    """Post a comment on a sandbox issue/PR."""
    r = requests.post(
        f"{GITHUB_API}/repos/{SANDBOX_REPO}/issues/{pr_number}/comments",
        headers=_headers(),
        json={"body": body},
        timeout=15,
    )
    if r.status_code not in (200, 201):
        return {"ok": False, "status": r.status_code, "error": r.text[:200]}
    return {"ok": True, "action": "post_comment", "pr": pr_number, "url": r.json().get("html_url")}

if __name__ == "__main__":
    # test: try to add a label to sandbox issue #1
    print(add_label(1, "test:keystone"))