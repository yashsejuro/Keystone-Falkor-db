"""Unit tests verifying demo artifacts, frontend placeholders, and generic example names."""
import re
from pathlib import Path


def test_demo_artifact_sanitized():
    """Verify demo_artifact.md does not contain hard-coded real usernames as recommended reviewers."""
    path = Path("demo_artifact.md")
    assert path.exists(), "demo_artifact.md must exist"
    content = path.read_text(encoding="utf-8")

    assert "davidhewitt" not in content, "Real username 'davidhewitt' must not appear in demo artifact"
    assert "example_reviewer" in content, "Generic example reviewer name should be used"
    assert "FalkorDB graph data" in content, "Notice explaining recommendations come from graph data must be present"


def test_frontend_placeholders_non_numeric():
    """Verify index.html initial metric placeholders are unobtrusive non-numeric strings or em-dashes."""
    path = Path("frontend/index.html")
    assert path.exists(), "frontend/index.html must exist"
    content = path.read_text(encoding="utf-8")

    for metric_id in ["cov-github-total", "cov-ingested", "cov-analysis-window", "cov-showing-count"]:
        match = re.search(rf'id="{metric_id}"[^>]*>(.*?)</div>', content)
        assert match is not None, f"Metric element {metric_id} not found"
        text = match.group(1).strip()
        assert text in ["—", "-", "Unavailable"], f"{metric_id} should have placeholder '—' or 'Unavailable', got '{text}'"

    sync_match = re.search(r'id="coverage-last-synced"[^>]*>(.*?)</strong>', content)
    assert sync_match is not None, "coverage-last-synced element not found"
    sync_text = sync_match.group(1).strip()
    assert sync_text in ["—", "-", "Unavailable"], f"coverage-last-synced should have placeholder '—', got '{sync_text}'"


def test_ingest_ui_batch_size_clarification():
    """Verify frontend explains 500 as batch size rather than full repository size."""
    path = Path("frontend/index.html")
    content = path.read_text(encoding="utf-8")

    assert "Batch size = number of PRs fetched per ingestion job page" in content
    assert "Batch size: 500 (default)" in content
