"""Unit tests for repository slug validation, collision-safe graph names, and Cypher security."""
import pytest
from backend.graph_client import validate_repo, register_repo, make_graph_name, REPOS
from backend.cypher_guard import validate_cypher_query, sanitize_and_bound_query, CypherSecurityError


def test_valid_repo_slugs():
    assert validate_repo("pydantic") == "pydantic"
    assert validate_repo("pydantic/pydantic") == "pydantic"
    assert validate_repo("FASTAPI") == "fastapi"


def test_invalid_repo_slugs():
    with pytest.raises(ValueError, match="not found"):
        validate_repo("nonexistent/repo_12345")
    with pytest.raises(ValueError, match="non-empty"):
        validate_repo("")
    with pytest.raises(ValueError):
        validate_repo(None)


def test_register_repo_slug_validation():
    with pytest.raises(ValueError, match="Invalid repository slug"):
        register_repo("invalid_format_without_slash")

    with pytest.raises(ValueError, match="Invalid repository slug"):
        register_repo("spaces in/repo")

    # Valid registration
    key = register_repo("test-owner/test-repo")
    assert key == "test-owner/test-repo"
    assert key in REPOS


def test_collision_safe_graph_naming():
    # Repositories with conflicting punctuation characters should produce distinct collision-safe graph names
    g1 = make_graph_name("foo-bar", "baz")
    g2 = make_graph_name("foo_bar", "baz")
    g3 = make_graph_name("foobar", "baz")
    g4 = make_graph_name("foo.bar", "baz")

    names = {g1, g2, g3, g4}
    assert len(names) == 4, f"Graph names collided: {names}"
    for name in names:
        assert name.startswith("keystone_")


def test_cypher_read_only_enforcement():
    # Allowed read-only queries
    validate_cypher_query("MATCH (n:Person) RETURN n.login LIMIT 10")
    validate_cypher_query("MATCH (pr:PullRequest)-[:TOUCHES]->(f:File) RETURN pr.number, count(f)")

    # Prohibited write / mutation operations
    with pytest.raises(CypherSecurityError, match="Write operations are prohibited"):
        validate_cypher_query("CREATE (p:Person {login: 'attacker'})")

    with pytest.raises(CypherSecurityError, match="Write operations are prohibited"):
        validate_cypher_query("MATCH (n) DETACH DELETE n")

    with pytest.raises(CypherSecurityError, match="Write operations are prohibited"):
        validate_cypher_query("MATCH (p:Person) SET p.admin = true")

    with pytest.raises(CypherSecurityError, match="Write operations are prohibited"):
        validate_cypher_query("MERGE (p:Person {login: 'test'})")

    with pytest.raises(CypherSecurityError, match="Write operations are prohibited"):
        validate_cypher_query("DROP INDEX ON :Person(login)")


def test_cypher_algorithm_and_unbounded_path_restriction():
    with pytest.raises(CypherSecurityError, match="restricted"):
        validate_cypher_query("CALL algo.betweenness({nodeLabels: ['File']})")

    with pytest.raises(CypherSecurityError, match="restricted"):
        validate_cypher_query("CALL db.labels()")

    with pytest.raises(CypherSecurityError, match="Unbounded variable-length path"):
        validate_cypher_query("MATCH (a)-[*..]->(b) RETURN b")

    with pytest.raises(CypherSecurityError, match="exceeds maximum allowable hops"):
        validate_cypher_query("MATCH (a)-[*1..20]->(b) RETURN b")


def test_cypher_query_bounding_limit():
    bounded = sanitize_and_bound_query("MATCH (n) RETURN n")
    assert "LIMIT 100" in bounded

    # Existing lower limit preserved
    bounded_small = sanitize_and_bound_query("MATCH (n) RETURN n LIMIT 10")
    assert "LIMIT 10" in bounded_small

    # Excessive limit clamped to maximum
    bounded_excessive = sanitize_and_bound_query("MATCH (n) RETURN n LIMIT 5000")
    assert "LIMIT 100" in bounded_excessive
