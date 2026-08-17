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

    def to_public_dict(self) -> dict[str, str | int | bool]:
        """Return metadata safe for the public configuration API."""
        data = asdict(self)
        data.pop("module_name")
        data.pop("class_name")
        data.pop("config_class_name")
        data.pop("required")
        return data


BUILTIN_CHANNEL_CATALOG = (
    ChannelDefinition(
        "console",
        ".console",
        "ConsoleChannel",
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
    ),
    ChannelDefinition(
        "feishu",
        ".feishu",
        "FeishuChannel",
        "FeishuConfig",
        20,
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
    ),
    ChannelDefinition(
        "telegram",
        ".telegram",
        "TelegramChannel",
        "TelegramConfig",
        50,
    ),
    ChannelDefinition("qq", ".qq", "QQChannel", "QQConfig", 60),
    ChannelDefinition(
        "wechat",
        ".wechat",
        "WeChatChannel",
        "WeChatConfig",
        70,
    ),
    ChannelDefinition(
        "wecom",
        ".wecom",
        "WecomChannel",
        "WecomConfig",
        80,
    ),
    ChannelDefinition(
        "yuanbao",
        ".yuanbao",
        "YuanbaoChannel",
        "YuanbaoConfig",
        90,
    ),
    ChannelDefinition(
        "matrix",
        ".matrix",
        "MatrixChannel",
        "MatrixConfig",
        100,
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
    ),
    ChannelDefinition(
        "slack",
        ".slack",
        "SlackChannel",
        "SlackConfig",
        130,
    ),
    ChannelDefinition(
        "mattermost",
        ".mattermost",
        "MattermostChannel",
        "MattermostConfig",
        140,
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


__all__ = [
    "BUILTIN_CHANNEL_CATALOG",
    "BUILTIN_CHANNEL_KEYS",
    "ChannelDefinition",
    "ChannelSurface",
]
