#!/usr/bin/env python3
"""Verify that relative Markdown links stay inside and resolve within a tree."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote

MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("#", "http://", "https://", "mailto:")
EXCLUDED_DIRECTORIES = {
    ".git",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    # These files are remapped to the export root and checked there.
    "oss",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    findings: list[str] = []
    markdown_files = (
        path
        for path in root.rglob("*.md")
        if not any(part in EXCLUDED_DIRECTORIES for part in path.relative_to(root).parts)
    )
    for markdown in sorted(markdown_files):
        try:
            text = markdown.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(f"{markdown.relative_to(root)}: unreadable ({exc})")
            continue
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>")
            if not target or target.startswith(EXTERNAL_PREFIXES):
                continue
            target = unquote(target.split("#", 1)[0])
            candidate = (markdown.parent / target).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                findings.append(
                    f"{markdown.relative_to(root)}: link leaves tree: {target}"
                )
                continue
            if not candidate.exists():
                findings.append(
                    f"{markdown.relative_to(root)}: missing target: {target}"
                )
    if findings:
        print("Broken relative Markdown links:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(f"Markdown link check passed under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
