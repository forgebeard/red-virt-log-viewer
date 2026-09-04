"""Background jobs, cancellation and progress callbacks. No sublime imports."""

from __future__ import annotations

import threading
from typing import Callable, Optional

from .models import JobProgress


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


ProgressCallback = Callable[[JobProgress], None]
JobFunc = Callable[[CancellationToken, ProgressCallback], object]
DoneCallback = Callable[[object], None]


class JobQueue:
    """One active worker per session. Submitting a new job cancels the previous one."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._lock = threading.Lock()
        self._job_id = 0
        self._token: Optional[CancellationToken] = None
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def job_id(self) -> str:
        return "%s-%s" % (self.session_id, self._job_id)

    def submit(
        self,
        func: JobFunc,
        on_done: DoneCallback,
        on_progress: Optional[ProgressCallback] = None,
    ) -> str:
        with self._lock:
            if self._token is not None:
                self._token.cancel()
            self._job_id += 1
            job_id_num = self._job_id
            token = CancellationToken()
            self._token = token
            self._active = True
            job_id = "%s-%s" % (self.session_id, job_id_num)

        def worker() -> None:
            def progress(payload: JobProgress) -> None:
                if job_id_num != self._job_id:
                    return
                if on_progress is not None:
                    on_progress(payload)

            error = None
            result = None
            try:
                result = func(token, progress)
            except Exception as exc:
                error = exc
            with self._lock:
                stale = job_id_num != self._job_id
                if not stale:
                    self._active = False
            if stale:
                return
            if error is not None:
                on_done(error)
            else:
                on_done(result)

        thread = threading.Thread(
            target=worker,
            name="redvirt-job-%s" % job_id,
            daemon=True,
        )
        thread.start()
        return job_id

    def cancel(self) -> None:
        with self._lock:
            if self._token is not None:
                self._token.cancel()

    def shutdown(self) -> None:
        """Request cancel. Do not join: blocking wait is not allowed on the UI thread."""
        self.cancel()
