from __future__ import annotations

from datetime import datetime, timezone

from core.timeparse import (
    journal_timestamp_issue,
    parse_explicit_timestamp,
    parse_journal_timestamp,
)
from tests.helpers import TempBundleTest


class TimeParseTests(TempBundleTest):
    def test_plus_ten_hours(self) -> None:
        result = parse_explicit_timestamp("2026-07-13 00:00:08,676+10 INFO")
        self.assertEqual(result.time_issue, None)
        self.assertEqual(result.time_basis, "explicit")
        utc = datetime.fromtimestamp(result.timestamp_utc_us / 1e6, tz=timezone.utc)
        self.assertEqual(utc.hour, 14)
        self.assertEqual(utc.minute, 0)
        self.assertEqual(utc.second, 8)
        self.assertEqual(utc.microsecond, 676000)

    def test_plus_hhmm(self) -> None:
        result = parse_explicit_timestamp("2026-08-28 13:01:03,184+0800 INFO")
        self.assertIsNone(result.time_issue)
        utc = datetime.fromtimestamp(result.timestamp_utc_us / 1e6, tz=timezone.utc)
        self.assertEqual(utc.hour, 5)

    def test_plus_0330(self) -> None:
        result = parse_explicit_timestamp("2026-01-01 12:00:00,000+03:30 x")
        self.assertIsNone(result.time_issue)
        utc = datetime.fromtimestamp(result.timestamp_utc_us / 1e6, tz=timezone.utc)
        self.assertEqual(utc.hour, 8)
        self.assertEqual(utc.minute, 30)
        self.assertEqual(result.timestamp_raw, "2026-01-01 12:00:00,000+03:30")

    def test_zulu(self) -> None:
        result = parse_explicit_timestamp("2026-05-21T01:35:57.210151Z qemu")
        self.assertIsNone(result.time_issue)
        utc = datetime.fromtimestamp(result.timestamp_utc_us / 1e6, tz=timezone.utc)
        self.assertEqual(utc.hour, 1)
        self.assertEqual(utc.microsecond, 210151)

    def test_truncated_offset_not_plus_three(self) -> None:
        result = parse_explicit_timestamp("2026-01-01 12:00:00+03:3X leftover")
        self.assertEqual(result.time_issue, "malformed_offset")
        self.assertIsNone(result.timestamp_utc_us)

    def test_missing_timezone(self) -> None:
        result = parse_explicit_timestamp("2026-01-01 12:00:00 INFO")
        self.assertEqual(result.time_issue, "missing_timezone")
        self.assertIsNone(result.timestamp_utc_us)

    def test_journal_does_not_use_today(self) -> None:
        result = journal_timestamp_issue("Jul 12 13:26:46 host systemd[1]: start")
        self.assertEqual(result.time_issue, "missing_year_and_timezone")
        self.assertIsNone(result.timestamp_utc_us)
        self.assertIn("Jul 12 13:26:46", result.timestamp_raw or "")

    def test_journal_year_and_offset(self) -> None:
        result = parse_journal_timestamp(
            "Jul 12 13:26:46 host systemd[1]: start",
            year=2026,
            utc_offset="+0000",
        )
        self.assertIsNone(result.time_issue)
        utc = datetime.fromtimestamp(result.timestamp_utc_us / 1e6, tz=timezone.utc)
        self.assertEqual(utc.year, 2026)
        self.assertEqual(utc.month, 7)
        self.assertEqual(utc.day, 12)
        self.assertEqual(utc.hour, 13)
        self.assertEqual(utc.minute, 26)

    def test_journal_year_without_offset_stays_unknown(self) -> None:
        result = parse_journal_timestamp("Jul 12 13:26:46 x", year=2026, utc_offset="")
        self.assertEqual(result.time_issue, "missing_year_and_timezone")
        self.assertIsNone(result.timestamp_utc_us)

    def test_journal_truncated_offset(self) -> None:
        result = parse_journal_timestamp(
            "Jul 12 13:26:46 x",
            year=2026,
            utc_offset="+03:3X",
        )
        self.assertEqual(result.time_issue, "malformed_offset")
        self.assertIsNone(result.timestamp_utc_us)
