# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements,unused-argument
# pylint: disable=too-many-public-methods,unnecessary-pass
"""
Base Channel: normalize inbound turns and deliver canonical runtime events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC
from pathlib import Path
from typing import (
    Optional,
    Dict,
    Any,
    List,
    Union,
    AsyncIterator,
    AsyncGenerator,
    Callable,
    TYPE_CHECKING,
)

from qwenpaw.schemas import (
    RunStatus,
    ContentType,
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    RefusalContent,
    MessageType,
)

from .renderer import ChannelDisplayConfig, MessageRenderer, RenderStyle
from .schema import ChannelType
from .access_control import get_access_control_store
from ...config.utils import load_config
from ...domain.channels.models import ReplyTarget
from ...domain.channels.ports import ReplyEventType
from .reply_delivery import ChannelReplyDelivery
from .event_projector import ChannelEventProjector
from .turn import ChannelTurn

# Optional callback to enqueue payload (set by manager)
EnqueueCallback = Optional[Callable[[Any], None]]

# Called when a user-originated reply was sent (channel, user_id, session_id)
OnReplySent = Optional[Callable[[str, str, str], None]]

logger = logging.getLogger(__name__)


_TOOL_OUTPUT_MESSAGE_TYPES = {
    MessageType.FUNCTION_CALL_OUTPUT,
    MessageType.PLUGIN_CALL_OUTPUT,
    MessageType.MCP_TOOL_CALL_OUTPUT,
}

if TYPE_CHECKING:
    from ...domain.turns.events import RuntimeEvent

# process: accepts TurnRequest and streams canonical RuntimeEvent objects.
ProcessHandler = Callable[[Any], AsyncIterator["RuntimeEvent"]]

# Outgoing part = runtime content types (no Dict[str, Any])
OutgoingContentPart = Union[
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    RefusalContent,
]


class BaseChannel(ABC):
    """Base for all channels. Queue lives in ChannelManager; channel defines
    how to consume via consume_one().
    """

    channel: ChannelType

    # If True, manager creates a queue and consumer loop for this channel.
    uses_manager_queue: bool = True

    @classmethod
    def doctor_connectivity_notes(
        cls,
        agent_id: str,
        config: Any,
        *,
        timeout: float,
    ) -> list[str]:
        """Optional ``copaw doctor --deep`` reachability checks.

        Override in custom channels. Default: no extra checks
        (built-in channels use shared probes in ``doctor_connectivity``
        unless this returns notes).

        Args:
            agent_id: Profile id from ``agents.profiles``.
            config: Channel subsection (Pydantic model or dict for extras).
            timeout: Seconds for TCP/HTTP probes.

        Returns:
            Informational lines (empty if OK / skipped).
        """
        return []

    # If True, streaming delta events (reasoning + message) are dispatched
    # to ``on_streaming_start`` / ``on_streaming_delta`` / ``on_streaming_end``
    # hooks *in addition to* the existing completed-message path.
    # Subclasses that support real-time text streaming should set this to True
    # (either as class attr or via __init__ / from_config).
    streaming_enabled: bool = False

    def __init__(
        self,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
        display_config: ChannelDisplayConfig | None = None,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        require_mention: bool = False,
        no_text_debounce: bool = True,
        streaming_enabled: bool = False,
        access_control_dm: bool = False,
        access_control_group: bool = False,
    ):
        self._process = process
        self._runtime_process = process
        self._on_reply_sent = on_reply_sent
        self._display_config = display_config or ChannelDisplayConfig()
        self._no_text_debounce = no_text_debounce
        self.streaming_enabled = streaming_enabled
        # Legacy fields — stored for backward compat but not used for
        # filtering (new ACL gate handles access control).
        self.dm_policy = dm_policy or "open"
        self.group_policy = group_policy or "open"
        self.allow_from = set(allow_from or [])
        self.deny_message = deny_message or ""
        self.require_mention = require_mention
        self.access_control_dm = access_control_dm
        self.access_control_group = access_control_group
        self._language = "zh"
        self._enqueue: EnqueueCallback = None
        self._workspace = None
        self._agent_id = "default"
        cfg = load_config()
        internal_tools = frozenset(
            name
            for name, tc in cfg.tools.builtin_tools.items()
            if not tc.display_to_user
        )
        self._render_style = RenderStyle(
            display_config=self._display_config,
            internal_tools=internal_tools,
        )
        self._renderer = MessageRenderer(self._render_style)
        self._http: Optional[Any] = None
        # Debounce: content from messages that had no text; merged when text
        # arrives. Key = session_id.
        self._pending_content_by_session: Dict[str, List[Any]] = {}
        # Time debounce: merge native payloads within _debounce_seconds.
        # Set > 0 in subclass (e.g. 0.3). Key = get_debounce_key(payload).
        self._debounce_seconds: float = 0.0
        self._debounce_pending: Dict[str, List[Any]] = {}
        self._debounce_timers: Dict[str, asyncio.Task[None]] = {}

    def channel_state_path(
        self,
        workspace_dir: Path,
        filename: str,
    ) -> Path:
        """Return compatible primary or isolated secondary state path."""
        identity = getattr(self, "_channel_identity", None)
        if identity is None or not hasattr(identity, "state_dir"):
            return workspace_dir / filename
        state_dir = identity.state_dir(workspace_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / filename

    def bind_identity(self, identity: Any) -> None:
        """Bind the stable instance identity assigned by the manager."""
        self._channel_identity = identity
        self._on_identity_bound()

    def _on_identity_bound(self) -> None:
        """Reload constructor-time state after an instance is assigned."""

    def runtime_session_id(self, platform_session_id: str) -> str:
        """Return the persisted session identity for this instance."""
        identity = getattr(self, "_channel_identity", None)
        if identity is None or not hasattr(identity, "runtime_session_id"):
            return platform_session_id
        return identity.runtime_session_id(platform_session_id)

    def platform_session_id(self, runtime_session_id: str) -> str:
        """Return the adapter-native session identity for this instance."""
        identity = getattr(self, "_channel_identity", None)
        if identity is None or not hasattr(identity, "platform_session_id"):
            return runtime_session_id
        return identity.platform_session_id(runtime_session_id)

    def on_runtime_bound(self) -> None:
        """Refresh workspace-dependent state after manager binding."""

    def _is_native_payload(self, payload: Any) -> bool:
        """True if payload is a native dict that can be time-debounced."""
        return isinstance(payload, dict) and "content_parts" in payload

    def get_debounce_key(self, payload: Any) -> str:
        """
        Key for time debounce (same key = same conversation).
        Delegates to ``resolve_session_id`` so every channel gets
        session-scoped isolation automatically.
        """
        if isinstance(payload, dict):
            sender_id = payload.get("sender_id") or ""
            meta = payload.get("meta") or {}
            return payload.get("session_id") or self.resolve_session_id(
                sender_id,
                meta,
            )
        return getattr(payload, "session_id", "") or ""

    def merge_native_items(self, items: List[Any]) -> Any:
        """
        Merge multiple native payloads into one. Override for
        channel-specific merge (e.g. meta keys). Default: concat
        content_parts, merge meta (reply_future, reply_loop, etc.).
        """
        if not items:
            return None
        first = items[0] if isinstance(items[0], dict) else {}
        merged_parts: List[Any] = []
        merged_meta: Dict[str, Any] = dict(first.get("meta") or {})
        for it in items:
            p = it if isinstance(it, dict) else {}
            merged_parts.extend(p.get("content_parts") or [])
            m = p.get("meta") or {}
            for k in (
                "reply_future",
                "reply_loop",
                "incoming_message",
                "conversation_id",
                "message_id",
            ):
                if k in m:
                    merged_meta[k] = m[k]
        return {
            "channel_id": first.get("channel_id") or self.channel,
            "sender_id": first.get("sender_id") or "",
            "acl_sender_id": first.get("acl_sender_id") or "",
            "content_parts": merged_parts,
            "meta": merged_meta,
        }

    def merge_requests(self, requests: List[Any]) -> Any:
        """
        Merge multiple ChannelTurn payloads (same session) into one.
        Used when manager drains same-session queue: concatenate
        messages[0].content from all, keep first turn's metadata/session.
        Returns one request; None if requests empty.
        """
        if not requests:
            return None
        first = requests[0]
        if len(requests) == 1:
            return first
        all_contents: List[Any] = []
        for req in requests:
            inp = getattr(req, "messages", None) or []
            if inp and hasattr(inp[0], "content"):
                all_contents.extend(getattr(inp[0], "content") or [])
        if not all_contents:
            return first
        msg = first.messages[0]
        if hasattr(msg, "model_copy"):
            new_msg = msg.model_copy(update={"content": all_contents})
        else:
            new_msg = msg
            setattr(new_msg, "content", all_contents)
        first.messages = [new_msg]
        return first

    def _on_debounce_buffer_append(
        self,
        key: str,
        payload: Any,
        existing_items: List[Any],
    ) -> None:
        """
        Hook when appending to time-debounce buffer (existing_items
        non-empty). Override e.g. to unblock previous reply_future.
        """
        del key
        del payload
        del existing_items

    def _content_has_text(self, contents: List[Any]) -> bool:
        """True if contents has at least one TEXT or REFUSAL with non-empty."""
        if not contents:
            return False
        for c in contents:
            t = getattr(c, "type", None)
            if t == ContentType.TEXT and (getattr(c, "text", None) or "").strip():
                return True
            if t == ContentType.REFUSAL and (getattr(c, "refusal", None) or "").strip():
                return True
        return False

    def _content_has_audio(self, contents: List[Any]) -> bool:
        """True if contents has at least one AUDIO block."""
        return any(
            getattr(c, "type", None) == ContentType.AUDIO for c in (contents or [])
        )

    def _apply_no_text_debounce(
        self,
        session_id: str,
        content_parts: List[Any],
    ) -> tuple[bool, List[Any]]:
        """
        Debounce: if content has no text, buffer and return (False, []).
        If has text, return (True, merged) with any buffered content prepended.
        Audio-only messages bypass debounce and are processed immediately
        (voice messages are standalone user input, not partial uploads).
        """
        if not self._no_text_debounce:
            pending = self._pending_content_by_session.pop(session_id, [])
            return (True, pending + list(content_parts))
        if not self._content_has_text(content_parts):
            if self._content_has_audio(content_parts):
                # Audio-only messages (e.g. voice messages) should be
                # processed immediately — they are complete user input.
                pending = self._pending_content_by_session.pop(
                    session_id,
                    [],
                )
                merged = pending + list(content_parts)
                return (True, merged)
            self._pending_content_by_session.setdefault(
                session_id,
                [],
            ).extend(content_parts)
            logger.debug(
                "channel debounce: no text, buffered session_id=%s",
                session_id[:24] if session_id else "",
            )
            return (False, [])
        pending = self._pending_content_by_session.pop(session_id, [])
        merged = pending + list(content_parts)
        return (True, merged)

    # ── Access-control i18n messages ───────────────────────────────────

    _ACL_I18N = {
        "blocked": {
            "zh": "您已被禁止访问此智能体。",
            "en": "You have been blocked from this agent.",
            "ja": "このエージェントへのアクセスがブロックされています。",
            "ru": "Вам заблокирован доступ к этому агенту.",
            "pt-BR": "Você foi bloqueado deste agente.",
            "id": "Anda telah diblokir dari agen ini.",
        },
        "pending": {
            "zh": "您目前没有访问此智能体的权限，需要审批。\n" "ID: {sender_id}",
            "en": "You do not have access to this agent. "
            "Approval required.\nID: {sender_id}",
            "ja": "このエージェントへのアクセス権がありません。"
            "承認が必要です。\nID: {sender_id}",
            "ru": "У вас нет доступа к этому агенту. "
            "Требуется одобрение.\nID: {sender_id}",
            "pt-BR": "Você não tem acesso a este agente. "
            "Aprovação necessária.\nID: {sender_id}",
            "id": "Anda tidak memiliki akses ke agen ini. "
            "Persetujuan diperlukan.\nID: {sender_id}",
        },
    }

    _ACL_LANG_FALLBACK = {"zh", "en", "ja", "ru", "pt-BR", "id"}

    def _acl_msg(self, key: str, **kwargs: str) -> str:
        """Return an access-control message in the agent's language."""
        lang = self._language
        if lang not in self._ACL_LANG_FALLBACK:
            lang = "zh" if lang.startswith("zh") else "en"
        template = self._ACL_I18N[key][lang]
        return template.format(**kwargs) if kwargs else template

    @property
    def access_control_enabled(self) -> bool:
        """True if access control is active for any chat type."""
        return self.access_control_dm or self.access_control_group

    async def _access_control_gate(self, payload: Any) -> bool:
        """Check access control. Returns True if blocked."""
        if not self.access_control_enabled:
            return False

        # Prefer acl_sender_id (real sender, unaffected by shared session)
        if isinstance(payload, dict):
            sender_id = payload.get("acl_sender_id") or payload.get("sender_id") or ""
            meta = dict(payload.get("meta") or {})
        else:
            state = dict(getattr(payload, "state", None) or {})
            sender_id = state.get("acl_sender_id") or getattr(
                payload,
                "sender_id",
                "",
            )
            meta = dict(getattr(payload, "metadata", None) or {})

        if not sender_id:
            return False

        # Skip if access control not enabled for this chat type
        is_group = meta.get("is_group", False)
        if is_group and not self.access_control_group:
            return False
        if not is_group and not self.access_control_dm:
            return False

        store = self._get_acl_store()
        channel_key = self.channel

        # ── Whitelist / blacklist / pending decision ────────────────────
        if store.is_whitelisted(channel_key, sender_id):
            return False  # allowed

        if store.is_blacklisted(channel_key, sender_id):
            deny_msg = self._acl_msg("blocked")
        else:
            first_message = self._extract_query_from_payload(payload)
            username = meta.get("user_name") or ""
            store.add_pending(
                channel_key,
                sender_id,
                first_message,
                username=username,
            )
            deny_msg = self._acl_msg("pending", sender_id=sender_id)

        # ── Send deny message back via the channel's own send() ─────────
        try:
            if isinstance(payload, dict):
                to_handle = sender_id
            else:
                to_handle = self.get_to_handle_from_turn(payload)
            await self.send_content_parts(
                to_handle,
                [TextContent(type=ContentType.TEXT, text=deny_msg)],
                meta,
            )
        except Exception:
            logger.debug(
                "%s access control: failed to send deny to %s",
                self.channel,
                sender_id[:20] if sender_id else "?",
            )

        logger.info(
            "%s access control blocked: sender=%s",
            self.channel,
            sender_id,
        )
        return True

    def _check_group_mention(
        self,
        is_group: bool,
        meta: dict,
    ) -> bool:
        """Return True if message should be processed under mention policy."""
        if not is_group or not self.require_mention:
            return True
        return bool(
            meta.get("bot_mentioned") or meta.get("has_bot_command"),
        )

    def _get_acl_store(self):
        """Get the AccessControlStore for this channel's workspace."""
        workspace_dir = None
        if self._workspace is not None:
            workspace_dir = Path(self._workspace.workspace_dir)
        return get_access_control_store(workspace_dir)

    def set_enqueue(self, cb: EnqueueCallback) -> None:
        """Set enqueue callback (called by ChannelManager)."""
        self._enqueue = cb

    def set_workspace(
        self,
        workspace,
        command_registry=None,
    ) -> None:
        """Set workspace reference for TaskTracker access.

        Args:
            workspace: Workspace instance with task_tracker and chat_manager
            command_registry: CommandRegistry for control command detection
        """
        self._workspace = workspace
        self._command_registry = command_registry
        runtime_process = getattr(workspace, "stream_channel_events", None)
        if callable(runtime_process):
            self._runtime_process = runtime_process

    def _extract_chat_name(self, payload: Any) -> str:
        """Extract chat name from payload for chat creation.

        Args:
            payload: Message payload (dict or ChannelTurn)

        Returns:
            Chat name (truncated to 50 chars)
        """
        try:
            if isinstance(payload, dict):
                parts = payload.get("content_parts", [])
                if parts:
                    first = parts[0]
                    if isinstance(first, dict):
                        text = first.get("text", "")
                    elif hasattr(first, "text"):
                        text = first.text
                    else:
                        text = str(first)
                    if text:
                        return text[:50]
                return "New Chat"
            if hasattr(payload, "messages") and payload.messages:
                msg = payload.messages[0]
                if hasattr(msg, "content") and msg.content:
                    content = msg.content[0]
                    if hasattr(content, "text"):
                        return content.text[:50]
            return "New Chat"
        except Exception as e:
            logger.warning(
                f"Failed to extract chat name from payload: {e}",
                exc_info=True,
            )
            return "New Chat"

    async def _consume_with_tracker(
        self,
        request: ChannelTurn,
        payload: Any,
    ) -> None:
        """Consume message with TaskTracker registration for cancellation.

        TaskTracker is used to track the running task so /stop can cancel it.
        Message serialization is ensured by UnifiedQueueManager which queues
        messages per (channel, session, priority).

        Args:
            request: ChannelTurn
            payload: Original payload
        """
        platform_session_id = getattr(request, "session_id", "") or ""
        session_id = self.runtime_session_id(platform_session_id)
        user_id = getattr(request, "sender_id", "") or ""
        channel_id = getattr(request, "channel_type", self.channel)
        identity = getattr(self, "_channel_identity", None)
        chat_meta = (
            {"channel_instance_id": identity.instance_id}
            if identity is not None and not identity.is_primary
            else None
        )

        chat = await self._workspace.chat_manager.get_or_create_chat(
            session_id,
            user_id,
            channel_id,
            name=self._extract_chat_name(payload),
            meta=chat_meta,
        )

        logger.info(
            f"_consume_with_tracker: chat_id={chat.id} " f"session={session_id[:30]}",
        )

        # Refresh updated_at so the session list surfaces this chat as the
        # latest activity (issue #6131). get_or_create_chat returns an
        # existing chat unchanged, so without this the timestamp stays stale.
        try:
            await self._workspace.chat_manager.touch_chat(chat.id)
        except Exception:  # pylint: disable=broad-except
            logger.debug(
                "failed to touch chat updated_at: chat_id=%s",
                chat.id,
                exc_info=True,
            )

        queue, is_new = await self._workspace.task_tracker.attach_or_start(
            chat.id,
            payload,
            self._stream_with_tracker,
            owner=self._workspace,
        )

        if is_new:
            try:
                async for _ in self._workspace.task_tracker.stream_from_queue(
                    queue,
                    chat.id,
                ):
                    pass
            except asyncio.CancelledError:
                logger.info(
                    f"Task cancelled: chat_id={chat.id} " f"session={session_id[:30]}",
                )
                raise
        else:
            logger.warning(
                f"Message ignored (task already running): "
                f"chat_id={chat.id} session={session_id[:30]}. "
                f"This should not happen with UnifiedQueueManager.",
            )

    _STREAMABLE_TYPES = {"reasoning", "message"}
    _STREAM_DELTA_MIN_INTERVAL_S: float = 0.0
    _STREAM_FLUSH_TIMEOUT_S: float = 5.0

    def _resolve_stream_type(self, event: Any) -> str:
        """Map event.type to a stream_type string.

        Returns ``"reasoning"`` or ``"message"`` for streamable text,
        or the raw type string (e.g. ``"plugin_call"``) otherwise.
        """
        msg_type = getattr(event, "type", None)
        if msg_type is None:
            return "message"
        type_str = msg_type.value if hasattr(msg_type, "value") else str(msg_type)
        return type_str

    async def _dispatch_streaming_event(
        self,
        request: "ChannelTurn",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        msg_id_to_stream_type: Dict[str, str],
        streaming_buffers: Dict[str, str],
    ) -> bool:
        """Dispatch streaming hooks for reasoning / message events.

        Returns *True* if the event was consumed by the streaming
        path (so the caller should skip ``on_event_message_completed``).
        Non-streamable types (e.g. ``plugin_call``) return *False*,
        falling through to the normal non-streaming path.
        """
        obj = getattr(event, "object", None)
        status = getattr(event, "status", None)

        if obj == "message" and status == RunStatus.InProgress:
            return await self._on_stream_msg_start(
                request,
                to_handle,
                event,
                send_meta,
                msg_id_to_stream_type,
                streaming_buffers,
            )
        if obj == "content":
            return await self._on_stream_content_delta(
                request,
                to_handle,
                event,
                send_meta,
                msg_id_to_stream_type,
                streaming_buffers,
            )
        if obj == "message" and status == RunStatus.Completed:
            return await self._on_stream_msg_end(
                request,
                to_handle,
                event,
                send_meta,
                msg_id_to_stream_type,
                streaming_buffers,
            )
        return False

    async def _on_stream_msg_start(
        self,
        request: "ChannelTurn",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        msg_id_to_stream_type: Dict[str, str],
        streaming_buffers: Dict[str, str],
    ) -> bool:
        stream_type = self._resolve_stream_type(event)
        if stream_type not in self._STREAMABLE_TYPES:
            return False
        msg_id = getattr(event, "id", None)
        if msg_id:
            msg_id_to_stream_type[msg_id] = stream_type
        if stream_type == "reasoning" and not self._display_config.show_thinking:
            return True
        streaming_buffers[stream_type] = ""
        await self.on_streaming_start(
            request,
            to_handle,
            event,
            send_meta,
            stream_type,
            accumulated_text="",
        )
        return True

    async def _on_stream_content_delta(
        self,
        request: "ChannelTurn",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        msg_id_to_stream_type: Dict[str, str],
        streaming_buffers: Dict[str, str],
    ) -> bool:
        if not getattr(event, "delta", False):
            return False
        content_msg_id = getattr(event, "msg_id", None) or ""
        stream_type = msg_id_to_stream_type.get(
            content_msg_id,
            "",
        )
        if (
            not stream_type
            or stream_type not in self._STREAMABLE_TYPES
            or stream_type not in streaming_buffers
        ):
            return False
        if stream_type == "reasoning" and not self._display_config.show_thinking:
            return True

        # Detect content index change → split into a new streaming box
        content_index = getattr(event, "index", 0) or 0
        index_key = f"_stream_last_index_{stream_type}"
        last_index = send_meta.get(index_key, 0)
        if content_index != last_index and streaming_buffers.get(
            stream_type,
            "",
        ):
            # Finalize current streaming box before starting a new one
            flush_meta = self._get_stream_flush_meta(
                send_meta,
                stream_type,
            )
            task = flush_meta.get("task")
            if task and not task.done():
                try:
                    await asyncio.wait_for(
                        task,
                        timeout=self._STREAM_FLUSH_TIMEOUT_S,
                    )
                except (
                    asyncio.TimeoutError,
                    asyncio.CancelledError,
                    Exception,
                ):
                    task.cancel()
            send_meta.get("_stream_flush", {}).pop(
                stream_type,
                None,
            )
            accumulated = streaming_buffers.pop(stream_type, "")
            await self.on_streaming_end(
                request,
                to_handle,
                event,
                send_meta,
                stream_type,
                accumulated_text=accumulated,
            )
            # Start a new streaming box
            streaming_buffers[stream_type] = ""
            await self.on_streaming_start(
                request,
                to_handle,
                event,
                send_meta,
                stream_type,
                accumulated_text="",
            )
        send_meta[index_key] = content_index

        delta_text = getattr(event, "text", "") or ""
        streaming_buffers[stream_type] = (
            streaming_buffers.get(stream_type, "") + delta_text
        )

        # --- Non-blocking flush with in-flight guard ---
        flush_meta = self._get_stream_flush_meta(send_meta, stream_type)
        now = time.monotonic()

        # Guard 1: previous flush still in-flight
        task = flush_meta.get("task")
        if task and not task.done():
            elapsed = now - flush_meta.get("last_ts", 0.0)
            if elapsed > self._STREAM_FLUSH_TIMEOUT_S:
                task.cancel()
            return True

        # Guard 2: minimum interval not elapsed
        if self._STREAM_DELTA_MIN_INTERVAL_S > 0:
            if now - flush_meta.get("last_ts", 0.0) < self._STREAM_DELTA_MIN_INTERVAL_S:
                return True

        # Fire-and-forget flush
        flush_meta["last_ts"] = now
        from qwenpaw.agents.context.scroll.serialize import strip_headline

        display_text = strip_headline(streaming_buffers[stream_type]) or ""
        flush_meta["task"] = asyncio.create_task(
            self._safe_streaming_delta(
                request,
                to_handle,
                event,
                send_meta,
                stream_type,
                display_text,
            ),
        )
        return True

    async def _on_stream_msg_end(
        self,
        request: "ChannelTurn",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        msg_id_to_stream_type: Dict[str, str],
        streaming_buffers: Dict[str, str],
    ) -> bool:
        stream_type = self._resolve_stream_type(event)
        msg_id = getattr(event, "id", None)
        if msg_id:
            msg_id_to_stream_type.pop(msg_id, None)
        if stream_type not in self._STREAMABLE_TYPES:
            return False
        if stream_type in streaming_buffers:
            if stream_type == "reasoning" and not self._display_config.show_thinking:
                streaming_buffers.pop(stream_type, None)
                return True

            # Await pending flush to ensure ordering before finalize
            flush_meta = self._get_stream_flush_meta(
                send_meta,
                stream_type,
            )
            task = flush_meta.get("task")
            if task and not task.done():
                try:
                    await asyncio.wait_for(
                        task,
                        timeout=self._STREAM_FLUSH_TIMEOUT_S,
                    )
                except (
                    asyncio.TimeoutError,
                    asyncio.CancelledError,
                    Exception,
                ):
                    task.cancel()
            # Clean up flush state
            send_meta.get("_stream_flush", {}).pop(
                stream_type,
                None,
            )

            buf = streaming_buffers.pop(stream_type, "")
            accumulated = self._extract_text_from_event(event) or buf
            from qwenpaw.agents.context.scroll.serialize import strip_headline

            accumulated = strip_headline(accumulated) or ""
            await self.on_streaming_end(
                request,
                to_handle,
                event,
                send_meta,
                stream_type,
                accumulated_text=accumulated,
            )
        return True

    @staticmethod
    def _extract_text_from_event(event: Any) -> str:
        """Extract concatenated text from event.content list."""
        content = getattr(event, "content", None)
        if not content or not isinstance(content, list):
            return ""
        parts = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)

    async def _stream_with_tracker(
        self,
        payload: Any,
    ) -> AsyncGenerator[Any, None]:
        """Run one Channel turn while publishing canonical task events.

        When ``streaming_enabled``, streaming hooks are invoked for
        reasoning / message events alongside the normal path.
        """
        request = self._payload_to_turn(payload)

        if isinstance(payload, dict):
            send_meta = dict(payload.get("meta") or {})
            if payload.get("session_webhook"):
                send_meta["session_webhook"] = payload["session_webhook"]
        else:
            send_meta = getattr(request, "metadata", None) or {}

        bot_prefix = getattr(self, "bot_prefix", None) or getattr(
            self,
            "_bot_prefix",
            "",
        )
        if bot_prefix and "bot_prefix" not in send_meta:
            send_meta = {**send_meta, "bot_prefix": bot_prefix}

        to_handle = self.get_to_handle_from_turn(request)
        session_id = getattr(request, "session_id", "") or ""
        self._clear_session_turn_usage(session_id)

        await self._before_consume_process(request)

        last_response = None
        process_iterator = None
        msg_id_to_stream_type: Dict[str, str] = {}
        streaming_buffers: Dict[str, str] = {}
        process_request = self._build_turn_request(request)
        adapter, delivery = self._create_reply_delivery(
            request,
            process_request,
            to_handle,
            send_meta,
        )
        try:
            process_iterator = self._runtime_process(process_request)
            async for runtime_event in process_iterator:
                yield runtime_event
                for reply in adapter.project(runtime_event):
                    event = reply.payload

                    # --- streaming path ---
                    handled_by_streaming = False
                    if self.streaming_enabled:
                        handled_by_streaming = await self._dispatch_streaming_event(
                            request,
                            to_handle,
                            event,
                            send_meta,
                            msg_id_to_stream_type,
                            streaming_buffers,
                        )

                    if not (
                        handled_by_streaming and reply.type == ReplyEventType.MESSAGE
                    ):
                        await delivery.deliver(reply)

            last_response = delivery.last_response
            err_msg = self._get_response_error_message(last_response)
            if err_msg:
                self._clear_session_turn_usage(session_id)
                await self._on_consume_error(
                    request,
                    to_handle,
                    f"Error: {err_msg}",
                )
            else:
                await self._on_process_completed(
                    request,
                    to_handle,
                    send_meta,
                )
                await self._commit_turn_usage(
                    request,
                    session_id,
                    emit_sse=False,
                )

            if self._on_reply_sent:
                args = self.get_on_reply_sent_args(request, to_handle)
                self._on_reply_sent(
                    self.channel,
                    *args,
                )

        except asyncio.CancelledError:
            logger.info(
                f"channel task cancelled: "
                f"session={getattr(request, 'session_id', '')[:30]}",
            )
            self._clear_session_turn_usage(session_id)
            if process_iterator is not None:
                await process_iterator.aclose()
            raise

        except Exception as e:
            logger.exception(
                f"channel _stream_with_tracker failed: {e}, "
                f"session={getattr(request, 'session_id', 'N/A')[:30]}, "
                f"agent={to_handle}",
            )
            self._clear_session_turn_usage(session_id)
            await self._on_consume_error(
                request,
                to_handle,
                "Internal error",
            )
            raise
        finally:
            await self._finish_response_cycle(session_id)

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "BaseChannel":
        raise NotImplementedError

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Any,
        on_reply_sent: OnReplySent = None,
        display_config: ChannelDisplayConfig | None = None,
        no_text_debounce: bool = True,
    ) -> "BaseChannel":
        raise NotImplementedError

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Map sender and optional channel meta to session_id.
        Override in subclasses for channel-specific session keys
        (e.g. short suffix of conversation_id for cron lookup).
        """
        return f"{self.channel}:{sender_id}"

    def build_channel_turn_from_user_content(
        self,
        channel_id: str,
        sender_id: str,
        session_id: str,
        content_parts: List[Any],
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> ChannelTurn:
        """
        Build ChannelTurn from runtime content parts (Message content list).
        Uses :mod:`qwenpaw.schemas` Message / Content types directly — no
        intermediate envelope. Subclasses call this after parsing the
        native payload into ``content_parts``.
        """
        from qwenpaw.schemas import Message, Role

        if not content_parts:
            content_parts = [
                TextContent(type=ContentType.TEXT, text=" "),
            ]
        msg = Message(
            type=MessageType.MESSAGE,
            role=Role.USER,
            content=content_parts,
        )
        return ChannelTurn(
            session_id=session_id,
            sender_id=sender_id,
            messages=[msg],
            channel_type=channel_id,
            metadata=dict(channel_meta or {}),
        )

    def build_channel_turn_from_native(
        self,
        native_payload: Any,
    ) -> ChannelTurn:
        """
        Convert channel-native message payload to ChannelTurn.
        Subclasses must implement: parse native -> content_parts (runtime
        Content types), session_id, then build_channel_turn_from_user_content.
        Attach channel_meta to result for send path:
        request.metadata = meta.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement "
            "build_channel_turn_from_native(native_payload)",
        )

    def _payload_to_turn(self, payload: Any) -> "ChannelTurn":
        """
        Convert queue payload to ChannelTurn. Default: if payload looks like
        ChannelTurn (has session_id, input), return it; else
        build_channel_turn_from_native(payload). Override if needed.
        """
        if payload is None:
            raise ValueError("payload is None")
        if isinstance(payload, ChannelTurn):
            return payload
        return self.build_channel_turn_from_native(payload)

    def bind_route(self, agent_id: str) -> None:
        """Bind the Agent that owns this Channel instance."""
        self._agent_id = agent_id

    def _build_turn_request(self, request: ChannelTurn) -> Any:
        """Route normalized Channel input into the runtime core."""
        identity = getattr(self, "_channel_identity", None)
        instance_id = getattr(identity, "instance_id", self.channel)
        return request.to_request(
            agent_id=self._agent_id,
            instance_id=instance_id,
            runtime_session_id=self.runtime_session_id(request.session_id),
            channel_instance=self,
        )

    def get_to_handle_from_turn(self, request: "ChannelTurn") -> str:
        """
        Resolve send target (to_handle) from ChannelTurn. Default: user_id.
        Override for channels that send by session_id (e.g. Feishu).
        """
        return getattr(request, "sender_id", "") or ""

    def get_on_reply_sent_args(
        self,
        request: "ChannelTurn",
        to_handle: str,
    ) -> tuple:
        """
        Args for _on_reply_sent(channel, *args). Default: (to_handle,
        session_id). Override e.g. to pass (user_id, session_id).
        """
        session_id = getattr(request, "session_id", "") or f"{self.channel}:{to_handle}"
        return (to_handle, session_id)

    async def refresh_webhook_or_token(self) -> None:
        """
        Optional: refresh webhook URL or API token. Override for channels
        that need periodic or on-401 refresh. Default no-op.
        """

    async def consume_one(self, payload: Any) -> None:
        """
        Process one payload from the manager-owned queue. If
        _debounce_seconds > 0 and payload is native (dict with
        content_parts), append to buffer and flush after delay;
        otherwise call _consume_one_request(payload). Messages
        with no text are buffered until text arrives (see
        _apply_no_text_debounce). Override only when you need
        a different flow (e.g. print).
        """
        if self._debounce_seconds > 0 and self._is_native_payload(payload):
            key = self.get_debounce_key(payload)
            if key in self._debounce_pending and self._debounce_pending[key]:
                self._on_debounce_buffer_append(
                    key,
                    payload,
                    self._debounce_pending[key],
                )
            self._debounce_pending.setdefault(key, []).append(payload)
            old = self._debounce_timers.pop(key, None)
            if old and not old.done():
                old.cancel()

            async def flush(k: str) -> None:
                await asyncio.sleep(self._debounce_seconds)
                items = self._debounce_pending.pop(k, [])
                self._debounce_timers.pop(k, None)
                if not items:
                    return
                merged = self.merge_native_items(items)
                if not merged:
                    return
                await self._consume_one_request(merged)

            self._debounce_timers[key] = asyncio.create_task(flush(key))
            return
        await self._consume_one_request(payload)

    def _extract_query_from_payload(self, payload: Any) -> str:
        """Extract query text from payload for command detection.

        Args:
            payload: Native dict or ChannelTurn

        Returns:
            Query text string (empty if not found)
        """
        if isinstance(payload, dict):
            parts = payload.get("content_parts") or []
            for part in parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    return part.get("text") or ""
                if hasattr(part, "type") and part.type == "text":
                    return getattr(part, "text", "") or ""
            return ""
        if hasattr(payload, "messages"):
            inp = payload.messages or []
            if inp and hasattr(inp[0], "content"):
                content = inp[0].content or []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            return part.get("text") or ""
                    elif hasattr(part, "type") and part.type == "text":
                        return getattr(part, "text", "") or ""
        return ""

    def _debounce_payload(self, payload: Any) -> bool:
        """Apply no-text debounce on payload; return False if buffered."""
        if isinstance(payload, dict):
            content_parts = payload.get("content_parts") or []
        elif hasattr(payload, "messages") and payload.messages:
            content_parts = getattr(payload.messages[0], "content", None) or []
        else:
            return True

        if not content_parts:
            return True

        session_id = self.get_debounce_key(payload)
        should_process, merged = self._apply_no_text_debounce(
            session_id,
            content_parts,
        )
        if not should_process:
            return False

        # Write merged parts back so downstream paths see full content.
        if isinstance(payload, dict):
            payload["content_parts"] = merged
        elif hasattr(payload, "messages") and payload.messages:
            first = payload.messages[0]
            if hasattr(first, "model_copy"):
                payload.messages = [
                    first.model_copy(
                        update={"content": merged},
                    )
                ]
            elif hasattr(first, "content"):
                first.content = merged
        return True

    async def _consume_one_request(self, payload: Any) -> None:
        """
        Convert payload to request, apply no-text debounce, run _process,
        send messages, handle errors and on_reply_sent. Used by
        consume_one (direct or after time-debounce flush).

        If workspace is available, routes through TaskTracker for tracking.
        Control commands bypass TaskTracker for immediate response.
        """
        logger.debug(
            "base _consume_one_request: "
            f"has_workspace={self._workspace is not None}",
        )

        if not self._debounce_payload(payload):
            return

        # ── Unified access control gate ─────────────────────────────────
        if await self._access_control_gate(payload):
            return

        if self._workspace is not None and self._command_registry is not None:
            query_text = self._extract_query_from_payload(payload)
            logger.debug(
                f"base _consume_one_request: query={query_text[:50]}",
            )
            is_control = self._command_registry.is_control_command(
                query_text,
            )
            logger.debug(
                f"base _consume_one_request: is_control={is_control}",
            )
            if not is_control:
                request = self._payload_to_turn(payload)
                await self._consume_with_tracker(request, payload)
                return

        request = self._payload_to_turn(payload)
        # Build meta from payload so session_webhook is never lost when
        # request has no channel_meta (e.g. ChannelTurn schema has no field).
        if isinstance(payload, dict):
            meta_from_payload = dict(payload.get("meta") or {})
            if payload.get("session_webhook"):
                meta_from_payload["session_webhook"] = payload["session_webhook"]
            # Always attach so channel _before_consume_process can use it
            # (e.g. Feishu save receive_id for cron send).
            request.metadata = meta_from_payload
        to_handle = self.get_to_handle_from_turn(request)
        await self._before_consume_process(request)
        # Prefer meta built from payload so session_webhook is present when
        # request.metadata is missing (ChannelTurn may not have the attr).
        if isinstance(payload, dict):
            send_meta = dict(payload.get("meta") or {})
            if payload.get("session_webhook"):
                send_meta["session_webhook"] = payload["session_webhook"]
        else:
            send_meta = getattr(request, "metadata", None) or {}
        bot_prefix = getattr(self, "bot_prefix", None) or getattr(
            self,
            "_bot_prefix",
            "",
        )
        if bot_prefix and "bot_prefix" not in send_meta:
            send_meta = {**send_meta, "bot_prefix": bot_prefix}
        logger.info(
            "base _consume_one_request: send_meta has_session_webhook=%s",
            bool((send_meta or {}).get("session_webhook")),
        )
        await self._run_process_loop(request, to_handle, send_meta)

    async def _run_process_loop(
        self,
        request: "ChannelTurn",
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """
        Run _process and send events. Override to use channel-specific
        loop (e.g. DingTalk _process_one_request with webhook sends).
        """
        session_id = getattr(request, "session_id", "") or ""
        self._clear_session_turn_usage(session_id)
        process_request = self._build_turn_request(request)
        adapter, delivery = self._create_reply_delivery(
            request,
            process_request,
            to_handle,
            send_meta,
        )
        try:
            async for event in self._runtime_process(process_request):
                for reply in adapter.project(event):
                    await delivery.deliver(reply)
            err_msg = self._get_response_error_message(
                delivery.last_response,
            )
            if err_msg:
                self._clear_session_turn_usage(session_id)
                await self._on_consume_error(
                    request,
                    to_handle,
                    f"Error: {err_msg}",
                )
            else:
                await self._on_process_completed(
                    request,
                    to_handle,
                    send_meta,
                )
                await self._commit_turn_usage(
                    request,
                    session_id,
                    emit_sse=False,
                )
            if self._on_reply_sent:
                args = self.get_on_reply_sent_args(request, to_handle)
                self._on_reply_sent(
                    self.channel,
                    *args,
                )
        except asyncio.CancelledError:
            logger.info(
                "channel task cancelled: session=%s",
                getattr(request, "session_id", "")[:30],
            )
            self._clear_session_turn_usage(session_id)
            raise
        except Exception:
            logger.exception("channel consume_one failed")
            self._clear_session_turn_usage(session_id)
            await self._on_consume_error(
                request,
                to_handle,
                "An error occurred while processing your request.",
            )
        finally:
            await self._finish_response_cycle(session_id)

    def _create_reply_delivery(
        self,
        request: "ChannelTurn",
        process_request: Any,
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> tuple[ChannelEventProjector, ChannelReplyDelivery]:
        """Create the Channel presenter and platform delivery port."""
        session_id = getattr(request, "session_id", "") or ""
        target = getattr(process_request, "reply_target", None)
        if not isinstance(target, ReplyTarget):
            target = ReplyTarget(
                channel_type=self.channel,
                conversation_id=to_handle or session_id,
                metadata=send_meta,
            )
        turn_id = str(
            getattr(process_request, "turn_id", "") or session_id,
        )
        adapter = ChannelEventProjector(target)
        delivery = ChannelReplyDelivery(
            channel=self,
            request=request,
            to_handle=to_handle,
            send_meta=send_meta,
        )
        return adapter, delivery

    def _get_response_error_message(self, last_response: Any) -> Optional[str]:
        """Extract an error message from a canonical runtime failure."""
        if not last_response:
            return None
        error_text = getattr(last_response, "error_text", None)
        if error_text:
            return str(error_text)
        resp = last_response
        if getattr(last_response, "data", None) is not None:
            resp = last_response.data
        elif getattr(last_response, "response", None) is not None:
            resp = last_response.response
        err = getattr(resp, "error", None)
        if not err:
            return None
        if hasattr(err, "message"):
            return getattr(err, "message", None) or str(err)
        if isinstance(err, dict):
            return err.get("message") or str(err)
        return str(err)

    async def _before_consume_process(self, request: "ChannelTurn") -> None:
        """
        Hook called once per consume_one before running _process. Override
        to e.g. save receive_id for send path (Feishu).
        """

    async def on_event_content(
        self,
        request: "ChannelTurn",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
    ) -> bool:
        """Hook: one content event. Return True if handled."""
        del request
        if getattr(event, "type", None) != ContentType.DATA:
            return False
        status = getattr(event, "status", None)
        if status != RunStatus.InProgress:
            return False
        if not self._display_config.show_tool_results:
            return False
        data = getattr(event, "data", None) or {}
        if not isinstance(data, dict) or "output" not in data:
            return False
        body = self._format_stream_tool_output_body(event)
        if not body:
            return False
        await self.send_content_parts(
            to_handle,
            [TextContent(text=body)],
            send_meta,
        )
        return True

    # ------------------------------------------------------------------
    # Streaming hooks — override in subclasses
    # ------------------------------------------------------------------

    def _get_stream_flush_meta(
        self,
        send_meta: Dict[str, Any],
        stream_type: str,
    ) -> Dict[str, Any]:
        """Return per-stream_type flush state dict from *send_meta*."""
        key = "_stream_flush"
        if key not in send_meta:
            send_meta[key] = {}
        if stream_type not in send_meta[key]:
            send_meta[key][stream_type] = {
                "task": None,
                "last_ts": 0.0,
            }
        return send_meta[key][stream_type]

    async def _safe_streaming_delta(
        self,
        request: "ChannelTurn",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str,
    ) -> None:
        """Wrapper that invokes on_streaming_delta and catches errors."""
        try:
            await self.on_streaming_delta(
                request,
                to_handle,
                event,
                send_meta,
                stream_type,
                accumulated_text=accumulated_text,
            )
        except Exception:
            logger.warning("streaming delta failed", exc_info=True)
            flush_meta = self._get_stream_flush_meta(
                send_meta,
                stream_type,
            )
            flush_meta["last_ts"] = 0.0

    async def on_streaming_start(
        self,
        request: "ChannelTurn",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Called when a new streaming segment begins.

        *stream_type* is ``"reasoning"`` or ``"message"``.
        ``accumulated_text`` is always ``""`` at this point.
        """

    async def on_streaming_delta(
        self,
        request: "ChannelTurn",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Called for each incremental text chunk.

        ``accumulated_text`` contains all text received so far
        for this *stream_type*, including the current delta.
        Useful for channels that overwrite the message bubble
        with full text on each update (e.g. WeCom).
        """

    async def on_streaming_end(
        self,
        request: "ChannelTurn",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Called when a streaming segment completes.

        ``accumulated_text`` is the final full text for this
        *stream_type*.
        """

    async def on_event_message_completed(
        self,
        request: "ChannelTurn",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
    ) -> None:
        """
        Hook: one message event completed. Default: send_message_content.
        Override for batch/debounce (e.g. DingTalk merge then send).
        """
        await self.send_message_content(to_handle, event, send_meta)

    async def on_event_response(
        self,
        request: "ChannelTurn",
        event: Any,
    ) -> None:
        """Hook: response event received. Default: no-op."""

    async def _on_process_completed(
        self,
        request: "ChannelTurn",
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Hook called after all events processed without error.

        Override for post-processing (e.g. Feishu DONE reaction).
        """

    async def _finish_response_cycle(self, session_id: str) -> None:
        """Run best-effort browser cleanup after one channel response cycle."""
        if not session_id or self._workspace is None:
            return
        workspace_dir = getattr(self._workspace, "workspace_dir", None)
        if workspace_dir is None:
            return
        try:
            from ...browser.execution.kernel import get_default_kernel_manager
            from ...browser.tool_entrypoint import derive_workspace_id

            await get_default_kernel_manager().on_response_cycle_end(
                derive_workspace_id(Path(workspace_dir)),
                session_id,
            )
        # Intentional boundary: provider cleanup cannot fail a channel reply.
        except Exception:
            logger.warning(
                "browser response-cycle cleanup failed for session=%s",
                session_id[:30],
                exc_info=True,
            )

    @staticmethod
    def _clear_session_turn_usage(session_id: str) -> None:
        """Drop any staged per-session usage (turn start / cancel / error)."""
        if not session_id:
            return
        import importlib

        mod = importlib.import_module("qwenpaw.token_usage.model_wrapper")
        mod.TokenRecordingModelWrapper.pop_usage_for_session(session_id)

    async def _commit_turn_usage(
        self,
        request: "ChannelTurn",
        session_id: str,
        *,
        emit_sse: bool = True,
    ) -> List[str]:
        """Resolve, persist, and optionally emit a ``turn_usage`` SSE."""
        if not session_id:
            return []
        try:
            import importlib

            turn_usage = importlib.import_module(
                "qwenpaw.token_usage.turn_usage",
            )
            token_usage = importlib.import_module("qwenpaw.token_usage")

            workspace = self._workspace
            session = (
                getattr(workspace, "session", None) if workspace is not None else None
            )
            agent_id = (
                getattr(workspace, "agent_id", "default")
                if workspace is not None
                else "default"
            )
            user_id = getattr(request, "sender_id", "") or ""
            channel = getattr(request, "channel_type", "") or self.channel
            turn, ctx, agent_state = await turn_usage.resolve_turn_usage(
                session_id=session_id,
                agent_id=agent_id,
                session=session,
                user_id=user_id,
                channel=channel,
            )
            if turn is None and ctx is None:
                return []
            self._on_turn_usage_ready(turn, ctx)
            if turn:
                logger.info("Usage for session %s: %s", session_id, turn)
            if session is not None:
                try:
                    await token_usage.persist_turn_usage(
                        session=session,
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        turn=turn,
                        ctx=ctx,
                        agent_state=agent_state,
                    )
                except Exception:
                    logger.warning(
                        "turn usage persist skipped",
                        exc_info=True,
                    )
            if not emit_sse:
                return []
            payload: Dict[str, Any] = {
                "type": "turn_usage",
                "session_id": session_id,
                "usage": turn,
                "context_usage": ctx,
            }
            return [
                f"data: {json.dumps(payload, ensure_ascii=False)}\n\n",
            ]
        except Exception:
            logger.warning("turn usage commit skipped", exc_info=True)
            return []

    def _on_turn_usage_ready(
        self,
        turn: Optional[Dict[str, Any]],
        ctx: Optional[Dict[str, Any]],
    ) -> None:
        """Hook: channel-specific side effect once per-turn usage is staged
        (e.g. console prints a terminal status line). Default: no-op.
        """

    async def _on_consume_error(
        self,
        request: Any,
        to_handle: str,
        err_text: str,
    ) -> None:
        """
        Called when consume_one hits an error or response.error. Default:
        send err_text via send_content_parts. Override to send via channel
        API (e.g. imessage _send_sync).
        """
        await self.send_content_parts(
            to_handle,
            [TextContent(type=ContentType.TEXT, text=err_text)],
            getattr(request, "metadata", None) or {},
        )

    def _message_to_content_parts(
        self,
        message: Any,
    ) -> List[OutgoingContentPart]:
        """
        Convert a Message (object=='message') into sendable parts.
        Delegates to self._renderer; override _renderer or _render_style
        for channel-specific formatting.
        """
        return self._renderer.message_to_parts(message)

    async def send_message_content(
        self,
        to_handle: str,
        message: Any,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send all content of a Message
        (text, image, video, audio, file, refusal).
        Subclasses may override send_content_parts for channel-specific
        multi-part sending.
        """
        parts = self._message_to_content_parts(message)
        if not parts:
            logger.debug(
                f"channel send_message_content: no parts for to_handle="
                f"{to_handle}, skip send",
            )
            return
        logger.debug(
            f"channel send_message_content: to_handle={to_handle} "
            f"parts_count={len(parts)} "
            f"part_types={[getattr(p, 'type', None) for p in parts]}",
        )
        await self.send_content_parts(to_handle, parts, meta)

    def _truncate_stream_tool_chunk(
        self,
        text: Any,
        limit: int = 72,
    ) -> str:
        preview = " ".join(str(text or "").split()).strip()
        if len(preview) > limit:
            return preview[:limit] + "..."
        return preview

    def _format_stream_tool_output_body(
        self,
        event: Any,
    ) -> Optional[str]:
        data = getattr(event, "data", None) or {}
        if not isinstance(data, dict):
            return None
        output = data.get("output")
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError:
                return None
        if not isinstance(output, list):
            return None

        tool_name = data.get("name") or "tool"
        chunks: List[str] = []
        seen_chunks: set[str] = set()
        for block in output:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            raw_text = ""
            if block_type == "text":
                raw_text = str(block.get("text") or "")
            elif block_type == "thinking":
                raw_text = str(block.get("thinking") or "")
            if not raw_text.strip():
                continue
            preview = self._truncate_stream_tool_chunk(raw_text)
            if not preview or preview in seen_chunks:
                continue
            seen_chunks.add(preview)
            chunks.append(preview)
        if not chunks:
            return None
        return f"⌛️ **{tool_name}**:\n" + "\n".join(f"`{text}`" for text in chunks)

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send a list of content parts.
        Default: merge text/refusal into one text, append media URLs as
        fallback, send one message; optionally call send_media for each
        media part if overridden.
        """
        text_parts: List[str] = []
        media_parts: List[OutgoingContentPart] = []
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
            elif t in (
                ContentType.IMAGE,
                ContentType.VIDEO,
                ContentType.AUDIO,
                ContentType.FILE,
            ):
                media_parts.append(p)
        body = "\n".join(text_parts) if text_parts else ""
        prefix = (meta or {}).get("bot_prefix", "") or ""
        if prefix and body:
            body = prefix + "  " + body
        for m in media_parts:
            t = getattr(m, "type", None)
            if t == ContentType.IMAGE and getattr(m, "image_url", None):
                body += f"\n[Image: {m.image_url}]"
            elif t == ContentType.VIDEO and getattr(m, "video_url", None):
                body += f"\n[Video: {m.video_url}]"
            elif t == ContentType.FILE and (
                getattr(m, "file_url", None) or getattr(m, "file_id", None)
            ):
                body += f"\n[File: {m.file_url or m.file_id}]"
            elif t == ContentType.AUDIO and getattr(m, "data", None):
                body += "\n[Audio]"
        if body.strip():
            logger.debug(
                f"channel send_content_parts: to_handle={to_handle} "
                f"body_len={len(body)} preview="
                f"{body[:120] + '...' if len(body) > 120 else body}",
            )
            await self.send(to_handle, body.strip(), meta)
        for m in media_parts:
            await self.send_media(to_handle, m, meta)

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send a single media part (image, video, audio, file).
        Default: no-op (already appended to text in send_content_parts).
        Subclasses override to send real attachments.
        """
        pass

    def clone(self, config) -> "BaseChannel":
        """Clone a new channel instance with updated config, cloning
        process and on_reply_sent from self.

        Subclasses must implement from_config(process, config, on_reply_sent).

        Global tool detail visibility is preserved while per-channel display
        settings are reloaded from the new configuration.
        """
        return self.__class__.from_config(
            process=self._process,
            config=config,
            on_reply_sent=self._on_reply_sent,
            display_config=ChannelDisplayConfig.from_config(
                config,
                show_tool_details=self._display_config.show_tool_details,
            ),
        )

    async def health_check(self) -> Dict[str, Any]:
        """Return health status for this channel.

        Default implementation returns a basic status dict.
        Subclasses can override to add channel-specific checks
        (e.g. webhook reachability, token validity, polling status).

        Returns:
            Dict with at least: channel, status ("healthy" / "unhealthy"),
            and optional detail, error fields.
        """
        return {
            "channel": self.channel,
            "status": "healthy",
            "detail": "Channel is loaded and running.",
        }

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Subclass implements: send one text
        (and optional attachments) to to_handle.
        """
        raise NotImplementedError

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        """Map cron dispatch target to channel-specific to_handle.

        Default: use user_id. For many channels, this is enough.
        Discord proactive send relies on meta['channel_id'] or
         meta['user_id'] anyway.
        """
        return user_id

    async def send_event(
        self,
        *,
        user_id: str,
        session_id: str,
        event: "Event",
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a runner Event to this channel (non-stream).

        We only send when event is a completed message, then reuse
        send_message_content().
        """
        # Delay import to avoid hard dependency at module import time

        obj = getattr(event, "object", None)
        status = getattr(event, "status", None)

        if obj != "message" or status != RunStatus.Completed:
            return

        to_handle = self.to_handle_from_target(
            user_id=user_id,
            session_id=session_id,
        )
        await self.send_message_content(to_handle, event, meta)

    async def send_approval_notification(
        self,
        *,
        session_id: str,
        user_id: str,
        request_id: str,
        tool_name: str,
        severity: str,
        result_summary: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Push a tool-guard approval notification.

        Constructs a mock event with metadata.message_type=tool_guard_approval
        so card-capable channels render interactive cards, while others fall
        back to plain text.
        """
        from qwenpaw.schemas import Event, Message, Role

        to_handle = self.to_handle_from_target(
            user_id=user_id,
            session_id=session_id,
        )
        send_meta: Dict[str, Any] = dict(channel_meta or {})
        send_meta.setdefault("session_id", session_id)
        send_meta.setdefault("user_id", user_id)
        bot_prefix = getattr(self, "bot_prefix", None) or getattr(
            self,
            "_bot_prefix",
            "",
        )
        if bot_prefix and "bot_prefix" not in send_meta:
            send_meta["bot_prefix"] = bot_prefix

        event = Event(
            object="message",
            status=RunStatus.Completed,
            metadata={
                "metadata": {
                    "message_type": "tool_guard_approval",
                    "approval_request_id": request_id,
                    "tool_name": tool_name,
                    "severity": severity,
                },
            },
            content=[
                TextContent(type=ContentType.TEXT, text=result_summary),
            ],
        )
        request = ChannelTurn(
            session_id=session_id,
            sender_id=user_id,
            messages=[
                Message(
                    type=MessageType.MESSAGE,
                    role=Role.USER,
                    content=[],
                ),
            ],
            channel_type=self.channel,
            metadata=send_meta,
        )

        await self.on_event_message_completed(
            request,
            to_handle,
            event,
            send_meta,
        )
