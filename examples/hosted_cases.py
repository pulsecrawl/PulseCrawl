"""Compatibility script; use python -m examples.hosted_cases from the package root."""

from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.shared.catalog import CASES, Case, RESPONSIBLE_POLITENESS
from examples.shared.recipes import normalize as _normalise
from examples.shared.hosted import provision_case, _field_ids, _scope_matches, _by_name
from examples.shared.cli import main_hosted as main_case

if __name__ == "__main__":
    main_case()
