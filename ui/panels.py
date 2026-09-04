"""Folder picker and input panels."""

from __future__ import annotations

import os
from typing import Callable, Optional

import sublime

INPUT_PANEL_DELAY_MS = 50


def _resolved_folder(path: str) -> Optional[str]:
    if not path or not str(path).strip():
        return None
    resolved = os.path.abspath(os.path.expanduser(str(path).strip()))
    if os.path.isdir(resolved):
        return resolved
    sublime.error_message(
        "RED Virt: %r is not a folder. Choose the unpacked dump directory "
        "(the catalog that contains rv_info), not a log file."
        % path
    )
    return None


def _initial_directory(window, directory: Optional[str]) -> str:
    if directory:
        return directory
    folders = window.folders() if window is not None else None
    if folders:
        return folders[0]
    return ""


def _show_input_panel(window, caption: str, initial: str, on_done) -> None:
    window.status_message("RED Virt: %s" % caption)

    def show() -> None:
        if window is None:
            return
        window.show_input_panel(caption, initial, on_done, None, None)

    sublime.set_timeout(show, INPUT_PANEL_DELAY_MS)


def pick_folder(
    window,
    on_path: Callable[[str], None],
    directory: Optional[str] = None,
) -> None:
    def deliver(raw) -> None:
        if not raw:
            return
        if isinstance(raw, list):
            if not raw:
                return
            raw = raw[0]
        resolved = _resolved_folder(raw)
        if resolved is None:
            return
        on_path(resolved)

    if window is None:
        window = sublime.active_window()
    if window is None:
        return

    window.status_message("RED Virt: enter the unpacked dump folder")
    settings = sublime.load_settings("RedVirtLogViewer.sublime-settings")
    if bool(settings.get("native_folder_dialog", False)) and hasattr(
        sublime, "select_folder_dialog"
    ):
        sublime.select_folder_dialog(
            deliver,
            directory=directory or _initial_directory(window, None) or None,
            multi_select=False,
        )
        return

    _show_input_panel(
        window,
        "RED Virt: support folder path",
        _initial_directory(window, directory),
        deliver,
    )


def ask_search_query(
    window,
    initial: str,
    on_done: Callable[[str], None],
) -> None:
    _show_input_panel(window, "RED Virt: search text", initial, on_done)


def ask_find_object_query(
    window,
    initial: str,
    on_done: Callable[[str], None],
) -> None:
    _show_input_panel(window, "RED Virt: find object", initial, on_done)


def ask_timeline_window(
    window,
    initial: str,
    on_done: Callable[[str], None],
) -> None:
    _show_input_panel(
        window,
        "RED Virt: timeline start|end (empty = all timed)",
        initial,
        on_done,
    )


def show_around_radii(window, on_select) -> None:
    items = [("±1 minute", 1), ("±5 minutes", 5), ("±15 minutes", 15)]
    captions = [item[0] for item in items]

    def callback(index: int) -> None:
        if index < 0:
            return
        on_select(items[index][1])

    def show() -> None:
        window.show_quick_panel(captions, callback)

    sublime.set_timeout(show, INPUT_PANEL_DELAY_MS)


def show_object_candidates(window, items, on_select) -> None:
    captions = [item[0] for item in items]

    def callback(index: int) -> None:
        if index < 0:
            return
        on_select(items[index][1])

    def show() -> None:
        window.show_quick_panel(captions, callback)

    sublime.set_timeout(show, INPUT_PANEL_DELAY_MS)
