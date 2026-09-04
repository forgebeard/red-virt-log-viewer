"""Parse explicit log timestamps. Do not guess the computer's timezone or year."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from .models import TIME_BASIS_EXPLICIT, TIME_BASIS_UNKNOWN, TimeParseResult

MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

DT_HEAD = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[ T](?P<hms>\d{2}:\d{2}:\d{2})(?P<frac>[.,]\d+)?"
)
JOURNAL_HEAD = re.compile(
    r"^(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(?P<day>\d{1,2})\s+(?P<hms>\d{2}:\d{2}:\d{2})\b"
)


def _frac_to_us(frac: Optional[str]) -> Tuple[int, str]:
    if not frac:
        return 0, "second"
    digits = frac[1:]
    precision = "millisecond" if len(digits) <= 3 else "microsecond"
    if len(digits) > 6:
        digits = digits[:6]
    else:
        digits = digits.ljust(6, "0")
    return int(digits), precision


def _parse_offset(text: str, pos: int) -> Tuple[Optional[timedelta], int, Optional[str]]:
    if pos >= len(text):
        return None, pos, "missing_timezone"
    ch = text[pos]
    if ch == "Z":
        return timedelta(0), pos + 1, None
    if ch not in "+-":
        return None, pos, "missing_timezone"
    sign = 1 if ch == "+" else -1
    rest = text[pos + 1 :]
    if len(rest) >= 5 and rest[2] == ":":
        if re.match(r"^\d{2}:\d{2}", rest):
            hours = int(rest[0:2])
            minutes = int(rest[3:5])
            if minutes > 59 or hours > 23:
                return None, pos, "malformed_offset"
            delta = timedelta(hours=sign * hours, minutes=sign * minutes)
            return delta, pos + 1 + 5, None
        return None, pos, "malformed_offset"
    if len(rest) >= 4 and rest[:4].isdigit():
        hours = int(rest[0:2])
        minutes = int(rest[2:4])
        if minutes > 59 or hours > 23:
            return None, pos, "malformed_offset"
        delta = timedelta(hours=sign * hours, minutes=sign * minutes)
        return delta, pos + 1 + 4, None
    if len(rest) >= 2 and rest[:2].isdigit():
        if len(rest) > 2 and rest[2] in "0123456789:":
            return None, pos, "malformed_offset"
        hours = int(rest[0:2])
        if hours > 23:
            return None, pos, "malformed_offset"
        delta = timedelta(hours=sign * hours)
        return delta, pos + 1 + 2, None
    return None, pos, "malformed_offset"


def parse_explicit_timestamp(text: str) -> TimeParseResult:
    """Parse a timestamp at the start of *text*. Reject truncated offsets."""
    match = DT_HEAD.match(text)
    if not match:
        return TimeParseResult(time_issue="unrecognized")
    raw_core = match.group(0)
    frac_us, precision = _frac_to_us(match.group("frac"))
    pos = match.end()
    offset, end, issue = _parse_offset(text, pos)
    raw = text[:end] if offset is not None else raw_core
    if issue == "malformed_offset":
        return TimeParseResult(
            timestamp_raw=text[match.start() : match.end() + 8],
            time_basis=TIME_BASIS_UNKNOWN,
            precision=precision,
            time_issue=issue,
        )
    if offset is None:
        return TimeParseResult(
            timestamp_raw=raw_core,
            time_basis=TIME_BASIS_UNKNOWN,
            precision=precision,
            time_issue="missing_timezone",
        )
    try:
        naive = datetime.strptime(
            "%s %s" % (match.group("date"), match.group("hms")),
            "%Y-%m-%d %H:%M:%S",
        )
    except ValueError:
        return TimeParseResult(
            timestamp_raw=raw,
            time_issue="invalid_datetime",
        )
    aware = naive.replace(tzinfo=timezone(offset), microsecond=frac_us)
    utc = aware.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    utc_us = int((utc - epoch).total_seconds()) * 1000000 + utc.microsecond
    return TimeParseResult(
        timestamp_raw=raw,
        timestamp_utc_us=utc_us,
        time_basis=TIME_BASIS_EXPLICIT,
        precision=precision,
        time_issue=None,
    )


def parse_offset_string(offset_text: str) -> Tuple[Optional[timedelta], Optional[str]]:
    text = (offset_text or "").strip()
    if not text:
        return None, "missing_timezone"
    offset, end, issue = _parse_offset(text, 0)
    if issue == "malformed_offset":
        return None, issue
    if offset is None:
        return None, issue or "missing_timezone"
    if end != len(text):
        return None, "malformed_offset"
    return offset, None


def parse_journal_timestamp(
    text: str,
    year: Optional[int] = None,
    utc_offset: str = "",
) -> TimeParseResult:
    match = JOURNAL_HEAD.match(text)
    if not match:
        return TimeParseResult(time_issue="unrecognized")
    raw = match.group(0)
    if year is None or not (utc_offset or "").strip():
        return TimeParseResult(
            timestamp_raw=raw,
            timestamp_utc_us=None,
            time_basis=TIME_BASIS_UNKNOWN,
            precision="second",
            time_issue="missing_year_and_timezone",
        )
    offset, off_issue = parse_offset_string(utc_offset)
    if offset is None:
        return TimeParseResult(
            timestamp_raw=raw,
            timestamp_utc_us=None,
            time_basis=TIME_BASIS_UNKNOWN,
            precision="second",
            time_issue=off_issue or "missing_timezone",
        )
    month = MONTHS[match.group("mon")]
    day = int(match.group("day"))
    hms = match.group("hms")
    hour, minute, second = [int(part) for part in hms.split(":")]
    try:
        naive = datetime(int(year), month, day, hour, minute, second)
    except ValueError:
        return TimeParseResult(
            timestamp_raw=raw,
            time_basis=TIME_BASIS_UNKNOWN,
            precision="second",
            time_issue="invalid_datetime",
        )
    aware = naive.replace(tzinfo=timezone(offset))
    utc = aware.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    utc_us = int((utc - epoch).total_seconds()) * 1000000 + utc.microsecond
    return TimeParseResult(
        timestamp_raw=raw,
        timestamp_utc_us=utc_us,
        time_basis=TIME_BASIS_EXPLICIT,
        precision="second",
        time_issue=None,
    )


def journal_timestamp_issue(text: str) -> TimeParseResult:
    return parse_journal_timestamp(text)


def looks_like_iso_timestamp(text: str) -> bool:
    return bool(DT_HEAD.match(text))


def looks_like_journal_timestamp(text: str) -> bool:
    return bool(JOURNAL_HEAD.match(text))
