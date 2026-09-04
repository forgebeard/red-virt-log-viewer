"""Engine log parser.

Adapted from ovirt-log-analyzer format_templates.txt (@engine), commit
ad6179a6622e49bc4f1682c16486555c04f29edb, Apache-2.0. Named groups were
completed; offset parsing is stricter (+03:30, +10, +0800, Z).
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence

from core.models import (
    COMPONENT_ENGINE,
    DecodedLine,
    FormatAssessment,
    ParseOutput,
    ParsedRecord,
)
from core.timeparse import parse_explicit_timestamp
from .base import Parser, preview_text, unmatched_issue

# Derived from upstream @engine template; groups filled in and timezone
# forms validated by core.timeparse rather than [+\\-0-9Z]*.
ENGINE_LINE = re.compile(
    r"^(?P<date_time>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2}|[+-]\d{4}|[+-]\d{2}))"
    r"\s+(?P<level>[A-Z]+)\s+"
    r"\[(?P<logger>[^\]]*)\]\s+"
    r"\((?P<thread>[^)]*)\)\s+"
    r"\[(?P<correlation>[^\]]*)\]\s+"
    r"(?P<msg>.*)$"
)


class EngineParser(Parser):
    parser_id = "engine"
    version = "1"
    component = COMPONENT_ENGINE

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
            if ENGINE_LINE.match(line.text):
                hits += 1
        if seen == 0:
            confidence = 0.0
        else:
            confidence = float(hits) / float(seen)
        if component_hint == COMPONENT_ENGINE:
            confidence = max(confidence, 0.4 if hits else confidence)
        return FormatAssessment(
            parser_id=self.parser_id,
            confidence=confidence,
            component=COMPONENT_ENGINE,
        )

    def parse(self, lines: Iterable[DecodedLine]) -> ParseOutput:
        out = ParseOutput()
        current: Optional[ParsedRecord] = None
        extras = []

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
            out.records.append(current)
            current = None
            extras = []

        for line in lines:
            match = ENGINE_LINE.match(line.text)
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
                    component=COMPONENT_ENGINE,
                    fields={
                        "logger": match.group("logger"),
                        "thread": match.group("thread"),
                        "correlation": match.group("correlation"),
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
