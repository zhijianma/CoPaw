# -*- coding: utf-8 -*-
"""Workspace-scoped third-party agent lifecycle and translation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from ..domain.turns.events import RuntimeEvent
from ..engines.harness import HarnessRuntimeEventMapper
from ..schemas import ContentType
from .base import HarnessAdapter
from .capabilities import HarnessCapabilityResolver
from .events import (
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessEvent,
    HarnessEventKind,
    HarnessProvider,
)
from .registry import (
    PROVIDER_CATALOG,
    adapter_config_key,
    create_adapter,
    get_provider,
)
from .session import HarnessSessionBridge

logger = logging.getLogger(__name__)


class HarnessRuntime:
    """Own adapters for one workspace and emit canonical runtime events."""

    def __init__(
        self,
        workspace_dir: Path,
        session: Any = None,
        agent_id: str = "default",
        workspace: Any = None,
    ) -> None:
        self._state_dir = workspace_dir / "harnesses"
        self._agent_id = agent_id
        self._adapters: dict[str, HarnessAdapter] = {}
        self._adapter_keys: dict[str, tuple[Any, ...]] = {}
        self._adapter_lock = asyncio.Lock()
        self._session_bridge = (
            HarnessSessionBridge(session) if session is not None else None
        )
        self._capability_resolver = HarnessCapabilityResolver(
            workspace_dir,
            workspace,
        )

    async def providers(
        self,
        provider_settings: dict[str, dict[str, Any]] | None = None,
    ) -> list[HarnessProvider]:
        """Return the third-party agent catalog with live provider status."""
        result: list[HarnessProvider] = []
        for item in PROVIDER_CATALOG:
            provider_id = item.id
            if item.coming_soon:
                result.append(
                    HarnessProvider(
                        id=provider_id,
                        name=item.name,
                        available=False,
                        coming_soon=True,
                    ),
                )
                continue
            adapter = await self.adapter(
                provider_id,
                (provider_settings or {}).get(provider_id),
            )
            provider = await adapter.status()
            provider.capabilities = item.capabilities
            result.append(provider)
        return result

    async def adapter(
        self,
        provider_id: str,
        settings: dict[str, Any] | None = None,
    ) -> HarnessAdapter:
        """Return an adapter matching the current provider configuration."""
        next_key = adapter_config_key(provider_id, settings)
        async with self._adapter_lock:
            adapter = self._adapters.get(provider_id)
            current_key = self._adapter_keys.get(provider_id)
            if adapter is not None and (current_key is None or current_key == next_key):
                return adapter
            if adapter is not None:
                await adapter.stop()
            adapter = create_adapter(provider_id, self._state_dir, settings)
            self._adapter_keys[provider_id] = next_key
            self._adapters[provider_id] = adapter
            return adapter

    async def stream_events(
        self,
        *,
        backend: str,
        request: Any,
        cwd: Path,
        settings: dict[str, Any] | None = None,
    ) -> AsyncGenerator[RuntimeEvent, None]:
        """Run one provider turn without choosing an output protocol."""
        settings = dict(settings or {})
        request_context = dict(settings.get("_request_context") or {})
        settings["_runtime_capabilities"] = await self._capability_resolver.resolve(
            request_context
        )
        adapter = await self.adapter(backend, settings)
        session_id = str(getattr(request, "session_id", "") or "default")
        prompt, attachments = self._content_from_request(request)
        command, arguments = (
            self._parse_command(prompt) if not attachments else ("", "")
        )
        mapper = HarnessRuntimeEventMapper(request.turn_id)
        captured_events: list[HarnessEvent] = []
        error_text = ""
        cancelled = False
        task_cancelled = False
        yield RuntimeEvent.turn_started(turn_id=request.turn_id)

        try:
            if command in {"new", "clear"}:
                await adapter.reset_session(session_id)
                events = [
                    HarnessEvent(
                        kind=HarnessEventKind.TEXT_DELTA,
                        text="Started a fresh conversation.",
                    ),
                    HarnessEvent(kind=HarnessEventKind.COMPLETED),
                ]
                event_stream = self._iter_events(events)
            elif command:
                provider = get_provider(backend)
                supported = {item.name for item in provider.capabilities.commands}
                if command not in supported:
                    raise ValueError(
                        f"Unsupported {provider.name} command: /{command}",
                    )
                events = await adapter.run_command(
                    session_id=session_id,
                    command=command,
                    arguments=arguments,
                    cwd=cwd,
                    settings=settings,
                )
                event_stream = self._iter_events(events)
            else:
                event_stream = adapter.run_turn(
                    session_id=session_id,
                    prompt=prompt,
                    cwd=cwd,
                    settings=settings,
                    attachments=attachments,
                )
            async for event in event_stream:
                captured_events.append(event)
                if event.kind == HarnessEventKind.ERROR:
                    error_text = event.text
                elif event.kind == HarnessEventKind.CANCELLED:
                    cancelled = True
                else:
                    for runtime_event in mapper.map(event):
                        yield runtime_event
        except asyncio.CancelledError:
            cancelled = True
            task_cancelled = True
        except Exception as exc:
            error_text = str(exc)

        for runtime_event in mapper.finish_content():
            yield runtime_event

        clear_history = command in {"new", "clear"}
        if self._session_bridge is not None and clear_history:
            try:
                await self._session_bridge.clear(
                    session_id=session_id,
                    user_id=str(
                        request.user_id or session_id,
                    ),
                    channel=str(request.source.channel_type or ""),
                )
            except Exception:
                logger.warning(
                    "Failed to clear third-party session %s",
                    session_id,
                    exc_info=True,
                )
        elif self._session_bridge is not None:
            try:
                await self._session_bridge.append_turn(
                    request=request,
                    events=captured_events,
                    backend=backend,
                )
            except Exception:
                logger.warning(
                    "Failed to persist third-party session %s",
                    session_id,
                    exc_info=True,
                )
        if task_cancelled:
            raise asyncio.CancelledError
        if error_text:
            yield RuntimeEvent.turn_failed(
                error_text,
                "harness_error",
                turn_id=request.turn_id,
            )
        elif cancelled:
            yield RuntimeEvent.turn_cancelled(turn_id=request.turn_id)
        else:
            yield RuntimeEvent.turn_completed(turn_id=request.turn_id)

    async def stop(self) -> None:
        """Stop every initialized adapter."""
        async with self._adapter_lock:
            for adapter in tuple(self._adapters.values()):
                await adapter.stop()
            self._adapters.clear()
            self._adapter_keys.clear()

    async def hydrate_session(
        self,
        *,
        backend: str,
        session_id: str,
        user_id: str,
        channel: str,
        settings: dict[str, Any] | None = None,
    ) -> None:
        """Recover an unmaterialized provider thread into QwenPaw."""
        if self._session_bridge is None:
            return
        if await self._session_bridge.has_history(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        ):
            return
        adapter = await self.adapter(backend, settings)
        history = await adapter.history(session_id)
        await self._session_bridge.hydrate(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            backend=backend,
            history=history,
        )

    @staticmethod
    def _content_from_request(
        request: Any,
    ) -> tuple[str, list[HarnessAttachment]]:
        parts: list[str] = []
        attachments: list[HarnessAttachment] = []
        for message in request.messages:
            for content in getattr(message, "content", None) or []:
                if isinstance(content, str):
                    parts.append(content)
                    continue
                text = getattr(content, "text", None)
                if text:
                    parts.append(str(text))
                    continue
                content_type = getattr(content, "type", None)
                if content_type == ContentType.IMAGE:
                    raw_path = getattr(content, "image_url", None)
                    if raw_path:
                        attachments.append(
                            HarnessAttachment(
                                kind=HarnessAttachmentKind.IMAGE,
                                path=Path(str(raw_path)).expanduser(),
                                name=Path(str(raw_path)).name,
                            ),
                        )
                    continue
                path_field = None
                if content_type == ContentType.FILE:
                    path_field = "file_url"
                elif content_type == ContentType.AUDIO:
                    path_field = "data"
                elif content_type == ContentType.VIDEO:
                    path_field = "video_url"
                raw_path = getattr(content, path_field, None) if path_field else None
                if raw_path:
                    attachments.append(
                        HarnessAttachment(
                            kind=HarnessAttachmentKind.FILE,
                            path=Path(str(raw_path)).expanduser(),
                            name=str(
                                getattr(content, "filename", None)
                                or Path(str(raw_path)).name,
                            ),
                        ),
                    )
        prompt = "\n".join(parts).strip()
        if not prompt and not attachments:
            raise ValueError(
                "Third-party agent requests require text or attachments",
            )
        return prompt, attachments

    @staticmethod
    def _parse_command(prompt: str) -> tuple[str, str]:
        if not prompt.startswith("/"):
            return "", ""
        first_line = prompt.splitlines()[0].strip()
        command, _, arguments = first_line[1:].partition(" ")
        return command.lower(), arguments.strip()

    @staticmethod
    async def _iter_events(
        events: list[Any],
    ) -> AsyncGenerator[Any, None]:
        for event in events:
            yield event


__all__ = ["HarnessRuntime"]
