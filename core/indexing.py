"""Index discovered files: sniff → parse → SQLite. Worker-thread only."""

from __future__ import annotations

import os
from typing import List, Optional

from parsers import choose_parser, parser_by_id

from .index import IndexStore
from .jobs import CancellationToken
from .models import (
    INDEX_CANCELLED,
    INDEX_COMPLETE,
    INDEX_FAILED,
    INDEX_INDEXING,
    INDEX_SKIPPED,
    INDEX_STALE,
    DiscoveredFile,
    IndexSummary,
    JobProgress,
    ParseIssue,
    SEARCHABLE_STATUSES,
    SessionSettings,
)
from .readers import ReaderError, iter_lines
from .session import Session


def db_path(session: Session) -> str:
    return os.path.join(session.cache_dir, "index.sqlite")


def sniff_sample(item: DiscoveredFile, settings: SessionSettings, cancel=None):
    sample = []
    limit = max(1, settings.sniff_lines)
    for line in iter_lines(
        item.absolute_path,
        compression=item.compression,
        encoding=settings.encoding,
        max_line_bytes=settings.max_line_bytes,
        cancel=cancel,
    ):
        sample.append(line)
        if len(sample) >= limit:
            break
    return sample


def index_session(
    session: Session,
    cancel: Optional[CancellationToken] = None,
    progress=None,
    force: bool = False,
) -> IndexSummary:
    session.ensure_cache_dir()
    store = IndexStore(db_path(session))
    settings = session.settings
    summary = IndexSummary()
    try:
        for bundle in session.bundles:
            store.upsert_bundle(bundle.bundle_id, bundle.root_path, bundle.label)
        store.commit()
        time_key = settings.time_settings_key()
        journal_stale = store.get_meta("time_settings") != time_key
        total = len(session.files)
        for index, item in enumerate(session.files):
            if cancel is not None and cancel.cancelled:
                summary.incomplete = True
                summary.incomplete_reason = INDEX_CANCELLED
                break
            if progress is not None:
                progress(
                    JobProgress(
                        job_id=session.jobs.job_id,
                        message="Indexing %s" % item.relative_path,
                        files_done=index,
                        files_total=total,
                        current_path=item.relative_path,
                    )
                )
            _index_file(
                store,
                session,
                item,
                force=force,
                cancel=cancel,
                journal_stale=journal_stale,
            )
            store.commit()
        from .entities import resolve_from_index

        resolve_from_index(store)
        summary = store.summary()
        if cancel is not None and cancel.cancelled:
            summary.incomplete = True
            summary.incomplete_reason = INDEX_CANCELLED
        store.set_meta("index_incomplete", "1" if summary.incomplete else "0")
        store.set_meta("index_incomplete_reason", summary.incomplete_reason or "")
        store.set_meta("time_settings", time_key)
        store.commit()
        session.last_index_summary = summary
        return summary
    finally:
        store.close()


def _index_file(
    store: IndexStore,
    session: Session,
    item: DiscoveredFile,
    force: bool,
    cancel: Optional[CancellationToken],
    journal_stale: bool = False,
) -> None:
    settings = session.settings
    file_id = store.upsert_file(item)
    if item.status not in SEARCHABLE_STATUSES:
        gen_id = store.begin_generation(
            file_id,
            parser_id="none",
            parser_version="0",
            encoding=settings.encoding,
            size=item.size,
            mtime_ns=item.mtime_ns,
            status=INDEX_SKIPPED,
        )
        store.finish_generation(gen_id, INDEX_SKIPPED, 0, 0, published=True)
        return

    try:
        sample = sniff_sample(item, settings, cancel=cancel)
    except ReaderError as exc:
        gen_id = store.begin_generation(
            file_id,
            parser_id="none",
            parser_version="0",
            encoding=settings.encoding,
            size=item.size,
            mtime_ns=item.mtime_ns,
            status=INDEX_FAILED,
        )
        store.insert_issues(
            gen_id,
            file_id,
            [ParseIssue(kind="read_error", message=exc.message)],
        )
        store.finish_generation(gen_id, INDEX_FAILED, 0, 1, published=True)
        return

    assessment = choose_parser(
        sample,
        relative_path=item.relative_path,
        component_hint=item.component_hint,
    )
    parser = parser_by_id(assessment.parser_id)
    skip_current = (
        not force
        and not (journal_stale and parser.parser_id == "journal")
        and store.is_current(
            file_id,
            item.size,
            item.mtime_ns,
            parser.parser_id,
            parser.version,
            settings.encoding,
        )
    )
    if skip_current:
        return

    complete = store.current_complete(file_id)
    if complete is not None:
        store.mark_stale(file_id)

    gen_id = store.begin_generation(
        file_id,
        parser_id=parser.parser_id,
        parser_version=parser.version,
        encoding=settings.encoding,
        size=item.size,
        mtime_ns=item.mtime_ns,
        status=INDEX_INDEXING,
    )
    store.commit()
    try:
        lines = iter_lines(
            item.absolute_path,
            compression=item.compression,
            encoding=settings.encoding,
            max_line_bytes=settings.max_line_bytes,
            cancel=cancel,
        )
        if parser.parser_id == "journal":
            parsed = parser.parse(
                lines,
                journal_year=settings.journal_year,
                journal_utc_offset=settings.journal_utc_offset,
            )
        else:
            parsed = parser.parse(lines)
    except ReaderError as exc:
        store.insert_issues(
            gen_id,
            file_id,
            [ParseIssue(kind="read_error", message=exc.message)],
        )
        store.finish_generation(gen_id, INDEX_FAILED, 0, 1, published=True)
        return

    if cancel is not None and cancel.cancelled:
        store.finish_generation(gen_id, INDEX_CANCELLED, 0, 0, published=False)
        return

    events = store.insert_events(gen_id, parsed.records, settings.event_preview_chars)
    issues = list(parsed.issues)
    if assessment.issue:
        issues.append(
            ParseIssue(kind="format_assessment", message=assessment.issue)
        )
    issue_count = store.insert_issues(gen_id, file_id, issues)
    store.finish_generation(
        gen_id,
        INDEX_COMPLETE,
        events,
        issue_count,
        published=True,
    )


def load_summary(session: Session) -> IndexSummary:
    path = db_path(session)
    if not os.path.isfile(path):
        return IndexSummary()
    store = IndexStore(path)
    try:
        summary = store.summary()
        session.last_index_summary = summary
        return summary
    finally:
        store.close()
