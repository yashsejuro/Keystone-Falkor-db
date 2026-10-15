"""Repository-scoped knowledge-risk inbox for Keystone."""
from html import escape
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
import uvicorn

from graph_client import get_graph, list_repos, DEFAULT_REPO
from tools import bus_factor_files, default_cutoff
from scoring import score_reviewers


router = APIRouter()


def build_inbox(repo: str) -> list[dict]:
    """Return recent merged PRs enriched with reviewer and knowledge-risk data."""
    g = get_graph(repo)
    pr_rows = g.query(
        """
        MATCH (pr:PullRequest)
        WHERE pr.merged_at IS NOT NULL
        RETURN pr.number, pr.title, pr.merged_at
        ORDER BY pr.merged_at DESC
        LIMIT 15
        """,
        {},
    ).result_set

    cutoff = default_cutoff()
    flagged_paths = {item["path"] for item in bus_factor_files(cutoff, repo=repo)}
    numbers = [row[0] for row in pr_rows]
    files_by_pr = {number: set() for number in numbers}

    if numbers:
        file_rows = g.query(
            """
            MATCH (pr:PullRequest)-[:TOUCHES]->(f:File)
            WHERE pr.number IN $numbers
            RETURN pr.number, f.path
            """,
            {"numbers": numbers},
        ).result_set
        for pr_number, file_path in file_rows:
            files_by_pr.setdefault(pr_number, set()).add(file_path)

    inbox = []
    for number, title, merged_at in pr_rows:
        reviewers = score_reviewers(number, cutoff, repo)
        top_reviewer = reviewers[0] if reviewers else None

        if files_by_pr.get(number, set()) & flagged_paths:
            risk = "HIGH"
        elif top_reviewer and top_reviewer["score"] < 0.5:
            risk = "MED"
        else:
            risk = "LOW"

        inbox.append(
            {
                "number": number,
                "title": title,
                "merged_at": merged_at,
                "risk": risk,
                "reviewer": top_reviewer["login"] if top_reviewer else "—",
                "score": top_reviewer["score"] if top_reviewer else None,
            }
        )

    risk_order = {"HIGH": 0, "MED": 1, "LOW": 2}
    inbox.sort(key=lambda item: item["merged_at"], reverse=True)
    inbox.sort(key=lambda item: risk_order[item["risk"]])
    return inbox


def _render_inbox(repo: str, repos: list[str], items: list[dict]) -> str:
    risk_colors = {"HIGH": "#ef4444", "MED": "#f59e0b", "LOW": "#10b981"}
    options = "".join(
        f'<option value="{escape(name)}"{" selected" if name == repo else ""}>'
        f"{escape(name)}</option>"
        for name in repos
    )
    rows = []
    for item in items:
        target = f"/?pr={item['number']}&amp;repo={quote(repo, safe='')}"
        reviewer = item["reviewer"]
        if item["score"] is not None:
            reviewer = f"{reviewer} ({item['score']:.2f})"
        rows.append(
            "<tr>"
            f'<td><a href="{target}">#{item["number"]}</a></td>'
            f'<td><a href="{target}">{escape(str(item["title"] or ""))}</a></td>'
            f'<td><a href="{target}" style="color: {risk_colors[item["risk"]]}; font-weight: 700;">'
            f'{item["risk"]}</a></td>'
            f'<td><a href="{target}">{escape(reviewer)}</a></td>'
            f'<td><a href="{target}">{escape(str(item["merged_at"]))}</a></td>'
            "</tr>"
        )

    graph_name = f"keystone_{repo}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Keystone PR inbox</title>
  <style>
    body {{ margin: 0; background: #111827; color: #e5e7eb; font-family: Arial, sans-serif; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 36px 24px; }}
    h1 {{ margin: 0 0 24px; font-size: 24px; }}
    select {{ margin-bottom: 20px; padding: 8px 10px; background: #1f2937; color: #e5e7eb; border: 1px solid #374151; border-radius: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: #1f2937; }}
    th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #374151; }}
    th {{ color: #9ca3af; font-size: 12px; text-transform: uppercase; }}
    tr:hover {{ background: #273449; }}
    a {{ color: inherit; text-decoration: none; display: block; }}
    footer {{ margin-top: 20px; color: #9ca3af; font-size: 13px; }}
  </style>
</head>
<body>
  <main>
    <h1>Keystone — {escape(repo)} PR inbox</h1>
    <select onchange="location.href='/inbox?repo='+this.value" aria-label="Repository">
      {options}
    </select>
    <table>
      <thead><tr><th>PR</th><th>Title</th><th>Risk</th><th>Top Reviewer</th><th>Last Merged</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <footer>Ranked by knowledge risk. Data: FalkorDB graph {escape(graph_name)}.</footer>
  </main>
</body>
</html>"""


@router.get("/inbox", response_class=HTMLResponse)
def inbox(repo: str | None = None) -> HTMLResponse:
    repos = list_repos()
    selected_repo = repo if repo in repos else repos[0]
    return HTMLResponse(_render_inbox(selected_repo, repos, build_inbox(selected_repo)))


if __name__ == "__main__":
    uvicorn.run(router, host="127.0.0.1", port=8000)
