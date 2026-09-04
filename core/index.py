"""SQLite index for parsed records. Open connections only in the worker thread."""

from __future__ import annotations

import sqlite3
from typing import Iterable, List, Optional

from .models import (
    INDEX_COMPLETE,
    INDEX_STALE,
    FileIndexRow,
    IndexSummary,
    ParsedRecord,
    ParseIssue,
)

SCHEMA_VERSION = "3"

DDL = """
CREATE TABLE IF NOT EXISTS session_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS bundles (
    bundle_id TEXT PRIMARY KEY,
    root_path TEXT NOT NULL,
    label TEXT
);
CREATE TABLE IF NOT EXISTS files (
    file_id INTEGER PRIMARY KEY,
    bundle_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    absolute_path TEXT,
    size INTEGER,
    mtime_ns INTEGER,
    compression TEXT,
    discovery_status TEXT,
    encoding TEXT,
    UNIQUE(bundle_id, relative_path)
);
CREATE TABLE IF NOT EXISTS file_generations (
    generation_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    parser_id TEXT,
    parser_version TEXT,
    encoding TEXT,
    size INTEGER,
    mtime_ns INTEGER,
    status TEXT NOT NULL,
    event_count INTEGER DEFAULT 0,
    issue_count INTEGER DEFAULT 0,
    published INTEGER DEFAULT 0,
    UNIQUE(file_id, generation)
);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY,
    generation_id INTEGER NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    timestamp_raw TEXT,
    timestamp_utc_us INTEGER,
    time_basis TEXT,
    time_issue TEXT,
    level TEXT,
    preview TEXT,
    truncated INTEGER,
    incomplete INTEGER
);
CREATE TABLE IF NOT EXISTS identifiers (
    id INTEGER PRIMARY KEY,
    generation_id INTEGER,
    event_id INTEGER,
    ident_type TEXT,
    value TEXT,
    basis TEXT,
    start_line INTEGER,
    end_line INTEGER
);
CREATE TABLE IF NOT EXISTS index_issues (
    id INTEGER PRIMARY KEY,
    generation_id INTEGER,
    file_id INTEGER,
    kind TEXT,
    message TEXT,
    line_no INTEGER
);
CREATE TABLE IF NOT EXISTS entities (
    entity_id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    uuid TEXT NOT NULL,
    status TEXT NOT NULL,
    UNIQUE(entity_type, uuid)
);
CREATE TABLE IF NOT EXISTS entity_names (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    observed_utc_us INTEGER,
    event_id INTEGER,
    generation_id INTEGER,
    basis TEXT,
    start_line INTEGER,
    end_line INTEGER
);
CREATE TABLE IF NOT EXISTS event_entities (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    generation_id INTEGER NOT NULL,
    basis TEXT,
    UNIQUE(entity_id, event_id, basis)
);
CREATE INDEX IF NOT EXISTS idx_events_gen ON events(generation_id, start_line);
CREATE INDEX IF NOT EXISTS idx_idents_value ON identifiers(ident_type, value);
CREATE INDEX IF NOT EXISTS idx_gen_file ON file_generations(file_id, published);
CREATE INDEX IF NOT EXISTS idx_entity_names_name ON entity_names(name);
CREATE INDEX IF NOT EXISTS idx_event_entities_entity ON event_entities(entity_id);
"""


class IndexStore(object):
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(DDL)
        self.set_meta("schema_version", SCHEMA_VERSION)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO session_meta(key, value) VALUES (?, ?)",
            (key, value),
        )

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM session_meta WHERE key=?",
            (key,),
        ).fetchone()
        if row is None or row["value"] is None:
            return default
        return str(row["value"])

    def upsert_bundle(self, bundle_id: str, root_path: str, label: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO bundles(bundle_id, root_path, label) VALUES (?, ?, ?)",
            (bundle_id, root_path, label),
        )

    def upsert_file(self, item) -> int:
        self.conn.execute(
            """
            INSERT INTO files(
                bundle_id, relative_path, absolute_path, size, mtime_ns,
                compression, discovery_status, encoding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bundle_id, relative_path) DO UPDATE SET
                absolute_path=excluded.absolute_path,
                size=excluded.size,
                mtime_ns=excluded.mtime_ns,
                compression=excluded.compression,
                discovery_status=excluded.discovery_status,
                encoding=excluded.encoding
            """,
            (
                item.bundle_id,
                item.relative_path,
                item.absolute_path,
                item.size,
                item.mtime_ns,
                item.compression,
                item.status,
                getattr(item, "encoding", "utf-8"),
            ),
        )
        row = self.conn.execute(
            "SELECT file_id FROM files WHERE bundle_id=? AND relative_path=?",
            (item.bundle_id, item.relative_path),
        ).fetchone()
        return int(row["file_id"])

    def latest_generation(self, file_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT * FROM file_generations
            WHERE file_id=?
            ORDER BY generation DESC LIMIT 1
            """,
            (file_id,),
        ).fetchone()

    def current_complete(self, file_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT * FROM file_generations
            WHERE file_id=? AND status=? AND published=1
            ORDER BY generation DESC LIMIT 1
            """,
            (file_id, INDEX_COMPLETE),
        ).fetchone()

    def is_current(
        self,
        file_id: int,
        size: int,
        mtime_ns: int,
        parser_id: str,
        parser_version: str,
        encoding: str,
    ) -> bool:
        row = self.current_complete(file_id)
        if row is None:
            return False
        return (
            int(row["size"]) == int(size)
            and int(row["mtime_ns"]) == int(mtime_ns)
            and row["parser_id"] == parser_id
            and row["parser_version"] == parser_version
            and row["encoding"] == encoding
        )

    def mark_stale(self, file_id: int) -> None:
        self.conn.execute(
            "UPDATE file_generations SET status=? WHERE file_id=? AND published=1",
            (INDEX_STALE, file_id),
        )

    def next_generation_number(self, file_id: int) -> int:
        row = self.latest_generation(file_id)
        if row is None:
            return 1
        return int(row["generation"]) + 1

    def begin_generation(
        self,
        file_id: int,
        parser_id: str,
        parser_version: str,
        encoding: str,
        size: int,
        mtime_ns: int,
        status: str,
    ) -> int:
        generation = self.next_generation_number(file_id)
        cur = self.conn.execute(
            """
            INSERT INTO file_generations(
                file_id, generation, parser_id, parser_version, encoding,
                size, mtime_ns, status, published
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                file_id,
                generation,
                parser_id,
                parser_version,
                encoding,
                size,
                mtime_ns,
                status,
            ),
        )
        return int(cur.lastrowid)

    def insert_events(
        self,
        generation_id: int,
        records: Iterable[ParsedRecord],
        preview_limit: int,
    ) -> int:
        count = 0
        for rec in records:
            preview = rec.preview
            if preview_limit > 0 and len(preview) > preview_limit:
                preview = preview[:preview_limit]
            cur = self.conn.execute(
                """
                INSERT INTO events(
                    generation_id, start_line, end_line, timestamp_raw,
                    timestamp_utc_us, time_basis, time_issue, level, preview,
                    truncated, incomplete
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generation_id,
                    rec.start_line,
                    rec.end_line,
                    rec.timestamp_raw,
                    rec.timestamp_utc_us,
                    rec.time_basis,
                    rec.time_issue,
                    rec.level,
                    preview,
                    1 if rec.truncated else 0,
                    1 if rec.incomplete else 0,
                ),
            )
            event_id = int(cur.lastrowid)
            for ident in rec.identifiers:
                self.conn.execute(
                    """
                    INSERT INTO identifiers(
                        generation_id, event_id, ident_type, value, basis,
                        start_line, end_line
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        generation_id,
                        event_id,
                        ident.ident_type,
                        ident.value,
                        ident.basis,
                        ident.start_line,
                        ident.end_line,
                    ),
                )
            count += 1
        return count

    def insert_issues(
        self,
        generation_id: int,
        file_id: int,
        issues: Iterable[ParseIssue],
    ) -> int:
        count = 0
        for issue in issues:
            self.conn.execute(
                """
                INSERT INTO index_issues(generation_id, file_id, kind, message, line_no)
                VALUES (?, ?, ?, ?, ?)
                """,
                (generation_id, file_id, issue.kind, issue.message, issue.line_no),
            )
            count += 1
        return count

    def finish_generation(
        self,
        generation_id: int,
        status: str,
        event_count: int,
        issue_count: int,
        published: bool,
    ) -> None:
        self.conn.execute(
            """
            UPDATE file_generations
            SET status=?, event_count=?, issue_count=?, published=?
            WHERE generation_id=?
            """,
            (status, event_count, issue_count, 1 if published else 0, generation_id),
        )

    def commit(self) -> None:
        self.conn.commit()

    def summary(self) -> IndexSummary:
        rows = self.conn.execute(
            """
            SELECT f.relative_path, f.discovery_status,
                   g.parser_id, g.status, g.generation, g.event_count, g.issue_count
            FROM files f
            LEFT JOIN file_generations g
              ON g.file_id = f.file_id
             AND g.generation_id = (
                    SELECT generation_id FROM file_generations
                    WHERE file_id = f.file_id
                    ORDER BY generation DESC LIMIT 1
             )
            ORDER BY f.relative_path
            """
        ).fetchall()
        summary = IndexSummary()
        summary.files_total = len(rows)
        by_status = {}
        files: List[FileIndexRow] = []
        for row in rows:
            status = row["status"] or "pending"
            by_status[status] = by_status.get(status, 0) + 1
            events = int(row["event_count"] or 0)
            issues = int(row["issue_count"] or 0)
            if status == INDEX_COMPLETE:
                summary.events += events
            summary.issues += issues
            files.append(
                FileIndexRow(
                    relative_path=row["relative_path"],
                    parser_id=row["parser_id"] or "",
                    status=status,
                    generation=row["generation"],
                    event_count=events,
                    issue_count=issues,
                    discovery_status=row["discovery_status"] or "",
                )
            )
        summary.by_status = by_status
        summary.files = files
        if by_status.get("cancelled") or by_status.get("failed") or by_status.get("indexing"):
            summary.incomplete = True
        meta = self.conn.execute(
            "SELECT value FROM session_meta WHERE key=?",
            ("index_incomplete",),
        ).fetchone()
        if meta is not None and meta["value"] == "1":
            summary.incomplete = True
            extra = self.conn.execute(
                "SELECT value FROM session_meta WHERE key=?",
                ("index_incomplete_reason",),
            ).fetchone()
            if extra is not None and extra["value"] and not summary.incomplete_reason:
                summary.incomplete_reason = extra["value"]
        return summary
