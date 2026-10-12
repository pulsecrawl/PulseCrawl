#!/usr/bin/env python3
"""Fail when a tracked text file resembles a committed credential.

Only rule, path, and line are reported; matching values are never printed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

RULES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "pulsecrawl-live-key": re.compile(r"\bpk_live_[A-Za-z0-9]{32,}\b"),
    "github-token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{32,}\b"),
    "azure-account-key": re.compile(r"\bAccountKey=[A-Za-z0-9+/]{32,}={0,2}\b"),
    "google-service-account-key": re.compile(r'"private_key"\s*:\s*"-----BEGIN'),
}


def tracked_files() -> list[Path]:
    # Include non-ignored untracked files so a pre-commit run protects changes
    # before they enter the index; CI naturally sees the committed set.
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    )
    return [Path(item.decode()) for item in output.split(b"\0") if item]


def main() -> int:
    files = tracked_files()
    findings: list[tuple[str, Path, int]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for rule, pattern in RULES.items():
                if pattern.search(line):
                    findings.append((rule, path, line_number))
    if findings:
        print("Potential tracked credentials found (values redacted):")
        for rule, path, line in findings:
            print(f"- {rule}: {path}:{line}")
        return 1
    print(f"Secret-pattern scan passed ({len(files)} tracked files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
