# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""Console Channel.

A lightweight channel that prints all agent responses to stdout.

Messages are sent to the agent via POST /api/console/chat. This channel
handles the **output** side: whenever a completed message event or a
proactive send arrives, it is pretty-printed to the terminal.
"""

from __future__ import annotations

import asyncio
import copy
import json as _json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from qwenpaw.schemas import (
    MessageType,
    Message,
    RunStatus,
)

from ...app.channels.base import (
    BaseChannel,
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
    VideoContent,
    TextContent,
)
from ...app.channels.renderer import ChannelDisplayConfig
from ...app.channels.utils import file_url_to_local_path
from ...app.console_push_store import append as push_store_append
from ...config.config import ConsoleTransportConfig
from ...constant import DEFAULT_MEDIA_DIR
from ...domain.turns.models import TurnRequest
from ...exceptions import ModelQuotaExceededException
from ...protocols.console import ConsoleEventPresenter, ConsoleTurnIngress
from ...protocols.ports import PresentationContext
from .sse import ConsoleSseEncoder

logger = logging.getLogger(__name__)

# ANSI colour helpers (degrade gracefully if not a tty)
_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

_GREEN = "\033[32m" if _USE_COLOR else ""
_YELLOW = "\033[33m" if _USE_COLOR else ""
_RED = "\033[31m" if _USE_COLOR else ""
_BOLD = "\033[1m" if _USE_COLOR else ""
_RESET = "\033[0m" if _USE_COLOR else ""


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


class ConsoleTransport(BaseChannel):
    """Console Channel: prints agent responses to stdout.

    Input is handled by ``POST /api/console/chat``; this channel only
    takes care of output (printing to the terminal).

    Supports filtering options via config:
        - display_config: Control thinking and tool message presentation
    """

    channel = "console"

    _strip_event_headlines = staticmethod(
        ConsoleSseEncoder.strip_event_headlines,
    )
    _serialize_event_for_sse = staticmethod(ConsoleSseEncoder.encode_event)
    _flush_headline_stream_states = staticmethod(
        ConsoleSseEncoder.flush_states,
    )

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        bot_prefix: str,
        on_reply_sent: OnReplySent = None,
        display_config: ChannelDisplayConfig | None = None,
        workspace_dir: Optional[Union[str, Path]] = None,
        media_dir: Optional[str] = None,
        agent_id: str = "default",
    ):
        """Initialize ConsoleTransport.

        Args:
            process: Handler for agent requests.
            enabled: Whether this channel is active.
            bot_prefix: Prefix string for bot messages.
            on_reply_sent: Callback when reply is sent.
            display_config: Thinking and tool display settings.
            workspace_dir: Agent workspace directory; used to resolve uploaded
                file names (media_dir = workspace_dir / "media").
            media_dir: Agent workspace directory for resolving uploads.
        """
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            display_config=display_config,
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix
        self._ingress = ConsoleTurnIngress(default_agent_id=agent_id)
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )

        # Use workspace-specific media dir if workspace_dir is provided
        if not media_dir and self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        elif media_dir:
            self._media_dir = Path(media_dir).expanduser()
        else:
            self._media_dir = DEFAULT_MEDIA_DIR
        self._media_dir.mkdir(parents=True, exist_ok=True)

        # Windows stdout encoding fix
        if sys.platform == "win32":
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug(
                    "Failed to reconfigure stdout encoding on Windows: %s",
                    e,
                )

    @property
    def media_dir(self) -> Path:
        """Media directory"""
        return self._media_dir

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "ConsoleTransport":
        return cls(
            process=process,
            enabled=os.getenv("CONSOLE_CHANNEL_ENABLED", "1") == "1",
            bot_prefix=os.getenv("CONSOLE_BOT_PREFIX", ""),
            on_reply_sent=on_reply_sent,
            media_dir=os.getenv("CONSOLE_MEDIA_DIR", ""),
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: ConsoleTransportConfig,
        on_reply_sent: OnReplySent = None,
        display_config: ChannelDisplayConfig | None = None,
        no_text_debounce: bool = True,
        workspace_dir: Optional[Union[str, Path]] = None,
        agent_id: str = "default",
    ) -> "ConsoleTransport":
        """Create ConsoleTransport from config.

        Args:
            process: Handler for agent requests.
            config: Console channel configuration.
            on_reply_sent: Callback when reply is sent.
            display_config: Thinking and tool display settings.
            workspace_dir: Agent workspace directory for resolving uploads.

        Returns:
            Configured ConsoleTransport instance.
        """
        return cls(
            process=process,
            enabled=config.enabled,
            bot_prefix=config.bot_prefix or "",
            on_reply_sent=on_reply_sent,
            display_config=display_config
            or ChannelDisplayConfig.from_config(config),
            workspace_dir=workspace_dir,
            media_dir=config.media_dir or "",
            agent_id=agent_id,
        )

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[dict] = None,
    ) -> str:
        """Resolve session_id: use explicit meta['session_id'] when provided
        (e.g. from the HTTP /console/chat API), otherwise fall back to
        'console:<sender_id>'.
        """
        if channel_meta and channel_meta.get("session_id"):
            return channel_meta["session_id"]
        return f"{self.channel}:{sender_id}"

    def _resolve_console_upload_refs(
        self,
        content_parts: List[Any],
    ) -> List[Any]:
        """Resolve Image/File/Audio/VideoContent."""
        if not self._media_dir:
            return content_parts

        def resolve_one(part: Any) -> Optional[OutgoingContentPart]:
            content_type = getattr(part, "type", None)
            if content_type == ContentType.IMAGE:
                url = getattr(part, "image_url", None)
                if url:
                    return ImageContent(
                        type=ContentType.IMAGE,
                        image_url=url,
                    )
            elif content_type == ContentType.VIDEO:
                url = getattr(part, "video_url", None)
                if url:
                    return VideoContent(
                        type=ContentType.VIDEO,
                        video_url=url,
                    )
            elif content_type == ContentType.AUDIO:
                url = getattr(part, "data", None)
                if url:
                    return AudioContent(
                        type=ContentType.AUDIO,
                        data=url,
                    )
            elif content_type == ContentType.FILE:
                url = getattr(part, "file_url", None)
                if url:
                    return FileContent(
                        type=ContentType.FILE,
                        filename=getattr(part, "filename", None)
                        or Path(url).name,
                        file_url=url,
                    )
            elif content_type == ContentType.TEXT:
                return TextContent(type=ContentType.TEXT, text=part.text)
            return part

        input_content_parts = []
        for content in content_parts:
            part = resolve_one(content)
            if part is not None:
                input_content_parts.append(part)
        return input_content_parts

    def build_turn_request_from_native(
        self,
        native_payload: Any,
    ) -> TurnRequest:
        """Decode the normalized Console payload at the protocol edge."""
        payload = (
            dict(native_payload) if isinstance(native_payload, dict) else {}
        )
        meta = dict(payload.get("meta") or {})
        meta["session_id"] = self.resolve_session_id(
            str(payload.get("sender_id") or ""),
            meta,
        )
        payload["meta"] = meta
        if not payload.get("content_parts"):
            payload["content_parts"] = [TextContent(text=" ")]
        return self._ingress.decode(payload)

    async def _extract_media_message(self, message: Message) -> Message | None:
        """Extract media message from message."""
        parts = self._message_to_content_parts(message)
        media_message = None
        if message.type in (
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL_OUTPUT,
        ):
            new_parts = []
            for part in parts:
                if part.type == ContentType.IMAGE:
                    new_part = copy.deepcopy(part)
                    new_part.image_url = file_url_to_local_path(
                        new_part.image_url,
                    )
                    new_parts.append(new_part)
                elif part.type == ContentType.VIDEO:
                    new_part = copy.deepcopy(part)
                    new_part.video_url = file_url_to_local_path(
                        new_part.video_url,
                    )
                    new_parts.append(new_part)
                elif part.type == ContentType.AUDIO:
                    new_part = copy.deepcopy(part)
                    new_part.data = file_url_to_local_path(new_part.data)
                    new_parts.append(new_part)
                elif part.type == ContentType.FILE:
                    new_part = copy.deepcopy(part)
                    new_part.file_url = file_url_to_local_path(
                        new_part.file_url,
                    )
                    new_parts.append(new_part)
            if new_parts:
                media_message = Message(
                    type=MessageType.MESSAGE,
                    role="assistant",
                    content=new_parts,
                    status=RunStatus.Completed,
                )
                media_message.object = "message"
        return media_message

    def _on_turn_usage_ready(
        self,
        turn: Optional[Dict[str, Any]],
        ctx: Optional[Dict[str, Any]],
    ) -> None:
        """Print a one-line terminal summary when per-turn usage is staged.

        The shared SSE block is built by ``BaseChannel`` — the console only
        adds the terminal status line on top of it.
        """
        if turn and ctx:
            self._print_status_line(turn, ctx)

    def _print_status_line(
        self,
        turn: Dict[str, Any],
        ctx: Dict[str, Any],
    ) -> None:
        """Print a one-line terminal summary of turn + context usage."""
        from ...token_usage import fmt_tokens

        pt = turn.get("prompt_tokens", 0)
        ct = turn.get("completion_tokens", 0)
        tt = turn.get("total_tokens", 0)
        est = int(ctx.get("estimated_tokens", 0) or 0)
        mx = int(ctx.get("max_input_length", 0) or 0)
        ratio = ctx.get("context_usage_ratio", 0) or 0
        turn_line = (
            f"{_GREEN}Turn {_BOLD}{fmt_tokens(tt)}{_RESET} "
            f"(in {fmt_tokens(pt)} · out {fmt_tokens(ct)})"
        )
        ctx_line = (
            f" · Context {_BOLD}{fmt_tokens(est)}{_RESET} / "
            f"{fmt_tokens(mx)} ({ratio:.1f}%)"
        )
        self._safe_print(f"📝 {turn_line}{ctx_line}")

    async def stream_one(self, payload: Any) -> AsyncGenerator[str, None]:
        """Process one payload and yield SSE-formatted events"""
        if isinstance(payload, dict) and "content_parts" in payload:
            session_id = self.resolve_session_id(
                payload.get("sender_id") or "",
                payload.get("meta"),
            )
            content_parts = payload.get("content_parts") or []
            should_process, merged = self._apply_no_text_debounce(
                session_id,
                content_parts,
            )
            if not should_process:
                return
            payload = {**payload, "content_parts": merged}
            request = self.build_turn_request_from_native(payload)
        else:
            request = (
                payload
                if isinstance(payload, TurnRequest)
                else self._ingress.decode(payload)
            )
            session_id = getattr(request, "session_id", "") or ""
            if request.messages:
                contents = list(
                    getattr(request.messages[0], "content", None) or [],
                )
                should_process, merged = self._apply_no_text_debounce(
                    session_id,
                    contents,
                )
                if not should_process:
                    return
                if merged:
                    first = request.messages[0]
                    request = TurnRequest(
                        turn_id=request.turn_id,
                        agent_id=request.agent_id,
                        session_id=request.session_id,
                        user_id=request.user_id,
                        messages=(
                            first.model_copy(update={"content": merged}),
                            *request.messages[1:],
                        ),
                        source=request.source,
                        reply_target=request.reply_target,
                        context=request.context,
                    )
        session_id = getattr(request, "session_id", "") or session_id
        self._clear_session_turn_usage(session_id)
        user_id = getattr(request, "user_id", "") or ""
        channel_name = request.source.channel_type or self.channel

        # Refresh the chat's updated_at so the console session list surfaces
        # this new message as the latest activity (issue #6131). stream_one is
        # the single console executor for the web streaming, background-task,
        # and terminal CLI paths, so touching here covers them all. We only
        # touch an already-existing chat (never create one) to preserve the
        # current behavior for sessions that have no ChatSpec yet.
        if self._workspace is not None and session_id:
            try:
                chat_mgr = getattr(self._workspace, "chat_manager", None)
                if chat_mgr is not None:
                    await chat_mgr.touch_chat_by_session(
                        session_id=session_id,
                        channel=channel_name,
                        user_id=user_id or None,
                    )
            except Exception:  # pylint: disable=broad-except
                logger.debug(
                    "failed to touch chat updated_at for session=%s",
                    session_id[:30],
                    exc_info=True,
                )

        try:
            last_response = None
            event_count = 0
            sse_encoder = ConsoleSseEncoder()
            presenter = ConsoleEventPresenter(session_id=session_id)
            presentation_context = PresentationContext(
                protocol="console",
                conversation_id=session_id,
                turn_id=request.turn_id,
            )

            async def _presented_events() -> AsyncGenerator[Any, None]:
                async for runtime_event in self._process(request):
                    async for output in presenter.present(
                        runtime_event,
                        presentation_context,
                    ):
                        yield output

            async for event in _presented_events():
                event_count += 1
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)
                ev_type = getattr(event, "type", None)

                logger.debug(
                    "console event #%s: object=%s status=%s type=%s",
                    event_count,
                    obj,
                    status,
                    ev_type,
                )

                if (
                    event.object == "response"
                    and event.status == RunStatus.Completed
                ):
                    event_output = event.output
                    event.output = []
                    if event_output is not None:
                        for message in event_output:
                            event.output.append(message)

                if obj == "message" and status == RunStatus.Completed:
                    msg_id = str(
                        getattr(event, "msg_id", "")
                        or getattr(event, "id", "")
                        or "",
                    )
                    for pending_data in sse_encoder.flush(msg_id=msg_id):
                        yield f"data: {pending_data}\n\n"
                elif obj == "response" and status == RunStatus.Completed:
                    for pending_data in sse_encoder.flush():
                        yield f"data: {pending_data}\n\n"

                data = sse_encoder.encode(event)
                yield f"data: {data}\n\n"

                if obj == "message" and status == RunStatus.Completed:
                    parts = self._message_to_content_parts(event)
                    self._print_parts(parts, ev_type)

                elif obj == "response":
                    last_response = event

            for pending_data in sse_encoder.flush():
                yield f"data: {pending_data}\n\n"

            err_msg = self._get_response_error_message(last_response)
            if err_msg:
                self._clear_session_turn_usage(session_id)
                self._print_error(err_msg)
            else:
                for sse in await self._commit_turn_usage(
                    request,
                    session_id,
                    emit_sse=True,
                ):
                    yield sse

            logger.info(
                "console stream done: event_count=%s has_response=%s",
                event_count,
                last_response is not None,
            )

            to_handle = request.user_id or ""
            if self._on_reply_sent:
                self._on_reply_sent(
                    self.channel,
                    to_handle,
                    request.session_id or f"{self.channel}:{to_handle}",
                )

        except asyncio.CancelledError:
            self._clear_session_turn_usage(session_id)
            raise
        except ModelQuotaExceededException as e:
            self._clear_session_turn_usage(session_id)
            logger.warning("rate limit hit: %s", e)
            alternatives = self._get_free_model_alternatives()
            rl_event = _json.dumps(
                {
                    "type": "rate_limited",
                    "error": str(e).strip(),
                    "alternatives": alternatives,
                },
            )
            yield f"data: {rl_event}\n\n"
            self._print_error(str(e).strip())
        except Exception as e:
            self._clear_session_turn_usage(session_id)
            logger.exception("console process/reply failed")
            err_msg = str(e).strip() or "An error occurred while processing."
            self._print_error(err_msg)
        finally:
            try:
                await self._on_response_cycle_end(session_id)
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "console response-cycle cleanup failed for session=%s",
                    session_id[:30],
                    exc_info=True,
                )

    async def _on_response_cycle_end(self, session_id: str) -> None:
        """Delegate console streaming cleanup to the shared channel path."""
        await self._finish_response_cycle(session_id)

    async def consume_one(self, payload: Any) -> None:
        """Process one payload; drain stream_one (queue/terminal)."""
        async for _ in self.stream_one(payload):
            pass

    # ── pretty-print helpers ────────────────────────────────────────

    def _safe_print(self, text: str) -> None:
        """Safely print text, handling Windows encoding and pipe issues.

        On Windows, print() can raise OSError [Errno 22] when output is
        piped or contains unsupported characters. This wrapper handles
        such cases gracefully.
        """
        try:
            print(text)
        except OSError as e:
            if e.errno == 22:
                logger.warning(
                    "Print failed with OSError [Errno 22], attempting "
                    "fallback encoding",
                )
                try:
                    sys.stdout.buffer.write(
                        text.encode("utf-8", errors="replace"),
                    )
                    sys.stdout.buffer.write(b"\n")
                    sys.stdout.buffer.flush()
                except Exception as fallback_err:
                    logger.error(
                        "Failed to print even with fallback: %s",
                        fallback_err,
                    )
            else:
                logger.error("Print failed with OSError: %s", e)

    def _print_parts(
        self,
        parts: List[OutgoingContentPart],
        ev_type: Optional[str] = None,
    ) -> None:
        """Print outgoing content parts to stdout."""
        ts = _ts()
        label = f" ({ev_type})" if ev_type else ""
        self._safe_print(
            f"\n{_GREEN}{_BOLD}🤖 [{ts}] Bot{label}{_RESET}",
        )
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                self._safe_print(f"{self.bot_prefix}{p.text}")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                self._safe_print(f"{_RED}⚠ Refusal: {p.refusal}{_RESET}")
            elif t == ContentType.IMAGE and getattr(p, "image_url", None):
                self._safe_print(f"{_YELLOW}🖼  [Image: {p.image_url}]{_RESET}")
            elif t == ContentType.VIDEO and getattr(p, "video_url", None):
                self._safe_print(f"{_YELLOW}🎬 [Video: {p.video_url}]{_RESET}")
            elif t == ContentType.AUDIO and getattr(p, "data", None):
                self._safe_print(f"{_YELLOW}🔊 [Audio]{_RESET}")
            elif t == ContentType.FILE:
                url = (
                    getattr(p, "file_url", None)
                    or getattr(p, "file_id", None)
                    or ""
                )
                self._safe_print(f"{_YELLOW}📎 [File: {url}]{_RESET}")
        self._safe_print("")

    def _get_free_model_alternatives(self) -> list:
        """Return a list of alternative free models."""
        try:
            from ...providers.provider_manager import (
                ProviderManager,
            )

            pm = ProviderManager.get_instance()
            if pm is None:
                return []
            alternatives = []
            all_providers = list(
                pm.builtin_providers.values(),
            ) + list(pm.custom_providers.values())
            for p in all_providers:
                meta = getattr(p, "meta", None) or {}
                if not meta.get("is_free_tier"):
                    continue
                for m in p.models:
                    if getattr(m, "is_free", False):
                        alternatives.append(
                            {
                                "provider_id": p.id,
                                "provider_name": p.name,
                                "model_id": m.id,
                                "model_name": m.name or m.id,
                            },
                        )
            return alternatives[:8]
        except Exception:
            return []

    def _print_error(self, err: str) -> None:
        ts = _ts()
        self._safe_print(
            f"\n{_RED}{_BOLD}❌ [{ts}] Error{_RESET}\n{_RED}{err}{_RESET}\n",
        )

    def _parts_to_text(
        self,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Merge parts to one body string (same logic as base send_content_parts).
        """
        text_parts: List[str] = []
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
        body = "\n".join(text_parts) if text_parts else ""
        prefix = (meta or {}).get("bot_prefix", self.bot_prefix) or ""
        if prefix and body:
            body = prefix + "  " + body
        return body

    # ── send (for proactive sends / cron) ───────────────────────────

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a text message — prints to stdout and pushes to frontend."""
        if not self.enabled:
            return
        ts = _ts()
        prefix = (meta or {}).get("bot_prefix", self.bot_prefix) or ""
        self._safe_print(
            f"\n{_GREEN}{_BOLD}🤖 [{ts}] Bot → {to_handle}{_RESET}\n"
            f"{prefix}{text}\n",
        )
        sid = (meta or {}).get("session_id")
        if (
            sid
            and text.strip()
            and not (meta or {}).get("suppress_console_push")
        ):
            await push_store_append(sid, text.strip())

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send content parts — prints to stdout and pushes to frontend store.
        """
        self._print_parts(parts)
        sid = (meta or {}).get("session_id")
        if sid and not (meta or {}).get("suppress_console_push"):
            body = self._parts_to_text(parts, meta)
            if body.strip():
                await push_store_append(sid, body.strip())

    # ── lifecycle ───────────────────────────────────────────────────

    async def health_check(self) -> Dict[str, Any]:
        """Console channel is always healthy when enabled."""
        if not self.enabled:
            return {
                "channel": self.channel,
                "status": "disabled",
                "detail": "Console channel is disabled.",
            }
        return {
            "channel": self.channel,
            "status": "healthy",
            "detail": "Console channel is running.",
        }

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("console channel disabled")
            return
        logger.info("Console channel started")

    async def stop(self) -> None:
        if not self.enabled:
            return
        logger.info("console channel stopped")
