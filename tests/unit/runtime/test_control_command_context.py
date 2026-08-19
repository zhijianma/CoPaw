# -*- coding: utf-8 -*-
"""Control commands depend on source identity, not Channel objects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from qwenpaw.runtime.commands.control.base import ControlContext
from qwenpaw.runtime.commands.control.stop_handler import StopCommandHandler


async def test_stop_uses_channel_type_without_channel_instance() -> None:
    chat_manager = SimpleNamespace(
        get_chat_id_by_session=AsyncMock(return_value="chat-1"),
    )
    task_tracker = SimpleNamespace(
        request_stop=AsyncMock(return_value=True),
    )
    channel_manager = SimpleNamespace(
        clear_queue=AsyncMock(return_value=0),
    )
    workspace = SimpleNamespace(
        chat_manager=chat_manager,
        task_tracker=task_tracker,
        channel_manager=channel_manager,
    )
    context = ControlContext(
        workspace=workspace,
        payload=None,
        channel_type="console",
        session_id="console:u1",
        user_id="u1",
        agent_id="default",
        args={},
    )

    result = await StopCommandHandler().handle(context)

    assert "Task Stopped" in result
    chat_manager.get_chat_id_by_session.assert_awaited_once_with(
        "console:u1",
        "console",
        user_id="u1",
    )
