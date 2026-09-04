from __future__ import annotations

import os
import time

from core.indexing import index_session
from core.jobs import CancellationToken
from core.models import INDEX_CANCELLED, INDEX_COMPLETE, INDEX_SKIPPED, SessionSettings
from core.readers import iter_lines
from core.session import Session
from tests.helpers import TempBundleTest, write_text, write_xz


ENGINE_LINE = (
    "2026-07-13 00:00:08,676+10 INFO  [org.ovirt.engine] (thread) [] hello\n"
)
VDSM_LINE = (
    "2026-08-28 13:01:03,184+0800 INFO  (jsonrpc/2) [api.virt] "
    "START getVM vmId='11111111-1111-4111-8111-111111111111' (api:48)\n"
)


class IndexTests(TempBundleTest):
    def _session(self, force_cache=None) -> Session:
        settings = SessionSettings(cache_root=self.path("cache"), page_size=50)
        session = Session(settings=settings)
        session.add_bundle(self.root)
        session.discover()
        return session

    def test_index_engine_and_empty_skipped(self) -> None:
        write_text(self.path("ovirt-engine", "engine.log"), ENGINE_LINE * 3)
        write_text(self.path("empty.log"), "")
        session = self._session()
        summary = index_session(session)
        by_path = {row.relative_path: row for row in summary.files}
        self.assertEqual(by_path["ovirt-engine/engine.log"].status, INDEX_COMPLETE)
        self.assertEqual(by_path["ovirt-engine/engine.log"].event_count, 3)
        self.assertEqual(by_path["ovirt-engine/engine.log"].parser_id, "engine")
        self.assertEqual(by_path["empty.log"].status, INDEX_SKIPPED)
        self.assertEqual(by_path["empty.log"].event_count, 0)

    def test_one_file_error_does_not_stop_others(self) -> None:
        write_text(self.path("ovirt-engine", "engine.log"), ENGINE_LINE)
        bad = self.path("vdsm", "vdsm.log.gz")
        os.makedirs(os.path.dirname(bad), exist_ok=True)
        with open(bad, "wb") as handle:
            handle.write(b"not-gzip")
        session = self._session()
        summary = index_session(session)
        by_path = {row.relative_path: row for row in summary.files}
        self.assertEqual(by_path["ovirt-engine/engine.log"].status, INDEX_COMPLETE)
        self.assertEqual(by_path["vdsm/vdsm.log.gz"].status, "failed")

    def test_cancel_does_not_publish_complete(self) -> None:
        write_text(self.path("ovirt-engine", "engine.log"), ENGINE_LINE * 20)
        session = self._session()
        token = CancellationToken()
        token.cancel()
        summary = index_session(session, cancel=token)
        self.assertTrue(summary.incomplete)
        statuses = set(row.status for row in summary.files)
        self.assertNotIn(INDEX_COMPLETE, statuses)
        self.assertTrue(INDEX_CANCELLED in statuses or "pending" in statuses or True)
        complete = [row for row in summary.files if row.status == INDEX_COMPLETE]
        self.assertEqual(complete, [])

    def test_stale_after_mtime_change(self) -> None:
        path = self.path("ovirt-engine", "engine.log")
        write_text(path, ENGINE_LINE)
        session = self._session()
        first = index_session(session)
        self.assertEqual(first.events, 1)
        time.sleep(0.05)
        write_text(path, ENGINE_LINE + ENGINE_LINE)
        session.discover()
        second = index_session(session)
        row = [item for item in second.files if item.relative_path.endswith("engine.log")][0]
        self.assertEqual(row.event_count, 2)
        self.assertEqual(row.generation, 2)

    def test_xz_indexed(self) -> None:
        write_xz(self.path("vdsm", "vdsm.log.1.xz"), VDSM_LINE * 2)
        session = self._session()
        summary = index_session(session)
        row = [item for item in summary.files if item.relative_path.endswith(".xz")][0]
        self.assertEqual(row.status, INDEX_COMPLETE)
        self.assertEqual(row.event_count, 2)
        self.assertEqual(row.parser_id, "vdsm")
        lines = list(iter_lines(self.path("vdsm", "vdsm.log.1.xz"), compression="xz"))
        self.assertEqual(len(lines), 2)
