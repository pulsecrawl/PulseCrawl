"""Compatibility entry point for the shared Chihuahua news hosted runner."""

from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.shared.cli import main_hosted


def main():
    main_hosted("news/chihuahua")


if __name__ == "__main__":
    main()
