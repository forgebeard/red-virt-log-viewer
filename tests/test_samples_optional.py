from __future__ import annotations

import os
import unittest

from core.discovery import iter_path_hints
from core.indexing import index_session
from core.models import SessionSettings
from core.search import search_files
from core.session import Session

TICKETS = "/home/redadmin/Documents/tickets"
SAMPLES = os.path.join(TICKETS, "log-parser-samples-BosLPH")
FILE_LIST = os.path.join(
    TICKETS, "70962", "rvsupport_zdrav.eao", "rvsupport-files.txt"
)


class OptionalSamplesTests(unittest.TestCase):
    def test_path_list_has_known_layout_hints(self) -> None:
        if not os.path.isfile(FILE_LIST):
            self.skipTest("rvsupport-files.txt is not available")
        with open(FILE_LIST, encoding="utf-8", errors="replace") as handle:
            paths = [line.strip() for line in handle if line.strip()]
        self.assertEqual(len(paths), 7018)
        hints = iter_path_hints(paths)
        components = {hint for _rel, hint, _kind in hints}
        kinds = {kind for _rel, _hint, kind in hints}
        self.assertIn("engine", components)
        self.assertIn("vdsm", components)
        self.assertIn("qemu", components)
        self.assertIn("journal", components)
        self.assertIn("gzip", kinds)
        self.assertIn("xz", kinds)

    def test_search_sample_bundle(self) -> None:
        if not os.path.isdir(SAMPLES):
            self.skipTest("log-parser-samples-BosLPH is not available")
        session = Session(settings=SessionSettings(page_size=20))
        session.add_bundle(SAMPLES)
        session.discover()
        statuses = session.status_counts()
        self.assertGreater(statuses.get("text", 0) + statuses.get("xz", 0), 0)
        result = search_files(
            session.files,
            "INFO",
            session_id=session.session_id,
            settings=session.settings,
        )
        self.assertGreater(result.hit_count, 0)
        vdsm_hits = [hit for hit in result.hits if hit.source.relative_path.endswith("vdsm.log")]
        self.assertTrue(vdsm_hits)
        xz_files = [item for item in session.files if item.status == "xz"]
        self.assertTrue(xz_files)
        from core.source import plan_open

        plan = plan_open(xz_files[0], 1, settings=session.settings)
        self.assertEqual(plan.mode, "fragment")
        self.assertTrue(plan.fragment.lines)
        self.assertEqual(plan.fragment.lines[0][0], 1)

    def test_index_parser_samples(self) -> None:
        if not os.path.isdir(SAMPLES):
            self.skipTest("log-parser-samples-BosLPH is not available")
        import tempfile

        cache = tempfile.mkdtemp()
        session = Session(settings=SessionSettings(cache_root=cache, page_size=20))
        session.add_bundle(SAMPLES)
        session.discover()
        summary = index_session(session)
        self.assertGreater(summary.events, 0)
        complete = [row for row in summary.files if row.status == "complete"]
        parsers = {row.parser_id for row in complete}
        self.assertIn("vdsm", parsers)
        self.assertIn("qemu", parsers)
        xz_row = [row for row in complete if row.relative_path.endswith(".xz")]
        self.assertTrue(xz_row)
        self.assertGreater(xz_row[0].event_count, 0)
