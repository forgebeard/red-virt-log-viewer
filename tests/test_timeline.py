from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from core.indexing import index_session
from core.models import SessionSettings
from core.session import Session, create_session, shutdown_all
from core.timeline import events_around, events_in_window, timestamp_at_location
from core.timeparse import parse_explicit_timestamp
from tests.helpers import write_text

FIXTURES = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "fixtures", "correlation")
)
ENGINE_A = "2026-08-28 13:00:00,000+0000 INFO  [org.ovirt.engine] (t) [] first\n"
ENGINE_B = "2026-08-28 13:10:00,000+0000 INFO  [org.ovirt.engine] (t) [] second\n"
JOURNAL = "Oct 10 12:50:50 host systemd[1]: Failed to start x\n"


class TimelineTests(unittest.TestCase):
    def tearDown(self) -> None:
        shutdown_all()

    def _index(self, root: str, settings: SessionSettings) -> Session:
        session = create_session(settings, root_paths=[root])
        session.discover()
        index_session(session)
        return session

    def test_parse_time_bounds(self) -> None:
        from core.timeline import parse_time_bounds

        start, end, err = parse_time_bounds("")
        self.assertIsNone(err)
        self.assertIsNone(start)
        start, end, err = parse_time_bounds(
            "2026-08-28 13:00:00+0000|2026-08-28 13:05:00+0000"
        )
        self.assertIsNone(err)
        self.assertLess(start, end)
        _s, _e, err = parse_time_bounds("nope")
        self.assertIsNotNone(err)

    def test_window_excludes_outside_and_untimed(self) -> None:
        root = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        write_text(os.path.join(root, "ovirt-engine", "engine.log"), ENGINE_A + ENGINE_B)
        write_text(os.path.join(root, "rv_info", "journalctl", "j.txt"), JOURNAL)
        session = self._index(root, SessionSettings(cache_root=os.path.join(root, "cache")))
        from core.index import IndexStore

        store = IndexStore(session.index_db_path())
        try:
            start = parse_explicit_timestamp("2026-08-28 13:00:00+0000").timestamp_utc_us
            end = parse_explicit_timestamp("2026-08-28 13:05:00+0000").timestamp_utc_us
            window = events_in_window(
                store, session.session_id, start, end, settings=session.settings
            )
            self.assertEqual(len(window.hits), 1)
            self.assertIn("first", window.hits[0].text)
            self.assertGreater(window.untimed_excluded, 0)
            around = events_around(
                store,
                session.session_id,
                start,
                1,
                settings=session.settings,
            )
            self.assertEqual(len(around.hits), 1)
            around15 = events_around(
                store,
                session.session_id,
                start,
                15,
                settings=session.settings,
            )
            self.assertEqual(len(around15.hits), 2)
            line = timestamp_at_location(
                store,
                os.path.join(root, "ovirt-engine", "engine.log"),
                1,
                "ovirt-engine/engine.log",
            )
            self.assertEqual(line, start)
        finally:
            store.close()

    def test_entity_timeline_does_not_mix_uuids(self) -> None:
        root = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        shutil.copyfile(
            os.path.join(FIXTURES, "qemu-vm.log"),
            os.path.join(root, "qemu-vm.log"),
        )
        shutil.copyfile(
            os.path.join(FIXTURES, "vdsm.log"),
            os.path.join(root, "vdsm.log"),
        )
        session = self._index(root, SessionSettings(cache_root=os.path.join(root, "cache")))
        from core.entities import find_object
        from core.index import IndexStore

        found = find_object(session, "11111111-1111-4111-8111-111111111111")
        entity_id = found.candidates[0].entity_id
        store = IndexStore(session.index_db_path())
        try:
            result = events_in_window(
                store,
                session.session_id,
                None,
                None,
                settings=session.settings,
                entity_id=entity_id,
            )
            texts = " ".join(hit.text for hit in result.hits)
            self.assertIn("11111111-1111-4111-8111-111111111111", texts)
            self.assertNotIn("22222222-2222-4222-8222-222222222222", texts)
        finally:
            store.close()

    def test_journal_settings_change_reindexes(self) -> None:
        root = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        write_text(os.path.join(root, "rv_info", "journalctl", "j.txt"), JOURNAL)
        cache = os.path.join(root, "cache")
        first = self._index(root, SessionSettings(cache_root=cache))
        from core.index import IndexStore

        store = IndexStore(first.index_db_path())
        try:
            row = store.conn.execute(
                "SELECT timestamp_utc_us FROM events LIMIT 1"
            ).fetchone()
            self.assertIsNone(row["timestamp_utc_us"])
        finally:
            store.close()
        first.settings.journal_year = 2026
        first.settings.journal_utc_offset = "Z"
        first.discover()
        second = index_session(first)
        row = [item for item in second.files if item.relative_path.endswith("j.txt")][0]
        self.assertGreaterEqual(row.generation, 2)
        store = IndexStore(first.index_db_path())
        try:
            row = store.conn.execute(
                "SELECT timestamp_utc_us FROM events WHERE timestamp_utc_us IS NOT NULL LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row)
        finally:
            store.close()
