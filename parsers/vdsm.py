"""VDSM log parser.

Adapted from ovirt-log-analyzer format_templates.txt (@vdsm), commit
ad6179a6622e49bc4f1682c16486555c04f29edb, Apache-2.0. Trailing (file:line)
is optional. vmId is stored as an identifier, not a VM entity.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

from core.models import (
    COMPONENT_VDSM,
    DecodedLine,
    FormatAssessment,
    FoundIdentifier,
    IDENT_VM_UUID,
    ParseOutput,
    ParsedRecord,
)
from core.timeparse import parse_explicit_timestamp
from .base import Parser, preview_text, unmatched_issue

# Derived from upstream @vdsm; source location at the end is optional.
VDSM_LINE = re.compile(
    r"^(?P<date_time>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2}|[+-]\d{4}|[+-]\d{2}))"
    r"\s+(?P<level>[A-Z]+)\s+"
    r"\((?P<thread>[^)]*)\)\s+"
    r"\[(?P<logger>[^\]]*)\]\s+"
    r"(?P<msg>.*)$"
)

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
VMID_RE = re.compile(
    r"""(?:['\"]vmId['\"]\s*:\s*['\"]|vmId\s*=\s*['\"]?)(%s)""" % UUID_RE.pattern
)


def identifiers_from_vdsm(text: str, start_line: int, end_line: int) -> List[FoundIdentifier]:
    found = []
    seen = set()
    for match in VMID_RE.finditer(text):
        value = match.group(1)
        if value in seen:
            continue
        seen.add(value)
        found.append(
            FoundIdentifier(
                ident_type=IDENT_VM_UUID,
                value=value,
                basis="vdsm_vmId_field",
                start_line=start_line,
                end_line=end_line,
            )
        )
    return found


class VdsmParser(Parser):
    parser_id = "vdsm"
    version = "1"
    component = COMPONENT_VDSM

    def assess(
        self,
        sample_lines: Sequence[DecodedLine],
        relative_path: str = "",
        component_hint: str = "",
    ) -> FormatAssessment:
        hits = 0
        seen = 0
        for line in sample_lines:
            if not line.text.strip():
                continue
            seen += 1
            if VDSM_LINE.match(line.text):
                hits += 1
        if seen == 0:
            confidence = 0.0
        else:
            confidence = float(hits) / float(seen)
        if component_hint == COMPONENT_VDSM:
            confidence = max(confidence, 0.4 if hits else confidence)
        return FormatAssessment(
            parser_id=self.parser_id,
            confidence=confidence,
            component=COMPONENT_VDSM,
        )

    def parse(self, lines: Iterable[DecodedLine]) -> ParseOutput:
        out = ParseOutput()
        current: Optional[ParsedRecord] = None
        extras: List[DecodedLine] = []

        def flush():
            nonlocal current, extras
            if current is None:
                return
            if extras:
                parts = [current.preview] + [line.text for line in extras]
                current.preview = preview_text("\n".join(parts))
                current.end_line = extras[-1].line_no
                current.truncated = current.truncated or any(
                    line.truncated for line in extras
                )
            current.identifiers = identifiers_from_vdsm(
                current.preview, current.start_line, current.end_line
            )
            out.records.append(current)
            current = None
            extras = []

        for line in lines:
            match = VDSM_LINE.match(line.text)
            if match:
                flush()
                parsed = parse_explicit_timestamp(match.group("date_time"))
                current = ParsedRecord(
                    start_line=line.line_no,
                    end_line=line.line_no,
                    timestamp_raw=parsed.timestamp_raw,
                    timestamp_utc_us=parsed.timestamp_utc_us,
                    time_basis=parsed.time_basis,
                    time_issue=parsed.time_issue,
                    level=match.group("level"),
                    preview=preview_text(line.text),
                    truncated=line.truncated,
                    component=COMPONENT_VDSM,
                    fields={
                        "logger": match.group("logger"),
                        "thread": match.group("thread"),
                    },
                )
                extras = []
                continue
            if current is not None:
                extras.append(line)
            else:
                if line.text.strip():
                    out.issues.append(unmatched_issue(line, self.parser_id))
        if current is not None:
            flush()
        return out
