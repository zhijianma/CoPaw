# -*- coding: utf-8 -*-
"""Integration tests for agent-owned Channel configuration APIs."""

from __future__ import annotations

import time

import pytest
from helpers import default_http_timeout

_CHANNEL_HTTP_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_channel_types_exclude_console_transport(app_server) -> None:
    response = app_server.api_request(
        "GET",
        "/api/config/channels/types",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )

    assert response.status_code == 200, app_server.logs_tail()
    channel_types = response.json()
    assert isinstance(channel_types, list)
    assert "telegram" in channel_types
    assert "console" not in channel_types


@pytest.mark.integration
@pytest.mark.p1
def test_channel_list_excludes_console_transport(app_server) -> None:
    response = app_server.api_request(
        "GET",
        "/api/config/channels",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )

    assert response.status_code == 200, app_server.logs_tail()
    channels = response.json()
    assert isinstance(channels, list)
    assert all(item.get("type") != "console" for item in channels)


@pytest.mark.integration
@pytest.mark.p1
def test_console_transport_get_put_roundtrip(app_server) -> None:
    endpoint = "/api/config/transports/console"
    get_before = app_server.api_request(
        "GET",
        endpoint,
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    updated = {**before, "bot_prefix": "integ-console-prefix"}

    try:
        put_response = app_server.api_request(
            "PUT",
            endpoint,
            json=updated,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert put_response.status_code == 200, app_server.logs_tail()
        assert put_response.json()["bot_prefix"] == "integ-console-prefix"

        get_after = app_server.api_request(
            "GET",
            endpoint,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json()["bot_prefix"] == "integ-console-prefix"
    finally:
        app_server.api_request(
            "PUT",
            endpoint,
            json=before,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p0
def test_channel_type_supports_multiple_configurations(app_server) -> None:
    endpoint = "/api/config/channels"
    payload = {
        "type": "telegram",
        "name": "Integration Main",
        "enabled": False,
        "settings": {"bot_token": "main-token"},
    }

    secondary_id = ""
    try:
        created = app_server.api_request(
            "POST",
            endpoint,
            json=payload,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert created.status_code == 201, app_server.logs_tail()

        duplicate = app_server.api_request(
            "POST",
            endpoint,
            json={**payload, "name": "Integration Backup"},
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert duplicate.status_code == 201, app_server.logs_tail()
        assert created.json()["id"] == "telegram"
        secondary_id = duplicate.json()["id"]
        assert secondary_id.startswith("telegram-")

        update = app_server.api_request(
            "PUT",
            f"{endpoint}/telegram",
            json={**payload, "name": "Integration Renamed"},
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert update.status_code == 200, app_server.logs_tail()
        assert update.json()["name"] == "Integration Renamed"

        fetched = app_server.api_request(
            "GET",
            f"{endpoint}/telegram",
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert fetched.status_code == 200, app_server.logs_tail()
        assert fetched.json()["name"] == "Integration Renamed"
    finally:
        if secondary_id:
            app_server.api_request(
                "DELETE",
                f"{endpoint}/{secondary_id}",
                timeout=_CHANNEL_HTTP_TIMEOUT,
            )
        app_server.api_request(
            "DELETE",
            f"{endpoint}/telegram",
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p2
def test_unknown_channel_configuration_returns_404(app_server) -> None:
    response = app_server.api_request(
        "GET",
        "/api/config/channels/nonexistent-channel",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )

    assert response.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_console_transport_config_persists_after_restart(app_server) -> None:
    config_endpoint = "/api/config/transports/console"
    get_before = app_server.api_request(
        "GET",
        config_endpoint,
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    updated = {**before, "bot_prefix": "restart-persist-test"}

    try:
        put_response = app_server.api_request(
            "PUT",
            config_endpoint,
            json=updated,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert put_response.status_code == 200, app_server.logs_tail()

        restart = app_server.api_request(
            "POST",
            "/api/config/channels/console/restart",
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert restart.status_code == 200, app_server.logs_tail()
        time.sleep(1.0)

        get_after = app_server.api_request(
            "GET",
            config_endpoint,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json()["bot_prefix"] == "restart-persist-test"
    finally:
        app_server.api_request(
            "PUT",
            config_endpoint,
            json=before,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p1
def test_console_runtime_health(app_server) -> None:
    response = app_server.api_request(
        "GET",
        "/api/config/channels/console/health",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )

    assert response.status_code == 200, app_server.logs_tail()
    assert response.json().get("status") in {"healthy", "unhealthy"}
