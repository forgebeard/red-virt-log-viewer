"""VM entities from published identifiers. Names are not unique keys."""

from __future__ import annotations

import os
import re
from typing import List, Optional

from .index import IndexStore
from .jobs import CancellationToken
from .models import (
    COMPRESSION_NONE,
    ENTITY_RESOLVED,
    ENTITY_UNRESOLVED_NAME,
    ENTITY_UUID_ONLY,
    ENTITY_VM,
    EntityCandidate,
    EntityEventsResult,
    FindObjectResult,
    IDENT_VM_NAME,
    IDENT_VM_UUID,
    INDEX_COMPLETE,
    NameObservation,
    SearchHit,
    SessionSettings,
    SourceRef,
)
from .session import Session

UUID_SHAPE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

def _canon_uuid(value: str) -> str:
    return value.strip().lower()


def resolve_from_index(store: IndexStore) -> None:
    """Rebuild entities from published identifier rows. Does not merge by name."""
    conn = store.conn
    conn.execute("DELETE FROM event_entities")
    conn.execute("DELETE FROM entity_names")
    conn.execute("DELETE FROM entities")
    rows = conn.execute(
        """
        SELECT i.event_id, i.generation_id, i.ident_type, i.value, i.basis,
               i.start_line, i.end_line, ev.timestamp_utc_us
        FROM identifiers i
        JOIN file_generations g ON g.generation_id = i.generation_id
        JOIN events ev ON ev.event_id = i.event_id
        WHERE g.published=1 AND g.status=?
        ORDER BY i.event_id, i.id
        """,
        (INDEX_COMPLETE,),
    ).fetchall()
    by_event = {}
    for row in rows:
        by_event.setdefault(int(row["event_id"]), []).append(row)

    for event_id, idents in by_event.items():
        names = [
            item
            for item in idents
            if item["ident_type"] == IDENT_VM_NAME
            and item["basis"] == "qemu_launch_name_guest"
        ]
        qemu_uuids = [
            item
            for item in idents
            if item["ident_type"] == IDENT_VM_UUID
            and item["basis"] == "qemu_launch_uuid"
        ]
        vdsm_uuids = [
            item
            for item in idents
            if item["ident_type"] == IDENT_VM_UUID
            and item["basis"] == "vdsm_vmId_field"
        ]
        for uuid_row in qemu_uuids:
            entity_id = _upsert_entity(store, uuid_row["value"], ENTITY_UUID_ONLY)
            _link_event(store, entity_id, uuid_row, "qemu_launch_uuid")
            paired = names
            if paired:
                _set_status(store, entity_id, ENTITY_RESOLVED)
                for name_row in paired:
                    _add_name(store, entity_id, name_row)
        for uuid_row in vdsm_uuids:
            entity_id = _upsert_entity(store, uuid_row["value"], ENTITY_UUID_ONLY)
            _link_event(store, entity_id, uuid_row, "vdsm_vmId_field")
    store.commit()


def _upsert_entity(store: IndexStore, uuid_value: str, status: str) -> int:
    uuid_value = _canon_uuid(uuid_value)
    row = store.conn.execute(
        "SELECT entity_id, status FROM entities WHERE entity_type=? AND uuid=?",
        (ENTITY_VM, uuid_value),
    ).fetchone()
    if row is None:
        cur = store.conn.execute(
            "INSERT INTO entities(entity_type, uuid, status) VALUES (?, ?, ?)",
            (ENTITY_VM, uuid_value, status),
        )
        return int(cur.lastrowid)
    if row["status"] != ENTITY_RESOLVED and status == ENTITY_RESOLVED:
        store.conn.execute(
            "UPDATE entities SET status=? WHERE entity_id=?",
            (ENTITY_RESOLVED, row["entity_id"]),
        )
    return int(row["entity_id"])


def _set_status(store: IndexStore, entity_id: int, status: str) -> None:
    store.conn.execute(
        "UPDATE entities SET status=? WHERE entity_id=?",
        (status, entity_id),
    )


def _add_name(store: IndexStore, entity_id: int, name_row) -> None:
    store.conn.execute(
        """
        INSERT INTO entity_names(
            entity_id, name, observed_utc_us, event_id, generation_id,
            basis, start_line, end_line
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_id,
            name_row["value"],
            name_row["timestamp_utc_us"],
            name_row["event_id"],
            name_row["generation_id"],
            name_row["basis"],
            name_row["start_line"],
            name_row["end_line"],
        ),
    )


def _link_event(store: IndexStore, entity_id: int, ident_row, basis: str) -> None:
    store.conn.execute(
        """
        INSERT OR IGNORE INTO event_entities(
            entity_id, event_id, generation_id, basis
        ) VALUES (?, ?, ?, ?)
        """,
        (entity_id, ident_row["event_id"], ident_row["generation_id"], basis),
    )


def _index_flags(store: IndexStore) -> tuple:
    summary = store.summary()
    empty = summary.events == 0 and summary.files_total == 0
    incomplete = summary.incomplete
    reason = summary.incomplete_reason
    meta = store.conn.execute(
        "SELECT value FROM session_meta WHERE key=?",
        ("index_incomplete",),
    ).fetchone()
    if meta is not None and meta["value"] == "1":
        incomplete = True
        extra = store.conn.execute(
            "SELECT value FROM session_meta WHERE key=?",
            ("index_incomplete_reason",),
        ).fetchone()
        if extra is not None and extra["value"]:
            reason = reason or extra["value"]
    if incomplete and not reason:
        reason = "incomplete_index"
    return incomplete, reason, empty


def find_candidates(
    store: IndexStore,
    query: str,
    settings: Optional[SessionSettings] = None,
) -> FindObjectResult:
    settings = settings or SessionSettings()
    incomplete, reason, empty = _index_flags(store)
    result = FindObjectResult(
        query=query,
        incomplete=incomplete,
        incomplete_reason=reason,
        index_empty=empty,
    )
    if not query.strip():
        return result
    if empty:
        return result

    needle = query.strip()
    uuid_query = _canon_uuid(needle) if UUID_SHAPE.match(needle) else None

    entity_ids = set()
    if uuid_query:
        for row in store.conn.execute(
            "SELECT entity_id FROM entities WHERE entity_type=? AND uuid=?",
            (ENTITY_VM, uuid_query),
        ):
            entity_ids.add(int(row["entity_id"]))
    name_rows = store.conn.execute(
        "SELECT DISTINCT entity_id, name FROM entity_names"
    ).fetchall()
    for row in name_rows:
        if settings.case_sensitive and needle not in row["name"]:
            continue
        if not settings.case_sensitive and needle.casefold() not in row["name"].casefold():
            continue
        entity_ids.add(int(row["entity_id"]))

    for entity_id in sorted(entity_ids):
        cand = _load_candidate(store, entity_id)
        if cand is not None:
            result.candidates.append(cand)

    result.unresolved_names = _unresolved_names(store, needle, settings.case_sensitive)
    return result


def _load_candidate(store: IndexStore, entity_id: int) -> Optional[EntityCandidate]:
    row = store.conn.execute(
        "SELECT * FROM entities WHERE entity_id=?",
        (entity_id,),
    ).fetchone()
    if row is None:
        return None
    names = []
    for n in store.conn.execute(
        """
        SELECT name, observed_utc_us, basis, start_line, end_line
        FROM entity_names WHERE entity_id=? ORDER BY observed_utc_us
        """,
        (entity_id,),
    ):
        names.append(
            NameObservation(
                name=n["name"],
                observed_utc_us=n["observed_utc_us"],
                basis=n["basis"],
                start_line=int(n["start_line"] or 0),
                end_line=int(n["end_line"] or 0),
            )
        )
    count_row = store.conn.execute(
        """
        SELECT COUNT(DISTINCT ee.event_id) AS n
        FROM event_entities ee
        JOIN file_generations g ON g.generation_id = ee.generation_id
        WHERE ee.entity_id=? AND g.published=1 AND g.status=?
        """,
        (entity_id, INDEX_COMPLETE),
    ).fetchone()
    evidence = "uuid"
    if names:
        evidence = "qemu_launch_name_and_uuid"
    return EntityCandidate(
        entity_id=entity_id,
        entity_type=row["entity_type"],
        uuid=row["uuid"],
        status=row["status"],
        names=names,
        event_count=int(count_row["n"] or 0),
        evidence=evidence,
    )


def _unresolved_names(
    store: IndexStore, needle: str, case_sensitive: bool
) -> List[EntityCandidate]:
    rows = store.conn.execute(
        """
        SELECT i.value AS name, i.event_id, i.start_line, i.end_line,
               i.basis, ev.timestamp_utc_us
        FROM identifiers i
        JOIN file_generations g ON g.generation_id = i.generation_id
        JOIN events ev ON ev.event_id = i.event_id
        WHERE g.published=1 AND g.status=? AND i.ident_type=?
          AND i.basis='qemu_launch_name_guest'
          AND NOT EXISTS (
            SELECT 1 FROM identifiers u
            WHERE u.event_id = i.event_id
              AND u.ident_type=?
              AND u.basis='qemu_launch_uuid'
          )
        """,
        (INDEX_COMPLETE, IDENT_VM_NAME, IDENT_VM_UUID),
    ).fetchall()
    found = []
    seen = set()
    for row in rows:
        name = row["name"]
        if case_sensitive:
            if needle not in name:
                continue
        elif needle.casefold() not in name.casefold():
            continue
        key = (name, int(row["event_id"]))
        if key in seen:
            continue
        seen.add(key)
        found.append(
            EntityCandidate(
                entity_id=None,
                entity_type=ENTITY_VM,
                uuid=None,
                status=ENTITY_UNRESOLVED_NAME,
                names=[
                    NameObservation(
                        name=name,
                        observed_utc_us=row["timestamp_utc_us"],
                        basis=row["basis"],
                        start_line=int(row["start_line"] or 0),
                        end_line=int(row["end_line"] or 0),
                    )
                ],
                event_count=0,
                evidence="name_without_uuid",
            )
        )
    return found


def events_for_entity(
    store: IndexStore,
    entity_id: int,
    session_id: str,
    settings: Optional[SessionSettings] = None,
) -> EntityEventsResult:
    settings = settings or SessionSettings()
    incomplete, reason, _empty = _index_flags(store)
    cand = _load_candidate(store, entity_id)
    result = EntityEventsResult(
        entity=cand,
        incomplete=incomplete,
        incomplete_reason=reason,
        hint=(
            "Only events with an explicit vm UUID are listed. "
            "Name-only matches need Search Text. This is not a diagnosis."
        ),
    )
    if cand is None:
        return result
    limit = max(1, settings.page_size)
    rows = store.conn.execute(
        """
        SELECT e.start_line, e.end_line, e.preview, e.truncated, e.level,
               e.timestamp_raw, e.timestamp_utc_us, f.relative_path, f.absolute_path, f.compression,
               f.bundle_id, f.discovery_status, f.size, g.generation, g.parser_id
        FROM event_entities ee
        JOIN events e ON e.event_id = ee.event_id
        JOIN file_generations g ON g.generation_id = ee.generation_id
        JOIN files f ON f.file_id = g.file_id
        WHERE ee.entity_id=? AND g.published=1 AND g.status=?
        GROUP BY e.event_id
        ORDER BY e.timestamp_utc_us IS NULL, e.timestamp_utc_us, f.relative_path, e.start_line
        LIMIT ?
        """,
        (entity_id, INDEX_COMPLETE, limit),
    ).fetchall()
    for row in rows:
        result.hits.append(
            SearchHit(
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
        )
    if len(result.hits) >= limit:
        result.incomplete = True
        result.incomplete_reason = result.incomplete_reason or "hit_limit"
    return result


def find_object(
    session: Session,
    query: str,
    cancel: Optional[CancellationToken] = None,
) -> FindObjectResult:
    path = session.index_db_path()
    if not os.path.isfile(path):
        return FindObjectResult(query=query, index_empty=True, incomplete=True,
                                incomplete_reason="no_index")
    if cancel is not None and cancel.cancelled:
        return FindObjectResult(query=query, incomplete=True, incomplete_reason="cancelled")
    store = IndexStore(path)
    try:
        return find_candidates(store, query, settings=session.settings)
    finally:
        store.close()


def entity_events(
    session: Session,
    entity_id: int,
    cancel: Optional[CancellationToken] = None,
) -> EntityEventsResult:
    path = session.index_db_path()
    if not os.path.isfile(path):
        return EntityEventsResult(incomplete=True, incomplete_reason="no_index")
    if cancel is not None and cancel.cancelled:
        return EntityEventsResult(incomplete=True, incomplete_reason="cancelled")
    store = IndexStore(path)
    try:
        return events_for_entity(
            store, entity_id, session.session_id, settings=session.settings
        )
    finally:
        store.close()
