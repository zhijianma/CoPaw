# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from pathlib import Path

import pytest

from qwenpaw.drivers.credentials.providers import (
    OAuth2AuthCodeProvider,
    OAuth2CCProvider,
    StandardOAuth2Exchanger,
    TokenExchangeResult,
)
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord


class _Exchanger:
    def __init__(self, result) -> None:
        self.result = result
        self.refresh_tokens: list[str] = []

    async def exchange(self, secrets):
        self.refresh_tokens.append(str(secrets.get("refresh_token") or ""))
        return self.result


async def _expired_auth_code_store(tmp_path: Path) -> AsyncCredentialStore:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="oauth",
            kind="oauth2_auth_code",
            public={
                "expires_at": time.time() - 60,
                "token_endpoint": "https://example.test/token",
            },
            secrets={
                "access_token": "access-old",
                "refresh_token": "refresh-old",
            },
        ),
    )
    return store


@pytest.mark.asyncio
async def test_auth_code_persists_rotated_refresh_token(
    tmp_path: Path,
) -> None:
    store = await _expired_auth_code_store(tmp_path)
    exchanger = _Exchanger(
        TokenExchangeResult("access-new", 3600, "refresh-new"),
    )
    provider = OAuth2AuthCodeProvider("oauth", store, exchanger)

    resolved = await provider.resolve()
    record = await store.get("oauth")

    assert resolved.secrets["access_token"] == "access-new"
    assert record.secrets["access_token"] == "access-new"
    assert record.secrets["refresh_token"] == "refresh-new"
    assert record.public["expires_at"] > time.time()
    assert exchanger.refresh_tokens == ["refresh-old"]


@pytest.mark.asyncio
async def test_auth_code_keeps_refresh_token_when_not_rotated(
    tmp_path: Path,
) -> None:
    store = await _expired_auth_code_store(tmp_path)
    provider = OAuth2AuthCodeProvider(
        "oauth",
        store,
        _Exchanger(TokenExchangeResult("access-new", 3600)),
    )

    await provider.resolve()

    assert (await store.get("oauth")).secrets["refresh_token"] == "refresh-old"


@pytest.mark.asyncio
async def test_legacy_two_tuple_exchanger_remains_supported(
    tmp_path: Path,
) -> None:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="cc",
            kind="oauth2_cc",
            public={"token_endpoint": "https://example.test/token"},
            secrets={"client_id": "client", "client_secret": "secret"},
        ),
    )
    provider = OAuth2CCProvider(
        "cc",
        store,
        _Exchanger(("legacy-access", 3600)),
    )

    assert (await provider.resolve()).secrets[
        "access_token"
    ] == "legacy-access"


@pytest.mark.asyncio
async def test_standard_exchanger_returns_rotated_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "access_token": "access-new",
                "refresh_token": "refresh-new",
                "expires_in": 123,
            }

    async def _post(self, url, data):
        del self, url, data
        return _Response()

    monkeypatch.setattr("httpx.AsyncClient.post", _post)
    result = await StandardOAuth2Exchanger().exchange(
        {
            "token_endpoint": "https://example.test/token",
            "refresh_token": "refresh-old",
            "client_id": "client",
        },
    )

    assert result == TokenExchangeResult("access-new", 123, "refresh-new")
    access_token, expires_in = result
    assert access_token == "access-new"
    assert expires_in == 123
    assert "access-new" not in repr(result)
    assert "refresh-new" not in repr(result)
