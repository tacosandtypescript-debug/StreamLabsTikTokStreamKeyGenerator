"""Application version with a source-checkout fallback.

Release builds may generate ``_version.py`` in CI.  A normal source checkout
must still be runnable, so the generated module is optional.
"""

try:
    from _version import __version__ as __version__
except ModuleNotFoundError:
    __version__ = "0.0.0-dev"
