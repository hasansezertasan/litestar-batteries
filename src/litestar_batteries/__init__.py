"""litestar-batteries: batteries-included utilities for Litestar."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("litestar-batteries")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = ["__version__"]
