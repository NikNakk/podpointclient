"""Tests for runtime dependency metadata."""
from pathlib import Path


def test_direct_runtime_imports_are_declared():
    """Ensure clean installations include directly imported dependencies."""
    setup_contents = Path("setup.py").read_text(encoding="utf-8")

    assert '"aiohttp>=3"' in setup_contents
    assert '"async-timeout>=4"' in setup_contents
    assert '"StrEnum>=0.4,<0.5"' in setup_contents
    assert '"pytz"' in setup_contents
    assert '"pyt"' not in setup_contents
