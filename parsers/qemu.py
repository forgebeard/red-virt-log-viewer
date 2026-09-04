"""QEMU / libvirt guest log parser. Command lines are data, never executed."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

from core.models import (
    COMPONENT_QEMU,
    DecodedLine,
    FormatAssessment,
    FoundIdentifier,
    IDENT_VM_NAME,
    IDENT_VM_UUID,
    ParseOutput,
    ParsedRecord,
)
from core.timeparse import looks_like_iso_timestamp, parse_explicit_timestamp
from .base import Parser, preview_text, unmatched_issue

LIBVIRT_QEMU_HEAD = re.compile(
    r"^(?P<date_time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:[.,]\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2}|[+-]\d{4}|[+-]\d{2})):\s+(?P<msg>.*)$"
)
QEMU_RUNTIME_HEAD = re.compile(
    r"^(?P<date_time>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z)\s+"
    r"(?P<emitter>\S+):\s*(?P<msg>.*)$"
)
NAME_GUEST = re.compile(r"-name\s+guest=([^\s,]+)")
UUID_ARG = re.compile(
    r"-uuid\s+([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def _is_record_start(text: str) -> bool:
    return bool(LIBVIRT_QEMU_HEAD.match(text) or QEMU_RUNTIME_HEAD.match(text))


def _level_from_msg(msg: str) -> str:
    lowered = msg.lower()
    if "warning" in lowered or lowered.startswith("warn"):
        return "WARNING"
    if "error" in lowered:
        return "unknown"
    return "INFO"


def _idents_from_block(text: str, start: int, end: int) -> List[FoundIdentifier]:
    found = []
    name_match = NAME_GUEST.search(text)
    uuid_match = UUID_ARG.search(text)
    if name_match:
        found.append(
            FoundIdentifier(
                ident_type=IDENT_VM_NAME,
                value=name_match.group(1),
                basis="qemu_launch_name_guest",
                start_line=start,
                end_line=end,
            )
        )
    if uuid_match:
        found.append(
            FoundIdentifier(
                ident_type=IDENT_VM_UUID,
                value=uuid_match.group(1),
                basis="qemu_launch_uuid",
                start_line=start,
                end_line=end,
            )
        )
    return found


class QemuParser(Parser):
    parser_id = "qemu"
    version = "1"
    component = COMPONENT_QEMU

    def assess(
        self,
        sample_lines: Sequence[DecodedLine],
        relative_path: str = "",
        component_hint: str = "",
    ) -> FormatAssessment:
        hits = 0
        for line in sample_lines:
            if _is_record_start(line.text):
                hits += 1
        confidence = 0.9 if hits else 0.0
        if component_hint == COMPONENT_QEMU and hits:
            confidence = max(confidence, 0.8)
        return FormatAssessment(
            parser_id=self.parser_id,
            confidence=confidence,
            component=COMPONENT_QEMU,
        )

    def parse(self, lines: Iterable[DecodedLine]) -> ParseOutput:
        out = ParseOutput()
        current: Optional[ParsedRecord] = None
        body: List[DecodedLine] = []

        def flush():
            nonlocal current, body
            if current is None:
                return
            parts = [current.fields.get("head", current.preview)]
            parts.extend(line.text for line in body)
            full = "\n".join(parts)
            if body:
                current.end_line = body[-1].line_no
                current.truncated = current.truncated or any(
                    line.truncated for line in body
                )
            current.preview = preview_text(full)
            current.identifiers = _idents_from_block(
                full, current.start_line, current.end_line
            )
            out.records.append(current)
            current = None
            body = []

        for line in lines:
            libvirt = LIBVIRT_QEMU_HEAD.match(line.text)
            runtime = QEMU_RUNTIME_HEAD.match(line.text)
            if libvirt or runtime:
                flush()
                date_time = (libvirt or runtime).group("date_time")
                parsed = parse_explicit_timestamp(date_time)
                msg = (libvirt or runtime).group("msg")
                current = ParsedRecord(
                    start_line=line.line_no,
                    end_line=line.line_no,
                    timestamp_raw=parsed.timestamp_raw,
                    timestamp_utc_us=parsed.timestamp_utc_us,
                    time_basis=parsed.time_basis,
                    time_issue=parsed.time_issue,
                    level=_level_from_msg(msg),
                    preview=preview_text(line.text),
                    truncated=line.truncated,
                    component=COMPONENT_QEMU,
                    fields={"head": line.text},
                )
                body = []
                continue
            if current is not None:
                body.append(line)
            else:
                if line.text.strip() and looks_like_iso_timestamp(line.text):
                    out.issues.append(unmatched_issue(line, self.parser_id))
                elif line.text.strip():
                    out.issues.append(unmatched_issue(line, self.parser_id))
        if current is not None:
            flush()
        return out
