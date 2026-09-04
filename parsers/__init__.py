"""Parser registry. Path is a hint; content assessment chooses the parser."""

from __future__ import annotations

from typing import List, Sequence

from core.models import COMPONENT_UNKNOWN, DecodedLine, FormatAssessment
from .base import Parser
from .engine import EngineParser
from .generic import GenericParser
from .journal import JournalParser
from .qemu import QemuParser
from .vdsm import VdsmParser

SPECIALIZED = [
    EngineParser(),
    VdsmParser(),
    QemuParser(),
    JournalParser(),
]
GENERIC = GenericParser()
MIN_CONFIDENCE = 0.5


def all_parsers() -> List[Parser]:
    return list(SPECIALIZED) + [GENERIC]


def choose_parser(
    sample_lines: Sequence[DecodedLine],
    relative_path: str = "",
    component_hint: str = COMPONENT_UNKNOWN,
) -> FormatAssessment:
    best = GENERIC.assess(sample_lines, relative_path, component_hint)
    best.parser_id = GENERIC.parser_id
    for parser in SPECIALIZED:
        assessment = parser.assess(sample_lines, relative_path, component_hint)
        if assessment.confidence > best.confidence:
            best = assessment
    if best.confidence < MIN_CONFIDENCE:
        fallback = GENERIC.assess(sample_lines, relative_path, component_hint)
        if best.parser_id != GENERIC.parser_id and best.confidence > 0:
            fallback.issue = "ambiguous_or_weak_match:%s" % best.parser_id
        fallback.parser_id = GENERIC.parser_id
        return fallback
    return best


def parser_by_id(parser_id: str) -> Parser:
    for parser in all_parsers():
        if parser.parser_id == parser_id:
            return parser
    return GENERIC
