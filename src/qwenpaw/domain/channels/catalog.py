# -*- coding: utf-8 -*-
"""Canonical definitions for built-in communication surfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import import_module
from typing import Literal

from pydantic import BaseModel


ChannelSurface = Literal["channel", "web"]


@dataclass(frozen=True, slots=True)
class ChannelDefinition:
    """Static identity and loading information for one built-in surface."""

    key: str
    module_name: str
    class_name: str
    config_class_name: str
    order: int
    label: str = ""
    surface: ChannelSurface = "channel"
    required: bool = False
    supports_access_control: bool = False
    supports_streaming: bool = False
    identity_fields: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, str | int | bool]:
        """Return metadata safe for the public configuration API."""
        data = asdict(self)
        data.pop("module_name")
        data.pop("class_name")
        data.pop("config_class_name")
        data.pop("required")
        data.pop("identity_fields")
        return data


BUILTIN_CHANNEL_CATALOG = (
    ChannelDefinition(
        "console",
        "qwenpaw.transports.console.channel",
        "ConsoleTransport",
        "ConsoleTransportConfig",
        0,
        label="Console",
        surface="web",
        required=True,
    ),
    ChannelDefinition(
        "dingtalk",
        ".dingtalk",
        "DingTalkChannel",
        "DingTalkConfig",
        10,
        label="DingTalk",
        supports_access_control=True,
        supports_streaming=True,
        identity_fields=("client_id",),
    ),
    ChannelDefinition(
        "feishu",
        ".feishu",
        "FeishuChannel",
        "FeishuConfig",
        20,
        label="Feishu",
        supports_access_control=True,
        supports_streaming=True,
        identity_fields=("app_id",),
    ),
    ChannelDefinition(
        "imessage",
        ".imessage",
        "IMessageChannel",
        "IMessageChannelConfig",
        30,
        label="iMessage",
        supports_access_control=True,
    ),
    ChannelDefinition(
        "discord",
        ".discord_",
        "DiscordChannel",
        "DiscordConfig",
        40,
        label="Discord",
        supports_access_control=True,
        supports_streaming=True,
        identity_fields=("bot_token",),
    ),
    ChannelDefinition(
        "telegram",
        ".telegram",
        "TelegramChannel",
        "TelegramConfig",
        50,
        label="Telegram",
        supports_access_control=True,
        supports_streaming=True,
        identity_fields=("bot_token",),
    ),
    ChannelDefinition(
        "qq",
        ".qq",
        "QQChannel",
        "QQConfig",
        60,
        label="QQ",
        supports_access_control=True,
        identity_fields=("app_id",),
    ),
    ChannelDefinition(
        "wechat",
        ".wechat",
        "WeChatChannel",
        "WeChatConfig",
        70,
        label="WeChat",
        supports_access_control=True,
        identity_fields=("bot_token",),
    ),
    ChannelDefinition(
        "wecom",
        ".wecom",
        "WecomChannel",
        "WecomConfig",
        80,
        label="WeCom",
        supports_access_control=True,
        supports_streaming=True,
        identity_fields=("bot_id",),
    ),
    ChannelDefinition(
        "yuanbao",
        ".yuanbao",
        "YuanbaoChannel",
        "YuanbaoConfig",
        90,
        label="Yuanbao",
        supports_access_control=True,
        identity_fields=("app_id",),
    ),
    ChannelDefinition(
        "matrix",
        ".matrix",
        "MatrixChannel",
        "MatrixConfig",
        100,
        label="Matrix",
        supports_access_control=True,
        supports_streaming=True,
        identity_fields=("homeserver", "user_id"),
    ),
    ChannelDefinition(
        "sip",
        ".sip",
        "SIPChannel",
        "SIPChannelConfig",
        110,
        label="SIP",
    ),
    ChannelDefinition(
        "xiaoyi",
        ".xiaoyi",
        "XiaoYiChannel",
        "XiaoYiConfig",
        120,
        label="XiaoYi",
        supports_access_control=True,
        identity_fields=("agent_id",),
    ),
    ChannelDefinition(
        "slack",
        ".slack",
        "SlackChannel",
        "SlackConfig",
        130,
        label="Slack",
        supports_access_control=True,
        supports_streaming=True,
        identity_fields=("bot_token",),
    ),
    ChannelDefinition(
        "mattermost",
        ".mattermost",
        "MattermostChannel",
        "MattermostConfig",
        140,
        label="Mattermost",
        supports_access_control=True,
        identity_fields=("url", "bot_token"),
    ),
    ChannelDefinition(
        "mqtt",
        ".mqtt",
        "MQTTChannel",
        "MQTTConfig",
        150,
        label="MQTT",
        supports_access_control=True,
    ),
    ChannelDefinition(
        "voice",
        ".voice",
        "VoiceChannel",
        "VoiceChannelConfig",
        160,
        label="Twilio",
        identity_fields=("phone_number_sid",),
    ),
    ChannelDefinition(
        "onebot",
        ".onebot",
        "OneBotChannel",
        "OneBotConfig",
        170,
        label="OneBot",
        supports_access_control=True,
    ),
)

BUILTIN_CHANNEL_KEYS = tuple(item.key for item in BUILTIN_CHANNEL_CATALOG)
_BUILTIN_CHANNEL_BY_KEY = {item.key: item for item in BUILTIN_CHANNEL_CATALOG}


def get_channel_definition(channel_key: str) -> ChannelDefinition:
    """Return one built-in definition or raise for an unknown key."""
    try:
        return _BUILTIN_CHANNEL_BY_KEY[channel_key]
    except KeyError as error:
        raise KeyError(f"Unknown built-in channel: {channel_key}") from error


def get_channel_config_model(
    channel_key: str,
) -> type[BaseModel] | None:
    """Resolve the Pydantic config model for a built-in Channel."""
    try:
        definition = get_channel_definition(channel_key)
    except KeyError:
        return None
    module = import_module("qwenpaw.config.config")
    model = getattr(module, definition.config_class_name)
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise TypeError(
            f"Invalid config model for Channel {channel_key}",
        )
    return model


__all__ = [
    "BUILTIN_CHANNEL_CATALOG",
    "BUILTIN_CHANNEL_KEYS",
    "ChannelDefinition",
    "ChannelSurface",
    "get_channel_config_model",
    "get_channel_definition",
]
