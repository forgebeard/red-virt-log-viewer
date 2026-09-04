from __future__ import annotations

from core.source import format_fragment, load_fragment, plan_open
from core.discovery import classify_file
from tests.helpers import SAMPLE_TEXT, TempBundleTest, write_gzip, write_text, write_xz


class SourceTests(TempBundleTest):
    def test_plain_file_opens_directly(self) -> None:
        path = self.path("a.log")
        write_text(path, SAMPLE_TEXT)
        item = classify_file(path, "a.log", "b1")
        plan = plan_open(item, 3, settings=self.settings)
        self.assertEqual(plan.mode, "file")
        self.assertEqual(plan.line, 3)
        self.assertEqual(plan.absolute_path, path)

    def test_xz_fragment_keeps_original_line_numbers(self) -> None:
        path = self.path("a.log.xz")
        write_xz(path, SAMPLE_TEXT)
        item = classify_file(path, "a.log.xz", "b1")
        plan = plan_open(item, 3, settings=self.settings)
        self.assertEqual(plan.mode, "fragment")
        self.assertIsNotNone(plan.fragment)
        numbers = [line[0] for line in plan.fragment.lines]
        self.assertIn(3, numbers)
        self.assertEqual(plan.fragment.focus_line, 3)
        text = format_fragment(plan.fragment)
        self.assertIn("     3|", text)
        self.assertIn("literal .* not a regex", text)

    def test_gzip_fragment_matches_plain_line(self) -> None:
        write_text(self.path("a.log"), SAMPLE_TEXT)
        gz = self.path("a.log.gz")
        write_gzip(gz, SAMPLE_TEXT)
        fragment = load_fragment(gz, "gzip", focus_line=2, context_lines=1)
        self.assertEqual(fragment.lines[1][1], "alpha line two")
        self.assertEqual(fragment.lines[1][0], 2)
