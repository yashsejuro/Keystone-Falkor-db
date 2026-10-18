# Keystone FastMCP Tool Example (Sample Interaction)

> [!NOTE]
> This artifact demonstrates an example MCP query and response when Keystone is connected as an MCP tool provider to Claude Desktop or Cursor.

### Query
`Use keystone:rank_reviewers to recommend reviewers for PR 13997 on repository pydantic/pydantic`

### Tool Call
`keystone:rank_reviewers(pr_number=13997, repo="pydantic")`

### Response
Candidate ranking computed deterministically via 4-component graph scoring:

| Rank | Candidate Reviewer | Composite Score | Shared Files | Recent Reviews | Last Review Date |
|:----:|:-------------------|:---------------:|:------------:|:--------------:|:-----------------|
| 1 | `davidhewitt` | 0.88 | 4 | 3 | 2026-08-27 |
| 2 | `Samielakkad` | 0.03 | 0 | 0 | None (Co-change) |

### Evidence & Rationale
`davidhewitt` shares direct review history on the changed files and has recent review activity in this part of the repository.

### Action Proposal
- **Proposed Action:** `request_review` on PR #13997 for `@davidhewitt`
- **Dispatch Gate:** Requires human approval (Dry-run, Shadow, or Live GitHub mode).