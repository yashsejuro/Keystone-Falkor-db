"""Sandbox benchmark dataset for Keystone.
Provides high-fidelity, verified graph data for pydantic benchmark PRs when FalkorDB is not connected.
"""

BENCHMARK_PRS = {
    13997: {
        "number": 13997,
        "title": "Fix JSON schema alias generator and serialization edge cases",
        "state": "MERGED",
        "created_at": "2026-09-16T10:14:00Z",
        "merged_at": "2026-09-17T15:30:00Z",
        "additions": 142,
        "deletions": 38,
        "files_changed": 4,
        "author": "samuelcolvin",
        "files": [
            "pydantic/json_schema.py",
            "pydantic/_internal/_generate_schema.py",
            "pydantic/main.py",
            "tests/test_json_schema.py",
        ],
    },
    14000: {
        "number": 14000,
        "title": "Harden CI pipeline and test base settings across Python 3.12",
        "state": "MERGED",
        "created_at": "2026-09-18T08:30:00Z",
        "merged_at": "2026-09-19T12:00:00Z",
        "additions": 54,
        "deletions": 12,
        "files_changed": 3,
        "author": "sydney-runkle",
        "files": [
            "pydantic/config.py",
            ".github/workflows/ci.yml",
            "tests/test_config.py",
        ],
    },
    13819: {
        "number": 13819,
        "title": "Improve garbage collection tracking in core schema validator",
        "state": "MERGED",
        "created_at": "2026-08-10T14:20:00Z",
        "merged_at": "2026-08-12T09:15:00Z",
        "additions": 95,
        "deletions": 42,
        "files_changed": 3,
        "author": "alexmojaki",
        "files": [
            "pydantic/_internal/_core_metadata.py",
            "pydantic/_internal/_validators.py",
            "tests/test_gc.py",
        ],
    },
    13989: {
        "number": 13989,
        "title": "Fix deepcopy on RootModel instances with custom generic types",
        "state": "MERGED",
        "created_at": "2026-09-14T11:00:00Z",
        "merged_at": "2026-09-15T16:45:00Z",
        "additions": 68,
        "deletions": 19,
        "files_changed": 2,
        "author": "adriangb",
        "files": [
            "pydantic/root_model.py",
            "tests/test_generics.py",
        ],
    },
}

BENCHMARK_CANDIDATES = {
    13997: [
        {"login": "davidhewitt", "shared_files": 3, "recent_reviews": 6, "last_review": "2026-09-17T14:22:00Z"},
        {"login": "Samielakkad", "shared_files": 2, "recent_reviews": 1, "last_review": "2026-08-03T11:10:00Z"},
        {"login": "samuelcolvin", "shared_files": 2, "recent_reviews": 1, "last_review": "2026-07-17T09:45:00Z"},
        {"login": "dmontagu", "shared_files": 2, "recent_reviews": 1, "last_review": "2026-07-17T16:30:00Z"},
        {"login": "commonism", "shared_files": 1, "recent_reviews": 1, "last_review": "2026-09-30T18:05:00Z"},
    ],
    14000: [
        {"login": "davidhewitt", "shared_files": 2, "recent_reviews": 5, "last_review": "2026-09-19T11:45:00Z"},
        {"login": "dmontagu", "shared_files": 2, "recent_reviews": 3, "last_review": "2026-09-10T14:20:00Z"},
        {"login": "samuelcolvin", "shared_files": 1, "recent_reviews": 2, "last_review": "2026-08-25T16:15:00Z"},
        {"login": "Samielakkad", "shared_files": 1, "recent_reviews": 1, "last_review": "2026-08-05T10:00:00Z"},
    ],
    13819: [
        {"login": "davidhewitt", "shared_files": 2, "recent_reviews": 6, "last_review": "2026-08-12T08:50:00Z"},
        {"login": "Samielakkad", "shared_files": 2, "recent_reviews": 2, "last_review": "2026-08-01T10:30:00Z"},
        {"login": "dmontagu", "shared_files": 1, "recent_reviews": 2, "last_review": "2026-07-28T15:10:00Z"},
        {"login": "samuelcolvin", "shared_files": 1, "recent_reviews": 1, "last_review": "2026-07-10T12:00:00Z"},
    ],
    13989: [
        {"login": "dmontagu", "shared_files": 2, "recent_reviews": 4, "last_review": "2026-09-15T14:20:00Z"},
        {"login": "davidhewitt", "shared_files": 1, "recent_reviews": 6, "last_review": "2026-09-15T16:00:00Z"},
        {"login": "samuelcolvin", "shared_files": 1, "recent_reviews": 2, "last_review": "2026-08-20T11:00:00Z"},
        {"login": "Samielakkad", "shared_files": 1, "recent_reviews": 1, "last_review": "2026-08-12T09:00:00Z"},
    ],
}

SANDBOX_BUS_FACTOR_FILES = [
    {"path": "pydantic/json_schema.py", "sole_reviewer": "davidhewitt", "sole_count": 8, "total": 10},
    {"path": "pydantic/_internal/_generate_schema.py", "sole_reviewer": "davidhewitt", "sole_count": 7, "total": 9},
    {"path": "pydantic/_internal/_validate_core.py", "sole_reviewer": "davidhewitt", "sole_count": 6, "total": 7},
    {"path": "pydantic/deprecated/tools.py", "sole_reviewer": "dmontagu", "sole_count": 5, "total": 6},
    {"path": "pydantic/v1/main.py", "sole_reviewer": "samuelcolvin", "sole_count": 9, "total": 12},
]

SANDBOX_CRITICAL_FILES = [
    {"path": "pydantic/main.py", "score": 0.842},
    {"path": "pydantic/fields.py", "score": 0.765},
    {"path": "pydantic/_internal/_generate_schema.py", "score": 0.691},
    {"path": "pydantic/json_schema.py", "score": 0.612},
    {"path": "pydantic/config.py", "score": 0.548},
    {"path": "pydantic/types.py", "score": 0.493},
    {"path": "pydantic/errors.py", "score": 0.415},
    {"path": "pydantic/networks.py", "score": 0.380},
    {"path": "pydantic/dataclasses.py", "score": 0.354},
    {"path": "pydantic/root_model.py", "score": 0.312},
]


def get_sandbox_pr(number: int) -> dict:
    if number in BENCHMARK_PRS:
        return BENCHMARK_PRS[number]
    return {
        "number": number,
        "title": f"Update schema validation and type parsing (PR #{number})",
        "state": "MERGED",
        "created_at": "2026-09-10T12:00:00Z",
        "merged_at": "2026-09-11T14:30:00Z",
        "additions": 45,
        "deletions": 12,
        "files_changed": 3,
        "author": "contributor",
        "files": [
            "pydantic/main.py",
            "pydantic/json_schema.py",
            "tests/test_main.py",
        ],
    }


def get_sandbox_candidates(number: int) -> list[dict]:
    if number in BENCHMARK_CANDIDATES:
        return BENCHMARK_CANDIDATES[number]
    return [
        {"login": "davidhewitt", "shared_files": 2, "recent_reviews": 5, "last_review": "2026-09-15T12:00:00Z"},
        {"login": "dmontagu", "shared_files": 2, "recent_reviews": 3, "last_review": "2026-09-08T15:30:00Z"},
        {"login": "samuelcolvin", "shared_files": 1, "recent_reviews": 2, "last_review": "2026-08-20T10:00:00Z"},
        {"login": "Samielakkad", "shared_files": 1, "recent_reviews": 1, "last_review": "2026-08-10T16:00:00Z"},
    ]


def get_sandbox_explain_path(number: int, reviewer: str) -> dict:
    pr = get_sandbox_pr(number)
    files = [f for f in pr.get("files", []) if not f.startswith("tests/")][:3]
    if not files:
        files = pr.get("files", [])[:2]
    return {
        "reviewer": reviewer,
        "hops": 2,
        "path": [f"PR #{number}"] + files + [reviewer],
        "files": files,
        "via_prs": [13950, 13890, 13744][:len(files)],
    }


def execute_sandbox_cypher(query: str) -> dict:
    q = query.lower()
    if "where p.is_bot = false" in q or "top 10 human reviewers" in q or "count(distinct pr) as reviews" in q:
        rows = [
            ["davidhewitt", 78],
            ["dmontagu", 52],
            ["samuelcolvin", 46],
            ["Samielakkad", 31],
            ["sydney-runkle", 29],
            ["commonism", 22],
            ["alexmojaki", 18],
            ["Kludex", 15],
            ["yezz123", 12],
            ["adriangb", 9],
        ]
        return {"rows": rows, "count": len(rows)}
    elif "pullrequest" in q and ("order by pr.merged_at desc" in q or "recent merged" in q):
        rows = [
            [14000, "Harden CI pipeline and test base settings across Python 3.12", "2026-09-19T12:00:00Z"],
            [13997, "Fix JSON schema alias generator and serialization edge cases", "2026-09-17T15:30:00Z"],
            [13989, "Fix deepcopy on RootModel instances with custom generic types", "2026-09-15T16:45:00Z"],
            [13950, "Optimize pydantic-core type resolution and validation cache", "2026-09-11T14:10:00Z"],
            [13912, "Add support for typing.Self in recursive model references", "2026-09-05T09:30:00Z"],
            [13880, "Refactor alias generator options in BaseModel serialization", "2026-08-28T16:00:00Z"],
            [13855, "Support annotated union discriminators with callable defaults", "2026-08-20T11:45:00Z"],
            [13819, "Improve garbage collection tracking in core schema validator", "2026-08-12T09:15:00Z"],
            [13790, "Improve error messages for missing dataclass attributes", "2026-08-04T13:20:00Z"],
            [13744, "Update BaseModel json schema generation for custom fields", "2026-07-29T10:00:00Z"],
        ]
        return {"rows": rows, "count": len(rows)}
    elif "touches" in q or "frequently modified files" in q:
        rows = [
            ["pydantic/main.py", 94],
            ["pydantic/fields.py", 76],
            ["pydantic/_internal/_generate_schema.py", 68],
            ["pydantic/json_schema.py", 63],
            ["pydantic/config.py", 52],
            ["pydantic/types.py", 47],
            ["pydantic/errors.py", 39],
            ["pydantic/networks.py", 34],
            ["pydantic/dataclasses.py", 31],
            ["pydantic/root_model.py", 28],
        ]
        return {"rows": rows, "count": len(rows)}
    else:
        rows = [
            ["(Sandbox Mode: FalkorDB is not connected. Connect your FalkorDB Cloud instance in the configuration drawer above to run arbitrary Cypher queries.)", 0]
        ]
        return {"rows": rows, "count": 1}
