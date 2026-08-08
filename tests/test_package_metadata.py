"""Tests for runtime dependency metadata."""
from pathlib import Path


def test_direct_runtime_imports_are_declared():
    """Ensure clean installations include directly imported dependencies."""
    project_contents = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '"aiohttp>=3"' in project_contents
    assert '"tzdata"' in project_contents
    assert "async-timeout" not in project_contents
    assert "StrEnum" not in project_contents
    assert "pytz" not in project_contents
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


def test_python_floor_and_legacy_setup_shim_removal():
    """Require Python 3.12 without retaining legacy build entry points."""
    project_contents = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.12"' in project_contents
    assert '"Programming Language :: Python :: 3.12"' in project_contents
    assert not Path("setup.py").exists()
