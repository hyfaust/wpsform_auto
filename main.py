#!/usr/bin/env python
"""Script-style entry point for running the CLI without `-m`."""

from wpsform.cli import main

if __name__ == "__main__":
    raise SystemExit(main())