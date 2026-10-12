"""Compatibility script; use python -m examples.local_cases from the package root."""

from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.shared.catalog import CASES, Case
from examples.shared.local import (
    provision_local_case,
    SYSTEM_FIELDS,
    _field_id,
    _system_fallbacks,
)
from examples.shared.cli import main_local as main_case

if __name__ == "__main__":
    main_case()
