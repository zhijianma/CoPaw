# -*- coding: utf-8 -*-
"""Token counting utilities for managing context windows.

This module provides token counting functionality for estimating
message token usage with Qwen tokenizer.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_token_counter = None


def _get_token_counter():
    """Get or initialize the global token counter instance.

    Returns:
        TokenCounterBase: The token counter instance for Qwen models.

    Raises:
        RuntimeError: If token counter initialization fails.
    """
    global _token_counter
    if _token_counter is None:
        from agentscope.token import HuggingFaceTokenCounter

        # Use Qwen tokenizer for DashScope models
        # Qwen3 series uses the same tokenizer as Qwen2.5

        # Try local tokenizer first, fall back to online if not found
        local_tokenizer_path = (
            Path(__file__).parent.parent.parent / "tokenizer"
        )

        if (
            local_tokenizer_path.exists()
            and (local_tokenizer_path / "tokenizer.json").exists()
        ):
            tokenizer_path = str(local_tokenizer_path)
            logger.info(f"Using local Qwen tokenizer from {tokenizer_path}")
        else:
            tokenizer_path = "Qwen/Qwen2.5-7B-Instruct"
            logger.info(
                "Local tokenizer not found, downloading from HuggingFace",
            )

        _token_counter = HuggingFaceTokenCounter(
            pretrained_model_name_or_path=tokenizer_path,
            use_mirror=True,  # Use HF mirror for users in China
            use_fast=True,
            trust_remote_code=True,
        )
        logger.debug("Token counter initialized with Qwen tokenizer")
    return _token_counter


def _extract_text_from_messages(messages: list[dict]) -> str:
    """Extract text content from messages and concatenate into a string.

    Handles various message formats:
    - Simple string content: {"role": "user", "content": "hello"}
    - List content with text blocks:
      {"role": "user", "content": [{"type": "text", "text": "hello"}]}

    Args:
        messages: List of message dictionaries in chat format.

    Returns:
        str: Concatenated text content from all messages.
    """
    parts = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    # Support {"type": "text", "text": "..."} format
                    text = block.get("text") or block.get("content", "")
                    if text:
                        parts.append(str(text))
                elif isinstance(block, str):
                    parts.append(block)
    return "\n".join(parts)


async def count_message_tokens(
    messages: list[dict],
) -> int:
    """Count tokens in messages using the tokenizer.

    Extracts text content from messages and uses the tokenizer to
    count tokens. This approach is more robust across different model
    types than using apply_chat_template directly.

    Args:
        messages: List of message dictionaries in chat format.

    Returns:
        int: The estimated number of tokens in the messages.

    Raises:
        RuntimeError: If token counter fails to initialize.
    """
    token_counter = _get_token_counter()
    text = _extract_text_from_messages(messages)
    token_ids = token_counter.tokenizer.encode(text)
    token_count = len(token_ids)
    logger.debug(
        "Counted %d tokens in %d messages",
        token_count,
        len(messages),
    )
    return token_count
