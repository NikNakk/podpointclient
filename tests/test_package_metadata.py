"""Tests for runtime dependency metadata."""
from pathlib import Path


def test_direct_runtime_imports_are_declared():
    """Ensure clean installations include directly imported dependencies."""
    project_contents = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '"aiohttp>=3"' in project_contents
    assert "async-timeout>=4" in project_contents
    assert "python_version < '3.11'" in project_contents
    assert '"StrEnum>=0.4,<0.5"' in project_contents
    assert '"pytz"' in project_contents
    assert '"pyt"' not in project_contents


def test_fork_distribution_metadata_preserves_attribution():
    """Ensure the fork has a distinct distribution and honest attribution."""
    project_contents = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "podpointclient-niknakk"' in project_contents
    assert 'name = "Matthew Rayner"' in project_contents
    assert 'name = "Nick Kennedy"' in project_contents
    assert 'Homepage = "https://github.com/NikNakk/podpointclient"' in project_contents
    assert 'license = "MIT"' in project_contents
    assert "License :: OSI Approved :: MIT License" not in project_contents
    assert 'include = ["podpointclient*"]' in project_contents


def test_setup_py_is_only_a_compatibility_shim():
    """Keep a legacy entry point without duplicating project metadata."""
    setup_contents = Path("setup.py").read_text(encoding="utf-8")

    assert "setup()" in setup_contents
    assert "podpointclient-niknakk" not in setup_contents
