"""Profile lifecycle with separately injected metadata, credentials and HTTP."""

from __future__ import annotations
from pulsecrawl.domain.synchronization.profiles import CloudProfile
from pulsecrawl.application.ports.cloud import ProfileRepository, CredentialStore

PROFILE_SERVICE = "pulsecrawl-cloud"
API_KEY_ENV = "PULSECRAWL_API_KEY"


class ProfileService:
    def __init__(
        self,
        *,
        store: ProfileRepository,
        credentials: CredentialStore,
        client_factory,
        environment_secret,
    ):
        self._store, self._credentials = store, credentials
        self._client_factory, self._environment_secret = (
            client_factory,
            environment_secret,
        )

    def _read(self):
        return self._store.read()

    def list(self) -> list[CloudProfile]:
        value = self._read()
        return [
            CloudProfile(name=name, **profile)
            for name, profile in sorted(value["profiles"].items())
        ]

    def connect(
        self,
        name: str,
        *,
        base_url: str,
        api_key: str,
        store_secret: bool = True,
    ) -> CloudProfile:
        if not name or any(character in name for character in "/\\\0"):
            raise ValueError("profile name must be non-empty and filesystem-safe")
        with self._client_factory(api_key=api_key, base_url=base_url) as client:
            identity = client.whoami()
        if identity.get("kind") != "apiKey":
            raise ValueError("cloud profiles require an API-key identity")
        profile = CloudProfile(
            name=name,
            base_url=base_url.rstrip("/"),
            org_id=str(identity["orgId"]),
            key_id=str(identity["keyId"]),
        )
        keyring = self._credentials if store_secret else None
        previous_secret = (
            keyring.get_password(PROFILE_SERVICE, name) if keyring else None
        )
        if keyring:
            keyring.set_password(PROFILE_SERVICE, name, api_key)
        try:
            value = self._read()
            value["profiles"][name] = {
                "base_url": profile.base_url,
                "org_id": profile.org_id,
                "key_id": profile.key_id,
            }
            self._store.write(value)
        except Exception:
            if keyring:
                try:
                    if previous_secret is None:
                        keyring.delete_password(PROFILE_SERVICE, name)
                    else:
                        keyring.set_password(PROFILE_SERVICE, name, previous_secret)
                except Exception:
                    pass
            raise
        return profile

    def get(self, name: str) -> CloudProfile:
        value = self._read()["profiles"].get(name)
        if value is None:
            raise KeyError(f"unknown cloud profile: {name}")
        return CloudProfile(name=name, **value)

    def client(self, name: str):
        profile = self.get(name)
        secret = self._environment_secret()
        if not secret:
            secret = self._credentials.get_password(PROFILE_SERVICE, name)
        if not secret:
            raise ValueError(
                f"profile {name!r} has no credential; reconnect it or set {API_KEY_ENV}"
            )
        return self._client_factory(api_key=secret, base_url=profile.base_url)

    def disconnect(self, name: str) -> None:
        value = self._read()
        if name not in value["profiles"]:
            raise KeyError(f"unknown cloud profile: {name}")
        del value["profiles"][name]
        self._store.write(value)
        try:
            self._credentials.delete_password(PROFILE_SERVICE, name)
        except Exception:
            # The metadata removal is authoritative; some keyring backends
            # report an error when no matching credential exists.
            pass
