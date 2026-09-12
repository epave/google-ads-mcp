"""Entry point for ``python -m google_ads_mcp`` and the console script."""

from __future__ import annotations

from .server import run


def main() -> None:
    run()


if __name__ == "__main__":
    main()
