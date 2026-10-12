"""Local runner for news/stocks; provisioning is shared across all cases."""

from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from examples.shared.cli import main_local as main_case

if __name__ == "__main__":
    main_case("news/stocks")
