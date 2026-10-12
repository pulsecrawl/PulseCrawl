"""Credential-free cloud connection metadata."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CloudProfile:
    name: str
    base_url: str
    org_id: str
    key_id: str
