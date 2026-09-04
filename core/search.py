"""Literal substring search over discovered files. Not a regular expression."""

from __future__ import annotations

from typing import Callable, List, Optional

from .jobs import CancellationToken
from .models import (
    INCOMPLETE_CANCELLED,
    INCOMPLETE_HIT_LIMIT,
    JobProgress,
    SearchHit,
    SearchSummary,
    SessionSettings,
    SourceRef,
    STATUS_EMPTY,
    STATUS_UNREADABLE,
    STATUS_UNSUPPORTED_BINARY,
    STATUS_UNSUPPORTED_CONTAINER,
    DiscoveredFile,
)
from .readers import ReaderError, iter_lines


SKIP_STATUSES = (
    STATUS_EMPTY,
    STATUS_UNREADABLE,
    STATUS_UNSUPPORTED_CONTAINER,
    STATUS_UNSUPPORTED_BINARY,
)


def _contains(haystack: str, needle: str, case_sensitive: bool) -> bool:
    if not needle:
        return False
    if case_sensitive:
        return needle in haystack
    return needle.casefold() in haystack.casefold()


def search_files(
    files: List[DiscoveredFile],
    query: str,
    session_id: str,
    settings: Optional[SessionSettings] = None,
    cancel: Optional[CancellationToken] = None,
    on_progress: Optional[Callable[[JobProgress], None]] = None,
    job_id: str = "",
) -> SearchSummary:
    settings = settings or SessionSettings()
    summary = SearchSummary(
        query=query,
        case_sensitive=settings.case_sensitive,
    )
    skipped = {}
    searchable = []
    for item in files:
        if item.searchable:
            searchable.append(item)
        else:
            skipped[item.status] = skipped.get(item.status, 0) + 1
    summary.skipped_by_status = skipped
    summary.files_skipped = sum(skipped.values())
    summary.files_total = len(searchable)
    max_hits = max(1, settings.page_size)
    if not query:
        summary.incomplete = False
        return summary

    for index, item in enumerate(searchable):
        if cancel is not None and cancel.cancelled:
            summary.incomplete = True
            summary.incomplete_reason = INCOMPLETE_CANCELLED
            break
        if on_progress is not None:
            on_progress(
                JobProgress(
                    job_id=job_id,
                    message="Searching %s" % item.relative_path,
                    files_done=index,
                    files_total=summary.files_total,
                    current_path=item.relative_path,
                )
            )
        try:
            for line in iter_lines(
                item.absolute_path,
                compression=item.compression,
                encoding=settings.encoding,
                max_line_bytes=settings.max_line_bytes,
                cancel=cancel,
            ):
                if cancel is not None and cancel.cancelled:
                    summary.incomplete = True
                    summary.incomplete_reason = INCOMPLETE_CANCELLED
                    break
                if _contains(line.text, query, settings.case_sensitive):
                    hit = SearchHit(
                        source=SourceRef(
                            session_id=session_id,
                            bundle_id=item.bundle_id,
                            relative_path=item.relative_path,
                            start_line=line.line_no,
                            end_line=line.line_no,
                            generation=None,
                            absolute_path=item.absolute_path,
                        ),
                        line_no=line.line_no,
                        text=line.text,
                        truncated=line.truncated,
                        compression=item.compression,
                        status=item.status,
                        component_hint=item.component_hint,
                        size=item.size,
                    )
                    summary.hits.append(hit)
                    summary.hit_count = len(summary.hits)
                    if summary.hit_count >= max_hits:
                        summary.incomplete = True
                        summary.incomplete_reason = INCOMPLETE_HIT_LIMIT
                        summary.files_scanned = index + 1
                        return summary
        except ReaderError as exc:
            summary.files_failed += 1
            summary.failed_files.append(
                {"path": item.relative_path, "issue": exc.message}
            )
        if summary.incomplete_reason == INCOMPLETE_CANCELLED:
            summary.files_scanned = index
            break
        summary.files_scanned = index + 1
    return summary
