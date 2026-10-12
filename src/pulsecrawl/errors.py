"""Compatibility import; implementation lives in :mod:`pulsecrawl.domain.errors`."""

import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("pulsecrawl.domain.errors")
