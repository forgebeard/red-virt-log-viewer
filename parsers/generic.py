"""Fallback parser: one physical line is one record."""

from __future__ import annotations

from typing import Iterable, Sequence

from core.models import (
    COMPONENT_UNKNOWN,
    DecodedLine,
    FormatAssessment,
    ParseOutput,
    ParsedRecord,
    TIME_BASIS_UNKNOWN,
)
from .base import Parser, preview_text


class GenericParser(Parser):
    parser_id = "generic"
    version = "1"
    component = COMPONENT_UNKNOWN

    def assess(
        self,
        sample_lines: Sequence[DecodedLine],
        relative_path: str = "",
        component_hint: str = COMPONENT_UNKNOWN,
    ) -> FormatAssessment:
        return FormatAssessment(
            parser_id=self.parser_id,
            confidence=0.1,
            component=component_hint or COMPONENT_UNKNOWN,
        )

    def parse(self, lines: Iterable[DecodedLine]) -> ParseOutput:
        out = ParseOutput()
        for line in lines:
            out.records.append(
                ParsedRecord(
                    start_line=line.line_no,
                    end_line=line.line_no,
                    time_basis=TIME_BASIS_UNKNOWN,
                    time_issue="no_timestamp",
                    level="unknown",
                    preview=preview_text(line.text),
                    truncated=line.truncated,
                    component=COMPONENT_UNKNOWN,
                )
            )
        return out
