from __future__ import annotations

import os
import unittest

from core.discovery import classify_file
from core.search import search_files
from core.models import SessionSettings

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "edge_cases"))


class CommittedFixtureTests(unittest.TestCase):
    def test_header_then_content_is_searchable(self) -> None:
        path = os.path.join(ROOT, "header_then_log.txt")
        item = classify_file(path, "edge_cases/header_then_log.txt", "b1")
        self.assertTrue(item.searchable)
        result = search_files(
            [item],
            "keep this searchable line",
            session_id="s1",
            settings=SessionSettings(),
        )
        self.assertEqual(result.hit_count, 1)
        self.assertEqual(result.hits[0].line_no, 2)

    def test_empty_fixture_is_not_searchable(self) -> None:
        path = os.path.join(ROOT, "empty.log")
        item = classify_file(path, "edge_cases/empty.log", "b1")
        self.assertEqual(item.status, "empty")
        self.assertFalse(item.searchable)
        result = search_files([item], "anything", session_id="s1")
        self.assertEqual(result.hit_count, 0)
        self.assertEqual(result.skipped_by_status.get("empty"), 1)
