from __future__ import annotations

import os
import tempfile
import unittest

from core.indexing import index_session
from core.models import SessionSettings
from core.session import (
    cache_key_for_roots,
    create_session,
    discard_session,
    folders_are_tickets_root,
    shutdown_all,
)
from tests.helpers import write_text


ENGINE_LINE = (
    "2026-07-13 00:00:08,676+10 INFO  [org.ovirt.engine] (thread) [] hello\n"
)


class SessionCacheTests(unittest.TestCase):
    def tearDown(self) -> None:
        shutdown_all()

    def test_same_roots_share_session_and_cache_dir(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_text(os.path.join(root, "a.log"), "x\n")
            cache = os.path.join(root, "cache")
            settings = SessionSettings(cache_root=cache)
            first = create_session(settings, root_paths=[root])
            second = create_session(settings, root_paths=[root])
            self.assertIs(first, second)
            self.assertTrue(first.cache_dir.endswith(os.path.join("roots", first.session_id)))
            self.assertEqual(os.path.basename(os.path.dirname(first.cache_dir)), "roots")
            self.assertEqual(first.session_id, cache_key_for_roots([root]))

    def test_different_roots_different_cache(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            a = os.path.join(parent, "a")
            b = os.path.join(parent, "b")
            os.makedirs(a)
            os.makedirs(b)
            write_text(os.path.join(a, "a.log"), "x\n")
            write_text(os.path.join(b, "b.log"), "y\n")
            cache = os.path.join(parent, "cache")
            settings = SessionSettings(cache_root=cache)
            first = create_session(settings, root_paths=[a])
            second = create_session(settings, root_paths=[b])
            self.assertIsNot(first, second)
            self.assertNotEqual(first.cache_dir, second.cache_dir)

    def test_second_index_without_change_keeps_generation(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_text(os.path.join(root, "ovirt-engine", "engine.log"), ENGINE_LINE)
            cache = os.path.join(root, "cache")
            session = create_session(SessionSettings(cache_root=cache), root_paths=[root])
            session.discover()
            first = index_session(session)
            row = [item for item in first.files if item.relative_path.endswith("engine.log")][0]
            self.assertEqual(row.generation, 1)
            session.discover()
            second = index_session(session)
            row = [item for item in second.files if item.relative_path.endswith("engine.log")][0]
            self.assertEqual(row.generation, 1)
            self.assertEqual(second.events, first.events)

    def test_discard_allows_new_instance_same_roots(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_text(os.path.join(root, "a.log"), "x\n")
            cache = os.path.join(root, "cache")
            settings = SessionSettings(cache_root=cache)
            first = create_session(settings, root_paths=[root])
            discard_session(first.session_id)
            second = create_session(settings, root_paths=[root])
            self.assertIsNot(first, second)
            self.assertEqual(first.cache_dir, second.cache_dir)

    def test_tickets_root_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tickets:
            child = os.path.join(tickets, "73682")
            os.makedirs(child)
            self.assertTrue(folders_are_tickets_root([tickets], tickets))
            self.assertFalse(folders_are_tickets_root([child], tickets))
            self.assertFalse(folders_are_tickets_root([tickets], ""))
            self.assertFalse(folders_are_tickets_root([], tickets))
