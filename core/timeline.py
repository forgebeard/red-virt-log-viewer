"""Time windows over published index events. Does not guess 'now' or host TZ."""

from __future__ import annotations

import os
from typing import Optional

from .entities import _index_flags
from .index import IndexStore
from .jobs import CancellationToken
from .models import (
    COMPRESSION_NONE,
    INDEX_COMPLETE,
    SearchHit,
    SessionSettings,
    SourceRef,
    TimelineResult,
)
from .timeparse import parse_explicit_timestamp

HINT = (
    "Interval is [start, end). Events without UTC time are excluded. "
    "This is not a diagnosis and not proof of one incident."
)


def parse_time_bounds(text: str):
    """Return (start_us, end_us, error). Empty or * means the whole timed index."""
    text = (text or "").strip()
    if not text or text == "*":
        return None, None, None
    if "|" not in text:
        return None, None, "enter start|end (explicit offset) or leave empty for all timed events"
    left, right = text.split("|", 1)
    start = end = None
    if left.strip():
        parsed = parse_explicit_timestamp(left.strip())
        if parsed.timestamp_utc_us is None:
            return None, None, "start: %s" % (parsed.time_issue or "unparsed")
        start = parsed.timestamp_utc_us
    if right.strip():
        parsed = parse_explicit_timestamp(right.strip())
        if parsed.timestamp_utc_us is None:
            return None, None, "end: %s" % (parsed.time_issue or "unparsed")
        end = parsed.timestamp_utc_us
    return start, end, None


def _hit_from_row(row, session_id: str) -> SearchHit:
    return SearchHit(
        source=SourceRef(
            session_id=session_id,
            bundle_id=row["bundle_id"],
            relative_path=row["relative_path"],
            start_line=int(row["start_line"]),
            end_line=int(row["end_line"] or row["start_line"]),
            generation=row["generation"],
            absolute_path=row["absolute_path"] or "",
        ),
        line_no=int(row["start_line"]),
        text=row["preview"] or "",
        truncated=bool(row["truncated"]),
        compression=row["compression"] or COMPRESSION_NONE,
        status=row["discovery_status"] or "text",
        component_hint=row["parser_id"] or "",
        size=int(row["size"] or 0),
        timestamp_raw=row["timestamp_raw"] or "",
        level=row["level"] or "",
        timestamp_utc_us=row["timestamp_utc_us"],
    )


def _untimed_count(store: IndexStore, entity_id: Optional[int]) -> int:
    if entity_id is None:
        row = store.conn.execute(
            """
            SELECT COUNT(*) AS n FROM events e
            JOIN file_generations g ON g.generation_id = e.generation_id
            WHERE g.published=1 AND g.status=? AND e.timestamp_utc_us IS NULL
            """,
            (INDEX_COMPLETE,),
        ).fetchone()
    else:
        row = store.conn.execute(
            """
            SELECT COUNT(DISTINCT e.event_id) AS n
            FROM event_entities ee
            JOIN events e ON e.event_id = ee.event_id
            JOIN file_generations g ON g.generation_id = ee.generation_id
            WHERE ee.entity_id=? AND g.published=1 AND g.status=?
              AND e.timestamp_utc_us IS NULL
            """,
            (entity_id, INDEX_COMPLETE),
        ).fetchone()
    return int(row["n"] or 0)


def events_in_window(
    store: IndexStore,
    session_id: str,
    start_utc_us: Optional[int],
    end_utc_us: Optional[int],
    settings: Optional[SessionSettings] = None,
    entity_id: Optional[int] = None,
) -> TimelineResult:
    settings = settings or SessionSettings()
    incomplete, reason, empty = _index_flags(store)
    result = TimelineResult(
        start_utc_us=start_utc_us,
        end_utc_us=end_utc_us,
        entity_id=entity_id,
        incomplete=incomplete,
        incomplete_reason=reason,
        hint=HINT,
        untimed_excluded=_untimed_count(store, entity_id) if not empty else 0,
    )
    if empty:
        result.incomplete = True
        result.incomplete_reason = result.incomplete_reason or "no_index"
        return result
    limit = max(1, settings.page_size)
    where = ["g.published=1", "g.status=?", "e.timestamp_utc_us IS NOT NULL"]
    args = [INDEX_COMPLETE]
    if start_utc_us is not None:
        where.append("e.timestamp_utc_us >= ?")
        args.append(start_utc_us)
    if end_utc_us is not None:
        where.append("e.timestamp_utc_us < ?")
        args.append(end_utc_us)
    join_entity = ""
    if entity_id is not None:
        join_entity = "JOIN event_entities ee ON ee.event_id = e.event_id AND ee.generation_id = e.generation_id"
        where.append("ee.entity_id=?")
        args.append(entity_id)
    args.append(limit)
    sql = """
        SELECT e.start_line, e.end_line, e.preview, e.truncated, e.level,
               e.timestamp_raw, e.timestamp_utc_us, f.relative_path, f.absolute_path,
               f.compression, f.bundle_id, f.discovery_status, f.size,
               g.generation, g.parser_id
        FROM events e
        JOIN file_generations g ON g.generation_id = e.generation_id
        JOIN files f ON f.file_id = g.file_id
        %s
        WHERE %s
        GROUP BY e.event_id
        ORDER BY e.timestamp_utc_us, f.relative_path, e.start_line
        LIMIT ?
    """ % (join_entity, " AND ".join(where))
    rows = store.conn.execute(sql, tuple(args)).fetchall()
    for row in rows:
        result.hits.append(_hit_from_row(row, session_id))
    if len(result.hits) >= limit:
        result.incomplete = True
        result.incomplete_reason = result.incomplete_reason or "hit_limit"
    return result


def events_around(
    store: IndexStore,
    session_id: str,
    center_utc_us: int,
    radius_minutes: int,
    settings: Optional[SessionSettings] = None,
    entity_id: Optional[int] = None,
) -> TimelineResult:
    radius_minutes = max(1, int(radius_minutes))
    delta = radius_minutes * 60 * 1000000
    start = center_utc_us - delta
    end = center_utc_us + delta
    result = events_in_window(
        store,
        session_id,
        start,
        end,
        settings=settings,
        entity_id=entity_id,
    )
    result.radius_minutes = radius_minutes
    return result


def timestamp_at_location(
    store: IndexStore,
    absolute_path: str,
    line_no: int,
    relative_path: str = "",
) -> Optional[int]:
    row = store.conn.execute(
        """
        SELECT e.timestamp_utc_us
        FROM events e
        JOIN file_generations g ON g.generation_id = e.generation_id
        JOIN files f ON f.file_id = g.file_id
        WHERE g.published=1 AND g.status=?
          AND e.start_line <= ? AND e.end_line >= ?
          AND (f.absolute_path = ? OR f.relative_path = ?)
        ORDER BY e.start_line DESC
        LIMIT 1
        """,
        (INDEX_COMPLETE, line_no, line_no, absolute_path, relative_path),
    ).fetchone()
    if row is None or row["timestamp_utc_us"] is None:
        return None
    return int(row["timestamp_utc_us"])


def session_events_in_window(
    session: Session,
    start_utc_us: Optional[int],
    end_utc_us: Optional[int],
    entity_id: Optional[int] = None,
    cancel: Optional[CancellationToken] = None,
) -> TimelineResult:
    path = session.index_db_path()
    if not os.path.isfile(path):
        return TimelineResult(
            incomplete=True,
            incomplete_reason="no_index",
            hint=HINT,
            entity_id=entity_id,
            start_utc_us=start_utc_us,
            end_utc_us=end_utc_us,
        )
    if cancel is not None and cancel.cancelled:
        return TimelineResult(incomplete=True, incomplete_reason="cancelled", hint=HINT)
    store = IndexStore(path)
    try:
        return events_in_window(
            store,
            session.session_id,
            start_utc_us,
            end_utc_us,
            settings=session.settings,
            entity_id=entity_id,
        )
    finally:
        store.close()


def session_events_around(
    session: Session,
    center_utc_us: int,
    radius_minutes: int,
    entity_id: Optional[int] = None,
    cancel: Optional[CancellationToken] = None,
) -> TimelineResult:
    path = session.index_db_path()
    if not os.path.isfile(path):
        return TimelineResult(
            incomplete=True,
            incomplete_reason="no_index",
            hint=HINT,
            radius_minutes=radius_minutes,
        )
    if cancel is not None and cancel.cancelled:
        return TimelineResult(incomplete=True, incomplete_reason="cancelled", hint=HINT)
    store = IndexStore(path)
    try:
        return events_around(
            store,
            session.session_id,
            center_utc_us,
            radius_minutes,
            settings=session.settings,
            entity_id=entity_id,
        )
    finally:
        store.close()


def session_timestamp_at_location(
    session: Session,
    absolute_path: str,
    line_no: int,
    relative_path: str = "",
) -> Optional[int]:
    path = session.index_db_path()
    if not os.path.isfile(path):
        return None
    store = IndexStore(path)
    try:
        return timestamp_at_location(store, absolute_path, line_no, relative_path)
    finally:
        store.close()
