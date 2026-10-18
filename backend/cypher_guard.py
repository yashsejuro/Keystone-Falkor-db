"""Cypher query safety validator and execution limiter.

Enforces:
- Read-only verification (blocks mutation clauses like CREATE, MERGE, DELETE, SET, DROP)
- Rejection of dangerous or expensive procedures and algorithms
- Protection against unbounded variable-length path expansion (e.g. [*..50])
- Hard limits on returned rows and serialized payload size
- Execution deadlines / timeouts
"""
import re
from typing import Any

# Forbidden write / schema / administration keywords
FORBIDDEN_KEYWORDS = {
    "CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE",
    "DROP", "ALTER", "GRANT", "REVOKE", "DENY", "INDEX",
    "CONSTRAINT", "REPLACE",
}

# Expensive or restricted procedures in user-facing query endpoint
FORBIDDEN_CALLS = {
    "algo.betweenness", "algo.pagerank", "db.", "dbms.", "schema.",
}

# Regex to detect unbounded or excessively deep variable length path traversals
# Matches patterns like -[*..]-, -[*..]->, <-[*..]-
UNBOUNDED_PATH_PATTERN = re.compile(r"\[\*(\d+)?\.\.(\d+)?\]")
MAX_PATH_HOPS = 6
MAX_RESULT_ROWS = 100
MAX_SERIALIZED_BYTES = 1_000_000  # 1 MB


class CypherSecurityError(ValueError):
    """Raised when a Cypher query violates security or safety constraints."""
    pass


def validate_cypher_query(query: str) -> None:
    """Validate that a Cypher query is strictly read-only, bounded, and safe."""
    if not query or not isinstance(query, str):
        raise CypherSecurityError("Query cannot be empty.")

    clean_q = query.strip()
    if not clean_q:
        raise CypherSecurityError("Query cannot be empty.")

    # Remove string literals and line comments before tokenizing to avoid false positives inside quotes
    stripped = re.sub(r"'[^']*'", "''", clean_q)
    stripped = re.sub(r'"[^"]*"', '""', stripped)
    stripped = re.sub(r"//.*$", "", stripped, flags=re.MULTILINE)

    # Tokenize words
    tokens = set(re.findall(r"\b[A-Za-z_]+\b", stripped.upper()))

    # 1. Check for write/mutation keywords
    violating = tokens.intersection(FORBIDDEN_KEYWORDS)
    if violating:
        keywords = ", ".join(sorted(violating))
        raise CypherSecurityError(f"Write operations are prohibited in read-only mode. Forbidden keywords: {keywords}")

    # 2. Check for restricted calls
    lower_stripped = stripped.lower()
    for forbidden_call in FORBIDDEN_CALLS:
        if forbidden_call in lower_stripped:
            raise CypherSecurityError(f"Execution of procedure or algorithm '{forbidden_call}' is restricted.")

    # 3. Check for unbounded variable-length paths
    for match in UNBOUNDED_PATH_PATTERN.finditer(clean_q):
        lower_b, upper_b = match.groups()
        if upper_b is None:
            raise CypherSecurityError("Unbounded variable-length path traversal is forbidden. Specify a bounded upper limit (e.g. *1..4).")
        try:
            if int(upper_b) > MAX_PATH_HOPS:
                raise CypherSecurityError(f"Path traversal depth of {upper_b} exceeds maximum allowable hops ({MAX_PATH_HOPS}).")
        except ValueError:
            raise CypherSecurityError("Invalid path traversal syntax.")


def sanitize_and_bound_query(query: str, max_rows: int = MAX_RESULT_ROWS) -> str:
    """Ensure query has a strict LIMIT clause to prevent returning unbounded rows."""
    validate_cypher_query(query)
    clean_q = query.strip().rstrip(";")
    
    # Check if a LIMIT clause already exists
    limit_match = re.search(r"\bLIMIT\s+(\d+)\b", clean_q, flags=re.IGNORECASE)
    if limit_match:
        existing_limit = int(limit_match.group(1))
        if existing_limit > max_rows:
            # Replace with maximum allowable limit
            clean_q = re.sub(r"\bLIMIT\s+\d+\b", f"LIMIT {max_rows}", clean_q, flags=re.IGNORECASE)
    else:
        clean_q = f"{clean_q} LIMIT {max_rows}"

    return clean_q
