"""Parser contract. Parsers do not open files, write SQL, or import sublime."""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from core.models import (
    COMPONENT_UNKNOWN,
    DecodedLine,
    FormatAssessment,
    ParseIssue,
    ParseOutput,
    ParsedRecord,
)

PREVIEW_DEFAULT = 1024


class Parser(object):
    parser_id = "base"
    version = "1"
    component = COMPONENT_UNKNOWN

    def assess(
        self,
        sample_lines: Sequence[DecodedLine],
        relative_path: str = "",
        component_hint: str = COMPONENT_UNKNOWN,
    ) -> FormatAssessment:
        raise NotImplementedError

    def parse(self, lines: Iterable[DecodedLine]) -> ParseOutput:
        raise NotImplementedError


def preview_text(text: str, limit: int = PREVIEW_DEFAULT) -> str:
    text = text.replace("\t", " ")
    if limit > 0 and len(text) > limit:
        return text[:limit]
    return text


def record_from_lines(
    start: DecodedLine,
    extra: Optional[List[DecodedLine]] = None,
    **kwargs
) -> ParsedRecord:
    extra = extra or []
    parts = [start.text] + [line.text for line in extra]
    end_line = extra[-1].line_no if extra else start.line_no
    truncated = start.truncated or any(line.truncated for line in extra)
    rec = ParsedRecord(
        start_line=start.line_no,
        end_line=end_line,
        preview=preview_text("\n".join(parts)),
        truncated=truncated,
        **kwargs
    )
    return rec


def unmatched_issue(line: DecodedLine, parser_id: str) -> ParseIssue:
    return ParseIssue(
        kind="unparsed_line",
        message="%s: line is not a record header and has no open record" % parser_id,
        line_no=line.line_no,
    )
