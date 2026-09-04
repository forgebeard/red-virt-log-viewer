from __future__ import annotations

import os
import threading
import time
import unittest

from core.jobs import CancellationToken, JobQueue
from core.models import JobProgress
from core.session import Session


class JobTests(unittest.TestCase):
    def test_cancel_token(self) -> None:
        token = CancellationToken()
        self.assertFalse(token.cancelled)
        token.cancel()
        self.assertTrue(token.cancelled)

    def test_submit_replaces_previous_job(self) -> None:
        queue = JobQueue("s1")
        started = threading.Event()
        first_done = []

        def slow(token, progress):
            started.set()
            while not token.cancelled:
                time.sleep(0.01)
            return "first"

        def fast(token, progress):
            progress(JobProgress(job_id="x", message="ok"))
            return "second"

        queue.submit(slow, lambda result: first_done.append(result))
        self.assertTrue(started.wait(1.0))
        second_done = []
        queue.submit(fast, lambda result: second_done.append(result))
        deadline = time.time() + 2.0
        while time.time() < deadline and not second_done:
            time.sleep(0.01)
        self.assertEqual(second_done, ["second"])
        self.assertFalse(first_done)

    def test_session_cache_is_outside_bundle(self) -> None:
        session = Session()
        self.assertIn("red-virt-log-viewer", session.cache_dir)
        self.assertIn(os.path.join("roots", session.session_id), session.cache_dir)


class SessionDiscoverTests(unittest.TestCase):
    def test_add_bundle_deduplicates(self) -> None:
        import tempfile
        from tests.helpers import write_text

        with tempfile.TemporaryDirectory() as root:
            write_text(root + "/a.log", "x\n")
            session = Session()
            first = session.add_bundle(root)
            second = session.add_bundle(root)
            self.assertIs(first, second)
            self.assertEqual(len(session.bundles), 1)
            session.discover()
            self.assertGreaterEqual(len(session.files), 1)
