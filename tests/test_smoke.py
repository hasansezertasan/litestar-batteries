"""Smoke tests for the litestar_batteries package."""

import litestar_batteries


def test_package_importable() -> None:
    """The top-level package imports without side effects."""
    assert litestar_batteries is not None


def test_version_is_nonempty_string() -> None:
    """The exposed version is a non-empty string (tag-derived or fallback)."""
    assert isinstance(litestar_batteries.__version__, str)
    assert litestar_batteries.__version__
