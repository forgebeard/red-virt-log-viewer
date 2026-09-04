"""Walk support folders and classify files. Symlinks are not followed."""

from __future__ import annotations

import os
import stat
from typing import Iterable, List, Optional

from .jobs import CancellationToken
from .models import (
    COMPONENT_ENGINE,
    COMPONENT_JOURNAL,
    COMPONENT_QEMU,
    COMPONENT_UNKNOWN,
    COMPONENT_VDSM,
    COMPRESSION_GZIP,
    COMPRESSION_NONE,
    COMPRESSION_XZ,
    STATUS_EMPTY,
    STATUS_GZIP,
    STATUS_TEXT,
    STATUS_UNREADABLE,
    STATUS_UNSUPPORTED_BINARY,
    STATUS_UNSUPPORTED_CONTAINER,
    STATUS_XZ,
    Bundle,
    DiscoveredFile,
)

SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".red-virt-log-viewer",
    ".cache",
}

CONTAINER_SUFFIXES = (
    ".tar.gz",
    ".tar.xz",
    ".tar.bz2",
    ".tar.zst",
    ".tgz",
    ".tbz2",
    ".tar",
    ".zip",
    ".7z",
    ".rar",
)


def posix_relpath(path: str) -> str:
    return path.replace("\\", "/")


def component_hint_from_path(relative_path: str) -> str:
    path = posix_relpath(relative_path).lower()
    name = os.path.basename(path)
    if "journalctl" in path or "/journal/" in path or path.endswith("/journal"):
        return COMPONENT_JOURNAL
    if "/libvirt/qemu/" in path or path.startswith("libvirt/qemu/"):
        return COMPONENT_QEMU
    if "qemu-ga" not in name and "qemu" in name:
        return COMPONENT_QEMU
    if "/vdsm/" in path or name == "vdsm.log" or name.startswith("vdsm.log."):
        return COMPONENT_VDSM
    if "/ovirt-engine/" in path or name == "engine.log" or name.startswith("engine.log."):
        return COMPONENT_ENGINE
    return COMPONENT_UNKNOWN


def name_kind(filename: str) -> str:
    lower = filename.lower()
    for suffix in CONTAINER_SUFFIXES:
        if lower.endswith(suffix):
            return "container"
    if lower.endswith(".gz"):
        return "gzip"
    if lower.endswith(".xz"):
        return "xz"
    return "text"


def _is_probably_binary(sample: bytes) -> bool:
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    return False


def _mtime_ns(info) -> int:
    return int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1000000000)))


def classify_file(
    absolute_path: str,
    relative_path: str,
    bundle_id: str,
    sniff_bytes: int = 8192,
) -> DiscoveredFile:
    hint = component_hint_from_path(relative_path)
    try:
        info = os.lstat(absolute_path)
    except OSError as exc:
        return DiscoveredFile(
            bundle_id=bundle_id,
            absolute_path=absolute_path,
            relative_path=posix_relpath(relative_path),
            size=0,
            compression=COMPRESSION_NONE,
            status=STATUS_UNREADABLE,
            component_hint=hint,
            issue=str(exc),
        )
    mtime_ns = _mtime_ns(info)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return DiscoveredFile(
            bundle_id=bundle_id,
            absolute_path=absolute_path,
            relative_path=posix_relpath(relative_path),
            size=getattr(info, "st_size", 0),
            compression=COMPRESSION_NONE,
            status=STATUS_UNREADABLE,
            component_hint=hint,
            issue="symlink_or_non_file",
            mtime_ns=mtime_ns,
        )
    size = info.st_size
    rel = posix_relpath(relative_path)
    if size == 0:
        return DiscoveredFile(
            bundle_id=bundle_id,
            absolute_path=absolute_path,
            relative_path=rel,
            size=0,
            compression=COMPRESSION_NONE,
            status=STATUS_EMPTY,
            component_hint=hint,
            mtime_ns=mtime_ns,
        )
    kind = name_kind(os.path.basename(rel))
    if kind == "container":
        return DiscoveredFile(
            bundle_id=bundle_id,
            absolute_path=absolute_path,
            relative_path=rel,
            size=size,
            compression=COMPRESSION_NONE,
            status=STATUS_UNSUPPORTED_CONTAINER,
            component_hint=hint,
            mtime_ns=mtime_ns,
        )
    if kind == "gzip":
        return DiscoveredFile(
            bundle_id=bundle_id,
            absolute_path=absolute_path,
            relative_path=rel,
            size=size,
            compression=COMPRESSION_GZIP,
            status=STATUS_GZIP,
            component_hint=hint,
            mtime_ns=mtime_ns,
        )
    if kind == "xz":
        return DiscoveredFile(
            bundle_id=bundle_id,
            absolute_path=absolute_path,
            relative_path=rel,
            size=size,
            compression=COMPRESSION_XZ,
            status=STATUS_XZ,
            component_hint=hint,
            mtime_ns=mtime_ns,
        )
    try:
        with open(absolute_path, "rb") as handle:
            sample = handle.read(sniff_bytes)
    except OSError as exc:
        return DiscoveredFile(
            bundle_id=bundle_id,
            absolute_path=absolute_path,
            relative_path=rel,
            size=size,
            compression=COMPRESSION_NONE,
            status=STATUS_UNREADABLE,
            component_hint=hint,
            issue=str(exc),
            mtime_ns=mtime_ns,
        )
    if _is_probably_binary(sample):
        return DiscoveredFile(
            bundle_id=bundle_id,
            absolute_path=absolute_path,
            relative_path=rel,
            size=size,
            compression=COMPRESSION_NONE,
            status=STATUS_UNSUPPORTED_BINARY,
            component_hint=hint,
            issue="nul_byte_in_sample",
            mtime_ns=mtime_ns,
        )
    return DiscoveredFile(
        bundle_id=bundle_id,
        absolute_path=absolute_path,
        relative_path=rel,
        size=size,
        compression=COMPRESSION_NONE,
        status=STATUS_TEXT,
        component_hint=hint,
        mtime_ns=mtime_ns,
    )


def discover_bundle(
    bundle: Bundle,
    cache_dir: Optional[str] = None,
    sniff_bytes: int = 8192,
    cancel: Optional[CancellationToken] = None,
) -> List[DiscoveredFile]:
    root = bundle.root_path
    found: List[DiscoveredFile] = []
    cache_real = os.path.realpath(cache_dir) if cache_dir else None
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if cancel is not None and cancel.cancelled:
            break
        if cache_real is not None:
            try:
                if os.path.realpath(dirpath) == cache_real or os.path.realpath(dirpath).startswith(
                    cache_real + os.sep
                ):
                    dirnames[:] = []
                    continue
            except OSError:
                pass
        keep = []
        for name in dirnames:
            if name in SKIP_DIR_NAMES:
                continue
            full = os.path.join(dirpath, name)
            try:
                if os.path.islink(full):
                    continue
            except OSError:
                continue
            keep.append(name)
        dirnames[:] = keep
        for filename in filenames:
            if cancel is not None and cancel.cancelled:
                break
            full = os.path.join(dirpath, filename)
            relative = os.path.relpath(full, root)
            found.append(
                classify_file(
                    absolute_path=full,
                    relative_path=relative,
                    bundle_id=bundle.bundle_id,
                    sniff_bytes=sniff_bytes,
                )
            )
    found.sort(key=lambda item: (item.relative_path, item.absolute_path))
    return found


def iter_path_hints(paths: Iterable[str]) -> List[tuple]:
    """Classify path strings without reading files. Used for list-only checks."""
    result = []
    for path in paths:
        rel = posix_relpath(path.lstrip("./"))
        result.append((rel, component_hint_from_path(rel), name_kind(os.path.basename(rel))))
    return result
