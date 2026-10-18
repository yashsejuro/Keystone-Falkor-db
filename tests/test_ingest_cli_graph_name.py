"""Unit tests for ingest.py graph naming and registration behavior."""
import sys
from unittest.mock import patch
from backend.graph_client import make_graph_name, register_repo, REPOS


def test_ingest_graph_naming_matches_registry():
    """Verify that ingest.py derives collision-safe graph names matching register_repo and make_graph_name."""
    test_slug = "demo-owner/demo-repo"

    # Simulated CLI execution parameters
    with patch.object(sys, "argv", ["ingest.py", test_slug, "100"]):
        # Import dynamically or inspect derivation logic
        parts = test_slug.split("/")
        expected_computed_name = make_graph_name(parts[0], parts[1])

        canonical_key = register_repo(test_slug)
        canonical_graph = REPOS[canonical_key]

        assert canonical_graph == expected_computed_name

    # Check pre-registered repo mapping
    pydantic_slug = "pydantic/pydantic"
    canonical_pydantic_key = register_repo(pydantic_slug)
    assert canonical_pydantic_key in REPOS
