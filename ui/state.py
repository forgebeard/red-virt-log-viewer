"""Window-to-session binding. Imported only from Sublime UI code."""

from __future__ import annotations

from typing import Dict, Optional

import sublime

from ..core.session import Session, get_session, shutdown_all

_WINDOW_SESSIONS: Dict[int, str] = {}


def bind(window_id: int, session: Session) -> None:
    _WINDOW_SESSIONS[window_id] = session.session_id


def unbind(window_id: int) -> None:
    _WINDOW_SESSIONS.pop(window_id, None)


def session_id_for(window_id: int) -> Optional[str]:
    return _WINDOW_SESSIONS.get(window_id)


def session_for_window_id(window_id: int) -> Optional[Session]:
    session_id = _WINDOW_SESSIONS.get(window_id)
    if not session_id:
        return None
    return get_session(session_id)


def windows_bound_to(session_id: str) -> bool:
    return any(value == session_id for value in _WINDOW_SESSIONS.values())


def on_plugin_loaded() -> None:
    def kick() -> None:
        from . import commands

        for window in sublime.windows():
            commands.sync_window(window)

    sublime.set_timeout(kick, 50)


def on_plugin_unloaded() -> None:
    _WINDOW_SESSIONS.clear()
    shutdown_all()
