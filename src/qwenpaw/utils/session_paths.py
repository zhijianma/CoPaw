# -*- coding: utf-8 -*-
"""Cross-platform naming helpers for persisted Agent sessions."""

from __future__ import annotations

import re
import unicodedata

_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


def sanitize_session_filename(
    name: str,
    *,
    normalize_unicode: bool = False,
) -> str:
    """Replace characters forbidden in Windows filenames with ``--``."""
    value = name or ""
    if normalize_unicode:
        value = unicodedata.normalize("NFC", value)
    return _UNSAFE_FILENAME_RE.sub("--", value)


def session_filename(
    session_id: str,
    user_id: str = "",
    *,
    normalize_unicode: bool = False,
) -> str:
    """Return the canonical JSON filename for one persisted session."""
    if not session_id:
        raise ValueError("session_id must not be None or empty")
    safe_sid = sanitize_session_filename(
        session_id,
        normalize_unicode=normalize_unicode,
    )
    safe_uid = (
        sanitize_session_filename(
            user_id,
            normalize_unicode=normalize_unicode,
        )
        if user_id
        else ""
    )
    if safe_uid and safe_uid == safe_sid:
        safe_uid = ""
    return f"{safe_uid}_{safe_sid}.json" if safe_uid else f"{safe_sid}.json"


__all__ = ["sanitize_session_filename", "session_filename"]
