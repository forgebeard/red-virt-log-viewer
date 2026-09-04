"""User-facing command implementations. Command classes live in the package root plugin."""

from __future__ import annotations

import os
from typing import Optional

import sublime

from ..core.entities import entity_events, find_object
from ..core.indexing import index_session, load_summary
from ..core.models import EntityCandidate, SearchHit, SearchSummary, SessionSettings, SourceRef
from ..core.timeline import (
    parse_time_bounds,
    session_events_around,
    session_events_in_window,
    session_timestamp_at_location,
)
from ..core.search import search_files
from ..core.session import (
    Session,
    create_session,
    discard_session,
    folders_are_tickets_root,
    get_session,
    normalize_root,
)
from ..core.source import format_fragment, plan_open, plan_open_hit
from . import panels, state
from .results import package_name, render_entity_events, render_search, render_session, render_timeline


def load_settings() -> SessionSettings:
    loaded = sublime.load_settings("RedVirtLogViewer.sublime-settings")
    return SessionSettings(
        encoding=str(loaded.get("encoding", "utf-8")),
        page_size=int(loaded.get("page_size", 200)),
        max_line_bytes=int(loaded.get("max_line_bytes", 1024 * 1024)),
        fragment_context_lines=int(loaded.get("fragment_context_lines", 40)),
        sniff_bytes=int(loaded.get("sniff_bytes", 8192)),
        case_sensitive=bool(loaded.get("case_sensitive", True)),
        direct_open_max_bytes=int(loaded.get("direct_open_max_bytes", 32 * 1024 * 1024)),
        event_preview_chars=int(loaded.get("event_preview_chars", 1024)),
        sniff_lines=int(loaded.get("sniff_lines", 40)),
        tickets_root=str(loaded.get("tickets_root", "") or ""),
        journal_year=_optional_int(loaded.get("journal_year", "")),
        journal_utc_offset=str(loaded.get("journal_utc_offset", "") or ""),
    )


def _optional_int(value):
    if value in ("", None):
        return None
    return int(value)


def _session(window) -> Optional[Session]:
    return state.session_for_window_id(window.id())


def _syntax_resource() -> str:
    return "Packages/%s/RedVirtLog.sublime-syntax" % package_name()


def _fill_view(view, text: str, name: str, session_id: str, hits=None) -> None:
    view.set_name(name)
    view.set_scratch(True)
    view.settings().set("red_virt_results", True)
    view.settings().set("red_virt_session_id", session_id)
    view.settings().set("red_virt_hits", hits or {})
    try:
        view.assign_syntax(_syntax_resource())
    except Exception:
        pass
    view.run_command("red_virt_replace_view", {"text": text})


def _show_text(window, session: Session, text: str, name: str, hits=None) -> None:
    view = None
    for candidate in window.views():
        if candidate.settings().get("red_virt_session_id") == session.session_id and candidate.name() == name:
            view = candidate
            break
    if view is None:
        view = window.new_file()
    _fill_view(view, text, name, session.session_id, hits=hits)
    window.focus_view(view)


def _run_job(window, session: Session, func, on_success) -> None:
    def on_done(result) -> None:
        def on_ui() -> None:
            if isinstance(result, Exception):
                sublime.error_message("RED Virt: %s" % result)
                return
            on_success(result)

        sublime.set_timeout(on_ui, 0)

    def on_progress(payload) -> None:
        message = "RED Virt: %s" % payload.message
        sublime.set_timeout(lambda m=message: window.status_message(m), 0)

    session.jobs.submit(func, on_done, on_progress)


def _folder_fingerprint(paths) -> tuple:
    return tuple(sorted(normalize_root(path) for path in paths if path))


def _is_tickets_catalog(paths, settings: SessionSettings) -> bool:
    return folders_are_tickets_root(paths, settings.tickets_root)


def _reject_tickets_catalog(window, paths, settings: SessionSettings) -> bool:
    if not _is_tickets_catalog(paths, settings):
        return False
    sublime.error_message(
        "RED Virt: open a ticket folder inside tickets_root, not the tickets catalog itself"
    )
    window.status_message(
        "RED Virt: open a ticket folder inside tickets_root, not the tickets catalog itself"
    )
    return True


def _bind_session(window, session: Session) -> None:
    previous = _session(window)
    if previous is not None and previous.session_id != session.session_id:
        state.unbind(window.id())
        if not state.windows_bound_to(previous.session_id):
            discard_session(previous.session_id)
    state.bind(window.id(), session)


def sync_window(window) -> None:
    folders = [path for path in (window.folders() or []) if os.path.isdir(path)]
    if not folders:
        return
    settings = load_settings()
    if _reject_tickets_catalog(window, folders, settings):
        return
    fingerprint = _folder_fingerprint(folders)
    session = _session(window)
    if session is not None:
        bound = _folder_fingerprint(b.root_path for b in session.bundles)
        if fingerprint == bound:
            return
        if set(fingerprint).issubset(set(bound)):
            return
    session = create_session(settings, root_paths=folders)
    _bind_session(window, session)
    discover_and_show(window, session)


def detach_window(window) -> None:
    session = _session(window)
    state.unbind(window.id())
    if session is not None and not state.windows_bound_to(session.session_id):
        discard_session(session.session_id)


def open_support_folder(window) -> None:
    def on_path(path: str) -> None:
        settings = load_settings()
        if _reject_tickets_catalog(window, [path], settings):
            return
        session = create_session(settings, root_paths=[path])
        _bind_session(window, session)
        discover_and_show(window, session)

    panels.pick_folder(window, on_path)


def add_support_folder(window) -> None:
    session = _session(window)
    if session is None:
        open_support_folder(window)
        return

    def on_path(path: str) -> None:
        settings = load_settings()
        if _reject_tickets_catalog(window, [path], settings):
            return
        roots = [bundle.root_path for bundle in session.bundles] + [path]
        combined = create_session(settings, root_paths=roots)
        _bind_session(window, combined)
        discover_and_show(window, combined)

    panels.pick_folder(window, on_path)


def discover_and_show(window, session: Session) -> None:
    def job(token, progress):
        session.discover(cancel=token, progress=progress)
        if token.cancelled:
            return load_summary(session)
        return index_session(session, cancel=token, progress=progress, force=False)

    def on_success(_summary) -> None:
        show_session(window)

    _run_job(window, session, job, on_success)


def rebuild_index(window) -> None:
    session = _session(window)
    if session is None:
        sublime.error_message("RED Virt: no active session. Open a support folder first.")
        return

    def job(token, progress):
        return index_session(session, cancel=token, progress=progress, force=True)

    def on_success(_summary) -> None:
        show_session(window)

    _run_job(window, session, job, on_success)


def clear_session_cache(window) -> None:
    session = _session(window)
    if session is None:
        sublime.error_message("RED Virt: no active session. Open a support folder first.")
        return
    session.clear_cache()
    show_session(window)
    window.status_message("RED Virt: session cache cleared")


def show_session(window) -> None:
    session = _session(window)
    if session is None:
        sublime.error_message("RED Virt: no active session. Open a support folder first.")
        return
    if session.last_index_summary is None:
        load_summary(session)
    _show_text(window, session, render_session(session), "RED Virt: Session")


def search_text(window) -> None:
    session = _session(window)
    if session is None:
        sublime.error_message("RED Virt: no active session. Open a support folder first.")
        return

    def on_query(query: str) -> None:
        query = query.strip()
        if not query:
            return
        settings = load_settings()
        session.settings = settings

        def job(token, progress):
            return search_files(
                session.files,
                query,
                session_id=session.session_id,
                settings=settings,
                cancel=token,
                on_progress=progress,
                job_id=session.jobs.job_id,
            )

        def on_success(summary: SearchSummary) -> None:
            text, hits = render_search(session, summary, settings)
            _show_text(window, session, text, "RED Virt: Search", hits=hits)

        _run_job(window, session, job, on_success)

    panels.ask_search_query(window, "", on_query)


def _candidate_caption(candidate: EntityCandidate) -> str:
    if candidate.names:
        label = candidate.names[0].name
    else:
        label = "(UUID only)"
    if candidate.uuid is None:
        return "%s  (name without UUID — not a confirmed VM; use Search Text)" % label
    return "%s  %s  %s events  %s" % (
        label,
        candidate.uuid,
        candidate.event_count,
        candidate.evidence,
    )


def find_object_command(window) -> None:
    session = _session(window)
    if session is None:
        sublime.error_message("RED Virt: no active session. Open a support folder first.")
        return

    def on_query(query: str) -> None:
        query = query.strip()
        if not query:
            return
        settings = load_settings()
        session.settings = settings

        def job(token, progress):
            return find_object(session, query, cancel=token)

        def on_success(result) -> None:
            if result.index_empty:
                sublime.error_message(
                    "RED Virt: index is empty or missing. Open a folder or Rebuild Index. "
                    "No objects were invented."
                )
                return
            if result.incomplete:
                window.status_message(
                    "RED Virt: Find Object used an incomplete index (%s)"
                    % (result.incomplete_reason or "yes")
                )
            items = []
            for candidate in result.candidates:
                items.append((_candidate_caption(candidate), ("entity", candidate)))
            for candidate in result.unresolved_names:
                items.append((_candidate_caption(candidate), ("unresolved", candidate)))
            if not items:
                sublime.message_dialog(
                    "RED Virt: no object matched %r.\n"
                    "Try Search Text for name-only mentions. "
                    "A VM is not created from a guess."
                    % query
                )
                return

            def on_select(payload) -> None:
                kind, candidate = payload
                if kind == "unresolved" or candidate.entity_id is None:
                    sublime.message_dialog(
                        "RED Virt: %s has no UUID in the same QEMU launch block.\n"
                        "It is not a confirmed VM. Use Search Text."
                        % (candidate.names[0].name if candidate.names else "this name")
                    )
                    return

                def events_job(token, progress):
                    return entity_events(session, candidate.entity_id, cancel=token)

                def on_events(events_result) -> None:
                    session.last_entity_id = candidate.entity_id
                    text, hits = render_entity_events(session, events_result, settings)
                    _show_text(window, session, text, "RED Virt: Object", hits=hits)

                _run_job(window, session, events_job, on_events)

            panels.show_object_candidates(window, items, on_select)

        _run_job(window, session, job, on_success)

    panels.ask_find_object_query(window, "", on_query)


def _center_utc_from_view(window, view, session, on_center) -> None:
    if view is None:
        sublime.error_message("RED Virt: no active view")
        return
    if view.settings().get("red_virt_results") and view.sel():
        row, _col = view.rowcol(view.sel()[0].begin())
        payload = (view.settings().get("red_virt_hits") or {}).get(str(row)) or {}
        stamp = payload.get("timestamp_utc_us")
        if stamp:
            on_center(int(stamp))
            return
    path = view.file_name() or ""
    if not path:
        sublime.error_message(
            "RED Virt: put the cursor on a result with a timestamp or an indexed source file. "
            "Not guessing the current time."
        )
        return
    line_no = view.rowcol(view.sel()[0].begin())[0] + 1
    relative = ""
    for item in session.files:
        if item.absolute_path == path:
            relative = item.relative_path
            break

    def job(token, progress):
        return session_timestamp_at_location(session, path, line_no, relative)

    def on_success(stamp) -> None:
        if not stamp:
            sublime.error_message(
                "RED Virt: no indexed UTC time at this line. Not guessing now."
            )
            return
        on_center(int(stamp))

    _run_job(window, session, job, on_success)


def show_timeline_command(window) -> None:
    session = _session(window)
    if session is None:
        sublime.error_message("RED Virt: no active session. Open a support folder first.")
        return
    settings = load_settings()
    session.settings = settings

    def run_window(entity_id) -> None:
        def on_bounds(text: str) -> None:
            start, end, err = parse_time_bounds(text)
            if err:
                sublime.error_message("RED Virt: %s" % err)
                return

            def job(token, progress):
                return session_events_in_window(
                    session, start, end, entity_id=entity_id, cancel=token
                )

            def on_success(result) -> None:
                body, hits = render_timeline(session, result, settings, "timeline")
                _show_text(window, session, body, "RED Virt: Timeline", hits=hits)

            _run_job(window, session, job, on_success)

        panels.ask_timeline_window(window, "", on_bounds)

    if session.last_entity_id is not None:
        run_window(session.last_entity_id)
        return

    def on_query(query: str) -> None:
        query = query.strip()
        if not query:
            return

        def job(token, progress):
            return find_object(session, query, cancel=token)

        def on_success(result) -> None:
            cands = [c for c in result.candidates if c.entity_id is not None]
            if not cands:
                sublime.error_message(
                    "RED Virt: no confirmed VM for Timeline. Find Object first."
                )
                return
            if len(cands) == 1:
                session.last_entity_id = cands[0].entity_id
                run_window(cands[0].entity_id)
                return

            def on_select(payload) -> None:
                _kind, candidate = payload
                if candidate.entity_id is None:
                    return
                session.last_entity_id = candidate.entity_id
                run_window(candidate.entity_id)

            items = [(_candidate_caption(c), ("entity", c)) for c in cands]
            panels.show_object_candidates(window, items, on_select)

        _run_job(window, session, job, on_success)

    panels.ask_find_object_query(window, "", on_query)


def events_around_command(window) -> None:
    session = _session(window)
    if session is None:
        sublime.error_message("RED Virt: no active session. Open a support folder first.")
        return
    settings = load_settings()
    session.settings = settings
    view = window.active_view()

    def after_center(center: int) -> None:
        def on_radius(minutes: int) -> None:
            def job(token, progress):
                return session_events_around(
                    session, center, minutes, cancel=token
                )

            def on_success(result) -> None:
                body, hits = render_timeline(session, result, settings, "events around")
                _show_text(window, session, body, "RED Virt: Around", hits=hits)

            _run_job(window, session, job, on_success)

        panels.show_around_radii(window, on_radius)

    _center_utc_from_view(window, view, session, after_center)


def cancel_operation(window) -> None:
    session = _session(window)
    if session is None:
        window.status_message("RED Virt: no active session")
        return
    session.jobs.cancel()
    window.status_message("RED Virt: cancel requested")


def open_hit(window, payload: dict) -> None:
    session = get_session(payload.get("session_id") or "")
    if session is None:
        session = _session(window)
    if session is None:
        sublime.error_message("RED Virt: session is no longer active")
        return
    item = session.file_by_path(payload["bundle_id"], payload["relative_path"])
    line_no = int(payload["line_no"])
    if item is None:
        hit = SearchHit(
            source=SourceRef(
                session_id=payload.get("session_id") or "",
                bundle_id=payload["bundle_id"],
                relative_path=payload["relative_path"],
                start_line=line_no,
                end_line=line_no,
                absolute_path=payload["absolute_path"],
            ),
            line_no=line_no,
            text="",
            compression=payload.get("compression") or "none",
            status=payload.get("status") or "text",
            component_hint=payload.get("component_hint") or "unknown",
            size=int(payload.get("size") or 0),
        )
        def job(token, progress):
            return plan_open_hit(hit, settings=session.settings, cancel=token)

    else:

        def job(token, progress):
            return plan_open(item, line_no, settings=session.settings, cancel=token)

    def on_success(plan) -> None:
        if plan.mode == "file":
            window.open_file(
                "%s:%s:1" % (plan.absolute_path, plan.line),
                sublime.ENCODED_POSITION,
            )
            return
        fragment = plan.fragment
        if fragment is None:
            sublime.error_message("RED Virt: could not load source fragment")
            return
        view = window.new_file()
        view.set_scratch(True)
        view.set_name("%s (fragment)" % os.path.basename(plan.absolute_path))
        view.settings().set("red_virt_fragment", True)
        view.run_command("red_virt_replace_view", {"text": format_fragment(fragment)})
        target = ">%6d|" % fragment.focus_line
        flags = getattr(sublime, "LITERAL", 1)
        found = view.find(target, 0, flags)
        if found:
            view.show(found)
            view.sel().clear()
            view.sel().add(found)

    _run_job(window, session, job, on_success)


def open_result_from_view(view) -> None:
    window = view.window()
    if window is None:
        return
    if not view.sel():
        return
    row, _col = view.rowcol(view.sel()[0].begin())
    hits = view.settings().get("red_virt_hits") or {}
    payload = hits.get(str(row))
    if not payload:
        return
    open_hit(window, payload)


def has_session(window) -> bool:
    return _session(window) is not None
