"""Sublime plugin entry point. Command classes must live in a root plugin module."""

from __future__ import annotations

import os
import sys
import traceback

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)

import sublime
import sublime_plugin

_SYNC_IMPORT_FAILED = False


def plugin_loaded() -> None:
    from .ui.state import on_plugin_loaded

    on_plugin_loaded()


def plugin_unloaded() -> None:
    from .ui.state import on_plugin_unloaded

    on_plugin_unloaded()


class RedVirtFolderListener(sublime_plugin.EventListener):
    def on_new_window(self, window) -> None:
        sublime.set_timeout(lambda: _sync(window), 50)

    def on_load_project(self, window) -> None:
        sublime.set_timeout(lambda: _sync(window), 50)

    def on_pre_close_window(self, window) -> None:
        from .ui.commands import detach_window

        detach_window(window)

    def on_post_window_command(self, window, command_name, _args) -> None:
        if command_name in (
            "prompt_open_folder",
            "prompt_add_folder",
            "close_folder_list",
            "prompt_open_project_or_workspace",
        ):
            sublime.set_timeout(lambda: _sync(window), 50)

    def on_activated(self, view) -> None:
        window = view.window() if view is not None else None
        if window is not None:
            _sync(window)


def _sync(window) -> None:
    global _SYNC_IMPORT_FAILED
    if _SYNC_IMPORT_FAILED:
        return
    try:
        from .ui.commands import sync_window
    except Exception:
        _SYNC_IMPORT_FAILED = True
        traceback.print_exc()
        return
    sync_window(window)


class RedVirtOpenSupportFolderCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        from .ui.commands import open_support_folder

        open_support_folder(self.window)


class RedVirtAddSupportFolderCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        from .ui.commands import add_support_folder

        add_support_folder(self.window)


class RedVirtShowSessionCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        from .ui.commands import show_session

        show_session(self.window)


class RedVirtSearchTextCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        from .ui.commands import search_text

        search_text(self.window)


class RedVirtFindObjectCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        from .ui.commands import find_object_command

        find_object_command(self.window)


class RedVirtShowTimelineCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        from .ui.commands import show_timeline_command

        show_timeline_command(self.window)


class RedVirtEventsAroundCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        from .ui.commands import events_around_command

        events_around_command(self.window)


class RedVirtCancelOperationCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        from .ui.commands import cancel_operation

        cancel_operation(self.window)


class RedVirtRebuildIndexCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        from .ui.commands import rebuild_index

        rebuild_index(self.window)


class RedVirtClearSessionCacheCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        from .ui.commands import clear_session_cache

        clear_session_cache(self.window)


class RedVirtOpenResultCommand(sublime_plugin.TextCommand):
    def run(self, edit) -> None:
        from .ui.commands import open_result_from_view

        open_result_from_view(self.view)

    def is_enabled(self) -> bool:
        return bool(self.view.settings().get("red_virt_results"))


class RedVirtReplaceViewCommand(sublime_plugin.TextCommand):
    def run(self, edit, text: str = "") -> None:
        self.view.set_read_only(False)
        self.view.replace(edit, sublime.Region(0, self.view.size()), text)
        self.view.set_read_only(True)
