"""Thin shim — delegates to scripts.discover.main().

This file is superseded by the multi-source orchestrator in scripts/discover.py
and will be removed in the next task."""
from __future__ import annotations

from scripts.discover import main

if __name__ == "__main__":
    main()
