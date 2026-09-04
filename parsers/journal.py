"""Text journalctl dumps. Year and timezone are not inferred from the host."""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from core.models import (
    COMPONENT_JOURNAL,
    DecodedLine,
    FormatAssessment,
    ParseOutput,
    ParsedRecord,
)
from core.timeparse import looks_like_journal_timestamp, parse_journal_timestamp
from .base import Parser, preview_text


def _skip_meta(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith("-----"):
        return True
    if stripped.startswith("-- "):
        return True
    if stripped.startswith("--"):
        return True
    return False


class JournalParser(Parser):
    parser_id = "journal"
    version = "2"
    component = COMPONENT_JOURNAL

    def assess(
        self,
        sample_lines: Sequence[DecodedLine],
        relative_path: str = "",
        component_hint: str = "",
    ) -> FormatAssessment:
        hits = 0
        seen = 0
        for line in sample_lines:
            if _skip_meta(line.text):
                continue
            seen += 1
            if looks_like_journal_timestamp(line.text):
                hits += 1
        if seen == 0:
            confidence = 0.0
        else:
            confidence = float(hits) / float(seen)
        if component_hint == COMPONENT_JOURNAL:
            confidence = max(confidence, 0.4 if hits else confidence)
        return FormatAssessment(
            parser_id=self.parser_id,
            confidence=confidence,
            component=COMPONENT_JOURNAL,
        )

    def parse(
        self,
        lines: Iterable[DecodedLine],
        journal_year: Optional[int] = None,
        journal_utc_offset: str = "",
    ) -> ParseOutput:
        out = ParseOutput()
        for line in lines:
            if _skip_meta(line.text):
                continue
            if not looks_like_journal_timestamp(line.text):
                continue
            parsed = parse_journal_timestamp(
                line.text,
                year=journal_year,
                utc_offset=journal_utc_offset,
            )
            out.records.append(
                ParsedRecord(
                    start_line=line.line_no,
                    end_line=line.line_no,
                    timestamp_raw=parsed.timestamp_raw,
                    timestamp_utc_us=parsed.timestamp_utc_us,
                    time_basis=parsed.time_basis,
                    time_issue=parsed.time_issue,
                    level="unknown",
                    preview=preview_text(line.text),
                    truncated=line.truncated,
                    component=COMPONENT_JOURNAL,
                )
            )
        return out
