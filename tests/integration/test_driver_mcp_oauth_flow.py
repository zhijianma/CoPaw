# -*- coding: utf-8 -*-
import asyncio
import time
from pathlib import Path

import pytest

from qwenpaw.drivers.capabilities import DriverInvocation
from qwenpaw.drivers.contracts import CredentialRef, DriverCard, PolicyRule
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.drivers.credentials.providers import (
    StandardOAuth2Exchanger,
    TokenExchangeResult,
)
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import card_path, dump_card
from tests.integration.driver_mcp_fakes import (
    FakeHttpClient,
    patch_mcp_runtime_clients,
)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.p1
async def test_driver_mcp_oauth_access_token_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/oauth_echo/oauth",
            kind="oauth2_auth_code",
            public={"expires_at": 0.0, "scope": "tools:read tools:call"},
            secrets={"access_token": "oauth-token"},
        ),
    )
    dump_card(
        DriverCard(
            name="oauth_echo",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "http://127.0.0.1:18081/mcp",
                "headers": {"public": {}, "secret_refs": {}},
            },
            credentials={
                "oauth": CredentialRef(
                    "oauth2_auth_code",
                    "mcp/oauth_echo/oauth",
                ),
            },
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(tmp_path / "drivers", "oauth_echo", protocol="mcp"),
    )
    manager = DriverManager(tmp_path / "drivers", store)
    manager.register_handler_type("mcp", MCPDriverHandler)

    await manager.build_drivers()
    capability = next(
        item
        for item in await manager.list_capabilities(kind="tool")
        if item.name == "oauth_echo"
    )
    result = await manager.invoke_capability(
        DriverInvocation(capability.capability_id, {"text": "hello"}),
    )

    assert result.ok is True
    assert FakeHttpClient.instances[0].kwargs["headers"] == {
        "Authorization": "Bearer oauth-token",
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.p2
async def test_driver_mcp_http_combines_oauth_and_static_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/composite/oauth",
            kind="oauth2_auth_code",
            public={"expires_at": 0.0},
            secrets={"access_token": "oauth-token"},
        ),
    )
    await store.put(
        CredentialRecord(
            ref="mcp/composite/static",
            kind="static",
            secrets={"api_key": "static-key"},
        ),
    )
    dump_card(
        DriverCard(
            name="composite",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "http://127.0.0.1:18081/mcp",
                "headers": {
                    "Authorization": {
                        "source": "credential",
                        "credential": "oauth",
                        "field": "access_token",
                        "format": "Bearer {value}",
                    },
                    "X-API-Key": {
                        "source": "credential",
                        "credential": "static",
                        "field": "api_key",
                    },
                    "X-Client-Name": {
                        "source": "literal",
                        "value": "qwenpaw-test",
                    },
                },
            },
            credentials={
                "oauth": CredentialRef(
                    "oauth2_auth_code",
                    "mcp/composite/oauth",
                ),
                "static": CredentialRef("static", "mcp/composite/static"),
            },
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(tmp_path / "drivers", "composite", protocol="mcp"),
    )
    manager = DriverManager(tmp_path / "drivers", store)
    manager.register_handler_type("mcp", MCPDriverHandler)

    await manager.build_drivers()
    capability = next(
        item
        for item in await manager.list_capabilities(kind="tool")
        if item.name == "inspect_headers"
    )
    result = await manager.invoke_capability(
        DriverInvocation(capability.capability_id, {}),
    )

    assert result.ok is True
    assert result.value["headers"] == {
        "Authorization": "Bearer oauth-token",
        "X-API-Key": "static-key",
        "X-Client-Name": "qwenpaw-test",
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.p1
async def test_driver_mcp_reconnects_when_access_token_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/rotating/oauth",
            kind="static",
            secrets={"access_token": "access-a"},
        ),
    )
    dump_card(
        DriverCard(
            name="rotating",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "http://127.0.0.1:18081/mcp",
            },
            credentials={
                "oauth": CredentialRef("static", "mcp/rotating/oauth"),
            },
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(tmp_path / "drivers", "rotating", protocol="mcp"),
    )
    manager = DriverManager(tmp_path / "drivers", store)
    manager.register_handler_type("mcp", MCPDriverHandler)
    await manager.build_drivers()
    capability = next(
        item
        for item in await manager.list_capabilities(kind="tool")
        if item.name == "oauth_echo"
    )
    old_client = FakeHttpClient.instances[0]

    await store.put(
        CredentialRecord(
            ref="mcp/rotating/oauth",
            kind="static",
            secrets={"access_token": "access-b"},
        ),
    )
    results = await asyncio.gather(
        manager.invoke_capability(
            DriverInvocation(capability.capability_id, {"call": 1}),
        ),
        manager.invoke_capability(
            DriverInvocation(capability.capability_id, {"call": 2}),
        ),
    )

    assert all(result.ok for result in results)
    assert len(FakeHttpClient.instances) == 2
    assert FakeHttpClient.instances[1].kwargs["headers"] == {
        "Authorization": "Bearer access-b",
    }
    assert old_client.is_connected is False


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.p1
async def test_driver_mcp_refreshes_expired_token_and_uses_new_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    now = time.time()
    refresh_inputs: list[str] = []

    async def exchange(_self, secrets):
        refresh_inputs.append(str(secrets["refresh_token"]))
        return TokenExchangeResult(
            access_token="access-new",
            expires_in=3600,
            refresh_token="refresh-new",
        )

    monkeypatch.setattr(
        StandardOAuth2Exchanger,
        "exchange",
        exchange,
    )
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/expiring/oauth",
            kind="oauth2_auth_code",
            public={
                "expires_at": now + 3600,
                "token_endpoint": "https://example.test/token",
            },
            secrets={
                "access_token": "access-old",
                "refresh_token": "refresh-old",
            },
        ),
    )
    dump_card(
        DriverCard(
            name="expiring",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "http://127.0.0.1:18081/mcp",
            },
            credentials={
                "oauth": CredentialRef(
                    "oauth2_auth_code",
                    "mcp/expiring/oauth",
                ),
            },
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(tmp_path / "drivers", "expiring", protocol="mcp"),
    )
    manager = DriverManager(tmp_path / "drivers", store)
    manager.register_handler_type("mcp", MCPDriverHandler)
    await manager.build_drivers()
    old_client = FakeHttpClient.instances[0]
    assert old_client.kwargs["headers"] == {
        "Authorization": "Bearer access-old",
    }

    monkeypatch.setattr(
        "qwenpaw.drivers.credentials.providers.time.time",
        lambda: now + 3601,
    )
    capability = next(
        item
        for item in await manager.list_capabilities(kind="tool")
        if item.name == "oauth_echo"
    )
    result = await manager.invoke_capability(
        DriverInvocation(capability.capability_id, {"text": "after-refresh"}),
    )
    record = await store.get("mcp/expiring/oauth")

    assert result.ok is True
    assert refresh_inputs == ["refresh-old"]
    assert record.secrets["access_token"] == "access-new"
    assert record.secrets["refresh_token"] == "refresh-new"
    assert len(FakeHttpClient.instances) == 2
    new_client = FakeHttpClient.instances[1]
    assert new_client.kwargs["headers"] == {
        "Authorization": "Bearer access-new",
    }
    assert new_client.calls == [
        ("oauth_echo", {"text": "after-refresh"}),
    ]
    assert old_client.calls == []
    assert old_client.is_connected is False


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.p1
async def test_driver_mcp_failed_reconnect_keeps_old_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingReplacementClient(FakeHttpClient):
        instances: list["_FailingReplacementClient"] = []

        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.__class__.instances.append(self)

        async def connect(self) -> None:
            if len(self.__class__.instances) > 1:
                raise RuntimeError("replacement connection failed")
            await super().connect()

    monkeypatch.setattr(
        "qwenpaw.drivers.handlers.mcp.HttpStatefulClient",
        _FailingReplacementClient,
    )
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/rollback/oauth",
            kind="static",
            secrets={"access_token": "access-a"},
        ),
    )
    card = DriverCard(
        name="rollback",
        protocol="mcp",
        endpoint={
            "transport": "streamable_http",
            "url": "http://127.0.0.1:18081/mcp",
        },
        credentials={
            "oauth": CredentialRef("static", "mcp/rollback/oauth"),
        },
        policy=[PolicyRule(subject="*", effect="allow")],
    )
    dump_card(
        card,
        card_path(tmp_path / "drivers", "rollback", protocol="mcp"),
    )
    manager = DriverManager(tmp_path / "drivers", store)
    manager.register_handler_type("mcp", MCPDriverHandler)
    await manager.build_drivers()
    capability = next(
        item
        for item in await manager.list_capabilities(kind="tool")
        if item.name == "oauth_echo"
    )
    old_client = _FailingReplacementClient.instances[0]
    await store.put(
        CredentialRecord(
            ref="mcp/rollback/oauth",
            kind="static",
            secrets={"access_token": "access-b"},
        ),
    )

    result = await manager.invoke_capability(
        DriverInvocation(capability.capability_id, {}),
    )

    assert result.ok is False
    assert "replacement connection failed" in result.message
    assert old_client.is_connected is True


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.p1
async def test_driver_mcp_drains_in_flight_call_before_closing_old_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingClient(FakeHttpClient):
        instances: list["_BlockingClient"] = []

        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.__class__.instances.append(self)

        async def call_tool(self, name, arguments):
            if arguments.get("block"):
                started.set()
                await release.wait()
            return await super().call_tool(name, arguments)

    monkeypatch.setattr(
        "qwenpaw.drivers.handlers.mcp.HttpStatefulClient",
        _BlockingClient,
    )
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    credential_ref = "mcp/draining/oauth"
    await store.put(
        CredentialRecord(
            ref=credential_ref,
            kind="static",
            secrets={"access_token": "access-a"},
        ),
    )
    dump_card(
        DriverCard(
            name="draining",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "http://127.0.0.1:18081/mcp",
            },
            credentials={
                "oauth": CredentialRef("static", credential_ref),
            },
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(tmp_path / "drivers", "draining", protocol="mcp"),
    )
    manager = DriverManager(tmp_path / "drivers", store)
    manager.register_handler_type("mcp", MCPDriverHandler)
    await manager.build_drivers()
    capability = next(
        item
        for item in await manager.list_capabilities(kind="tool")
        if item.name == "oauth_echo"
    )
    old_client = _BlockingClient.instances[0]
    first_call = asyncio.create_task(
        manager.invoke_capability(
            DriverInvocation(capability.capability_id, {"block": True}),
        ),
    )
    await started.wait()

    await store.put(
        CredentialRecord(
            ref=credential_ref,
            kind="static",
            secrets={"access_token": "access-b"},
        ),
    )
    second_result = await manager.invoke_capability(
        DriverInvocation(capability.capability_id, {"block": False}),
    )

    assert second_result.ok is True
    assert old_client.is_connected is True
    assert len(_BlockingClient.instances) == 2

    release.set()
    first_result = await first_call
    assert first_result.ok is True
    assert old_client.is_connected is False
