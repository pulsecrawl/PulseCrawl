from __future__ import annotations


class _Resource:
    def __init__(self, client) -> None:
        self._c = client
