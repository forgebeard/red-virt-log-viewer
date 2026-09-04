from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from core.entities import entity_events, find_object, resolve_from_index
from core.index import IndexStore
from core.indexing import index_session
from core.jobs import CancellationToken
from core.models import (
    ENTITY_UNRESOLVED_NAME,
    INDEX_COMPLETE,
    SessionSettings,
)
from core.session import Session
from tests.helpers import TempBundleTest

FIXTURES = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "fixtures", "correlation")
)
UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"
DISK_UUID = "33333333-3333-4333-8333-333333333333"


class EntityTests(TempBundleTest):
    def _index_dir(self, *rel_files: str) -> Session:
        for rel in rel_files:
            src = os.path.join(FIXTURES, rel)
            dest = self.path(rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(src, dest)
        session = Session(settings=SessionSettings(cache_root=self.path("cache")))
        session.add_bundle(self.root)
        session.discover()
        summary = index_session(session)
        self.assertGreater(summary.events, 0)
        return session

    def test_qemu_name_and_uuid_finds_vdsm_vmId(self) -> None:
        session = self._index_dir("qemu-vm.log", "vdsm.log")
        found = find_object(session, "vm-demo-01.example.test")
        self.assertFalse(found.index_empty)
        uuids = sorted(c.uuid for c in found.candidates)
        self.assertEqual(uuids, [UUID_A, UUID_B])
        by_uuid = {c.uuid: c for c in found.candidates}
        events_a = entity_events(session, by_uuid[UUID_A].entity_id)
        paths = [hit.source.relative_path for hit in events_a.hits]
        self.assertTrue(any(p.endswith("vdsm.log") for p in paths))
        self.assertTrue(any(UUID_A in hit.text for hit in events_a.hits))
        self.assertFalse(any(UUID_B in hit.text for hit in events_a.hits))
        self.assertFalse(any(DISK_UUID in hit.text and UUID_A not in hit.text for hit in events_a.hits))

    def test_same_name_different_uuid_are_separate(self) -> None:
        session = self._index_dir("qemu-vm.log", "vdsm.log")
        found = find_object(session, "vm-demo-01")
        self.assertEqual(len(found.candidates), 2)
        ids = {c.entity_id for c in found.candidates}
        self.assertEqual(len(ids), 2)
        events = {
            c.uuid: {hit.text for hit in entity_events(session, c.entity_id).hits}
            for c in found.candidates
        }
        self.assertTrue(any(UUID_A in text for text in events[UUID_A]))
        self.assertTrue(any(UUID_B in text for text in events[UUID_B]))
        self.assertFalse(any(UUID_B in text for text in events[UUID_A]))
        self.assertFalse(any(UUID_A in text for text in events[UUID_B]))

    def test_disk_uuid_is_not_a_vm(self) -> None:
        session = self._index_dir("qemu-vm.log", "vdsm.log")
        found = find_object(session, DISK_UUID)
        self.assertEqual(found.candidates, [])
        self.assertEqual(found.unresolved_names, [])

    def test_name_without_uuid_is_not_a_fake_entity(self) -> None:
        session = self._index_dir("qemu-name-only.log")
        found = find_object(session, "orphan-vm")
        self.assertEqual(found.candidates, [])
        self.assertEqual(len(found.unresolved_names), 1)
        unresolved = found.unresolved_names[0]
        self.assertIsNone(unresolved.uuid)
        self.assertIsNone(unresolved.entity_id)
        self.assertEqual(unresolved.status, ENTITY_UNRESOLVED_NAME)
        self.assertEqual(unresolved.evidence, "name_without_uuid")

    def test_find_by_exact_uuid(self) -> None:
        session = self._index_dir("qemu-vm.log", "vdsm.log")
        found = find_object(session, UUID_A.upper())
        self.assertEqual(len(found.candidates), 1)
        self.assertEqual(found.candidates[0].uuid, UUID_A)

    def test_no_index_is_explicit(self) -> None:
        session = Session(settings=SessionSettings(cache_root=self.path("cache")))
        found = find_object(session, "anything")
        self.assertTrue(found.index_empty)
        self.assertTrue(found.incomplete)
        self.assertEqual(found.incomplete_reason, "no_index")
        self.assertEqual(found.candidates, [])

    def test_cancelled_index_flags_find_object(self) -> None:
        dest = self.path("libvirt", "qemu", "qemu-vm.log")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(os.path.join(FIXTURES, "qemu-vm.log"), dest)
        session = Session(settings=SessionSettings(cache_root=self.path("cache")))
        session.add_bundle(self.root)
        session.discover()
        token = CancellationToken()
        token.cancel()
        summary = index_session(session, cancel=token)
        self.assertTrue(summary.incomplete)
        found = find_object(session, "vm-demo-01")
        self.assertTrue(found.incomplete)
        complete = [row for row in summary.files if row.status == INDEX_COMPLETE]
        self.assertEqual(complete, [])

    def test_cancelled_find_object(self) -> None:
        session = self._index_dir("qemu-vm.log")
        token = CancellationToken()
        token.cancel()
        found = find_object(session, "vm-demo-01", cancel=token)
        self.assertTrue(found.incomplete)
        self.assertEqual(found.incomplete_reason, "cancelled")
        self.assertEqual(found.candidates, [])

    def test_resolve_rebuilds_from_published_only(self) -> None:
        session = self._index_dir("qemu-vm.log", "vdsm.log")
        store = IndexStore(session.index_db_path())
        try:
            before = store.conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
            self.assertGreaterEqual(before, 2)
            resolve_from_index(store)
            after = store.conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
            self.assertEqual(before, after)
            disk = store.conn.execute(
                "SELECT 1 FROM entities WHERE uuid=?",
                (DISK_UUID,),
            ).fetchone()
            self.assertIsNone(disk)
        finally:
            store.close()


class OptionalBosLPHEntityTests(unittest.TestCase):
    def test_qemu_uuid_identity_in_vdsm_samples(self) -> None:
        samples = "/home/redadmin/Documents/tickets/log-parser-samples-BosLPH"
        if not os.path.isdir(samples):
            self.skipTest("log-parser-samples-BosLPH is not available")
        cache = tempfile.mkdtemp()
        session = Session(settings=SessionSettings(cache_root=cache, page_size=5000))
        session.add_bundle(samples)
        session.discover()
        index_session(session)
        store = IndexStore(session.index_db_path())
        try:
            row = store.conn.execute(
                """
                SELECT value FROM identifiers
                WHERE ident_type='vm_uuid' AND basis='qemu_launch_uuid'
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                self.skipTest("no qemu launch uuid in samples")
            uuid_value = row["value"]
        finally:
            store.close()
        found = find_object(session, uuid_value)
        self.assertEqual(len(found.candidates), 1)
        events = entity_events(session, found.candidates[0].entity_id)
        vdsm_hits = [
            hit
            for hit in events.hits
            if "vdsm" in hit.source.relative_path and uuid_value.lower() in hit.text.lower()
        ]
        self.assertTrue(
            vdsm_hits,
            "UUID from QEMU should appear as vmId in VDSM (identity, not one incident)",
        )
