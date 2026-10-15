# MCP demo output (Claude Desktop)

Query: "Use keystone to tell me who should review PR 13997"

Response:
davidhewitt is the best reviewer for PR 13997, and by a wide margin.

Rank	Reviewer	Score	Shared files	Recent reviews	Last review
1	davidhewitt	0.93	3	6	Sep 17, 2026
2	Samielakkad	0.53	2	1	Aug 3, 2026
3	samuelcolvin	0.51	2	1	Jul 17, 2026
4	dmontagu	0.51	2	1	Jul 17, 2026
5	commonism	0.46	1	1	Sep 30, 2026

davidhewitt has reviewed all three of the PR’s overlapping files and has six recent reviews, so he’s the clear first choice.

For a second reviewer, Samielakkad is the top-scoring alternative. commonism reviewed most recently (Sep 30), so he may be more available or have fresher context. samuelcolvin and dmontagu score almost identically and both last reviewed on Jul 17.

I can also trace how any of these reviewers connects to the PR’s files if you want to see why they were ranked.

Screenshot: mcp_demo.png (save separately)