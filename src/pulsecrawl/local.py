"""Compatibility import; implementation lives in :mod:`pulsecrawl.adapters.inbound.python.local`."""

import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module(
    "pulsecrawl.adapters.inbound.python.local"
)
