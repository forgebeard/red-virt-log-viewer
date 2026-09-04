"""Data models for sources, search hits and jobs. Stage 1 has no index generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


STATUS_TEXT = "text"
STATUS_GZIP = "gzip"
STATUS_XZ = "xz"
STATUS_EMPTY = "empty"
STATUS_UNREADABLE = "unreadable"
STATUS_UNSUPPORTED_CONTAINER = "unsupported_container"
STATUS_UNSUPPORTED_BINARY = "unsupported_binary"

SEARCHABLE_STATUSES = (STATUS_TEXT, STATUS_GZIP, STATUS_XZ)

COMPRESSION_NONE = "none"
COMPRESSION_GZIP = "gzip"
COMPRESSION_XZ = "xz"

COMPONENT_ENGINE = "engine"
COMPONENT_VDSM = "vdsm"
COMPONENT_QEMU = "qemu"
COMPONENT_JOURNAL = "journal"
COMPONENT_UNKNOWN = "unknown"

INCOMPLETE_CANCELLED = "cancelled"
INCOMPLETE_HIT_LIMIT = "hit_limit"
INCOMPLETE_READ_LIMIT = "read_limit"

INDEX_PENDING = "pending"
INDEX_INDEXING = "indexing"
INDEX_COMPLETE = "complete"
INDEX_FAILED = "failed"
INDEX_CANCELLED = "cancelled"
INDEX_SKIPPED = "skipped"
INDEX_STALE = "stale"

TIME_BASIS_EXPLICIT = "explicit"
TIME_BASIS_UNKNOWN = "unknown"

IDENT_VM_UUID = "vm_uuid"
IDENT_VM_NAME = "vm_name"
IDENT_UUID_UNKNOWN = "uuid_unknown"


@dataclass
class SessionSettings:
    encoding: str = "utf-8"
    page_size: int = 200
    max_line_bytes: int = 1024 * 1024
    fragment_context_lines: int = 40
    sniff_bytes: int = 8192
    case_sensitive: bool = True
    direct_open_max_bytes: int = 32 * 1024 * 1024
    cache_root: Optional[str] = None
    event_preview_chars: int = 1024
    sniff_lines: int = 40
    index_batch_events: int = 200
    tickets_root: str = ""
    journal_year: Optional[int] = None
    journal_utc_offset: str = ""

    def time_settings_key(self) -> str:
        year = "" if self.journal_year is None else str(int(self.journal_year))
        return "%s|%s" % (year, (self.journal_utc_offset or "").strip())


@dataclass
class Bundle:
    bundle_id: str
    root_path: str
    label: str = ""


@dataclass
class DiscoveredFile:
    bundle_id: str
    absolute_path: str
    relative_path: str
    size: int
    compression: str
    status: str
    component_hint: str
    issue: Optional[str] = None
    mtime_ns: int = 0

    @property
    def searchable(self) -> bool:
        return self.status in SEARCHABLE_STATUSES


@dataclass
class SourceRef:
    session_id: str
    bundle_id: str
    relative_path: str
    start_line: int
    end_line: int
    generation: Optional[int] = None
    absolute_path: str = ""


@dataclass
class SearchHit:
    source: SourceRef
    line_no: int
    text: str
    truncated: bool = False
    compression: str = COMPRESSION_NONE
    status: str = STATUS_TEXT
    component_hint: str = COMPONENT_UNKNOWN
    size: int = 0
    timestamp_raw: str = ""
    level: str = ""
    timestamp_utc_us: Optional[int] = None


@dataclass
class JobProgress:
    job_id: str
    message: str
    files_done: int = 0
    files_total: int = 0
    lines_done: int = 0
    current_path: str = ""
    incomplete: bool = False


@dataclass
class SearchSummary:
    query: str
    case_sensitive: bool
    hits: list = field(default_factory=list)
    files_total: int = 0
    files_scanned: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    hit_count: int = 0
    incomplete: bool = False
    incomplete_reason: Optional[str] = None
    skipped_by_status: dict = field(default_factory=dict)
    failed_files: list = field(default_factory=list)


@dataclass
class SourceFragment:
    absolute_path: str
    compression: str
    start_line: int
    end_line: int
    focus_line: int
    lines: list = field(default_factory=list)
    incomplete: bool = False
    issue: Optional[str] = None


@dataclass
class SourceOpenPlan:
    mode: str
    absolute_path: str
    line: int
    compression: str = COMPRESSION_NONE
    fragment: Optional[SourceFragment] = None


@dataclass
class DecodedLine:
    line_no: int
    text: str
    truncated: bool = False
    had_replacements: bool = False


@dataclass
class FoundIdentifier:
    ident_type: str
    value: str
    basis: str
    start_line: int
    end_line: int


@dataclass
class TimeParseResult:
    timestamp_raw: Optional[str] = None
    timestamp_utc_us: Optional[int] = None
    time_basis: str = TIME_BASIS_UNKNOWN
    precision: str = "unknown"
    time_issue: Optional[str] = None


@dataclass
class FormatAssessment:
    parser_id: str
    confidence: float
    component: str = COMPONENT_UNKNOWN
    issue: Optional[str] = None


@dataclass
class ParsedRecord:
    start_line: int
    end_line: int
    timestamp_raw: Optional[str] = None
    timestamp_utc_us: Optional[int] = None
    time_basis: str = TIME_BASIS_UNKNOWN
    time_issue: Optional[str] = None
    level: str = "unknown"
    preview: str = ""
    identifiers: list = field(default_factory=list)
    truncated: bool = False
    incomplete: bool = False
    component: str = COMPONENT_UNKNOWN
    fields: dict = field(default_factory=dict)


@dataclass
class ParseIssue:
    kind: str
    message: str
    line_no: Optional[int] = None


@dataclass
class ParseOutput:
    records: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    incomplete: bool = False


@dataclass
class FileIndexRow:
    relative_path: str
    parser_id: str
    status: str
    generation: Optional[int] = None
    event_count: int = 0
    issue_count: int = 0
    discovery_status: str = ""


@dataclass
class IndexSummary:
    files_total: int = 0
    events: int = 0
    issues: int = 0
    incomplete: bool = False
    incomplete_reason: Optional[str] = None
    by_status: dict = field(default_factory=dict)
    files: list = field(default_factory=list)


ENTITY_VM = "vm"
ENTITY_RESOLVED = "resolved"
ENTITY_UUID_ONLY = "uuid_only"
ENTITY_UNRESOLVED_NAME = "unresolved_name"


@dataclass
class NameObservation:
    name: str
    observed_utc_us: Optional[int] = None
    basis: str = ""
    start_line: int = 0
    end_line: int = 0


@dataclass
class EntityCandidate:
    entity_id: Optional[int]
    entity_type: str
    uuid: Optional[str]
    status: str
    names: list = field(default_factory=list)
    event_count: int = 0
    evidence: str = ""


@dataclass
class FindObjectResult:
    query: str
    candidates: list = field(default_factory=list)
    unresolved_names: list = field(default_factory=list)
    incomplete: bool = False
    incomplete_reason: Optional[str] = None
    index_empty: bool = False


@dataclass
class EntityEventsResult:
    entity: Optional[EntityCandidate] = None
    hits: list = field(default_factory=list)
    incomplete: bool = False
    incomplete_reason: Optional[str] = None
    hint: str = ""


@dataclass
class TimelineResult:
    hits: list = field(default_factory=list)
    start_utc_us: Optional[int] = None
    end_utc_us: Optional[int] = None
    entity_id: Optional[int] = None
    untimed_excluded: int = 0
    incomplete: bool = False
    incomplete_reason: Optional[str] = None
    hint: str = ""
    radius_minutes: Optional[int] = None
