"""Diagnostic session: bundles, settings and cache location outside support dumps."""

from __future__ import annotations

import hashlib
import os
import uuid
from typing import Dict, Iterable, List, Optional, Sequence

from .discovery import discover_bundle
from .jobs import CancellationToken, JobQueue
from .models import Bundle, DiscoveredFile, JobProgress, SessionSettings


def default_cache_root() -> str:
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return os.path.join(xdg, "red-virt-log-viewer")
    return os.path.join(os.path.expanduser("~"), ".cache", "red-virt-log-viewer")


def normalize_root(path: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def cache_key_for_roots(root_paths: Sequence[str]) -> str:
    real = sorted({normalize_root(path) for path in root_paths})
    blob = "\n".join(real).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def folders_are_tickets_root(folder_paths: Sequence[str], tickets_root: str) -> bool:
    """True when the only open folder is tickets_root itself (not a ticket subfolder)."""
    tickets_root = (tickets_root or "").strip()
    if not tickets_root or not folder_paths:
        return False
    root = normalize_root(tickets_root)
    reals = [normalize_root(path) for path in folder_paths]
    return len(reals) == 1 and reals[0] == root


class Session:
    def __init__(
        self,
        settings: Optional[SessionSettings] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.session_id = session_id or uuid.uuid4().hex
        self.settings = settings or SessionSettings()
        if not self.settings.cache_root:
            self.settings.cache_root = default_cache_root()
        self.bundles: List[Bundle] = []
        self.files: List[DiscoveredFile] = []
        self.jobs = JobQueue(self.session_id)
        self.cache_dir = os.path.join(self.settings.cache_root, "roots", self.session_id)
        self.last_index_summary = None
        self.last_entity_id = None

    def ensure_cache_dir(self) -> str:
        os.makedirs(self.cache_dir, exist_ok=True)
        return self.cache_dir

    def add_bundle(self, root_path: str) -> Bundle:
        root = os.path.abspath(os.path.expanduser(root_path))
        if not os.path.isdir(root):
            raise ValueError("Not a directory: %s" % root)
        bundle_id = os.path.realpath(root)
        for existing in self.bundles:
            if existing.bundle_id == bundle_id:
                return existing
        bundle = Bundle(
            bundle_id=bundle_id,
            root_path=root,
            label=os.path.basename(root) or root,
        )
        self.bundles.append(bundle)
        return bundle

    def clear_bundles(self) -> None:
        self.bundles = []
        self.files = []

    def discover(
        self,
        cancel: Optional[CancellationToken] = None,
        progress=None,
    ) -> List[DiscoveredFile]:
        found: List[DiscoveredFile] = []
        total = len(self.bundles)
        for index, bundle in enumerate(self.bundles):
            if cancel is not None and cancel.cancelled:
                break
            if progress is not None:
                progress(
                    JobProgress(
                        job_id=self.jobs.job_id,
                        message="Discovering %s" % bundle.label,
                        files_done=index,
                        files_total=total,
                        current_path=bundle.root_path,
                    )
                )
            found.extend(
                discover_bundle(
                    bundle,
                    cache_dir=self.cache_dir,
                    sniff_bytes=self.settings.sniff_bytes,
                    cancel=cancel,
                )
            )
        self.files = found
        return found

    def status_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.files:
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts

    def file_by_path(self, bundle_id: str, relative_path: str) -> Optional[DiscoveredFile]:
        for item in self.files:
            if item.bundle_id == bundle_id and item.relative_path == relative_path:
                return item
        return None

    def searchable_files(self) -> List[DiscoveredFile]:
        return [item for item in self.files if item.searchable]

    def index_db_path(self) -> str:
        return os.path.join(self.cache_dir, "index.sqlite")

    def clear_cache(self) -> None:
        import shutil

        self.jobs.cancel()
        if os.path.isdir(self.cache_dir):
            shutil.rmtree(self.cache_dir, ignore_errors=True)
        self.last_index_summary = None
        os.makedirs(self.cache_dir, exist_ok=True)

    def shutdown(self) -> None:
        self.jobs.shutdown()


_SESSIONS: Dict[str, Session] = {}


def create_session(
    settings: Optional[SessionSettings] = None,
    root_paths: Optional[Sequence[str]] = None,
) -> Session:
    settings = settings or SessionSettings()
    if root_paths:
        session_id = cache_key_for_roots(root_paths)
        existing = _SESSIONS.get(session_id)
        if existing is not None:
            return existing
        session = Session(settings=settings, session_id=session_id)
        for path in root_paths:
            session.add_bundle(path)
        _SESSIONS[session.session_id] = session
        return session
    session = Session(settings=settings)
    _SESSIONS[session.session_id] = session
    return session


def get_session(session_id: str) -> Optional[Session]:
    return _SESSIONS.get(session_id)


def discard_session(session_id: str) -> None:
    session = _SESSIONS.pop(session_id, None)
    if session is not None:
        session.shutdown()


def shutdown_all() -> None:
    for session_id in list(_SESSIONS):
        discard_session(session_id)


def iter_sessions() -> Iterable[Session]:
    return list(_SESSIONS.values())
