"""Compatibility import for the standard local authoring composition."""

import sys
from pulsecrawl.bootstrap import authoring as _implementation

sys.modules[__name__] = _implementation
