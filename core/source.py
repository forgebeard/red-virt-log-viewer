"""Open original lines. Compressed files are shown as a numbered fragment."""

from __future__ import annotations

from typing import Optional

from .jobs import CancellationToken
from .models import (
    COMPRESSION_GZIP,
    COMPRESSION_XZ,
    DiscoveredFile,
    SearchHit,
    SessionSettings,
    SourceFragment,
    SourceOpenPlan,
    SourceRef,
)
from .readers import ReaderError, iter_lines


def _ref_from_hit(hit: SearchHit) -> SourceRef:
    return hit.source


def plan_open(
    item: DiscoveredFile,
    line: int,
    settings: Optional[SessionSettings] = None,
    cancel: Optional[CancellationToken] = None,
) -> SourceOpenPlan:
    settings = settings or SessionSettings()
    compression = item.compression
    compressed = compression in (COMPRESSION_GZIP, COMPRESSION_XZ, "gzip", "xz")
    large = item.size > settings.direct_open_max_bytes
    if compressed or large:
        fragment = load_fragment(
            item.absolute_path,
            compression=compression,
            focus_line=line,
            context_lines=settings.fragment_context_lines,
            encoding=settings.encoding,
            max_line_bytes=settings.max_line_bytes,
            cancel=cancel,
        )
        return SourceOpenPlan(
            mode="fragment",
            absolute_path=item.absolute_path,
            line=line,
            compression=compression,
            fragment=fragment,
        )
    return SourceOpenPlan(
        mode="file",
        absolute_path=item.absolute_path,
        line=line,
        compression=compression,
    )


def plan_open_hit(
    hit: SearchHit,
    item: Optional[DiscoveredFile] = None,
    settings: Optional[SessionSettings] = None,
    cancel: Optional[CancellationToken] = None,
) -> SourceOpenPlan:
    settings = settings or SessionSettings()
    if item is None:
        item = DiscoveredFile(
            bundle_id=hit.source.bundle_id,
            absolute_path=hit.source.absolute_path,
            relative_path=hit.source.relative_path,
            size=hit.size,
            compression=hit.compression,
            status=hit.status,
            component_hint=hit.component_hint,
        )
    return plan_open(item, hit.line_no, settings=settings, cancel=cancel)


def load_fragment(
    path: str,
    compression: str,
    focus_line: int,
    context_lines: int = 40,
    encoding: str = "utf-8",
    max_line_bytes: int = 1024 * 1024,
    cancel: Optional[CancellationToken] = None,
) -> SourceFragment:
    start = max(1, focus_line - context_lines)
    end = focus_line + context_lines
    collected = []
    incomplete = False
    issue = None
    last_line = 0
    try:
        for decoded in iter_lines(
            path,
            compression=compression,
            encoding=encoding,
            max_line_bytes=max_line_bytes,
            cancel=cancel,
        ):
            last_line = decoded.line_no
            if decoded.line_no < start:
                continue
            if decoded.line_no > end:
                break
            collected.append((decoded.line_no, decoded.text, decoded.truncated))
        if cancel is not None and cancel.cancelled:
            incomplete = True
            issue = "cancelled"
    except ReaderError as exc:
        incomplete = True
        issue = exc.message
    if collected:
        start_line = collected[0][0]
        end_line = collected[-1][0]
    else:
        start_line = start
        end_line = last_line
    return SourceFragment(
        absolute_path=path,
        compression=compression,
        start_line=start_line,
        end_line=end_line,
        focus_line=focus_line,
        lines=collected,
        incomplete=incomplete,
        issue=issue,
    )


def format_fragment(fragment: SourceFragment) -> str:
    header = [
        "RED Virt source fragment (read-only)",
        "File: %s" % fragment.absolute_path,
        "Compression: %s" % fragment.compression,
        "Original lines: %s-%s  focus: %s"
        % (fragment.start_line, fragment.end_line, fragment.focus_line),
        "Random access is not available for gzip/xz; this fragment was read from the start of the stream.",
    ]
    if fragment.incomplete:
        header.append("Incomplete: %s" % (fragment.issue or "yes"))
    header.append("")
    body = []
    for line_no, text, truncated in fragment.lines:
        mark = ">" if line_no == fragment.focus_line else " "
        cut = " [truncated]" if truncated else ""
        body.append("%s%6d|%s%s" % (mark, line_no, text, cut))
    return "\n".join(header + body) + "\n"
