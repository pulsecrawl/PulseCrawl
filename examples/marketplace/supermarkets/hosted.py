"""Hosted runner for marketplace/supermarkets; provisioning is shared across all cases."""

from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from examples.shared.cli import main_hosted as main_case

if __name__ == "__main__":
    main_case("marketplace/supermarkets")
