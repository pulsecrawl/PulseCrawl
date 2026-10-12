"""Compatibility import; implementation lives in :mod:`pulsecrawl.adapters.inbound.cli.main`."""

import importlib as _importlib
import sys as _sys

_implementation = _importlib.import_module("pulsecrawl.adapters.inbound.cli.main")
if __name__ == "__main__":
    raise SystemExit(_implementation.main())
_sys.modules[__name__] = _implementation
