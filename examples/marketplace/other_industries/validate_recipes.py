"""Validate saved samples by default; live sampling requires explicit opt-in.

Use --list for source slugs, --saved-dir PATH for offline HTML,
or --live --user-agent CONTACT after reviewing access policy.
"""

from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from examples.shared.validation import main as validate_case


def main(argv=None):
    return validate_case("marketplace/other_industries", argv)


if __name__ == "__main__":
    raise SystemExit(main())
