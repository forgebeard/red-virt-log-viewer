"""Render session and search result views."""

from __future__ import annotations

import os
from typing import Dict, List, Tuple

from ..core.models import EntityEventsResult, SearchSummary, SessionSettings, TimelineResult
from ..core.session import Session

MAX_LISTED_FILES = 400


def _status_line(counts: dict) -> str:
    order = [
        "text",
        "gzip",
        "xz",
        "empty",
        "unreadable",
        "unsupported_container",
        "unsupported_binary",
    ]
    parts = []
    for key in order:
        if counts.get(key):
            parts.append("%s %s" % (counts[key], key))
    extra = [key for key in sorted(counts) if key not in order and counts[key]]
    for key in extra:
        parts.append("%s %s" % (counts[key], key))
    return ", ".join(parts) if parts else "no files"


def render_session(session: Session) -> str:
    lines = [
        "RED Virt Log Viewer — session",
        "Session: %s" % session.session_id,
        "Cache: %s" % session.cache_dir,
        "Roots:",
    ]
    if not session.bundles:
        lines.append("  (none)")
    for bundle in session.bundles:
        lines.append("  %s" % bundle.root_path)
    counts = session.status_counts()
    lines.append("Files: %s" % _status_line(counts))
    lines.append("Searchable: %s" % len(session.searchable_files()))
    summary = getattr(session, "last_index_summary", None)
    if summary is not None and summary.files_total:
        parts = []
        for key in (
            "complete",
            "skipped",
            "failed",
            "cancelled",
            "indexing",
            "stale",
            "pending",
        ):
            if summary.by_status.get(key):
                parts.append("%s %s" % (summary.by_status[key], key))
        lines.append("Index: %s" % (", ".join(parts) if parts else "none"))
        lines.append(
            "Events: %s  issues: %s  incomplete=%s%s"
            % (
                summary.events,
                summary.issues,
                summary.incomplete,
                (" (%s)" % summary.incomplete_reason) if summary.incomplete_reason else "",
            )
        )
        lines.append("Indexed files:")
        for row in summary.files[:MAX_LISTED_FILES]:
            lines.append(
                "  [%s/%s gen=%s events=%s] %s"
                % (
                    row.status,
                    row.parser_id or "-",
                    row.generation if row.generation is not None else "-",
                    row.event_count,
                    row.relative_path,
                )
            )
        if len(summary.files) > MAX_LISTED_FILES:
            lines.append("  … and %s more" % (len(summary.files) - MAX_LISTED_FILES))
    else:
        lines.append("Index: not built yet. Open a folder or run Rebuild Index.")
    lines.append("")
    lines.append("Session follows the folders in this window. Index is reused for the same path.")
    lines.append("Stage 4: Show Timeline and Events Around. Not a diagnosis.")
    lines.append("Use Tools → RED Virt Log Viewer → Find Object or Search Text.")
    lines.append("")
    notable = [
        item
        for item in session.files
        if item.status in ("empty", "unreadable", "unsupported_container", "unsupported_binary")
    ]
    if notable:
        lines.append("Non-searchable files:")
        for item in notable[:MAX_LISTED_FILES]:
            extra = " (%s)" % item.issue if item.issue else ""
            lines.append("  [%s] %s%s" % (item.status, item.relative_path, extra))
        if len(notable) > MAX_LISTED_FILES:
            lines.append("  … and %s more" % (len(notable) - MAX_LISTED_FILES))
    return "\n".join(lines) + "\n"


def render_search(session: Session, summary: SearchSummary, settings: SessionSettings) -> Tuple[str, Dict[str, dict]]:
    lines: List[str] = [
        "RED Virt Log Viewer — text search",
        "Session: %s" % session.session_id,
        "Roots:",
    ]
    for bundle in session.bundles:
        lines.append("  %s" % bundle.root_path)
    lines.append("Query: %r  case_sensitive=%s" % (summary.query, summary.case_sensitive))
    lines.append("Files: %s" % _status_line(session.status_counts()))
    lines.append(
        "Scanned %s/%s searchable, skipped %s, failed %s"
        % (
            summary.files_scanned,
            summary.files_total,
            summary.files_skipped,
            summary.files_failed,
        )
    )
    limit_note = "showing first %s" % settings.page_size
    if summary.incomplete:
        lines.append(
            "INCOMPLETE: %s (%s)"
            % (summary.incomplete_reason or "yes", limit_note)
        )
    else:
        lines.append("Hits: %s (%s)" % (summary.hit_count, limit_note))
    if summary.failed_files:
        lines.append("Read errors:")
        for item in summary.failed_files[:20]:
            lines.append("  %s: %s" % (item.get("path"), item.get("issue")))
    lines.append("Enter on a result line opens the source.")
    lines.append("")
    line_map: Dict[str, dict] = {}
    for hit in summary.hits:
        row = len(lines)
        preview = hit.text.replace("\t", " ")
        if len(preview) > 240:
            preview = preview[:240] + "…"
        lines.append(
            "[%s] %s:%s  %s"
            % (hit.component_hint, hit.source.relative_path, hit.line_no, preview)
        )
        line_map[str(row)] = {
            "session_id": hit.source.session_id,
            "bundle_id": hit.source.bundle_id,
            "relative_path": hit.source.relative_path,
            "absolute_path": hit.source.absolute_path,
            "line_no": hit.line_no,
            "compression": hit.compression,
            "status": hit.status,
            "component_hint": hit.component_hint,
            "size": hit.size,
            "timestamp_utc_us": hit.timestamp_utc_us,
        }
    if not summary.hits:
        lines.append("(no matches)")
    return "\n".join(lines) + "\n", line_map


def _observed_names(entity) -> str:
    if entity is None or not entity.names:
        return "(no observed name)"
    parts = []
    for obs in entity.names:
        stamp = obs.observed_utc_us if obs.observed_utc_us is not None else "unknown time"
        parts.append("%s [%s, %s]" % (obs.name, obs.basis or "name", stamp))
    return "; ".join(parts)


def render_entity_events(
    session: Session,
    result: EntityEventsResult,
    settings: SessionSettings,
) -> Tuple[str, Dict[str, dict]]:
    entity = result.entity
    uuid_value = entity.uuid if entity is not None else "(none)"
    lines: List[str] = [
        "RED Virt Log Viewer — find object",
        "Session: %s" % session.session_id,
        "UUID: %s" % uuid_value,
        "Observed names: %s" % _observed_names(entity),
        "Showing first %s confirmed events (explicit vm UUID / vmId only)."
        % settings.page_size,
    ]
    if result.incomplete:
        lines.append(
            "INCOMPLETE INDEX OR PAGE: %s"
            % (result.incomplete_reason or "yes")
        )
    if result.hint:
        lines.append(result.hint)
    lines.append("This list is not a diagnosis of why the VM failed.")
    lines.append("Enter on a result line opens the source.")
    lines.append("")
    line_map: Dict[str, dict] = {}
    for hit in result.hits:
        row = len(lines)
        preview = hit.text.replace("\t", " ")
        if len(preview) > 240:
            preview = preview[:240] + "…"
        lines.append(
            "[%s] %s %s %s:%s  %s"
            % (
                hit.level or "unknown",
                hit.timestamp_raw or "-",
                hit.component_hint,
                hit.source.relative_path,
                hit.line_no,
                preview,
            )
        )
        line_map[str(row)] = {
            "session_id": hit.source.session_id,
            "bundle_id": hit.source.bundle_id,
            "relative_path": hit.source.relative_path,
            "absolute_path": hit.source.absolute_path,
            "line_no": hit.line_no,
            "compression": hit.compression,
            "status": hit.status,
            "component_hint": hit.component_hint,
            "size": hit.size,
            "timestamp_utc_us": hit.timestamp_utc_us,
        }
    if not result.hits:
        lines.append("(no confirmed UUID events)")
    return "\n".join(lines) + "\n", line_map


def render_timeline(
    session: Session,
    result: TimelineResult,
    settings: SessionSettings,
    title: str,
) -> Tuple[str, Dict[str, dict]]:
    lines: List[str] = [
        "RED Virt Log Viewer — %s" % title,
        "Session: %s" % session.session_id,
        "Window UTC µs: [%s, %s)" % (result.start_utc_us, result.end_utc_us),
    ]
    if result.entity_id is not None:
        lines.append("Entity id: %s" % result.entity_id)
    if result.radius_minutes is not None:
        lines.append("Around ±%s minutes" % result.radius_minutes)
    lines.append(
        "Showing first %s timed events. Untimed excluded: %s."
        % (settings.page_size, result.untimed_excluded)
    )
    if result.incomplete:
        lines.append("INCOMPLETE: %s" % (result.incomplete_reason or "yes"))
    if result.hint:
        lines.append(result.hint)
    lines.append("Enter on a result line opens the source.")
    lines.append("")
    line_map: Dict[str, dict] = {}
    for hit in result.hits:
        row = len(lines)
        preview = hit.text.replace("\t", " ")
        if len(preview) > 240:
            preview = preview[:240] + "…"
        lines.append(
            "[%s] %s %s %s:%s  %s"
            % (
                hit.level or "unknown",
                hit.timestamp_raw or "-",
                hit.component_hint,
                hit.source.relative_path,
                hit.line_no,
                preview,
            )
        )
        line_map[str(row)] = {
            "session_id": hit.source.session_id,
            "bundle_id": hit.source.bundle_id,
            "relative_path": hit.source.relative_path,
            "absolute_path": hit.source.absolute_path,
            "line_no": hit.line_no,
            "compression": hit.compression,
            "status": hit.status,
            "component_hint": hit.component_hint,
            "size": hit.size,
            "timestamp_utc_us": hit.timestamp_utc_us,
        }
    if not result.hits:
        lines.append("(no timed events in this window)")
    return "\n".join(lines) + "\n", line_map


def package_name() -> str:
    return os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
