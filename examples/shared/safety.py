"""Validate operator identification without claiming to verify authorization."""

import re


def operator_user_agent(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 4096
        or "\r" in value
        or "\n" in value
        or not re.search(r"(?:https://|mailto:)[^\s)]+", value)
    ):
        raise ValueError(
            "provide a user agent with an operator https:// contact URL or mailto: address"
        )
    return value.strip()
