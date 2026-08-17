# -*- coding: utf-8 -*-
"""Canonical definitions for built-in communication surfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


ChannelSurface = Literal["channel", "web"]


@dataclass(frozen=True, slots=True)
class ChannelDefinition:
    """Static identity and loading information for one built-in surface."""

    key: str
    module_name: str
    class_name: str
    config_class_name: str
    order: int
    surface: ChannelSurface = "channel"
    required: bool = False
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
        "ConsoleConfig",
        0,
        surface="web",
        required=True,
    ),
    ChannelDefinition(
        "dingtalk",
        ".dingtalk",
        "DingTalkChannel",
        "DingTalkConfig",
        10,
        identity_fields=("client_id",),
    ),
    ChannelDefinition(
        "feishu",
        ".feishu",
        "FeishuChannel",
        "FeishuConfig",
        20,
        identity_fields=("app_id",),
    ),
    ChannelDefinition(
        "imessage",
        ".imessage",
        "IMessageChannel",
        "IMessageChannelConfig",
        30,
    ),
    ChannelDefinition(
        "discord",
        ".discord_",
        "DiscordChannel",
        "DiscordConfig",
        40,
        identity_fields=("bot_token",),
    ),
    ChannelDefinition(
        "telegram",
        ".telegram",
        "TelegramChannel",
        "TelegramConfig",
        50,
        identity_fields=("bot_token",),
    ),
    ChannelDefinition(
        "qq",
        ".qq",
        "QQChannel",
        "QQConfig",
        60,
        identity_fields=("app_id",),
    ),
    ChannelDefinition(
        "wechat",
        ".wechat",
        "WeChatChannel",
        "WeChatConfig",
        70,
        identity_fields=("bot_token",),
    ),
    ChannelDefinition(
        "wecom",
        ".wecom",
        "WecomChannel",
        "WecomConfig",
        80,
        identity_fields=("bot_id",),
    ),
    ChannelDefinition(
        "yuanbao",
        ".yuanbao",
        "YuanbaoChannel",
        "YuanbaoConfig",
        90,
        identity_fields=("app_id",),
    ),
    ChannelDefinition(
        "matrix",
        ".matrix",
        "MatrixChannel",
        "MatrixConfig",
        100,
        identity_fields=("homeserver", "user_id"),
    ),
    ChannelDefinition(
        "sip",
        ".sip",
        "SIPChannel",
        "SIPChannelConfig",
        110,
    ),
    ChannelDefinition(
        "xiaoyi",
        ".xiaoyi",
        "XiaoYiChannel",
        "XiaoYiConfig",
        120,
        identity_fields=("agent_id",),
    ),
    ChannelDefinition(
        "slack",
        ".slack",
        "SlackChannel",
        "SlackConfig",
        130,
        identity_fields=("bot_token",),
    ),
    ChannelDefinition(
        "mattermost",
        ".mattermost",
        "MattermostChannel",
        "MattermostConfig",
        140,
        identity_fields=("url", "bot_token"),
    ),
    ChannelDefinition(
        "mqtt",
        ".mqtt",
        "MQTTChannel",
        "MQTTConfig",
        150,
    ),
    ChannelDefinition(
        "voice",
        ".voice",
        "VoiceChannel",
        "VoiceChannelConfig",
        160,
        identity_fields=("phone_number_sid",),
    ),
    ChannelDefinition(
        "onebot",
        ".onebot",
        "OneBotChannel",
        "OneBotConfig",
        170,
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


__all__ = [
    "BUILTIN_CHANNEL_CATALOG",
    "BUILTIN_CHANNEL_KEYS",
    "ChannelDefinition",
    "ChannelSurface",
    "get_channel_definition",
]
