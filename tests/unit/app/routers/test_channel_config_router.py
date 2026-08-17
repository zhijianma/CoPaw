# -*- coding: utf-8 -*-
"""API contracts for one Channel configuration per type and Agent."""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.config import router as config_router
from qwenpaw.config.config import AgentProfileConfig


@pytest.fixture
def agent_workspace() -> MagicMock:
    workspace = MagicMock()
    workspace.agent_id = "default"
    workspace.config = AgentProfileConfig(
        id="default",
        name="Default",
        channels={
            "telegram": {
                "name": "Main Bot",
                "settings": {"bot_token": "secret"},
            },
        },
    )
    return workspace


@pytest.fixture
def client(agent_workspace: MagicMock):
    app = FastAPI()
    app.state.multi_agent_manager = MagicMock()
    app.state.multi_agent_manager.agents = {
        "default": agent_workspace,
    }
    app.include_router(config_router, prefix="/api")
    with patch(
        "qwenpaw.app.agent_context.get_agent_for_request",
        new=AsyncMock(return_value=agent_workspace),
    ):
        yield TestClient(app)


def test_list_returns_channel_configurations(client: TestClient) -> None:
    response = client.get("/api/config/channels")

    assert response.status_code == 200
    assert response.json() == [
        {
            "type": "telegram",
            "name": "Main Bot",
            "enabled": True,
            "settings": {"bot_token": "secret"},
        },
    ]


def test_create_rejects_second_configuration_of_same_type(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/config/channels",
        json={
            "type": "telegram",
            "name": "Backup Bot",
            "enabled": False,
            "settings": {"bot_token": "backup"},
        },
    )

    assert response.status_code == 422
    assert "already configured" in response.text


def test_update_uses_channel_type(client: TestClient) -> None:
    with patch("qwenpaw.config.config.save_agent_config") as save:
        response = client.put(
            "/api/config/channels/telegram",
            json={
                "type": "telegram",
                "name": "Renamed",
                "enabled": False,
                "settings": {"bot_token": "new"},
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["type"] == "telegram"
    assert response.json()["name"] == "Renamed"
    assert save.call_args.args[1].channels["telegram"].enabled is False


def test_delete_uses_channel_type(client: TestClient) -> None:
    with patch("qwenpaw.config.config.save_agent_config") as save:
        response = client.delete("/api/config/channels/telegram")

    assert response.status_code == 204, response.text
    assert save.call_args.args[1].channels == {}


def test_unknown_channel_returns_404(client: TestClient) -> None:
    response = client.get("/api/config/channels/missing")

    assert response.status_code == 404


def test_conflict_check_ignores_current_agent(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/config/channels/telegram/conflict-check",
        json={"enabled": True, "bot_token": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["conflict"] is False
