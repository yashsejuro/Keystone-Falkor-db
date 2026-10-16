"""Execute human-approved actions on GitHub.

direct: the analysed repository is listed in KEYSTONE_WRITE_REPOS, so a review request or
        label lands on the pull request itself.
shadow: any other repository. The action is written to a per-PR tracking issue in the
        sandbox repository instead. Reviewer logins and upstream references are written as
        code spans, so no maintainer is @mentioned and the upstream PR gets no cross-reference.
"""
import os
from threading import Lock

import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_API = "https://api.github.com"
SANDBOX_REPO = os.getenv("KEYSTONE_SANDBOX_REPO") or "yashsejuro/keystone-sandbox"
KINDS = ("request_review", "add_label")
_TRACKING_LOCK = Lock()


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub returned {status}: {message}")
        self.status = status


def write_repos() -> set[str]:
    raw = os.getenv("KEYSTONE_WRITE_REPOS") or SANDBOX_REPO
    return {r.strip().lower() for r in raw.split(",") if r.strip()}


def plan_target(repo_slug: str, pr_number: int) -> dict:
    """Where an approved action for this PR lands; shown to the person approving it."""
    if repo_slug.lower() in write_repos():
        return {"mode": "direct", "target": f"{repo_slug} PR {pr_number}"}
    return {"mode": "shadow", "target": f"Tracking issue in {SANDBOX_REPO}"}


def _code(value) -> str:
    return "`" + str(value).replace("`", "'").replace("\n", " ") + "`"


def _call(method: str, path: str, **kwargs):
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set, so approved actions cannot be written to GitHub.")
    response = requests.request(
        method, f"{GITHUB_API}{path}", timeout=15,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
        **kwargs,
    )
    if response.status_code >= 300:
        try:
            message = response.json().get("message", "")
        except ValueError:
            message = response.text[:200]
        raise GitHubError(response.status_code, message)
    return response.json() if response.content else {}


def _tracking_title(repo_slug: str, pr_number: int) -> str:
    return f"Keystone review plan for {repo_slug} PR {pr_number}"


def _tracking_body(repo_slug: str, pr_number: int) -> str:
    return (
        f"Keystone records human-approved actions for {_code(repo_slug)} PR {_code(pr_number)} here.\n\n"
        f"Upstream pull request: {_code(f'https://github.com/{repo_slug}/pull/{pr_number}')}\n\n"
        f"**Shadow mode.** {_code(repo_slug)} is not in {_code('KEYSTONE_WRITE_REPOS')}, so review "
        "requests are recorded here instead of being sent upstream. Reviewer logins are written as "
        "code, so nobody is notified.\n\n"
        "Every action below was proposed from FalkorDB graph evidence and approved by a person."
    )


def _tracking_issue(repo_slug: str, pr_number: int, hint: int | None) -> dict:
    title = _tracking_title(repo_slug, pr_number)
    if hint:
        try:
            issue = _call("GET", f"/repos/{SANDBOX_REPO}/issues/{hint}")
            if issue.get("title") == title:
                return issue
        except GitHubError:
            pass
    # Listing is strongly consistent, unlike the search API, so a just-created issue is found.
    for page in range(1, 11):
        batch = _call("GET", f"/repos/{SANDBOX_REPO}/issues",
                      params={"state": "all", "per_page": 100, "page": page})
        for issue in batch:
            if issue.get("title") == title and "pull_request" not in issue:
                return issue
        if len(batch) < 100:
            break
    return _call("POST", f"/repos/{SANDBOX_REPO}/issues",
                 json={"title": title, "body": _tracking_body(repo_slug, pr_number)})


def _comment(action: dict, repo_slug: str) -> str:
    if action["kind"] == "request_review":
        lines = ["**Review request (shadow mode)**", "",
                 f"Keystone recommends {_code(action['who'])} to review "
                 f"{_code(repo_slug)} PR {_code(action['pr'])}."]
    else:
        lines = [f"**Label {_code(action['label'])} applied**"]
    if action.get("reason"):
        lines += ["", f"Why: {action['reason']}."]
    if action.get("evidence_path"):
        lines += ["", f"Graph evidence ({action.get('evidence')}, {action.get('hops')} hops): "
                  + " → ".join(_code(p) for p in action["evidence_path"])]
    lines += ["", f"Approved in Keystone. Action {_code(action['id'])}."]
    return "\n".join(lines)


def _shadow(action: dict, repo_slug: str, hint: int | None) -> dict:
    with _TRACKING_LOCK:
        issue = _tracking_issue(repo_slug, action["pr"], hint)
    number = issue["number"]
    if action["kind"] == "add_label":
        _call("POST", f"/repos/{SANDBOX_REPO}/issues/{number}/labels",
              json={"labels": [action["label"]]})
    comment = _call("POST", f"/repos/{SANDBOX_REPO}/issues/{number}/comments",
                    json={"body": _comment(action, repo_slug)})
    return {"target_repo": SANDBOX_REPO, "target_number": number,
            "url": comment.get("html_url") or issue.get("html_url")}


def _direct(action: dict, repo_slug: str) -> dict:
    number = action["pr"]
    if action["kind"] == "request_review":
        pr = _call("POST", f"/repos/{repo_slug}/pulls/{number}/requested_reviewers",
                   json={"reviewers": [action["who"]]})
        url = pr.get("html_url")
    else:
        _call("POST", f"/repos/{repo_slug}/issues/{number}/labels",
              json={"labels": [action["label"]]})
        url = f"https://github.com/{repo_slug}/pull/{number}"
    return {"target_repo": repo_slug, "target_number": number, "url": url}


def execute(action: dict, repo_slug: str, tracking_hint: int | None = None) -> dict:
    """Run one approved action from the ledger in the mode it was approved under."""
    if action.get("kind") not in KINDS:
        return {"ok": False, "error": f"Unknown action: {action.get('kind')}"}
    mode = action.get("mode") or plan_target(repo_slug, action["pr"])["mode"]
    try:
        if mode == "direct":
            if repo_slug.lower() not in write_repos():
                return {"ok": False, "mode": mode,
                        "error": f"{repo_slug} is no longer in KEYSTONE_WRITE_REPOS."}
            done = _direct(action, repo_slug)
        else:
            done = _shadow(action, repo_slug, tracking_hint)
        return {"ok": True, "mode": mode, **done}
    except (RuntimeError, requests.RequestException) as exc:
        return {"ok": False, "mode": mode, "error": str(exc)}
