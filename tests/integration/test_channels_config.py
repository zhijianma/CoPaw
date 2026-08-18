# -*- coding: utf-8 -*-
"""Agent-scoped integration tests for Channel configurations."""

from __future__ import annotations

import pytest


def _create_agent(app_server, agent_id: str) -> None:
    response = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped Channel Agent",
            "description": "",
        },
    )
    assert response.status_code == 201, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_console_transport_roundtrip(app_server) -> None:
    agent_id = "integ-scoped-console-01"
    endpoint = f"/api/agents/{agent_id}/config/transports/console"
    _create_agent(app_server, agent_id)

    try:
        get_before = app_server.api_request("GET", endpoint)
        assert get_before.status_code == 200, app_server.logs_tail()
        before = get_before.json()
        updated = {**before, "bot_prefix": "scoped-console"}

        put_response = app_server.api_request(
            "PUT",
            endpoint,
            json=updated,
        )
        assert put_response.status_code == 200, app_server.logs_tail()

        get_after = app_server.api_request("GET", endpoint)
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json()["bot_prefix"] == "scoped-console"
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_channel_type_supports_multiple_instances(
    app_server,
) -> None:
    agent_id = "integ-scoped-channels-01"
    endpoint = f"/api/agents/{agent_id}/config/channels"
    _create_agent(app_server, agent_id)

    try:
        payload = {
            "type": "telegram",
            "name": "Scoped Telegram",
            "enabled": False,
            "settings": {"bot_token": "main"},
        }
        created = app_server.api_request("POST", endpoint, json=payload)
        assert created.status_code == 201, app_server.logs_tail()

        duplicate = app_server.api_request(
            "POST",
            endpoint,
            json={**payload, "name": "Scoped Backup"},
        )
        assert duplicate.status_code == 201, app_server.logs_tail()
        assert created.json()["id"] == "telegram"
        assert duplicate.json()["id"].startswith("telegram-")

        listed = app_server.api_request("GET", endpoint)
        assert listed.status_code == 200, app_server.logs_tail()
        telegrams = [
            item for item in listed.json() if item["type"] == "telegram"
        ]
        assert len(telegrams) == 2
        selected = next(item for item in telegrams if item["id"] == "telegram")

        updated = {
            **selected,
            "name": "Scoped Main Renamed",
        }
        put_response = app_server.api_request(
            "PUT",
            f"{endpoint}/{selected['id']}",
            json=updated,
        )
        assert put_response.status_code == 200, app_server.logs_tail()
        assert put_response.json()["name"] == "Scoped Main Renamed"

        fetched = app_server.api_request(
            "GET",
            f"{endpoint}/telegram",
        )
        assert fetched.status_code == 200, app_server.logs_tail()
        assert fetched.json()["enabled"] is False
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_profile_exposes_channel_map_and_transport(app_server) -> None:
    response = app_server.api_request("GET", "/api/agents/default")

    assert response.status_code == 200, app_server.logs_tail()
    profile = response.json()
    assert isinstance(profile.get("channels"), dict)
    assert isinstance(profile.get("transports", {}).get("console"), dict)


@pytest.mark.integration
@pytest.mark.p2
def test_channel_health_requires_running_channel_type(app_server) -> None:
    response = app_server.api_request(
        "GET",
        "/api/config/channels/not-running-channel/health",
    )

    assert response.status_code == 404, app_server.logs_tail()
