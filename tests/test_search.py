from __future__ import annotations

from core.discovery import discover_bundle
from core.jobs import CancellationToken
from core.models import Bundle, INCOMPLETE_HIT_LIMIT, SessionSettings
from core.search import search_files
from tests.helpers import SAMPLE_TEXT, TempBundleTest, write_gzip, write_text, write_xz


class SearchTests(TempBundleTest):
    def _bundle_files(self):
        write_text(self.path("notes.log"), SAMPLE_TEXT)
        write_gzip(self.path("notes.log.gz"), SAMPLE_TEXT)
        write_xz(self.path("notes.log.xz"), SAMPLE_TEXT)
        write_text(self.path("empty.log"), "")
        bundle = Bundle(bundle_id="b1", root_path=self.root, label="t")
        return discover_bundle(bundle)

    def test_literal_dot_star_is_not_regex(self) -> None:
        files = self._bundle_files()
        result = search_files(files, ".*", session_id="s1", settings=self.settings)
        self.assertGreaterEqual(result.hit_count, 3)
        self.assertTrue(all(".*" in hit.text for hit in result.hits))
        missing = search_files(files, "^alpha", session_id="s1", settings=self.settings)
        self.assertEqual(missing.hit_count, 0)

    def test_case_insensitive_option(self) -> None:
        files = self._bundle_files()
        sensitive = search_files(
            files, "ALPHA", session_id="s1", settings=SessionSettings(case_sensitive=True)
        )
        self.assertEqual(sensitive.hit_count, 0)
        insensitive = search_files(
            files, "ALPHA", session_id="s1", settings=SessionSettings(case_sensitive=False)
        )
        self.assertGreater(insensitive.hit_count, 0)

    def test_empty_files_are_skipped_not_success(self) -> None:
        files = self._bundle_files()
        result = search_files(files, "omega", session_id="s1", settings=self.settings)
        self.assertGreater(result.files_skipped, 0)
        self.assertEqual(result.skipped_by_status.get("empty"), 1)
        empty = [item for item in files if item.status == "empty"][0]
        self.assertFalse(empty.searchable)

    def test_hit_limit_pages_without_gaps(self) -> None:
        write_text(self.path("many.log"), "\n".join("hit %s" % i for i in range(50)) + "\n")
        files = discover_bundle(Bundle(bundle_id="b1", root_path=self.root, label="t"))
        result = search_files(
            files,
            "hit",
            session_id="s1",
            settings=SessionSettings(page_size=10),
        )
        self.assertEqual(result.hit_count, 10)
        self.assertTrue(result.incomplete)
        self.assertEqual(result.incomplete_reason, INCOMPLETE_HIT_LIMIT)
        lines = [hit.line_no for hit in result.hits]
        self.assertEqual(lines, list(range(1, 11)))

    def test_cancel_marks_incomplete(self) -> None:
        write_text(self.path("many.log"), "\n".join("hit %s" % i for i in range(5000)) + "\n")
        files = discover_bundle(Bundle(bundle_id="b1", root_path=self.root, label="t"))
        token = CancellationToken()
        token.cancel()
        result = search_files(
            files,
            "hit",
            session_id="s1",
            settings=SessionSettings(page_size=1000),
            cancel=token,
        )
        self.assertTrue(result.incomplete)
        self.assertEqual(result.incomplete_reason, "cancelled")
