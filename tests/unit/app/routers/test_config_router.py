# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.routers.config``.

Scope: non-Channel configuration endpoints. Channel instance API tests
live in ``test_channel_instance_router.py``.

Covers:

- ``GET /config/channels/types`` and catalog metadata
- ``GET /config/security/tool-guard`` — happy path
- ``PUT /config/security/tool-guard`` — happy path + engine reload
- 422 on a malformed PUT body
- 404 propagated from ``get_agent_for_request``
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.crons import heartbeat
from qwenpaw.app.routers.config import router as config_router
from qwenpaw.config.config import (
    AgentProfileConfig,
    Config,
    HeartbeatConfig,
    ToolGuardConfig,
)
from qwenpaw.constant import (
    HEARTBEAT_FILE,
    HEARTBEAT_TARGET_INBOX,
    HEARTBEAT_TARGET_LAST,
)


class _HeartbeatWorkspace:
    async def stream_query(self, _req):
        for event in ():
            yield event


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    # Manager isn't used directly by these endpoints once we patch
    # ``get_agent_for_request``, but keep state attribute populated to
    # avoid spurious 500s from the auth-context fallback.
    application.state.multi_agent_manager = MagicMock(name="ManagerStub")
    application.include_router(config_router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_agent_workspace():
    """Workspace stub with a real agent configuration model."""
    workspace = MagicMock(name="Workspace")
    workspace.agent_id = "default"
    workspace.config = AgentProfileConfig(
        id="default",
        name="Default Agent",
    )
    return workspace


@pytest.fixture
def root_config() -> Config:
    return Config()


@pytest.fixture
def patch_get_agent(fake_agent_workspace, root_config):
    """Patch ``get_agent_for_request`` (imported lazily inside handlers)."""
    with (
        patch(
            "qwenpaw.app.agent_context.get_agent_for_request",
            new=AsyncMock(return_value=fake_agent_workspace),
        ) as patched,
        patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=root_config,
        ),
    ):
        yield patched


# ---------------------------------------------------------------------------
# /config/channels/types — pure list, no deps
# ---------------------------------------------------------------------------


def test_list_channel_types_returns_list(client):
    response = client.get("/api/config/channels/types")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert "telegram" in body
    assert "console" not in body


def test_list_channel_catalog_returns_ordered_definitions(client):
    response = client.get("/api/config/channels/catalog")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["key"] == "console"
    assert body[0]["surface"] == "web"
    assert [item["order"] for item in body] == sorted(
        item["order"] for item in body
    )
    assert {item["key"] for item in body} >= {
        "console",
        "onebot",
        "wechat",
        "mattermost",
    }


# ---------------------------------------------------------------------------
# /config/heartbeat — get + put
# ---------------------------------------------------------------------------


def test_get_heartbeat_returns_timeout_seconds(
    client,
    fake_agent_workspace,
    patch_get_agent,
):
    fake_agent_workspace.config.heartbeat = HeartbeatConfig(
        enabled=True,
        every="2h",
        target="inbox",
        timeoutSeconds=240,
    )

    response = client.get("/api/config/heartbeat")

    assert response.status_code == 200
    assert response.json()["timeoutSeconds"] == 240


def test_put_heartbeat_preserves_timeout_seconds(
    client,
    fake_agent_workspace,
    patch_get_agent,
):
    fake_agent_workspace.cron_manager = None

    with patch("qwenpaw.config.config.save_agent_config") as save_mock:
        response = client.put(
            "/api/config/heartbeat",
            json={
                "enabled": True,
                "every": "2h",
                "target": "inbox",
                "timeoutSeconds": 360,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timeoutSeconds"] == 360
    assert fake_agent_workspace.config.heartbeat.timeout_seconds == 360
    save_mock.assert_called_once()


def test_heartbeat_config_rejects_timeout_above_max():
    with pytest.raises(ValueError):
        HeartbeatConfig(timeoutSeconds=3601)


def test_put_heartbeat_rejects_timeout_above_max(
    client,
    fake_agent_workspace,
    patch_get_agent,
):
    fake_agent_workspace.cron_manager = None

    response = client.put(
        "/api/config/heartbeat",
        json={
            "enabled": True,
            "every": "2h",
            "target": "inbox",
            "timeoutSeconds": 3601,
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "last_dispatch"),
    [
        ("main", None),
        (
            HEARTBEAT_TARGET_LAST,
            SimpleNamespace(
                channel="console",
                user_id="user-1",
                session_id="session-1",
            ),
        ),
        (HEARTBEAT_TARGET_INBOX, None),
    ],
)
async def test_run_heartbeat_once_uses_configured_timeout(
    monkeypatch,
    tmp_path,
    target,
    last_dispatch,
):
    (tmp_path / HEARTBEAT_FILE).write_text("check status", encoding="utf-8")
    seen_timeouts: list[float] = []

    async def fake_wait_for(awaitable, timeout):
        seen_timeouts.append(timeout)
        return await awaitable

    monkeypatch.setattr(heartbeat.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(
        heartbeat,
        "get_heartbeat_config",
        lambda _agent_id=None: HeartbeatConfig(
            enabled=True,
            target=target,
            timeoutSeconds=240,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(last_dispatch=last_dispatch),
    )
    monkeypatch.setattr(
        heartbeat,
        "read_session_messages",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(heartbeat, "create_trace", AsyncMock())
    monkeypatch.setattr(
        heartbeat,
        "append_trace_from_session_delta",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(heartbeat, "finalize_trace", AsyncMock())
    monkeypatch.setattr(heartbeat, "append_inbox_event", AsyncMock())

    await heartbeat.run_heartbeat_once(
        workspace=_HeartbeatWorkspace(),
        channel_manager=SimpleNamespace(send_event=AsyncMock()),
        agent_id="agent-1",
        workspace_dir=tmp_path,
    )

    assert seen_timeouts == [240]


# ---------------------------------------------------------------------------
# /config/security/tool-guard
# ---------------------------------------------------------------------------


def test_get_tool_guard_returns_current_config(client):
    fake_cfg = MagicMock()
    fake_cfg.security.tool_guard = ToolGuardConfig(enabled=True)

    with patch(
        "qwenpaw.app.routers.config.load_config",
        return_value=fake_cfg,
    ):
        response = client.get("/api/config/security/tool-guard")

    assert response.status_code == 200
    assert response.json()["enabled"] is True


def test_put_tool_guard_saves_and_reloads_engine(client):
    fake_cfg = MagicMock()
    fake_cfg.security.tool_guard = ToolGuardConfig(enabled=False)
    engine_mock = MagicMock(enabled=False)

    with (
        patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=fake_cfg,
        ),
        patch("qwenpaw.app.routers.config.save_config") as save_mock,
        patch(
            "qwenpaw.security.tool_guard.engine.get_guard_engine",
            return_value=engine_mock,
        ),
    ):
        response = client.put(
            "/api/config/security/tool-guard",
            json={"enabled": True},
        )

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    save_mock.assert_called_once()
    # The handler must flip the engine flag AND ask it to reload rules.
    assert engine_mock.enabled is True
    engine_mock.reload_rules.assert_called_once()


# ---------------------------------------------------------------------------
# /config/security/sandbox — GET
# ---------------------------------------------------------------------------


def test_get_sandbox_returns_enabled_effective_reason(client):
    """GET /security/sandbox returns enabled, effective, reason fields."""
    fake_cfg = MagicMock()
    fake_cfg.security.sandbox_enabled = True

    with (
        patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=fake_cfg,
        ),
        patch(
            "qwenpaw.app.routers.config._sandbox_effective_status",
            return_value=(True, None),
        ),
    ):
        response = client.get("/api/config/security/sandbox")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["effective"] is True
    assert body["reason"] is None


def test_get_sandbox_preview_with_enabled_param(client):
    """GET /security/sandbox?enabled=false previews without persisting."""
    fake_cfg = MagicMock()
    fake_cfg.security.sandbox_enabled = True

    with (
        patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=fake_cfg,
        ),
        patch(
            "qwenpaw.app.routers.config._sandbox_effective_status",
            return_value=(False, None),
        ) as mock_status,
    ):
        response = client.get("/api/config/security/sandbox?enabled=false")

    assert response.status_code == 200
    body = response.json()
    # The preview should use the proposed value, not the current config.
    assert body["enabled"] is False
    mock_status.assert_called_once_with(False)


# ---------------------------------------------------------------------------
# /config/security/sandbox — PUT (idempotent + admin guard)
# ---------------------------------------------------------------------------


def test_put_sandbox_idempotent_same_value_no_save(client):
    """PUT with unchanged value must skip save (idempotent)."""
    fake_cfg = MagicMock()
    fake_cfg.security.sandbox_enabled = True

    with (
        patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=fake_cfg,
        ),
        patch(
            "qwenpaw.app.routers.config._sandbox_effective_status",
            return_value=(True, "unelevated"),
        ),
        patch("qwenpaw.app.routers.config.save_config") as mock_save,
    ):
        response = client.put(
            "/api/config/security/sandbox",
            json={"enabled": True},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["effective"] is True
    assert body["reason"] == "unelevated"
    # Must NOT have saved (value unchanged)
    mock_save.assert_not_called()


def test_put_sandbox_non_admin_enabling_saves_with_unelevated(client):
    """PUT enabling sandbox as non-admin must save and return unelevated."""
    fake_cfg = MagicMock()
    fake_cfg.security.sandbox_enabled = False

    with (
        patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=fake_cfg,
        ),
        patch(
            "qwenpaw.app.routers.config._sandbox_effective_status",
            return_value=(True, "unelevated"),
        ),
        patch("qwenpaw.app.routers.config.save_config") as mock_save,
    ):
        response = client.put(
            "/api/config/security/sandbox",
            json={"enabled": True},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["effective"] is True
    assert body["reason"] == "unelevated"
    mock_save.assert_called_once()


def test_put_sandbox_admin_enabling_saves(client):
    """PUT enabling sandbox as admin must save and return effective=true."""
    fake_cfg = MagicMock()
    fake_cfg.security.sandbox_enabled = False

    with (
        patch(
            "qwenpaw.app.routers.config.load_config",
            return_value=fake_cfg,
        ),
        patch(
            "qwenpaw.app.routers.config._sandbox_effective_status",
            return_value=(True, None),
        ),
        patch("qwenpaw.app.routers.config.save_config") as mock_save,
    ):
        response = client.put(
            "/api/config/security/sandbox",
            json={"enabled": True},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["effective"] is True
    mock_save.assert_called_once()
